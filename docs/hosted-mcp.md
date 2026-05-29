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
and scales to zero between sessions to keep the demo cheap.

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
