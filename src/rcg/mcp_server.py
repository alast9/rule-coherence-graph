"""Expose RCG over the Model Context Protocol (stdio) so agents can call it.

Tools default to the offline mock provider so the server runs without an API key.
Each tool's logic lives in a thin ``_*_impl`` helper that returns a JSON-serialisable
dict; the decorated tool functions just delegate, keeping the logic unit-testable
without an MCP client.
"""

from __future__ import annotations

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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
