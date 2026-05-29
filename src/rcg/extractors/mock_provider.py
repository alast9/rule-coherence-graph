"""Deterministic, keyword-driven mock provider.

Lets the slice run end-to-end without an Anthropic API key — used for the demo
and for unit tests. It is intentionally lossy: it knows just enough heuristics
to extract the conflicts the gemini_incident fixture is designed to expose.

This is NOT a production extractor. It exists so the pipeline is verifiable
without paid dependencies.
"""

from __future__ import annotations

import re

from rcg.schema import Directive, Modality, RawRule, Rule, Source, Trigger

PROMPT_VERSION = "mock.v3"

# Policy-as-code action references (OPA Rego / AWS Cedar). Checked before the
# natural-language heuristics so an explicit machine-readable action reference
# (e.g. ``Action::"DeleteObject"`` or ``input.method == "DELETE"``) lands on the
# same coarse class as the prose rule it should conflict with — without this the
# generic words around it (e.g. "production") would mis-class the policy.
_POLICY_ACTION_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r'(?:Action::|input\.action\s*==\s*)"[^"]*(?:delete|remove|destroy|wipe)[^"]*"'
            r'|input\.method\s*==\s*"DELETE"',
            re.I,
        ),
        "fs.destructive",
    ),
    (
        re.compile(
            r'(?:Action::|input\.action\s*==\s*)"[^"]*(?:deploy|release|publish)[^"]*"',
            re.I,
        ),
        "deploy.production",
    ),
]

# Action-class heuristics. Order matters — first match wins. The order is
# arranged so the *most specific* class wins (rules-meta before deploy before
# generic confirm/destructive/scope).
_ACTION_CLASS_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"rule files|\.agent/rules|modify (its|their) own rule", re.I),
        "rules.modify_self",
    ),
    (re.compile(r"firebase|production|deploy|rewrite", re.I), "deploy.production"),
    (re.compile(r"permission|grant", re.I), "permissions.grant"),
    # Deliberately strict — generic words like "prompt" / "ask" cause false positives
    # ("user's prompt", "task" matching "ask\b"), so require explicit confirmation vocab.
    (re.compile(r"confirm|confirmation|xác nhận|yêu cầu", re.I), "agent.confirm"),
    (re.compile(r"scope|unrelated files|touch.*files", re.I), "agent.scope"),
    (re.compile(r"destructive|delete|wipe", re.I), "fs.destructive"),
]

# Policy-as-code modality signals (OPA Rego / AWS Cedar). A denial keyword
# (``forbid``/``deny``) reads as MUST_NOT; a grant keyword (``permit``/``allow``)
# reads as MAY. Checked before the natural-language modality rules but only as an
# *additional* signal so they never regress markdown phrasing — they fire only
# when the keyword appears as a policy verb (word-boundary match).
_POLICY_MODALITY_RULES: list[tuple[re.Pattern[str], Modality]] = [
    (re.compile(r"\b(forbid|deny)\b", re.I), Modality.MUST_NOT),
    (re.compile(r"\b(permit|allow)\b", re.I), Modality.MAY),
]

# Modality heuristics. Order matters; first hit wins. Negative forms come first
# because text like "MUST NOT" must not be matched by the "must" pattern.
_MODALITY_RULES: list[tuple[re.Pattern[str], Modality]] = [
    (
        re.compile(r"\bmust not\b|\bnever\b|\bdo not\b|\bdon't\b|\bcannot\b", re.I),
        Modality.MUST_NOT,
    ),
    (re.compile(r"\bkhông bao giờ\b|\bkhông\b", re.I), Modality.MUST_NOT),
    (re.compile(r"\bshould not\b|\bavoid\b", re.I), Modality.SHOULD_NOT),
    (re.compile(r"\bmay\b|\bcan\b", re.I), Modality.MAY),
    (re.compile(r"\bmust\b|\balways\b|\brequire(s|d)?\b", re.I), Modality.MUST),
    (re.compile(r"\bauto-?deploy|automatically|default to\b", re.I), Modality.MUST),
    (re.compile(r"\bshould\b|\bprefer\b", re.I), Modality.SHOULD),
]

