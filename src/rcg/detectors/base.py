"""Shared detector primitives.

All three detectors (syntactic, semantic, precedence) emit findings that share a
common structural shape. The :class:`Finding` protocol captures that shape so
scoring, reporting and the baseline can treat any finding uniformly.

This module also hosts :func:`scopes_overlap`, the public scope-matching helper
reused by the syntactic and precedence passes.
"""

from __future__ import annotations

from fnmatch import fnmatch
from typing import Literal, Protocol, runtime_checkable

from rcg.schema import Rule

Severity = Literal["low", "medium", "high", "critical"]


@runtime_checkable
class Finding(Protocol):
    """Structural shape shared by every detector's output.

    Members are declared as read-only properties so that ``@dataclass(frozen=True)``
    findings (whose attributes are read-only) structurally satisfy the protocol,
    and so that a finding's ``severity``/``type`` ``Literal`` types are accepted
    where the protocol only requires ``str``.
    """

    @property
    def rule_a(self) -> Rule: ...

    @property
    def rule_b(self) -> Rule: ...

    @property
    def type(self) -> str: ...

    @property
    def severity(self) -> str: ...

    @property
    def reason(self) -> str: ...


def scopes_overlap(a: Rule, b: Rule) -> bool:
    """Return ``True`` if two rules' glob scope patterns can match the same path.

    Patterns are glob-like (v1). ``*`` matches everything. We over-report rather
    than miss a real clash: a pair overlaps if either pattern matches the other.
    """
    sa, sb = a.trigger.scope_pattern, b.trigger.scope_pattern
    if sa == sb:
        return True
    return fnmatch(sa, sb) or fnmatch(sb, sa)
