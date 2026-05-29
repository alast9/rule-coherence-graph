"""Render a list of Conflicts as a markdown report.

Includes original `raw_text` (any language) plus the English-normalised summary,
and flags rules that were translated by the LLM so the reader can adjudicate.
"""

from __future__ import annotations

from collections.abc import Iterable

from rcg.detectors.syntactic import Conflict

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def render(conflicts: Iterable[Conflict]) -> str:
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


def _render_rule(label: str, rule) -> str:  # type: ignore[no-untyped-def]
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
