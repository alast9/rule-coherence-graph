import pytest
from pydantic import ValidationError

from rcg.schema import OPPOSING_MODALITY, Directive, Modality, Rule, Source, Trigger


def _rule(text: str = "ban prompts", file: str = "CLAUDE.md") -> Rule:
    return Rule(
        raw_text=text,
        source=Source(file=file, format="markdown"),
        trigger=Trigger(action_class="agent.execute_action"),
        directive=Directive(modality=Modality.MUST_NOT, action="prompt for confirmation"),
    )


def test_id_is_deterministic():
    a = _rule()
    b = _rule()
    assert a.id == b.id


def test_id_changes_when_text_changes():
    assert _rule(text="ban prompts").id != _rule(text="ban prompts!").id


def test_id_changes_when_source_file_changes():
    """Same rule text in two files should be two distinct governance instances."""
    assert _rule(file="CLAUDE.md").id != _rule(file=".cursorrules").id


def test_confidence_bounds():
    with pytest.raises(ValidationError):
        Rule(
            raw_text="x",
            source=Source(file="a", format="markdown"),
            trigger=Trigger(action_class="a"),
            directive=Directive(modality=Modality.MUST, action="x"),
            confidence=1.5,
        )


def test_opposing_modality_table():
    assert OPPOSING_MODALITY[Modality.MUST] is Modality.MUST_NOT
    assert OPPOSING_MODALITY[Modality.SHOULD_NOT] is Modality.SHOULD
    assert Modality.MAY not in OPPOSING_MODALITY


def test_original_language_defaults_to_none():
    """English rules don't need to declare a language; only non-English ones do."""
    r = _rule()
    assert r.source.original_language is None
