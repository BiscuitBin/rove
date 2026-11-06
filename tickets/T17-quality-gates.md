---
id: T17
title: "Conversion quality: every quality gate and flag, islands for what Markdown cannot carry, every tab panel, the mslearn and devsite profiles, fail_on_low_quality and rovo verify"
status: open
depends_on: [T16]
parallel_with: []
branch: full-final-prototype
estimated_size: L
---

# T17: Conversion quality: every quality gate and flag, islands for what Markdown cannot carry, every tab panel, the mslearn and devsite profiles, fail_on_low_quality and rovo verify

## Context

T09 (`fd1b423`) to T16 (`8361182`, follow-up `7249e5a`) are slices 1 to 8. `rovo sync`
reads robots.txt, paces and retries, discovers through sitemaps and `llms.txt`, fetches
the seeds and the pages they link to, keeps each page through its lifecycle, publishes it
at `pages/<host>/<path>`, writes the indexes and `crawl-report.json`, refuses in the
specified order, survives an interrupt or a crash with a report, and `rovo report` prints
the last report. They fixed every pattern this slice follows: the private subpackages
`rovo._convert`, `rovo._mirror` and `rovo._crawl` with `rovo._config`, `rovo._report` and
`rovo._commands` above them (import direction enforced by
`tests/test_import_direction.py`), the `Fetcher` and `Timer` seams (`FixedClock`,
`SteppingTimer`, `FakeFetcher`, `ScriptedFetcher` in `tests/fakes.py`), obligation-named
tests (`test_<obligation id>`), the end-to-end harness `serve_site` in
`tests/e2e/conftest.py`, the state files of `docs/reference/mirror.md`, and the
development guard `rovo._unfinished.NotInThisSlice`. Read `tickets/T16-errors-report.md`
(its Context table, Facts and Open points), `src/rovo/_convert/fidelity.py`,
`src/rovo/_convert/profiles.py`, `src/rovo/_convert/model.py`, `src/rovo/_report.py`
(`summarise`, `rank_and_write_report`), `src/rovo/_commands.py` (`index`, `report`),
`src/rovo/_mirror/state.py` (`encode_quality`, the frontmatter codec),
`src/rovo/_mirror/indexes.py` (`index_files`), `tests/test_convert.py` and
`tests/e2e/test_index_files.py` before starting.

This is slice 9 of T08 to T20, run in this worktree on `full-final-prototype`. Until now
conversion carries only what Markdown carries: a non-heading `id` stops the run
(`NotInThisSlice("UncarryableBecomesIsland")`, `fidelity.py` 158), and so does an island
to restore (192) and the inline anchor style (`BodyShape`, 558); a profile other than
`generic` stops conversion (`NotInThisSlice("ConvertFetched")`, `run.py` 1578 to 1579);
`_CONTENT_ELEMENTS` (`fidelity.py` 41) knows only the generic selection; `normalize`
never counts a tab panel, raises no normalisation flag and makes no island; and there is
no `rovo verify` (`cli.py` has `version`, `init`, `sync`, `index` and `report`). The ten
gates, the score and the low-confidence verdict are already measured (`measure`,
`fidelity.py` 196), and `rank_and_write_report` already ranks `fail_on_low_quality`
(`_report.py` 464). The specification base is `9a253a4` (`git diff --stat 9a253a4 HEAD
-- docs/specs` is empty); every specification line number below is at `9a253a4`, every
source line number at `7249e5a`.

### The specified path, and what this slice does with each rule on it

| Class | Rules |
| --- | --- |
| **Realised** (every branch reachable in this slice, or constructible on unit inputs where noted) | `convert.allium`: the `Fidelity` contract (178 to 272) under every profile: `ExtractNeverEmptyHanded` (185, its profile and whole-body branches; the fallback extractor is Open points item 3), `NeverDropCarriedContent` (191), `UncarryableBecomesIsland` (196: a complex, header-less or row-header table, a block definition list, `details`, math without TeX and an id-only anchor become islands; a token the converter loses raises `fidelity_loss`), `ExpectedAgainstSurvived` (203: islands and the Markdown inside them counted), `DeclaredReductions` (209: an interactive embed becomes a one-line note, `interactive_omitted`; links inside code become their text; line-number gutters leave code; form controls go and button labels stay; layout tables unwrap; footnote back-links go; images keep `src`, `alt`, `title` and `id`; custom elements keep `id`, `class` and the tab language; a table kept as HTML raises `html_table_kept`), `SanitizedMeansInert` (219), `EveryTabPanelEmitted` (229), `BodyShape` (236) its inline anchor style (on unit inputs: no catalogue profile is `inline`), `ScoreIsAFraction`, `FailedGatesAreFlagged` and `Determinism` (244 to 257) over the new constructs, and the guidance's construct families (259 to 271: callouts to GFM alerts, `sup`, `sub`, `kbd` and `mark` kept inline, math to TeX delimiters, footnotes to `[^n]`); the ten `QualityGate`s and their flags (278 to 294) on bodies that fail each gate; the `PageConversion` guarantees `GatesMeasureExtractedContent`, `FlagsAreComplete` and `ProfilesAreTheOnlyPlatformKnowledge` (446 to 466); the `mslearn` and `devsite` profiles' content selection (376 to 403: content, chrome, breadcrumbs, tab groups and callouts), `devsite` end to end and `mslearn` on unit inputs only (Facts). `crawl.allium`: `ConvertFetched` (2004) under every profile. `mirror.allium`: `VerifyPages` (1385) with every `VerificationReason` (259) and `VerificationFailure` (239); `StoreNewPage`'s and `RefreshPage`'s `version` (797, 858) and `locale` fields (`Page.version` on unit inputs only: Facts). `rovo.allium`: `Verify` (789), `RefuseVerify` (796), `ReportVerification` (806); `GateFailure` (129) and `LowConfidencePage` (170) as the report writes them; `RankAndWriteReport`'s `fail_on_low_quality` input (704) end to end, both branches of `quality_failed` (241); the `verify` sentence of `VerifyIndexReportExitCodes` (962); `SyncExitCodes`' 4 (950). |
| **Traversed, nothing new to do** | `measure`'s gate predicates, score and verdict (`fidelity.py` 196), `QualityResult`'s predicates (`convert.allium` 121 to 136), `with_fetch_flags` and `ConvertedContentCarriesFetchFlags` (`mirror.allium` 1622); `FinalisePageBody` (1187: the link flags and the recomputed `low_confidence`); the `Page` invariants `FailedGatesAreFlagged` and `LowConfidenceDefinition` (369, 373); `TallyFinalisedPage` (629) and `summarise` (`_report.py` 483); `QualitySummary` (135). |
| **Specified as not yet covered; the stop stays** | `sitemap_admitted` (`crawl.allium` 1057 to 1065: how `{section}` and `{locale}` are filled is not specified, and a run under such a filter stops before that sitemap is read; `sitemaps.py` 82) and the version label in a page path (`mirror.allium` 686 to 689: its form is not specified; `urls.py` 150). Both are Open points items 1 and 2; their raises stay until the maintainer answers. |
| **Later slices'** | The login-wall and soft-block verdicts, `soft_block_suspected` raised by a run, and every block verdict (T18); `render_needed` raised by a run, the browser tier and `rovo fetch` (T19); owner testing (T20). The `MirrorCommands` surface's actor and provides obligations, which list `fetch` (T19) and the owner options (T20). |
| **Outside this slice; reaching one still stops the run** | Of the 23 raises at `7249e5a` (`ai_tmp/T17/notinthisslice-7249e5a.txt`), this slice removes four: `ConvertFetched` (`run.py` 1579), `UncarryableBecomesIsland` (`fidelity.py` 158, 192) and `BodyShape` (558). The other 19 stay, by `rule=`, as many of each: `sitemap_admitted` (`sitemaps.py` 82), `assign_path` (`urls.py` 150) and, in `run.py`, `PrepareRun` (247), `Discover` (318), `RetireHostOnLongRetryAfter` (400, 844, 1894), `RetireHostOnLongCrawlDelay` (404), `EnqueuePageLinks` (710), `RefollowUnchangedLinks` (751), `SelectBatch` (1199), `AttemptTier` (1317), `classify_block` (1345, 1709, 1711), `DisposeFetch` (1487), `StartRun` (1782), `Escalate` (1899), `BreakerTrips` (1902). |

