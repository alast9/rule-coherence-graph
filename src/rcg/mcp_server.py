"""Expose RCG over the Model Context Protocol so agents can call it.

By default the server speaks stdio, so local clients (Claude Code etc.) launch
``rcg-mcp`` and talk to it over a pipe unchanged. Set ``RCG_MCP_TRANSPORT=http``
(or ``sse``) to instead serve over streamable HTTP — this is how the hosted
demo on Fly.io runs. See ``docs/hosted-mcp.md``.

Tools default to the offline mock provider so the server runs without an API key.
Each tool's logic lives in a thin ``_*_impl`` helper that returns a JSON-serialisable
dict; the decorated tool functions just delegate, keeping the logic unit-testable
without an MCP client.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from rcg import metrics
from rcg.detectors.base import Finding
from rcg.detectors.precedence import PrecedenceDetector
from rcg.detectors.syntactic import SyntacticDetector
from rcg.explain import explain as run_explain
from rcg.extractors.extract import extract_all
from rcg.mcp_guard import (
    DemoConfig,
    _demo_config,
    _demo_guard_check,
    _should_clear,
    _too_many_rules_error,
)
from rcg.parsers.discovery import discover
from rcg.providers.llm import LLMProvider
from rcg.schema import Rule
from rcg.scoring import score_corpus

# Re-exported here so tests and tooling can reach the guardrail helpers via the
# server module; the implementations live in rcg.mcp_guard.
__all__ = [
    "DemoConfig",
    "_demo_config",
    "_demo_guard_check",
    "_should_clear",
]

mcp = FastMCP("rcg")

# Filename each format expects on disk, so a pasted corpus is routed to the right
# parser by ``discover`` (which dispatches purely on file name / suffix).
_FORMAT_FILENAMES: dict[str, str] = {
    "markdown": "CLAUDE.md",
    "cursorrules": ".cursorrules",
    "cedar": "policy.cedar",
    "rego": "policy.rego",
    "opa_rego": "policy.rego",
    "yaml": "rules.yaml",
}


def _build_provider(name: str) -> LLMProvider:
    if name.lower() == "anthropic":
        from rcg.extractors.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    from rcg.extractors.mock_provider import MockProvider

    return MockProvider()


def _load_rules(path: str, provider: str) -> list[Rule]:
    raws = discover(Path(path))
    if not raws:
        return []
    return extract_all(raws, _build_provider(provider), cache=None)


def _rule_dict(rule: Rule) -> dict[str, Any]:
    return {
        "text": rule.raw_text,
        "file": rule.source.file,
        "modality": rule.directive.modality.value,
        "action_class": rule.trigger.action_class,
    }


def _finding_dict(finding: Finding) -> dict[str, Any]:
    return {
        "type": finding.type,
        "severity": finding.severity,
        "reason": finding.reason,
        "rule_a": _rule_dict(finding.rule_a),
        "rule_b": _rule_dict(finding.rule_b),
    }


def _check_impl(
    path: str,
    provider: str = "mock",
    semantic: bool = False,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if env is None else env
    cfg = _demo_config(env)
    if cfg is not None:
        # Reads a server-side path, so size abuse is bounded; only rate-limit.
        error = _demo_guard_check(None, cfg)
        if error is not None:
            metrics.record_rejection(error["error"])
            return error
    rules = _load_rules(path, provider)
    metrics.record_rules_extracted(len(rules))
    findings: list[Finding] = []
    findings.extend(SyntacticDetector().detect(rules))
    if semantic:
        from rcg.detectors.semantic import MockJudge, SemanticDetector
        from rcg.providers.embedding import HashingEmbeddingProvider

        findings.extend(
            SemanticDetector(HashingEmbeddingProvider(), MockJudge()).detect(rules)
        )
    exclude = {frozenset({f.rule_a.id, f.rule_b.id}) for f in findings}
    findings.extend(PrecedenceDetector().detect(rules, exclude=exclude))
    report = score_corpus(len(rules), findings)
    return {
        "n_rules": report.n_rules,
        "score": report.score,
        "by_type": report.by_type,
        "findings": [_finding_dict(f) for f in findings],
    }


def _check_rules_impl(
    rules_text: str,
    fmt: str = "markdown",
    semantic: bool = False,
    provider: str = "mock",
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run the check pipeline over a pasted rules string (no filesystem access).

    The text is written to a temp file named for ``fmt`` so the normal discovery
    path picks the right parser, then the temp directory is removed.
    """
    env = os.environ if env is None else env
    cfg = _demo_config(env)
    if cfg is not None:
        # Rate limit then input size, checked before any expensive extraction.
        error = _demo_guard_check(len(rules_text.encode("utf-8")), cfg)
        if error is not None:
            metrics.record_rejection(error["error"])
            return error
    filename = _FORMAT_FILENAMES.get(fmt.lower(), _FORMAT_FILENAMES["markdown"])
    with tempfile.TemporaryDirectory(prefix="rcg-mcp-") as tmp:
        target = Path(tmp) / filename
        target.write_text(rules_text, encoding="utf-8")
        # Pass an empty env to _check_impl so it does not re-run the guard
        # (this outer call already owns rate-limit/size enforcement).
        result = _check_impl(str(target), provider=provider, semantic=semantic, env={})
    if cfg is not None and result.get("n_rules", 0) > cfg.max_rules:
        error = _too_many_rules_error(int(result["n_rules"]), cfg)
        metrics.record_rejection(error["error"])
        return error
    return result


