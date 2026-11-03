---
id: T09
title: "Tracer bullet: rovo init creates a mirror, rovo sync mirrors its seed page"
status: open
depends_on: [T08]
parallel_with: []
branch: full-final-prototype
estimated_size: L
---

# T09: Tracer bullet: rovo init creates a mirror, rovo sync mirrors its seed page

## Context

Decision 0012 (`docs/decisions/0012-rovo-is-a-documentation-mirror.md`) defines rovo as
a documentation mirror. Four modules under `docs/specs/` specify it, importing downward:
`rovo.allium` (the command) uses `crawl.allium` (one sync run), which uses
`mirror.allium` (the mirror on disk), which uses `convert.allium` (pure conversion).
T08 laid down decision 0013 (`docs/decisions/0013-mirror-state-on-disk.md`: state is
JSON under `<out>/.rovo/`, written atomically, keys sorted, no wall-clock time in a page
file), the runtime dependencies, the docstring-only private modules `rovo._convert`,
`rovo._mirror`, `rovo._crawl`, `rovo._config` and `rovo._report`, the import-direction
test `tests/test_import_direction.py`, and the end-to-end harness `serve_site` in
`tests/e2e/conftest.py`. Nothing of the specification is implemented yet: `rovo` answers
only `--version` and `version`.

This is slice 1 of T08 to T20, run in this worktree on `full-final-prototype`. It is
the thinnest real path through all four modules: `rovo init` creates a mirror, then
`rovo sync` fetches the configured seed page over HTTP, converts it to Markdown with the
generic profile, publishes it as a page file with frontmatter at its assigned path, ends
the run, writes `crawl-report.json` and exits 0. Links, scope beyond the seeds,
indexes, politeness, discovery beyond the seeds, incremental fetch, the page lifecycle,
errors and refusals, the quality gates' depth, blocks and the browser tier are later
slices. **This slice sets the patterns every later slice follows**: module layout, the
seams, configuration resolution, the state files, test style and end-to-end style.
Choose the smallest coherent design and write it down where later slices will read it.

### The specified path, and what this slice does with each rule on it

The task named the rules to realise; the specification's trigger chain crosses more.
Each rule the chain crosses is classified here, so that no rule is skipped silently.
Line numbers are at `f4bcc7c`, except `rovo.allium`'s, which are at the specification
base, `4ea7bb0`: `f4bcc7c` plus the built-in defaults the maintainer decided (C2), stated in
`rovo.allium`'s `config` block (247 to 249).

| Class | Rules |
| --- | --- |
| **Realised** (fully, every branch reachable in this slice) | `rovo.allium`: `InitialiseMirror` (264), `RefuseInit` (289), `RefuseSyncWithoutDirectory` (302), `StartSync` (450), `TallyFinalisedPage` (594), `CloseRun` (617), `FinaliseRunReport` (651), `RankAndWriteReport` (659). `crawl.allium`: `StartRun` (596), `CreateFrontier` (611), `AttachFrontier` (619), `PrepareRun` (631, standard full-run branches), `Discover` (706, the seeds and host opening), `OpenHost` (737), `FetchRobots` (762), `AdoptRobotsRules` (785; the host-rate effect deferred), `AllowAllWhenRobotsAbsent` (824), `Enqueue` (986), `DropStaleObservations` (1010), `BeginCrawl` (1034), `SelectBatch` (1053), `NextBatch` (1109), `SkipRobotsDisallowed` (1130), `OpenHostForEntry` (1140), `ProceedWithKnownHost` (1154), `SkipRobotsDisallowedOnNewHost` (1167), `FetchEntry` (1174), `AttemptTier` (1208, http tier, one try), `PrepareAttempt` (1253, no challenge is ever offered), `SettleWalk` (1384, the no-escalation case), `DisposeFetch` (1509, the ok-HTML branch), `ConvertFetched` (1605), `SettleStoredEntry` (1635), `FinishRun` (1699), `EndRun` (1736). `mirror.allium`: `AdmitCandidate` (484), `RequestPass` (495), `StoreNewPage` (651), `RefreshPage` (698), `RecordAlias` (757), `DropAliasOfOwnIdentity` (769), `FinalisePageBody` (987, over a body with no links), `PublishPage` (1013, with `frontmatter_of`, `assign_path`, `keywords_of`), and, from `e818eb0`, `RefuseUnplaceableCandidate` with `assign_path`'s full-digest fallback and null outcome. The refused candidate's path crosses `crawl.allium` `FailDiscardedEntry` and `EntryFails` and `rovo.allium` `TallyFailedUrl`, one branch each (the row fails with the discard's reason, the report lists a failed URL and a failed change, exit `partial`); their obligations stay outside the owned set and the scenarios in `tests/test_unplaceable_candidate.py` cover them. `convert.allium`: the `Fidelity` contract's (178) five signatures, `ExpectedAgainstSurvived` (203) and `BodyShape` (236), for the generic profile; its other invariants are in the Deviation row. |
| **Traversed, nothing to do in this slice** | `ResolveMirrorLinks` (909) and `FinishLinkPass` (1046): the slice's pages carry no links (Non-goals), so no `DestinationFound` is raised and `find_broken_links` is empty. `FeedBreaker` (1417): the breaker's window lasts one run and nothing in this slice reads it; the blocks slice owns it. |
| **Deviation, named and closed by a later slice** | `BuildIndexes` (1072): the finalise pass completes and raises `IndexesWritten` without writing `index.md`, `index.jsonl`, `links.jsonl`, `llms.txt` or `_index.md`; the indexes slice writes them. `Discover` raises no `SitemapsRequested` or `LlmsTxtRequested`; the discovery slice does. A failed `StartSync` guard other than the missing mirror exits `usage` (2) with the problem on standard error and writes no report, where the specification's `RefuseSyncOnBadConfig` and its siblings write a refused report through `ReportRefusal` (417); the refusals slice closes it. `convert.allium`'s `Fidelity` contract (178) is realised only in part: `ExtractNeverEmptyHanded` (185) runs profile selection then the whole body, skipping the fallback extractor (`extractor_fallback` is never raised), closed by the slice that picks the extractor under decision 0005 (Open points); `UncarryableBecomesIsland` (196), `DeclaredReductions` (209), `SanitizedMeansInert` (219) and `EveryTabPanelEmitted` (229) create no island and declare no reduction here, since the fixtures hold no such construct, and are closed by the fidelity slice. |
| **Outside this slice; reaching one stops the run** | The guard points actually written, and no others: (1) `DisposeFetch` (1509): any settled walk that is not (ok, verdict `none`, HTML, no redirect, no known page) raises `NotInThisSlice("DisposeFetch")`; since this slice makes one try, a retryable answer (`HttpRetry`, `RetireHostOnLongRetryAfter`) settles and reaches this fallthrough too, and `Escalate` is unreachable under `render_mode = never` (`usable_tiers` is `[http]`); (2) `classify_block`: an answer that would need a verdict other than `none` (a 401 or 403, or an HTML page with an `input` whose type is `password`, read with bs4 however the attribute is quoted or cased; a challenge header or page, an access-denied reference or a bot cookie on a tiny body is not recognised here and gets `none`, a gap the blocks slice closes); (3) a robots answer other than ok or absent (`DenyAllWhenRobotsRefused`, `DenyAllWhenRobotsUnreachable`, a 3xx answer to `/robots.txt`); (4) extraction with a profile other than `generic`; (5) `RetireOutOfScopePages` (894): a page it would retire (reachable when `rovo.toml`'s scope is edited between syncs); (6) `normalize`: an element other than a heading that carries a source id raises `NotInThisSlice("UncarryableBecomesIsland")`, since its anchor needs an island (the extracted root's own id, such as `<main id>`, is not part of the content and does not stop it). Each raises one private exception, `rovo._unfinished.NotInThisSlice` (a leaf module every layer may import), naming the rule; the command reports it on standard error and exits 1 (`partial`), with no page written and the report not claimed. No test asserts the message; the slice that implements each branch deletes its raise. |

Robots is on the path, not a later slice: `Discover` opens every allowed host
(`HostOpened`), `OpenHost` always raises `RobotsRequested`, and `FetchEntry` requires
`robots_allows(run, entry.identity)`. The minimum is therefore one http GET of
`<origin>/robots.txt` per host, an absent answer (`AllowAllWhenRobotsAbsent`: no error,
not refused, not a server error) giving `allow_all`, and an ok answer
(`AdoptRobotsRules`) giving `rules` evaluated with the standard library's
`urllib.robotparser` for the user agent `rovo`. The `RobotsPolicy` is created in full,
`crawl_delay` and `declared_sitemaps` included (`crawl_delay()` and `site_maps()`);
only `AdoptRobotsRules`' effect on the host's rate is deferred, since pacing is the
politeness slice's. The fetcher follows no redirect in this slice, so a 3xx robots
answer would meet `AllowAllWhenRobotsAbsent`'s guard literally where the specification's
`fetch_resource` would have followed it: a 3xx robots answer raises `NotInThisSlice`.

### Facts a later reader would otherwise rediscover

- **The seed's path.** `assign_path` (guidance at `mirror.allium` 646 to 712, at
  `fed9ed8`) gives `pages/`, the host segment, `/` and the relative path; it strips the
  scope prefix and names a directory URL `index`, so a seed at the prefix directory maps
  to `pages/<host>/index.md`, an ordinary name there; a last segment the dropped
  `.html`, `.htm` or `.aspx` leaves empty is named `index` too (`1be7354`). The fixture seed is
  `/guide/start.html`: `initial_scope` gives `path_prefixes = ["/guide/"]`, so the page
  path is `pages/127.0.0.1_<port>/start.md`. The collision rule is implemented in full
  here, since `assign_path` is pure and the rule is a few lines; it is tested on unit
  inputs.
