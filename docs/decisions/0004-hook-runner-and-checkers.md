---
title: "Decision 0004: Hook runner and checkers"
kind: "decision"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["decision_hooks_and_checkers"]
requires: []
---

# Decision 0004: Hook runner and checkers

Adapted from alliumpy's decision 0002 at `c8e1a46`.

## Context

The quality gate is the one every Biscuit Games repository runs: prek runs the hooks,
and the shared `biscuit-games-tooling` package supplies the documentation and agent
validators, the ordered gate with worktree snapshots, and the secret-checking wrapper.
This repository is Python already, so the checkers' interpreter costs nothing extra;
the only friction is that the checkers need Python 3.14 while the package supports 3.13
([decision 0001](0001-uv-and-hatchling.md)).

## Decision

Keep the shared checkers and prek, behind `just check`. prek is an exact pin in the
`dev` group; the checkers are the `tooling` group, pinned to their Git tag `v0.3.0`,
and `uv.lock` records the commit that tag named when it was locked. The
`[tool.biscuit-games-tooling]` table in `pyproject.toml` names the eight gate recipes
in order, and `just check` runs them through `bg-project-check`, which snapshots the
worktree between recipes and ends with `check-clean`. Decision 0001 owns their
installation through uv; no fork of the checkers lives here.

Until the required phrases become configurable, `AGENTS.md` carries honest
explanations for the phrases the agent validator requires but this repository does not
otherwise use; the [agent contract](../reference/agent-contract.md) records that
compatibility requirement.

## Consequences

The gate is the same gate the other house repositories run, from the same pinned
package. A fix to a checker arrives as a pin move rather than a local fork. Both
contracts are enforced mechanically from the first commit, which lets later tickets
replace registered pages, records and skills under a green gate.

The cost is that the full gate is 3.14-only: on 3.13 the Python gates run, but nothing
runs the validators or the snapshotting runner. prek's hook environments, and the
lychee binary, reach the network the first time they are built, so a fresh worktree
runs `just initialize` before `just check` can run offline. `just initialize` does
not yet check that lychee's first-run download succeeded: a failed download still ends
in `Ready`, and the next `just check` then needs the network. That check is handed back
to T00's recipes (`CONVENTIONS.md` §4 `install-hooks`, §5 `scripts/initialize.sh`).

## What would reopen this

The checkers being rewritten as binaries inside the shared package, or the validators
becoming simple enough to rewrite as a local check that runs on the package's 3.13
floor, so that the gate no longer needs the 3.14-only `tooling` group. A change must
replace the package's whole contract rather than only the ordered runner. The checkers
lowering their Python floor is not a reopening of this record; it reopens decision 0001.

## Related pages

- [Quality gates](../reference/quality-gates.md)
- [Maintain dependencies](../how-to/maintain-dependencies.md)
- [Decision 0001: uv and hatchling](0001-uv-and-hatchling.md)
