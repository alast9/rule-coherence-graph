"""Anthropic-backed LLM extractor.

Uses tool-use for structured output. The prompt explicitly handles non-English
rules: the canonical fields are normalised to English while the original verbatim
text is preserved on the resulting Rule (in `raw_text`), and the detected source
language is recorded on `Rule.source.original_language` (BCP-47).

The prompt text, tool schema, and payload→Rule mapping are shared with the
OpenAI-compatible provider via :mod:`rcg.extractors._schema` so every provider's
extraction cache keys on the same prompt semantics.
"""

from __future__ import annotations

import json
import os

from anthropic import Anthropic

from rcg.extractors import _schema
from rcg.extractors._schema import PROMPT_VERSION, user_content
from rcg.schema import RawRule, Rule

# Re-exported under their historical private names so existing imports
# (``from rcg.extractors.anthropic_provider import _TOOL_SCHEMA``) keep working;
# the definitions now live in the shared rcg.extractors._schema module.
_TOOL_NAME = _schema.TOOL_NAME
_TOOL_SCHEMA = _schema.TOOL_SCHEMA
_SYSTEM = _schema.SYSTEM
_to_rule = _schema.to_rule

__all__ = [
    "PROMPT_VERSION",
    "DEFAULT_MODEL",
    "AnthropicProvider",
    "_TOOL_SCHEMA",
    "_SYSTEM",
    "_to_rule",
]

DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicProvider:
    model_id: str
    prompt_version: str = PROMPT_VERSION

    def __init__(self, model_id: str = DEFAULT_MODEL, client: Anthropic | None = None):
        self.model_id = model_id
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        self._client = client or Anthropic(api_key=api_key)

    def extract(self, raw: RawRule) -> Rule:
        # The anthropic SDK's create() overloads don't accept plain dict literals
        # for messages/tool_choice (Literal-key inference); the call is correct at
        # runtime. Scoped ignore keeps strict mypy green against the pinned SDK.
        response = self._client.messages.create(  # type: ignore[call-overload]
            model=self.model_id,
            max_tokens=1024,
            system=_SYSTEM,
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": user_content(raw)}],
        )

        tool_use = next(
            (block for block in response.content if getattr(block, "type", None) == "tool_use"),
            None,
        )
        if tool_use is None:
            raise RuntimeError(
                f"Anthropic provider returned no tool_use block for: {raw.text[:80]!r}"
            )

        payload = tool_use.input if isinstance(tool_use.input, dict) else json.loads(tool_use.input)
        return _to_rule(raw, payload)
