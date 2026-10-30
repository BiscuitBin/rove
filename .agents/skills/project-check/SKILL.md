---
name: project-check
description: Bring a workspace to a state where the full gate runs, and interpret what it reports.
---

# Run the full gate

1. Read `AGENTS.md`. The `Justfile` is the supported interface to the checks; use its
   recipes rather than assembling an equivalent pipeline by hand.
2. Check prerequisites: uv, just, git, and a Rust toolchain whose `cargo` is on `PATH`
   for prek to build the ripsecrets hook. `.python-version` makes 3.14 the tooling
   interpreter, because the shared checkers need it. `just initialize` builds `.venv/`
   from `uv.lock` and prepares the hook environments; in a secondary worktree it skips
   only the hook shim. It downloads, so it needs explicit authorization unless the task
   already grants it.
3. Run `just check`. It runs the eight gates that `pyproject.toml` lists, in order, and
   snapshots the worktree between them: 1 `lock-check`, 2 `lint`, 3 `py-lint`,
   4 `py-typecheck`, 5 `coverage`, 6 `wheel-smoke`, 7 `check-docs`, 8 `check-agents`;
   then `check-clean`.
4. Read only the first failure and rerun the named recipe. Later failures often follow
   from earlier ones.
5. A recipe that changes the worktree is defective: checks are read-only; `just fix`
   and `just format` are where mutation belongs.
6. Hand a failing gate to `fix-quality` rather than working around it.
7. Report success only when `just check` ends with
   `All checks passed and the worktree is unchanged.` and `git status --short` prints
   nothing after the commit. Quote outputs against the commit actually tested, marking
   uncommitted changes when present, with exit status and any outstanding findings.
