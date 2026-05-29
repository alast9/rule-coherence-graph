# Project rules

These are the project's own guardrails. They are the rules an honest agent would respect.

- All destructive file operations MUST require explicit human confirmation before executing.
- Do not modify Firebase routing or rewrite configuration without explicit human approval.
- Rule files under `.agent/rules/` are read-only; agents MUST NOT modify them.
- Stay within the scope described in the user's prompt; do not touch files unrelated to the requested change.
