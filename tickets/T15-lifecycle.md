---
id: T15
title: "Page lifecycle: rovo sync removes and archives absent pages, follows redirects within the scope, moves and merges pages with their aliases, revives returning pages, settles duplicates and retires pages a narrowed scope no longer admits"
status: open
depends_on: [T14]
parallel_with: []
branch: full-final-prototype
estimated_size: L
---

# T15: Page lifecycle: rovo sync removes and archives absent pages, follows redirects within the scope, moves and merges pages with their aliases, revives returning pages, settles duplicates and retires pages a narrowed scope no longer admits

## Context

T09 (`fd1b423`), T10 (`9fd11fd`), T11 (`d2979c8`, `2658231`), T12 (`7a9c135`), T13
(`f5683e3`, follow-up `71437de`) and T14 (`6a50e9d`, follow-up `0475304`) are slices 1
to 6. `rovo sync` reads each origin's robots.txt, paces and retries per host name, reads
sitemaps and `llms.txt`, fetches the seeds, the pages discovery admits and the pages they
link to, publishes each at `pages/<host>/<path>`, writes the indexes and
`crawl-report.json`, and a second sync is incremental. They fixed every pattern this
slice follows: the private subpackages `rovo._convert`, `rovo._mirror` and `rovo._crawl`
with `rovo._config`, `rovo._report` and `rovo._commands` above them (import direction
enforced by `tests/test_import_direction.py`), the `Fetcher` seam (`HttpxFetcher` in
`src/rovo/_crawl/fetch.py`, which follows no redirect), the `Timer` seam of
`src/rovo/_crawl/pace.py` (`FixedClock`, `SteppingTimer`, `FakeFetcher`,
`ScriptedFetcher` and `StampingFetcher` in `tests/fakes.py`), obligation-named tests
(`test_<obligation id>`), the end-to-end harness `serve_site` in `tests/e2e/conftest.py`
with scripted answers (`Answer`, `DROP`, `script=`, `always=`) and its request log, the
state files of `docs/reference/mirror.md`, and the development guard
`rovo._unfinished.NotInThisSlice`. Read `tickets/T14-incremental.md` (its Context table,
Facts and Open points), `tickets/T13-discovery.md` (its Facts),
`src/rovo/_crawl/run.py`, `src/rovo/_crawl/pace.py`, `src/rovo/_mirror/intake.py`,
`src/rovo/_mirror/finalise.py` and `tests/e2e/test_second_sync.py` before starting.

This is slice 7 of T08 to T20, run in this worktree on `full-final-prototype`. Until
now a page lives for ever once written, and every lifecycle answer stops the run: a 404
or 410, an out-of-scope or looping redirect and a followed one all reach
`dispose_fetch` (`run.py` 1340), which raises `NotInThisSlice("DisposeFetch")` for a raw
3xx (1376) and for its `earlier_branch` (1397); a 3xx to robots.txt, a sitemap or
`llms.txt` raises `NotInThisSlice` in `fetch_robots` (322), `fetch_sitemap` (756) and
`read_llms_txt` (941); a canonical that merges a known page into another written page
raises `NotInThisSlice("RewriteKnownPage")` (`intake.py` 285); any converted candidate
that `StoreNewPage`, `RefuseUnplaceableCandidate` and `RewriteKnownPage` do not take (a
duplicate in one run, a move, a revival) ends at `NotInThisSlice("PageCandidate.created")`
(`intake.py` 310); and `finalise` (`finalise.py` 232) raises
`NotInThisSlice("RetireOutOfScopePages")` (246) for a written page whose source URL the
scope no longer admits. `PrepareRun` already re-pends removed pages at
`deferred_priority` (`run.py` 227), `record_alias` already re-points an alias whose URL
is a removed page's (`intake.py` 203), `link_to_removed_page` already resolves a link to
a removed page as `dangling` (`links.py` 94), the manifest already round-trips
`moved_from`, `removed_at` and `removal_reason` (`state.py` 213, 229), and `PublishPage`
already reports `moved` with `previous_path` (`finalise.py` 214). The specification base
is `a0814ab` (`git diff --stat a0814ab HEAD -- docs/specs` is empty); every
specification line number below is at `a0814ab`, every source line number at `0475304`.

### The specified path, and what this slice does with each rule on it

