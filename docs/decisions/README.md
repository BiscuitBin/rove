---
title: "Architecture decisions"
kind: "decision"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["decision_index"]
requires: []
---

# Architecture decisions

A record of what was chosen, what it cost, and what would have to change for the choice
to be revisited. Each entry is numbered and never renumbered; a decision that is
superseded is marked rather than deleted, because the reasoning is what makes the
successor legible.

These are decisions about how this repository is built, checked and distributed. The
product is not yet specified, so no record decides product behaviour; that arrives with
the product's own tickets.

## The record

| Number | Decision |
| --- | --- |
| [0001](0001-uv-and-hatchling.md) | uv and hatchling, with Python 3.13 as the floor and 3.14 for the tools |
| [0002](0002-src-layout-and-public-api.md) | The src layout, the public API boundary and the single version |
| [0003](0003-typer-cli-and-lazy-import.md) | A Typer command line that `import rovo` never loads |
| [0004](0004-hook-runner-and-checkers.md) | Hook runner and checkers |
| [0005](0005-dependency-policy.md) | Dependency policy: compatible ranges for runtime, exact tools, `uv.lock` the pin |
| [0006](0006-licence-deferred.md) | The licence is undecided, and a release waits for it |
| [0007](0007-pypi-name-rovo.md) | The PyPI name `rovo` in the repository `rove` |
| [0008](0008-renovate.md) | Dependency updates through Renovate |

## The numbering

This series is the repository's own and starts at 0001. Records 0004 and 0005 are
adapted from alliumpy's decisions 0002 and 0004 at `c8e1a46`, and each opens by saying
so, so that its argument can be checked against the original. The others are new.
[Decision 0001](0001-uv-and-hatchling.md) owns how the tools are installed;
[decision 0004](0004-hook-runner-and-checkers.md) owns which runner and checkers they
are.

## Writing a new one

Copy the shape of an existing entry: Context, Decision, Consequences (including the
ones that hurt), What would reopen this, and Related pages. Make each reopening
condition something a reader could check. Add the file, add a manifest entry, add a row
above. A decision nobody can find is not recorded. To supersede a record, write the new
one and mark the old one superseded, naming its successor; never edit the old reasoning
away.

## Related pages

- [Documentation map](../README.md)
- [Architecture](../explanation/architecture.md)
