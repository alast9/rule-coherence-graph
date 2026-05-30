# mcp_guard.py
"""Cost and abuse guardrails for the public RCG MCP demo.

These guardrails are **opt-in** via the ``RCG_PUBLIC_DEMO`` environment
variable. When it is not set (local/stdio/self-hosted use), every helper in
this module is a no-op and the MCP tools behave exactly as before.

The pieces here are intentionally pure and easy to unit-test:

* :func:`_demo_config` reads tunable limits from an env mapping.
* :class:`_RateLimiter` is an in-process sliding-window limiter with an
  injectable clock so tests never sleep.
* :func:`_demo_guard_check` centralizes input-size / rate-limit enforcement and
  returns a structured error dict (never raises across the MCP boundary).
* :func:`_should_clear` is the pure decision for the graph node cap auto-clear.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

# Default guardrail limits for the public demo. Chosen to keep a free
# AuraDB graph (~50k node hard cap) well clear of full and to bound the
# work a single small Fly.io VM performs per request.
_DEFAULT_MAX_INPUT_BYTES = 50_000
_DEFAULT_MAX_RULES = 200
_DEFAULT_GRAPH_MAX_NODES = 5_000
_DEFAULT_RATE_LIMIT_PER_MIN = 30

_TRUTHY = {"1", "true", "yes"}


@dataclass(frozen=True)
class DemoConfig:
    """Resolved guardrail limits for the public demo."""

    max_input_bytes: int
    max_rules: int
    graph_max_nodes: int
    rate_limit_per_min: int


def _env_int(env: Mapping[str, str], key: str, default: int) -> int:
    """Parse an int env var, falling back to ``default`` on any bad value."""
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _demo_config(env: Mapping[str, str]) -> DemoConfig | None:
    """Return demo guardrail limits, or None when the demo switch is off.

    Returns None unless ``RCG_PUBLIC_DEMO`` is truthy ("1"/"true"/"yes",
    case-insensitive), keeping local/stdio/self-hosted use unrestricted.
    """
    if env.get("RCG_PUBLIC_DEMO", "").strip().lower() not in _TRUTHY:
        return None
    return DemoConfig(
        max_input_bytes=_env_int(env, "RCG_MAX_INPUT_BYTES", _DEFAULT_MAX_INPUT_BYTES),
        max_rules=_env_int(env, "RCG_MAX_RULES", _DEFAULT_MAX_RULES),
        graph_max_nodes=_env_int(env, "RCG_GRAPH_MAX_NODES", _DEFAULT_GRAPH_MAX_NODES),
        rate_limit_per_min=_env_int(env, "RCG_RATE_LIMIT_PER_MIN", _DEFAULT_RATE_LIMIT_PER_MIN),
    )


class _RateLimiter:
    """In-process sliding-window rate limiter with an injectable clock.

    Because there is no reliable per-client identity over the MCP transport,
    this limiter is **global** (process-wide): it caps the total demo
    throughput, not per-user throughput. Timestamps for the trailing 60s
    window are kept in a deque and evicted as they age out. The critical
    section is guarded by a lock since FastMCP may serve requests
    concurrently.
    """

    _WINDOW_SECONDS = 60.0

    def __init__(
        self,
        limit_per_min: int,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit_per_min
        self._now = now
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """Record a hit and return False if the 60s window is over the limit."""
        now = self._now()
        with self._lock:
            cutoff = now - self._WINDOW_SECONDS
            while self._hits and self._hits[0] <= cutoff:
                self._hits.popleft()
            if len(self._hits) >= self._limit:
                return False
            self._hits.append(now)
            return True


def _demo_guard_check(text_len: int | None, cfg: DemoConfig) -> dict[str, Any] | None:
    """Enforce rate limit then input size; return an error dict or None.

    The error dict shape is ``{"error": <machine_code>, "message": <text>,
    "limit": <int>}`` with codes ``rate_limited`` and ``input_too_large``.
    The ``too_many_rules`` code is emitted by callers after rule extraction.
    The rate limit is checked first so abusive callers are stopped before any
    expensive work; ``text_len`` is the UTF-8 byte length of the input (pass
    None for tools that read server-side files and only need rate limiting).
    """
    if not _shared_limiter(cfg.rate_limit_per_min).allow():
        return {
            "error": "rate_limited",
            "message": (
                "Demo rate limit exceeded. This shared public demo caps total "
                "throughput; please retry in a minute."
            ),
            "limit": cfg.rate_limit_per_min,
        }
    if text_len is not None and text_len > cfg.max_input_bytes:
        return {
            "error": "input_too_large",
            "message": (
                f"Input is {text_len} bytes which exceeds the demo limit of "
                f"{cfg.max_input_bytes} bytes."
            ),
            "limit": cfg.max_input_bytes,
        }
    return None


def _too_many_rules_error(n_rules: int, cfg: DemoConfig) -> dict[str, Any]:
    """Build the ``too_many_rules`` error dict for the demo rule cap."""
    return {
        "error": "too_many_rules",
        "message": (
            f"Extracted {n_rules} rules which exceeds the demo limit of "
            f"{cfg.max_rules}."
        ),
        "limit": cfg.max_rules,
    }


def _should_clear(existing: int, incoming: int, cap: int) -> bool:
    """Return True when loading ``incoming`` nodes would exceed the cap.

    Used to auto-clear the small demo graph before it fills the free AuraDB
    node cap, keeping the public demo from getting stuck.
    """
    return existing + incoming > cap


# Module-level rate limiter, created lazily and sized from the demo config.
# It is intentionally global (process-wide) for the same reason documented on
# :class:`_RateLimiter`: there is no per-client identity over the transport.
_limiter_lock = threading.Lock()
_limiter: _RateLimiter | None = None


def _shared_limiter(limit_per_min: int) -> _RateLimiter:
    """Return the process-wide limiter, creating it on first use."""
    global _limiter
    with _limiter_lock:
        if _limiter is None:
            _limiter = _RateLimiter(limit_per_min)
        return _limiter


def _reset_limiter() -> None:
    """Drop the shared limiter so tests start from a clean slate."""
    global _limiter
    with _limiter_lock:
        _limiter = None
