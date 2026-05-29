"""Precision/recall benchmark for the RCG detection passes.

This measures the *detectors* (syntactic + semantic), not the LLM extractor:
rules are built directly from the explicit labeled fields so the numbers
reflect detection quality on a fixed, honest input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from rcg.detectors.semantic import SemanticJudge
from rcg.detectors.syntactic import SyntacticDetector
from rcg.providers.embedding import EmbeddingProvider, cosine
from rcg.schema import Directive, Modality, Rule, Source, Trigger

DEFAULT_DATASET = Path("benchmarks/dataset.jsonl")

_BENCHMARK_FORMAT = "benchmark"


@dataclass(frozen=True)
class RulePair:
    """One labeled rule pair from the dataset."""

    category: str
    label: str  # "conflict" | "ok"
    a_text: str
    a_action_class: str
    a_modality: Modality
    a_scope: str
    a_context: tuple[str, ...]
    b_text: str
    b_action_class: str
    b_modality: Modality
    b_scope: str
    b_context: tuple[str, ...]
    note: str = ""

    @property
    def is_conflict(self) -> bool:
        """Ground-truth label as a boolean."""
        return self.label == "conflict"

    def rule_a(self) -> Rule:
        """Build the first Rule directly from labeled fields."""
        return _make_rule(
            self.a_text,
            self.a_action_class,
            self.a_modality,
            self.a_scope,
            self.a_context,
            file="benchmark::a",
        )

    def rule_b(self) -> Rule:
        """Build the second Rule directly from labeled fields."""
        return _make_rule(
            self.b_text,
            self.b_action_class,
            self.b_modality,
            self.b_scope,
            self.b_context,
            file="benchmark::b",
        )


def _make_rule(
    text: str,
    action_class: str,
    modality: Modality,
    scope: str,
    context: tuple[str, ...],
    *,
    file: str,
) -> Rule:
    return Rule(
        raw_text=text,
        source=Source(file=file, format=_BENCHMARK_FORMAT),
        trigger=Trigger(
            action_class=action_class,
            scope_pattern=scope,
            context_conditions=list(context),
        ),
        directive=Directive(modality=modality, action=text),
    )


def _side(obj: dict[str, object]) -> tuple[str, str, Modality, str, tuple[str, ...]]:
    text = str(obj["text"])
    action_class = str(obj["action_class"])
    modality: Modality = Modality(str(obj["modality"]))
    scope = str(obj.get("scope", "*"))
    raw_ctx = obj.get("context_conditions", [])
    context = tuple(str(c) for c in raw_ctx) if isinstance(raw_ctx, list) else ()
    return text, action_class, modality, scope, context


def load_dataset(path: Path) -> list[RulePair]:
    """Parse a JSONL labeled dataset into typed RulePair objects."""
    pairs: list[RulePair] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        obj = json.loads(line)
        a = _side(obj["a"])
        b = _side(obj["b"])
        pairs.append(
            RulePair(
                category=str(obj["category"]),
                label=str(obj["label"]),
                a_text=a[0],
                a_action_class=a[1],
                a_modality=a[2],
                a_scope=a[3],
                a_context=a[4],
                b_text=b[0],
                b_action_class=b[1],
                b_modality=b[2],
                b_scope=b[3],
                b_context=b[4],
                note=str(obj.get("note", "")),
            )
        )
    return pairs


@dataclass
class Metrics:
    """TP/FP/FN/TN counts plus derived precision/recall/F1."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def add(self, predicted: bool, actual: bool) -> None:
        """Accumulate one prediction against ground truth."""
        if predicted and actual:
            self.tp += 1
        elif predicted and not actual:
            self.fp += 1
        elif not predicted and actual:
            self.fn += 1
        else:
            self.tn += 1

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class PassMetrics:
    """Overall + per-category metrics for a single detection pass."""

    name: str
    overall: Metrics = field(default_factory=Metrics)
    by_category: dict[str, Metrics] = field(default_factory=dict)

    def record(self, category: str, predicted: bool, actual: bool) -> None:
        """Record one prediction into overall and the per-category bucket."""
        self.overall.add(predicted, actual)
        self.by_category.setdefault(category, Metrics()).add(predicted, actual)


