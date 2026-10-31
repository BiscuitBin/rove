---
title: "Decision 0009: Specifications decide behaviour"
kind: "decision"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["decision_spec_first"]
requires: []
---

# Decision 0009: Specifications decide behaviour

Adapted from pachinko's decision 0002 at `611a86e`, itself carried from libpawdoku's
decision 0002 at `ccdd001`.

## Context

This repository's behaviour is to be written in Allium before the code that implements
it, in the modules under `docs/specs/`. Today there is one, `docs/specs/rovo.allium`, a
placeholder root module that declares no entity, rule, surface or invariant: the product
is not defined yet, and the first specification change that names a behaviour defines it.
Until now `AGENTS.md` said that new behaviour arrives only through a ticket or a decision
record; a ticket or a record still introduces the change, but what the code then does is
stated in a specification. The question is whether the specifications remain
authoritative once implementation starts, or become a design document that quietly falls
behind.

Deciding it before the first behaviour exists is the cheap moment. The rule that decides
whether an action is allowed often has a trap somewhere in it, and the difference between
a correct implementation and a plausible one is a few lines. Left in prose, that detail
is lost in the first refactor.

## Decision

The specifications are the source of truth for behaviour. `AGENTS.md` states the split:
when deciding *what* the code should do, the specifications win; when deciding *how* to
build it, `AGENTS.md` wins.

In practice: behaviour changes in the specification first, then in the tests, then in the
code. No rule, guard or threshold the specifications state is re-decided in code. A test
is never weakened to make it pass; the specification is corrected and the tests are
re-derived.

## Consequences

Contracts become testable obligations rather than intentions. A surface's `@guarantee`
clauses name what it owes, and a test asserts each one directly, including the edge cases
a plausible implementation gets wrong. `just plan-spec <module>` lists those obligations
for a module.

Unresolved product decisions stay visible. They are recorded as `open question` blocks and
answered by someone entitled to answer them rather than by whoever writes the code first.

The costs are real. Every behaviour change is two edits, not one. The project-managed
`allium` binary ([decision 0010](0010-project-managed-allium-cli.md)) holds every module
to parsing and analysing cleanly, but nothing mechanical holds the code to a clause, so
drift between a clause and its implementation is still caught by review.

Until the product is defined the decision constrains nothing in `src/rovo/`: the
placeholder module states no behaviour, so no code can contradict it, and the placeholder
API and command stand outside it. It binds from the first specification change that names
a behaviour.

## What would reopen this

If the specifications stopped being maintained, so that a behaviour change landed in
code without a matching edit and nobody noticed, the honest response would be to distil
them back from the implementation and restart, or to abandon the approach outright
rather than keep a document that lies. The check is mechanical enough: a pull request
that changes behaviour under `src/rovo/` without touching `docs/specs/` is the symptom.

## Related pages

- [Specifications](../explanation/specifications.md)
- [Work with the specifications](../how-to/work-with-the-specs.md)
