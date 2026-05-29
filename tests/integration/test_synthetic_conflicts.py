from pathlib import Path

from typer.testing import CliRunner

from rcg.cli import app
from rcg.parsers.discovery import discover

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "examples" / "synthetic_conflicts"


def test_discovers_all_three_formats() -> None:
    rules = discover(CORPUS)
    formats = {r.source.format for r in rules}
    assert {"cursorrules", "mdc", "yaml"} <= formats


def test_check_reports_a_conflict() -> None:
    # `rcg check` exits non-zero when any (non-baselined) finding is reported.
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["check", str(CORPUS), "--provider", "mock", "--no-graph"],
    )
    assert result.exit_code != 0, result.output
