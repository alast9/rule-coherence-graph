"""Orchestrator: run RawRule -> Rule extraction with caching."""

from __future__ import annotations

from collections.abc import Iterable

from rcg.extractors.cache import ExtractionCache
from rcg.providers.llm import LLMProvider
from rcg.schema import RawRule, Rule


def extract_all(
    raws: Iterable[RawRule],
    provider: LLMProvider,
    cache: ExtractionCache | None = None,
) -> list[Rule]:
    cache = cache or ExtractionCache()
    rules: list[Rule] = []
    for raw in raws:
        cached = cache.get(raw, provider.model_id, provider.prompt_version)
        if cached is not None:
            rules.append(cached)
            continue
        rule = provider.extract(raw)
        cache.put(raw, provider.model_id, provider.prompt_version, rule)
        rules.append(rule)
    return rules
