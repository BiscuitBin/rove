---
id: T19
title: "The browser tier: render reasons, escalation from http to the browser, learned tiers, render_mode, the missing-engine refusal and rovo fetch"
status: open
depends_on: [T18]
parallel_with: []
branch: full-final-prototype
estimated_size: L
---

# T19: The browser tier: render reasons, escalation from http to the browser, learned tiers, render_mode, the missing-engine refusal and rovo fetch

## Context

T09 (`fd1b423`) to T18 (`7c49df8`) are slices 1 to 10. `rovo sync` reads robots.txt,
paces and retries, discovers through sitemaps and `llms.txt`, fetches the seeds and the
pages they link to, keeps each page through its lifecycle, converts it under every
catalogue profile, classifies blocks, trips a host's breaker or retires the host, writes
the indexes and `crawl-report.json`, and `rovo verify`, `rovo index` and `rovo report`
read the mirror offline. Every fetch is at the http tier. They fixed every pattern this
slice follows: the private subpackages `rovo._convert`, `rovo._mirror` and `rovo._crawl`
with `rovo._config`, `rovo._report` and `rovo._commands` above them (import direction
enforced by `tests/test_import_direction.py`), the `Fetcher` and `Timer` seams
(`FixedClock`, `SteppingTimer`, `FakeFetcher`, `ScriptedFetcher` in `tests/fakes.py`),
obligation-named tests (`test_<obligation id>`), the end-to-end harness `serve_site` in
`tests/e2e/conftest.py` (its `script=` and `always=` answers), the state files of
`docs/reference/mirror.md`, and the development guard `rovo._unfinished.NotInThisSlice`.
Read `tickets/T17-quality-gates.md` and `tickets/T18-blocks-breaker.md` (their Context
tables, Facts and Open points), `src/rovo/_crawl/run.py` (`fetch_entry` 1325,
`attempt_tier` 1359, `settle_walk` 1466, `stop_walk_on_tripped_host` 1489,
`convert_fetched` 1704, `render_reason_of` 1869, `drive_run` 1905, `_settle` 2050,
`load_frontier` 2100, `save_frontier` 2117, `_starting_tier` 2404, `_next_tier` 2413),
`src/rovo/_crawl/model.py` (`Frontier` 399, `Host` 649, `LadderWalk` 711,
`FetchAttempt` 751), `src/rovo/_crawl/pace.py` (`follow` 200, `fetch_resource` 280),
`src/rovo/_commands.py` (`sync` 90, `_start_problem` 150, `_tier_installed` 526),
`src/rovo/cli.py`, `tests/test_slice_boundaries.py`, `tests/e2e/test_harness.py`, the
`Justfile`'s `e2e-browser` recipe (140), `pytest.ini` and `pyproject.toml`'s `browser`
extra (61 to 67) before starting.

This is slice 11 of T08 to T20, run in this worktree on `full-final-prototype`. Until now
the browser tier is a stop: a walk whose http answer has a render reason under
`render_mode = auto` stops at `NotInThisSlice("Escalate")` (`run.py` 2067), and a walk
that starts at the browser under `render_mode = always` stops at
`NotInThisSlice("AttemptTier")` (1373). `rovo._commands.sync` takes a `NotInThisSlice`
as a stop, exits 1 and leaves the previous report. Already built and kept:
`render_reason_of` (1869, T09) sets `render_reason` on an unblocked ok http answer;
`RefuseMissingEngine` is a sync refusal (`_start_problem`, 199 to 206, T09 and T16), with
`tier_installed` the importability of `playwright` (`_tier_installed`, 526);
`ConvertFetched` adds `render_needed` to a page whose standing http attempt has a render
reason (1722), so `render_mode = never` already stores such a page flagged; `tier_hints`
is written as `[]` (`save_frontier`, 2131; `docs/reference/mirror.md` 121 to 122).
There is no `rovo fetch` command (`docs/reference/cli.md` 17). The `browser` extra pins
playwright 1.64.1 (`pyproject.toml` 61 to 67) and nothing imports it; it is installed in
this worktree's `.venv` with `uv sync --frozen --extra browser`, and Chromium (build 1248,
the headless shell) is in `~/Library/Caches/ms-playwright`, both maintainer-authorised.
CI runs `uv sync --locked` (`scripts/initialize.sh` 13), so CI has no playwright.
`just check` was green at `7c49df8` with playwright present
(`ai_tmp/T19/baseline-check.txt`), and `just e2e-browser -ra` ran the harness's one
browser test: `1 passed, 1475 deselected in 0.22s`.

The specification base is `7d01367`; `git diff --stat 7d01367 7c49df8 -- docs/specs` is
empty. Every specification line number below is at `7d01367`; every source line number
is at `7c49df8`.

### The specified path, and what this slice does with each rule on it