- **Extraction without a fallback extractor.** `ExtractNeverEmptyHanded`
  (`convert.allium` 185) tries the profile's selection, then a fallback extractor, then
  the whole body. No fallback extractor library was chosen in T08. This slice goes from
  the generic selection (`main`, else `article`) straight to the whole body, raising
  `whole_body_extracted`; choosing the fallback extractor is an open point. The fixture
  page has a `<main>`, so its method is `profile`.
- **Second syncs are not in this slice.** A second `rovo sync` of the same mirror finds
  a known page: `FetchEntry` sends validators and `http.server` answers 304, or the raw
  digest is unchanged; both are `DisposeFetch` branches this slice stops on. The
  incremental slice owns them.
- **`markdownify`, `bs4` and `httpx` ship `py.typed`** (read under `.venv` at
  `f4bcc7c`); `lxml` does not, and is reached only through `bs4`'s parser name, never
  imported, so `mypy.ini` does not move.
- **The obligation source.** The obligations are what `just --quiet plan-spec
  <module>` emits as bare JSON over the committed `docs/specs/<module>.allium` at the
  specification base, `4ea7bb0` (`f4bcc7c` plus C2's built-in defaults in
  `rovo.allium`); the copies under `ai_tmp/T09/` are
  scratch, regenerated by step 0.

## Goal

From a clean checkout, `rovo init http://127.0.0.1:<port>/guide/start.html <out>` writes
`<out>/rovo.toml` and an empty manifest under `<out>/.rovo/` and exits 0; `rovo sync
<out>` reads `/robots.txt`, fetches the seed over HTTP once, converts it with the generic
profile, writes `<out>/pages/127.0.0.1_<port>/start.md` (sorted-key YAML frontmatter,
no wall-clock time, then the Markdown body), saves the manifest, the frontier and the run history under
`<out>/.rovo/`, writes `<out>/crawl-report.json` (`report_status: finished`,
`exit_code: ok`, `converted: 1`, one `added` change) and exits 0. Every owned obligation
listed under Steps has a test named after its id; an end-to-end test proves the path
against a served fixture site through the installed `rovo` script; `just check` is
green; the Allium loop's witness record says `PASS`.

## Non-goals

- No link handling: no `DestinationFound`, no rewriting, no link flags, no `LinksFound`
  enqueueing (`EnqueuePageLinks`), no `links.jsonl`. The fixture pages hold no link.
- No index files (`BuildIndexes` deviation above).
- No sitemaps, no `llms.txt`, no discovery beyond the configured seeds.
- No politeness: no rate limiting, concurrency control, Crawl-delay pacing, pauses,
  retries, Retry-After, backoff or `Sleeper` seam. A batch's rows run one after another.
- No incremental fetch: no validators sent (no page is known on a first run), no 304,
  no unchanged outcome, no `max_age`.
- No page lifecycle: no removal, move, revival or `_removed/`. Redirect-hop aliases
  cannot arise (no redirect is followed in this slice); the aliases `RefreshPage`
  records from the source and requested identities when a same-host canonical moves
  the page identity (`page_identity`, `mirror.allium` 134 to 135) are realised, through
  `RecordAlias` and `DropAliasOfOwnIdentity`.
- No refusal reports, no `ReportRefusal`, no `verify`, `index`, `report` or `fetch`
  command, no `--dry-run`, `--yes`, named URLs or paths, owner testing or JSON progress.
- No breaker, no block classification beyond `kind = none` (`classify_block` returns
  none for an ok answer; any other answer is outside this slice), no browser or stealth
  tier, no `BrowserEngine` seam.
- No environment-variable or flag layer in `resolve_config`: built-in defaults then
  `rovo.toml`. The configuration slice adds `ROVO_<SECTION>__<FIELD>` and flags.
- No specification change: `docs/specs/` is read, not edited. The five `open question`
  blocks stay open (`crawl.allium` 1974 and 1975, `convert.allium` 473 to 475); this
  slice touches only the tab-expansion one, and takes its interim behaviour: panels
  emitted are compared with panels found, both zero under the generic profile.
- No change to the public API: `__all__` stays `["__version__"]`, so
  `docs/reference/api.md` does not move.
