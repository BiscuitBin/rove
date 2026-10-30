---
title: "Decision 0006: The licence is undecided, and a release waits for it"
kind: "decision"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["decision_license"]
requires: []
---

# Decision 0006: The licence is undecided, and a release waits for it

## Context

The repository is public on GitHub, and its maintainer has not chosen a licence. A
licence is easier to settle before contributions arrive, because relicensing later can
mean asking every contributor. A package on PyPI carries its licence in its metadata,
so nothing should be published until there is one to carry.

## Decision

The licence is undecided. There is no `LICENSE` file, no `license` or `license-files`
field in `pyproject.toml`, and no licence classifier. A public repository with no
licence grants no rights beyond GitHub's terms of service: all rights are reserved, and
the `README.md` says so in one sentence.

A release waits for the decision. The `Private :: Do Not Upload` classifier in
`pyproject.toml` makes PyPI refuse any upload, and it stays until the release ticket,
which removes it in the same pull request that adds the licence. The options under
consideration: none listed yet; the maintainer will name them when the decision is
taken.

## Consequences

Contributions arrive under no stated licence until the decision is made, and nobody
may reuse the code beyond what GitHub's terms allow. The release ticket is blocked on
this record.

One setting exists only because of it, and lifts with it: `ruff.toml` ignores rule
`CPY001` (there is no copyright notice to write while the licence is undecided).
`_typos.toml` accepts `cpy`, the rule's prefix, and that entry stays after the ignore
lifts, because this record and T00's ticket keep naming the rule once superseded.

## What would reopen this

The maintainer choosing a licence. That decision supersedes this record with a new one
naming the licence, adds the `LICENSE` file and the metadata, lifts the `CPY001`
ignore in `ruff.toml`, and unblocks the release ticket, which removes the upload guard.

## Related pages

- [Python packaging](../explanation/packaging.md)
- [Purpose and scope](../project/purpose-and-scope.md)
- [Configuration](../reference/configuration.md)
