#!/usr/bin/env python3
"""Smoke-test the hosted RCG MCP server over the streamable-HTTP transport.

This is a standalone, stdlib-only client (no ``mcp`` package, no ``requests``):
it speaks just enough of the Model Context Protocol to verify that a deployed
RCG MCP server initializes, lists its tools, and returns sensible results from
``check_rules`` (and optionally ``ingest_to_graph``). It is meant to be copied
and run as-is against any RCG deployment.

Usage examples::

    # Smoke-test the public demo (default URL).
    python3 scripts/smoke_test.py

    # Point at your own deployment.
    python3 scripts/smoke_test.py https://my-app.fly.dev/mcp
    python3 scripts/smoke_test.py --url https://my-app.fly.dev/mcp

    # Also exercise ingest_to_graph (needs NEO4J_* configured server-side).
    python3 scripts/smoke_test.py --graph
    python3 scripts/smoke_test.py --graph --path examples/gemini_incident

Exit code is 0 when every check passes and 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "https://rcg-mcp-demo.fly.dev/mcp"
DEFAULT_GRAPH_PATH = "examples/gemini_incident"
PROTOCOL_VERSION = "2025-06-18"

# A tiny markdown corpus with a clear MUST vs MUST_NOT deploy conflict, used to
# verify that check_rules extracts rules and detects the contradiction.
CONFLICT_CORPUS = (
    "# Deploy policy\n"
    "- You MUST deploy to production after tests pass.\n"
    "- You MUST NOT deploy to production without human approval.\n"
)


class MCPError(RuntimeError):
    """Raised when the server returns a malformed or error MCP response."""


class MCPClient:
    """A minimal MCP-over-streamable-HTTP client built on ``urllib``.

    The streamable-HTTP transport is plain HTTP POST of JSON-RPC messages; the
    server may reply with either a single JSON object or a ``text/event-stream``
    (SSE) body whose ``data:`` lines carry the JSON-RPC responses. This client
    handles both. A session id is issued by the server on ``initialize`` (in the
    ``mcp-session-id`` response header) and must be echoed on every later call.
    """

    def __init__(self, url: str, timeout: float) -> None:
        self.url = url
        self.timeout = timeout
        self.session_id: str | None = None
        self._next_id = 0

    # -- low-level transport ------------------------------------------------

    def _request_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _post(self, payload: dict[str, Any]) -> tuple[dict[str, str], bytes]:
        """POST a JSON-RPC payload and return ``(headers, body)``."""
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            # The server may stream the reply as SSE, so advertise both.
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id is not None:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                # Header names are case-insensitive; normalise to lower-case.
                resp_headers = {k.lower(): v for k, v in resp.getheaders()}
                return resp_headers, resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise MCPError(f"HTTP {exc.code} {exc.reason} from {self.url}: {body}") from exc
        except urllib.error.URLError as exc:
            raise MCPError(f"could not reach {self.url}: {exc.reason}") from exc

    @staticmethod
    def _parse_body(body: bytes) -> dict[str, Any]:
        """Extract a single JSON-RPC response from a JSON or SSE body."""
        text = body.decode("utf-8", "replace").strip()
        if not text:
            raise MCPError("empty response body")
        # SSE framing: pick the JSON object from the last non-empty ``data:`` line.
        if text.startswith("data:") or "\ndata:" in text:
            messages: list[dict[str, Any]] = []
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    chunk = line[len("data:") :].strip()
                    if chunk:
                        messages.append(json.loads(chunk))
            if not messages:
                raise MCPError("SSE response carried no data lines")
            return messages[-1]
        # Plain JSON body.
        return json.loads(text)

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and return its ``result`` object."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id(),
            "method": method,
            "params": params,
        }
        headers, body = self._post(payload)
        # initialize hands back the session id we must reuse on later calls.
        if "mcp-session-id" in headers and self.session_id is None:
            self.session_id = headers["mcp-session-id"]
        message = self._parse_body(body)
        if "error" in message:
            raise MCPError(f"{method} returned error: {message['error']}")
        result = message.get("result")
        if not isinstance(result, dict):
            raise MCPError(f"{method} returned no result object")
        return result

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._post(payload)

    # -- MCP handshake + tools ---------------------------------------------

    def initialize(self) -> dict[str, Any]:
        """Run the initialize handshake and send notifications/initialized."""
        result = self._call(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "rcg-smoke-test", "version": "1.0"},
            },
        )
        if self.session_id is None:
            raise MCPError("server did not return an mcp-session-id header")
        # The protocol requires this notification before any tool calls.
        self._notify("notifications/initialized", {})
        return result

    def list_tools(self) -> list[str]:
        """Return the names of the tools the server advertises."""
        result = self._call("tools/list", {})
        tools = result.get("tools", [])
        return [t["name"] for t in tools if isinstance(t, dict) and "name" in t]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool and return its structured result as a dict.

        RCG tools return JSON objects; FastMCP exposes these as
        ``structuredContent`` and/or a JSON text block in ``content``. Prefer
        the structured form, falling back to parsing the first text block.
        """
        result = self._call("tools/call", {"name": name, "arguments": arguments})
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        for block in result.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                return json.loads(block["text"])  # type: ignore[no-any-return]
        raise MCPError(f"tool {name} returned no parseable content")


