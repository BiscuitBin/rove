---
title: "Install and run"
kind: "how-to"
audience: ["user", "contributor", "maintainer", "agent"]
canonical_for: ["install_and_run"]
requires: []
---

# Install and run

Nothing is on PyPI yet, and nothing can be: the licence is undecided and the package
carries a classifier that makes PyPI refuse an upload
([decision 0006](../decisions/0006-licence-deferred.md)). Today the only way to run
`rovo` is from a checkout. What `rovo` does today is a placeholder: the package exports
its version, and the command prints it.

## Run from a checkout

After [Develop locally](develop-locally.md)'s first run (`just initialize`), run the
command through the project environment from the repository root:

```console
uv run --frozen rovo --version
uv run --frozen rovo version
uv run --frozen python -m rovo --version
```

Each prints `rovo 0.0.0` and exits 0. `--frozen` runs exactly what `uv.lock` pins and
never rewrites it. `rovo --help` lists the options and commands; the
[command-line reference](../reference/cli.md) has each one and its exit codes.

## Use the API

The same environment imports the package:

```console
uv run --frozen python -c 'import rovo; print(rovo.__version__, rovo.__all__)'
```

It prints `0.0.0 ['__version__']`. Importing `rovo` never loads the command line or
typer ([decision 0003](../decisions/0003-typer-cli-and-lazy-import.md)). The
[API reference](../reference/api.md) describes each exported name.

## From PyPI, once a release exists

A later release ticket publishes `rovo`, after the licence decision. None of these
works today; they are what will work then. The distribution and the command share a
name, so no `--from` flag is needed:

```console
uvx rovo --version
uv tool install rovo
pip install rovo
```

Python 3.13 or newer will be required. The package's page will be
`https://pypi.org/project/rovo/`, written here as a code span rather than a link,
because until the first upload it does not exist.

## Related pages

- [Test and debug](test-and-debug.md)
- [Purpose and scope](../project/purpose-and-scope.md)
- [Python packaging](../explanation/packaging.md)