# Human-in-the-loop stance. For approval-sensitive rules the real axis of
# conflict is "is human approval required" vs "is it bypassed" — NOT the surface
# MUST/MUST_NOT, which mis-reads "do not X without approval" as a prohibition.
# Checked requires-first so "do not deploy without approval" is read as
# approval-required, not as a bypass.
_REQUIRES_APPROVAL: list[re.Pattern[str]] = [
    re.compile(r"\brequire(s|d)?\b.{0,40}\b(confirm|confirmation|approval|consent)\b", re.I),
    re.compile(
        r"\b(do not|don'?t|never|cannot|must not)\b.{0,60}\bwithout\b.{0,40}"
        r"\b(approval|confirmation|consent|review)\b",
        re.I,
    ),
    re.compile(r"\bexplicit (human )?(approval|confirmation|consent)\b", re.I),
]
_BYPASSES_APPROVAL: list[re.Pattern[str]] = [
    re.compile(r"\bnever\b.{0,40}\b(prompt|ask)\b", re.I),
    re.compile(r"\bwithout\b.{0,20}\b(waiting|review|human review)\b", re.I),
    re.compile(r"\bauto-?deploy\b|\bautomatically\b|\bimmediately\b", re.I),
    re.compile(r"\bkhông bao giờ\b.{0,40}\b(xác nhận|yêu cầu)\b", re.I),
]


class MockProvider:
    model_id = "mock-extractor"
    prompt_version = PROMPT_VERSION

    def extract(self, raw: RawRule) -> Rule:
        text = raw.text
        action_class = _classify_action(text)
        modality = _classify_modality(text)
        lang = "vi" if _looks_vietnamese(text) else None
        stance = _classify_approval_stance(text)

        return Rule(
            raw_text=text,
            source=Source(
                file=raw.source.file,
                line_start=raw.source.line_start,
                line_end=raw.source.line_end,
                format=raw.source.format,
                section=raw.source.section,
                original_language=lang,
            ),
            trigger=Trigger(
                action_class=action_class,
                scope_pattern="*",
                context_conditions=[stance] if stance else [],
            ),
            directive=Directive(modality=modality, action=text),
            confidence=0.6,
            tags=[],
        )


def _classify_action(text: str) -> str:
    # Machine-readable policy action references win first so a Rego/Cedar rule
    # lands on the same coarse class as the prose rule it should conflict with.
    for pattern, cls in _POLICY_ACTION_RULES:
        if pattern.search(text):
            return cls
    for pattern, cls in _ACTION_CLASS_RULES:
        if pattern.search(text):
            return cls
    return "agent.execute_action"


def _classify_modality(text: str) -> Modality:
    for pattern, mod in _MODALITY_RULES:
        if pattern.search(text):
            return mod
    # Fall back to policy denial/grant keywords only when natural-language
    # phrasing was inconclusive, so markdown rules never regress.
    for pattern, mod in _POLICY_MODALITY_RULES:
        if pattern.search(text):
            return mod
    return Modality.SHOULD


def _classify_approval_stance(text: str) -> str | None:
    """Return the rule's human-in-the-loop stance, or None if it expresses none."""
    if any(p.search(text) for p in _REQUIRES_APPROVAL):
        return "requires_human_approval"
    if any(p.search(text) for p in _BYPASSES_APPROVAL):
        return "bypasses_human_approval"
    return None


def _looks_vietnamese(text: str) -> bool:
    return bool(re.search(r"[ơưăâêôỳỹýỷỵạảấầẩẫậắằẳẵặẹẻẽếềểễệịỉĩỏốồổỗộớờởỡợụủũứừửữựỳỵỷỹ]", text))