### Facts a later reader would otherwise rediscover

- **What the profiles' selections are.** `Profile.content_selection` is opaque by
  specification (`convert.allium` 316): which elements hold a platform's content, chrome,
  breadcrumbs, tab groups and callouts is this slice's data, one table in
  `src/rovo/_convert/profiles.py` keyed by the selection string, never a branch on a host
  name (`ProfilesAreTheOnlyPlatformKnowledge`). `generic` keeps today's `main`, then
  `article`, and has no tab, breadcrumb or callout selection. `devsite` selects the
  DevSite article body, `devsite-selector` tab groups (each panel's label its `section`'s
  heading or `title`), `devsite-breadcrumb-list` and the `aside` note, caution and
  warning callouts. `mslearn` selects the Learn article content, its `tabGroup` tab
  groups (labels from the `role="tab"` links, panels the `role="tabpanel"` sections) and
  `div.alert` callouts. The selectors are written from the platforms' published markup
  conventions; there is no network in the gate, so the fixture sites carry representative
  structure, not captured pages, and no profile is called supported (`convert.allium`'s
  third open question).
- **mslearn cannot complete a sync.** `mslearn`'s `sitemap_include` holds placeholders,
  and `sitemap_admitted` is applied to the conventional sitemap probe of every host before
  the seed is fetched (`tests/test_slice_boundaries.py::test_a_sitemap_filter_placeholder_stops`
  asserts the seed is never requested); and `version_default` is `"v1.0"`, so every
  `mslearn` page has a version label and `assign_path` stops for it. So `mslearn`'s
  content selection, tab groups, `view` parameter and `locale_codes` are tested on unit
  inputs only (`extract`, `normalize`, `version_label`, `initial_scope`), no end-to-end
  scenario syncs under `mslearn`, and no owned obligation needs one. `devsite` has no
  versions and no `sitemap_include`, so it syncs end to end.
- **Islands.** `normalize` replaces each uncarryable construct with a token (one
  placeholder paragraph per island, text the converter carries verbatim and no source can
  hold), records an `Island` per token, and counts its content into `ExpectedCounts`
  (`ExpectedAgainstSurvived`): a sanitised HTML island's elements by parsing it, a
  Markdown-carrying shell's (`details`, footnotes) by its Markdown. `restore` replaces each
  token with its payload; a token the converter lost leaves its island out, and `measure`
  raises `fidelity_loss` when an island's payload is not in the body or a token string
  survives in it, derived from `normalized.islands` and the body alone: no field is added
  to `NormalizedContent` or any other specified value, and the token bookkeeping stays
  private to `fidelity.py`. The body measurement reads islands as `OutputMeasurement`
  says (`convert.allium` 90 to 91, "Markdown tokens plus parsed HTML in islands"): each
  HTML block outside fences is parsed, its elements counted with the Markdown ones
  (tables, cells, headings, links, images, list items, code blocks) and its text counted
  as words, its tag and attribute names never; today's line-based `_measure_body` counts
  none of an HTML table and reads its tags as words, so without this every island page
  would fail `tables`, `table_cells` and `text_coverage`. `verify`'s `quality_drift`
  re-measures with the same function. Sanitising is one function
  (`SanitizedMeansInert`): the attributes it keeps, the targets and subtrees it drops, no
  text removed, no blank line inside; a Markdown-carrying shell wraps its Markdown between
  blank lines. An id-only anchor (an element with an `id` that is not a heading) becomes
  an anchor island `<a id="..."></a>` before its element's content, so `anchors` keeps
  every source id and a link to `page.md#id` resolves (`BodyShape`). Under the `inline`
  anchor style a heading's id is the same anchor island before the heading.
