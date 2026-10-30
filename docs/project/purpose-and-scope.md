---
title: "Purpose and scope"
kind: "project"
audience: ["user", "contributor", "maintainer", "agent"]
canonical_for: ["project_purpose"]
requires: []
---

# Purpose and scope

`rovo` is one pure-Python distribution with two interfaces: an importable package,
`rovo`, which is the Python API, and a Typer command of the same name. The
[architecture](../explanation/architecture.md) describes how the two are separated;
[Python packaging](../explanation/packaging.md) explains the wheel they ship in.

## What it does today

The product is not yet specified. What exists is a gated skeleton around a placeholder:
the API exports `rovo.__version__` and nothing else, and the command answers
`rovo --version` and `rovo version`. Around that placeholder the repository already
runs everything a real change will need: lint and type gates with positive controls, a
coverage floor, a wheel built and smoke-installed offline on every `just check`, the
documentation and agent contracts, and CI. The product's first ticket replaces the
placeholder and lands on a gate that already proves everything around it.

## What it deliberately does not do

It does not describe or invent the product: no page, test or command here says what
`rovo` will do beyond the placeholder, and anything that would is a defect until a
ticket specifies it. Nothing is released: the package is not on PyPI, and a
`Private :: Do Not Upload` classifier makes PyPI refuse an accidental upload. There is
no licence yet ([decision 0006](../decisions/0006-licence-deferred.md)), so the
repository grants no rights beyond GitHub's terms of service, and a release waits for
that decision.

## Who it is for

Contributors and agents who will build the product on this skeleton, and the
maintainer who decides what it becomes. Users of the Python API and of the command
arrive with the first release; until then the only way to run `rovo` is from a
checkout ([Install and run](../how-to/install-and-run.md)).

## Related pages

- [Repository map](repository-map.md)
- [Terminology](terminology.md)
- [Decision 0007: The PyPI name](../decisions/0007-pypi-name-rovo.md)
