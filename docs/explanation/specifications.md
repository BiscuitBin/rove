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

Four modules specify the product, a documentation mirror
([decision 0012](../decisions/0012-rovo-is-a-documentation-mirror.md)). `convert` is
the leaf: pure conversion with no rules, held together by the `Fidelity` contract.
`mirror` owns the mirror on disk: identity, the page lifecycle, links, indexes,
finalisation and verification. `crawl` owns one sync run: discovery, the frontier,
politeness, the tiers, the breaker and owner testing. `rovo`, the root, owns the
command line: the commands, the refusals, the report and the exit codes. Each header
states its Scope, Includes, Excludes, Dependencies and Vocabulary, and
[Work with the specifications](../how-to/work-with-the-specs.md) has the table.

The placeholder API, `rovo.__version__`, and the placeholder command, `rovo --version`
and `rovo version`, stand outside the modules: they hold the product's place and no
clause describes them. Empty diagnostics and findings say the modules are valid, not
that the package does anything: nothing in the specification is implemented yet.
`just plan-spec <module>` lists the obligations each module owes a test; the
implementation tickets derive those tests, confirm they fail, and build until they
pass.

## Open questions are a feature

An `open question` records a product decision nobody has made yet. An unwritten
gap is easily filled by whoever writes the code first; a written one stays visible
until someone entitled to decide answers it.

The modules carry five, each stating the behaviour that holds until it is decided:
what the tab-expansion gate should measure, whether hidden content outside a tab panel
survives extraction, which construct families the fidelity corpus must cover, whether a
sitemap index may point at child sitemaps on other hosts, and whether a URL that fails
on every sync is ever retired. Every other decision the elicitation reached is stated
outright, many as defaults the maintainer may veto at review. A low count is normal for
a settled module, but it is not a reason to hide uncertainty.

## What a specification is not

A specification does not choose a programming language, framework, storage
mechanism or layout. It states what any implementation must satisfy.
`AGENTS.md` governs how this repository builds that implementation, including the
import boundary between the API and the command line and the quality gate.

## Related pages

- [Work with the specifications](../how-to/work-with-the-specs.md)
- [Decision 0009](../decisions/0009-specs-are-the-source-of-truth.md)
