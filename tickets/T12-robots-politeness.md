---
id: T12
title: "Robots and politeness: rovo sync reads robots.txt per origin, paces each host, retries with backoff and Retry-After, and exits partial on a failure"
status: open
depends_on: [T11]
parallel_with: []
branch: full-final-prototype
estimated_size: L
---

# T12: Robots and politeness: rovo sync reads robots.txt per origin, paces each host, retries with backoff and Retry-After, and exits partial on a failure

## Context

T09 (`fd1b423`), T10 (`9fd11fd`) and T11 (`d2979c8`, `2658231`) are slices 1 to 3. `rovo
sync` fetches the seed pages and the pages they link to within the crawl scope, publishes
each at `pages/<host>/<path>`, rewrites links between page files, writes the indexes and
`crawl-report.json`. They fixed every pattern this slice follows: the private subpackages
`rovo._convert`, `rovo._mirror` and `rovo._crawl` with `rovo._config`, `rovo._report`
and `rovo._commands` above them (import direction enforced by
`tests/test_import_direction.py`), the `Fetcher` and `Clock` seams with `tests/fakes.py`,
obligation-named tests (`test_<obligation id>`), the end-to-end harness `serve_site` in
`tests/e2e/conftest.py`, the state files of `docs/reference/mirror.md`, and the
development guard `rovo._unfinished.NotInThisSlice`. Read
`tickets/T09-tracer-init-sync-one-page.md` (its Context table and "Robots is on the path"
paragraph), `tickets/T10-links-and-scope.md`, `tickets/T11-indexes.md`,
`src/rovo/_crawl/run.py` and `src/rovo/_crawl/fetch.py` before starting.

This is slice 4 of T08 to T20, run in this worktree on `full-final-prototype`. Until now
robots is read only as far as the tracer bullet needed (T09): one GET of
`<host.origin>/robots.txt` per host name, an ok answer parsed with `urllib.robotparser`, a
404 giving `allow_all`, any other answer stopping the run with `NotInThisSlice`; no
pacing, no retry, no Crawl-delay effect; a batch's rows run one after another. The
specification base is `91d5623`, which scoped robots.txt per origin (scheme, host and
port, as RFC 9309 does): `RobotsRequested` and `RobotsAnswered` carry the origin,
`robots_allows(run, url)` reads the policy of `origin_of(url)` only, the new rule
`ReadRobotsForNewOrigin` reads a new origin's robots.txt before its first page, and
`AdoptRobotsRules` keeps the longest Crawl-delay and the lowest rate among a host's
origins, while rate, concurrency, pause, Crawl-delay and the breaker stay keyed by host
name (`git show 91d5623 -- docs/specs/crawl.allium`). The code still keys robots by
`host.origin` (`robots_allows`, `src/rovo/_crawl/run.py` 335): this slice moves it
to the URL's origin.

The maintainer answered the batched needs-user question (Open points) before any code was
written, and the answer moved the specification past `91d5623`: `crawl.allium` now states
RFC 9309 matching for `robots_allows`, a decimal `robots_crawl_delay`, `Crawl-delay: 0`
leaving the rate unchanged, no burst, robots.txt tries retried as page tries (a
Retry-After past the cap retiring the host), the batch's concurrency as a permission with
a new `open question`, and `rovo.allium` that nothing is printed without `json_events`.
That change is uncommitted at this writing; it lands as its own `Spec:` commit before
step 0, and that commit is the specification base from then on (called "the answers'
`Spec:` commit" below). It also adds one runtime dependency, the robots parser `protego`
(step 1a).

### The specified path, and what this slice does with each rule on it

The task named the rules to realise; the trigger chain crosses more. Each rule the chain
crosses is classified here, so that no rule is skipped silently. Line numbers are at the
answers' `Spec:` commit (`docs/specs/` as the maintainer's answer left it); `rovo.allium`
moved only after line 936, so its numbers are those of `91d5623`.

