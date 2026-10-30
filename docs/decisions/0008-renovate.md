---
title: "Decision 0008: Dependency updates through Renovate"
kind: "decision"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["decision_dependency_updates"]
requires: []
---

# Decision 0008: Dependency updates through Renovate

## Context

[Decision 0005](0005-dependency-policy.md) pins everything: typer's range and `uv.lock`,
the exact tool pins in `[dependency-groups]` and `[build-system]`, the shared checkers'
Git tag, the hook revisions in both prek configurations, the action SHAs under
`.github/`, and the uv and just versions the setup action installs. Pins that nothing
moves age silently, and moving them by hand is a monthly chore that is easy to skip.

libpawdoku's dependency spike compared Dependabot, Renovate and doing nothing.
Dependabot cannot move lychee's revision together with the `LYCHEE_VERSION=` arguments
that must match it, has no reader for a version inside a `run:` line such as the setup
action's `rust-just==`, and opens its pull requests the moment its file lands, with no
held state. Renovate reads every one of these pins, through a native manager or a regex
manager, and can hold every update until someone approves it on a dashboard issue.

## Decision

Renovate, through the Mend Renovate GitHub App, configured by `renovate.json` at the
root. The configuration:

- Holds every update for approval on the dependency dashboard
  (`:dependencyDashboardApproval`): nothing opens a pull request until a maintainer ticks
  it there, except a fix for a vulnerability GitHub reports, which Renovate's
  `vulnerabilityAlerts` defaults open at once and outside the weekly window. Automerge
  is off and stays off, for those too.
- Proposes on one weekly window, early Monday (UTC), security fixes aside, and runs
  lock-file maintenance on `uv.lock` in the same window, as its own pull request, also
  held.
- Reads `pyproject.toml` with the native `pep621` manager, which relocks `uv.lock` when it
  moves a pin and reads the shared checkers' tag from `[tool.uv.sources]`; `.github/`
  with the native `github-actions` manager, which keeps each action a full SHA with its
  version comment and also reads the setup action's uv `version:` input; and through
  regex managers what has no native one: the hook revisions (the native `pre-commit`
  manager is off, because it would read the revisions as tags), lychee's revision and its
  `LYCHEE_VERSION=` arguments, and the setup action's `rust-just==` pin.
- Groups the action SHAs into one pull request, the hook revisions into another, and
  lychee's revision with both of its `LYCHEE_VERSION=` arguments into a third, so the
  three move together while all three are detected. A group cannot require that: the
  dashboard must list three `lycheeverse/lychee` readings, and a lychee pull request that
  changes fewer than three lines is rejected: `just install-hooks` (and so CI's setup)
  fails when the revision's `# lychee-v` comment and `LYCHEE_VERSION` disagree, but
  nothing checks offline that the SHA is the commit that tag names.
- Leaves to a person the two Python versions [decision 0001](0001-uv-and-hatchling.md)
  owns: `.python-version` and `requires-python`. Both managers that would read them
  are switched off for them.

## Consequences

A dependency update becomes a pull request that `check` proves before anyone merges it,
and a maintainer's routine becomes reading the dashboard rather than reading release
pages. The held state is also the cost: an approval click is needed per update, so an
unread dashboard is the same as no updater.

The app holds write access to contents, pull requests, issues, checks, commit statuses
and workflows ([security model](../explanation/security-model.md)). Its pull requests are
written by code nobody here reviewed, so they are data until `check` is green and a
person has read the diff.

Some bumps pass the gate without proving themselves. A hook that stops reporting passes
`just lint`, and so does a release of the shared checkers that accepts more than the
last one did; only the Python gates have positive controls. So hook and checker
updates are read, not waved through.

## What would reopen this

The app's permissions widening, or its installation reaching repositories it should not.
Renovate dropping a manager this configuration relies on, which the dashboard would show
as a pin no longer detected. Dependabot gaining a held state and the readings above,
which would make it the smaller dependency. Automerge being wanted for any group, which
needs a required review on `main` first.

## Related pages

- [Maintain dependencies](../how-to/maintain-dependencies.md)
- [Maintenance](../operations/maintenance.md)
- [Security model](../explanation/security-model.md)
- [Decision 0005: Dependency policy](0005-dependency-policy.md)
