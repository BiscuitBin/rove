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

**Weekly.** Read Renovate's dependency dashboard, the open issue it keeps in this
repository ([decision 0008](../decisions/0008-renovate.md)). Every pending update waits
there, except security fixes, which open as pull requests at once; tick the ones to
take, one kind at a time. Each becomes a pull request: read its
diff and the release notes, wait for `check`, then merge it yourself. Hook revisions and
the shared checkers deserve the closest reading, because the gate cannot tell a weaker
check from a passing one.

**Monthly.** Move by hand what Renovate leaves alone, as
[Maintain dependencies](../how-to/maintain-dependencies.md) lists: `.python-version`,
`requires-python`, the CI `python-version` inputs, the setup action's `python-version`
default and the `tooling` group's `requires-python` floor when a new Python is adopted,
and the uv and just floors in [Develop locally](../how-to/develop-locally.md) after
their pins move.

**Monthly.** Run `just check-links-online`. It is not part of the gate because it needs
the network, so external links rot silently until someone looks.

**Per shared-checkers release.** Read its changelog, move the tag, and run `just check`
before committing: the release supplies the gate runner and both validators.

Nothing here moves on its own: Renovate proposes, and a person approves and merges.

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
- [Decision 0008: Dependency updates through Renovate](../decisions/0008-renovate.md)
