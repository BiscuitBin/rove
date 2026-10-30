---
name: plan-change
description: Plan a change when the scope, affected specifications, risks, or validation need evidence before any code is written.
---

# Plan a change

This skill is a stub that T03 replaces; its frontmatter is final.

1. Read `AGENTS.md`, `tickets/CONVENTIONS.md` and the ticket, and inspect the worktree.
2. Write the observable outcome and the non-goals, and name which invariants the change
   touches.
3. Split the work into steps, each with its test and its page under `docs/`.
4. Name every action that needs explicit authorization, then confirm the plan runs green
   with `just check`.
