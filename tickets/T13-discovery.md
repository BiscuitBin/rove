---
id: T13
title: "Discovery: rovo sync reads sitemaps and llms.txt, records what they name, keeps the sitemap budgets, and --dry-run lists what it would fetch"
status: open
depends_on: [T12]
parallel_with: []
branch: full-final-prototype
estimated_size: L
---

# T13: Discovery: rovo sync reads sitemaps and llms.txt, records what they name, keeps the sitemap budgets, and --dry-run lists what it would fetch

## Context

T09 (`fd1b423`), T10 (`9fd11fd`), T11 (`d2979c8`, `2658231`) and T12 (`7a9c135`) are
slices 1 to 4. `rovo sync` reads each origin's robots.txt, paces and retries per host
name, fetches the seed pages and the pages they link to within the crawl scope,
publishes each at `pages/<host>/<path>`, rewrites links between page files, writes the
indexes and `crawl-report.json`, and exits 1 on a failed page or a refused or
unreachable robots.txt. They fixed every pattern this slice follows: the private
subpackages `rovo._convert`, `rovo._mirror` and `rovo._crawl` with `rovo._config`,
`rovo._report` and `rovo._commands` above them (import direction enforced by
`tests/test_import_direction.py`), the `Fetcher` seam and the `Timer` seam of
`src/rovo/_crawl/pace.py` (`FixedClock`, `SteppingTimer`, `ScriptedFetcher` and
`StampingFetcher` in `tests/fakes.py`), `pace.fetch_resource` (the http tier under the
host's limiter, with a page's retries, no redirect followed), obligation-named tests
(`test_<obligation id>`), the end-to-end harness `serve_site` in `tests/e2e/conftest.py`
with scripted answers (`Answer`, `DROP`, `always=`) and its request log, the state files
of `docs/reference/mirror.md`, and the development guard `rovo._unfinished.NotInThisSlice`.
Read `tickets/T12-robots-politeness.md` (its Context table, Facts and Open points),
`src/rovo/_crawl/run.py`, `src/rovo/_crawl/pace.py` and `tests/e2e/test_polite_sync.py`
before starting.

This is slice 5 of T08 to T20, run in this worktree on `full-final-prototype`. Until now
discovery stops at the seeds: `discover` (`run.py` 232) enqueues each seed and opens
every allowed host, and nothing else; `RobotsPolicy.declared_sitemaps` is recorded and
never read; `drop_stale_observations` (`run.py` 633) does nothing; `frontier.json`
writes `observed_urls` as `[]` and `load_frontier` never reads it back; a dry run stops
at `NotInThisSlice("DryRun")` (`run.py` 1133) and `close_run` at
`NotInThisSlice("CloseRun")` (`_report.py` 317). The specification base is `fa096c4`
(`git diff --stat fa096c4 HEAD -- docs/specs` is empty); every line number below is at
`fa096c4` unless it says `at ecfa257`. The follow-up after the maintainer's answers (Open
points) moves the base to `ecfa257`.

The page and byte budgets are already realised and covered: `select_batch`,
`Run.page_budget_remaining`, `Run.byte_budget_left`, `_choose_batch`, the
`skipped_limit` stop and the partial exit over `run.budget_stopped` (T09, with
`test_rule_success_SelectBatch` and `test_transition_edge_FrontierEntry_pending_skipped_limit`);
the depth limit is `CrawlScope.allows` (T10). What this slice adds to the budgets is the
discovery side: the per-host sitemap caps of `ExpandSitemapEntries` (at most
`sitemap_max_children` child sitemaps, at most `max_pages * sitemap_cap_multiplier`
entries admitted), the discovery depths `sitemap_depth` and `llms_txt_depth`, and the
first end-to-end proof that a page budget stops a run whose frontier discovery filled.

### The specified path, and what this slice does with each rule on it

