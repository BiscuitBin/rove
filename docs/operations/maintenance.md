---
title: "Maintenance"
kind: "operations"
audience: ["maintainer", "operator", "agent"]
canonical_for: ["maintenance_routine"]
requires: []
---

# Maintenance

There is no service to operate. `rovo` runs inside whoever calls it, nothing has been
released, and there is no on-call. What follows is upkeep of the pins that build and
check it, and of the gate itself.

## Routine

**Weekly.** Run `just audit`, which checks every version in `uv.lock` against known
vulnerabilities. It needs the network, so it is not part of `just check`, and a finding
there blocks nothing until someone reads it. A vulnerable package is fixed by moving it,
not by ignoring it.

**Monthly.** Move the dependency pins, one kind at a time, as
[Maintain dependencies](../how-to/maintain-dependencies.md) describes. `just lock-upgrade`
moves the runtime tree within `pyproject.toml`'s ranges; an exact tool pin moves by
editing its line and running `just lock`. Then `just sync`, `just check`, and commit
`uv.lock` with `pyproject.toml`. A hook `rev` or a GitHub Action SHA moves by hand, with
its version comment moved beside it.

**Monthly.** Run `just check-links-online`. It is not part of the gate because it needs
the network, so external links rot silently until someone looks.

**Per shared-checkers release.** Read its changelog, move the tag, and run `just check`
before committing: the release supplies the gate runner and both validators.

Nothing here moves on its own. The Renovate ticket (T06) adds automated update pull
requests and a dependency dashboard on GitHub; once it lands, the monthly pin move
becomes reviewing those pull requests and reading the dashboard, and this page says so.
Until then the routine above is manual.

## When the gate itself fails on a clean tree

A green `main` that turns red with no change usually means a pin moved under it: a hook
environment rebuilt from a cleared cache, or a CI runner image that changed. Rerun the
one recipe `just check` names, read its first failure, and fix the cause; never disable
the gate or its positive control to get a green run.
[Troubleshooting](troubleshooting.md) lists the common symptoms.

## Secrets

None are stored, and there is nothing to rotate. CI uses the token GitHub mints for
each run, with read access only, and discards it with the run. There is no PyPI
credential, because nothing is published.

## Related pages

- [Maintain dependencies](../how-to/maintain-dependencies.md)
- [Troubleshooting](troubleshooting.md)
- [Security model](../explanation/security-model.md)
