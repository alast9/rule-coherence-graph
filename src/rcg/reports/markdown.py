"""Render detector findings as a markdown report.

`render` is the original flat conflict renderer (kept for backward compatibility);
`render_report` is the richer, multi-pass report with the coherence score and
findings grouped by type.

Both include original `raw_text` (any language) plus the English-normalised
summary, and flag rules that were translated by the LLM so the reader can
adjudicate.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from rcg.detectors.base import Finding

if TYPE_CHECKING:
    from rcg.schema import Rule
    from rcg.scoring import ScoreReport

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_TYPE_TITLES = {
    "syntactic": "Syntactic conflicts",
    "semantic": "Semantic conflicts",
    "precedence": "Precedence ambiguities",
}
_TYPE_ORDER = ["syntactic", "semantic", "precedence"]


def render(conflicts: Iterable[Finding]) -> str:
    """Flat, severity-sorted conflict report (backward-compatible)."""
    conflicts = sorted(
        conflicts,
        key=lambda c: (_SEVERITY_ORDER.get(c.severity, 99), c.rule_a.source.file),
    )

    lines: list[str] = ["# RCG conflict report", ""]
    if not conflicts:
        lines += ["No conflicts detected.", ""]
        return "\n".join(lines)

    lines += [f"Found **{len(conflicts)}** conflict(s).", ""]

    for i, c in enumerate(conflicts, 1):
        lines += [
            f"## {i}. {c.severity.upper()} — {c.type}",
            "",
            f"_{c.reason}_",
            "",
            _render_rule("Rule A", c.rule_a),
            "",
            _render_rule("Rule B", c.rule_b),
            "",
            "---",
            "",
        ]
    return "\n".join(lines)


def render_report(
    findings: Sequence[Finding],
    score: ScoreReport | None = None,
    suppressed: int = 0,
) -> str:
    """Render findings grouped by type, each sorted by severity, with the score."""
    lines: list[str] = ["# RCG report", ""]

    if score is not None:
        lines.append(f"**Coherence score:** {score.score:.3f}  ({score.n_rules} rule(s))")
        if score.by_type:
            breakdown = ", ".join(
                f"{t}: {score.by_type[t]}" for t in _TYPE_ORDER if t in score.by_type
            )
            lines.append(f"**Findings by type:** {breakdown}")
        lines.append("")

    if not findings:
        lines.append("No conflicts detected.")
        if suppressed > 0:
            lines += ["", f"_Suppressed by baseline: {suppressed}._"]
        lines.append("")
        return "\n".join(lines)

    lines.append(f"Found **{len(findings)}** finding(s).")
    if suppressed > 0:
        lines.append(f"_Suppressed by baseline: {suppressed}._")
    lines.append("")

    grouped: dict[str, list[Finding]] = {}
    for f in findings:
        grouped.setdefault(f.type, []).append(f)

    ordered_types = [t for t in _TYPE_ORDER if t in grouped]
    ordered_types += [t for t in grouped if t not in _TYPE_ORDER]

    for ftype in ordered_types:
        group = sorted(grouped[ftype], key=lambda c: _SEVERITY_ORDER.get(c.severity, 99))
        title = _TYPE_TITLES.get(ftype, ftype.capitalize())
        lines += [f"## {title} ({len(group)})", ""]
        for i, f in enumerate(group, 1):
            lines += [
                f"### {i}. {f.severity.upper()}",
                "",
                f"_{f.reason}_",
                "",
                _render_rule("Rule A", f.rule_a),
                "",
                _render_rule("Rule B", f.rule_b),
                "",
                "---",
                "",
            ]
    return "\n".join(lines)


def _render_rule(label: str, rule: Rule) -> str:
    src = rule.source
    location = f"`{src.file}`"
    if src.line_start:
        location += f":{src.line_start}"
    section = f" — _{src.section}_" if src.section else ""

    lang_note = ""
    if src.original_language and src.original_language != "en":
        lang_note = (
            f"\n\n> ⚠ Rule originally in `{src.original_language}`; "
            f"extracted via LLM translation. Verify wording."
        )

    return (
        f"**{label}** ({location}{section}) "
        f"[`{rule.directive.modality.value}` `{rule.trigger.action_class}`]\n"
        f"\n"
        f"> {rule.raw_text}\n"
        f"\n"
        f"_English summary: {rule.directive.action}_"
        f"{lang_note}"
    )
