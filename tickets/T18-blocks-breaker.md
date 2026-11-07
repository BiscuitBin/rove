---
id: T18
title: "Blocks and the breaker: block verdicts, blocked and skipped rows, the per-host breaker, host retirement on a long Crawl-delay or Retry-After, and exit 3"
status: open
depends_on: [T17]
parallel_with: []
branch: full-final-prototype
estimated_size: L
---

# T18: Blocks and the breaker: block verdicts, blocked and skipped rows, the per-host breaker, host retirement on a long Crawl-delay or Retry-After, and exit 3

## Context

T09 (`fd1b423`) to T17 (`8707969`, follow-up `663fb9a`) are slices 1 to 9. `rovo sync`
reads robots.txt, paces and retries, discovers through sitemaps and `llms.txt`, fetches
the seeds and the pages they link to, keeps each page through its lifecycle, converts
it with islands and every tab panel under the `generic`, `devsite` and `mslearn`
profiles, publishes it at `pages/<host>/<path>`, writes the indexes and
`crawl-report.json`, refuses in the specified order, survives an interrupt or a crash
with a report, and `rovo verify` and `rovo report` read the mirror offline. They fixed
every pattern this slice follows: the private subpackages `rovo._convert`,
`rovo._mirror` and `rovo._crawl` with `rovo._config`, `rovo._report` and
`rovo._commands` above them (import direction enforced by
`tests/test_import_direction.py`), the `Fetcher` and `Timer` seams (`FixedClock`,
`SteppingTimer`, `FakeFetcher`, `ScriptedFetcher` in `tests/fakes.py`), obligation-named
tests (`test_<obligation id>`), the end-to-end harness `serve_site` in
`tests/e2e/conftest.py` (its `script=` and `always=` answers), the state files of
`docs/reference/mirror.md`, and the development guard `rovo._unfinished.NotInThisSlice`.
Read `tickets/T16-errors-report.md` and `tickets/T17-quality-gates.md` (their Context
tables, Facts and Open points), `tickets/T12-robots-politeness.md` (the limiter, the
retry loop and the guard points it left for this slice), `src/rovo/_crawl/run.py`
(`fetch_robots`, `fetch_sitemap`, `select_batch`, `attempt_tier`, `feed_breaker`,
`dispose_fetch`, `classify_block`, `drive_run`, `_handle_entry`, `_settle`),
`src/rovo/_crawl/model.py` (`BlockVerdict`, `SiteResponse`, `Host`, `Breaker`,
`FetchAttempt`, `UrlSkippedBlocked`), `src/rovo/_report.py` (`tally_skipped_url`,
`announce_backoff`, `rank_and_write_report`), `src/rovo/_commands.py` (`sync` and the
post-run tallies), `tests/test_slice_boundaries.py` and `tests/e2e/test_polite_sync.py`
before starting.

This is slice 10 of T08 to T20, run in this worktree on `full-final-prototype`. Until now
every block stops the run: a 401 or 403 page and a login wall stop at
`NotInThisSlice("classify_block")` (`run.py` 1707, 1709), a 429 that survived its
retries at the same rule (1344), any verdict other than `none` at
`NotInThisSlice("DisposeFetch")` (1486), a host whose breaker should act at
`NotInThisSlice("BreakerTrips")` (1900), rows only on a tripped host at
`NotInThisSlice("SelectBatch")` (1198), and a host retirement at
`NotInThisSlice("RetireHostOnLongRetryAfter")` (a robots.txt try, 399; a declared
sitemap, 843; a page attempt, 1892) or `NotInThisSlice("RetireHostOnLongCrawlDelay")`
(403). `rovo._commands.sync` takes a `NotInThisSlice` as a stop, exits 1 and leaves the
previous report, so a retired host exits 1 today where the specification ranks it 3
(`rovo.allium` 706, `run.has_tripped_host`). `rank_and_write_report` already ranks
`blocked` (`_report.py` 462), `tally_skipped_url` exists with nothing raising its
trigger, and `SiteResponse.main_text` is never set by any fetcher (`model.py` 333, default
0), so no host ever has a text baseline and no soft verdict by text ratio can arise. The
specification base is `7d01367`. `86e2ec5` holds the maintainer's answers to this
slice's batched question (Open points): `crawl.allium` puts `not host.breaker_tripped`
on `FetchRobots`, `QueueSitemaps`, `ReadRobotsBeforeSitemap`, `FetchSitemap` and
`ReadLlmsTxt`, stops a redirect hop onto a tripped host, says no challenge recogniser
is specified yet and states the 429 reading; `mirror.allium` form-decodes the version
value; no obligation id was added, removed or renumbered
(`ai_tmp/T18/spec-answers/obligations-diff.md`). `7d01367` holds the answers to the
T18-2 batched question (Open points): `SkipTrippedHostAfterReady` settles a row whose
own readiness retires its host, `AttemptTier`, `HttpRetry` and `Escalate` require an
untripped host, `StopWalkOnTrippedHost` stops a walk that would need another request on
its tripped host while `SettleWalk` settles an answer it already holds
(`FetchAttempt.hop_refused`), and `rovo.allium`'s `AnnouncePage` says a page event means
a fetch settled; `crawl` gained nine obligations (382 to 391) and none was removed or
renumbered (`ai_tmp/T18/spec-answers-2/obligations-diff.md`). `git diff --stat 7d01367
-- docs/specs` is empty. Every specification line number below is at `7d01367`
(`ai_tmp/T18/spec-answers/line-map.md` maps `663fb9a` to `86e2ec5`, and
`ai_tmp/T18/spec-answers-2/line-map.md` `86e2ec5` to `7d01367`, its key-rules list
apart: `SkipTrippedHost` is at 1478, not 1476); every source line number is at
`663fb9a`, whose source neither specification commit changes.

### The specified path, and what this slice does with each rule on it

