"""Parser for Cursor ``.cursorrules`` files (freeform text or markdown)."""

from __future__ import annotations

from pathlib import Path

from rcg.schema import RawRule, Source

from .markdown_rules import extract_markdown_rules, has_markdown_bullets


class CursorRulesParser:
    """Parse ``.cursorrules``.

    If the file uses markdown bullets, reuse the markdown bullet/heading
    extraction. Otherwise treat every non-empty, non-comment line as one rule.
    """

    format = "cursorrules"

    def matches(self, path: Path) -> bool:
        return path.name == ".cursorrules"

    def parse(self, path: Path) -> list[RawRule]:
        lines = path.read_text(encoding="utf-8").splitlines()
        if has_markdown_bullets(lines):
            return extract_markdown_rules(lines, file=str(path), fmt=self.format)
        rules: list[RawRule] = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            rules.append(
                RawRule(
                    text=stripped,
                    source=Source(
                        file=str(path),
                        line_start=idx + 1,
                        line_end=idx + 1,
                        format=self.format,
                    ),
                )
            )
        return rules
