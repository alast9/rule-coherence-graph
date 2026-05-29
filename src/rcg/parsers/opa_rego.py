"""Parser for Open Policy Agent (OPA) Rego ``.rego`` policy files.

Splitting heuristic: each Rego rule definition becomes one RawRule. A unit is
any contiguous block of leading ``#`` comment lines immediately above a rule
definition, plus the rule definition itself (its head and, where present, its
``{ ... }`` body). ``package`` / ``import`` lines and blank lines are skipped.

Rego is not parsed structurally — RCG ships no Rego toolchain. The unit
boundaries are found by tracking brace depth while ignoring ``{``/``}`` that
appear inside double-quoted strings or after a ``#`` comment on a line.
"""

from __future__ import annotations

from pathlib import Path

from rcg.schema import RawRule, Source


class OpaRegoParser:
    """Parse ``.rego`` policy files into one raw rule per rule definition."""

    format = "opa_rego"

    def matches(self, path: Path) -> bool:
        return path.suffix == ".rego"

    def parse(self, path: Path) -> list[RawRule]:
        lines = path.read_text(encoding="utf-8").splitlines()
        rules: list[RawRule] = []

        i = 0
        n = len(lines)
        while i < n:
            stripped = lines[i].strip()

            # Blank lines and package/import directives never start a rule.
            if not stripped or _is_skippable(stripped):
                i += 1
                continue

            # A bare comment line begins a candidate unit only if a rule
            # definition eventually follows it (before a blank line breaks the
            # block). Otherwise it is a stray comment and is skipped.
            if stripped.startswith("#"):
                comment_start = i
                j = i
                while j < n and lines[j].strip().startswith("#"):
                    j += 1
                # The line after the comment block must be a rule definition for
                # the comments to attach; blank/package/import lines detach them.
                if j < n and lines[j].strip() and not _is_skippable(lines[j].strip()):
                    end = _find_unit_end(lines, j)
                    rules.append(_make_rule(lines, comment_start, end, path))
                    i = end + 1
                else:
                    i = j
                continue

            # A code line that is a rule head: emit it (no leading comment).
            end = _find_unit_end(lines, i)
            rules.append(_make_rule(lines, i, end, path))
            i = end + 1

        return rules


def _is_skippable(stripped: str) -> bool:
    """Return True for ``package``/``import`` lines that are not rules."""
    return stripped.startswith(("package ", "import ")) or stripped in {"package", "import"}


def _find_unit_end(lines: list[str], start: int) -> int:
    """Return the 0-based index of the last line of the rule unit at ``start``.

    For a definition with a ``{ ... }`` body, the unit ends on the line where
    brace depth returns to zero. For a single-line assignment with no body (e.g.
    ``default allow := false``), the unit is just that one line.
    """
    depth = 0
    seen_open = False
    i = start
    n = len(lines)
    while i < n:
        depth += _brace_delta(lines[i])
        if depth > 0:
            seen_open = True
        if seen_open and depth <= 0:
            return i
        if not seen_open and depth == 0:
            # No body started on this line. If the next line opens a body
            # (head and body on separate lines), keep going; otherwise the
            # head is a single-line definition and ends here.
            nxt = lines[i + 1].strip() if i + 1 < n else ""
            if "{" not in nxt:
                return i
        i += 1
    return n - 1


def _brace_delta(line: str) -> int:
    """Net ``{`` minus ``}`` on a line, ignoring strings and ``#`` comments."""
    delta = 0
    in_string = False
    prev = ""
    for ch in line:
        if in_string:
            if ch == '"' and prev != "\\":
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "#":
            break
        elif ch == "{":
            delta += 1
        elif ch == "}":
            delta -= 1
        prev = ch
    return delta


def _make_rule(lines: list[str], start: int, end: int, path: Path) -> RawRule:
    text = "\n".join(lines[start : end + 1]).rstrip()
    return RawRule(
        text=text,
        source=Source(
            file=str(path),
            line_start=start + 1,
            line_end=end + 1,
            format="opa_rego",
        ),
    )
