---
title: "Python packaging"
kind: "explanation"
audience: ["user", "contributor", "maintainer", "agent"]
canonical_for: ["python_packaging"]
requires: []
---

# Python packaging

One pure-Python wheel installs the API and the `rovo` command together, for CPython
3.13 and newer on every platform. [Architecture](architecture.md) owns how the package
is divided; this page owns how it is built and what ships.

## The build backend

hatchling, pinned exactly in `[build-system]`, builds both artefacts
([decision 0001](../decisions/0001-uv-and-hatchling.md)). `just build` runs
`uv build --offline --out-dir dist` after emptying `dist/`. uv builds the sdist first
and then the wheel from the unpacked sdist, so anything the sdist leaves out cannot
reach the wheel either. Offline means the build backend comes from the cache
`just sync` filled; nothing is fetched at build time.

## The src layout

The package lives at `src/rovo/`, and `[tool.hatch.build.targets.wheel]` names it.
Nothing called `rovo` sits at the repository root, so an import from the checkout cannot
shadow the installed package ([decision 0002](../decisions/0002-src-layout-and-public-api.md)).
The wheel holds exactly `rovo/__init__.py`, `rovo/__main__.py`, `rovo/cli.py`,
`rovo/py.typed` and the `.dist-info` metadata, with the console script in
`entry_points.txt`.

## The version

`version = "0.0.0"` in `pyproject.toml` is static and the only copy. hatchling writes it
into the wheel's `METADATA`, and `rovo.__version__` reads it back through
`importlib.metadata`, so the package, the command and the metadata cannot disagree.
`uv.lock` records it too, so a bump is a relock.

## The sdist's contents

Without a rule, hatchling packs every file Git does not ignore. `only-include` in
`[tool.hatch.build.targets.sdist]` limits the sdist to `src/rovo`, `tests`, `README.md`
and `CHANGELOG.md`; hatchling adds `pyproject.toml`, `PKG-INFO` and `.gitignore` itself.
Tickets, the handbook and the CI configuration stay out; the tests, fixtures included,
ship with the source.

## The README as the project description

`readme = "README.md"`, so the repository's README becomes the wheel's long description,
with `Description-Content-Type: text/markdown`, and will be the project's page on PyPI.
PyPI renders it without the repository around it, so every link in it is absolute.

## The upload guard

Nothing here publishes. The classifier `Private :: Do Not Upload` makes PyPI refuse any
upload carrying it, so an accidental `uv publish` fails at the index. It stays until the
release ticket, which removes it in the same pull request that adds the licence
([decision 0006](../decisions/0006-licence-deferred.md)). Until then the metadata has no
licence field and the wheel no licence file.

## Related pages

- [Install and run](../how-to/install-and-run.md)
- [Configuration](../reference/configuration.md)
- [Decision 0007: The PyPI name](../decisions/0007-pypi-name-rovo.md)
