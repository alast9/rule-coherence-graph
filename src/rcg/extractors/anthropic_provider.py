"""Anthropic-backed LLM extractor.

Uses tool-use for structured output. The prompt explicitly handles non-English
rules: the canonical fields are normalised to English while the original verbatim
text is preserved on the resulting Rule (in `raw_text`), and the detected source
language is recorded on `Rule.source.original_language` (BCP-47).
"""

from __future__ import annotations

import json
import os
from typing import Any

from anthropic import Anthropic

from rcg.detectors.syntactic import APPROVAL_STANCES
from rcg.schema import Directive, Modality, RawRule, Rule, Source, Trigger

PROMPT_VERSION = "2026-05-28.v2"
DEFAULT_MODEL = "claude-sonnet-4-6"

_TOOL_NAME = "record_rule"
_TOOL_SCHEMA: dict[str, Any] = {
    "name": _TOOL_NAME,
    "description": "Record the structured form of a single agent rule.",
    "input_schema": {
        "type": "object",
        "required": [
            "action_class",
            "scope_pattern",
            "modality",
            "action",
            "confidence",
            "original_language",
            "tags",
        ],
        "properties": {
            "action_class": {
                "type": "string",
                "description": (
                    "Coarse verb class the rule governs, e.g. agent.execute_action, "
                    "db.write, deploy.production, fs.delete, rules.modify_self."
                ),
            },
            "scope_pattern": {
                "type": "string",
                "description": "Glob-like scope. Use '*' if the rule has no narrower scope.",
            },
            "modality": {
                "type": "string",
                "enum": [m.value for m in Modality],
            },
            "action": {
                "type": "string",
                "description": (
                    "Normalised English summary of what the rule requires or forbids. "
                    "Always English, even when raw_text is in another language."
                ),
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "original_language": {
                "type": "string",
                "description": (
                    "BCP-47 language tag of the raw_text. Use 'en' for English, "
                    "'vi' for Vietnamese, etc."
                ),
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "e.g. security, autonomy, style, data, rules-meta.",
            },
            "approval_stance": {
                "type": "string",
                "enum": ["requires_human_approval", "bypasses_human_approval", "none"],
                "description": (
                    "Human-in-the-loop stance. Use 'requires_human_approval' if the "
                    "rule demands human approval/confirmation before acting (this "
                    "INCLUDES prohibitions phrased as 'do not X without approval'); "
                    "'bypasses_human_approval' if it removes the human gate (e.g. "
                    "auto-deploy, never prompt, act immediately); 'none' if the rule "
                    "is not about approval gating."
                ),
            },
        },
    },
}

_SYSTEM = """You normalise AI-agent rules into a canonical structured form.

For each rule you receive, call the `record_rule` tool exactly once.

Translation policy: if the rule text is not in English, set `original_language`
to the BCP-47 tag of the source language and write the `action` field in English.
The original verbatim text will be preserved separately; do not translate it.

Modality mapping:
- "must", "always", "never" -> MUST or MUST_NOT
- "should", "prefer", "avoid" -> SHOULD or SHOULD_NOT
- "may", "can" -> MAY

When a rule grants or describes a permission the agent has (e.g. "agent may modify
its rule files"), use MAY and set action_class to `rules.modify_self` or similar
meta-class — these are flagged as critical at the detector layer.

Set `approval_stance` to capture the human-in-the-loop posture: use
`requires_human_approval` when the rule demands human approval/confirmation before
acting (this INCLUDES prohibitions phrased as "do not X without approval"), use
`bypasses_human_approval` when the rule removes the human gate (auto-deploy, never
prompt, act immediately), and `none` when the rule is not about approval gating.
The detector treats two approval-gated rules as conflicting only when their
stances differ, so classify this carefully.
"""


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
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Rule text (verbatim, may not be English):\n{raw.text}\n\n"
                        f"Source file: {raw.source.file}\n"
                        f"Section: {raw.source.section or '(none)'}\n"
                    ),
                }
            ],
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


def _to_rule(raw: RawRule, payload: dict[str, Any]) -> Rule:
    lang = payload.get("original_language") or "en"
    source = Source(
        file=raw.source.file,
        line_start=raw.source.line_start,
        line_end=raw.source.line_end,
        format=raw.source.format,
        section=raw.source.section,
        original_language=None if lang == "en" else lang,
    )
    stance = payload.get("approval_stance")
    conditions = [stance] if stance in APPROVAL_STANCES else []
    return Rule(
        raw_text=raw.text,
        source=source,
        trigger=Trigger(
            action_class=payload["action_class"],
            scope_pattern=payload.get("scope_pattern", "*"),
            context_conditions=conditions,
        ),
        directive=Directive(
            modality=Modality(payload["modality"]),
            action=payload["action"],
        ),
        confidence=float(payload.get("confidence", 1.0)),
        tags=list(payload.get("tags", [])),
    )
