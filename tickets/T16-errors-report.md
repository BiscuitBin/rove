---
id: T16
title: "Errors and the report: rovo sync skips non-HTML answers, refuses in the specified order with a refused report, survives an interrupt or a crash with a report, ranks every exit code, prints --json progress, reads ROVO_ variables and --set flags, and rovo report shows the last report"
status: open
depends_on: [T15]
parallel_with: []
branch: full-final-prototype
estimated_size: L
---

# T16: Errors and the report: rovo sync skips non-HTML answers, refuses in the specified order with a refused report, survives an interrupt or a crash with a report, ranks every exit code, prints --json progress, reads ROVO_ variables and --set flags, and rovo report shows the last report

## Context

T09 (`fd1b423`) to T15 (`6cdd087`, follow-up `cc46695`) are slices 1 to 7. `rovo sync`
reads each origin's robots.txt, paces and retries per host name, reads sitemaps and
`llms.txt`, fetches the seeds, the pages discovery admits and the pages they link to,
keeps each page through its lifecycle, publishes it at `pages/<host>/<path>`, writes the
indexes and `crawl-report.json`, and a second sync is incremental. They fixed every
pattern this slice follows: the private subpackages `rovo._convert`, `rovo._mirror` and
`rovo._crawl` with `rovo._config`, `rovo._report` and `rovo._commands` above them (import
direction enforced by `tests/test_import_direction.py`), the `Fetcher` seam, the `Timer`
seam of `src/rovo/_crawl/pace.py` (`FixedClock`, `SteppingTimer`, `FakeFetcher`,
`ScriptedFetcher` and `StampingFetcher` in `tests/fakes.py`), obligation-named tests
(`test_<obligation id>`), the end-to-end harness `serve_site` in `tests/e2e/conftest.py`
with scripted answers (`Answer`, `DROP`, `script=`, `always=`) and its request log, the
state files of `docs/reference/mirror.md`, and the development guard
`rovo._unfinished.NotInThisSlice`. Read `tickets/T15-lifecycle.md` (its Context table,
Facts and Open points), `tickets/T14-incremental.md` (its Context table),
`src/rovo/_commands.py`, `src/rovo/_config.py`, `src/rovo/_report.py`, `src/rovo/cli.py`,
`src/rovo/_crawl/run.py` (`drive_run`, `dispose_fetch`, `prepare_run`) and
`tests/e2e/test_lifecycle_sync.py` before starting.

This is slice 8 of T08 to T20, run in this worktree on `full-final-prototype`. Until now
the error paths around a run are thin: a non-HTML answer stops the run
(`NotInThisSlice("DisposeFetch")`, `run.py` 1432); every failed `StartSync` guard exits
usage with no report (`_commands.sync` 72, `_start_problem` 112, `_refuse` 300); there is
no `--yes`, `--json`, `--url` or `--path` (`cli.py` 67 takes `--dry-run` only, and
`_start_sync` 145 builds `SyncOptions` with `confirmed=False`, `json_events=False` and no
targets); an operator interrupt (Ctrl-C) or an uncaught error leaves the previous report
in place and a traceback; `CrawlResult.backed_off` (`run.py` 151) collects
`HostBackedOff` events nobody prints; `resolve_config` (`_config.py` 176) reads only the
built-in defaults and `rovo.toml`; and there is no `rovo report`. `TallyFailedUrl`,
`EntryFails` and `PrepareRun`'s re-pending of failed rows already work (T12), and
`rank_and_write_report` (`_report.py` 344) already ranks all five inputs. The
specification base is `bad753c` (`git diff --stat bad753c HEAD -- docs/specs` is empty);
every specification line number below is at `bad753c`, every source line number at
`cc46695`.

### The specified path, and what this slice does with each rule on it

| Class | Rules |
| --- | --- |
| **Realised** (every branch reachable in this slice, or constructible on unit inputs where noted) | `rovo.allium`: the configuration layers of `Configuration` (60 to 101: built-in defaults, `rovo.toml`, `ROVO_<SECTION>__<FIELD>` variables, then flags, key by key; `ROVO_MIRROR__PRUNE` and `ROVO_CRAWL__REFOLLOW_UNCHANGED_LINKS` included); `SyncOptions` (103) with `confirmed`, `json_events`, `urls` and `paths` from flags; `RefuseSyncOnBadConfig` (324), `RefuseSyncOnChangedRoot` (333), `RefuseOffHostTarget` (343), `RefuseUnknownTargetPath` (358), in that order after `RefuseSyncWithoutDirectory` (315) and before the two later refusals the code already checks (`RefuseMissingEngine` 374, `RefuseInvalidOwnerRequest` 407, whose own obligations stay T19's and T20's); `ReportRefusal` (430) for every refusal `SyncRefused` names, the two later ones included; `StartSync` (463) its `urls` and `paths` guards; `TallySkippedUrl` (562, on unit inputs only: `UrlSkippedBlocked` comes from `SelectBatch`'s all-tripped branch, T18); `AnnounceBackoff` (576); `RankAndWriteReport` (673) its `done` event and every input of its ranking (`blocked`, `target_skipped` and the owner-testing input on unit inputs only); `InterruptSync` (709), `RecordCrash` (721), `RecordCrashAfterRun` (736); `ShowReport` (814), `RefuseShowReport` (825); the invariants `RefusedReportsHaveNoRun`, `RunReportsNameTheirRun`, `OneOpenReportPerMirror` (878 to 892); the guarantees `SyncExitCodes` (916), `VerifyIndexReportExitCodes` (928) its `report` sentence, `ReportOnEveryExit` (936), `ProgressOnRequest` (942) and `RefusalsInOrder` (950); the `ReportView` surface (962). `crawl.allium`: `DisposeFetch` (1895) its `skipped_not_html` branch (1963); `InterruptRun` (2152) and `EndRun` (2170) its interrupted branch; `FailDiscardedEntry` (2039) under its own obligation names; the frontier edges `in_progress -> skipped_not_html`, `skipped_not_html -> pending` (by `PrepareRun`'s written-page recheck) and `in_progress -> pending` (by `InterruptRun`); the `Run` edge `running -> interrupted`; the `SyncControl` guarantees `ReportableOutcome` and `NoResume` (2278 to 2287). |
| **Traversed, nothing new to do** | `TallyFailedUrl` (546) and `EntryFails` (1983): a failed URL already gets a `failed_urls` row and a `failed` change. `PrepareRun` (647): already re-pends every failed row on every sync, the interim of the specification's second open question (`crawl.allium` 2411), which this slice keeps. `CloseRun` (631): already maps an interrupted run to `report_status: interrupted` and carries `run.error`; finalisation runs after an interrupted run too (its guidance). `FinishRun` (2133): `unresolved_urls` already excludes `skipped_not_html` (`_UNRESOLVED`, `run.py` 115). `TallyDiscoveryProblem` (569), `TallyRemoval` (595), `TallyFinalisedPage` (608), `TakeBrokenLinks` (657), `FinaliseRunReport` (665). `mirror.allium`: nothing; a known page whose URL now answers non-HTML is simply not delivered, so the mirror keeps it as it stands. |
| **Later slices'** | The targeted run: `PrepareRun` (`run.py` 235) and `Discover` (270) keep their raises for named targets, so a sync with `--url` or `--path` that passes the refusals stops there (scope note, Open points); the edge `duplicate -> pending`, reached only by a targeted or owner-testing run. `AnnounceTrip` (581), `TallyBlockedUrl` (555), `SelectBatch`'s all-tripped branch (`run.py` 1147) and every block verdict (T18). `RefuseMissingEngine`'s and `RefuseInvalidOwnerRequest`'s obligations, `AnnounceOwnerWarning` (590), `CrawlReport.baseline_run_id`, `preceding_run_id` and `requested_owner_test` (T19, T20). `Verify`, `RefuseVerify`, `ReportVerification` and the quality gates (T17); `rovo fetch` (T19). The `MirrorCommands` and `SyncControl` surfaces' actor and provides obligations, which list the operations of T17, T19 and T20 (the last of those slices). |
| **Outside this slice; reaching one still stops the run** | The 23 raises at `cc46695` (`ai_tmp/T16/notinthisslice-cc46695.txt`) all stay, by `rule=`: `sitemap_admitted` (`sitemaps.py` 82); in `run.py`, `PrepareRun` (235), `Discover` (270), `RetireHostOnLongRetryAfter` (348, 792, 1769), `RetireHostOnLongCrawlDelay` (352), `EnqueuePageLinks` (658), `RefollowUnchangedLinks` (699), `SelectBatch` (1147), `AttemptTier` (1265), `classify_block` (1293, 1632, 1634), `DisposeFetch` (1432), `ConvertFetched` (1516), `StartRun` (1693), `Escalate` (1774), `BreakerTrips` (1777); `assign_path` (`urls.py` 150); `UncarryableBecomesIsland` (`fidelity.py` 158, 192) and `BodyShape` (558). `DisposeFetch`'s raise stays, narrowed to a block verdict other than `none` (T18): a non-HTML answer no longer reaches it. A `NotInThisSlice` is never taken for a crash (Facts). |

