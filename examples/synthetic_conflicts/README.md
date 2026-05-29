# Synthetic conflicts example

A tiny corpus that mixes three rule formats to show RCG ingesting and
cross-checking them together:

- `.cursorrules` (Cursor freeform) — an autonomy directive to auto-merge PRs.
- `rules/deploy.mdc` (Cursor `.mdc` with YAML frontmatter) — requires explicit
  human approval before deploying to production.
- `rules.yaml` (YAML `rules:` list) — a contradictory directive to deploy
  automatically without manual approval.

Run:

```bash
rcg check examples/synthetic_conflicts --provider mock --no-graph
```

The `.mdc` deploy-approval rule and the YAML auto-deploy rule encode opposing
human-in-the-loop stances on the same action, so at least one conflict is
reported.
