# Security Policy

## Supported versions

RCG is pre-1.0 and ships from `main`. Security fixes are applied to the latest
release on [PyPI](https://pypi.org/project/rule-coherence-graph/) and the current
`main` branch. Older versions are not patched — please upgrade to the latest.

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through GitHub's [private vulnerability reporting](https://github.com/alast9/rule-coherence-graph/security/advisories/new)
(repo **Security** tab → **Report a vulnerability**). If you can't use that, email
**alast9@gmail.com** with the details.

Please include:

- a description of the issue and its impact,
- steps to reproduce (a minimal proof of concept if possible),
- the affected version(s) and your environment.

You can expect an acknowledgement within a few days. Once the issue is confirmed
and a fix is available, we'll coordinate disclosure and credit you (unless you
prefer to remain anonymous).

## Scope notes

RCG is an **analysis** tool: it parses rule corpora and reports conflicts. It does
**not** gate agent execution at runtime, so it is not a runtime security control.
Areas where reports are especially welcome:

- The **hosted MCP demo** (`docs/hosted-mcp.md`) is **public and unauthenticated**
  by default. That trade-off is documented intentionally; reports about the demo
  should focus on issues *beyond* that known limitation (e.g. a way to read other
  users' data, escape the temp sandbox, or bypass the cost guardrails).
- Parsing untrusted rule files (parser crashes, resource exhaustion, path
  traversal).
- The `anthropic` provider's handling of API keys and request data.
