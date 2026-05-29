from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rcg.cli import app

runner = CliRunner()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = str(PROJECT_ROOT / "examples" / "gemini_incident")


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    yield


def test_explain_exits_zero_and_prints_verdict() -> None:
    result = runner.invoke(
        app,
        ["explain", "deploy to production", EXAMPLE, "--provider", "mock"],
    )
    assert result.exit_code == 0
    assert "Verdict:" in result.output
    assert "deploy.production" in result.output


def test_explain_strict_exits_one_on_conflict() -> None:
    result = runner.invoke(
        app,
        ["explain", "deploy to production", EXAMPLE, "--provider", "mock", "--strict"],
    )
    assert result.exit_code == 1


def test_explain_no_firing_exits_zero_even_strict() -> None:
    result = runner.invoke(
        app,
        ["explain", "water the office plants", EXAMPLE, "--provider", "mock", "--strict"],
    )
    assert result.exit_code == 0
    assert "no rules fire" in result.output
