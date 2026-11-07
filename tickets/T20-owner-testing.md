---
id: T20
title: "Owner testing: saved ownership, the owner-request refusal and warning, the relaxed policy on owned hosts, follow-up runs, breaker escalation and interactive challenges"
status: open
depends_on: [T19]
parallel_with: []
branch: full-final-prototype
estimated_size: L
---

# T20: Owner testing: saved ownership, the owner-request refusal and warning, the relaxed policy on owned hosts, follow-up runs, breaker escalation and interactive challenges

## Context

T09 (`fd1b423`) to T19 (`42ca9b0`, follow-up `941e02d`) are slices 1 to 11. `rovo sync`
reads robots.txt, paces and retries, discovers through sitemaps and `llms.txt`, fetches
and converts every page under the standard policy, keeps each page through its
lifecycle, classifies blocks, trips or retires a host, climbs from http to the browser
for a page that needs JavaScript and learns its tier, writes the indexes and
`crawl-report.json`; `rovo fetch`, `rovo verify`, `rovo index` and `rovo report` work
offline or on one page. Every run is a standard run. They fixed every pattern this slice
follows: the private subpackages `rovo._convert`, `rovo._mirror` and `rovo._crawl` with
`rovo._config`, `rovo._report` and `rovo._commands` above them (import direction enforced
by `tests/test_import_direction.py`), the `Fetcher`, `Timer` and `BrowserEngine` seams
(`FixedClock`, `SteppingTimer`, `FakeFetcher`, `ScriptedFetcher`, `RaisingFetcher`,
`FakeEngine` in `tests/fakes.py`), obligation-named tests (`test_<obligation id>`), the
end-to-end harness `serve_site` in `tests/e2e/conftest.py`, the state files of
`docs/reference/mirror.md`, and the development guard `rovo._unfinished.NotInThisSlice`.
Read `tickets/T18-blocks-breaker.md` and `tickets/T19-browser-tier.md` (their Context
tables, Facts and Open points), `.allium-loop/T19-browser-tier.json`'s `open_questions`,
`src/rovo/_crawl/run.py` (`start_run` 183, `prepare_run` 248, `discover` 322,
`robots_allows` 661, `enqueue_page_links` 730, `refollow_unchanged_links` 769,
`fetch_entry` 1332, `attempt_tier` 1369, `prepare_attempt` 1503,
`retire_host_on_long_retry_after` 1531, `stop_walk_on_tripped_host` 1702, `feed_breaker`
1724, `breaker_trips` 1750, `interrupt_run` 2017, `classify_block` 2051, `drive_run` 2179, `save_run` 2266,
`_settle` 2337, `load_runs` 2445, `_append_run` 2464, `_starting_tier` 2727,
`_unresolved_urls` 2774), `src/rovo/_crawl/model.py` (`CrawlPolicy` 252, `Run` 508 and its
`usable_tiers` 589, `Breaker` 626, `Host` 665, `LadderWalk` 727, `FetchAttempt` 767 and
its `challenges` 777, `RunRequest` 909), `src/rovo/_crawl/pace.py` (every `run.policy`
read: 119, 145, 174, 281, 318), `src/rovo/_config.py` (`SyncOptions` 109,
`effective_policy` 320), `src/rovo/_commands.py` (`sync` 92, `fetch` 165,
`_start_problem` 242, `_start_sync` 334), `src/rovo/_report.py` (`CrawlReport` 167, the
owner fields 185 to 191, their encoding 571 to 579, the per-host `effective_policy`
670), `src/rovo/_mirror/model.py` (`declared_owned_hosts` 341, `has_declared_owner`
377), `src/rovo/_mirror/state.py` (170, 293) and `tests/test_slice_boundaries.py` before
starting.

This is slice 12 of T08 to T20, the last, run in this worktree on
`full-final-prototype`. Six `NotInThisSlice` raises remain, every one an owner-testing
branch (`ai_tmp/T20/notinthisslice-941e02d.txt`): `PrepareRun` (`run.py` 263), `Discover`
(334), `EnqueuePageLinks` (742), `RefollowUnchangedLinks` (783), `StartRun` (2205) and
`BreakerEscalates` (2369). None is reachable from `_commands.sync`, which has no owner
options (`SyncOptions.owner_test` is typed `None`, `_config.py` 118). Already built and
kept: `Run.usable_tiers` with its stealth branch (`model.py` 589 to 598) and
`test_invariant_Run_StealthIsOwnerOnly` (`tests/test_crawl.py` 2121); the
`robots = "ignore"` refusal of a standard request (`_start_problem`, 258), which is
`owner_request_problem`'s no-owner-test half; `RefuseOwnerTestingFetch` (`_commands.fetch`
202, its `owner_test` parameter, T19); `RefuseMissingEngine`'s stealth half, where
`tier_installed(stealth)` is always false (`_missing_engine`, 641 to 646); the manifest's
`declared_owned_hosts`, persisted but never set (`state.py` 170, 293); `prepare_attempt`,
which offers no challenge (1503); `classify_block`, which recognises no challenge (2051 to
2072); the report's owner fields, always `null` or empty (`_report.py` 185 to 191);
`unresolved_urls` reading the preceding run's snapshot (2790). `runs.json` rows hold
`id`, `kind`, `mode`, `status`, `scope_hash`, `dry_run`, `started_at`, `finished_at` and
`unresolved_urls` (`_append_run`, 2464): no `targeted` flag and no lineage, which
`owner_request_problem` needs. No stealth engine exists and no dependency is authorised
for one.

The specification base is `53687d9`. At `39c1f9c` the maintainer answered this ticket's
batched question (`ai_tmp/T20/spec-answers/answers.md` items 1 to 9): comments, guidance
and four new open questions only, no rule changed, every obligation id unchanged
(`ai_tmp/T20/spec-answers/obligations-diff.md`). At `fc9ad9f` the maintainer answered
weed tick 1's batched question (items 10 to 14): every per-host control reads the host's
request policy (`Host.policy`), a redirected answer is judged by the host that answered
it, and the new rule `FeedAnsweringBreaker` feeds that host's breaker; crawl gains five
obligation ids (396 to 401) and 26 ids change detail, none removed or renumbered, and
rovo, mirror and convert are unchanged in obligations
(`ai_tmp/T20/spec-answers/obligations-diff-2.md`). At `53687d9` the maintainer answered
weed's question at `fc9ad9f` (item 15): a render subrequest redirected to another host
pauses the host that answered it, under that host's request policy, the requested host
standing in when that host is not open; `AttemptTier` guidance only, every obligation
unchanged (`ai_tmp/T20/spec-answers/obligations-diff-3.md`). Every specification line
number below is at `53687d9`, remapped from `fc9ad9f` with
`ai_tmp/T20/spec-answers/line-map-3.md` (before that from `39c1f9c` with `line-map-2.md`
and from `e0f0c44` with `line-map.md`); every source line number is at `941e02d`.

### The specified path, and what this slice does with each rule on it