| Class | Rules |
| --- | --- |
| **Realised** (every branch reachable in this slice, or constructible on unit inputs where noted) | `crawl.allium`: `Discover` (711), its standard branch now raising `SitemapsRequested` and `LlmsTxtRequested` for every allowed host after `HostOpened`, hosts in sorted order; `QueueSitemaps` (908: each declared sitemap of the host's first origin, `host.origin`, then each of `well_known_sitemaps(name)` not declared, `/sitemap.xml` and `/sitemap_index.xml` at `host.origin`); `ReadRobotsBeforeSitemap` (929, handed over by T12: a sitemap at another origin of its host waits for that origin's robots.txt, read through T12's `fetch_robots`, then is due again); `FetchSitemap` (942: each sitemap read at most once per run, through `fetch_resource`; a sitemap on another host, one `sitemap_admitted` refuses or one robots disallows produces nothing and no problem; no validators sent, Facts); `AcceptFreshSitemap` (1017, the snapshot created or updated in the run's frontier); `RejectNonSitemap` (1036); `SkipUnavailableSitemap` (1044); `ExpandSitemapEntries` (1057: an index's children queued only on the host that served it, the open question's interim, at most `sitemap_max_children` per host; a urlset's entries observed whatever their scope and admitted at `sitemap_depth` with `sitemap_priority`, `from` the sitemap's URL and the entry's `lastmod`, at most `max_pages * sitemap_cap_multiplier` per host); `ReadLlmsTxt` (1082: never conditional, silent when absent or unreachable, each target observed and admitted at `llms_txt_depth` with `llms_txt_priority`, `from` `llms_txt_url(name)`); `RecordObservation` (1102); `DropStaleObservations` (1142), now with an effect, over the observations `load_frontier` reads back; `DryRun` (1153) and `BeginCrawl` (1166) on both sides of `run.dry_run`; `Enqueue` (1118) now meeting `via: sitemap` and `via: llms_txt` with `from` and `lastmod`; `PrepareRun` (636) re-pending a `skipped_limit` row (`retry_entries`). `rovo.allium`: `CloseRun` (623), its dry-run branch (`ReportReady` without the finalise pass) and `discovered_count` as the frontier's rows after discovery (Facts); `TallyDiscoveryProblem` (561), now also reached by `sitemap_unavailable`, `sitemap_unreachable` and `not_a_sitemap`; `RankAndWriteReport` (665) over a dry run; the `ProgressOnRequest` guarantee's last sentence (934 to 939: a dry run prints its frontier as plain text). `mirror.allium`: a page's and a candidate's `sitemap_lastmod`, carried from the frontier row (`ConvertFetched`, `crawl.allium` 1787) into the manifest and the frontmatter (`PageFileProvenance`). |
| **Traversed, nothing new to do** | `OpenHost` (742), `FetchRobots` (767) and the robots rules: unchanged, `fetch_robots` serving `ReadRobotsBeforeSitemap` for another origin; `AdoptRobotsRules` (811) still records `declared_sitemaps` with `robots_sitemaps` (Facts). `SelectBatch` (1185), `NextBatch` (1243) and the entry rules: unchanged, now meeting rows at depth 1 with `sitemap_priority` and `llms_txt_priority`, and the page budget stopping a run that discovery filled. `FetchEntry` (1325): unchanged; its `conditional` test already reads `entry.sitemap_lastmod`, which a sitemap now sets (a change of `lastmod` makes the next refetch unconditional; the incremental slice owns what follows). `FinishRun` (1861): not reached by a dry run, which goes `DryRun` to `RunEnding` (`EndRun`, 1898), so a dry run's `unresolved_urls` is empty. `AnnounceBackoff` (`rovo.allium` 568): a sitemap's retries raise `HostBackedOff` as robots.txt's do, with no sink. |
| **Later slices'** | `ReuseUnchangedSitemap` (1009) and the conditional sitemap fetch are the incremental slice's (T14): this slice keeps each `SitemapSnapshot` in the run's frontier only, never saves or loads one, and so never sends a sitemap's validators (Facts). `config-default.discovery_max_redirects` and every 3xx answer to a sitemap or an llms.txt are the redirects slice's, as a 3xx robots.txt is (T12). The targeted and owner-testing branches of `Discover` and `PrepareRun` stay where T09 left them. |
| **Outside this slice; reaching one still stops the run** | Every raise T12 left, minus `NotInThisSlice("DryRun")` (`run.py` 1133) and `NotInThisSlice("CloseRun")` (`_report.py` 317), which this slice removes; plus three new ones: a 3xx answer to a sitemap (`NotInThisSlice("FetchSitemap")`) or to an llms.txt (`NotInThisSlice("ReadLlmsTxt")`), redirect following being the redirects slice's as it is for robots.txt; and a profile whose `sitemap_include` holds a `{section}` or `{locale}` placeholder (`NotInThisSlice("sitemap_admitted")`, Open points, item 4), which only `mslearn` has and whose conversion already stops the run. A Retry-After past `retry_after_cap` on a robots.txt or a declared sitemap's try retires the host, which stays `NotInThisSlice("RetireHostOnLongRetryAfter")` (the breaker slice's, T18); on a speculative probe it pauses the host instead (Open points, item 1, answered at `ecfa257`). |

### Facts a later reader would otherwise rediscover

- **Every sync now makes three more requests per host.** For each allowed host,
  `/sitemap.xml`, `/sitemap_index.xml` and `/llms.txt` at `host.origin`, after its
  robots.txt and before any page, whenever that origin's robots rules allow them
  (`FetchSitemap` and `ReadLlmsTxt` require `robots_allows`). A disallow-all origin (a
  refused or unreachable robots.txt) gets none, and a second origin of a host gets none
  unless a sitemap names it (`QueueSitemaps` reads only `RobotsPolicy{origin:
  host.origin}`; `ReadLlmsTxt` reads `llms_txt_url(name)` at `host.origin`). A 404 for
  each is silent (a speculative probe never fails the run). So every earlier test that
  asserts an exact request list or request log over a site that allows `/` changes, and
  so does every `bytes_fetched` equality over the fixture server, whose 404 bodies are
  not empty (`tests/fakes.py`' `not_found` has size 0, so the unit suite's byte counts
  stay). Predicted, from `rg -n 'requests ==|\.paths\(|bytes_fetched ==' tests` at
  `7a9c135`: `tests/test_crawl.py` (the `discover`-driven lists from 590 to 1244 and
  1154, 1452, 1952), `tests/test_links.py` 280, `tests/test_commands.py` 259,
  `tests/e2e/test_polite_sync.py` 323 (the installed-script log); `test_polite_sync.py`
  212 (robots refused) and 287 (a second origin) are unchanged. Step 3's red run is the
  authority: every earlier test it shows red for this reason is re-propagated with a
  ledger note, its expected list gaining the three probes in that order, and nothing
  else in it changes.
- **The `CliRunner` sync over `robots-disallow` would now sleep for real.**
  `tests/e2e/test_init_sync.py`' `test_robots_disallow_skips_the_seed` (142, at
  `7a9c135`) syncs through `CliRunner`, which reaches `SystemTimer`. Its robots.txt
  disallows `/guide/` only, so the three probes follow at `1 / rate_per_host` (0.5 s)
  apart: about 1.5 s of real sleeping. It is re-propagated to patch the sleep `pace`
  calls first (`monkeypatch.setattr(pace.time, "sleep", recorder)`), as T12's exit-1
  `CliRunner` scenario does; nothing else in it changes. The other `CliRunner` syncs
  (`test_init_sync.py` 156 and 185, refusals; `test_polite_sync.py` 237, robots refused
  every time, so no probe) still never wait. Step 0 re-runs `rg -n 'invoke\(app' tests`
  and confirms it. The new `--dry-run` `CliRunner` scenario patches the sleep the same
  way.
- **The installed-script scenario grows by about 6 s.**
  `test_the_installed_script_waits_out_the_crawl_delay` (`test_polite_sync.py` 306) serves
  `Crawl-delay: 2`, so the three probes add three 2 s gaps; its expected log becomes
  robots.txt, the three probes, the seed and the page. It is re-propagated for that list
  only; its gap and elapsed assertions stand. Step 7 records the e2e suite's wall time
  before and after.
- **Sitemap snapshots last one run in this slice.** `AcceptFreshSitemap` creates or
  updates a `SitemapSnapshot` in the run's frontier, and nothing saves or loads one, so
  `FetchSitemap`'s `snapshot?.etag` is always null and no sitemap is ever fetched
  conditionally, `ReuseUnchangedSitemap` never fires, and `fetch_resource` keeps its
  signature (no validators parameter). Saving and loading the snapshots (their own file
  under `.rovo/`, decision 0013), sending their validators and reusing an unchanged
  sitemap are the incremental slice's together (T14); `save_frontier`'s docstring
  (`run.py` 1233 to 1234) is reworded to say so. Within one run a snapshot is created
  once, since each sitemap is read at most once, so `AcceptFreshSitemap`'s update branch
  is reached on unit inputs only.
- **Observations persist.** `frontier.json`'s `observed_urls` (today `[]`) holds one row
  per `ObservedUrl` (`url`, `sources` as a sorted list, `last_seen_run`), sorted by
  `url`, and `load_frontier` reads it back, so `RecordObservation`'s update branch and
  `DropStaleObservations` (a row unseen for more than `observed_url_retention_syncs`
  runs is dropped) act across runs. `docs/reference/mirror.md` moves with it.
- **The sitemap and llms.txt black boxes, as built** (contracts the specification leaves
  to the implementation, `crawl.allium` 47 to 59, with the readings Open points item 7
  asks the maintainer to confirm). `well_known_sitemaps(name)`: `<host.origin>/sitemap.xml`
  and `<host.origin>/sitemap_index.xml`, in that order. `llms_txt_url(name)`:
  `<host.origin>/llms.txt`. `is_sitemap_document`: the answer parses as XML and its root
  element is `urlset` or `sitemapindex` (local name, any namespace); `sitemap_is_index`:
  the root is `sitemapindex`; `sitemap_entries`: each `url` or `sitemap` child's `loc`
  text, stripped, with its `lastmod` text or null, in document order, a child without a
  `loc` skipped. A gzip file that HTTP did not decode, or a plain-text sitemap, is not a
  sitemap document. `resolve_url(base, loc)`: `urllib.parse.urljoin`. `robots_sitemaps`:
  protego's `sitemaps`, every `Sitemap` line of the file in order, as T09 records it;
  one on another host is dropped by `FetchSitemap`'s `hostname_of(url) = name` guard,
  producing nothing and no problem, whatever `robots_sitemaps` does with the host name.
  `llms_txt_targets`: the destination of every inline Markdown link (`[text](url)`) in
  the file, resolved against `llms_txt_url(name)`, in order, each once. `sitemap_admitted`
  with an empty `sitemap_include` (`generic`, `devsite`) admits every sitemap, as an
  empty `CrawlScope.include` admits every URL.
- **XML is parsed safely, with the locked `lxml`, in a new module.** The sitemap black
  boxes live in `src/rovo/_crawl/sitemaps.py` (pure: a `SiteResponse` or text in, values
  out) and parse with `lxml.etree.fromstring` under an `XMLParser` with
  `resolve_entities=False`, `no_network=True`, `load_dtd=False` and `huge_tree=False`;
  a document that does not parse is not a sitemap document. `lxml` is already a runtime
  dependency (beautifulsoup4's parser) and already in `ROOT_FORBIDDEN_TOPS`, so no
  dependency moves; `import rovo` stays third-party-free. ruff 0.17.3 has removed the
  bandit lxml rules (`ruff rule S320`, `ruff rule S410` say "Removed"), so ruff needs no
  suppression. mypy does: lxml ships neither `py.typed` nor stubs, and no stub package
  is locked (checked at `7a9c135`: `mypy --strict` over `from lxml import etree` reports
  `import-untyped`), and `mypy.ini` is not changed, so the one expected suppression is
  on that import line in `sitemaps.py`, naming its rule and reason as invariant 4 asks
  (`# type: ignore[import-untyped]  lxml ships no type information`). Every value read
  from the tree is then `Any`, so `sitemaps.py` turns each into a `str` (or `None`)
  before returning it, and no `Any` crosses its boundary (`warn_return_any`, part of
  strict). `scripts/wheel_smoke.py`' `PACKAGE_FILES` gains `rovo/_crawl/sitemaps.py`
  and every page that counts the package files (twenty-six) follows.
- **A URL with no identity is neither observed nor discovered** (Open points, items 2
  and 10, answered at `ecfa257`: skipped silently and uncounted, no problem). The specification says `identity_of` is null for a URL `normalise_url`
  cannot normalise (`mirror.allium` 113 to 118), and `ExpandSitemapEntries` and
  `ReadLlmsTxt` raise `UrlObserved` with `scope.identity_of(...)` unguarded; the code's
  `normalise_url` raises `ValueError` instead. Until the maintainer answers, such a
  sitemap entry or llms.txt target is skipped: no `ObservedUrl`, no `UrlDiscovered`, no
  problem, and it counts toward neither sitemap cap, by the precedent of `mirror.allium`
  1106 to 1109 (a destination whose identity cannot be computed satisfies no rule) and
  of `within_bounds` (a malformed URL is out of bounds). The run never crashes on one.
- **Sitemap and llms.txt tries are `fetch_resource`'s** (Open points, items 1 and 3,
  answered at `ecfa257`): each is retried as a robots.txt try is, with a `HostBackedOff`
  per retry and every honoured Retry-After on a retryable answer (a 429 or any 5xx)
  counted. A Retry-After past `retry_after_cap` ends the tries with that answer, no wait
  and no pause; the caller decides: a robots.txt or a declared sitemap (named by
  robots.txt or by a declared index) retires the host, still
  `NotInThisSlice("RetireHostOnLongRetryAfter")` (T18); a speculative probe (an
  undeclared well-known sitemap, llms.txt, or a speculative index's child) ends
  unavailable and silent and pauses the host until `retry_after_cap` from then, never
  shortening a longer pause, with a `HostBackedOff`. With `honor_retry_after` off
  neither happens. An index's children are declared exactly when the index is. Their
  bytes count toward `run.bytes_fetched`; their tries never count toward
  `run.fetch_attempts`.
- **The dry run, as built** (Open points, items 5 and 6, the interims). `rovo sync
  --dry-run OUT_DIR` passes `SyncOptions.dry_run` to the run. Discovery runs in full
  (robots.txt, sitemaps, llms.txt), then `DryRun` ends the run: no page is fetched,
  converted or written, and no finalise pass runs, so no page file, no index and no
  `_indexes/` is written or rewritten. `_commands` prints to standard output one line
  per row `SelectBatch` would consider (its `pending_rows`), the row's identity, in
  `next_pending` order (non-deferred first, then shallowest, then highest priority,
  then discovery order), and nothing else. It saves the manifest (`StartSync`'s fields,
  as every sync does), the frontier (the re-pended rows persist, `DryRun` guidance
  1159 to 1163) and the run's row in `runs.json` (`dry_run: true`), and writes
  `crawl-report.json` (`options.dry_run` true, `fetched` 0, `discovered` the frontier's
  rows after discovery, the report replacing the previous one). Its exit code is
  `RankAndWriteReport`'s: 1 for a discovery problem, else 0.
- **`discovered` is counted after discovery.** `CloseRun`'s `discovered_count` is "the
  number of frontier rows after discovery" (`rovo.allium` 642 to 643); `close_run`
  counts the frontier's rows when the run closes (`_report.py` 314), which includes
  every row a link added. The run records the count when `DropStaleObservations` raises
  `DiscoveryDone`, and `close_run` reports it. This divergence predates the slice and
  matters now that discovery fills the frontier; the fix has its regression test in
  `tests/test_regressions.py`, and every earlier test asserting `discovered` over a run
  that followed links is re-propagated with a ledger note.
- **Generating sites with ports.** A sitemap `loc` is an absolute URL, and an index's
  child on another host must carry a port, so the discovery sites are generated into
  `tmp_path` by a helper in `tests/e2e/test_discovery_sync.py`, served first and written
  after (`http.server` reads each file per request), as T12's two-origin site was. The
  "another host" is `localhost` on a second server's port: `hostname_of` gives
  `localhost`, not `127.0.0.1`, so it is another host name, and the second server's
  empty request log proves the child was never fetched.
- **Changing a `config` value in a test.** The page budget (`max_pages`, 5000) is a
  `config` constant, not a `rovo.toml` key. The budget scenario replaces `CONFIG` with
  `dataclasses.replace(CONFIG, max_pages=2)` in every module that binds it
  (`rg -l 'import.*\bCONFIG\b|CONFIG =' src` at step 0: `model.py`, `run.py`, `pace.py`
  and any other it prints) with `monkeypatch.setattr`; the code is never changed to make
  that easier.
- **No end-to-end scenario syncs written pages twice.** A second ordinary sync over a
  mirror that holds pages refetches them conditionally, and `http.server` answers
  `If-Modified-Since` with 304, which reaches `DisposeFetch`'s unchanged branch, still
  `NotInThisSlice` (the incremental slice's). So the scenarios that need several runs
  make them dry runs, or follow a dry run with one ordinary sync of a mirror that holds
  no page yet; a re-pend across runs is proved on unit inputs.
- **The obligation source.** `just plan-spec <module>` over `docs/specs/<module>.allium`
  at `fa096c4`, written to `ai_tmp/T13/plan-spec-<module>.txt` (its echo line to
  `ai_tmp/T13/plan-spec-<module>.err`): crawl 375, rovo 165, mirror 200, convert 47
  obligations. The obligations with no test named after them at `7a9c135` are in
  `ai_tmp/T13/uncovered-<module>.txt` (crawl 195, rovo 98, mirror 88, convert 0); the
  owned set of step 3 is `ai_tmp/T13/owned.json`. The copies are scratch, regenerated by
  step 0.

## Goal

From a clean checkout, against served fixture sites, `rovo sync` discovers pages beyond
the seeds: it reads each allowed host's declared sitemaps and its conventional
`/sitemap.xml` and `/sitemap_index.xml` (sitemap indexes too, their children only on
the host that served the index, at most `sitemap_max_children` per host), reads
`/llms.txt`, records every URL they name under `observed_urls` in `frontier.json`
whatever its scope, admits the in-scope ones at depth 1 with their priorities (at most
`max_pages * sitemap_cap_multiplier` sitemap entries per host), fetches and publishes
them like any page, reports a declared sitemap that is unavailable, unreachable or not
a sitemap under `discovery_problems` and exits 1 for it, and stays silent for a
speculative probe or an llms.txt that fails. `rovo sync --dry-run` does the same
discovery, fetches no page, prints the pending identities one per line, saves the
frontier and the report, and writes no page or index. Every owned obligation listed
under Steps has a test named after its id; no test sleeps for real; `just check` is
green; the Allium loop's witness record says `PASS`.

## Non-goals

- No incremental reuse: no sitemap snapshot is saved, loaded or sent as validators, and
  `ReuseUnchangedSitemap` is not realised (T14; Facts).
- No redirect following for a sitemap or an llms.txt: a 3xx answer stops the run, as for
  robots.txt; `config-default.discovery_max_redirects` is not owned.
- No sitemap children on another host: the open question (`crawl.allium` 2272 at
  `ecfa257`) stays
  open, and its interim, children read only on the host that served the index, is what
  this slice builds and tests.
- No `{section}` or `{locale}` filling in `sitemap_include` (Open points, item 4): a
  profile with a placeholder stops the run at `sitemap_admitted`.
- No progress output: `HostBackedOff` reaches no sink; the dry run's listing is the one
  thing printed, as `ProgressOnRequest` states.
- No targeted or owner-testing discovery: `Discover`'s and `PrepareRun`'s other branches
  stay `NotInThisSlice`.
- No new `rovo.toml` key or environment variable; one new flag, `--dry-run`; no new
  dependency (`lxml` is already a runtime dependency, Facts).
- No specification change: `docs/specs/` is read, not edited. The six `open question`
  blocks stay open (`crawl.allium` 2272 to 2274 at `ecfa257`, `convert.allium` 473 to 475); the first
  is on this slice's path and its interim holds. A specification gap found while
  planning, implementing, in weed or in review is never resolved in code or in the
  specification: every such gap joins the one batched needs-user question (Open points)
  and the ledger's `open_questions`.
- No change to the public API: `__all__` stays `["__version__"]`, so
  `docs/reference/api.md` does not move. No decision record changes.
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `src/rovo/_crawl/sitemaps.py` | new | the pure discovery black boxes (Facts): `well_known_sitemaps`, `llms_txt_url`, `is_sitemap_document`, `sitemap_is_index`, `sitemap_entries` (lxml with entities, the network and DTDs off), `resolve_url`, `llms_txt_targets`, `sitemap_admitted` (an empty `sitemap_include` admits all; a placeholder raises `NotInThisSlice("sitemap_admitted")`); the follow-up moves two docstrings' citations to the specification |
| `src/rovo/_crawl/model.py` | shared, own lines | `SitemapEntry`, `ObservedUrl` and `SitemapSnapshot`; `Frontier.observed_urls` typed and `Frontier.sitemap_snapshots`; the run's implementation state for the sitemaps read this run and the frontier's row count after discovery; the follow-up drops `SiteResponse.may_carry_retry_after` (gone from `crawl.allium` at `ecfa257`) and moves two citations to `ecfa257` |
| `src/rovo/_crawl/run.py` | shared, own lines | `discover` raising the host's sitemaps and llms.txt; `queue_sitemaps`, `read_robots_before_sitemap`, `fetch_sitemap`, `accept_fresh_sitemap`, `reject_non_sitemap`, `skip_unavailable_sitemap`, `expand_sitemap_entries`, `read_llms_txt`, `record_observation`; `drop_stale_observations` with its effect and the discovered count; `dry_run` and `begin_crawl`; `drive_run` ending a dry run at `DryRun` (its `NotInThisSlice("DryRun")` removed); the 3xx guards of Context; `load_frontier` and `save_frontier` reading and writing `observed_urls`; a pure `dry_run_listing(run, frontier)` (the pending rows' identities in `next_pending` order); the module and `save_frontier` docstrings; the follow-up: an index's children inherit `declared`, `fetch_robots` and a declared sitemap retire the host on a long Retry-After (still `NotInThisSlice`), a speculative probe's long Retry-After pauses the host, `count_retry_after` counts any retryable answer |
| `src/rovo/_report.py` | shared, own lines | `close_run`'s dry-run branch (no finalise pass; its `NotInThisSlice("CloseRun")` removed) and `discovered` from the run's count |
| `src/rovo/_commands.py` | shared, own lines | `sync(..., dry_run=False)`: `SyncOptions.dry_run` from it; a dry run prints the listing on standard output, skips `finalise`, saves the manifest and the run, and writes the report |
| `src/rovo/cli.py` | shared, own lines | `sync_command` gains `--dry-run` |
| `scripts/wheel_smoke.py` | shared, own lines | `PACKAGE_FILES` gains `rovo/_crawl/sitemaps.py`; the verdict line's count follows |
| `tests/fakes.py` | shared, own lines | `xml_response(url, text)` beside `html_response` and `text_response`; `fixture_site` answers `.xml` files with it |
| `tests/test_crawl.py` | shared, own lines | the crawl obligations of step 3; the re-propagated tests of step 3; the follow-up renumbers `rule-failure.ReadRobotsBeforeSitemap.3` to `.5` and `rule-failure.FetchSitemap.3` to `.6` one up, adds the identity guards `.3`, re-propagates T12's `test_rule_success_CountRetryAfter`, `test_rule_failure_CountRetryAfter_3` and `test_entity_fields_SiteResponse`, and adds the pause, retry-count, declaredness and no-identity guarantees |
| `tests/test_sitemaps.py` | new | hand-written black-box tables (Facts): a urlset, an index, a namespaced and an unnamespaced root, a child without `loc`, `lastmod` present and absent, a document that does not parse, an entity declaration not expanded, a plain-text and an HTML answer; `llms_txt_targets` on inline links, a relative link, a repeated link, text with no link; `sitemap_admitted` on an empty filter and a placeholder; the follow-up adds an empty `loc` skipped and a `lastmod` stripped |
| `tests/test_mirror.py` | shared, own lines | the mirror obligations of step 3 |
| `tests/test_report.py` | shared, own lines (re-propagated) | `test_rule_success_CloseRun` gains the dry-run branch and `discovered` after discovery |
| `tests/test_commands.py` | shared, own lines (re-propagated) | `sync` with `dry_run`; the exact request list at 259; the follow-up moves a docstring's citation to the specification |
| `tests/test_cli.py` | shared, own lines | `rovo sync --help` names `--dry-run`, only if a test lists sync's options |
| `tests/test_links.py` | shared, own lines (re-propagated) | the exact request list at 280 |
| `tests/test_slice_boundaries.py` | shared, own lines (re-propagated) | `test_owner_testing_and_dry_runs_stop` loses its dry-run half and `test_a_dry_run_report_and_a_versioned_path_stop` its `close_run` half (both now realised); the three new guards of Context, each asserted; the follow-up adds a declared sitemap's long Retry-After stopping at `RetireHostOnLongRetryAfter`, and re-propagates T12's `test_httpx_fetcher_sends_validators_and_reads_retry_after` (`retryable` for `may_carry_retry_after`) |
| `tests/test_regressions.py` | shared, own lines | one test per divergence planning, weed or review finds: `discovered` counts the rows after discovery, not the rows a link added later; a sitemap entry and an llms.txt target with no identity (a port out of range) leave the run finishing, unobserved and undiscovered; the follow-up moves two docstrings' citations to the specification |
| `tests/test_pace.py` | shared, own lines (re-propagated) | only the tests the red run shows red for the three probes (Facts); the follow-up moves its `crawl.allium` citations to `ecfa257` |
| `tests/test_convert.py` | shared, own lines | the follow-up moves one `crawl.allium` citation to `ecfa257` |
| `src/rovo/_crawl/pace.py` | shared, own lines | the follow-up: `fetch_resource` counts every honoured Retry-After on a retryable answer and ends its tries on one past `retry_after_cap`, leaving retirement or pause to its caller |
| `tests/e2e/test_discovery_sync.py` | new | the end-to-end scenarios (Acceptance criteria) and the site-generating helper; not `test_sitemaps.py` or `test_discovery.py`, so no unit test shares its basename; the follow-up adds the speculative probes' pause and silence scenario |
| `tests/e2e/test_init_sync.py` | shared, own lines (re-propagated) | `test_robots_disallow_skips_the_seed` patches `pace.time.sleep` before its `CliRunner` sync (Facts) |
| `tests/e2e/test_polite_sync.py` | shared, own lines (re-propagated) | the installed-script scenario's expected log gains the three probes; any other scenario the red run shows red for them |
| `tests/e2e/test_follow_links.py`, `tests/e2e/test_index_files.py` | shared, own lines (re-propagated) | only where the red run shows an exact log, `discovered` or `bytes_fetched` assertion red for the probes |
| `docs/reference/cli.md` | shared, own lines | `rovo sync`: discovery from sitemaps and llms.txt, the index children, the observations, the declared-sitemap problems and the silent probes, the sitemap caps; `--dry-run` and its listing; the later-slice sentence gains a redirected sitemap or llms.txt and a profile whose sitemap filter has a placeholder; the usage block; the follow-up: retries of sitemaps and `llms.txt`, a probe's long Retry-After pausing the host, children declared as their index, every honoured Retry-After counted |
| `docs/reference/mirror.md` | shared, own lines | `frontier.json`'s `observed_urls` filled and read back; sitemap snapshots not yet saved (T14); a dry run's files |
| `docs/reference/testing.md` | shared, own lines | `tests/test_sitemaps.py`, `tests/e2e/test_discovery_sync.py`, `xml_response`, the package-file count |
| `docs/how-to/test-and-debug.md` | shared, own lines | the package-file count |
| `docs/explanation/architecture.md` | shared, own lines | `sitemaps` in `_crawl`'s part of the private modules' row |
| `docs/project/repository-map.md` | shared, own lines | the tree gains `sitemaps.py`, `test_sitemaps.py` and `test_discovery_sync.py` |
| `AGENTS.md` | shared, own lines | line 10's "today" sentence ("mirror the pages linked from the seeds") becomes false: it names the sitemaps and llms.txt too |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` Added entry: sitemaps, llms.txt, observations, the sitemap caps and `--dry-run`; the follow-up extends it with the answered behaviour |
| `tickets/README.md`, `tickets/T13-discovery.md` | ticket | index row, graph, slice bullet, this ticket |
| `.allium-loop/T13-discovery.json`, `.allium-loop/T13-discovery.witness.json` | gitignored | the loop ledger and the witness record; never committed |

`pyproject.toml`, `uv.lock`, `pytest.ini`, `.coveragerc`, `ruff.toml`, `mypy.ini`,
`Justfile`, `src/rovo/__init__.py`, `src/rovo/_crawl/fetch.py`,
`src/rovo/_mirror/`, `src/rovo/_convert/`, `src/rovo/_config.py`, `tests/e2e/conftest.py`,
`tests/test_import_direction.py`, `docs/decisions/` and `docs/specs/` are read, not
changed. A file not in this table that turns out to need a change is added to the table
in the same change with its reason, or handed back if it is a decision record or a
specification.

## Steps

This slice has no **Adversarial review** checkpoint (`tickets/CONVENTIONS.md` §14): it
builds on T12's limiter and fetcher and lays down no design a later lane builds on
beyond the black boxes, which `tests/test_sitemaps.py` pins. Weed and the witness (step
8) are its review.

0. `just check` baseline on the untouched worktree at `7a9c135` plus this ticket, last
   line quoted, and `{ time just py-test tests/e2e -ra; echo "exit $?"; } 2>&1 | tail -6`
   with its wall time. Scratch output goes in `ai_tmp/T13/`. Write `just plan-spec
   <module>` for each of `crawl`, `rovo`, `mirror` and `convert` to
   `ai_tmp/T13/plan-spec-<module>.txt`, confirm `ai_tmp/T13/owned.json` against them, and
   re-run `rg -n 'invoke\(app' tests`, `rg -n 'requests ==|\.paths\(|bytes_fetched ==|"discovered"' tests`
   and `rg -l 'import.*\bCONFIG\b|CONFIG =' src`, quoting each against Facts. Create the
   ledger `.allium-loop/T13-discovery.json` against
   `allium-skill-reference/allium/schemas/ledger.schema.json`, shaped like T12's: `goal`
   `"T13-discovery"`, `mode` `"spec-first"`, `tick` 0, `specification_base` `fa096c4`,
   `obligation_source` the four files, and `open_questions` holding the six
   specification open questions verbatim and the batched question of the Open points,
   each item marked OPEN. Read `.agents/skills/propagate/SKILL.md`,
   `.agents/skills/weed/SKILL.md`, `.agents/skills/witness/SKILL.md` and
   `.agents/skills/python-change/SKILL.md` before step 3.

1. **The black boxes.** `src/rovo/_crawl/sitemaps.py` per Facts, pure, importing only the
   standard library, `lxml` and `rovo._crawl.model`, `rovo._mirror` and `rovo._convert`
   types; `tests/test_sitemaps.py`. `just py-test tests/test_sitemaps.py
   tests/test_import_direction.py`.

2. **The rules.** In `run.py`, per the Context table: `discover`'s standard branch, for
   each allowed host in sorted order, opens it, then `queue_sitemaps` and
   `read_llms_txt`, so every host is opened and its robots.txt answered before its
   sitemaps (`QueueSitemaps` guidance). Each `SitemapDue` goes to
   `read_robots_before_sitemap` (then due again) or `fetch_sitemap`, whose answer goes
   to exactly one of `accept_fresh_sitemap`, `reject_non_sitemap` or
   `skip_unavailable_sitemap` (a 304 with no snapshot meets none: no rule fires); an
   accepted one goes to `expand_sitemap_entries`, whose children are due in turn. Every
   value comes from `CONFIG`, the profile or the scope, never a literal. Each
   `DiscoveryFailed` joins `run.discovery_failures`, which `_commands` already tallies.
   `record_observation` keys by URL; `drop_stale_observations` drops a row whose
   `last_seen_run + observed_url_retention_syncs < run.id`, then records the discovered
   count. `drive_run` ends a dry run after `drop_stale_observations` (`DryRun`, then
   `end_run`), else `begin_crawl`.

3. **Tests first, from the obligations** (the `propagate` skill, spec-first). Write a
   failing test for each owned obligation below into the test file of its module, named
   `test_<obligation id with dots and hyphens as underscores>`, its docstring quoting the
   obligation's description from the plan-spec file. Generated tests satisfy EditorConfig
   (indentation in 4-space multiples in `*.py`, string literals included, so a sitemap
   or llms.txt literal is indented by four), ruff and mypy, since the gate stages them.
   Run `just py-test` and record the red run in `ai_tmp/T13/red.txt`, its summary line
   under `last_results.propagate` in the ledger. Record each generated or re-propagated
   test file's SHA-256 under `generated_test_hashes`, and the reconciliation line (`N
   obligations, M covered, K uncovered`) over the owned set. A test changed after the red
   run is re-recorded: a new hash, `tick` incremented, a ledger note naming the test and
   why; never silently. An obligation a test cannot reach without a later slice's
   behaviour is not owned: move it to the hand-back notes with its reason rather than
   writing a vacuous test.

   Owned obligations, new in this slice (ids as `just plan-spec <module>` emits them at
   `fa096c4`; 52):

   - **`crawl`** (50), in `tests/test_crawl.py`: `value-equality.SitemapEntry`,
     `entity-fields.SitemapEntry`, `enum-comparable.DiscoverySource`,
     `entity-relationship.Frontier.observed_urls`,
     `entity-optional.FrontierEntry.discovered_from`,
     `entity-optional.FrontierEntry.sitemap_lastmod`, `entity-fields.ObservedUrl`,
     `entity-fields.SitemapSnapshot`, `entity-optional.SitemapSnapshot.etag`,
     `entity-optional.SitemapSnapshot.last_modified`,
     `transition-edge.FrontierEntry.skipped_limit.pending`,
     `config-default.sitemap_max_children`, `config-default.sitemap_cap_multiplier`,
     `config-default.sitemap_depth`, `config-default.llms_txt_depth`,
     `config-default.sitemap_priority`, `config-default.llms_txt_priority`,
     `rule-success.QueueSitemaps`, `rule-failure.QueueSitemaps.1`,
     `rule-failure.QueueSitemaps.2`, `rule-success.ReadRobotsBeforeSitemap`,
     `rule-failure.ReadRobotsBeforeSitemap.1` to `.6`, `rule-success.FetchSitemap`,
     `rule-failure.FetchSitemap.1` to `.7`, `rule-success.AcceptFreshSitemap`,
     `rule-failure.AcceptFreshSitemap.1`, `rule-success.RejectNonSitemap`,
     `rule-failure.RejectNonSitemap.1`, `rule-success.SkipUnavailableSitemap`,
     `rule-failure.SkipUnavailableSitemap.1`, `rule-success.ExpandSitemapEntries`,
     `rule-failure.ExpandSitemapEntries.1`, `rule-success.ReadLlmsTxt`,
     `rule-failure.ReadLlmsTxt.1` to `.3`, `rule-success.RecordObservation`,
     `rule-success.DryRun`, `rule-failure.DryRun.1`, `rule-failure.DryRun.2`,
     `rule-failure.BeginCrawl.2`.
   - **`mirror`** (2), in `tests/test_mirror.py`:
     `entity-optional.PageCandidate.sitemap_lastmod`,
     `entity-optional.Page.sitemap_lastmod` (a non-null value now reaches both from a
     sitemap entry's `lastmod`).
   - **`rovo`**, **`convert`**: none.

   Extended, not new (re-propagated in place, same names, each re-hashed in this slice's
   ledger with a note naming its origin slice; T09's to T12's ledgers are never edited):
   `test_rule_success_Discover` (the host's sitemaps and llms.txt are requested, after
   its robots.txt), `test_rule_success_DropStaleObservations` and
   `test_rule_failure_DropStaleObservations_1` (a stale row dropped, a fresh one kept,
   `DiscoveryDone` still raised), `test_rule_success_CloseRun` (the dry-run branch
   requests no finalise pass; `discovered` is the count after discovery), the two
   `tests/test_slice_boundaries.py` tests the Files touched table names, and every earlier
   test whose exact request list, request log, `discovered` or `bytes_fetched` the three
   probes or the discovered count change (Facts), each with only that expectation moved.
   Claim an earlier test "passes unedited" only where it does; the hand-back notes list
   every earlier test this slice edited.

   Guarantees and black boxes (no obligation id; hand-written): `tests/test_sitemaps.py`
   (Files touched); in `tests/test_crawl.py`, the open question's interim (an index's
   child on another host is never requested and not counted toward
   `sitemap_children_read`), each sitemap read at most once per run (an index naming
   itself, and two indexes naming one child), the two caps (the
   `sitemap_max_children + 1`th child and the `max_pages * sitemap_cap_multiplier + 1`th
   entry not queued, on a run whose `CONFIG` is replaced as Facts says), a declared 404
   silent, the speculative probes silent on every failure, an llms.txt silent on a 404
   and a transport error, and `ProgressOnRequest`'s dry-run listing on unit inputs.

   Not owned, and why, for the hand-back notes: `rule-*.ReuseUnchangedSitemap` (T14,
   the conditional sitemap fetch); `config-default.discovery_max_redirects` (the
   redirects slice); `value-equality.SyncOptions` and `entity-fields.SyncOptions` (the
   model lacks `owner_test`, the owner-testing slice's); `rule-failure.StartSync.4` and
   `.5` (the targets slice); every other uncovered obligation in the four files, each
   belonging to the slice T09's Context table names.

4. **Crawl** (`src/rovo/_crawl/`). `sitemaps.py`, then `model.py` and `run.py` per steps
   1 and 2 and the Context table. Unit cases in `tests/test_crawl.py` on `FakeFetcher`
   and `ScriptedFetcher` with `FixedClock`. `just py-test tests/test_crawl.py
   tests/test_sitemaps.py tests/test_slice_boundaries.py tests/test_regressions.py`.

5. **Report and command** (`src/rovo/_report.py`, `src/rovo/_commands.py`,
   `src/rovo/cli.py`). `close_run`'s dry-run branch and the discovered count; `sync`'s
   dry run per Facts; `--dry-run` on the command line (`typer.Option("--dry-run",
   help=...)`). Unit cases in `tests/test_report.py` and `tests/test_commands.py`, the
   dry run's standard output read with `capsys`. Run `just py-lint`, `just py-typecheck`,
   `just coverage`; add `rovo/_crawl/sitemaps.py` to `PACKAGE_FILES` and run
   `just wheel-smoke`, quoting its `api` line.

6. **End to end.** No new static fixture site: every discovery site is generated into
   `tmp_path` by `tests/e2e/test_discovery_sync.py`' helper (Facts), each page with a
   `<title>` and a `<main>` holding an `h1` and a paragraph of prose, two-space
   indentation and a final newline, no link to a missing file, a directory without its
   slash or a non-HTML file. The base site: `robots.txt` (`User-agent: *`,
   `Disallow: /guide/private/`, `Sitemap: <base>maps/index.xml`); `maps/index.xml`, a
   `sitemapindex` naming `<base>maps/guide.xml` and `http://localhost:<other port>/maps/child.xml`;
   `maps/guide.xml`, a `urlset` naming `<base>guide/orphan.html` (with
   `<lastmod>2026-10-01</lastmod>`), `<base>outside/page.html` and
   `<base>guide/private/hidden.html`; `llms.txt` with one inline link to
   `<base>guide/from-llms.html`; `guide/start.html` (the seed, linking nothing),
   `guide/orphan.html`, `guide/from-llms.html`, `guide/private/hidden.html` and
   `outside/page.html`, none linked from any page. The scenarios are the Acceptance
   criteria's; the in-process ones run `rovo._commands.sync` over a real `HttpxFetcher`
   with `FixedClock` (which never sleeps), and read order off the server's request log.
   `just py-test tests/e2e -ra`, its wall time quoted beside step 0's.

7. **Witness** (the `weed` and `witness` skills). Run `weed` over `crawl`, `rovo` and
   `mirror` against the code, scoped to the owned and extended obligations, the
   black-box readings and the guarantees; record its verdict under `last_results.weed`
   and fix any code divergence, each with a regression test in
   `tests/test_regressions.py`. A divergence weed attributes to the specification is not
   fixed: it joins the one batched needs-user question. Then run `witness`
   non-interactively: it writes `.allium-loop/T13-discovery.witness.json` per
   `witness-result.schema.json`. The verdict must be `PASS`; a `FAIL` routes back per the
   skill, and the hand-back notes record each round. A batched question still OPEN does
   not block `PASS` unless it blocks an owned obligation; the witness escalates one that
   does.

8. **Documents** (the `review-docs` skill). The pages of the Files touched table; find
   the sentences this slice makes false with
   `rg -n -i "sitemap|llms|dry.run|observed|linked from the seeds|discovery slice" -g '*.md' -g '!tickets/**' -g '!allium-skill-reference/**' -g '!docs/specs/**' -g '!docs/decisions/**'`;
   `CHANGELOG.md` `Unreleased` gains one Added entry. Keep the required phrases of
   `AGENTS.md` in always-visible text. `just check-docs`, `just check-agents`, and
   `just lint`, whose hooks include markdownlint over this ticket.

9. Hand-back notes, `status: done`, `just check` ending with
   `All checks passed and the worktree is unchanged.`, `git status --short` empty after
   the commit. Commit on the branch. **Authorisation required**: pushing and opening the
   pull request.

## Acceptance criteria

- **End to end, sitemaps and llms.txt** (`tests/e2e/test_discovery_sync.py`, in process):
  the base site (step 6) at `<base>`, a second server for `localhost` serving an empty
  directory at `<other port>`; `rovo init <base>guide/start.html <tmp>/out`, then
  `rovo._commands.sync` exits 0. The server's log starts with `/robots.txt`;
  `/maps/index.xml`, `/maps/guide.xml`, `/sitemap.xml`, `/sitemap_index.xml` and
  `/llms.txt` are each requested once, all before the first page request; the second
  server's log is empty. `start`, `orphan` and `from-llms` are written;
  `/outside/page.html` and `/guide/private/hidden.html` are never requested. In
  `frontier.json`, the orphan's row has `discovered_via: "sitemap"`, `depth`
  `sitemap_depth`, `priority` `sitemap_priority`, `discovered_from` `<base>maps/guide.xml`
  and `sitemap_lastmod` `"2026-10-01"`; the from-llms row has `discovered_via:
  "llms_txt"`, `depth` `llms_txt_depth`, `priority` `llms_txt_priority` and
  `discovered_from` `<base>llms.txt`; the hidden page's row is `skipped_robots`; no row
  holds the outside page; `observed_urls` holds the orphan, the outside page and the
  hidden page with `sources: ["sitemap"]` and the from-llms page with
  `sources: ["llms_txt"]`, each with `last_seen_run: 1`. The orphan's page file's
  frontmatter carries `sitemap_lastmod: "2026-10-01"` (JSON-quoted, as `_yaml_value`
  writes every string). `crawl-report.json` has
  `exit_code: "ok"`, `discovery_problems: []` and `discovered` 4 (the seed, the orphan,
  the from-llms page and the hidden page).
- **End to end, declared sitemaps that fail** (in process): the base site's robots.txt
  declares five sitemaps, `maps/missing.xml` (no file: 404), `maps/broken.xml` (scripted
  500 every time), `maps/page.html` (an HTML page), `maps/drop.xml` (scripted `DROP`
  every time) and `maps/guide.xml`; `/sitemap.xml` is scripted 500 and
  `/sitemap_index.xml` `DROP` every time, and `/llms.txt` `DROP` every time. The sync exits
  1; `discovery_problems` is exactly `[{"url": "<base>maps/broken.xml", "problem":
  "sitemap_unavailable"}, {"url": "<base>maps/drop.xml", "problem":
  "sitemap_unreachable"}, {"url": "<base>maps/page.html", "problem": "not_a_sitemap"}]`
  (sorted by URL): the declared 404, the speculative probes and the llms.txt are silent;
  the orphan from `maps/guide.xml` is still written.
- **End to end, the dry run** (`test_rovo_sync_dry_run_lists_what_it_would_fetch`, through
  `typer.testing.CliRunner`, with `pace.time.sleep` patched to a recorder first): over
  the base site, `rovo init`, then `CliRunner().invoke(app, ["sync", "--dry-run", <out>])`.
  `result.exit_code == 0`; `result.stdout` is exactly four lines, the identities of the
  seed, the orphan, the hidden page and the from-llms page, in that order, which is
  `next_pending`'s (the seed at depth 0 first, then the two sitemap rows at
  `sitemap_priority` in discovery order, then the llms.txt row at `llms_txt_priority`); the server's log holds robots.txt, the sitemaps and llms.txt and no page;
  `pages/`, `index.md`, `index.jsonl`, `links.jsonl`, `llms.txt` and `_indexes/` do not
  exist under `<out>`; `frontier.json` holds the four rows, all `pending`;
  `runs.json`'s one row has `dry_run: true`; `crawl-report.json` has
  `options.dry_run: true`, `fetched: 0`, `discovered: 4`, `exit_code: "ok"` and
  `unresolved_urls: []`; nothing slept for real. A second, ordinary sync of the same
  mirror (in process; the mirror holds no page yet, so no page is known and nothing is
  refetched conditionally) then writes the seed, the orphan and the from-llms page, so
  the dry run's rows persisted.
- **End to end, the page budget** (in process, `CONFIG` replaced with `max_pages = 2` as
  Facts says): a variant of the base site whose `maps/guide.xml` names four other
  in-scope pages, none disallowed, and which has no llms.txt. The sync exits 1;
  `crawl-report.json` has `budget_stopped: true` and `fetched: 2` (the seed's batch,
  then one row while `page_budget_remaining` is above zero; each walk is one attempt);
  the three rows not fetched are `skipped_limit`. Their re-pending on the next run
  (`transition-edge.FrontierEntry.skipped_limit.pending`) is a unit test: a second sync
  over written pages would refetch them conditionally, and the fixture server's 304
  answer is the incremental slice's (`DisposeFetch`'s unchanged branch still stops the
  run).
