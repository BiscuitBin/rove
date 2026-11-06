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
product is specified under `docs/specs/` and implemented slice by slice: the command
side runs `rovo init`, `rovo sync` and `rovo index` through private modules, and the API side is still
the placeholder `__version__`; the rule is what every implementation ticket inherits.

## The modules

| Module | Responsibility |
| --- | --- |
| `rovo` (`src/rovo/__init__.py`) | The public API: exactly the names in `__all__`. Today that is `__version__`, read from the installed metadata. It imports only the standard library. |
| `rovo.cli` (`src/rovo/cli.py`) | The Typer application `app`: the root callback with the eager `--version` option, and the `version`, `init`, `sync`, `verify`, `index` and `report` commands. It imports `rovo` and presents it. |
| `rovo.__main__` (`src/rovo/__main__.py`) | `python -m rovo`: imports `app` and runs it under the program name `rovo`, so it and the console script print the same usage line. |
| `rovo._commands` | The root's rules, `init`, `sync`, `verify`, `index`, `report` and `fetch`: they compose configuration, crawl, mirror and report, and take the `Fetcher` and `Timer` seams so tests run them in process. `rovo.cli` imports it inside each command's body, so `rovo --version` loads no runtime dependency. It imports only the mirror's modules on import and `_config`, `_crawl` and `_report` inside `init`'s, `sync`'s and `fetch`'s bodies, so `rovo verify`, `rovo index` and `rovo report`, which never crawl, load neither httpx nor `rovo._crawl`. |
| `rovo._exit` | `ExitCode`, the code a command ends with; a leaf that imports no rovo module, which `_report` re-exports, so `rovo index` can return one without loading the report. |
| `rovo._unfinished` | `NotInThisSlice`, the exception a branch a later slice implements raises; a leaf that imports no rovo module, so every layer may raise it. |
| `py.typed` | Marks the package as typed, so type checkers read its annotations. |
| `rovo._convert`, `rovo._mirror`, `rovo._crawl`, `rovo._config`, `rovo._report` | Private modules that realise the specification, one slice at a time: `_convert` the pure conversion, `_mirror` the mirror's state, page files, the links between them and the indexes, `_crawl` one sync run behind the `Fetcher` seam (httpx in use, a fake in tests), its `pace` module spacing each host name's requests and waiting out retries on the `Timer` seam (`now()` and `sleep()`: `SystemTimer` in use, on a monotonic clock, a stepping fake in tests) its `sitemaps` module reading sitemaps and `llms.txt` (pure, with lxml's entities, DTDs and network off) and its `browser` module, the `BrowserEngine` seam a render goes through (`PlaywrightEngine` in use, the one module that imports playwright, and only at its first render; a fake in tests), every request a render makes answered by the crawl, `_config` `rovo.toml`, `_report` `crawl-report.json`. The first three follow the specification's direction ([decision 0012](../decisions/0012-rovo-is-a-documentation-mirror.md)): `_convert` imports nothing of rovo's, `_mirror` may import `_convert`, and `_crawl` may import both; none imports `rovo.cli`. `_config` and `_report` serve the command and the root. `import rovo` loads none of them. |

The console script `rovo` is `rovo.cli:app`, declared in `[project.scripts]`.

## The boundary

The command depends on the API, never the reverse. `import rovo` never imports
`rovo.cli`, typer, or anything else outside the standard library, so a program that
uses only the API never pays for the command line's start-up time or imports
([decision 0003](../decisions/0003-typer-cli-and-lazy-import.md)). Two checks hold the
line: `tests/test_api.py` imports `rovo` in a fresh interpreter and asserts that
no typer, rich or click module was loaded, and the wheel smoke imports `rovo` from a wheel installed with no
dependencies while recording every import attempted outside `rovo` and the standard
library. A third holds the direction inside the package:
`tests/test_import_direction.py` reads every module with `ast` and fails when one
imports against it, or when `src/rovo/__init__.py` imports a private module, the command
line or a runtime dependency.

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
