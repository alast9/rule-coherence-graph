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
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from rcg.detectors.base import Finding
from rcg.detectors.precedence import PrecedenceDetector
from rcg.detectors.syntactic import SyntacticDetector
from rcg.explain import explain as run_explain
from rcg.extractors.extract import extract_all
from rcg.parsers.discovery import discover
from rcg.providers.llm import LLMProvider
from rcg.schema import Rule
from rcg.scoring import score_corpus

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


def _check_impl(path: str, provider: str = "mock", semantic: bool = False) -> dict[str, Any]:
    rules = _load_rules(path, provider)
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
    rules_text: str, fmt: str = "markdown", semantic: bool = False, provider: str = "mock"
) -> dict[str, Any]:
    """Run the check pipeline over a pasted rules string (no filesystem access).

    The text is written to a temp file named for ``fmt`` so the normal discovery
    path picks the right parser, then the temp directory is removed.
    """
    filename = _FORMAT_FILENAMES.get(fmt.lower(), _FORMAT_FILENAMES["markdown"])
    with tempfile.TemporaryDirectory(prefix="rcg-mcp-") as tmp:
        target = Path(tmp) / filename
        target.write_text(rules_text, encoding="utf-8")
        return _check_impl(str(target), provider=provider, semantic=semantic)


def _ingest_to_graph_impl(
    path: str, provider: str = "mock", env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Check a corpus and, if Neo4j env is configured, persist it to the graph.

    Never raises on a missing or unreachable database — failures are reported in
    the return value so the server stays up for the next caller.
    """
    env = os.environ if env is None else env
    uri = env.get("NEO4J_URI")
    if not uri:
        return {"written": False, "reason": "NEO4J_URI not set"}

    user = env.get("NEO4J_USERNAME") or env.get("NEO4J_USER") or "neo4j"
    password = env.get("NEO4J_PASSWORD")
    if not password:
        return {"written": False, "reason": "NEO4J_PASSWORD not set"}

    rules = _load_rules(path, provider)
    findings: list[Finding] = []
    findings.extend(SyntacticDetector().detect(rules))
    exclude = {frozenset({f.rule_a.id, f.rule_b.id}) for f in findings}
    findings.extend(PrecedenceDetector().detect(rules, exclude=exclude))

    # AuraDB uses the neo4j+s:// scheme; pass the URI through unchanged.
    uri_scheme = uri.split("://", 1)[0]
    try:
        from rcg.graph.loader import GraphLoader

        with GraphLoader.connect(uri, user, password) as loader:
            loader.load_rules(rules)
            loader.load_conflicts(findings)
    except Exception as exc:  # noqa: BLE001 — report, never crash the server.
        return {
            "written": False,
            "reason": f"graph write failed: {exc}",
            "uri_scheme": uri_scheme,
        }

    return {
        "written": True,
        "n_rules": len(rules),
        "n_conflicts": len(findings),
        "uri_scheme": uri_scheme,
    }


def _explain_impl(
    action: str, path: str, scope: str = "*", provider: str = "mock"
) -> dict[str, Any]:
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


def _score_impl(path: str, provider: str = "mock") -> dict[str, Any]:
    rules = _load_rules(path, provider)
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
    return _check_impl(path, provider=provider, semantic=semantic)


@mcp.tool()
def explain_action(
    action: str, path: str, scope: str = "*", provider: str = "mock"
) -> dict[str, Any]:
    """Explain which rules fire for a hypothetical action and whether they conflict."""
    return _explain_impl(action, path, scope=scope, provider=provider)


@mcp.tool(name="score_corpus")
def score_corpus_tool(path: str, provider: str = "mock") -> dict[str, Any]:
    """Return only the coherence score for a rules corpus."""
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
    return _check_rules_impl(rules_text, fmt=format, semantic=semantic, provider="mock")


@mcp.tool()
def ingest_to_graph(path: str, provider: str = "mock") -> dict[str, Any]:
    """Check a corpus and persist it to Neo4j when ``NEO4J_URI`` is configured.

    Returns a summary of what was written. If no graph is configured, returns
    ``{"written": false, "reason": ...}`` rather than raising.
    """
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
        mcp.run()
        return
    # HTTP transports need a bound host/port; FastMCP reads these from settings.
    mcp.settings.host = host
    mcp.settings.port = port
    if transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
