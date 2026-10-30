---
title: "Decision 0002: The src layout, the public API boundary and the single version"
kind: "decision"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["decision_package_layout"]
requires: []
---

# Decision 0002: The src layout, the public API boundary and the single version

## Context

`rovo` is imported by its users, so three things have to be unambiguous: which copy of
the package a test or a smoke run imports, which names are the API, and where the
version is written. A package directory at the repository root is importable from the
root without being installed, so a test can pass against the source tree while the
built wheel is broken. A version written in two places drifts.

## Decision

The package lives under `src/rovo/`. Nothing named `rovo` sits at the repository root,
so an import from the checkout cannot shadow the installed package: `uv sync` installs
the project into `.venv/` (in editable mode), and every test imports what is installed.
`scripts/wheel_smoke.py` runs with `python -I` against a wheel in a fresh environment,
which rules out the worktree entirely.

The public API is exactly what `src/rovo/__init__.py` lists in `__all__`. A name that
starts with `_` is private, and `py.typed` ships in the wheel so that type checkers read
the package's annotations. Today `__all__` is `["__version__"]`, a placeholder that the
product's first ticket replaces.

The version is static and written once, as `version = "0.0.0"` in `pyproject.toml`.
hatchling writes it into the wheel's metadata, and `rovo.__version__` reads it back
with `importlib.metadata.version("rovo")`. The command line prints `rovo.__version__`;
nothing else holds a copy.

## Consequences

A checkout that has not been synced cannot import `rovo`, even from the repository
root; every command goes through `uv run` or the environment. The metadata read means
an uninstalled source tree fails at import with `PackageNotFoundError` rather than
reporting a wrong version.

`uv.lock` records the project's own version, so a version change is also a relock:
`just lock-check` fails until `just lock` has run and the new lock is committed.

The boundary is a convention that tests and review enforce, not the language: Python
cannot stop a caller importing a private name.

## What would reopen this

The release ticket choosing a version derived from Git tags instead of a static field,
which would change how `rovo.__version__` is produced. A second import package in the
same distribution, which would change what `src/` holds. Adding names to `__all__` is
not a reopening; it is the boundary working.

## Related pages

- [Python packaging](../explanation/packaging.md)
- [API reference](../reference/api.md)
- [Architecture](../explanation/architecture.md)