| Class | Rules |
| --- | --- |
| **Realised** (every branch reachable in this slice, or constructible on unit inputs where noted) | `crawl.allium`: `BlockVerdict` (133) and `counts_against_host`; `BlockKind` (195); `Run.tripped_hosts` and `has_tripped_host` (256 to 257); `Host` (408) its `median_text`, `has_text_baseline`, `breaker_tripped`, `block_rate` and `BlockedWithinFetched`; `Breaker` (439) its window, `over_threshold`, `should_act` and the edge `watching -> tripped`; `LadderWalk.soft_suspect` (479); `FetchAttempt.retires_host` (504) as it now settles the walk; the blocks and breaker config (586 to 595: `breaker_window`, `block_rate_threshold`, `breaker_min_outcomes`, `soft_block_ratio`, `median_min_pages`, `host_text_history`); the tripped-host guard `not host.breaker_tripped` of `FetchRobots` (796, its guard 800), `QueueSitemaps` (977), `ReadRobotsBeforeSitemap` (998), `FetchSitemap` (1012) and `ReadLlmsTxt` (1242), so a tripped host gets no further discovery request (`FetchRobots` guidance 860 to 866) and a declared sitemap a retirement leaves unread is not reported; a redirect hop onto a tripped host, not requested, its robots.txt not read, the fetch an error `"redirect to a retired host"` (`fetch_resource`, `FetchRobots` guidance 836 to 840; a page's hop, `AttemptTier` guidance 1655 to 1663, retried under `HttpRetry` as the robots-disallowed hop is, so the page fails); `FetchRobots` its `retires_host` branch, the answer standing (`robots_refused`); `RetireHostOnLongCrawlDelay` (916); `FetchSitemap` its `retires_host` branch, the answer standing (`sitemap_unavailable`); `SelectBatch` (1410) its all-tripped branch (`skipped_blocked`, `UrlSkippedBlocked`); `SkipTrippedHost` (1478); `SkipTrippedHostAfterReady` (1552 to 1566: a row whose own readiness, `OpenHostForEntry` or `ReadRobotsForNewOrigin`, retires its host is `skipped_blocked` with a `UrlSkippedBlocked`, so the batch goes idle) and `SkipRobotsDisallowedOnNewHost`'s untripped-host guard (1547 to 1548); `AttemptTier` (1601, its untripped-host guard 1604) its `classify_block` (guidance 1616 to 1630: a 401 or 403 hard, every 429 hard, a main text under `soft_block_ratio` of the host's median soft once the host has a text baseline, a login wall soft; no challenge recogniser is specified, so none is recognised; a 429 past the Retry-After cap is blocked and a 503 past it fails) and the response's `main_text` (Facts); `RetireHostOnLongRetryAfter` (1775); `HttpRetry`'s untripped-host guard (1749); `StopWalkOnTrippedHost` (1855 to 1884: a walk on a tripped host that needs another request, a retry, an escalation or a hop its tripped host refused, `FetchAttempt.hop_refused` 516 to 517, stops, its row `skipped_blocked` with a `UrlSkippedBlocked` and its `page` event raised, `AnnouncePage`, `rovo.allium` 610 to 613); `SettleWalk`'s guard `not (walk.host.breaker_tripped and attempt.hop_refused)` (1823); `FeedBreaker` (1888) now fed a non-zero `main_text`; `BreakerTrips` (1953), its standard branch end to end and its owner-testing branch on unit inputs; `DisposeFetch` (1983) its `{hard, challenge}` branch (2016 to 2020: `blocked`, the host's `blocked` and `fetched`, `UrlBlocked`) and a soft verdict falling through to `PageFetched`; `ConvertFetched` (2091) raising `soft_block_suspected` from a run; the frontier edges `pending -> skipped_blocked`, `in_progress -> blocked`, `in_progress -> skipped_blocked`, and `blocked -> pending` and `skipped_blocked -> pending` (by `PrepareRun`'s retry of the rows the scope admits, 649); the `SiteExchange` guarantees `BreakerStopsTheRun` (2437: no request of any kind to a tripped host for the rest of the run) and `BrowserRendersContentNeverAnswersBlocks` (2422) as a standard run reaches it (a block never escalates). `rovo.allium`: `BlockedUrl` (152), `TallyBlockedUrl` (563), `TallySkippedUrl` (570) now raised by a run, `AnnounceTrip` (589), `RankAndWriteReport` (697) its `blocked` input end to end and the `partial` input of a blocked URL (`has_failures`), `HostReport` (116) its `blocked`, `block_rate` and `breaker_tripped`, `SyncExitCodes` (955) its 3, `ProgressOnRequest` (981) its `breaker_tripped` event. `mirror.allium`: `MovePage`'s guidance (688 to 704) and `StoreNewPage`'s (829 to 834): the version value is form-decoded (`+` a space, `%XX` decoded) before it is mapped and sanitised. |
| **Traversed, nothing new to do** | `PrepareRun` (649) re-pending `blocked` and `skipped_blocked` rows (`Frontier.retry_entries`, `crawl/model.py` 416 to 425), `HttpRetry` (1746) and `CountRetryAfter` (1790), which run before a verdict matters, `HttpRetry` now only on an untripped host (1749); `SettleWalk` (1820) for a blocked or soft attempt (`wants_escalation` is false for every verdict other than `none` in a standard run, since `protection_escalation` is off), and for an answer a walk already holds when its host trips (1823, guidance 1849 to 1852); `DryRun` (1367), whose listing keeps a retired host's rows and whose discovery the guards above stop for that host; `with_fetch_flags` and the `incomplete_flags` (`convert.allium` 364) making a soft page low confidence; `summarise` and the per-host rows (`_report.py` 513 to 516). |
| **Specified as unrecognised until owner testing** | The three challenge recognisers of `classify_block` (a challenge header or page, an access-denied reference, a bot cookie on a tiny body): the specification names no header, page marker, reference or cookie until they are specified (`AttemptTier` guidance 1622 to 1624, the maintainer's answer to Open points item 2), so none is recognised and such an answer falls to the later checks. |
| **Later slices'** | `Escalate` (1807), `RememberRenderTier` (1905), `render_reason_of` as a run raises it, `render_needed` from a run, the browser tier, `RefuseMissingEngine` and `rovo fetch` (T19). `BreakerEscalates` (1930), which needs `protection_escalation` and so an owner-testing run; `OwnerChallenge` and its rules; the stealth tier; any challenge recogniser; `SaveOwnership` (T20). |
| **Outside this slice; reaching one still stops the run** | Of the 17 raises at `663fb9a` (`ai_tmp/T18/notinthisslice-663fb9a.txt`), this slice removes ten: `RetireHostOnLongRetryAfter` (`run.py` 399, 843, 1892), `RetireHostOnLongCrawlDelay` (403), `SelectBatch` (1198), `classify_block` (1344, 1707, 1709), `DisposeFetch` (1486) and `BreakerTrips` (1900), and adds one, `NotInThisSlice(rule="BreakerEscalates")`, in `BreakerTrips`' place for a breaker that should act while `protection_escalation` holds and its tier is below the highest (owner testing only, T20). The other seven stay, by `rule=`, as many of each: `PrepareRun` (246), `Discover` (317), `EnqueuePageLinks` (709), `RefollowUnchangedLinks` (750), `AttemptTier` (1316), `StartRun` (1780) and `Escalate` (1897). |

### Facts a later reader would otherwise rediscover

- **`classify_block`, in the guidance's order** (`AttemptTier`, 1616 to 1630). It stays a
  pure function of the response and the host's median, as the specification calls it,
  in `run.py`. A 401 or 403 is `hard`; a 429 is `hard`; on a 200 HTML answer, once the
  host has a text baseline, a `main_text` under `soft_block_ratio` times the median is
  `soft`; a login wall is `soft`; anything else is `none`. The signature is a
  human-readable reason, empty for `none`: `status_text` for a status verdict
  (`"403 Forbidden"`, `"429 Too Many Requests"`), `"login wall"`, and a text-ratio
  sentence naming the two lengths. No challenge recogniser is specified (1622 to 1624,
  Open points item 2, ANSWERED), so none produces anything.
- **Every 429 is `hard`** (1625 to 1630, Open points item 4, ANSWERED). `classify_block`
  cannot see the try, so every 429 is classified `hard`; only the standing attempt's
  verdict is disposed of and fed, and a retryable attempt never reaches `Escalate` or
  `SettleWalk` (both require `not attempt.retryable`), so the hard verdict of a 429 that
  is retried has no effect: a 429 blocks once `HttpRetry`'s retries leave it standing.
  `retryable` and `retires_host` do not read the verdict.
- **A retiring answer becomes.** `RetireHostOnLongRetryAfter` settles the walk with the
  answer standing; `FeedBreaker` does nothing (the breaker is already tripped); then
  `DisposeFetch` runs: a 429 past the cap is `hard`, so its row is `blocked` with a
  `UrlBlocked` (status 429), and a 503 past the cap is not ok, so its row is `failed`
  with `"503 Service Unavailable"`. A robots.txt try past the cap trips the breaker and
  the answer stands: a 429 or 5xx is `robots_refused`, a disallow-all origin and a
  discovery problem. A declared sitemap past the cap trips the breaker and stands as
  `sitemap_unavailable`; any other declared sitemap of that host is then not read and
  not reported (`FetchRobots` guidance 864 to 866), the retirement (`BreakerTripped`)
  covering it. A speculative probe past the cap still only pauses the host (T13,
  unchanged).
- **No request of any kind to a tripped host** (Open points item 1, ANSWERED;
  `BreakerStopsTheRun`, 2437). `FetchRobots`, `QueueSitemaps`,
  `ReadRobotsBeforeSitemap`, `FetchSitemap` and `ReadLlmsTxt` each require
  `not host.breaker_tripped` (`FetchEntry`'s form, 1572), so once a host is retired, by
  a long Crawl-delay or Retry-After on robots.txt or by its block rate, none of its
  robots.txt, sitemaps or `llms.txt` is requested; `DryRun` (1367) still lists its rows.
  A redirect hop onto a tripped host, from robots.txt, a sitemap, `llms.txt` or a page,
  is not requested and its robots.txt is not read: the fetch is the error answer
  `"redirect to a retired host"` (836 to 840, 1655 to 1663), which `HttpRetry` retries as
  it does the robots-disallowed hop's, so a page fails with it (`DisposeFetch`); no
  `RedirectStop` value is added. The T18-2 answers (`7d01367`) close the two ways a host
  trips under a row being handled: a row whose own readiness retires its host is
  `skipped_blocked` (`SkipTrippedHostAfterReady`, 1552 to 1566), and a walk whose own
  host trips mid-walk (its hop's robots.txt retires it) makes no further request:
  `AttemptTier`, `HttpRetry` and `Escalate` require an untripped host (1604, 1749,
  1810), a walk that needs another request stops with its row `skipped_blocked`
  (`StopWalkOnTrippedHost`, 1855 to 1884), and an answer it already holds settles and is
  disposed of as usual (`SettleWalk`, 1823, guidance 1849 to 1852). A page event means a
  fetch settled (`rovo.allium` `AnnouncePage`, 610 to 613): a stopped walk raises one, a
  row skipped without a fetch none. A hop onto another, tripped host, from a walk whose
  host stays untripped, is still the retried error answer above.
- **The login wall.** The password-form test T12 wrote (`_has_password_input`,
  `run.py` 1713; `tests/test_regressions.py::test_a_password_input_is_a_login_wall_however_quoted`)
  is the login wall, on an ok HTML answer, under every profile: `classify_block` takes no
  profile (`convert.allium` 379 names the generic profile's `password-form login wall`;
  the other catalogue profiles name none).
- **`main_text`.** `SiteResponse.main_text` is `fetch_or_render`'s "extracted text
  length". `attempt_tier` sets it, on an ok HTML http answer, before `classify_block`,
  to the length of the visible text of the profile's content selection, else of the
  whole body (one public function in `src/rovo/_convert/fidelity.py` beside `extract`,
  sharing its selection table), never running the fallback extractor, whose cost per
  page is not worth a heuristic; the fetchers do not change. A non-HTML or failed
  answer keeps 0. `FeedBreaker` then fills `recent_text_lengths` (`host_text_history`
  long) and a host has a baseline after `median_min_pages` unblocked pages with text.
- **The version value, form-decoded** (Open points item 3, ANSWERED; `mirror.allium`
  688 to 704 and 829 to 834). The raw `version_param` value is decoded as
  `application/x-www-form-urlencoded` (`+` is a space, `%XX` decoded) before it is mapped
  through `version_map` or sanitised, so `?view=a+b` is `a b` and labelled `a-b`, and a
  `version_map` raw value holding a space matches it. `version_label` reads the value
  through `parse_qsl`, which already decodes so; the code's two citations move to
  `mirror.allium` 688 to 704 and 829 to 834.
- **The breaker in a standard run.** `protection_escalation` is off
  (`StandardRunsStayPolite`), so the first breach trips it with no pause and no climb
  (`BreakerTrips` guidance): once `min(breaker_window, breaker_min_outcomes)` walks have
  settled with more than `block_rate_threshold` of them hard, challenge or failed
  outright, the breaker trips, every pending row of the host that the run may sweep
  becomes `skipped_blocked` with a `UrlSkippedBlocked` (`BreakerTrips`, 1963 to 1967:
  in a standard run every pending row of the host when the run is not targeted, and in
  a targeted run only its targets, `not run.targeted or e.identity in run.targets`;
  every other pending row of the host stays `pending`, absent from `skipped_urls`), and
  `BreakerTripped` is raised. Rows of a batch already
  `in_progress` but not yet started meet `SkipTrippedHost` when their turn comes:
  batches run one row at a time (`crawl.allium`'s third open question, interim
  unchanged), so a row starts when it is handled, and walks already in flight are the
  one being handled. A row a retirement leaves pending is set aside by `SelectBatch`
  and skipped only when no other row is open. A tripped host stays tripped for the run.
- **Events and the report.** `UrlBlocked` and `BreakerTripped` join `crawl/model.py`
  beside `UrlSkippedBlocked`, and `CrawlResult` returns them (`blocked`, `skipped`,
  `tripped`), which `_commands.sync` tallies after the run as it tallies `failed`
  (`TallyBlockedUrl`, `TallySkippedUrl`, `AnnounceTrip`'s `report.breaker_tripped`).
  `AnnounceTrip`'s `breaker_tripped` progress event is printed live, through a sink
  passed to `drive_run` as `on_backoff` is. The report's `blocked_urls`, `skipped_urls`,
  `breaker_tripped` and per-host rows are already written by `_report.py`; a tripped
  host ranks `blocked`, exit 3, above a blocked URL's `partial`.
- **Exit 3 for a retired host: ANSWERED-BY-SPEC.** `RankAndWriteReport` (`rovo.allium`
  706) ranks `run.has_tripped_host` as `blocked`, `SyncExitCodes` (955 to 965) says 3
  when a host's breaker tripped, and `RetireHostOnLongCrawlDelay`'s guidance (933 to
  935) says the run's report and exit follow `BreakerTripped`. A retirement trips the
  breaker, so it exits 3. The carried T16 item is closed by the specification's text.
- **The obligation source.** `just plan-spec <module>` over `docs/specs/<module>.allium`
  at `663fb9a`, written to `ai_tmp/T18/plan-spec-<module>.txt` (its echo line to
  `ai_tmp/T18/plan-spec-<module>.err`): crawl 382, rovo 169, mirror 201, convert 47
  obligations. The obligations with no test named after them at `663fb9a` are in
  `ai_tmp/T18/uncovered-<module>.txt` (crawl 118, rovo 35, mirror 14, convert 0, by
  `ai_tmp/T18/uncovered.py`); the owned set of step 3 is `ai_tmp/T18/owned.json` (40, by
  `ai_tmp/T18/owned.py`, which checks each id is in the plan and uncovered); the
  `NotInThisSlice` raises at `663fb9a` are in
  `ai_tmp/T18/notinthisslice-663fb9a.txt`. Re-derived at `86e2ec5`
  (`ai_tmp/T18/spec-answers/after2/<module>.json`): the same ids and descriptions in
  every module; 26 `crawl` obligations of the five guarded discovery rules
  (`FetchRobots`, `QueueSitemaps`, `ReadRobotsBeforeSitemap`, `FetchSitemap`,
  `ReadLlmsTxt`, success and failure) changed only in their read dependencies, which now
  include `Host`, and each rule's `rule-failure.<Rule>.2` (its `exists host` clause) now
  also covers a tripped host. Re-derived at `7d01367`
  (`ai_tmp/T18/spec-answers-2/after2/<module>.json`, confirmed by
  `ai_tmp/T18/propagate-3/plan-<module>.json`): `crawl` 391, the nine added obligations
  of step 3 and none removed or renumbered; `entity-fields.FetchAttempt` lists
  `hop_refused`; the `SkipRobotsDisallowedOnNewHost` obligations read `Host`; the
  folded guards widen `rule-failure.AttemptTier.2`, `rule-failure.HttpRetry.2`,
  `rule-failure.Escalate.1` and `rule-failure.SettleWalk.1` without an id change;
  `rovo`, `mirror` and `convert` unchanged (169, 201, 47). The copies are scratch,
  regenerated by step 0.

## Goal

From a clean checkout, against served fixture sites, `rovo sync` classifies a 401, 403
or 429 page as blocked and reports it in `blocked_urls` instead of stopping; a host whose
blocks breach the threshold trips its breaker, its remaining rows are skipped and
listed in `skipped_urls`, `--json` prints a `breaker_tripped` event, and the sync exits 3
with `exit_code: "blocked"`; a Crawl-delay or a Retry-After past `retry_after_cap` on
robots.txt, a declared sitemap or a page retires the host the same way, exit 3; a tripped
host gets no further request of any kind, discovery and redirect hops included; a page
whose main text falls under the host's baseline, or a login wall, is converted with
`soft_block_suspected`; a version label is form-decoded. Every owned obligation listed under Steps has a test named
after its id, red before the code; every re-propagated test is re-hashed with its
ledger note; no test this slice adds or edits sleeps for real; the adversarial review
has run with every valid finding fixed or handed back; `just check` is green; the
Allium loop's witness record says `PASS`.

## Non-goals

- No challenge recogniser (a challenge header or page, an access-denied reference, a
  bot cookie on a tiny body): the specification names none until owner testing (Open
  points item 2, ANSWERED). `BlockKind.challenge` is reached on constructed verdicts
  only.
- No `BreakerEscalates`, owner testing, interactive challenge or stealth tier (T20); no
  browser tier, `Escalate`, `render_needed` from a run or `rovo fetch` (T19).
- No harness change: `tests/e2e/conftest.py` is read, not changed.
- No new `rovo.toml` key and no new dependency. No change to the public API: `__all__`
  stays `["__version__"]`, so `docs/reference/api.md` does not move. No new package
  module, so `scripts/wheel_smoke.py` does not change. No decision record changes.
- No specification change: `docs/specs/` is read, not edited. A specification gap found
  while planning, implementing, in weed or in review is never resolved in code or in the
  specification: it joins the one batched needs-user question (Open points) and the
  ledger's `open_questions`.
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `src/rovo/_crawl/run.py` | shared, own lines | `classify_block` (Facts); `attempt_tier` setting `main_text` and dropping its 429 raise; `fetch_robots` and `fetch_sitemap` tripping the breaker on `retires_host` with the answer standing; the Crawl-delay retirement after `adopt_robots_rules`; `_settle` running `RetireHostOnLongRetryAfter` and `BreakerTrips` (the `BreakerEscalates` guard in its place for the owner branch); `select_batch`'s all-tripped branch; `SkipTrippedHost` in `_handle_entry`; `dispose_fetch`'s `{hard, challenge}` branch; `CrawlResult.blocked`, `.skipped` and `.tripped`; the trip sink on `drive_run` (`on_trip`); the tripped-host guard of `fetch_robots`, `queue_sitemaps`, the sitemap robots read, `fetch_sitemap` and `read_llms_txt`; ten `NotInThisSlice` raises removed; the docstrings that name the breaker slice; at `7d01367`: `skip_tripped_host_after_ready` (`SkipTrippedHostAfterReady`) in `_entry_ready` after the readiness rules, the untripped-host guard of `skip_robots_disallowed_on_new_host`, `attempt_tier` and `http_retry`, `stop_walk_on_tripped_host` (`StopWalkOnTrippedHost`) in `_settle` before `HttpRetry`, `settle_walk`'s `not (tripped and hop_refused)` guard |
| `src/rovo/_crawl/model.py` | shared, own lines | the `UrlBlocked` and `BreakerTripped` triggers; `UrlSkippedBlocked`'s docstring; `FetchAttempt.hop_refused` and the `RETIRED_HOP` error text it compares, moved here from `pace.py` (`7d01367`); nothing else unless step 4 shows a field missing |
| `src/rovo/_crawl/pace.py` | shared, own lines | the redirect hop onto a tripped host (`follow` and `fetch_resource`): not requested, its robots.txt not read, the error answer `"redirect to a retired host"` beside `DISALLOWED_HOP` (`RETIRED_HOP`, re-exported from `model.py` at `7d01367`); the docstrings that call the retirement a later slice's |
| `src/rovo/_mirror/urls.py` | shared, own lines | `version_label` and `_path_label`: the form-decoded value (Facts) and their citations, `mirror.allium` 688 to 704 and 829 to 834 |
| `src/rovo/_convert/fidelity.py` | shared, own lines | the public main-text length of the profile's selection (Facts, `main_text`) |
| `src/rovo/_report.py` | shared, own lines | `tally_blocked_url` (`TallyBlockedUrl`) and `announce_trip` (`AnnounceTrip`: `report.breaker_tripped` and the progress event) |
| `src/rovo/_commands.py` | shared, own lines | `sync` tallies `result.blocked`, `.skipped` and `.tripped` and passes the trip sink |
| `tests/test_blocks.py` | new | the `crawl` obligations of step 3 (the nine of `7d01367` included) and the guarantees; no e2e module is named `test_blocks.py` |
| `tests/test_report.py` | shared, own lines | the `rovo` obligations of step 3; exit 3 over a blocked URL's 1 |
| `tests/test_commands.py` | shared, own lines | a sync whose host trips exits 3 with the report written; the `--json` `breaker_tripped` line |
| `tests/test_slice_boundaries.py` | shared, own lines (re-propagated) | `test_a_later_slices_answer_stops_the_run` loses its three cases (T09, T12; the test goes when no case is left), `test_a_429_that_survives_its_retries_stops_at_classify_block` (T12), `test_a_crawl_delay_past_the_cap_stops_at_retire_host_on_long_crawl_delay` (T12), `test_a_breaker_breach_stops_the_run` (T12), `test_a_declared_sitemap_past_the_cap_stops_at_retire_host` (T13) and the tripped half of `test_a_tripped_host_and_a_browser_attempt_stop` (T12) become their behaviour, renamed; `test_classify_block_gives_none_otherwise` (T09) keeps its `none` half and its 403 half asserts `hard`; each with a ledger note naming its origin slice and its old name |
| `tests/test_regressions.py` | shared, own lines (re-propagated) | `test_a_password_input_is_a_login_wall_however_quoted` (T12) asserts `soft` with the login-wall signature; `test_a_saturated_retry_after_retires_the_host`, `test_a_huge_crawl_delay_retires_the_host_instead_of_overflowing` and `test_a_crawl_delay_is_compared_with_the_cap_as_written` (T12) assert the trip and exit 3 instead of the raise; `test_a_stopped_finalisation_persists_no_done_row` (T09) stops at an SPA shell's escalation instead of a login wall; ledger notes |
| `tests/test_pace.py` | shared, own lines (re-propagated) | `test_a_robots_retry_after_past_the_cap_stops_the_run` (T12) becomes the retirement: one robots.txt request, `robots_refused`, the breaker tripped; a page's redirect hop onto a tripped host (beside `test_RedirectsFollowedOnlyInScope_a_stopped_hop_is_never_requested`, T15) and a robots.txt hop onto one are never requested and fail with `"redirect to a retired host"`; ledger note |
| `tests/test_crawl.py` | shared, own lines (re-propagated) | the tripped-host case of `test_rule_failure_FetchRobots_2` (T12) and of `test_rule_failure_QueueSitemaps_2`, `test_rule_failure_ReadRobotsBeforeSitemap_2`, `test_rule_failure_FetchSitemap_2` and `test_rule_failure_ReadLlmsTxt_2` (T13), each asserting no request; any earlier test the red run shows red because a page now has a `main_text` or a verdict; at `7d01367`, the tripped-host halves of `test_rule_failure_AttemptTier_2` and `test_rule_failure_SettleWalk_1` (T09) and `test_rule_failure_HttpRetry_2` (T12), and `hop_refused` in `test_entity_fields_FetchAttempt` (T12); each with a ledger note naming its slice |
| `tests/test_version_label.py` | shared, own lines (re-propagated, T17) | a `+` in the version value is a space: mapped through a `version_map` raw value holding a space, and sanitised to `-` when unmapped; ledger note |
| `tests/fakes.py` | shared, own lines | only a fake the red run shows red because a page now has a `main_text` or a verdict, with a ledger note naming its slice |
| `tests/test_blocks_regressions.py` | new | one test per divergence weed or the adversarial review finds; hash-pinned in this slice's ledger |
| `tests/e2e/test_blocks_sync.py` | new | the end-to-end scenarios (Acceptance criteria), the two of `7d01367` serving both fixture sites as two origins of one host and importing `set_key` from `tests/test_commands.py`; no unit test is named `test_blocks_sync.py` |
| `tests/fixtures/sites/blocks/` | new | `robots.txt` (`User-agent: *`, no Crawl-delay, no `Sitemap:`), `guide/start.html` linking `guide/p01.html` to `guide/p12.html`, and the twelve pages; two-space indentation per `.editorconfig` |
| `tests/fixtures/sites/soft/` | new | `robots.txt` as above, `guide/start.html` linking five prose pages, then `guide/thin.html` (a page whose main text is under `soft_block_ratio` of the others') and `guide/login.html` (a password form) |
| `docs/reference/cli.md` | shared, own lines | `rovo sync`: blocked pages, every 429 that outlives its retries blocked, the breaker, host retirement (no further request of any kind to the host, discovery and redirect hops included) and the `breaker_tripped` event; at `7d01367`, a row whose own robots.txt read retires its host is skipped, and a page whose host trips mid-walk is skipped rather than retried while an answer already held is kept; the later-slice sentence (302 to 308) keeps only the browser tier and owner testing; the exit-code table's 1 drops "stopped at a branch a later slice implements" only if no branch is left that reaches it, and its 3 drops "(reached by a later slice)" |
| `docs/reference/mirror.md` | shared, own lines | the `crawl-report.json` section: `blocked_urls`, `skipped_urls`, `breaker_tripped` and the per-host rows; the page files' `soft_block_suspected` raised by a run; the version label's form decoding (202 to 203) |
| `docs/project/purpose-and-scope.md` | shared, own lines | lines 28 to 29: blocks no longer stop the sync |
| `docs/reference/testing.md`, `docs/project/repository-map.md` | shared, own lines | `tests/e2e/test_blocks_sync.py`, the two fixture sites, `tests/test_blocks.py`, `tests/test_blocks_regressions.py` |
| `docs/project/terminology.md` | shared, own lines | only if step 6's search shows "block verdict", "retired host" or "skipped" missing or wrong |
| `README.md`, `AGENTS.md` | shared, own lines | only the sentences step 6's search shows false; `AGENTS.md`'s required phrases stay in always-visible text |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` Added entry: blocks, the breaker and host retirement with no further request to the host (a page or row on a host retired under it skipped); the version label's form decoding |
| `tickets/README.md`, `tickets/T18-blocks-breaker.md` | ticket | index row, graph, slice bullet, this ticket |
| `.allium-loop/T18-blocks-breaker.json`, `.allium-loop/T18-blocks-breaker.witness.json` | gitignored | the loop ledger and the witness record; never committed |

`pyproject.toml`, `uv.lock`, `pytest.ini`, `.coveragerc`, `ruff.toml`, `mypy.ini`,
`Justfile`, `scripts/wheel_smoke.py`, `src/rovo/__init__.py`, `src/rovo/cli.py`,
`src/rovo/_exit.py`, `src/rovo/_config.py`, `src/rovo/_unfinished.py`,
`src/rovo/_crawl/fetch.py`, `src/rovo/_crawl/sitemaps.py`, `src/rovo/_mirror/` but `urls.py`,
`src/rovo/_convert/` but `fidelity.py`, `tests/e2e/conftest.py`,
`tests/test_import_direction.py`, `docs/reference/quality-gates.md`,
`docs/manifest.yml`, `docs/decisions/` and `docs/specs/` are read, not changed. A file
not in this table that turns out to need a change is added to the table in the same
change with its reason, or handed back if it is a decision record, a specification or a
dependency.

## Steps

0. `just check` baseline on the untouched worktree at `663fb9a` plus this ticket, last
   line quoted, and `( set -o pipefail; { time just py-test tests/e2e -ra; } 2>&1 | tail -6 )`
   with its wall time. Scratch output goes in `ai_tmp/T18/`. Write `just plan-spec
   <module>` for each of `crawl`, `rovo`, `mirror` and `convert` to
   `ai_tmp/T18/plan-spec-<module>.txt`; run `ai_tmp/T18/uncovered.py` and
   `ai_tmp/T18/owned.py`, and confirm the 40 ids. While the worktree is at `663fb9a`,
   write `rg -n 'NotInThisSlice\(' src > ai_tmp/T18/notinthisslice-663fb9a.txt`. Create
   the ledger `.allium-loop/T18-blocks-breaker.json` (propagate's first tick creates it)
   against `allium-skill-reference/allium/schemas/ledger.schema.json`, shaped like T17's:
   `goal` `"T18-blocks-breaker"`, `mode` `"spec-first"`, `specification_base` `7d01367`,
   `obligation_source` the four files and their re-derivations at `86e2ec5` and
   `7d01367`, and
   `open_questions` holding the six specification open questions verbatim (the third
   `crawl.allium` one, 2449, marked "on T18's path", with this slice's interim: batches
   run one row at a time, which decides when a batch's unstarted rows meet
   `SkipTrippedHost`), the T18 batched question's four items (Open points) marked
   ANSWERED at `86e2ec5`, the T18-2 batched question's two items marked ANSWERED at
   `7d01367` (its residue OPEN, Open points), and the carried T16 item "whether a host
   retirement ranks exit 3 or 1" marked ANSWERED-BY-SPEC (Facts). Read `.agents/skills/propagate/SKILL.md`,
   `.agents/skills/weed/SKILL.md`, `.agents/skills/witness/SKILL.md` and
   `.agents/skills/python-change/SKILL.md` before step 3.

1. **Verdicts and the breaker.** In `run.py`, per the Context table and Facts:
   `classify_block`; `main_text` in `attempt_tier` (with its function in
   `fidelity.py`); the 429 raise in `attempt_tier` goes; `_settle` runs
   `RetireHostOnLongRetryAfter` (the breaker tripped, the walk settled with the attempt
   standing, its tier in `tiers_used`), then `FeedBreaker`, then `BreakerTrips` when the
   breaker should act and `BreakerTrips`' guard holds, else the `BreakerEscalates`
   guard; `select_batch`'s all-tripped branch; `SkipTrippedHost` when a row of a tripped
   host comes to be handled; `dispose_fetch`'s `{hard, challenge}` branch in its
   specified place (after `absent`, before `redirected_out`). Every threshold, window,
   ratio and cap comes from `CONFIG` or the run's policy, never a literal.

2. **Retirement and the report.** `fetch_robots` and a declared sitemap's
   `fetch_sitemap` trip the breaker on a Retry-After past the cap, the answer standing
   (Facts); the Crawl-delay retirement trips it when Crawl-delay is honoured and
   `robots_crawl_delay_exceeds` holds, any origin of the host retiring the whole host.
   The five discovery rules take no step for a tripped host, and a redirect hop onto one
   is not made: `fetch_resource` and `follow` answer the error
   `"redirect to a retired host"` instead (Facts). `_path_label` form-decodes the version
   value and its citations move (Facts).
   `UrlBlocked` and `BreakerTripped` in `crawl/model.py`, returned through `CrawlResult`;
   `tally_blocked_url` and `announce_trip` in `_report.py`; `_commands.sync` tallies them
   and prints the trip event live under `--json`. Each function returns `None`, `False`
   or an empty result when its guards do not hold.

3. **Tests first, from the obligations** (the `propagate` skill, spec-first). Write a
   failing test for each owned obligation below into the test file named, named
   `test_<obligation id with dots and hyphens as underscores>`, its docstring quoting the
   obligation's description from the plan-spec file. Each `rule_failure` test makes
   exactly one `requires` clause false. Generated tests satisfy EditorConfig
   (indentation in 4-space multiples in `*.py`, string literals included), ruff and
   mypy, since the gate stages them. Run `just py-test` and record the red run in
   `ai_tmp/T18/red.txt`, its summary line under `last_results.propagate` in the ledger.
   Record each generated, re-propagated or extended test file's SHA-256 under
   `generated_test_hashes` (`tests/e2e/test_blocks_sync.py` and
   `tests/test_blocks_regressions.py` included), and the reconciliation line
   (`N obligations, M covered, K uncovered`) over the owned set. A test changed after the
   red run is re-recorded: a new hash, `tick` incremented, a ledger note naming the test
   and why; never silently. An obligation a test cannot reach without a later slice's
   behaviour is not owned: move it to the hand-back notes with its reason rather than
   writing a vacuous test.

   Owned obligations, new in this slice (ids as `just plan-spec <module>` emits them at
   `663fb9a`, unchanged at `86e2ec5`, and the nine `7d01367` added; 49):

   - **`crawl`** (43), in `tests/test_blocks.py`: `value-equality.BlockVerdict`,
     `entity-fields.BlockVerdict`, `enum-comparable.BlockKind`,
     `projection.Run.tripped_hosts`, `derived.Run.has_tripped_host`,
     `transition-edge.FrontierEntry.pending.skipped_blocked`,
     `transition-edge.FrontierEntry.in_progress.blocked`,
     `transition-edge.FrontierEntry.in_progress.skipped_blocked`,
     `transition-edge.FrontierEntry.blocked.pending`,
     `transition-edge.FrontierEntry.skipped_blocked.pending`,
     `derived.Host.has_text_baseline`, `derived.Host.breaker_tripped`,
     `transition-edge.Breaker.watching.tripped`, `transition-rejected.Breaker.status`,
     `transition-terminal.Breaker.status`, `derived.Breaker.should_act`,
     `projection.LadderWalk.soft_suspect`, `config-default.soft_block_ratio`,
     `config-default.median_min_pages`, `rule-success.RetireHostOnLongCrawlDelay`,
     `rule-failure.RetireHostOnLongCrawlDelay.1`, `.2`, `.3`,
     `rule-success.SkipTrippedHost`, `rule-failure.SkipTrippedHost.1`, `.2`,
     `rule-success.RetireHostOnLongRetryAfter`, `rule-failure.RetireHostOnLongRetryAfter.1`,
     `.2`, `when-set.RetireHostOnLongRetryAfter.LadderWalk.standing`,
     `rule-success.BreakerTrips`, `rule-failure.BreakerTrips.1`, `.2`, `.3` (the
     owner-testing branch of `BreakerTrips` and `.3`'s `protection_escalation` on a
     constructed run and policy; `.3` also asserts `NotInThisSlice("BreakerEscalates")`
     for that state through `_settle`, as `tests/test_slice_boundaries.py` asserts the
     other guards, so the one added raise is covered and deliberate); and, added at
     `7d01367` (the T18-2 answers), `derived.FetchAttempt.hop_refused`,
     `rule-success.SkipTrippedHostAfterReady`,
     `rule-failure.SkipTrippedHostAfterReady.1`, `.2`,
     `rule-failure.SkipRobotsDisallowedOnNewHost.3`,
     `rule-success.StopWalkOnTrippedHost` and
     `rule-failure.StopWalkOnTrippedHost.1`, `.2`, `.3` (the escalation disjunct of
     `.3`'s clause on constructed inputs only: a refused hop carries an error, never a
     render reason, and a standard run's verdicts want no escalation).
   - **`rovo`** (6), in `tests/test_report.py`: `value-equality.BlockedUrl`,
     `entity-fields.BlockedUrl`, `rule-success.TallyBlockedUrl`,
     `rule-failure.TallyBlockedUrl.1`, `rule-success.AnnounceTrip`,
     `rule-failure.AnnounceTrip.1`.
   - **`mirror`** and **`convert`**: none new.

   Re-propagated at `7d01367` (T18-2), in `tests/test_crawl.py`, each with a ledger note
   naming its origin slice: `test_rule_failure_AttemptTier_2` and
   `test_rule_failure_HttpRetry_2` gain the tripped-host half of their folded guard (no
   request, no attempt, no pause); `test_rule_failure_SettleWalk_1` gains a refused hop
   on the walk's own tripped host (not settled) beside a held answer that still settles;
   `test_entity_fields_FetchAttempt` lists `hop_refused`. The
   `SkipRobotsDisallowedOnNewHost` success, `.1` and `.2` tests pass unedited on an
   untripped host. `rule-failure.Escalate.1` has no test and no `Escalate` here (T19):
   its tripped-host half is shown by `StopWalkOnTrippedHost`'s escalation disjunct. In
   `tests/test_blocks.py`,
   `test_a_crawl_delay_on_a_second_origin_retires_the_whole_host` pins the row
   `skipped_blocked`.

   Re-propagated, not new (each re-hashed in this slice's ledger with a note naming its
   origin slice; T09's to T17's ledgers are never edited): the tests the Files touched
   table names in `tests/test_slice_boundaries.py`, `tests/test_regressions.py` and
   `tests/test_pace.py`, each now asserting the behaviour where it asserted the raise,
   asserting no less than before (the requests made, the files left); the five
   discovery rules' `rule-failure.<Rule>.2` tests in `tests/test_crawl.py` (T12's
   `FetchRobots`, T13's `QueueSitemaps`, `ReadRobotsBeforeSitemap`, `FetchSitemap` and
   `ReadLlmsTxt`), each gaining the tripped-host case of its guard with no request made,
   their `rule-success` tests passing unedited on an untripped host; the redirect hop onto
   a tripped host in `tests/test_pace.py` (a page's hop, retried and failed with
   `"redirect to a retired host"`, and a robots.txt hop, never requested); the
   form-decoded version value in `tests/test_version_label.py` (T17); every other
   earlier test the red run shows red because a page now has a verdict or a `main_text`,
   each with only that expectation moved. Claim an earlier test "passes unedited" only
   where it does; the hand-back notes list every earlier test this slice edited.

   Guarantees and black boxes (no obligation id; hand-written), in `tests/test_blocks.py`
   unless named: `classify_block` (each check alone, the order when two hold, the
   signature text, a soft ratio never without a baseline, a 429 `hard` at every try);
   the main-text length (selection, whole body, non-HTML 0, no fallback extractor);
   `FeedBreaker` filling `recent_text_lengths` up to `host_text_history`;
   `DisposeFetch`'s branch order (an absent page with a 403-like body is absent; a
   challenge verdict on a constructed attempt is blocked); a soft verdict converted with
   `soft_block_suspected` and low confidence; each retirement path (robots.txt
   Retry-After, Crawl-delay on either origin of a host, `honor_crawl_delay` off leaving
   the host alone, a declared sitemap, a page 429 blocked, a page 503 failed, a
   speculative probe only pausing); `BreakerStopsTheRun` (no request of any kind to the
   host after the trip, robots.txt, sitemaps, `llms.txt` and redirect hops included, and
   every blocked and skipped URL in the report; a declared sitemap left unread by a
   retirement has no `sitemap_unavailable` row); `BlockedWithinFetched` after a
   run; `BrowserRendersContentNeverAnswersBlocks` (a blocked attempt never escalates in a
   standard run, under `render_mode = auto` too); exit 3 over 1, and 3 under a skipped
   target (`tests/test_report.py`).

   Four more guarantees, in `tests/test_blocks.py` (from the T18-1 review):
   - **The targeted sweep** (the targeted half of `BreakerTrips`, 1963 to 1967): a
     targeted run on a host with one target and one other pending row; when the
     target's host trips, the target is `skipped_blocked` with a `UrlSkippedBlocked`,
     and the other row stays `pending` in the saved frontier, absent from
     `skipped_urls`, with no `UrlSkippedBlocked` raised for it. The sweep filters by
     `not run.targeted or e.identity in run.targets`.
   - **Host isolation** (`SelectBatch`'s `open_rows`, 1419, and its guidance, 1449 to
     1452; `BreakerTrips` sweeping `where host_name = host.name`): on `FakeFetcher`
     with two allowed hosts (precedent: `tests/test_crawl.py`'s
     `allowed_hosts=frozenset({HOST, "api.example"})`), host A's pages block until its
     breaker trips; every pending row of host B is fetched and written, host A's
     remaining rows are `skipped_blocked`, the two per-host rows carry independent
     `blocked`, `block_rate` and `breaker_tripped`, and the run exits 3. A unit test:
     the harness serves one origin per site and is not changed (Non-goals).
   - **Config, not literals** (step 1): `CONFIG` monkeypatched, with
     `dataclasses.replace`, in every module that imported it (`rovo._crawl.model` and
     `rovo._crawl.run`; precedent: `tests/e2e/test_discovery_sync.py`) to non-default
     `breaker_min_outcomes`, `block_rate_threshold`, `soft_block_ratio` and
     `median_min_pages`, chosen so the outcomes differ from the defaults'; the trip
     point and a soft verdict move to where the altered values put them; and one
     retirement case with a non-default `retry_after_cap` on the run's policy, where a
     value past the altered cap retires the host and the same value under it does not.
   - **A block keeps a mirrored page** (`DisposeFetch`'s `{hard, challenge}` branch,
     2016 to 2020): a run whose mirror holds a written page for the entry, whose fetch
     answers 403, leaves the page file's bytes, its manifest row, its validators
     (`etag`, `last_modified`) and its index membership unchanged, delivers no
     candidate and lists the URL in `blocked_urls`; the next sync, answered 200,
     refreshes it.

   Not owned, and why, for the hand-back notes: `rule-*.BreakerEscalates`,
   `config-default.breaker_pause`, `config-default.min_host_rate`,
   `invariant.BreakerNeverPassesHighestTier`, `entity-relationship.FetchAttempt.challenges`,
   every `OwnerChallenge` obligation, `enum-comparable.PolitenessControl`,
   `enum-comparable.StealthMode` and the owner-testing obligations (T20);
   `derived.FetchAttempt.wants_escalation`, `rule-*.Escalate`, `rule-*.RememberRenderTier`,
   `projection.LadderWalk.ok_http`, `derived.LadderWalk.render_needed`,
   `entity-optional.FetchAttempt.render_reason`, `enum-comparable.RenderReason`,
   `enum-comparable.RenderMode`, `entity-fields.TierHint`, the rendering config defaults,
   `invariant.LearnedTierIsNeverHttp` and `rule-*.RefuseMissingEngine`, `FetchOneUrl`,
   `RefuseMissingFetchTier`, `enum-comparable.Tier` (T19); the `SyncControl`,
   `MirrorCommands` and `MirrorContents` surface obligations (they list T19's and T20's
   operations); `enum-comparable.FrontierStatus`, `enum-comparable.RunKind`,
   `enum-comparable.RunMode`, `entity-relationship.Run.hosts`,
   `entity-relationship.Frontier.entries`, `when-presence.LadderWalk.standing`, the
   `LadderWalk` status edge and its rejected and terminal obligations,
   `entity-relationship.LadderWalk.attempts`, `surface-actor.SiteExchange`,
   `entity-fields.DocumentationSite`, `entity-fields.SyncRun`,
   `entity-relationship.Mirror.pages`, `entity-optional.Page.canonical_url`,
   `entity-optional.Page.frontmatter` and the `PageIntake` surface obligations
   (reachable since T09 to T16, assigned by no ticket: carried to the last slice's
   review, named in the ledger).

4. **Verdicts, breaker, retirement and report.** Steps 1 and 2. Unit cases on
   `FakeFetcher` and `ScriptedFetcher` with `FixedClock` or `SteppingTimer`.
   `just py-test tests/test_blocks.py tests/test_report.py tests/test_commands.py
   tests/test_slice_boundaries.py tests/test_regressions.py tests/test_pace.py
   tests/test_crawl.py`, then `just py-lint`, `just py-typecheck`, `just coverage` and
   `just wheel-smoke`, quoting its `api` line and the package-file count (unchanged
   from `663fb9a`).

5. **End to end.** The two fixture sites are committed under `tests/fixtures/sites/`
   and served with `serve_site("blocks")` and `serve_site("soft")`; the blocks, the
   long Retry-After and the long Crawl-delay are scripted with `always=` and `script=`
   (robots.txt bodies and headers built in the test from `CONFIG`, never a literal cap).
   Each page has a `<title>`, two-space indentation and a final newline; there is no
   `llms.txt` and no sitemap. The scenarios are the Acceptance criteria's; those that
   fetch run `rovo._commands.sync` in process over a real `HttpxFetcher` with a
   `SteppingTimer` or `FixedClock`, which never sleep, and read requests off the
   server's log; `rovo init` runs through `CliRunner`. `just py-test tests/e2e -ra`, its
   wall time quoted beside step 0's.

6. **Documents** (the `review-docs` skill). The pages of the Files touched table; find
   the sentences this slice makes false with
   `rg -n -i "block|breaker|trip|retire|skipped|login|soft|later slice|exit 1|exit 3|not yet" -g '*.md' -g '!tickets/**' -g '!allium-skill-reference/**' -g '!docs/specs/**' -g '!docs/decisions/**'`;
   `CHANGELOG.md` `Unreleased` gains one Added entry. Keep the required phrases of
   `AGENTS.md` in always-visible text. `just check-docs`, `just check-agents`, and
   `just lint`, whose hooks include markdownlint over this ticket.

7. **Witness** (the `weed` and `witness` skills). Run `weed` over `crawl` and `rovo`
   against the code, scoped to the owned and re-propagated obligations, the Realised
   rules of the Context table and the guarantees; record its verdict under
   `last_results.weed` and fix any code divergence, each with a regression test in
   `tests/test_blocks_regressions.py`. A divergence weed attributes to the
   specification is not fixed: it joins the one batched needs-user question. Then run
   `witness` non-interactively: it writes `.allium-loop/T18-blocks-breaker.witness.json`
   per `witness-result.schema.json`. The verdict must be `PASS`; a `FAIL` routes back
   per the skill, and the hand-back notes record each round. A batched question still
   OPEN does not block `PASS` unless it blocks an owned obligation; the T18 batched
   question is answered (`86e2ec5`), the T18-2 one too (`7d01367`) but for its residue,
   which blocks no owned obligation, and the witness escalates any new one that blocks.

8. **Adversarial review** (`tickets/CONVENTIONS.md` §14; checkpoint 1, after the
   witness's `PASS` and before the final commit; the breaker, the verdicts and the
   retirement are what T19's escalation and T20's owner testing build on). Brief: this
   ticket, `tickets/CONVENTIONS.md`, `git diff 663fb9a` plus the uncommitted changes, the
   ledger and the witness record (not the hand-back notes), and the questions: does any
   block, breach or retirement still stop the run, exit 1 where 3 is specified, or reach
   any request after the trip (a page, robots.txt, a sitemap, `llms.txt` or a redirect
   hop); is any threshold, window, ratio or cap a literal rather than `CONFIG` or the
   policy; is any `NotInThisSlice` removed whose branch is not realised, or any branch
   realised that the Context table keeps outside (a challenge recogniser,
   `BreakerEscalates`); is every acceptance
   criterion shown by a test that would fail if the claim were false; does any
   re-propagated test assert less than before; can any test sleep for real or hang on a
   non-advancing timer; does a verification command print a pass when it failed; is
   every gap in the batched question rather than resolved. Two lenses, conformance and
   breakage, written to `ai_tmp/review/T18-1/findings-conformance.md` and
   `ai_tmp/review/T18-1/findings-breakage.md` with
   `codex exec -m gpt-6-astra -s read-only -C <worktree> -o <file> "<brief>"`, run in
   the foreground and waited on until each findings file exists and is non-empty (an
   empty or missing file is no review), or
   `claude -p --model claude-opus-5-5 --permission-mode plan "<brief>" > <file>` when
   codex is not on `PATH`; triage verdicts in `ai_tmp/review/T18-1/verdicts.md`; valid
   fixes applied one at a time, within the Files touched table, each with a regression
   test in `tests/test_blocks_regressions.py` re-hashed in the ledger; a second round
   over the fix diff when a high-severity finding was valid, two rounds at most; a
   finding that adds complexity for an implausible input is weighed for proportionality
   and its verdict says so; anything still open goes into Open points. Then steps 4 and
   5's commands and `just check` rerun and quoted. The model call is the checkpoint's
   authorised network use.

9. Hand-back notes; `status: done`; `just check` ending with
   `All checks passed and the worktree is unchanged.`, `git status --short` empty after
   the commit. Commit on the branch.
   **Authorisation required**: pushing and opening the pull request.

## Acceptance criteria

The end-to-end scenarios live in `tests/e2e/test_blocks_sync.py`; each starts with
`rovo init <base>guide/start.html <tmp>/out`, and every count the assertions use is
derived from `CONFIG` (`breaker_window`, `breaker_min_outcomes`, `block_rate_threshold`,
`retry_after_cap`, `http_attempts`, `median_min_pages`, `soft_block_ratio`).

- **End to end, the breaker trips**
  (`test_blocks_trip_the_breaker_and_the_sync_exits_3`): on the `blocks` site,
  `p02.html`, `p04.html` and `p06.html` answer 403, 401 and 429 on every request
  (`always=`), enough that the share of blocked outcomes after
  `min(breaker_window, breaker_min_outcomes)` settled walks exceeds
  `block_rate_threshold` (the test asserts the committed site has more linked pages than
  that count). `start.html` is the first outcome, so under the default configuration
  the trip lands on `p09.html`'s walk and `p10.html` to `p12.html` are skipped (rows of
  that batch not yet started meet `SkipTrippedHost`); the test derives the skipped set
  from `CONFIG` and the link order. `rovo sync --json` exits 3 where at `86e2ec5` it stopped at
  `classify_block` and exited 1: `crawl-report.json` has `exit_code: "blocked"`,
  `breaker_tripped: true`, `blocked_urls` holding the three URLs with statuses 403, 401
  and 429, signature and tier `http`, `skipped_urls` holding every linked page not
  fetched before the trip, and the host's per-host row `breaker_tripped: true` with
  `blocked` and `block_rate` as counted; the 429 page was requested `http_attempts`
  times; the server's log holds no request for a skipped page; standard output holds one
  `breaker_tripped` event naming the host, before `done`; every page converted before
  the trip is written, and no page file exists for `p02.html`, `p04.html` or `p06.html`
  (a blocked answer delivers no candidate, `DisposeFetch` 2016 to 2020).
- **End to end, a long Crawl-delay retires the host**
  (`test_a_crawl_delay_past_the_cap_retires_the_host`): robots.txt declares a
  Crawl-delay of `retry_after_cap` plus one second. The sync exits 3 with
  `breaker_tripped: true`, the seed in `skipped_urls` and no page written, where at
  `86e2ec5` it stopped at `RetireHostOnLongCrawlDelay`; the server's log holds
  robots.txt alone: no sitemap, `llms.txt` or page is requested after the retirement.
- **End to end, a long Retry-After on robots.txt retires the host**
  (`test_a_robots_retry_after_past_the_cap_retires_the_host`): robots.txt answers 429
  with a Retry-After of `retry_after_cap` plus one second. The server's log holds
  robots.txt once and nothing else, the report holds a `robots_refused` discovery
  problem, the seed is in `skipped_urls`, and the sync exits 3.
- **End to end, a long Retry-After on a page**
  (`test_a_page_retry_after_past_the_cap_blocks_it_and_retires_the_host`): on the
  `blocks` site, `p01.html` answers 429 with a Retry-After past the cap. It is requested
  once, it is in `blocked_urls` with status 429, every other linked page is in
  `skipped_urls`, and the sync exits 3.
- **End to end, soft verdicts** (`test_a_thin_page_and_a_login_wall_are_soft_blocks`):
  on the `soft` site, `thin.html` is fetched after `median_min_pages` prose pages and its
  main text is under `soft_block_ratio` of their median; `login.html` holds a password
  form. The sync exits 0 (a soft verdict never counts against the host, and
  `fail_on_low_quality` is unset): both page files exist, their frontmatter's
  `quality_flags` holds `soft_block_suspected` and `low_confidence` is true; the prose
  pages carry no such flag; `blocked_urls` is empty and `breaker_tripped` false. The
  test asserts the committed site has at least `median_min_pages` prose pages before
  `thin.html` in `start.html`'s link order. (`fail_on_low_quality` over a low-confidence
  page is T17's scenario; a re-sync is not used here, since an unchanged page is not
  touched and the host's text baseline lasts one run.)
- **The review's four guarantees** (step 3, in `tests/test_blocks.py`): a trip in a
  targeted run sweeps only its targets and leaves the host's other pending rows
  `pending` and out of `skipped_urls`; a tripped host never stops a healthy host's
  rows; a non-default `CONFIG` or `retry_after_cap` moves the trip point, the soft
  verdict and the retirement with it; a 403 on a mirrored page leaves the page, its
  manifest row, its validators and its index membership unchanged.
- **End to end, a host tripped under a row being handled** (the T18-2 answers,
  `7d01367`; two `serve_site` servers are two origins of `127.0.0.1`):
  `test_a_hop_whose_robots_txt_retires_its_own_host_stops_the_walk`: `p01.html`
  redirects to the other origin, whose robots.txt has a Crawl-delay past the cap; the
  host is retired, `p01.html` is requested once (not `http_attempts` times) and is in
  `skipped_urls`, not `failed_urls`; the other origin's log holds robots.txt alone; the
  `page` events name `start.html` and `p01.html` only; the sync exits 3.
  `test_a_seed_whose_own_robots_txt_retires_the_host_is_skipped`: the other origin's
  start page is a second start URL; its robots.txt retires the host before its first
  page, so it is `skipped_blocked` unrequested, the batch goes idle and the next batch's
  links are skipped; `skipped_urls` holds it and every link, and only the first
  `start.html` raises a `page` event; the sync exits 3.
- **End to end, earlier scenarios**: every module under `tests/e2e/` but
  `test_blocks_sync.py` passes unedited, unless the ledger names an edit and why.
- Every owned obligation in step 3 has a test named after it, red before the code and
  green after (`ai_tmp/T18/red.txt`, `ai_tmp/T18/red-3.txt` for the nine of `7d01367`,
  and the final run); the reconciliation line shows
  zero uncovered; every re-propagated test is re-hashed in the ledger with its note;
  every obligation dropped from the owned list is in the hand-back notes with its reason.
- No test this slice adds or edits sleeps for real; the suite's one real wait is T12's
  installed-script Crawl-delay scenario (`tests/e2e/test_polite_sync.py`), kept by
  design: `rg -n 'time\.sleep\(' tests; test $? -eq 1`,
  `test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py`, and
  `rg -n 'subprocess' tests/e2e/test_blocks_sync.py; test $? -eq 1`.
- The `NotInThisSlice` raises in `src/` carry the `rule=` names of
  `ai_tmp/T18/notinthisslice-663fb9a.txt` less three `RetireHostOnLongRetryAfter`, one
  `RetireHostOnLongCrawlDelay`, one `SelectBatch`, three `classify_block`, one
  `DisposeFetch` and one `BreakerTrips`, plus one `BreakerEscalates`, as many of each
  (`ai_tmp/T18/rules-expected.txt` and `ai_tmp/T18/rules-after.txt`, written by the
  Verification block, do not differ).
- Every fixture page the end-to-end scenarios serve is committed under
  `tests/fixtures/sites/blocks/` or `tests/fixtures/sites/soft/`:
  `rg -n 'write_text' tests/e2e/test_blocks_sync.py` names no `.html` file.
- `.allium-loop/T18-blocks-breaker.witness.json` exists with `"verdict": "PASS"`, and
  the ledger validates against `ledger.schema.json` with the T18 batched question's four
  items ANSWERED at `86e2ec5`, the T18-2 question's two ANSWERED at `7d01367`, and the
  carried exit-3 item ANSWERED-BY-SPEC.
- `ai_tmp/review/T18-1/findings-conformance.md`, `findings-breakage.md` and
  `verdicts.md` exist and are non-empty; every valid finding is fixed with a test in
  `tests/test_blocks_regressions.py` or handed back.
- `just check-specs` and `just analyse-specs` pass with `docs/specs/` unchanged since
  `7d01367` (`git diff --stat 7d01367 -- docs/specs` empty).
- `import rovo` loads no module outside the standard library and `rovo`; `__all__` is
  `["__version__"]`; `just wheel-smoke` passes with the package-file count unchanged.
- `just coverage` stays at or above the floor of 95.
- `just check-docs` and `just check-agents` pass; `docs/reference/cli.md` describes
  blocked pages, the breaker, host retirement with no further request to the host, the
  `breaker_tripped` event and exit 3 as reached; no page says a block stops the sync;
  `docs/reference/mirror.md` says the version value is form-decoded.
- `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty after the commit.

## Verification

```sh
just plan-spec crawl > ai_tmp/T18/plan-spec-crawl.txt
just plan-spec rovo > ai_tmp/T18/plan-spec-rovo.txt
just plan-spec mirror > ai_tmp/T18/plan-spec-mirror.txt
just plan-spec convert > ai_tmp/T18/plan-spec-convert.txt
git diff --stat 7d01367 -- docs/specs
just py-test tests/test_blocks.py tests/test_report.py tests/test_commands.py tests/test_slice_boundaries.py tests/test_regressions.py tests/test_pace.py tests/test_crawl.py tests/test_version_label.py tests/test_blocks_regressions.py -ra
( set -o pipefail; { time just py-test tests/e2e -ra; } 2>&1 | tail -6 )
just py-lint
just py-typecheck
just coverage
just wheel-smoke
uv run --frozen python -I -c "import rovo, sys; print(sorted(m for m in sys.modules if not m.startswith(('rovo', '_')) and m not in sys.stdlib_module_names))"
{ rg -o 'rule="[^"]+"' -N --no-filename ai_tmp/T18/notinthisslice-663fb9a.txt | rg -v '"(RetireHostOnLongRetryAfter|RetireHostOnLongCrawlDelay|SelectBatch|classify_block|DisposeFetch|BreakerTrips)"'; echo 'rule="BreakerEscalates"'; } | sort > ai_tmp/T18/rules-expected.txt
rg -o 'rule="[^"]+"' -N --no-filename src | sort > ai_tmp/T18/rules-after.txt
diff ai_tmp/T18/rules-expected.txt ai_tmp/T18/rules-after.txt  # prints nothing
rg -n 'time\.sleep\(' tests; test $? -eq 1  # only "no match" passes
test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py
rg -n 'subprocess' tests/e2e/test_blocks_sync.py; test $? -eq 1  # only "no match" passes
test -s ai_tmp/review/T18-1/findings-conformance.md && test -s ai_tmp/review/T18-1/findings-breakage.md && test -s ai_tmp/review/T18-1/verdicts.md
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
after; `classify_block`, `main_text`, the breaker, the retirement paths and the report
wiring as built, and any departure from Facts and steps 1 and 2; the red run and the
reconciliation line; every re-propagated test, its origin slice, its old name and its
new hash; every obligation dropped from the owned list and why; the weed verdict and
the witness verdict, each round; the adversarial review per `tickets/CONVENTIONS.md`
§14's Record (harness and model, findings, verdicts with reasons, what was applied,
what was handed back, the rerun headed by its commit); the one batched needs-user
question with every gap found while planning, implementing, in weed or in review, and
the maintainer's answer if one arrived; the verification output, each headed by its
commit.

## Open points

- **The T18 batched needs-user question: ANSWERED** (found while planning; the
  maintainer's answers of 2026-11-05, `ai_tmp/T18/spec-answers/answers.md`, written into
  the specification at `86e2ec5`; copied into the ledger's `open_questions` as
  ANSWERED). A gap found later joins a new batched question, OPEN.
  1. **A retired host's remaining discovery: STOP ALL REQUESTS.** Once a host's breaker
     has tripped, by a retirement or by its block rate, `FetchRobots`, `QueueSitemaps`,
     `ReadRobotsBeforeSitemap`, `FetchSitemap` and `ReadLlmsTxt` require an untripped
     host (800, 981, 1002, 1016, 1246, `FetchEntry`'s form), so it gets no further
     discovery request (`FetchRobots` guidance 860 to 866, `BreakerStopsTheRun` 2437); a
     redirect hop onto it is not requested and its robots.txt is not read, the fetch the
     error `"redirect to a retired host"`, retried under `HttpRetry` as the
     robots-disallowed hop is (836 to 840, 1655 to 1663); a declared sitemap a retirement
     leaves unread is not reported, the retirement covering it (864 to 866); `DryRun`
     still lists the host's rows (1367). Built in this slice (Facts).
  2. **The challenge recognisers of `classify_block`: NONE UNTIL T20.** The guidance
     (1622 to 1624) says the recognisers name no header, page marker, reference or
     cookie yet, so none is recognised and such an answer falls to the later checks.
     `BlockKind.challenge` is reached on constructed verdicts only (its `DisposeFetch`
     branch and `counts_against_host` are unit-tested).
  3. **The spelling of the raw version value: DECODED.** The value is form-decoded
     (`+` a space, `%XX` decoded) before it is mapped through `version_map` and
     sanitised (`mirror.allium` 688 to 704 and 829 to 834). Built in this slice (Facts).
  4. **The 429 reading: ACCEPTED.** A 429 that reaches `classify_block` after
     `HttpRetry`'s retries is a hard block; a 429 whose Retry-After is past the cap is
     blocked and a 503 whose Retry-After is past it fails (1625 to 1630).
- **The T18-2 batched needs-user question: ANSWERED** (found while propagating at
  `86e2ec5`; the maintainer's answers written into the specification at `7d01367`;
  copied into the ledger's `open_questions` as ANSWERED, its residue OPEN).
  1. **A row whose own host readiness retires its host: SKIPPED_BLOCKED.**
     `OpenHostForEntry` or `ReadRobotsForNewOrigin` reads a robots.txt whose Crawl-delay
     or Retry-After past the cap retires the row's host; `SkipTrippedHostAfterReady`
     (1552 to 1566) settles the row `skipped_blocked` with a `UrlSkippedBlocked`, as
     `SkipTrippedHost` (1478) settles the host's other rows, so the batch goes idle and
     other hosts are still fetched; `SkipRobotsDisallowedOnNewHost` requires an
     untripped host (1547 to 1548), so a row robots.txt both disallows and retires is
     `skipped_blocked`, not `skipped_robots`. Tests:
     `tests/test_blocks.py::test_rule_success_SkipTrippedHostAfterReady`, its two
     failure tests, `::test_rule_failure_SkipRobotsDisallowedOnNewHost_3`,
     `::test_a_crawl_delay_on_a_second_origin_retires_the_whole_host` and
     `tests/e2e/test_blocks_sync.py::test_a_seed_whose_own_robots_txt_retires_the_host_is_skipped`.
  2. **A walk whose own host trips mid-walk: STOP FURTHER REQUESTS, KEEP A HELD
     ANSWER.** `AttemptTier`, `HttpRetry` and `Escalate` require an untripped host
     (1604, 1749, 1810); a walk on a tripped host that would need another request, a
     retry, an escalation or a hop its tripped host refused (`FetchAttempt.hop_refused`,
     516 to 517), stops: `StopWalkOnTrippedHost` (1855 to 1884) settles the walk with
     the attempt standing and its row `skipped_blocked` with a `UrlSkippedBlocked`; an
     answer the walk already holds settles as usual (`SettleWalk`, 1823, guidance 1849
     to 1852) and is disposed of as usual, so a good 200 is stored; an attempt that
     itself retires the host settles as it stands (`RetireHostOnLongRetryAfter`).
     `BreakerTrips`' default (1946 to 1952) and `BreakerStopsTheRun` (2437 to 2445)
     say so. Page events are unchanged in kind: a `page` event means a fetch settled
     (`rovo.allium` `AnnouncePage`, 610 to 613), so a stopped walk raises one and a row
     skipped without a fetch raises none. Tests:
     `tests/test_blocks.py::test_derived_FetchAttempt_hop_refused`,
     `::test_rule_success_StopWalkOnTrippedHost`, its three failure tests, the
     re-propagated `tests/test_crawl.py::test_rule_failure_AttemptTier_2`,
     `::test_rule_failure_HttpRetry_2`, `::test_rule_failure_SettleWalk_1` and
     `::test_entity_fields_FetchAttempt`, and
     `tests/e2e/test_blocks_sync.py::test_a_hop_whose_robots_txt_retires_its_own_host_stops_the_walk`.
  3. **Residue, OPEN, carried to T20: a challenge waiting when its host trips.** In an
     owner-testing run, a walk whose `OwnerChallenge` is waiting when its host trips,
     then resolved, asks for a retry that `AttemptTier` now refuses (it requires an
     untripped host), and no rule settles the walk, so it stays `walking`. Owner
     testing is T20's: nothing is built or pinned here.
  4. **Residue: the discovery side of item 2** (review T18-2 C4). **ANSWERED** (the
     maintainer, 2026-11-06; spec `e0f0c44`, through T19's batched item 1): stop, no
     retry. Once a `fetch_resource`'s own host has tripped, its retry or hop is not
     made and the fetch ends with the answer it holds (`crawl.allium` `FetchRobots`
     guidance 868 to 875); built and pinned by T19 (`tests/test_tripped_discovery.py`).
     The question as it was asked: `7d01367`
     answers item 2 for a walk only. A `fetch_resource` hop onto another origin of the
     source's own host, whose robots.txt read retires that host, ends the try as the
     error `"redirect to a retired host"`; `fetch_resource` retries an error answer
     "as HttpRetry does" (`FetchRobots` guidance 843 to 851). `BreakerStopsTheRun`
     (2437 to 2445, "no further request to that host") and the guidance's "no further
     discovery request goes to it" (860 to 863) read as forbidding the next try, but no
     rule says so for a fetch already under way, nor what the fetch then answers (the
     refused hop's error, so `robots_refused`, `sitemap_unavailable` or an unread
     `llms.txt`?). Interim: unchanged (the next try is made;
     `tests/test_blocks_regressions.py`'s C4 tests pin a hop to a second host only);
     none built and none pinned. It blocked no owned obligation; it was item 1 of the
     T18-3 batched needs-user question, now answered.
- **Carried, ANSWERED-BY-SPEC** (from `.allium-loop/T17-quality-gates.json`, originally
  T16): whether a host retirement ranks exit 3 or 1. Exit 3 (Facts): `rovo.allium` 706
  and 955 to 965, `crawl.allium` 933 to 935. Mark it so in this slice's ledger.
- **The specification's open questions.** The third `crawl.allium` one (2514, batch
  concurrency) is on this slice's path: its interim, one row at a time, decides that a
  batch's unstarted rows meet `SkipTrippedHost` after a trip (Facts). The first and
  second (2512, 2513) and the three `convert.allium` ones (486 to 488) are not on this
  slice's path; the second's interim (failed rows retried on every sync) extends to
  blocked and skipped rows, which `PrepareRun` re-pends as before.
- **Unowned residue.** The earlier-reachable obligations step 3 lists as carried are
  named in the ledger so the last slice's review owns or assigns them.
- **`NotInThisSlice`.** A development guard, not product behaviour: each later slice
  removes the raises it implements, and the last slice's review confirms none is left.
  This slice removes ten and adds `BreakerEscalates`' (Acceptance criteria).
