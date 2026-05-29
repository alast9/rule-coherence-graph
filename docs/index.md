# Rule Coherence Graph (RCG)

**Detect conflicts in the rule corpora that govern AI coding agents — before the agent does.**

AI coding agents (Cursor, Claude Code, Cline, Gemini in agent IDEs, custom
LangGraph/Pydantic-AI stacks) are governed by rules spread across many files:
`.cursorrules`, `CLAUDE.md`, `AGENTS.md`, `.agent/rules/*.md`, `memory.md`, and
third-party rule packs. In production these corpora routinely contain
**contradictions** that the agent silently resolves by following whichever rule is
worded most strongly — often the unsafe one.

RCG treats a rule corpus as a **typed graph** instead of flat text: it ingests the
files, extracts each rule into a canonical schema, detects conflicts, scores
coherence, and lets you query, visualize, and fail CI on them.

[Get started](quickstart.md){ .md-button .md-button--primary }
[Use it in your assistant](mcp-clients.md){ .md-button }

## Why it exists

In May 2026 a Gemini coding agent reportedly deleted **28,745 lines** and broke
production after following a third-party rule pack whose directives ("never prompt
for confirmation", "auto-deploy", "grant all permissions") contradicted the
project's own safety rules. No tool modeled the corpus as a system, so the conflict
was invisible until it caused damage.

RCG reconstructs that corpus (`examples/gemini_incident`) and surfaces the
contradictions the agent silently resolved:

![RCG conflicts graph](img/rcg-neo4j-conflicts.png)

## What it does

- **Three detection passes** — *syntactic* (with a human-in-the-loop "approval
  stance" that removes false positives between aligned safety rules), *semantic*
  (embeddings + LLM-as-judge, evidence-bearing), and *precedence* (rules that can
  co-fire with no declared ordering).
- **Coherence score** per corpus, with `--min-score` to gate CI.
- **Accepted-conflicts baseline** to suppress reviewed/intended conflicts.
- **Ingests** `.cursorrules`, Cursor `.mdc`, `CLAUDE.md` / `AGENTS.md` /
  `memory.md` / `.agent/rules/*.md`, and YAML/JSON rule files.
- A **CLI**, an **MCP server** (so agents can check coherence pre-flight), a
  reusable **GitHub Action**, and optional **Neo4j** graph persistence.

!!! note "Analyzes, doesn't enforce"
    RCG checks corpora for internal coherence; it does **not** gate agent execution
    at runtime — that's OPA/Cedar/Microsoft AGT's job, downstream. RCG is the linter
    that runs upstream so a contradiction never reaches them.

Open source (Apache-2.0) · `pipx install rule-coherence-graph` ·
[GitHub](https://github.com/alast9/rule-coherence-graph) ·
[PyPI](https://pypi.org/project/rule-coherence-graph/)