| Class | Rules |
| --- | --- |
| **Realised** (every branch reachable in this slice, or constructible on unit inputs where noted) | `crawl.allium`: `OpenHost` (740, `RobotsRequested` now carries the origin); `FetchRobots` (765, any origin, through the host's limiter, with `fetch_resource`'s retries and backoff as a page's http tries, guidance 796 to 806: a `HostBackedOff` per retry, `retry_after_honored` counted; every retry's bytes counted; its host-retiring branch, 772 to 781, still stops the run: Outside, item 2; except its redirect following, which still stops the run: Outside, item 1); `AdoptRobotsRules` (809, the host-rate and Crawl-delay effect T09 deferred: `host.crawl_delay = max(...)`, `host.rate = min(...)` when `honor_crawl_delay` and the delay is above zero, 818 to 823; `robots_crawl_delay` read as a decimal through `protego`, guidance 829 to 832); `DenyAllWhenRobotsRefused` (840) and `DenyAllWhenRobotsUnreachable` (849), each with its `DiscoveryFailed`; `AllowAllWhenRobotsAbsent` (858); `SkipRobotsDisallowed` (1190), `OpenHostForEntry` (1201), `ReadRobotsForNewOrigin` (1218, new), `ProceedWithKnownHost` (1230), `SkipRobotsDisallowedOnNewHost` (1244), all reading `robots_allows` by the URL's own origin, matched as RFC 9309 says through `protego` (`FetchSitemap` guidance 924 to 933); `FetchEntry` (1251) and `AttemptTier` (1285) under the limiter (pause, rate token, Crawl-delay floor, concurrency; no burst, guidance 1321 to 1324); `HttpRetry` (1401) with `retry_wait` and `HostBackedOff`; `CountRetryAfter` (1442); `SettleWalk` (1470, a retryable attempt now retries instead of stopping); `FeedBreaker` (1503, the outcome window, `since_escalation` and `recent_text_lengths`, see Facts); `DisposeFetch` (1595), its `failed_outright` and `not response.ok` branches (`EntryFailed`); `EntryFails` (1682); the invariants `OneRobotsPolicyPerOrigin` (1880) and `HostRateNeverRises` (1896); the `SiteExchange` surface's exposure and its `Politeness` guarantee (1948, 1964). `rovo.allium`: `TallyFailedUrl` (538, now reached by a retried-out page), `TallyDiscoveryProblem` (561), and `RankAndWriteReport`'s partial branch over `has_failures` (665, 671) through `SyncExitCodes` (908). |
| **Traversed, nothing new to do** | `Discover` (709): unchanged, still opening every allowed host at `host_origin`. `SelectBatch` (1111), `NextBatch` (1169): unchanged; a batch's rows still run one after another, which its guidance now permits (1160 to 1162; the concurrency `open question`, 2063; Non-goals). `PrepareAttempt` (1333): no challenge in a standard run. `PrepareRun` (634): unchanged, now meeting `failed` and `skipped_robots` rows to re-pend (`retry_entries`). `FinishRun` (1786): `unresolved_urls` now holds failed and robots-skipped rows. `AnnounceBackoff` (`rovo.allium` 568): `HostBackedOff` is raised and returned by the code, and its `ProgressReported` has no sink without `json_events` (`ProgressOnRequest`, `rovo.allium` 937 to 938), so nothing is printed; the sink is the progress slice's. `CloseRun` (623): `host_reports` already carries `retry_after_honored`, now non-zero. |
| **Split with the discovery slice (T13)** | `ReadRobotsBeforeSitemap` (890): its robots side is this slice's `FetchRobots` taking any origin of a host, which is all the rule needs of robots; its trigger `SitemapDue` and its guard `sitemap_admitted` are the discovery slice's, so the rule itself, its six obligations (`rule-success.ReadRobotsBeforeSitemap`, `rule-failure.ReadRobotsBeforeSitemap.1` to `.5`) and `rule-failure.FetchSitemap.6` move to T13. `QueueSitemaps` (869) and the `declared_sitemaps` it reads are T13's; `RobotsPolicy.declared_sitemaps` is still recorded, as T09 records it. |
| **Outside this slice; reaching one still stops the run** | The guard points written after this slice, and no others: (1) a 3xx answer to a robots.txt (`fetch_resource`'s redirect following, up to `discovery_max_redirects`, is the redirects slice's, with the page fetcher's; `tickets/README.md` does not list that slice yet, so it is named here, as the blocks and breaker slice is, by what it does); (2) `RetireHostOnLongRetryAfter` (1427): a Retry-After past `retry_after_cap` on a page attempt trips the breaker (the blocks and breaker slice), and a Retry-After past `retry_after_cap` on a robots.txt try is the same condition and, by the maintainer's answer, retires the host the same way (`FetchRobots` 772 to 781: the breaker trips and `BreakerTripped` is raised, which `rovo.allium`'s `AnnounceTrip` turns into `breaker_tripped` and exit 3), so `pace.fetch_resource` raises `NotInThisSlice("RetireHostOnLongRetryAfter")` there too: the specification is settled, the trip stays the breaker slice's; and, since `71b5b0f`, `RetireHostOnLongCrawlDelay` (857 to 876 there): an honoured Crawl-delay past `retry_after_cap` retires the host the same way, so the run raises `NotInThisSlice("RetireHostOnLongCrawlDelay")` once robots.txt is read; (3) `classify_block` (1285 guidance): a 401 or 403, a login wall, and now a 429 on a page attempt that is no longer retryable ("a 429 that survived its retries (hard)"), each needing a verdict other than `none`; (4) `Breaker.should_act` (`BreakerEscalates` 1545, `BreakerTrips` 1565): `FeedBreaker` now fills the window, and the moment `should_act` would hold the run stops, since the trip, its `skipped_blocked` rows and exit 3 are the breaker slice's; (5) every other `DisposeFetch` branch (an absent page, a 304 or unchanged page, a blocked verdict, a redirect, a non-HTML answer, a known page); (6) every other `NotInThisSlice` T09 to T11 left (`PrepareRun`'s and `Discover`'s targeted and owner branches, `SelectBatch` with only tripped rows, the browser tier, `Escalate`, `ConvertFetched` beyond `generic`, `RetireOutOfScopePages`, `assign_path`, `PageCandidate.created`, `CloseRun`'s dry run, the convert guards). The two raises this slice removes are `DenyAllWhenRobotsRefused` (`run.py` 287) and `HttpRetry` (`run.py` 865); `DisposeFetch`'s raise stays, narrowed. |

### Facts a later reader would otherwise rediscover

- **"Partial when something was skipped or failed" is narrower in the specification.**
  `RankAndWriteReport` (665 to 673) gives `partial` for a failed or blocked URL, a
  discovery problem (a refused or unreachable robots.txt), an error, an interrupt, a
  budget stop, a skipped target, or an owner-testing run left unresolved. A page
  robots.txt disallows is `skipped_robots` and listed in `unresolved_urls`, but alone it
  leaves the exit `ok`: T09's `test_robots_disallow_skips_the_seed` (exit 0) stays true
  and unedited. `skipped_urls` lists only breaker skips (`rovo.allium` 225), which this
  slice never produces.
- **A robots.txt try is retried as a page's http try** (the maintainer's answer, items 5
  and 6; `FetchRobots` guidance 796 to 806, cross-referenced from `HttpRetry`'s guidance
  1419 to 1420, `RetireHostOnLongRetryAfter`'s comment 1423 to 1426, `CountRetryAfter`'s
  guidance 1450 to 1452 and `FetchAttempt.retires_host`'s comment 490 to 491).
  `FetchRobots`' `fetch_resource` is not a `LadderWalk`, so `HttpRetry` (on
  `AttemptReady`) does not literally fire; the contract says it behaves the same: one
  helper serves both (`retry_wait`, the black box, pure, and the limiter's wait), each
  retry pauses the host and raises a `HostBackedOff` (returned through `CrawlResult` as a
  page retry's is), and each try carrying a Retry-After on a 429 or 503 while
  `honor_retry_after` adds one to the host's `retry_after_honored`. These two outcomes are
  guidance-backed, not obligation-backed (`just plan-spec crawl` has no id for them), so
  `tests/test_pace.py` hand-writes them. A Retry-After past `retry_after_cap` on any try
  retires the host (`FetchRobots` 772 to 781, the same test as `FetchAttempt.retires_host`):
  realising that trip is the breaker slice's, so the run stops there instead (Context row
  "Outside", item 2). After `http_attempts` tries, a transport error gives
  `robots_unreachable` and a 401, 403, 429 or 5xx gives `robots_refused`, each
  `disallow_all` for that origin with a `DiscoveryFailed` row, so the run exits 1. Its
  tries never count toward `run.fetch_attempts` (`FetchRobots` adds bytes only).
- **The limiter.** Per host name: a request waits for `paused_until`, then for the
  host's next rate slot. "A rate token" is a fixed spacing with no burst (the
  maintainer's answer, item 4; `AttemptTier` guidance 1320 to 1324): the starts of two
  requests to one host name are at least `1 / host.rate` apart, and at least
  `host.crawl_delay` apart when Crawl-delay is honoured. `AdoptRobotsRules` already folds the
  Crawl-delay into `host.rate` (`min(rate, 1 / delay)`), so in a standard run the spacing
  honours it; when the rate control is null (owner testing only), the spacing is
  `host.crawl_delay` ("disabling one control never disables another"). Robots, page
  attempts and retries all pass through it; every value comes from `run.policy`,
  `host.rate`, `host.crawl_delay` or `CONFIG`, never a literal.
- **Concurrency is respected by running one row at a time.** `SelectBatch` chooses up to
  `concurrency_per_host` rows per allowed host, and T09's driver runs them one after
  another, so at most one request is ever in flight per host, which is within any
  `concurrency_per_host >= 1`. By the maintainer's answer (item 7) `SelectBatch`'s
  guidance now says the batch "may run concurrently up to the per-host limits" and that
  one row at a time respects `concurrency_per_host` (1160 to 1162), so sequential is
  conformant, not a deviation; whether and when a batch should run concurrently across
  hosts is the new `open question` (`crawl.allium` 2063), which no slice resolves yet.
- **`retry_wait`.** `min(backoff_base * 2^(try - 1), max_backoff)`, then scaled by a
  factor drawn uniformly from `[1 - backoff_jitter, 1 + backoff_jitter]` when
  `retry_backoff` holds, else zero; a Retry-After on a 429 or 503 lengthens it to at
  least the Retry-After when `honor_retry_after` holds (HttpRetry guidance, 1413 to
  1420). The draw comes from an injected source, never the module-global `random`, so
  tests pin it. `host.paused_until = later_of(paused_until, now + wait)`; a retry never
  raises `host.rate`.
- **A Retry-After given as an HTTP date.** `fetch.py`'s `_retry_after` (98) reads only
  seconds and leaves a date to this slice. `SiteResponse.retry_after` is a duration, so
  the fetcher converts a date against the response's `Date` header, else against its
  own clock; a date already past is zero. This is the fetcher's black box, not
  specification behaviour; `test_httpx_fetcher_sends_validators_and_reads_retry_after`
  is extended, not replaced.
- **Why `FeedBreaker` is realised here.** `FeedBreaker` and `DisposeFetch` share the
  trigger `LadderWalk.status transitions_to settled`. Until now every settled walk that
  was not ok stopped at `DisposeFetch`; this slice lets a transport failure settle as
  `failed`, and such a walk is a counted breaker outcome (`failed_outright`). Leaving
  `FeedBreaker` unrealised would let the breaker silently never trip; realising it and
  stopping at `should_act` keeps the divergence visible. `recent_text_lengths` grows only
  when `response.main_text > 0`, and `HttpxFetcher` leaves `main_text` 0 (T09), so no host
  gains a text baseline and `classify_block`'s soft verdict stays unreachable, as before.
- **The robots parser is `protego`, replacing `urllib.robotparser`** (the maintainer's
  answer, items 1 and 2). Python 3.13's `urllib.robotparser` keeps a Crawl-delay only
  when the value is all digits, so `Crawl-delay: 0.5` is dropped, and answers by the
  first matching rule in file order, not RFC 9309's longest match (`Disallow: /a/` then
  `Allow: /a/b` disallows `/a/b`; checked at `2658231`). The specification now states
  the contracts and still names no library (`crawl.allium` 23 to 27): `robots_allows`
  matches as RFC 9309 says, the longest matching path winning, Allow winning a tie, `*`
  and a final `$` as wildcards (`FetchSitemap` guidance 924 to 933), and
  `robots_crawl_delay` reads a decimal number of seconds, null when absent or not a
  number (`AdoptRobotsRules` guidance 829 to 832). `protego` (Scrapy's parser,
  BSD-3-Clause, pure Python, no dependencies, `crawl_delay()` a float) does both; the
  evaluation is `ai_tmp/T12/robots-parser-choice.md`, and step 1a adds it under decision
  0005.
- **`Crawl-delay: 0` adds no delay** (the maintainer's answer, item 3). `AdoptRobotsRules`
  lowers the rate only when the delay is above zero (818 to 823), so there is no `1 / 0`:
  the rate is unchanged and `crawl_delay` stays `max(crawl_delay, 0)`, its old value
  (guidance 828 to 829).
- **Two origins of one host name, served locally.** `hostname_of` drops the port, so two
  `serve_site` servers on two ports of `127.0.0.1` are one host name and two origins: the
  end-to-end proof of per-origin robots and shared pacing needs no new server type.
- **Real time in the end-to-end tests.** `rate_per_host` (2.0 per second) is a `config`
  constant, not a `rovo.toml` key, so every sync through the installed script now spaces
  its requests to one host by 0.5 s. T11's
  `test_a_large_directory_gets_its_own_index` makes about 203 requests to one host
  through the installed script: about 100 s against its 120 s `TIMEOUT`. It is
  re-propagated to run in process through `rovo._commands.sync` over a real
  `HttpxFetcher` with the non-advancing fake timer (step 3); nothing else in it changes.
  The other installed-script scenarios gain at most a few seconds; step 7 records the
  e2e suite's duration before and after. Every in-process `_commands.sync` call in the
  suite passes `FixedClock`, which now never sleeps; the three `CliRunner` syncs
  (`tests/e2e/test_init_sync.py` 142, 156 and 185, at `2658231`) reach `SystemTimer`
  but make at most one request per host name (a robots.txt, then nothing, or a refusal
  before any request), so the limiter never waits there. Step 0 re-runs
  `rg -n 'invoke\(app' tests` and confirms it. Any other in-process sync with two
  requests to one host is written against `_commands.sync` and a fake timer, with one
  exception: the `CliRunner` scenario proving exit 1 at the command boundary (Acceptance
  criteria) cannot avoid backoff waits, since retry backoff is not a `rovo.toml` key, so
  it patches the sleep `pace` calls (`monkeypatch.setattr(pace.time, "sleep", recorder)`)
  before invoking and never sleeps for real.
- **How spacing is measured.** In process the timer is fake, so the server's arrival
  times show no gaps. The in-process scenarios wrap the real `HttpxFetcher` in
  `tests/fakes.py`' `StampingFetcher`, which records `(url, timer.now())` before each
  request, and read every gap off `SteppingTimer`'s time. One limiter wait (pause and
  rate slot folded into one `max`) is one recorded sleep.
