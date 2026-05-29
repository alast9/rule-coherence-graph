"""Walk a corpus root and route files to registered parsers."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from rcg.parsers.base import Parser
from rcg.parsers.cedar import CedarParser
from rcg.parsers.cursorrules import CursorRulesParser
from rcg.parsers.markdown_rules import MarkdownRulesParser
from rcg.parsers.mdc import MdcParser
from rcg.parsers.opa_rego import OpaRegoParser
from rcg.parsers.structured import StructuredRulesParser
from rcg.schema import RawRule

_DEFAULT_PARSERS: list[Parser] = [
    MarkdownRulesParser(),
    MdcParser(),
    CursorRulesParser(),
    StructuredRulesParser(),
    OpaRegoParser(),
    CedarParser(),
]

_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".rcg"}


def discover(root: Path, parsers: list[Parser] | None = None) -> list[RawRule]:
    parsers = parsers or _DEFAULT_PARSERS
    root = root.resolve()
    # Rule identity (Rule.id) hashes source.file, so the stored path must be
    # stable regardless of how the corpus root was spelled on the command line
    # (relative vs absolute, or with redundant segments). Record each file as a
    # POSIX path relative to the corpus root — this keeps ingest deterministic
    # and machine-independent (§8 determinism non-negotiable).
    base = root if root.is_dir() else root.parent
    raw_rules: list[RawRule] = []
    for path in _walk(root):
        for parser in parsers:
            if parser.matches(path):
                for raw in parser.parse(path):
                    raw.source.file = path.resolve().relative_to(base).as_posix()
                    raw_rules.append(raw)
                break
    return raw_rules


def _walk(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file():
            yield path
