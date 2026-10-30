---
title: "API reference"
kind: "reference"
audience: ["user", "contributor", "maintainer", "agent"]
canonical_for: ["api_reference"]
requires: []
---

# API reference

The public API is exactly what `src/rovo/__init__.py` lists in `__all__`
([decision 0002](../decisions/0002-src-layout-and-public-api.md)). Today that is one
name, a placeholder the product's first ticket replaces:

```console
$ uv run --frozen python -c 'import rovo; print(rovo.__all__)'
['__version__']
```

## Names

| Name | Contract |
| --- | --- |
| `__version__: str` | The installed distribution's version, read with `importlib.metadata.version("rovo")` when `rovo` is imported. It equals `version` in `pyproject.toml`, for example `0.0.0`, and is what `rovo --version` prints after the program name (`rovo 0.0.0`). |

## What importing costs

`import rovo` imports only the standard library: never `rovo.cli`, typer, or any other
third-party module ([decision 0003](../decisions/0003-typer-cli-and-lazy-import.md)).
Importing it from a source tree that has not been installed raises
`importlib.metadata.PackageNotFoundError`, because the version comes from installed
metadata.

## What is not API

A name that starts with `_` is private, including `rovo._version`, the module's alias
for `importlib.metadata.version`. `rovo.cli` and its `app` are the command line's
implementation, reached through the `rovo` command, not a Python API; its behaviour is
in the [command-line reference](cli.md). The package ships `py.typed`, so type checkers
read the annotations of the names above.

## Related pages

- [Architecture](../explanation/architecture.md)
- [Command-line reference](cli.md)
- [Install and run](../how-to/install-and-run.md)
