---
title: "Specifications"
kind: "explanation"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["specification_model"]
requires: []
---

# Specifications

The specifications under `docs/specs/` decide what rovo does. Behaviour is written down
in Allium before it is built. The handbook, code and tests answer to those
specifications; when they disagree, the specification wins.
[Decision 0009](../decisions/0009-specs-are-the-source-of-truth.md) records that choice.

The procedure is in [Work with the specifications](../how-to/work-with-the-specs.md).
This page explains why.

## What a specification is for

A rule left to prose or implicit in code can drift as implementations change.
Stating its trigger, guards and outcomes makes the required behaviour explicit,
and gives tests something independent of the implementation to assert. Named
invariants and surface guarantees likewise describe obligations an implementation
must satisfy.

Passing a syntax check alone does not prove that the code fulfils those obligations.
Tests derived from the clauses and reviews of the implementation establish that
connection. A change in intended behaviour starts with the specification and carries
its tests and implementation with it.

## What exists today

There is one module, `rovo.allium`, the root, and it declares no behaviour. Its header
says why: the product is undefined, so the module's Scope is the place the first
specification change will define it, its Includes are empty, and its Excludes are every
behaviour until then. The placeholder API, `rovo.__version__`, and the placeholder
command, `rovo --version` and `rovo version`, stand outside it: they hold the product's
place and no clause describes them.

Empty diagnostics and findings say the module is valid, not that the package does
anything. `just plan-spec rovo` lists no obligations, because there is no clause to owe a
test. The first specification change gives the root a Scope, entities and rules, or adds
a module the root imports, with explicit boundaries so that each behaviour has an owner;
the same change derives the tests, confirms they fail, and builds until they pass.

## Open questions are a feature

An `open question` records a product decision nobody has made yet. An unwritten
gap is easily filled by whoever writes the code first; a written one stays visible
until someone entitled to decide answers it.

The root carries none today, because it states nothing. That will not last: the first
specification change will reach decisions the maintainer has not made, and each becomes
an `open question` rather than a guess in code. A low count is normal for a settled
module, but it is not a reason to hide uncertainty.

## What a specification is not

A specification does not choose a programming language, framework, storage
mechanism or layout. It states what any implementation must satisfy.
`AGENTS.md` governs how this repository builds that implementation, including the
import boundary between the API and the command line and the quality gate.

## Related pages

- [Work with the specifications](../how-to/work-with-the-specs.md)
- [Decision 0009](../decisions/0009-specs-are-the-source-of-truth.md)