def _check(label: str, passed: bool, detail: str = "") -> bool:
    """Print a PASS/FAIL line for one check and return ``passed``."""
    status = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"[{status}] {label}{suffix}")
    return passed


def _warn(message: str) -> None:
    """Print a non-fatal warning line."""
    print(f"[WARN] {message}")


def run_smoke_test(url: str, timeout: float, graph: bool, path: str) -> bool:
    """Drive the full smoke test against ``url``; return True if all checks pass."""
    print(f"RCG MCP smoke test → {url}")
    client = MCPClient(url, timeout)
    ok = True

    # 1. Handshake.
    try:
        info = client.initialize()
        server_name = info.get("serverInfo", {}).get("name", "?")
        ok &= _check("initialize", True, f"session established, server={server_name!r}")
    except MCPError as exc:
        return _check("initialize", False, str(exc))

    # 2. tools/list.
    try:
        tools = client.list_tools()
        ok &= _check("tools/list", bool(tools), f"tools={', '.join(tools) or '(none)'}")
    except MCPError as exc:
        ok &= _check("tools/list", False, str(exc))
        tools = []

    # 3. check_rules with a MUST vs MUST_NOT conflict corpus.
    try:
        result = client.call_tool(
            "check_rules", {"rules_text": CONFLICT_CORPUS, "format": "markdown"}
        )
        if "error" in result:
            ok &= _check("check_rules", False, f"guard error: {result['error']}")
        else:
            n_rules = result.get("n_rules", 0)
            findings = result.get("findings", [])
            passed = isinstance(n_rules, int) and n_rules > 0 and bool(findings)
            ok &= _check(
                "check_rules conflict",
                passed,
                f"n_rules={n_rules}, findings={len(findings)}",
            )
    except MCPError as exc:
        ok &= _check("check_rules conflict", False, str(exc))

    # 4. Optional ingest_to_graph.
    if graph:
        try:
            result = client.call_tool("ingest_to_graph", {"path": path})
            written = result.get("written")
            if written is True:
                n_rules = result.get("n_rules", 0)
                n_conflicts = result.get("n_conflicts", 0)
                ok &= _check(
                    "ingest_to_graph",
                    True,
                    f"written=true, n_rules={n_rules}, n_conflicts={n_conflicts}",
                )
                if not n_rules:
                    # Not fatal: the path may simply not be bundled in the image.
                    _warn(
                        "ingest_to_graph wrote 0 rules — the examples/ directory "
                        "may not be bundled in the server image (Dockerfile must "
                        "COPY examples)."
                    )
            else:
                reason = result.get("reason", "unknown")
                ok &= _check("ingest_to_graph", False, f"written={written}, reason={reason}")
        except MCPError as exc:
            ok &= _check("ingest_to_graph", False, str(exc))

    print("\nSUMMARY:", "ALL CHECKS PASSED" if ok else "ONE OR MORE CHECKS FAILED")
    return ok


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the smoke test, and return a process exit code."""
    parser = argparse.ArgumentParser(
        description="Smoke-test a hosted RCG MCP server over streamable HTTP.",
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help=f"MCP endpoint URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--url",
        dest="url_flag",
        default=None,
        help="MCP endpoint URL (alternative to the positional argument).",
    )
    parser.add_argument(
        "--graph",
        action="store_true",
        help="Also call ingest_to_graph (requires NEO4J_* configured server-side).",
    )
    parser.add_argument(
        "--path",
        default=DEFAULT_GRAPH_PATH,
        help=f"Server-side corpus path for --graph (default: {DEFAULT_GRAPH_PATH}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-request timeout in seconds (default: 60).",
    )
    args = parser.parse_args(argv)

    url = args.url_flag or args.url or DEFAULT_URL
    passed = run_smoke_test(url, args.timeout, args.graph, args.path)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
