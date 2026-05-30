# How RCG works — a beginner's guide

This page explains the ideas behind RCG from scratch: what embeddings are (and
the difference between *lexical* and *semantic* ones), how raw rule text becomes a
structured "canonical rule", how conflicts are detected, where the LLM fits, what
Neo4j is actually for, and how the whole thing scales. Every step is shown with a
worked example so you can see the data transform.

No prior ML background is assumed.

---

## The big picture

RCG is a **linter for the rule files that govern AI agents**. Those rules live in
files like `CLAUDE.md`, `.cursorrules`, `AGENTS.md`, or policy files (`.rego`,
`.cedar`). In a big project they pile up and start to **contradict each other** —
and the agent silently follows whichever rule is worded most strongly, sometimes
the unsafe one. RCG finds those contradictions before the agent acts.

It works as a pipeline. Each stage takes the previous stage's output and
transforms it:

```
 raw files → [Parser] → raw rules → [Extractor] → canonical rules
           → [Detectors] → findings → [Score] → a number + a report
                                   ↘ [Neo4j] → a queryable graph
```

Let's walk each arrow with the same running example.

---

## Step 1 — Parsing: files → raw rules

A **parser** reads one file and pulls out the individual rule statements as plain
text, remembering where each came from. It does *no* interpretation — it just
chops the file into rule-sized pieces.

**Input** (a file `CLAUDE.md`):

```markdown
# Deployment
- The agent MUST deploy to production after tests pass.
- The agent MUST NOT deploy to production without human approval.
```

**Output** — a list of *raw rules*. A raw rule is just `{text, source}`:

```json
[
  {
    "text": "The agent MUST deploy to production after tests pass.",
    "source": {"file": "CLAUDE.md", "line_start": 2, "line_end": 2, "format": "markdown"}
  },
  {
    "text": "The agent MUST NOT deploy to production without human approval.",
    "source": {"file": "CLAUDE.md", "line_start": 3, "line_end": 3, "format": "markdown"}
  }
]
```

That's it — raw rules are still English sentences. The machine can't compare them
yet, because "deploy to production" and "production deploy" look like different
strings even though they mean the same thing. That's what Step 2 fixes.

---

## Step 2 — Extraction: raw rules → canonical rules

A **canonical rule** is the same rule rewritten into a fixed, structured shape so
that *any* two rules can be compared field-by-field. This is the heart of RCG.

The canonical schema (simplified):

| Field | Meaning | Example |
| --- | --- | --- |
| `trigger.action_class` | the *kind of action* the rule governs | `deploy.production` |
| `trigger.scope_pattern` | what it applies to | `*` |
| `directive.modality` | MUST / MUST_NOT / SHOULD / SHOULD_NOT / MAY | `MUST` |
| `directive.action` | a normalized English summary | `deploy to production` |
| `trigger.context_conditions` | e.g. approval stance | `["requires_human_approval"]` |
| `raw_text` | the original sentence, kept verbatim | `"The agent MUST deploy…"` |

**Transformation** — our two raw rules become:

```json
Rule A:
  raw_text:   "The agent MUST deploy to production after tests pass."
  trigger:    { action_class: "deploy.production", scope_pattern: "*" }
  directive:  { modality: "MUST",     action: "deploy to production after tests pass" }

Rule B:
  raw_text:   "The agent MUST NOT deploy to production without human approval."
  trigger:    { action_class: "deploy.production", scope_pattern: "*" }
  directive:  { modality: "MUST_NOT", action: "deploy to production" }
  context_conditions: ["requires_human_approval"]
```

Notice what extraction did: it recognized that **both rules are about the same
thing** (`action_class = deploy.production`) even though one said "deploy to
production" and the other "production deploy". Now they line up and can be
compared. This normalization is the whole point.

### Why an LLM here?

Extraction is exactly the kind of fuzzy language task LLMs are good at: read a
messy human sentence, decide its action class, its modality, translate it to
English if needed, summarize it. RCG asks the LLM to fill in the structured
fields.

- **Input to the LLM:** one raw rule's text + its source, plus a system prompt
  describing the schema, and a *tool/function definition* (`record_rule`) whose
  parameters are exactly the schema fields. The LLM is *forced* to call that
  function — so it can't ramble; it must return structured arguments.
- **Output from the LLM:** a JSON object like
  `{"action_class": "deploy.production", "modality": "MUST", "action": "...", "confidence": 0.9, ...}`.
  RCG maps that straight onto a canonical `Rule`.

