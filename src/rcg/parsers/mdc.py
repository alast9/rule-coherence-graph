"""Parser for Cursor ``.mdc`` rule files (markdown with optional frontmatter)."""

from __future__ import annotations

import re
from pathlib import Path

from rcg.schema import RawRule

from .markdown_rules import extract_markdown_rules

_FENCE = re.compile(r"^---\s*$")
_DESCRIPTION = re.compile(r"^description\s*:\s*(.*)$")


def _split_frontmatter(lines: list[str]) -> tuple[list[str], int, str | None]:
    """Split off a leading ``---`` YAML frontmatter block.

    Returns ``(body_lines, line_offset, description)`` where ``line_offset`` is
    the number of lines consumed before the body, so body line numbers stay
    accurate. If there is no (terminated) frontmatter the file is treated wholly
    as body.
    """
    if not lines or not _FENCE.match(lines[0]):
        return lines, 0, None
    for idx in range(1, len(lines)):
        if _FENCE.match(lines[idx]):
            description: str | None = None
            for fm_line in lines[1:idx]:
                m = _DESCRIPTION.match(fm_line)
                if m:
                    value = m.group(1).strip().strip("'\"")
                    description = value or None
            return lines[idx + 1 :], idx + 1, description
    # Unterminated frontmatter: treat the whole file as body.
    return lines, 0, None


class MdcParser:
    """Parse Cursor ``.mdc`` files: optional YAML frontmatter + markdown body."""

    format = "mdc"

    def matches(self, path: Path) -> bool:
        return path.suffix == ".mdc"

    def parse(self, path: Path) -> list[RawRule]:
        lines = path.read_text(encoding="utf-8").splitlines()
        body, offset, description = _split_frontmatter(lines)
        return extract_markdown_rules(
            body,
            file=str(path),
            fmt=self.format,
            line_offset=offset,
            default_section=description,
        )
