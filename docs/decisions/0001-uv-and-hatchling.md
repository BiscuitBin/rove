---
title: "Decision 0001: uv and hatchling, with Python 3.13 as the floor and 3.14 for the tools"
kind: "decision"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["decision_toolchain"]
requires: []
---

# Decision 0001: uv and hatchling, with Python 3.13 as the floor and 3.14 for the tools

## Context

This repository builds one pure-Python distribution. It needs something to install
Python, resolve and lock dependencies, hold the development environment and build the
wheel, and nothing it ships is native code. alliumpy, where these conventions come from,
uses pixi and maturin because it compiles Rust and installs Rust tools from conda-forge;
none of that applies here.

Two facts constrain the choice. The shared checkers, `biscuit-games-tooling`, require
Python 3.14 (`requires-python = ">=3.14"` in their `pyproject.toml` at `v0.3.0`), while
the package itself supports 3.13. And `uv lock` resolves every dependency group for the
project's whole `requires-python` range, so a 3.14-only package cannot sit in an
ordinary group of a project whose floor is 3.13.

## Decision

uv owns Python, the environment and the lock. `pyproject.toml` is the manifest,
`uv.lock` is the pin, the environment is the gitignored `.venv/`, and every tool runs
through `uv run --frozen`, which never resolves and never rewrites the lock.
hatchling, pinned exactly in `[build-system]`, is the build backend: two
`[tool.hatch.build.targets.*]` tables name the wheel's package and the sdist's contents,
and nothing else is needed. Not pixi, whose reason for existing in alliumpy is a Rust
tool set this repository does not have. Not setuptools: hatchling is the backend of the
uv project template these conventions take their Python shape from, and its settings
are carried as they are.

The package's floor is `requires-python = ">=3.13"`. The shared checkers sit in their
own `tooling` group, which carries its own floor in `[tool.uv.dependency-groups]`
(`tooling = { requires-python = ">=3.14" }`), so `uv.lock` records them under the marker
`python_full_version >= '3.14'`. `.python-version` holds `3.14`: it selects the tooling
interpreter, not the package's floor, and without it uv would pick the newest CPython
installed on the machine.

## Consequences

The full gate, `just check`, runs on 3.14 only, because its runner is one of the shared
checkers. On 3.13 the Python gates run without the `tooling` group
(`UV_PYTHON=3.13 UV_NO_GROUP=tooling`), and `uv sync --frozen --python 3.13` refuses,
naming the group's floor. So the documentation and agent validators, and the worktree
snapshot between recipes, are proven on 3.14 alone.

uv and just are prerequisites a contributor installs before the first run: just cannot
come from the environment the `Justfile` creates. The per-group floor is a uv table;
another installer reading `pyproject.toml` ignores it, and would try to put the
checkers on 3.13.

## What would reopen this

The shared checkers lowering their `requires-python` to 3.13 or below in a release
this repository pins: then the group's floor goes, and `just check` runs on 3.13 as
well. Native code in the package, which needs a different build backend. uv removing or
changing the per-group `requires-python` table, which `uv lock` would show as a failure
to lock.

## Related pages

- [Develop locally](../how-to/develop-locally.md)
- [Configuration](../reference/configuration.md)
- [Python packaging](../explanation/packaging.md)
- [Decision 0004: Hook runner and checkers](0004-hook-runner-and-checkers.md)