- **The obligation source.** `just plan-spec <module>` over the committed
  `docs/specs/<module>.allium` at the answers' `Spec:` commit, written to
  `ai_tmp/T12/plan-spec-<module>.txt` (its echo line to `ai_tmp/T12/plan-spec-<module>.err`):
  crawl 371, rovo 165, mirror 200, convert 47 obligations. Against `91d5623` the answers
  added and removed no id (`ai_tmp/T12/plan-spec-crawl-answers.json`,
  `ai_tmp/T12/plan-spec-rovo-answers.json`); in `crawl` only the four `FetchRobots`
  obligations changed, each now writing `Breaker` and emitting `BreakerTripped` (the
  host-retiring branch, 772 to 781); `rovo`, `mirror` and `convert` are unchanged. The owned set of step 3 is in
  `ai_tmp/T12/owned.json`. The copies are scratch, regenerated by step 0. The maintainer's
  answer to the second batched question moved the base to `71b5b0f` (Open points), which
  changed `crawl.allium` only: `ai_tmp/T12/plan-spec-crawl-cap.json` has 375 obligations,
  the four new ones `RetireHostOnLongCrawlDelay`'s (`rule-success` and `rule-failure.1`
  to `.3`), none removed and none changed ignoring their spans
  (`ai_tmp/T12/spec-cap-obligations-diff.md`). The owned set is unchanged; the
  `AdoptRobotsRules` body changed, so its tests are re-propagated (step 3). Line numbers
  in this ticket are at `3470232` unless they say otherwise; `71b5b0f` shifts them by +1
  after line 51, +3 after 811, +36 after about 840 and +38 after 1416.

## Goal

From a clean checkout, against served fixture sites, `rovo sync` reads each origin's
`/robots.txt` before anything else there, skips what it disallows (matched as RFC 9309
says, through `protego`), spaces the requests to
one host name by at least `max(1 / rate_per_host, the longest Crawl-delay any of its
origins declares)` with no burst (a decimal Crawl-delay read, a zero one adding nothing),
retries a 5xx, a 429 or a transport error up to `http_attempts` tries with exponential
backoff, jitter and Retry-After, a robots.txt as a page, and exits 1 with the URL in
`failed_urls` when a 5xx or transport error runs out of tries (a 429 that runs out stops
the run under `classify_block`, the blocks slice's), or with the robots URL in
`discovery_problems` when an origin's robots.txt is refused or unreachable (that origin
disallowed entirely). No
unit or in-process test sleeps for real: every wait goes through the timer seam, or,
for the two tests in which `SystemTimer` waits, through a patched `pace.time.sleep`. Every
owned obligation listed under Steps has a test named after its id; `just check` is
green; the Allium loop's witness record says `PASS`.

## Non-goals

- No concurrent fetching: a batch's rows still run one after another, which `SelectBatch`
  now permits (Facts); whether a batch should run concurrently across hosts is
  `crawl.allium`'s new `open question` (2063), not this slice's to settle.
- No redirect following, for robots.txt or pages: a 3xx robots answer still stops the
  run; `config-default.discovery_max_redirects` is not owned.
- No breaker trip, escalation, pause after a breach, `skipped_blocked` row or exit 3:
  `should_act` stops the run. No `RetireHostOnLongRetryAfter`, for a page or for a
  robots.txt try (`FetchRobots` 772 to 781): the specification is settled, the trip stays
  the breaker slice's. No `RetireHostOnLongCrawlDelay` either (`71b5b0f`): its trip is
  the breaker slice's, and reaching it stops the run. No block verdict other than `none`.
- No sitemaps and no `llms.txt`: `QueueSitemaps`, `FetchSitemap` and
  `ReadRobotsBeforeSitemap` are T13's (Context table).
- No progress output: `HostBackedOff` reaches no sink; without `json_events` nothing is
  printed (`rovo.allium` 937 to 938), and `json_events` is the progress slice's.
- No owner testing: `robots = "ignore"`, a null rate or concurrency and the relaxed
  controls stay refused by `StartSync`; their branches are tested on unit inputs only
  where an owned obligation needs them (`entity-optional.Host.rate`,
  `rule-failure.FeedBreaker.3`, `rule-failure.CountRetryAfter.4`).
- No new `rovo.toml` key, environment variable or flag; one new runtime dependency, the
  robots parser `protego` (step 1a), and no other.
- No specification change beyond the maintainer's answer, which lands first as the
  answers' `Spec:` commit (Context); after it `docs/specs/` is read, not edited. The six
  `open question` blocks stay open (`crawl.allium` 2061 to 2063, the third new with the
  answer; `convert.allium` 473 to 475); the second
  (a URL that fails on every sync) is on this slice's path, and its interim holds: a
  failed row is re-pended on every sync and `FrontierEntry.attempts` keeps counting. A
  specification gap found while planning, implementing, in weed or in review is never
  resolved in code or in the specification: every such gap joins the one batched
  needs-user question (Open points) and the ledger's `open_questions`.