- **End to end, observations across runs** (in process, every sync a dry run, so no
  page is written and none is refetched): after the first dry run, the orphan's entry is
  removed from `maps/guide.xml`; after `observed_url_retention_syncs` further dry runs
  its `observed_urls` row is still there with `last_seen_run: 1`, and after one more it
  is gone, while the outside page's row (still listed) has `last_seen_run` equal to the
  last run's id.
- **End to end, earlier scenarios**: `tests/e2e/test_init_sync.py`,
  `tests/e2e/test_follow_links.py`, `tests/e2e/test_index_files.py`,
  `tests/e2e/test_polite_sync.py` and `tests/e2e/test_harness.py` pass; only the tests
  the Files touched table names were edited, each for the three probes or the
  discovered count alone, and the ledger says so.
- Every owned obligation in step 3 has a test named after it, red before the code and
  green after (`ai_tmp/T13/red.txt` and the final run); the reconciliation line shows
  zero uncovered; every extended test is re-hashed in the ledger with its note; every
  obligation dropped from the owned list is in the hand-back notes with its reason.
- No test sleeps for real: `rg -n 'time\.sleep\(' tests; test $? -eq 1`, and
  `test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py`; every `CliRunner` sync that
  makes two requests to one host patches `pace.time.sleep` first.
