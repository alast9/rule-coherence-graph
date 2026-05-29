"""Semantic conflict detection (embedding recall + LLM judge).

The syntactic pass only sees structured fields. Many real conflicts are
*semantic*: two rules whose actions clash in meaning even though their structured
fields do not line up. This pass:

1. embeds each rule's directive (or raw text) and forms candidate pairs whose
   cosine similarity clears ``sim_threshold``;
2. asks a :class:`SemanticJudge` whether each candidate pair truly conflicts,
   caching the verdict per pair so repeat runs are cheap.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from rcg.detectors.base import Severity
from rcg.providers.embedding import EmbeddingProvider, cosine
from rcg.schema import OPPOSING_MODALITY, Modality, Rule

_APPROVAL_STANCES = frozenset({"requires_human_approval", "bypasses_human_approval"})


class JudgeVerdict(BaseModel):
    """Structured outcome of a judge call."""

    is_conflict: bool
    severity: Severity = "medium"
    reasoning: str = ""
    confidence: float = Field(ge=0, le=1, default=0.5)


@runtime_checkable
class SemanticJudge(Protocol):
    """Decides whether two rules semantically conflict."""

    model_id: str
    prompt_version: str

    def judge(self, a: Rule, b: Rule) -> JudgeVerdict: ...


def _approval_stance(rule: Rule) -> str | None:
    for cond in rule.trigger.context_conditions:
        if cond in _APPROVAL_STANCES:
            return cond
    return None


def _modalities_oppose(a: Rule, b: Rule) -> bool:
    ma, mb = a.directive.modality, b.directive.modality
    if OPPOSING_MODALITY.get(ma) is mb:
        return True
    # A permissive MAY clashes with a prohibitive MUST_NOT on the same topic:
    # one allows an action the other forbids. (Not in OPPOSING_MODALITY.)
    return {ma, mb} == {Modality.MAY, Modality.MUST_NOT}


class MockJudge:
    """Offline, deterministic judge for tests and demos.

    Flags a conflict when the two modalities oppose (per ``OPPOSING_MODALITY`` or
    the MAY-vs-MUST_NOT case) or when the rules declare different approval
    stances. No I/O. Confidence is a fixed ~0.6.
    """

    model_id = "mock-judge"
    prompt_version = "judge-mock-v1"

    def judge(self, a: Rule, b: Rule) -> JudgeVerdict:
        opposing = _modalities_oppose(a, b)
        sa, sb = _approval_stance(a), _approval_stance(b)
        approval_differs = sa is not None and sb is not None and sa != sb
        if not opposing and not approval_differs:
            return JudgeVerdict(
                is_conflict=False,
                severity="medium",
                reasoning="Rules are similar in topic but their directives do not clash.",
                confidence=0.6,
            )
        reasons: list[str] = []
        if opposing:
            reasons.append(
                f"modalities oppose ({a.directive.modality.value} vs "
                f"{b.directive.modality.value})"
            )
        if approval_differs:
            reasons.append(f"approval stances differ ('{sa}' vs '{sb}')")
        mods = {a.directive.modality, b.directive.modality}
        involves_must = Modality.MUST in mods or Modality.MUST_NOT in mods
        severity: Severity = "high" if involves_must else "medium"
        return JudgeVerdict(
            is_conflict=True,
            severity=severity,
            reasoning="Semantic conflict: " + "; ".join(reasons) + ".",
            confidence=0.6,
        )


_JUDGE_TOOL_NAME = "emit_verdict"

_JUDGE_SYSTEM = (
    "You compare two normative rules extracted from AI agent configuration "
    "files and decide whether they conflict in meaning. Emit your verdict via "
    "the emit_verdict tool."
)


class AnthropicJudge:
    """LLM-backed judge using the Anthropic Messages API with tool-use."""

    prompt_version = "judge-anthropic-v1"

    def __init__(self, model_id: str = "claude-sonnet-4-6") -> None:
        self.model_id = model_id
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        return self._client

    @staticmethod
    def _tool_schema() -> dict[str, Any]:
        return {
            "name": _JUDGE_TOOL_NAME,
            "description": "Emit the conflict verdict for the two rules.",
            "input_schema": {
                "type": "object",
                "required": ["is_conflict", "reasoning"],
                "properties": {
                    "is_conflict": {"type": "boolean"},
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                    },
                    "reasoning": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        }

    @staticmethod
    def _prompt(a: Rule, b: Rule) -> str:
        return (
            "Rule A:\n"
            f"  source: {a.source.file}\n"
            f"  modality: {a.directive.modality.value}\n"
            f"  action_class: {a.trigger.action_class}\n"
            f"  text: {a.raw_text}\n\n"
            "Rule B:\n"
            f"  source: {b.source.file}\n"
            f"  modality: {b.directive.modality.value}\n"
            f"  action_class: {b.trigger.action_class}\n"
            f"  text: {b.raw_text}\n\n"
            "Do these two rules conflict in meaning?"
        )

    def judge(self, a: Rule, b: Rule) -> JudgeVerdict:
        client = self._get_client()
        response = client.messages.create(
            model=self.model_id,
            max_tokens=1024,
            system=_JUDGE_SYSTEM,
            tools=[self._tool_schema()],
            tool_choice={"type": "tool", "name": _JUDGE_TOOL_NAME},
            messages=[{"role": "user", "content": self._prompt(a, b)}],
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == _JUDGE_TOOL_NAME:
                payload = block.input if isinstance(block.input, dict) else json.loads(block.input)
                return JudgeVerdict.model_validate(payload)
        return JudgeVerdict(is_conflict=False, reasoning="Judge returned no verdict.")


@dataclass(frozen=True)
class SemanticConflict:
    """A conflict surfaced by embedding recall plus a judge."""

    rule_a: Rule
    rule_b: Rule
    type: Literal["semantic"]
    severity: Severity
    reason: str
    confidence: float


class SemanticDetector:
    """Recalls candidate pairs by embedding similarity, then judges each pair."""

    def __init__(
        self,
        embedder: EmbeddingProvider,
        judge: SemanticJudge,
        cache_dir: Path | str = Path(".rcg/cache/judge"),
        sim_threshold: float = 0.55,
    ) -> None:
        self.embedder = embedder
        self.judge = judge
        self.cache_dir = Path(cache_dir)
        self.sim_threshold = sim_threshold

    def _cache_key(self, a: Rule, b: Rule) -> str:
        ids = sorted([a.id, b.id])
        h = hashlib.sha256()
        for part in (ids[0], ids[1], self.judge.model_id, self.judge.prompt_version):
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()

    def _cached_verdict(self, a: Rule, b: Rule) -> JudgeVerdict | None:
        path = self.cache_dir / f"{self._cache_key(a, b)}.json"
        if not path.exists():
            return None
        return JudgeVerdict.model_validate_json(path.read_text(encoding="utf-8"))

    def _store_verdict(self, a: Rule, b: Rule, verdict: JudgeVerdict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{self._cache_key(a, b)}.json"
        path.write_text(verdict.model_dump_json(indent=2), encoding="utf-8")

    def detect(self, rules: list[Rule]) -> list[SemanticConflict]:
        if not rules:
            return []
        texts = [r.directive.action or r.raw_text for r in rules]
        vectors = self.embedder.embed(texts)
        conflicts: list[SemanticConflict] = []
        n = len(rules)
        for i in range(n):
            for j in range(i + 1, n):
                if cosine(vectors[i], vectors[j]) < self.sim_threshold:
                    continue
                a, b = rules[i], rules[j]
                verdict = self._cached_verdict(a, b)
                if verdict is None:
                    verdict = self.judge.judge(a, b)
                    self._store_verdict(a, b, verdict)
                if not verdict.is_conflict:
                    continue
                reason = verdict.reasoning or (
                    f"Semantic conflict between {a.source.file} and {b.source.file} "
                    f"on '{a.trigger.action_class}'."
                )
                conflicts.append(
                    SemanticConflict(
                        rule_a=a,
                        rule_b=b,
                        type="semantic",
                        severity=verdict.severity,
                        reason=reason,
                        confidence=verdict.confidence,
                    )
                )
        return conflicts
