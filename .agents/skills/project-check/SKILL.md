---
name: project-check
description: Bring a workspace to a state where the full gate runs, and interpret what it reports.
---

# Run the full gate

This skill is a stub that T03 replaces; its frontmatter is final.

1. Read `AGENTS.md`. The `Justfile` is the interface to every check.
2. Run `just initialize` once per worktree; it downloads, so it needs explicit
   authorization unless the task grants it.
3. Run `just check` and read only its first failure; rerun that recipe alone.
4. Report green only when `just check` ends with
   `All checks passed and the worktree is unchanged.`