- The `NotInThisSlice` raises in `src/` are T12's set minus `DryRun` and `CloseRun`,
  plus `FetchSitemap` and `ReadLlmsTxt` (a 3xx answer) and `sitemap_admitted` (a
  placeholder) (`rg -n 'NotInThisSlice\(' src` compared with the same at `7a9c135`, the
  difference quoted).
- `lxml` is imported in `src` only under `src/rovo/_crawl/` and `src/rovo/_convert/`
  (`rg -n '^\s*(from|import) lxml' src`), and `sitemaps.py`' parser sets
  `resolve_entities=False` and `no_network=True` (`rg -n 'resolve_entities=False|no_network=True' src/rovo/_crawl/sitemaps.py`).
- `.allium-loop/T13-discovery.witness.json` exists with `"verdict": "PASS"`, and the
  ledger validates against `ledger.schema.json` with the batched question's items OPEN
  unless the maintainer answered them.
- `just check-specs` and `just analyse-specs` pass with `docs/specs/` unchanged since
  `fa096c4` (`git diff --stat fa096c4 -- docs/specs` empty).
- `import rovo` loads no module outside the standard library and `rovo`; `__all__` is
  `["__version__"]`; `just wheel-smoke` passes with the new package-file count.
- `just coverage` stays at or above the floor of 95.
- `just check-docs` and `just check-agents` pass; `docs/reference/cli.md` describes what
  `rovo sync` and `rovo sync --dry-run` now do, and `AGENTS.md` line 10 is true.
