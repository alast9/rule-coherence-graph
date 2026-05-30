"""RCG-specific Prometheus metrics for the hosted MCP demo.

This module is a tiny, dependency-free metrics layer: an in-process counter
registry plus a stdlib HTTP server that renders the counters in the Prometheus
text exposition format. There is **no** dependency on ``prometheus_client`` —
the exposition text is hand-rendered so the hosted image stays lean.

Design mirrors :mod:`rcg.mcp_guard`: pure, lock-guarded, easy to unit-test.

* The :data:`_registry` is a module-level :class:`_Registry`; the convenience
  ``record_*`` functions delegate to it so call sites read cleanly.
* All metric names are pre-declared (see :data:`_KNOWN_COUNTERS`) so
  :meth:`_Registry.render` emits zero-valued series before the first hit, which
  is nicer in Grafana.
* :func:`start_metrics_server` launches a daemon HTTP thread serving
  ``/metrics``; it never crashes the process — a bind failure is logged to
  stderr and the MCP server keeps running.

Recording metrics is always safe (just counters), so the ``record_*`` helpers
run unconditionally from the MCP tools. The HTTP server, by contrast, is only
started for the non-stdio transports (see :func:`resolve_metrics_config` and
``rcg.mcp_server.main``) so local/stdio use is completely untouched.
"""

from __future__ import annotations

import http.server
import sys
import threading
from collections.abc import Mapping

_TRUTHY = {"1", "true", "yes"}

_DEFAULT_METRICS_PORT = 9091
_DEFAULT_METRICS_PATH = "/metrics"
_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# Pre-declared counters: name -> HELP text. ``render`` emits a zero-valued
# series for each so the metric is visible in Grafana before the first event.
_KNOWN_COUNTERS: dict[str, str] = {
    "rcg_tool_calls_total": "Total MCP tool invocations, labelled by tool.",
    "rcg_guard_rejections_total": "Demo guardrail rejections, labelled by reason.",
    "rcg_rules_extracted_total": "Total rules extracted across check/score/ingest calls.",
    "rcg_graph_writes_total": "Successful ingest_to_graph writes.",
    "rcg_graph_clears_total": "Times the demo graph auto-cleared at the node cap.",
    "rcg_graph_write_failures_total": "ingest_to_graph attempts that failed.",
}

# Pre-declared zero-valued label sets, so common series show up immediately.
_PREDECLARED_SERIES: dict[str, tuple[tuple[tuple[str, str], ...], ...]] = {
    "rcg_tool_calls_total": tuple(
        ((("tool", tool),))
        for tool in (
            "check_corpus",
            "check_rules",
            "explain_action",
            "ingest_to_graph",
            "score_corpus",
        )
    ),
    "rcg_guard_rejections_total": tuple(
        ((("reason", reason),))
        for reason in ("input_too_large", "rate_limited", "too_many_rules")
    ),
    "rcg_rules_extracted_total": ((),),
    "rcg_graph_writes_total": ((),),
    "rcg_graph_clears_total": ((),),
    "rcg_graph_write_failures_total": ((),),
}


def _label_key(labels: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    """Normalise a label mapping to a deterministic, hashable, sorted tuple."""
    if not labels:
        return ()
    return tuple(sorted(labels.items()))


def _escape_label_value(value: str) -> str:
    """Escape a label value per the Prometheus exposition format rules."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(label_key: tuple[tuple[str, str], ...]) -> str:
    """Render a sorted label tuple as a ``{k="v",...}`` suffix (or empty)."""
    if not label_key:
        return ""
    inner = ",".join(f'{k}="{_escape_label_value(v)}"' for k, v in label_key)
    return "{" + inner + "}"


def _format_value(value: float) -> str:
    """Render a counter value, using an integer form when it is whole."""
    if value == int(value):
        return str(int(value))
    return repr(value)


class _Registry:
    """A thread-safe in-process registry of named, labelled counters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[tuple[tuple[str, str], ...], float]] = {}
        self._seed()

    def _seed(self) -> None:
        """Populate the known counters with their pre-declared zero series."""
        for name in _KNOWN_COUNTERS:
            series = {key: 0.0 for key in _PREDECLARED_SERIES.get(name, ((),))}
            self._counters[name] = series

    def inc(
        self,
        name: str,
        labels: Mapping[str, str] | None = None,
        amount: float = 1.0,
    ) -> None:
        """Increment ``name`` for the given label set by ``amount``."""
        key = _label_key(labels)
        with self._lock:
            series = self._counters.setdefault(name, {})
            series[key] = series.get(key, 0.0) + amount

    def render(self) -> str:
        """Render all counters in Prometheus text exposition format.

        Output is deterministic: metrics are sorted by name, and each metric's
        series are sorted by their (already sorted) label tuple. Each metric
        gets a single ``# HELP``/``# TYPE`` header followed by one line per
        series.
        """
        with self._lock:
            snapshot = {
                name: dict(series) for name, series in self._counters.items()
            }
        lines: list[str] = []
        for name in sorted(snapshot):
            help_text = _KNOWN_COUNTERS.get(name, name)
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} counter")
            for label_key in sorted(snapshot[name]):
                value = snapshot[name][label_key]
                lines.append(f"{name}{_format_labels(label_key)} {_format_value(value)}")
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        """Clear all counters and re-seed the pre-declared zero series (tests)."""
        with self._lock:
            self._counters = {}
            self._seed()


