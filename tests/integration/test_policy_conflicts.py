from pathlib import Path

from rcg.detectors.syntactic import SyntacticDetector
from rcg.extractors.mock_provider import MockProvider
from rcg.parsers.discovery import discover

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "policy_conflicts"


def test_policy_corpus_discovers_all_formats() -> None:
    raw = discover(EXAMPLES)
    formats = {r.source.format for r in raw}
    assert "opa_rego" in formats
    assert "cedar" in formats
    assert "markdown" in formats


def test_policy_corpus_yields_cross_format_conflict() -> None:
    raw = discover(EXAMPLES)
    rules = [MockProvider().extract(r) for r in raw]
    conflicts = SyntacticDetector().detect(rules)

    # The whole point of the feature: a policy-as-code rule (rego/cedar) must
    # conflict with the natural-language markdown rule.
    cross = [
        c
        for c in conflicts
        if c.rule_a.source.format != c.rule_b.source.format
        and {c.rule_a.source.format, c.rule_b.source.format} & {"opa_rego", "cedar"}
        and "markdown" in {c.rule_a.source.format, c.rule_b.source.format}
    ]
    assert cross, "expected a policy-vs-prose cross-format syntactic conflict"