- **Tabs.** Under a profile with a tab selection, each tab group's every panel is made
  visible and emitted in source order (`EveryTabPanelEmitted`): one labelled fence per
  panel when every panel is one code sample in a named language, otherwise a heading one
  level below the group's context, the panel's label, then the panel. `expected.tab_panels`
  counts the panels found and `tab_panels_emitted` the panels emitted, and the
  `tabs_expanded` gate compares the two: the specification's current definition, which
  cannot fail by construction (`convert.allium`'s first open question, which stays open).
  Expected counts are taken after expansion, so the added headings are expected
  (the guidance's "normalised against output, never raw against output").
- **Hidden content.** Inactive tab panels are made visible (their `hidden` attribute and
  inline `display: none` removed) before anything else; no other hidden element is
  removed, because `NeverDropCarriedContent` requires every construct to reach the body
  and `DeclaredReductions` lists no hidden-content reduction. That is this slice's
  reading while `convert.allium`'s second open question stays open.
- **The flags.** `measure` raises every failed gate's flag, `whole_body_extracted`,
  `extracted_share`, `empty_content`, and now the normalisation flags `html_table_kept`,
  `interactive_omitted` and `fidelity_loss` (`FlagsAreComplete`). `extractor_fallback`
  needs the fallback extractor (Open points item 3): until then `ExtractionMethod.fallback`
  and `extractor_fallback` are never produced by `extract`, and their effect on
  `low_confidence` is tested on unit inputs. `render_needed` and `soft_block_suspected`
  are the crawl's (T18, T19), already added by `with_fetch_flags`.
- **`fail_on_low_quality`.** `rank_and_write_report` already ranks it; this slice proves
  it end to end: a page with no `main` or `article` is extracted whole
  (`whole_body_extracted`, an incomplete flag), so it is low confidence, and a sync with
  `--set quality.fail_on_low_quality=true` exits 4 with `exit_code: "quality"`; a broken
  relative link in a page file does the same with every page high confidence (the second
  branch of `quality_failed`). Without the setting both exit 0.
- **`rovo verify OUT_DIR`.** No directory or no loadable manifest prints the problem on
  standard error and exits 2 (`RefuseVerify`). Otherwise a `verify` pass
  (`MirrorPass.kind = verify`, `run_id` null) runs `verification_failures` offline, in
  `src/rovo/_mirror/verify.py`: `missing_file`, `unmanaged_file` (a Markdown file under
  `pages/` the manifest does not know, or under `_indexes/` `index_files` would not
  write; nothing else at the root is reported), `invalid_page_file` (no frontmatter, a
  frontmatter that does not parse, or a required key missing), `digest_mismatch` (the
  body's digest differs from the frontmatter's or the manifest's `content_digest`),
  `quality_drift` (a gate that fails when the file's current body is measured against the
  stored `quality.expected` but is not in `quality.failed`; `measure`'s body measurement
  becomes a public `fidelity` function for it), `broken_link` (a relative link in a page
  file or a generated index that leaves the mirror, reaches no file, or names a fragment
  the target page's `anchors` do not hold) and `index_stale` (an index file whose text
  differs from what `index_files` would write). The findings are sorted by path, reason
  and detail. `ReportVerification` prints one line per finding on standard output,
  `<reason> <path> <detail>`, then the gate tallies over the mirror's written pages, one
  `<gate> <pages>` line per gate that failed on any page, sorted by gate (the
  specification excludes table rendering, so this is the slice's layout); it exits 0 with
  no finding and 4 with any; the tallies never move the exit code. The manifest, the
  state files and the report are never written. `rovo verify` imports neither httpx nor
  `rovo._crawl` (like `rovo index` and `rovo report`).
- **The rovo.allium defaults' sentence** "verify, index and report exit usage for a
  missing manifest, an unreadable page file or an absent report" (803 to 805) reads
  respectively, as `VerifyIndexReportExitCodes` (962 to 968) states it: verify exits 2
  only without a manifest, and an unreadable page file is a verify finding
  (`invalid_page_file`, exit 4).
- **The obligation source.** `just plan-spec <module>` over `docs/specs/<module>.allium`
  at `9a253a4`, written to `ai_tmp/T17/plan-spec-<module>.txt` (its echo line to
  `ai_tmp/T17/plan-spec-<module>.err`): crawl 382, rovo 169, mirror 201, convert 47
  obligations. The obligations with no test named after them at `7249e5a` are in
  `ai_tmp/T17/uncovered-<module>.txt` (crawl 118, rovo 44, mirror 22, convert 0, by
  `ai_tmp/T17/uncovered.py`); the owned set of step 3 is `ai_tmp/T17/owned.json` (17, by
  `ai_tmp/T17/owned.py`, which checks each id is in the plan and uncovered); the
  `NotInThisSlice` raises at `7249e5a` are in `ai_tmp/T17/notinthisslice-7249e5a.txt`. The
  copies are scratch, regenerated by step 0. Every `convert` obligation already has a test
  named after it (T09), so this slice's conversion work extends those tests in place.

## Goal

From a clean checkout, against served fixture sites, `rovo sync` converts a page holding
a complex table, a block definition list, `details`, math and a non-heading `id` anchor
instead of stopping, carrying each as a sanitised island; emits every tab panel under a
profile with a tab selection; converts under `devsite`; raises every gate flag and the
normalisation flags; exits 4 under `fail_on_low_quality` when a page touched this run is
low confidence or a link is broken; and `rovo verify` reports every kind of drift on disk
offline, exiting 0, 4 or 2. Every owned obligation listed under Steps has a test named
after its id, red before the code; every extended test is re-hashed with its ledger note;
no test this slice adds or edits sleeps for real; `just check` is green; the Allium loop's
witness record says `PASS`.

## Non-goals

- No change to `sitemap_admitted` or to the version label in a page path: both are
  specified as not yet covered and stay stopped (Open points items 1 and 2). No
  end-to-end sync under `mslearn`.
- No fallback extractor and no new dependency (Open points item 3): a library extractor
  needs decision 0005's note and `just lock`, which reaches the network and is not
  authorised in this slice.
- No resolution of `convert.allium`'s three open questions (473 to 475): the tab gate
  keeps its current definition, no hidden content but an inactive tab panel's marker is
  removed, and no profile is called supported, in code, documents or the changelog.
- No block verdict, login wall or `soft_block_suspected` from a run (T18); no browser
  tier, `render_needed` from a run or `rovo fetch` (T19); no owner testing (T20).
- No harness change: `tests/e2e/conftest.py` is read, not changed.
- No new `rovo.toml` key. No change to the public API: `__all__` stays
  `["__version__"]`, so `docs/reference/api.md` does not move. No decision record changes.
- No specification change: `docs/specs/` is read, not edited. A specification gap found
  while planning, implementing, in weed or in review is never resolved in code or in the
  specification: it joins the one batched needs-user question (Open points) and the
  ledger's `open_questions`.
- No adversarial review checkpoint: this slice has none.
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `src/rovo/_convert/fidelity.py` | shared, own lines | islands, the sanitiser and `restore`; tab expansion; the declared reductions; the construct families; the inline anchor style; the normalisation flags and `fidelity_loss`; the selection read from the profile's table; a public body measurement for verify; its three `NotInThisSlice` raises removed; the docstrings |
| `src/rovo/_convert/profiles.py` | shared, own lines | the selection table for `generic`, `devsite` and `mslearn` (Facts); the profiles themselves do not change |
| `src/rovo/_convert/model.py` | shared, own lines | only what step 4 shows missing; no field is added to a specified value type (`NormalizedContent`, `OutputMeasurement`, `QualityResult` and the rest keep the specification's field lists) |
| `src/rovo/_crawl/run.py` | shared, own lines | `convert_fetched`'s `ConvertFetched` raise removed; its docstring |
| `src/rovo/_mirror/verify.py` | new | `verification_failures` and the `verify` pass (`VerifyPages`): reads the manifest, the page files and the index files, writes nothing |
| `src/rovo/_mirror/model.py` | shared, own lines | `VerificationReason`, `VerificationFailure` and `VerificationFinished` (added with the generated tests' skeleton); `MirrorPass.failures` typed as a list of `VerificationFailure` |
| `src/rovo/_mirror/links.py` | shared, own lines | `anchors_in` (a target file's anchors are its `{#id}` heading suffixes and the ids in its HTML, so a link to an anchor island resolves) and `broken_reason` (the broken-link check, shared by finalisation and verify, safe on a file that is not UTF-8) |
| `src/rovo/_mirror/finalise.py`, `src/rovo/_mirror/state.py` | shared, own lines | only the frontmatter reader and the pass request `verify.py` needs, if step 4 shows them missing |
| `src/rovo/_commands.py` | shared, own lines | `verify` (`Verify`, `RefuseVerify`, `ReportVerification`); the module docstring |
| `src/rovo/cli.py` | shared, own lines | the `rovo verify` command, importing only `rovo._commands` in its body |
| `scripts/wheel_smoke.py` | shared, own lines | `PACKAGE_FILES` gains `rovo/_mirror/verify.py` |
| `tests/test_convert.py` | shared, own lines (re-propagated) | the `Fidelity` contract tests (`test_contract_signature_Fidelity_extract`, `_normalize`, `_restore`, `_measure`), `test_body_shape` and `test_surface_exposure_PageConversion` extended with islands, tabs, reductions, flags and both catalogue profiles' selections (ledger notes, T09); one test per gate failing alone; `Determinism` over the new constructs |
| `tests/test_verify.py` | new | the `mirror` verify obligations of step 3 and one test per `VerificationReason`; no e2e module is named `test_verify.py` |
| `tests/test_mirror.py` | shared, own lines | `entity-optional.Page.version` (constructed) and `entity-optional.Page.locale` |
| `tests/test_report.py` | shared, own lines | `value-equality.GateFailure`, `entity-fields.GateFailure`, `value-equality.LowConfidencePage`, `entity-fields.LowConfidencePage`; `fail_on_low_quality` with each branch of `quality_failed` |
| `tests/test_commands.py` | shared, own lines | the `rovo` verify obligations of step 3 on the command |
| `tests/test_cli.py` | shared, own lines | `rovo verify` through `CliRunner` and the installed script; `rovo verify` loads neither httpx nor `rovo._crawl` |
| `tests/test_slice_boundaries.py` | shared, own lines (re-propagated) | `test_a_non_generic_profile_stops_conversion` becomes `test_a_devsite_page_converts` (ledger note, T09); `test_convert_branches_of_later_slices_stop` becomes `test_an_island_restores_and_the_inline_style_anchors` (ledger note, T09); `test_a_sitemap_filter_placeholder_stops` and the versioned case of `test_a_dry_run_report_and_a_versioned_path_stop` unchanged |
| `tests/test_regressions.py` | shared, own lines | only an earlier test the red run shows red because conversion now carries what it dropped or stopped on (ledger note naming its slice); one test per divergence weed finds |
| `tests/e2e/test_quality_sync.py` | new | the end-to-end scenarios (Acceptance criteria); no unit test is named `test_quality_sync.py` |
| `tests/fixtures/sites/quality/` | new | the generic-profile fixture site: `robots.txt`, `guide/start.html` (linking `islands.html`, `linked.html`, `gates.html` and `plain.html`), `guide/islands.html`, `guide/plain.html` (no `main`), `guide/gates.html` and `guide/linked.html` (Acceptance criteria); two-space indentation per `.editorconfig` |
| `tests/fixtures/sites/devsite/` | new | the `devsite`-shaped fixture site: `robots.txt`, `guide/start.html` (linking `tabs.html`), `guide/tabs.html` |
| `docs/reference/cli.md` | shared, own lines | the new `rovo verify` section (findings, tallies, exit codes); line 17's later commands lose `verify`; the exit-code table's 4 gains verify; `--profile`'s row says what `devsite` and `mslearn` select and that `mslearn` stops (Open points items 1 and 2) |
| `docs/reference/mirror.md` | shared, own lines | the "Page files" section: islands, tab panels, the declared reductions, the flags and when a page is low confidence; line 198's version-label sentence stays true |
| `docs/how-to/test-and-debug.md`, `docs/explanation/architecture.md` | shared, own lines | the wheel smoke's package-file count; `rovo._commands` and `rovo.cli` gain `verify` and `report` |
| `docs/reference/testing.md` | shared, own lines | `tests/e2e/test_quality_sync.py`, the two fixture sites, `tests/test_verify.py` |
| `docs/project/repository-map.md` | shared, own lines | the tree gains `test_quality_sync.py`, `test_verify.py`, `verify.py` and the two fixture sites |
| `docs/project/terminology.md` | shared, own lines | only if step 6's search shows "island", "tab panel" or "verify" missing or wrong |
| `docs/project/purpose-and-scope.md`, `README.md` | shared, own lines | only the sentences the step 6 search shows false (`rovo verify`, a profile that stopped) |
| `AGENTS.md` | shared, own lines | the "today" sentence (lines 10 to 13) gains `rovo verify`; the required phrases stay in always-visible text |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` Added entry: conversion quality and `rovo verify` |
| `tickets/README.md`, `tickets/T17-quality-gates.md` | ticket | index row, graph, slice bullet, this ticket |
| `tests/test_sitemaps.py` | shared, own lines (follow-up, re-propagated) | T13's `test_a_sitemap_filter_placeholder_stops_at_sitemap_admitted` becomes the placeholder-filling tests (ledger note, T13); the module docstring |
| `tests/test_version_label.py` | new (follow-up) | the version label in a page path and `Page.version` (MovePage and StoreNewPage guidance at `022eca4`) |
| `tests/test_slice_boundaries.py`, `tests/test_mirror.py`, `tests/test_convert.py`, `tests/test_regressions.py`, `tests/test_commands.py`, `tests/e2e/test_quality_sync.py` | shared, own lines (follow-up, re-propagated) | the placeholder and version-label stops become their behaviour (ledger notes, T13/T15 and T09); `entity-optional.Page.version` on a stored page; the whole-body cases become fallback cases and keep a page trafilatura finds nothing in; the union attributes; tallies sorted with no finding |
| `tests/test_lifecycle_regressions.py`, `tests/test_assign_path_reserved_segments.py` | shared, comments only (follow-up) | `mirror.allium` citations moved by `022eca4` |
| `tests/e2e/test_mslearn_sync.py` | new (follow-up) | an `mslearn` mirror synced through its sitemap index and filter, `api@beta.md`, and a page converted by the fallback extractor; no unit test is named `test_mslearn_sync.py` |
| `tests/fixtures/sites/mslearn/` | new (follow-up) | Learn-shaped `guide/start.html`, `guide/api.html` and `guide/hidden.html`, and `guide/loose.html` the selection misses; robots.txt and the sitemaps are written by the test, which needs the port |
| `pyproject.toml`, `uv.lock`, `docs/decisions/0005-dependency-policy.md` | shared, own lines (follow-up) | `trafilatura>=2.3.1,<3`, authorised by the maintainer for this follow-up, with decision 0005's note |
| `src/rovo/_crawl/sitemaps.py`, `src/rovo/_mirror/urls.py`, `src/rovo/_convert/fidelity.py` | shared, own lines (follow-up) | `sitemap_admitted` fills the placeholders; `assign_path` appends `@` and the label, `version_label` follows StoreNewPage; `extract` runs trafilatura (imported in `_fallback` alone) before the whole body; the two `NotInThisSlice` stops go |
| `src/rovo/_convert/model.py`, `src/rovo/_convert/profiles.py`, `src/rovo/_crawl/model.py`, `src/rovo/_crawl/run.py`, `src/rovo/_mirror/finalise.py`, `src/rovo/_mirror/indexes.py`, `src/rovo/_mirror/intake.py`, `src/rovo/_mirror/links.py`, `src/rovo/_mirror/model.py` | shared, comments only (follow-up) | specification citations moved by `022eca4` (`ai_tmp/T17/spec-answers/line-map.md`) |
| `docs/reference/cli.md`, `docs/reference/mirror.md`, `docs/project/purpose-and-scope.md` | shared, own lines (follow-up) | `mslearn` no longer stops; the version label in a page path; the fallback extractor; the union attributes |
| `docs/reference/configuration.md`, `docs/how-to/maintain-dependencies.md` | shared, own lines (follow-up) | the runtime dependencies gain trafilatura |
| `docs/reference/testing.md`, `docs/project/repository-map.md` | shared, own lines (follow-up) | `tests/e2e/test_mslearn_sync.py`, the `mslearn` fixture site and `tests/test_version_label.py` |
| `CHANGELOG.md` | shared, own lines (follow-up) | the T17 entry loses the `mslearn` stop; one Added entry for the follow-up and the trafilatura dependency |
| `.allium-loop/T17-quality-gates.json`, `.allium-loop/T17-quality-gates.witness.json` | gitignored | the loop ledger and the witness record; never committed |

`pyproject.toml`, `uv.lock`, `pytest.ini`, `.coveragerc`, `ruff.toml`, `mypy.ini`,
`Justfile`, `src/rovo/__init__.py`, `src/rovo/_exit.py`, `src/rovo/_config.py`,
`src/rovo/_report.py`, `src/rovo/_crawl/` but `run.py`, `src/rovo/_mirror/` but the files
the table names, `tests/e2e/conftest.py`, `tests/test_import_direction.py`,
`tests/test_sitemaps.py`, `docs/reference/quality-gates.md` (its topic is `just check`'s
gates, not conversion's), `docs/manifest.yml`, `docs/decisions/` and `docs/specs/` are read,
not changed, except where a follow-up row above names one. A file not in this table that turns out to need a change is added to the
table in the same change with its reason, or handed back if it is a decision record, a
specification or a dependency.

## Steps

This slice has no **Adversarial review** checkpoint (`tickets/CONVENTIONS.md` §14): the
witness of step 7 is its only independent check.

0. `just check` baseline on the untouched worktree at `7249e5a` plus this ticket, last
   line quoted, and `( set -o pipefail; { time just py-test tests/e2e -ra; } 2>&1 | tail -6 )`
   with its wall time. Scratch output goes in `ai_tmp/T17/`. Write `just plan-spec
   <module>` for each of `crawl`, `rovo`, `mirror` and `convert` to
   `ai_tmp/T17/plan-spec-<module>.txt`; run `ai_tmp/T17/uncovered.py` and
   `ai_tmp/T17/owned.py`, and confirm the 17 ids. While the worktree is at `7249e5a`,
   write `rg -n 'NotInThisSlice\(' src > ai_tmp/T17/notinthisslice-7249e5a.txt`. Create
   the ledger `.allium-loop/T17-quality-gates.json` against
   `allium-skill-reference/allium/schemas/ledger.schema.json`, shaped like T16's: `goal`
   `"T17-quality-gates"`, `mode` `"spec-first"`, `tick` 0, `specification_base`
   `9a253a4`, `obligation_source` the four files, and `open_questions` holding the six
   specification open questions verbatim (the three `convert.allium` ones marked "on
   T17's path", with this slice's interim), the T17 batched question's items (Open
   points) and the two carried T18 items, each marked OPEN. Read
   `.agents/skills/propagate/SKILL.md`, `.agents/skills/weed/SKILL.md`,
   `.agents/skills/witness/SKILL.md` and `.agents/skills/python-change/SKILL.md` before
   step 3.

1. **Conversion.** In `fidelity.py` and `profiles.py`, per the Context table and Facts:
   the selection table and its use by `extract` (content, chrome, breadcrumbs); in
   `normalize`, in this order, inactive tab panels made visible, tab expansion, the
   declared reductions, the construct families, the islands with their tokens, then the
   expected counts, the anchors and the heading ids in the profile's style; `restore`;
   `measure`'s normalisation flags and `fidelity_loss`; the body measurement made public
   and extended to parse the HTML blocks outside fences (Facts, Islands).
   Every gate value and weight comes from `CONFIG`, never a literal. Then `run.py`'s
   `ConvertFetched` raise goes.

2. **Verify.** `src/rovo/_mirror/verify.py` (`verification_failures`, the `verify`
   pass), `_commands.verify` and `rovo verify` in `cli.py`, per Facts. Each function
   returns `None` or an empty result when its guards do not hold.

3. **Tests first, from the obligations** (the `propagate` skill, spec-first). Write a
   failing test for each owned obligation below into the test file named, named
   `test_<obligation id with dots and hyphens as underscores>`, its docstring quoting the
   obligation's description from the plan-spec file. Each `rule_failure` test makes
   exactly one `requires` clause false. Generated tests satisfy EditorConfig
   (indentation in 4-space multiples in `*.py`, string literals included), ruff and
   mypy, since the gate stages them. Run `just py-test` and record the red run in
   `ai_tmp/T17/red.txt`, its summary line under `last_results.propagate` in the ledger.
   Record each generated, re-propagated or extended test file's SHA-256 under
   `generated_test_hashes` (`tests/test_cli.py` and `tests/e2e/test_quality_sync.py`
   included), and the reconciliation line (`N obligations, M covered, K uncovered`) over
   the owned set. A test changed after the red run is re-recorded: a new hash, `tick`
   incremented, a ledger note naming the test and why; never silently. An obligation a
   test cannot reach without a later slice's behaviour is not owned: move it to the
   hand-back notes with its reason rather than writing a vacuous test.

   Owned obligations, new in this slice (ids as `just plan-spec <module>` emits them at
   `9a253a4`; 17):

   - **`rovo`** (9). In `tests/test_report.py`: `value-equality.GateFailure`,
     `entity-fields.GateFailure`, `value-equality.LowConfidencePage`,
     `entity-fields.LowConfidencePage`. In `tests/test_commands.py`:
     `rule-success.Verify`, `rule-failure.Verify.1`, `rule-success.RefuseVerify`,
     `rule-failure.RefuseVerify.1`, `rule-success.ReportVerification`.
   - **`mirror`** (8). In `tests/test_verify.py`: `value-equality.VerificationFailure`,
     `entity-fields.VerificationFailure`, `enum-comparable.VerificationReason`,
     `rule-success.VerifyPages`, `rule-failure.VerifyPages.1`, `rule-failure.VerifyPages.2`.
     In `tests/test_mirror.py`: `entity-optional.Page.version` (a constructed record with
     a label and one without: no run stores a versioned page while `assign_path` stops)
     and `entity-optional.Page.locale` (a page stored under a pinned locale and one
     without).
   - **`crawl`** and **`convert`**: none new.

   Extended, not new (re-propagated in place, each re-hashed in this slice's ledger with a
   note naming its origin slice; T09's to T16's ledgers are never edited): in
   `tests/test_convert.py`, `test_contract_signature_Fidelity_extract` (each catalogue
   profile's selection, the whole-body branch), `_normalize` (each island kind, tab
   expansion both ways, each declared reduction, the inline style), `_restore` (each
   island restored, a lost token), `_measure` (each normalisation flag, `fidelity_loss`),
   `test_body_shape` (the anchor island) and `test_surface_exposure_PageConversion`; the
   two `tests/test_slice_boundaries.py` tests the Files touched table names, renamed
   there, the old name in the ledger note; every other earlier test the red run shows red
   because a page now converts, carries an island or emits a tab panel, each with only
   that expectation moved. Claim an earlier test "passes unedited" only where it does;
   the hand-back notes list every earlier test this slice edited.

   Guarantees and black boxes (no obligation id; hand-written), in `tests/test_convert.py`
   unless named: each `QualityGate` failing alone on a constructed body, its flag raised
   and the score one minus its weight (`FailedGatesAreFlagged`, `ScoreIsAFraction`);
   `UncarryableBecomesIsland` for each construct it names; `SanitizedMeansInert` (each
   kept attribute kept, every other dropped, `javascript:` and `vbscript:` targets and
   non-image `data:` URLs dropped, `script` and `style` subtrees dropped, the text kept,
   no blank line inside); `EveryTabPanelEmitted` (a code-only group as labelled fences,
   a mixed group as headings plus panels, source order, an inactive panel's text present);
   `DeclaredReductions`, one case each; `GatesMeasureExtractedContent` and `FlagsAreComplete`;
   `ProfilesAreTheOnlyPlatformKnowledge` (the same markup under each profile converts by
   its selection, whatever the URL's host); `Determinism` (each fixture page converted
   twice, byte-identical); `verification_failures` (`tests/test_verify.py`: each reason
   alone, a clean mirror with none, nothing at the root but managed files reported, a
   `.git/` directory and a `README.md` at the root not reported, the manifest and the
   files unchanged after a verify, no request on a fetcher); `ReportVerification`'s
   output and exit (`tests/test_commands.py`: the findings and tallies printed, 0 with no
   finding, 4 with any, a tally alone never 4); `fail_on_low_quality`
   (`tests/test_report.py`: set and unset, a touched low-confidence page, an untouched
   one, a broken link alone).

   Not owned, and why, for the hand-back notes: `surface-actor.MirrorCommands` and
   `surface-provides.MirrorCommands` (they list `fetch` and the owner options: T19, T20);
   `value-equality.BlockedUrl`, `entity-fields.BlockedUrl`, `rule-*.TallyBlockedUrl` and
   `rule-*.AnnounceTrip` (T18); `rule-*.RefuseMissingEngine`, `rule-*.RefuseOwnerTestingFetch`,
   `rule-*.RefuseMissingFetchTier`, `rule-*.FetchOneUrl` and `enum-comparable.Tier` (T19);
   `rule-*.RefuseInvalidOwnerRequest`, `rule-success.AnnounceOwnerWarning`,
   `entity-optional.CrawlReport.baseline_run_id`, `.preceding_run_id`,
   `.requested_owner_test`, `derived.Mirror.has_declared_owner`, `rule-*.SaveOwnership`
   and the `MirrorContents` surface obligations (its provides list
   `OperatorSavesOwnership`) (T20); every uncovered `crawl` obligation (block verdicts and
   the breaker, T18; the browser ladder, T19; owner testing, T20);
   `entity-fields.SyncRun`, `entity-relationship.Mirror.pages`,
   `entity-optional.Page.canonical_url`, `entity-optional.Page.frontmatter` and the
   `PageIntake` surface obligations (reachable since T09 to T14, assigned by no ticket, and
   not on this slice's path: carried to the last slice's review, named in the ledger).

4. **Conversion, verify and command.** Steps 1 and 2. Unit cases on HTML strings, on a
   mirror written in `tmp_path` and on `FakeFetcher` with `FixedClock`.
   `just py-test tests/test_convert.py tests/test_verify.py tests/test_mirror.py
   tests/test_report.py tests/test_commands.py tests/test_cli.py
   tests/test_slice_boundaries.py tests/test_regressions.py`, then `just py-lint`,
   `just py-typecheck`, `just coverage` and `just wheel-smoke`, quoting its `api` line
   and the package-file count (one more than at `7249e5a`).

5. **End to end.** The two fixture sites are committed under `tests/fixtures/sites/`
   and served with `serve_site("quality")` and `serve_site("devsite")`. Each page has a
   `<title>`, two-space indentation and a final newline; `robots.txt` is `User-agent: *`
   with no Crawl-delay and no `Sitemap:` line; there is no `llms.txt`. The scenarios are
   the Acceptance criteria's; those that fetch run `rovo._commands.sync` in process over
   a real `HttpxFetcher` with a `SteppingTimer` or `FixedClock`, which never sleep, and
   read requests off the server's log; `rovo init` and `rovo verify` run through
   `CliRunner`. `just py-test tests/e2e -ra`, its wall time quoted beside step 0's.

6. **Documents** (the `review-docs` skill). The pages of the Files touched table; find
   the sentences this slice makes false with
   `rg -n -i "verify|island|tab|profile|devsite|mslearn|quality|low.confidence|flag|later slice|not yet supported" -g '*.md' -g '!tickets/**' -g '!allium-skill-reference/**' -g '!docs/specs/**' -g '!docs/decisions/**'`;
   `CHANGELOG.md` `Unreleased` gains one Added entry, which names no profile supported.
   Keep the required phrases of `AGENTS.md` in always-visible text. `just check-docs`,
   `just check-agents`, and `just lint`, whose hooks include markdownlint over this
   ticket.

7. **Witness** (the `weed` and `witness` skills). Run `weed` over `convert`, `mirror` and
   `rovo` against the code, scoped to the owned and extended obligations, the Realised
   rules of the Context table and the guarantees; record its verdict under
   `last_results.weed` and fix any code divergence, each with a regression test in
   `tests/test_regressions.py`. A divergence weed attributes to the specification is not
   fixed: it joins the one batched needs-user question. Then run `witness`
   non-interactively: it writes `.allium-loop/T17-quality-gates.witness.json` per
   `witness-result.schema.json`. The verdict must be `PASS`; a `FAIL` routes back per the
   skill, and the hand-back notes record each round. A batched question still OPEN does
   not block `PASS` unless it blocks an owned obligation; none of items 1 to 3 does
   (Facts), and the witness escalates one that turns out to.

8. **Follow-up, only if the maintainer answers.** An answer to item 1 or 2 arrives as a
   specification change; then mark the item ANSWERED here and in the ledger, move the
   ledger's `specification_base`, write `just plan-spec <module>` to
   `ai_tmp/T17/followup/plan-spec-<module>.txt`, remove the raise the answer covers, give
   the newly reachable branches tests named after their ids (red first), add an
   end-to-end `mslearn` scenario once both are answered, re-propagate the tests the answer
   changes with ledger notes, move the specification line citations, and run steps 4 to 7
   again. An answer to item 3 that adds a dependency is a separate authorised change
   (decision 0005, `just lock`).

9. Hand-back notes; `status: done`; `just check` ending with
   `All checks passed and the worktree is unchanged.`, `git status --short` empty after
   the commit. Commit on the branch.
   **Authorisation required**: pushing and opening the pull request.

## Acceptance criteria

The end-to-end scenarios live in `tests/e2e/test_quality_sync.py`; each starts with
`rovo init <base>guide/start.html <tmp>/out` (with `--profile devsite` on the `devsite`
site), and every sync exits 0 unless stated.

- **End to end, islands** (`test_a_page_with_uncarryable_constructs_syncs_with_islands`):
  `guide/start.html` links `guide/islands.html`, which holds a table with a `rowspan`, a
  table with no header row, a definition list whose definition holds a paragraph and a
  list, a `details` element holding a list, a MathML formula with no TeX annotation, a
  `<span id="note">` in a paragraph, and an `onclick` and a `style` attribute on table
  cells, and a fenced code block in a named language; `guide/linked.html` links
  `islands.html#note`. The sync exits 0, where at
  `7249e5a` it stopped at `UncarryableBecomesIsland`. `pages/<host>/guide/islands.md`
  holds each table as one HTML block with its `rowspan` and without `onclick` or `style`,
  the definition list and the formula as HTML blocks, `<details>` with its list as
  Markdown between blank lines, and `<a id="note"></a>`; its frontmatter's
  `quality_flags` holds `html_table_kept` and not `fidelity_loss`, and `low_confidence`
  is false. `linked.md` links `islands.md#note`, and the report's `broken_links` is empty.
- **End to end, every gate and flag** (`test_a_lossy_page_is_flagged_and_reported`):
  `guide/gates.html` holds two code blocks, one naming no language (a rate of 0.5, under
  `lang_rate_gate`), and an interactive embed (`iframe`). Its frontmatter's
  `quality_flags` holds `code_lang_rate` and `interactive_omitted`, `low_confidence` is
  true (a failed gate), its `quality_score` is one minus `weight_code_lang_rate` read from
  `CONFIG`, the embed's URL is in the body as a one-line note, and the report's
  `quality_summary.gate_failures` counts `code_lang_rate` on one page.
- **End to end, `fail_on_low_quality`** (`test_fail_on_low_quality_exits_4_for_a_touched_low_confidence_page`):
  `guide/plain.html` has no `main` or `article`. A sync exits 0 and its report's
  `low_confidence_pages` holds, among its rows (`gates.md` is low confidence too), one for
  `plain.md` with `whole_body_extracted` and `touched_this_run: true`; a second sync with `--set quality.fail_on_low_quality=true`
  exits 4 with `exit_code: "quality"` and the same row. The broken-link branch of
  `quality_failed` (no low-confidence page, one broken link) is unit-tested in
  `tests/test_report.py`: no committed fixture site yields a broken relative link from a
  sync.
- **End to end, `devsite`** (`test_a_devsite_page_emits_every_tab_panel`): the `devsite`
  site's `guide/tabs.html` holds a DevSite header, a left navigation and a footer around
  the article body, a breadcrumb list, a `devsite-selector` with three code panels
  (Python, Java, shell; the last two inactive), a `devsite-selector` with two prose
  panels, and a note callout. The sync exits 0: `tabs.md` holds three labelled fences in
  source order, then each prose panel under a heading naming its label, the callout as a
  GFM alert, none of the header, navigation or footer text; its frontmatter has `method:
  "profile"`, `profile: "devsite"`, the breadcrumbs and no `tabs_expanded` flag.
- **End to end, `rovo verify`** (`test_rovo_verify_reports_drift_offline`): after a sync
  of the quality site, `rovo verify <out>` exits 0 with nothing on standard output. Then
  `islands.md`'s body is edited (one fenced block deleted), `gates.md` is deleted,
  `pages/<host>/guide/stray.md` is written, a link in `start.md` is pointed at
  `missing.md`, `index.md` gains a line and a `README.md` is written at the root:
  `rovo verify <out>` exits 4 and prints, among its lines, a `digest_mismatch` and a
  `quality_drift` line for `islands.md`, `missing_file` for `gates.md`, `unmanaged_file`
  for `stray.md`, `digest_mismatch` and `broken_link` for `start.md` and `index_stale`
  for `index.md`, and no line naming `README.md`;
  the server's log gains no request and `.rovo/` and `crawl-report.json` are
  byte-identical. On a directory with no mirror it exits 2 with nothing on standard
  output.
- **End to end, earlier scenarios**: `tests/e2e/test_init_sync.py`,
  `tests/e2e/test_follow_links.py`, `tests/e2e/test_index_files.py`,
  `tests/e2e/test_polite_sync.py`, `tests/e2e/test_discovery_sync.py`,
  `tests/e2e/test_second_sync.py`, `tests/e2e/test_lifecycle_sync.py`,
  `tests/e2e/test_errors_report_sync.py` and `tests/e2e/test_harness.py` pass unedited,
  unless the ledger names an edit and why.
- Every owned obligation in step 3 has a test named after it, red before the code and
  green after (`ai_tmp/T17/red.txt` and the final run); the reconciliation line shows
  zero uncovered; every extended test is re-hashed in the ledger with its note; every
  obligation dropped from the owned list is in the hand-back notes with its reason.
- No test this slice adds or edits sleeps for real; the suite's one real wait is T12's
  installed-script Crawl-delay scenario (`tests/e2e/test_polite_sync.py`), kept by
  design: `rg -n 'time\.sleep\(' tests; test $? -eq 1`,
  `test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py`, and
  `rg -n 'subprocess' tests/e2e/test_quality_sync.py; test $? -eq 1`.
- The `NotInThisSlice` raises in `src/` carry the `rule=` names of
  `ai_tmp/T17/notinthisslice-7249e5a.txt` less one `ConvertFetched`, two
  `UncarryableBecomesIsland` and one `BodyShape`, as many of each
  (`ai_tmp/T17/rules-expected.txt` and `ai_tmp/T17/rules-after.txt`, written by the
  Verification block, do not differ); `sitemap_admitted` and `assign_path` are among
  them.
- Every fixture page the end-to-end scenarios serve is committed under
  `tests/fixtures/sites/quality/` or `tests/fixtures/sites/devsite/`: `rg -n
  'write_text' tests/e2e/test_quality_sync.py` names no `.html` file.
- `rovo verify --help` runs through the installed script; `rovo verify`, `rovo report`
  and `rovo index` load neither httpx nor `rovo._crawl`.
- `.allium-loop/T17-quality-gates.witness.json` exists with `"verdict": "PASS"`, and the
  ledger validates against `ledger.schema.json` with the T17 batched question's items,
  the three `convert.allium` open questions and the carried T18 items OPEN unless the
  maintainer answered them.
- `just check-specs` and `just analyse-specs` pass with `docs/specs/` unchanged since
  `9a253a4` (`git diff --stat 9a253a4 -- docs/specs` empty).
- `import rovo` loads no module outside the standard library and `rovo`; `__all__` is
  `["__version__"]`; `just wheel-smoke` passes with one package file more.
- `just coverage` stays at or above the floor of 95.
- `just check-docs` and `just check-agents` pass; `docs/reference/cli.md` describes
  `rovo verify` and `docs/reference/mirror.md` islands, tab panels and the flags; no page
  calls a profile supported.
- `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty after the commit.

## Verification

```sh
just plan-spec crawl > ai_tmp/T17/plan-spec-crawl.txt
just plan-spec rovo > ai_tmp/T17/plan-spec-rovo.txt
just plan-spec mirror > ai_tmp/T17/plan-spec-mirror.txt
just plan-spec convert > ai_tmp/T17/plan-spec-convert.txt
git diff --stat 9a253a4 -- docs/specs
just py-test tests/test_convert.py tests/test_verify.py tests/test_mirror.py tests/test_report.py tests/test_commands.py tests/test_cli.py tests/test_slice_boundaries.py tests/test_regressions.py -ra
( set -o pipefail; { time just py-test tests/e2e -ra; } 2>&1 | tail -6 )
just py-lint
just py-typecheck
just coverage
just wheel-smoke
uv run --frozen python -I -c "import rovo, sys; print(sorted(m for m in sys.modules if not m.startswith(('rovo', '_')) and m not in sys.stdlib_module_names))"
rg -o 'rule="[^"]+"' -N --no-filename ai_tmp/T17/notinthisslice-7249e5a.txt | rg -v '"(ConvertFetched|UncarryableBecomesIsland|BodyShape)"' | sort > ai_tmp/T17/rules-expected.txt
rg -o 'rule="[^"]+"' -N --no-filename src | sort > ai_tmp/T17/rules-after.txt
diff ai_tmp/T17/rules-expected.txt ai_tmp/T17/rules-after.txt  # prints nothing
uv run --frozen rovo verify --help
rg -n 'time\.sleep\(' tests; test $? -eq 1  # only "no match" passes
test "$(rg -l 'SystemTimer' tests)" = tests/test_pace.py
rg -n 'subprocess' tests/e2e/test_quality_sync.py; test $? -eq 1  # only "no match" passes
rg -n -i 'supported' CHANGELOG.md docs/reference/cli.md docs/reference/mirror.md
just lint  # markdownlint over this ticket among the hooks
just check-specs
just analyse-specs
just check-docs
just check-agents
just check
git status --short
```

The `supported` search is read, not asserted: each hit must not call a profile
supported. CI evidence exists only after the push, which is separately authorised; it
goes in the closing pull request's notes.

## Hand-back notes

To be written by the executing agent: the baseline and the e2e wall time before and
after; the profile selections, the islands, the tab expansion, the reductions and verify
as built, and any departure from Facts and steps 1 and 2; the red run and the
reconciliation line; every extended or re-propagated test, its origin slice and its new
hash; every obligation dropped from the owned list and why; the weed verdict and the
witness verdict, each round; the one batched needs-user question with every gap found
while planning, implementing or in weed, and the maintainer's answer if one arrived; the
verification output, each headed by its commit.

## Open points

- **The T17 batched needs-user question: ANSWERED** (the maintainer, 2026-11-05;
  specification commit `022eca4`, `ai_tmp/T17/spec-answers/answers.md`). The follow-up
  conforms to each answer; every line number in this item is at `022eca4`.
  1. **`mslearn`'s `sitemap_include` placeholders: ANSWERED, wildcards and the pinned
     locale.** `{section}` matches as `*` does; `{locale}` is the scope's pinned locale,
     else any one of the scope's `locale_codes`; with neither, a `{locale}` pattern admits
     nothing (FetchSitemap guidance, `crawl.allium` 1057 to 1066). The stop
     `NotInThisSlice("sitemap_admitted")` goes. Tests:
     `tests/test_sitemaps.py::test_a_sitemap_filter_placeholder_is_filled`,
     `::test_a_locale_placeholder_with_no_locale_admits_nothing`,
     `::test_a_section_placeholder_matches_as_a_star_does`,
     `tests/test_slice_boundaries.py::test_a_sitemap_filter_placeholder_is_filled` and
     `tests/e2e/test_mslearn_sync.py`.
  2. **The version label: ANSWERED, a suffix, only when explicit.** An identity carrying
     the profile's `version_param` gets `@` and its label after the rewritten last
     segment, before `.md` (`foo@beta.md`, `index@x.md`, `README@x.md`, `con-@x.md`); the
     label is the `version_map` value, else the raw value, sanitised; `version_default` is
     only the recorded `Page.version` of an identity without the parameter and never
     touches the path (MovePage guidance, `mirror.allium` 678 to 702; StoreNewPage, 827
     to 832). The stop `NotInThisSlice("assign_path")` goes. Tests:
     `tests/test_version_label.py`,
     `tests/test_slice_boundaries.py::test_a_versioned_path_carries_its_label`,
     `tests/test_mirror.py::test_entity_optional_Page_version` and
     `tests/e2e/test_mslearn_sync.py`.
  3. **The fallback extractor: ANSWERED, trafilatura** (`trafilatura>=2.3.1,<3`, the
     maintainer authorised the dependency for this follow-up). It runs only when the
     profile's selection matches nothing, before the whole body; its output is method
     `fallback`, flagged `extractor_fallback` (ExtractNeverEmptyHanded, `convert.allium`
     186 to 198). Tests: `tests/test_convert.py::test_ExtractNeverEmptyHanded`, the
     re-propagated extract, measure, QualityFlag and ProfilesAreTheOnlyPlatformKnowledge
     tests, `tests/test_regressions.py::test_whole_body_extraction_strips_the_profiles_chrome`,
     `tests/e2e/test_quality_sync.py::test_fail_on_low_quality_exits_4_for_a_touched_low_confidence_page`
     and `tests/e2e/test_mslearn_sync.py`.
  4. **Gate tallies with no finding: ANSWERED, always printed**, after the findings,
     sorted by gate, never the exit code (ReportVerification guidance, `rovo.allium` 811
     to 817). The interim already did this. Test:
     `tests/test_commands.py::test_verify_tallies_are_always_printed_sorted_by_gate`.
  5. **Island attributes: ANSWERED, the union.** A custom element keeps the sanitiser's
     attributes plus `class`, `data-tab`, `data-language` and `language`; an image keeps
     the sanitiser's attributes (`src`, `alt`, `title` and `id` among them) and no other
     (DeclaredReductions and SanitizedMeansInert, `convert.allium` 214 to 235). The
     interim already did this. Test:
     `tests/test_convert.py::test_DeclaredReductions[custom-element-attributes]`.
- **Veto-able choices the follow-up records, not OPEN.** Two are the spec author's: an
  existing `.md` is stripped before the label goes on (`README.md?view=x` gives
  `README@x.md`), and an empty raw value gives `foo@.md` (`Page.version` is then the empty
  label). One is a reading of "matches as `*` does": `pattern_matches` is `fnmatch`, whose
  `*` crosses `/`, so `{section}` does too.
- **The T17 follow-up batched needs-user question: OPEN** (found by propagate, follow-up
  tick 1). It blocks no owned obligation.
  1. **Which spelling of the raw version value is sanitised.** An identity's query is
     URL-encoded (`normalise_url`), so a raw value such as `a/b` or `é` is `a%2Fb` or
     `%C3%A9` in the identity and `a/b` or `é` decoded, and sanitising gives `a-2Fb` or
     `-C3-A9` from the first and `a-b` or `-` from the second (MovePage guidance,
     `mirror.allium` 688 to 702, says "the raw value"; segments are never decoded). Which
     is it? Interim: the decoded value, as `version_label` reads it today; no test pins
     either spelling (`tests/test_version_label.py` uses values both spellings agree on).
- **Carried, realised in this slice** (from `.allium-loop/T16-errors-report.json`): a
  non-heading `id` anchor no longer stops the sync; `UncarryableBecomesIsland` already
  specifies it as an island, so it needs no answer. Mark it ANSWERED-BY-SPEC in this
  slice's ledger, citing `convert.allium` 196 to 201.
- **Carried, OPEN, to T18** (from `.allium-loop/T16-errors-report.json`): a retired host's
  remaining discovery is still requested, and whether a host retirement ranks exit 3 or 1.
- **The specification's open questions.** The three `convert.allium` ones (473 to 475)
  are on this slice's path and stay open. Their interims, as built: (1) `tabs_expanded`
  compares `tab_panels_emitted` with `expected.tab_panels`, which cannot fail by
  construction; (2) only an inactive tab panel's hidden marker is removed, no other hidden
  content (Facts); (3) the slice tests each construct family the question names with
  hand-written unit cases and fixture pages, which are not the fidelity corpus, and no
  profile is called supported. The three `crawl.allium` ones (2421 to 2423) are not on
  this slice's path.
- **Unowned residue.** `entity-fields.SyncRun`, `entity-relationship.Mirror.pages`,
  `entity-optional.Page.canonical_url`, `entity-optional.Page.frontmatter` and the
  `PageIntake` surface obligations are reachable since earlier slices but no ticket
  assigned them; they are not on this slice's path. The ledger names them so the last
  slice's review owns or assigns them.
- **`NotInThisSlice`.** A development guard, not product behaviour: each later slice
  removes the raises it implements, and the last slice's review confirms none is left.
  This slice removes four and keeps the two the specification itself leaves uncovered
  (Acceptance criteria).
