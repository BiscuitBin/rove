---
id: T10
title: "Links and scope: rovo sync follows links within the crawl scope and rewrites them between page files"
status: open
depends_on: [T09]
parallel_with: []
branch: full-final-prototype
estimated_size: L
---

# T10: Links and scope: rovo sync follows links within the crawl scope and rewrites them between page files

## Context

T09 (`fd1b423`) is slice 1, the tracer bullet: `rovo init` creates a mirror and
`rovo sync` reads each host's `robots.txt`, fetches the seed pages over HTTP, converts
each with the generic profile, publishes it at `pages/<host>/<path>` with sorted-key
frontmatter, saves `.rovo/manifest.json`, `.rovo/frontier.json` and `.rovo/runs.json`,
and writes `crawl-report.json`. It fixed every pattern this slice follows: the private
subpackages `rovo._convert`, `rovo._mirror` and `rovo._crawl` with `rovo._config`,
`rovo._report` and `rovo._commands` above them (import direction enforced by
`tests/test_import_direction.py`), the `Fetcher` and `Clock` seams with `tests/fakes.py`,
obligation-named tests (`test_<obligation id>`), the end-to-end harness `serve_site` in
`tests/e2e/conftest.py`, the state files of `docs/reference/mirror.md`, and the
development guard `rovo._unfinished.NotInThisSlice`, raised wherever a specified branch
belongs to a later slice. Read `tickets/T09-tracer-init-sync-one-page.md`,
`docs/reference/mirror.md` and `src/rovo/_unfinished.py` before starting.

This is slice 2 of T08 to T20, run in this worktree on `full-final-prototype`. T09's
pages hold no link: `finalise_page_body` (`src/rovo/_mirror/finalise.py` 175 to 176)
raises `NotInThisSlice("ResolveMirrorLinks")` on any body with a link destination, and
`Page.outbound_links` and its relatives (`src/rovo/_mirror/model.py` 318 to 366) are
placeholders returning nothing. This slice makes `rovo sync` follow links: each stored
page's content and navigation links are enqueued at depth + 1 when the crawl scope
allows them, fetched in later batches, and every finalisation resolves each written
page's links against the whole mirror and rewrites a link to a written page as a
relative path between page files, across hosts too (`pages/a.example/guide/x.md` links
to `pages/b.example/y.md` as `../../b.example/y.md`). Every other link stays absolute.

### The specified path, and what this slice does with each rule on it

The task named the rules to realise; the trigger chain crosses more. Each rule the chain
crosses is classified here, so that no rule is skipped silently. Line numbers are at the
specification base `1be7354` (`git diff --stat 1be7354 fd1b423 -- docs/specs` is empty).

