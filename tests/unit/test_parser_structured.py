from pathlib import Path

from rcg.parsers.structured import StructuredRulesParser


def test_matches_positive() -> None:
    p = StructuredRulesParser()
    assert p.matches(Path("rules.yaml"))
    assert p.matches(Path("my_rules.json"))
    assert p.matches(Path(".agent/policy.yaml"))
    assert p.matches(Path("rules/deploy.json"))


def test_matches_negative() -> None:
    p = StructuredRulesParser()
    # Arbitrary config must not be swallowed.
    assert not p.matches(Path("config.yaml"))
    assert not p.matches(Path("config.yml"))
    assert not p.matches(Path("package.json"))
    assert not p.matches(Path("data/settings.yml"))


def test_parse_list_of_strings(tmp_path: Path) -> None:
    p = StructuredRulesParser()
    f = tmp_path / "rules.yaml"
    f.write_text("- First rule\n- Second rule\n")
    rules = p.parse(f)
    assert [r.text for r in rules] == ["First rule", "Second rule"]
    assert rules[0].source.format == "yaml"


def test_parse_list_of_dicts(tmp_path: Path) -> None:
    p = StructuredRulesParser()
    f = tmp_path / "rules.json"
    f.write_text('[{"rule": "Do X"}, {"description": "Do Y"}, {"other": "skip"}]')
    rules = p.parse(f)
    assert [r.text for r in rules] == ["Do X", "Do Y"]
    assert rules[0].source.format == "json"


def test_parse_dict_with_rules_key(tmp_path: Path) -> None:
    p = StructuredRulesParser()
    f = tmp_path / "rules.yaml"
    f.write_text("rules:\n  - Alpha\n  - Beta\n")
    rules = p.parse(f)
    assert [r.text for r in rules] == ["Alpha", "Beta"]
    assert rules[0].source.section == "rules"


def test_parse_unrecognized_shape_returns_empty(tmp_path: Path) -> None:
    p = StructuredRulesParser()
    f = tmp_path / "rules.yaml"
    f.write_text("name: something\nvalue: 42\n")
    assert p.parse(f) == []


def test_parse_invalid_yaml_returns_empty(tmp_path: Path) -> None:
    p = StructuredRulesParser()
    f = tmp_path / "rules.yaml"
    f.write_text("key: : : broken\n  - [unbalanced\n")
    assert p.parse(f) == []