@dataclass
class BenchmarkReport:
    """Full benchmark result across the three detection passes."""

    syntactic: PassMetrics
    semantic: PassMetrics
    combined: PassMetrics
    n_pairs: int
    semantic_enabled: bool
    sim_threshold: float
    precedence_ambiguities: int = 0

    def _passes(self) -> list[PassMetrics]:
        passes = [self.syntactic]
        if self.semantic_enabled:
            passes.append(self.semantic)
        passes.append(self.combined)
        return passes

    def to_markdown(self) -> str:
        """Render the report as markdown tables (overall + per category)."""
        lines: list[str] = []
        lines.append(f"## Benchmark ({self.n_pairs} labeled pairs)")
        lines.append("")
        lines.append(
            f"semantic={'on' if self.semantic_enabled else 'off'}, "
            f"sim_threshold={self.sim_threshold}"
        )
        lines.append("")
        lines.append("### Overall")
        lines.append("")
        lines.append("| pass | precision | recall | F1 | TP | FP | FN | TN |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for p in self._passes():
            m = p.overall
            lines.append(
                f"| {p.name} | {m.precision:.3f} | {m.recall:.3f} | {m.f1:.3f} "
                f"| {m.tp} | {m.fp} | {m.fn} | {m.tn} |"
            )
        lines.append("")

        categories = sorted(self.combined.by_category)
        lines.append("### By category")
        lines.append("")
        lines.append("| category | pass | precision | recall | F1 | TP | FP | FN | TN |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for cat in categories:
            for p in self._passes():
                cm = p.by_category.get(cat)
                if cm is None:
                    continue
                lines.append(
                    f"| {cat} | {p.name} | {cm.precision:.3f} | {cm.recall:.3f} | {cm.f1:.3f} "
                    f"| {cm.tp} | {cm.fp} | {cm.fn} | {cm.tn} |"
                )
        lines.append("")
        if self.precedence_ambiguities:
            lines.append(
                f"_Precedence note: {self.precedence_ambiguities} same-action / same-modality "
                "pair(s) would raise a precedence ambiguity; excluded from precision/recall "
                "by design._"
            )
            lines.append("")
        return "\n".join(lines)


def _semantic_predict(
    pair: RulePair,
    *,
    embedder: EmbeddingProvider,
    judge: SemanticJudge,
    sim_threshold: float,
) -> bool:
    va = embedder.embed([pair.a_text])[0]
    vb = embedder.embed([pair.b_text])[0]
    if cosine(va, vb) < sim_threshold:
        return False
    return judge.judge(pair.rule_a(), pair.rule_b()).is_conflict


def evaluate(
    pairs: list[RulePair],
    *,
    embedder: EmbeddingProvider,
    judge: SemanticJudge,
    semantic: bool,
    sim_threshold: float = 0.55,
) -> BenchmarkReport:
    """Run the detectors over labeled pairs and compute precision/recall/F1."""
    syntactic = PassMetrics("syntactic")
    semantic_pass = PassMetrics("semantic")
    combined = PassMetrics("combined")
    detector = SyntacticDetector()
    precedence_ambiguities = 0

    for pair in pairs:
        ra = pair.rule_a()
        rb = pair.rule_b()
        actual = pair.is_conflict

        syn_pred = bool(detector.detect([ra, rb]))
        syntactic.record(pair.category, syn_pred, actual)

        if semantic:
            sem_pred = _semantic_predict(
                pair, embedder=embedder, judge=judge, sim_threshold=sim_threshold
            )
            semantic_pass.record(pair.category, sem_pred, actual)
        else:
            sem_pred = False

        combined.record(pair.category, syn_pred or sem_pred, actual)

        # Precedence is about co-firing-without-ordering, reported separately and
        # kept OUT of precision/recall: same action class + same modality co-fire.
        if (
            ra.trigger.action_class == rb.trigger.action_class
            and ra.directive.modality == rb.directive.modality
        ):
            precedence_ambiguities += 1

    return BenchmarkReport(
        syntactic=syntactic,
        semantic=semantic_pass,
        combined=combined,
        n_pairs=len(pairs),
        semantic_enabled=semantic,
        sim_threshold=sim_threshold,
        precedence_ambiguities=precedence_ambiguities,
    )
