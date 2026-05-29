from pathlib import Path

from rcg.parsers.opa_rego import OpaRegoParser


def test_matches_positive() -> None:
    p = OpaRegoParser()
    assert p.matches(Path("deploy.rego"))
    assert p.matches(Path("policy/authz.rego"))


def test_matches_negative() -> None:
    p = OpaRegoParser()
    assert not p.matches(Path("policy.cedar"))
    assert not p.matches(Path("rules.yaml"))
    assert not p.matches(Path("CLAUDE.md"))


def test_parse_multi_rule(tmp_path: Path) -> None:
    p = OpaRegoParser()
    f = tmp_path / "authz.rego"
    f.write_text(
        "package authz\n"
        "\n"
        "import rego.v1\n"
        "\n"
        "# Deletes are denied in production.\n"
        "deny contains msg if {\n"
        '    input.action == "delete"\n'
        '    msg := "no delete"\n'
        "}\n"
        "\n"
        "allow if {\n"
        '    input.action == "read"\n'
        "}\n"
    )
    rules = p.parse(f)

    assert len(rules) == 2
    # First unit keeps its leading comment.
    assert rules[0].text.startswith("# Deletes are denied in production.")
    assert 'input.action == "delete"' in rules[0].text
    assert rules[0].text.rstrip().endswith("}")
    assert rules[0].source.format == "opa_rego"
    assert rules[0].source.line_start == 5  # the comment line
    assert rules[0].source.line_end == 9  # the closing brace
    # Second unit has no leading comment.
    assert rules[1].text.startswith("allow if {")
    assert rules[1].source.line_start == 11
    assert rules[1].source.line_end == 13


def test_parse_single_line_default(tmp_path: Path) -> None:
    p = OpaRegoParser()
    f = tmp_path / "default.rego"
    f.write_text(
        "package authz\n"
        "\n"
        "# Closed by default.\n"
        "default allow := false\n"
    )
    rules = p.parse(f)
    assert len(rules) == 1
    assert rules[0].text == "# Closed by default.\ndefault allow := false"
    assert rules[0].source.line_start == 3
    assert rules[0].source.line_end == 4


def test_parse_only_package_and_imports_returns_empty(tmp_path: Path) -> None:
    p = OpaRegoParser()
    f = tmp_path / "empty.rego"
    f.write_text("package authz\n\nimport rego.v1\nimport data.lib\n")
    assert p.parse(f) == []


def test_parse_empty_file_returns_empty(tmp_path: Path) -> None:
    p = OpaRegoParser()
    f = tmp_path / "blank.rego"
    f.write_text("")
    assert p.parse(f) == []
