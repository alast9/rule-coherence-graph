"""Canonical Rule schema.

Every component downstream of the parsers operates on `Rule`. The schema is the
contract; downstream changes that don't fit it should propose an extension here
rather than working around it.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field


class Modality(StrEnum):
    MUST = "MUST"
    MUST_NOT = "MUST_NOT"
    SHOULD = "SHOULD"
    SHOULD_NOT = "SHOULD_NOT"
    MAY = "MAY"


OPPOSING_MODALITY: dict[Modality, Modality] = {
    Modality.MUST: Modality.MUST_NOT,
    Modality.MUST_NOT: Modality.MUST,
    Modality.SHOULD: Modality.SHOULD_NOT,
    Modality.SHOULD_NOT: Modality.SHOULD,
}


class Source(BaseModel):
    file: str
    line_start: int = 0
    line_end: int = 0
    format: str
    section: str | None = None
    original_language: str | None = None
    """BCP-47 tag. None means the extractor judged the rule to be in English."""


class Trigger(BaseModel):
    action_class: str
    """Coarse verb class the rule governs, e.g. `agent.execute_action`, `db.write`."""
    scope_pattern: str = "*"
    """Glob-like string in v1. Structured representation deferred to v2."""
    context_conditions: list[str] = Field(default_factory=list)


class Directive(BaseModel):
    modality: Modality
    action: str
    """Normalised English summary of what the rule requires or forbids."""


class Priority(BaseModel):
    explicit_priority: int | None = None
    declared_precedence_over: list[str] = Field(default_factory=list)


class Rule(BaseModel):
    raw_text: str
    source: Source
    trigger: Trigger
    directive: Directive
    priority: Priority = Field(default_factory=Priority)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    tags: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        h = hashlib.sha256()
        h.update(self.raw_text.encode("utf-8"))
        h.update(b"\x00")
        h.update(self.source.file.encode("utf-8"))
        return h.hexdigest()[:16]


class RawRule(BaseModel):
    """Pre-extraction output of a Parser. The LLM extractor turns this into Rule."""

    text: str
    source: Source
