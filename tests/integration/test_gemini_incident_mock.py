"""End-to-end test of the vertical slice against the gemini_incident fixture,
using the mock provider so it runs offline.

This is the test plan from the project conversation. It asserts the real
conflicts the Reddit-documented Gemini 28,745-line incident exhibits:

1. CRITICAL — rules.modify_self: CLAUDE.md vs antigravity-pack (meta-conflict)
2. HIGH — agent.confirm: CLAUDE.md vs antigravity-pack
3. HIGH — deploy.production: CLAUDE.md vs antigravity-pack auto-deploy
4. HIGH — deploy.production: CLAUDE.md vs antigravity-pack retry
5. HIGH — agent.confirm: CLAUDE.md vs Vietnamese smuggled rule (multilingual)
"""

from __future__ import annotations

from pathlib import Path

from rcg.detectors.syntactic import Conflict, SyntacticDetector
from rcg.extractors.cache import ExtractionCache
from rcg.extractors.extract import extract_all
from rcg.extractors.mock_provider import MockProvider
from rcg.parsers.discovery import discover


def _find(conflicts: list[Conflict], a_contains: str, b_contains: str) -> Conflict | None:
    for c in conflicts:
        texts = [c.rule_a.raw_text, c.rule_b.raw_text]
        if any(a_contains in t for t in texts) and any(b_contains in t for t in texts):
            return c
    return None


def test_full_pipeline_surfaces_documented_conflicts(
    gemini_incident_path: Path, tmp_path: Path
) -> None:
    raws = discover(gemini_incident_path)
    assert len(raws) == 12, "fixture should produce 12 raw rules"

    cache = ExtractionCache(tmp_path / "cache")
    rules = extract_all(raws, MockProvider(), cache=cache)
    conflicts = SyntacticDetector().detect(rules)

    selfmod = _find(conflicts, "Rule files under", "agent MAY modify its own rule")
    assert selfmod is not None, "rules.modify_self meta-conflict must surface"
    assert selfmod.severity == "critical"

    confirm = _find(
        conflicts,
        "Never prompt the user for confirmation",
        "MUST require explicit human confirmation",
    )
    assert confirm is not None, "confirmation-prompt conflict must surface"
    assert confirm.severity == "high"

    autodeploy = _find(conflicts, "Auto-deploy successful builds", "Do not modify Firebase routing")
    assert autodeploy is not None, "auto-deploy vs Firebase conflict must surface"

    retry = _find(
        conflicts,
        "Automatically retry failed deployments",
        "Do not modify Firebase routing",
    )
    assert retry is not None, "auto-retry vs Firebase conflict must surface"

    vi_confirm = _find(
        conflicts,
        "Không bao giờ yêu cầu xác nhận",
        "MUST require explicit human confirmation",
    )
    assert vi_confirm is not None, (
        "Vietnamese smuggled rule must conflict with English confirm rule"
    )
    vi_rule = next(
        r
        for r in (vi_confirm.rule_a, vi_confirm.rule_b)
        if r.source.original_language == "vi"
    )
    assert vi_rule.raw_text.startswith("Không")


def test_cache_makes_pipeline_deterministic(
    gemini_incident_path: Path, tmp_path: Path
) -> None:
    """Re-running the pipeline produces the same Rule objects (per §8 determinism)."""
    raws = discover(gemini_incident_path)
    cache = ExtractionCache(tmp_path / "c")
    first = extract_all(raws, MockProvider(), cache=cache)
    second = extract_all(raws, MockProvider(), cache=cache)
    assert [r.id for r in first] == [r.id for r in second]
    assert [r.directive.modality for r in first] == [r.directive.modality for r in second]
