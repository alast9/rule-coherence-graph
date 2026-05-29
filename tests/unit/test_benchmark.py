"""Tests for the precision/recall benchmark harness."""

from __future__ import annotations

from pathlib import Path

from rcg.benchmark import Metrics, RulePair, evaluate, load_dataset
from rcg.detectors.semantic import MockJudge
from rcg.providers.embedding import HashingEmbeddingProvider
from rcg.schema import Modality

DATASET = Path(__file__).resolve().parents[2] / "benchmarks" / "dataset.jsonl"


def test_load_dataset_parses_shipped_file() -> None:
    pairs = load_dataset(DATASET)
    assert len(pairs) >= 60
    labels = {p.label for p in pairs}
    assert labels == {"conflict", "ok"}
    categories = {p.category for p in pairs}
    assert {"modality", "approval-stance", "semantic", "precedence", "unrelated"} <= categories
    # Balanced enough: a healthy share of conflicts.
    n_conflict = sum(1 for p in pairs if p.is_conflict)
    assert 20 <= n_conflict <= 35
    # Modality enum parsed on both sides.
    assert all(isinstance(p.a_modality, Modality) for p in pairs)
    assert all(isinstance(p.b_modality, Modality) for p in pairs)


def test_metrics_precision_recall_f1() -> None:
    m = Metrics(tp=3, fp=1, fn=1, tn=5)
    assert m.precision == 0.75
    assert m.recall == 0.75
    assert m.f1 == 0.75
    empty = Metrics()
    assert empty.precision == 0.0
    assert empty.recall == 0.0
    assert empty.f1 == 0.0


def _pair(label: str, a_mod: Modality, b_mod: Modality, *, action: str = "deploy") -> RulePair:
    return RulePair(
        category="modality",
        label=label,
        a_text=f"do {action}",
        a_action_class=action,
        a_modality=a_mod,
        a_scope="*",
        a_context=(),
        b_text=f"do not {action}",
        b_action_class=action,
        b_modality=b_mod,
        b_scope="*",
        b_context=(),
    )


def test_evaluate_known_cases() -> None:
    # Clear syntactic conflict (MUST vs MUST_NOT, same action) -> TP.
    tp_pair = _pair("conflict", Modality.MUST, Modality.MUST_NOT)
    # "ok" pair: opposing modality but different action class -> not detected -> TN.
    tn_pair = RulePair(
        category="modality",
        label="ok",
        a_text="do merge",
        a_action_class="merge",
        a_modality=Modality.MUST,
        a_scope="*",
        a_context=(),
        b_text="do not lint",
        b_action_class="lint",
        b_modality=Modality.MUST_NOT,
        b_scope="*",
        b_context=(),
    )
    # Labeled conflict the syntactic pass misses (same modality) -> FN for syntactic.
    fn_pair = _pair("conflict", Modality.MUST, Modality.MUST, action="release")

    report = evaluate(
        [tp_pair, tn_pair, fn_pair],
        embedder=HashingEmbeddingProvider(),
        judge=MockJudge(),
        semantic=False,
    )
    syn = report.syntactic.overall
    assert syn.tp == 1  # tp_pair
    assert syn.fp == 0  # tn_pair ignored (different action class)
    assert syn.tn == 1  # tn_pair is ok and not detected
    assert syn.fn == 1  # fn_pair is conflict but not detected
    assert syn.precision == 1.0
    assert syn.recall == 0.5


def test_to_markdown_contains_metric_labels() -> None:
    report = evaluate(
        [_pair("conflict", Modality.MUST, Modality.MUST_NOT)],
        embedder=HashingEmbeddingProvider(),
        judge=MockJudge(),
        semantic=True,
    )
    md = report.to_markdown()
    assert "precision" in md
    assert "recall" in md
    assert "F1" in md
    assert "syntactic" in md
    assert "semantic" in md
    assert "combined" in md


def test_deterministic_regression_guard() -> None:
    """Run the full shipped dataset deterministically (hashing + MockJudge, no network).

    Thresholds come from the observed deterministic run: syntactic precision 1.000 and
    recall 0.500, combined precision ~0.867 and recall 0.500. The load-bearing invariant
    is that adding the semantic pass NEVER reduces recall (combined >= syntactic). Bounds
    are loose so the test stays stable if the dataset grows slightly.
    """
    pairs = load_dataset(DATASET)
    report = evaluate(
        pairs,
        embedder=HashingEmbeddingProvider(),
        judge=MockJudge(),
        semantic=True,
    )
    syn = report.syntactic.overall
    comb = report.combined.overall
    # The syntactic pass is deliberately conservative: high precision.
    assert syn.precision >= 0.9
    # Semantic never hurts recall.
    assert comb.recall >= syn.recall
    # Sanity floor on syntactic recall from the observed run (0.500).
    assert syn.recall >= 0.45
    # Combined must not introduce wild false positives.
    assert comb.precision >= 0.75
