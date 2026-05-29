"""Tests for corpus coherence scoring."""

from __future__ import annotations

from dataclasses import dataclass

from rcg.schema import Directive, Modality, Rule, Source, Trigger
from rcg.scoring import score_corpus


def _rule(text: str) -> Rule:
    return Rule(
        raw_text=text,
        source=Source(file="f.md", format="markdown"),
        trigger=Trigger(action_class="x"),
        directive=Directive(modality=Modality.MUST, action="a"),
    )


@dataclass
class _Finding:
    rule_a: Rule
    rule_b: Rule
    type: str
    severity: str
    reason: str


def _finding(ftype: str, a: Rule, b: Rule) -> _Finding:
    return _Finding(rule_a=a, rule_b=b, type=ftype, severity="high", reason="r")


def test_weights_applied() -> None:
    r1, r2 = _rule("one"), _rule("two")
    findings = [
        _finding("syntactic", r1, r2),
        _finding("semantic", r1, r2),
        _finding("precedence", r1, r2),
    ]
    report = score_corpus(10, findings)
    assert report.weighted == 1.0 + 0.7 + 0.4
    assert report.score == 1.0 - 2.1 / 10
    assert report.by_type == {"syntactic": 1, "semantic": 1, "precedence": 1}


def test_clamp_at_zero() -> None:
    r1, r2 = _rule("one"), _rule("two")
    findings = [_finding("syntactic", r1, r2) for _ in range(5)]
    report = score_corpus(2, findings)
    assert report.score == 0.0


def test_per_rule_counts() -> None:
    r1, r2, r3 = _rule("one"), _rule("two"), _rule("three")
    findings = [
        _finding("syntactic", r1, r2),
        _finding("semantic", r1, r3),
    ]
    report = score_corpus(3, findings)
    assert report.per_rule[r1.id] == 2
    assert report.per_rule[r2.id] == 1
    assert report.per_rule[r3.id] == 1


def test_empty_corpus_scores_one() -> None:
    report = score_corpus(0, [])
    assert report.score == 1.0
    assert report.by_type == {}
    assert report.per_rule == {}