- `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty after the commit.

## Verification

```sh
just plan-spec crawl > ai_tmp/T13/plan-spec-crawl.txt
just plan-spec rovo > ai_tmp/T13/plan-spec-rovo.txt
just plan-spec mirror > ai_tmp/T13/plan-spec-mirror.txt
just plan-spec convert > ai_tmp/T13/plan-spec-convert.txt
git diff --stat fa096c4 -- docs/specs
just py-test tests/test_crawl.py tests/test_sitemaps.py tests/test_mirror.py tests/test_report.py tests/test_commands.py tests/test_slice_boundaries.py tests/test_regressions.py -ra
{ time just py-test tests/e2e -ra; echo "exit $?"; } 2>&1 | tail -6
just py-lint
just py-typecheck
just coverage
just wheel-smoke
uv run --frozen python -I -c "import rovo, sys; print(sorted(m for m in sys.modules if not m.startswith(('rovo', '_')) and m not in sys.stdlib_module_names))"
rg -n 'NotInThisSlice\(' src  # compared with the same at 7a9c135
rg -n '^\s*(from|import) lxml' src  # only src/rovo/_crawl/ and src/rovo/_convert/
rg -n 'resolve_entities=False|no_network=True' src/rovo/_crawl/sitemaps.py  # positive: both print
rg -n 'time\.sleep\(' tests; test $? -eq 1  # only "no match" passes
test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py
rg -n "discovery slice" src; test $? -eq 1  # only "no match" passes
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
after; the black boxes and the dry run as built and any departure from Facts and steps 1
and 2; the red run and the reconciliation line; every extended or re-propagated test,
its origin slice and its new hash; every obligation dropped from the owned list and why;
the weed verdict and the witness verdict, each round; the one batched needs-user
question with every gap found while planning, implementing, in weed or in review, and
the maintainer's answer if one arrived; the verification output, each headed by its
commit.

