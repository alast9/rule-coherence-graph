"""OpenAI-compatible LLM extractor.

One provider class for any endpoint that speaks the OpenAI Chat Completions API
with function/tool calling: OpenAI itself, DeepSeek, Qwen (DashScope or a local
OpenAI-compatible server such as vLLM/Ollama). The endpoint is selected purely by
``base_url`` + ``model_id`` + ``api_key``; the factory in :mod:`rcg.cli` exposes
named presets (``deepseek``, ``qwen``, ``openai``).

It produces the same structured payload as the Anthropic provider and reuses the
shared prompt/tool schema and :func:`rcg.extractors._schema.to_rule` mapping, so
cache keys and downstream behaviour are identical across providers.

Structured-output reliability varies across compatible endpoints, so the
extraction is validated and retried once before giving up: if the first response
has no tool call or returns unparseable / incomplete arguments, the provider
nudges the model once more before raising.
"""

from __future__ import annotations

import json
import os
from typing import Any

from rcg.extractors._schema import (
    PROMPT_VERSION,
    REQUIRED_KEYS,
    SYSTEM,
    TOOL_NAME,
    TOOL_SCHEMA,
    to_rule,
    user_content,
)
from rcg.schema import RawRule, Rule

# The OpenAI tools API wraps each tool in a ``{"type": "function", "function": ...}``
# envelope, where ``function`` carries name/description/parameters. The shared
# Anthropic-shaped schema uses ``input_schema`` for the parameter object, so adapt it.
_OPENAI_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": TOOL_SCHEMA["description"],
        "parameters": TOOL_SCHEMA["input_schema"],
    },
}
_TOOL_CHOICE: dict[str, Any] = {"type": "function", "function": {"name": TOOL_NAME}}

_RETRY_NUDGE = (
    "Return ONLY a record_rule function call with valid JSON arguments "
    "containing every required field."
)


class OpenAICompatibleProvider:
    """LLMProvider for any OpenAI-compatible chat-completions endpoint."""

    model_id: str
    prompt_version: str

    def __init__(
        self,
        model_id: str,
        base_url: str | None = None,
        api_key: str | None = None,
        client: Any = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self.model_id = model_id
        self.prompt_version = prompt_version
        self._base_url = base_url
        # Resolve the key eagerly so a real client can be built lazily later; the
        # generic provider also honours the SDK's own OPENAI_API_KEY fallback.
        self._api_key = api_key or os.environ.get("RCG_LLM_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(base_url=self._base_url, api_key=self._api_key)
        return self._client

    def extract(self, raw: RawRule) -> Rule:
        client = self._get_client()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_content(raw)},
        ]

        payload = self._extract_payload(client, messages)
        if payload is None:
            # One retry with an explicit nudge before giving up — some compatible
            # endpoints need a second pass to emit a clean tool call.
            messages.append({"role": "user", "content": _RETRY_NUDGE})
            payload = self._extract_payload(client, messages)
        if payload is None:
            raise RuntimeError(
                "OpenAI-compatible provider returned no valid record_rule call for: "
                f"{raw.text[:80]!r}"
            )
        return to_rule(raw, payload)

    def _extract_payload(
        self, client: Any, messages: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Call the API once and return a validated payload, or None if unusable."""
        response = client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            tools=[_OPENAI_TOOL],
            tool_choice=_TOOL_CHOICE,
        )
        tool_calls = getattr(response.choices[0].message, "tool_calls", None)
        if not tool_calls:
            return None
        arguments = tool_calls[0].function.arguments
        # Compatible endpoints differ: some return a dict already, others a string.
        if isinstance(arguments, dict):
            payload = arguments
        else:
            try:
                payload = json.loads(arguments)
            except (TypeError, ValueError):
                return None
        if not isinstance(payload, dict) or any(key not in payload for key in REQUIRED_KEYS):
            return None
        return payload
