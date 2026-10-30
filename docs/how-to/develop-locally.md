---
title: "Develop locally"
kind: "how-to"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["local_development"]
requires: []
---

# Develop locally

## Prerequisites

| Tool | Why |
| --- | --- |
| `uv`, 0.13.6 or newer | Installs Python, resolves and locks dependencies, and builds the environment `.venv/` from `uv.lock`. Every tool the gate runs comes from there. |
| `just`, 1.59.0 or newer | The task runner, and the only supported interface to the checks. It cannot come from the project environment, because the `Justfile` is what creates that: install it from a package manager or with `uv tool install rust-just==1.59.0`. |
| `git` | The gate lists files and snapshots the worktree through Git. |
| A Rust toolchain, `cargo` on `PATH` | prek builds the ripsecrets hook from source with cargo the first time the hook environments are prepared. Nothing in the package is Rust. |
| `gh`, `rg`, `jq` | Only for the tickets' verification commands and for maintainer work on GitHub. |

Nothing else: not pixi, not a system Python. uv installs the interpreters it needs.
[Configuration](../reference/configuration.md) has each pin; this page states only the
floors.

## First run

```console
just initialize
```

This runs `uv sync --locked`, which refuses a `uv.lock` that disagrees with
`pyproject.toml` rather than rewriting it, then prepares every hook environment and
runs lychee, because lychee downloads its binary at first run; it fails if that
download did not succeed in three tries. It needs the
network for Python, the dependencies, the shared checkers' Git tag and the hook
clones. It never formats, stages, commits, tags or pushes.

The Git hook shim is installed from the primary checkout only, because every worktree
shares one `.git/hooks` and the shim names an absolute path into the worktree that
installed it. In a secondary worktree `just initialize` says so and skips only the
shim; it still prepares the hook environments. Run `just install-hooks` once from the
primary checkout. Once the environments exist, `just check` runs offline.

## Which Python

`.python-version` holds `3.14`. It is the tooling interpreter: `.venv/` is built on
3.14, and every recipe runs there, because the shared checkers in the `tooling` group
require 3.14. The package's own floor is `requires-python = ">=3.13"`
([decision 0001](../decisions/0001-uv-and-hatchling.md)).

## Every day

```console
just py-test
just check
```

`just py-test` runs the suite without coverage, and passes its arguments to pytest.
`just check` runs the eight gates in order and proves the run left the worktree
unchanged; [Test and debug](test-and-debug.md) covers narrower runs.

## The 3.13 run

The Python gates also pass on the 3.13 floor, without the shared checkers. Point uv at
3.13, leave out the `tooling` group, and give the run its own environment so that
`.venv/` stays on 3.14:

```console
UV_PROJECT_ENVIRONMENT=target/venv-3.13 UV_PYTHON=3.13 UV_NO_GROUP=tooling \
  just lock-check py-lint py-typecheck coverage wheel-smoke
```

The first such run fetches the 3.13 wheels it lacks. `just check` itself cannot run on
3.13: its runner is one of the shared checkers. `uv sync --frozen --python 3.13`
refuses, naming the `tooling` group's floor.

## Before handing work back

```console
just fix       # formats and applies the safe automatic repairs
just check     # the whole gate, read-only
```

Of the two, only `just fix` modifies files; outside the pair, `just format`, `just lock`
and `just lock-upgrade` write too. Every gate is read-only, and `just check` proves it by
comparing the worktree before and after each recipe.

## Keeping the environment current

After pulling, re-sync so the installed dependencies match the lock:

```console
just sync
```

It installs `uv.lock` exactly as committed and never rewrites it.

## Related pages

- [Commands](../reference/commands.md)
- [Test and debug](test-and-debug.md)
- [Troubleshooting](../operations/troubleshooting.md)
- [Configuration](../reference/configuration.md)
