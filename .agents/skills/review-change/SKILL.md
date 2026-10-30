---
name: review-change
description: Review a change in this repository against its invariants, specifications, tests, and documentation contract.
---

# Review a change

This skill is a stub that T03 replaces; its frontmatter is final.

1. Read `AGENTS.md` and the ticket the change claims to satisfy.
2. Check the diff against the six invariants and the documentation contract.
3. Run `just check`, and `just check-docs` or `just check-agents` for the surface touched.
4. Report findings by severity with a `file:line` each, and quote the commit tested.
