"""LLM provider protocol.

Adding a new provider (Bedrock, Ollama, OpenAI, etc.) is a single-file change:
implement this Protocol and register the class in the provider factory.
"""

from __future__ import annotations

from typing import Protocol

from rcg.schema import RawRule, Rule


class LLMProvider(Protocol):
    model_id: str
    """Stable identifier of the underlying model. Part of the cache key."""

    prompt_version: str
    """Version tag of this provider's extraction prompt. Bump to invalidate cache."""

    def extract(self, raw: RawRule) -> Rule:
        """Convert a raw rule string into a canonical Rule."""
        ...
