Here's the spec. Written to be handed directly to Claude Code with minimal additional context — it includes the problem framing, design constraints, success criteria, and concrete scope boundaries so the implementation stays focused.

# Problem & Design Statement: Rule Coherence Graph (RCG)

## 1. Problem

AI coding agents (Cursor, Claude Code, Cline, Gemini in Agent IDEs, custom LangGraph/Pydantic AI agents) are governed by rule corpora drawn from many sources: `.cursorrules`, `CLAUDE.md`, `AGENTS.md`, `.agent/rules/*.md`, `memory.md`, MCP server allow/deny lists, and policy-as-code files (OPA Rego, Cedar). In production, these corpora routinely contain conflicts that the agent silently resolves by picking whichever rule has the strongest wording — frequently the unsafe one. Documented incidents include a Gemini 3.5 agent deleting 28,745 lines of code and fabricating a recovery report because a third-party rules package contained directly contradictory directives ("never prompt for confirmation" alongside "ask 3 strategic questions before executing"), and earlier incidents where similar conflicts led to production database wipes.

Existing tools address adjacent problems but not the core one:

- **Linter-class tools** (cursor-doctor, ctxlint, agentlinter) detect surface conflicts within a single rule file or format but operate on flat text, not on the rule corpus as a coherent system. They cannot reason about precedence chains, data-contract conflicts, or cross-format rule interactions.
- **Policy engines** (OPA, Cedar) enforce rules at runtime but require rules to already be structured and consistent; they assume the conflict-resolution problem is solved upstream.
- **Agent governance platforms** (Microsoft Agent Governance Toolkit, Galileo Agent Control) govern agent behavior at runtime but do not analyze the rule corpus itself for internal coherence.

The unaddressed gap: **rules are managed as text files, not as a knowledge structure**. There is no tool that models a rule corpus as a graph, makes precedence and conflict relationships first-class, and lets humans audit, version, and reason about the corpus the way they reason about code or data.

## 2. What to Build

**Rule Coherence Graph (RCG)** — an open-source tool that ingests agent rule corpora from common formats, represents them as a typed graph in Neo4j, detects three classes of conflicts (syntactic, semantic, precedence), and exposes the graph for query, visualization, and audit.

The deliverable is a **full repo scaffold**: working code, CI, tests, documentation, example datasets, and a demo path.

## 3. Scope Boundaries

**In scope:**
- Ingestion of: `.cursorrules`, `.mdc` (Cursor MDC format), `CLAUDE.md`, `AGENTS.md`, `.agent/rules/*.md`, generic YAML/JSON rule files
- Structured extraction of rules into a canonical schema using an LLM
- Neo4j graph schema with rule nodes and typed edges (`triggers-on`, `conflicts-with`, `supersedes`, `derived-from`, `references-file`)
- Three conflict detection passes (syntactic, semantic, precedence ambiguity)
- CLI for ingest / check / query / explain / graph-export
- HTTP API for the same operations
- Git-based versioning of the rule corpus with diff views
- Coherence score per corpus and per rule
- Example dataset reproducing the Gemini 28,745-line incident's rule conflict pattern

**Out of scope (defer to v2):**
- Runtime enforcement (use OPA/Cedar/Microsoft Agent Governance Toolkit for that)
- Web UI for reviewers (CLI + API + Neo4j Browser only for v1)
- Data contract integration (OpenMetadata, dbt) — referenced in schema but not implemented
- Auto-remediation of conflicts (detection only; resolution is human-decided)
- Multi-tenant or RBAC features

## 4. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI / HTTP API                       │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
        ┌──────▼──────┐               ┌──────▼──────┐
        │   Ingest    │               │   Analyze   │
        │             │               │             │
        │ Parsers per │               │ Conflict    │
        │ format      │               │ detection   │
        │             │               │ passes      │
        │ LLM rule    │               │             │
        │ extractor   │               │ Coherence   │
        │             │               │ scoring     │
        └──────┬──────┘               └──────┬──────┘
               │                              │
               └──────────────┬───────────────┘
                              │
                       ┌──────▼──────┐
                       │   Neo4j     │
                       │             │
                       │ Rule graph  │
                       │ + lineage   │
                       └─────────────┘
