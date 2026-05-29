"""Action explanation: which rules fire for a hypothetical action, and do they conflict?

Given a natural-language description of an action an agent might take, classify it
into an ``action_class`` (reusing the same extractor used for the corpus), find the
rules that would fire, and run the syntactic + precedence passes over just those
firing rules so the caller learns whether the corpus gives a coherent answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from rcg.detectors.base import Finding, scopes_overlap
from rcg.detectors.precedence import PrecedenceDetector
from rcg.detectors.syntactic import SyntacticDetector
from rcg.providers.llm import LLMProvider
from rcg.schema import Directive, Modality, RawRule, Rule, Source, Trigger


@dataclass(frozen=True)
class ExplainResult:
    """Outcome of explaining a hypothetical action against a rule corpus."""

    action: str
    scope: str
    action_class: str
    firing: list[Rule]
    conflicts: list[Finding]
    ambiguities: list[Finding]
    verdict: str


def _classify(action: str, provider: LLMProvider) -> str:
    """Extract a synthetic rule from ``action`` to read off its action class."""
    from rcg.extractors.extract import extract_all

    raw = RawRule(text=action, source=Source(file="<query>", format="query"))
    rules = extract_all([raw], provider, cache=None)
    return rules[0].trigger.action_class


def _synthetic_query_rule(action_class: str, scope: str) -> Rule:
    """A throwaway Rule carrying the query's action class + scope for scope matching."""
    return Rule(
        raw_text="<query>",
        source=Source(file="<query>", format="query"),
        trigger=Trigger(action_class=action_class, scope_pattern=scope),
        directive=Directive(modality=Modality.MAY, action="<query>"),
    )


def _build_verdict(
    action_class: str,
    firing: list[Rule],
    conflicts: list[Finding],
    ambiguities: list[Finding],
) -> str:
    if not firing:
        return f"no rules fire for action_class '{action_class}'"
    head = f"{len(firing)} rule(s) fire for action_class '{action_class}'"
    if not conflicts and not ambiguities:
        return f"{head}; no conflicts — consistent"
    detail: list[str] = []
    if conflicts:
        detail.append(f"{len(conflicts)} direct conflict(s)")
    if ambiguities:
        detail.append(f"{len(ambiguities)} precedence ambiguity")
    return f"{head}; {', '.join(detail)} — RESOLUTION AMBIGUOUS"


def explain(
    rules: list[Rule],
    action: str,
    provider: LLMProvider,
    scope: str = "*",
) -> ExplainResult:
    """Explain which rules fire for ``action`` (within ``scope``) and whether they clash."""
    action_class = _classify(action, provider)
    query_rule = _synthetic_query_rule(action_class, scope)
    firing = [
        r
        for r in rules
        if r.trigger.action_class == action_class and scopes_overlap(query_rule, r)
    ]
    conflicts: list[Finding] = list(SyntacticDetector().detect(firing))
    exclude = {frozenset({c.rule_a.id, c.rule_b.id}) for c in conflicts}
    ambiguities: list[Finding] = list(PrecedenceDetector().detect(firing, exclude=exclude))
    verdict = _build_verdict(action_class, firing, conflicts, ambiguities)
    return ExplainResult(
        action=action,
        scope=scope,
        action_class=action_class,
        firing=firing,
        conflicts=conflicts,
        ambiguities=ambiguities,
        verdict=verdict,
    )
