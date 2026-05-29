from pathlib import Path

from rcg.parsers.discovery import discover


def test_discover_mixed_formats(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("- md rule\n")
    (tmp_path / ".cursorrules").write_text("cursor rule\n")
    (tmp_path / "deploy.mdc").write_text("---\ndescription: D\n---\n- mdc rule\n")
    (tmp_path / "rules.yaml").write_text("- yaml rule\n")

    rules = discover(tmp_path)
    by_text = {r.text: r for r in rules}
    assert set(by_text) == {"md rule", "cursor rule", "mdc rule", "yaml rule"}

    assert by_text["md rule"].source.format == "markdown"
    assert by_text["md rule"].source.file == "CLAUDE.md"
    assert by_text["cursor rule"].source.format == "cursorrules"
    assert by_text["cursor rule"].source.file == ".cursorrules"
    assert by_text["mdc rule"].source.format == "mdc"
    assert by_text["mdc rule"].source.file == "deploy.mdc"
    assert by_text["yaml rule"].source.format == "yaml"
    assert by_text["yaml rule"].source.file == "rules.yaml"