### Facts a later reader would otherwise rediscover

- **The refusals, in order, and the refused report.** `_commands.sync` checks, in the
  specification's order: no directory or no loadable manifest (`RefuseSyncWithoutDirectory`:
  usage, no report, as today); an invalid configuration, no seeds or an
  `unblocking.provider` (`RefuseSyncOnBadConfig`); a changed root without `--yes`
  (`RefuseSyncOnChangedRoot`); a `--url` that is not http(s) or not on an allowed host
  (`RefuseOffHostTarget`); a `--path` that is not a written page's mirror-relative path,
  a removed page's path included (`RefuseUnknownTargetPath`); a missing engine; then
  `robots = "ignore"` without an owner test (`owner_request_problem`'s first sentence).
  The first problem wins and no request is made. Each of the last six raises
  `SyncRefused` and `ReportRefusal` writes `crawl-report.json` with `run_id: null`,
  `report_status: refused`, `exit_code: usage`, `refusal_reason` the specification's
  text exactly (`"invalid configuration"`, `"changed root requires confirmation"`,
  `"invalid or off-host target"`, `"unknown target path"`, `"configured tier is not
  installed"`, and for the robots case the problem `owner_request_problem` names),
  `configuration` the resolved settings (an invalid one with its `problems`), `options`
  as asked, `kind` `update` when the mirror holds a written page, `effective_policy:
  null`, every count zero and every list empty, `started_at` and `finished_at` the
  clock's now. Standard error keeps today's detailed line. A refusal saves no manifest,
  frontier or run: `runs.json` and `.rovo/` are untouched, and only the report is
  replaced.
- **The options.** `rovo sync` gains `--yes` (`confirmed`), `--json` (`json_events`),
  `--url URL` and `--path PATH` (each repeatable, `urls` and `paths`); `interactive`
  stays `sys.stdin.isatty()`. A `--url` or `--path` that passes the refusals reaches
  `PrepareRun`'s targeted raise: the sync stops, exits 1 and leaves the previous report,
  as `render_mode = "auto"` with an installed browser already does (scope note).
- **The configuration layers.** `resolve_config(out_dir, environ, overrides)` (both new
  parameters defaulting to empty, so `rovo index` and the earlier tests are unchanged)
  merges, key by key: the built-in defaults, `rovo.toml`, then each environment variable
  named `ROVO_<SECTION>__<FIELD>` (section and field matched case-insensitively against
  `rovo.toml`'s `[section] field` names, so `ROVO_MIRROR__PRUNE` is `mirror.prune` and
  `ROVO_CRAWL__REFOLLOW_UNCHANGED_LINKS` is `crawl.refollow_unchanged_links`), then each
  `--set SECTION.FIELD=VALUE` flag, later ones winning. The specification excludes flag
  and file syntax, so this is the slice's syntax: a variable or flag value is read as one
  TOML value (`3`, `true`, `["/a/"]`, `"x"`), and a value that does not parse as one is
  the raw string; the same `_SCHEMA` reader then judges it, so a bad value, an unknown
  section and an unknown key from any layer are problems named by their key path
  (`scope.max_depth: invalid value 'deep'`), and the configuration is invalid. A
  variable starting `ROVO_` that lacks the `__` separator is not a configuration
  variable and is ignored; a `--set` with no `=` or no `.` is a problem. `hash` covers
  the resolved configuration, so it moves with an environment or flag value.
  `_commands.sync` passes `os.environ` and the `--set` values; `starter_config` does not
  change.
- **Progress.** A `ProgressEvent(event, host, until)`, in `rovo._crawl.model` because
  `pace.py` raises one and `rovo._crawl` never imports the root, reaches a sink the root
  hands the run (`AnnounceBackoff` is the root's `announce_backoff`, which turns a
  `HostBackedOff` into the `host_backoff` event the sink receives): `rovo.cli`
  wires it to standard output under `--json`, one JSON object a line,
  `{"event": ..., "host": ..., "until": ...}` with sorted keys and `until` an ISO 8601
  UTC timestamp or null; without `--json` there is no sink and nothing is printed.
  `host_backoff` is written live, when `HostBackedOff` is raised (`back_off` and
  `pause_for_cap` in `pace.py`, 136 and 162), not from `CrawlResult.backed_off` after the
  run; `done` is written by `RankAndWriteReport`, once, last, after the report. `start`
  and `page` are interim (Open points item 2). `breaker_tripped` (T18) and
  `owner_testing_warning` (T20) are not raised in this slice. A dry run's listing stays
  plain text on standard output, ahead of its `done` event. A refusal raises no event.
- **Interrupts and crashes.** From the moment `StartRun` creates the run, `drive_run`
  catches `KeyboardInterrupt` (an operator interrupt: `InterruptSync`, which sets
  `interrupt_requested`) and any `Exception` that is not `NotInThisSlice` (`RecordCrash`:
  `run.error` is `"<ExceptionType>: <message>"`, and `interrupt_requested`); then
  `InterruptRun` returns every in-progress row to pending and takes the unresolved
  snapshot, and `EndRun` ends the run `interrupted`. `InterruptSync` and `RecordCrash`
  are the root's rules: they live in `rovo._report` and reach `drive_run` as one
  callable the root passes, since `rovo._crawl` never imports the root. The result flows
  on as any run's does: `CloseRun` (`report_status: interrupted`, `error`), the finalise
  pass (pages stored before the interrupt are published, links and indexes rewritten),
  the saves and `RankAndWriteReport`, which ranks it partial (exit 1). An uncaught error
  after the run has ended (in `CloseRun`, the finalise pass, the saves or the report's
  assembly) is `RecordCrashAfterRun`: `report.error` is set, `report_status` becomes
  `interrupted` and `RankAndWriteReport` writes the report as it stands (exit 1); a
  `KeyboardInterrupt` there is taken the same way (Open points item 4); the manifest and
  the frontier are not saved, and the run's record is appended to `runs.json` so its id
  is never reused (Open points item 5). An error before `StartSync` has created the
  report (loading the manifest, resolving the configuration) propagates as today: there
  is no report to write. `NotInThisSlice` is a development guard, not
  product behaviour: it passes through every handler unchanged and `_commands.sync`
  keeps its stop (exit 1, previous report in place), so `tests/test_slice_boundaries.py`
  keeps its `pytest.raises(NotInThisSlice)` assertions.
- **A non-HTML answer.** `dispose_fetch`'s last branch: an ok answer that is not HTML
  and not raw-unchanged counts toward `host.fetched` and settles its row
  `skipped_not_html`; no candidate is delivered, no `failed_urls`, `changes`,
  `skipped_urls` or `unresolved_urls` row is written (`skipped_urls` is the breaker's,
  T18), and the sync's exit code is unaffected. A known page that now answers non-HTML
  keeps its record and its file; the next full sync re-pends its row as a written page
  (`skipped_not_html -> pending`). A URL with no page that answered non-HTML is never
  fetched again by a full sync (Open points item 3).
- **The report command.** `rovo report OUT_DIR` prints `OUT_DIR/crawl-report.json` as
  written (its JSON, a final newline) on standard output and exits 0 (`ShowReport`);
  with no loadable manifest, or no report file that reads as JSON (`latest_report` is
  null), it prints the problem on standard error and exits 2 (`RefuseShowReport`).
  `report_path` moves from `rovo._report` to `rovo._mirror.state`, beside
  `manifest_path`, and `rovo._report` imports it from there, so `rovo report` reads the
  file with `rovo._mirror.state` alone and loads neither httpx nor `rovo._crawl` (like
  `rovo index`).
- **The exit ranking.** `rank_and_write_report` already takes the most severe of its
  five inputs; this slice feeds it `run.status = interrupted` and `report.error`, and its
  test enumerates every input alone and in combination (ok 0, partial 1, usage 2 only
  from a refusal, blocked 3, quality 4), the inputs later slices raise constructed on unit
  inputs.
- **What `http.server` answers.** A `.txt` fixture file is served `text/plain`; a page
  that fails on every try is scripted `always={"/guide/broken.html": Answer(500)}`. So
  `tests/e2e/conftest.py` is read, not changed. A sync in process uses `SteppingTimer` or
  `FixedClock`, which never sleep.
- **The obligation source.** `just plan-spec <module>` over `docs/specs/<module>.allium`
  at `bad753c`, written to `ai_tmp/T16/plan-spec-<module>.txt` (its echo line to
  `ai_tmp/T16/plan-spec-<module>.err`): crawl 382, rovo 167, mirror 200, convert 47
  obligations. The obligations with no test named after them at `cc46695` are in
  `ai_tmp/T16/uncovered-<module>.txt` (crawl 130, rovo 95, mirror 22, convert 0, by
  `ai_tmp/T16/uncovered.py`); the owned set of step 3 is `ai_tmp/T16/owned.json` (61, by
  `ai_tmp/T16/owned.py`, which checks each id is in the plan and uncovered); the
  `NotInThisSlice` raises at `cc46695` are in `ai_tmp/T16/notinthisslice-cc46695.txt`.
  The copies are scratch, regenerated by step 0.

## Goal

From a clean checkout, against served fixture sites, `rovo sync` settles a non-HTML
answer as `skipped_not_html` instead of stopping; refuses a bad configuration, a changed
root without `--yes`, an off-host `--url` and an unknown `--path` in the specified order,
each with a refused `crawl-report.json` and no request; leaves a report on every exit,
an interrupted or crashed run included, with the run's in-progress rows back to pending
and its stored pages published; ranks every exit code; prints JSON progress under
`--json`; reads `ROVO_<SECTION>__<FIELD>` variables and `--set` flags over `rovo.toml`;
and `rovo report` prints the last report. Every owned obligation listed under Steps has a
test named after its id; no test this slice adds or edits sleeps for real (the suite's
one real wait is T12's installed-script Crawl-delay scenario, kept by design);
`just check` is green; the Allium loop's witness record says `PASS`.

## Non-goals

- No targeted run: `PrepareRun`'s and `Discover`'s raises for named targets stay; the
  two targeted refusals and the `--url` and `--path` options are this slice's (scope
  note, Open points).
- No block verdict, breaker, skipped-blocked rows or `breaker_tripped` event (T18); no
  `rovo verify`, quality gates or `fail_on_low_quality` beyond the ranking input that
  already exists (T17); no browser, `rovo fetch` or engine refusal obligations (T19); no
  owner testing (T20).
- No harness change: `tests/e2e/conftest.py` is read, not changed (Facts).
- No new `rovo.toml` key; no new dependency; no new module, so `scripts/wheel_smoke.py`'
  `PACKAGE_FILES` does not move.
- No specification change: `docs/specs/` is read, not edited. The six `open question`
  blocks stay open (`crawl.allium` 2410 to 2412, `convert.allium` 473 to 475). A
  specification gap found while planning, implementing, in weed or in review is never
  resolved in code or in the specification: every such gap joins the one batched
  needs-user question (Open points) and the ledger's `open_questions`.
- No change to the public API: `__all__` stays `["__version__"]`, so
  `docs/reference/api.md` does not move. No decision record changes.
- No adversarial review checkpoint: this slice has none.
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `src/rovo/cli.py` | shared, own lines | `rovo sync` gains `--yes`, `--json`, `--url`, `--path` and `--set`, and wires the progress sink under `--json`; the new `rovo report` command, importing only `rovo._commands` in its body |
| `src/rovo/_commands.py` | shared, own lines | the refusals in order and `ReportRefusal`'s report; `SyncOptions` from the options; `resolve_config` with `os.environ` and the `--set` values; `RecordCrashAfterRun` around everything after the run; the progress sink handed to the run; `report` (`ShowReport`, `RefuseShowReport`); the module and function docstrings |
| `src/rovo/_config.py` | shared, own lines | `resolve_config`'s environment and flag layers (Facts); the module docstring |
| `src/rovo/_report.py` | shared, own lines | `report_refusal`, `tally_skipped_url`, `announce_backoff`, `interrupt_sync`, `record_crash`, `record_crash_after_run`; `RankAndWriteReport`'s `done` event; the event's JSON line; `report_path` imported from `rovo._mirror.state` |
| `src/rovo/_crawl/model.py` | shared, own lines | `ProgressEvent` and the progress sink on `Run` or `RunRequest`; the `UrlSkippedBlocked` trigger (absent at `cc46695`; `TallySkippedUrl` takes it, raised by nothing until T18); nothing else unless step 4 shows a field missing |
| `src/rovo/_mirror/state.py` | shared, own lines | `report_path` (moved from `rovo._report`, unchanged) |
| `src/rovo/_crawl/pace.py` | shared, own lines | `back_off` and `pause_for_cap` hand their `HostBackedOff` to the run's sink as they raise it |
| `src/rovo/_crawl/run.py` | shared, own lines | `dispose_fetch`'s `skipped_not_html` branch, its raise narrowed to a block verdict; `interrupt_run`; `drive_run` catching an interrupt or a crash after `StartRun` (Facts) and appending a run's record on its own for `RecordCrashAfterRun`; `start` and `page` events (Open points item 2); the docstrings |
| `tests/fakes.py` | shared, own lines | a fetcher wrapper raising a given exception on a given URL, beside `FakeFetcher` |
| `tests/test_commands.py` | shared, own lines (re-propagated) | the rovo obligations of step 3 on the command; T09's `test_rule_failure_StartSync_2`, `_3`, `_6` and `_7` and the module docstring re-propagated (a refusal now writes a refused report; ledger notes, T09) |
| `tests/test_report.py` | shared, own lines | the rovo obligations of step 3 on the report; the ranking enumeration |
| `tests/test_crawl.py` | shared, own lines | the crawl obligations of step 3; `DisposeFetch`'s `skipped_not_html` branch; `InterruptRun`'s and `RecordCrash`'s run-level cases |
| `tests/test_config.py` | shared, own lines | the layer precedence, the two named variables, a bad value and an unknown key from each layer, the hash |
| `tests/test_cli.py` | shared, own lines | the new options and `rovo report` through `CliRunner` (option wiring with `rovo._commands.sync` monkeypatched to record its arguments); `rovo report` through the installed script; `rovo report` loads neither httpx nor `rovo._crawl` |
| `tests/test_slice_boundaries.py` | shared, own lines (re-propagated) | `test_a_later_slices_answer_stops_the_run` loses its `not-html` case; `test_a_known_pages_non_html_answer_stops` replaced by `test_a_known_pages_non_html_answer_settles_skipped_not_html` (the page kept, the row `skipped_not_html`; ledger note, T14) |
| `tests/test_regressions.py` | shared, own lines | only an earlier test the red run shows red because a refusal now writes a report (ledger note naming its slice); one test per divergence weed finds |
| `tests/e2e/test_errors_report_sync.py` | new | the end-to-end scenarios (Acceptance criteria) and their site-generating helper; no unit test is named `test_errors_report_sync.py` |
| `docs/reference/cli.md` | shared, own lines | `rovo sync`: the options, the environment and `--set` layers, the refusals in order and the refused report, interrupts and crashes, `--json` events, a non-HTML answer, the exit codes (1 gains interrupted and crashed); the new `rovo report` section; line 16's later commands lose `report`; line 226's "progress output is a later slice's" and the later-slice sentence (234 to 243) lose what this slice realises |
| `docs/reference/mirror.md` | shared, own lines | the `rovo.toml` section: the four layers and where the variable and flag syntax is described (`cli.md`); the `crawl-report.json` section: a refused report, `error` and `report_status: interrupted`; `runs.json`: a run crashed after it ended is still recorded |
| `docs/reference/testing.md` | shared, own lines | `tests/e2e/test_errors_report_sync.py` |
| `docs/project/repository-map.md` | shared, own lines | the tree gains `test_errors_report_sync.py` |
| `docs/project/purpose-and-scope.md`, `README.md` | shared, own lines | only the sentences the step 6 search shows false (`rovo report`, a stop now settled) |
| `AGENTS.md` | shared, own lines | line 10 to 12's "today" sentence gains `rovo report` printing the last report; the required phrases stay in always-visible text |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` Added entry: errors and the report |
| `tickets/README.md`, `tickets/T16-errors-report.md` | ticket | index row, graph, slice bullet, this ticket |
| `.allium-loop/T16-errors-report.json`, `.allium-loop/T16-errors-report.witness.json` | gitignored | the loop ledger and the witness record; never committed |

`pyproject.toml`, `uv.lock`, `pytest.ini`, `.coveragerc`, `ruff.toml`, `mypy.ini`,
`Justfile`, `scripts/wheel_smoke.py`, `src/rovo/__init__.py`, `src/rovo/_exit.py`,
`src/rovo/_mirror/` but `state.py`, `src/rovo/_convert/`, `src/rovo/_crawl/fetch.py`,
`src/rovo/_crawl/sitemaps.py`, `tests/e2e/conftest.py`, `tests/test_import_direction.py`,
`docs/reference/configuration.md` (its topic is the repository's toolchain; its line 73
stays true of it), `docs/decisions/` and `docs/specs/` are read, not changed. A file not
in this table that turns out to need a change is added to the table in the same change
with its reason, or handed back if it is a decision record or a specification.

## Steps

This slice has no **Adversarial review** checkpoint (`tickets/CONVENTIONS.md` §14): the
witness of step 7 is its only independent check.

0. `just check` baseline on the untouched worktree at `cc46695` plus this ticket, last
   line quoted, and `( set -o pipefail; { time just py-test tests/e2e -ra; } 2>&1 | tail -6 )`
   with its wall time. Scratch output goes in `ai_tmp/T16/`. Write `just plan-spec
   <module>` for each of `crawl`, `rovo`, `mirror` and `convert` to
   `ai_tmp/T16/plan-spec-<module>.txt`; run `ai_tmp/T16/uncovered.py` and
   `ai_tmp/T16/owned.py`, and confirm the 61 ids. While the worktree is at `cc46695`,
   write `rg -n 'NotInThisSlice\(' src > ai_tmp/T16/notinthisslice-cc46695.txt`. Create
   the ledger `.allium-loop/T16-errors-report.json` against
   `allium-skill-reference/allium/schemas/ledger.schema.json`, shaped like T15's: `goal`
   `"T16-errors-report"`, `mode` `"spec-first"`, `tick` 0, `specification_base`
   `bad753c`, `obligation_source` the four files, and `open_questions` holding the six
   specification open questions verbatim, the T16 batched question's items (Open points,
   item 1 the carried T15 follow-up item) and the carried T17 and T18 items, each marked
   OPEN. Read `.agents/skills/propagate/SKILL.md`, `.agents/skills/weed/SKILL.md`,
   `.agents/skills/witness/SKILL.md` and `.agents/skills/python-change/SKILL.md` before
   step 3.