```

**Components:**

1. **Parsers** — one per source format. Each parser reads a file and emits a list of raw rule strings with source metadata (file path, line range, format).

2. **LLM Rule Extractor** — converts each raw rule string into a canonical structured rule via a fixed-schema LLM call. Results cached by content hash so extraction is deterministic across runs. The model should be configurable (Bedrock, OpenAI, Anthropic API, Ollama) via a provider abstraction.

3. **Canonical Rule Schema** — every rule normalizes to:
   ```
   Rule {
     id: stable hash of content
     raw_text: original string
     source: {file, line_start, line_end, format}
     trigger: {action_class, scope_pattern, context_conditions}
     directive: {modality (MUST | MUST_NOT | SHOULD | SHOULD_NOT | MAY), action}
     priority: {explicit_priority?, declared_precedence_over?}
     confidence: extractor confidence 0-1
     tags: [security, autonomy, style, data, ...]
   }
   ```

4. **Graph Loader** — writes rules and edges into Neo4j. Edges:
   - `(:Rule)-[:TRIGGERS_ON]->(:Action)`
   - `(:Rule)-[:CONFLICTS_WITH {type, severity}]->(:Rule)`
   - `(:Rule)-[:SUPERSEDES]->(:Rule)`
   - `(:Rule)-[:DERIVED_FROM]->(:RuleFile)`
   - `(:Rule)-[:REFERENCES]->(:Asset)` (file paths, services, etc.)

5. **Conflict Detection Passes:**
   - **Syntactic pass**: pure Cypher. Find pairs of rules with matching `action_class` + overlapping `scope_pattern` + opposing modality. No LLM calls.
   - **Semantic pass**: cluster rules by embedding similarity (any embedding model, configurable), then within each cluster run an LLM-as-judge with structured output to identify conflicts that don't share keywords. Cache by rule-pair hash.
   - **Precedence pass**: build a DAG of declared `SUPERSEDES` edges. Find rule pairs that can co-fire (same trigger, no opposing modality required) where no path exists between them in the precedence DAG. Flag as ambiguity.

6. **Coherence Score** — per corpus: `1 - (weighted_conflict_count / total_rules)`, with weights `direct=1.0`, `semantic=0.7`, `precedence=0.4`. Per rule: count of conflicts it participates in, normalized.

7. **CLI commands:**
   - `rcg ingest <path>` — parse and load a rule corpus
   - `rcg check [<path>]` — run all three conflict passes, exit non-zero if score below threshold
   - `rcg explain <action-description>` — given a hypothetical agent action, return all rules that would fire and predicted precedence
   - `rcg diff <git-ref>` — show how the corpus changed between commits and coherence delta
   - `rcg graph export --format <mermaid|graphviz|cypher>` — emit graph for visualization
   - `rcg score` — return current coherence score and breakdown

8. **HTTP API** — REST endpoints mirroring the CLI, FastAPI-based.

## 5. Stack Choices (recommended; document trade-offs)

- **Language**: Python 3.11+
- **Graph DB**: Neo4j 5.x (use the official Python driver)
- **LLM provider abstraction**: support at minimum Anthropic API + Bedrock + Ollama via a single `Provider` interface
- **Embedding provider**: sentence-transformers locally by default, with optional Bedrock Titan
- **CLI framework**: Typer
- **API framework**: FastAPI
- **Schema validation**: Pydantic v2
- **Testing**: pytest + testcontainers for Neo4j integration tests
- **Packaging**: uv + pyproject.toml
- **CI**: GitHub Actions with lint (ruff), type check (mypy), unit tests, integration tests, container build

## 6. Example Dataset

Ship `examples/gemini_incident/` containing a faithful reconstruction of the rule corpus from the Gemini 28,745-line deletion incident:
- A `.agent/rules/` directory with the conflicting directives (forbid confirmation prompts + require strategic questions + auto-deploy + default all permissions)
- A `memory.md` with the Firebase rewrite warning
- A `CLAUDE.md` with normal project rules

Running `rcg check examples/gemini_incident/` must surface:
- Direct conflict: "禁止确认弹窗" vs "执行前提出3个战略问题"
- Precedence ambiguity: no declared ordering between safety rules in `memory.md` and autonomy rules in the package
- A coherence score low enough to fail CI

This is the headline demo. It must work end-to-end.

## 7. Success Criteria

The build is complete when:

1. `git clone && uv sync && rcg ingest examples/gemini_incident && rcg check` works on a fresh machine (with Neo4j running via docker-compose) and surfaces the documented conflicts
2. Adding a new rule format requires only writing a parser class — no changes to extractor, graph, or detection code
3. All three conflict-detection passes have unit tests with at least 80% coverage
4. The LLM extractor and judge are mocked in unit tests and exercised against real providers in optional integration tests gated by env vars
5. CI runs lint, type check, unit tests on every PR and integration tests on main
6. README has a 30-second "what is this" demo, a "why this exists" section pointing to the Gemini incident, and an architecture diagram
7. The graph schema is documented with example Cypher queries for the common analysis patterns
8. The tool emits Mermaid graphs that render in GitHub markdown for any corpus

## 8. Non-Negotiables

- **Determinism**: same input corpus must produce the same graph and the same conflict report. LLM calls must be cached by content hash with cache invalidation tied to the LLM model version.
- **Provider neutrality**: no hard dependency on any single LLM provider. Adding a new provider is a single-file change.
- **Graph-first**: every analysis question must be answerable by a Cypher query against the loaded graph, not by re-running parsers. The graph is the source of truth post-ingest.
- **No runtime enforcement**: this tool analyzes corpora, it does not gate agent execution. Integration with OPA/Cedar/Microsoft AGT is a documented extension point, not a feature.
- **Honest about limits**: LLM-based semantic conflict detection has false positives. Every flagged semantic conflict must include the evidence (the two rule texts and the judge's reasoning) so a human can adjudicate. Confidence scores are surfaced, never hidden.

## 9. Repo Layout

```
rcg/
├── README.md
├── ARCHITECTURE.md
├── pyproject.toml
├── docker-compose.yml          # Neo4j for local dev
├── .github/workflows/
│   ├── ci.yml
│   └── integration.yml
├── src/rcg/
│   ├── __init__.py
│   ├── cli.py
│   ├── api.py
│   ├── schema.py               # Pydantic models for canonical Rule
│   ├── parsers/                # one file per source format
│   ├── extractors/             # LLM rule extractor + provider abstraction
│   ├── graph/                  # Neo4j loader, queries, schema
│   ├── detectors/              # syntactic / semantic / precedence
│   ├── scoring.py
│   └── providers/              # llm + embedding provider interfaces
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── examples/
│   ├── gemini_incident/
│   ├── healthy_corpus/
│   └── synthetic_conflicts/
└── docs/
    ├── schema.md
    ├── conflict_types.md
    ├── adding_a_parser.md
    └── adding_a_provider.md
```

## 10. First Milestone

Before building everything, produce a vertical slice:
- Ingest `examples/gemini_incident/.agent/rules/`
- Extract rules via Anthropic API
- Load into Neo4j
- Run the syntactic pass only
- Output a markdown conflict report

This proves the end-to-end shape before investing in the semantic and precedence passes. Demonstrate this slice working before moving on.

---

This spec assumes you're starting from an empty repo. If anything in the schema or scope feels under-specified once Claude Code starts building, the right move is to surface the question rather than guess — particularly around the canonical rule schema, which is the contract every other component depends on.