- No change to the public API: `__all__` stays `["__version__"]`, so
  `docs/reference/api.md` does not move. No decision record changes: decision 0005 asks
  for the dependency note beside the entry in `pyproject.toml` and in the pull request,
  not in the record (its "today the one entry is typer" sentence is already historical
  and stays).
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `src/rovo/_crawl/pace.py` | new | the timer seam (`Timer`: `now()` and `sleep(seconds)`; `SystemTimer` over a wall-clock anchor, `time.monotonic` and `time.sleep`, called through the `time` module; the pure `anchored_now` helper), the per-host limiter (pause, then rate slot), `retry_wait` with an injected jitter draw, and `fetch_resource` (the http tier under the limiter, with retries; no redirect followed) |
| `pyproject.toml` | shared, own lines | `[project] dependencies` gains `protego>=0.7.0,<0.8` with its decision 0005 note (step 1a) |
| `uv.lock` | generated | `just lock` (authorised for this dependency only) adds `protego`; never hand-edited |
| `src/rovo/_crawl/run.py` | shared, own lines | robots parsed with `protego` (`Protego.parse`, `can_fetch(url, "rovo")`, `crawl_delay("rovo")` as a decimal duration, `sitemaps`) in place of `urllib.robotparser`; `open_host` and `fetch_robots` per origin; `deny_all_when_robots_refused`, `deny_all_when_robots_unreachable`, `read_robots_for_new_origin`; `robots_allows` by `origin_of(url)`; `adopt_robots_rules` with the host effect; `attempt_tier` under the limiter; `http_retry`, `count_retry_after`, `feed_breaker`; `dispose_fetch`'s failed branches; `_handle_entry` gaining the new-origin branch and the retry loop; the guards of Context row 4; the `DiscoveryFailed` and `HostBackedOff` events returned through `CrawlResult`, robots.txt retries' included; the module and `adopt_robots_rules` docstrings lose "the politeness slice's"; at `71b5b0f`, `robots_crawl_delay_exceeds` (the number as written against `retry_after_cap`, never a `timedelta`; after review T12-2-r2 C1/B1 an exact `Decimal` that `parse_robots` keeps by rewriting each Crawl-delay value to an ordinal before `Protego.parse`, so `1e400` and `120.000000000000001` are past a 120 s cap; after review T12-3-r2 C1/B1/C2 the value is first checked with `float()`, protego's grammar, and a number whose exponent is past `Decimal`'s limit is kept past every cap), `adopt_robots_rules` adopting only a delay not past the cap, and the `NotInThisSlice("RetireHostOnLongCrawlDelay")` guard; the module docstring's line citation moved (to `f547525`: 600 to 1881; to `fa096c4`: 601 to 1908); `robots_allows`' docstring states RFC 9309 matching as protego 0.7 implements it (`fa096c4`, 963 to 1003) |
| `src/rovo/_crawl/model.py` | shared, own lines | the robots policy holds a `protego.Protego` in place of `RobotFileParser`; `Breaker.over_threshold` and `should_act`; the host's next rate slot (implementation state beside `paused_until`); the run's timer and jitter source; the robots policy's `declared_delay`, the Crawl-delay as written (review T12-2-r2 C1/B1); the `DiscoveryFailed` and `HostBackedOff` triggers; the config block and `SyncControl` line citations moved to `71b5b0f`, and `SyncControl`'s again to `f547525` (1973); both again to `fa096c4` (config 539 to 584, `SyncControl` 2000) |
| `src/rovo/_crawl/fetch.py` | shared, own lines | `_retry_after` reads an HTTP date (Facts); the fetcher's clock for it |
| `src/rovo/_report.py` | shared, own lines | `tally_discovery_problem` (`TallyDiscoveryProblem`) |
| `src/rovo/_commands.py` | shared, own lines | `sync` takes a `Timer` where it took a `Clock`; tallies the run's discovery problems before `CloseRun` |
| `src/rovo/cli.py` | shared, own lines | `sync_command` builds a `SystemTimer` instead of a `SystemClock` |
| `scripts/wheel_smoke.py` | shared, own lines | `PACKAGE_FILES` gains `rovo/_crawl/pace.py`; the verdict line's count follows |
| `tests/fakes.py` | shared, own lines | `FixedClock` gains `sleep`, which records the requested seconds and does not advance (so every earlier test's timestamps stay); a `SteppingTimer` whose `sleep` advances `now`; a `ScriptedFetcher` answering a sequence of responses per URL; a `StampingFetcher` wrapping any fetcher and recording `(url, timer.now())` per request |
| `tests/test_crawl.py` | shared, own lines | the crawl obligations of step 3; the re-propagated tests of step 3, the `AdoptRobotsRules` ones again at `71b5b0f` (a delay at the cap adopted, past it never); its `User-Agent` citation moved to `f547525`'s line, then to `fa096c4`'s (1402), and the Crawl-delay tables' guidance citation to `fa096c4` (837 to 843), both re-propagated at propagate tick 7; at propagate tick 6 (reviews T12-2-r2 and T12-3-r2) the shared Crawl-delay tables (`PAST_CAP_DELAYS` gains `1e309`, `1e400`, the cap plus one sub-ULP step, `1e1000000000000000000`, `1e9999999999999999999`; `NULL_DELAYS`; `TINY_DELAY`; `SPELLED_DELAYS`) and `test_rule_success_AdoptRobotsRules_reads_the_crawl_delay_as_written` |
| `tests/test_report.py` | shared, own lines | the rovo obligations of step 3 |
| `tests/test_commands.py` | shared, own lines | `sync` with a `Timer`; its discovery problems and failed URLs tallied before `CloseRun` |
| `tests/test_pace.py` | new | hand-written: the `Politeness` guarantee on unit inputs (spacing by rate and by the longest Crawl-delay across two origins, pause honoured, no request before robots), `retry_wait` table (each try, the cap, the jitter bounds, Retry-After lengthening, `retry_backoff` and `honor_retry_after` off), `Crawl-delay: 0` leaving the rate unchanged, a fractional Crawl-delay read (`Crawl-delay: 0.5` spaces by 0.5 s), RFC 9309 matching (a longer `Allow` beating a shorter `Disallow` in either file order, `Allow` winning a tie, `*` and `$`), the robots retry outcomes (a robots.txt answering 503 with `Retry-After` then 200 raises one `HostBackedOff` and leaves `retry_after_honored == 1`; a Retry-After past `retry_after_cap` on a robots.txt try asserts the `NotInThisSlice("RetireHostOnLongRetryAfter")` raise), `HostRateNeverRises` across many adoptions; at `71b5b0f`, a Crawl-delay equal to `retry_after_cap` honoured, and one past it (cap + 1, `99999999999`, `1e12`, `1e15`) never reaching the limiter with Crawl-delay not honoured; at propagate tick 6 (re-propagated) the past-cap values of `PAST_CAP_DELAYS`, a Crawl-delay that is no number or too small for `Decimal` leaving the rate alone and the host not retired, and the `index.html` fold cases of review B2 (`f547525`); at propagate tick 7 (re-propagated, `fa096c4`, review T12-2-r3 C1) the literal-`$` copy cases (under `Disallow: /guide/private/` and `Allow: /guide/private/$`, the directory, `$secret` and `%24secret` allowed, `x` and `?a=1` not; under `Allow: /` and `Disallow: /guide/x$`, `/guide/x` and `/guide/x$y` disallowed, `/guide/xy` allowed; the fold's line getting no copy); `test_system_timer_delegates_to_time`, with `pace.time.sleep` and `pace.time.monotonic` patched: `SystemTimer().sleep(1.5)` hands `1.5` to the patched sleep, and `now()` advances by exactly the patched monotonic delta |
| `tests/test_import_direction.py` | shared, own lines | `ROOT_FORBIDDEN_TOPS` gains `protego`, so `import rovo` is proved never to load it |
| `tests/test_slice_boundaries.py` | shared, own lines (re-propagated) | `test_a_later_slices_answer_stops_the_run` loses the `robots-refused` and `retryable` parameters (now realised) and gains a last-try 429, a robots 3xx kept, a `should_act` breach; `test_httpx_fetcher_sends_validators_and_reads_retry_after` gains the HTTP-date case; at `71b5b0f`, an honoured Crawl-delay past `retry_after_cap` stops at `NotInThisSlice("RetireHostOnLongCrawlDelay")`, for every value of `PAST_CAP_DELAYS` (propagate tick 6) |
| `tests/test_regressions.py` | shared, own lines | one test per divergence weed or review finds, including review T12-1's: `anchored_now` gives the same result when the wall clock jumps forward between two calls (step 1); weed tick 4's huge Crawl-delay (`1e15`, `1e12`, `99999999999`) through `HttpxFetcher` stopping at `RetireHostOnLongCrawlDelay`, never overflowing; reviews T12-2-r2 C1/B1 and T12-3-r2 C1/B1/C2 (re-propagated, tick 6): `1e309`, `1e400`, the cap plus one sub-ULP step and an exponent past `Decimal`'s limit stop there too, while `_121`, `121_`, `1__21` and `-1e9999999999999999999` are no Crawl-delay and `1e-9999999999999999999` no delay, the run finishing; at propagate tick 7 its `AdoptRobotsRules` guidance citation moved to `fa096c4` (837 to 843, re-propagated) |
| `tests/test_convert.py` | shared, own lines (re-propagated) | one docstring's `crawl.allium` line citation moved to `71b5b0f`, then to `f547525` (`with_fetch_flags`, 1753), then to `fa096c4` (1780); no test changes |
| `tests/e2e/conftest.py` | shared, own lines | `serve_site` gains optional scripted answers per path (a status, headers and body per try, then the file) and a request log (path and arrival time), and a "drop" answer that closes the connection without a response |
| `tests/e2e/test_harness.py` | shared, own lines | the scripted answers, the drop and the request log, each tested |
| `tests/e2e/test_polite_sync.py` | new | the end-to-end scenarios (Acceptance criteria), the `CliRunner` exit-1 scenario among them; not `test_pace.py` or `test_politeness.py`, so no unit test shares its basename |
| `tests/e2e/test_index_files.py` | shared, own lines (re-propagated) | `test_a_large_directory_gets_its_own_index` runs in process (Facts) |
| `tests/fixtures/sites/polite/robots.txt`, `tests/fixtures/sites/polite/guide/start.html`, `tests/fixtures/sites/polite/guide/a.html`, `tests/fixtures/sites/polite/guide/flaky.html`, `tests/fixtures/sites/polite/guide/private/secret.html` | new | the `polite` site (step 7) |
| `docs/reference/cli.md` | shared, own lines | `rovo sync`: robots per origin, matched as RFC 9309 as protego 0.7 implements it (`fa096c4`), a decimal Crawl-delay and a zero one adding nothing, the refused or unreachable robots.txt, pacing with no burst, retries (robots.txt included), the exit 1 cases, nothing printed without `json_events`; the later-slice sentence loses "a retry"; the `index.html` fold (`f547525`) and the literal-`$` copy (`fa096c4`) |
| `docs/reference/configuration.md` | shared, own lines | the `[project]` row's runtime dependencies gain `protego>=0.7.0,<0.8` |
| `docs/how-to/maintain-dependencies.md` | shared, own lines | the runtime ranges row gains protego |
| `docs/reference/testing.md` | shared, own lines | the timer fakes and `ScriptedFetcher`, the scripted harness, the `polite` site, `tests/test_pace.py`, the package-file count; the import-direction paragraph's dependency list gains `protego` |
| `docs/how-to/test-and-debug.md` | shared, own lines | the package-file count |
| `docs/explanation/architecture.md` | shared, own lines | `pace` in `_crawl`'s part of the private modules' row; the timer seam |
| `docs/project/repository-map.md` | shared, own lines | the tree gains `pace.py` and the fixture site |
| `AGENTS.md` | shared, own lines | line 10's "today" sentence, only if it becomes false |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` entry, naming the `protego` dependency, the `index.html` fold and the literal-`$` copy |
| `docs/specs/crawl.allium`, `docs/specs/rovo.allium` | specification | the maintainer's answer, landed before step 0 as the answers' `Spec:` commit; not edited after it |
| `tickets/README.md`, `tickets/T12-robots-politeness.md` | ticket | index row, graph, slice bullet, this ticket |
| `.allium-loop/T12-robots-politeness.json`, `.allium-loop/T12-robots-politeness.witness.json` | gitignored | the loop ledger and the witness record; never committed |

`pytest.ini`, `.coveragerc`, `ruff.toml`, `mypy.ini`, `Justfile`,
`src/rovo/__init__.py`, `src/rovo/_mirror/`, `docs/decisions/`, `docs/reference/mirror.md`
(it lists neither the frontier's statuses nor the report's lists, so nothing there
names `failed`, `skipped_robots` or `discovery_problems`; review T12-2-r2 C3) and, after the answers'
`Spec:` commit, `docs/specs/` are read, not changed. A file not in this table that turns out to need a change is added to the table
in the same change with its reason, or handed back if it is a decision record or a
specification.

## Steps

0. `just check` baseline on the untouched worktree at the answers' `Spec:` commit (whose
   only change from `2658231` is `docs/specs/` and this ticket), last line quoted, and
   `{ just py-test tests/e2e -ra 2>&1; echo "exit $?"; } | tail -3` with its wall time.
   Scratch output goes in `ai_tmp/T12/`. Write `just plan-spec <module>` for each of
   `crawl`, `rovo`, `mirror` and `convert` to `ai_tmp/T12/plan-spec-<module>.txt`, and the
   owned set of step 3 to `ai_tmp/T12/owned.json`. Create the ledger
   `.allium-loop/T12-robots-politeness.json` against
   `allium-skill-reference/allium/schemas/ledger.schema.json`, shaped like T11's: `goal`
   `"T12-robots-politeness"`, `mode` `"spec-first"`, `tick` 0, `specification_base` the
   answers' `Spec:` commit, `obligation_source` the four files, and `open_questions`
   holding the six specification open questions verbatim (the new concurrency one
   included) and the batched question of the Open points with the maintainer's answer.
   Read `.agents/skills/propagate/SKILL.md`, `.agents/skills/weed/SKILL.md`,
   `.agents/skills/witness/SKILL.md` and `.agents/skills/python-change/SKILL.md` before
   step 3.

1. **The timer seam.** `rovo._crawl.pace.Timer` is a protocol with `now()` (timezone-aware
   UTC, as `Clock`) and `sleep(seconds: float)`. `start_run(request, clock)` keeps its
   signature with `clock: Timer` and puts the timer on the run, so `open_host`,
   `fetch_robots`, `fetch_entry` and `attempt_tier` keep theirs and every earlier call
   site is unchanged. `tests/fakes.py`' `FixedClock` satisfies `Timer`: its `sleep`
   records and never advances, so no earlier test's timestamp moves and no test sleeps.
   The limiter computes its wait once (`max(0, slot - now)`) and never loops on the
   clock, so a non-advancing timer cannot hang it. `SteppingTimer` advances on `sleep`
   for the tests that read spacing. The jitter draw is a run-scoped injected source.
   Only `rovo.cli` builds `SystemTimer` in the product. `SystemTimer` paces on a monotonic
   clock, never the wall clock (`SystemClock.now()` is `datetime.now(UTC)`, adjustable, so
   a step of the wall clock would shrink or stretch a wait): it anchors once at
   construction (`self._wall = datetime.now(UTC)`, `self._mono = time.monotonic()`) and
   its `now()` returns `anchored_now(self._wall, self._mono, time.monotonic())`, a small
   pure helper in `pace.py` giving `wall0 + timedelta(seconds=mono_now - mono0)`. The
   `Timer` protocol, `paused_until` and every call site are unchanged; a Retry-After HTTP
   date is compared against this anchored `now()`. `pace.py` does `import time` and calls
   `time.sleep(...)` and `time.monotonic()` as module attributes at call time (never
   `from time import sleep`), so that a test can replace them with
   `monkeypatch.setattr(pace.time, "sleep", recorder)`; the two tests in which
   `SystemTimer` waits (Acceptance criteria) rely on it.
   `just py-test tests/test_import_direction.py`
   stays green (`pace` is inside `_crawl`; the test's one edit is step 1a's).

   1a. **The robots parser dependency** (the maintainer's answer, items 1 and 2; the
   `plan-change` skill's dependency guidance and decision 0005). The candidate and the
   evidence are in `ai_tmp/T12/robots-parser-choice.md`.

   - `pyproject.toml`: `[project] dependencies` gains `"protego>=0.7.0,<0.8"`, a compatible
     range whose lower bound is the version the lock holds, so the gate runs against it
     (at 0.x the next minor bounds it, as for httpx). If `just lock` resolves another
     version, the lower bound and the note follow the locked one. Beside it, the
     decision 0005 note in the form the other entries use: what it does (robots.txt
     parsing and matching: RFC 9309 longest match, Allow winning ties, `*` and `$`
     wildcards, a decimal Crawl-delay); why the standard library will not do (Python
     3.13's `urllib.robotparser` answers by the first matching rule and drops a
     fractional Crawl-delay; rovo supports `>=3.13`); its licence (BSD-3-Clause; pure
     Python, no dependencies); its maintenance (released by the Scrapy project, author
     Anubhav Patel, the locked 0.7.0 uploaded 2026-09-21); and that `rovo._crawl` alone
     imports it. The same note goes in the pull request.
   - `just lock` (reaches the network; **authorised for this dependency only**), then
     `just lock-check`. Installing it into `.venv` takes `just sync`, which also reaches
     the network and is **not** covered by that authorisation. After `just lock`, work
     stops until `just sync` is authorised: no test runs without `protego` installed.
   - Imports: `from protego import Protego` only inside `rovo._crawl` (`model.py` and
     `run.py`, where `urllib.robotparser` is imported today), never from `import rovo` or
     `rovo.cli`; `tests/test_import_direction.py`' `ROOT_FORBIDDEN_TOPS` gains
     `"protego"`. `robots_allows` calls `can_fetch(url, "rovo")`; `robots_crawl_delay`
     turns `crawl_delay("rovo")`'s float into a duration (null stays null).
   - `just wheel-smoke`: its `api` line proves `import rovo` with no dependency
     installed; `just py-test tests/test_import_direction.py`.
   - Documents: `docs/reference/configuration.md`, `docs/how-to/maintain-dependencies.md`,
     `docs/reference/testing.md`, `CHANGELOG.md` (step 9).

2. **Robots per origin.** `fetch_robots(run, name, origin, fetcher)` (realising
   `FetchRobots` for that origin; `open_host` passes `host.origin`) goes through
   `fetch_resource` and ends in exactly one of `AdoptRobotsRules`,
   `DenyAllWhenRobotsRefused`, `DenyAllWhenRobotsUnreachable` or
   `AllowAllWhenRobotsAbsent`; a 3xx still raises. `robots_allows` reads
   `run.robots_policy(origin_of(url))`. `_handle_entry`: a new host opens and its entry
   goes to `SkipRobotsDisallowedOnNewHost` or `FetchEntry`; a known host with an unread
   origin goes through `ReadRobotsForNewOrigin` the same way; a known origin through
   `SkipRobotsDisallowed` or `ProceedWithKnownHost` (their new fourth guard keeps the
   three disjoint). The returned `DiscoveryFailed` events reach
   `tally_discovery_problem` in `_commands`.

3. **Tests first, from the obligations** (the `propagate` skill, spec-first). Write a
   failing test for each owned obligation below into the test file of its module, named
   `test_<obligation id with dots and hyphens as underscores>`, its docstring quoting the
   obligation's description from the plan-spec file. Generated tests satisfy EditorConfig
   (indentation in 4-space multiples in `*.py`, string literals included), ruff and
   mypy, since the gate stages them. Run `just py-test` and record the red run in
   `ai_tmp/T12/red.txt`, its summary line under `last_results.propagate` in the ledger.
   Record each generated or re-propagated test file's SHA-256 under
   `generated_test_hashes`, and the reconciliation line (`N obligations, M covered, K
   uncovered`) over the owned set. A test changed after the red run is re-recorded: a
   new hash, `tick` incremented, a ledger note naming the test and why; never silently.
   An obligation a test cannot reach without a later slice's behaviour is not owned:
   move it to the hand-back notes with its reason rather than writing a vacuous test.

   Owned obligations, new in this slice (ids as `just plan-spec <module>` emits them at
   the answers' `Spec:` commit, the same ids as at `91d5623`, Facts; 67):

   - **`crawl`** (59), in `tests/test_crawl.py`: `enum-comparable.RobotsMode`,
     `enum-comparable.RobotsStance`, `enum-comparable.DiscoveryProblem`,
     `entity-optional.RobotsPolicy.crawl_delay`, `entity-optional.RobotsPolicy.problem`,
     `entity-optional.Host.rate`, `entity-optional.Host.paused_until`,
     `entity-relationship.Host.breaker`, `entity-fields.FetchAttempt`,
     `invariant.FetchAttempt.TriesBounded`, `derived.FetchAttempt.retryable`,
     `derived.FetchAttempt.retires_host`, `derived.FetchAttempt.failed_outright`,
     `entity-fields.Breaker`, `invariant.Breaker.WindowBounded`,
     `derived.Breaker.over_threshold`, `projection.Frontier.retry_entries`,
     `transition-edge.FrontierEntry.in_progress.failed`,
     `transition-edge.FrontierEntry.failed.pending`,
     `transition-edge.FrontierEntry.skipped_robots.pending`,
     `config-default.http_attempts`, `config-default.backoff_base`,
     `config-default.max_backoff`, `config-default.backoff_jitter`,
     `config-default.retry_after_cap`, `config-default.breaker_window`,
     `config-default.breaker_min_outcomes`, `config-default.block_rate_threshold`,
     `config-default.host_text_history`, `rule-success.DenyAllWhenRobotsRefused`,
     `rule-failure.DenyAllWhenRobotsRefused.1`, `rule-failure.DenyAllWhenRobotsRefused.2`,
     `rule-entity-creation.DenyAllWhenRobotsRefused.1`,
     `rule-success.DenyAllWhenRobotsUnreachable`,
     `rule-failure.DenyAllWhenRobotsUnreachable.1`,
     `rule-failure.DenyAllWhenRobotsUnreachable.2`,
     `rule-entity-creation.DenyAllWhenRobotsUnreachable.1`,
     `rule-failure.SkipRobotsDisallowed.4`, `rule-success.ReadRobotsForNewOrigin`,
     `rule-failure.ReadRobotsForNewOrigin.1`, `rule-failure.ReadRobotsForNewOrigin.2`,
     `rule-failure.ReadRobotsForNewOrigin.3`, `rule-failure.ProceedWithKnownHost.4`,
     `rule-success.HttpRetry`, `rule-failure.HttpRetry.1`, `rule-failure.HttpRetry.2`,
     `rule-success.CountRetryAfter`, `rule-failure.CountRetryAfter.1`,
     `rule-failure.CountRetryAfter.2`, `rule-failure.CountRetryAfter.3`,
     `rule-failure.CountRetryAfter.4`, `rule-success.FeedBreaker`,
     `rule-failure.FeedBreaker.1`, `rule-failure.FeedBreaker.2`,
     `rule-failure.FeedBreaker.3`, `rule-success.EntryFails`, `rule-failure.EntryFails.1`,
     `invariant.HostRateNeverRises`, `surface-exposure.SiteExchange`.
   - **`rovo`** (8), in `tests/test_report.py`: `rule-success.TallyDiscoveryProblem`,
     `rule-failure.TallyDiscoveryProblem.1`, `value-equality.DiscoveryProblemRow`,
     `entity-fields.DiscoveryProblemRow`, `rule-success.TallyFailedUrl`,
     `rule-failure.TallyFailedUrl.1`, `value-equality.FailedUrl`,
     `entity-fields.FailedUrl`.
   - **`mirror`**, **`convert`**: none.

   Extended, not new (re-propagated in place, same names, each re-hashed in this slice's
   ledger with a note naming its origin slice; T09's to T11's ledgers are never edited):
   `test_rule_success_AdoptRobotsRules` (T09 reserved the host-rate assertion for this
   slice: `host.rate` and `host.crawl_delay` after a Crawl-delay, the longest of two
   origins winning; a `Crawl-delay: 0` leaving `host.rate` unchanged; a `Crawl-delay: 0.5`
   read as half a second; at `71b5b0f`, a delay equal to `retry_after_cap` adopted and one
   past it, however large, never adopted and never raising) and
   `test_rule_entity_creation_AdoptRobotsRules_1` (at `71b5b0f`, `crawl_delay` is the
   declared delay, null past the cap), `test_rule_success_FetchRobots` and `test_rule_failure_FetchRobots_1`
   to `_3` (the `origin` argument; the request goes to that origin; their obligations now
   also name `Breaker` written and `BreakerTripped` emitted, the host-retiring branch,
   which this slice reaches only as the `NotInThisSlice("RetireHostOnLongRetryAfter")`
   raise, so each test asserts the breaker untouched on an ordinary answer and
   `tests/test_pace.py` asserts the raise), `test_rule_success_OpenHost`
   (`RobotsRequested` carries the origin), `test_invariant_OneRobotsPolicyPerOrigin` (two
   origins of one host each hold a policy), and every `robots_allows` assertion that
   assumed `host.origin` (by `origin_of(url)` now). In `tests/test_slice_boundaries.py`,
   the parameters and cases the Files touched table names. In
   `tests/e2e/test_index_files.py`, `test_a_large_directory_gets_its_own_index` (Facts).
   Claim an earlier test "passes unedited" only where it does; the hand-back notes list
   every earlier test this slice edited.

   Guarantees (no obligation id; hand-written in `tests/test_pace.py`): `Politeness`
   (`SiteExchange`, 1964: on a `SteppingTimer`, the gap between the starts of two
   requests to one host name is at least `1 / host.rate`; with two origins declaring
   Crawl-delays 2 and 3, at least 3 s; nothing is requested before a host's
   `paused_until`; robots.txt of an origin is the first request there; every request a
   `ScriptedFetcher` sees is one the robots policy of its origin allows) and
   `SyncExitCodes`' exit-1 cases this slice reaches (a failed URL, a discovery problem;
   a robots-skipped page alone stays 0).

   Not owned, and why, for the hand-back notes: `surface-actor.SiteExchange` (the surface
   as a whole also guarantees `RedirectsFollowedOnlyInScope`,
   `BrowserRendersContentNeverAnswersBlocks` and `BreakerStopsTheRun`, later slices');
   `derived.Breaker.should_act`, `rule-*.BreakerEscalates`, `rule-*.BreakerTrips`,
   `rule-*.RetireHostOnLongRetryAfter`, `when-set.RetireHostOnLongRetryAfter.LadderWalk.standing`,
   `rule-*.RetireHostOnLongCrawlDelay` (new at `71b5b0f`; this slice only raises
   `NotInThisSlice("RetireHostOnLongCrawlDelay")` when its condition holds),
   `derived.Host.breaker_tripped`, `config-default.breaker_pause`,
   `config-default.min_host_rate` (the blocks and breaker slice); `rule-*.AnnounceBackoff`
   (the progress slice); `config-default.discovery_max_redirects` (the redirects slice);
   `rule-*.ReadRobotsBeforeSitemap`, `rule-failure.FetchSitemap.6` and `rule-*.QueueSitemaps`
   (T13); `enum-comparable.PolitenessControl` (owner testing); every other uncovered
   obligation in the four files, each belonging to the slice T09's Context table names.

4. **Crawl** (`src/rovo/_crawl/`). `pace.py`, then `run.py` and `model.py` per steps 1
   and 2 and the Context table: the limiter before every request; `AdoptRobotsRules`'
   host effect; `HttpRetry` on a retryable attempt (`HostBackedOff`, a new try at
   `try + 1`, the rate never raised); `CountRetryAfter` on an http attempt that carries a
   Retry-After on a 429 or 503 while `honor_retry_after`; `FeedBreaker` on every settled
   walk, then `NotInThisSlice("BreakerTrips")` the moment `should_act` holds;
   `DisposeFetch`'s `failed_outright` branch (`EntryFailed` with the error) and
   `not response.ok` branch (`EntryFailed` with `status_text`), every other non-success
   branch still raising; a 429 attempt that is no longer retryable and does not retire
   the host raises `NotInThisSlice("classify_block")`; a retires-host attempt still
   raises `NotInThisSlice("RetireHostOnLongRetryAfter")`, and so does a robots.txt try in
   `fetch_resource` whose Retry-After is past `retry_after_cap`. An ok robots.txt whose
   Crawl-delay, compared as written (`robots_crawl_delay_exceeds`), is past
   `retry_after_cap` is never adopted: the policy records no `crawl_delay`, the host is
   unchanged and no value too large for a `timedelta` is ever built; when Crawl-delay is
   honoured the run then raises `NotInThisSlice("RetireHostOnLongCrawlDelay")` (`71b5b0f`,
   Open points). A robots.txt try in
   `pace.fetch_resource` is retried as a page's http try: each retry raises a
   `HostBackedOff`, returned through `CrawlResult`, and each try carrying a Retry-After
   on a 429 or 503 while `honor_retry_after` adds one to the host's `retry_after_honored`
   (Open points, items 5 and 6). Unit cases in
   `tests/test_crawl.py` and `tests/test_pace.py` on `ScriptedFetcher` and the timers.
   `just py-test tests/test_crawl.py tests/test_pace.py tests/test_slice_boundaries.py`.

   **Adversarial review** (`tickets/CONVENTIONS.md` §14; checkpoint 1, a design later
   lanes build on: the breaker, browser and concurrency slices reuse the limiter and the
   timer seam). Brief: this ticket, `tickets/CONVENTIONS.md`, `git diff 2658231` plus the
   uncommitted changes, and the questions: does every request, robots and retries
   included, pass through the limiter; can any test sleep for real or hang on a
   non-advancing timer; is any politeness value a literal rather than `CONFIG` or the
   policy; does `robots_allows` ever read another origin's policy; is any `NotInThisSlice`
   removed whose branch is not realised, or any branch realised silently that the
   Context table keeps outside. Two lenses, conformance and breakage, written to
   `ai_tmp/review/T12-1/findings-conformance.md` and
   `ai_tmp/review/T12-1/findings-breakage.md` with
   `codex exec -m gpt-6-astra -s read-only -C <worktree> -o <file> "<brief>"` or
   `claude -p --model claude-opus-5-5 --permission-mode plan "<brief>" > <file>`, the
   harness the executing agent is not when it is on `PATH`; triage verdicts in
   `ai_tmp/review/T12-1/verdicts.md`; valid fixes applied one at a time, within the
   Files touched table; then step 4's tests rerun and quoted. The model call is the
   checkpoint's authorised network use.

5. **Report and command** (`src/rovo/_report.py`, `src/rovo/_commands.py`,
   `src/rovo/cli.py`, `src/rovo/_crawl/fetch.py`). `tally_discovery_problem`; `sync`
   tallies the run's discovery problems and failed URLs before `CloseRun`; `cli` builds
   the `SystemTimer`; the fetcher reads an HTTP-date Retry-After. Unit cases in
   `tests/test_report.py` and `tests/test_commands.py`. Run `just py-lint`,
   `just py-typecheck`, `just coverage`; add `rovo/_crawl/pace.py` to `PACKAGE_FILES` and
   run `just wheel-smoke`, quoting its `api` line.

6. **The harness.** `serve_site` gains scripted answers and a request log without
   changing what an unscripted call serves; `tests/e2e/test_harness.py` proves a scripted
   status with its headers, a sequence then the file, the drop, and the log's order.
   `just py-test tests/e2e/test_harness.py`.

7. **End to end.** Fixture site `polite`, two-space indentation and a final newline,
   each page with a `<title>` and a `<main>` holding an `h1` and a paragraph of prose; no
   link to a missing file, a directory without its slash or a non-HTML file.
   - `polite/robots.txt`: `User-agent: *`, `Crawl-delay: 3`, `Disallow: /guide/private/`.
   - `polite/guide/start.html`: links to `a.html`, `flaky.html` and
     `private/secret.html`.
   - `polite/guide/a.html`, `polite/guide/flaky.html`, `polite/guide/private/secret.html`:
     one paragraph, no link.
   The two-origin scenario's sites are generated into `tmp_path` by a helper in
   `tests/e2e/test_polite_sync.py`, since a link must carry the second server's port:
   the second site is served first (`serve_site(<path>)`), its `robots.txt` holding
   `Crawl-delay: 5` and `Disallow: /guide/closed/`, with `guide/open.html` and
   `guide/closed/x.html`; then the first site, its `robots.txt` holding `Crawl-delay: 2`,
   its seed `guide/start.html` linking both pages by absolute URL on the second port.
   The scope admits them: it compares host names, not ports
   (`CrawlScope.host_allowed`). The installed-script scenario's site is generated the
   same way. The scenarios are the Acceptance criteria's; every in-process
   scenario uses a real `HttpxFetcher` wrapped in `StampingFetcher`, with a
   `SteppingTimer`, and reads gaps off the stamps and order off the server's request
   log. The retry and robots-failure scenarios serve a generated copy of `polite` whose
   `robots.txt` has no Crawl-delay, so the host's spacing (`1 / rate_per_host`, 0.5 s)
   is below every backoff and each wait the timer records is the backoff alone. `just py-test tests/e2e -ra`, its wall
   time quoted beside step 0's.

8. **Witness** (the `weed` and `witness` skills). Run `weed` over `crawl` and `rovo`
   against the code, scoped to the owned and extended obligations and the guarantees;
   record its verdict under `last_results.weed` and fix any code divergence, each with a
   regression test in `tests/test_regressions.py`. A divergence weed attributes to the
   specification is not fixed: it joins the one batched needs-user question. Then run
   `witness` non-interactively: it writes `.allium-loop/T12-robots-politeness.witness.json`
   per `witness-result.schema.json`. The verdict must be `PASS`; a `FAIL` routes back per
   the skill, and the hand-back notes record each round.

9. **Documents** (the `review-docs` skill). The pages of the Files touched table; find
   the sentences this slice makes false with
   `rg -n -i "robots|retry|politeness slice|crawl-delay|one after another|a retry" -g '*.md' -g '!tickets/**' -g '!allium-skill-reference/**' -g '!docs/specs/**' -g '!docs/decisions/**'`;
   `CHANGELOG.md` `Unreleased` gains one Added entry. Keep the required phrases of
   `AGENTS.md` in always-visible text. `just check-docs`, `just check-agents`.

   **Adversarial review** (`tickets/CONVENTIONS.md` §14; checkpoint 2, before the final
   commit). Brief: this ticket, `tickets/CONVENTIONS.md`, `git diff 2658231` plus the
   uncommitted changes, the ledger and the witness record (not the hand-back notes), and
   the questions: is every acceptance criterion shown by a test that would fail if the
   claim were false; does any re-propagated earlier test assert less than before; does a
   verification command print a pass when it failed; does `just check` need the
   network or sleep for real; is every gap in the batched question rather than resolved.
   Files `ai_tmp/review/T12-2/findings-conformance.md`,
   `ai_tmp/review/T12-2/findings-breakage.md` and `ai_tmp/review/T12-2/verdicts.md`; the
   same commands, triage and one-at-a-time fixes as checkpoint 1; a second round over
   the fix diff when a high-severity finding was valid, two rounds at most; then
   `just check` rerun and quoted.

10. Hand-back notes, `status: done`, `just check` ending with
    `All checks passed and the worktree is unchanged.`, `git status --short` empty after
    the commit. Commit on the branch. **Authorisation required**: pushing and opening the
    pull request.

## Acceptance criteria

- **End to end, robots and Crawl-delay** (`tests/e2e/test_polite_sync.py`, in process):
  with `serve_site("polite")` at `<base>`, `rovo init <base>guide/start.html <tmp>/out`
  then `rovo._commands.sync` over `HttpxFetcher` and a `SteppingTimer` exit 0. The
  server's log starts with `/robots.txt`; `/guide/private/secret.html` is never requested
  and its frontier row is `skipped_robots`; `start`, `a` and `flaky` are written; every
  stamped gap between consecutive requests to the host is at least 3 s (the
  Crawl-delay, above `1 / rate_per_host`); `crawl-report.json` has `exit_code: "ok"` and
  the robots-skipped URL in `unresolved_urls`.
- **End to end, a retry with Retry-After** (the copy of `polite` without a Crawl-delay,
  step 7): `/guide/flaky.html` scripted to answer 503 with `Retry-After: 4`, then the
  file. The sync exits 0, `flaky` is written, the server
  saw it twice, the timer recorded a wait of at least 4 s before the second try, the
  report's `per_host` row has `retry_after_honored: 1` and `fetched` counts both tries.
- **End to end, retries run out** (the same copy): `/guide/flaky.html` scripted to
  answer 503 every time. The sync exits 1; the server saw it `http_attempts` times; the
  stamped gaps between its tries are `min(backoff_base * 2^(n - 1), max_backoff)` within `backoff_jitter`
  either way; `failed_urls` holds the URL with `attempts` equal to `http_attempts`, and
  `changes` a `failed` row; the other pages are written.
- **End to end, robots refused and unreachable** (the same copy): robots.txt scripted to answer 500 every
  time, then (a separate mirror) the drop every time. Each sync exits 1, requests no page,
  leaves the seed row `skipped_robots`, and its report's `discovery_problems` is
  `[{"url": "<base>robots.txt", "problem": "robots_refused"}]`, respectively
  `"robots_unreachable"`; the robots.txt was tried `http_attempts` times.
- **End to end, exit 1 at the command boundary**
  (`test_rovo_sync_exits_1_through_the_command_line_when_robots_is_refused`, through
  `typer.testing.CliRunner`): robots.txt scripted to answer 500 every time, `rovo init`,
  then, with `pace.time.sleep` patched to a recorder
  (`monkeypatch.setattr(pace.time, "sleep", recorder)`),
  `CliRunner().invoke(app, ["sync", <out>])`. `result.exit_code == 1`, the report has
  `exit_code: "partial"`, and the recorder saw the backoff waits; nothing sleeps for real.
- **End to end, two origins of one host**: the seed on the first port links to two pages
  on the second port (step 7). The second origin's `/robots.txt` is requested once, after
  the first origin's and before any page there; `guide/open.html` is written,
  `guide/closed/x.html` is never requested and is `skipped_robots`; the stamped gaps
  between consecutive requests to `127.0.0.1` are at least 2 s before the second
  robots.txt and at least 5 s after it (the longer Crawl-delay wins for the host name);
  the sync exits 0.
- **End to end, the installed script waits for real**: through the installed `rovo`
  script beside `sys.executable`, a generated site whose `robots.txt` holds
  `Crawl-delay: 2` and whose seed links one page: the sync exits 0, the server's log
  holds robots.txt, the seed and the page in that order, and the request log's arrival
  gap between the seed and the page is at least 1.8 s (the Crawl-delay, which the default
  spacing `1 / rate_per_host`, 0.5 s, cannot reach; interpreter start-up is outside the
  gap). The `rovo sync` subprocess's elapsed wall time is at least 2 s, as supplementary
  evidence only; no upper bound is asserted.
- **End to end, earlier scenarios**: `tests/e2e/test_init_sync.py`,
  `tests/e2e/test_follow_links.py` and `tests/e2e/test_index_files.py` pass; only
  `test_a_large_directory_gets_its_own_index` was edited (in process, Facts), and the
  ledger says so.
- Every owned obligation in step 3 has a test named after it, red before the code and
  green after (`ai_tmp/T12/red.txt` and the final run); the reconciliation line shows
  zero uncovered; every extended test is re-hashed in the ledger with its note; every
  obligation dropped from the owned list is in the hand-back notes with its reason.
- The `Politeness` guarantee and the exit-1 cases have their named tests in
  `tests/test_pace.py`; no test sleeps for real. No test calls `time.sleep(`
  (`rg -n 'time\.sleep\(' tests; test $? -eq 1`), and the only test file naming
  `SystemTimer` is `tests/test_pace.py`, whose `test_system_timer_delegates_to_time`
  patches `pace.time.sleep` and `pace.time.monotonic` first
  (`test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py`). The one other test in
  which `SystemTimer` waits, the `CliRunner` exit-1 scenario, reaches it through
  `rovo.cli` and patches `pace.time.sleep` first; the earlier `CliRunner` syncs reach it
  without a wait (Facts). Positive control: `rg -n 'time\.sleep|SystemTimer' src`
  prints `pace.py` and `cli.py`. The installed-script scenario sleeps inside the `rovo`
  process, never in the test.
- The `NotInThisSlice` raises in `src/` are T11's set minus `DenyAllWhenRobotsRefused`
  and `HttpRetry`, plus the last-try 429 under `classify_block`, `BreakerTrips` and
  `RetireHostOnLongRetryAfter` in `pace.fetch_resource` (a robots.txt try past
  `retry_after_cap`) and `RetireHostOnLongCrawlDelay` (an honoured Crawl-delay past
  `retry_after_cap`) (`rg -n 'NotInThisSlice\(' src` compared with the same at
  `2658231`, the difference quoted).
- `.allium-loop/T12-robots-politeness.witness.json` exists with `"verdict": "PASS"`, and
  the ledger validates against `ledger.schema.json`.
- `just check-specs` and `just analyse-specs` pass with `docs/specs/` unchanged
  since `fa096c4`, the maintainer's answer to review T12-2-r3 C1
  (`git diff --stat fa096c4 -- docs/specs` empty); the base moved from `71b5b0f` through
  `f547525` (the `index.html` fold) to `fa096c4`.
- `protego` is a runtime dependency with a compatible range whose lower bound is the
  locked version and its decision 0005 note beside it; `just lock-check` passes; `protego`
  is imported only under `src/rovo/_crawl/` (`rg -n 'protego' src` prints only files
  there) and `urllib.robotparser` nowhere in `src` (`rg -n 'robotparser' src; test $? -eq 1`).
- `import rovo` loads no module outside the standard library and `rovo`; `__all__` is
  `["__version__"]`; `just wheel-smoke` passes with the new package-file count.
- `just coverage` stays at or above the floor of 95.
- `just check-docs` and `just check-agents` pass; `docs/reference/cli.md` describes what
  `rovo sync` now does.
- Both adversarial reviews ran (§14) and their records are in the hand-back notes.
- `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty after the commit.

## Verification

```sh
just plan-spec crawl > ai_tmp/T12/plan-spec-crawl.txt
just plan-spec rovo > ai_tmp/T12/plan-spec-rovo.txt
just plan-spec mirror > ai_tmp/T12/plan-spec-mirror.txt
just plan-spec convert > ai_tmp/T12/plan-spec-convert.txt
git diff --stat <the answers' Spec: commit> -- docs/specs
just py-test tests/test_crawl.py tests/test_pace.py tests/test_report.py tests/test_slice_boundaries.py -ra
{ time just py-test tests/e2e -ra; echo "exit $?"; } 2>&1 | tail -6
just py-lint
just py-typecheck
just coverage
just lock-check
just wheel-smoke
rg -n 'protego' src  # only src/rovo/_crawl/ files
rg -n 'robotparser' src; test $? -eq 1  # only "no match" passes
uv run --frozen python -I -c "import rovo, sys; print(sorted(m for m in sys.modules if not m.startswith(('rovo', '_')) and m not in sys.stdlib_module_names))"
rg -n 'NotInThisSlice\(' src  # compared with the same at 2658231
rg -n 'time\.sleep|SystemTimer' src  # positive control: prints pace.py and cli.py
rg -n 'time\.sleep\(' tests; test $? -eq 1  # only "no match" passes
test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py  # the one patched delegation test
rg -n "politeness slice" src; test $? -eq 1  # only "no match" passes
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
after; the timer seam and limiter as built and any departure from steps 1 and 2; the red
run and the reconciliation line; every extended or re-propagated test, its origin slice
and its new hash; every obligation dropped from the owned list and why; the weed verdict
and the witness verdict, each round; both adversarial reviews' records (§14); the one
batched needs-user question with every gap found while planning, implementing, in weed
or in review, and the maintainer's answer if one arrived; the verification output, each
headed by its commit.

## Open points

- **The one batched needs-user question: answered.** The maintainer answered points 1
  to 8 before any code; the answer moved the specification (the answers' `Spec:`
  commit, Context) and adds one dependency (step 1a). Line numbers are at that commit.
  Every later gap still joins a new batched question, never resolved in code.
  - Points 1 and 2: **Robots parsing: a parser dependency.** `robots_allows` matches as RFC 9309
     says: the longest matching path wins, Allow wins a tie, `*` and a final `$` are
     wildcards (`crawl.allium`, `FetchSitemap` guidance 924 to 933). `robots_crawl_delay`
     reads a decimal number of seconds, null when absent or not a number
     (`AdoptRobotsRules` guidance 829 to 832). The parser is `protego>=0.7.0,<0.8`
     (`ai_tmp/T12/robots-parser-choice.md`), imported only inside `rovo._crawl` (step 1a).
  - Point 3: **`Crawl-delay: 0` adds no delay.** The rate is unchanged (no `1 / 0`) and
     `crawl_delay` keeps its value (`AdoptRobotsRules` 818 to 823, guidance 828 to 829).
  - Point 4: **No burst.** The starts of two requests to one host name are at least
     `1 / host.rate` apart, and at least `host.crawl_delay` apart when Crawl-delay is
     honoured, robots.txt and retries included (`AttemptTier` guidance 1320 to 1324).
  - Points 5 and 6: **robots.txt retries behave exactly like page retries.** Each retry raises
     `HostBackedOff` and pauses the host as `HttpRetry` does; each try carrying a
     Retry-After on a 429 or 503 counts toward `retry_after_honored` as `CountRetryAfter`
     does; a Retry-After past `retry_after_cap`, on any try, retires the host for the
     run as `RetireHostOnLongRetryAfter` does, and that answer stands (`FetchRobots`
     772 to 781 and guidance 796 to 806; cross-references at 490 to 491, 1419 to 1420,
     1423 to 1426 and 1450 to 1452). This slice realises the first two (Facts; tested in
     `tests/test_pace.py`, since no plan-spec id covers them); the retirement is a
     breaker trip, the breaker slice's, so the guard
     `NotInThisSlice("RetireHostOnLongRetryAfter")` stays in `pace.fetch_resource`
     (Context row "Outside", item 2). The trip raises `BreakerTripped`, which
     `rovo.allium`'s `AnnounceTrip` turns into `breaker_tripped` and exit 3: a
     consequence the breaker slice inherits.
  - Points 7 and 8: **Batches run sequentially; nothing is printed without `json_events`.**
     `SelectBatch`'s guidance now says the batch may run concurrently up to the per-host
     limits, and that one row at a time respects `concurrency_per_host` (1160 to 1162);
     whether and when a batch should run concurrently across hosts is a new `open
     question` (`crawl.allium` 2063), recorded at the maintainer's request and in the
     ledger's `open_questions`. Without `json_events`, `ProgressReported` has no sink and
     nothing is printed (`rovo.allium`, `ProgressOnRequest`, 937 to 938).
- **The second batched needs-user question: answered at `71b5b0f`** (raised by
  propagate tick 1, its item 3 escalated by implement tick 2 and weed ticks 1 to 4;
  `ai_tmp/T12/spec-cap-report.md`; line numbers at `71b5b0f`).
  1. **A Retry-After on any retryable answer lengthens the wait** (a 429 or any 5xx,
     `HttpRetry` guidance 1451 to 1456). The code already does this.
  2. **Sitemap retries** through `fetch_resource`: carried to T13's batched question.
  3. **A Crawl-delay past `retry_after_cap` is never adopted** (`AdoptRobotsRules` 810 to
     852): `robots_crawl_delay_exceeds` compares the number as written and never builds
     a duration, so `Crawl-delay: 1e15` cannot overflow; a delay equal to the cap is
     adopted. The new rule `RetireHostOnLongCrawlDelay` (857 to 876) retires the host
     when Crawl-delay is honoured, as `RetireHostOnLongRetryAfter` does; its four
     obligations and the trip are the breaker slice's (T18), so this slice raises
     `NotInThisSlice("RetireHostOnLongCrawlDelay")`. Reusing `BreakerTripped` means the
     breaker slice exits `blocked` (3) there, as for a long Retry-After.
  New, recorded for T13's batched question and not resolved here:
  `retry_after_honored` is still counted only for a 429 or 503 (`CountRetryAfter`,
  `may_carry_retry_after`, and `FetchRobots`' guidance), while a Retry-After on a 500 or
  502 now lengthens the wait uncounted.
- **Review finding B2 (the `index.html` fold): answered at `f547525`** (maintainer;
  `ai_tmp/T12/spec-fold-report.md`). `robots_allows` honours the fold exactly as
  protego 0.7.0 does (`FetchSitemap` guidance 962 to 979): an `Allow` path ending in
  `/index.html` with no final `$` also allows its directory, as though `index.html` were
  replaced by `$`, so under `Disallow: /private/` the identity `/private/` is allowed and
  `/private/?a=1` is not. `index.htm`, `INDEX.HTML`, an `Allow` with a final `$` and
  `Disallow` lines never fold. The code passes already (protego's `can_fetch`);
  `tests/test_pace.py` asserts each case (propagate tick 6). The change is guidance only:
  375 obligations, identical ids (`ai_tmp/T12/spec-fold-obligations-diff.md`); every
  `crawl.allium` line after old 970 moved down 9.
- **Review finding T12-2-r3 C1 (the literal-`$` copy): answered at `fa096c4`**
  (maintainer, escalated by witness 9; `ai_tmp/T12/spec-protego-report.md`, probe
  `ai_tmp/T12/dollar-probe/probe-output.txt`). `robots_allows`, the robots parsing it
  rests on and the choice of group are RFC 9309 matching as protego implements it in the
  pinned range `protego>=0.7.0,<0.8` (`FetchSitemap` guidance 963 to 1003); moving the
  pin or the parser is a specification change, and the header's Excludes now excepts
  robots matching (26 to 29). The `index.html` fold (978 to 986) and the literal-`$`
  copy (987 to 1003) are listed as consequences: a line ending in `$` also matches as a
  prefix with that `$` written `%24`, and a `$` in a request path is compared as `%24`,
  so under `Disallow: /private/` the line `Allow: /private/$` allows `/private/$secret`
  and `/private/%24secret`, and `Disallow: /x$` disallows `/x$y`; the fold's line gets
  no copy. A divergence between literal RFC 9309 and protego 0.7 is therefore no defect;
  only one between `robots_allows` and protego's own answer, or in the Crawl-delay read,
  is. The code passes already (protego's `can_fetch`); `tests/test_pace.py` asserts each
  case (propagate tick 7, five scratch mutants show each row non-vacuous). The change is
  guidance only: 375 obligations, identical ids
  (`ai_tmp/T12/spec-protego-obligations-diff.md`); every `crawl.allium` line after old
  26 moved down 1, and after old 977 down 27 in all.
- **`FeedBreaker` is realised here, not in the blocks and breaker slice.** Facts give the
  reason. If the maintainer prefers the breaker slice to own it, that slice's ticket
  takes the `Breaker` and `FeedBreaker` rows of step 3, and this slice instead stops the
  run at a transport failure that settles a walk.
- **`ReadRobotsBeforeSitemap` belongs to T13.** Context table; T13's ticket lists its six
  obligations and `rule-failure.FetchSitemap.6` as owned.
- **The second `crawl.allium` open question** (2062) is on this slice's path: a URL that
  fails on every sync. Its interim holds unchanged (Non-goals).
- **`NotInThisSlice`.** A development guard, not product behaviour: each later slice
  removes the raises it implements, and the last slice's review confirms none is left.
  This slice removes two and adds three (Acceptance criteria).
