---
title: "Quality philosophy"
kind: "explanation"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["quality_philosophy"]
requires: []
---

# Quality philosophy

Gates encode decisions, not taste. Each one exists because someone decided something, and
the gate is what stops the decision quietly reverting. If a gate cannot be traced back to
a decision, it should be deleted rather than tolerated.

## Checks are read-only

Every recipe under `just check` reports and never repairs. Recipes outside it do write
(`just format` and the lock recipes among them), and `just fix` is the one whose job is
repairing what a check reported. `bg-project-check`, the runner behind `just check`,
enforces the split by snapshotting every path Git does not ignore and comparing after
every recipe, so a check that rewrites a file fails the run rather than hiding drift.

This is why the pre-commit configuration is split in two. `.pre-commit-config.yaml` is
the gate and is what gets installed; `.pre-commit-fix.yaml` holds the mutating hooks and
runs only from `just fix`.

## Fix the cause, not the report

A suppression is a last resort: one rule, one line, with a stated reason. Lowering the
coverage floor, disabling a lint rule at a call site, or loosening an assertion until it
passes are all ways of deleting the signal while keeping the machinery.

Where a rule is genuinely wrong for this project, the fix is to configure it once, in the
config file, with a comment saying why. Here that is `ruff.toml`, which selects every
rule and ignores three, each with its reason beside it; its per-file ignores for
`tests/**` and `scripts/**` carry one comment per rule. At a call site the only form is
`# noqa: XXX123  reason`, naming the rule. mypy runs strict with `warn_unused_ignores`,
so a type suppression that no longer suppresses anything reports itself.

## Unreachable is not untested

Coverage distinguishes two things that look alike. A branch no input can reach is not a
gap in the tests; it is code that should not exist, such as a defensive default no
caller can trigger. Delete it rather than cover it with a contrived test.

The corollary: do not chase the last few percent. The floor is 90 per cent of
`src/rovo/**`, lines and branches combined, as coverage's total. While the package is
small so is the denominator, so one untested branch can breach the floor on its own.
Lower the complexity, not the number.

## Evidence must be able to fail

A gate that cannot fire is worse than no gate, because it reports a pass nobody earned.
So each lint gate carries a positive control: `just py-lint` must see ruff reject
`tests/fixtures/py-lint-violation/ruff.py` with exit status 1 naming `F401` and `E501`,
the fixture's own violations, and must see the package in ruff's file list, because ruff
exits 0 when an exclude has emptied the gate. `just py-typecheck` must see mypy reject
its fixture with exit status 1. A missing input or a tool error is no evidence: exit
status 2 is a usage error, not a fired control.

Tests assert observable results rather than that an internal function was called. And
the wheel is smoked offline, in two steps, because each step proves something the
other cannot. The first installs the wheel alone, with no dependencies, into a fresh
environment and imports `rovo` with `python -I`: that proves on the real artefact that
the API needs nothing outside the standard library, and nothing in the checkout can
hide a broken wheel. The second installs exactly the runtime closure `uv.lock` pins,
from the cache, and runs the command: that proves the console script against the
versions a user would get. Offline, because a smoke that can reach an index can pass on
something other than what the lock says. `dist/` is emptied first, because a stale wheel
proves nothing.

## Related pages

- [Quality gates](../reference/quality-gates.md)
- [Testing](../reference/testing.md)
- [Architecture](architecture.md)