# Module-level registry shared by the whole process.
_registry = _Registry()


def inc(name: str, labels: Mapping[str, str] | None = None, amount: float = 1.0) -> None:
    """Increment a counter on the shared registry."""
    _registry.inc(name, labels, amount)


def render() -> str:
    """Render the shared registry as Prometheus exposition text."""
    return _registry.render()


def reset() -> None:
    """Reset the shared registry (used by tests for isolation)."""
    _registry.reset()


def record_tool_call(tool: str) -> None:
    """Count one MCP tool invocation for ``tool``."""
    _registry.inc("rcg_tool_calls_total", {"tool": tool})


def record_rejection(reason: str) -> None:
    """Count one demo guardrail rejection for ``reason``."""
    _registry.inc("rcg_guard_rejections_total", {"reason": reason})


def record_rules_extracted(n: int) -> None:
    """Add ``n`` to the total rules-extracted counter."""
    _registry.inc("rcg_rules_extracted_total", amount=float(n))


def record_graph_write() -> None:
    """Count one successful graph write."""
    _registry.inc("rcg_graph_writes_total")


def record_graph_clear() -> None:
    """Count one demo graph auto-clear at the node cap."""
    _registry.inc("rcg_graph_clears_total")


def record_graph_write_failure() -> None:
    """Count one failed graph write attempt."""
    _registry.inc("rcg_graph_write_failures_total")


def resolve_metrics_config(env: Mapping[str, str]) -> tuple[bool, str, int]:
    """Decide whether to serve metrics and on which host/port (pure, testable).

    Returns ``(enabled, host, port)``. The metrics endpoint is enabled when
    either ``RCG_METRICS_PORT`` is set, or ``RCG_PUBLIC_DEMO`` is truthy
    (``1``/``true``/``yes``, case-insensitive) — both signals indicate the
    hosted/HTTP demo. The host is always ``"0.0.0.0"`` so Fly can scrape it.
    The port comes from ``RCG_METRICS_PORT`` and falls back to the default
    (9091) on a missing or invalid value.

    The caller only starts the server for non-stdio transports, so stdio/local
    use is never affected even if these env vars happen to be set.
    """
    raw_port = env.get("RCG_METRICS_PORT")
    enabled = raw_port is not None or env.get("RCG_PUBLIC_DEMO", "").strip().lower() in _TRUTHY
    port = _DEFAULT_METRICS_PORT
    if raw_port is not None:
        try:
            port = int(raw_port.strip())
        except (TypeError, ValueError):
            port = _DEFAULT_METRICS_PORT
    return enabled, "0.0.0.0", port


class _MetricsHandler(http.server.BaseHTTPRequestHandler):
    """Serve ``GET /metrics`` from the shared registry; 404 for anything else."""

    # Set by start_metrics_server so the handler knows which path to serve.
    metrics_path: str = _DEFAULT_METRICS_PATH

    def do_GET(self) -> None:  # noqa: N802 — name mandated by BaseHTTPRequestHandler.
        if self.path != self.metrics_path:
            self.send_response(404)
            self.end_headers()
            return
        body = render().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", _CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Silence the default request logging (keeps stdout clean)."""


def start_metrics_server(host: str, port: int, path: str = _DEFAULT_METRICS_PATH) -> None:
    """Start a daemon HTTP thread serving the metrics endpoint.

    Never raises: a bind failure (e.g. port already in use) is logged to stderr
    and the function returns, so the MCP server keeps running regardless.
    """

    class _Handler(_MetricsHandler):
        metrics_path = path

    try:
        server = http.server.ThreadingHTTPServer((host, port), _Handler)
    except OSError as exc:
        print(f"rcg.metrics: failed to bind {host}:{port}: {exc}", file=sys.stderr)
        return

    def _serve() -> None:
        try:
            server.serve_forever()
        except Exception as exc:  # noqa: BLE001 — never let the metrics thread crash the app.
            print(f"rcg.metrics: server loop stopped: {exc}", file=sys.stderr)

    thread = threading.Thread(target=_serve, name="rcg-metrics", daemon=True)
    thread.start()
