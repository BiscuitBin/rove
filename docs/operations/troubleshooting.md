---
title: "Troubleshooting"
kind: "operations"
audience: ["contributor", "maintainer", "operator", "agent"]
canonical_for: ["troubleshooting"]
requires: []
---

# Troubleshooting

Symptoms as headings, causes and fixes as bodies.

## `just check` reports that a recipe changed the worktree

The recipe is the defect, not your change. Checks are read-only; anything that writes
belongs in `.pre-commit-fix.yaml` and runs from `just fix`. The report names which paths
moved. Move the offending hook, or add the generated path to `.gitignore`. Here the
usual paths are a build or tool output that escaped the ignore rules, or a rewritten
`uv.lock`, which means something resolved dependencies instead of reading the lock with
`--frozen`.

## uv runs the wrong Python

`.python-version` holds `3.14`, and uv uses it for `.venv/`. Without it, uv picks the
newest CPython installed, which may be a release newer than CI's. A `UV_PYTHON` set in
your shell overrides the file: if it names 3.13, `uv sync` refuses with
`The requested interpreter resolved to Python 3.13...`, naming the `tooling` group's
`>=3.14` floor. Unset `UV_PYTHON`, or use the
[3.13 run](../how-to/develop-locally.md#the-313-run), which gives 3.13 its own
environment.

## The shared checkers on 3.13: `Failed to spawn: bg-...`

The `tooling` group, which provides `bg-project-check`, `bg-validate-docs`,
`bg-validate-agents` and `bg-ripsecrets`, needs Python 3.14 and is left out of any 3.13
environment. On 3.13, `just check`, `just check-docs` and `just check-agents` therefore
fail with `Failed to spawn` and `No such file or directory`. That is expected: only
`lock-check`, `py-lint`, `py-typecheck`, `coverage` and `wheel-smoke` run on 3.13. Run
the rest on 3.14 ([decision 0001](../decisions/0001-uv-and-hatchling.md)).

## A stale `.venv`

After pulling a moved `uv.lock`, the environment still holds the old versions until
`just sync` installs the new ones; a tool behaving like its previous release is the
usual sign. A worktree that was renamed or moved needs more: the Python scripts in
`.venv/bin/`, the `bg-*` checkers among them, name the interpreter at the old absolute
path in their first line, so they fail to start. Delete `.venv/` and run `just sync`, which
rebuilds it from `uv.lock`.

## `just lock-check` fails

`uv.lock` is stale against `pyproject.toml`: a dependency, a pin or the project's
version moved and the lock was not solved again. Run `just lock`, read the diff, and
commit the lock with the manifest. A new dependency is a decision before it is an edit:
[decision 0005](../decisions/0005-dependency-policy.md) says what it has to justify.

## wheel-smoke reports two wheels in dist

`just wheel-smoke` runs `build`, which empties `dist/` before building, so a second
wheel means something wrote there after that cleanup: a concurrent build, or a manual
copy. Stop that writer and rerun. Do not weaken the exactly-one-wheel guard or pick one
of the matches.

## Coverage fails but everything is tested

Distinguish two cases. If a real path is untested, add the test. If the uncovered branch
cannot be reached by any input, delete the branch. Do not lower the floor. While the
package is this small, one untested branch is enough to breach the floor on its own.

## `just lint` clones or downloads

Every hook environment should already be prepared, so `lint`, and `just check` around
it, never reaches the network. If it does, prek's cache was cleared, or the first run
did not finish preparing it. Run `just initialize` again (in a secondary worktree it
prepares the environments without installing the shim), or `just install-hooks` from
the primary checkout. A failed lychee download is not reported by either, so a later
`just lint` may still fetch it.

## The ripsecrets hook fails to build

prek builds ripsecrets from source with cargo. If no `cargo` is on `PATH`, or rustup has
no default toolchain, the build fails while the hook environments are prepared. Install
a Rust toolchain, or select one for the shell with `RUSTUP_TOOLCHAIN=stable`, and run
`just initialize` again.

## `docs validation: frontmatter <field> disagrees with the manifest`

Almost always list order. The comparison between `docs/manifest.yml` and a page's
frontmatter is order-sensitive, so `["maintainer", "contributor"]` fails against
`["contributor", "maintainer"]`. Copy the order from the manifest. If the field is
`title`, check punctuation: the level-one heading must match it byte for byte as well.

## `agent validation: unexpected managed file`

Something appeared under `.agents/`, `.claude/` or `.codex/` that is neither a declared
skill nor `.claude/settings.json`. If it is local tool state, add it to `.gitignore`:
the inventory reads Git, so an ignored file is invisible to it. If it is real content,
it belongs in `.agents/skills/` with its bridges, or somewhere else entirely.

## Related pages

- [Test and debug](../how-to/test-and-debug.md)
- [Develop locally](../how-to/develop-locally.md)
- [Agent contract](../reference/agent-contract.md)
