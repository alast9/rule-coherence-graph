# Using RCG with your coding assistant (MCP)

RCG ships an MCP server, **`rcg-mcp`**, so your AI coding assistant can check your
agent rule corpus for contradictions **before it acts** — and answer "which rules
fire for this action, and do they conflict?" on demand.

This guide gives copy-paste setup for the popular tools.

## What you get — three tools

| Tool | What it does |
| --- | --- |
| `check_corpus(path, provider="mock", semantic=False)` | Run the conflict passes over a rules directory → findings + coherence score. |
| `explain_action(action, path, scope="*", provider="mock")` | "Which rules fire for this action, and do they conflict?" + a verdict. |
| `score_corpus(path, provider="mock")` | Just the coherence score + by-type breakdown. |

By default the server uses the **offline heuristic extractor** — no API key, and
nothing leaves your machine. For LLM-quality extraction/judging, set
`ANTHROPIC_API_KEY` in the server's environment and pass `provider="anthropic"`.

---

## Step 1 — install the server (once)

**Recommended (stable, pinned):**
```bash
pipx install 'rule-coherence-graph[mcp]'     # provides the `rcg-mcp` command
```

**Zero-install alternative** (needs [uv](https://docs.astral.sh/uv/); re-resolves each launch):
```bash
uvx --from 'rule-coherence-graph[mcp]' rcg-mcp
```

> **PATH gotcha:** GUI apps (e.g. Claude Desktop) often don't inherit your shell
> `PATH`, so they may not find `rcg-mcp` in `~/.local/bin`. If a client says
> "command not found," use the absolute path from `which rcg-mcp` (or `which uvx`),
> or use the `uvx` form below.

## The universal config

Most clients accept this shape (stdio transport):

```json
{
  "mcpServers": {
    "rcg": { "command": "rcg-mcp" }
  }
}
```

Zero-install variant:

```json
{
  "mcpServers": {
    "rcg": {
      "command": "uvx",
      "args": ["--from", "rule-coherence-graph[mcp]", "rcg-mcp"]
    }
  }
}
```

To enable LLM-backed extraction, add an `env` block to the server entry:

```json
"env": { "ANTHROPIC_API_KEY": "sk-ant-..." }
```

---

## Per-assistant setup

### Claude Code (CLI)
```bash
# zero-install
claude mcp add rcg -- uvx --from "rule-coherence-graph[mcp]" rcg-mcp
# …or, if installed via pipx
claude mcp add rcg -- rcg-mcp
```
- Scope: add `-s user` to enable it in every project, or `-s project` to share it via a committed `.mcp.json`.
- Verify with `claude mcp list`, or run `/mcp` inside a session.
- Then ask: *"Use the rcg tools to check `.agent/rules` for conflicts."*

### Claude Desktop
Edit the config file:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add the universal `mcpServers` block. Use the **`uvx` form or an absolute path** to
`rcg-mcp` (Desktop doesn't see your shell `PATH`). Restart Claude Desktop — the
tools appear under the tools/🔌 menu.

### Cursor
Create `.cursor/mcp.json` (project-scoped) or `~/.cursor/mcp.json` (global):
```json
{ "mcpServers": { "rcg": { "command": "uvx", "args": ["--from", "rule-coherence-graph[mcp]", "rcg-mcp"] } } }
```
Open **Settings → MCP** — "rcg" should appear; toggle it on (green dot). In
Agent/Composer, ask it to run the rcg tools.

### VS Code (GitHub Copilot — Agent mode)
VS Code uses the `servers` key (not `mcpServers`). Create `.vscode/mcp.json`:
```json
{ "servers": { "rcg": { "type": "stdio", "command": "uvx", "args": ["--from", "rule-coherence-graph[mcp]", "rcg-mcp"] } } }
```
Or run **Command Palette → "MCP: Add Server"**. Requires Copilot Chat in **Agent**
mode; the tools then show in the tools picker.

### Windsurf (Codeium)
Edit `~/.codeium/windsurf/mcp_config.json` (or **Cascade → MCP → Manage/Configure**):
```json
{ "mcpServers": { "rcg": { "command": "uvx", "args": ["--from", "rule-coherence-graph[mcp]", "rcg-mcp"] } } }
```
Click **Refresh** in the Cascade MCP panel.

### Cline (VS Code extension)
In the Cline panel → **MCP Servers → Configure MCP Servers** (opens
`cline_mcp_settings.json`) → add the universal `mcpServers` block. "rcg" and its
tools appear in the list.

### Zed
Zed uses `context_servers` in `settings.json`:
```json
{ "context_servers": { "rcg": { "command": { "path": "uvx", "args": ["--from", "rule-coherence-graph[mcp]", "rcg-mcp"] } } } }
```

---

## Verify it works
Ask your assistant something like:
- *"Use the rcg `check_corpus` tool on `.agent/rules` and summarize the conflicts."*
- *"With rcg `explain_action`, what rules fire if I deploy to production, and do they conflict?"*

You should see the tool get invoked and a findings/score result come back.

## Notes & troubleshooting
- **Offline by default.** `provider="mock"` needs no key and sends nothing externally. Pass `provider="anthropic"` (+ `ANTHROPIC_API_KEY` in the server `env`) for LLM-quality results.
- **"command not found".** GUI clients may not see `~/.local/bin` — use the absolute path (`which rcg-mcp`) or the `uvx` form.
- **Point it at your rules.** Pass the `path` to your corpus (e.g. `.agent/rules`, `.cursor/rules`, `CLAUDE.md`, or `.` to scan the repo).
- **Config formats evolve.** If a client renamed a key, check its current MCP docs — the `command`/`args` for `rcg` stay the same.

> Want conflict checks in CI instead of (or alongside) your editor? Use the
> reusable **GitHub Action** — see the README's "Use it in CI" section.
