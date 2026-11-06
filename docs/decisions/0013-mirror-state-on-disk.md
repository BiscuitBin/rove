---
title: "Decision 0013: The mirror's state on disk"
kind: "decision"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["decision_mirror_state"]
requires: []
---

# Decision 0013: The mirror's state on disk

## Context

A mirror outlives the run that writes it. Between runs it keeps more than its page
files: the manifest of pages, aliases and links that a later run compares against; the
frontier, which `crawl.allium` calls "the persisted queue of every identity ever
discovered" (line 41), with the URLs it has observed (`ObservedUrl`, line 352); the
sitemap snapshots (`SitemapSnapshot`, line 365); the learned tiers; and the history of
runs that owner testing looks back on. The specifications say what
that state holds and never how it is stored: `mirror.allium` names "storage mechanics
(the manifest's format, atomic writes)" among its Excludes (lines 25 to 29), and
[decision 0009](0009-specs-are-the-source-of-truth.md) keeps behaviour in the
specifications, so the how is a decision record's to fix.

The specifications fix three facts any storage must agree with. `.rovo/` is a managed
directory at the mirror's root, and no page can have a path inside it: the mirror's
layout keeps every collected page under `pages/<host>/`, beside the managed files,
`_removed/` and `_indexes/` and never among them (`mirror.allium`, the layout in the
Vocabulary at lines 49 to 53, the guidance of `MovePage` at lines 710 to 712, and the
invariant `PagePathsAvoidManagedNames` at line 1443), and a page directory named `.rovo`
is written as `-rovo` so that no page is hidden (line 696). Fetch times and the site's
validators (`etag` and `last_modified`) live in the manifest and never in a page file or
an index (the comment above `value Frontmatter`, lines 157 to 161, the comment above
`value IndexEntry`, and the frontmatter contract at lines 1536 to 1539). No index and no
generated file carries wall-clock time (line 1276 and the guarantee
`UnchangedRunIsStable` at line 1551). The crawl report, `crawl-report.json`, sits at the
mirror's root, where `rovo.allium` (line 194) and the layout put it.

Three formats were weighed. SQLite answers concurrent writers and partial updates, and
neither is needed here: one run writes a mirror at a time. TOML has no writer in the
standard library. JSON is read and written by the standard library, reads in a diff, and
sorts its keys on request.

## Decision

Everything the mirror persists between runs that is not a page file, an index or
`crawl-report.json` is JSON under `<out>/.rovo/`, one file per kind of state: the
manifest of pages, aliases and links, with the mirror's own fields; the frontier with
its observed URLs and learned tiers; the sitemap snapshots; and the run history.
`crawl-report.json` stays at the mirror's root.

Every write of a state file goes to a temporary file in the same directory, is flushed
and `fsync`ed, and is then moved over its target with `os.replace`, so a reader sees the
old file or the new one and never a torn one. The encoding is fixed: UTF-8, keys sorted,
an indent of two spaces, and a trailing newline, so that an unchanged state rewrites
byte-identically.

No page file carries a wall-clock time or the site's validators; fetch times, `etag` and
`last_modified` live in the manifest, as `mirror.allium` already says. This record fixes how the state is stored and never what
it holds: what each kind of state records is the specifications' to say. The exact file
names under `.rovo/` are left to the slice that first writes each file.

## Consequences

The state is inspectable with any text tool and diffs cleanly between runs, and it needs
no dependency. The cost is whole-file rewrites: a save rewrites the file in full, so a
large frontier is rewritten in full on each save, and that time grows with the site. A
crash between saves loses the work since the last save, never the file. One writer is
assumed; nothing here locks the directory against a second.

## What would reopen this

A save time or a state file size that a later slice measures and records as too large
for the sites rovo is pointed at, which would argue for a format with partial updates.
A second writer to one mirror, such as concurrent syncs, which would need locking or a
database. A specification change that moves a kind of state into a page file or an
index, which would contradict the facts above.

## Related pages

- [Decision 0012: rovo is a documentation mirror](0012-rovo-is-a-documentation-mirror.md)
- [Decision 0009: Specifications decide behaviour](0009-specs-are-the-source-of-truth.md)
- [Specifications](../explanation/specifications.md)
