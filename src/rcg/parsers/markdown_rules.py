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


def has_markdown_bullets(lines: list[str]) -> bool:
    """Return True if any line is a markdown bullet (`- ` / `* `) at column 0."""
    return any(_BULLET.match(line) for line in lines)


def extract_markdown_rules(
    lines: list[str],
    *,
    file: str,
    fmt: str,
    line_offset: int = 0,
    default_section: str | None = None,
) -> list[RawRule]:
    """Extract bullet rules + nearest-heading sections from markdown lines.

    ``line_offset`` is added to every recorded line number so callers that
    stripped a prefix (e.g. YAML frontmatter) still report 1-based positions
    relative to the original file. ``default_section`` seeds the section for
    bullets that appear before the first heading.
    """
    rules: list[RawRule] = []
    section: str | None = default_section

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

        start_line = i + 1 + line_offset
        parts = [bullet.group(1).strip()]
        j = i + 1
        while j < len(lines) and _CONTINUATION_INDENT.match(lines[j]):
            parts.append(lines[j].strip())
            j += 1
        end_line = j + line_offset  # j is exclusive index → 1-based inclusive end
        text = " ".join(p for p in parts if p)

        rules.append(
            RawRule(
                text=text,
                source=Source(
                    file=file,
                    line_start=start_line,
                    line_end=end_line,
                    format=fmt,
                    section=section,
                ),
            )
        )
        i = j

    return rules


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
        return extract_markdown_rules(lines, file=str(path), fmt=self.format)
