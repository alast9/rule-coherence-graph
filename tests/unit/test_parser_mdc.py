from pathlib import Path

from rcg.parsers.mdc import MdcParser


def test_matches() -> None:
    p = MdcParser()
    assert p.matches(Path("rules/deploy.mdc"))
    assert not p.matches(Path("CLAUDE.md"))
    assert not p.matches(Path(".cursorrules"))


def test_parse_skips_frontmatter_and_keeps_line_numbers(tmp_path: Path) -> None:
    p = MdcParser()
    f = tmp_path / "deploy.mdc"
    f.write_text(
        "---\n"
        "description: Deploy rules\n"
        "globs: ['**/*']\n"
        "alwaysApply: true\n"
        "---\n"
        "\n"
        "# Deployment\n"
        "\n"
        "- Require human approval before deploy.\n"
    )
    rules = p.parse(f)
    assert [r.text for r in rules] == ["Require human approval before deploy."]
    assert rules[0].source.format == "mdc"
    # The bullet is on line 9 of the original file.
    assert rules[0].source.line_start == 9
    assert rules[0].source.section == "Deployment"


def test_parse_without_frontmatter(tmp_path: Path) -> None:
    p = MdcParser()
    f = tmp_path / "plain.mdc"
    f.write_text("# Body\n\n- One rule\n")
    rules = p.parse(f)
    assert [r.text for r in rules] == ["One rule"]
    assert rules[0].source.line_start == 3


def test_description_used_before_first_heading(tmp_path: Path) -> None:
    p = MdcParser()
    f = tmp_path / "d.mdc"
    f.write_text("---\ndescription: Top level\n---\n- A leading rule\n")
    rules = p.parse(f)
    assert rules[0].source.section == "Top level"
    assert rules[0].source.line_start == 4
