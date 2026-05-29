from pathlib import Path

from rcg.parsers.cedar import CedarParser


def test_matches_positive() -> None:
    p = CedarParser()
    assert p.matches(Path("access.cedar"))
    assert p.matches(Path("policy/authz.cedar"))


def test_matches_negative() -> None:
    p = CedarParser()
    assert not p.matches(Path("deploy.rego"))
    assert not p.matches(Path("rules.yaml"))
    assert not p.matches(Path("CLAUDE.md"))


def test_parse_multi_policy(tmp_path: Path) -> None:
    p = CedarParser()
    f = tmp_path / "access.cedar"
    f.write_text(
        "// Deleting production resources is forbidden.\n"
        '@id("forbid-delete")\n'
        "forbid(\n"
        "    principal,\n"
        '    action == Action::"DeleteObject",\n'
        "    resource\n"
        ")\n"
        "when {\n"
        '    resource.environment == "production"\n'
        "};\n"
        "\n"
        "permit(principal, action, resource);\n"
    )
    rules = p.parse(f)

    assert len(rules) == 2
    # First policy keeps its leading // comment and @annotation line.
    assert rules[0].text.startswith("// Deleting production resources is forbidden.")
    assert '@id("forbid-delete")' in rules[0].text
    assert 'action == Action::"DeleteObject"' in rules[0].text
    assert rules[0].text.rstrip().endswith("};")
    assert rules[0].source.format == "cedar"
    assert rules[0].source.line_start == 1
    assert rules[0].source.line_end == 10
    # Second policy is a single line.
    assert rules[1].text == "permit(principal, action, resource);"
    assert rules[1].source.line_start == 12
    assert rules[1].source.line_end == 12


def test_parse_empty_file_returns_empty(tmp_path: Path) -> None:
    p = CedarParser()
    f = tmp_path / "blank.cedar"
    f.write_text("")
    assert p.parse(f) == []


def test_parse_comment_only_returns_empty(tmp_path: Path) -> None:
    p = CedarParser()
    f = tmp_path / "comments.cedar"
    f.write_text("// just a comment\n// another comment\n")
    assert p.parse(f) == []