## Open points

- **The T13 batched needs-user question: ANSWERED** (items 1 to 10; the specification
  states the answers at `ecfa257`). Item 1: sitemap and llms.txt tries are retried as
  robots.txt's are; a declared sitemap may retire its host on a long Retry-After (the
  trip stays T18's), a speculative probe never does (follow-up B: it pauses the host for
  `retry_after_cap` instead), and an index's children are declared exactly when the
  index is (follow-up A). Items 2 and 10: a URL with no identity is skipped silently,
  uncounted, with no problem. Item 3: every honoured Retry-After is counted, on any
  retryable answer. Items 4 to 9: the interims are accepted as the specification now
  states them (`FetchSitemap`, `DryRun`, `AcceptFreshSitemap`, `ExpandSitemapEntries`,
  `ReadLlmsTxt` and `Discover` guidance). The question as asked follows. One question to the maintainer, its
  items numbered so an answer can cite them. Items 1 to 3 are carried from T12
  (`tickets/T12-robots-politeness.md` Open points; `ai_tmp/T12/answers-report.md`,
  Residual risk); items 4 to 7 were found while planning T13, item 8 by propagate.
  Item 9 was found by implement, item 10 by weed. Each states the interim this slice builds, which is reversible and never presented
  as the answer; propagate
  copies every item into the ledger's `open_questions` as OPEN, and the witness
  escalates one that blocks convergence. A gap found later (propagate, implement, weed)
  joins this question as a new item, never resolved in code. Line numbers are at
  `fa096c4`.
  1. **Sitemap and llms.txt retries through `fetch_resource`.** `FetchRobots`' guidance
     (798 to 808) says a robots.txt try is a page's http try: a `HostBackedOff` per
     retry, `retry_after_honored` counted, a Retry-After past `retry_after_cap` retiring
     the host. `FetchSitemap` (953) and `ReadLlmsTxt` (1089) call the same
     `fetch_resource`, whose general contract (792 to 797) says "with retries", but
     whether those three outcomes hold for a sitemap or an llms.txt try is unstated; in
     particular, whether a long Retry-After on a speculative `/sitemap.xml` probe may
     retire a host. Interim: they hold, exactly as for robots.txt (`fetch_resource`
     unchanged; the retirement stops at `NotInThisSlice("RetireHostOnLongRetryAfter")`).
  2. **A URL with no identity.** `mirror.allium` 113 to 118 says `identity_of` is null
     for a URL `normalise_url` cannot normalise; `ExpandSitemapEntries` (1068) and
     `ReadLlmsTxt` (1094) raise `UrlObserved(url: scope.identity_of(...))` unguarded, so
     the specification raises an observation with a null URL, which `RecordObservation`
     then keys on; the code's `normalise_url` raises `ValueError`. Is such an entry
     dropped, counted toward the sitemap cap, or reported? Interim: dropped, not
     observed, not discovered, not counted, no problem (Facts).
  3. **`retry_after_honored` on a 500 or 502.** `CountRetryAfter` (1517) and
     `FetchRobots`' guidance count a Retry-After only on a 429 or 503
     (`may_carry_retry_after`), while since `71b5b0f` a Retry-After on any retryable
     answer lengthens the wait (`HttpRetry` guidance). Should every honoured Retry-After
     be counted? Interim: only a 429 or 503, as the code does today.
  4. **`sitemap_admitted`'s placeholders.** `FetchSitemap`'s guidance (959 to 961) fills
     `sitemap_include`'s `{section}` and `{locale}` "with the scope's section and
     locale", but `CrawlScope` (`mirror.allium` 101 to 111) has no section, and the
     locale may be unpinned (null). What is `{section}`, and what does a pattern with
     `{locale}` match when no locale is pinned? Also unstated: whether an empty
     `sitemap_include` admits every sitemap or none. Interim: an empty filter admits
     every sitemap (as an empty `CrawlScope.include` admits every URL); a pattern with a
     placeholder stops the run at `NotInThisSlice("sitemap_admitted")` (only `mslearn`
     has one, and its conversion already stops the run).
  5. **The dry run's listing.** `DryRun`'s guidance (1160) and `ProgressOnRequest`
     (`rovo.allium` 938 to 939) say a dry run "lists the frontier as plain text" without
     saying which rows, in which order, or with which fields. Interim: the identity of
     each row `SelectBatch` would consider (`pending_rows`), one per line, in
     `next_pending` order, on standard output.
  6. **A dry run's state files.** The guidance says the re-pended rows persist and the
     report replaces the previous one; it does not say whether the manifest's
     `StartSync` fields (scope, profile, `recorded_root_url`, processing signature) and
     `runs.json` are saved. Interim: both are saved, as on every sync (`StartSync`'s
     ensures are unconditional); no page, index or finalisation.
  7. **The discovery black boxes' readings.** `crawl.allium` 47 to 59 leaves
     `is_sitemap_document`, `sitemap_entries`, `llms_txt_targets` and `resolve_url` to
     the implementation, yet their choice is visible: a declared gzip or plain-text
     sitemap is `not_a_sitemap`, which exits 1, and which llms.txt lines discover pages
     decides what is mirrored. Interim: the readings of Facts (an XML `urlset` or
     `sitemapindex`, any namespace, no gzip or text sitemap; every inline Markdown link
     of llms.txt; `urljoin`).
  8. **The order of discovery requests within a host** (found by propagate, tick 1).
     The specification says only that robots.txt comes first and that every host is
     opened before any sitemap, llms.txt or page request to it (`Discover`,
     `QueueSitemaps` guidance): whether an index's children are read as they fall due
     (depth first) or after every queued sitemap (breadth first), and whether llms.txt
     follows the sitemaps, is unstated. The order decides discovery order,
     `next_pending`'s last tie-break, so it shows in the dry run's listing and in which
     rows a page budget admits. Interim, pinned by the tests: per host in sorted order,
     robots.txt, the declared sitemaps in robots.txt order with each index's children
     read depth first as they fall due, then the well-known sitemaps not declared, then
     llms.txt.
  9. **Ranking a sitemap index's children** (found by implement, tick 1). The comment
     before `ExpandSitemapEntries` (1052 to 1054) ranks an index's children, one
     naming a token of the path prefixes first, then one naming the pinned locale, and
     drops one naming only other locales; the rule's `ensures` queues every child on
     the host in document order up to `sitemap_max_children`. Which ranking, and what
     "naming a token" means, is unstated, and it decides which children a large index
     gets within the cap. Interim: the `ensures` as written, document order, no
     ranking and no locale drop.
  10. **A sitemap URL with no identity** (found by weed, tick 1). Item 2 covers urlset
      entries and llms.txt targets; a robots-declared sitemap or a sitemap index child
      whose URL `normalise_url` cannot normalise (a port out of range, an unclosed IPv6
      bracket) meets the same gap through `hostname_of` and `origin_of` in
      `ReadRobotsBeforeSitemap` (933 to 938), `FetchSitemap` (947 to 950) and
      `ExpandSitemapEntries`' index branch (1064). Is such a sitemap skipped silently,
      as one on another host is, or reported under `discovery_problems` when declared
      (`DiscoveryProblem` has no member for it), and does such a child count toward
      `sitemap_children_read`? Interim: skipped, no problem, not counted; the run never
      crashes on one.
