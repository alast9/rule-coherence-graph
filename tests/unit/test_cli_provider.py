"""Tests for the CLI provider factory, especially the 'auto' default that makes
the offline demo work out of the box without an API key."""

import pytest
import typer

from rcg.cli import _build_provider
from rcg.extractors.anthropic_provider import AnthropicProvider
from rcg.extractors.mock_provider import MockProvider


def test_auto_falls_back_to_mock_without_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = _build_provider("auto")
    assert isinstance(provider, MockProvider)
    assert "ANTHROPIC_API_KEY not set" in capsys.readouterr().err


def test_auto_uses_anthropic_when_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    provider = _build_provider("auto")
    assert isinstance(provider, AnthropicProvider)


def test_explicit_anthropic_without_key_exits(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(typer.Exit):
        _build_provider("anthropic")


def test_unknown_provider_exits():
    with pytest.raises(typer.Exit):
        _build_provider("nope")