| Class | Rules |
| --- | --- |
| **Realised** (every branch reachable in this slice, or constructible on unit inputs where noted) | `crawl.allium`: `OwnerAccess` (78, opaque, always empty: Open points item 5, decided), `CrawlPolicy` (89 to 110) relaxed, `OwnerTestOptions` (115 to 129), `PolitenessControl` (186), `StealthMode` (213); `Run` (223 to 288) its `baseline`, `preceding`, `requested_owner_test`, `owned_hosts`, `is_owner_testing`, `usable_tiers`' owner branch and the invariants `OwnerRunHasExplicitAuthority` and `StealthIsOwnerOnly` (270 to 282); `FetchAttempt.challenges` and `unsuccessful_challenge` (540 to 541), `wants_escalation`'s `protection_escalation` disjunct (547) from a run; `OwnerChallenge` (559 to 570); `config` `owner_challenge_timeout`, `min_host_rate`, `breaker_pause`; `StartRun` (640 to 653) its owner branch; `PrepareRun` (676 to 743) its owner branch, `followup_targets` and `OwnerTestingWarningIssued`; `Discover` (752 to 787) its owner branch; `FetchEntry` (1627 to 1659) `starting_tier`'s breaker tier under owner testing; `AttemptTier`'s `request_policy(run, host)` (guidance 1694 to 1704: `run.policy` for a selected owned host only, the standard policy for every other host, before redirects, subrequests, robots, discovery and retries alike), read as `Host.policy` (438) by every per-host control (`OpenHost` 802, `AdoptRobotsRules`, `RetireHostOnLongCrawlDelay`, `BreakerEscalates`, `BreakerTrips`, `HostRateNeverRises` 2494); a redirected answer judged by the host that answered it (`FetchAttempt.answering_host_name` and `answering_policy`, 514 to 524, read by `retires_host` and `wants_escalation`; `HttpRetry` 1840 to 1864, `RetireHostOnLongRetryAfter` 1876 to 1892, `CountRetryAfter` 1894 to 1909, `PauseHostOnRenderRetryAfter` 1915 to 1927; a render subrequest's Retry-After pausing the host that answered it under that host's request policy, the requested host standing in when that host is not open, never retiring a host or feeding a breaker, `AttemptTier` guidance 1745 to 1755), `FeedAnsweringBreaker` (2041 to 2053) and the discovery fetches' `judged` host (`FetchRobots` 827 to 920, `FetchSitemap` 1065 to 1185, `ReadLlmsTxt` 1298 to 1345); `PrepareAttempt` (1766 to 1784) its challenge offer, on constructed verdicts (Open points item 3); `OwnerCompletesChallenge`, `OwnerAbandonsChallenge`, `OwnerChallengeTimesOut` and `SettleChallenge` (1786 to 1838); `BreakerEscalates` (2083 to 2097) and `BreakerTrips`' `protection_escalation` guard (2106 to 2124); `EnqueuePageLinks` (2302 to 2332) and `RefollowUnchangedLinks` (2340 to 2362) with `owner_link_needed`; `InterruptRun`'s waiting challenges abandoned (2403 to 2418); the invariants `OwnerRunHasStandardBaseline`, `OwnerAccessStaysOnSelectedHosts`, `BreakerNeverPassesHighestTier` and `InteractiveChallengeIsOwnerOnly` (2455 to 2504); `DeclaredSiteOwner` (2513) and the `OwnerTesting` surface (2602 to 2661). `rovo.allium`: `SyncOptions.owner_test` (111 to 122); `CrawlReport`'s `declared_owned_hosts`, `baseline_run_id`, `preceding_run_id`, `requested_owner_test` (serialised without access) and `effective_policy` (205, 220 to 223); `HostReport.effective_policy` and `robots_ignored` per host (124 to 135; `CloseRun`'s `host_reports(run.hosts)`, 693, guidance 704 to 708: each host's request policy); `owner_request_problem` (417 to 433) and `RefuseInvalidOwnerRequest` (434 to 456), in its place in `RefusalsInOrder`; `ReportRefusal`'s owner mode and `OwnerRefusalWarned` (458 to 484); `StartSync`'s owner branch (491 to 570): `preceding`, `baseline`, `effective_policy(settings, owner_test)` (guidance 557 to 566), `mode`, `owned`; `AnnounceOwnerWarning` (621 to 631); `SyncExitCodes`' "an owner-testing run left URLs unresolved" (1024 to 1034, built at `_report.py` 487); `SecretsNeverSerialised` (1127 to 1130). `mirror.allium`: `Mirror.declared_owned_hosts` and `has_declared_owner` (287, 299); `SaveOwnership` (546 to 558); `MirrorContents`' `OperatorSavesOwnership` (1544) and `OwnershipIsADeclaration` (1602). |
| **Traversed, nothing new to do** | `RefuseOwnerTestingFetch` (`rovo.allium` 908 to 916, T19, its tests kept); `RefuseMissingEngine`'s stealth half (a configured stealth tier is always refused, Open points item 1, decided; `rovo.allium` open question 1137); `TallyBlockedUrl`, `FeedBreaker`, `StopWalkOnTrippedHost`, `DisposeFetch` and `SettleWalk` over an owner run's walks; `Escalate` on a block under `protection_escalation` (T19's rule, its verdict conjunct now reachable from a run). |
| **Specified, not reachable from a run until the maintainer answers** | A `challenge` verdict (`classify_block`'s recognisers are unspecified, `AttemptTier` guidance 1677 to 1685: "none is recognised"; `crawl.allium` open question 2670), so `PrepareAttempt`'s offer and every `OwnerChallenge` rule run on constructed `FetchAttempt` inputs through the challenge seam, never invented recognisers, and no prompt ships (`crawl.allium` open question 2671); the stealth tier (no engine: every request that needs it is refused by `RefuseMissingEngine`); `OwnerAccess` contents (none can be supplied). |
| **Outside every slice** | None: this is the last slice. After it no `NotInThisSlice` raise is left in `src/` (Acceptance criteria); the guard module, the root's handler and the two tests that inject it stay (Non-goals). |

### Facts a later reader would otherwise rediscover

- **The owner options and the ownership declaration have no command-line spelling.**
  `rovo.allium`'s `MirrorCommands` (1007 to 1019) provides no command that saves
  ownership and names no flag for `OwnerTestOptions`; `SyncOptions.owner_test` is a
  value. The maintainer decided (Open points item 2; `rovo.allium` open question 1138)
  that both are reached in process only for now, as T19 reached `rovo fetch`'s
  `owner_test`: `_commands.sync` gains keyword seams `owner_test` (an `OwnerTestOptions`,
  default `None`) and `interactive` (default `sys.stdin.isatty()`, today hard-wired at
  `_commands.py` 137; it reads no input), `drive_run` and `run_crawl` gain the
  `challenge_prompt` seam (below), and `_commands` gains `save_ownership(out_dir, hosts)`,
  realising `SaveOwnership` over `rovo._mirror` (normalised hosts, each in
  `mirror.scope.allowed_hosts`, an empty set revoking, the manifest saved atomically, no
  run started, exit 2 for a missing mirror or a host outside the allowed hosts). `cli.py`
  does not change. `rovo fetch` gains no owner flag.
- **`effective_policy(settings, owner_test)`** (`StartSync` guidance 557 to 566) starts
  from `standard_policy()` afresh and applies only the owner options: each
  `PolitenessControl` in `disabled_controls` clears its flag (`robots` makes
  `robots = ignore`, `crawl_delay` clears `honor_crawl_delay`, `rate` and `concurrency`
  become `null`, `retry_backoff` and `retry_after` clear their flags, `breaker_pause`
  becomes zero, `breaker` clears `breaker_enabled`); each supplied value replaces its
  default; `protection_escalation` and `interactive_challenges` are copied; the challenge
  timeout defaults to `CONFIG.owner_challenge_timeout`. The configuration's own keys never
  relax it (Open points item 6). With no owner options it is `standard_policy()`, as
  built.
- **`owner_request_problem`** (`rovo.allium` 417 to 433) lives in `rovo._config` beside
  `effective_policy` and returns the first problem, in the order the comment lists it,
  as the refused report's `refusal_reason` and standard error's text. With no
  `owner_test` it is today's `robots = ignore` refusal. With one: named URLs or paths; an
  empty host set, or a host outside the allowed hosts or without a saved declaration; no
  preceding run in `runs.json` with that id, or one that did not finish, was dry or has
  another scope hash; no baseline (the preceding run if it is standard, else its own
  baseline) that is a finished, non-dry, non-targeted standard run with the same scope
  hash; a rate or concurrency that is not positive, a backoff or pause that is negative,
  a retry cap that is not positive, or a challenge timeout that is not finite and
  positive (`rovo.allium` 426; a `timedelta` cannot hold `inf` or `nan`, so no request
  carries one, pinned by a test); a control both disabled and
  given a value; interactive challenges without an interactive operator, with
  `render_mode = never`, without `protection_escalation` or without an installed browser;
  access naming an unselected host. `--yes` waives none of it. The interactive-challenge
  clause "without an installed browser" is never reached alone: rendering enabled
  without an installed browser is refused first by `RefuseMissingEngine`. With an
  owner request, `rovo.toml`'s `robots = "ignore"` is accepted and ignored (decided,
  Open points item 6). `RefuseInvalidOwnerRequest` comes after `RefuseMissingEngine`
  and before any request (`RefusalsInOrder`). Each refusal reason names its problem by a
  word the tests read: `url` or `path`, `host`, `declaration`, `preceding`,
  `baseline`, the option's field name (`rate_per_host`, `concurrency_per_host`,
  `backoff_base`, `max_backoff`, `breaker_pause`, `retry_after_cap`,
  `challenge_timeout`), the doubly selected control's name, `interactive` and `access`.
- **Run lineage in `runs.json`.** `mirror.allium`'s `SyncRun` is external (86 to 88), so
  the row format is the implementation's (decision 0013). Each row gains `targeted`,
  `baseline_run_id`, `preceding_run_id` and `owned_hosts` (sorted), so a later request can
  rebuild `Run.preceding` and `Run.baseline` as read-only records, and the `OwnerTesting`
  surface's per-run fields exist. A row written before this slice lacks `targeted` and is
  never accepted as a baseline (it cannot be shown non-targeted); it is otherwise read as
  before. `docs/reference/mirror.md` documents the four fields.
- **`request_policy(run, host_name)`** is `run.policy` when the run is owner testing and
  the host is in `run.owned_hosts`, else `standard_policy()`. Every read of `run.policy`
  that concerns one host (`robots_allows`, the limiter's rate, Crawl-delay, Retry-After,
  backoff, the breaker, retirement, `wants_escalation`; `run.py` and `pace.py`) reads it
  instead; `Run.policy` stays the run's snapshot for the report. In a standard run
  `run.policy` is the standard policy (`StandardRunsStayPolite`), so `request_policy`
  may return `run.policy` there: equal by the invariant, and it keeps green the earlier
  tests that construct a relaxed policy on a standard run to reach a branch. `HostReport`'s
  `effective_policy` and `robots_ignored` are that host's `request_policy`, so an allowed
  but unselected host in an owner run reports the standard policy.
