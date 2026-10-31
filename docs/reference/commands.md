---
title: "Commands"
kind: "reference"
audience: ["contributor", "maintainer", "operator", "agent"]
canonical_for: ["command_reference"]
requires: []
---

# Commands

`just --list` prints the live set; `just --show <recipe>` prints one recipe's text. This
page says what each recipe is for. The `Justfile` is the supported interface: if
something is worth running twice, it belongs there rather than in a shell history.
Every tool runs through `uv run --frozen`, which never resolves and never rewrites
`uv.lock`, except the pinned `allium` binary, which `plan-spec` runs by path from
`.tools/bin/`.

`initialize`, `sync`, `lock`, `lock-upgrade`, `install-hooks`, `install-allium`,
`audit` and `check-links-online` are the network recipes. Initialization fills the
caches and installs the allium binary; after it, `check` needs no network. Setup recipes and the recipes that write files sit
outside `check`.

## Setup

| Recipe | Purpose |
| --- | --- |
| `default` | Print the recipe list when `just` has no arguments. |
| `initialize` | Run `scripts/initialize.sh`: `uv sync --locked`, then `install-allium`, then `install-hooks` in the primary checkout, or, in a secondary worktree, prepare both hook configurations and warm lychee without installing the shim. Never formats, stages, commits, tags or pushes. |
| `sync` | Install the environment exactly as `uv.lock` pins it (`uv sync --frozen`). Network on a cold cache. |
| `lock` | Relock after a `pyproject.toml` edit (`uv lock`). Writes `uv.lock`; read the diff. |
| `lock-upgrade` | Move every locked version as far as `pyproject.toml` allows (`uv lock --upgrade`). Writes `uv.lock`. |
| `lock-check` | Fail when `uv.lock` disagrees with `pyproject.toml` (`uv lock --check --offline`). Never writes. |
| `install-hooks` | Install the prek shim into `.git/hooks`, prepare both hook configurations, and run lychee to download its binary, failing unless the version `.pre-commit-config.yaml` pins is present (three tries). Fails first, offline, when lychee's `# lychee-vX.Y.Z` rev comment and `LYCHEE_VERSION` disagree. Primary checkout only: in a secondary worktree it exits 2 before touching anything. |
| `install-allium` | Download, verify and install the pinned `allium` binary into `.tools/bin/`, which Git ignores (`bg-install-allium`). Version-checks first, so a present pin downloads nothing. Over the network; `uv.lock` cannot name a binary ([decision 0010](../decisions/0010-project-managed-allium-cli.md)). |

## Format and repair

| Recipe | Purpose |
| --- | --- |
| `format` | Apply ruff's safe fixes, then ruff's formatter. Writes files. |
| `fix` | Run the fixer configuration, `.pre-commit-fix.yaml`, twice (the first pass may fail on what a later fixer repairs), then `lint`. Writes files. |

## Check

| Recipe | Purpose |
| --- | --- |
| `lint` | Run every hook in `.pre-commit-config.yaml` over all tracked files, read-only. |
| `py-lint` | ruff lint and format check; require the package in ruff's file list; require the positive control to fail with exit 1 naming `F401` and `E501`. |
| `py-typecheck` | mypy over the files `mypy.ini` names; require the positive control to fail with exit 1. |
| `py-test *args` | Run pytest, passing any arguments through. Quick and uncovered; not a gate. |
| `coverage` | Run the suite under coverage, combine, enforce the floor (`coverage_floor`, 95), and write `target/coverage.xml`. |
| `build` | Empty `dist/`, then build the sdist and the wheel offline. |
| `wheel-smoke` | After `build`: require exactly one wheel, install it alone into a fresh `target/wheel-smoke/venv` and run the `api` smoke, then install the locked runtime closure from the cache and run the `cli` smoke and `rovo --version`. Offline. |
| `audit` | Check the locked versions for known vulnerabilities (`uv audit --frozen`). Needs the network; outside `check`. |

## Documents

| Recipe | Purpose |
| --- | --- |
| `check-docs` | markdownlint, typos and offline links over all tracked files, then the documentation contract (`bg-validate-docs`). |
| `check-agents` | Validate `AGENTS.md`, the two adapters and the fourteen skills with their bridges (`bg-validate-agents`). |
| `check-specs` | `allium check` over `docs/specs/` through `bg-run-allium`. Asserts that every module reports an empty `diagnostics` array; anything reported is a regression. Waiver terms: [Work with the specifications](../how-to/work-with-the-specs.md). Gate 9. |
| `analyse-specs` | `allium analyse` over `docs/specs/` through `bg-run-allium`: the same structural diagnostics plus data flow, reachability, deadlocks and conflicts. Asserts that both arrays are empty; a finding cannot be waived, so any finding is a regression. Gate 10. |
| `plan-spec <module>` | Print the raw JSON test obligations for `docs/specs/<module>.allium`; give the module name without the extension. Plans that module alone, reading no imports, so plan imported modules separately. A suggestion list: asserts nothing, writes nothing and is outside `just check`. Runs `.tools/bin/allium` by path, so it needs the pinned binary from `just install-allium` and never falls through to another `allium` on `PATH`. |
| `check-links-online` | Resolve external links (the manual `lychee-online` hook). Needs the network; outside `check`. |

## Aggregate

| Recipe | Purpose |
| --- | --- |
| `check` | The complete gate (`bg-project-check run`): the ten recipes `pyproject.toml` lists, in order, with the worktree snapshotted between each, then `check-clean`. |
| `check-clean baseline=""` | Standalone, require a clean Git worktree; given a baseline file (as `check` passes one, last), require the worktree to equal the snapshot taken at the start of the run. |

The gate order is `lock-check`, `lint`, `py-lint`, `py-typecheck`, `coverage`,
`wheel-smoke`, `check-docs`, `check-agents`, `check-specs`, `analyse-specs`. A green
run ends with
`All checks passed and the worktree is unchanged.`
[Quality gates](quality-gates.md) gives each gate's purpose and positive control.

## Related pages

- [Quality gates](quality-gates.md)
- [Develop locally](../how-to/develop-locally.md)
- [Configuration](configuration.md)