- No change to a decision record. Where a record's "today" sentence goes stale, it is an
  open point.
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `src/rovo/_convert/__init__.py` | shared, own lines | docstring names the modules below |
| `src/rovo/_convert/model.py` | new | the convert value types and enums, as frozen dataclasses and `enum.Enum` |
| `src/rovo/_convert/profiles.py` | new | `Profile` and the three catalogue defaults as data; `config` gate values and weights |
| `src/rovo/_convert/fidelity.py` | new | `extract`, `normalize`, `convert`, `restore`, `measure`, `converted_content`, `with_fetch_flags` |
| `src/rovo/_mirror/__init__.py` | shared, own lines | docstring names the modules below |
| `src/rovo/_mirror/model.py` | new | `CrawlScope`, `Frontmatter`, `Mirror`, `Page`, `Alias`, `PageCandidate`, `MirrorPass`, enums, `config` |
| `src/rovo/_mirror/urls.py` | new | `normalise_url`, `hostname_of`, `path_of`, `assign_path` |
| `src/rovo/_mirror/state.py` | new | the atomic JSON writer, the `Clock` protocol and `SystemClock`, the manifest's load and save |
| `src/rovo/_mirror/intake.py` | new | `AdmitCandidate`, `StoreNewPage`, `RefreshPage`, `RecordAlias`, `DropAliasOfOwnIdentity` |
| `src/rovo/_mirror/finalise.py` | new | the finalise pass: `RequestPass` to `IndexesWritten`, `frontmatter_of`, `keywords_of`, page-file text |
| `src/rovo/_unfinished.py` | new | `NotInThisSlice` alone; a leaf that imports no `rovo` module, so `_convert`, `_mirror`, `_crawl` and `_commands` may each raise it without breaking the import direction |
| `src/rovo/_crawl/__init__.py` | shared, own lines | docstring names the modules below |
| `src/rovo/_crawl/model.py` | new | `CrawlPolicy`, `SiteResponse`, `Run`, `Frontier`, `FrontierEntry`, `Host`, `RobotsPolicy`, `LadderWalk`, `FetchAttempt`, `config` |
| `src/rovo/_crawl/fetch.py` | new | the `Fetcher` protocol and `HttpxFetcher` |
| `src/rovo/_crawl/run.py` | new | `StartRun` to `EndRun`, the frontier's load and save, the run history |
| `src/rovo/_config.py` | shared, own lines | `Configuration`, `resolve_config`, `initial_scope`, the `rovo.toml` template |
| `src/rovo/_report.py` | shared, own lines | `CrawlReport`, `ExitCode`, `summarise`, `host_reports`, `most_severe`, the report writer |
| `src/rovo/_commands.py` | new | the root's rules: `init` and `sync`, taking a `Fetcher` and a `Clock`; neither `_report.py` (the report's shape and writing) nor `cli.py` (argument parsing, kept thin and free of runtime imports at module level) is the place for `StartSync` and `CloseRun`, which compose config, crawl, mirror and report |
| `src/rovo/cli.py` | shared, own lines | `rovo init` and `rovo sync`, importing `rovo._commands` inside each command |
| `scripts/wheel_smoke.py` | shared, own lines | `PACKAGE_FILES` gains every new module; the verdict line's count follows |
| `tests/test_import_direction.py` | shared, own lines | `rovo._commands` and `rovo._unfinished` join the scan; the widened direction and relative-import resolution (step 2) |
| `tests/fakes.py` | new | `FakeFetcher` (a URL to `SiteResponse` map that records requests) and `FixedClock` |
| `tests/test_convert.py`, `tests/test_mirror.py`, `tests/test_crawl.py`, `tests/test_config.py`, `tests/test_report.py`, `tests/test_commands.py` | new | the owned obligations, one test or one parametrised case each |
| `tests/spec_values.py` | new | reads a module's `config` defaults from the committed `.allium` file, so a `config-default` test never restates a value |
| `tests/test_slice_boundaries.py` | new | the `NotInThisSlice` guard points and the black boxes' corners (implement tick 1) |
| `tests/test_regressions.py` | new | one test per divergence a weed or review found, each naming the statement it broke |
| `tests/test_assign_path_reserved_segments.py` | new | the propagated tests for `assign_path`'s segment rewrites inside `pages/<host>/` (`22c0261`, regenerated at `fed9ed8`: leading and trailing dots, directories named like managed root files or ending in `.md`, device names, the `.md` suffix; `_removed` no longer rewritten) |
| `tests/test_page_namespace.py` | new | the propagated tests for `fed9ed8`'s layout: the host segment (lower case, trailing dot, `[a-z0-9.-]`, device rule, `_<port>`), `pages/<host>/index.md` for the scope root, a trailing-dot host as one identity, `path_template` and `max_path_chars` not `rovo.toml` keys; and `1be7354`'s decisions: the IPv6 host segment `---1-_8080` and a bare-suffix last segment named `index` |
| `tests/test_assign_path_fallback.py`, `tests/test_unplaceable_candidate.py` | new | the propagated tests for `e818eb0`: the full-digest fallback, the null outcome, `RefuseUnplaceableCandidate`, the `FailDiscardedEntry` reason and the three- and four-seed scenarios; re-propagated at `fed9ed8` (paths under `pages/<host>/`, `max_path_chars` over the whole path, a host with no room refused) |
| `ruff.toml` | shared, own lines | `tests/**` ignores N802 with its reason: an obligation test's name carries the CamelCase rule name |
| `mypy.ini` | shared, own lines | `[mypy-test_mirror]` (added in implement tick 5 for the then hash-pinned `test_invariant_PagePathsAvoidManagedNames`) is removed by implement at `fed9ed8`: propagate regenerated that test with narrowing asserts, and `just py-typecheck` passes without the section |
| `tests/test_cli.py` | shared, own lines | `init` and `sync` through `CliRunner`: help, usage exits |
| `tests/e2e/test_init_sync.py` | new | the end-to-end scenarios (Acceptance criteria); at `fed9ed8` the page is `pages/127.0.0.1_<port>/start.md`, the port read from the served base URL |
| `tests/fixtures/sites/one-page/guide/start.html` | new | one page with a `<main>`, a title, a meta description, an `h1`, an `h2` and two paragraphs; no link, image, list, table or code |
| `tests/fixtures/sites/robots-disallow/robots.txt`, `tests/fixtures/sites/robots-disallow/guide/start.html` | new | `User-agent: *` / `Disallow: /guide/`, and a copy of the page |
| `docs/reference/mirror.md` | new | the mirror on disk: `rovo.toml`, the `.rovo/` files, a page file, `crawl-report.json` |
| `docs/manifest.yml` | shared, own lines | the `reference/mirror.md` entry, `canonical_for: ["mirror_files_reference"]` |
| `docs/README.md` | shared, own lines | the map's reference list gains the page |
| `docs/reference/cli.md` | shared, own lines | `rovo init`, `rovo sync`, the exit codes |
| `docs/reference/testing.md` | shared, own lines | `tests/fakes.py`, the obligation-named tests, the new fixture sites, the package-file count |
| `docs/how-to/test-and-debug.md` | shared, own lines | the package-file count |
| `docs/explanation/architecture.md` | shared, own lines | the private modules' rows, `rovo._commands`, the seams |
| `docs/project/repository-map.md` | shared, own lines | the tree |
| `docs/project/purpose-and-scope.md`, `docs/how-to/install-and-run.md`, `docs/project/terminology.md`, `docs/explanation/specifications.md`, `docs/how-to/work-with-the-specs.md`, `docs/explanation/security-model.md`, `README.md` | shared, own lines | "not yet implemented" and "placeholder" sentences that this slice makes false, and only those |
| `AGENTS.md` | shared, own lines | the opening paragraph's "not yet implemented" and the project map's `src/rovo/` line |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` entry |
| `tickets/README.md`, `tickets/T09-tracer-init-sync-one-page.md` | ticket | index row, graph, this ticket |
| `.allium-loop/T09-tracer-init-sync-one-page.json`, `.allium-loop/T09-tracer-init-sync-one-page.witness.json` | gitignored | the loop ledger and the witness record; never committed |

`pyproject.toml`, `uv.lock`, `pytest.ini`, `.coveragerc`, `Justfile` and `docs/specs/`
are read, not changed; `ruff.toml` and `mypy.ini` change only by the rows above. A file not in this table that turns
out to need a change (a tool setting, a further page made false) is added to the table
in the same change with its reason, or handed back if it is a decision record or a
specification.

## Steps

0. `just check` baseline on the untouched worktree at the specification base, last
   line quoted.
   Scratch output goes in `ai_tmp/T09/`. The obligation source is
   `just --quiet plan-spec <module>` over the committed `docs/specs/<module>.allium` at
   the specification base; write its output to `ai_tmp/T09/plan-spec-<module>.json` for each of
   `rovo`, `crawl`, `mirror` and `convert`. Create the ledger
   `.allium-loop/T09-tracer-init-sync-one-page.json` against
   `allium-skill-reference/allium/schemas/ledger.schema.json`: `goal`
   `"T09-tracer-init-sync-one-page"`, `mode` `"spec-first"`, `tick` 0, and
   `open_questions` holding the five specification open questions verbatim and the
   Open points below. Read `.agents/skills/propagate/SKILL.md`,
   `.agents/skills/weed/SKILL.md`, `.agents/skills/witness/SKILL.md` and
   `.agents/skills/python-change/SKILL.md` before step 3.

1. **The state and configuration design** (what later slices build on). Write it into
   `docs/reference/mirror.md` first, then code to it.
   - **Mirror layout.** `<out>/rovo.toml`; `<out>/.rovo/manifest.json` (the `Mirror`
     fields, the pages with every `Page` field including the fetch timestamps, the
     aliases, the links), `<out>/.rovo/frontier.json` (entries, observed URLs and learned
     tiers, the last two empty here; decision 0013 gives sitemap snapshots their own
     file, which the discovery slice names and first writes), `<out>/.rovo/runs.json` (one
     row per run: id, kind, mode, status, `scope_hash`, `dry_run`, `started_at`,
     `finished_at`, `unresolved_urls`); page files at their assigned paths;
     `<out>/crawl-report.json`. `exists mirror/Mirror{out_dir}` is mapped per guard,
     so that a damaged mirror is never overwritten: for `rovo init` (`RefuseInit`) the
     mirror exists when `<out>/.rovo/manifest.json` exists, whether or not it parses,
     and init also refuses when `<out>/rovo.toml` exists, so it never overwrites a file
     it would write; for `rovo sync` (`RefuseSyncWithoutDirectory`) it is "exists and
     parses", and an unparsable manifest exits 2 with the problem on standard error and
     writes no report, as a missing one does. `directory_exists` is `Path.is_dir()`. Every JSON file is
     written by one function in `rovo._mirror.state` with decision 0013's encoding
     (UTF-8, `sort_keys`, indent 2, trailing LF; temporary file in the same directory,
     flush, `os.fsync`, `os.replace`). Timestamps are ISO 8601 UTC strings from the
     `Clock`, and appear only in `.rovo/` and the report, never in a page file.
     `next_run_id` is one more than the highest id in `runs.json`, starting at 1.
   - **`rovo.toml`.** `rovo init` writes it from a template string (the standard library
     reads TOML through `tomllib` and writes none), every key present with its value,
     and a test round-trips it through `tomllib`. Sections and keys, with the source of
     each default:

     | Key | `Configuration` field | Default and its source |
     | --- | --- | --- |
     | `site.root_url` | `root_url` | `initial_scope`: the URL keeping the locale and first product segment (`rovo.allium` 283 to 286) |
     | `site.start_urls` | `start_urls` | `[site_url]` (same guidance) |
     | `scope.allowed_hosts` | `allowed_hosts` | `[host of site_url]` (same) |
     | `scope.path_prefixes` | `path_prefixes` | `[directory of site_url]` (same) |
     | `scope.include`, `scope.exclude` | `include`, `exclude` | `[]`: empty means no filter (`mirror.allium` 126) |
     | `scope.max_depth` | `max_depth` | `10` (`config.max_depth`, `rovo.allium` 248); no link is enqueued in this slice |
     | `scope.locale` | `locale` | absent: no pinning (`mirror.allium` 93) |
     | `scope.meaningful_query_params` | `meaningful_query_params` | `[]`: the profile's apply when none is named (`rovo.allium` 513 to 515) |
     | `conversion.profile` | `profile_name` | `profile_for(site_url, --profile)` (`rovo.allium` 282 to 284) |
     | `crawl.robots` | `robots` | `"respect"` (`StandardRunsStayPolite`, `crawl.allium` 271) |
     | `crawl.render_mode` | `render_mode` | `"never"` (`config.render_mode`, `rovo.allium` 247); `auto` or `always` makes `StartSync` require an installed browser (`rovo.allium` 460), which this slice has not |
     | `crawl.stealth_mode` | `stealth_mode` | `"off"` (`StealthIsOwnerOnly`, `crawl.allium` 275) |
     | `crawl.max_age` | `max_age` | absent: never stale (`crawl.allium` 690 to 692) |
     | `quality.fail_on_low_quality` | `fail_on_low_quality` | `false` (`config.fail_on_low_quality`, `rovo.allium` 249) |
     | `unblocking.provider` | `unblocking_provider` | absent; any value is a configuration problem (`rovo.allium` 85) |

     A key absent from the file takes the built-in default; an absent `site.root_url`
     is `null`. `resolve_config` returns `valid = false` with every bad key path in
     `problems` for an unreadable or unparsable file, an unknown section or key, a value
     of the wrong type or outside its enum, or a profile the catalogue lacks. `hash` is
     the first 16 hex digits of the SHA-256 of the resolved configuration as canonical
     JSON (sorted keys, no whitespace). Hosts are lower-cased, port dropped.
   - **Page file.** `---\n`, the frontmatter as YAML with keys sorted and absent values
     omitted (strings as JSON-quoted scalars, lists as flow sequences of JSON-quoted
     strings, booleans `true`/`false`, `quality_score` as a decimal with at most four
     places), `---\n`, then the body. `content_digest` and `raw_digest` are lowercase
     SHA-256 hex. Only `PublishPage` writes a page file, and only when the text on disk
     differs (`page_file_current`).
   - **Exit statuses.** `ExitCode`'s declaration order is its severity
     (`rovo.allium` 171 to 173: ok 0, partial 1, usage 2, blocked 3, quality 4); the
     process exits with that number. Usage agrees with Typer's own 2.
   - **Seams.** `Fetcher` (one method, `fetch(url, *, validators) -> SiteResponse`;
     `HttpxFetcher` holds one `httpx.Client` per run, closed in a `finally`, sends
     `User-Agent: rovo/<version>` (`crawl.allium` 1248), uses `config.fetch_timeout`,
     follows no redirect, and turns a transport error into `status = 0` with `error`
     set; it takes an optional `transport: httpx.BaseTransport | None` constructor
     argument so its own behaviour is unit-tested without a network); `Clock` (`now() -> datetime`, UTC). `rovo._commands.init` and
     `rovo._commands.sync` take both as arguments; `rovo.cli` builds the real ones.
     `Sleeper` and `BrowserEngine` arrive with the slices that need them.
   - **Rules as functions.** The specification is event-driven; the code is a plain
     procedure. Each function that realises a rule names it in its docstring
     (`Realises crawl.allium FetchEntry.`), and each test names its obligation id in its
     name and docstring, so `weed` and a reader can trace both ways.

   **Adversarial review** (`CONVENTIONS.md` §14) over `docs/reference/mirror.md` and the
   module skeleton (names and signatures, before bodies): a default presented as
   specified that the specification does not state; a state file whose content
   contradicts decision 0013 or the three facts its Context names; a seam that a later
   slice (politeness, browser, incremental, lifecycle, indexes) cannot extend without
   changing a signature this slice fixes; a key name that collides with a specified
   name; an exit status mapping that disagrees with Typer's usage exit.

2. **The import direction.** The direction becomes `_convert` ← `_mirror` ← `_crawl` ←
   (`_config`, `_report`) ← `_commands` ← `cli`, with the leaf `_unfinished` below
   `_convert`, importable by every layer. Extend
   `tests/test_import_direction.py`: `rovo._commands` and `rovo._unfinished` join
   `PRIVATE_MODULES` and `ROOT_FORBIDDEN_MODULES`; `rovo._unfinished` imports no other
   `rovo` module; nothing under `_convert`, `_mirror` or `_crawl` imports
   `rovo._config`, `rovo._report` or `rovo._commands`; `_config` and `_report` import
   neither `rovo._commands` nor `rovo.cli`; `_convert` imports no `httpx`; and
   `rovo.cli` imports `rovo._commands` only inside a function body (an `ast` check that
   no module-level statement of `cli.py` imports a private module), so `rovo --version`
   loads no runtime dependency. The gate today ignores relative imports: `_imported`
   reads `ImportFrom.module` without `level`, and skips `from . import x` (module
   `None`), so `from .._crawl import X` inside `rovo._mirror` passes every direction
   test. Pass the importing module's dotted name (and whether it is a package
   `__init__`) into `_imported`, resolve an `ImportFrom` with `level > 0` to its absolute
   name (`importlib.util.resolve_name` with the right package), and for `module is None`
   record `<package>.<alias>` for each name; a unit test on the helper shows
   `from .._crawl import X` inside `rovo._mirror.finalise` resolving to `rovo._crawl`.
   Positive control on a scratch copy (`CONVENTIONS.md` §11): a module-level
   `import rovo._commands` in `cli.py` fails the new test, and an upward relative import
   (`from .._crawl import X` in a `rovo._mirror` module) fails the mirror's direction
   test; restore and show `cmp` print nothing.

3. **Tests first, from the obligations** (the `propagate` skill, spec-first). Write a
   failing test for each owned obligation below into the test file of its module, named
   `test_<obligation id with dots and hyphens as underscores>`, its docstring quoting
   the obligation's description from the plan-spec file. Run `just py-test` and record
   the red run in `ai_tmp/T09/red.txt` (the witness's red-before-green evidence). Record
   each generated test file's SHA-256 under `generated_test_hashes` in the ledger, and
   the reconciliation line (`N obligations, M covered, K uncovered`) over the owned set.
   Put the red run's summary line under `last_results.propagate` in the ledger too, since
   the witness reads red-before-green from the ledger. A test changed after the red run
   (steps 4 to 8) is re-recorded by repeating this step for that file: a new hash, `tick`
   incremented, and a ledger note naming the test and why it changed; never silently,
   or the witness's no-test-weakened check fails, as it should.
   An obligation a test cannot reach without a later slice's behaviour is not owned:
   move it to the hand-back notes with its reason rather than writing a vacuous test.

   Owned obligations (ids as `just --quiet plan-spec <module>` emits them at the
   specification base):

   - **`rovo`**: `rule-success.InitialiseMirror`, `rule-failure.InitialiseMirror.1`,
     `.2`, `.3`, `rule-entity-creation.InitialiseMirror.1`, `rule-success.RefuseInit`,
     `rule-failure.RefuseInit.1`, `rule-success.RefuseSyncWithoutDirectory`,
     `rule-failure.RefuseSyncWithoutDirectory.1`, `rule-success.StartSync`,
     `rule-failure.StartSync.1`, `.2`, `.3`, `.6`, `.7`,
     `rule-entity-creation.StartSync.1`, `rule-success.TallyFinalisedPage`,
     `rule-failure.TallyFinalisedPage.1`, `.2`, `rule-success.CloseRun`,
     `rule-failure.CloseRun.1`, `rule-success.FinaliseRunReport`,
     `rule-failure.FinaliseRunReport.1`, `.2`, `rule-success.RankAndWriteReport`,
     `rule-failure.RankAndWriteReport.1`, `transition-edge.CrawlReport.open.written`,
     `transition-rejected.CrawlReport.status`, `transition-terminal.CrawlReport.status`,
     `when-presence.CrawlReport.finished_at`, `entity-fields.CrawlReport`,
     `entity-optional.CrawlReport.run_id`, `derived.CrawlReport.has_failures`,
     `derived.CrawlReport.quality_failed`, `projection.CrawlReport.touched_low_confidence`,
     `value-equality.Configuration`, `entity-fields.Configuration`,
     `value-equality.HostReport`, `entity-fields.HostReport`,
     `value-equality.QualitySummary`, `entity-fields.QualitySummary`,
     `value-equality.Change`, `entity-fields.Change`, `enum-comparable.ExitCode`,
     `enum-comparable.ChangeKind`, `enum-comparable.ReportStatus`,
     `config-default.report_percentile`, `config-default.render_mode`,
     `config-default.max_depth`, `config-default.fail_on_low_quality`. The built-in
     defaults are read from the specification, not restated: the `config-default` tests
     and the `rovo.toml` round-trip test assert that the template's and
     `resolve_config`'s values for these keys equal `rovo.allium`'s `config` defaults
     (247 to 249).
   - **`crawl`**: `rule-success.StartRun`, `rule-failure.StartRun.1`,
     `rule-entity-creation.StartRun.1`, `rule-success.CreateFrontier`,
     `rule-failure.CreateFrontier.1`, `rule-entity-creation.CreateFrontier.1`,
     `rule-success.AttachFrontier`, `rule-failure.AttachFrontier.1`,
     `rule-success.PrepareRun`, `rule-failure.PrepareRun.1`, `.2`,
     `rule-success.Discover`, `rule-failure.Discover.1`, `rule-success.OpenHost`,
     `rule-failure.OpenHost.1`, `.2`, `rule-entity-creation.OpenHost.1`,
     `rule-success.FetchRobots`, `rule-failure.FetchRobots.1`, `.2`, `.3`,
     `rule-success.AdoptRobotsRules`, `rule-failure.AdoptRobotsRules.1`,
     `rule-entity-creation.AdoptRobotsRules.1`, `rule-success.AllowAllWhenRobotsAbsent`,
     `rule-failure.AllowAllWhenRobotsAbsent.1`, `.2`,
     `rule-entity-creation.AllowAllWhenRobotsAbsent.1`, `rule-success.Enqueue`,
     `rule-success.DropStaleObservations`, `rule-failure.DropStaleObservations.1`,
     `rule-success.BeginCrawl`, `rule-failure.BeginCrawl.1`, `rule-success.SelectBatch`,
     `rule-failure.SelectBatch.1`, `rule-success.NextBatch`,
     `rule-success.SkipRobotsDisallowed`, `rule-failure.SkipRobotsDisallowed.1`, `.2`,
     `.3`, `rule-success.OpenHostForEntry`, `rule-failure.OpenHostForEntry.1`, `.2`,
     `rule-success.ProceedWithKnownHost`, `rule-failure.ProceedWithKnownHost.1`, `.2`,
     `.3`, `rule-success.SkipRobotsDisallowedOnNewHost`,
     `rule-failure.SkipRobotsDisallowedOnNewHost.1`, `.2`, `rule-success.FetchEntry`,
     `rule-failure.FetchEntry.1`, `.2`, `.3`, `rule-entity-creation.FetchEntry.1`,
     `rule-success.AttemptTier`, `rule-failure.AttemptTier.1`, `.2`,
     `rule-entity-creation.AttemptTier.1`, `rule-success.PrepareAttempt`,
     `rule-failure.PrepareAttempt.1`, `rule-success.SettleWalk`,
     `rule-failure.SettleWalk.1`, `.2`, `.3`, `rule-success.DisposeFetch`,
     `rule-failure.DisposeFetch.1`, `.2`, `rule-success.ConvertFetched`,
     `rule-failure.ConvertFetched.1`, `rule-success.SettleStoredEntry`,
     `rule-failure.SettleStoredEntry.1`, `rule-success.FinishRun`,
     `rule-failure.FinishRun.1`, `rule-success.EndRun`, `rule-failure.EndRun.1`,
     `transition-edge.Run.running.finished`, `transition-rejected.Run.status`,
     `transition-terminal.Run.status`, `when-presence.Run.finished_at`,
     `transition-edge.FrontierEntry.pending.in_progress`,
     `transition-edge.FrontierEntry.pending.skipped_limit`,
     `transition-edge.FrontierEntry.in_progress.done`,
     `transition-edge.FrontierEntry.in_progress.skipped_robots`,
     `transition-rejected.FrontierEntry.status`, `invariant.Run.StandardRunsStayPolite`,
     `invariant.Run.StealthIsOwnerOnly`, `invariant.RobotsPolicy.OnlyParsedFilesCarryDirectives`,
     `invariant.Host.BlockedWithinFetched`, `invariant.OneFrontierEntryPerIdentity`,
     `invariant.OneFrontierPerMirror`, `invariant.RunIdentityIsUnique`,
     `invariant.OneHostPerNamePerRun`, `invariant.OneRobotsPolicyPerOrigin`,
     `entity-fields.Run`, `entity-fields.Frontier`, `entity-fields.FrontierEntry`,
     `entity-fields.Host`, `entity-fields.RobotsPolicy`, `value-equality.CrawlPolicy`,
     `entity-fields.CrawlPolicy`, `value-equality.SiteResponse`,
     `entity-fields.SiteResponse`, `derived.Run.byte_budget_left`,
     `derived.Frontier.batch_idle`, `derived.FrontierEntry.is_deferred`,
     `config-default.max_pages`, `config-default.max_bytes`,
     `config-default.start_priority`, `config-default.recheck_priority`,
     `config-default.deferred_priority`, `config-default.batch_lookahead`,
     `config-default.rate_per_host`, `config-default.concurrency_per_host`,
     `config-default.fetch_timeout`, `config-default.observed_url_retention_syncs`.
   - **`mirror`**: `rule-success.AdmitCandidate`, `rule-entity-creation.AdmitCandidate.1`,
     `rule-success.RequestPass`, `rule-entity-creation.RequestPass.1`,
     `rule-success.StoreNewPage`, `rule-failure.StoreNewPage.1`, `.2`, `.3`, `.4`,
     `rule-entity-creation.StoreNewPage.1`, `rule-success.RefreshPage`,
     `rule-failure.RefreshPage.1`, `.2`, `rule-success.RecordAlias`,
     `rule-failure.RecordAlias.1`, `rule-success.DropAliasOfOwnIdentity`,
     `rule-failure.DropAliasOfOwnIdentity.1`, `entity-fields.Alias`,
     `invariant.Alias.AliasIsNotItsTarget`, `invariant.OneAliasPerUrl`,
     `invariant.AliasesPointAtWrittenPages`, `rule-success.FinalisePageBody`,
     `rule-success.PublishPage`, `transition-edge.PageCandidate.pending.accepted`,
     `transition-rejected.PageCandidate.status`, `transition-terminal.PageCandidate.status`,
     `transition-edge.MirrorPass.pending.completed`, `transition-rejected.MirrorPass.status`,
     `transition-terminal.MirrorPass.status`, `value-equality.CrawlScope`,
     `entity-fields.CrawlScope`, `value-equality.Frontmatter`, `entity-fields.Frontmatter`,
     `entity-fields.Mirror`, `entity-optional.Mirror.recorded_root_url`,
     `derived.Mirror.is_populated`, `projection.Mirror.written_pages`,
     `entity-fields.Page`, `entity-fields.PageCandidate`, `entity-fields.MirrorPass`,
     `derived.Page.is_new_this_run`, `invariant.Page.ScoreIsAFraction`,
     `invariant.Page.FullScoreIffAllGatesPass`, `invariant.Page.FailedGatesAreFlagged`,
     `invariant.Page.LowConfidenceDefinition`, `invariant.Page.KeywordsAreBounded`,
     `invariant.UniquePageIdentity`, `invariant.UniquePagePathIgnoringCase`,
     `invariant.PagePathsAvoidManagedNames`, `invariant.PageProcessedUnderOneSignature`,
     `config-default.max_path_chars`, `config-default.collision_hash_chars`,
     `config-default.keywords_per_page`, `config-default.keywords_min`,
     `invariant.MaxPathCharsInRange` (from `fed9ed8`, which also removed
     `config-default.path_template`: the template is fixed at `"pages/{host}/{path}"`).
   - **`convert`**: every obligation `just --quiet plan-spec convert` emits (47 at
     `f4bcc7c`), the five
     `contract-signature.Fidelity.*` among them, on HTML strings with no network or file.
     The surface obligations (`surface-actor.PageConversion`,
     `surface-exposure.PageConversion`) are met by a test that every exposed `Profile`
     field is readable on each catalogue profile.

   Partly realised rules keep one test that a later slice extends rather than
   replaces: `rule-success.Discover` asserts the seed enqueue and the host opening, and
   the discovery slice adds `SitemapsRequested` and `LlmsTxtRequested` to the same
   test; `rule-success.AdoptRobotsRules` asserts the policy, and the politeness slice
   adds the host rate. `rule-failure.StartSync.6` injects `tier_installed` (a parameter
   of `rovo._commands.sync`, defaulting to `importlib.util.find_spec("playwright") is
   not None` for `browser` and `False` for `stealth`), so the test does not depend on
   what the machine has installed. `rule-failure.StartSync.7` covers only the branch
   with no `owner_test`, where `owner_request_problem` accepts only `robots = respect`.

   Not owned, and why, for the hand-back notes: every other obligation in the four
   files, each belonging to the slice the Context table names; the `PageIntake` and
   `MirrorContents` surface guarantees (links, indexes and unchanged-run stability come
   with their slices; `PageFileProvenance` is covered by the Frontmatter and page-file
   tests here).

4. **Convert** (`src/rovo/_convert/`). Pure functions, no clock, no network, no file.
   `extract`: the generic selection (`main`, else `article`) with method `profile`;
   otherwise the whole `<body>` with method `whole_body` and the flag
   `whole_body_extracted`; title, description (meta description, else the first
   paragraph cut at `description_max_chars`), canonical URL resolved against the page
   URL, `<html lang>`, breadcrumbs (empty under generic), navigation targets (absolute
   hrefs in `<nav>` outside the content), `extracted_share` and its flag under
   `extracted_share_gate`. `normalize`: chrome removal for the profile, no islands for
   the constructs this slice's fixtures hold, `ExpectedCounts` over the ten element
   classes, anchors, headings, link targets. `convert`: markdownify to ATX headings.
   `restore`: re-inserts islands (identity with none). `BodyShape` (`convert.allium`
   236): LF, at most one blank line outside fences, exactly one `h1` (synthesised from
   the title when absent, extras demoted), heading ids as `{#id}` (`attr`), one final
   LF. `measure`: the ten gate predicates of `QualityResult` (`convert.allium` 121 to
   136), counts on the body (ATX headings, fences and their languages, pipe tables and
   cells, list items, links, images, all outside fenced and inline code), `score` as
   the weighted share of passed gates, `failed`, `flags` and `low_confidence`. A unit
   test feeds a page with each element class so that no gate passes by being unmeasured
   (`CONVENTIONS.md` §13, a gate that cannot fire). Determinism: the same input twice
   gives equal output. `just py-test tests/test_convert.py`.

5. **Mirror** (`src/rovo/_mirror/`). `CrawlScope` with `identity_of`, `host_allowed`,
   `foreign_locale`, `seeds`, `is_seed`, `within_bounds`, `allows`, `page_identity`
   (`mirror.allium` 100 to 156 at `fed9ed8`); `normalise_url` per the identity comment
   (112 to 116, a host's trailing `.` dropped); `assign_path` per its guidance (646 to
   712): the fixed layout `pages/<host>/<path>` (no `path_template` parameter), the host
   segment, the segment rewrites and the collision suffixes; `StoreNewPage` and `RefreshPage` on a `PageCandidate`, recording no file;
   `RefreshPage` raises `AliasRecorded` for the source identity and the requested
   identity whenever either differs from the page identity (a canonical moved it), and
   `RecordAlias` creates or retargets the alias in the manifest's `aliases` while
   `DropAliasOfOwnIdentity` drops one whose URL is a written page's identity. A
   `tests/test_mirror.py` case stores `/guide/start.html` declaring the same-host
   canonical `/guide/topic.html`: the page identity is the canonical, its path is
   assigned from it, and the manifest holds one alias from the seed identity to the
   page; a cross-host canonical (host not allowed) keeps the source identity and
   records no alias;
   the finalise pass: `RequestPass`, the retire check (stopping with `NotInThisSlice` if
   any page meets it), `FinalisePageBody` (body = converted body, no link flags,
   `keywords_of`), `PublishPage` (`frontmatter_of`, outcome, `page_file_current`, the
   atomic page-file write), `pass.status = completed`, `IndexesWritten` with no index
   file. `keywords_of`: lower-cased words of the body outside code, at least three
   letters, not in a fixed English stop-word list in the module, ranked by count then
   first occurrence, the first `keywords_per_page`, unique; the list is a pure function
   of the body. The manifest's load and save. `just py-test tests/test_mirror.py`.

6. **Crawl** (`src/rovo/_crawl/`). `run.py` drives one standard run from
   `RunRequested` to `RunEnded` over a `Fetcher`, a `Clock`, the `Mirror` and the
   persisted frontier: the realised rules of the Context table, in the specification's
   order; `SelectBatch` with `next_pending` and `choose_batch` per its guidance (rows
   run one after another); `fetch_or_render` for the http tier only, one try;
   `classify_block` returning `none` for an ok HTML answer and `NotInThisSlice` for
   anything else that would need a verdict; `render_reason_of` a pure function
   implementing the four recognisers of `AttemptTier`'s guidance (`crawl.allium` 1229 to
   1231: an SPA shell, a noscript notice, an absent main selector, thin text on a page
   over `large_raw_html` bytes, read from config) independent of `render_mode`: under
   `render_mode = never` the walk settles on http and `ConvertFetched` adds
   `render_needed`. A `tests/test_crawl.py` case serves, through `FakeFetcher`, a page
   holding a noscript JavaScript notice: the stored page carries `render_needed` and
   `low_confidence: true` (the one-page fixture has a `<main>`, so the end-to-end path
   is unaffected); `DisposeFetch` implementing the ok-HTML branch only: any
   settled walk that is not (ok, verdict `none`, HTML, no redirect, no known page)
   raises one `NotInThisSlice("DisposeFetch")`, and later slices insert their branches
   in the specification's order; `ConvertFetched` through the convert
   functions; delivery to the mirror's intake; `unresolved_urls` per `FinishRun`'s
   guidance; the frontier and the run history saved when the run ends. `bytes_fetched`
   counts the robots answer and the page. `HttpxFetcher` is tested in
   `tests/test_crawl.py` through `httpx.MockTransport`, recording requests: exactly one
   request per `fetch`, `User-Agent: rovo/<version>`, a 3xx answer returned unfollowed,
   the timeout from `config.fetch_timeout`, a transport error mapped to `status = 0`
   with `error` set, and the client closed after the run. `just py-test tests/test_crawl.py`.

