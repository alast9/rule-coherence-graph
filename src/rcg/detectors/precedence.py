"""Precedence / priority ambiguity detection.

Rules can declare precedence over other rules (``priority.declared_precedence_over``).
When two rules from *different files* could fire on the same action and overlapping
scope, but neither is declared to supersede the other, their relative ordering is
ambiguous — an agent has no principled way to choose. This pass flags such pairs.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Literal

from rcg.detectors.base import Severity, scopes_overlap
from rcg.schema import Rule


@dataclass(frozen=True)
class PrecedenceAmbiguity:
    """Two co-firing rules with no declared ordering between them."""

    rule_a: Rule
    rule_b: Rule
    type: Literal["precedence"]
    severity: Severity
    reason: str


class PrecedenceDetector:
    """Flags cross-file co-firing rule pairs whose ordering is unresolved."""

    def detect(
        self,
        rules: list[Rule],
        exclude: set[frozenset[str]] | None = None,
    ) -> list[PrecedenceAmbiguity]:
        exclude = exclude or set()
        graph = self._build_graph(rules)
        ambiguities: list[PrecedenceAmbiguity] = []
        n = len(rules)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = rules[i], rules[j]
                if a.source.file == b.source.file:
                    continue
                if frozenset({a.id, b.id}) in exclude:
                    continue
                if not self._co_fire(a, b):
                    continue
                if self._reachable(graph, a.id, b.id) or self._reachable(graph, b.id, a.id):
                    continue
                ambiguities.append(self._make(a, b))
        return ambiguities

    @staticmethod
    def _build_graph(rules: list[Rule]) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = {}
        for rule in rules:
            graph.setdefault(rule.id, set())
            for superseded in rule.priority.declared_precedence_over:
                graph[rule.id].add(superseded)
                graph.setdefault(superseded, set())
        return graph

    @staticmethod
    def _reachable(graph: dict[str, set[str]], src: str, dst: str) -> bool:
        """True if ``dst`` is reachable from ``src`` along declared-precedence edges."""
        if src == dst or src not in graph:
            return False
        seen: set[str] = {src}
        queue: deque[str] = deque([src])
        while queue:
            node = queue.popleft()
            for nxt in graph.get(node, set()):
                if nxt == dst:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return False

    @staticmethod
    def _co_fire(a: Rule, b: Rule) -> bool:
        return a.trigger.action_class == b.trigger.action_class and scopes_overlap(a, b)

    @staticmethod
    def _make(a: Rule, b: Rule) -> PrecedenceAmbiguity:
        action_class = a.trigger.action_class
        severity: Severity = "critical" if action_class.startswith("rules.") else "medium"
        reason = (
            f"Unresolved precedence on action class '{action_class}': "
            f"{a.source.file} and {b.source.file} both apply but neither declares "
            f"precedence over the other, so their ordering is ambiguous."
        )
        return PrecedenceAmbiguity(
            rule_a=a,
            rule_b=b,
            type="precedence",
            severity=severity,
            reason=reason,
        )