You don't need the LLM, though. RCG ships an **offline `mock` extractor** that
uses keyword heuristics (sees "MUST", "production", "deploy" → fills the fields).
It's lossy but free and deterministic — great for demos and CI. The LLM
(`--provider anthropic|openai|deepseek|qwen|bedrock`) gives much better accuracy
on real, messy rules.

> **Determinism + caching:** every extraction is cached by
> `hash(rule text) + model + prompt version`. Re-running RCG on an unchanged rule
> costs nothing — it reuses the cached canonical rule. This matters for scale
> (see below).

---

## Step 3 — Detecting conflicts

Now that rules are canonical, RCG runs three independent **detectors**. Each
compares rules and emits *findings*.

### 3a. Syntactic conflicts (the certain ones)

Two rules conflict syntactically when they have the **same `action_class`**,
**overlapping scope**, and **opposing modality** (MUST vs MUST_NOT, etc.).

Our example:

```
Rule A: deploy.production | MUST
Rule B: deploy.production | MUST_NOT
        same action_class ✓   scopes overlap ✓   MUST vs MUST_NOT ✓
→ SYNTACTIC CONFLICT (severity: high)
```

**The clever bit — approval stance.** Naively, "MUST require approval" vs "MUST
NOT proceed without approval" looks like a MUST-vs-MUST_NOT conflict, but they
actually say the *same* thing. So RCG compares an **approval stance**
(`requires_human_approval` vs `bypasses_human_approval`) when present, instead of
raw modality. Two rules that both require approval *don't* conflict; one that
requires it and one that bypasses it *do*. This removes a whole class of false
positives.

No LLM needed here — it's pure field comparison.

### 3b. Precedence ambiguities (the soft ones)

Two rules fire on the same `action_class` + scope, **don't** outright contradict,
but **no ordering is declared** — so at runtime the agent can't tell which wins.
That's a latent bug ("which rule takes priority?"). Lower severity. Also pure
field comparison, no LLM.

### 3c. Semantic conflicts (the subtle ones)

The hard case: two rules that clash in **meaning** but whose structured fields
*don't* line up — e.g. different action classes, no shared keywords. Field
comparison misses these. This is where **embeddings + an LLM judge** come in, and
where the lexical-vs-semantic distinction matters. Next section.

---

## Embeddings, explained

An **embedding** turns a piece of text into a list of numbers (a *vector*) so a
computer can measure how "close" two texts are. Closeness is measured by **cosine
similarity**: ~1.0 = very similar, ~0.0 = unrelated.

RCG uses embeddings only as a **cheap pre-filter** for the semantic detector: out
of all possible rule pairs, find the ones that *look related enough to be worth an
expensive LLM check*. There are two kinds.

### Lexical embedding (the default: `HashingEmbeddingProvider`)

"Lexical" = based on the **actual words/characters**, not meaning. RCG's lexical
embedder uses the *hashing trick*:

1. lowercase and split into tokens: `"deploy to production"` → `["deploy","to","production"]`
2. also take adjacent pairs (bigrams): `"deploy_to"`, `"to_production"`
3. hash each token into one of 256 buckets, count how many land in each bucket
4. normalize the 256-number vector to length 1

Two texts that **share words** get similar vectors. Two texts that mean the same
thing but use **different words** do **not**:

```
"deploy to production"      → shares "deploy","production" with…
"production deployment"     → HIGH lexical similarity ✓ (shared words)

"ship the build live"       → means the same, but…
"deploy to production"      → LOW lexical similarity ✗ (no shared words)
```

It's free, offline, deterministic, needs no model download — which is why it's the
default. But it's blind to paraphrase.

### Semantic embedding (opt-in: `SentenceTransformerEmbeddingProvider`)

"Semantic" = based on **meaning**. It uses a small neural model (default
`all-MiniLM-L6-v2`) trained so that texts with similar *meaning* get similar
vectors, even with zero shared words:

```
"ship the build live"   →  ┐  these now land CLOSE together
"deploy to production"   →  ┘  (high semantic similarity) ✓
```

Install it with `pip install 'rule-coherence-graph[embeddings]'`. It catches
paraphrased conflicts the lexical embedder misses, at the cost of a model download
and more compute.

| | Lexical (hashing) | Semantic (transformer) |
| --- | --- | --- |
| Based on | shared words/characters | meaning |
| Catches paraphrases? | ❌ no | ✅ yes |
| Needs a model? | no | yes (download) |
| Speed | very fast | slower |
| Default? | ✅ yes | opt-in extra |

