---
name: python-change
description: Implement or review a change to the rovo package, its command line or its tests with the lint, type, coverage and wheel-smoke evidence the invariants require.
---

# Change the Python package

This skill is a stub that T03 replaces; its frontmatter is final.

1. Read `AGENTS.md`, its invariants first.
2. Write the failing test under `tests/` before the change under `src/rovo/`.
3. Run `just py-lint`, `just py-typecheck` and `just coverage` until each passes.
4. Run `just wheel-smoke` to prove the installed wheel, then `just check`.