1. **The root's rules.** In `_config.py`, the environment and flag layers; in
   `_report.py`, `report_refusal`, `tally_skipped_url`, `announce_backoff`,
   `interrupt_sync`, `record_crash`, `record_crash_after_run` and the `done` event, each
   returning `False` or `None` when its guards do not hold; in `_commands.py`, the
   refusals in order, `report` and the handling after the run; in `cli.py`, the options
   and `rovo report`. Every value comes from the configuration, the clock or `CONFIG`,
   never a literal; the refusal reasons are the specification's text.

2. **The crawl's rules.** In `run.py` and `pace.py`, per the Context table and Facts:
   `dispose_fetch`'s `skipped_not_html` branch and its narrowed raise; `interrupt_run`
   and `end_run`'s interrupted branch; `drive_run`'s interrupt and crash handling; the
   progress sink and the `host_backoff`, `start` and `page` events.

3. **Tests first, from the obligations** (the `propagate` skill, spec-first). Write a
   failing test for each owned obligation below into the test file of its module, named
   `test_<obligation id with dots and hyphens as underscores>`, its docstring quoting the
   obligation's description from the plan-spec file. Each `rule_failure` test makes
   exactly one `requires` clause false. Generated tests satisfy EditorConfig
   (indentation in 4-space multiples in `*.py`, string literals included), ruff and
   mypy, since the gate stages them. Run `just py-test` and record the red run in
   `ai_tmp/T16/red.txt`, its summary line under `last_results.propagate` in the ledger.
   Record each generated, re-propagated or extended test file's SHA-256 under
   `generated_test_hashes` (`tests/test_config.py` and `tests/test_cli.py`, which gain
   hand-written tests only, and `tests/e2e/test_errors_report_sync.py` included), and the reconciliation line (`N obligations, M covered, K
   uncovered`) over the owned set. A test changed after the red run is re-recorded: a
   new hash, `tick` incremented, a ledger note naming the test and why; never silently.
   An obligation a test cannot reach without a later slice's behaviour is not owned:
   move it to the hand-back notes with its reason rather than writing a vacuous test.

   Owned obligations, new in this slice (ids as `just plan-spec <module>` emits them at
   `bad753c`; 61):

   - **`rovo`** (51). In `tests/test_commands.py`: `value-equality.SyncOptions`,
     `entity-fields.SyncOptions`, `rule-success.RefuseSyncOnBadConfig`,
     `rule-failure.RefuseSyncOnBadConfig.1`, `.2`,
     `rule-success.RefuseSyncOnChangedRoot`, `rule-failure.RefuseSyncOnChangedRoot.1` to
     `.3`, `rule-success.RefuseOffHostTarget`, `rule-failure.RefuseOffHostTarget.1` to
     `.4`, `rule-success.RefuseUnknownTargetPath`,
     `rule-failure.RefuseUnknownTargetPath.1` to `.5`, `rule-failure.StartSync.4`,
     `rule-failure.StartSync.5`, `rule-success.InterruptSync`,
     `rule-failure.InterruptSync.1`, `.2`, `rule-success.RecordCrash`,
     `rule-failure.RecordCrash.1`, `.2`, `rule-success.RecordCrashAfterRun`,
     `rule-failure.RecordCrashAfterRun.1` to `.4`, `rule-success.ShowReport`,
     `rule-failure.ShowReport.1`, `.2`, `rule-success.RefuseShowReport`,
     `rule-failure.RefuseShowReport.1`. In `tests/test_report.py`:
     `entity-optional.CrawlReport.error`, `entity-optional.CrawlReport.refusal_reason`,
     `entity-optional.CrawlReport.effective_policy`, `rule-success.ReportRefusal`,
     `rule-entity-creation.ReportRefusal.1`, `rule-success.TallySkippedUrl`,
     `rule-failure.TallySkippedUrl.1` (unit inputs: a constructed `UrlSkippedBlocked`),
     `rule-success.AnnounceBackoff`, `invariant.RefusedReportsHaveNoRun`,
     `invariant.RunReportsNameTheirRun`, `invariant.OneOpenReportPerMirror`,
     `surface-actor.ReportView`, `surface-exposure.ReportView`.
   - **`crawl`** (10), in `tests/test_crawl.py`:
     `transition-edge.Run.running.interrupted`, `entity-optional.Run.error`,
     `transition-edge.FrontierEntry.in_progress.pending`,
     `transition-edge.FrontierEntry.in_progress.skipped_not_html`,
     `transition-edge.FrontierEntry.skipped_not_html.pending` (a known page's row
     re-pended by the next full sync), `rule-success.FailDiscardedEntry`,
     `rule-failure.FailDiscardedEntry.1`, `.2`, `rule-success.InterruptRun`,
     `rule-failure.InterruptRun.1`.
   - **`mirror`** and **`convert`**: none.

   Extended, not new (re-propagated in place, each re-hashed in this slice's ledger with
   a note naming its origin slice; T09's to T15's ledgers are never edited): the
   `tests/test_commands.py` and `tests/test_slice_boundaries.py` tests the Files touched
   table names, renamed where it says, the old name in the ledger note; every other
   earlier test the red run shows red because a refusal now writes a report or a
   non-HTML answer no longer stops the run, each with only that expectation moved. Claim
   an earlier test "passes unedited" only where it does; the hand-back notes list every
   earlier test this slice edited.

   Guarantees and black boxes (no obligation id; hand-written), in the file of the rule
   named: `RefusalsInOrder` (`tests/test_commands.py`: for each adjacent pair of
   refusals, a request with both problems is refused for the first, with no request in
   the fetcher's log, and `RefuseSyncWithoutDirectory` writes no report);
   `ReportOnEveryExit` (a refused, a dry, an interrupted, a crashed-in-run and a
   crashed-after-run sync each leave `crawl-report.json` with its exit code, kind,
   status and, for a crash, the error text); `SyncExitCodes` and the ranking
   (`tests/test_report.py`: each input alone and two together, the higher winning);
   `ProgressOnRequest` (the sink receives `start`, `page`, `host_backoff` when a retry
   backs off and exactly one `done`, last; no sink, nothing printed; a dry run's listing
   still plain text); `ReportableOutcome` and `NoResume` (`tests/test_crawl.py`: after an
   interrupt no fetch starts, every in-progress row is pending, and the next run fetches
   the row again); `resolve_config`'s layers (`tests/test_config.py`: a key set in all
   four layers takes the flag's value, then the variable's, then the file's; each layer
   alone; `ROVO_MIRROR__PRUNE=true` and `ROVO_CRAWL__REFOLLOW_UNCHANGED_LINKS=false`
   resolved; an unknown section, an unknown key and a bad value from the environment and
   from `--set` each named in `problems`; a `ROVO_` name with no `__` ignored; `hash`
   moving with a variable); `latest_report` (a missing and an unparsable report are
   null); a `NotInThisSlice` raised inside the run still propagating, with no report
   written (`tests/test_commands.py`).

   Not owned, and why, for the hand-back notes: `transition-edge.FrontierEntry.duplicate.pending`
   and the targeted branches of `PrepareRun` and `Discover` (scope note);
   `rule-*.RefuseMissingEngine`, `rule-*.RefuseOwnerTestingFetch`,
   `rule-*.RefuseMissingFetchTier`, `rule-*.FetchOneUrl` (T19);
   `rule-*.RefuseInvalidOwnerRequest`, `rule-success.AnnounceOwnerWarning`,
   `entity-optional.CrawlReport.baseline_run_id`, `.preceding_run_id`,
   `.requested_owner_test`, `derived.Run.is_owner_testing` and every owner-testing
   obligation (T20); `rule-*.TallyBlockedUrl`, `rule-*.AnnounceTrip`,
   `value-equality.BlockedUrl`, `entity-fields.BlockedUrl` and the blocked and
   skipped-blocked edges (T18); `rule-*.Verify`, `rule-*.RefuseVerify`,
   `rule-success.ReportVerification`, `GateFailure` and `LowConfidencePage` (T17);
   `derived.Run.targeted` (reachable only by a targeted run: scope note);
   `surface-actor.MirrorCommands`, `surface-provides.MirrorCommands`,
   `surface-actor.SyncControl`, `surface-provides.SyncControl` (they list the operations
   of T17, T19 and T20); every other uncovered obligation in the four files, each
   belonging to the slice its rule names.