- **The T13 follow-up batched needs-user question: OPEN.** Gaps the answers leave,
  found while specifying them; each states the interim the specification at `ecfa257`
  implies, built and never presented as the answer. Line numbers are at `ecfa257`.
  1. **One URL falling due twice with different `declared` values** (a robots-declared
     sitemap that a speculative index also names, or a speculative well-known sitemap
     a declared index names). Interim: each sitemap is read at most once per run, so
     the first due wins; declared sitemaps come first in discovery order (`Discover`
     guidance, 742 to 756).
  2. **The speculative pause's length.** A speculative probe's Retry-After past the cap
     pauses the host for `retry_after_cap`, not for the longer time the server asked
     (`FetchSitemap` 999 to 1001, `ReadLlmsTxt` 1193 to 1195), and further discovery to
     that host carries on after it. Interim: `retry_after_cap`, as stated.
  3. **Speculative children and `sitemap_children_read`.** A speculative index's
     children count toward the per-host `sitemap_max_children` cap shared with declared
     ones, so a speculative index can use the cap up with silent probes. Interim: they
     count (`ExpandSitemapEntries`, 1143 to 1173).
  4. **Carried to T17: `mslearn`'s `sitemap_include`** (`*/{section}_{locale}_*.xml`,
     `convert.allium` 381). Until a decision fills `{section}` and `{locale}`, a run
     under it stops at `NotInThisSlice("sitemap_admitted")` at its first sitemap.
  5. **Carried to T18: a retired host's remaining discovery.** Once a host is retired,
     its remaining sitemaps and llms.txt are still requested as the rules stand. Interim:
     unchanged; retirement itself is still `NotInThisSlice` here.
- **The first `crawl.allium` open question** (2272 at `ecfa257`) is on this slice's path: may a
  sitemap index on an allowed host point at child sitemaps on other hosts? It stays
  open; its interim, children read only on the host that served the index, is built and
  tested (Acceptance criteria, the second server's empty log).
- **`ReuseUnchangedSitemap` and sitemap snapshot persistence belong to T14.** Facts give
  the boundary; T14's ticket owns `rule-success.ReuseUnchangedSitemap`, its two failure
  obligations, the snapshots' state file and the validators parameter of
  `fetch_resource`.
- **`NotInThisSlice`.** A development guard, not product behaviour: each later slice
  removes the raises it implements, and the last slice's review confirms none is left.
  This slice removes two and adds three (Acceptance criteria).
