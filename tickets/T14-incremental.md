---
id: T14
title: "Incremental sync: a second rovo sync fetches known pages conditionally, keeps what did not change, reuses unchanged sitemaps, honours max_age and rewrites nothing on an unchanged site"
status: open
depends_on: [T13]
parallel_with: []
branch: full-final-prototype
estimated_size: M
---

# T14: Incremental sync: a second rovo sync fetches known pages conditionally, keeps what did not change, reuses unchanged sitemaps, honours max_age and rewrites nothing on an unchanged site

## Context

T09 (`fd1b423`), T10 (`9fd11fd`), T11 (`d2979c8`, `2658231`), T12 (`7a9c135`) and T13
(`f5683e3`, follow-up `71437de`) are slices 1 to 5. `rovo sync` reads each origin's
robots.txt, paces and retries per host name, reads each allowed host's sitemaps and
`llms.txt`, fetches the seeds, the pages discovery admitted and the pages they link to,
publishes each at `pages/<host>/<path>`, writes the indexes and `crawl-report.json`, and
`--dry-run` lists what it would fetch. They fixed every pattern this slice follows: the
private subpackages `rovo._convert`, `rovo._mirror` and `rovo._crawl` with
`rovo._config`, `rovo._report` and `rovo._commands` above them (import direction enforced
by `tests/test_import_direction.py`), the `Fetcher` seam (`Validators` in
`src/rovo/_crawl/fetch.py`), the `Timer` seam of `src/rovo/_crawl/pace.py` (`FixedClock`,
`SteppingTimer`, `FakeFetcher`, `ScriptedFetcher` and `StampingFetcher` in
`tests/fakes.py`), obligation-named tests (`test_<obligation id>`), the end-to-end
harness `serve_site` in `tests/e2e/conftest.py` with scripted answers (`Answer`, `DROP`,
`always=`) and its request log, the state files of `docs/reference/mirror.md`, and the
development guard `rovo._unfinished.NotInThisSlice`. Read `tickets/T13-discovery.md`
(its Context table, Facts and Open points), `tickets/T12-robots-politeness.md` (its
Facts), `src/rovo/_crawl/run.py`, `src/rovo/_mirror/intake.py`,
`src/rovo/_mirror/finalise.py` and `tests/e2e/test_discovery_sync.py` before starting.

This is slice 6 of T08 to T20, run in this worktree on `full-final-prototype`. Until
now a mirror can be synced once: a second ordinary sync re-pends every written page
(`prepare_run`, `run.py` 205), fetches it conditionally (`fetch_entry` already sets
`LadderWalk.conditional` and `attempt_tier` already sends `_validators(walk)`), and then
stops at the first known page it refetches: `dispose_fetch` (`run.py` 1230 to 1272)
raises `NotInThisSlice("DisposeFetch")` for a 304 on a known page (its `earlier_branch`)
and for an ok HTML answer whose `known is not None` (its last guard), and
`settle_candidate` (`intake.py` 226) would raise `NotInThisSlice("PageCandidate.created")`
for a converted candidate whose page is known or an unchanged one. A sitemap's snapshot
lives one run (`SitemapSnapshot`, `model.py` 475, "kept one run, T13"; `save_frontier`,
`run.py` 1562), so no sitemap is ever fetched conditionally and `ReuseUnchangedSitemap`
never fires. `max_age` is already read (`rovo.toml`'s `crawl.max_age`, `_config.py` 390)
and `prepare_run` already computes `run.forced_refetch` from it (`_stale_pages`,
`run.py` 1664), but nothing past `fetch_entry` acts on it. The specification base is
`ecfa257` (`git diff --stat ecfa257 HEAD -- docs/specs` is empty); every specification
line number below is at `ecfa257`, every source line number at `71437de`.

### The specified path, and what this slice does with each rule on it

| Class | Rules |
| --- | --- |
| **Realised** (every branch reachable in this slice, or constructible on unit inputs where noted) | `crawl.allium`: `DisposeFetch` (1806), its two unchanged branches: a 304 for a known page (`entry.status = unchanged`, `CandidateDelivered` with `outcome: unchanged`, the 304's validators and `raw_digest: known.raw_digest`) and an ok answer whose `raw_unchanged` holds (known page, same `raw_digest`, same `processing_signature`, no redirect hop) for an identity not in `run.forced_refetch` in a standard run (`host.fetched` counted, `CandidateDelivered` unchanged with the response's validators); and its `PageFetched` branch now for a known page too (an HTML answer whose raw document changed, or a page refetched by force), which `ConvertFetched` (1903) delivers as `converted`. `ReuseUnchangedSitemap` (1083): a 304 to a sitemap with a snapshot raises `SitemapEntriesFound` with the snapshot's `is_index` and `entries`, which `ExpandSitemapEntries` (1143) treats as a fresh read. `FetchSitemap` (975), its validators: `fetch_resource(url, snapshot?.etag, snapshot?.last_modified, run, host)` now sends a saved snapshot's validators. `AcceptFreshSitemap` (1091), its update branch now reached across runs. `PrepareRun` (638): `forced = stale_pages(run.target, run.max_age)` on an update run (guidance 697 to 699), and the `done -> pending` and `unchanged -> pending` re-pends of a written page's row, first exercised end to end by a second sync. `FetchEntry` (1457): its `conditional` test, now meeting known pages, a page past `max_age`, a changed processing signature and a newer sitemap `lastmod`. `mirror.allium`: `RecordUnchanged` (903), `DiscardUnchangedWithoutPage` (924, constructible on unit inputs only: both of `DisposeFetch`'s unchanged branches require a known page), and `RewriteKnownPage` (593) when the candidate's identity is the requested page's own (`previous = target`), which raises `PageContentAccepted` to `RefreshPage` (818) with `previous_digest` carried. The surface guarantee `UnchangedRunIsStable` (1480). |
| **Traversed, nothing new to do** | `PublishPage` (1146): already writes a page file only when `page_file_current` is false (`finalise.py` 221) and already gives `unchanged` when the body's digest did not move, so a page `RecordUnchanged` keeps or `RewriteKnownPage` reconverts to the same body is not rewritten unless its frontmatter moved (Facts). `BuildIndexes` (1209): already writes each index file only when it differs (`indexes.py` 186). `SettleStoredEntry` (1933): not reached by an unchanged row, which `DisposeFetch` settles itself; reached by a rewritten known page as by a new one. `FailDiscardedEntry` (1949) and `EntryFails`: reached by `DiscardUnchangedWithoutPage`'s `CandidateDiscarded` on unit inputs only (`no page to confirm`). `EnqueuePageLinks` (1961): a rewritten page's `LinksFound` is enqueued as a new page's is; an unchanged page raises no `LinksFound` (`RecordUnchanged` raises `PageStored` alone; Open points, item 1). `Enqueue` (1240): a reused sitemap's entries meet existing rows, whose status it never changes. `SkipUnavailableSitemap` (1128) and `RejectNonSitemap` (1120): unchanged, a 304 meeting neither. `rovo.allium` `TallyFinalisedPage` (600) and `CloseRun` (623): already count an unchanged page seen this run under `skipped_unchanged` and list it as an `unchanged` change, and report `fetched` as the run's `fetch_attempts`, so a 304 counts as fetched there while `per_host` `fetched` (`host.fetched`) does not count it. `StartSync` (456): already passes `settings.max_age` (`_commands.py` 231) and `kind = update` when the mirror holds pages (`_commands.py` 196). |
| **Later slices'** | Every other branch of `DisposeFetch` and of page intake stays where T09 to T13 left it: an absent answer, a redirected-out or unfollowed redirect, a followed redirect (`redirect_hops`), `RejectDuplicateCandidate` (561), `MovePage` (620), `ReviveRemovedPage` (729), `RewriteKnownPage`'s merge branch (`previous != target`, `PageRetired(merged)`), `RemoveAbsentPage` and the other removal rules are the lifecycle slice's (T15); a block verdict is the breaker's (T18); a non-HTML answer (`skipped_not_html`) is not this slice's and keeps its stop; the targeted and owner-testing branches of `PrepareRun` and `FetchEntry` (`run.targets`, `run.mode = owner_testing`) are T16's and T20's. |
| **Outside this slice; reaching one still stops the run** | Every raise T13 left, with `NotInThisSlice("DisposeFetch")`'s conditions narrowed (a 304 on a known page and a known page's ok HTML answer no longer meet them) and `NotInThisSlice("PageCandidate.created")` no longer reached by an unchanged candidate or by a converted one whose identity is its known page's; plus one new raise, `NotInThisSlice("RewriteKnownPage")`, for the merge branch (a canonical that moves a known page onto another written page). |