4. **Root, crawl, report and command.** Steps 1 and 2. Unit cases on `FakeFetcher`,
   `ScriptedFetcher` and the raising wrapper with `FixedClock`.
   `just py-test tests/test_commands.py tests/test_report.py tests/test_crawl.py
   tests/test_config.py tests/test_cli.py tests/test_slice_boundaries.py
   tests/test_regressions.py`, then `just py-lint`, `just py-typecheck`,
   `just coverage` and `just wheel-smoke`, quoting its `api` line.

5. **End to end.** No new static fixture site: every site is generated into `tmp_path`
   by `tests/e2e/test_errors_report_sync.py`' helper, served first and written after, as
   `tests/e2e/test_lifecycle_sync.py` does; the helper is the module's own. Each page has
   a `<title>` and a `<main>` holding an `h1` and a paragraph of prose, two-space
   indentation and a final newline; `robots.txt` is `User-agent: *` with no Crawl-delay
   and no `Sitemap:` line; there is no `llms.txt`. The scenarios are the Acceptance
   criteria's; those that fetch run `rovo._commands.sync` in process over a real
   `HttpxFetcher` (or the raising wrapper around it) with a `SteppingTimer` or
   `FixedClock`, which never sleep, and read requests off the server's log; the refusal
   and `rovo report` scenarios run through `CliRunner`, which makes no request for
   them. `just py-test tests/e2e -ra`, its wall time quoted beside step 0's.

