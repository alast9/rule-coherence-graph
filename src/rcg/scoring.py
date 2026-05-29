"""Corpus-level coherence scoring.

A coherence score in ``[0, 1]`` summarizes how conflict-free a rule corpus is.
Each finding contributes a type-weighted penalty (syntactic conflicts are the
most severe, precedence ambiguities the least), normalized by the number of
rules.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from rcg.detectors.base import Finding

TYPE_WEIGHTS: dict[str, float] = {
    "syntactic": 1.0,
    "semantic": 0.7,
    "precedence": 0.4,
}


@dataclass
class ScoreReport:
    """Aggregate coherence metrics for a corpus."""

    n_rules: int
    score: float
    weighted: float
    by_type: dict[str, int] = field(default_factory=dict)
    per_rule: dict[str, int] = field(default_factory=dict)


def score_corpus(n_rules: int, findings: Sequence[Finding]) -> ScoreReport:
    """Compute a :class:`ScoreReport` for ``findings`` over ``n_rules`` rules."""
    weighted = sum(TYPE_WEIGHTS.get(f.type, 1.0) for f in findings)
    if n_rules == 0:
        score = 1.0
    else:
        score = max(0.0, 1.0 - weighted / n_rules)

    by_type: dict[str, int] = dict(Counter(f.type for f in findings))

    per_rule: Counter[str] = Counter()
    for f in findings:
        per_rule[f.rule_a.id] += 1
        per_rule[f.rule_b.id] += 1

    return ScoreReport(
        n_rules=n_rules,
        score=score,
        weighted=weighted,
        by_type=by_type,
        per_rule=dict(per_rule),
    )
