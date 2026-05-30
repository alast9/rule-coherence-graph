"""Unit tests for the public-demo cost/abuse guardrails."""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")

from rcg import mcp_guard  # noqa: E402


def test_demo_config_none_without_switch() -> None:
    assert mcp_guard._demo_config({}) is None
    assert mcp_guard._demo_config({"RCG_PUBLIC_DEMO": "0"}) is None
    assert mcp_guard._demo_config({"RCG_PUBLIC_DEMO": "off"}) is None


def test_demo_config_defaults() -> None:
    cfg = mcp_guard._demo_config({"RCG_PUBLIC_DEMO": "1"})
    assert cfg is not None
    assert cfg.max_input_bytes == 50_000
    assert cfg.max_rules == 200
    assert cfg.graph_max_nodes == 5_000
    assert cfg.rate_limit_per_min == 30


def test_demo_config_truthy_variants() -> None:
    for value in ("1", "true", "TRUE", "Yes"):
        assert mcp_guard._demo_config({"RCG_PUBLIC_DEMO": value}) is not None


def test_demo_config_honors_overrides() -> None:
    cfg = mcp_guard._demo_config(
        {
            "RCG_PUBLIC_DEMO": "1",
            "RCG_MAX_INPUT_BYTES": "123",
            "RCG_MAX_RULES": "7",
            "RCG_GRAPH_MAX_NODES": "99",
            "RCG_RATE_LIMIT_PER_MIN": "5",
        }
    )
    assert cfg is not None
    assert cfg.max_input_bytes == 123
    assert cfg.max_rules == 7
    assert cfg.graph_max_nodes == 99
    assert cfg.rate_limit_per_min == 5


def test_demo_config_bad_int_falls_back_to_default() -> None:
    cfg = mcp_guard._demo_config(
        {"RCG_PUBLIC_DEMO": "1", "RCG_MAX_RULES": "not-a-number"}
    )
    assert cfg is not None
    assert cfg.max_rules == 200


def test_rate_limiter_blocks_over_limit() -> None:
    clock = {"t": 0.0}
    limiter = mcp_guard._RateLimiter(limit_per_min=3, now=lambda: clock["t"])
    assert limiter.allow() is True
    assert limiter.allow() is True
    assert limiter.allow() is True
    # The 4th call within the same 60s window is blocked.
    assert limiter.allow() is False


def test_rate_limiter_recovers_after_window() -> None:
    clock = {"t": 0.0}
    limiter = mcp_guard._RateLimiter(limit_per_min=1, now=lambda: clock["t"])
    assert limiter.allow() is True
    assert limiter.allow() is False
    # Advance past the trailing 60s window; the old hit ages out.
    clock["t"] = 61.0
    assert limiter.allow() is True


def test_should_clear() -> None:
    assert mcp_guard._should_clear(existing=4000, incoming=2000, cap=5000) is True
    assert mcp_guard._should_clear(existing=10, incoming=10, cap=5000) is False
    # Exactly at the cap does not trigger a clear; strictly over does.
    assert mcp_guard._should_clear(existing=4990, incoming=10, cap=5000) is False
    assert mcp_guard._should_clear(existing=4990, incoming=11, cap=5000) is True
