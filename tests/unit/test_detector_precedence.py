"""Tests for the precedence detector."""

from __future__ import annotations

from rcg.detectors.precedence import PrecedenceDetector
from rcg.schema import Directive, Modality, Rule, Source, Trigger


def _rule(
    text: str,
    file: str,
    action_class: str = "rules.precedence",
    precedence_over: tuple[str, ...] = (),
) -> Rule:
    return Rule(
        raw_text=text,
        source=Source(file=file, format="markdown"),
        trigger=Trigger(action_class=action_class, scope_pattern="*"),
        directive=Directive(modality=Modality.MUST, action="x"),
        priority={"declared_precedence_over": list(precedence_over)},
    )


def test_cross_file_unordered_pair_flagged() -> None:
    a = _rule("cursor wins", "a.md")
    b = _rule("agent wins", "b.md")
    found = PrecedenceDetector().detect([a, b])
    assert len(found) == 1
    assert found[0].type == "precedence"
    assert found[0].severity == "critical"  # rules.* action class


def test_declared_order_suppresses() -> None:
    b = _rule("agent wins", "b.md")
    a = _rule("cursor wins", "a.md", precedence_over=(b.id,))
    found = PrecedenceDetector().detect([a, b])
    assert found == []


def test_same_file_not_flagged() -> None:
    a = _rule("rule one", "same.md")
    b = _rule("rule two", "same.md")
    found = PrecedenceDetector().detect([a, b])
    assert found == []


def test_excluded_pair_not_flagged() -> None:
    a = _rule("cursor wins", "a.md")
    b = _rule("agent wins", "b.md")
    exclude = {frozenset({a.id, b.id})}
    found = PrecedenceDetector().detect([a, b], exclude=exclude)
    assert found == []


def test_non_co_firing_not_flagged() -> None:
    a = _rule("a", "a.md", action_class="deploy.release")
    b = _rule("b", "b.md", action_class="data.export")
    found = PrecedenceDetector().detect([a, b])
    assert found == []


def test_non_rules_action_class_is_medium() -> None:
    a = _rule("a", "a.md", action_class="deploy.release")
    b = _rule("b", "b.md", action_class="deploy.release")
    found = PrecedenceDetector().detect([a, b])
    assert len(found) == 1
    assert found[0].severity == "medium"
