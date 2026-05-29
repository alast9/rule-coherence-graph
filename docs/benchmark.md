# Benchmark

RCG ships a labeled dataset and a `rcg benchmark` harness so the detectors' quality
is **measurable and reproducible** — not just asserted.

```bash
rcg benchmark benchmarks/dataset.jsonl --embedder hashing --judge mock --semantic
```

On the 62-pair labeled set (deterministic config — `mock` judge, lexical embedder):

| pass | precision | recall | F1 |
| --- | --- | --- | --- |
| syntactic | 1.000 | 0.500 | 0.667 |
| combined (lexical embedder + mock judge) | 0.867 | 0.500 | 0.634 |

By category, the syntactic pass scores **1.000 / 1.000** on *approval-stance* and
1.000 / 0.800 on *modality* — perfect precision, and the approval-stance logic that
kills false positives works exactly as intended.

!!! info "An honest finding"
    Non-keyword *semantic* conflicts (rules that disagree without sharing words) need
    the **Anthropic judge** — the deterministic mock judge is the bottleneck there, not
    the embedder. A real (sentence-transformers) embedder widens the semantic pass's
    *candidate* recall (0.269 → 0.462) at a precision cost; converting those to true
    positives needs `--judge anthropic`. We publish this rather than claim a recall
    lift the mock judge masks.

Reproduce the real-embeddings + real-judge numbers:

```bash
pip install 'rule-coherence-graph[embeddings]'
export ANTHROPIC_API_KEY=sk-...
rcg benchmark benchmarks/dataset.jsonl --embedder sentence-transformers --judge anthropic --semantic
```

Full tables, every config, and the complete reading:
**[benchmarks/RESULTS.md on GitHub](https://github.com/alast9/rule-coherence-graph/blob/main/benchmarks/RESULTS.md)**.

!!! warning "Caveats"
    The dataset is small and synthetic/illustrative, and the default embedder is
    *lexical* — install the `[embeddings]` extra for real semantic recall. Treat these
    numbers as a regression signal and a starting point, not a leaderboard.