7. **Configuration, report, commands, command line.** `rovo._config` per step 1;
   `rovo._report`: the `CrawlReport` created at `StartSync`, `TallyFinalisedPage`,
   `CloseRun`, `RankAndWriteReport` (`most_severe` over the five terms, `summarise`
   rounding to four places with the percentile at index `round(p * (n - 1))`, every
   list sorted by URL or path), written to `<out>/crawl-report.json` atomically by
   `RankAndWriteReport` and nowhere else. The `finally` that writes a report around a
   crashed run arrives with the crash slice (`RecordCrash`, `rovo.allium` 707), which
   defines that report's shape; until then a run stopped by `NotInThisSlice` leaves
   the previous report, if any, in place. Durations (`CrawlPolicy`'s and `max_age`)
   serialise as seconds, a JSON number; `SyncOptions.interactive` is
   `sys.stdin.isatty()`, and the other `SyncOptions` fields are false or empty, since
   this slice has no flag that sets them; `rovo._commands.init` and
   `.sync`; `rovo.cli`: `rovo init SITE_URL OUT_DIR [--profile NAME]` and
   `rovo sync OUT_DIR`, each importing `rovo._commands` inside the function, raising
   `typer.Exit(code)` with the `ExitCode` number. `RefuseInit`: a non-http URL, an
   existing mirror (a manifest present, parsable or not, or an existing `rovo.toml`)
   or an unknown profile exits 2 and writes nothing.
   `RefuseSyncWithoutDirectory`: a missing directory or a missing or unparsable
   manifest exits 2 and writes no report. `NotInThisSlice` exits 1 with its rule name on standard error. Run
   `just py-lint`, `just py-typecheck`, `just coverage`; add the new modules to
   `PACKAGE_FILES` and run `just wheel-smoke`, quoting its `api` line.

8. **End to end.** `tests/fixtures/sites/one-page/` and `robots-disallow/` per the
   Files touched table, two-space indentation and a final newline. The scenarios are
   the Acceptance criteria's. `just py-test tests/e2e -ra`.

9. **Witness** (the `weed` and `witness` skills). Run `weed` over the four modules
   against the code, scoped to the owned obligations; record its verdict under
   `last_results.weed` in the ledger and fix any divergence in the code (never in the
   specification). Then run `witness` non-interactively: it writes
   `.allium-loop/T09-tracer-init-sync-one-page.witness.json` per
   `witness-result.schema.json`. The verdict must be `PASS`; a `FAIL` routes back per
   the skill, and the hand-back notes record each round.

   **Adversarial review** (`CONVENTIONS.md` §14) over the implementation and the tests
   once the witness says `PASS`: a test that passes while its obligation is false (a
   gate that cannot fire, an assertion on a fake's own echo, a test that catches
   `NotInThisSlice` and calls that a pass); a rule realised with a branch silently
   dropped instead of raising `NotInThisSlice`; a specified default replaced by a
   constant in code (every `config` value read from its module's config); wall-clock
   time reaching a page file; a non-atomic write; an `httpx.Client` or socket left open
   under `filterwarnings = error`; `import rovo` or `rovo --version` loading a runtime
   dependency; behaviour the specification does not state.

10. **Documents** (the `review-docs` skill). `docs/reference/mirror.md` (from step 1, now matching the code),
    registered in `docs/manifest.yml` and `docs/README.md`; `docs/reference/cli.md`:
    `rovo init` and `rovo sync` with their usage, effects, outputs and exit codes, the
    placeholder sentence corrected; `testing.md`, `test-and-debug.md`,
    `architecture.md`, `repository-map.md` and `AGENTS.md`'s project map per the Files
    touched table; every "not yet implemented" or "placeholder" sentence outside
    `docs/decisions/` and `docs/specs/` that this slice makes false (find them with
    `rg -n -i "not yet implemented|placeholder" -g '*.md' -g '!tickets/**' -g
    '!allium-skill-reference/**'`) says instead that the implementation is under way
    and names what works; `CHANGELOG.md` `Unreleased` gains one Added entry. Keep the
    required phrases of `AGENTS.md` in always-visible text. `just check-docs`,
    `just check-agents`.

11. Hand-back notes, `status: done`, `just check`.

    **Adversarial review** (`CONVENTIONS.md` §14) over the full diff before the commit:
    a page made false and not corrected; a count that disagrees (package files,
    pages, canonical topics); a ticket claim with no quoted evidence; whether
    `just check`, the `floor` job on 3.13 or the wheel smoke needs the network, a
    browser or the `.allium-loop/` files; whether the end-to-end tests depend on test
    order or on a port. Rerun `just check` if any fix landed. Commit on the branch.
    **Authorisation required**: pushing and opening the pull request.

## Acceptance criteria

- **End to end, the path** (`tests/e2e/test_init_sync.py`, through the installed
  `rovo` script as a subprocess, the one beside `sys.executable`): with
  `serve_site("one-page")` at `<base>`, `rovo init <base>guide/start.html <tmp>/out`
  exits 0 and writes `rovo.toml` and `.rovo/manifest.json` and no page file; `rovo sync
  <tmp>/out` exits 0; `<tmp>/out/pages/127.0.0.1_<port>/start.md` starts with `---`, its
  frontmatter keys are sorted and include `source_url` (the seed), `title`, `content_digest`,
  `quality_score`, `low_confidence: false`, `quality_flags`, `tier: "http"`,
  `method: "profile"`, `profile: "generic"` and `keywords`, and none of its lines
  matches an ISO 8601 timestamp (positive control: the same matcher finds one in
  `.rovo/manifest.json`); its body holds exactly one level-one heading and the page's
  level-two heading; `crawl-report.json` has `report_status: "finished"`, `exit_code: "ok"`,
  `run_id: 1`, `kind: "initial"`, `fetched: 1`, `converted: 1`, and `changes` equal to
  one `added` row for the seed and `pages/127.0.0.1_<port>/start.md`. The order of
  requests (`/robots.txt`, then the page, then nothing) is proven by the unit test of
  `rule-success.FetchRobots` with `FakeFetcher`, which records requests, and that the
  real `HttpxFetcher` sends one request per fetch by its `httpx.MockTransport` tests
  (step 6); the harness's contract does not change.
- **End to end, robots** (through `CliRunner`): with `serve_site("robots-disallow")`,
  init then sync exits 0, writes no page file, and the frontier row for the seed is
  `skipped_robots`, and `crawl-report.json` has `fetched: 0` and `converted: 0`.
- **End to end, the guards** (through `CliRunner`): `rovo sync` on a directory with no
  manifest exits 2 and writes no `crawl-report.json`; `rovo init` over an existing
  mirror exits 2 and leaves `rovo.toml` byte-identical; over a directory whose
  `.rovo/manifest.json` holds invalid JSON, `rovo init` exits 2 and leaves `rovo.toml`
  and the manifest byte-identical, and `rovo sync` exits 2 and writes no
  `crawl-report.json`.
- Every owned obligation in step 3 has a test named after it, red before the code and
  green after (`ai_tmp/T09/red.txt` and the final run); the reconciliation line shows
  zero uncovered owned obligations, and every obligation dropped from the owned list is
  in the hand-back notes with its reason.
- `.allium-loop/T09-tracer-init-sync-one-page.witness.json` exists with
  `"verdict": "PASS"`, and the ledger validates against `ledger.schema.json`.
- `just check-specs` and `just analyse-specs` pass with `docs/specs/` unchanged from
  the specification base (`git diff --stat 4ea7bb0 -- docs/specs` empty, `4ea7bb0` the
  commit that states C2's defaults).
- `import rovo` loads no module outside the standard library and `rovo`;
  `rovo --version` loads no runtime dependency; `__all__` is `["__version__"]`;
  `just wheel-smoke` passes with the new package-file count.
- `tests/test_import_direction.py` passes with the widened direction and resolves
  relative imports, and its positive controls (absolute and relative) are quoted
  failing.
- `just coverage` stays at or above the floor of 95.
- `just check-docs` and `just check-agents` pass; `docs/reference/mirror.md` and
  `docs/reference/cli.md` describe what the code does.
- `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty after the commit.
- The three adversarial reviews ran (`CONVENTIONS.md` §14), and every valid finding is
  fixed or handed back.

## Verification

```sh
just --quiet plan-spec rovo > ai_tmp/T09/plan-spec-rovo.json
just --quiet plan-spec crawl > ai_tmp/T09/plan-spec-crawl.json
just --quiet plan-spec mirror > ai_tmp/T09/plan-spec-mirror.json
just --quiet plan-spec convert > ai_tmp/T09/plan-spec-convert.json
git diff --stat 4ea7bb0 -- docs/specs
just py-test tests/test_import_direction.py tests/e2e -ra
just py-lint
just py-typecheck
just coverage
just wheel-smoke
uv run --frozen python -I -c "import rovo, sys; print(sorted(m for m in sys.modules if not m.startswith(('rovo', '_')) and m not in sys.stdlib_module_names))"
just check-specs
just analyse-specs
just check-docs
just check-agents
just check
git status --short
```

CI evidence (the `gate` job and the 3.13 `floor` job running the new tests) exists only
after the push, which is separately authorised; it goes in the closing pull request's
notes.

## Hand-back notes

To be written by the executing agent: the baseline; the step-1 design as built and any
departure from it; the positive control of step 2; the red run and the reconciliation
line; every obligation dropped from the owned list and why; the `NotInThisSlice` raises
left in the code, by rule; that `contract-signature.Fidelity.extract` covers the signature and the profile and
whole-body branches of `ExtractNeverEmptyHanded`, not the fallback extractor;
the weed verdict and the witness verdict; the review record
for each checkpoint; the verification output, each headed by its commit.

### Propagate, tick 1 (specification base `4ea7bb0`)

- Obligation source: `just plan-spec <module>` (the first echo line stripped; `--quiet`
  prints nothing with just 1.59.0) into `ai_tmp/T09/plan-spec-<module>.json`: rovo 165,
  crawl 358, mirror 192, convert 47. The owned set of step 3 is 268: rovo 50, crawl 116,
  mirror 55, convert 47 (`ai_tmp/T09/owned.json`).
- Reconciliation: `268 obligations, 268 covered, 0 uncovered`. Each owned obligation has
  exactly one test named `test_<id>` in the test file of its module (`test_commands.py`,
  `test_config.py` and `test_report.py` share rovo's). No obligation was dropped.
- Red run (`just py-test`, `ai_tmp/T09/red.txt`): `292 failed, 16 passed, 1 skipped`.
  The 292 are every generated test: the 268, plus BodyShape, `with_fetch_flags`, the
  cross-host canonical, the manifest round trip, `write_json`, the noscript
  `render_needed` case, five `HttpxFetcher` MockTransport tests, four configuration tests,
  four `test_cli.py` tests and five end-to-end scenarios. The 16 are the suite that was
  there before. Causes: a spec value or profile the skeleton leaves unset
  (`AttributeError`), a skeleton body (`NotImplementedError`), `No such command`.
- Skeleton: the step-1 module skeleton (names and signatures; every body raises
  `NotImplementedError`; config values and catalogue profiles are bare annotations), so
  that the tests collect and `just py-typecheck` checks them. Fixed by the tests:
  `rovo._commands.init(site_url, out_dir, profile_name=None)` takes no Fetcher or Clock
  (init makes no request and writes no time); `rovo._report.close_run(report, run,
  frontier)` reads the frontier for `discovered_count`; `crawl-report.json` holds every
  `CrawlReport` field but `mirror`, `operator` and `status`.
- `ruff.toml` (not in Files touched): `tests/**` ignores `N802`, with its reason, since a
  test name carries a CamelCase obligation id.
- For the maintainer: `assign_path`'s collision rule (`mirror.allium` 617 to 623) keeps a
  reserved directory segment (`_removed/`, `.rovo/`) inside the hashed stem, which
  `PagePathsAvoidManagedNames` forbids; the tests do not exercise those two segments.

### Implement, tick 1 (specification base `4ea7bb0`)

- Every skeleton body is filled; no generated test was edited (the thirteen hashes in
  the ledger match). `just py-test`: `344 passed, 1 skipped` (the 292 generated tests,
  the 16 that were there, 7 new import-direction tests and 29 in the new
  `tests/test_slice_boundaries.py`; the skip is the browser marker).
- Gates, at the working tree: `just py-lint` and `just py-typecheck` clean; `just
  coverage` 97% (floor 95); `just wheel-smoke`: `wheel_smoke api: rovo 0.0.0, no CLI
  module imported, exactly the twenty-two package files and the expected metadata`;
  `just check-docs`: `Validated 40 pages and 40 canonical topics.`; `just check`: `All
  checks passed and the worktree is unchanged.`
- Step 2, positive controls (`ai_tmp/T09/positive-controls.txt`): a module-level
  `import rovo._commands` in `cli.py` fails
  `test_the_command_line_imports_private_modules_only_inside_commands`; `from .._crawl
  import model` in `rovo._mirror.finalise` fails
  `test_mirror_imports_neither_crawl_nor_the_command_line`; `cmp` prints nothing after
  each restore.
- `NotInThisSlice` raises, by rule: `FetchRobots` (a 3xx robots.txt),
  `DenyAllWhenRobotsRefused` (any other robots answer neither ok nor absent),
  `classify_block` (a 401 or 403, a password-form login wall), `HttpRetry`,
  `RetireHostOnLongRetryAfter` and `Escalate` (raised by the driver where `SettleWalk`'s
  guard refuses the attempt, rather than settling it and failing in `DisposeFetch`),
  `DisposeFetch` (every branch but ok HTML with no redirect and no known page),
  `ConvertFetched` (a profile other than `generic`), `AttemptTier` (a tier other than
  http), `SelectBatch` (only tripped-host rows open), `PrepareRun` and `Discover` (named
  targets or owner testing), `StartRun` and `DryRun` (in the driver), `CloseRun` (a dry
  run), `PageCandidate.created` (a candidate StoreNewPage does not take),
  `RetireOutOfScopePages`, `ResolveMirrorLinks` (a page body with a link),
  `assign_path` (a version label), `UncarryableBecomesIsland` (an island to restore)
  and `BodyShape` (the inline anchor style). Departures from the Context table's list:
  the last five and `ResolveMirrorLinks`, so that no branch is dropped silently.
- `extract` takes the generic selection (`main`, else `article`), else the whole body
  stripped of `nav`, `header` and `footer`; the catalogue's other profiles select
  nothing yet, so `extract` takes their whole body and the crawl stops before
  converting with them. `contract-signature.Fidelity.extract` covers the profile and
  whole-body branches of `ExtractNeverEmptyHanded`, not the fallback extractor.
- `signature_of` digests the profile and the pinned locale; `effective_policy` is the
  standard policy afresh; a `Retry-After` given as an HTTP date is read as absent.
- Not done this tick (ticket steps 9 and 10): the `weed` and `witness` runs; the
  "not yet implemented" and "placeholder" sentences of `AGENTS.md`, `README.md`,
  `purpose-and-scope.md`, `install-and-run.md`, `terminology.md`, `specifications.md`,
  `work-with-the-specs.md`, `architecture.md` and `security-model.md`; `testing.md` (`tests/fakes.py`, the obligation-named tests, the fixture
  sites), `architecture.md` and `repository-map.md`. Done: `docs/reference/cli.md`,
  the new `docs/reference/mirror.md` (manifest and map), the package-file count in
  `testing.md` and `test-and-debug.md`, and `CHANGELOG.md`.
- Files touched beyond the table: `tests/test_slice_boundaries.py` (new: the guard
  points and the black boxes' corners, so coverage holds at the floor without editing a
  generated test).

### Implement, tick 2 (specification base `4ea7bb0`)

- The four code-bugs of weed tick 1 are fixed, each with a regression test in the new
  `tests/test_regressions.py`; no generated test was edited (thirteen hashes match).
- Persistence: `rovo._crawl.run.drive_run` drives a run and saves nothing; `save_run`
  writes `frontier.json` and appends `runs.json`; `run_crawl` is the two together (the
  generated tests' driver). `_start_sync` calls `save_run` only after `save_mirror`, so
  a sync whose finalisation stops saves neither file and the next sync fetches the page
  again (`SettleStoredEntry`: a `done` row always has its page). Every later slice
  saves crawl state after the mirror.
- Heading ids: `normalize` marks a heading with a `data-rovo-anchor` attribute instead
  of appending text, and `fidelity._Converter` (a `MarkdownConverter`) writes the ATX
  heading and its unescaped `{#id}` suffix.
- Fenced code: `_Converter.convert_pre` writes the `<pre>` text as parsed, dropping only
  a newline straight after the `<pre>` start tag (HTML drops it; lxml keeps it), adds a
  final newline when the code lacks one, and uses a fence longer than any backtick run
  in the code. This takes weed's reading of "byte-identical" (the parked question stays
  open in the ledger).
- `normalise_url` keeps an IPv6 literal's brackets.
- Still open, not touched: the spec-bug in `mirror.allium` (assign_path's collision
  rule keeps a reserved `_removed` or `.rovo` segment that `PagePathsAvoidManagedNames`
  forbids). It needs a maintainer reading before `tend`.
- Gates: `just py-test` 348 passed, 1 skipped; `just py-lint`, `just py-typecheck`
  clean; `just coverage` 97%; `just wheel-smoke` and `just check-docs` pass; `just
  check`: `All checks passed and the worktree is unchanged.`

### Implement, tick 3 (specification base `4ea7bb0`)

- The two code-bugs of weed tick 2 are fixed, each with a regression test in
  `tests/test_regressions.py`; no generated test was edited (thirteen hashes match).
- Fenced code: `fidelity._code_text` reads a `<pre>`'s code text as `get_text` does
  (text and CDATA, no comment) but writes each `<br>` as a line break, and drops a
  newline only when it opens the `<pre>`'s first child string.
- Heading ids: `normalize` strips any `data-rovo-anchor` the source carries before it
  marks the headings, so a `{#id}` suffix only ever names a recorded anchor.
- Still open, not touched: the `mirror.allium` spec-bug (assign_path's collision rule vs
  `PagePathsAvoidManagedNames`); route: maintainer decision, then `tend` and `propagate`.
- Gates: `just py-test` 350 passed, 1 skipped; `just py-lint`, `just py-typecheck`
  clean; `just coverage` 97%; `just wheel-smoke` and `just check-docs` pass.

### Implement, tick 4 (specification base `22c0261`)

- The `mirror.allium` spec-bug is resolved by the maintainer at `22c0261`: `assign_path`
  now replaces the leading `_` or `.` of a directory segment equal to `_removed` or
  `.rovo`, ignoring case, with `-` in the sanitising step (`urls._safe_segment`), before
  the collision check; a final segment such as `_removed.md` keeps its name. The
  reserved-segment check in `urls._usable` compares directory segments ignoring case.
- `tests/test_assign_path_reserved_segments.py` (propagate tick 2) passes unedited;
  `docs/reference/mirror.md` describes the rewrite instead of a hash suffix.

### Implement, tick 5 (specification base `e818eb0`)

- `assign_path` returns `str | None`: the plain path, else the stem cut to
  `max_path_chars - 10` with `-` and the first `collision_hash_chars` hex, else the stem
  cut to fit with the full 64-hex digest, else `None`. `StoreNewPage` requires a
  non-null path; `RefuseUnplaceableCandidate` (`intake.refuse_unplaceable_candidate`)
  accepts the candidate and raises `CandidateDiscarded(reason: "no free path")`.
  `intake.settle_candidate` dispatches a candidate (store, else refuse, else
  `NotInThisSlice`); `take_candidate` keeps its `Page | None` result, because a
  generated test hands that result to `refresh_page`.
- The crawl: `fail_discarded_entry` passes the reason on as the error; `entry_fails`
  fails the row and gives `UrlFailed`, which `drive_run` collects on
  `CrawlResult.failed`; `_commands` tallies each with `_report.tally_failed_url` before
  `CloseRun`. `MovePage` and `ReviveRemovedPage` (and their `.4` obligations) stay with
  their later slices.
- Review 2 (`ai_tmp/review/T09-2/`), every valid finding applied, record in
  `ai_tmp/review/T09-2/applied.md`: the path is no longer percent-decoded, and
  `finalise.page_file` refuses a path that resolves outside the mirror (B1); reserved
  file names compare ignoring case (B3); `urls.is_http_url` catches `ValueError`, and
  `rovo.toml`'s root and start URLs, hosts and `max_age` are checked so a bad value is a
  configuration problem, not a traceback (B4, C3); the configured root and start URLs
  must be http or https URLs, this slice's reading of `Configuration`'s "a value is bad"
  (the specification's `is_http_url` guards name only `init`'s URL and `--url`); the login-wall guard parses the markup
  (B5, C1); a non-heading source id stops normalisation (C2); the import-direction test
  resolves relative `import_module` names and reads every statement that runs on import
  (B6); the Files touched rows (C4); the step-10 sentences (C5).
- `mypy.ini` gains `[mypy-test_mirror]` (Files touched): a **propagate follow-up**
  regenerates `test_invariant_PagePathsAvoidManagedNames` with a narrowing
  `assert path is not None`, re-records the hash and removes the section.
- No generated test was edited (sixteen hashes match).

### Propagate, tick 4 (specification base `fed9ed8`)

- Obligation source: `just plan-spec <module>` at `fed9ed8` into
  `ai_tmp/T09/plan-spec-<module>-fed9ed8.json`: rovo 165, crawl 358, mirror 199,
  convert 47. Against `e818eb0`: mirror loses `config-default.path_template` and gains
  `invariant.MaxPathCharsInRange`; `invariant.PagePathsAvoidManagedNames` and
  `entity-fields.DirectoryIndex` change (the latter is the indexes slice's). The owned
  set stays 273 (mirror 60; `ai_tmp/T09/owned.json`, the previous one in
  `owned-e818eb0.json`).
- Reconciliation: `273 obligations, 273 covered, 0 uncovered`.
- Re-propagated, because the specification moved (`fed9ed8`), each re-hashed in the
  ledger: `tests/test_mirror.py` (paths under `pages/docs.example/`;
  `test_invariant_PagePathsAvoidManagedNames` regenerated with `assert path is not None`
  and the four clauses; `test_invariant_MaxPathCharsInRange` added;
  `test_config_default_path_template` removed), `tests/test_commands.py`,
  `tests/test_report.py`, `tests/e2e/test_init_sync.py`,
  `tests/test_assign_path_fallback.py`, `tests/test_unplaceable_candidate.py`, and
  `tests/test_assign_path_reserved_segments.py` (regenerated around the segment
  rewrites). New: `tests/test_page_namespace.py`. Not generated, expectations moved
  with the specification: `tests/test_regressions.py` (B1 percent escapes under
  `pages/<host>/`; review B3's reserved index names superseded: `index.md` and
  `_index.md` are ordinary names inside `pages/<host>/`) and
  `tests/test_slice_boundaries.py` (`con-.md`, `pages/<host>/` paths).
- Red run (`just py-test`, `ai_tmp/T09/red-tick4-full.txt`):
  `107 failed, 369 passed, 1 skipped`; every failure an `AssertionError` (105) or a
  `FileNotFoundError` (2: the page file is looked for under `pages/<host>/`), none a
  collection, type or fixture error. `just py-typecheck` passes with
  `[mypy-test_mirror]` removed (checked on a scratch copy of `mypy.ini`).
- Open question for the maintainer: `mirror.allium` 56 and 653 give `[::1]:8080` the
  host segment `--1-_8080`, but the rule at 647 to 649 applied to the five characters of
  `[::1]` gives `---1-_8080`. The test asserts only what both agree on.
- Left to implement: step 5's `path_template` sentence, the Acceptance criteria's
  `<tmp>/out/start.md` path, and the removal of `[mypy-test_mirror]` from `mypy.ini`.

### Implement, tick 6 (specification base `fed9ed8`)

- `urls.assign_path` gives `page_root(identity)` (`pages/`, `host_segment`, `/`) and
  the relative path; `host_segment` sanitises the host as written in the identity
  (lower case, trailing `.` dropped, `[a-z0-9.-]`, device rule, `_<port>` for a
  non-default port). `_rewrite_segment` applies the segment rewrites (leading and
  trailing dots, a directory named like a managed root file or ending in `.md`, the
  device `-` on the stem before the first dot); `.md` is appended unless the name ends
  in `.md` exactly. Every fallback cut keeps `pages/<host>/` whole, so a host too long
  for a page yields `None` (`RefuseUnplaceableCandidate`). No name is reserved inside
  `pages/<host>/`, and `_removed` is no longer rewritten. A version label still raises
  `NotInThisSlice`.
- `normalise_url` drops a host's trailing `.`. `MirrorConfig.path_template` is removed:
  the layout is fixed, and `rovo.toml` already rejects it as an unknown key.
- `mypy.ini` is back to its committed text (`[mypy-test_mirror]` removed).
- Interim reading of the IPv6 open question: the host is read with its brackets, so
  `[::1]:8080` gives `---1-_8080` (the rule's reading); the test accepts either.
- Stale `mirror.allium`, `rovo.allium` and `crawl.allium` line citations in `src/` are
  refreshed to `fed9ed8`; `docs/reference/mirror.md` and `CHANGELOG.md` describe the
  layout. No generated test was edited.

### Implement, tick 7 (specification base `fed9ed8`)

Fixes the three code-bugs weed found at `fed9ed8` (`ai_tmp/T09/weed-1.md`), each with a
regression test in `tests/test_regressions.py` that failed before it
(`ai_tmp/T09/red-implement-2-resume.txt`); no generated test edited.

- `urls._rewrite_segment` reads every rewrite off the sanitised segment and applies
  them together, the device `-` inserted after the part before the first `.` of that
  segment: `con.` gives `con--.md`, `nul.md/x` gives `nul--md/x.md` (`mirror.allium`
  674 to 691).
- `urls._cut` accepts a cut equal to `pages/<host>/` (`>=`, was `>`): such a cut
  shortens nothing (699 to 712).
- `urls.hostname_of` drops a trailing `.`, as the identity does, so a scope derived from
  `http://docs.example./...` allows its own seed (112 to 118).
- Left for tend (maintainer decisions, not touched): `/guide/.html` (assign_path leaves
  no segment; the code still raises `IndexError`), and the `[::1]:8080` host-segment
  example.

### Implement, tick 8 (specification base `1be7354`)

Realises the maintainer's two decisions at `1be7354` (`ai_tmp/T09/spec7-report.md`),
pinned by propagate tick 5's hand-written tests in `tests/test_page_namespace.py` (both
are `@guidance`, so `plan-spec` yields no new obligation); no generated test edited.

- `urls._relative_path` drops the `.html`, `.htm` or `.aspx` suffix before naming an
  empty or directory-ended relative path `index`, so `/guide/.html` gives
  `pages/<host>/guide/index.md` and `/.html` gives `pages/<host>/index.md` under the
  prefix `/` (`mirror.allium` 662 to 665); `rovo sync` no longer raises `IndexError`.
- `[::1]:8080` gives the host segment `---1-_8080`: `host_segment` already read the
  bracketed form, and the test now pins it exactly (`mirror.allium` 56, 653 to 654).
- `docs/reference/mirror.md` and `CHANGELOG.md` state the bare-suffix case.

## Open points

- **Configuration defaults: resolved.** The maintainer decided the built-in defaults
  `Configuration` (`rovo.allium` 66 to 91) left unstated, and the specification now
  states them in `rovo.allium`'s `config` block: `render_mode: crawl/RenderMode = never`
  (247), `max_depth: Integer = 10` (248), `fail_on_low_quality: Boolean = false` (249).
  `docs/reference/mirror.md` documents them as defaults, not as interim values; a
  browser slice that wants `auto` changes the specification first.
- **The fallback extractor.** `ExtractNeverEmptyHanded` names a fallback extractor
  between the profile's selection and the whole body. No library was chosen in T08;
  choosing one is a dependency under decision 0005 and belongs to the slice that
  deepens extraction.
- **`keywords_of` and the frontmatter's number format** are black boxes the
  specification leaves to the implementation; this slice fixes a frequency ranking and
  four decimal places. A change later moves every page file once, which
  `UnchangedRunIsStable` tolerates only across a release.
- **Stale "today" sentences in decision records.** Decisions 0002, 0009 and 0012 say
  the API and command are placeholders and the product unimplemented. Records are
  superseded, not rewritten (`docs/decisions/README.md`); as with decision 0005's
  sentence in T08, whether a factual "today" clause may be refreshed in place is the
  maintainer's call.
- **`NotInThisSlice`.** A development guard, not product behaviour: each later slice
  removes the raises it implements, and the last slice's review confirms none is left.