6. **Documents** (the `review-docs` skill). The pages of the Files touched table; find
   the sentences this slice makes false with
   `rg -n -i "refus|report|interrupt|crash|progress|json|non-HTML|ROVO_|environment|--yes|--url|--path|later slice" -g '*.md' -g '!tickets/**' -g '!allium-skill-reference/**' -g '!docs/specs/**' -g '!docs/decisions/**'`;
   `CHANGELOG.md` `Unreleased` gains one Added entry. Keep the required phrases of
   `AGENTS.md` in always-visible text. `just check-docs`, `just check-agents`, and
   `just lint`, whose hooks include markdownlint over this ticket.

7. **Witness** (the `weed` and `witness` skills). Run `weed` over `rovo` and `crawl`
   against the code, scoped to the owned and extended obligations, the Realised rules of
   the Context table and the guarantees; record its verdict under `last_results.weed`
   and fix any code divergence, each with a regression test in `tests/test_regressions.py`.
   A divergence weed attributes to the specification is not fixed: it joins the one
   batched needs-user question. Then run `witness` non-interactively: it writes
   `.allium-loop/T16-errors-report.witness.json` per `witness-result.schema.json`. The
   verdict must be `PASS`; a `FAIL` routes back per the skill, and the hand-back notes
   record each round. A batched question still OPEN does not block `PASS` unless it
   blocks an owned obligation; the witness escalates one that does.

