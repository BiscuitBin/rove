---
title: "Architecture"
kind: "explanation"
audience: ["contributor", "maintainer", "operator", "agent"]
canonical_for: ["architecture"]
requires: []
---

# Architecture

One import package, `rovo`, carries two interfaces: the Python API and the `rovo`
command. The architecture is one rule about which way imports run between them. The
product is specified under `docs/specs/` and not yet implemented, so what sits on each
side today is a placeholder; the rule is what the implementation tickets inherit.

## The modules

| Module | Responsibility |
| --- | --- |
| `rovo` (`src/rovo/__init__.py`) | The public API: exactly the names in `__all__`. Today that is `__version__`, read from the installed metadata. It imports only the standard library. |
| `rovo.cli` (`src/rovo/cli.py`) | The Typer application `app`: the root callback with the eager `--version` option, and the `version` command. It imports `rovo` and presents it. |
| `rovo.__main__` (`src/rovo/__main__.py`) | `python -m rovo`: imports `app` and runs it under the program name `rovo`, so it and the console script print the same usage line. |
| `py.typed` | Marks the package as typed, so type checkers read its annotations. |

The console script `rovo` is `rovo.cli:app`, declared in `[project.scripts]`.

## The boundary

The command depends on the API, never the reverse. `import rovo` never imports
`rovo.cli`, typer, or anything else outside the standard library, so a program that
uses only the API never pays for the command line's start-up time or imports
([decision 0003](../decisions/0003-typer-cli-and-lazy-import.md)). Two checks hold the
line: `tests/test_api.py` imports `rovo` in a fresh interpreter and asserts that
no typer, rich or click module was loaded, and the wheel smoke imports `rovo` from a wheel installed with no
dependencies while recording every import attempted outside `rovo` and the standard
library.

What goes where follows from the boundary, as a guide rather than a gate. Behaviour, and anything a Python caller could want,
belongs in the API, where it is tested as Python. `rovo.cli` parses arguments, calls
the API and formats the result; it holds no logic the API lacks. A command that needs
something the API does not expose is a sign the API is missing a name.

## What crosses the boundary

The API's surface is `__all__` and nothing else; a name starting with `_` is private
([decision 0002](../decisions/0002-src-layout-and-public-api.md)). The version is the
one value both sides share, and it has one source: `version` in `pyproject.toml`,
written into the metadata by the build and read back by `rovo.__version__`, which the
command prints.

## Related pages

- [Repository map](../project/repository-map.md)
- [Python packaging](packaging.md)
- [API reference](../reference/api.md)
- [Command-line reference](../reference/cli.md)
