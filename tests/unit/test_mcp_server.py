from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mcp")

from rcg import mcp_server  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = str(PROJECT_ROOT / "examples" / "gemini_incident")


def test_check_impl_shape_and_findings() -> None:
    result = mcp_server._check_impl(EXAMPLE, provider="mock")
    assert set(result) == {"n_rules", "score", "by_type", "findings"}
    assert result["n_rules"] > 0
    assert 0.0 <= result["score"] <= 1.0
    assert result["findings"], "gemini_incident should yield findings"
    f = result["findings"][0]
    assert set(f) == {"type", "severity", "reason", "rule_a", "rule_b"}
    assert set(f["rule_a"]) == {"text", "file", "modality", "action_class"}


def test_explain_impl_shape() -> None:
    result = mcp_server._explain_impl("deploy to production", EXAMPLE, provider="mock")
    assert result["action_class"] == "deploy.production"
    assert result["firing"]
    assert result["conflicts"]
    assert "verdict" in result
    assert set(result["firing"][0]) == {"text", "file", "modality", "action_class"}


def test_score_impl_shape() -> None:
    result = mcp_server._score_impl(EXAMPLE, provider="mock")
    assert set(result) == {"n_rules", "score", "weighted", "by_type"}
    assert 0.0 <= result["score"] <= 1.0


def test_tool_callables_work_directly() -> None:
    # The decorated tools should delegate to the impls and stay directly callable.
    assert mcp_server.check_corpus(EXAMPLE)["n_rules"] > 0
    assert mcp_server.explain_action("deploy to production", EXAMPLE)["firing"]
    assert 0.0 <= mcp_server.score_corpus_tool(EXAMPLE)["score"] <= 1.0
