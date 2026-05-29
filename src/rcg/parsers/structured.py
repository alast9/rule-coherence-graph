"""Parser for structured (YAML/JSON) rule files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from rcg.schema import RawRule, Source

_RULE_KEYS = ("rule", "text", "description", "content", "message")


class StructuredRulesParser:
    """Parse rule-related YAML/JSON files into raw rules.

    Deliberately conservative about which files it claims so that arbitrary
    config YAML/JSON is not swallowed: the file name must contain ``rule`` or the
    file must live under an ``.agent``/``rules`` directory.
    """

    format = "yaml"

    _SUFFIXES = {".yaml", ".yml", ".json"}

    def matches(self, path: Path) -> bool:
        if path.suffix.lower() not in self._SUFFIXES:
            return False
        if "rule" in path.name.lower():
            return True
        parts = {p.lower() for p in path.parts}
        return bool(parts & {".agent", "agent", "rules"})

    def parse(self, path: Path) -> list[RawRule]:
        fmt = "json" if path.suffix.lower() == ".json" else "yaml"
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            return []
        return self._extract(data, file=str(path), fmt=fmt, section=None)

    def _extract(
        self,
        data: Any,
        *,
        file: str,
        fmt: str,
        section: str | None,
    ) -> list[RawRule]:
        if isinstance(data, list):
            return self._from_list(data, file=file, fmt=fmt, section=section)
        if isinstance(data, dict) and "rules" in data:
            return self._extract(data["rules"], file=file, fmt=fmt, section="rules")
        return []

    def _from_list(
        self,
        items: list[Any],
        *,
        file: str,
        fmt: str,
        section: str | None,
    ) -> list[RawRule]:
        rules: list[RawRule] = []
        for item in items:
            text = self._item_text(item)
            if text:
                rules.append(
                    RawRule(
                        text=text,
                        source=Source(
                            file=file,
                            line_start=0,
                            line_end=0,
                            format=fmt,
                            section=section,
                        ),
                    )
                )
        return rules

    @staticmethod
    def _item_text(item: Any) -> str | None:
        if isinstance(item, str):
            return item.strip() or None
        if isinstance(item, dict):
            for key in _RULE_KEYS:
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None
