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


def test_transport_security_multiple_hosts() -> None:
    sec = mcp_server._resolve_transport_security(
        {"RCG_MCP_ALLOWED_HOSTS": "a.example.com,b.example.com"}
    )
    assert sec is not None
    # Each bare host yields the host plus a "host:*" entry.
    for host in ("a.example.com", "b.example.com"):
        assert host in sec.allowed_hosts
        assert f"{host}:*" in sec.allowed_hosts
        assert f"https://{host}" in sec.allowed_origins
        assert f"http://{host}" in sec.allowed_origins


def test_transport_security_host_with_port_preserved() -> None:
    sec = mcp_server._resolve_transport_security(
        {"RCG_MCP_ALLOWED_HOSTS": "demo.example.com:8443"}
    )
    assert sec is not None
    # An explicit host:port entry is kept as-is; no extra ":*" form is added.
    assert sec.allowed_hosts == ["demo.example.com:8443"]
    assert sec.allowed_origins == [
        "https://demo.example.com:8443",
        "http://demo.example.com:8443",
    ]


def test_transport_security_trims_whitespace() -> None:
    sec = mcp_server._resolve_transport_security(
        {"RCG_MCP_ALLOWED_HOSTS": "  a.example.com ,  b.example.com  "}
    )
    assert sec is not None
    assert "a.example.com" in sec.allowed_hosts
    assert "b.example.com" in sec.allowed_hosts
    # No whitespace leaked into any entry.
    assert all(h == h.strip() for h in sec.allowed_hosts)


def test_transport_security_empty_string_is_none() -> None:
    assert mcp_server._resolve_transport_security({"RCG_MCP_ALLOWED_HOSTS": "   "}) is None


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


def test_check_rules_rego_parses() -> None:
    policy = (
        "package deploy\n"
        "default allow = false\n"
        "allow {\n"
        "    input.tests_passed == true\n"
        "}\n"
        "deny {\n"
        "    input.change_freeze == true\n"
        "}\n"
    )
    result = mcp_server._check_rules_impl(policy, fmt="rego")
    assert result["n_rules"] > 0


def test_check_rules_yaml_parses() -> None:
    rules = (
        "rules:\n"
        "  - id: deploy-prod\n"
        "    description: Require approval before any production deploy.\n"
        "    rule: MUST get approval from a human reviewer\n"
        "  - id: deploy-fast\n"
        "    description: Auto-deploy to production when tests pass.\n"
        "    rule: MUST_NOT block automated deploys when CI is green\n"
    )
    result = mcp_server._check_rules_impl(rules, fmt="yaml")
    assert result["n_rules"] > 0


def test_check_corpus_gemini_incident_finds_conflicts() -> None:
    result = mcp_server._check_impl("examples/gemini_incident")
    assert set(result) == {"n_rules", "score", "by_type", "findings"}
    assert result["n_rules"] > 0
    assert isinstance(result["score"], float)
    assert 0.0 <= result["score"] <= 1.0
    assert result["findings"], "gemini_incident corpus should yield findings"
    finding = result["findings"][0]
    assert set(finding) == {"type", "severity", "reason", "rule_a", "rule_b"}


def test_score_corpus_shape() -> None:
    result = mcp_server._score_impl("examples/gemini_incident")
    assert set(result) == {"n_rules", "score", "weighted", "by_type"}
    assert isinstance(result["n_rules"], int)
    assert 0.0 <= result["score"] <= 1.0
    assert isinstance(result["by_type"], dict)


def test_explain_action_shape() -> None:
    result = mcp_server._explain_impl("commit to main", "examples/gemini_incident")
    assert set(result) == {
        "action",
        "action_class",
        "scope",
        "verdict",
        "firing",
        "conflicts",
        "ambiguities",
    }
    assert result["action"] == "commit to main"
    assert isinstance(result["firing"], list)
    assert isinstance(result["conflicts"], list)
    assert isinstance(result["ambiguities"], list)


def test_public_tools_callable_against_gemini_incident() -> None:
    # Exercise the decorated tool functions (not just the _impl helpers).
    assert mcp_server.check_corpus("examples/gemini_incident")["n_rules"] > 0
    assert "score" in mcp_server.score_corpus_tool("examples/gemini_incident")
    explained = mcp_server.explain_action("push to main", "examples/gemini_incident")
    assert explained["action"] == "push to main"


def test_check_rules_tool_callable() -> None:
    rules = "- You MUST always run tests.\n"
    result = mcp_server.check_rules(rules)
    assert result["n_rules"] > 0


def test_tool_call_increments_metric() -> None:
    mcp_server.check_rules("- You MUST always run tests.\n")
    assert 'rcg_tool_calls_total{tool="check_rules"} 1' in metrics.render()


def test_check_rules_bumps_tool_and_extraction_metrics() -> None:
    # A successful check_rules call increments both the per-tool counter and the
    # total rules-extracted counter (registry reset via the autouse fixture).
    mcp_server.check_rules(
        "# Deploy policy\n"
        "- You MUST deploy to production after tests pass.\n"
        "- You MUST NOT deploy to production without human approval.\n"
    )
    text = metrics.render()
    assert 'rcg_tool_calls_total{tool="check_rules"} 1' in text
    # Two rules were extracted, so the total counter must be >= 1 (not zero).
    extracted = next(
        line for line in text.splitlines() if line.startswith("rcg_rules_extracted_total ")
    )
    assert int(extracted.rsplit(" ", 1)[1]) >= 1


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


def test_ingest_to_graph_missing_password() -> None:
    # NEO4J_URI is set but the password is absent: must report the password
    # reason and never attempt a real connection.
    result = mcp_server._ingest_to_graph_impl(
        "examples/gemini_incident",
        env={"NEO4J_URI": "neo4j+s://ac3f157b.databases.neo4j.io"},
    )
    assert result == {"written": False, "reason": "NEO4J_PASSWORD not set"}


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