def _ingest_to_graph_impl(
    path: str, provider: str = "mock", env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Check a corpus and, if Neo4j env is configured, persist it to the graph.

    Never raises on a missing or unreachable database — failures are reported in
    the return value so the server stays up for the next caller.
    """
    env = os.environ if env is None else env
    # Check NEO4J_URI first so the no-database behavior and return shape are
    # identical in demo and non-demo mode (existing tests rely on this exact
    # ``{"written": False, "reason": "NEO4J_URI not set"}`` return).
    uri = env.get("NEO4J_URI")
    if not uri:
        return {"written": False, "reason": "NEO4J_URI not set"}

    user = env.get("NEO4J_USERNAME") or env.get("NEO4J_USER") or "neo4j"
    password = env.get("NEO4J_PASSWORD")
    if not password:
        return {"written": False, "reason": "NEO4J_PASSWORD not set"}

    cfg = _demo_config(env)
    if cfg is not None:
        # Reads a server-side path; rate-limit here. The node cap is enforced
        # below once a connection is open.
        error = _demo_guard_check(None, cfg)
        if error is not None:
            metrics.record_rejection(error["error"])
            return error

    rules = _load_rules(path, provider)
    metrics.record_rules_extracted(len(rules))
    findings: list[Finding] = []
    findings.extend(SyntacticDetector().detect(rules))
    exclude = {frozenset({f.rule_a.id, f.rule_b.id}) for f in findings}
    findings.extend(PrecedenceDetector().detect(rules, exclude=exclude))

    # AuraDB uses the neo4j+s:// scheme; pass the URI through unchanged.
    uri_scheme = uri.split("://", 1)[0]
    try:
        from rcg.graph.loader import GraphLoader

        graph_cleared = False
        n_nodes = 0
        with GraphLoader.connect(uri, user, password) as loader:
            if cfg is not None:
                # Auto-clear the small demo graph before it would exceed the
                # node cap, keeping the free AuraDB graph from filling up.
                # Estimate new nodes as rules + their distinct RuleFile nodes.
                n_files = len({rule.source.file for rule in rules})
                estimated_new = len(rules) + n_files
                existing = loader.count_nodes()
                if _should_clear(existing, estimated_new, cfg.graph_max_nodes):
                    loader.clear_all()
                    graph_cleared = True
                    metrics.record_graph_clear()
            loader.load_rules(rules)
            loader.load_conflicts(findings)
            if cfg is not None:
                n_nodes = loader.count_nodes()
    except Exception as exc:  # noqa: BLE001 — report, never crash the server.
        metrics.record_graph_write_failure()
        return {
            "written": False,
            "reason": f"graph write failed: {exc}",
            "uri_scheme": uri_scheme,
        }

    metrics.record_graph_write()

    summary: dict[str, Any] = {
        "written": True,
        "n_rules": len(rules),
        "n_conflicts": len(findings),
        "uri_scheme": uri_scheme,
    }
    if cfg is not None:
        summary["graph_cleared"] = graph_cleared
        summary["n_nodes"] = n_nodes
    return summary


def _explain_impl(
    action: str,
    path: str,
    scope: str = "*",
    provider: str = "mock",
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if env is None else env
    cfg = _demo_config(env)
    if cfg is not None:
        error = _demo_guard_check(None, cfg)
        if error is not None:
            metrics.record_rejection(error["error"])
            return error
    rules = _load_rules(path, provider)
    result = run_explain(rules, action, _build_provider(provider), scope=scope)
    return {
        "action": result.action,
        "action_class": result.action_class,
        "scope": result.scope,
        "verdict": result.verdict,
        "firing": [_rule_dict(r) for r in result.firing],
        "conflicts": [_finding_dict(f) for f in result.conflicts],
        "ambiguities": [_finding_dict(f) for f in result.ambiguities],
    }


def _score_impl(
    path: str, provider: str = "mock", env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    env = os.environ if env is None else env
    cfg = _demo_config(env)
    if cfg is not None:
        error = _demo_guard_check(None, cfg)
        if error is not None:
            metrics.record_rejection(error["error"])
            return error
    rules = _load_rules(path, provider)
    metrics.record_rules_extracted(len(rules))
    findings: list[Finding] = []
    findings.extend(SyntacticDetector().detect(rules))
    exclude = {frozenset({f.rule_a.id, f.rule_b.id}) for f in findings}
    findings.extend(PrecedenceDetector().detect(rules, exclude=exclude))
    report = score_corpus(len(rules), findings)
    return {
        "n_rules": report.n_rules,
        "score": report.score,
        "weighted": report.weighted,
        "by_type": report.by_type,
    }


@mcp.tool()
def check_corpus(path: str, provider: str = "mock", semantic: bool = False) -> dict[str, Any]:
    """Discover, extract, and check a rules corpus for conflicts and ambiguities."""
    metrics.record_tool_call("check_corpus")
    return _check_impl(path, provider=provider, semantic=semantic)


@mcp.tool()
def explain_action(
    action: str, path: str, scope: str = "*", provider: str = "mock"
) -> dict[str, Any]:
    """Explain which rules fire for a hypothetical action and whether they conflict."""
    metrics.record_tool_call("explain_action")
    return _explain_impl(action, path, scope=scope, provider=provider)


@mcp.tool(name="score_corpus")
def score_corpus_tool(path: str, provider: str = "mock") -> dict[str, Any]:
    """Return only the coherence score for a rules corpus."""
    metrics.record_tool_call("score_corpus")
    return _score_impl(path, provider=provider)


@mcp.tool()
def check_rules(
    rules_text: str, format: str = "markdown", semantic: bool = False
) -> dict[str, Any]:
    """Check a pasted rules corpus for conflicts and ambiguities.

    Use this from a remote client that cannot share its filesystem: paste the
    rules text and pick a ``format`` (markdown, cursorrules, cedar, rego, yaml).
    Runs offline with the deterministic mock extractor.
    """
    metrics.record_tool_call("check_rules")
    return _check_rules_impl(rules_text, fmt=format, semantic=semantic, provider="mock")


@mcp.tool()
def ingest_to_graph(path: str, provider: str = "mock") -> dict[str, Any]:
    """Check a corpus and persist it to Neo4j when ``NEO4J_URI`` is configured.

    Returns a summary of what was written. If no graph is configured, returns
    ``{"written": false, "reason": ...}`` rather than raising.
    """
    metrics.record_tool_call("ingest_to_graph")
    return _ingest_to_graph_impl(path, provider=provider)


def _resolve_transport(env: Mapping[str, str]) -> tuple[str, str, int]:
    """Decide the MCP transport from the environment (no socket binding).

    Returns ``(transport, host, port)`` where ``transport`` is one of
    ``"stdio"``, ``"streamable-http"`` or ``"sse"``. ``host``/``port`` are only
    meaningful for the HTTP transports; for stdio they are returned as defaults
    and ignored. Defaults to stdio so local clients keep working unchanged.
    """
    raw = env.get("RCG_MCP_TRANSPORT", "stdio").strip().lower()
    if raw in {"http", "streamable-http"}:
        transport = "streamable-http"
    elif raw == "sse":
        transport = "sse"
    else:
        transport = "stdio"

    host = "0.0.0.0" if transport != "stdio" else "127.0.0.1"
    try:
        port = int(env.get("PORT", "8080"))
    except ValueError:
        port = 8080
    return transport, host, port


def main() -> None:
    transport, host, port = _resolve_transport(os.environ)
    if transport == "stdio":
        # Never start the metrics server for stdio so local/Claude-Code use is
        # untouched and stdout stays clean for the MCP framing.
        mcp.run()
        return
    # HTTP transports may serve a Prometheus metrics endpoint on a separate
    # port (scraped by Fly; see docs/hosted-mcp.md). Start it before mcp.run.
    enabled, mhost, mport = metrics.resolve_metrics_config(os.environ)
    if enabled and mport == port:
        # The metrics endpoint must not collide with the MCP port; skip rather
        # than crash if they were misconfigured to the same value.
        print(
            f"rcg.metrics: metrics port {mport} equals MCP port {port}; "
            "not starting the metrics server.",
            file=sys.stderr,
        )
    elif enabled:
        metrics.start_metrics_server(mhost, mport)
    # HTTP transports need a bound host/port; FastMCP reads these from settings.
    mcp.settings.host = host
    mcp.settings.port = port
    if transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
