"""Parser for markdown rule files: CLAUDE.md, AGENTS.md, memory.md, .agent/rules/*.md.

Splitting heuristic: each top-level markdown bullet (`- ` or `* ` at column 0,
with optional continuation lines indented under it) becomes one RawRule. The
nearest preceding `#`-level heading is captured as `source.section`.
"""

from __future__ import annotations

import re
from pathlib import Path

from rcg.schema import RawRule, Source

_BULLET = re.compile(r"^[-*]\s+(.+)$")
_HEADING = re.compile(r"^(#+)\s+(.+)$")
_CONTINUATION_INDENT = re.compile(r"^[ \t]+\S")


class MarkdownRulesParser:
    format = "markdown"

    _RECOGNISED_NAMES = {"CLAUDE.md", "AGENTS.md", "memory.md"}

    def matches(self, path: Path) -> bool:
        if path.suffix != ".md":
            return False
        if path.name in self._RECOGNISED_NAMES:
            return True
        return ".agent" in path.parts and "rules" in path.parts

    def parse(self, path: Path) -> list[RawRule]:
        lines = path.read_text(encoding="utf-8").splitlines()
        rules: list[RawRule] = []
        section: str | None = None

        i = 0
        while i < len(lines):
            line = lines[i]
            heading = _HEADING.match(line)
            if heading:
                section = heading.group(2).strip()
                i += 1
                continue

            bullet = _BULLET.match(line)
            if not bullet:
                i += 1
                continue

            start_line = i + 1
            parts = [bullet.group(1).strip()]
            j = i + 1
            while j < len(lines) and _CONTINUATION_INDENT.match(lines[j]):
                parts.append(lines[j].strip())
                j += 1
            end_line = j  # inclusive 1-based: j is exclusive index → end is j
            text = " ".join(p for p in parts if p)

            rules.append(
                RawRule(
                    text=text,
                    source=Source(
                        file=str(path),
                        line_start=start_line,
                        line_end=end_line,
                        format=self.format,
                        section=section,
                    ),
                )
            )
            i = j

        return rules
