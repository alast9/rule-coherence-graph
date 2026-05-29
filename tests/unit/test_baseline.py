"""Tests for the accepted-conflicts baseline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rcg.baseline import fingerprint, load_baseline, split_baselined, write_baseline
from rcg.schema import Directive, Modality, Rule, Source, Trigger


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


def test_fingerprint_stable_and_order_independent() -> None:
    a, b = _rule("alpha"), _rule("beta")
    f1 = _finding("syntactic", a, b)
    f2 = _finding("syntactic", b, a)
    assert fingerprint(f1) == fingerprint(f2)
    # type changes the fingerprint
    assert fingerprint(_finding("semantic", a, b)) != fingerprint(f1)


def test_write_load_round_trip(tmp_path: Path) -> None:
    a, b, c = _rule("alpha"), _rule("beta"), _rule("gamma")
    findings = [_finding("syntactic", a, b), _finding("semantic", a, c)]
    path = tmp_path / "baseline.json"
    count = write_baseline(path, findings)
    assert count == 2
    loaded = load_baseline(path)
    assert loaded == {fingerprint(findings[0]), fingerprint(findings[1])}


def test_load_missing_returns_empty(tmp_path: Path) -> None:
    assert load_baseline(tmp_path / "nope.json") == set()


def test_split_baselined_filters() -> None:
    a, b, c = _rule("alpha"), _rule("beta"), _rule("gamma")
    keep = _finding("syntactic", a, b)
    accept = _finding("semantic", a, c)
    accepted = {fingerprint(accept)}
    kept, suppressed = split_baselined([keep, accept], accepted)
    assert kept == [keep]
    assert suppressed == [accept]
