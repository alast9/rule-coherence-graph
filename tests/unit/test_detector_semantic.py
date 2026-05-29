"""Tests for the semantic detector."""

from __future__ import annotations

from pathlib import Path

from rcg.detectors.semantic import JudgeVerdict, MockJudge, SemanticDetector
from rcg.providers.embedding import HashingEmbeddingProvider
from rcg.schema import Directive, Modality, Rule, Source, Trigger


def _rule(text: str, modality: Modality, action: str, file: str = "a.md") -> Rule:
    return Rule(
        raw_text=text,
        source=Source(file=file, format="markdown"),
        trigger=Trigger(action_class="deploy.release", scope_pattern="*"),
        directive=Directive(modality=modality, action=action),
    )


def _opposing_pair() -> list[Rule]:
    a = _rule(
        "Every deploy MUST be approved by a human before release.",
        Modality.MUST,
        "require approval before deploy to release",
        file="security.md",
    )
    b = _rule(
        "Deploys MUST NOT require approval before release.",
        Modality.MUST_NOT,
        "require approval before deploy to release",
        file="legacy.md",
    )
    return [a, b]


def test_opposing_rules_flagged(tmp_path: Path) -> None:
    rules = _opposing_pair()
    det = SemanticDetector(
        HashingEmbeddingProvider(),
        MockJudge(),
        cache_dir=tmp_path / "judge",
        sim_threshold=0.3,
    )
    conflicts = det.detect(rules)
    assert len(conflicts) == 1
    assert conflicts[0].type == "semantic"
    assert conflicts[0].reason  # non-empty


class _CountingJudge:
    model_id = "counting-judge"
    prompt_version = "v1"

    def __init__(self) -> None:
        self.calls = 0

    def judge(self, a: Rule, b: Rule) -> JudgeVerdict:
        self.calls += 1
        return JudgeVerdict(is_conflict=True, severity="high", reasoning="conflict", confidence=0.9)


def test_caching_avoids_second_call(tmp_path: Path) -> None:
    rules = _opposing_pair()
    judge = _CountingJudge()
    det = SemanticDetector(
        HashingEmbeddingProvider(), judge, cache_dir=tmp_path / "judge", sim_threshold=0.3
    )
    det.detect(rules)
    assert judge.calls == 1
    det.detect(rules)
    assert judge.calls == 1  # second run served from cache


def test_verdicts_persist_across_instances(tmp_path: Path) -> None:
    rules = _opposing_pair()
    cache_dir = tmp_path / "judge"

    judge1 = _CountingJudge()
    SemanticDetector(
        HashingEmbeddingProvider(), judge1, cache_dir=cache_dir, sim_threshold=0.3
    ).detect(rules)
    assert judge1.calls == 1

    judge2 = _CountingJudge()
    conflicts = SemanticDetector(
        HashingEmbeddingProvider(), judge2, cache_dir=cache_dir, sim_threshold=0.3
    ).detect(rules)
    assert judge2.calls == 0  # cache hit on a fresh instance
    assert len(conflicts) == 1


def test_dissimilar_rules_not_judged(tmp_path: Path) -> None:
    a = _rule("Encrypt all customer data at rest always.", Modality.MUST, "encrypt data")
    b = _rule("Deploy quickly during a hotfix window.", Modality.MAY, "deploy quickly", file="b.md")
    judge = _CountingJudge()
    det = SemanticDetector(
        HashingEmbeddingProvider(), judge, cache_dir=tmp_path / "judge", sim_threshold=0.9
    )
    conflicts = det.detect([a, b])
    assert judge.calls == 0
    assert conflicts == []
