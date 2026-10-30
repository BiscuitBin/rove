# rovo

rovo is a Python API and a command, `rovo`, shipped together as one pure-Python
distribution for Python 3.13 and newer. The product is not yet specified: today the
package exports a placeholder API, `rovo.__version__`, and the command answers
`rovo --version` and `rovo version`. Around that placeholder the repository already runs
the whole quality gate a real change will need, so that the product's first change lands
on a gate that proves everything around it.

## Status

Pre-release. Nothing has been published, and `rovo` is not on PyPI. The package carries
the `Private :: Do Not Upload` classifier, which makes PyPI refuse an upload, until the
licence is decided and a release ticket removes it.

## Run it from a checkout

You need [uv](https://docs.astral.sh/uv/) and [just](https://just.systems/). From a
clone of [the repository](https://github.com/BiscuitBin/rove):

```console
just initialize
uv run --frozen rovo --version
uv run --frozen python -c 'import rovo; print(rovo.__version__)'
```

`just initialize` installs the environment exactly as `uv.lock` pins it and prepares the
hooks; the first command then prints `rovo 0.0.0`, and the second `0.0.0`.

## Documentation

The handbook starts at the
[documentation map](https://github.com/BiscuitBin/rove/blob/main/docs/README.md): how
to install and run, develop and test, the architecture, the command and API references,
and the [decision records](https://github.com/BiscuitBin/rove/blob/main/docs/decisions/README.md).

## Contributing

```console
just initialize
just check
```

`just check` runs every gate and must end with
`All checks passed and the worktree is unchanged.` before a change is handed back. The
[first-change tutorial](https://github.com/BiscuitBin/rove/blob/main/docs/tutorials/first-change.md)
walks through one change, test first. Contributions arrive under no stated licence until
the licence is decided.

## Licence

This repository has no licence yet, so it grants no rights beyond GitHub's terms of
service: all rights are reserved.