8. Hand-back notes; `status: done`; `just check` ending with
   `All checks passed and the worktree is unchanged.`, `git status --short` empty after
   the commit. Commit on the branch.
   **Authorisation required**: pushing and opening the pull request.

## Acceptance criteria

The end-to-end scenarios live in `tests/e2e/test_errors_report_sync.py`; each starts with
`rovo init <base>guide/start.html <tmp>/out`, and every sync exits 0 unless stated.

- **End to end, refusals in order** (`test_a_sync_is_refused_once_for_its_first_problem_with_a_report`):
  a first sync writes the seed. `site.root_url` in `rovo.toml` becomes `<base>`
  (still a prefix of the seed, so the scope keeps it). Through `CliRunner`: `rovo sync <out>` with
  `ROVO_SCOPE__MAX_DEPTH=deep` in its environment exits 2 and its report has
  `report_status: refused`, `run_id: null`, `exit_code: "usage"`, `refusal_reason:
  "invalid configuration"`, `effective_policy: null` and `configuration.problems`
  naming `scope.max_depth` (the bad configuration wins over the changed root); without
  the variable it exits 2 with `refusal_reason: "changed root requires confirmation"`;
  with `--yes --url http://elsewhere.invalid/x.html` it exits 2 with
  `"invalid or off-host target"`; with `--yes --path pages/<host>/guide/missing.md` it
  exits 2 with `"unknown target path"`. The server's log gains no request across the
  four, and `.rovo/runs.json` is unchanged. `rovo sync --yes <out>` then exits 0 with
  `report_status: finished` and `run_id` 2.
