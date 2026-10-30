---
name: fix-quality
description: Diagnose and repair a failing quality gate at its root instead of suppressing the finding.
---

# Fix a failing gate

This skill is a stub that T03 replaces; its frontmatter is final.

1. Read `AGENTS.md` and the first failure only; rerun its recipe alone, such as
   `just py-lint` or `just lint`.
2. Find the root cause; never weaken a gate, a positive control or the coverage floor.
3. Use `just fix` or `just format` for mechanical repairs, then rerun `just check`.
4. Hand back anything whose fix lies in a frozen file.