| Class | Rules |
| --- | --- |
| **Realised** (every branch reachable in this slice, or constructible on unit inputs where noted) | `mirror.allium`: `RejectDuplicateCandidate` (560), `RewriteKnownPage` (592) its merge branch (`previous != target`, `PageRetired(merged)`), `MovePage` (619), `ReviveRemovedPage` (728), `RemoveAbsentPage` (938), `AcceptAbsentWithoutPage` (948), `RemoveRedirectedOutPage` (957), `AcceptRedirectedOutWithoutPage` (967, on unit inputs only: `DisposeFetch` delivers `redirected_out` only for a known page), `RetirePage` (984; its `prune` branch on unit inputs only, Open points item 3), `RetireOutOfScopePages` (1020); the guarantees `RemovedAreaKeepsPath` (1503) and `EveryCandidateIsSettled` (1546), now with `CandidateDuplicate` and `PageRemoved` among the answers. `crawl.allium`: `DisposeFetch` (1850), its `absent` branch (`entry.status = absent`, an `absent` candidate with no validators), its `redirected_out and exists known` branch (`entry.status = done`, a `redirected_out` candidate carrying `redirect_target`) and its `unfollowed_redirect` branch (`EntryFailed` with `"redirect loop"`, `"too many redirects"` or `"redirected out of scope"`); `SettleDuplicateEntry` (1985); redirect following in `fetch_or_render` (the `AttemptTier` guidance, 1559 to 1567: in-scope hops followed, at most `discovery_max_redirects`, never revisiting, recorded in `redirect_hops`; otherwise `redirect_location` with its `redirect_stop`) and in `fetch_resource` (the `FetchRobots` guidance, 811 to 820: at most `discovery_max_redirects` redirects within the allowed hosts, anything else an error), so robots.txt (`FetchRobots`, 791), a sitemap (`FetchSitemap`, 984) and `llms.txt` (`ReadLlmsTxt`, 1211) follow redirects too; the guarantee `RedirectsFollowedOnlyInScope` (2264); the frontier edges `in_progress -> absent`, `in_progress -> duplicate` and `absent -> pending` (the last by `PrepareRun`'s removed-page recheck, 645). `rovo.allium`: `TallyRemoval` (590). |
| **Traversed, nothing new to do** | `PrepareRun` (645): already re-pends a removed page in scope at `deferred_priority`, the row `ReviveRemovedPage` then meets. `RecordAlias` (876) and `DropAliasOfOwnIdentity` (888): already written; a merge or a move now reaches the removed-own branch. `RefreshPage` (817): already records the requested identity, every hop and the source URL as aliases, so a move or a duplicate leaves its old URLs resolving to the page. `ResolveMirrorLinks` (1035), `LinkToRemovedPage` (1072): a link to a removed page is already `dangling`, and to an alias already resolves to its target. `PublishPage` (1149): already gives `moved` and `previous_path` when `was_moved`, and `added` for a revived page (`previous_digest = null`). `TallyFinalisedPage` (603) and `CloseRun` (626): already list `moved` and `added` changes. `RefuseUnplaceableCandidate` (802) and `FailDiscardedEntry` (1993): a move or revival with no free path is refused as a new page is. `SettleStoredEntry` (1977): a moved, revived or merged page settles its row `done`. |
| **Later slices'** | A soft or hard verdict and a 429 that survives (T18's `classify_block` and breaker); a browser render's redirects (T19); the targeted and owner-testing branches of `PrepareRun`, `Enqueue` and `DisposeFetch` (T16, T20), so the edge `duplicate -> pending`, reached only by a targeted or owner-testing run, is not this slice's; `InterruptRun` and `in_progress -> pending` (T16); `VerifyPages` and `rovo verify` (T16); `SaveOwnership` (T20); a failed URL's report row beyond what T12 writes (T16). |
| **Outside this slice; reaching one still stops the run** | The 23 raises at `0475304` that stay (step 0's `rg` output minus the seven below), by `rule=`: `sitemap_admitted` (`sitemaps.py` 82); in `run.py`, `PrepareRun` (218), `Discover` (250), `RetireHostOnLongRetryAfter` (320, 753, 1679), `RetireHostOnLongCrawlDelay` (326), `EnqueuePageLinks` (620), `RefollowUnchangedLinks` (661), `SelectBatch` (1111), `AttemptTier` (1225), `classify_block` (1247, 1545, 1547), `DisposeFetch` (1397), `ConvertFetched` (1438), `StartRun` (1606), `Escalate` (1684), `BreakerTrips` (1687); `assign_path` (`urls.py` 149); `UncarryableBecomesIsland` (`fidelity.py` 158, 192) and `BodyShape` (558). Every other raise at `0475304`, these seven, this slice removes: `FetchRobots` (`run.py` 322), `FetchSitemap` (756), `ReadLlmsTxt` (941), `DisposeFetch`'s raw-3xx raise (1376), `RetireOutOfScopePages` (`finalise.py` 246), `RewriteKnownPage` (`intake.py` 285) and `PageCandidate.created` (310: after this slice the intake partition is total for all four outcomes, so the fallback is unreachable and goes). `DisposeFetch`'s second raise (1397) stays, narrowed to a soft verdict (T18) and a non-HTML answer (`skipped_not_html`, Open points, scope note). |

### Facts a later reader would otherwise rediscover

- **The redirect follower, one per fetch.** `HttpxFetcher` keeps `follow_redirects=False`
  (`fetch.py` 50) and gains the raw `Location` header of a 3xx answer in a new
  `SiteResponse` field (`location`, `model.py` 318), never in `redirect_location`, whose
  specified meaning is an unfollowed redirect's target. The follower lives in
  `pace.py`, used by `attempt_tier` (`run.py` 1219, the http tier's `fetch_or_render`)
  and by `fetch_resource` (`pace.py` 150). Per hop: an answer in 301, 302, 303, 307 or
  308 with a `Location` is a redirect; the `Location` is resolved against the current
  URL (RFC 3986, as `sitemaps.resolve_url` does); the target is tested (a page: the scope's
  `within_bounds`, Open points item 7; `fetch_resource`: its host among the allowed
  hosts); a target already visited in this fetch, the requested URL included, compared
  by identity, stops with `loop`; the hop past `CONFIG.discovery_max_redirects` stops
  with `hop_limit`; a page's out-of-scope target stops with `out_of_scope`. A stopped
  page fetch returns the last answer with `redirect_location` (the resolved target) and
  `redirect_stop`; a stopped `fetch_resource` returns an error answer, and so does a 3xx
  it gets with no usable `Location`. An error answer to robots.txt meets
  `DenyAllWhenRobotsUnreachable`, so a robots.txt that redirects off the allowed hosts,
  loops, passes the hop limit or lacks a `Location` disallows its origin and is
  reported `robots_unreachable`; a sitemap's or `llms.txt`'s error answer meets the
  rules an unreachable one already meets. Every hop waits
  its turn on the destination host name's limiter (`wait_turn`), reading the
  destination origin's robots.txt first when the run has not (Open points item 5; a
  page's hops and a sitemap's or `llms.txt`'s, never the hops of `FetchRobots`' own
  fetch, since robots.txt is not governed by robots.txt, RFC 9309: those are bounded
  only by the allowed hosts, the hop limit and the no-revisit test), and its bytes count toward `bytes_fetched` as they arrive; hops never count toward
  `fetch_attempts`. Validators go on the first request only (Open points item 6;
  `raw_unchanged` already needs zero hops). A retryable answer at any hop ends the try
  with that answer; the retry restarts at the requested URL. The final answer's
  `source_url` is the URL that answered and `redirect_hops` every URL left behind, the
  requested one first.
- **When the files move.** `RetirePage`, `MovePage` and `ReviveRemovedPage` raise
  `PageFileArchived`, `PageFileDeleted`, `PageFileMoved` and `ArchivedCopyDeleted` at
  intake, but the manifest is saved only after finalisation (`drive_run`, `run.py`
  1596) and `RefreshPage`'s guidance says no file is written at intake. Interim (Open
  points item 1): the mirror records each file effect in memory as its rule fires
  (`RetireOutOfScopePages`' effects at the start of the pass), and `finalise` applies
  them in order before `PublishPage`, each idempotent: a missing source is a no-op, an
  existing destination is replaced atomically. Pending effects compose per page path
  as they are recorded: recording `PageFileArchived(path)` while an unapplied
  `ArchivedCopyDeleted(path)` is pending cancels that deletion and records no archive
  (the archive already holds the last published bytes), so a page revived and retired
  again in one run keeps its archived copy. An archive takes
  `pages/<host>/<relative path>` to `_removed/<host>/<relative path>`; a move deletes the
  old page file once `PublishPage` has written the new one; `ArchivedCopyDeleted`
  deletes `_removed/<path minus pages/>`. A directory under `pages/` or `_removed/`
  left empty is removed (Open points item 2). So a run interrupted before its finalise
  pass leaves the disk as the last finalisation left it. A crash inside the pass, after
  an effect and before `save_mirror`, can leave files ahead of the manifest: the next
  finalisation's `PublishPage` rewrites a written page whose file is missing, and a
  stale archived copy stays until the page is retired again; crash recovery is T16's
  (`InterruptRun`, `RecordCrashAfterRun`).
- **The intake partition, complete.** `settle_candidate` (`intake.py` 291) fires, in
  this order: `StoreNewPage`, `RefuseUnplaceableCandidate`, `RejectDuplicateCandidate`
  (target written and stored this run), `RewriteKnownPage` (target written, stored in an
  earlier run; when `known_page(requested_identity)` is another page it is retired
  `merged` first), `MovePage` (a known page, no target or a removed one; a removed
  target's record leaves `mirror.pages` and its archived copy is deleted; a stale alias
  of the new identity is dropped), `ReviveRemovedPage` (no known page, a removed
  target), `RecordUnchanged`, `DiscardUnchangedWithoutPage`, `RemoveAbsentPage`,
  `AcceptAbsentWithoutPage`, `RemoveRedirectedOutPage`,
  `AcceptRedirectedOutWithoutPage`. Exactly one fires per candidate; the result is
  `PageStored`'s page, `CandidateDuplicate`, `CandidateDiscarded`, `PageRemoved`, or,
  for the two `Accept…WithoutPage` rules, none (Open points item 8).
  `RetirePage` requires a written page, so a removed page is never reported removed
  again: its next 404 meets `AcceptAbsentWithoutPage` (`known_page` skips removed
  pages).
- **Removals reach the report two ways.** Intake removals (`RemoveAbsentPage`,
  `RemoveRedirectedOutPage`, a merge) happen during the run and travel in
  `CrawlResult` (`run.py` 131, a new `removed` tuple of `PageRemoved`);
  `RetireOutOfScopePages`' happen in the finalise pass and travel in `Finalisation`
  (`finalise.py` 153, likewise). `_commands.sync` hands both to
  `_report.tally_removal` (`TallyRemoval`), intake removals first, so `changes` gains
  one `removed` row (`url`, `path`, `moved_from: null`) per removal.
- **An absent URL with no page is silent.** A URL never written that answers 404 or
  410, the seed included, meets `AcceptAbsentWithoutPage`: its row is `absent`, and the
  report gains no `failed_urls`, `changes` or `unresolved_urls` row (the
  `unresolved_urls` guidance, `crawl.allium` 2088 to 2093, excludes confirmed absent
  outcomes), so a sync whose only seed is absent exits 0 over an empty mirror.
- **What a lifecycle row does to the frontier.** An absent answer settles its row
  `absent`; a redirected-out known page settles `done`; an unknown URL redirected out,
  a loop and a hop limit fail the row (`EntryFails`, its error the specification's
  text, a `failed_urls` row as today); a duplicate settles `duplicate`
  (`SettleDuplicateEntry`); a moved, merged or revived page settles `done`. A standard
  run re-pends only written pages, removed pages and `retry_entries` (Open points
  item 4).
- **What `http.server` answers.** A deleted fixture file answers 404 with no scripting.
  A redirect is scripted: `script={"/guide/old.html": [Answer(200, {"Content-Type":
  "text/html"}, <page>)]}` serves the page to the first sync, then
  `always={"/guide/old.html": Answer(301, {"Location": "/guide/new.html"})}` answers
  every later request. So `tests/e2e/conftest.py` is read, not changed. A changed or
  restored file has its mtime moved a minute forward (`os.utime`), or it answers 304
  (T14 Facts).
- **The obligation source.** `just plan-spec <module>` over `docs/specs/<module>.allium`
  at `a0814ab`, written to `ai_tmp/T15/plan-spec-<module>.txt` (its echo line to
  `ai_tmp/T15/plan-spec-<module>.err`): crawl 382, rovo 166, mirror 200, convert 47
  obligations. The obligations with no test named after them at `0475304` are in
  `ai_tmp/T15/uncovered-<module>.txt` (crawl 137, rovo 98, mirror 72, convert 0); the
  owned set of step 3 is `ai_tmp/T15/owned.json` (60); the `NotInThisSlice` raises at
  `0475304` are in `ai_tmp/T15/notinthisslice-0475304.txt`. The copies are scratch,
  regenerated by step 0.

## Goal

From a clean checkout, against served fixture sites, `rovo sync` keeps a mirror's pages
through their lifecycle: a page that answers 404 or 410 or redirects out of scope is
removed and its file archived under `_removed/<host>/`, mirroring `pages/`; a redirect
within the scope is followed (robots.txt, sitemaps and `llms.txt` included) and a page
whose identity moves is moved with its old URLs as aliases; a canonical that names
another written page merges the page into it; two URLs resolving to one page in one run
settle as one page and a duplicate row; a removed page that answers again is revived in
place; a page a narrowed scope no longer admits is retired at the next finalisation; and
the report lists every removal. Every owned obligation listed under Steps has a test
named after its id; no test this slice adds or edits sleeps for real (the suite's one
real wait is T12's installed-script Crawl-delay scenario, kept by design); `just check`
is green; the Allium loop's
witness record says `PASS`; the checkpoint's adversarial review has run.

## Non-goals

- No `skipped_not_html`: a non-HTML answer still stops the run (Open points, scope note).
- No block verdict, breaker or browser: a soft or hard verdict, a 429 that survives and a
  render's redirects stay `NotInThisSlice` (T18, T19).
- No targeted or owner-testing run (T16, T20); no `rovo verify` (T16); no crash recovery
  (`InterruptRun`, T16).
- No `prune` key: `prune` stays the mirror's built-in `false`, reachable on unit inputs
  only (Open points item 3).
- No harness change: `tests/e2e/conftest.py` is read, not changed (Facts).
- No new `rovo.toml` key, flag or environment variable, except the follow-up's
  `[mirror] prune` (`bad753c`, the answer to Open points item 3); no new dependency; no
  new module, so `scripts/wheel_smoke.py`' `PACKAGE_FILES` does not move.
- No specification change: `docs/specs/` is read, not edited. The six `open question`
  blocks stay open (`crawl.allium` 2410 to 2412, `convert.allium` 473 to 475). A
  specification gap found while planning, implementing, in weed or in review is never
  resolved in code or in the specification: every such gap joins the one batched
  needs-user question (Open points) and the ledger's `open_questions`.
- No change to the public API: `__all__` stays `["__version__"]`, so
  `docs/reference/api.md` does not move. No decision record changes.
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `src/rovo/_crawl/fetch.py` | shared, own lines | `HttpxFetcher` records a 3xx's `Location` header in `SiteResponse.location`; the module docstring |
| `src/rovo/_crawl/model.py` | shared, own lines | `SiteResponse.location`; `RedirectStop` and the redirect docstrings; nothing else unless step 4 shows a field missing; follow-up (`bad753c`): `Run.recheckable_urls` |
| `src/rovo/_crawl/pace.py` | shared, own lines | the redirect follower (Facts); `fetch_resource` following redirects within the allowed hosts, its docstring |
| `src/rovo/_crawl/run.py` | shared, own lines | `attempt_tier` following in-scope redirects; `fetch_robots`, `fetch_sitemap` and `read_llms_txt` lose their 3xx raises; `dispose_fetch`'s `absent`, `redirected_out` and `unfollowed_redirect` branches, its raw-3xx raise removed and its last raise narrowed; `_handle_entry` routing an absent or redirected-out candidate to the mirror and a `CandidateDuplicate` to `settle_duplicate_entry`; `CrawlResult.removed`; the docstrings; follow-up (`bad753c`): `prepare_run` notes a full run's absent, duplicate and done rows in `recheckable_urls` and `enqueue` re-pends a rediscovered one once |
| `src/rovo/_mirror/model.py` | shared, own lines | the mirror's pending file effects and their composition per page path (Facts); `PageRemoved`, `CandidateDuplicate` and the file-effect event types if absent; `RemovalReason` used; follow-up (`bad753c`): `Mirror.prune` (in memory, the resolved `prune`), and an archive cancels a revived page's pending `ArchivedCopyDeleted` by the path the page is held at |
| `src/rovo/_mirror/intake.py` | shared, own lines | `reject_duplicate_candidate`, `move_page`, `revive_removed_page`, `remove_absent_page`, `accept_absent_without_page`, `remove_redirected_out_page`, `accept_redirected_out_without_page`, `retire_page`; `rewrite_known_page`'s merge branch; `settle_candidate`'s complete partition, its fallback raise removed; the module docstring; follow-up (`bad753c`): `retire_page` reads the mirror's `prune`, `revive_removed_page` names the revived path on its `ArchivedCopyDeleted` |
| `src/rovo/_mirror/urls.py` | shared, own lines | added at implement tick 2 (weed T15-1): `assign_path` takes the page `MovePage` moves, whose own path is not held by another page (mirror.allium 729 to 742 at `9a253a4`); follow-up (`bad753c`): each directory segment folds onto the spelling a held path uses |
| `src/rovo/_mirror/finalise.py` | shared, own lines | `retire_out_of_scope_pages`; `finalise` applying the file effects before `PublishPage` and removing emptied directories; `Finalisation.removed`; the docstrings; follow-up (`bad753c`): its spec citation moved |
| `src/rovo/_mirror/state.py` | shared, own lines | only if step 4 shows it: a page record `MovePage` deletes leaves the manifest; `redirect_target` round-trips |
| `src/rovo/_report.py` | shared, own lines | `tally_removal` (`TallyRemoval`) |
| `src/rovo/_commands.py` | shared, own lines | `sync` tallies the run's and the pass's removals; follow-up (`bad753c`): the resolved `prune` set on the mirror |
| `src/rovo/_report.py`, `src/rovo/_mirror/indexes.py`, `src/rovo/_mirror/links.py` | shared, own lines | follow-up (`bad753c`): their spec line citations moved, comments only |
| `src/rovo/_config.py` | shared, own lines | follow-up (`bad753c`): `Configuration.prune`, read from `rovo.toml`'s `[mirror] prune`; `starter_config` writes the `[mirror]` section |
| `tests/fakes.py` | shared, own lines | a `redirect_response(url, location, status=301)` helper beside `html_response` |
| `tests/test_mirror.py` | shared, own lines | the mirror obligations of step 3 and the mirror guarantees |
| `tests/test_crawl.py` | shared, own lines | the crawl obligations of step 3; `test_raw_unchanged_is_defeated_by_a_redirect_hop` re-propagated (a hopped answer now raises `PageFetched`; ledger note, T14) |
| `tests/test_pace.py` | shared, own lines | the follower and `fetch_resource`'s redirects (hop limit, loop, off-host error, bytes, limiter per hop, retry restarting the chain) |
| `tests/test_report.py` | shared, own lines | `TallyRemoval`'s three obligations |
| `tests/test_config.py` | shared, own lines (re-propagated) | follow-up (`bad753c`): `config-default.prune`; `test_entity_fields_Configuration` and the template's keys gain `prune` (ledger note, T09) |
| `tests/test_assign_path_fallback.py`, `tests/test_assign_path_reserved_segments.py`, `tests/test_page_namespace.py` | shared, own lines | follow-up (`bad753c`): their `mirror.allium` line citations moved, comments only; T09's `test_segment_rewrites_happen_before_the_collision_check` re-propagated (`-ROVO` folds onto the held `-rovo`) |
| `tests/test_commands.py` | shared, own lines | two syncs over `FakeFetcher`: a 404 removes and archives, the report's `removed` row; a narrowed scope retires |
| `tests/test_slice_boundaries.py` | shared, own lines (re-propagated) | `test_a_later_slices_answer_stops_the_run` loses its `robots-redirect`, `absent-page` and `page-redirect` cases; `test_a_redirected_sitemap_or_llms_txt_and_a_sitemap_filter_placeholder_stop` keeps only the placeholder case, renamed `test_a_sitemap_filter_placeholder_stops`; `test_mirror_branches_of_later_slices_stop` and `test_a_canonical_merging_a_known_page_into_another_stops` replaced by assertions that the duplicate, the retirement and the merge now settle (renamed, ledger notes naming T10, T13 and T14); a soft verdict and a non-HTML answer asserted still to stop |
| `tests/test_regressions.py` | shared, own lines | `test_a_raw_page_redirect_is_a_later_slices` re-propagated: a 3xx with no `Location` fails with its status text (T12 ledger note); one test per divergence planning, weed or review finds |
| `tests/test_lifecycle_regressions.py` | new | added at review T15-2: one test per valid review finding (T15-2: C1/B1, C2/B2, C3/B3; T15-3: C1/B1), kept out of the hash-pinned `tests/test_regressions.py` so no generated test file changes; hash-pinned at the follow-up (`bad753c`), its citations moved |
| `tests/e2e/test_lifecycle_sync.py` | new | the end-to-end scenarios (Acceptance criteria) and their site-generating helper; no unit test is named `test_lifecycle_sync.py` |
| `docs/reference/cli.md` | shared, own lines | `rovo sync`: removal, archive, redirects, moves, merges, duplicates, revival, a narrowed scope, the report's `removed` rows; a robots.txt redirect that stops disallows its origin; an absent URL with no page is silent; the later-slice sentence loses a redirect, a 404 and a merging canonical; follow-up (`bad753c`): `rovo init`'s starter file gains `[mirror]`, and a full sync rechecks a settled URL its discovery names again |
| `docs/reference/mirror.md` | shared, own lines | a `_removed/` section (the archive mirrors `pages/`, a removed page keeps its record and path, revival, `prune` as `rovo.toml`'s `[mirror] prune` since the follow-up); removed pages, `redirect_target` and aliases in the manifest; when files move (Facts); emptied directories; follow-up (`bad753c`): `mirror.prune` in the `rovo.toml` table, one spelling per directory, a revived-then-retired page keeping its copy |
| `docs/reference/testing.md` | shared, own lines | `tests/e2e/test_lifecycle_sync.py` |
| `docs/project/repository-map.md` | shared, own lines | the tree gains `test_lifecycle_sync.py` |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` Added entry: the page lifecycle; follow-up (`bad753c`): `[mirror] prune`, rediscovered rows rechecked, one spelling per directory |
| `tickets/README.md`, `tickets/T15-lifecycle.md`, `tickets/T14-incremental.md` | ticket | index row, graph, slice bullet, this ticket; follow-up (`bad753c`): T14's follow-up items 1 to 4 marked ANSWERED |
| `.allium-loop/T15-lifecycle.json`, `.allium-loop/T15-lifecycle.witness.json`, `.allium-loop/T14-incremental.json` | gitignored | the loop ledger and the witness record; never committed |

`pyproject.toml`, `uv.lock`, `pytest.ini`, `.coveragerc`, `ruff.toml`, `mypy.ini`,
`Justfile`, `AGENTS.md` (line 10 stays true), `scripts/wheel_smoke.py`,
`src/rovo/__init__.py`, `src/rovo/cli.py`,
`src/rovo/_crawl/sitemaps.py`, `src/rovo/_convert/`, `tests/e2e/conftest.py`,
`tests/test_import_direction.py`, `docs/decisions/` and `docs/specs/` are read, not
changed. A file not in this table that turns out to need a change is added to the table
in the same change with its reason, or handed back if it is a decision record or a
specification.

## Steps

This slice has one **Adversarial review** checkpoint (`tickets/CONVENTIONS.md` §14), in
step 8: after the implementation is witnessed and before the final commit. Its brief
carries the two designs later slices build on (when files move, and the redirect
follower), so they are reviewed once, against the finished slice.

0. `just check` baseline on the untouched worktree at `0475304` plus this ticket, last
   line quoted, and `( set -o pipefail; { time just py-test tests/e2e -ra; } 2>&1 | tail -6 )`
   with its wall time. Scratch output goes in `ai_tmp/T15/`. Write `just plan-spec
   <module>` for each of `crawl`, `rovo`, `mirror` and `convert` to
   `ai_tmp/T15/plan-spec-<module>.txt`. While the worktree is at `0475304`, write
   `rg -n 'NotInThisSlice\(' src > ai_tmp/T15/notinthisslice-0475304.txt` (its raises
   are the Context table's 23 that stay plus the seven this slice removes), and write
   `ai_tmp/T15/owned.json` from the ids listed in step 3, one array per module, then
   confirm each id against the `plan-spec` outputs. Create the ledger
   `.allium-loop/T15-lifecycle.json` against
   `allium-skill-reference/allium/schemas/ledger.schema.json`, shaped like T14's: `goal`
   `"T15-lifecycle"`, `mode` `"spec-first"`, `tick` 0, `specification_base` `a0814ab`,
   `obligation_source` the four files, and `open_questions` holding the six
   specification open questions verbatim, the T15 batched question's items (Open
   points) and the carried items, each marked OPEN. Read
   `.agents/skills/propagate/SKILL.md`, `.agents/skills/weed/SKILL.md`,
   `.agents/skills/witness/SKILL.md` and `.agents/skills/python-change/SKILL.md` before
   step 3.

1. **The mirror rules.** In `intake.py`, the eight rules of the intake partition
   (Facts) and `retire_page`, each returning `None` when its guards do not hold, and
   `rewrite_known_page`'s merge branch; in `finalise.py`, `retire_out_of_scope_pages`
   and the file effects; in `_report.py`, `tally_removal`. Every value comes from the
   candidate, the mirror, the clock or `CONFIG`, never a literal; `prune` is read from
   `CONFIG.prune`.

2. **The crawl rules.** In `fetch.py`, `pace.py` and `run.py`, per the Context table
   and Facts: the follower; `attempt_tier` and `fetch_resource` through it; the three
   discovery raises removed; `dispose_fetch`'s branches in the specification's order;
   `_handle_entry`'s routing and `settle_duplicate_entry`; `CrawlResult.removed`.
   `discovery_max_redirects` is read from `CONFIG`.

3. **Tests first, from the obligations** (the `propagate` skill, spec-first). Write a
   failing test for each owned obligation below into the test file of its module, named
   `test_<obligation id with dots and hyphens as underscores>`, its docstring quoting the
   obligation's description from the plan-spec file. Each `rule_failure` test makes
   exactly one `requires` clause false. Generated tests satisfy EditorConfig
   (indentation in 4-space multiples in `*.py`, string literals included), ruff and
   mypy, since the gate stages them. Run `just py-test` and record the red run in
   `ai_tmp/T15/red.txt`, its summary line under `last_results.propagate` in the ledger.
   Record each generated or re-propagated test file's SHA-256 under
   `generated_test_hashes`, and the reconciliation line (`N obligations, M covered, K
   uncovered`) over the owned set. A test changed after the red run is re-recorded: a
   new hash, `tick` incremented, a ledger note naming the test and why; never silently.
   An obligation a test cannot reach without a later slice's behaviour is not owned:
   move it to the hand-back notes with its reason rather than writing a vacuous test.

   Owned obligations, new in this slice (ids as `just plan-spec <module>` emits them at
   `a0814ab`; 60):

   - **`mirror`** (50), in `tests/test_mirror.py`: `enum-comparable.RemovalReason`,
     `enum-comparable.CandidateOutcome`, `enum-comparable.StoreOutcome`,
     `entity-relationship.Mirror.aliases`, `projection.Mirror.removed_pages`,
     `when-presence.Page.removed_at`, `when-presence.Page.removal_reason`,
     `transition-edge.Page.written.removed`, `transition-edge.Page.removed.written`,
     `transition-rejected.Page.status`, `entity-optional.Page.moved_from`,
     `entity-optional.Page.redirect_target`, `entity-relationship.Page.aliases`,
     `derived.Page.was_moved`, `transition-edge.PageCandidate.pending.duplicate`,
     `entity-optional.PageCandidate.redirect_target`,
     `entity-optional.PageCandidate.content`, `config-default.prune`,
     `rule-success.RejectDuplicateCandidate`, `rule-failure.RejectDuplicateCandidate.1`,
     `rule-failure.RejectDuplicateCandidate.2`, `rule-success.MovePage`,
     `rule-failure.MovePage.1` to `.4`, `rule-success.ReviveRemovedPage`,
     `rule-failure.ReviveRemovedPage.1` to `.4`, `rule-success.RemoveAbsentPage`,
     `rule-failure.RemoveAbsentPage.1`, `.2`, `rule-success.AcceptAbsentWithoutPage`,
     `rule-failure.AcceptAbsentWithoutPage.1`, `.2`,
     `rule-success.RemoveRedirectedOutPage`, `rule-failure.RemoveRedirectedOutPage.1`,
     `.2`, `rule-success.AcceptRedirectedOutWithoutPage`,
     `rule-failure.AcceptRedirectedOutWithoutPage.1`, `.2`, `rule-success.RetirePage`,
     `rule-failure.RetirePage.1`, `rule-success.RetireOutOfScopePages`,
     `rule-failure.RetireOutOfScopePages.1`, `.2`,
     `when-set.RetirePage.Page.removed_at`, `when-set.RetirePage.Page.removal_reason`.
   - **`crawl`** (7), in `tests/test_crawl.py`:
     `transition-edge.FrontierEntry.in_progress.duplicate`,
     `transition-edge.FrontierEntry.in_progress.absent`,
     `transition-edge.FrontierEntry.absent.pending` (a removed page's absent row
     re-pended by `PrepareRun`), `rule-success.SettleDuplicateEntry`,
     `rule-failure.SettleDuplicateEntry.1`, `config-default.discovery_max_redirects`,
     `enum-comparable.RedirectStop`.
   - **`rovo`** (3), in `tests/test_report.py`: `rule-success.TallyRemoval`,
     `rule-failure.TallyRemoval.1`, `rule-failure.TallyRemoval.2`.
   - **`convert`**: none.

   Extended, not new (re-propagated in place, each re-hashed in this slice's ledger with
   a note naming its origin slice; T09's to T14's ledgers are never edited): the
   `tests/test_slice_boundaries.py`, `tests/test_regressions.py` and
   `tests/test_crawl.py` tests the Files touched table names, renamed where it says, the
   old name in the ledger note; `test_rule_success_DisposeFetch` and every other earlier
   test the red run shows red because a lifecycle answer no longer stops the run, each
   with only that expectation moved. Claim an earlier test "passes unedited" only where
   it does; the hand-back notes list every earlier test this slice edited.

   Guarantees and black boxes (no obligation id; hand-written), in `tests/test_mirror.py`
   unless named: `RemovedAreaKeepsPath` (archive at `_removed/<host>/<relative path>`,
   the record and path kept, revival in place); `EveryCandidateIsSettled` (of the
   twelve partition cases, ten answer exactly one of `PageStored`, `CandidateDuplicate`,
   `CandidateDiscarded`, `PageRemoved`; the two `Accept…WithoutPage` cases accept the
   candidate and answer none, Open points item 8; no case answers two); a removed page
   never reported removed twice;
   the file effects applied by `finalise` and idempotent, emptied directories removed;
   a written page whose file was archived with the manifest not saved republished by
   the next `finalise` (no general fault-injection harness); a removed page A revived
   through page B's canonical and then answering 404 in the same run, after which
   `_removed/<host>/<A path>` still holds A's earlier bytes and `pages/` has no A file
   (`RemovedAreaKeepsPath`, the effect composition of Facts); the same two duplicate
   candidates with identical content settled in both orders giving the same page, path,
   aliases and frontier statuses, up to which row is `duplicate` (Open points item 9;
   no e2e reordering harness);
   a merge leaving the merged URL an alias of the survivor; a move's stale alias of the
   new identity dropped; `RedirectsFollowedOnlyInScope` (`tests/test_pace.py`: in-scope
   hops followed, out-of-scope, looping and over-limit ones stopped, never a request
   past a stop, validators on the first request only, each hop's bytes counted, the
   destination's limiter per hop, a robots-disallowed hop not requested, and a
   robots.txt redirect that stops or lacks a `Location` disallowing its origin with a
   `robots_unreachable` discovery problem, a robots.txt redirected within its origin
   followed with no second robots.txt request (the fake fetcher's request log), and a
   robots.txt of origin A redirected to B's robots.txt and back to A's requested at most
   once per URL, with no nested robots fetch, disallowing A with `robots_unreachable`);
   `DisposeFetch`'s three new branches and their row statuses (`tests/test_crawl.py`).

   Not owned, and why, for the hand-back notes:
   `transition-edge.FrontierEntry.duplicate.pending` (reached only by a targeted or
   owner-testing run: T16, T20); `transition-edge.FrontierEntry.in_progress.pending`
   and `rule-*.InterruptRun` (T16); `transition-edge.FrontierEntry.in_progress.skipped_not_html`
   and `.skipped_not_html.pending` (Open points, scope note); `rule-*.FailDiscardedEntry`
   (T16's failed URLs; covered by `tests/test_unplaceable_candidate.py`);
   `rule-*.VerifyPages` and the verification types (T16); `rule-*.SaveOwnership` and
   `derived.Mirror.has_declared_owner` (T20); `enum-comparable.Tier` (T19); every other
   uncovered obligation in the four files, each belonging to the slice its rule names.

4. **Mirror, crawl, report and command.** Steps 1 and 2, then `_commands.sync`'s
   removal tally. Unit cases on `FakeFetcher` and `ScriptedFetcher` with `FixedClock`.
   `just py-test tests/test_mirror.py tests/test_crawl.py tests/test_pace.py
   tests/test_report.py tests/test_commands.py tests/test_slice_boundaries.py
   tests/test_regressions.py`, then `just py-lint`, `just py-typecheck`,
   `just coverage` and `just wheel-smoke`, quoting its `api` line.

5. **End to end.** No new static fixture site: every site is generated into `tmp_path`
   by `tests/e2e/test_lifecycle_sync.py`' helper, served first and written after, as
   `tests/e2e/test_second_sync.py` does; the helper is the module's own. Each page has a
   `<title>` and a `<main>` holding an `h1` and a paragraph of prose, two-space
   indentation and a final newline; `robots.txt` is `User-agent: *` with no Crawl-delay
   and no `Sitemap:` line; there is no `llms.txt`. The scenarios are the Acceptance
   criteria's; they run `rovo._commands.sync` in process over a real `HttpxFetcher` with
   a `FixedClock`, which never sleeps, and read requests off the server's log.
   `just py-test tests/e2e -ra`, its wall time quoted beside step 0's.

6. **Documents** (the `review-docs` skill). The pages of the Files touched table; find
   the sentences this slice makes false with
   `rg -n -i "redirect|404|410|removed|_removed|archive|prune|moved|merge|duplicate|revive|later slice" -g '*.md' -g '!tickets/**' -g '!allium-skill-reference/**' -g '!docs/specs/**' -g '!docs/decisions/**'`;
   `CHANGELOG.md` `Unreleased` gains one Added entry. Keep the required phrases of
   `AGENTS.md` in always-visible text. `just check-docs`, `just check-agents`, and
   `just lint`, whose hooks include markdownlint over this ticket.

7. **Witness** (the `weed` and `witness` skills). Run `weed` over `mirror`, `crawl` and
   `rovo` against the code, scoped to the owned and extended obligations, the Realised
   rules of the Context table and the guarantees; record its verdict under
   `last_results.weed` and fix any code divergence, each with a regression test in
   `tests/test_regressions.py`. A divergence weed attributes to the specification is not
   fixed: it joins the one batched needs-user question. Then run `witness`
   non-interactively: it writes `.allium-loop/T15-lifecycle.witness.json` per
   `witness-result.schema.json`. The verdict must be `PASS`; a `FAIL` routes back per the
   skill, and the hand-back notes record each round. A batched question still OPEN does
   not block `PASS` unless it blocks an owned obligation; the witness escalates one that
   does.

8. `just check`, its last line quoted.

   **Adversarial review** (`tickets/CONVENTIONS.md` §14; checkpoint 1, after the
   implementation is witnessed and before the final commit; it also covers two designs
   later slices build on). Both lenses, conformance and breakage, run with
   `codex exec -m gpt-6-astra -s read-only -C <worktree> -o <file> "<brief>"`; the
   reviewer driver runs codex in the foreground and waits until the findings file
   exists before triage starts, never backgrounding it. Brief: this ticket,
   `tickets/CONVENTIONS.md`, `git diff 0475304` plus the uncommitted changes, the ledger
   and the witness record (not the hand-back notes), and the questions: can a file
   effect run before the manifest that records it is saved, or leave a page file both
   under `pages/` and `_removed/`, or delete a file the manifest still points at; does
   any request, redirect hop included, bypass the limiter, robots or the scope, or
   follow a hop past a stop; is any value a literal rather than `CONFIG`; is the
   intake partition total and exclusive, and is a removed page ever reported removed
   twice; is any `NotInThisSlice` removed whose branch is not realised, or any branch
   realised that the Context table keeps outside; is every acceptance criterion shown
   by a test that would fail if the claim were false; does any re-propagated earlier
   test assert less than before; does a verification command print a pass when it
   failed; does `just check` need the network or sleep for real; is every gap in the
   batched question rather than resolved. Files
   `ai_tmp/review/T15-1/findings-conformance.md`,
   `ai_tmp/review/T15-1/findings-breakage.md` and `ai_tmp/review/T15-1/verdicts.md`;
   triage by subagents that are neither the reviewers nor the executing agent; valid
   fixes applied one at a time, within the Files touched table; a second round over the
   fix diff when a high-severity finding was valid, two rounds at most, anything still
   open going into Open points; then the witness rerun if a fix touched code or tests,
   and `just check` rerun and quoted. The model call is the checkpoint's authorised
   network use.

9. Hand-back notes, with the review's record; `status: done`; `just check` ending with `All checks passed and the worktree is unchanged.`,
   `git status --short` empty after the commit. Commit on the branch.
   **Authorisation required**: pushing and opening the pull request.

## Acceptance criteria

The end-to-end scenarios live in `tests/e2e/test_lifecycle_sync.py`; each starts with
`rovo init <base>guide/start.html <tmp>/out`, `<host>` below is the host segment of
`<base>`, and every sync exits 0 unless stated.

- **End to end, removal, archive and revival**
  (`test_an_absent_page_is_archived_and_revived_in_place`): `guide/start.html` links
  `guide/gone.html`. The first sync writes both. `guide/gone.html` is deleted; the
  second sync's request for it is answered 404; its manifest record is `removed` with
  `removal_reason: absent` and its `path` unchanged; `pages/<host>/guide/gone.md` no
  longer exists and `_removed/<host>/guide/gone.md` holds the bytes it had; its
  frontier row is `absent`; `links.jsonl` lists its URL as `dangling` and `start`'s
  frontmatter flags carry `dangling_inbound`; `index.jsonl` no longer lists it;
  `crawl-report.json` `changes` has one row `{"kind": "removed", "url": <its URL>,
  "path": "pages/<host>/guide/gone.md", "moved_from": null}`. A third sync with no
  change requests it again and lists no second `removed` row. The file is restored,
  its mtime a minute later; a fourth sync, at `FixedClock(START + timedelta(days=1))`,
  revives it: the record is `written` at the
  same path, `_removed/` no longer exists, the report lists it `added`, and its
  `first_seen` is the fourth sync's clock.
- **End to end, a move with aliases** (`test_a_redirected_page_moves_with_an_alias`):
  `guide/start.html` links `guide/old.html`; `guide/new.html` exists; the server
  scripts `guide/old.html` as one 200 then `always` a 301 to `/guide/new.html`
  (Facts). The first sync writes `old`. The second sync requests `/guide/old.html`
  then `/guide/new.html`, in that order, once each; the page's record has the identity
  `<base>guide/new.html` and the path `pages/<host>/guide/new.md`, the old file is
  gone, the manifest holds the alias `<base>guide/old.html` to it, the report lists it
  `moved` with `moved_from: "pages/<host>/guide/old.md"` and no `added` row, and
  `start`'s link to `guide/old.html` is rewritten to `new.md`.
- **End to end, a redirect out of scope and a duplicate**
  (`test_a_page_redirected_out_is_removed_and_a_second_url_is_a_duplicate`): the seed
  links `guide/alpha.html`, `guide/beta.html` and `guide/away.html`; `beta` always
  answers 301 to `/guide/alpha.html`; `away` is scripted as one 200, then always a 301
  to `http://elsewhere.invalid/away.html`. The first sync writes `start`, `alpha` and
  `away`, one page file for `alpha` and `beta` whichever is fetched first: one of the
  two rows is `duplicate` and the other `done`, the manifest holds the page
  `<base>guide/alpha.html` and the alias `<base>guide/beta.html` to it, and `start`'s
  link to `beta` is rewritten to `alpha.md`. The second sync removes `away` with
  `removal_reason: redirected_out` and `redirect_target:
  "http://elsewhere.invalid/away.html"`, archives its file and settles its row `done`;
  the `.invalid` name never resolves, so a followed hop would have failed the row
  instead of removing the page.
- **End to end, a narrowed scope**
  (`test_a_narrowed_scope_retires_pages_it_no_longer_admits`): the seed links
  `guide/keep/a.html` and `guide/drop/b.html`. The first sync writes three pages.
  `rovo.toml`'s `path_prefixes` becomes `["/guide/keep/"]`; the second sync never
  requests `/guide/drop/b.html`, retires `b` at finalisation with `removal_reason:
  out_of_scope`, archives it at `_removed/<host>/guide/drop/b.md`, removes the emptied
  `pages/<host>/guide/drop/`, and lists one `removed` row; the seed stays written.
- **End to end, discovery redirects** (`test_discovery_follows_redirects_within_the_allowed_hosts`):
  `robots.txt` is served as a 301 to `/robots-real.txt`, which disallows
  `/guide/private/`, and `/sitemap.xml` as a 301 to `/maps/site.xml`, which names
  `guide/orphan.html`. The sync follows both, never requests `/guide/private/x.html`
  (linked from the seed), writes `orphan`, and reports no discovery problem.
- **End to end, earlier scenarios**: `tests/e2e/test_init_sync.py`,
  `tests/e2e/test_follow_links.py`, `tests/e2e/test_index_files.py`,
  `tests/e2e/test_polite_sync.py`, `tests/e2e/test_discovery_sync.py`,
  `tests/e2e/test_second_sync.py` and `tests/e2e/test_harness.py` pass unedited, unless
  the ledger names an edit and why.
- Every owned obligation in step 3 has a test named after it, red before the code and
  green after (`ai_tmp/T15/red.txt` and the final run); the reconciliation line shows
  zero uncovered; every extended test is re-hashed in the ledger with its note; every
  obligation dropped from the owned list is in the hand-back notes with its reason.
- No test this slice adds or edits sleeps for real; the suite's one real wait is T12's
  installed-script Crawl-delay scenario (`tests/e2e/test_polite_sync.py`), kept by
  design: `rg -n 'time\.sleep\(' tests; test $? -eq 1`,
  `test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py`, and
  `rg -n 'subprocess|rovo\(' tests/e2e/test_lifecycle_sync.py; test $? -eq 1` (the new
  module runs `rovo._commands.sync` in process).
- The `NotInThisSlice` raises in `src/` are those of
  `ai_tmp/T15/notinthisslice-0475304.txt` minus the seven the Context table names
  (`rg -n 'NotInThisSlice\(' src` compared with that file, the difference quoted), and
  `rg -n 'rule="(FetchRobots|FetchSitemap|ReadLlmsTxt|RetireOutOfScopePages|RewriteKnownPage|PageCandidate.created)"' src; test $? -eq 1`.
- `discovery_max_redirects` and `prune` appear in `src/` only as `CONFIG` fields and
  their reads (`rg -n 'discovery_max_redirects|prune' src`, quoted).
- `.allium-loop/T15-lifecycle.witness.json` exists with `"verdict": "PASS"`, and the
  ledger validates against `ledger.schema.json` with the T15 batched question's items
  and the carried items OPEN unless the maintainer answered them.
- `ai_tmp/review/T15-1/findings-conformance.md`, `findings-breakage.md` and
  `verdicts.md` exist, and the hand-back notes record every finding's verdict.
- `just check-specs` and `just analyse-specs` pass with `docs/specs/` unchanged since
  `a0814ab` (`git diff --stat a0814ab -- docs/specs` empty).
- `import rovo` loads no module outside the standard library and `rovo`; `__all__` is
  `["__version__"]`; `just wheel-smoke` passes with the package-file count unchanged.
- `just coverage` stays at or above the floor of 95.
- `just check-docs` and `just check-agents` pass; `docs/reference/cli.md` describes the
  lifecycle a sync applies, and `docs/reference/mirror.md` describes `_removed/`.
- `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty after the commit.

## Verification

```sh
just plan-spec crawl > ai_tmp/T15/plan-spec-crawl.txt
just plan-spec rovo > ai_tmp/T15/plan-spec-rovo.txt
just plan-spec mirror > ai_tmp/T15/plan-spec-mirror.txt
just plan-spec convert > ai_tmp/T15/plan-spec-convert.txt
git diff --stat a0814ab -- docs/specs
just py-test tests/test_mirror.py tests/test_crawl.py tests/test_pace.py tests/test_report.py tests/test_commands.py tests/test_slice_boundaries.py tests/test_regressions.py -ra
( set -o pipefail; { time just py-test tests/e2e -ra; } 2>&1 | tail -6 )
just py-lint
just py-typecheck
just coverage
just wheel-smoke
uv run --frozen python -I -c "import rovo, sys; print(sorted(m for m in sys.modules if not m.startswith(('rovo', '_')) and m not in sys.stdlib_module_names))"
rg -n 'NotInThisSlice\(' src  # compared with ai_tmp/T15/notinthisslice-0475304.txt
rg -n 'rule="(FetchRobots|FetchSitemap|ReadLlmsTxt|RetireOutOfScopePages|RewriteKnownPage|PageCandidate.created)"' src; test $? -eq 1  # only "no match" passes
rg -n 'discovery_max_redirects|prune' src
rg -n 'time\.sleep\(' tests; test $? -eq 1  # only "no match" passes
test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py
rg -n 'subprocess|rovo\(' tests/e2e/test_lifecycle_sync.py; test $? -eq 1  # only "no match" passes
test -s ai_tmp/review/T15-1/findings-conformance.md && test -s ai_tmp/review/T15-1/findings-breakage.md
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
after; the intake partition, the follower and the file effects as built, and any
departure from Facts and steps 1 and 2; the red run and the reconciliation line; every
extended or re-propagated test, its origin slice and its new hash; every obligation
dropped from the owned list and why; the weed verdict and the witness verdict, each
round; the adversarial review per `tickets/CONVENTIONS.md` §14 (harness and model,
findings, verdicts with one-line reasons, what was applied, what was handed back, the
rerun output headed by its commit); the one batched needs-user question with every gap
found while planning, implementing, in weed or in review, and the maintainer's answer if
one arrived; the verification output, each headed by its commit.

## Open points

- **The T15 batched needs-user question: ANSWERED** (items 1 to 11, the addenda and
  the carried T14 items a to d, specification `bad753c`). One question to the
  maintainer, its items numbered so an answer can cite them; items 1 to 7 were found
  while planning T15, items 8 and 9 in the checkpoint review (round 1), items 10 and 11
  by the weed passes. Item 4 is answered "recheck when rediscovered", item 3 "a
  `rovo.toml` key", item 11 "reuse the existing spelling"; every other interim is
  accepted as built and stated as decided in the specification. The text of each item
  is the question as asked, with line numbers at `a0814ab`.
  1. **ANSWERED, accepted as built** (`RetirePage`'s guidance at `bad753c`), and the
     unresolved case decided: a page revived at a new path (its old one no longer
     free) and retired again in the same run keeps its existing `_removed/` copy, its
     last published bytes; the pending `ArchivedCopyDeleted` is cancelled and the
     never-published new path is not archived. A page moved, then retired in one run,
     archives from its last published path to `_removed/<host>/<new path>` (deleted
     under `prune`), as built. **When a lifecycle rule's file effect happens on
     disk.** `RetirePage` (984),
     `MovePage` (619) and `ReviveRemovedPage` (728) raise `PageFileArchived`,
     `PageFileDeleted`, `PageFileMoved` and `ArchivedCopyDeleted` at intake, while the
     manifest is saved only after finalisation and `RefreshPage`'s guidance (817) keeps
     page files for finalisation. Interim: the mirror records each effect as its rule
     fires and the finalise pass applies them, in order and idempotently, before
     `PublishPage` (Facts). A crash inside the pass, after an effect and before
     `save_mirror`, can leave files ahead of the manifest: the next finalisation's
     `PublishPage` rewrites a written page whose file is missing, and a stale archived
     copy stays beside it until the page is retired again (crash recovery is T16's).
     Replayed in order, the spec's events lose a file when a removed page is revived
     (say through another page's canonical) and retired again in the same run: the
     archived copy is deleted, then an archive of a never-published `pages/` file is a
     no-op. Interim: pending effects compose per page path (Facts), so
     `PageFileArchived(path)` cancels a pending `ArchivedCopyDeleted(path)` and records
     no archive. Not resolved: a revival that gave the page a different path because
     its old one was no longer free, then a retirement in the same run. A page moved
     (once or more) and then retired in the same run would, replayed literally, lose its
     last published bytes; interim: the archive is taken from the path the page was
     last published at and lands at `_removed/<host>/<new path>` (under `prune`, that
     file is deleted), so the page is never lost (review T15-2 and T15-3).
  2. **ANSWERED, accepted as built: removed, the namespace root included**
     (`RetirePage`'s guidance at `bad753c`). **Emptied directories under `pages/` and
     `_removed/`.** An archive, a move or a
     deletion can leave a directory empty; the specification does not say whether it
     stays. Interim: removed, the namespace root included, as `_indexes/` already is
     (`docs/reference/mirror.md`, the indexes section).
  3. **ANSWERED: a `rovo.toml` key.** `prune` is `rovo.allium`'s `Configuration.prune`
     (default `mirror/config.prune`, false), in a new `[mirror]` section
     (`mirror.prune`), wired to the mirror's `prune`; `init`'s starter file writes the
     section. Only the layers `resolve_config` already has read it; the environment and
     flag layers arrive in T16 like every other key. **`prune` reaches no
     configuration layer.** `mirror.allium` config (498) declares
     `prune` (default false), but `rovo.allium`'s `Configuration` (69) names no `prune`
     key, and unlike `max_path_chars` the specification does not say it is not a key.
     Interim: `CONFIG.prune` false, no `rovo.toml` key; the delete branch is tested on
     unit inputs only.
  4. **ANSWERED: recheck when rediscovered.** A full sync's `PrepareRun` notes its
     `absent`, `duplicate` and `done` rows in `Run.recheckable_urls`; `Enqueue`
     re-pends one of them, once per run, when the run's discovery (a page link, a
     sitemap entry or `llms.txt`) names it again and no page has that identity; a row
     nothing names stays settled. A rediscovered alias that now serves its own page
     moves the page it aliased (`MovePage`'s guidance). **Rows a full sync never
     re-pends.** `PrepareRun` (645) re-pends written pages,
     removed pages and `retry_entries`, and `Enqueue` never changes an existing row's
     status in a standard run, so an `absent` row with no page
     (`AcceptAbsentWithoutPage`), a `duplicate` row (its URL now an alias) and the
     requested identity of a moved page (`done`) are never fetched again by a full
     sync: a URL that answered 404 and later appears, or an alias whose redirect is
     later removed, is never rechecked. Interim: as written.
  5. **ANSWERED, accepted as built**, the addendum included: a disallowed page hop is
     retried under `HttpRetry` like any other error answer (`FetchRobots`' and
     `AttemptTier`'s guidance at `bad753c`). **A redirect hop robots.txt disallows.** `RedirectStop` (202) has `out_of_scope`,
     `loop` and `hop_limit` only, while `Politeness` (2258) respects robots.txt in every
     standard run and `rovo.allium`'s fetch guidance (862) says every redirect respects
     robots. Interim: before a hop the destination origin's robots.txt is read when the
     run has not (as `ReadRobotsForNewOrigin`, 1468, through the destination host,
     opened as `OpenHostForEntry`, 1451, does); a hop it disallows is not requested and
     the fetch ends as an error, `"redirect disallowed by robots.txt"`, which fails the
     entry (a page) or comes back as an error (`fetch_resource`). The read and check
     apply to a page's hops and to a sitemap's and `llms.txt`'s `fetch_resource` hops,
     never to `FetchRobots`' own fetch (RFC 9309: robots.txt is not governed by
     robots.txt), whose hops are bounded only by the allowed hosts, the hop limit and
     the no-revisit test; so a robots.txt redirect never requests robots.txt again.
     Also open: a disallowed page hop is an error answer, so `HttpRetry` retries the
     original URL up to `http_attempts` times and each try counts toward the breaker.
     Interim: as built.
  6. **ANSWERED, accepted as built** (`AttemptTier`, `FetchRobots` and `DisposeFetch`
     at `bad753c`). **Validators across hops, and a 3xx with no `Location`.** `fetch_or_render` is
     called with `conditional` for the requested identity (`AttemptTier`, 1535); nothing
     says whether a hop carries the requested page's validators, nor what a 3xx without
     a usable `Location` is. Interim: validators on the first request only; a 3xx with
     no usable `Location` is not followed and is not an unfollowed redirect, so a page's
     reaches `DisposeFetch`'s not-ok branch and fails with its status text, and
     `fetch_resource` returns it as an error answer, as it does a stopped redirect
     (Facts: robots.txt then disallows its origin).
  7. **ANSWERED, accepted as built** (`AttemptTier`'s guidance at `bad753c`). **Which
     scope test a page's redirect hop meets.** The `AttemptTier` guidance
     (1564) follows "in-scope redirects" without naming the predicate. Interim:
     `within_bounds` of the hop's target (the test `PrepareRun` and
     `RetireOutOfScopePages` use; a redirect is not a link and carries no depth), a
     revisit compared by identity.
  8. **ANSWERED, accepted as built**: `EveryCandidateIsSettled` now says at most one
     event follows, none for the two `Accept...WithoutPage` rules (`bad753c`).
     **Candidates settled with no event.** `EveryCandidateIsSettled` (1546) says
     exactly one of `PageStored`, `CandidateDuplicate`, `CandidateDiscarded` or
     `PageRemoved` follows every candidate, but `AcceptAbsentWithoutPage` (948) and
     `AcceptRedirectedOutWithoutPage` (967) only accept the candidate. Interim: the
     rules as written; the two answer no event (their frontier row is already settled
     by `DisposeFetch`).
  9. **ANSWERED, accepted as built**: the content fetched first stands, so the mirror
     is deterministic for a given frontier order (`RejectDuplicateCandidate`'s guidance
     at `bad753c`). **Duplicates with differing content.** `RejectDuplicateCandidate`'s guidance
     (584 to 589) says the first store's content stands and that the order in which the
     two URLs were fetched never changes the mirror; for two URLs with one canonical and
     different content both cannot hold. Interim: the rule as written, the first
     store's content stands (frontier order is deterministic, so a given site still
     mirrors byte-stably).
  10. **ANSWERED, confirmed: the requested URL** (`ExpandSitemapEntries` and
     `ReadLlmsTxt` at `bad753c`). **Base URL of a redirected `llms.txt` or sitemap.** `crawl.allium` (1181, 1229)
     resolves relative targets against the requested URL; RFC 3986 would use the URL
     that answered. Interim: the requested URL, as the specification states (pinned by
     `tests/test_regressions.py::test_a_redirected_llms_txt_resolves_its_targets_against_llms_txt_url`).
  11. **ANSWERED: reuse the existing spelling.** `assign_path` folds each directory
     segment, ignoring case, onto the spelling a held page path already uses for that
     directory (the page's own included); where held paths use several spellings, the
     held path first by code point gives it; existing pages are not moved; the last
     segment keeps its own spelling (`MovePage`'s guidance at `bad753c`). **Directory
     segments that differ only in case.** `UniquePagePathIgnoringCase`
     (`mirror.allium` 1362 to 1366) compares whole page paths, so `pages/<host>/sub/a.md`
     and `pages/<host>/Sub/b.md` may coexist, and a page may move from `sub/x.md` to
     `Sub/x.md`; on a case-insensitive file system both land in one directory, which
     keeps its first spelling, so the manifest and links can name a spelling the tree
     lacks once the mirror is copied to a case-sensitive one. Interim: as built (the
     leaf file takes its new spelling; a directory keeps the spelling it was created
     with).
- **Carried, ANSWERED at `bad753c`, accepted as built** (from
  `tickets/T14-incremental.md` and `.allium-loop/T14-incremental.json`, the T14
  follow-up batched question, joined to T15's, and marked there): (a) `sitemap_lastmod` is still in the page frontmatter, so a moved sitemap
  lastmod rewrites a byte-identical page; (b) navigation links are not stored with a
  page, so an unchanged page re-follows only its content links; (c) after a crash
  before finalisation a page's stored links are empty until the next finalised sync;
  (d) stored link targets were normalised under the last finalisation's scope. Each
  is now decided as T14 built it. Still carried, OPEN, to T17: `mslearn`'s `sitemap_include`
  placeholders, and a non-heading id anchor stopping the sync
  (`UncarryableBecomesIsland`). Carried to T18: a retired host's remaining discovery is
  still requested.
- **The T15 follow-up batched needs-user question: ANSWERED** (spec `9a253a4`, carried as
  item 1 of the T16 batched question, `tickets/T16-errors-report.md`). Found while
  propagating the answers at `bad753c`; the question as asked is kept below. The
  maintainer's answer: the record returns to its old path, the path its kept copy is at
  (`Page.revived_from`, set by `ReviveRemovedPage` and cleared by `PublishPage`), so
  nothing moves on disk and record and copy agree; when another page has taken that old
  path in the same run, the record keeps its new path and the kept copy moves to it
  (`ArchivedCopyMoved`, cancelling the pending `ArchivedCopyDeleted`). The T16 follow-up
  realises it.
  1. **Which path a removed record holds when its kept copy is at its old path.**
     `RetirePage`'s guidance (`mirror.allium` 1030 to 1047) keeps the existing
     `_removed/` copy of a page revived at a new path and retired again in the same
     run, but `ReviveRemovedPage` (748) set the record's `path` to the new path and
     `RetirePage` leaves it there. `RemovedAreaKeepsPath` (1546) says a removed page's
     copy is at `_removed/<host>/<its path>` and that the page keeps its path, so the
     record names a path its copy is not at; a later revival raises
     `ArchivedCopyDeleted` for the record's (new) path and the copy at the old path
     stays in `_removed/` for ever. Should the record return to its old path, should
     the copy move to the new one, or is the stale copy accepted? Interim: as the rules
     are written (the record keeps the new path, the copy stays at the old one); the
     tests assert the files only. ANSWERED, as above.
- **Scope note, not a specification gap.** `DisposeFetch`'s `skipped_not_html` branch
  and the edges `in_progress -> skipped_not_html` and `skipped_not_html -> pending` are
  claimed by no slice in the T15 to T20 list; this slice keeps their stop. The
  orchestrator assigns them (T16 is the nearest, with failed and skipped URLs).
- **The specification's open questions.** The three `crawl.allium` ones (2410 to 2412)
  and the three `convert.allium` ones (473 to 475) stay open; none is on this slice's
  path except the second (a URL that fails on every sync is retried for ever), which a
  redirect loop or an unknown URL redirected out now reaches: its interim holds and
  nothing here changes it.
- **`NotInThisSlice`.** A development guard, not product behaviour: each later slice
  removes the raises it implements, and the last slice's review confirms none is left.
  This slice removes seven and narrows `DisposeFetch`'s last (Acceptance criteria).
