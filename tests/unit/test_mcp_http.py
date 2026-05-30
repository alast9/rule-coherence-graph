from __future__ import annotations

from collections.abc import Iterator

import pytest

pytest.importorskip("mcp")

from rcg import mcp_guard, mcp_server, metrics  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Iterator[None]:
    """Reset the process-wide limiter so demo-mode tests stay deterministic."""
    mcp_guard._reset_limiter()
    yield
    mcp_guard._reset_limiter()


@pytest.fixture(autouse=True)
def _reset_metrics() -> Iterator[None]:
    """Reset the metrics registry so counters are isolated between tests."""
    metrics.reset()
    yield
    metrics.reset()


def test_resolve_transport_defaults_to_stdio() -> None:
    transport, host, port = mcp_server._resolve_transport({})
    assert transport == "stdio"
    assert host == "127.0.0.1"
    assert port == 8080


def test_transport_security_none_by_default() -> None:
    assert mcp_server._resolve_transport_security({}) is None


def test_transport_security_allows_configured_host() -> None:
    sec = mcp_server._resolve_transport_security(
        {"RCG_MCP_ALLOWED_HOSTS": "rcg-mcp-demo.fly.dev"}
    )
    assert sec is not None
    assert sec.enable_dns_rebinding_protection is True
    assert "rcg-mcp-demo.fly.dev" in sec.allowed_hosts
    assert "rcg-mcp-demo.fly.dev:*" in sec.allowed_hosts
    assert "https://rcg-mcp-demo.fly.dev" in sec.allowed_origins


def test_transport_security_disable_flag() -> None:
    sec = mcp_server._resolve_transport_security(
        {"RCG_MCP_DISABLE_DNS_REBINDING_PROTECTION": "1"}
    )
    assert sec is not None
    assert sec.enable_dns_rebinding_protection is False


def test_resolve_transport_http_binds_all_interfaces() -> None:
    result = mcp_server._resolve_transport({"RCG_MCP_TRANSPORT": "http", "PORT": "1234"})
    assert result == ("streamable-http", "0.0.0.0", 1234)


def test_resolve_transport_streamable_http_alias() -> None:
    transport, host, _ = mcp_server._resolve_transport(
        {"RCG_MCP_TRANSPORT": "streamable-http"}
    )
    assert transport == "streamable-http"
    assert host == "0.0.0.0"


def test_resolve_transport_sse() -> None:
    transport, host, port = mcp_server._resolve_transport(
        {"RCG_MCP_TRANSPORT": "sse", "PORT": "9000"}
    )
    assert transport == "sse"
    assert host == "0.0.0.0"
    assert port == 9000


def test_resolve_transport_bad_port_falls_back() -> None:
    _, _, port = mcp_server._resolve_transport(
        {"RCG_MCP_TRANSPORT": "http", "PORT": "not-a-number"}
    )
    assert port == 8080


def test_check_rules_markdown_finds_conflict() -> None:
    rules = (
        "# Deploy policy\n"
        "- You MUST deploy to production after tests pass.\n"
        "- You MUST NOT deploy to production without human approval.\n"
    )
    result = mcp_server._check_rules_impl(rules, fmt="markdown")
    assert set(result) == {"n_rules", "score", "by_type", "findings"}
    assert result["n_rules"] > 0
    assert result["findings"], "conflicting MUST vs MUST_NOT should yield a finding"
    finding = result["findings"][0]
    assert set(finding) == {"type", "severity", "reason", "rule_a", "rule_b"}
    assert set(finding["rule_a"]) == {"text", "file", "modality", "action_class"}
    assert finding["rule_a"]["file"] == "CLAUDE.md"