> **Key point:** the embedder doesn't *decide* conflicts. It only narrows
> millions of possible pairs down to a shortlist of "these look related". The
> actual yes/no conflict decision is made by the **judge**.

### The semantic detector end-to-end

```
1. Embed every rule's action text → vectors
2. For every pair, compute cosine similarity
3. Keep only pairs above a threshold (0.55) ← the embedding pre-filter
4. For each surviving candidate pair, ask the JUDGE: "do these conflict?"
5. Judge returns {is_conflict, severity, reasoning, confidence}
```

The **judge** is an LLM (or the offline `MockJudge`):
- **Input:** the two rules (their text, modality, action_class) + a prompt asking
  "do these conflict in meaning?" + a forced `emit_verdict` tool.
- **Output:** `{is_conflict: true/false, severity, reasoning, confidence}`.

Judge verdicts are **cached per rule-pair** (keyed by the two rule ids + judge
model + prompt version), so re-running never re-pays for an unchanged pair.

---

## Step 4 — Scoring: findings → one number

All findings feed a single **coherence score** in `[0, 1]` (1.0 = perfectly
coherent). The formula is deliberately simple and explainable:

```
penalty = Σ over findings of  type_weight
score   = max(0, 1 − penalty / number_of_rules)
```

Each finding contributes a **type weight** to the penalty (more certain finding
types cost more):

| type | weight |
| --- | --- |
| syntactic | 1.0 |
| semantic | 0.7 |
| precedence | 0.4 |

> **Note:** every finding also carries a `severity` (low/medium/high/critical)
> that is shown in the report so a human can triage — but severity does **not**
> change the score. Only the finding's *type* affects the number. (Folding
> severity into the score is a possible future refinement.)

**Worked example.** Our corpus has 2 rules and 1 finding (a *syntactic*
conflict, reported at *high* severity):

```
penalty = 1.0 (syntactic type weight)
score   = max(0, 1 − 1.0 / 2) = 1 − 0.5 = 0.50
```

This matches what the live server returns for this exact corpus: `score: 0.5`.

Dividing by the rule count means a large corpus isn't punished just for being
large — one bad pair in 2 rules hurts more than one bad pair in 200. You gate CI
with `--min-score 0.8` (fail the build if coherence drops below 0.8).

---

## What is Neo4j for? (Is it only visualization?)

**No — but it is optional, and detection does not need it.**

Important: **all conflict detection happens in pure Python, in memory.** RCG loads
the canonical rules into a list and the detectors loop over them. You can run
`rcg check` with `--no-graph` and get every finding without any database.

Neo4j is a **graph database**. RCG can *persist* the result into it:
- **Nodes:** each `Rule` and each `RuleFile`.
- **Edges:** `CONFLICTS_WITH` between rules that a detector flagged.

So Neo4j gives you three things beyond a one-shot CLI run:

1. **Visualization** — open Neo4j Browser and literally see the conflict graph
   (`MATCH (a:Rule)-[c:CONFLICTS_WITH]-(b:Rule) RETURN a,c,b`). Great for "show me
   the mess".
2. **Querying** — ask graph questions the CLI doesn't: "which rule conflicts with
   the most others?", "show all conflicts touching `deploy.production`", "which
   files are involved in conflicts?". These are Cypher queries over the graph.
3. **Persistence / history** — a durable store you can diff over time or share
   across a team, rather than re-deriving everything each run.

If you only want a pass/fail CI gate, skip Neo4j (`--no-graph`). If you want to
*explore and explain* the conflicts, Neo4j earns its keep. It is a presentation
and analysis layer, not part of the detection algorithm.

---

## Scaling to many rules

Two different costs scale very differently. Knowing which is which is the key to
scaling RCG.

### Cost 1 — Extraction (the expensive, LLM-bound part)

One LLM call per *new or changed* rule. This dominates wall-clock time and money.

The saving grace is the **extraction cache**: a rule is only re-extracted if its
text (or the model/prompt version) changed. So on a stable corpus, extraction is a
**one-time cost**; subsequent runs are nearly free.

To scale extraction:
- **Cache** (built in) — unchanged rules cost nothing on re-runs.
- **Parallelize** the LLM calls (the current `extract_all` is sequential; batching/
  concurrency is the obvious lever for large first-time ingests).
- **Use the offline mock** for fast pre-checks, the LLM for the real audit.

