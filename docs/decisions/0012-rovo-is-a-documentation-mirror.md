---
title: "Decision 0012: rovo is a documentation mirror"
kind: "decision"
audience: ["maintainer", "agent"]
canonical_for: ["decision_product_definition"]
requires: []
---

# Decision 0012: rovo is a documentation mirror

## Context

Until this record the product was undefined. [Decision 0009](0009-specs-are-the-source-of-truth.md)
said that the first specification change would be where the product gets defined, and
the placeholder root module declared nothing. The maintainer brought a product brief: a
documentation website becomes a local, self-linking Markdown mirror that documentation
outside it can link to, that re-syncs with one command, that measures how well every
page converted, and that writes a report of every run. Two prototype specifications
distilled from working prototypes served as evidence. Neither could be transplanted:
each was a single-file monolith written for a different checker regime, they disagreed
on several product decisions, and they bound `.created` calls in a way this repository's
gate rejects. The specification was elicited from the brief instead, with the prototypes
as the floor for depth.

## Decision

rovo turns a product's documentation website into a mirror: an output directory holding
one Markdown page file per page, each with frontmatter naming its source URL and its
measured quality, with the links between pages rewritten to relative paths, with
generated indexes, and with a crawl report. A second sync against an unchanged site
rewrites no file. Platform knowledge lives in profiles, which are configuration, never
in code specific to one site.

The specification is four Allium modules under `docs/specs/`, in one dependency
direction with no cycle:

| Module | Owns |
| --- | --- |
| `convert.allium` | Pure conversion: extraction, normalisation, the ten quality gates, the score, the flags and the low-confidence verdict; the profile; the `Fidelity` contract. No rules. |
| `mirror.allium` | The mirror on disk: the crawl scope and URL identity, the page lifecycle (written, removed, moved, revived), aliases, paths, link resolution and rewriting, frontmatter, the indexes, finalisation, verification, the ownership declaration. |
| `crawl.allium` | One sync run: discovery, the frontier, budgets, politeness, the tiers and the ladder up them, block verdicts, the breaker, learned tiers, owner testing. |
| `rovo.allium` | The command line: the commands init, sync, verify, index, report and fetch; configuration layers; refusals and their order; the crawl report; exit codes. |

A lower module never names an upper one. An upper module delivers work downward by
emitting a trigger the lower module's surface provides, which a rule there turns into an
entity; a lower module reports upward by emitting triggers the upper module responds to.

The crawl is polite by default: robots.txt is respected, requests to one host are paced
and paused, and a per-host breaker stops a standard run on a host that blocks it, with
the blocked and skipped URLs in the report. The browser tier renders JavaScript and is
never used to get past a block; no proxy, solver or paid unblocking service is ever used.
The one exception is owner-testing mode, so that owners can test their own
documentation reliably: it needs a saved ownership declaration for every host, a
finished standard run with the same scope as its baseline, and a preceding run, it warns
that ownership is self-declared and unverified before any request, and it is refused
otherwise.

Product decisions the specification states as defaults, and the five it carries as
`open question` blocks, are listed in the modules themselves. Implementation follows
through tickets, each deriving its tests from the clauses it builds.

## Consequences

The product exists on paper before any of it is built, and the gate now holds four
modules to zero diagnostics and zero findings. The placeholder API and command remain
placeholders until the implementation tickets replace them; every page that said the
product was undefined now says it is specified and not yet implemented. The
specification is large, and the checker it is held to is per module, so a change to a
trigger or an entity ripples through every module above it. Nothing mechanical holds
future code to a clause ([decision 0009](0009-specs-are-the-source-of-truth.md)); the
tickets owe that evidence.

## What would reopen this

The maintainer vetoing one of the stated defaults, which changes a clause but not this
record; a change to the module boundary, such as merging crawl and mirror or splitting
owner testing out, which changes the table above; or a decision that rovo should not be
a mirror at all, which supersedes this record.

## Related pages

- [Specifications](../explanation/specifications.md)
- [Work with the specifications](../how-to/work-with-the-specs.md)
- [Terminology](../project/terminology.md)
- [Decision 0009: Specifications decide behaviour](0009-specs-are-the-source-of-truth.md)