def test_check_rules_cedar_forbid_is_must_not() -> None:
    policy = 'forbid(principal, action == Action::"DeleteObject", resource);\n'
    result = mcp_server._check_rules_impl(policy, fmt="cedar")
    assert result["n_rules"] == 1
    # The cedar `forbid` verb extracts as a MUST_NOT directive.
    modalities = {f["modality"] for f in result["findings"]}
    # No second rule to conflict with, so assert via the tool round-trip instead.
    rule_modality = _single_rule_modality(policy, "cedar")
    assert rule_modality == "MUST_NOT"
    assert "MUST_NOT" in modalities or not result["findings"]


def _single_rule_modality(text: str, fmt: str) -> str:
    """Extract one rule's modality through the same pipeline check_rules uses."""
    import tempfile
    from pathlib import Path

    from rcg.mcp_server import _FORMAT_FILENAMES, _load_rules

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / _FORMAT_FILENAMES[fmt]
        target.write_text(text, encoding="utf-8")
        rules = _load_rules(str(target), "mock")
    assert rules, "cedar forbid policy should extract one rule"
    return rules[0].directive.modality.value


def test_check_rules_tool_callable() -> None:
    rules = "- You MUST always run tests.\n"
    result = mcp_server.check_rules(rules)
    assert result["n_rules"] > 0


def test_tool_call_increments_metric() -> None:
    mcp_server.check_rules("- You MUST always run tests.\n")
    assert 'rcg_tool_calls_total{tool="check_rules"} 1' in metrics.render()


def test_demo_oversized_input_increments_rejection_metric() -> None:
    mcp_server._check_rules_impl(
        "x" * 60_000, fmt="markdown", env={"RCG_PUBLIC_DEMO": "1"}
    )
    assert 'rcg_guard_rejections_total{reason="input_too_large"} 1' in metrics.render()


def test_ingest_to_graph_no_neo4j_uri() -> None:
    result = mcp_server._ingest_to_graph_impl("examples/gemini_incident", env={})
    assert result == {"written": False, "reason": "NEO4J_URI not set"}


def test_ingest_to_graph_no_neo4j_uri_demo_mode() -> None:
    # NEO4J_URI is checked before demo mode, so the shape is identical.
    result = mcp_server._ingest_to_graph_impl(
        "examples/gemini_incident", env={"RCG_PUBLIC_DEMO": "1"}
    )
    assert result == {"written": False, "reason": "NEO4J_URI not set"}


def test_ingest_to_graph_tool_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEO4J_URI", raising=False)
    result = mcp_server.ingest_to_graph("examples/gemini_incident")
    assert result["written"] is False


def test_check_rules_impl_non_demo_allows_large_input() -> None:
    # Without the demo switch, oversized input is processed normally.
    result = mcp_server._check_rules_impl(
        "- You MUST always run tests.\n" * 5000, fmt="markdown"
    )
    assert "error" not in result
    assert result["n_rules"] >= 1


def test_check_rules_impl_demo_input_too_large() -> None:
    result = mcp_server._check_rules_impl(
        "x" * 60_000, fmt="markdown", env={"RCG_PUBLIC_DEMO": "1"}
    )
    assert result["error"] == "input_too_large"
    assert result["limit"] == 50_000


def test_check_rules_impl_demo_too_many_rules() -> None:
    text = (
        "- You MUST deploy to production after tests pass.\n"
        "- You MUST NOT deploy to production without human approval.\n"
    )
    result = mcp_server._check_rules_impl(
        text,
        fmt="markdown",
        env={"RCG_PUBLIC_DEMO": "1", "RCG_MAX_RULES": "1"},
    )
    assert result["error"] == "too_many_rules"
    assert result["limit"] == 1


def test_check_rules_impl_demo_rate_limited() -> None:
    env = {"RCG_PUBLIC_DEMO": "1", "RCG_RATE_LIMIT_PER_MIN": "1"}
    first = mcp_server._check_rules_impl("- You MUST run tests.\n", fmt="markdown", env=env)
    assert "error" not in first
    second = mcp_server._check_rules_impl("- You MUST run tests.\n", fmt="markdown", env=env)
    assert second["error"] == "rate_limited"
    assert second["limit"] == 1