| Class | Rules |
| --- | --- |
| **Realised** (every branch reachable in this slice, or constructible on unit inputs where noted) | `crawl.allium` (lines at `e0f0c44`): `RenderReason` (198) and `RenderMode` (209); `Run.usable_tiers` and `highest_tier` (259 to 264) as a run reaches them; `TierHint` (382 to 390) and its `reprobe_due`, persisted in `frontier.json` (`Frontier`, 289 to 292: "every learned tier"); `Host.tiers_used` and `render_escalations` (419, 422) as a climb sets them; `LadderWalk` (472 to 492) its `escalated`, `ok_http` (484) and `render_needed` (486); `FetchAttempt` (494 to 532) its `render_reason` (500) and `wants_escalation` (522 to 527; the `unsuccessful_challenge` conjunct on constructed inputs only, owner testing being T20's); the rendering config (585 to 589: `render_min_text_chars`, `render_max_wait`, `large_raw_html`, `reprobe_every_syncs`) and `soft_render_gain` (597); `FetchEntry` (1579) its starting tier (guidance 1604 to 1610: `browser` under `render_mode = always`, else the later of the breaker's tier and the hint's tier unless `reprobe_due`, else `http`) and `start_from`; `AttemptTier` (1613) at the browser tier: `fetch_or_render` renders (guidance 1645 to 1697: robots, the limiter, Retry-After and the standard policy before redirects and browser subrequests; in-scope redirects; a render waits for the load state capped at `render_max_wait`; a navigation with no response is an error; every response counts toward `max_bytes`), `classify_block` on a render, no `render_reason` off http; `Escalate` (1853 to 1864); `SettleWalk` (1866 to 1901) its full `stands` (a browser attempt that failed outright falls back to `latest(walk.ok_http)`; `render_added_nothing` keeps `latest(walk.soft_suspect)`) and its `render_escalations` count; `StopWalkOnTrippedHost`'s escalation disjunct (1919 to 1921) as a run reaches it; `RememberRenderTier` (1956 to 1976); follow-up `e0f0c44`: `PauseHostOnRenderRetryAfter` (1833 to 1849), `CountRetryAfter` (1818 to 1830) and `retires_host` (508 to 512) at any tier, the escalation counted by `RetireHostOnLongRetryAfter` and `StopWalkOnTrippedHost`, and `fetch_resource`'s stop on its own tripped host (`FetchRobots` guidance 868 to 875); `ConvertFetched` (2142) its `render_needed` from a run (2153) and a page's `tier` `browser`; `LearnedTierIsNeverHttp` (2387 to 2390); `SyncControl` (2421 to 2442) its `EnginesRefusedBeforeRequests`; `SiteExchange` (2444) its `BrowserRendersContentNeverAnswersBlocks` (2473 to 2477) with the browser tier present. `rovo.allium`: `Configuration.needs_browser` (106) and `render_mode` (96, default 266); `RefuseMissingEngine` (388 to 413); `StartSync`'s engine guards (498 to 499); `HostReport.tiers_used` and `render_escalations` (129, 132) as a climb sets them; `RefuseOwnerTestingFetch` (890 to 898), `RefuseFetchOnBadConfig` (900 to 912, follow-up), `resolve_fetch_config` (73 to 80, follow-up), `RefuseMissingFetchTier` (914 to 928) and `FetchOneUrl` (930 to 956), the `rovo fetch` command; `MirrorCommands` (983) its `OperatorFetchesUrl` and `VerifyIndexReportExitCodes`' fetch codes (1013 to 1019). `mirror.allium`: `Tier` (251) and a page's `tier` (313, 868) set to `browser`. |
| **Traversed, nothing new to do** | `render_reason_of` (T09, 1917), kept as built; `classify_block` and `FeedBreaker` (T18) over a browser attempt; `DisposeFetch` (2034) for a browser attempt (blocked with tier `browser`, failed, converted); `HttpRetry` (1770), http only; `CountRetryAfter` (1818), at any tier since `e0f0c44` (Realised, follow-up); `RefusalsInOrder` (`rovo.allium` 1042), the engine refusal fifth as built; `TallyBlockedUrl` with a `browser` tier. |
| **Specified as owner-testing only** (on constructed inputs here, never from a standard run) | `wants_escalation` on a verdict other than `none` (it needs `protection_escalation`); `LadderWalk.soft_suspect`, `render_added_nothing` and `SettleWalk`'s `latest(walk.soft_suspect)` branch (a soft attempt wants escalation only under `protection_escalation`); `unsuccessful_challenge`. |
| **Later slices'** (T20) | Owner testing: `OwnerChallenge` and its rules, `PrepareAttempt`'s challenge offer, `BreakerEscalates`, the stealth tier and `RefuseMissingEngine`'s stealth half as anything but a refusal (no stealth engine exists, so `tier_installed(stealth)` is false), `RefuseInvalidOwnerRequest`, `SaveOwnership`, and the command-line spelling of `owner_test` for `rovo sync` and `rovo fetch`. |
| **Outside this slice; reaching one still stops the run** | Of the eight raises at `7c49df8` (`ai_tmp/T19/notinthisslice-7c49df8.txt`), this slice removes two, `AttemptTier` (`run.py` 1373) and `Escalate` (2067), and adds none. The six that stay are owner-testing branches, as many of each: `PrepareRun` (256), `Discover` (327), `EnqueuePageLinks` (735), `RefollowUnchangedLinks` (776), `StartRun` (1929) and `BreakerEscalates` (2075). None is reachable from `_commands.sync`, which refuses an owner-testing request before a run starts. |

### Facts a later reader would otherwise rediscover

- **The engine seam.** A `BrowserEngine` protocol lives in a new module
  `src/rovo/_crawl/browser.py`, beside a `PlaywrightEngine` that is its one real
  implementation; `tests/fakes.py` gains a `FakeEngine`. `playwright` is imported in that
  module alone, inside the engine's opening, through
  `importlib.import_module("playwright.sync_api")`, so `import rovo`, `rovo sync` under
  `render_mode = never`, `rovo verify`, `rovo index` and `rovo report` never load it, and
  `just py-typecheck` gives the same result with and without the extra (CI has none). An
  engine is opened once per run only when the run's `usable_tiers` include `browser`, or
  once per `rovo fetch --tier browser`, and closed when the run ends.
  `_commands.sync` and the new `_commands.fetch` take the engine as a seam beside
  `fetcher` and `clock` (an engine factory; `None` opens `PlaywrightEngine`), as
  `tier_installed` is already one.
- **A render makes no request of its own.** The engine executes the page; every request
  it would make, the navigation and every subrequest, is answered through a callback the
  crawl passes it, over the run's `Fetcher` (playwright's request routing fulfils each
  from it). So every request a render causes is made by the crawl: the navigation
  through `pace.follow`, exactly as an http try (in-scope redirects only, each hop's
  robots.txt read first, a disallowed hop or a hop onto a tripped host refused with the
  same error answers, the host's rate, Crawl-delay and pause, the `rovo` User-Agent, no
  validators: a conditional fetch is http only, `FetchEntry` 1609 to 1610); a subrequest
  to an origin of an allowed host after that origin's robots.txt is read (as a hop's
  is), under the host's limiter, aborted when robots.txt disallows it; a subrequest to
  any other origin aborted (the interim of Open points item 4). A redirected navigation
  must leave the browser at the URL the content came from, so relative subrequest URLs
  resolve against it: either each 3xx is fulfilled as given, so the browser asks for the
  next hop and the gate decides it, or the final `source_url` is the document's base;
  `tests/test_browser_engine.py` pins a relative subrequest after a redirect. Every
  response a render receives adds its bytes to the render's `size`, so to `run.bytes_fetched`. A render
  waits for playwright's `load` state, capped at `CONFIG.render_max_wait` (Open points
  item 3); a navigation that gets no response, or a render that does not reach `load` in
  time, is an answer with status 0 and the error set (`failed_outright`). The render's
  `SiteResponse` carries the navigation's status, headers, `source_url` and
  `redirect_hops`, and the rendered DOM as `markup`; `main_text` is set from it as for
  an http answer (T18's `main_text_length`), and `classify_block` reads it.
- **Escalation in a standard run.** `protection_escalation` is off, so `wants_escalation`
  holds only for an http attempt with a `render_reason`, a verdict of `none`, an ok HTML
  answer and no 304. Under `render_mode = auto` such an attempt climbs to the browser
  (`Escalate`, `walk.escalated`), the browser attempt is never retried (`retryable` is
  http only) and never has a `render_reason`, so it settles (`SettleWalk`): an ok render
  stands with tier `browser` and the host's `render_escalations` rises by one; a render
  that failed outright falls back to the walk's last ok http attempt, flagged
  `render_needed` (`ConvertFetched` 2153 at `e0f0c44`); a blocked render stands blocked with tier
  `browser`, never falling back. Under `render_mode = never` `usable_tiers` is `[http]`,
  `next_tier` is null and the http attempt stands flagged `render_needed` (built, T09).
  Under `render_mode = always` the walk starts at the browser and has no http attempt.
  A blocked http answer never escalates in a standard run
  (`BrowserRendersContentNeverAnswersBlocks`).
- **Learned tiers.** `RememberRenderTier` remembers the browser for a walk that
  escalated, whose standing browser attempt is ok and unblocked, and whose first render
  reason is `spa_shell` or `noscript_needs_js`, never `main_selector_absent` or
  `thin_text`: a `TierHint` keyed by host name and `path_pattern(identity)` (Open points
  item 5), created or updated with `learned_in_run`. `frontier.json`'s `tier_hints` holds
  one row per hint, sorted by host name then pattern (`host_name`, `path_pattern`,
  `tier`, `learned_in_run`), read back by `load_frontier`. `FetchEntry` starts a walk at
  the hint's tier unless `reprobe_due(run.id)`, when it probes http again: a reprobe that
  escalates again renews `learned_in_run`, and one that does not leaves the hint as it
  was, so every later run probes http until one escalates (the hint is never deleted; no
  rule deletes one). A hint is never `http` (`LearnedTierIsNeverHttp`).
- **`rovo fetch URL [--tier TIER]`.** `RefuseOwnerTestingFetch` exits 2 with no request
  for `--tier stealth` or a URL that is not http(s); its `owner_test` disjunct is reached
  through `_commands.fetch`'s `owner_test` parameter only, since the command line spells
  no owner option until T20. `RefuseMissingFetchTier` exits 2 with no request for
  `--tier browser` when the browser tier is not installed. Otherwise `FetchOneUrl`
  fetches one page with `fetch_one(url, tier, resolve_config(""))`: no `rovo.toml` is
  read; the configuration is the built-in defaults with the `ROVO_` variables layered
  over them (`resolve_config`'s layers with no file, Open points item 2); the profile is
  the one the catalogue picks by host (`profile_for(url, None)`); the scope is
  `initial_scope(url, profile)`, for redirects; the policy is the standard one. The URL's
  origin's robots.txt is read first, every request is paced as a sync's, and a Retry-After
  is honoured and retried as `HttpRetry` does. The walk's tiers are `[tier]` when a tier
  is named and `[http]` otherwise, with no escalation (Open points item 1). An ok,
  unblocked HTML answer is converted under the profile and its Markdown body, without
  frontmatter, is printed to standard output, exit 0; a robots refusal, a block, a
  non-HTML answer or a failed fetch prints no page and exits 1 (`VerifyIndexReportExitCodes`,
  `rovo.allium` 1013 to 1019 at `e0f0c44`). It writes no file: no mirror, report,
  frontier or run, in memory only. **Superseded at `e0f0c44`** (Open points item 2,
  answered): `rovo fetch` takes `--config PATH`; the configuration is
  `resolve_fetch_config` (defaults, the file's shared sections, its `[fetch]`
  `render_mode` and `profile`; no `ROVO_` variables), a bad one refused with exit 2
  (`RefuseFetchOnBadConfig`); with no `--tier` the walk's tiers follow `render_mode` as
  a sync's do, and with `--config` the file's `[scope]` bounds redirects.
- **`tier_installed`.** Kept as built at T16: the browser tier is installed when
  `playwright` is importable; the stealth tier never is. A missing Chromium binary is not
  detected before the run: the first render fails outright (Open points item 6).
  **Superseded at `e0f0c44`** (item 6, answered): installed is the package and its
  Chromium binary (`missing_browser_piece`, a seam), refused up front with a message
  naming the missing piece and both fixes.
- **Browser tests outside `just check`.** With playwright in `.venv`, the tests marked
  `browser` would launch Chromium inside `just check` and `just coverage`, where they
  only skip without the extra today. `pytest.ini`'s `addopts` gains `-m "not browser"`,
  which the `e2e-browser` recipe's `-m browser` overrides (pytest keeps the last `-m`),
  so `just check` and `just coverage` deselect them on every machine and
  `just e2e-browser` runs exactly them. The `PlaywrightEngine` adapter stays thin and is
  covered in `just check` by unit tests over a stub `playwright.sync_api` module
  (`monkeypatch.setitem(sys.modules, ...)`), not by an omission from coverage.
- **The obligation source.** `just plan-spec <module>` over `docs/specs/<module>.allium`
  at `7d01367`, written to `ai_tmp/T19/plan-spec-<module>.txt` (its echo line to
  `ai_tmp/T19/plan-spec-<module>.err`): crawl 391, rovo 169, mirror 201, convert 47
  obligations. The obligations with no test named after them at `7c49df8` are in
  `ai_tmp/T19/uncovered-<module>.txt` (crawl 84, rovo 29, mirror 14, convert 0, by
  `ai_tmp/T19/uncovered.py`); the owned set of step 3 is `ai_tmp/T19/owned.json` (44, by
  `ai_tmp/T19/owned.py`, which checks each id is in the plan and uncovered); the
  `NotInThisSlice` raises at `7c49df8` are in `ai_tmp/T19/notinthisslice-7c49df8.txt`.

## Goal

From a clean checkout, against served fixture sites, `rovo sync` under
`render_mode = "auto"` renders a page whose http answer is an SPA shell or asks for
JavaScript in the browser, stores the rendered page with tier `browser`, counts the
escalation in the report and remembers the tier for the page's path pattern, so the next
sync starts that page at the browser; under `render_mode = "always"` every page starts at
the browser; under `"never"` such a page is stored from http flagged `render_needed`; a
sync that needs a browser with no engine installed is refused with exit 2 before any
request; every request a render causes passes robots.txt and the host's limiter; and
`rovo fetch URL [--tier http|browser]` prints one page's Markdown and writes nothing.
`just e2e-browser` renders a JavaScript-only fixture page in a real Chromium. Every owned
obligation listed under Steps has a test named after its id, red before the code (or
recorded green at its first run where the behaviour already exists, with a ledger note);
every re-propagated test is re-hashed with its ledger note; no test this slice adds or
edits sleeps for real; `just check` is green and browser-free; the Allium loop's witness
record says `PASS`.

## Non-goals

- No owner testing, interactive challenge, `BreakerEscalates`, stealth tier or stealth
  engine, and no command-line owner option for `rovo sync` or `rovo fetch` (T20).
- No escalation in `rovo fetch` and no browser subrequest outside the allowed hosts'
  origins until the maintainer answers Open points items 1 and 4.
- No `playwright install`, `just lock`, `just sync` or `just install-allium`: the engine
  and Chromium are already installed. No new dependency and no change to `uv.lock`: the
  `browser` extra's range stays; only its comment ("Imported by nothing yet.") moves.
- No change to the public API: `__all__` stays `["__version__"]`, so
  `docs/reference/api.md` does not move. No harness change: `tests/e2e/conftest.py` is
  read, not changed.
- No new `rovo.toml` key: `render_mode` exists. No decision record changes.
- No specification change: `docs/specs/` is read, not edited. A specification gap found
  while planning, implementing or in weed is never resolved in code or in the
  specification: it joins the one batched needs-user question (Open points) and the
  ledger's `open_questions`.
- No adversarial review checkpoint in this slice.
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `src/rovo/_crawl/browser.py` | new | the `BrowserEngine` protocol, `PlaywrightEngine` (the one module that imports playwright, through `importlib`), the request callback a render is answered through, the subrequest gate (Facts); follow-up `e0f0c44`: the engine probe (`playwright_importable`, `chromium_executable`, `missing_browser_piece`) |
| `src/rovo/_crawl/run.py` | shared, own lines | `attempt_tier` at the browser tier (`fetch_or_render` through the engine) and its `NotInThisSlice` gone; `escalate` (`Escalate`) in `_settle` where `NotInThisSlice("Escalate")` was; `settle_walk`'s full `stands` and its `render_added_nothing` guard; `remember_render_tier` (`RememberRenderTier`) after `feed_breaker`; `_starting_tier` reading the hint and `reprobe_due`; `path_pattern`; `tier_hints` encoded and decoded in `save_frontier` and `load_frontier`; the engine passed through `drive_run`, `fetch_entry` and `_settle`; `fetch_one` (`FetchOneUrl`'s black box); the docstrings that call the browser tier a later slice's; follow-up `e0f0c44`: `pause_host_on_render_retry_after`, `count_retry_after` and `retires_host` at any tier, a render escalation counted on retirement and on a tripped-host stop, `fetch_one` taking the configuration's tiers and scope |
| `src/rovo/_crawl/model.py` | shared, own lines | `TierHint` and `Frontier.tier_hints`; nothing else unless step 4 shows a field missing; follow-up `e0f0c44`: `FetchAttempt.retires_host` loses `tier = http` |
| `src/rovo/_crawl/pace.py` | shared, own lines | only what the subrequest gate needs from `follow` or the limiter, with its docstring; follow-up `e0f0c44`: `fetch_resource` makes no retry or hop once its own host has tripped (Open points item 1) |
| `src/rovo/_commands.py` | shared, own lines | the engine seam on `sync`; `fetch` (`RefuseOwnerTestingFetch`, `RefuseMissingFetchTier`, `FetchOneUrl`); the module docstring; follow-up `e0f0c44`: `RefuseFetchOnBadConfig`, `config_path`, the missing-engine message naming the piece and both fixes, `_tier_installed` through the probe |
| `src/rovo/_config.py` | shared, own lines (follow-up `e0f0c44`) | `resolve_fetch_config` and the `[fetch]` section, which `resolve_config` accepts and ignores |
| `src/rovo/cli.py` | shared, own lines | the `fetch` command (`URL`, `--tier`), its lazy imports, the real `HttpxFetcher` and `SystemTimer` as `sync` builds them; follow-up `e0f0c44`: `--config PATH` |
| `pyproject.toml` | shared, own lines | the `browser` extra's comment only: playwright is imported by `rovo._crawl.browser`; the range and `uv.lock` unchanged |
| `pytest.ini` | shared, own lines | `addopts` gains `-m "not browser"`, with a comment saying `just e2e-browser` overrides it (Facts) |
| `scripts/wheel_smoke.py` | shared, own lines | `rovo/_crawl/browser.py` in the expected package files and "twenty-eight" becomes "twenty-nine" |
| `tests/test_escalation.py` | new | the `crawl` and `mirror` obligations of step 3 and the guarantees; no e2e module is named `test_escalation.py` |
| `tests/test_fetch_command.py` | new | the `rovo` fetch obligations and `MirrorCommands`' of step 3; the installed `rovo fetch` of a non-http URL exiting 2 |
| `tests/test_browser_engine.py` | new | `PlaywrightEngine` over a stub `playwright.sync_api` module, the subrequest gate, the render's `size`, the `load` wait and its cap |
| `tests/test_commands.py` | shared, own lines | the `RefuseMissingEngine` obligations of step 3 |
| `tests/test_slice_boundaries.py` | shared, own lines (re-propagated) | `test_escalation_to_the_browser_stops_the_run` (T09) and the browser half of `test_a_browser_attempt_stops_and_a_tripped_hosts_rows_are_skipped` (T12, re-propagated by T18) become their behaviour, renamed, with ledger notes naming their origin slices and old names |
| `tests/test_regressions.py` | shared, own lines (re-propagated) | `test_a_stopped_finalisation_persists_no_done_row` (T09, re-propagated by T15, T16 and T18): no later slice's branch is reachable from a standard sync after this slice, so its stop is injected with `RaisingFetcher` (`tests/fakes.py`) raising `NotInThisSlice` on the request for `next.html`, which `drive_run` lets escape, asserting no less than before; ledger note |
| `tests/test_crawl.py` | shared, own lines (re-propagated) | only a test the red run shows red because a walk can now climb or a hint is now saved, with a ledger note naming its slice; follow-up `e0f0c44`: T12's `CountRetryAfter` tests renumbered and the success test counting a render (hash-tracked by this ledger from then), and T12's `test_derived_FetchAttempt_retires_host` re-propagated to the tier-free `retires_host` (a render's answer past the cap retires the host) |
| `tests/test_tripped_discovery.py` | new (follow-up `e0f0c44`) | Open points item 1: a discovery fetch stops on its own tripped host; hash-pinned in this slice's ledger |
| `tests/fakes.py` | shared, own lines | `FakeEngine`: renders from a map of URL to rendered markup, answering the navigation through the crawl's callback so the request is made and logged; records each render; hash-tracked; follow-up `e0f0c44`: `probe_engine` |
| `tests/test_render_regressions.py` | new | one test per divergence weed finds; hash-pinned in this slice's ledger |
| `tests/e2e/test_render_sync.py` | new | the `just check` end-to-end scenarios (Acceptance criteria): a served site, a real `HttpxFetcher`, `FakeEngine`; no unit test is named `test_render_sync.py` |
| `tests/e2e/test_browser_sync.py` | new | the real-browser scenarios, every test marked `browser`, `PlaywrightEngine` over a served site; run by `just e2e-browser` only; no unit test is named `test_browser_sync.py` |
| `tests/fixtures/sites/spa/` | new | `robots.txt` (`User-agent: *`, `Disallow: /private/`, no Crawl-delay, no `Sitemap:`); `guide/start.html` (a prose page in `<main>`) linking `guide/app.html` and `guide/plain.html`; `guide/app.html`, an SPA shell (`<div id="root"></div>`, a root `_SPA_ROOTS` names, so its render reason is `spa_shell`) whose inline `<script>` writes a `<main>` with an `<h1>` and prose over `render_min_text_chars`, and which also loads `guide/style.css` and `/private/tracker.js`; `guide/app.rendered.html`, the DOM `FakeEngine` returns for it; `guide/plain.html`, a prose page; `guide/style.css`; two-space indentation per `.editorconfig` |
| `docs/reference/cli.md` | shared, own lines | a `rovo fetch` section (usage, `--tier`, the refusals, exit codes 0, 1 and 2, nothing written); line 17's "later command" sentence; `rovo sync` under each `render_mode`, the escalation, the learned tier and the subrequest rules; 328 to 329 and the exit-code table's 1 keep only owner testing; follow-up `e0f0c44`: `--config`, the missing-engine refusal and its message (152 to 153, 274, 345 to 346, 367 to 382) |
| `docs/reference/mirror.md` | shared, own lines | `tier_hints` (121 to 122); a page's `tier` `browser`; `render_needed` from `render_mode = never` or a failed render; the report's `tiers_used` and `render_escalations`; 451 keeps only owner testing; follow-up `e0f0c44`: the `[fetch]` section and the fetch's layers (49 to 80) |
| `docs/reference/testing.md`, `docs/reference/configuration.md`, `docs/reference/commands.md` | shared, own lines | the `browser` marker deselected from `just check` (`pytest.ini`), `FakeEngine`, the two e2e modules and the fixture site; `commands.md`'s `e2e-browser` row only if its text turns false |
| `docs/project/purpose-and-scope.md`, `docs/project/repository-map.md`, `docs/explanation/architecture.md` | shared, own lines | line 30 of purpose-and-scope (the browser tier no longer stops a sync); the new module and test files |
| `README.md`, `AGENTS.md` | shared, own lines | only the sentences step 6's search shows false (AGENTS.md's "today `rovo init` and `rovo sync`" and "`_commands` (`init`, `sync` and `index`)"); `AGENTS.md`'s required phrases stay in always-visible text |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` Added entry: the browser tier, escalation, learned tiers, `rovo fetch`; follow-up `e0f0c44`: `--config`, the fail-fast engine check, a render's Retry-After |
| `tickets/README.md`, `tickets/T19-browser-tier.md` | ticket | index row, graph, slice bullet, this ticket |
| `tickets/T18-blocks-breaker.md`, `.allium-loop/T18-blocks-breaker.json` | ticket; gitignored (follow-up `e0f0c44`) | T18-3 item 1 marked ANSWERED, on the follow-up task's instruction |
| `.allium-loop/T19-browser-tier.json`, `.allium-loop/T19-browser-tier.witness.json` | gitignored | the loop ledger and the witness record; never committed |

`uv.lock`, `.coveragerc`, `ruff.toml`, `mypy.ini`, `Justfile`, `src/rovo/__init__.py`,
`src/rovo/_exit.py`, `src/rovo/_report.py`,
`src/rovo/_unfinished.py`, `src/rovo/_crawl/fetch.py`, `src/rovo/_crawl/sitemaps.py`,
`src/rovo/_mirror/`, `src/rovo/_convert/`, `tests/e2e/conftest.py`,
`tests/test_import_direction.py`, `docs/manifest.yml`, `docs/decisions/` and
`docs/specs/` are read, not changed. A file not in this table that turns out to need a
change is added to the table in the same change with its reason, or handed back if it is
a decision record, a specification or a dependency.

## Steps

0. `just check` baseline on the untouched worktree at `7c49df8` plus this ticket, last
   line quoted, and `( set -o pipefail; { time just py-test tests/e2e -ra; } 2>&1 | tail -6 )`
   with its wall time. Scratch output goes in `ai_tmp/T19/`. Write `just plan-spec
   <module>` for each of `crawl`, `rovo`, `mirror` and `convert` to
   `ai_tmp/T19/plan-spec-<module>.txt`; run `ai_tmp/T19/uncovered.py` and
   `ai_tmp/T19/owned.py`, and confirm the 44 ids. Confirm
   `ai_tmp/T19/notinthisslice-7c49df8.txt` is `rg -n 'NotInThisSlice\(' src` at
   `7c49df8`. Run `just e2e-browser` once, before any change, and quote its result (the
   harness's `test_browser_tier_is_importable` passes). Create the ledger
   `.allium-loop/T19-browser-tier.json` (propagate's first tick creates it) against
   `allium-skill-reference/allium/schemas/ledger.schema.json`, shaped like T18's: `goal`
   `"T19-browser-tier"`, `mode` `"spec-first"`, `specification_base` `7d01367`,
   `obligation_source` the four files, and `open_questions` holding the six
   specification open questions verbatim (none on T19's path but the third
   `crawl.allium` one, 2514, whose interim, one row at a time, decides that a render
   runs while no other row of the batch is fetched), the carried T18-3 item OPEN as
   item 1 of the T19 batched question, the carried T18-2 residue (a challenge waiting
   when its host trips) OPEN and carried to T20, and every item of the T19 batched
   needs-user question (Open points) OPEN. Read `.agents/skills/propagate/SKILL.md`,
   `.agents/skills/weed/SKILL.md`, `.agents/skills/witness/SKILL.md` and
   `.agents/skills/python-change/SKILL.md` before step 3.

1. **The engine and the climb.** `src/rovo/_crawl/browser.py` and the seam (Facts);
   `attempt_tier` at the browser tier; `escalate` and the full `settle_walk` in `_settle`
   (`RetireHostOnLongRetryAfter`, `StopWalkOnTrippedHost`, `HttpRetry`, then `Escalate`
   or `SettleWalk`, in that order); `remember_render_tier`; `_starting_tier` with the
   hint and `reprobe_due`; `tier_hints` persisted. Every cap, size and count comes from
   `CONFIG` or the run's policy, never a literal. `pytest.ini`'s `-m "not browser"`
   lands in this step, before any browser-marked test exists.

2. **The command.** `_commands.sync` opens an engine only when the run's usable tiers
   include `browser` and closes it when the run ends; `_commands.fetch` and `rovo fetch`
   in `cli.py` (Facts); `fetch_one` in `run.py`. Each function returns `None`, `False` or
   an empty result when its guards do not hold.

3. **Tests first, from the obligations** (the `propagate` skill, spec-first). Write a
   failing test for each owned obligation below into the test file named, named
   `test_<obligation id with dots and hyphens as underscores>`, its docstring quoting the
   obligation's description from the plan-spec file. Each `rule_failure` test makes
   exactly one `requires` clause false. Generated tests satisfy EditorConfig
   (indentation in 4-space multiples in `*.py`, string literals included), ruff and
   mypy, since the gate stages them. Run `just py-test` and record the red run in
   `ai_tmp/T19/red.txt`, its summary line under `last_results.propagate` in the ledger.
   The seven `RefuseMissingEngine` tests and the config defaults may pass at their first
   run, the behaviour being built (T09, T16): record each as green at tick 1 with a
   ledger note, never as red before green. Record each generated, re-propagated or
   extended test file's SHA-256 under `generated_test_hashes`
   (`tests/fakes.py`, `tests/e2e/test_render_sync.py`, `tests/e2e/test_browser_sync.py`
   and `tests/test_render_regressions.py` included), and the reconciliation line
   (`N obligations, M covered, K uncovered`) over the owned set. A test changed after the
   red run is re-recorded: a new hash, `tick` incremented, a ledger note naming the test
   and why; never silently. An obligation a test cannot reach without a later slice's
   behaviour is not owned: move it to the hand-back notes with its reason rather than
   writing a vacuous test.

   Owned obligations, new in this slice (ids as `just plan-spec <module>` emits them at
   `7d01367`; 44):

   - **`crawl`** (26), in `tests/test_escalation.py`: `enum-comparable.RenderReason`,
     `enum-comparable.RenderMode`, `entity-fields.TierHint`,
     `projection.LadderWalk.ok_http`, `derived.LadderWalk.render_needed`,
     `entity-optional.FetchAttempt.render_reason`, `derived.FetchAttempt.wants_escalation`
     (its verdict and `unsuccessful_challenge` conjuncts on constructed inputs),
     `config-default.render_min_text_chars`, `config-default.render_max_wait`,
     `config-default.large_raw_html`, `config-default.reprobe_every_syncs`,
     `config-default.soft_render_gain`, `rule-success.Escalate`,
     `rule-failure.Escalate.1` (the walk settled, the run ended, and the host tripped,
     each alone), `.2`, `.3`, `.4`, `.5` (`render_added_nothing` on a constructed walk
     with a soft-suspected attempt), `rule-success.RememberRenderTier` (created, and an
     existing hint updated), `rule-failure.RememberRenderTier.1`, `.2`, `.3`, `.4`,
     `invariant.LearnedTierIsNeverHttp` (after every rule that touches a hint, and after a
     `frontier.json` round trip), `surface-actor.SyncControl` and
     `surface-provides.SyncControl`.
   - **`rovo`** (17): in `tests/test_commands.py`, `rule-success.RefuseMissingEngine` and
     `rule-failure.RefuseMissingEngine.1` to `.6` (`.1` to `.5` each the earlier refusal
     or no mirror that precedes it, `.6` an installed engine, or `render_mode = never`,
     with `tier_installed` injected); in `tests/test_fetch_command.py`,
     `rule-success.RefuseOwnerTestingFetch` (`--tier stealth`, a non-http URL and an
     `owner_test` through `_commands.fetch`, each alone, no request),
     `rule-failure.RefuseOwnerTestingFetch.1`, `rule-success.RefuseMissingFetchTier`,
     `rule-failure.RefuseMissingFetchTier.1`, `.2`, `rule-success.FetchOneUrl`,
     `rule-failure.FetchOneUrl.1`, `.2`, `surface-actor.MirrorCommands` and
     `surface-provides.MirrorCommands` (`rovo fetch` completes the command set).
   - **`mirror`** (1), in `tests/test_escalation.py`: `enum-comparable.Tier`.
   - **`convert`**: none new.

   Follow-up at `e0f0c44` (the maintainer's answers; `ai_tmp/T19/followup/owned.json`,
   55): **`crawl`** gains `rule-success.PauseHostOnRenderRetryAfter` and
   `rule-failure.PauseHostOnRenderRetryAfter.1` to `.5` (`tests/test_escalation.py`);
   **`rovo`** gains `rule-success.RefuseFetchOnBadConfig`,
   `rule-failure.RefuseFetchOnBadConfig.1`, `.2`, `rule-failure.RefuseMissingFetchTier.3`
   and `rule-failure.FetchOneUrl.3` (`tests/test_fetch_command.py`), while
   `RefuseMissingFetchTier.2` and `FetchOneUrl.2` now name the `settings.valid` clause.
   T12's `CountRetryAfter` ids (`.3` to `.2`, `.4` to `.3`, `.2` removed) stay T12's,
   re-propagated in place with a ledger note.

   Re-propagated, not new (each re-hashed in this slice's ledger with a note naming its
   origin slice; T09's to T18's ledgers are never edited): the tests the Files touched
   table names in `tests/test_slice_boundaries.py` and `tests/test_regressions.py`, each
   now asserting the behaviour where it asserted the raise, asserting no less than before
   (the requests made, the files left); every other earlier test the red run shows red
   because a walk can now climb or a hint is now saved, each with only that expectation
   moved. Claim an earlier test "passes unedited" only where it does; the hand-back notes
   list every earlier test this slice edited.

   Guarantees and black boxes (no obligation id; hand-written), in
   `tests/test_escalation.py` unless named: the starting tier (always, hint, hint with
   `reprobe_due`, a reprobe that does not escalate leaving the hint, a breaker tier
   ignored outside owner testing); `path_pattern` (Open points item 5's interim);
   `SettleWalk`'s fallback (a render that failed outright stands the last ok http
   attempt, flagged `render_needed` after conversion; a blocked render never falls back;
   one render escalation per climbing walk, none for a walk that started at the browser);
   `BrowserRendersContentNeverAnswersBlocks` with the browser tier usable (a 403 or a soft
   verdict at http never climbs under `render_mode = auto`); `StopWalkOnTrippedHost`'s
   escalation disjunct now from a run (a walk whose host trips before its climb is
   `skipped_blocked` and the engine is never called); `max_bytes` counting a render's
   subrequests; a `TierHint` round trip through `frontier.json` with sorted rows; in
   `tests/test_browser_engine.py`, the request callback (the navigation through `follow`,
   a subrequest to an allowed origin after its robots.txt, a disallowed one aborted and
   never requested, an off-host one aborted, the host's limiter waited on, the `rovo`
   User-Agent), a navigation with no response as status 0 with an error, the wait capped
   at `CONFIG.render_max_wait`, the engine opened only when a usable tier needs it; in
   `tests/test_fetch_command.py`, nothing written under the current directory or any
   mirror, robots.txt read before the page, a blocked or non-HTML answer exiting 1 with
   nothing printed, and `--tier browser` rendering through `FakeEngine`.

   Not owned, and why, for the hand-back notes: every `OwnerChallenge` obligation,
   `entity-relationship.FetchAttempt.challenges`, `rule-*.BreakerEscalates`,
   `config-default.breaker_pause`, `config-default.min_host_rate`,
   `config-default.owner_challenge_timeout`, `invariant.BreakerNeverPassesHighestTier`,
   `enum-comparable.PolitenessControl`, `enum-comparable.StealthMode`, the `OwnerTesting`
   surface, `rule-*.RefuseInvalidOwnerRequest`, `rule-success.AnnounceOwnerWarning`, the
   `CrawlReport` owner optionals, `rule-*.SaveOwnership`,
   `derived.Mirror.has_declared_owner` and the other owner-testing obligations (T20);
   `enum-comparable.FrontierStatus`, `enum-comparable.RunKind`,
   `enum-comparable.RunMode`, `entity-relationship.Run.hosts`,
   `entity-relationship.Frontier.entries`, `when-presence.LadderWalk.standing`, the
   `LadderWalk` status edge and its rejected and terminal obligations,
   `entity-relationship.LadderWalk.attempts`, `surface-actor.SiteExchange`,
   `entity-fields.DocumentationSite`, `entity-fields.SyncRun`,
   `entity-relationship.Mirror.pages`, `entity-optional.Page.canonical_url`,
   `entity-optional.Page.frontmatter` and the `MirrorContents` and `PageIntake` surface
   obligations (reachable since T09 to T18, assigned by no ticket: carried to the last
   slice's review, named in the ledger).

4. **Escalation, learned tiers and the engine.** Steps 1 and 2. Unit cases on
   `FakeFetcher`, `ScriptedFetcher` and `FakeEngine` with `FixedClock` or
   `SteppingTimer`. `just py-test tests/test_escalation.py tests/test_fetch_command.py
   tests/test_browser_engine.py tests/test_commands.py tests/test_slice_boundaries.py
   tests/test_regressions.py tests/test_crawl.py`, then `just py-lint`,
   `just py-typecheck`, `just coverage` and `just wheel-smoke`, quoting its `api` line and
   the package-file count (twenty-nine, one more than at `7c49df8`).

5. **End to end.** The `spa` fixture site is committed under `tests/fixtures/sites/` and
   served with `serve_site("spa")`. The scenarios are the Acceptance criteria's; those
   that fetch run `rovo._commands.sync` or `rovo._commands.fetch` in process over a real
   `HttpxFetcher` with a `SteppingTimer` or `FixedClock`, which never sleep, and read
   requests off the server's log; `rovo init` runs through `CliRunner`.
   `just py-test tests/e2e -ra`, its wall time quoted beside step 0's, and its summary
   showing the browser-marked tests deselected. Then `just e2e-browser -ra`, its output
   and wall time quoted: every test in `tests/e2e/test_browser_sync.py` and the harness's
   `test_browser_tier_is_importable` pass, none skipped.

6. **Documents** (the `review-docs` skill). The pages of the Files touched table; find
   the sentences this slice makes false with
   `rg -n -i "browser|render|javascript|tier|later slice|fetch\b|not yet|exit 1" -g '*.md' -g '!tickets/**' -g '!allium-skill-reference/**' -g '!docs/specs/**' -g '!docs/decisions/**'`;
   `CHANGELOG.md` `Unreleased` gains one Added entry. Keep the required phrases of
   `AGENTS.md` in always-visible text. `just check-docs`, `just check-agents`, and
   `just lint`, whose hooks include markdownlint over this ticket.

7. **Witness** (the `weed` and `witness` skills). Run `weed` over `crawl`, `rovo` and
   `mirror` against the code, scoped to the owned and re-propagated obligations, the
   Realised rules of the Context table and the guarantees; record its verdict under
   `last_results.weed` and fix any code divergence, each with a regression test in
   `tests/test_render_regressions.py`. A divergence weed attributes to the specification
   is not fixed: it joins the one batched needs-user question. Then run `witness`
   non-interactively: it writes `.allium-loop/T19-browser-tier.witness.json` per
   `witness-result.schema.json`. The verdict must be `PASS`; a `FAIL` routes back per the
   skill, and the hand-back notes record each round. A batched question still OPEN does
   not block `PASS` unless it blocks an owned obligation; none of the T19 items does, each
   having an interim, and the witness escalates any new one that blocks.

8. Hand-back notes; `status: done`; `just check` ending with
   `All checks passed and the worktree is unchanged.`, `git status --short` empty after
   the commit. Commit on the branch.
   **Authorisation required**: pushing and opening the pull request.

## Acceptance criteria

The end-to-end scenarios that `just check` runs live in `tests/e2e/test_render_sync.py`;
the real-browser ones in `tests/e2e/test_browser_sync.py`, run by `just e2e-browser`.
Each sync scenario starts with `rovo init <base>guide/start.html <tmp>/out` and sets
`crawl.render_mode` with `set_key` (from `tests/test_commands.py`); every count and limit
the assertions use comes from `CONFIG`.

- **End to end, an SPA page escalates and its tier is learned**
  (`test_an_spa_shell_is_rendered_and_its_tier_learned`): under `render_mode = "auto"`
  with `FakeEngine` rendering `guide/app.html` as the committed
  `guide/app.rendered.html`, `rovo sync` exits 0 where at `7c49df8` it stopped at
  `Escalate` and exited 1: `pages/<host>/guide/app.md` holds the rendered heading, its
  frontmatter's `tier` is `browser` and `quality_flags` holds no `render_needed`;
  `start.md` and `plain.md` have tier `http`; the report's per-host row has
  `render_escalations: 1` and `tiers_used` `["browser", "http"]`; `frontier.json`'s
  `tier_hints` holds one row for the host with `tier: "browser"` and the run's id; the
  server's log holds `guide/app.html` twice (the http try and the render's navigation),
  after `robots.txt`. A second sync starts `app.html` at the browser: the engine renders
  it with no http try before it, so the log holds `guide/app.html` once more.
- **End to end, `render_mode = "never"`** (`test_render_mode_never_stores_the_http_answer_flagged`):
  the same site, no engine opened (the engine factory passed raises if called): exit 0, `app.md` from the http answer with
  `render_needed` in `quality_flags` and `low_confidence: true`, `tier_hints` empty.
- **End to end, `render_mode = "always"`** (`test_render_mode_always_renders_every_page`):
  every page is rendered and has tier `browser`; on a second sync `FakeEngine` records
  every navigation without validators (a conditional fetch is http only);
  `render_escalations` is 0 (no walk climbed).
- **End to end, no engine** (`test_a_sync_needing_a_missing_engine_is_refused`): under
  `render_mode = "auto"` with `tier_installed` reporting the browser absent, the sync
  exits 2, `crawl-report.json` is refused with `"configured tier is not installed"`, and
  the server's log is empty.
- **End to end, `rovo fetch`** (`test_rovo_fetch_prints_one_page_and_writes_nothing`):
  `_commands.fetch` of `<base>guide/plain.html` prints its Markdown body (its `<h1>` as a
  heading, no frontmatter) and exits 0; the server's log holds `robots.txt` then the
  page; no file is created under the test's directory. A URL under `/private/` exits 1
  and prints nothing, its page never requested; `--tier stealth` and an `ftp:` URL exit 2
  with an empty log; `--tier browser` with `tier_installed` reporting it absent exits 2
  with an empty log.
- **Real browser, an SPA page rendered in Chromium**
  (`test_chromium_renders_the_spa_page`, marked `browser`): under
  `render_mode = "auto"` with `PlaywrightEngine`, `rovo sync` exits 0, `app.md` holds the
  heading and prose the page's script wrote (absent from `app.html`'s source), its tier
  `browser`, `tier_hints` one row; the server's log holds `guide/style.css` and never
  `/private/tracker.js` (robots.txt disallows it, so the render's subrequest was aborted);
  every request the render caused arrived after `robots.txt`.
- **Real browser, `rovo fetch --tier browser`** (`test_rovo_fetch_renders_in_chromium`,
  marked `browser`): `_commands.fetch` of `<base>guide/app.html` with `PlaywrightEngine`
  prints the script-written heading and exits 0, writing no file.
- **End to end, earlier scenarios**: every module under `tests/e2e/` but the two new ones
  passes unedited, unless the ledger names an edit and why.
- `just e2e-browser -ra` passes with every browser-marked test run, none skipped, its
  output quoted in the hand-back notes; `just py-test tests/e2e -ra` deselects them.
- Every owned obligation in step 3 has a test named after it, red before the code and
  green after (`ai_tmp/T19/red.txt` and the final run), or green at tick 1 with its ledger
  note; the reconciliation line shows zero uncovered; every re-propagated test is
  re-hashed in the ledger with its note; every obligation dropped from the owned list is
  in the hand-back notes with its reason.
- No test this slice adds or edits sleeps for real; the suite's one real wait is T12's
  installed-script Crawl-delay scenario (`tests/e2e/test_polite_sync.py`), kept by
  design, and a real render's own wait for `load`, which `just check` never runs:
  `rg -n 'time\.sleep\(' tests; test $? -eq 1`,
  `test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py`, and
  `rg -n 'subprocess' tests/e2e/test_render_sync.py tests/e2e/test_browser_sync.py; test $? -eq 1`.
- `playwright` is imported by `src/rovo/_crawl/browser.py` alone (`_commands.py`'s
  `find_spec("playwright")` in `_tier_installed` finds it without importing it):
  `test "$(rg -l 'import_module\("playwright|^\s*(from|import) playwright' src --glob '*.py')" = src/rovo/_crawl/browser.py`.
- The `NotInThisSlice` raises in `src/` carry the `rule=` names of
  `ai_tmp/T19/notinthisslice-7c49df8.txt` less `AttemptTier` and `Escalate`, as many of
  each (`ai_tmp/T19/rules-expected.txt` and `ai_tmp/T19/rules-after.txt`, written by the
  Verification block, do not differ).
- Every fixture page the end-to-end scenarios serve is committed under
  `tests/fixtures/sites/spa/`: `rg -n 'write_text' tests/e2e/test_render_sync.py tests/e2e/test_browser_sync.py`
  names no `.html` file.
- `.allium-loop/T19-browser-tier.witness.json` exists with `"verdict": "PASS"`, and the
  ledger validates against `ledger.schema.json` with the T19 batched question's items
  OPEN and the carried items as Open points says.
- `just check-specs` and `just analyse-specs` pass with `docs/specs/` unchanged since
  `7d01367` (`git diff --stat 7d01367 -- docs/specs` empty).
- `import rovo` loads no module outside the standard library and `rovo`; `__all__` is
  `["__version__"]`; `just wheel-smoke` passes with twenty-nine package files.
- `just coverage` stays at or above the floor of 95, with no file omitted.
- `just check-docs` and `just check-agents` pass; `docs/reference/cli.md` documents
  `rovo fetch` and the browser tier under each `render_mode`; no page says the browser
  tier stops a sync.
- `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty after the commit.

## Verification

```sh
just plan-spec crawl > ai_tmp/T19/plan-spec-crawl.txt
just plan-spec rovo > ai_tmp/T19/plan-spec-rovo.txt
just plan-spec mirror > ai_tmp/T19/plan-spec-mirror.txt
just plan-spec convert > ai_tmp/T19/plan-spec-convert.txt
git diff --stat 7d01367 -- docs/specs
just py-test tests/test_escalation.py tests/test_fetch_command.py tests/test_browser_engine.py tests/test_commands.py tests/test_slice_boundaries.py tests/test_regressions.py tests/test_crawl.py tests/test_render_regressions.py -ra
( set -o pipefail; { time just py-test tests/e2e -ra; } 2>&1 | tail -6 )
( set -o pipefail; { time just e2e-browser -ra; } 2>&1 | tail -12 )
just py-lint
just py-typecheck
just coverage
just wheel-smoke
uv run --frozen python -I -c "import rovo, sys; print(sorted(m for m in sys.modules if not m.startswith(('rovo', '_')) and m not in sys.stdlib_module_names))"
test "$(rg -l 'import_module\("playwright|^\s*(from|import) playwright' src --glob '*.py')" = src/rovo/_crawl/browser.py
rg -o 'rule="[^"]+"' -N --no-filename ai_tmp/T19/notinthisslice-7c49df8.txt | rg -v '"(AttemptTier|Escalate)"' | sort > ai_tmp/T19/rules-expected.txt
rg -o 'rule="[^"]+"' -N --no-filename src | sort > ai_tmp/T19/rules-after.txt
diff ai_tmp/T19/rules-expected.txt ai_tmp/T19/rules-after.txt  # prints nothing
rg -n 'time\.sleep\(' tests; test $? -eq 1  # only "no match" passes
test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py
rg -n 'subprocess' tests/e2e/test_render_sync.py tests/e2e/test_browser_sync.py; test $? -eq 1  # only "no match" passes
just lint  # markdownlint over this ticket among the hooks
just check-specs
just analyse-specs
just check-docs
just check-agents
just check
git status --short
```

CI evidence exists only after the push, which is separately authorised; it goes in the
closing pull request's notes. CI has no playwright, so `just e2e-browser` is local
evidence only.

## Hand-back notes

To be written by the executing agent: the baseline, the e2e wall time and the
`just e2e-browser` result before and after; the engine, the request callback and the
subrequest gate, the climb, the learned tiers and `rovo fetch` as built, and any
departure from Facts and steps 1 and 2; the red run, the tests green at tick 1 and the
reconciliation line; every re-propagated test, its origin slice, its old name and its
new hash; every obligation dropped from the owned list and why; the weed verdict and the
witness verdict, each round; the one batched needs-user question with every gap found
while planning, implementing or in weed, and the maintainer's answer if one arrived; the
verification output, each headed by its commit.

## Open points

- **The T19 batched needs-user question: ANSWERED** (found while planning at `7d01367`,
  item 9 in weed; the maintainer answered on 2026-11-06, written into the specification
  at `e0f0c44`; `ai_tmp/T19/spec-answers/answers.md`). Each answer is built and pinned
  by the tests named in the ledger's `open_questions`.
  1. **Carried from T18 (T18-3 item 1): the discovery side of the tripped-host stop.**
     Stop, no retry: once a `fetch_resource`'s own host has tripped, its retry or hop is
     not made and the fetch ends with the answer it holds, the error `"redirect to a
     retired host"` for a refused hop, the retryable answer for a retry not made
     (`crawl.allium` `FetchRobots` guidance 868 to 875). Tests:
     `tests/test_tripped_discovery.py`.
  2. **`rovo fetch`'s tiers and configuration.** `rovo fetch URL [--tier T] [--config
     PATH]`: `resolve_fetch_config` reads the built-in defaults, then the file's shared
     sections, then an optional `[fetch]` section (`render_mode` and `profile` only; any
     other key is invalid), never a `ROVO_` variable; a sync ignores `[fetch]`; a bad
     configuration is refused with exit 2 (`RefuseFetchOnBadConfig`). `render_mode`
     means what it means for a sync, `--tier` runs that tier only, and with `--config`
     the file's `[scope]` bounds the redirects followed, else the URL's own host
     (`rovo.allium` 73 to 80, 900 to 957). Tests: `tests/test_fetch_command.py`.
  3. **The render's load state.** As built: the page's load state, capped at
     `render_max_wait` (`AttemptTier` guidance, 1681 to 1682).
  4. **Browser subrequests outside the allowed hosts.** As built for now (`AttemptTier`
     guidance, 1687 to 1693), with a new `crawl.allium` open question (2566, OPEN, below)
     as its interim.
  5. **`path_pattern`.** As built: the first two segments, the query dropped (375 to
     381).
  6. **`tier_installed(browser)`.** Fail fast: installed means the `playwright` package
     and its Chromium binary; a sync under `render_mode` auto or always, and `rovo
     fetch` with `--tier browser` or no `--tier` under an effective auto or always, are
     refused up front with exit 2, the message naming the missing piece and both fixes
     (`playwright install chromium`, or `render_mode = never`) (`rovo.allium` 403 to
     413, 914 to 929). The engine probe is a seam (`missing_browser_piece`), so no unit
     test needs a real Chromium.
  7. **Cookies a render earns.** As built: every request a render causes goes out on
     the run's http session; a cookie the page's script sets is not copied out (1683 to
     1686).
  8. **Undeclared helpers.** `starting_tier`, `first_render_reason` and
     `render_added_nothing` are in the black-box list (53 to 55).
  9. **A render navigation's Retry-After** (found in weed). Like http: it pauses the
     host (`PauseHostOnRenderRetryAfter`), counts toward `retry_after_honored`, and past
     `retry_after_cap` retires the host; `render_escalations` counts every escalation,
     one that retires its host or stops on a tripped one included.
- **The T19-2 batched needs-user question** (found while propagating the follow-up at
  `e0f0c44`; copied into the ledger's `open_questions`). Items 1 and 3 ANSWERED by the
  maintainer on 2026-11-06 (spec `39c1f9c`, recorded at T20,
  `ai_tmp/T20/spec-answers/answers.md`); item 2 stays as the maintainer's answer to T20
  item 6 leaves it ("stays as decided at T19"). No item blocks an owned obligation and
  none is pinned by a test.
  1. **ANSWERED:** no profile named in `[conversion]` or `[fetch]` means the catalogue's
     pick for the fetched URL's host, else `generic`, the interim as built. The question
     was: with `--config` and neither `[conversion]` nor `[fetch]` naming a profile, which
     profile converts the page: `resolve_config`'s default (the catalogue's pick for the
     file's first seed, else `generic`) or, as without `--config`, the catalogue's pick
     for the fetched URL's host? Interim: the catalogue's pick for the fetched URL's
     host, else `generic`.
  2. A valid `--config` whose `[crawl]` sets `robots = "ignore"` or `stealth_mode =
     "on"`: no fetch rule refuses it, and `FetchOneUrl`'s guidance names the standard
     policy and tiers from `--tier` or `render_mode`. Interim: `rovo fetch` uses
     neither key (robots respected, stealth never used, no refusal).
  3. **ANSWERED:** the URL is fetched even outside `[scope]`, which bounds only
     redirects, the interim as built. The question was: with `--config`, a fetched URL
     outside the file's `[scope]`: the guidance bounds only its redirects. Interim: the
     URL itself is fetched; only its redirects are bounded.
- **Carried, OPEN, to T20** (from `.allium-loop/T18-blocks-breaker.json`, the T18-2
  residue): a challenge waiting when its host trips, then resolved, asks for a retry
  `AttemptTier` refuses (it requires an untripped host), and no rule settles the walk.
  Owner testing is T20's: nothing is built or pinned here.
- **The specification's open questions.** The third `crawl.allium` one (2565 at
  `e0f0c44`, batch concurrency) is on this slice's path only in that a render runs while
  no other row of its batch is fetched (interim unchanged). The first and second (2563,
  2564) and the three `convert.allium` ones (486 to 488) are not on this slice's path.
  The fourth, new at `e0f0c44` at the maintainer's request (2566: may a render load
  subresources from origins outside the allowed hosts?), is **OPEN**; its interim, as
  built, requests only allowed hosts' origins.
- **Unowned residue.** The earlier-reachable obligations step 3 lists as carried are
  named in the ledger so the last slice's review owns or assigns them.
- **`NotInThisSlice`.** A development guard, not product behaviour: each later slice
  removes the raises it implements, and the last slice's review confirms none is left.
  This slice removes two and adds none; the six left are T20's (Acceptance criteria).