| Class | Rules |
| --- | --- |
| **Realised** (every branch reachable in this slice, or constructible on unit inputs where noted) | `crawl.allium`: `EnqueuePageLinks` (1664, the standard-mode branch; content and navigation targets, self-links skipped, `scope.allows(url, depth + 1)`, `config.link_priority`), `Enqueue` (986, now with rediscovery: the depth lowered to the shortest route, the status unchanged, a deferred pending row's priority promoted), `NextBatch` (1109, now firing more than once: the links of one batch are fetched in later batches), `SelectBatch` (1053, its depth-0-first guidance now observable across batches). `mirror.allium`: `CrawlScope` (101 to 155) bounds as the links meet them: `within_bounds`, `allows(url, depth)` with `max_depth`, `include`, `exclude`, `path_prefixes`, `host_allowed` (port dropped), `foreign_locale`; `RefreshPage` (815, its `for l in page.outbound_links: not exists l` and its `LinksFound` at 856, both inert in T09); `ResolveMirrorLinks` (1029, with `link_destinations`' guidance: frontmatter, fenced code, inline code and pre or code blocks skipped; images, empty targets and `mailto:`, `tel:`, `javascript:` and `data:` targets never links); `LinkToPage` (1054, directly or through an alias, `known_page` per 505 to 507, `fragment_resolved` against the holder's `anchors`); `LinkToRemovedPage` (1066: realised in code and unit-tested on a mirror holding a page record constructed with `status = removed`, `removed_at` and `removal_reason`; no run in this slice removes a page, so no end-to-end scenario reaches kind `dangling`); `LinkToUncrawledPage` (1078); `LinkToExternalPage` (1090); `FinalisePageBody` (1117, now over bodies with links: `rewrite_destinations`, the three link flags, the recomputed `low_confidence` and keywords); `FinishLinkPass` (1176, `find_broken_links`); the `MirrorContents` guarantees `RelativeLinksOnly` (1420) and `CodeSamplesNeverRewritten` (1442). `rovo.allium`: `TakeBrokenLinks` (649: the report takes the pass's broken links). |
| **Traversed, nothing new to do** | `StoreNewPage` (749): unchanged; it creates the page and `RefreshPage` raises `LinksFound`. `PublishPage` (1143): unchanged, now publishing rewritten bodies. `BuildIndexes` (1206): still T09's deviation (no index file written); `links.jsonl` and `LinkIndexEntry` (206) are the indexes slice's, as are `outbound_internal` and `inbound_internal` in index entries. `SettleStoredEntry` (1636), `FinishRun` (1700): unchanged, now over several pages. |
| **Outside this slice; reaching one still stops the run** | The guards T09 left, unchanged: `DisposeFetch` (1509): a known page (a second sync), a 404 or 410, a redirect, a non-HTML answer, any verdict other than `none`; `RetireOutOfScopePages` (1014); `SelectBatch`'s tripped-host branch; `Discover`'s targeted and owner-testing branches (so `EnqueuePageLinks`' owner-testing branch, `owner_link_needed`, is unreachable: it raises `NotInThisSlice("EnqueuePageLinks")` if a run that is not standard ever reaches it); every other raise T09's hand-back notes list. The one guard this slice deletes is `finalise.py`'s `NotInThisSlice("ResolveMirrorLinks")`. |

### Facts a later reader would otherwise rediscover

- **The converted body already holds absolute links.** `normalize` resolves every
  content `href` against the page URL (`src/rovo/_convert/fidelity.py` 315 to 320), as
  `ConvertedContent.body` states (`convert.allium` 156: "Markdown with absolute links;
  the mirror rewrites them"). `link_targets` are absolute and de-duplicated
  (`convert.allium` 86, 166); `navigation_targets` are absolute hrefs in `<nav>` outside
  the content (148). `fidelity.link_destinations` (263) returns bare targets outside
  fences and inline code. Rewriting needs the targets' positions, and the regular
  expressions that find them are private to `fidelity.py`, so this slice adds one pure
  function there, `map_destinations(body, rewrite)`, which applies a mapping to each
  link destination outside code and leaves every other byte untouched, and rebuilds
  `link_destinations` on it. The mirror's `rewrite_destinations` and the destination
  filter (non-web schemes, empty targets, fragment split) live in `rovo._mirror`.
  Convert's 47 obligations are all T09's; this slice owns none of them, and
  `tests/test_convert.py` must stay green unedited.
- **What stops an end-to-end run.** The static server answers a missing file with 404
  and a directory URL without a trailing slash with 301, and the fetcher returns any
  non-HTML file as non-HTML: each reaches a `DisposeFetch` branch this slice still
  guards, so the run exits 1. Fixture sites therefore hold no in-bounds link to a
  missing file, to a directory without its slash, or to a non-HTML file. Kind
  `uncrawled` is reached by a robots-disallowed target (in bounds, its row
  `skipped_robots`, no page) and by a target past `max_depth` (the test edits
  `rovo.toml`'s `scope.max_depth`); kind `external` by an off-prefix path and by
  `https://example.invalid/`, neither of which is ever requested.
- **Cross-host links under one host name.** `allowed_hosts` and `Host` are port-less
  (`mirror.allium` 104, `crawl.allium` 1144), while the host segment of a page path keeps
  a non-default port (`127.0.0.1_<port>`). Two fixture servers on `127.0.0.1` are
  therefore one allowed host and one `Host` with one robots policy (read from the
  origin of the first seed, `host_origin`, `crawl.allium` 728), yet their pages live
  under two `pages/<host>/` directories, which is what the cross-host rewrite needs.
  The end-to-end scenario serves the target site first and the source site from a
  temporary copy whose links name the target's base URL. Distinct host names
  (`docs.example` and `api.example`) are proven at unit level through `FakeFetcher`.
- **No new configuration key.** `scope.max_depth`, `scope.include`, `scope.exclude` and
  `scope.locale` are already `rovo.toml` keys (T09 step 1); `link_priority` is a
  `crawl.allium` `config` value (548), read from `rovo._crawl.model.CONFIG`, never a
  literal.
- **`unresolved_fragment` does not lower confidence by default.** `incomplete_flags`
  holds no link flag by default (`convert.allium` 109 to 111), so a page with an
  unresolved fragment or an uncrawled link is flagged but not low-confidence, and the
  run still exits 0. A test reads the flag set from the spec, not a literal.
- **The obligation source.** `just plan-spec <module>` (its echo line goes to standard
  error) over the committed `docs/specs/<module>.allium` at `1be7354`, written to
  `ai_tmp/T10/plan-spec-<module>.txt`: crawl 358, mirror 199, rovo 165, convert 47
  obligations. The copies are scratch, regenerated by step 0.

## Goal

From a clean checkout, against the served fixture site `links`, `rovo init` then
`rovo sync` exits 0 having fetched the seed, then the pages it links to in later
batches, never requesting a URL twice, an out-of-scope URL or a robots-disallowed one;
each page file's links to written pages are relative paths between page files (with
their fragments; a self-link with a fragment a bare fragment), every other link is
absolute, code samples are untouched, the link flags agree with the page's links, and
`crawl-report.json` has `broken_links: []`. Against two served sites, a link from one
host's page to the other's is written as `../<other host segment>/<path>.md`. Every
owned obligation listed under Steps has a test named after its id; `just check` is
green; the Allium loop's witness record says `PASS`.

## Non-goals

- No index files: no `index.md`, `index.jsonl`, `links.jsonl`, `llms.txt` or
  `_indexes/`; no `LinkIndexEntry`, no `outbound_internal` or `inbound_internal` in an
  index (the indexes slice).
- No page lifecycle: no removal, move, revival, `_removed/` or retirement; a `dangling`
  link only on unit inputs (Context table).
- No second sync: a known page still stops `DisposeFetch` (the incremental slice), so
  `UnchangedRunIsStable` is not tested here.
- No sitemaps or `llms.txt`, no politeness (rate, concurrency, pauses, retries), no
  redirects followed, no block classification beyond `none`, no browser tier.
- No owner testing and no targeted runs: `EnqueuePageLinks`' owner branch stays guarded.
- No `verify` command, though `find_broken_links` is the check it will reuse.
- No new `rovo.toml` key, no environment or flag layer.
- No specification change: `docs/specs/` is read, not edited. The five `open question`
  blocks stay open (`crawl.allium` 1975 and 1976, `convert.allium` 473 to 475); none is
  on this slice's path. A specification gap found while planning, implementing, in
  weed or in review is never resolved in code or in the specification: every such gap
  is batched into one needs-user question in the hand-back notes and the ledger's
  `open_questions`.
- No change to the public API: `__all__` stays `["__version__"]`, so
  `docs/reference/api.md` does not move. No decision record changes.
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `src/rovo/_convert/fidelity.py` | shared, own lines | `map_destinations(body, rewrite)`, pure; `link_destinations` rebuilt on it, its result unchanged |
| `src/rovo/_mirror/model.py` | shared, own lines | `LinkKind`, `BrokenLinkReason`, `BrokenLink`, the `Link` entity, `Mirror.links`; `Page.outbound_links`, `inbound_links`, `internal_outbound`, `internal_inbound`, `has_uncrawled_link`, `has_dangling_link` and `has_unresolved_fragment` computed from the mirror's links; `MirrorPass.broken_links` typed |
| `src/rovo/_mirror/links.py` | new | `destinations_of` (the filter and fragment split of `link_destinations`' guidance), `resolve_mirror_links`, `link_to_page`, `link_to_removed_page`, `link_to_uncrawled_page`, `link_to_external_page`, `rewrite_destinations`, `relative_path`, `find_broken_links`, `finish_link_pass` |
| `src/rovo/_mirror/intake.py` | shared, own lines | `RefreshPage` drops the page's outbound links and returns `LinksFound` (candidate, page, depth, targets, navigation targets) |
| `src/rovo/_mirror/finalise.py` | shared, own lines | the `ResolveMirrorLinks` guard removed; the pass resolves every written page's links, then finalises every body with `rewrite_destinations` and the link flags, then publishes, then `FinishLinkPass` |
| `src/rovo/_mirror/state.py` | shared, own lines | the manifest's `links` rows (source identity, target identity, fragment, kind, target page identity, `fragment_resolved`), loaded and saved, sorted |
| `src/rovo/_mirror/__init__.py` | shared, own lines | the docstring names `links` |
| `src/rovo/_crawl/run.py` | shared, own lines | `enqueue_page_links` (`EnqueuePageLinks`), called from `_store` with the `LinksFound` the intake returns; `enqueue`'s rediscovery branch; the owner-branch guard |
| `src/rovo/_report.py` | shared, own lines | `take_broken_links` (`TakeBrokenLinks`); `broken_links` serialised as rows sorted by `from_path` then `href` |
| `src/rovo/_commands.py` | shared, own lines | hands the pass's `LinksRewritten` to `take_broken_links` before `FinaliseRunReport` |
| `scripts/wheel_smoke.py` | shared, own lines | `PACKAGE_FILES` gains `rovo/_mirror/links.py`; the verdict line's count follows |
| `tests/test_crawl.py`, `tests/test_mirror.py`, `tests/test_report.py` | shared, own lines | the owned obligations (step 3); the extended tests re-propagated |
| `tests/test_links.py` | new | the hand-written tests: `RelativeLinksOnly`, `CodeSamplesNeverRewritten`, `rewrite_destinations` idempotent, `relative_path` across hosts, `find_broken_links` firing on a missing file, a path outside the mirror and an absent fragment, the request order over several batches through `FakeFetcher`, `CrawlScope` bounds as links meet them (include, exclude, prefix, host with another port, depth) |
| `tests/test_convert.py` | shared, own lines | one test of `map_destinations` (identity mapping returns the body byte for byte; code untouched); no generated test edited |
| `tests/test_slice_boundaries.py` | shared, own lines | the `ResolveMirrorLinks` guard test removed; an `EnqueuePageLinks` owner-branch guard test added |
| `tests/test_regressions.py` | shared, own lines | one test per divergence weed or review finds |
| `tests/fakes.py` | shared, own lines | only if `FakeFetcher` needs a helper to serve several pages; its contract unchanged |
| `tests/e2e/conftest.py` | shared, own lines | `serve_site` also accepts a `Path` to a directory, so a test can serve a temporary copy whose links name another server's base URL; its shutdown contract unchanged |
| `tests/e2e/test_follow_links.py` | new | the end-to-end scenarios (Acceptance criteria); not `test_links.py`, a basename `tests/test_links.py` already takes |
| `tests/fixtures/sites/links/robots.txt`, `tests/fixtures/sites/links/guide/start.html`, `tests/fixtures/sites/links/guide/b.html`, `tests/fixtures/sites/links/guide/deep/c.html`, `tests/fixtures/sites/links/guide/deep/d.html`, `tests/fixtures/sites/links/guide/private/secret.html`, `tests/fixtures/sites/links/outside/x.html` | new | the `links` site (step 7) |
| `tests/fixtures/sites/cross-host/guide/start.html`, `tests/fixtures/sites/cross-target/guide/y.html` | new | the cross-host pair (step 7); `start.html` holds the placeholder `@TARGET_BASE@` |
| `docs/reference/mirror.md` | shared, own lines | the manifest's `links` rows; a page file's links (relative to written pages, absolute otherwise, code untouched); the link flags; the report's `broken_links` |
| `docs/reference/cli.md` | shared, own lines | `rovo sync` follows links within scope; the stops a link can reach (a missing in-scope page, a redirect, a non-HTML target) |
| `docs/reference/testing.md` | shared, own lines | the new fixture sites, `serve_site` accepting a directory, `tests/test_links.py`, the package-file count |
| `docs/how-to/test-and-debug.md` | shared, own lines | the package-file count |
| `docs/explanation/architecture.md` | shared, own lines | the links in `_mirror`'s part of the private modules' row |
| `docs/project/repository-map.md` | shared, own lines | the tree gains `links.py` and the fixture sites |
| `AGENTS.md` | shared, own lines | line 10's "mirror the seed pages" becomes what the command now does |
| `docs/README.md`, `docs/project/purpose-and-scope.md`, `docs/how-to/install-and-run.md`, `README.md` | shared, own lines | each "seed pages" sentence this slice makes false, and only those |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` entry |
| `tickets/README.md`, `tickets/T10-links-and-scope.md` | ticket | index row, graph, this ticket |
| `.allium-loop/T10-links-and-scope.json`, `.allium-loop/T10-links-and-scope.witness.json` | gitignored | the loop ledger and the witness record; never committed |

`pyproject.toml`, `uv.lock`, `pytest.ini`, `.coveragerc`, `ruff.toml`, `mypy.ini`,
`Justfile` and `docs/specs/` are read, not changed. A file not in this table that turns
out to need a change is added to the table in the same change with its reason, or handed
back if it is a decision record or a specification.

## Steps

0. `just check` baseline on the untouched worktree at `fd1b423`, last line quoted.
   Scratch output goes in `ai_tmp/T10/`. Write `just plan-spec <module>` for each of
   `crawl`, `mirror`, `rovo` and `convert` to `ai_tmp/T10/plan-spec-<module>.txt`, and
   the owned set of step 3 to `ai_tmp/T10/owned.json`. Create the ledger
   `.allium-loop/T10-links-and-scope.json` against
   `allium-skill-reference/allium/schemas/ledger.schema.json`, shaped like T09's:
   `goal` `"T10-links-and-scope"`, `mode` `"spec-first"`, `tick` 0,
   `specification_base` `"1be7354"`, `obligation_source` the four files, and
   `open_questions` holding the five specification open questions verbatim and the Open
   points below. Read `.agents/skills/propagate/SKILL.md`, `.agents/skills/weed/SKILL.md`,
   `.agents/skills/witness/SKILL.md` and `.agents/skills/python-change/SKILL.md` before
   step 3.

1. **The link model and its state.** Write it into `docs/reference/mirror.md` first,
   then code to it.
   - **`Link`** (`mirror.allium` 406): `source` and `target` are pages, held in memory as
     references and in the manifest as identities; `target_identity` is the destination's
     identity before alias resolution; `fragment` is the text after `#`, absent when there
     is none or it is empty; `fragment_resolved` is true when there is no fragment or the
     target's `anchors` hold it. `Mirror.links` holds every link; a page's outbound links
     are those whose source it is, its inbound links those whose target it is. The
     manifest's `links` rows are sorted by source identity, then target identity, then
     fragment, so the manifest is a pure function of the mirror.
   - **Destinations.** `destinations_of(body)` applies `link_destinations`' guidance
     (`mirror.allium` 1041 to 1048) to `fidelity.link_destinations`: an empty target or
     a `mailto:`, `tel:`, `javascript:` or `data:` target is dropped (images are already
     excluded); each remaining target splits at its first `#` into target and fragment;
     a bare `#fragment` targets the page itself. Each destination is made absolute against
     the page's `source_url` and normalised with `scope.identity_of`.
   - **Rewriting.** `rewrite_destinations(body, page)` maps each internal destination to
     `relative_path(page.path, holder.path)` plus `#fragment`, a self-link with a
     fragment to the bare `#fragment`, and leaves every other destination as written
     (already absolute). Resolution and rewriting always start from `converted_body`
     (`mirror.allium` 1119), never from the published `body`: that is what makes
     rewriting idempotent. Re-resolving a rewritten body would read `b.md` against the
     source URL as `<base>guide/b.md`, an in-bounds URL no page holds, and misclassify
     every relative link as uncrawled. `relative_path` is computed between the two
     mirror-relative paths with `posixpath.relpath` from the source file's directory, so
     a link between hosts climbs to `pages/` and descends
     (`pages/a.example/guide/x.md` to `pages/b.example/y.md` is `../../b.example/y.md`).
   - **Broken links.** `find_broken_links(mirror)` reads every written page's file and
     lists each relative destination outside code that leaves the mirror
     (`outside_mirror`), reaches no file (`missing_file`) or names a fragment that is
     not a `{#id}` heading anchor of the target file (`fragment_not_found`); a missing page
     file is itself one `missing_file` finding. It runs after the page files are
     written, as `FinishLinkPass` follows `MirrorLinksResolved`. After a complete pass
     it is empty.
   - **Order of the pass.** As `ResolveMirrorLinks`' guidance requires (every page's
     destinations resolved and every body finalised before `MirrorLinksResolved`): drop
     every written page's links; resolve every page's destinations in path order (one of
     the four `LinkTo*` rules fires per destination, their guards partitioning the
     cases); `FinalisePageBody` then `PublishPage` for each page in path order;
     `FinishLinkPass`; then T09's `BuildIndexes` deviation.

2. **The import direction.** No new layer: `rovo._mirror.links` imports
   `rovo._convert.fidelity` and `rovo._mirror`'s own modules only, and `_crawl` reaches
   it only through the intake's `LinksFound`. `just py-test tests/test_import_direction.py`
   stays green unedited.

3. **Tests first, from the obligations** (the `propagate` skill, spec-first). Write a
   failing test for each owned obligation below into the test file of its module, named
   `test_<obligation id with dots and hyphens as underscores>`, its docstring quoting the
   obligation's description from the plan-spec file. Generated tests satisfy EditorConfig
   (indentation in 4-space multiples in `*.py`, string literals included), ruff and mypy,
   since the gate stages them. Run `just py-test` and record the red run in
   `ai_tmp/T10/red.txt`, its summary line under `last_results.propagate` in the ledger.
   Record each generated or re-propagated test file's SHA-256 under
   `generated_test_hashes`, and the reconciliation line (`N obligations, M covered, K
   uncovered`) over the owned set. A test changed after the red run is re-recorded: a new
   hash, `tick` incremented, a ledger note naming the test and why; never silently. An
   obligation a test cannot reach without a later slice's behaviour is not owned: move it
   to the hand-back notes with its reason rather than writing a vacuous test.

   Owned obligations, new in this slice (ids as `just plan-spec <module>` emits them at
   `1be7354`; 42):

   - **`crawl`** (5): `rule-success.EnqueuePageLinks`, `rule-failure.EnqueuePageLinks.1`,
     `config-default.link_priority`, `projection.Frontier.pending_entries`,
     `projection.Frontier.in_progress_entries` (the projections `SelectBatch` and
     `batch_idle` read, first exercised over several batches here).
   - **`mirror`** (34): `value-equality.BrokenLink`, `entity-fields.BrokenLink`,
     `enum-comparable.LinkKind`, `enum-comparable.BrokenLinkReason`,
     `invariant.Page.LinkFlagsAgreeWithLinks`, `invariant.Link.OnlyInternalLinksHaveTargets`,
     `entity-fields.Link`, `entity-optional.Link.fragment`, `entity-optional.Link.target`,
     `entity-relationship.Page.outbound_links`, `entity-relationship.Page.inbound_links`,
     `projection.Page.internal_outbound`, `projection.Page.internal_inbound`,
     `rule-success.ResolveMirrorLinks`, `rule-failure.ResolveMirrorLinks.1`,
     `rule-success.LinkToPage`, `rule-failure.LinkToPage.1`,
     `rule-entity-creation.LinkToPage.1`, `rule-success.LinkToRemovedPage`,
     `rule-failure.LinkToRemovedPage.1`, `.2`, `rule-entity-creation.LinkToRemovedPage.1`,
     `rule-success.LinkToUncrawledPage`, `rule-failure.LinkToUncrawledPage.1`, `.2`, `.3`,
     `rule-entity-creation.LinkToUncrawledPage.1`, `rule-success.LinkToExternalPage`,
     `rule-failure.LinkToExternalPage.1`, `.2`, `.3`,
     `rule-entity-creation.LinkToExternalPage.1`, `rule-success.FinishLinkPass`,
     `rule-failure.FinishLinkPass.1`.
   - **`rovo`** (3): `rule-success.TakeBrokenLinks`, `rule-failure.TakeBrokenLinks.1`,
     `.2`.
   - **`convert`**: none; all 47 are T09's.

   Extended, not new: T09 owns these and generated their tests, which only covered the
   linkless case. Each is re-propagated in place (same name, a stronger assertion that
   keeps T09's), re-hashed in this slice's ledger with a note naming T09 as the origin:
   `crawl` `rule-success.Enqueue` (rediscovery lowers the depth, keeps the status,
   promotes a deferred row's priority), `rule-success.NextBatch` (a second and third
   batch fetch the links), `derived.Frontier.batch_idle` (idle between batches);
   `mirror` `rule-success.RefreshPage` (the page's previous outbound links are dropped
   and `LinksFound` carries the content's link and navigation targets at the
   candidate's depth), `rule-success.FinalisePageBody` (the rewritten body, its digest,
   the three link flags, `low_confidence` and keywords recomputed). The T09 hashes of
   those files are superseded in T10's ledger, never edited in T09's.

   Guarantees (no obligation id; a hand-written test named after each in
   `tests/test_links.py`): `RelativeLinksOnly` and `CodeSamplesNeverRewritten`
   (`mirror.allium` 1420, 1442).

   Not owned, and why, for the hand-back notes: `value-equality.LinkIndexEntry`,
   `entity-fields.LinkIndexEntry` and the `MirrorContents` surface obligations (the
   indexes and lifecycle slices: the surface exposes `removed_pages` and the index);
   `PageIntake`'s surface obligations (the `CandidateDelivered` shape belongs with the
   incremental slice's validators); every other obligation in the four files, each
   belonging to the slice T09's Context table names.

4. **Convert.** `fidelity.map_destinations`, then `link_destinations` on it, its output
   unchanged for every existing test. `just py-test tests/test_convert.py`.

5. **Mirror** (`src/rovo/_mirror/`). The model of step 1; `links.py`; the intake's
   `LinksFound`; the pass of step 1 replacing `finalise_page_body`'s guard; the manifest's
   `links` rows. Unit cases in `tests/test_mirror.py` and `tests/test_links.py`: a link
   to a written page by its identity and by an alias (internal, relative path); a
   fragment present and absent in the holder's anchors; a self-link with a fragment
   (bare `#x`); an in-bounds URL with no page (uncrawled); a page record with
   `status = removed` (dangling); an off-prefix, off-host and excluded URL (external,
   left absolute); `mailto:`, `data:`, an image and a link inside a fence or inline code
   (never a link, byte-identical); two hosts (`docs.example` and `api.example`): the
   relative path climbs to `pages/`; `find_broken_links` finds a deleted target file, an
   absent fragment and a `../../../` path, so the check can fire (`CONVENTIONS.md` §13).
   A run over two host names through `FakeFetcher` maps each host's `robots.txt` to an
   absent answer, `https://api.example/robots.txt` included: `Discover` opens every
   allowed host (`crawl.allium` 720 to 721) and `host_origin` gives a host without a seed
   `https://<name>` (728), so an unmapped robots URL would stop the run at
   `DenyAllWhenRobotsRefused`.
   `just py-test tests/test_mirror.py tests/test_links.py`.

6. **Crawl, report, commands** (`src/rovo/_crawl/run.py`, `_report.py`,
   `_commands.py`). `enqueue_page_links` per `EnqueuePageLinks`: for each content then
   navigation target, skip the page's own identity, require `scope.allows(url, depth +
   1)`, raise `UrlDiscovered` with `via` `link` or `navigation`, `priority`
   `CONFIG.link_priority`, `from` the page identity, handled by `enqueue`; a run whose
   mode is not standard raises `NotInThisSlice("EnqueuePageLinks")`. `enqueue`'s
   rediscovery branch per `Enqueue`. The driver's batch loop is T09's: rows enqueued
   during a batch are pending for the next, and `SelectBatch`'s depth-0 rule keeps the
   start pages' batch to depth 0. A `FakeFetcher` test in `tests/test_links.py` asserts
   the request sequence over the `links` site's shape: `/robots.txt`, the seed, then its
   in-scope links in `next_pending` order, then the next depth; no URL twice; the
   robots-disallowed and out-of-scope URLs never requested.
   `take_broken_links` per `TakeBrokenLinks`, between `FinishLinkPass` and
   `FinaliseRunReport`. Run `just py-lint`, `just py-typecheck`, `just coverage`; add
   `rovo/_mirror/links.py` to `PACKAGE_FILES` and run `just wheel-smoke`, quoting its
   `api` line.

7. **End to end.** Fixture sites, two-space indentation and a final newline. Every
   fixture page has a `<title>` and a `<main>` holding an `h1` (so it is extracted by
   the profile, not whole-body); an `id` only on a heading (any other `id` stops
   normalisation at `UncarryableBecomesIsland`); no image; no `<a>` inside `pre` or
   `code`. Every link a fixture holds is named here:
   - `links/robots.txt`: `User-agent: *` / `Disallow: /guide/private/`.
   - `links/guide/start.html`: a `<nav>` outside `<main>` linking `b.html`; a `<main>`
     with an `h1`, an `h2 id="intro"`, and links to `b.html`, `b.html#install`,
     `b.html#missing`, `#intro`, `deep/c.html`, `private/secret.html`,
     `/outside/x.html`, `https://example.invalid/` and `mailto:docs@example.invalid`; a
     `<pre><code>` block whose text holds `[b](b.html)`.
   - `links/guide/b.html`: an `h2 id="install"` and a link back to `start.html`.
   - `links/guide/deep/c.html`: a link to `d.html` and to `../start.html#intro`.
   - `links/guide/deep/d.html`, `links/guide/private/secret.html`,
     `links/outside/x.html`: one paragraph each, no link (the last two are never
     requested).
   - `cross-target/guide/y.html`: one paragraph, no link.
   - `cross-host/guide/start.html`: a link to `@TARGET_BASE@guide/y.html`; the test
     serves `cross-target`, copies `cross-host` into `tmp_path` with the placeholder
     replaced by that base URL, and serves the copy.
   The scenarios are the Acceptance criteria's. `just py-test tests/e2e -ra`.

8. **Witness** (the `weed` and `witness` skills). Run `weed` over `crawl`, `mirror` and
   `rovo` against the code, scoped to the owned and extended obligations; record its
   verdict under `last_results.weed` and fix any code divergence, each with a regression
   test in `tests/test_regressions.py`. A divergence weed attributes to the
   specification is not fixed: it joins the one batched needs-user question (Non-goals).
   Then run `witness` non-interactively: it writes
   `.allium-loop/T10-links-and-scope.witness.json` per `witness-result.schema.json`. The
   verdict must be `PASS`; a `FAIL` routes back per the skill, and the hand-back notes
   record each round.

9. **Documents** (the `review-docs` skill). The pages of the Files touched table; find
   the sentences this slice makes false with
   `rg -n -i "seed page|no link|links? .*later slice" -g '*.md' -g '!tickets/**' -g '!allium-skill-reference/**' -g '!docs/specs/**' -g '!docs/decisions/**'`;
   `CHANGELOG.md` `Unreleased` gains one Added entry. Keep the required phrases of
   `AGENTS.md` in always-visible text. `just check-docs`, `just check-agents`.

10. Hand-back notes, `status: done`, `just check` ending with
    `All checks passed and the worktree is unchanged.`, `git status --short` empty after
    the commit. Commit on the branch. **Authorisation required**: pushing and opening the
    pull request.

## Acceptance criteria

- **End to end, links within scope** (`tests/e2e/test_links.py`, through the installed
  `rovo` script beside `sys.executable`): with `serve_site("links")` at `<base>`,
  `rovo init <base>guide/start.html <tmp>/out` then `rovo sync <tmp>/out` both exit 0.
  Page files exist for `start`, `b`, `deep/c` and `deep/d` under
  `pages/127.0.0.1_<port>/`, and none for `private/secret` or `outside/x`. In
  `start.md`: `[...](b.md)`, `[...](b.md#install)`, `[...](b.md#missing)`, `[...](#intro)`,
  `[...](deep/c.md)`; `<base>guide/private/secret.html`, `<base>outside/x.html`,
  `https://example.invalid/` and the `mailto:` link stay absolute; the fenced code still
  reads `[b](b.html)`; its `quality_flags` hold `uncrawled_internal` and
  `unresolved_fragment` and not `dangling_inbound`. In `deep/c.md`: `[...](d.md)` and
  `[...](../start.md#intro)`. `.rovo/frontier.json` has the seed at depth 0, `b` and
  `deep/c` at depth 1 (`b` reached by both content and navigation, one row),
  `deep/d` at depth 2, `private/secret` `skipped_robots`, and no row for
  `outside/x` or `example.invalid`. `crawl-report.json` has `exit_code: "ok"`,
  `converted: 4`, four `added` changes and `broken_links: []`.
- **End to end, the depth bound**: the same site with `rovo.toml`'s `scope.max_depth`
  set to `1` before the sync: no page file for `deep/d`, no frontier row for it, and
  `deep/c.md` links `<base>guide/deep/d.html` absolute and carries
  `uncrawled_internal`.
- **End to end, across hosts**: with `cross-target` served at `<target>` and the
  templated `cross-host` copy at `<source>`, init on `<source>guide/start.html` then
  sync exit 0; `pages/127.0.0.1_<target port>/y.md` exists and
  `pages/127.0.0.1_<source port>/start.md` links it as `../127.0.0.1_<target port>/y.md`.
- **End to end, T09's scenarios** (`tests/e2e/test_init_sync.py`) still pass unedited.
- Every owned obligation in step 3 has a test named after it, red before the code and
  green after (`ai_tmp/T10/red.txt` and the final run); the reconciliation line shows
  zero uncovered; the extended tests are re-hashed in the ledger with their notes;
  every obligation dropped from the owned list is in the hand-back notes with its reason.
- `find_broken_links` is shown to fire (step 5), and `RelativeLinksOnly` and
  `CodeSamplesNeverRewritten` have their named tests.
- No `NotInThisSlice("ResolveMirrorLinks")` remains in `src/`; every other raise T09
  left is still there, plus the `EnqueuePageLinks` owner-branch guard.
- `.allium-loop/T10-links-and-scope.witness.json` exists with `"verdict": "PASS"`, and
  the ledger validates against `ledger.schema.json`.
- `just check-specs` and `just analyse-specs` pass with `docs/specs/` unchanged
  (`git diff --stat 1be7354 -- docs/specs` empty).
- `import rovo` loads no module outside the standard library and `rovo`; `__all__` is
  `["__version__"]`; `just wheel-smoke` passes with the new package-file count.
- `just coverage` stays at or above the floor of 95.
- `just check-docs` and `just check-agents` pass; `docs/reference/mirror.md` and
  `docs/reference/cli.md` describe what the code does.
- `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty after the commit.

## Verification

```sh
just plan-spec crawl > ai_tmp/T10/plan-spec-crawl.txt
just plan-spec mirror > ai_tmp/T10/plan-spec-mirror.txt
just plan-spec rovo > ai_tmp/T10/plan-spec-rovo.txt
just plan-spec convert > ai_tmp/T10/plan-spec-convert.txt
git diff --stat 1be7354 -- docs/specs
just py-test tests/test_links.py tests/e2e -ra
just py-lint
just py-typecheck
just coverage
just wheel-smoke
uv run --frozen python -I -c "import rovo, sys; print(sorted(m for m in sys.modules if not m.startswith(('rovo', '_')) and m not in sys.stdlib_module_names))"
! rg -n 'NotInThisSlice\(rule="ResolveMirrorLinks"\)' src  # positive control: the same rg at fd1b423 prints finalise.py
just check-specs
just analyse-specs
just check-docs
just check-agents
just check
git status --short
```

CI evidence exists only after the push, which is separately authorised; it goes in the
closing pull request's notes.

## Hand-back notes

To be written by the executing agent: the baseline; the link model as built and any
departure from step 1; the red run and the reconciliation line; the extended tests and
their new hashes; every obligation dropped from the owned list and why; the
`NotInThisSlice` raises removed and added, by rule; the weed verdict and the witness
verdict, each round; the one batched needs-user question, if any gap was found; the
verification output, each headed by its commit.

## Open points

- **Robots across ports.** Two servers on one host name are one `Host` with one robots
  policy (`crawl.allium` 728, 1144), so the second port's `robots.txt` is never read,
  while `OneRobotsPolicyPerOrigin` keys policies by origin. The specification is
  followed as written; whether a port-distinct origin should open its own robots policy
  is a question for the maintainer, carried in the ledger as deferred to the robots
  slice T12; it does not block this slice.
- **Uncrawled versus would-be-fetched.** Settled by the maintainer in `32f2210`:
  `CrawlScope`'s comment (`mirror.allium` 94 to 97) now says a link is uncrawled when
  its target is within the crawl's bounds, whether or not depth or robots let the crawl
  fetch it, which agrees with `LinkToUncrawledPage` (1078) and its depth-blind
  `within_bounds`: a robots-disallowed target and a target past `max_depth` are
  `uncrawled` and raise `uncrawled_internal`, as the Acceptance criteria assert.
- **`relative_path` and case.** Paths are compared as written; two page files whose
  paths differ only in case cannot coexist (`UniquePagePathIgnoringCase`), so no case
  folding is needed in a relative link.
- **`NotInThisSlice`.** A development guard, not product behaviour: each later slice
  removes the raises it implements, and the last slice's review confirms none is left.
