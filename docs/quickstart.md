# Quickstart

## Install

```bash
pipx install rule-coherence-graph        # or: uv tool install rule-coherence-graph
```

Zero-install (needs [uv](https://docs.astral.sh/uv/)):

```bash
uvx --from rule-coherence-graph rcg check examples/gemini_incident
```

## Check your rules

```bash
rcg check ./path/to/your/agent/rules
```

Offline by default — the heuristic extractor needs no API key and nothing leaves
your machine. For LLM-quality extraction:

```bash
export ANTHROPIC_API_KEY=sk-...
rcg check ./rules --provider anthropic
```

## Commands

| Command | Description |
| --- | --- |
| `rcg check <path>` | Run the detection passes; exits non-zero on findings. |
| `rcg score <path>` | Print the coherence score + by-type breakdown. |
| `rcg explain "<action>" <path>` | Which rules fire for an action, and do they conflict? |
| `rcg ingest <path>` | Parse + extract + load the corpus into Neo4j. |
| `rcg benchmark [dataset]` | Precision/recall over a labeled set. |

Useful flags: `--semantic` (embedding + judge pass), `--min-score 0.8` (gate on the
coherence score), `--baseline rcg-baseline.json` / `--update-baseline` (suppress
reviewed conflicts), `--no-graph` (skip Neo4j).

## Use it in CI (GitHub Action)

```yaml
permissions:
  contents: read
  pull-requests: write
jobs:
  rule-coherence:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: alast9/rule-coherence-graph@v0.4.0
        with:
          path: .agent/rules
          min-score: "0.8"
```

It runs `rcg check` on the PR and posts the conflict report as a sticky comment.
`pull-requests: write` is required for commenting; `provider: anthropic` needs
`ANTHROPIC_API_KEY` as a repo secret.

## Persist & explore the graph (Neo4j)

```bash
docker compose up -d neo4j      # Neo4j 5.x on bolt://localhost:7687
rcg ingest examples/gemini_incident   # writes Rule / RuleFile / CONFLICTS_WITH
```

Then browse it at <http://localhost:7474> and run, e.g.:

```cypher
MATCH (a:Rule)-[c:CONFLICTS_WITH]-(b:Rule) RETURN a, c, b;
```