### Facts a later reader would otherwise rediscover

- **The guard that stopped every second sync.** `tests/test_slice_boundaries.py`'
  `test_a_second_sync_of_a_known_page_stops` (382) asserts that a second sync exits
  `partial` and keeps the first report. It is re-propagated with a ledger note: the
  second sync now exits 0 and the request still carries `Validators(etag=None,
  last_modified=None)` (the fake's page has neither); its check of the page file's mode
  (an atomic write gives an ordinary new file's mode) stays. Nothing else in it changes.
  `test_mirror_branches_of_later_slices_stop` (402) still raises: its second candidate
  carries the same `run_id`, so `RejectDuplicateCandidate`'s guard holds
  (`target.last_stored_run = candidate.run_id`), `RewriteKnownPage`'s does not, and
  `settle_candidate` still ends at `NotInThisSlice("PageCandidate.created")`; step 0
  confirms it.
- **The intake partition.** `settle_candidate` fires the rule whose guards hold, in
  this order: `StoreNewPage`, `RefuseUnplaceableCandidate` (both T09), then
  `RecordUnchanged` (pending, `outcome = unchanged`, a known page),
  `DiscardUnchangedWithoutPage` (pending, unchanged, no known page) and
  `RewriteKnownPage` (pending, converted, a written page at the candidate's identity
  whose `last_stored_run` is not this run). An unchanged candidate takes exactly one of
  the two unchanged rules; a converted one at most one of the others; whatever is left
  raises `NotInThisSlice("PageCandidate.created")` as today. `RewriteKnownPage` sets
  `target.previous_digest = target.content_digest` and hands the candidate to
  `refresh_page`; when `known_page(requested_identity)` is not the target it raises
  `NotInThisSlice("RewriteKnownPage")` before changing anything.
- **What an unchanged row does to the run.** `dispose_fetch` returns the unchanged
  `CandidateDelivered` (a third result beside `EntryFailed` and `True`), and
  `_handle_entry` routes it to `admit_candidate` and `settle_candidate`, never to
  `convert_fetched`, `enqueue_page_links` or `settle_stored_entry` (the row is already
  `unchanged`). `RecordUnchanged` sets `last_seen` and `last_seen_run`, takes the
  candidate's `etag`, `last_modified` and `sitemap_lastmod` when not null and keeps the
  stored ones otherwise, and leaves every other field, the body and the measurement as
  they were. The row's next run re-pends it (`unchanged -> pending`).
- **When a page file moves on an unchanged body.** `PageFileProvenance` (1460) puts
  `etag`, `last_modified` and `sitemap_lastmod` in the frontmatter, and `IndexEntry`
  (`mirror.allium` 185) puts `last_modified` in `index.jsonl`. So a page whose raw
  document is unchanged but whose server sends a new `Last-Modified` or `ETag`, or
  whose sitemap `lastmod` moved, keeps its body and its outcome `unchanged` but has its
  page file and `index.jsonl` rewritten for the frontmatter alone. That is what the
  specification says (Open points, item 3); the end-to-end scenarios therefore make a
  raw-unchanged page with a scripted answer that carries no validator, and the
  stability scenario uses only 304 answers.
- **What `http.server` answers.** `SimpleHTTPRequestHandler.send_head` (Python 3.14,
  read at `71437de`) sends `Last-Modified` (the file's mtime, to the second) and no
  `ETag`, and answers `304` with no header when the request carries `If-Modified-Since`
  without `If-None-Match` and the file's mtime, microseconds dropped, is not later. So a
  second sync of untouched fixture files gets a 304 for every page and sitemap it has
  validators for, which proves the validators were sent without changing the harness;
  `tests/e2e/conftest.py` is read, not changed. A file changed between syncs must also
  have its mtime moved forward by at least a second (`os.utime`), or a change made
  within the second of the first fetch is answered 304. `If-None-Match` is proved on
  unit inputs with `ScriptedFetcher` (`tests/fakes.py`), whose scripted answer can
  carry an `ETag`.
- **Sitemap snapshots are saved in their own file.** Decision 0013 lists "the sitemap
  snapshots" as one kind of state and leaves the file name to the slice that first
  writes it: `.rovo/sitemaps.json`, `{"snapshots": [...]}`, one row per snapshot sorted
  by `url`: `url`, `etag`, `last_modified`, `is_index` and `entries` (each `loc` and
  `lastmod`, in document order), written atomically with sorted keys by `write_json`
  beside `frontier.json` (in `save_frontier`, so a dry run saves it too, as it saves the
  frontier) and read back by `load_frontier`; an absent file is no snapshot. Nothing
  drops a snapshot (Open points, item 2). `fetch_resource` (`pace.py` 150) gains a
  `validators: Validators | None = None` parameter, passed to `fetcher.fetch`, which
  only `fetch_sitemap` sets; robots.txt and `llms.txt` stay unconditional (`crawl.allium`
  790, 1186).
- **`max_age` and the clock.** `stale_pages` is every written page whose `last_seen` is
  more than `max_age` before `run.started_at` (`_stale_pages`), and nothing when
  `max_age` is null. A forced page is fetched without validators, and an unchanged raw
  document is still reconverted (`RewriteKnownPage`), its row ending `done`, not
  `unchanged`; its file is rewritten only if its text would differ. `FixedClock` stands
  still, so a scenario that needs a page to go stale gives the later sync a
  `FixedClock(START + ...)` past `max_age`; nothing sleeps.
- **The report's counts on a second sync.** `fetched` is `run.fetch_attempts`, so every
  page walked counts, 304 or not; `per_host` `fetched` is `host.fetched`, which a 304
  does not move and a raw-unchanged 200 does (`DisposeFetch`'s `else` branch);
  `converted` counts a page seen this run whose outcome is not `unchanged`;
  `skipped_unchanged` counts one whose outcome is `unchanged`, whether `RecordUnchanged`
  kept it or `RewriteKnownPage` reconverted it to the same body.
- **The obligation source.** `just plan-spec <module>` over `docs/specs/<module>.allium`
  at `ecfa257`, written to `ai_tmp/T14/plan-spec-<module>.txt` (its echo line to
  `ai_tmp/T14/plan-spec-<module>.err`): crawl 377, rovo 165, mirror 200, convert 47
  obligations. The obligations with no test named after them at `71437de` are in
  `ai_tmp/T14/uncovered-<module>.txt` (crawl 145, rovo 98, mirror 86, convert 0); the
  owned set of step 3 is `ai_tmp/T14/owned.json`, and the `NotInThisSlice` raises at
  `71437de` are in `ai_tmp/T14/notinthisslice-71437de.txt`. The copies are scratch,
  regenerated by step 0.

## Goal

From a clean checkout, against served fixture sites, a second `rovo sync` of a mirror
is incremental: it sends each known page's stored validators and each saved sitemap's,
keeps a page answered 304 or whose raw document did not change (`RecordUnchanged`, its
row `unchanged`), reconverts a page that did change or that `max_age` forces
(`RewriteKnownPage`), reuses a sitemap answered 304 (`ReuseUnchangedSitemap`), saves the
sitemap snapshots in `.rovo/sitemaps.json`, and, against an unchanged site, rewrites no
page file and no index file (`UnchangedRunIsStable`) and exits 0. Every owned obligation
listed under Steps has a test named after its id; no test sleeps for real; `just check`
is green; the Allium loop's witness record says `PASS`.

## Non-goals

- No page lifecycle: no removal on a 404 or 410, no redirect following, no move, merge,
  duplicate or revival; `RewriteKnownPage`'s merge branch stops the run (T15).
- No targeted or owner-testing run: the `run.targets` and `owner_testing` branches of
  `PrepareRun`, `FetchEntry` and `DisposeFetch` stay `NotInThisSlice` (T16, T20).
- No `skipped_not_html`: a non-HTML answer still stops the run.
- No browser tier: validators stay http-only, as they already are.
- No pruning of sitemap snapshots or of frontier rows (Open points, item 2).
- No harness change: `tests/e2e/conftest.py` is read, not changed (Facts).
- No new `rovo.toml` key, flag or environment variable (`crawl.max_age` exists); no new
  dependency; no new module, so `scripts/wheel_smoke.py`' `PACKAGE_FILES` does not move.
- No specification change: `docs/specs/` is read, not edited. The six `open question`
  blocks stay open (`crawl.allium` 2272 to 2274, `convert.allium` 473 to 475); none is
  on this slice's path. A specification gap found while planning, implementing, in weed
  or in review is never resolved in code or in the specification: every such gap joins
  the one batched needs-user question (Open points) and the ledger's `open_questions`.
- No change to the public API: `__all__` stays `["__version__"]`, so
  `docs/reference/api.md` does not move. No decision record changes.
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `src/rovo/_crawl/run.py` | shared, own lines | `dispose_fetch`'s two unchanged branches and its `PageFetched` branch for a known page, its last `NotInThisSlice("DisposeFetch")` narrowed (Context); `_handle_entry` routing an unchanged `CandidateDelivered` to the mirror; `fetch_sitemap` sending the snapshot's validators; `reuse_unchanged_sitemap`; the discovery loop handing a 304 with a snapshot to it, then to `expand_sitemap_entries`; `load_frontier` and `save_frontier` reading and writing `.rovo/sitemaps.json`; the module, `fetch_sitemap` and `save_frontier` docstrings |
| `src/rovo/_crawl/pace.py` | shared, own lines | `fetch_resource` gains `validators: Validators \| None = None`, passed to every try's `fetcher.fetch` |
| `src/rovo/_crawl/model.py` | shared, own lines | `SitemapSnapshot`'s docstring ("kept one run, T13") says the snapshots are saved; nothing else, unless step 4 shows a field missing |
| `src/rovo/_mirror/intake.py` | shared, own lines | `record_unchanged`, `discard_unchanged_without_page`, `rewrite_known_page` (its merge branch `NotInThisSlice("RewriteKnownPage")`); `settle_candidate`'s partition (Facts); the module docstring |
| `tests/fakes.py` | shared, own lines | only if step 3 needs it: a helper giving a `SiteResponse` with an `ETag` or `Last-Modified`, or a 304, beside `html_response` and `xml_response` |
| `tests/test_crawl.py` | shared, own lines | the crawl obligations of step 3 and the crawl guarantees; `test_rule_success_FetchSitemap`'s docstring (re-propagated) |
| `tests/test_mirror.py` | shared, own lines | the mirror obligations of step 3 |
| `tests/test_pace.py` | shared, own lines | `fetch_resource` sends the validators it is given on every try and none by default |
| `tests/test_commands.py` | shared, own lines | a second `sync` over `FakeFetcher`: exit 0, the rows `unchanged`, `skipped_unchanged`, the page file untouched |
| `tests/test_slice_boundaries.py` | shared, own lines (re-propagated) | `test_a_second_sync_of_a_known_page_stops` per Facts, renamed `test_a_second_sync_of_a_known_page_keeps_it` (ledger note); `RewriteKnownPage`'s merge branch and a known page's non-HTML answer asserted to stop |
| `tests/test_regressions.py` | shared, own lines | one test per divergence planning, weed or review finds |
| `tests/e2e/test_discovery_sync.py` | shared, own lines (re-propagated) | `test_observations_are_forgotten_after_the_retention_syncs` moves the rewritten `maps/guide.xml`'s mtime forward a minute (`os.utime`), else the sitemap answers 304 and `ReuseUnchangedSitemap` replays the orphan (ledger note) |
| `tests/e2e/test_second_sync.py` | new | the end-to-end scenarios (Acceptance criteria) and their site-generating helper; no unit test is named `test_second_sync.py` |
| `docs/reference/cli.md` | shared, own lines | `rovo sync`: a second sync is incremental (validators, 304, an unchanged raw document, reconversion, `max_age`, reused sitemaps, nothing rewritten on an unchanged site, the report's counts); the later-slice sentence loses "a page already in the mirror" and gains a canonical that merges a known page into another |
| `docs/reference/mirror.md` | shared, own lines | `.rovo/sitemaps.json`; "A sitemap's validators and entries last one run and are not yet saved" replaced; the `crawl.max_age` row, if its wording moves |
| `docs/reference/testing.md` | shared, own lines | `tests/e2e/test_second_sync.py` |
| `docs/project/repository-map.md` | shared, own lines | the tree gains `test_second_sync.py` |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` Added entry: incremental sync |
| `tickets/README.md`, `tickets/T14-incremental.md` | ticket | index row, graph, slice bullet, this ticket |
| `.allium-loop/T14-incremental.json`, `.allium-loop/T14-incremental.witness.json` | gitignored | the loop ledger and the witness record; never committed |

`pyproject.toml`, `uv.lock`, `pytest.ini`, `.coveragerc`, `ruff.toml`, `mypy.ini`,
`Justfile`, `AGENTS.md` (line 10 stays true), `scripts/wheel_smoke.py`,
`src/rovo/__init__.py`, `src/rovo/cli.py`, `src/rovo/_commands.py`, `src/rovo/_report.py`,
`src/rovo/_config.py`, `src/rovo/_crawl/fetch.py`, `src/rovo/_crawl/sitemaps.py`,
`src/rovo/_mirror/finalise.py`, `src/rovo/_mirror/indexes.py`, `src/rovo/_mirror/state.py`,
`src/rovo/_convert/`, `tests/e2e/conftest.py`, `tests/test_import_direction.py`,
`docs/decisions/` and `docs/specs/` are read, not changed. A file not in this table that
turns out to need a change is added to the table in the same change with its reason, or
handed back if it is a decision record or a specification.

## Steps

This slice has no **Adversarial review** checkpoint (`tickets/CONVENTIONS.md` §14): it
completes branches T09 left open and lays down no design a later lane builds on beyond
the snapshot file, which `docs/reference/mirror.md` states. Weed and the witness (step 7)
are its review.

0. `just check` baseline on the untouched worktree at `71437de` plus this ticket, last
   line quoted, and `{ time just py-test tests/e2e -ra; echo "exit $?"; } 2>&1 | tail -6`
   with its wall time. Scratch output goes in `ai_tmp/T14/`. Write `just plan-spec
   <module>` for each of `crawl`, `rovo`, `mirror` and `convert` to
   `ai_tmp/T14/plan-spec-<module>.txt`, confirm `ai_tmp/T14/owned.json` against them,
   re-run `rg -n 'NotInThisSlice\(' src` against `ai_tmp/T14/notinthisslice-71437de.txt`,
   and confirm the two `tests/test_slice_boundaries.py` facts (Facts, the first bullet).
   Create the ledger `.allium-loop/T14-incremental.json` against
   `allium-skill-reference/allium/schemas/ledger.schema.json`, shaped like T13's: `goal`
   `"T14-incremental"`, `mode` `"spec-first"`, `tick` 0, `specification_base` `ecfa257`,
   `obligation_source` the four files, and `open_questions` holding the six
   specification open questions verbatim and the batched question of the Open points,
   each item marked OPEN. Read `.agents/skills/propagate/SKILL.md`,
   `.agents/skills/weed/SKILL.md`, `.agents/skills/witness/SKILL.md` and
   `.agents/skills/python-change/SKILL.md` before step 3.

1. **The mirror rules.** In `intake.py`, `record_unchanged`,
   `discard_unchanged_without_page` and `rewrite_known_page`, each returning `None` when
   its guards do not hold, and `settle_candidate`'s partition (Facts). Every value comes
   from the candidate, the mirror or the clock, never a literal; the discard reason is
   the specification's `"no page to confirm"`.

2. **The crawl rules.** In `run.py` and `pace.py`, per the Context table:
   `dispose_fetch`'s branches in the specification's order, `_handle_entry`'s routing,
   `fetch_resource`'s validators, `fetch_sitemap` sending a snapshot's,
   `reuse_unchanged_sitemap` (a 304 with no snapshot still meets no rule), and the
   snapshots saved and loaded with the frontier.

3. **Tests first, from the obligations** (the `propagate` skill, spec-first). Write a
   failing test for each owned obligation below into the test file of its module, named
   `test_<obligation id with dots and hyphens as underscores>`, its docstring quoting the
   obligation's description from the plan-spec file. Each `rule_failure` test makes
   exactly one `requires` clause false. Generated tests satisfy EditorConfig
   (indentation in 4-space multiples in `*.py`, string literals included), ruff and
   mypy, since the gate stages them. Run `just py-test` and record the red run in
   `ai_tmp/T14/red.txt`, its summary line under `last_results.propagate` in the ledger.
   Record each generated or re-propagated test file's SHA-256 under
   `generated_test_hashes`, and the reconciliation line (`N obligations, M covered, K
   uncovered`) over the owned set. A test changed after the red run is re-recorded: a
   new hash, `tick` incremented, a ledger note naming the test and why; never silently.
   An obligation a test cannot reach without a later slice's behaviour is not owned:
   move it to the hand-back notes with its reason rather than writing a vacuous test.

   Owned obligations, new in this slice (ids as `just plan-spec <module>` emits them at
   `ecfa257`; 22):

   - **`crawl`** (8), in `tests/test_crawl.py`: `entity-optional.Run.max_age` (null and
     a duration, the latter making a page stale), `entity-fields.LadderWalk` (its
     `conditional` first matters here), `transition-edge.FrontierEntry.in_progress.unchanged`,
     `transition-edge.FrontierEntry.unchanged.pending`,
     `transition-edge.FrontierEntry.done.pending` (both re-pends by `PrepareRun` on a
     second run), `rule-success.ReuseUnchangedSitemap`,
     `rule-failure.ReuseUnchangedSitemap.1` (not a 304),
     `rule-failure.ReuseUnchangedSitemap.2` (a 304 with no snapshot).
   - **`mirror`** (14), in `tests/test_mirror.py`: `entity-optional.Page.previous_digest`,
     `entity-optional.Page.etag`, `entity-optional.Page.last_modified`,
     `entity-optional.PageCandidate.etag`, `entity-optional.PageCandidate.last_modified`,
     `rule-success.RewriteKnownPage`, `rule-failure.RewriteKnownPage.1`,
     `rule-failure.RewriteKnownPage.2`, `rule-success.RecordUnchanged`,
     `rule-failure.RecordUnchanged.1`, `rule-failure.RecordUnchanged.2`,
     `rule-success.DiscardUnchangedWithoutPage`,
     `rule-failure.DiscardUnchangedWithoutPage.1`,
     `rule-failure.DiscardUnchangedWithoutPage.2` (on unit inputs, Context).
   - **`rovo`**, **`convert`**: none.

   Extended, not new (re-propagated in place, same names, each re-hashed in this slice's
   ledger with a note naming its origin slice; T09's to T13's ledgers are never edited):
   `test_a_second_sync_of_a_known_page_stops` (Facts), renamed
   `test_a_second_sync_of_a_known_page_keeps_it`, the old name in its ledger note;
   `test_rule_success_FetchSitemap` (`tests/test_crawl.py` 4064), its docstring only
   ("no snapshot is ever loaded in this slice" becomes "no snapshot is saved yet");
   `test_rule_success_DisposeFetch`
   only if step 4 shows its single-branch expectation red; every earlier test the red
   run shows red because a known page no longer stops the run, each with only that
   expectation moved. Claim an earlier test "passes unedited" only where it does; the
   hand-back notes list every earlier test this slice edited.

   Guarantees and black boxes (no obligation id; hand-written), in `tests/test_crawl.py`
   unless named: `DisposeFetch`'s unchanged branches (a 304 on a known page keeps
   `known.raw_digest` and takes the 304's validators; a raw-unchanged 200 counts
   `host.fetched`; a page in `forced_refetch`, a changed processing signature and a
   redirect hop each defeat `raw_unchanged`); `FetchEntry`'s `conditional` false for a
   page past `max_age`, a changed processing signature and a newer sitemap `lastmod`,
   each sending no validators; a conditional walk sends both stored validators
   (`If-None-Match` from an `ETag`, on `ScriptedFetcher`); `RecordUnchanged` keeping a
   stored validator the answer lacks and taking the entry's `lastmod` so the next run is
   conditional again; the snapshots' round trip through `.rovo/sitemaps.json` (sorted by
   URL, sorted keys, an absent file is no snapshot) and a dry run saving them;
   `fetch_resource` passing its validators on every retry (`tests/test_pace.py`);
   `UnchangedRunIsStable` on unit inputs (`tests/test_commands.py`: two syncs over one
   `FakeFetcher`, the page file's `st_mtime_ns` and `st_ino` and every index file's
   unchanged).

   Not owned, and why, for the hand-back notes: `entity-optional.Page.redirect_target`,
   `entity-optional.PageCandidate.redirect_target`, `rule-*.RejectDuplicateCandidate`,
   `rule-*.MovePage`, `rule-*.ReviveRemovedPage`, `rule-*.RemoveAbsentPage`,
   `rule-*.AcceptAbsentWithoutPage`, `rule-*.RemoveRedirectedOutPage`,
   `rule-*.AcceptRedirectedOutWithoutPage`, `rule-*.RetirePage`,
   `rule-*.RetireOutOfScopePages`, `transition-edge.FrontierEntry.in_progress.absent`,
   `.in_progress.duplicate` and their `-> pending` edges (T15);
   `transition-edge.FrontierEntry.in_progress.skipped_not_html` and
   `.skipped_not_html.pending` (not this slice: a non-HTML answer keeps its stop);
   `rule-*.FailDiscardedEntry` (left outside T09's owned set, covered by
   `tests/test_unplaceable_candidate.py`, and claimed by no slice; T14's
   `no page to confirm` path is unit-only and does not change that); every other uncovered
   obligation in the four files, each belonging to the slice its rule names.

4. **Mirror and crawl** (`src/rovo/_mirror/intake.py`, `src/rovo/_crawl/`). Steps 1 and
   2. Unit cases on `FakeFetcher` and `ScriptedFetcher` with `FixedClock`. `just py-test
   tests/test_mirror.py tests/test_crawl.py tests/test_pace.py tests/test_commands.py
   tests/test_slice_boundaries.py tests/test_regressions.py`, then `just py-lint`,
   `just py-typecheck`, `just coverage` and `just wheel-smoke`, quoting its `api` line.

5. **End to end.** No new static fixture site: every site is generated into `tmp_path`
   by `tests/e2e/test_second_sync.py`' helper, served first and written after
   (`http.server` reads each file per request), as `tests/e2e/test_discovery_sync.py`
   does; the helper is the module's own, not imported from that module. Each page has a
   `<title>` and a `<main>` holding an `h1` and a paragraph of prose, two-space
   indentation and a final newline. The base site: `robots.txt` (`User-agent: *`,
   `Sitemap: <base>maps/guide.xml`); `maps/guide.xml`, a `urlset` naming
   `<base>guide/orphan.html` and `<base>outside/page.html`; `guide/start.html` (the
   seed) linking `guide/linked.html`; `guide/linked.html`, `guide/orphan.html` and
   `outside/page.html`, linking nothing; no `llms.txt`. The scenarios are the Acceptance
   criteria's; they run `rovo._commands.sync` in process over a real `HttpxFetcher` with
   a `FixedClock` (which never sleeps), the robots.txt declaring no Crawl-delay.
   `just py-test tests/e2e -ra`, its wall time quoted beside step 0's.

6. **Documents** (the `review-docs` skill). The pages of the Files touched table; find
   the sentences this slice makes false with
   `rg -n -i "second sync|already in the mirror|last one run|not yet saved|incremental|max_age|unchanged" -g '*.md' -g '!tickets/**' -g '!allium-skill-reference/**' -g '!docs/specs/**' -g '!docs/decisions/**'`;
   `CHANGELOG.md` `Unreleased` gains one Added entry. Keep the required phrases of
   `AGENTS.md` in always-visible text. `just check-docs`, `just check-agents`, and
   `just lint`, whose hooks include markdownlint over this ticket.

7. **Witness** (the `weed` and `witness` skills). Run `weed` over `crawl` and `mirror`
   against the code, scoped to the owned and extended obligations, the Realised rules of
   the Context table and the guarantees; record its verdict under `last_results.weed`
   and fix any code divergence, each with a regression test in
   `tests/test_regressions.py`. A divergence weed attributes to the specification is not
   fixed: it joins the one batched needs-user question. Then run `witness`
   non-interactively: it writes `.allium-loop/T14-incremental.witness.json` per
   `witness-result.schema.json`. The verdict must be `PASS`; a `FAIL` routes back per the
   skill, and the hand-back notes record each round. A batched question still OPEN does
   not block `PASS` unless it blocks an owned obligation; the witness escalates one that
   does.

8. Hand-back notes, `status: done`, `just check` ending with
   `All checks passed and the worktree is unchanged.`, `git status --short` empty after
   the commit. Commit on the branch. **Authorisation required**: pushing and opening the
   pull request.

## Acceptance criteria

- **End to end, an unchanged site** (`test_an_unchanged_site_syncs_again_without_rewriting_a_file`,
  in process): the base site (step 5) at `<base>`; `rovo init <base>guide/start.html
  <tmp>/out`, then `rovo._commands.sync` exits 0 and writes `start`, `linked` and
  `orphan`. `.rovo/sitemaps.json` holds one snapshot, `<base>maps/guide.xml`, with
  `etag: null`, a non-null `last_modified`, `is_index: false` and the two entries in
  document order. The test records the bytes, `st_mtime_ns` and `st_ino` of every file
  under `<out>` outside `.rovo/` except `crawl-report.json`, and the length of the
  server's log. A second sync (a new `HttpxFetcher`, the same `FixedClock`) exits 0;
  its requests (the log past the recorded length) are `/robots.txt`, `/maps/guide.xml`,
  `/sitemap.xml`, `/sitemap_index.xml`, `/llms.txt`, then each of the three pages
  exactly once. Every recorded file has the same bytes, `st_mtime_ns` and `st_ino`
  (`UnchangedRunIsStable`); no file was added outside `.rovo/`. In `frontier.json` the
  three page rows are `unchanged`; the outside page's `observed_urls` row has
  `last_seen_run: 2`, which only the reused snapshot's entries can give, since
  `/maps/guide.xml` was answered 304 (`ReuseUnchangedSitemap`). `crawl-report.json` has
  `exit_code: "ok"`, `fetched: 3`, `converted: 0`, `skipped_unchanged: 3`, three
  `changes` of kind `unchanged`, `failed_urls: []`, and `per_host`'s one row `fetched: 0`
  (every page answered 304).
- **End to end, a changed page, a raw-unchanged page and `max_age`**
  (`test_a_second_sync_reconverts_what_changed_and_what_max_age_forces`, in process):
  the base site with `guide/start.html` also linking `guide/plain.html`, which is served
  by `always={"/guide/plain.html": Answer(200, {"Content-Type": "text/html"}, <page>)}`
  (no `Last-Modified`, no `ETag`). First sync exits 0 and writes four pages. Then
  `guide/start.html` gets a new paragraph and an mtime 60 s later (`os.utime`); a second
  sync exits 0: `start` is reconverted (`RewriteKnownPage`), its page file rewritten
  with the new paragraph and its row `done`; `plain` is answered 200 with the same bytes
  (`raw_unchanged`), its row `unchanged` and its page file's `st_mtime_ns` unchanged;
  `linked` and `orphan` are answered 304, rows `unchanged`; the report has `converted:
  1`, `skipped_unchanged: 3`, `changes` holding one row of kind `changed` (`start`) and
  three of kind `unchanged`, and `per_host` `fetched: 2`. Then `rovo.toml`'s commented
  `# max_age = 86400` under `[crawl]` becomes `max_age = 60` and a third sync runs at
  `FixedClock(START + timedelta(minutes=5))`: every page is past `max_age`, so it is
  fetched without validators (the unit tests prove none is sent) and answered 200, and
  every page row ends `done` (reconverted, not `unchanged`); the report has
  `converted: 0`, `skipped_unchanged: 4` (the bodies came out the same) and `per_host`
  `fetched: 4`; and no page file's `st_mtime_ns` moved since the second sync.
- **End to end, earlier scenarios**: `tests/e2e/test_init_sync.py`,
  `tests/e2e/test_follow_links.py`, `tests/e2e/test_index_files.py`,
  `tests/e2e/test_polite_sync.py`, `tests/e2e/test_discovery_sync.py` and
  `tests/e2e/test_harness.py` pass unedited, unless the ledger names an edit and why.
- Every owned obligation in step 3 has a test named after it, red before the code and
  green after (`ai_tmp/T14/red.txt` and the final run); the reconciliation line shows
  zero uncovered; every extended test is re-hashed in the ledger with its note; every
  obligation dropped from the owned list is in the hand-back notes with its reason.
- No test sleeps for real: `rg -n 'time\.sleep\(' tests; test $? -eq 1`, and
  `test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py`; every `CliRunner` sync that
  makes two requests to one host patches `pace.time.sleep` first.
- The `NotInThisSlice` raises in `src/` are those of `ai_tmp/T14/notinthisslice-71437de.txt`
  plus `RewriteKnownPage` (the merge branch), with `DisposeFetch`'s two raises still
  present but no longer reached by a 304 on a known page or a known page's ok HTML
  answer (`rg -n 'NotInThisSlice\(' src` compared with that file, the difference
  quoted).
- `fetch_resource` is called with validators only from `fetch_sitemap`
  (`rg -n 'fetch_resource\(' src`, quoted).
- `.allium-loop/T14-incremental.witness.json` exists with `"verdict": "PASS"`, and the
  ledger validates against `ledger.schema.json` with the batched question's items OPEN
  unless the maintainer answered them.
- `just check-specs` and `just analyse-specs` pass with `docs/specs/` unchanged since
  `ecfa257` (`git diff --stat ecfa257 -- docs/specs` empty).
- `import rovo` loads no module outside the standard library and `rovo`; `__all__` is
  `["__version__"]`; `just wheel-smoke` passes with the package-file count unchanged.
- `just coverage` stays at or above the floor of 95.
- `just check-docs` and `just check-agents` pass; `docs/reference/cli.md` describes what
  a second `rovo sync` does, and `docs/reference/mirror.md` describes
  `.rovo/sitemaps.json`.
- `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty after the commit.

## Verification

```sh
just plan-spec crawl > ai_tmp/T14/plan-spec-crawl.txt
just plan-spec rovo > ai_tmp/T14/plan-spec-rovo.txt
just plan-spec mirror > ai_tmp/T14/plan-spec-mirror.txt
just plan-spec convert > ai_tmp/T14/plan-spec-convert.txt
git diff --stat ecfa257 -- docs/specs
just py-test tests/test_crawl.py tests/test_mirror.py tests/test_pace.py tests/test_commands.py tests/test_slice_boundaries.py tests/test_regressions.py -ra
{ time just py-test tests/e2e -ra; echo "exit $?"; } 2>&1 | tail -6
just py-lint
just py-typecheck
just coverage
just wheel-smoke
uv run --frozen python -I -c "import rovo, sys; print(sorted(m for m in sys.modules if not m.startswith(('rovo', '_')) and m not in sys.stdlib_module_names))"
rg -n 'NotInThisSlice\(' src  # compared with ai_tmp/T14/notinthisslice-71437de.txt
rg -n 'fetch_resource\(' src  # validators only from fetch_sitemap
rg -n 'time\.sleep\(' tests; test $? -eq 1  # only "no match" passes
test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py
rg -n "kept one run|last one run|not yet saved" src docs/reference; test $? -eq 1  # only "no match" passes
just lint  # markdownlint over this ticket among the hooks
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

To be written by the executing agent: the baseline and the e2e wall time before and
after; the intake partition, the unchanged routing and the snapshot file as built, and
any departure from Facts and steps 1 and 2; the red run and the reconciliation line;
every extended or re-propagated test, its origin slice and its new hash; every
obligation dropped from the owned list and why; the weed verdict and the witness
verdict, each round; the one batched needs-user question with every gap found while
planning, implementing, in weed or in review, and the maintainer's answer if one
arrived; the verification output, each headed by its commit.

## Open points

- **The T14 batched needs-user question: OPEN.** One question to the maintainer, its
  items numbered so an answer can cite them; all three were found while planning T14.
  Each states the interim this slice builds, which is the specification as written,
  reversible and never presented as the answer; propagate copies every item into the
  ledger's `open_questions` as OPEN, and the witness escalates one that blocks
  convergence (none blocks an owned obligation). A gap found later (propagate,
  implement, weed) joins this question as a new item, never resolved in code. Line
  numbers are at `ecfa257`.
  1. **An unchanged page's links are not followed again.** `RecordUnchanged`
     (`mirror.allium` 903 to 922) raises `PageStored` and no `LinksFound`, so
     `EnqueuePageLinks` (`crawl.allium` 1961) never sees an unchanged page's links. The
     rows its earlier runs enqueued persist and are re-pended, so a stable scope loses
     nothing; but when the scope widens between syncs (a path prefix or an include
     pattern added, which moves neither the processing signature nor the raw digest), a
     link an unchanged page holds to a newly admitted URL is never enqueued until that
     page changes or `max_age` forces its reconversion. Should a sync re-enqueue an
     unchanged page's stored links, or is a scope change meant to need `max_age` or a
     changed page? Interim: as written, no `LinksFound` for an unchanged page.
  2. **Sitemap snapshots are never dropped.** No rule removes a `SitemapSnapshot`
     (`crawl.allium` 358 to 368, `AcceptFreshSitemap` 1091 only creates or updates one),
     so a sitemap no longer declared, now absent, or no longer a sitemap keeps its
     snapshot, and `.rovo/sitemaps.json` only grows; a later 304 to it would reuse
     entries read long before. Should a snapshot be dropped when its sitemap answers
     absent or not a sitemap, or after some runs unseen, as `ObservedUrl` is after
     `observed_url_retention_syncs`? Interim: every snapshot is kept.
  3. **An unchanged body can still rewrite its page file.** `UnchangedRunIsStable`
     (`mirror.allium` 1480 to 1485) says a sync against an unchanged site rewrites no
     page file and no index file, yet `PageFileProvenance` (1460) puts `etag` and
     `last_modified` in the frontmatter and `IndexEntry` (185 to 203) puts
     `last_modified` in `index.jsonl`, and `RecordUnchanged` takes a new value of each.
     A server that stamps every answer with a fresh `Last-Modified` or `ETag` while the
     body stays byte-identical (common on generated sites) therefore makes every sync
     rewrite every page file and `index.jsonl`. Is a moved validator an upstream change
     the mirror should show, or should validators stay out of the files the guarantee
     covers? Interim: as written, the validators are written and the file moves.
- **Carried, not touched by T14.** The T13 follow-up batched question's items 1 to 3
  (one URL falling due twice with different `declared` values; the speculative pause's
  length; speculative children counting toward `sitemap_children_read`) stay OPEN in
  `tickets/T13-discovery.md` and its ledger; this slice changes none of those
  behaviours, so they are not part of T14's batch. Items 4 and 5 there stay carried to
  T17 and T18.
- **The specification's open questions.** The three `crawl.allium` ones (2272 to 2274)
  and the three `convert.allium` ones (473 to 475) stay open; none is on this slice's
  path. The second (a URL that fails on every sync is retried for ever) is reached by
  every second sync, whose `PrepareRun` re-pends every failed row; its interim holds
  and nothing here changes it.
- **`NotInThisSlice`.** A development guard, not product behaviour: each later slice
  removes the raises it implements, and the last slice's review confirms none is left.
  This slice narrows `DisposeFetch`'s and `PageCandidate.created`'s and adds
  `RewriteKnownPage`'s merge branch (Acceptance criteria).
