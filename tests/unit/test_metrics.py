"""Unit tests for the RCG Prometheus metrics registry and HTTP endpoint."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

from rcg import metrics


@pytest.fixture(autouse=True)
def _reset_registry() -> Iterator[None]:
    """Reset the shared registry so counts are isolated between tests."""
    metrics.reset()
    yield
    metrics.reset()


def test_render_includes_predeclared_zero_series() -> None:
    text = metrics.render()
    # Every known counter has a HELP and TYPE header exactly once.
    for name in (
        "rcg_tool_calls_total",
        "rcg_guard_rejections_total",
        "rcg_rules_extracted_total",
        "rcg_graph_writes_total",
        "rcg_graph_clears_total",
        "rcg_graph_write_failures_total",
    ):
        assert text.count(f"# HELP {name} ") == 1
        assert text.count(f"# TYPE {name} counter") == 1
    # Pre-declared zero-valued series are present before any increment.
    assert 'rcg_tool_calls_total{tool="check_rules"} 0' in text
    assert 'rcg_guard_rejections_total{reason="rate_limited"} 0' in text
    assert "rcg_rules_extracted_total 0" in text


def test_inc_accumulates() -> None:
    metrics.record_tool_call("check_rules")
    metrics.record_tool_call("check_rules")
    metrics.record_tool_call("score_corpus")
    text = metrics.render()
    assert 'rcg_tool_calls_total{tool="check_rules"} 2' in text
    assert 'rcg_tool_calls_total{tool="score_corpus"} 1' in text


def test_record_rules_extracted_sums() -> None:
    metrics.record_rules_extracted(3)
    metrics.record_rules_extracted(4)
    assert "rcg_rules_extracted_total 7" in metrics.render()


def test_reset_clears_counts() -> None:
    metrics.record_tool_call("check_rules")
    metrics.reset()
    assert 'rcg_tool_calls_total{tool="check_rules"} 0' in metrics.render()


def test_render_is_deterministic() -> None:
    metrics.record_tool_call("score_corpus")
    metrics.record_tool_call("check_corpus")
    assert metrics.render() == metrics.render()


def test_label_escaping() -> None:
    metrics.inc("rcg_tool_calls_total", {"tool": 'a"b\\c\nd'})
    text = metrics.render()
    assert 'rcg_tool_calls_total{tool="a\\"b\\\\c\\nd"} 1' in text


def test_render_line_shape() -> None:
    metrics.record_tool_call("check_rules")
    metrics.record_rules_extracted(2)
    series_line = re.compile(r"^[a-z_]+(\{.*\})? \d+(\.\d+)?$")
    for line in metrics.render().splitlines():
        if line.startswith("#") or not line:
            continue
        assert series_line.match(line), line


def test_resolve_metrics_config_disabled_by_default() -> None:
    enabled, host, port = metrics.resolve_metrics_config({})
    assert enabled is False
    assert host == "0.0.0.0"
    assert port == 9091


def test_resolve_metrics_config_enabled_by_public_demo() -> None:
    enabled, host, port = metrics.resolve_metrics_config({"RCG_PUBLIC_DEMO": "1"})
    assert enabled is True
    assert host == "0.0.0.0"
    assert port == 9091


def test_resolve_metrics_config_custom_port_enables() -> None:
    enabled, _, port = metrics.resolve_metrics_config({"RCG_METRICS_PORT": "9200"})
    assert enabled is True
    assert port == 9200


def test_resolve_metrics_config_bad_port_falls_back() -> None:
    enabled, _, port = metrics.resolve_metrics_config({"RCG_METRICS_PORT": "not-a-number"})
    assert enabled is True
    assert port == 9091


def test_start_metrics_server_serves_metrics() -> None:
    import socket

    # Grab a free port, then let the server bind it.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    metrics.record_tool_call("check_rules")
    metrics.start_metrics_server("127.0.0.1", port)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
        assert 'rcg_tool_calls_total{tool="check_rules"} 1' in body
        # An unknown path 404s.
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)
        assert exc_info.value.code == 404
    finally:
        # Daemon thread; nothing to join. The server is bound to an ephemeral
        # port and will be cleaned up at process exit.
        pass
