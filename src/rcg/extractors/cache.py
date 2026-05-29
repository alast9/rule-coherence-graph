"""File-based extraction cache.

Cache key = sha256(raw_text + source.file + model_id + prompt_version).

Including source.file means the same rule text in two files cached separately —
matches the Rule.id design (different governance instances).

Bumping prompt_version invalidates all cache entries for that provider.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from rcg.schema import RawRule, Rule

DEFAULT_CACHE_DIR = Path(".rcg") / "cache" / "extract"


class ExtractionCache:
    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR):
        self.cache_dir = cache_dir

    def _key(self, raw: RawRule, model_id: str, prompt_version: str) -> str:
        h = hashlib.sha256()
        for part in (raw.text, raw.source.file, model_id, prompt_version):
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, raw: RawRule, model_id: str, prompt_version: str) -> Rule | None:
        path = self._path(self._key(raw, model_id, prompt_version))
        if not path.exists():
            return None
        return Rule.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, raw: RawRule, model_id: str, prompt_version: str, rule: Rule) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(self._key(raw, model_id, prompt_version))
        path.write_text(rule.model_dump_json(indent=2), encoding="utf-8")
