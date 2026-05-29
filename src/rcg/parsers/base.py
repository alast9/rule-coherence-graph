"""Parser protocol. Adding a new source format = one new module here."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from rcg.schema import RawRule


class Parser(Protocol):
    """A parser reads one file and emits a list of raw, pre-extraction rules."""

    format: str

    def matches(self, path: Path) -> bool:
        ...

    def parse(self, path: Path) -> list[RawRule]:
        ...
