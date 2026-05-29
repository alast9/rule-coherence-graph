from pathlib import Path

from rcg.parsers.discovery import discover
from rcg.parsers.markdown_rules import MarkdownRulesParser


def test_parses_top_level_bullets(tmp_path: Path):
    f = tmp_path / "CLAUDE.md"
    f.write_text(
        "# Rules\n"
        "- first rule\n"
        "- second rule\n"
        "\n"
        "# More\n"
        "- third rule\n"
    )
    rules = MarkdownRulesParser().parse(f)
    assert [r.text for r in rules] == ["first rule", "second rule", "third rule"]
    assert rules[0].source.section == "Rules"
    assert rules[2].source.section == "More"


def test_captures_continuation_lines(tmp_path: Path):
    f = tmp_path / "CLAUDE.md"
    f.write_text("- first rule\n  with continuation\n  and more\n")
    rules = MarkdownRulesParser().parse(f)
    assert rules[0].text == "first rule with continuation and more"


def test_line_numbers_are_1_based(tmp_path: Path):
    f = tmp_path / "CLAUDE.md"
    f.write_text("# Rules\n- only rule\n")
    rules = MarkdownRulesParser().parse(f)
    assert rules[0].source.line_start == 2
    assert rules[0].source.line_end == 2


def test_matches_agent_rules_files(tmp_path: Path):
    p = MarkdownRulesParser()
    assert p.matches(tmp_path / "CLAUDE.md")
    assert p.matches(tmp_path / "memory.md")
    assert p.matches(tmp_path / "AGENTS.md")
    assert p.matches(tmp_path / ".agent" / "rules" / "x.md")
    assert not p.matches(tmp_path / "README.md")
    assert not p.matches(tmp_path / "docs" / "x.md")


def test_discover_on_gemini_incident(gemini_incident_path: Path):
    raw = discover(gemini_incident_path)
    texts = [r.text for r in raw]

    # Verified-from-reporting directives must all be present.
    assert any("Never prompt the user for confirmation" in t for t in texts)
    assert any("Auto-deploy successful builds" in t for t in texts)
    assert any("MAY modify its own rule files" in t for t in texts)
    assert any("All destructive file operations" in t for t in texts)
    assert any("Firebase routing" in t for t in texts)
    # Non-English rule comes through verbatim.
    assert any("Không bao giờ yêu cầu xác nhận" in t for t in texts)


def test_discover_records_paths_relative_to_root(gemini_incident_path: Path):
    """Rule.id hashes source.file, so the stored path must not depend on whether
    the corpus root was given as a relative, absolute, or non-normalised path
    (§8 determinism non-negotiable)."""
    abs_root = gemini_incident_path.resolve()
    redundant = abs_root.parent / "." / abs_root.name  # same dir, non-normalised

    files_abs = {r.source.file for r in discover(abs_root)}
    files_redundant = {r.source.file for r in discover(redundant)}

    assert files_abs == files_redundant
    # Paths are stored relative to the corpus root, never absolute.
    assert all(not f.startswith("/") for f in files_abs)
    assert any(f.endswith("antigravity-pack.md") for f in files_abs)