- **End to end, a non-HTML answer and a failed URL**
  (`test_a_non_html_answer_is_skipped_and_a_failing_url_is_reported_every_sync`): the
  seed links `guide/data.txt` (served `text/plain`) and `guide/broken.html` (always
  500). The first sync, in process, exits 1: the `data.txt` row is `skipped_not_html`,
  no page, `failed_urls` or `changes` row names it; `failed_urls` holds one row for
  `broken.html` with `attempts` equal to `CONFIG.http_attempts` and `changes` one
  `failed` row for it. A second sync requests `/guide/broken.html` again and not
  `/guide/data.txt`, and exits 1 with the same `failed_urls` row.
- **End to end, the report command** (`test_rovo_report_prints_the_last_report`): after
  the scenario's sync, `rovo report <out>` through `CliRunner` exits 0 and its standard
  output parses as JSON equal to `crawl-report.json`; on a freshly initialised mirror it
  exits 2 with nothing on standard output.
- **End to end, an interrupt** (`test_an_interrupted_sync_publishes_what_it_stored_and_reports`):
  the seed links `guide/a.html` and `guide/b.html`; the fetcher wrapper raises
  `KeyboardInterrupt` on the request for `b.html`. The sync exits 1: the report has
  `report_status: interrupted` and `error: null`; `pages/<host>/guide/start.md` and
  `a.md` are published; `frontier.json` holds `b.html` `pending`. A second sync with the
  plain fetcher requests `/guide/b.html`, publishes it and exits 0 with
  `report_status: finished`.
- **End to end, a crash** (`test_a_crashed_sync_records_the_error_and_reports`): as the
  interrupt scenario, the wrapper raising `RuntimeError("boom")`: exit 1,
  `report_status: interrupted`, `error: "RuntimeError: boom"`, `a.md` published. Then,
  with `rovo._commands.finalise` monkeypatched to raise `RuntimeError("late")`, a sync
  exits 1 with `error: "RuntimeError: late"` and `report_status: interrupted`, no page
  file changes, and `runs.json` holds its run id, so the next sync's `run_id` is one
  higher.
- **End to end, progress** (`test_json_progress_ends_with_one_done_event`): the seed
  links `guide/flaky.html`, scripted as one 503 then served. A sync in process with a
  sink collecting events gives `start` first, a `host_backoff` naming the host, `page`
  events, and exactly one `done`, last; each event serialises to one JSON line with
  `event`, `host` and `until`. Without a sink nothing is printed on standard output.
- **End to end, the environment layer** (`test_rovo_mirror_prune_from_the_environment_deletes_removed_files`):
  `guide/start.html` links `guide/gone.html`; after the first sync `gone.html` is
  deleted; a second sync with `ROVO_MIRROR__PRUNE=true` in the environment passed to
  `resolve_config` removes it: its record is `removed`, `pages/<host>/guide/gone.md` is
  gone and `_removed/` does not exist.
- **End to end, earlier scenarios**: `tests/e2e/test_init_sync.py`,
  `tests/e2e/test_follow_links.py`, `tests/e2e/test_index_files.py`,
  `tests/e2e/test_polite_sync.py`, `tests/e2e/test_discovery_sync.py`,
  `tests/e2e/test_second_sync.py`, `tests/e2e/test_lifecycle_sync.py` and
  `tests/e2e/test_harness.py` pass unedited, unless the ledger names an edit and why.
- Every owned obligation in step 3 has a test named after it, red before the code and
  green after (`ai_tmp/T16/red.txt` and the final run); the reconciliation line shows
  zero uncovered; every extended test is re-hashed in the ledger with its note; every
  obligation dropped from the owned list is in the hand-back notes with its reason.
- No test this slice adds or edits sleeps for real; the suite's one real wait is T12's
  installed-script Crawl-delay scenario (`tests/e2e/test_polite_sync.py`), kept by
  design: `rg -n 'time\.sleep\(' tests; test $? -eq 1`,
  `test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py`, and
  `rg -n 'subprocess' tests/e2e/test_errors_report_sync.py; test $? -eq 1`.
- The `NotInThisSlice` raises in `src/` carry the same `rule=` names, as many of each, as
  `ai_tmp/T16/notinthisslice-cc46695.txt`
  (`ai_tmp/T16/rules-before.txt` and `ai_tmp/T16/rules-after.txt`, written by the
  Verification block, do not differ), and `dispose_fetch`'s raise no longer tests `is_html`.
- `rovo sync --help` lists `--yes`, `--json`, `--url`, `--path` and `--set`; `rovo report`
  runs through the installed script; `rovo report` and `rovo index` load neither httpx
  nor `rovo._crawl`.
- `.allium-loop/T16-errors-report.witness.json` exists with `"verdict": "PASS"`, and the
  ledger validates against `ledger.schema.json` with the T16 batched question's items
  and the carried items OPEN unless the maintainer answered them.
- `just check-specs` and `just analyse-specs` pass with `docs/specs/` unchanged since
  `bad753c` (`git diff --stat bad753c -- docs/specs` empty).
- `import rovo` loads no module outside the standard library and `rovo`; `__all__` is
  `["__version__"]`; `just wheel-smoke` passes with the package-file count unchanged.
- `just coverage` stays at or above the floor of 95.
- `just check-docs` and `just check-agents` pass; `docs/reference/cli.md` describes the
  options, the layers, the refusals, interrupts and crashes, `--json` events and
  `rovo report`.
