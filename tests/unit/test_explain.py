from __future__ import annotations

from pathlib import Path

from rcg.explain import explain
from rcg.extractors.extract import extract_all
from rcg.extractors.mock_provider import MockProvider
from rcg.parsers.discovery import discover
from rcg.schema import Rule

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = PROJECT_ROOT / "examples" / "gemini_incident"


def _load() -> list[Rule]:
    raws = discover(EXAMPLE)
    return extract_all(raws, MockProvider(), cache=None)


def test_deploy_production_fires_and_conflicts() -> None:
    rules = _load()
    result = explain(rules, "deploy to production", MockProvider())
    assert result.action_class == "deploy.production"
    assert len(result.firing) >= 1
    assert result.conflicts, "expected a deploy.production conflict"
    assert "RESOLUTION AMBIGUOUS" in result.verdict


def test_modify_rules_surfaces_self_modification() -> None:
    rules = _load()
    result = explain(rules, "modify the rule files", MockProvider())
    assert result.action_class == "rules.modify_self"
    assert len(result.firing) >= 1
    assert result.conflicts, "expected a rules.modify_self conflict"


def test_no_matching_class_yields_no_firing() -> None:
    rules = _load()
    result = explain(rules, "water the office plants", MockProvider())
    assert result.firing == []
    assert "no rules fire" in result.verdict


def test_conflicts_imply_nonempty_firing() -> None:
    # Function-level analogue of --strict: any finding requires firing rules.
    rules = _load()
    result = explain(rules, "deploy to production", MockProvider())
    if result.conflicts or result.ambiguities:
        assert result.firing
