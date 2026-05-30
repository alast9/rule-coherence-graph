"""Tests for the OpenAI-compatible extractor, judge, and the CLI/MCP factories.

All offline: a fake client mimics the openai response shape so neither the
``openai`` package nor a network connection is required. The provider only imports
``openai`` when it has to build a real client, which an injected fake avoids.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import typer

from rcg.detectors.semantic import JudgeVerdict, MockJudge, OpenAICompatibleJudge
from rcg.extractors.openai_provider import OpenAICompatibleProvider
from rcg.schema import Directive, Modality, RawRule, Rule, Source, Trigger


def _raw(text: str = "Never deploy to production without human approval.") -> RawRule:
    return RawRule(text=text, source=Source(file="CLAUDE.md", format="markdown", section="Deploy"))


def _rule() -> Rule:
    return Rule(
        raw_text="Never deploy without approval.",
        source=Source(file="a.md", format="markdown"),
        trigger=Trigger(action_class="deploy.production", scope_pattern="*"),
        directive=Directive(modality=Modality.MUST_NOT, action="deploy without approval"),
    )


def _valid_args() -> dict[str, Any]:
    return {
        "action_class": "deploy.production",
        "scope_pattern": "*",
        "modality": "MUST_NOT",
        "action": "deploy to production without human approval",
        "confidence": 0.9,
        "original_language": "en",
        "tags": ["security"],
        "approval_stance": "requires_human_approval",
    }


class _FakeToolCall:
    def __init__(self, arguments: Any) -> None:
        self.function = type("Fn", (), {"arguments": arguments})()


class _FakeMessage:
    def __init__(self, tool_calls: list[_FakeToolCall] | None) -> None:
        self.tool_calls = tool_calls


class _FakeResponse:
    def __init__(self, tool_calls: list[_FakeToolCall] | None) -> None:
        self.choices = [type("Choice", (), {"message": _FakeMessage(tool_calls)})()]


class _FakeCompletions:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.calls = 0

    def create(self, **kwargs: Any) -> _FakeResponse:
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.completions = _FakeCompletions(responses)
        self.chat = type("Chat", (), {"completions": self.completions})()


def _client_returning(*tool_call_args: Any) -> _FakeClient:
    responses = [
        _FakeResponse([_FakeToolCall(args)] if args is not None else None)
        for args in tool_call_args
    ]
    return _FakeClient(responses)


def test_extract_happy_path_json_string() -> None:
    client = _client_returning(json.dumps(_valid_args()))
    provider = OpenAICompatibleProvider(model_id="deepseek-chat", client=client)
    rule = provider.extract(_raw())
    assert rule.directive.modality == Modality.MUST_NOT
    assert rule.trigger.action_class == "deploy.production"
    assert rule.directive.action == "deploy to production without human approval"
    assert rule.trigger.context_conditions == ["requires_human_approval"]
    assert client.completions.calls == 1


def test_extract_accepts_arguments_as_dict() -> None:
    client = _client_returning(_valid_args())
    provider = OpenAICompatibleProvider(model_id="qwen-max", client=client)
    rule = provider.extract(_raw())
    assert rule.trigger.action_class == "deploy.production"
    assert "security" in rule.tags


def test_extract_retries_once_then_succeeds() -> None:
    # First response has no tool call; second returns valid arguments.
    client = _client_returning(None, json.dumps(_valid_args()))
    provider = OpenAICompatibleProvider(model_id="gpt-4o-mini", client=client)
    rule = provider.extract(_raw())
    assert rule.trigger.action_class == "deploy.production"
    assert client.completions.calls == 2


def test_extract_retries_on_missing_required_key() -> None:
    bad = _valid_args()
    del bad["modality"]  # required key missing -> first attempt rejected
    client = _client_returning(json.dumps(bad), json.dumps(_valid_args()))
    provider = OpenAICompatibleProvider(model_id="gpt-4o-mini", client=client)
    provider.extract(_raw())
    assert client.completions.calls == 2


def test_extract_hard_failure_raises_runtime_error() -> None:
    client = _client_returning(None, "not valid json")
    provider = OpenAICompatibleProvider(model_id="gpt-4o-mini", client=client)
    with pytest.raises(RuntimeError):
        provider.extract(_raw())
    assert client.completions.calls == 2


def test_judge_happy_path() -> None:
    args = {"is_conflict": True, "severity": "high", "reasoning": "they oppose", "confidence": 0.8}
    client = _client_returning(json.dumps(args))
    judge = OpenAICompatibleJudge(model_id="deepseek-chat", client=client)
    a = _rule()
    verdict = judge.judge(a, a)
    assert isinstance(verdict, JudgeVerdict)
    assert verdict.is_conflict
    assert verdict.severity == "high"


def test_judge_no_tool_call_falls_back() -> None:
    client = _client_returning(None)
    judge = OpenAICompatibleJudge(model_id="deepseek-chat", client=client)
    a = _rule()
    verdict = judge.judge(a, a)
    assert verdict.is_conflict is False
    assert verdict.reasoning == "Judge returned no verdict."


# --- factory tests (no live client; assert config only) ---------------------


def test_cli_factory_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.cli import _build_provider

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.delenv("RCG_LLM_MODEL", raising=False)
    monkeypatch.delenv("RCG_LLM_BASE_URL", raising=False)
    provider = _build_provider("deepseek")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model_id == "deepseek-chat"
    assert provider._base_url == "https://api.deepseek.com"


def test_cli_factory_qwen_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.cli import _build_provider

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qwen-test")
    monkeypatch.setenv("RCG_LLM_MODEL", "qwen-plus")
    provider = _build_provider("qwen")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model_id == "qwen-plus"
    assert provider._base_url == "https://dashscope.aliyun.com/compatible-mode/v1"


def test_cli_factory_openai_base_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.cli import _build_provider

    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setenv("RCG_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("RCG_LLM_MODEL", raising=False)
    provider = _build_provider("openai")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._base_url == "http://localhost:11434/v1"


def test_cli_factory_generic_key_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.cli import _build_provider

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("RCG_LLM_API_KEY", "sk-generic-test")
    provider = _build_provider("deepseek")
    assert isinstance(provider, OpenAICompatibleProvider)


def test_cli_factory_missing_key_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.cli import _build_provider

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("RCG_LLM_API_KEY", raising=False)
    with pytest.raises(typer.Exit):
        _build_provider("deepseek")


def test_cli_judge_uses_openai_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.cli import _build_judge

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    judge = _build_judge("deepseek")
    assert isinstance(judge, OpenAICompatibleJudge)


def test_cli_judge_falls_back_to_mock_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.cli import _build_judge

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("RCG_LLM_API_KEY", raising=False)
    assert isinstance(_build_judge("deepseek"), MockJudge)


def test_mcp_factory_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.mcp_server import _build_provider

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.delenv("RCG_LLM_MODEL", raising=False)
    provider = _build_provider("deepseek")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model_id == "deepseek-chat"


# --- bedrock factory tests --------------------------------------------------


def _clear_bedrock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "AWS_BEARER_TOKEN_BEDROCK",
        "RCG_LLM_API_KEY",
        "RCG_LLM_REGION",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "RCG_LLM_BASE_URL",
        "RCG_LLM_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_cli_factory_bedrock_region(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.cli import _build_provider

    _clear_bedrock_env(monkeypatch)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bedrock-key")
    monkeypatch.setenv("RCG_LLM_REGION", "us-west-2")
    provider = _build_provider("bedrock")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model_id == "openai.gpt-oss-120b-1:0"
    assert provider._base_url == "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1"


def test_cli_factory_bedrock_region_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.cli import _build_provider

    _clear_bedrock_env(monkeypatch)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bedrock-key")
    provider = _build_provider("bedrock")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._base_url == "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1"


def test_cli_factory_bedrock_base_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.cli import _build_provider

    _clear_bedrock_env(monkeypatch)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bedrock-key")
    monkeypatch.setenv("RCG_LLM_REGION", "us-west-2")
    monkeypatch.setenv("RCG_LLM_BASE_URL", "https://bedrock-mantle.us-west-2.api.aws/v1")
    provider = _build_provider("bedrock")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._base_url == "https://bedrock-mantle.us-west-2.api.aws/v1"


def test_cli_factory_bedrock_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.cli import _build_provider

    _clear_bedrock_env(monkeypatch)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bedrock-key")
    monkeypatch.setenv("RCG_LLM_MODEL", "openai.gpt-oss-20b-1:0")
    provider = _build_provider("bedrock")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model_id == "openai.gpt-oss-20b-1:0"


def test_cli_factory_bedrock_generic_key_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.cli import _build_provider

    _clear_bedrock_env(monkeypatch)
    monkeypatch.setenv("RCG_LLM_API_KEY", "generic-key")
    provider = _build_provider("bedrock")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._api_key == "generic-key"


def test_cli_factory_bedrock_missing_key_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.cli import _build_provider

    _clear_bedrock_env(monkeypatch)
    with pytest.raises(typer.Exit):
        _build_provider("bedrock")


def test_cli_judge_bedrock_uses_openai_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rcg.cli import _build_judge

    _clear_bedrock_env(monkeypatch)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bedrock-key")
    monkeypatch.setenv("RCG_LLM_REGION", "us-west-2")
    judge = _build_judge("bedrock")
    assert isinstance(judge, OpenAICompatibleJudge)
    assert judge._base_url == "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1"


def test_cli_judge_bedrock_falls_back_to_mock_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rcg.cli import _build_judge

    _clear_bedrock_env(monkeypatch)
    assert isinstance(_build_judge("bedrock"), MockJudge)


def test_mcp_factory_bedrock(monkeypatch: pytest.MonkeyPatch) -> None:
    from rcg.mcp_server import _build_provider

    _clear_bedrock_env(monkeypatch)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "bedrock-key")
    monkeypatch.setenv("RCG_LLM_REGION", "us-west-2")
    provider = _build_provider("bedrock")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model_id == "openai.gpt-oss-120b-1:0"
    assert provider._base_url == "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1"
