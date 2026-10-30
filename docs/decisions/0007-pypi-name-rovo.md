---
title: "Decision 0007: The PyPI name `rovo` in the repository `rove`"
kind: "decision"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["decision_pypi_name"]
requires: []
---

# Decision 0007: The PyPI name `rovo` in the repository `rove`

## Context

The repository already existed as `BiscuitBin/rove` when this project was set up. The
distribution, the import package and the command each need a name, and they need not
share one. On 2026-10-29 `https://pypi.org/pypi/rovo/json` answered 404: no project of
that name existed.

An import name has constraints a distribution name does not. The installed package is
imported as a top-level module, so a Python keyword or soft keyword makes every import
of it a syntax error, and a name that already belongs to the standard library or to a
dependency's top-level module shadows that module for everything in the environment.
`rovo` is none of these: it is not a keyword or a soft keyword, it is not in
`sys.stdlib_module_names`, and no package in `uv.lock` has a top-level module of that
name.

## Decision

The distribution, the import package and the command are all `rovo`. The repository
stays `rove`; the only place the two names meet is `[project.urls]`, whose `Repository`
entry is `https://github.com/BiscuitBin/rove`. Because the command and the distribution
share a name, an installer that runs a package's command of the same name, such as
`uvx rovo`, will need no extra flag once a release exists.

## Consequences

Contributors read `rove` in the repository's URL and `rovo` everywhere else, and the
one-letter difference invites typing the wrong one; the handbook writes `rovo` except
when it means the repository.

A name is not reserved until a first upload, and uploading is out of scope until the
licence is decided ([decision 0006](0006-licence-deferred.md)). The 404 above is
evidence of availability on one day, not a reservation: someone else can register
`rovo` first, and the release ticket rechecks before it uploads.

## What would reopen this

`https://pypi.org/pypi/rovo/json` answering 200 for a project that is not this one
before the first upload, which forces a new distribution name; the import package and
the command could keep theirs. A rename of the repository is not a reopening.

## Related pages

- [Install and run](../how-to/install-and-run.md)
- [Terminology](../project/terminology.md)
- [Python packaging](../explanation/packaging.md)
