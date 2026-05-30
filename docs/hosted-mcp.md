# Hosted MCP demo

Run RCG as a public HTTP service so anyone can paste their own rules and get a
coherence check back — no local install, no filesystem access required. This
guide deploys the MCP server to [Fly.io](https://fly.io) over the streamable
HTTP transport, optionally backed by a free [Neo4j AuraDB](https://neo4j.com/cloud/aura/)
instance for graph persistence.

!!! danger "Security: the demo endpoint is public and unauthenticated"
    By default the hosted server accepts requests from anyone on the internet
    and runs no per-request auth. **Do not paste secrets, credentials, or
    confidential rules into a public instance.** The `check_rules` tool writes
    pasted text to a temporary file that is deleted immediately after the check,
    but the request still traverses the public network.

    Hardening options:

    - Set the `RCG_MCP_TOKEN` secret and keep the URL private (the current build
      documents this risk rather than enforcing a token in code — see
      *Authentication* below).
    - Restrict access with [Fly private networking](https://fly.io/docs/networking/private-networking/)
      and only expose the app inside your organisation.
    - Run your own instance instead of sharing one.

## Cost & guardrails

The public demo targets **under $5/month**. A `shared-cpu-1x` VM with 512MB is
~$3.32/mo at worst-case 24/7, and scale-to-zero (`min_machines_running = 0`)
makes the real cost far lower. A 1GB VM (~$5.92/mo) would exceed the budget, so
the VM size is pinned in `fly.toml`. The graph runs on Neo4j AuraDB Free, which
is $0 but hard-capped at ~50k nodes.

These guardrails are **opt-in** via `RCG_PUBLIC_DEMO=1`. When that switch is not
set (local, stdio, or self-hosted use), the tools are fully unrestricted and
behave exactly as before. `fly.toml` sets `RCG_PUBLIC_DEMO=1` for the hosted
demo.

### Tunable limits

All limits have safe defaults; overriding them is optional.

| Env var | Default | Meaning |
| --- | --- | --- |
| `RCG_PUBLIC_DEMO` | (unset) | Master switch. Truthy (`1`/`true`/`yes`, case-insensitive) enables all guardrails below. |
| `RCG_MAX_INPUT_BYTES` | `50000` | Max UTF-8 byte size of `check_rules` input text. |
| `RCG_MAX_RULES` | `200` | Max rules extracted per `check_rules` call. |
| `RCG_GRAPH_MAX_NODES` | `5000` | Node count at which the graph auto-clears before ingest. |
| `RCG_RATE_LIMIT_PER_MIN` | `30` | Requests allowed per trailing 60s window. |

Each limit is parsed defensively: a missing or invalid value falls back to its
default.

### Graph auto-clear at cap

Before each `ingest_to_graph` write in demo mode, the server counts existing
nodes and estimates the new ones (rules + their distinct parent file nodes). If
`existing + estimated_new` would exceed `RCG_GRAPH_MAX_NODES`, the whole demo
graph is wiped (`DETACH DELETE`) before the new ingest, and the response
includes `"graph_cleared": true`. This keeps the free AuraDB graph from filling
its ~50k node cap and getting stuck. The return summary also includes
`"n_nodes"` (the post-write node count) in demo mode.

### Rate limit is process-global

There is no reliable per-client identity over the MCP transport, so the rate
limiter is **process-wide**: it caps the demo's *total* throughput, not
per-user throughput. The concurrency limits in `fly.toml`
(`[http_service.concurrency]`) provide a complementary cap on simultaneous
requests.

### Error shapes

In demo mode the tools never raise across the MCP boundary; instead they return
a structured error dict of the form
`{"error": "<machine_code>", "message": "<human text>", "limit": <int>}`:

| `error` code | When |
| --- | --- |
| `rate_limited` | The process-wide per-minute request limit was exceeded. |
| `input_too_large` | `check_rules` input exceeded `RCG_MAX_INPUT_BYTES`. |
| `too_many_rules` | Extracted rule count exceeded `RCG_MAX_RULES`. |

The file-reading tools (`check_corpus`, `explain_action`, `score_corpus`,
`ingest_to_graph`) apply only the rate limit in demo mode, since they read
server-side paths rather than caller-supplied text.

## 1. Create a Neo4j AuraDB instance (optional)

Graph persistence is optional — every tool works without it. To enable it:

1. Sign in at [console.neo4j.io](https://console.neo4j.io) and create a free
   **AuraDB** instance.
2. When the instance is created, copy the **Connection URI** — it uses the
   `neo4j+s://` scheme, e.g. `neo4j+s://abcd1234.databases.neo4j.io`.
3. Copy the generated **username** (usually `neo4j`) and **password**. The
   password is shown only once.

RCG passes the URI through unchanged, so the `neo4j+s://` (TLS) scheme that
AuraDB requires is honoured.

## 2. Deploy to Fly.io

From the repository root:

```bash
fly launch --no-deploy   # generates/uses fly.toml; pick a unique app name
fly deploy
```

The bundled `fly.toml` serves over streamable HTTP on port 8080, forces HTTPS,
pins a 512MB `shared-cpu-1x` VM, and scales to zero between sessions to keep the
demo cheap. The hosted image installs only the `[mcp]` extra; the `embeddings`
extra (sentence-transformers/torch) is intentionally omitted to keep the image
lean and fit the 512MB VM — `check_rules` defaults to the mock provider and a
hashing embedder, so no heavy ML dependencies are needed for the public demo.

## 3. Set secrets

All secrets are optional. Set only the ones you need:

```bash
fly secrets set \
  ANTHROPIC_API_KEY=sk-ant-... \
  NEO4J_URI=neo4j+s://abcd1234.databases.neo4j.io \
  NEO4J_USERNAME=neo4j \
  NEO4J_PASSWORD=your-aura-password
```

Never commit secrets — `fly secrets set` stores them encrypted on Fly.

## 4. Connect an MCP client

The hosted endpoint lives at the `/mcp` path:

```
https://rcg-mcp-demo.fly.dev/mcp
```

(replace `rcg-mcp-demo` with your app name).

Claude Code (or any client that supports the streamable HTTP transport) can be
pointed at it with a config entry like:

```json
{
  "mcpServers": {
    "rcg-hosted": {
      "type": "http",
      "url": "https://rcg-mcp-demo.fly.dev/mcp"
    }
  }
}
```

A generic streamable-HTTP MCP client just needs the same URL.

## 5. Try the `check_rules` tool

`check_rules` lets a remote client check a pasted corpus without sharing any
files. Call it with the rules text and a format:

```json
{
  "name": "check_rules",
  "arguments": {
    "rules_text": "# Deploy policy\n- You MUST deploy to production after tests pass.\n- You MUST NOT deploy to production without human approval.\n",
    "format": "markdown"
  }
}
```

It returns the same shape as `check_corpus`:

```json
{
  "n_rules": 2,
  "score": 0.0,
  "by_type": {"contradiction": 1},
  "findings": [
    {
      "type": "contradiction",
      "severity": "...",
      "reason": "...",
      "rule_a": {"text": "...", "file": "CLAUDE.md", "modality": "MUST", "action_class": "deploy.production"},
      "rule_b": {"text": "...", "file": "CLAUDE.md", "modality": "MUST_NOT", "action_class": "deploy.production"}
    }
  ]
}
```

Supported `format` values: `markdown` (default), `cursorrules`, `cedar`,
`rego`, `yaml`. The check runs offline with the deterministic mock extractor.

## Tools available over HTTP

| Tool | Purpose |
| --- | --- |
| `check_rules` | Check a pasted corpus (no filesystem access). |
| `check_corpus` | Check a corpus on the server's filesystem. |
| `explain_action` | Explain which rules fire for a hypothetical action. |
| `score_corpus` | Return only the coherence score. |
| `ingest_to_graph` | Check a corpus and persist it to Neo4j when configured. |

`ingest_to_graph` returns `{"written": false, "reason": "NEO4J_URI not set"}`
when no graph is configured, and a written/failed summary otherwise — it never
crashes the server, even if the database is unreachable.

## Transport selection

The server picks its transport from the environment, defaulting to stdio so
local clients keep working unchanged:

| `RCG_MCP_TRANSPORT` | Transport |
| --- | --- |
| unset / `stdio` | stdio (default) |
| `http` / `streamable-http` | streamable HTTP on `0.0.0.0:$PORT` |
| `sse` | Server-Sent Events on `0.0.0.0:$PORT` |

`PORT` defaults to `8080`.

## Authentication

The MCP HTTP transport in the pinned `mcp` version makes robust per-request
token auth awkward to wire up cleanly, so this build **documents the public risk
above rather than enforcing a token in application code**. Treat any hosted
instance as public unless you put it behind Fly private networking or a
reverse proxy that enforces auth. The `RCG_MCP_TOKEN` secret is reserved for a
future enforced-auth build and is safe to set now as a placeholder.
