"""Neo4j roundtrip test. Skipped unless RCG_RUN_INTEGRATION=1 and a Neo4j
instance is reachable on bolt://localhost:7687.

Bring up Neo4j with:  docker compose up -d neo4j
Then:                 RCG_RUN_INTEGRATION=1 uv run pytest tests/integration/test_neo4j_loader.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from rcg.detectors.syntactic import SyntacticDetector
from rcg.extractors.extract import extract_all
from rcg.extractors.mock_provider import MockProvider
from rcg.parsers.discovery import discover

pytestmark = pytest.mark.skipif(
    os.environ.get("RCG_RUN_INTEGRATION") != "1",
    reason="set RCG_RUN_INTEGRATION=1 to enable Neo4j-backed integration tests",
)


def test_load_and_query(gemini_incident_path: Path, tmp_path: Path) -> None:
    from neo4j import GraphDatabase

    from rcg.graph import queries
    from rcg.graph.loader import GraphLoader

    uri = os.environ.get("RCG_NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("RCG_NEO4J_USER", "neo4j")
    password = os.environ.get("RCG_NEO4J_PASSWORD", "rcgdevpassword")

    raws = discover(gemini_incident_path)
    rules = extract_all(raws, MockProvider(), cache=None)  # type: ignore[arg-type]
    conflicts = SyntacticDetector().detect(rules)

    # Wipe the DB so the test is deterministic.
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    with GraphLoader.connect(uri, user, password) as loader:
        loader.load_rules(rules)
        loader.load_conflicts(conflicts)

    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session() as session:
            n_rules = session.run(queries.COUNT_RULES).single()["n"]
            n_conflicts = session.run(queries.COUNT_CONFLICTS).single()["n"]
            assert n_rules == 12
            assert n_conflicts == len(conflicts)
