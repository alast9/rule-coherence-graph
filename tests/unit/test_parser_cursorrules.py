from pathlib import Path

from rcg.parsers.cursorrules import CursorRulesParser


def test_matches_positive() -> None:
    p = CursorRulesParser()
    assert p.matches(Path(".cursorrules"))
    assert p.matches(Path("sub/.cursorrules"))


def test_matches_negative() -> None:
    p = CursorRulesParser()
    assert not p.matches(Path("cursorrules.txt"))
    assert not p.matches(Path("CLAUDE.md"))
    assert not p.matches(Path("rules.mdc"))


def test_parse_plain_lines(tmp_path: Path) -> None:
    p = CursorRulesParser()
    f = tmp_path / ".cursorrules"
    f.write_text(
        "# header comment\n"
        "Always write tests.\n"
        "\n"
        "Prefer composition over inheritance.\n"
    )
    rules = p.parse(f)
    assert [r.text for r in rules] == [
        "Always write tests.",
        "Prefer composition over inheritance.",
    ]
    assert rules[0].source.format == "cursorrules"
    assert rules[0].source.line_start == 2
    assert rules[1].source.line_start == 4


def test_parse_markdown_bullets(tmp_path: Path) -> None:
    p = CursorRulesParser()
    f = tmp_path / ".cursorrules"
    f.write_text("# Style\n\n- Use tabs\n- Avoid globals\n")
    rules = p.parse(f)
    assert [r.text for r in rules] == ["Use tabs", "Avoid globals"]
    assert rules[0].source.section == "Style"
    assert rules[0].source.line_start == 3
    assert rules[0].source.format == "cursorrules"
