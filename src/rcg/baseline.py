"""Accepted-conflicts baseline.

Some flagged conflicts are intentional and reviewed-as-acceptable. A baseline
file records their fingerprints so subsequent runs suppress them while still
surfacing anything new. The file is human-reviewable JSON.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from rcg.detectors.base import Finding


def fingerprint(f: Finding) -> str:
    """Stable, order-independent fingerprint for a finding."""
    ids = sorted([f.rule_a.id, f.rule_b.id])
    payload = f.type + "\x00" + "\x00".join(ids)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_baseline(path: Path) -> set[str]:
    """Return the set of accepted fingerprints (empty if the file is missing)."""
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {entry["fingerprint"] for entry in data.get("accepted", [])}


def _excerpt(text: str, limit: int = 120) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "..."


def write_baseline(path: Path, findings: Sequence[Finding]) -> int:
    """Write a human-reviewable baseline of ``findings``; return the count."""
    accepted = [
        {
            "fingerprint": fingerprint(f),
            "type": f.type,
            "rule_a": _excerpt(f.rule_a.raw_text),
            "rule_b": _excerpt(f.rule_b.raw_text),
            "note": "",
        }
        for f in findings
    ]
    payload = {"accepted": accepted}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return len(accepted)


def split_baselined(
    findings: Sequence[Finding],
    accepted: set[str],
) -> tuple[list[Finding], list[Finding]]:
    """Split findings into (kept, suppressed) based on accepted fingerprints."""
    kept: list[Finding] = []
    suppressed: list[Finding] = []
    for f in findings:
        if fingerprint(f) in accepted:
            suppressed.append(f)
        else:
            kept.append(f)
    return kept, suppressed
