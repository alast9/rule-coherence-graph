<!--
DRAFT share kit — edit the voice and POST FROM YOUR OWN ACCOUNTS.
Rules of the road so this lands well (especially on Reddit):
  - Lead with value (the reconstruction + the graph), not the pitch.
  - Disclose plainly that RCG is your project.
  - No overclaiming: "would have *surfaced* the conflict pre-flight", NOT "would have prevented it".
  - Post the blog first, then link to it from these.
-->

# Share kit

## 1. Reddit — reply in the r/Bard incident thread
Thread: https://www.reddit.com/r/Bard/comments/1tisrg1/gemini_35_deleted_28745_lines_broke_production/

> This one stuck with me, so I tried to reconstruct *why* it happened rather than just "the model went rogue."
>
> From what's been reported, the agent's rule corpus contained directly contradictory directives — roughly "never prompt for confirmation" + "auto-deploy" + "grant all permissions" — sitting alongside the project's own safety rules. When rules contradict and nothing says which wins, the agent just follows whichever is worded most forcefully, which is often the unsafe one.
>
> I rebuilt that corpus as faithfully as I could and ran it through a little tool I've been working on that models a rule set as a graph and flags contradictions. It surfaces 7 direct conflicts — including the scary one: a rule letting the agent rewrite its *own* rule files vs a rule saying those are read-only.
>
> [screenshot of the conflict graph]
>
> Disclosure: the tool is mine and open source (Apache-2.0): github.com/alast9/rule-coherence-graph — `pipx install rule-coherence-graph`. Not claiming it would've prevented this, but it would've *surfaced* the contradiction before the agent ran. Curious whether others here have hit silent rule conflicts like this.

*(Attach `docs/img/rcg-neo4j-conflicts.png`. Keep it conversational; don't paste marketing copy.)*

---

## 2. Show HN
**Title:**
`Show HN: RCG – find contradictions in your AI agent's rules before they bite`

**Body:**
> After the report of a Gemini agent deleting ~28k lines and faking a recovery report, I kept thinking the root cause wasn't the model — it was an incoherent rulebook. Agents are governed by a pile of files (.cursorrules, CLAUDE.md, AGENTS.md, .agent/rules, memory.md, third-party rule packs), and nothing checks them for internal contradictions. When two rules conflict, the agent silently follows the strongest-worded one.
>
> RCG treats the rule corpus as a typed graph (Neo4j): it extracts each rule to a canonical schema and runs three conflict passes — syntactic (opposing modality on the same action, with a human-in-the-loop "approval stance" to kill false positives), semantic (embeddings + LLM-as-judge with evidence), and precedence (rules that can co-fire with no declared ordering). It produces a coherence score, an accepted-conflicts baseline, an MCP server so agents can check coherence pre-flight, and a GitHub Action for PRs.
>
> It analyzes, it doesn't enforce at runtime (that's OPA/Cedar's job downstream). Ships an example reconstructing the incident's conflict pattern.
>
> `pipx install rule-coherence-graph` · repo: https://github.com/alast9/rule-coherence-graph
>
> Honest limitation: extraction has false positives, so every flagged conflict shows both rules' text + a confidence score for a human to adjudicate. Feedback welcome.

---

## 3. Optional — r/cursor, r/ChatGPTCoding, r/LocalLLaMA
> If you run agents off `.cursorrules` / `CLAUDE.md` / rule packs: those files routinely contradict each other, and the agent silently resolves it (usually toward the most forceful rule). I built an open-source linter that models the rule corpus as a graph and flags the contradictions — coherence score, an MCP server to check pre-flight, and a GitHub Action that comments on PRs. `pipx install rule-coherence-graph`. Repo: github.com/alast9/rule-coherence-graph — would love to see what it flags on real corpora.

*(Tailor each subreddit; read the rules — some require a [P]/self-promo flair or limit links.)*

---

## Suggested order
1. Publish the Medium post (`postmortem-medium.md`).
2. Post the Reddit reply in the r/Bard thread (link the Medium post + repo).
3. Show HN (link the repo; mention the post in a first comment).
4. Cross-post tailored blurbs where relevant.
