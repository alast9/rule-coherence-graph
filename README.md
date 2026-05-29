# Rule Coherence Graph (RCG)

[![CI](https://github.com/alast9/rule-coherence-graph/actions/workflows/ci.yml/badge.svg)](https://github.com/alast9/rule-coherence-graph/actions/workflows/ci.yml)

**Detect conflicts in the rule corpora that govern AI coding agents — before the agent does.**

AI coding agents (Cursor, Claude Code, Cline, Gemini in agent IDEs, custom
LangGraph/Pydantic-AI agents) are governed by rules drawn from many files:
`.cursorrules`, `CLAUDE.md`, `AGENTS.md`, `.agent/rules/*.md`, `memory.md`, and
more. In production these corpora routinely contain **contradictions** that the
agent silently resolves by following whichever rule is worded most strongly —
often the unsafe one.

RCG treats a rule corpus as a **typed graph** instead of flat text: it ingests
the files, extracts each rule into a canonical schema, loads them into Neo4j, and
detects conflicts you can query, visualize, and fail CI on.

---

## 30-second demo

```bash
git clone <this-repo> && cd rcg
uv sync
uv run rcg check examples/gemini_incident
```

With no `ANTHROPIC_API_KEY` set, `check` falls back to the offline heuristic
extractor (with a warning) so the demo runs anywhere. It surfaces **7 conflicts**
in the bundled corpus and exits non-zero, e.g.:

```
## 1. CRITICAL — syntactic
_action_class='rules.modify_self'; modalities=MAY vs MUST_NOT_

Rule A (.agent/rules/antigravity-pack.md:11) [MAY rules.modify_self]
> The agent MAY modify its own rule files in `.agent/rules/` when necessary.

Rule B (CLAUDE.md:7) [MUST_NOT rules.modify_self]
> Rule files under `.agent/rules/` are read-only; agents MUST NOT modify them.
```

For real (LLM-backed) extraction:

```bash
export ANTHROPIC_API_KEY=sk-...
uv run rcg check examples/gemini_incident --provider anthropic --no-graph
```

To load the graph into Neo4j as well, drop `--no-graph` and start the DB:

```bash
docker compose up -d neo4j      # Neo4j 5.x on bolt://localhost:7687
uv run rcg ingest examples/gemini_incident   # writes Rule/RuleFile/CONFLICTS_WITH
```

---

## Why this exists

In May 2026 a Gemini agent deleted 28,745 lines of code and fabricated a
recovery report. The root cause was a **rule conflict**: a third-party rules
package shipped directly contradictory directives ("never prompt for
confirmation" alongside "ask strategic questions before executing", plus
"auto-deploy" and "default to granting all permissions"), which collided with the
project's own safety rules. No tool modeled the corpus as a system, so the
conflict was invisible until it caused damage.

`examples/gemini_incident/` is a faithful reconstruction of that corpus. Running
`rcg check` on it surfaces the contradictions that the agent silently resolved.

> RCG **analyzes** corpora; it does not gate agent execution at runtime (use
> OPA/Cedar/Microsoft AGT for that — a documented extension point, not a feature).

---

## Architecture

```
            ┌──────────── CLI (rcg ingest | check) ────────────┐
            │                                                   │
      ┌─────▼─────┐   ┌──────────────┐   ┌────────────┐   ┌─────▼──────┐
      │  Parsers  │──▶│ LLM Extractor│──▶│  Detectors │──▶│  Reports   │
      │ (markdown)│   │ + hash cache │   │ (syntactic)│   │ (markdown) │
      └───────────┘   └──────────────┘   └─────┬──────┘   └────────────┘
                                               │
                                        ┌──────▼──────┐
                                        │    Neo4j    │
                                        │  rule graph │
                                        └─────────────┘
```

- **Parsers** read a file and emit raw rule strings with source metadata. Adding
  a format is a single new parser class — nothing downstream changes.
- **Extractor** turns each raw rule into a canonical `Rule` via a provider
  (`anthropic`, `mock`, or `auto`). Results are cached by content hash + model +
  prompt version, so extraction is deterministic and re-runs are free.
- **Detector** finds conflicts over the in-memory `Rule` list (pure Python).
- **Graph loader** persists rules and `CONFLICTS_WITH` edges to Neo4j idempotently.
- **Report** renders conflicts as GitHub-flavored markdown, preserving original
  (possibly non-English) text alongside the English-normalized summary.

### Canonical rule schema

Every rule normalizes to (`src/rcg/schema.py`):

```
Rule {
  id            # stable hash of raw_text + corpus-relative source path
  raw_text      # original string, verbatim (any language)
  source        { file, line_start, line_end, format, section, original_language }
  trigger       { action_class, scope_pattern, context_conditions }
  directive     { modality: MUST|MUST_NOT|SHOULD|SHOULD_NOT|MAY, action }
  confidence    # extractor confidence 0..1
  tags
}
```

### Conflict detection: the approval-stance insight

The syntactic pass pairs rules with the same `action_class`, overlapping scope,
and opposing modality. But modality alone produces false positives: *"do not
deploy **without** approval"* (MUST_NOT) and *"**require** approval before
deploy"* (MUST) look opposed yet encode the **same** policy.

RCG models a **human-in-the-loop stance** (`requires_human_approval` vs
`bypasses_human_approval`) on `trigger.context_conditions`. For approval-gated
rules it compares stance instead of surface modality — so aligned safety rules
don't conflict, while an "auto-deploy / never prompt" rule correctly conflicts
with a "require confirmation" rule.

---

## CLI

| Command | Description |
| --- | --- |
| `rcg ingest <path>` | Parse, extract, and load a corpus into Neo4j. |
| `rcg check <path>` | Ingest + run the syntactic conflict pass; exits non-zero if any conflict is found. |

Useful flags: `--provider auto\|anthropic\|mock`, `--no-graph` (skip Neo4j),
`--out report.md` (write report to a file).

## Example Cypher

```cypher
// All conflicts, most severe first
MATCH (a:Rule)-[c:CONFLICTS_WITH]->(b:Rule)
RETURN c.severity, c.type, a.raw_text, b.raw_text
ORDER BY c.severity;

// Rules that govern the rule corpus itself (the Gemini meta-failure mode)
MATCH (r:Rule) WHERE r.action_class STARTS WITH 'rules.' RETURN r;
```

---

## Development

```bash
uv sync --extra dev
uv run pytest -q            # unit + offline integration tests
uv run ruff check src tests
uv run mypy                 # strict, src only

# Neo4j-backed integration tests (optional)
docker compose up -d neo4j
RCG_RUN_INTEGRATION=1 uv run pytest tests/integration
```

**Stack:** Python 3.11+, Typer, Pydantic v2, neo4j driver, Anthropic SDK,
pytest/ruff/mypy, packaged with `uv`.

---

## Status & scope

This repo implements the **first vertical slice**: markdown ingestion → LLM
extraction (with cache) → syntactic conflict pass → markdown report, with
optional Neo4j persistence and a faithful incident example that works end-to-end.

Deferred (see [`docs/SPEC.md`](docs/SPEC.md) for the full design): semantic and
precedence detection passes, a per-corpus coherence score, `explain`/`diff`/
`graph export` commands, an HTTP API, additional parsers (`.cursorrules`, `.mdc`,
YAML/JSON), and an embedding provider.

**Honest about limits:** heuristic/LLM extraction has false positives. Every
flagged conflict includes both rules' original text as evidence so a human can
adjudicate; confidence and the source language are always surfaced, never hidden.
