"""Syntactic conflict detector.

Pairs rules with matching action_class + overlapping scope + opposing modality.
Pure Python over an in-memory Rule list — no LLM, no Neo4j, no I/O. The graph
layer is responsible for persisting the resulting CONFLICTS_WITH edges.

Severity rules:
- `critical` if either rule's action_class starts with `rules.` — rules that
  govern the rule corpus itself (e.g. `rules.modify_self`) are the meta-failure
  mode reported most loudly in the Gemini incident.
- `high` for opposing MUST / MUST_NOT.
- `medium` for opposing SHOULD / SHOULD_NOT.
- `low` for one-sided MAY collisions (not currently emitted; reserved).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Literal

from rcg.detectors.base import scopes_overlap
from rcg.schema import OPPOSING_MODALITY, Modality, Rule

Severity = Literal["low", "medium", "high", "critical"]

# Canonical context-condition tokens describing a rule's human-in-the-loop stance.
APPROVAL_STANCES = frozenset({"requires_human_approval", "bypasses_human_approval"})


def _approval_stance(rule: Rule) -> str | None:
    for cond in rule.trigger.context_conditions:
        if cond in APPROVAL_STANCES:
            return cond
    return None


@dataclass(frozen=True)
class Conflict:
    rule_a: Rule
    rule_b: Rule
    type: Literal["syntactic"]
    severity: Severity
    reason: str


class SyntacticDetector:
    def detect(self, rules: list[Rule]) -> list[Conflict]:
        conflicts: list[Conflict] = []
        for a, b in combinations(rules, 2):
            if not self._scopes_overlap(a, b):
                continue
            if not self._actions_match(a, b):
                continue
            if not self._modalities_oppose(a, b):
                continue
            conflicts.append(
                Conflict(
                    rule_a=a,
                    rule_b=b,
                    type="syntactic",
                    severity=self._severity(a, b),
                    reason=(
                        f"action_class={a.trigger.action_class!r}; "
                        f"modalities={a.directive.modality.value} vs {b.directive.modality.value}"
                    ),
                )
            )
        return conflicts

    @staticmethod
    def _actions_match(a: Rule, b: Rule) -> bool:
        return a.trigger.action_class == b.trigger.action_class

    @staticmethod
    def _scopes_overlap(a: Rule, b: Rule) -> bool:
        return scopes_overlap(a, b)

    @staticmethod
    def _modalities_oppose(a: Rule, b: Rule) -> bool:
        # For approval-gated rules the axis of conflict is whether human approval
        # is required vs bypassed, not the surface modality. "Do not deploy
        # without approval" (MUST_NOT) and "require approval before deploy" (MUST)
        # read as opposite modalities but encode the SAME policy, so comparing
        # modality there yields false positives. When both rules carry an approval
        # stance, compare the stance instead.
        sa, sb = _approval_stance(a), _approval_stance(b)
        if sa is not None and sb is not None:
            return sa != sb
        # Explicit permission vs prohibition is a conflict regardless of order.
        if {a.directive.modality, b.directive.modality} == {Modality.MAY, Modality.MUST_NOT}:
            return True
        opposite = OPPOSING_MODALITY.get(a.directive.modality)
        if opposite is None:
            return False
        return b.directive.modality is opposite

    @staticmethod
    def _severity(a: Rule, b: Rule) -> Severity:
        if a.trigger.action_class.startswith("rules.") or b.trigger.action_class.startswith(
            "rules."
        ):
            return "critical"
        modalities = {a.directive.modality, b.directive.modality}
        if Modality.MUST in modalities or Modality.MUST_NOT in modalities:
            return "high"
        return "medium"
