"""CLI tests for the score command, baseline update, and suppression."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rcg.cli import app

runner = CliRunner()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = PROJECT_ROOT / "examples" / "gemini_incident"


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate each test: no leaked API key, and cwd-relative artifacts
    (`.rcg/cache`, the default `rcg-baseline.json`) land in a throwaway dir."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    yield


def test_score_command_outputs_float_and_exits_zero() -> None:
    result = runner.invoke(app, ["score", str(EXAMPLE), "--provider", "mock", "--no-graph"])
    assert result.exit_code == 0
    assert "Coherence score:" in result.output
    match = re.search(r"Coherence score:\s*([0-9.]+)", result.output)
    assert match is not None
    value = float(match.group(1))
    assert 0.0 <= value <= 1.0


def test_update_baseline_writes_file_and_exits_zero(tmp_path: Path) -> None:
    baseline = tmp_path / "rcg-baseline.json"
    result = runner.invoke(
        app,
        [
            "check",
            str(EXAMPLE),
            "--provider",
            "mock",
            "--no-graph",
            "--baseline",
            str(baseline),
            "--update-baseline",
        ],
    )
    assert result.exit_code == 0
    assert baseline.exists()


def test_check_with_baseline_suppresses(tmp_path: Path) -> None:
    baseline = tmp_path / "rcg-baseline.json"
    write = runner.invoke(
        app,
        [
            "check",
            str(EXAMPLE),
            "--provider",
            "mock",
            "--no-graph",
            "--baseline",
            str(baseline),
            "--update-baseline",
        ],
    )
    assert write.exit_code == 0

    result = runner.invoke(
        app,
        [
            "check",
            str(EXAMPLE),
            "--provider",
            "mock",
            "--no-graph",
            "--baseline",
            str(baseline),
        ],
    )
    assert result.exit_code == 0
    assert "Suppressed by baseline" in result.output
    assert "No conflicts detected" in result.output


def test_check_semantic_runs_and_reports() -> None:
    # The corpus has syntactic conflicts, so check exits non-zero. The semantic
    # pass runs without error; on this corpus the lexical HashingEmbeddingProvider
    # does not recall the (lexically dissimilar) opposing pairs, so no semantic
    # conflicts surface -- that is the documented stand-in limitation.
    result = runner.invoke(
        app,
        ["check", str(EXAMPLE), "--provider", "mock", "--no-graph", "--semantic"],
    )
    assert result.exit_code == 1
    assert "RCG report" in result.output
    assert "Coherence score:" in result.output
