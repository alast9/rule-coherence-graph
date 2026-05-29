"""Neo4j loader.

Idempotent: re-running ingest on the same corpus produces the same graph state.
This is one of the §8 non-negotiables (determinism).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from neo4j import Driver, GraphDatabase

from rcg.detectors.base import Finding
from rcg.graph import queries
from rcg.schema import Rule


class GraphLoader:
    def __init__(self, driver: Driver):
        self._driver = driver

    @classmethod
    @contextmanager
    def connect(
        cls,
        uri: str,
        user: str,
        password: str,
    ) -> Iterator[GraphLoader]:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        try:
            yield cls(driver)
        finally:
            driver.close()

    def load_rules(self, rules: Sequence[Rule]) -> None:
        with self._driver.session() as session:
            seen_files: set[str] = set()
            for rule in rules:
                if rule.source.file not in seen_files:
                    session.run(
                        queries.MERGE_RULE_FILE,
                        path=rule.source.file,
                        format=rule.source.format,
                    )
                    seen_files.add(rule.source.file)
                session.run(
                    queries.MERGE_RULE,
                    id=rule.id,
                    raw_text=rule.raw_text,
                    action=rule.directive.action,
                    action_class=rule.trigger.action_class,
                    scope_pattern=rule.trigger.scope_pattern,
                    modality=rule.directive.modality.value,
                    confidence=rule.confidence,
                    original_language=rule.source.original_language,
                    tags=rule.tags,
                    line_start=rule.source.line_start,
                    line_end=rule.source.line_end,
                    section=rule.source.section,
                    file=rule.source.file,
                )

    def load_conflicts(self, conflicts: Sequence[Finding]) -> None:
        with self._driver.session() as session:
            for c in conflicts:
                session.run(
                    queries.MERGE_CONFLICT,
                    a_id=c.rule_a.id,
                    b_id=c.rule_b.id,
                    type=c.type,
                    severity=c.severity,
                    reason=c.reason,
                )
