# Benchmark results

Precision / recall for the RCG detection passes on the labeled dataset
[`dataset.jsonl`](dataset.jsonl): **62 rule pairs** (26 labeled `conflict`,
36 labeled `ok`), spread across the `modality`, `approval-stance`, `semantic`,
`precedence`, and `unrelated` categories.

The dataset is **synthetic and illustrative** — hand-written to exercise the
detectors, not sampled from production. Treat the absolute numbers as a behavior
smoke test, not a claim about real-world accuracy.

Rules are built directly from the labeled fields; the LLM extractor is **not**
run, so these numbers measure the *detectors* (syntactic + semantic), not
extraction.

## Configurations

Ground truth = `label == "conflict"`. Per pair:

- `syntactic` = `SyntacticDetector` fires (opposing modality / differing approval
  stance, same action class, overlapping scope).
- `semantic` = embedding cosine ≥ `--sim-threshold` (0.55) **and** the judge
  returns a conflict.
- `combined` = `syntactic OR semantic`.

Precedence pairs (same action, co-firing, no opposing modality) are **excluded**
from precision/recall by design — precedence is about ordering ambiguity, not
pairwise truth. They appear in the per-category breakdown only as negatives. The
harness separately reports that **27** same-action/same-modality pairs in this
dataset would raise a precedence ambiguity.

## Overall results

| Config | Pass | Precision | Recall | F1 |
| --- | --- | --- | --- | --- |
| 1. syntactic only (deterministic) | syntactic | 1.000 | 0.500 | 0.667 |
| 2. + semantic, hashing + MockJudge (deterministic) | semantic | 0.778 | 0.269 | 0.400 |
| 2. + semantic, hashing + MockJudge (deterministic) | combined | 0.867 | 0.500 | 0.634 |
| 3. + semantic, sentence-transformers (all-MiniLM-L6-v2) + MockJudge | semantic | 0.600 | 0.462 | 0.522 |
| 3. + semantic, sentence-transformers (all-MiniLM-L6-v2) + MockJudge | combined | 0.619 | 0.500 | 0.553 |

## `semantic` category — and an honest caveat about the judge

The `semantic` category holds genuine conflicts that share few/no keywords and
have **non-opposing surface modality** (both rules are e.g. `MUST`). The
intent was to show a real embedder recalling these where the lexical one cannot.

| Config | Precision | Recall | F1 |
| --- | --- | --- | --- |
| syntactic only | 0.000 | 0.000 | 0.000 |
| + semantic, hashing (lexical) + MockJudge | 0.000 | 0.000 | 0.000 |
| + semantic, sentence-transformers + MockJudge | 0.000 | 0.000 | 0.000 |

**Recall on this category is 0.000 for both embedders — but the cause is the
judge, not the embedder.** The offline `MockJudge` only declares a conflict on
opposing modality or a differing approval stance; it has no way to see that two
same-modality rules clash in *meaning*. So for all 11 `semantic`-conflict pairs
the MockJudge returns "no conflict" regardless of which embedder surfaced them.
Catching this category requires a real reasoning judge — run config 4
(`--judge anthropic`).

Where the **real embedder does measurably change behavior** is the overall
semantic pass: it clears the 0.55 similarity gate on more pairs than the lexical
hashing embedder (semantic-pass recall **0.269 → 0.462**), sending more candidates
to the judge. That extra recall comes with a precision cost (semantic-pass
precision **0.778 → 0.600**): the real embedder also pulls in semantically
similar but *aligned* `approval-stance` and `modality` ok-pairs, which the
MockJudge then mis-flags on its modality/stance heuristic. The lexical embedder,
by contrast, only fires on near-lexical-duplicate pairs, so it is higher
precision but lower recall.

## Honest reading

The syntactic pass is high precision (1.000) but only half the labeled conflicts
are direct modality/approval contradictions, so its recall caps at 0.500. Adding
the semantic pass **never lowers combined recall** (0.500 either way here),
because with the MockJudge the only true conflicts the semantic pass can catch
are ones the syntactic pass already caught (opposing modality / approval stance).
The real `all-MiniLM-L6-v2` embedder broadens candidate recall — useful in front
of a capable judge — but with the deterministic MockJudge that breadth mostly
adds false positives, dropping combined precision from 0.867 to 0.619. The clear
takeaway: **lexical recall is the floor, a real embedder widens recall, and the
`semantic` category specifically needs a real judge (config 4) to convert that
recall into true positives.**

## Reproduce

```bash
# Config 1 — syntactic only (deterministic):
uv run rcg benchmark benchmarks/dataset.jsonl --embedder hashing --judge mock --no-semantic

# Config 2 — lexical stand-in baseline (deterministic):
uv run rcg benchmark benchmarks/dataset.jsonl --embedder hashing --judge mock --semantic

# Config 3 — real embeddings (downloads all-MiniLM-L6-v2 on first run):
uv run --extra embeddings rcg benchmark benchmarks/dataset.jsonl \
    --embedder sentence-transformers --judge mock --semantic

# Config 4 — real embeddings + Anthropic judge (needs ANTHROPIC_API_KEY).
#   This is the configuration expected to recall the `semantic` category;
#   documented but not run here (requires an API key and network).
ANTHROPIC_API_KEY=sk-... uv run --extra embeddings rcg benchmark benchmarks/dataset.jsonl \
    --embedder sentence-transformers --judge anthropic --semantic
```

Configs 1–3 were run in this environment. Config 4 is documented only.
