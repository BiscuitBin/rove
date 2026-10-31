---
title: "Quality gates"
kind: "reference"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["quality_gates"]
requires: []
---

# Quality gates

`just check` runs the ten gates `[tool.biscuit-games-tooling] recipes` lists in
`pyproject.toml`, in this order, and snapshots the worktree between each one. A recipe
that modifies a file Git does not ignore fails the run, because checks are read-only;
an ignored path such as `target/` or `dist/` is outside the snapshot.

| Order | Gate | Proves |
| --- | --- | --- |
| 1 | `lock-check` | `uv.lock` matches `pyproject.toml`, checked offline without writing. |
| 2 | `lint` | Every hook in `.pre-commit-config.yaml` passes over all tracked files: file hygiene, EditorConfig, markdownlint, typos, offline links, shellcheck, actionlint, ripsecrets, and the Python and contract hooks. |
| 3 | `py-lint` | ruff sees the package, its lint (`select = ["ALL"]`) and format checks pass, and the positive control fires. |
| 4 | `py-typecheck` | mypy, strict, passes over `src`, `tests` and `scripts`, and the positive control fires. |
| 5 | `coverage` | The suite passes under coverage, and coverage of `src/rovo/**`, lines and branches combined, is at least 95 per cent. |
| 6 | `wheel-smoke` | A freshly built wheel installs and works offline in a new environment: first alone, with no dependencies, then with the locked runtime closure. |
| 7 | `check-docs` | Markdown, spelling and local links pass, then the documentation contract. |
| 8 | `check-agents` | `AGENTS.md`, the adapters, the skills and their bridges satisfy the agent contract. |
| 9 | `check-specs` | Every module under `docs/specs/` reports an empty `diagnostics` array to `allium check`. |
| 10 | `analyse-specs` | Every module reports an empty `findings` array to `allium analyse` too. |

After these ten, `check-clean` compares the worktree with the snapshot taken at the
start, and a green run ends with `All checks passed and the worktree is unchanged.`

## Positive controls

A gate that cannot fire reports a pass nobody earned. Each guard below is part of its
recipe, so it runs on every `just check`:

| Gate | Guard |
| --- | --- |
| `py-lint` | `ruff check --show-files` must list `src/rovo/__init__.py`, because ruff exits 0 on no files. Then `tests/fixtures/py-lint-violation/ruff.py` must exist and ruff must reject it with exit status 1, naming `F401` and `E501`, the fixture's own violations. Exit 2 is a tool error, not a fired control. |
| `py-typecheck` | mypy must reject `tests/fixtures/py-lint-violation/mypy.py` with exit status 1. Exit 2 is a usage or I/O error, not a fired control. |
| `coverage` | `coverage erase` runs first, so no stale data file counts toward the floor. |
| `wheel-smoke` | `dist/` is emptied before the build, and exactly one wheel must exist, so a stale wheel cannot be smoked. The first install has no dependencies, and a recording import finder fails the run if `import rovo` attempts any import outside `rovo` and the standard library. The installed file list and metadata must match exactly, so a wheel that ships tests, loses `py.typed` or gains a licence field fails. |
| `check-specs`, `analyse-specs` | Neither exit code is the verdict. `allium check` exits 0 on an `info` diagnostic and `allium analyse` keys its status on findings alone, so `bg-run-allium` reads the JSON arrays instead, demands both keys in every block, and compares the modules reported against the `.allium` files on disk, so a module the tool dropped in silence fails. allium's exit 2 means it resolved no module at all and is a failure, not a pass; a non-zero exit beside an empty report is a tool fault, not a pass either. The pinned binary is run from `.tools/bin` by path and version-checked first. |

`ruff.toml` and `mypy.ini` exclude the fixtures from normal discovery, so the package
gates stay clean; both tools still check a file named explicitly, which is how the
controls run. `lock-check`, `lint`, `check-docs` and `check-agents` carry no built-in
control: each fails on any finding it reports, and nothing in the recipe proves it saw
its inputs.

Gates 9 and 10 cost the gate something real: the pinned `allium` binary lives in the
gitignored `.tools/bin/`, a per-worktree install, so a worktree that has never run
`just initialize` fails `just lint` (whose hooks run the same two checks) and
`just check` until `just install-allium` puts one there. The alternative was a gate that
skipped itself whenever its tool was absent, which asserts nothing.
[Decision 0010](../decisions/0010-project-managed-allium-cli.md) is the record; a
diagnostic may be waived only where the checker itself is wrong, on the terms in
[Work with the specifications](../how-to/work-with-the-specs.md), and a finding cannot
be waived at all.

## Outside the gate

`py-test`, `build`, `format`, `fix`, `audit` and `check-links-online` are not gates.
`build` runs inside `wheel-smoke`; `audit` and `check-links-online` need the network.
On Python 3.13 ([the 3.13 run](../how-to/develop-locally.md#the-313-run)) only
`lock-check`, `py-lint`, `py-typecheck`, `coverage` and `wheel-smoke` run, because the
runner, both validators and the allium runner need 3.14.

## Related pages

- [Commands](commands.md)
- [Quality philosophy](../explanation/quality-philosophy.md)
- [Testing](testing.md)