### Cost 2 — Detection (the cheap, CPU-bound part)

The detectors compare **every pair of rules** — that's `O(n²)` comparisons for `n`
rules. But each comparison is a few field checks or one cosine calculation
(microseconds). So:

- 100 rules → ~5,000 pairs → milliseconds.
- 1,000 rules → ~500,000 pairs → still well under a second for syntactic/precedence.
- The **semantic** pass adds, per candidate pair over the similarity threshold,
  one **judge** call — but those are LLM calls, cached per pair. So semantic cost
  is "number of *related-looking* pairs not yet judged", not all `n²`.

If `n` gets very large (tens of thousands of rules), the `O(n²)` pairwise loops
are the thing to optimize — typically by **blocking**: only compare rules that
share an `action_class` (group first, compare within groups), which turns `n²` into
the sum of much smaller per-group squares. RCG doesn't do this yet; it's the
natural next optimization.

### Do you have to re-check everything when one rule changes?

Today: **`rcg check` recomputes the full pass each run** — but most of the work is
cached, so it's not as wasteful as it sounds:

- **Extraction:** only the changed rule is re-extracted (cache hit on all others).
- **Semantic judging:** only pairs involving the changed rule need new verdicts
  (every other pair is a cache hit).
- **Syntactic + precedence detection:** these re-run fully, but they're pure-Python
  microsecond comparisons, so a full recompute is cheap.

So in practice a one-rule change costs ≈ **1 extraction call + (a few) judge calls
for that rule's related pairs + a fast full in-memory scan** — not a full
re-extraction. A truly *incremental* detector (only re-examine pairs touching the
changed rule) is a possible future optimization, but the caches already remove the
expensive part.

The **accepted-conflicts baseline** (`--update-baseline` / `--baseline`) is the
other half of change management: once you've reviewed and accepted certain
conflicts, RCG suppresses them and only surfaces *new* ones on later runs.

---

## A formula to estimate check time

Let:

- `n` = number of rules
- `c` = number of rules **not** already in the extraction cache (new/changed)
- `L` = average LLM latency per extraction call (e.g. ~1–3 s for a hosted model)
- `p` = number of candidate pairs over the similarity threshold **not** already
  judged (semantic pass only; 0 if you don't pass `--semantic`)
- `J` = average judge LLM latency per pair

Then a single `rcg check` run takes roughly:

```
T  ≈  c · L                ← extraction of new/changed rules (LLM, dominant)
   +  p · J                ← semantic judging of new candidate pairs (LLM, if --semantic)
   +  k · n²               ← in-memory pairwise detection (k ≈ microseconds)
   +  (graph write, if not --no-graph: ~linear in nodes+edges)
```

Reading the formula:

- **First full run** on `N` rules with the LLM: `c = N`, so `T ≈ N · L` — the LLM
  calls dominate completely. 500 rules × 2 s ≈ ~17 minutes sequentially (and this
  is exactly why parallelizing extraction is the big win).
- **Re-run after editing 1 rule:** `c = 1`, `p` = a handful → `T ≈ L + few·J +
  microseconds` — seconds, not minutes. The cache is doing the heavy lifting.
- **Offline mock provider** (`L`, `J` ≈ microseconds): the whole thing collapses to
  the `k · n²` term — sub-second even for thousands of rules. Great for CI smoke
  checks; use the LLM for the authoritative audit.

Rule of thumb: **if you're using an LLM, your check time is `≈ (new-or-changed
rules) × (LLM latency)`. Everything else is noise** until you reach tens of
thousands of rules, at which point the `n²` detection loops start to matter and
blocking-by-action-class is the fix.

---

## Try it yourself

```bash
# Offline, instant — see the canonical rules + findings on the bundled example
uvx --from rule-coherence-graph rcg check examples/gemini_incident   # (from a checkout)

# Add the semantic pass with a real embedding model
pip install 'rule-coherence-graph[embeddings]'
rcg check ./rules --semantic

# LLM-quality extraction
export ANTHROPIC_API_KEY=sk-...
rcg check ./rules --provider anthropic

# Persist to Neo4j and explore the graph
docker compose up -d neo4j
rcg ingest ./rules
# then in Neo4j Browser: MATCH (a:Rule)-[c:CONFLICTS_WITH]-(b:Rule) RETURN a,c,b
```

See also: [Design & schema](SPEC.md) for the full data model, and
[LLM providers](providers.md) for swapping models.
