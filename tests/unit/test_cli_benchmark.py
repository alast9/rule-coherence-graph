"""Tests for the `rcg benchmark` CLI command."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from rcg.cli import app

runner = CliRunner()

DATASET = Path(__file__).resolve().parents[2] / "benchmarks" / "dataset.jsonl"


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_benchmark_no_semantic_prints_table() -> None:
    result = runner.invoke(app, ["benchmark", str(DATASET), "--no-semantic"])
    assert result.exit_code == 0
    assert "precision" in result.stdout
    assert "recall" in result.stdout
    assert "syntactic" in result.stdout


def test_benchmark_writes_out_file(tmp_path: Path) -> None:
    out = tmp_path / "results.md"
    result = runner.invoke(
        app,
        ["benchmark", str(DATASET), "--no-semantic", "--out", str(out)],
    )
    assert result.exit_code == 0
    text = out.read_text(encoding="utf-8")
    assert "precision" in text
    assert "recall" in text


def test_benchmark_missing_dataset_errors(tmp_path: Path) -> None:
    missing = tmp_path / "nope.jsonl"
    result = runner.invoke(app, ["benchmark", str(missing), "--no-semantic"])
    assert result.exit_code != 0