- **A follow-up run.** `PrepareRun`'s owner branch: `forced_refetch` is `run.targets`
  (`crawl.allium` 676 to 690; empty under `StartSync`, Open points item 8, decided, as
  `run.py` 295 already sets it on the targeted branch); the seeds are
  `followup_targets(preceding.unresolved_urls, owned_hosts, scope)` (the preceding run's
  unresolved URLs on a selected host within the unchanged scope; an empty set stays
  empty, never a full recrawl); `active_urls` are the seeds; `OwnerTestingWarningIssued`
  is raised before any request; each seed's row is re-pended (a deferred one at the start
  priority) or created `named` at depth 0. `Discover`'s owner branch opens the hosts of
  `run.targets` and walks no seed, sitemap or `llms.txt` (Open points item 8: an owner
  run's `targets` are empty under `StartSync`, decided, so a host is opened by `fetch_entry`'s
  `OpenHostForEntry` before its first fetch). `EnqueuePageLinks` and
  `RefollowUnchangedLinks` admit a link in an owner run only on a selected host when
  `owner_link_needed`: false for a confirmed absent or non-HTML URL or a stored,
  confident, non-challenge page, true for an unseen or unresolved one. A walk is never
  conditional in an owner run (`FetchEntry`'s `conditional` requires `mode = standard`).
- **The warning.** `AnnounceOwnerWarning` raises the `owner_testing_warning` progress
  event (`--json` prints it, `host`, `until` and `url` null). Decided (Open points item
  7; `rovo.allium` 624 to 630): the warning's text goes to standard error on every owner
  run, before the first request, and with every owner refusal (`OwnerRefusalWarned`),
  with or without `--json`; a refusal raises no event. The text says ownership is
  `self-declared` and `not verified` (the tests read both phrases) and names the selected
  hosts. `PrepareRun` raises `OwnerTestingWarningIssued(operator, hosts, policy)` to the
  run's `on_owner_warning` sink, a `drive_run` and `run_crawl` keyword.
- **The breaker under owner testing.** `BreakerEscalates` replaces the raise at
  `run.py` 2369: a breaker that should act below the highest usable tier under
  `breaker_enabled` and `protection_escalation` climbs one tier, counts the escalation,
  clears its outcomes, lowers the host's rate to no less than `CONFIG.min_host_rate`
  (never raising it, `HostRateNeverRises`), pauses the host for `breaker_pause` and
  raises `HostBackedOff`. `_starting_tier` then takes the later of the breaker's tier and
  the hint's tier in an owner run (`FetchEntry` guidance 1652 to 1658); T19's
  `test_a_breaker_tier_is_ignored_outside_owner_testing` stays true. A breaker never
  passes the highest usable tier, so a breaker at the browser with no stealth engine
  trips as `BreakerTrips` says.
- **The challenge seam.** A `ChallengePrompt` protocol in `rovo._crawl.model` answers one
  waiting `OwnerChallenge` by its deadline with `resolved`, `abandoned` or nothing (timed
  out); `tests/fakes.py` gains `FakeChallengePrompt`, scripted, which records each
  challenge and advances a `SteppingTimer` instead of sleeping. No real prompt ships
  (the maintainer's answer to Open points items 3, 4 and C3; `crawl.allium` open
  questions 2670 and 2671): nothing reads standard input or prompts on standard error,
  and the seam reaches a run only through `drive_run`'s and `run_crawl`'s
  `challenge_prompt` keyword. `prepare_attempt`'s offer (`offer_challenge`,
  `crawl.allium` 1766 to 1776) checks both host conjuncts: the walk's host and the host of the attempt's
  `response.source_url` (after a redirect) are each in `run.owned_hosts`;
  `InteractiveChallengeIsOwnerOnly` checks the walk's host only, so the second conjunct
  has its own test. `_settle` calls `prepare_attempt`, and when it offers a challenge
  the walk waits on the prompt, then `SettleChallenge`: resolved asks for the same tier
  again (`TierRequested`, try 1), abandoned and timed out raise `AttemptReady` with the
  blocked result. `OwnerCompletesChallenge`'s guards (waiting, before `expires_at`,
  running owner run, walking walk, owned host) are checked on the prompt's answer; a
  completion that fails one is no completion. `InterruptRun` abandons a waiting
  challenge. Under the batch-concurrency interim (`crawl.allium` open question 2668, one
  row at a time) no other row is fetched while a challenge waits and the walk's own attempt is
  not yet fed, so its host cannot trip during the wait: the carried T18-2 residue (Open
  points item 9, decided, `SettleChallenge`'s comment since `39c1f9c`) is unreachable here,
  and a test pins that.
- **The stealth tier.** `usable_tiers` gains stealth only for an owner run with
  `protection_escalation` and `stealth_mode = on` (built). `tier_installed(stealth)` is
  false, so such a request is refused by `RefuseMissingEngine` before
  `RefuseInvalidOwnerRequest` is reached; `attempt_tier` at the stealth tier is therefore
  unreachable and stays an explicit error, not a render. Which engine backs it is the
  specification's open question (`rovo.allium` 1137; Open points item 1).
- **`StartRun`'s `None` branch.** `start_run` returns `None` for an owner request with no
  baseline, preceding run or owned host (`StartRun`'s `requires`). The root refuses such
  a request first, so `drive_run` cannot see it from `_commands.sync`; the raise at
  `run.py` 2205 becomes a `ValueError` naming the unmet `requires`, a defect, not a
  product stop, with a test.
- **The obligation source.** `just plan-spec <module>` over `docs/specs/<module>.allium`
  at `941e02d`, written to `ai_tmp/T20/plan-spec-<module>.txt` (its echo line to
  `ai_tmp/T20/plan-spec-<module>.err`): crawl 396, rovo 174, mirror 201, convert 47
  obligations. An obligation is uncovered when no `def test_<id>` exists anywhere under
  `tests/`, `<id>` being the id in the plan's JSON `obligations` with every `.` and `-`
  replaced by `_`. As the last slice T20 owns every uncovered id of the four modules,
  each in its module's plan: 83 at `941e02d` (crawl 58, rovo 12, mirror 13, convert 0).
  At `fc9ad9f` the same files are rewritten (crawl 401, rovo 174, mirror 201, convert
  47; the `941e02d` copies kept in `ai_tmp/T20/propagate/fc9ad9f/`), and T20 owns the five
  ids crawl gained there too: 88 in all (crawl 63). The Verification block's obligation check states the rule as a command; the
  `ai_tmp/T20/` files are its outputs only. The `NotInThisSlice` raises at `941e02d` are in
  `ai_tmp/T20/notinthisslice-941e02d.txt`.

## Goal

From a clean checkout, against a served fixture site, an operator who has saved an
ownership declaration for a host and has a finished standard run can run an
owner-testing sync of that host: the warning that ownership is self-declared and
unverified is presented before any request, the preceding run's unresolved URLs on the
selected hosts are the seeds, and only links on those hosts that are unseen or
unresolved (`owner_link_needed`) are followed, never a full recrawl, under the relaxed
policy the owner options select
(robots ignored, rate, backoff and breaker relaxed, protection escalation) and on those
hosts alone, the breaker climbs a tier before it trips, a challenge waits for the owner
under the challenge seam, and the report records the declaration, the baseline and
preceding runs, the requested options without access and the effective policy per host.
An invalid owner request is refused with exit 2, the warning and no request. No
`NotInThisSlice` raise is left in `src/`. Every owned obligation listed under Steps has a
test named after its id, red before the code (or green at tick 1 with a ledger note for
the carried residue); every re-propagated test is re-hashed with its ledger note; no test
this slice adds or edits sleeps for real or reads real standard input; `just check` is
green; the Allium loop's witness record says `PASS`; both adversarial reviews have run.

## Non-goals

- No stealth engine and no dependency: `tier_installed(stealth)` stays false and a
  request that needs the stealth tier is refused (Open points item 1). No `just lock`,
  `just sync`, `playwright install` or `just install-allium`.
- No command-line spelling of the owner options or of saving ownership, and no change to
  `cli.py` (decided, Open points item 2; `rovo.allium` open question 1138).
- No challenge recogniser: `classify_block` keeps recognising none (Open points item 3,
  `crawl.allium` open question 2670). No headful browser and no prompt: nothing reads
  standard input or prompts on standard error (Open points items 4 and C3,
  `crawl.allium` open question 2671).
- No `OwnerAccess` contents: the access set is always empty (Open points item 5).
- No change to the public API: `__all__` stays `["__version__"]`, so
  `docs/reference/api.md` does not move. No harness change: `tests/e2e/conftest.py` is
  read, not changed.
- No new `rovo.toml` key. No decision record changes.
- No specification change: `docs/specs/` is read, not edited. The eleven specification
  open questions (`convert.allium` 486 to 488, `crawl.allium` 2666 to 2671, `rovo.allium`
  1137 to 1138) stay OPEN.
  A specification gap found while planning, implementing or in weed is never resolved in
  code or in the specification: it joins the one batched needs-user question (Open
  points) and the ledger's `open_questions`.
- `rovo._unfinished`, the root's `NotInThisSlice` handler in `_commands.sync`, and the
  two tests that inject the guard
  (`tests/test_regressions.py::test_a_stopped_finalisation_persists_no_done_row` and
  `tests/test_commands.py::test_a_later_slices_stop_inside_the_run_still_propagates_with_no_report`)
  stay: removing the guard is a maintainer's call recorded in the hand-back, not this
  slice's.
- T19-2 items 1 and 3 (`rovo fetch --config`'s profile and a URL outside `[scope]`) are
  not on this slice's path: the maintainer answered both (spec `39c1f9c`) and T19's
  behaviour already matches; only their records are marked ANSWERED.
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `src/rovo/_crawl/model.py` | shared, own lines | `OwnerTestOptions`, `OwnerAccess`, `PolitenessControl`, `OwnerChallenge` and its status, the `ChallengePrompt` protocol; `Run.requested_owner_test`, `RunRequest.requested_owner_test` and `FetchAttempt.challenges` typed; `unsuccessful_challenge` read from the challenges; the docstrings that call owner testing a later slice's; at `fc9ad9f`, `FetchAttempt.answering_host_name` and `answering_policy`, read by `retires_host` and `wants_escalation` |
| `src/rovo/_crawl/run.py` | shared, own lines | the six owner branches and their raises gone (`PrepareRun`, `Discover`, `EnqueuePageLinks`, `RefollowUnchangedLinks`, `StartRun`, `BreakerEscalates`); `followup_targets`, `owner_link_needed`, `request_policy`; `prepare_attempt`'s offer, `owner_completes_challenge`, `owner_abandons_challenge`, `owner_challenge_times_out`, `settle_challenge` and the wait in `_settle`; `breaker_escalates`; `_starting_tier`'s breaker tier; `interrupt_run` abandoning a waiting challenge; `runs.json`'s lineage fields in `RunRecord`, `_append_run` and `load_runs`; the run's `challenge_prompt` and `on_owner_warning` seams through `drive_run` and `run_crawl`; at `fc9ad9f`, `feed_answering_breaker` and the answering host in `http_retry`, `retire_host_on_long_retry_after`, `count_retry_after`, `pause_host_on_render_retry_after`, `_settle`'s breaker check, and `fetch_robots`, `fetch_sitemap` and `read_llms_txt`'s `judged` host, through `_answering_host` and `pace.judged_host`; the module docstring's spec citations remapped to `fc9ad9f`; at `53687d9` (item 15), `_Render.__call__` pauses the host that answered a subrequest (`pace.judged_host`, the requested host standing in) under that host's request policy, and `_Render.through`'s no-DOM answer carries the navigation's last URL as its `source_url` (weed's code bug at `fc9ad9f`), citations remapped to `53687d9`; `lineage_run` rebuilds a run's lineage oldest first without recursion (review T20-2 r4) |
| `src/rovo/_crawl/pace.py` | shared, own lines | every per-host `run.policy` read through `request_policy`, with its docstring; `judged_host`, and `fetch_resource`'s per-try Retry-After count and pause on the host that answered (spec `fc9ad9f`); the docstrings' spec citations remapped to `fc9ad9f` |
| `src/rovo/_config.py` | shared, own lines | `SyncOptions.owner_test` typed; `effective_policy(settings, owner_test)`; `owner_request_problem`, refusing a NaN or infinite `rate_per_host` (review T20-2 r4) |
| `src/rovo/_commands.py` | shared, own lines | `sync`'s `owner_test` and `interactive` seams; `RefuseInvalidOwnerRequest` in `_start_problem` after the engine refusals; the warning on standard error; `AnnounceOwnerWarning`; the preceding and baseline records passed to `RunRequest`; `save_ownership`; the module docstring (no terminal prompt ships) |
| `src/rovo/_report.py` | shared, own lines | `report_refusal`'s owner mode; `requested_owner_test` serialised without access; `declared_owned_hosts`, `baseline_run_id`, `preceding_run_id` from the run; `HostReport`'s `effective_policy` and `robots_ignored` per host from `request_policy`; `host_reports(hosts, policy)` keeps the run's policy as a parameter: taking the hosts alone, as `rovo.allium` 693 writes `host_reports(run.hosts)`, would change five calls in the earlier slices' `tests/test_report.py`, which only a re-propagation may do (weed's noted gap, same rows either way) |
| `src/rovo/_mirror/model.py` | shared, own lines | `save_ownership` (`SaveOwnership`): the hosts normalised as URL hosts and checked against the allowed hosts |
| `tests/test_owner_testing.py` | new | the owner obligations of step 3 but the challenge ones, and the guarantees; no e2e module shares its name |
| `tests/test_owner_challenges.py` | new | the `OwnerChallenge`, `PrepareAttempt` offer, `SettleChallenge`, `InteractiveChallengeIsOwnerOnly` and interrupt obligations and guarantees, through `FakeChallengePrompt` and `SteppingTimer` |
| `tests/test_carried_obligations.py` | new | the 22 residue obligations of step 3 that T09 to T19 reached and no ticket assigned |
| `tests/test_owner_regressions.py` | new | one test per divergence weed or an adversarial review finds; hash-pinned in this slice's ledger; first, weed tick 1's intentional gap 3: `await_challenge`'s resolved and timed-out branches through `drive_run` via the challenge seam; then weed's code bug at `fc9ad9f`: a render with no DOM after a redirected navigation is an error whose `source_url` is the URL last requested, so the answering host's breaker is fed; then review T20-2 r4: a NaN or infinite `rate_per_host` refused, a redirected subrequest's `Retry-After` read under the answering host's own policy, and a lineage longer than the recursion limit rebuilt |
| `tests/test_answering_host.py` | new | the five `FeedAnsweringBreaker` obligations (spec `fc9ad9f`) and the redirect guarantees: a redirected answer judged, paused, counted and retired by the host that answered, its breaker fed, discovery's `judged` host, the non-redirect case unchanged; at `53687d9` (item 15), a render subrequest redirected to another host pauses that host under its own policy and cap, never the requested host, never retiring a host or feeding a breaker, and the requested host stands in when the answering host is not open; no e2e module shares its name |
| `tests/e2e/test_answering_host_sync.py` | new | the redirect scenario end to end: owned `127.0.0.1` redirects to unselected `localhost`, which answers 429 past the cap and is retired; over the committed `robots-disallow` and `one-page` sites |
| `src/rovo/_convert/model.py`, `src/rovo/_convert/fidelity.py` | shared, own lines | final review F2 (spec `9149df7`): `ExtractedContent.source_url`, set by `extract` to the URL it was given; `_footnotes` turns only a same-page reference into `[^n]` (a bare `#id`, or a target whose URL without its fragment is `source_url` without its fragment) |
| `src/rovo/_crawl/browser.py` | shared, own lines | final review F3 (spec `9149df7`): `PlaywrightEngine.render`'s route aborts a request whose method is not GET or HEAD before asking the crawl, so it is never sent |
| `src/rovo/_convert/profiles.py`, `src/rovo/_crawl/model.py`, `src/rovo/_mirror/finalise.py`, `src/rovo/_mirror/indexes.py`, `src/rovo/_mirror/intake.py`, `src/rovo/_mirror/links.py`, `src/rovo/_mirror/model.py`, `src/rovo/_mirror/urls.py` | shared, own lines | docstring spec citations remapped to `9149df7` (`ai_tmp/review/final/spec-answers/line-map.md`); no code |
| `tests/test_final_review_regressions.py` | new | the final whole-branch review's regression tests (19), hash-pinned in this slice's ledger; citations remapped to `9149df7` |
| `tests/test_final_review_answers.py` | new | final review F2 and F3 (spec `9149df7`) as guarantee tests: same-page references become footnotes, a link to another page whose fragment names a local note stays a link, a non-GET render request is aborted and never reaches the crawl, GET and HEAD are still answered; hash-pinned |
| `tests/e2e/test_subrequest_methods_sync.py`, `tests/fixtures/sites/spa-methods/` | new | final review F3 end to end in a real Chromium: a page's GET and HEAD are fetched through rovo, its POST is aborted and never reaches the server |
| `tests/test_convert.py` | shared, own lines (re-propagated) | `test_entity_fields_ExtractedContent` (T09) gains `source_url` (spec `9149df7`), ledger note |
| `tests/test_slice_boundaries.py` | shared, own lines (re-propagated) | `test_owner_testing_and_dry_runs_stop` (T09), `test_owner_testing_runs_stop` (T09, re-propagated by the T16 follow-up) and `test_enqueue_page_links_owner_branch_stops` (T10) become their behaviour, renamed (`test_an_owner_request_without_its_authority_is_a_defect`, `test_owner_testing_runs_prepare_their_follow_up_and_discover_nothing`, `test_enqueue_page_links_owner_branch_admits_only_owned_needed_links`), with ledger notes naming their origin slices and old names; the module docstring no longer says a branch raises the guard |
| `tests/test_blocks.py` | shared, own lines (re-propagated) | `test_rule_failure_BreakerTrips_3` (T18, 882), whose escalating half expects `NotInThisSlice("BreakerEscalates")` (911 to 913), asserts the climb there instead, ledger note |
| `tests/test_fetch_command.py` | shared, own lines (re-propagated) | `test_surface_provides_MirrorCommands` (T19, hash-pinned by `.allium-loop/T19-browser-tier.json`): help printed as plain text whatever the environment says about colour (`typer.rich_utils.FORCE_TERMINAL` patched false, as `tests/test_cli.py`'s fixture does), since on GitHub Actions Typer's ANSI codes split `Usage: rovo fetch`; ledger note naming T19 and the reason |
| `.allium-loop/T19-browser-tier.json`, `tickets/T19-browser-tier.md` | ledger (gitignored) and ticket | T19-2 items 1 and 3 marked ANSWERED with the maintainer's answers (spec `39c1f9c`); nothing else |
| `tests/test_crawl.py`, `tests/test_report.py`, `tests/test_targeted_run.py`, `tests/test_mirror.py`, `tests/test_commands.py` | shared, own lines (re-propagated) | only a test the red run shows red because `runs.json` gained its lineage fields, the report its owner fields, or `effective_policy` its second argument, each with only that expectation moved and a ledger note naming its slice; in `tests/test_crawl.py`, `test_entity_fields_FetchAttempt` (T12) and `test_entity_fields_Host` (T09) gain the fields `fc9ad9f` adds (hash-tracked by this slice's ledger) |
| `tests/fakes.py` | shared, own lines | `FakeChallengePrompt`; an `OwnerTestOptions` builder if two test files need one; hash-tracked |
| `tests/e2e/test_owner_sync.py` | new | the end-to-end scenarios (Acceptance criteria) over `serve_site("robots-disallow")`, a real `HttpxFetcher` and a `SteppingTimer`, in process; no unit test is named `test_owner_sync.py` |
| `docs/reference/cli.md` | shared, own lines | `rovo sync`'s refusals gain the invalid owner request; 362 to 365 lose "a branch a later slice implements (owner testing)"; a short owner-testing section: what it does, that it is reached in process only until the maintainer answers, the warning, exit 1 for unresolved URLs and 2 for a refusal; that a redirected answer pauses or retires the host that answered it and feeds that host's breaker (spec `fc9ad9f`); that a render subrequest's `Retry-After` pauses the host that answered it (spec `53687d9`), only for a retryable answer, and that a request whose method is not GET or HEAD is aborted (spec `9149df7`) |
| `docs/reference/mirror.md` | shared, own lines | `runs.json`'s four lineage fields (144 to 149); `declared_owned_hosts` set by saving ownership (97); the report's owner fields and per-host policy; 467 to 468 lose the later-slice sentence; footnotes are same-page references only (spec `9149df7`) |
| `docs/reference/configuration.md` | shared, own lines | that no `rovo.toml` key relaxes a policy and `robots = "ignore"` is refused for a standard sync, only if the page does not already say so |
| `docs/reference/testing.md` | shared, own lines | `FakeChallengePrompt`, the new test modules and the owner e2e module |
| `docs/project/purpose-and-scope.md`, `docs/project/repository-map.md`, `docs/explanation/architecture.md` | shared, own lines | purpose-and-scope 32 to 33 (no branch stops a sync any more; owner testing exists, in process only); the new test files |
| `README.md`, `AGENTS.md` | shared, own lines | only the sentences step 6's search shows false; `AGENTS.md`'s required phrases stay in always-visible text |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` Added entry: owner testing, with the redirected answer judged by the host that answered (spec `fc9ad9f`), a render subrequest's included (spec `53687d9`) |
| `tickets/README.md`, `tickets/T20-owner-testing.md` | ticket | index row, graph, slice bullet, this ticket |
| `.allium-loop/T20-owner-testing.json`, `.allium-loop/T20-owner-testing.witness.json` | gitignored | the loop ledger and the witness record; never committed |

`uv.lock`, `pyproject.toml`, `pytest.ini`, `.coveragerc`, `ruff.toml`, `mypy.ini`,
`Justfile`, `scripts/wheel_smoke.py` (no module is added, so the package-file count stays
twenty-nine), `src/rovo/__init__.py`, `src/rovo/cli.py`, `src/rovo/_exit.py`,
`src/rovo/_unfinished.py`, `src/rovo/_crawl/fetch.py`,
`src/rovo/_crawl/sitemaps.py`, `src/rovo/_mirror/state.py` (it already persists
`declared_owned_hosts`), `tests/e2e/conftest.py`,
`tests/fixtures/sites/` (but `spa-methods`), `tests/test_import_direction.py`, `docs/manifest.yml`,
`docs/decisions/` and `docs/specs/` are read, not changed. A file not in this table that
turns out to need a change is added to the table in the same change with its reason, or
handed back if it is a decision record, a specification or a dependency.

## Steps

0. `just check` baseline on the untouched worktree at `941e02d` plus this ticket, last
   line quoted, and `( set -o pipefail; { time just py-test tests/e2e -ra; } 2>&1 | tail -6 )`
   with its wall time. Scratch output goes in `ai_tmp/T20/`. Write `just plan-spec
   <module>` for each of `crawl`, `rovo`, `mirror` and `convert` to
   `ai_tmp/T20/plan-spec-<module>.txt`; derive the uncovered and owned sets by the rule
   in Facts (The obligation source) with the Verification block's obligation check,
   which at `941e02d` prints `{'crawl': 58, 'rovo': 12, 'mirror': 13, 'convert': 0}`
   and exits 1, and confirm the 83 ids. Confirm
   `ai_tmp/T20/notinthisslice-941e02d.txt` is `rg -n 'NotInThisSlice\(' src` at
   `941e02d`. Create the ledger `.allium-loop/T20-owner-testing.json` (propagate's first
   tick creates it) against `allium-skill-reference/allium/schemas/ledger.schema.json`,
   shaped like T19's: `goal` `"T20-owner-testing"`, `mode` `"spec-first"`,
   `specification_base` `53687d9` (`39c1f9c` until weed tick 1's answers, `fc9ad9f` until weed's question at `fc9ad9f` was answered), `obligation_source` the four files, and
   `open_questions` holding the eleven specification open questions verbatim, OPEN, each
   with whether it is on T20's path (`crawl.allium` 2668, whose interim makes the T18-2
   residue unreachable, and the four added at `39c1f9c`); every item of the T20 batched
   needs-user question (Open points) ANSWERED with its decision; T19-2 items 1 and 3
   ANSWERED, not on T20's path. Read `.agents/skills/propagate/SKILL.md`, `.agents/skills/weed/SKILL.md`,
   `.agents/skills/witness/SKILL.md` and `.agents/skills/python-change/SKILL.md` before
   step 3.

1. **The policy and the request.** `OwnerTestOptions` and the other model types;
   `effective_policy(settings, owner_test)` and `owner_request_problem` in `rovo._config`;
   `save_ownership`; `RefuseInvalidOwnerRequest` in `_start_problem` after the engine
   refusals, with `ReportRefusal`'s owner mode and the refusal's warning; `runs.json`'s
   lineage fields and the preceding and baseline records `StartSync` passes; `StartRun`'s
   owner branch and the `ValueError` in `drive_run`. Every default, cap and count comes
   from `CONFIG` or the policy, never a literal.

2. **The run.** `request_policy` at every per-host policy read in `run.py` and
   `pace.py`; `PrepareRun`'s, `Discover`'s, `EnqueuePageLinks`' and
   `RefollowUnchangedLinks`' owner branches with `followup_targets` and
   `owner_link_needed`; `OwnerTestingWarningIssued` and `AnnounceOwnerWarning` (the
   progress event and standard error) before any request; `BreakerEscalates` and the
   breaker tier in `_starting_tier`; the challenge seam, `prepare_attempt`'s offer, the
   four challenge rules and `InterruptRun`'s abandonment; the report's owner fields and
   per-host policy. Each function returns `None`, `False` or an empty result when its
   guards do not hold. Afterwards `rg -n 'NotInThisSlice\(' src` prints only the class
   definition in `src/rovo/_unfinished.py`.

3. **Tests first, from the obligations** (the `propagate` skill, spec-first). Write a
   failing test for each owned obligation below into the test file named, named
   `test_<obligation id with dots and hyphens as underscores>`, its docstring quoting the
   obligation's description from the plan-spec file. Each `rule_failure` test makes
   exactly one `requires` clause false. Generated tests satisfy EditorConfig
   (indentation in 4-space multiples in `*.py`, string literals included), ruff and
   mypy, since the gate stages them. No test reads real standard input or sleeps: the
   prompt is `FakeChallengePrompt`, time is `FixedClock` or `SteppingTimer`, and
   `interactive` is passed. Run `just py-test` and record the red run in
   `ai_tmp/T20/red.txt`, its summary line under `last_results.propagate` in the ledger.
   Record each generated, re-propagated or extended test file's SHA-256 under
   `generated_test_hashes` (`tests/fakes.py`, `tests/e2e/test_owner_sync.py` and
   `tests/test_owner_regressions.py` included), and the reconciliation line
   (`N obligations, M covered, K uncovered`) over the owned set. A test changed after the
   red run is re-recorded: a new hash, `tick` incremented, a ledger note naming the test
   and why; never silently. An obligation a test cannot reach without behaviour the
   maintainer has not specified (a recogniser, a stealth engine, access contents) is
   tested on constructed inputs where the rule's guards allow it; one that cannot be
   reached even so is moved to the hand-back notes with its reason rather than given a
   vacuous test.

   Owned obligations, owner testing (ids as `just plan-spec <module>` emits them at
   `941e02d`; 61, red before green):

   - **`crawl`** (46). In `tests/test_owner_challenges.py`:
     `entity-relationship.FetchAttempt.challenges`,
     `transition-edge.OwnerChallenge.waiting.resolved`,
     `transition-edge.OwnerChallenge.waiting.abandoned`,
     `transition-edge.OwnerChallenge.waiting.timed_out`,
     `transition-rejected.OwnerChallenge.status`,
     `transition-terminal.OwnerChallenge.status`, `entity-fields.OwnerChallenge`,
     `config-default.owner_challenge_timeout`, `rule-success.OwnerCompletesChallenge`,
     `rule-failure.OwnerCompletesChallenge.1` to `.5`,
     `rule-success.OwnerAbandonsChallenge`, `rule-failure.OwnerAbandonsChallenge.1`,
     `.2`, `rule-success.OwnerChallengeTimesOut`, `temporal.OwnerChallengeTimesOut`
     (through `SteppingTimer`: waiting before `expires_at`, timed out at it),
     `rule-failure.OwnerChallengeTimesOut.1`, `rule-success.SettleChallenge`,
     `rule-failure.SettleChallenge.1`, `invariant.InteractiveChallengeIsOwnerOnly`
     (after every rule that creates or settles a challenge). In
     `tests/test_owner_testing.py`: `entity-fields.OwnerAccess`,
     `value-equality.OwnerTestOptions`, `entity-fields.OwnerTestOptions`,
     `enum-comparable.PolitenessControl`, `enum-comparable.StealthMode`,
     `invariant.Run.OwnerRunHasExplicitAuthority`, `entity-optional.Run.baseline`,
     `entity-optional.Run.preceding`, `entity-optional.Run.requested_owner_test`,
     `derived.Run.is_owner_testing`, `config-default.min_host_rate`,
     `config-default.breaker_pause`, `rule-success.BreakerEscalates`,
     `rule-failure.BreakerEscalates.1` to `.4`, `invariant.OwnerRunHasStandardBaseline`,
     `invariant.OwnerAccessStaysOnSelectedHosts`,
     `invariant.BreakerNeverPassesHighestTier` (after every climb, with and without the
     stealth tier usable), `surface-actor.OwnerTesting`, `surface-exposure.OwnerTesting`
     and `surface-provides.OwnerTesting`.
   - **`rovo`** (12), in `tests/test_owner_testing.py`:
     `entity-optional.CrawlReport.baseline_run_id`,
     `entity-optional.CrawlReport.preceding_run_id`,
     `entity-optional.CrawlReport.requested_owner_test` (serialised, its access never),
     `rule-success.RefuseInvalidOwnerRequest` (one test per problem of
     `owner_request_problem`, each alone, no request, the warning on standard error;
     an infinite and a NaN challenge timeout each refused with no request made),
     `rule-failure.RefuseInvalidOwnerRequest.1` to `.7` (`.1` to `.6` each the earlier
     refusal or no mirror that precedes it, `.7` a valid owner request, which starts a
     run), `rule-success.AnnounceOwnerWarning`.
   - **`mirror`** (3), in `tests/test_owner_testing.py`:
     `derived.Mirror.has_declared_owner`, `rule-success.SaveOwnership` (set, replaced,
     revoked by an empty set, normalised), `rule-failure.SaveOwnership.1` (a host outside
     the allowed hosts, the manifest unchanged).
   - **`convert`**: none.

   Owned obligations, carried residue (22; reachable since T09 to T19 and assigned by no
   ticket, so expected green at tick 1, each recorded so with a ledger note; one that is
   red is recorded red and fixed like any other), in `tests/test_carried_obligations.py`:
   **`crawl`** (12) `entity-fields.DocumentationSite`, `enum-comparable.RunKind`,
   `enum-comparable.RunMode`, `enum-comparable.FrontierStatus`,
   `entity-relationship.Run.hosts`, `entity-relationship.Frontier.entries`,
   `when-presence.LadderWalk.standing`, `transition-edge.LadderWalk.walking.settled`,
   `transition-rejected.LadderWalk.status`, `transition-terminal.LadderWalk.status`,
   `entity-relationship.LadderWalk.attempts`, `surface-actor.SiteExchange`;
   **`mirror`** (10) `entity-fields.SyncRun`, `entity-relationship.Mirror.pages`,
   `entity-optional.Page.canonical_url`, `entity-optional.Page.frontmatter`,
   `surface-actor.MirrorContents`, `surface-exposure.MirrorContents`,
   `surface-provides.MirrorContents` (its `OperatorSavesOwnership` new here, so this one
   may be red), `surface-actor.PageIntake`, `surface-exposure.PageIntake`,
   `surface-provides.PageIntake`.

   Owned obligations added at `fc9ad9f` (weed tick 1's answers, items 10 to 14; 5, red
   before green), in `tests/test_answering_host.py`: **`crawl`**
   `rule-success.FeedAnsweringBreaker` and `rule-failure.FeedAnsweringBreaker.1` to `.4`.
   Beside them, the redirect guarantees, each red before green: an answer's
   `answering_host_name` and `answering_policy` (redirected, not redirected, and on an
   error the host of the URL last requested); owned A redirecting to unselected B, which
   answers 429 past B's cap, retires B and never A (`retires_host`,
   `RetireHostOnLongRetryAfter`), whether A ignores Retry-After or has a longer cap;
   `CountRetryAfter`, `HttpRetry`'s pause and `PauseHostOnRenderRetryAfter` fall on B
   under B's policy; `wants_escalation` reads B's `protection_escalation`; B's breaker,
   fed by redirected answers through `drive_run`, trips while the owner has disabled A's;
   a redirected declared sitemap past the cap retires B, a speculative probe and
   `llms.txt` pause B, a discovery try's Retry-After is counted and paused on B, and a
   redirected robots.txt past the cap retires an open B while A's origin keeps the
   answer; the non-redirect case unchanged. Two hold already and pin a reading: a
   robots.txt hop onto a host the run has not opened is judged by the fetching host
   (`judged`), and `entity-fields.Host`'s new `policy`, read by its code name
   `request_policy`. End to end, `tests/e2e/test_answering_host_sync.py`: owned
   `127.0.0.1` redirects to unselected `localhost` (a distinct host name for the same
   loopback server; a port alone never makes one), which answers 429 past the cap, and
   `localhost` is retired, never `127.0.0.1`.

   At `53687d9` (item 15, no obligation added) the subrequest guarantees, in
   `tests/test_answering_host.py`, each red before green unless noted: a render of A's
   seed whose style sheet A redirects to B, which answers 429 under the cap, pauses B
   under B's policy and never A, whose owner policy ignores Retry-After; with A's cap
   longer than B's and a Retry-After past both, B is paused at most B's cap and is never
   retired, and no breaker is fed; a subrequest answered from a host the run has not
   opened pauses the requested host (green at once: the code already pauses the
   requested host, so it pins the stand-in). In `tests/test_owner_regressions.py`, weed's
   code bug at `fc9ad9f`: a render with no DOM after the navigation's redirect to B is an
   error whose `source_url` is B's URL, so B's breaker is fed.

   Re-propagated, not new (each re-hashed in this slice's ledger with a note naming its
   origin slice; T09's to T19's ledgers are never edited): the tests the Files touched
   table names in `tests/test_slice_boundaries.py` and `tests/test_blocks.py`, each now
   asserting the behaviour where it asserted the raise, asserting no less than before;
   `tests/test_fetch_command.py::test_surface_provides_MirrorCommands` (T19), which
   failed on GitHub Actions because Typer forces coloured help there, now reads the help
   as plain text, and the whole suite passes alike with and without `GITHUB_ACTIONS=true`;
   `tests/test_crawl.py::test_entity_fields_FetchAttempt` (T12) and
   `::test_entity_fields_Host` (T09), whose obligations gained `answering_host_name`,
   `answering_policy` and `policy` at `fc9ad9f`; every other earlier test the red run
   shows red because of a change the Files touched table names, each with only that
   expectation moved. Claim an earlier test "passes
   unedited" only where it does; the hand-back notes list every earlier test this slice
   edited.

   Guarantees and black boxes (no obligation id; hand-written), in
   `tests/test_owner_testing.py` unless named: `effective_policy` (each control
   disabled alone, each value supplied alone, the timeout default, no options the
   standard policy, a configuration key never relaxing it); `request_policy` (an owned
   host relaxed, an allowed unselected host in the same run standard, its report row
   standard); `followup_targets` (unresolved URLs on selected hosts only, out-of-scope
   ones dropped, an empty set staying empty; an owner run whose preceding run left a
   nonempty unresolved set has `forced_refetch == frozenset()`, the seeds only in
   `active_urls`); `owner_link_needed` (each case of
   `EnqueuePageLinks`' guidance, for content and navigation links and for
   `RefollowUnchangedLinks` alike, which also settles the carried review note that the
   `RefollowUnchangedLinks` owner guard had no test); the warning before the first
   request (the event and standard error, the fetcher's log empty when it arrives);
   `ExplicitOwnerTestingOnly` (a saved declaration alone never relaxes a standard sync;
   `--yes` waives nothing); `RelaxationsAreRecorded` and `SecretsNeverSerialised` (the
   report on a finished, a refused and an interrupted owner run); the breaker tier as an
   owner run's starting tier, and still ignored in a standard run; `BreakerTrips` at the
   highest usable tier of an owner run; `runs.json`'s lineage round trip and a pre-slice
   row never a baseline; `StartRun`'s `None` branch as a `ValueError` from `drive_run`;
   `save_ownership` starting no run and making no request; a stealth-needing owner
   request refused by `RefuseMissingEngine` with no request. In
   `tests/test_owner_challenges.py`: no challenge is offered at http, outside owner
   testing, to a non-interactive run, when the walk's host is unselected, or twice in
   one walk; none is offered when the walk's host is selected and owned but the
   attempt's `response.source_url` was redirected to an allowed, unselected host (a
   constructed `challenge` verdict at the browser tier in an interactive owner run: no
   `OwnerChallenge` is created, `walk.challenge_offered` stays false and `AttemptReady`
   is raised with the blocked result); a
   resolved challenge re-requests the same tier at try 1 and a fresh response decides
   the page; an abandoned or timed-out one keeps the blocked result and no further
   escalation (`unsuccessful_challenge`); an interrupt abandons a waiting challenge;
   while a challenge waits, no other request is made and the host's breaker is not fed
   (the T18-2 residue unreachable under the interim).

4. **Owner testing in units.** Steps 1 and 2. Unit cases on `FakeFetcher`,
   `ScriptedFetcher`, `FakeEngine` and `FakeChallengePrompt` with `FixedClock` or
   `SteppingTimer`. `just py-test tests/test_owner_testing.py tests/test_owner_challenges.py
   tests/test_carried_obligations.py tests/test_slice_boundaries.py tests/test_blocks.py
   tests/test_crawl.py tests/test_report.py tests/test_commands.py`, then `just py-lint`,
   `just py-typecheck`, `just coverage` and `just wheel-smoke`, quoting its `api` line and
   the package-file count (twenty-nine, unchanged).

5. **End to end.** `tests/e2e/test_owner_sync.py` over
   `serve_site("robots-disallow")` (committed: its `robots.txt` disallows `/guide/`, the
   seed `guide/start.html`). The scenarios are the Acceptance criteria's; each runs
   `rovo init` through `CliRunner` and `rovo._commands.sync` and
   `rovo._commands.save_ownership` in process over a real `HttpxFetcher` with a
   `SteppingTimer`, which never sleeps, and reads requests off the server's log.
   `just py-test tests/e2e -ra`, its wall time quoted beside step 0's.

6. **Documents** (the `review-docs` skill). The pages of the Files touched table; find
   the sentences this slice makes false with
   `rg -n -i "owner|later slice|stealth|challenge|not yet|stops the sync|exit 1" -g '*.md' -g '!tickets/**' -g '!allium-skill-reference/**' -g '!docs/specs/**' -g '!docs/decisions/**'`;
   `CHANGELOG.md` `Unreleased` gains one Added entry. Keep the required phrases of
   `AGENTS.md` in always-visible text. `just check-docs`, `just check-agents`, and
   `just lint`, whose hooks include markdownlint over this ticket.

7. **Witness** (the `weed` and `witness` skills). Run `weed` over `crawl`, `rovo` and
   `mirror` against the code, scoped to the owned and re-propagated obligations, the
   Realised rules of the Context table and the guarantees; record its verdict under
   `last_results.weed` and fix any code divergence, each with a regression test in
   `tests/test_owner_regressions.py`. A divergence weed attributes to the specification
   is not fixed: it joins the one batched needs-user question. Then run `witness`
   non-interactively: it writes `.allium-loop/T20-owner-testing.witness.json` per
   `witness-result.schema.json`. The verdict must be `PASS`; a `FAIL` routes back per the
   skill, and the hand-back notes record each round. A batched question still OPEN does
   not block `PASS` unless it blocks an owned obligation; none of the T20 items does,
   each having an interim, and the witness escalates any new one that blocks.

   **Adversarial review** (`CONVENTIONS.md` §14, checkpoint T20-1, after the
   implementation is witnessed). Two fresh-context reviewers on the preferred model of
   the harness the executing agent is not, one per lens, write to
   `ai_tmp/review/T20-1/findings-conformance.md` and
   `ai_tmp/review/T20-1/findings-breakage.md`. The brief gives this ticket's path,
   `tickets/CONVENTIONS.md`, `git diff 941e02d` plus the uncommitted changes, and these
   questions: does any request in an owner run reach an unselected host under the
   relaxed policy, or any request precede the warning; can a standard sync reach any
   owner branch, relax any control or offer a challenge; does `owner_request_problem`
   accept a request the specification refuses (each clause of `rovo.allium` 417 to 433);
   does any access content or `OwnerAccess` reach the report, the log or a page file;
   does any test sleep, read real standard input, or pass without exercising its
   obligation (a vacuous `rule_failure`, a constructed input that bypasses the guard
   under test); did any earlier test lose an assertion when re-propagated; is any spec
   gap resolved in code rather than batched. Triage and apply per §14 phase 2 and 3,
   verdicts in `ai_tmp/review/T20-1/verdicts.md`, each valid fix with a regression test
   in `tests/test_owner_regressions.py` (re-hashed in the ledger); then rerun step 4's
   and step 5's commands and `witness` if any code moved. A second round runs over the
   fix diff if a high-severity finding was valid; two rounds at most, anything left goes
   into Open points.

8. Hand-back notes; `status: done`; `just check` ending with
   `All checks passed and the worktree is unchanged.`.

   **Adversarial review** (`CONVENTIONS.md` §14, checkpoint T20-2, before the final
   commit and the authorisation stop). The same two lenses over the whole slice as it
   will be committed, `ai_tmp/review/T20-2/`: the ticket's Acceptance criteria each
   shown by quoted output; the documents against the code (`cli.md`, `mirror.md`,
   `configuration.md`, `CHANGELOG.md`); the ledger and witness record against the tests
   on disk (every hash, every note, the reconciliation line); the Verification block
   for a command that would print a pass when it failed; the batched question complete
   and every interim stated where the code realises it. Triage and apply as at T20-1,
   then rerun `just check`. Commit on the branch; `git status --short` empty after the
   commit.
   **Authorisation required**: pushing and opening the pull request.

## Acceptance criteria

The end-to-end scenarios live in `tests/e2e/test_owner_sync.py`. Each starts with
`rovo init <base>guide/start.html <tmp>/out` and a standard `rovo sync` (the baseline):
robots.txt disallows the seed, so the run finishes with the seed `skipped_robots` and in
its `unresolved_urls`, and `runs.json` holds run 1 as a finished, non-dry, non-targeted
standard run. Every count and limit the assertions use comes from `CONFIG` or the
policy.

- **End to end, an owner-testing sync mirrors what robots.txt kept out**
  (`test_an_owner_testing_sync_mirrors_a_page_robots_disallows`): after
  `save_ownership(out, {host})`, which makes no request, `_commands.sync` with
  `OwnerTestOptions(preceding_run_id=1, hosts={host}, disabled_controls={robots})`
  exits 0: `pages/<host>/guide/start.md` holds the page's heading; the
  `owner_testing_warning` event (with `json_events`) and the warning on standard error
  arrive while the server's log holds no request of this run; the log then holds
  `guide/start.html` and no sitemap or `llms.txt` request; `crawl-report.json` has
  `mode: owner_testing`, `declared_owned_hosts: [host]`, `baseline_run_id: 1`,
  `preceding_run_id: 1`, `requested_owner_test` with the options and no access contents,
  `robots_ignored: true`, the per-host row's `effective_policy.robots` `ignore`, and
  `unresolved_urls` empty; `runs.json`'s run 2 has `mode: owner_testing`,
  `baseline_run_id: 1` and `preceding_run_id: 1`.
- **End to end, an owner request without a declaration is refused**
  (`test_an_owner_request_without_a_declaration_is_refused`): the same options with no
  saved ownership exit 2 with a refused report (`mode: owner_testing`, `run_id: null`,
  `refusal_reason` naming the missing declaration, `effective_policy: null`), the
  warning on standard error, no row added to `runs.json`, and no request in the server's
  log after the baseline's.
- **End to end, a saved declaration alone relaxes nothing**
  (`test_a_saved_declaration_alone_never_relaxes_a_standard_sync`): after
  `save_ownership`, a standard sync exits as the baseline did, the seed still
  `skipped_robots` and never requested, `robots_ignored: false`.
- **End to end, a redirected answer is judged by the host that answered** (spec
  `fc9ad9f`; `tests/e2e/test_answering_host_sync.py::test_a_redirected_retry_after_past_the_cap_retires_the_host_that_answered`):
  `allowed_hosts` holds `127.0.0.1` and `localhost` before the baseline; after
  `save_ownership(out, {127.0.0.1})`, an owner sync with robots disabled follows the
  seed's redirect to `localhost`, whose page answers 429 with a Retry-After past
  `retry_after_cap`: it is requested once, the sync exits 3, and the report's
  `localhost` row has `breaker_tripped: true` and `retry_after_honored: 1` while the
  `127.0.0.1` row has `breaker_tripped: false`.
- **End to end, earlier scenarios**: every module under `tests/e2e/` but the new one
  passes unedited, unless the ledger names an edit and why.
- No `NotInThisSlice` raise is left in `src/`: `rg -n 'NotInThisSlice\(' src` prints only
  `src/rovo/_unfinished.py`'s class line (`ai_tmp/T20/rules-after.txt`, written by the
  Verification block, is empty).
- Every owned obligation in step 3 has a test named after it, red before the code and
  green after (`ai_tmp/T20/red.txt` and the final run), or, for the carried residue,
  green at tick 1 with its ledger note; the reconciliation line shows zero uncovered
  (the Verification block's obligation check, rerun after the slice, prints 0 for every
  module and exits 0); every
  re-propagated test is re-hashed in the ledger with its note; every obligation dropped
  from the owned list is in the hand-back notes with its reason.
- No test this slice adds or edits sleeps for real or reads real standard input:
  `rg -n 'time\.sleep\(' tests; test $? -eq 1`,
  `test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py`, and
  `rg -n 'sys\.stdin|subprocess' tests/test_owner_testing.py tests/test_owner_challenges.py tests/e2e/test_owner_sync.py; test $? -eq 1`.
- No access content is serialised: the e2e and unit reports hold `access` only as an
  empty list, and `rg -n 'OwnerAccess' src/rovo/_report.py` shows it encoded by host
  alone or not at all.
- `.allium-loop/T20-owner-testing.witness.json` exists with `"verdict": "PASS"`, and the
  ledger validates against `ledger.schema.json` with the T20 batched question's items
  ANSWERED, weed tick 1's batched question (items 10 to 14) ANSWERED, weed's question at
  `fc9ad9f` (item 15) ANSWERED, the eleven
  specification open questions OPEN and T19-2 items 1 and 3 ANSWERED.
- Both adversarial reviews ran: `ai_tmp/review/T20-1/` and `ai_tmp/review/T20-2/` each
  hold both findings files and `verdicts.md`.
- `just check-specs` and `just analyse-specs` pass with `docs/specs/` unchanged since
  `53687d9` (`git diff --stat 53687d9 -- docs/specs` empty).
- The suite passes with `GITHUB_ACTIONS=true` as without it (`GITHUB_ACTIONS=true just
  py-test` and `just py-test` report the same counts).
- `import rovo` loads no module outside the standard library and `rovo`; `__all__` is
  `["__version__"]`; `just wheel-smoke` passes with twenty-nine package files.
- `just coverage` stays at or above the floor of 95, with no file omitted.
- `just check-docs` and `just check-agents` pass; no page says a branch a later slice
  implements stops a sync.
- `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty after the commit.

## Verification

```sh
just plan-spec crawl > ai_tmp/T20/plan-spec-crawl.txt
just plan-spec rovo > ai_tmp/T20/plan-spec-rovo.txt
just plan-spec mirror > ai_tmp/T20/plan-spec-mirror.txt
just plan-spec convert > ai_tmp/T20/plan-spec-convert.txt
git diff --stat 53687d9 -- docs/specs
GITHUB_ACTIONS=true just py-test -ra
# The obligation check: exits 1 while any obligation has no test named after it.
python3 -I - <<'EOF'
import json, pathlib, re, sys
names = {n for p in pathlib.Path("tests").rglob("*.py") for n in re.findall(r"def (test_\w+)", p.read_text())}
left = {}
for m in ("crawl", "rovo", "mirror", "convert"):
    plan = json.loads(pathlib.Path(f"ai_tmp/T20/plan-spec-{m}.txt").read_text())["obligations"]
    left[m] = [o["id"] for o in plan if "test_" + re.sub(r"[.-]", "_", o["id"]) not in names]
print({m: len(ids) for m, ids in left.items()})
sys.exit(1 if any(left.values()) else 0)
EOF
just py-test tests/test_owner_testing.py tests/test_owner_challenges.py tests/test_carried_obligations.py tests/test_owner_regressions.py tests/test_answering_host.py tests/test_slice_boundaries.py tests/test_blocks.py tests/test_crawl.py tests/test_report.py tests/test_commands.py -ra
( set -o pipefail; { time just py-test tests/e2e -ra; } 2>&1 | tail -6 )
just py-lint
just py-typecheck
just coverage
just wheel-smoke
uv run --frozen python -I -c "import rovo, sys; print(sorted(m for m in sys.modules if not m.startswith(('rovo', '_')) and m not in sys.stdlib_module_names))"
rg -n 'NotInThisSlice\(' src --glob '!src/rovo/_unfinished.py' > ai_tmp/T20/rules-after.txt; test $? -eq 1  # only "no match" passes
test ! -s ai_tmp/T20/rules-after.txt
rg -n 'time\.sleep\(' tests; test $? -eq 1  # only "no match" passes
test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py
rg -n 'sys\.stdin|subprocess' tests/test_owner_testing.py tests/test_owner_challenges.py tests/e2e/test_owner_sync.py; test $? -eq 1  # only "no match" passes
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
after; the owner options, `effective_policy`, `owner_request_problem`, `request_policy`,
the run lineage, the follow-up run, the breaker climb, the challenge seam and
`save_ownership` as built, and any departure from Facts and steps 1 and 2; the red run,
the tests green at tick 1 and the reconciliation line; every re-propagated test, its
origin slice, its old name and its new hash; every obligation dropped from the owned
list and why; the weed verdict and the witness verdict, each round; both adversarial
reviews, their findings and verdicts, each round; the one batched needs-user question
with every gap found while planning, implementing, in weed or in review, and the
maintainer's answer if one arrived; that no `NotInThisSlice` raise is left, and the
guard module kept for the maintainer to remove or keep; the verification output, each
headed by its commit.

## Open points

- **The T20 batched needs-user question: ANSWERED** (found while planning at `e0f0c44`;
  answered by the maintainer on 2026-11-06, spec `39c1f9c`,
  `ai_tmp/T20/spec-answers/answers.md`; copied into the ledger's `open_questions`). Items
  1 to 4 and C3 became specification open questions, OPEN; items 5 to 9 were decided as
  their interims and stated in the specification. A gap found later joins a new batched
  question.
  1. **The stealth engine: ANSWERED.** Not installed for now: `tier_installed(stealth)`
     is false and a request needing it is refused up front (exit 2) by
     `RefuseMissingEngine`, `rovo fetch --tier stealth` by `RefuseOwnerTestingFetch`; no
     stealth attempt is ever made. Which engine and dependency back it is
     `rovo.allium` open question 1137, OPEN.
  2. **The command-line spelling of owner testing: ANSWERED.** In process only for now:
     `_commands.save_ownership` and `_commands.sync(owner_test=...)`; `cli.py` gains
     nothing and `rovo fetch` no owner option. The spelling is `rovo.allium` open
     question 1138, OPEN.
  3. **The challenge recognisers: ANSWERED.** Rules only, through a seam: no recogniser
     ships, so no run offers a challenge; the challenge rules are built and tested on
     constructed attempts. Which signals mark a challenge is `crawl.allium` open
     question 2670, OPEN.
  4. **How the owner completes a challenge: ANSWERED.** No prompt ships: nothing reads
     standard input or prompts on standard error; the `ChallengePrompt` seam answers a
     waiting challenge only through `drive_run`'s keyword (`FakeChallengePrompt` in
     tests); the browser stays headless. How the owner answers, and a visible browser,
     is `crawl.allium` open question 2671, OPEN.
  5. **`OwnerAccess`: ANSWERED, decided** (`crawl.allium` 73 to 80). The access set is
     always empty; nothing is supplied, applied or serialised.
  6. **Configuration keys with an owner request: ANSWERED, decided** (`rovo.allium` 417
     to 433, `StartSync` guidance 557 to 566). With an owner request, `rovo.toml`'s
     `robots = "ignore"` is accepted and ignored; robots is relaxed only by
     `disabled_controls` holding `robots`. T19-2 item 2 stays as decided at T19.
  7. **Where the owner warning is shown: ANSWERED, decided** (`rovo.allium` 624 to 630).
     The warning text goes to standard error on every owner run and owner refusal, and
     a run under `--json` also emits the `owner_testing_warning` event.
  8. **An owner run's targets: ANSWERED, decided** (`crawl.allium` 241, `Discover`
     guidance). As written: an owner run's targets are empty, its seeds are its
     `active_urls`, its `forced_refetch` is empty, and each host is opened before its
     first fetch (`OpenHostForEntry`).
  9. **Carried, from T18-2 via T19, a challenge waiting when its host trips: ANSWERED,
     decided** (`SettleChallenge`'s comment). Unreachable while rows run one at a time
     (the batch-concurrency interim, `crawl.allium` open question 2668): no other row is
     fetched while a challenge waits and the waiting walk's attempt is not fed, so its
     host cannot trip; a test pins that.
  - **C3 (T20-1 ticket review, needs-user): ANSWERED** with items 3 and 4. The step
    that built a terminal `ChallengePrompt` reading standard input is dropped; no real
    prompt ships.
- **The weed tick 1 batched needs-user question: ANSWERED** (`ai_tmp/T20/weed-1.md`,
  one grouped spec-bug: the rule bodies read `run.policy` where the guidance and the code
  read `request_policy`, with the sub-point of which host's policy judges a redirected
  answer; answered by the maintainer on 2026-11-06, spec `fc9ad9f`,
  `ai_tmp/T20/spec-answers/answers.md` items 10 to 14; copied into the ledger's
  `open_questions`). All decided, none a new open question:
  10. **Per-host policy: ANSWERED, decided.** Every rule body, invariant and contract
      that reads a host's controls reads `request_policy(run, host)`, written
      `Host.policy` (`crawl.allium` 438), as the code already did; `CloseRun` writes
      `host_reports(run.hosts)` (`rovo.allium` 693, guidance 704 to 708).
  11. **A redirected answer: ANSWERED, decided.** It is judged by the answering host's
      policy (`FetchAttempt.answering_host_name` and `answering_policy`, 514 to 524):
      its Retry-After pause, count and past-cap retirement, `HttpRetry`'s pause and
      `wants_escalation` fall on and read that host; the walk still settles as it
      stands and the walk's host keeps `tiers_used` and `render_escalations`. The code
      read the walk host's policy (`pace.py` about 320, `model.py` about 875): a code
      change, owed to implement.
  12. **The answering host's breaker: ANSWERED, decided.** `FeedAnsweringBreaker`
      (2041 to 2053) feeds the answering host's breaker one outcome for a redirected
      answer; the walk's host keeps its page tallies and its `FeedBreaker`.
  13. **Discovery: ANSWERED, decided.** A redirected robots.txt, sitemap or `llms.txt`
      answer, a past-cap Retry-After included, pauses or retires the host that answered
      it when that host is open (`judged`), else the fetching host; adopted robots
      rules and Crawl-delay stay with the requesting origin (`FetchRobots` guidance 892
      to 904).
  14. **Confirmed.** On an error the answering host is the host of the URL last
      requested; `wants_escalation` reads the answering host's policy.
  Two readings the lead accepted are not gaps: a robots.txt hop onto a host the run has
  not opened is judged by the fetching host; the walk's host's breaker is still fed
  for a redirected answer as well as the answering host's.
- **Weed's question at `fc9ad9f`: ANSWERED** (`ai_tmp/T20/weed-1.md`, one spec-bug:
  which host a redirected render subrequest's Retry-After pauses; answered by the
  maintainer on 2026-11-06, spec `53687d9`, `ai_tmp/T20/spec-answers/answers.md` item 15;
  copied into the ledger's `open_questions`). Decided, not a new open question:
  15. **A render subrequest: ANSWERED, decided** (`AttemptTier` guidance, `crawl.allium`
      1745 to 1755). A subrequest sent to allowed host X and redirected to host Y, which
      answers with a Retry-After, pauses Y, the host of its last request, under Y's
      request policy (whether it honours Retry-After, and its cap), never X; when Y is
      not open, X stands in. A subrequest only pauses: it never retires a host and never
      feeds a breaker. The code paused X (`_Render.__call__`): a code change, owed to
      implement.
  Weed's code bug at `fc9ad9f` is owed to implement too: `_Render.through` builds a
  no-DOM render's answer with the walk's URL as its `source_url` after a redirected
  navigation, where `crawl.allium` 148 makes an error's `source_url` the URL last
  requested; pinned by `tests/test_owner_regressions.py`.
- **Review T20-2 r4 C2: ANSWERED** (spec `aeeb818`, `crawl.allium` 1652 to 1658,
  wording only). When an owner run's breaker is above http and the tier hint's
  `reprobe_due` holds, the reprobe drops only the hint, never the breaker's tier: the
  start is the breaker's tier, else http, as `_starting_tier` already does.
- **T19-2 items 1 and 3: ANSWERED** (not on this slice's path; spec `39c1f9c`). Item 1:
  `rovo fetch --config` with no profile named in `[conversion]` or `[fetch]` converts
  with the catalogue's pick for the fetched URL's host, else generic. Item 3: with
  `--config`, a fetched URL outside the file's `[scope]` is still fetched; `[scope]`
  bounds only redirects. Recorded in `.allium-loop/T19-browser-tier.json` and
  `tickets/T19-browser-tier.md`.
- **The final review's answers: ANSWERED** (the maintainer's answers F1 to F4 to the
  final whole-branch review's hand-backs, 2026-11-06, spec `9149df7`,
  `ai_tmp/review/final/spec-answers/answers.md`; no obligation added, removed or
  renumbered, `entity-fields.ExtractedContent` gains `source_url`). All decided, none a
  new open question:
  - **F1, page-file frontmatter: ANSWERED, decided** (`mirror.allium` 157 to 162, 1554
    to 1555). Frontmatter is `key: <JSON value>` lines; a hand-edited non-JSON value is
    `invalid_page_file`. Spec wording matching the code; no code change.
  - **F2, footnotes (convert B1): ANSWERED, decided** (`convert.allium` 143, 284 to
    288). `ExtractedContent.source_url` is the URL `extract` was given, and only a
    same-page reference becomes `[^n]`: a bare `#id`, or a link whose target without its
    fragment is the page URL without its fragment. A link to another page stays a link
    even when its fragment names a local note. Built in `_convert/fidelity.py`.
  - **F3, render subrequest methods (crawl B1): ANSWERED, decided** (`crawl.allium`
    1748 to 1750). A render request whose method is not GET or HEAD is aborted, never
    sent; GET and HEAD are fetched through rovo as before. Built in
    `_crawl/browser.py`; the T19-pinned `Answers` seam in `tests/test_browser_engine.py`
    already carried the request's method, so it was not widened.
  - **F4, clarifications: ANSWERED, decided** (spec wording only). Only a retryable
    answer's `Retry-After` (an error, a 429 or a 5xx) pauses a host for a render
    subrequest, as `_Render.__call__` does; a crash while the report is assembled has
    saved the manifest and frontier only if finalisation finished before it
    (`rovo.allium` 814 to 818); the content root's own id is not a source id
    (`BodyShape`, as T09 decided). No code change.
  At `9149df7` the eleven open questions sit at `convert.allium` 493 to 495,
  `crawl.allium` 2670 to 2675 and `rovo.allium` 1140 and 1141; the line numbers cited
  elsewhere in this ticket are those of the spec each paragraph names.
- **The specification's open questions.** All eleven stay **OPEN**: `convert.allium` 486
  to 488 and `crawl.allium` 2666, 2667 and 2669 are not on this slice's path; 2668
  (batch concurrency) is, only as the interim that makes item 9 unreachable; the four
  added at `39c1f9c` (`crawl.allium` 2670 and 2671, `rovo.allium` 1137 and 1138) are,
  as the interims items 1 to 4 state.
- **`NotInThisSlice`.** After this slice no raise is left; the guard class, the root's
  handler and the two tests that inject it remain. Whether to delete them is the
  maintainer's call, recorded in the hand-back notes.