- `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty after the commit.

## Verification

```sh
just plan-spec crawl > ai_tmp/T16/plan-spec-crawl.txt
just plan-spec rovo > ai_tmp/T16/plan-spec-rovo.txt
just plan-spec mirror > ai_tmp/T16/plan-spec-mirror.txt
just plan-spec convert > ai_tmp/T16/plan-spec-convert.txt
git diff --stat bad753c -- docs/specs
just py-test tests/test_commands.py tests/test_report.py tests/test_crawl.py tests/test_config.py tests/test_cli.py tests/test_slice_boundaries.py tests/test_regressions.py -ra
( set -o pipefail; { time just py-test tests/e2e -ra; } 2>&1 | tail -6 )
just py-lint
just py-typecheck
just coverage
just wheel-smoke
uv run --frozen python -I -c "import rovo, sys; print(sorted(m for m in sys.modules if not m.startswith(('rovo', '_')) and m not in sys.stdlib_module_names))"
rg -o 'rule="[^"]+"' -N --no-filename ai_tmp/T16/notinthisslice-cc46695.txt | sort > ai_tmp/T16/rules-before.txt
rg -o 'rule="[^"]+"' -N --no-filename src | sort > ai_tmp/T16/rules-after.txt
diff ai_tmp/T16/rules-before.txt ai_tmp/T16/rules-after.txt  # prints nothing
uv run --frozen rovo sync --help
rg -n 'time\.sleep\(' tests; test $? -eq 1  # only "no match" passes
test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py
rg -n 'subprocess' tests/e2e/test_errors_report_sync.py; test $? -eq 1  # only "no match" passes
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
after; the refusals, the layers, the progress sink and the interrupt and crash handling
as built, and any departure from Facts and steps 1 and 2; the red run and the
reconciliation line; every extended or re-propagated test, its origin slice and its new
hash; every obligation dropped from the owned list and why; the weed verdict and the
witness verdict, each round; the one batched needs-user question with every gap found
while planning, implementing or in weed, and the maintainer's answer if one arrived; the
verification output, each headed by its commit.

## Open points

- **The T16 batched needs-user question: OPEN.** One question to the maintainer, its
  items numbered so an answer can cite them. Item 1 is carried from T15; items 2 to 5
  were found while planning T16, item 6 by the weed pass. Each states the interim the slice builds, never
  presented as the answer; none blocks an owned obligation. Line numbers at `bad753c`.
  1. **Carried from the T15 follow-up batched question, item 1** (OPEN in
     `.allium-loop/T15-lifecycle.json` and `tickets/T15-lifecycle.md`). **Which path a
     removed record holds when its kept copy is at its old path.** `RetirePage`'s
     guidance (`mirror.allium` 1030 to 1047) keeps the existing `_removed/` copy of a
     page revived at a new path and retired again in the same run, but
     `ReviveRemovedPage` (748) set the record's `path` to the new path and `RetirePage`
     leaves it there. `RemovedAreaKeepsPath` (1546) says a removed page's copy is at
     `_removed/<host>/<its path>` and that the page keeps its path, so the record names a
     path its copy is not at; a later revival raises `ArchivedCopyDeleted` for the
     record's (new) path and the copy at the old path stays in `_removed/` for ever.
     Should the record return to its old path, should the copy move to the new one, or
     is the stale copy accepted? Interim: as the rules are written (the record keeps the
     new path, the copy stays at the old one); T15's test asserts the files only.
  2. **The `start` and `page` progress events.** `ProgressOnRequest` (`rovo.allium` 942)
     lists `start` and `page` among the `--json` events, but no rule raises
     `ProgressReported` with either, and the trigger carries only `event`, `host` and
     `until`, so a `page` event can name no URL. When is each raised, and what does it
     carry? Interim: `start` once, when the run is created (`host` and `until` null);
     `page` once per frontier row a fetch settles, with the row's host name and `until`
     null.
  3. **A non-HTML URL is never rechecked.** `DisposeFetch` (1963) settles a non-HTML
     answer `skipped_not_html`, a status in neither `retry_entries` (`crawl.allium`
     `Frontier`) nor `Enqueue`'s `rediscovered` set (1302 to 1306), so a URL with no page
     that once answered non-HTML is never fetched again by a full sync, even when
     discovery names it again and it now serves HTML; the T15 answer "recheck when
     rediscovered" (absent, duplicate and done rows) did not cover it. Likewise a written
     page whose URL now answers non-HTML stays written, its last HTML published, on every
     sync. Should `skipped_not_html` rows join the recheckable rows, and should a written
     page that answers non-HTML be removed? Interim: as written (`skipped_not_html ->
     pending` only through a written page's recheck).
  4. **An operator interrupt after the run has ended.** `InterruptSync` (709) needs a
     running run, and `RecordCrashAfterRun` (736) speaks of a crash, so a Ctrl-C during
     finalisation or while the report is assembled meets no rule, while
     `ReportOnEveryExit` (936) still wants a report. Interim: it is taken as
     `RuntimeFails` with the error `"KeyboardInterrupt: "` and `RecordCrashAfterRun`
     writes the report (exit 1).
  5. **What a crash after the run saves.** `RecordCrashAfterRun` writes the open report
     "as it stands" but says nothing of the manifest, the frontier or the run's record,
     while `RunIdentityIsUnique` (crawl invariants) needs the run's id never reused and
     `SettleStoredEntry` relies on a done row's page being saved. Interim: the manifest
     and the frontier are not saved (the disk keeps the last finalisation's state, as
     T15's file-effect note describes), and the run's record is appended to `runs.json`
     with its status, so the next sync takes the next id.
  6. **An off-host `--url` when `allowed_hosts` is empty.** `RefuseOffHostTarget`
     (`rovo.allium` 343 to 352) tests the target's host against the configuration's own
     `allowed_hosts`, which may be empty (`scope_of` derives the first seed's host only
     then, 521 to 527), so a `rovo.toml` that leaves `allowed_hosts` out refuses every
     `--url` as off-host. Interim: the specification's literal text; the starter
     `rovo.toml` always writes `allowed_hosts`.
- **Carried, OPEN** (from `tickets/T15-lifecycle.md` and
  `.allium-loop/T15-lifecycle.json`): to T17, `mslearn`'s `sitemap_include`
  placeholders, and a non-heading id anchor stopping the sync
  (`UncarryableBecomesIsland`); to T18, a retired host's remaining discovery is still
  requested, and whether a host retirement ranks exit 3 or 1.
- **Scope note, not a specification gap.** T14 and T15 assigned the targeted branches of
  `PrepareRun`, `Discover` and `SelectBatch` (a sync with `--url` or `--path`) and the
  edge `duplicate -> pending` to T16, but T16's capability names the targeted refusals
  and not the targeted run. This slice takes the refusals and the options and keeps the
  run's two raises, so a named target that passes the refusals stops the sync. The
  orchestrator assigns the targeted run (T16's follow-up or a later slice).
- **The specification's open questions.** The three `crawl.allium` ones (2410 to 2412)
  and the three `convert.allium` ones (473 to 475) stay open; the second (a URL that
  fails on every sync is retried for ever) is on this slice's path: its interim holds,
  every failed row is re-pended on every sync, and the e2e failed-URL scenario asserts
  it.
- **`NotInThisSlice`.** A development guard, not product behaviour: each later slice
  removes the raises it implements, and the last slice's review confirms none is left.
  This slice removes none and narrows `DisposeFetch`'s (Acceptance criteria).
