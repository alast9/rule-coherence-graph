"""Parser for AWS Cedar ``.cedar`` policy files.

Splitting heuristic: each Cedar policy becomes one RawRule. A policy is a
``permit(...)`` or ``forbid(...)`` statement with optional ``when {...}`` /
``unless {...}`` clauses, terminated by a top-level ``;``. Any leading ``//``
comment lines and ``@annotation(...)`` lines are kept with the policy they
precede.

Cedar is not parsed structurally — RCG ships no Cedar toolchain. Policy
boundaries are found by tracking ``()``/``{}``/``[]`` nesting depth while
ignoring brackets and ``;`` that appear inside double-quoted strings or after a
``//`` line comment.
"""

from __future__ import annotations

from pathlib import Path

from rcg.schema import RawRule, Source

_OPEN = {"(": ")", "{": "}", "[": "]"}
_CLOSE = {")", "}", "]"}


class CedarParser:
    """Parse ``.cedar`` policy files into one raw rule per policy."""

    format = "cedar"

    def matches(self, path: Path) -> bool:
        return path.suffix == ".cedar"

    def parse(self, path: Path) -> list[RawRule]:
        lines = path.read_text(encoding="utf-8").splitlines()
        rules: list[RawRule] = []

        depth = 0
        buf_start: int | None = None
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if buf_start is None:
                if not stripped:
                    continue
                buf_start = idx

            depth, ends_policy = _scan_line(line, depth)
            if ends_policy and depth == 0:
                rules.append(_make_rule(lines, buf_start, idx, path))
                buf_start = None

        return rules


def _scan_line(line: str, depth: int) -> tuple[int, bool]:
    """Update nesting depth across one line; flag a top-level ``;``.

    Returns the new depth and whether a ``;`` was seen at depth 0 (policy end).
    Brackets and ``;`` inside double-quoted strings or after ``//`` are ignored.
    """
    in_string = False
    prev = ""
    ends_policy = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_string:
            if ch == '"' and prev != "\\":
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            break
        elif ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0:
            ends_policy = True
        prev = ch
        i += 1
    return depth, ends_policy


def _make_rule(lines: list[str], start: int, end: int, path: Path) -> RawRule:
    text = "\n".join(lines[start : end + 1]).rstrip()
    return RawRule(
        text=text,
        source=Source(
            file=str(path),
            line_start=start + 1,
            line_end=end + 1,
            format="cedar",
        ),
    )
