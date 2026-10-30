---
name: fix-quality
description: Diagnose and repair a failing quality gate at its root instead of suppressing the finding.
---

# Fix a failing gate

1. Read `AGENTS.md`, then reproduce with the narrowest recipe: `just check` names
   the failed recipe; run that one alone and read its first failure.
2. Dispatch on which gate failed, in `just check`'s order:
   - `lock-check` — `uv.lock` disagrees with `pyproject.toml`, usually after a manifest
     edit. Run `just lock`, a network recipe needing explicit authorization, and read
     the `uv.lock` diff before accepting it.
   - `lint` — a hook failed; `just lint` names it. Hooks `py-lint` and `py-typecheck`
     go to their gate's line below; `validate-docs` goes to `check-docs`,
     `validate-agents` to `check-agents`. For the rest (whitespace, Markdown, typos,
     links, shell, workflows, secrets), run `just fix` for automatic repairs, then fix
     the remainder by hand. Remove a secret ripsecrets found; never allowlist it.
     Hooks that take file names see only files Git tracks, so they check a new file
     once it is added; `py-lint` and `py-typecheck` scan the tree themselves and already
     see an untracked file.
   - `py-lint` — a ruff finding or unformatted code. Run `just format`, then fix the
     rest by hand. A rule wrong for one line gets `# noqa: RULE  reason`; a per-file
     ignore in `ruff.toml` carries a comment. Never add a rule to the global `ignore`
     list in `ruff.toml` without a comment and a review. "ruff did not see the
     package" means an exclude emptied the gate. Leave
     `tests/fixtures/py-lint-violation/ruff.py` failing: it is the positive control.
   - `py-typecheck` — a mypy error under strict. Run `just py-typecheck` and fix the
     type; a `# type: ignore[code]` carries a reason, and `mypy.ini` stays strict.
     Leave `tests/fixtures/py-lint-violation/mypy.py` failing: it is the positive control.
   - `coverage` — a failing test or a total below the floor. Run `just py-test` to
     reproduce a failure; pytest turns warnings into errors. Below the floor, add the
     missing test; never lower `coverage_floor` in the `Justfile`.
   - `wheel-smoke` — the installed wheel misbehaves. Run `just wheel-smoke` and read
     which step failed: `api` means `import rovo` reached a non-standard-library module
     (invariant 1), the version disagrees with the metadata, or `py.typed` is missing;
     `cli` means `python -m rovo --version` or the console script failed. A network
     error is a defect in the recipe: the smoke installs offline.
   - `check-docs` — a Markdown, typos or link hook, or `bg-validate-docs`. Run
     `just check-docs`; a frontmatter disagreement with `docs/manifest.yml` is often
     list order, which the comparison checks. Repair the owning page and its entry.
   - `check-agents` — inventory, a required phrase in `AGENTS.md`, or a bridge whose
     body or frontmatter differs from the canonical skill. Run `just check-agents`;
     bridges and adapters stay thin.
3. Distinguish an unreachable branch from an untested one: remove defensive code no
   input can reach instead of covering it with a contrived test.
4. Never disable a gate to make a run green. A suppression is a last resort: one rule,
   one line, with a stated reason.
5. A recipe that changes the worktree is defective, and `check-clean` reports it after
   the gates. Repair the recipe within the ticket's scope, or hand it back if it is
   frozen or owned by another lane.
6. Run the narrow recipe, then `just check` to confirm nothing else moved.
