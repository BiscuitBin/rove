---
id: T11
title: "Indexes: every finalisation writes index.md, the directory indexes, llms.txt, index.jsonl and links.jsonl, and rovo index rebuilds them"
status: open
depends_on: [T10]
parallel_with: []
branch: full-final-prototype
estimated_size: L
---

# T11: Indexes: every finalisation writes index.md, the directory indexes, llms.txt, index.jsonl and links.jsonl, and rovo index rebuilds them

## Context

T09 (`fd1b423`) is slice 1, the tracer bullet, and T10 (`9fd11fd`) is slice 2: `rovo sync`
fetches the seed pages and the pages they link to within the crawl scope, publishes
each at `pages/<host>/<path>`, resolves every written page's links against the whole
mirror (`Mirror.links`, saved as the manifest's `links` rows), rewrites a link to a
written page as a relative path between page files and writes `crawl-report.json`. They
fixed every pattern this slice follows: the private subpackages `rovo._convert`,
`rovo._mirror` and `rovo._crawl` with `rovo._config`, `rovo._report` and
`rovo._commands` above them (import direction enforced by
`tests/test_import_direction.py`), the `Fetcher` and `Clock` seams with `tests/fakes.py`,
obligation-named tests (`test_<obligation id>`), the end-to-end harness `serve_site` in
`tests/e2e/conftest.py` (a fixture name or a `Path` to a directory), the state files of
`docs/reference/mirror.md`, and the development guard `rovo._unfinished.NotInThisSlice`.
Read `tickets/T09-tracer-init-sync-one-page.md`, `tickets/T10-links-and-scope.md`,
`docs/reference/mirror.md` and `src/rovo/_unfinished.py` before starting.

This is slice 3 of T08 to T20, run in this worktree on `full-final-prototype`. Until now
the finalise pass ends at T09's named deviation: `finalise` (`src/rovo/_mirror/finalise.py`
227 to 247) completes the pass itself after `FinishLinkPass` and writes no index file
(its docstring, line 233: "BuildIndexes completes the pass without them"), and
`Mirror.index` is typed `None` (`src/rovo/_mirror/model.py` 260). That deviation is a
docstring and a test assertion (`tests/test_mirror.py` 755 to 756, "IndexesWritten is
raised without writing an index file in this slice"), not a `NotInThisSlice` raise, so
this slice removes no raise. It makes every finalisation build the indexes from the
written pages and their links and write them at the mirror's root, and adds the
command `rovo index OUT_DIR`, which rebuilds them offline from the manifest.

### The specified path, and what this slice does with each rule on it

The task named the rules to realise; the trigger chain crosses more. Each rule the chain
crosses is classified here, so that no rule is skipped silently. Line numbers are at the
specification base `32f2210` (`git diff --stat 32f2210 9fd11fd -- docs/specs` is empty).

| Class | Rules |
| --- | --- |
| **Realised** (every branch reachable in this slice, or constructible on unit inputs where noted) | `mirror.allium`: `BuildIndexes` (1206: `index_entries`, `link_index_entries`, `directory_indexes_for(entries, config.hierarchical_index_threshold)`, `llms_summary`, both the create and the update branch of `Index`, `IndexFilesWritten`, the pass completed, `IndexesWritten`; the whole of its guidance, including the files under `_indexes/<host>/`, stale ones deleted, and a file written only when its text would differ); `RebuildIndexes` (1196: an `index` pass raises `IndexBuildDue`); the values `IndexEntry` (184), `LinkIndexEntry` (206) and `DirectoryIndex` (213 to 225: path lower-cased, directories differing only in case sharing one index, no index for a host's top level); the entity `Index` (467 to 477) and `Mirror.index` (290); `config.hierarchical_index_threshold` and `config.llms_txt_cap` (494, 495), read from `rovo._mirror.model.CONFIG`, never a literal; the `MirrorContents` guarantee `DeterministicIndexes` (1437), and the index half of `RelativeLinksOnly` (1420: "a generated index links down into pages/"). `rovo.allium`: `RebuildIndex` (776), `RefuseRebuildIndex` (783), `FinishIndexCommand` (790), and the index line of `MirrorCommands`' `VerifyIndexReportExitCodes` (914: "index: 0 when rebuilt, 2 when a page file cannot be read"). |
| **Traversed, nothing new to do** | `RequestPass` (528): unchanged, now also creating an `index` pass with a null `run_id`. `FinishLinkPass` (1176): unchanged; the `IndexBuildDue` it raises now reaches `BuildIndexes`. `FinaliseRunReport` (`rovo.allium` 657) and `RankAndWriteReport`: unchanged, now after the index files are written. `PublishPage` (1143): unchanged; the index files are not page files. `FixedLayout` (1453): the managed root files `index.md`, `index.jsonl`, `links.jsonl` and `llms.txt` and the `_indexes/` namespace now exist; `assign_path` already keeps every page path out of them (T09, `1be7354`). |
| **Outside this slice; reaching one still stops the run or is absent** | `VerifyPages` (1267) and its `index_stale` and generated-index `broken_link` findings (the verify slice); `UnchangedRunIsStable` (1430): a second sync still stops at `DisposeFetch` (the incremental slice), so only the index half of stability (`DeterministicIndexes`) is tested here; the `MirrorContents` surface obligations (`surface-actor`, `surface-exposure`, `surface-provides`): the surface also exposes `removed_pages` and provides `OperatorSavesOwnership` (the lifecycle and ownership slices); `MirrorCommands`' `surface-provides` (`verify`, `report` and `fetch` are later slices'). Every `NotInThisSlice` raise T09 and T10 left stays, unchanged. |

### Facts a later reader would otherwise rediscover

- **The task's capability sentence is narrower than `BuildIndexes`.** It names `index.md`,
  the directory indexes, `llms.txt` and `index.jsonl`; `BuildIndexes` also sets
  `index.link_entries` and its guidance writes `links.jsonl`. T09 (Context table,
  `BuildIndexes` row) and T10 (Non-goals) both handed `links.jsonl` and `LinkIndexEntry`
  to "the indexes slice", and no later slice owns them, so this slice writes
  `links.jsonl` too. It needs nothing new: the kinds are the manifest's `links` rows of
  T10.
- **The index pass reads no page body.** `FinishIndexCommand`'s guidance (`rovo.allium`
  796 to 797): "The indexes are rebuilt offline from the manifest and the page files;
  links are not re-resolved." Every `IndexEntry` field is a `Page` field or a count over
  `Mirror.links`, all held in `.rovo/manifest.json`; the page files are only checked by
  `page_files_readable` (every written page's file exists and decodes as UTF-8, the
  `rovo.allium` black box, line 50). An existing mirror (`exists target`) is one whose
  manifest loads: `load_mirror` raising `ManifestError` exits usage, as `rovo sync`
  does. The `index` command writes the index files only: no manifest, frontier, runs or
  report save, and it builds no `Clock`, since no index carries wall-clock time.
- **`Index` is not persisted.** The spec regenerates it "from scratch by every pass that
  writes them" (`mirror.allium` 469 to 470); it lives in memory on `Mirror.index` for the
  pass and on disk only as the index files. `docs/reference/mirror.md` says so.
- **`word_count` has no source yet.** `IndexEntry.word_count` (199) is not a `Page` field,
  and `convert.allium` 40 names `word_count` as a black box "where the comments name
  them", which no comment does. The measured `QualityResult.output.words`
  (`convert.allium` 100, `src/rovo/_convert/model.py` 120) is the body's word list outside
  code; this slice uses its length as the interim value and carries the gap in the one
  batched question (Open points).
- **Paths and links in an index.** Every path an index records is mirror-relative
  (`pages/<host>/...`), and every link is relative to the index file
  (`BuildIndexes`' guidance, 1250 to 1254): `index.md` and `llms.txt` link down into
  `pages/` and `_indexes/`, `_indexes/<host>/api.md` links up and back down
  (`../../pages/<host>/api/ref.md`) and across to its nearest indexed descendants
  (`api/v2.md`). The links reuse T10's `relative_path` (`src/rovo/_mirror/links.py`).
- **The directory-index threshold in tests.** `hierarchical_index_threshold` is 200 and
  `llms_txt_cap` 2000, `mirror.allium` config values, not `rovo.toml` keys. Unit tests pass
  a small threshold and cap through the functions' parameters
  (`directory_indexes_for(entries, threshold)` is the spec's own signature); the code
  calls them with `CONFIG`'s values, and no test patches `CONFIG`. The end-to-end
  scenario that produces a real `_indexes/<host>/<dir>.md` serves a site generated into
  `tmp_path` with `CONFIG.hierarchical_index_threshold + 1` pages in one directory,
  rather than committing 201 fixture files. No budget stops that crawl early: `max_pages`
  is 5000 fetch attempts per run and `max_bytes` 2 GiB (`crawl.allium` 536 to 537).
- **Case-differing directories.** Two directories that differ only in case cannot be
  served from one macOS checkout (a case-insensitive file system), so the shared
  lower-case directory index is proven on unit inputs only.
- **The obligation source.** `just plan-spec <module>` (its echo line goes to standard
  error) over the committed `docs/specs/<module>.allium` at `32f2210`, written to
  `ai_tmp/T11/plan-spec-<module>.txt`: mirror 200, rovo 165, crawl 358, convert 47
  obligations. The copies are scratch, regenerated by step 0.

## Goal

From a clean checkout, against the served fixture site `indexes`, `rovo init` then
`rovo sync` exits 0 and leaves at the mirror's root `index.md` (one heading for the host,
then one per top-level directory, linking every page and every directory index),
`index.jsonl` (one `IndexEntry` per written page, sorted by path), `links.jsonl` (one
`LinkIndexEntry` per cited identity, sorted by URL) and `llms.txt` (the start page's
description as its summary, every page listed), all LF-terminated UTF-8 with every link
relative to the index file. Against a generated site with more than
`hierarchical_index_threshold` pages in one directory, `_indexes/<host>/<dir>.md` exists,
is linked from `index.md` and links each of its pages. `rovo index OUT_DIR` rebuilds the
same files byte for byte and exits 0, deletes a stale file under `_indexes/`, rewrites no
file whose text is unchanged, and exits 2 writing nothing when a page file is missing or
the directory holds no mirror. Every owned obligation listed under Steps has a test
named after its id; `just check` is green; the Allium loop's witness record says `PASS`.

## Non-goals

- No `verify` command, no `index_stale` or generated-index `broken_link` finding (the
  verify slice), though the index text is a pure function `verify` will reuse.
- No second sync: a known page still stops `DisposeFetch` (the incremental slice), so
  `UnchangedRunIsStable` is not tested here; `DeterministicIndexes` is, through
  `rovo index`.
- No page lifecycle: no removed page, no `_removed/`; `index_entries` takes written pages
  only, which is all a mirror holds in this slice.
- No `MirrorContents` surface obligations and no `MirrorCommands` `surface-provides`
  (Context table).
- No discovery: the site's own `llms.txt` is never read (`ReadLlmsTxt`, `llms_txt_depth`
  and `llms_txt_priority` are the discovery slice's); this slice only writes the mirror's.
- No new `rovo.toml` key, no environment or flag layer, no option on `rovo index` beyond
  `OUT_DIR`.
- No `NotInThisSlice` raise added or removed.
- No specification change: `docs/specs/` is read, not edited. The five `open question`
  blocks stay open (`crawl.allium` 1975 and 1976, `convert.allium` 473 to 475); none is
  on this slice's path. A specification gap found while planning, implementing, in weed
  or in review is never resolved in code or in the specification: every such gap joins
  the one batched needs-user question (Open points) and the ledger's `open_questions`.
- No change to the public API: `__all__` stays `["__version__"]`, so
  `docs/reference/api.md` does not move. No decision record changes.
- No adversarial review checkpoint in this slice.
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `src/rovo/_mirror/model.py` | shared, own lines | the values `IndexEntry`, `LinkIndexEntry`, `DirectoryIndex` and the entity `Index`; `Mirror.index` typed as an optional `Index`; the `IndexFilesWritten`, `IndexBuildDue` and `IndexesWritten` triggers |
| `src/rovo/_mirror/indexes.py` | new | `index_entries`, `link_index_entries`, `directory_indexes_for`, `llms_summary`, the pure renderers of `index.md`, `_indexes/<host>/<dir>.md`, `llms.txt`, `index.jsonl` and `links.jsonl`, `rebuild_indexes` (`RebuildIndexes`), `build_indexes` (`BuildIndexes`, writing each file only when its text differs and deleting stale files under `_indexes/`), `page_files_readable`, `index_pass` (`RequestPass` to `IndexesWritten` for an `index` pass) |
| `src/rovo/_mirror/finalise.py` | shared, own lines | `finalise` hands `FinishLinkPass`'s `IndexBuildDue` to `build_indexes`, which completes the pass; the docstring loses the deviation; `Finalisation` carries `IndexesWritten` |
| `src/rovo/_mirror/state.py` | shared, own lines | only if a helper to delete a file atomically under `_indexes/` is needed beside `write_text`; the manifest's shape unchanged |
| `src/rovo/_mirror/__init__.py` | shared, own lines | the docstring names the indexes |
| `src/rovo/_commands.py` | shared, own lines | `index(out_dir)`: `RefuseRebuildIndex`, `RebuildIndex`, `FinishIndexCommand`; `_start_sync` reads `IndexesWritten` from the finalisation; `_config`, `_crawl` and `_report` imported inside `init`'s and `sync`'s bodies, so importing the module loads no crawl (step 6) |
| `src/rovo/_exit.py` | new (added in implement) | `ExitCode`, moved from `_report.py` into a leaf importing no rovo module: `rovo index` must load neither httpx nor `rovo._crawl` (step 6), yet `_report` and `_config` import `rovo._crawl.model` on import |
| `src/rovo/_report.py` | shared, own lines (added in implement) | `ExitCode` re-exported from `rovo._exit`, so every caller keeps importing it from here |
| `src/rovo/cli.py` | shared, own lines | the `index` command, `OUT_DIR` its one argument, importing `rovo._commands` inside its body only |
| `scripts/wheel_smoke.py` | shared, own lines | `PACKAGE_FILES` gains `rovo/_mirror/indexes.py` and `rovo/_exit.py`; the verdict line's count follows |
| `tests/test_mirror.py`, `tests/test_commands.py` | shared, own lines | the owned obligations (step 3); the extended test re-propagated; `test_rule_success_StartSync` lists page files under `pages/` only (propagate tick 2) |
| `tests/test_indexes.py` | new | the hand-written tests: `DeterministicIndexes`, the index half of `RelativeLinksOnly`, directory indexes on unit inputs (threshold boundary, nesting, nearest indexed descendants skipping an unindexed directory, case-differing directories sharing one lower-case index, no index for a host's top level), `llms.txt` past the cap, the summary's start-page and first-by-path branches, a file written only when its text differs, a stale `_indexes/` file deleted, two hosts in `index.md` |
| `tests/test_cli.py` | shared, own lines | `index` joins `test_mirror_commands_have_help` and `test_mirror_commands_without_arguments_are_usage_errors`; `rovo index` through `CliRunner` exits 0, and 2 without a mirror |
| `tests/e2e/test_init_sync.py`, `tests/test_unplaceable_candidate.py` | shared, own lines (added in propagate tick 2) | the helpers `markdown_files` and `page_files`, and the robots-disallow assertion, list page files under `pages/` rather than every `.md` in the mirror, since `BuildIndexes` writes the root `index.md`; `tests/e2e/test_follow_links.py` and `tests/test_page_namespace.py` use these helpers and are not edited |
| `tests/test_regressions.py` | shared, own lines | one test per divergence weed or review finds |
| `tests/e2e/test_index_files.py` | new | the end-to-end scenarios (Acceptance criteria), with the generator of the large-directory site; not `test_indexes.py`, a basename `tests/test_indexes.py` takes |
| `tests/fixtures/sites/indexes/guide/start.html`, `tests/fixtures/sites/indexes/guide/b.html`, `tests/fixtures/sites/indexes/guide/api/ref.html`, `tests/fixtures/sites/indexes/guide/api/v2/x.html` | new | the `indexes` site (step 7) |
| `docs/reference/mirror.md` | shared, own lines | the tree and a section per index file: what it holds, its order, its exact text, its links; `_indexes/`; `Index` not persisted |
| `docs/reference/cli.md` | shared, own lines | the intro sentence ("the later commands (`verify`, `index`, ...)"); a `rovo index` section with its usage and exit codes; `rovo sync` writes the indexes |
| `docs/reference/testing.md` | shared, own lines | the new fixture site, the generated large-directory site, `tests/test_indexes.py`, the package-file count |
| `docs/how-to/test-and-debug.md` | shared, own lines | the package-file count |
| `docs/explanation/architecture.md` | shared, own lines | the indexes in `_mirror`'s part of the private modules' row |
| `docs/project/repository-map.md` | shared, own lines | the tree gains `indexes.py` and the fixture site |
| `AGENTS.md` | shared, own lines | line 10's "today `rovo init` and `rovo sync` mirror the seed pages" becomes what the commands now do, `rovo index` included |
| `docs/README.md`, `docs/project/purpose-and-scope.md`, `docs/how-to/install-and-run.md`, `README.md` | shared, own lines | each sentence this slice makes false (no index, `index` a later command), and only those |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` entry |
| `tickets/README.md`, `tickets/T11-indexes.md` | ticket | index row, graph, slice bullet, this ticket |
| `.allium-loop/T11-indexes.json`, `.allium-loop/T11-indexes.witness.json` | gitignored | the loop ledger and the witness record; never committed |

`pyproject.toml`, `uv.lock`, `pytest.ini`, `.coveragerc`, `ruff.toml`, `mypy.ini`,
`Justfile`, `src/rovo/__init__.py` and `docs/specs/` are read, not changed. A file not in
this table that turns out to need a change is added to the table in the same change with
its reason, or handed back if it is a decision record or a specification.

## Steps

0. `just check` baseline on the untouched worktree at `9fd11fd`, last line quoted.
   Scratch output goes in `ai_tmp/T11/`. Write `just plan-spec <module>` for each of
   `mirror`, `rovo`, `crawl` and `convert` to `ai_tmp/T11/plan-spec-<module>.txt`, and
   the owned set of step 3 to `ai_tmp/T11/owned.json`. Create the ledger
   `.allium-loop/T11-indexes.json` against
   `allium-skill-reference/allium/schemas/ledger.schema.json`, shaped like T10's: `goal`
   `"T11-indexes"`, `mode` `"spec-first"`, `tick` 0, `specification_base` `"32f2210"`,
   `obligation_source` the four files, and `open_questions` holding the five
   specification open questions verbatim and the batched question of the Open points.
   Read `.agents/skills/propagate/SKILL.md`, `.agents/skills/weed/SKILL.md`,
   `.agents/skills/witness/SKILL.md` and `.agents/skills/python-change/SKILL.md` before
   step 3.

1. **The index files and their text.** Write each file into `docs/reference/mirror.md`
   first, exactly as the code will write it, then code to it. The specification fixes
   the structure; the text below is the interim the batched question (Open points) asks
   the maintainer to confirm, and changes only through that answer.
   - **`IndexEntry`** (184): one per written page, sorted by path; every field from the
     page (`path`, `identity`, `source_url`, `title`, `description`, `keywords`,
     `headings`, `quality_score` the page's `quality.score`, `low_confidence`,
     `quality_flags` the page's `flags`, `content_digest`, `last_modified`, `version`,
     `locale`), `word_count` the length of `quality.output.words` (Facts),
     `outbound_internal` and `inbound_internal` the page's counts over `Mirror.links`.
   - **`index.jsonl`**: one entry per line in path order, each a JSON object with
     sorted keys, compact separators, UTF-8 unescaped, sets as sorted lists, an absent
     optional value as `null`; LF after every line, so an empty mirror writes an empty
     file.
   - **`LinkIndexEntry`** (206) and **`links.jsonl`**: one entry per distinct
     `target_identity` across `Mirror.links`, sorted by URL; `kind` the link's kind;
     `path` the holder's path when the kind is `internal`, else `null`; `cited_by` the
     sorted, de-duplicated paths of the linking pages. Encoded as `index.jsonl` is.
   - **`DirectoryIndex`** (220) and **`directory_indexes_for(entries, threshold)`**: group
     each entry by its directory below `pages/<host>/`, lower-cased; a group holding more
     than `threshold` entries directly gets `_indexes/<host>/<dir>.md`, its `directory`
     the lower-cased `pages/<host>/<dir>`, its `heading` `<host>/<dir>`, its entries in
     path order. A host's top level never gets one. Sorted by `path`.
   - **`index.md`**: `# Index`, then per host in name order `## <host segment>`, a list of
     the host's top-level pages, then per top-level directory in name order
     `### <directory>`, a list of the directory's directory indexes (nearest first,
     `- [<heading>](<relative path>)`) followed by its pages. A page line is
     `- [<title>](<relative path>)`, followed by a space and `(low confidence)` when
     `low_confidence` holds.
   - **`_indexes/<host>/<dir>.md`**: `# <heading>`, a list of the directory's nearest
     indexed descendants (the indexes of the directories below its own, skipping any
     directory without an index of its own), then its pages, each line as in
     `index.md`, every link relative to the index file.
   - **`llms.txt`**: `# <host segment of the first entry>` (an empty mirror: `# Index`),
     a blank line, `> <summary>` when the summary is not empty, a blank line, then the
     page lines of `index.md` in path order. When the written pages number more than
     `llms_txt_cap`, each directory with its own directory index is listed as one line
     linking it instead of its pages; a host's top-level pages, and the pages of a
     directory without an index, are always listed.
   - **`llms_summary(mirror, entries)`**: the description of the page whose identity, or
     an alias of which, matches a start URL of the scope (normalised with
     `scope.identity_of`), else of the first entry by path, else the empty string.
   - **Writing.** Every file is LF-terminated UTF-8, written through `write_text` (T09's
     atomic write) only when its current text differs; a file under `_indexes/` that
     this build would not write is deleted, and a directory under `_indexes/` this leaves
     empty is removed. Nothing an index writes carries a time.

2. **The import direction.** No new layer: `rovo._mirror.indexes` imports `rovo._mirror`'s
   own modules and `rovo._convert` only; `rovo._commands` calls it; `_crawl` never does.
   `just py-test tests/test_import_direction.py` stays green unedited.

3. **Tests first, from the obligations** (the `propagate` skill, spec-first). Write a
   failing test for each owned obligation below into the test file of its module,
   named `test_<obligation id with dots and hyphens as underscores>`, its docstring
   quoting the obligation's description from the plan-spec file. Generated tests satisfy
   EditorConfig (indentation in 4-space multiples in `*.py`, string literals included),
   ruff and mypy, since the gate stages them. Run `just py-test` and record the red run
   in `ai_tmp/T11/red.txt`, its summary line under `last_results.propagate` in the
   ledger. Record each generated or re-propagated test file's SHA-256 under
   `generated_test_hashes`, and the reconciliation line (`N obligations, M covered, K
   uncovered`) over the owned set. A test changed after the red run is re-recorded: a
   new hash, `tick` incremented, a ledger note naming the test and why; never silently.
   An obligation a test cannot reach without a later slice's behaviour is not owned:
   move it to the hand-back notes with its reason rather than writing a vacuous test.

   Owned obligations, new in this slice (ids as `just plan-spec <module>` emits them at
   `32f2210`; 23):

   - **`mirror`** (17), in `tests/test_mirror.py`: `value-equality.IndexEntry`,
     `entity-fields.IndexEntry`, `value-equality.LinkIndexEntry`,
     `entity-fields.LinkIndexEntry`, `value-equality.DirectoryIndex`,
     `entity-fields.DirectoryIndex`, `entity-fields.Index`,
     `entity-relationship.Mirror.index`, `enum-comparable.PassKind`,
     `entity-optional.MirrorPass.run_id` (first null with an `index` pass),
     `config-default.hierarchical_index_threshold`, `config-default.llms_txt_cap`,
     `rule-success.RebuildIndexes`, `rule-failure.RebuildIndexes.1`,
     `rule-failure.RebuildIndexes.2`, `rule-success.BuildIndexes`,
     `rule-failure.BuildIndexes.1`.
   - **`rovo`** (6), in `tests/test_commands.py`: `rule-success.RebuildIndex`,
     `rule-failure.RebuildIndex.1`, `rule-success.RefuseRebuildIndex`,
     `rule-failure.RefuseRebuildIndex.1`, `rule-success.FinishIndexCommand`,
     `rule-failure.FinishIndexCommand.1`.
   - **`crawl`**, **`convert`**: none.

   Extended, not new: T09 owns `transition-edge.MirrorPass.pending.completed` and
   generated its test, which asserts that no `index.md` is written
   (`tests/test_mirror.py` 755 to 756). It is re-propagated in place (same name, the
   assertion inverted to the index files existing, T09's other assertions kept),
   re-hashed in this slice's ledger with a note naming T09 as the origin; T09's and
   T10's hashes of that file are superseded in T11's ledger, never edited in theirs.

   Guarantees (no obligation id; a hand-written test named after each in
   `tests/test_indexes.py`): `DeterministicIndexes` (1437: built twice from one mirror,
   every file byte-identical; entries sorted by path and link entries by URL; LF-terminated
   UTF-8) and the index half of `RelativeLinksOnly` (1420: every link an index holds
   resolves from the index file's directory to a file that exists).

   Not owned, and why, for the hand-back notes: `surface-actor`, `surface-exposure` and
   `surface-provides` of `MirrorContents` (the lifecycle and ownership slices: the surface
   exposes `removed_pages` and provides `OperatorSavesOwnership`);
   `surface-actor.MirrorCommands` and `surface-provides.MirrorCommands` (the surface
   provides `verify`, `report` and `fetch`); `config-default.llms_txt_depth` and
   `config-default.llms_txt_priority` (`crawl`, the discovery slice's reading of a site's
   `llms.txt`); every other uncovered obligation in the four files, each belonging to
   the slice T09's Context table names.

4. **Mirror** (`src/rovo/_mirror/`). The values and entity of step 1 in `model.py`;
   `indexes.py`; `finalise` calling `build_indexes` with `FinishLinkPass`'s
   `IndexBuildDue`, `BuildIndexes` completing the pass (`rule-failure.BuildIndexes.1`: a
   completed pass builds nothing). Unit cases in `tests/test_mirror.py` and
   `tests/test_indexes.py` on mirrors built in memory and written under `tmp_path`: two
   hosts (`docs.example` and `api.example`), a host's top-level pages and two top-level
   directories; a directory at `threshold` entries (no index) and at `threshold + 1`
   (an index); `api` and `api/v2/ref` indexed with `api/v2` not, so `api.md` links
   `api/v2/ref.md`; `API/a.md` and `api/b.md` sharing `_indexes/<host>/api.md`; a
   low-confidence page marked; `llms.txt` at `cap` and at `cap + 1` pages; a summary from
   a start URL, from an alias of one, from the first page by path, and empty; a
   `links.jsonl` entry for each kind (`internal` with `path`, `uncrawled`, `external`, and
   `dangling` on a page record constructed with `status = removed`, as T10's unit tests
   do) and one cited by two pages; a stale `_indexes/<host>/old.md` deleted with its
   emptied directory; a second build writing nothing (`write_text` counted through a
   monkeypatched wrapper). `just py-test tests/test_mirror.py tests/test_indexes.py`.

5. **Commands and the command line** (`src/rovo/_commands.py`, `src/rovo/cli.py`).
   `index(out_dir)`: a missing directory or a manifest that does not load, or a written
   page whose file is missing or is not UTF-8, writes `rovo: index: <problem>` to
   standard error and exits `usage` (`RefuseRebuildIndex`); otherwise `RebuildIndex`
   requests an `index` pass with a null `run_id`, `RebuildIndexes` and `BuildIndexes`
   write the files, and `FinishIndexCommand` exits `ok`. `_start_sync` takes the
   finalisation's `IndexesWritten` for `FinaliseRunReport`, its behaviour otherwise
   unchanged. The `index` command in `cli.py` imports `rovo._commands` inside its body
   and nothing for fetching or the clock. Unit cases in `tests/test_commands.py` and
   `tests/test_cli.py` through `CliRunner`. Run `just py-lint`, `just py-typecheck`,
   `just coverage`; add `rovo/_mirror/indexes.py` to `PACKAGE_FILES` and run
   `just wheel-smoke`, quoting its `api` line.

6. **The import of the command.** A test in `tests/test_cli.py` runs, in a subprocess
   (`sys.executable -I -c`), `rovo.cli`'s `index` on a mirror under `tmp_path` and
   prints `sys.modules`: neither `httpx` nor `rovo._crawl` is loaded. Its positive
   control is the same check on `sync`, which loads both.

7. **End to end.** Fixture site `indexes`, two-space indentation and a final newline.
   Every page has a `<title>` and a `<main>` holding an `h1` and a paragraph of prose; an
   `id` only on a heading; no image; no `<a>` inside `pre` or `code`; no link to a missing
   file, a directory without its slash or a non-HTML file (each still stops the run at
   `DisposeFetch`, as in T10). Every link a fixture holds is named here:
   - `indexes/guide/start.html`: a `<meta name="description">` (the summary), links to
     `b.html`, `api/ref.html` and `api/v2/x.html`.
   - `indexes/guide/b.html`: a link back to `start.html`.
   - `indexes/guide/api/ref.html`: a link to `v2/x.html` and to
     `https://example.invalid/` (external, never requested).
   - `indexes/guide/api/v2/x.html`: one paragraph, no link.
   - The large-directory site is generated by a helper in `tests/e2e/test_index_files.py`
     into `tmp_path`: `guide/start.html` linking `guide/big/p<NNN>.html` for
     `CONFIG.hierarchical_index_threshold + 1` pages, each as the fixture rules above
     require, then served with `serve_site(<path>)`.
   The scenarios are the Acceptance criteria's. `just py-test tests/e2e -ra`.

8. **Witness** (the `weed` and `witness` skills). Run `weed` over `mirror` and `rovo`
   against the code, scoped to the owned and extended obligations and the two
   guarantees; record its verdict under `last_results.weed` and fix any code
   divergence, each with a regression test in `tests/test_regressions.py`. A divergence
   weed attributes to the specification is not fixed: it joins the one batched
   needs-user question. Then run `witness` non-interactively: it writes
   `.allium-loop/T11-indexes.witness.json` per `witness-result.schema.json`. The verdict
   must be `PASS`; a `FAIL` routes back per the skill, and the hand-back notes record
   each round.

9. **Documents** (the `review-docs` skill). The pages of the Files touched table; find
   the sentences this slice makes false with
   `rg -n -i "index(es)? slice|no index|arrive with their slices|verify., .index|seed pages" -g '*.md' -g '!tickets/**' -g '!allium-skill-reference/**' -g '!docs/specs/**' -g '!docs/decisions/**'`;
   `CHANGELOG.md` `Unreleased` gains one Added entry. Keep the required phrases of
   `AGENTS.md` in always-visible text. `just check-docs`, `just check-agents`.

10. Hand-back notes, `status: done`, `just check` ending with
    `All checks passed and the worktree is unchanged.`, `git status --short` empty after
    the commit. Commit on the branch. **Authorisation required**: pushing and opening the
    pull request.

## Acceptance criteria

- **End to end, the indexes after a sync** (`tests/e2e/test_index_files.py`, through the
  installed `rovo` script beside `sys.executable`): with `serve_site("indexes")` at
  `<base>`, `rovo init <base>guide/start.html <tmp>/out` then `rovo sync <tmp>/out` both
  exit 0. At the mirror's root: `index.md` has one `## 127.0.0.1_<port>` heading, the
  top-level pages `start` and `b` beneath it, then `### api` listing `api/ref` and
  `api/v2/x`, each linked as `pages/127.0.0.1_<port>/<path>.md`; `index.jsonl` has four
  lines in path order whose `path` values are the four page paths and whose
  `outbound_internal` and `inbound_internal` agree with the pages' links; `links.jsonl`
  has one line per cited identity, sorted by `url`, `https://example.invalid/` of kind
  `external` with a `null` path, `<base>guide/b.html` of kind `internal` cited by
  `start`; `llms.txt` holds a `>` blockquote marker, a space and the start page's description, then the four page
  lines; no `_indexes/` directory exists (no directory reaches the threshold). Every
  file ends with a line feed and every relative link in it reaches an existing file.
  `crawl-report.json` still has `exit_code: "ok"` and `broken_links: []`.
- **End to end, `rovo index` rebuilds them**: on that mirror, `rovo index <tmp>/out`
  exits 0 and every index file is byte-identical to the sync's, with its modification
  time unchanged (written only when the text differs); after `index.md` is deleted and a
  file `_indexes/127.0.0.1_<port>/stale.md` is created, `rovo index` exits 0, `index.md`
  is back byte for byte and `_indexes/` holds nothing; `.rovo/manifest.json`,
  `.rovo/frontier.json`, `.rovo/runs.json` and `crawl-report.json` are byte-identical
  throughout.
- **End to end, the refusals**: after a page file is deleted, `rovo index <tmp>/out` exits
  2, names the file on standard error and changes no index file; `rovo index` on an
  empty directory exits 2 and writes nothing.
- **End to end, a directory index**: against the generated large-directory site, sync
  exits 0, `_indexes/127.0.0.1_<port>/big.md` exists with one line per page linking
  `../../pages/127.0.0.1_<port>/big/p<NNN>.md`, and `index.md` links it as
  `_indexes/127.0.0.1_<port>/big.md`.
- **End to end, earlier scenarios** (`tests/e2e/test_init_sync.py`,
  `tests/e2e/test_follow_links.py`) still pass. `BuildIndexes` writes `index.md` at the
  mirror root on every finalisation, so their page listings were re-propagated in propagate
  tick 2 to read page files under `pages/` only; nothing else in them changed.
- Every owned obligation in step 3 has a test named after it, red before the code and
  green after (`ai_tmp/T11/red.txt` and the final run); the reconciliation line shows
  zero uncovered; the extended test is re-hashed in the ledger with its note; every
  obligation dropped from the owned list is in the hand-back notes with its reason.
- `DeterministicIndexes` and the index half of `RelativeLinksOnly` have their named tests;
  the directory-index unit cases of step 4 pass.
- `rovo index --help` and `rovo index` without an argument behave as the other mirror
  commands through `CliRunner`; `docs/reference/cli.md` documents `rovo index` and its
  exit codes 0 and 2; `rovo index` loads neither `httpx` nor `rovo._crawl` (step 6).
- `finalise.py`'s docstring no longer names the `BuildIndexes` deviation; the set of
  `NotInThisSlice` raises in `src/` is the one T10 left
  (`rg -c 'NotInThisSlice\(' src` unchanged from `9fd11fd`).
- `.allium-loop/T11-indexes.witness.json` exists with `"verdict": "PASS"`, and the ledger
  validates against `ledger.schema.json`.
- `just check-specs` and `just analyse-specs` pass with `docs/specs/` unchanged
  (`git diff --stat 32f2210 -- docs/specs` empty).
- `import rovo` loads no module outside the standard library and `rovo`; `__all__` is
  `["__version__"]`; `just wheel-smoke` passes with the new package-file count.
- `just coverage` stays at or above the floor of 95.
- `just check-docs` and `just check-agents` pass; `docs/reference/mirror.md` and
  `docs/reference/cli.md` describe what the code does.
- `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty after the commit.

## Verification

```sh
just plan-spec mirror > ai_tmp/T11/plan-spec-mirror.txt
just plan-spec rovo > ai_tmp/T11/plan-spec-rovo.txt
just plan-spec crawl > ai_tmp/T11/plan-spec-crawl.txt
just plan-spec convert > ai_tmp/T11/plan-spec-convert.txt
git diff --stat 32f2210 -- docs/specs
just py-test tests/test_indexes.py tests/test_cli.py tests/e2e -ra
just py-lint
just py-typecheck
just coverage
just wheel-smoke
uv run --frozen python -I -c "import rovo, sys; print(sorted(m for m in sys.modules if not m.startswith(('rovo', '_')) and m not in sys.stdlib_module_names))"
rg -c 'NotInThisSlice\(' src  # compared with the same count at 9fd11fd
! rg -n 'BuildIndexes completes the pass without them' src  # positive control: the same rg at 9fd11fd prints finalise.py
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

To be written by the executing agent: the baseline; the index files as built and any
departure from step 1; the red run and the reconciliation line; the extended test and
its new hash; every obligation dropped from the owned list and why; the weed verdict and
the witness verdict, each round; the one batched needs-user question with every gap
found while planning, implementing, in weed or in review, and the maintainer's answer if
one arrived; the verification output, each headed by its commit.

## Open points

- **The one batched needs-user question: the index text and three undefined values.**
  The specification fixes what the indexes hold and how they are ordered and linked, but
  not these, which the slice needs before its files are a contract (`verify`'s
  `index_stale` will compare their bytes). Step 1 states the interim for each; the
  slice proceeds on it, names it in `docs/reference/mirror.md` and the ledger's
  `open_questions`, and changes it only through the maintainer's answer, never silently:
  1. The exact text of `index.md`, `_indexes/<host>/<dir>.md` and `llms.txt`: the title
     line of each, the heading text of a host, a top-level directory and a directory
     index (`DirectoryIndex.heading`, 223), the shape of a page line, and how a
     low-confidence page is marked (`BuildIndexes`' guidance says only "marks").
  2. Where a host's top-level pages sit in `index.md`, whose guidance names one heading
     per host and one per top-level directory but no place for the pages directly under
     `pages/<host>/`, and where in `index.md` each directory index is linked.
  3. `llms.txt` past `llms_txt_cap`: whether the pages of a non-top-level directory
     without an index of its own are still listed one by one, and whether "past it"
     means the written pages number more than the cap (the interim) or the listing
     reaches the cap partway.
  4. `IndexEntry.word_count` (199): no `Page` field and no comment defines it; the
     interim is the length of `quality.output.words` (words outside code).
  5. The encoding of `index.jsonl` and `links.jsonl` lines: key order, separators,
     escaping, and whether an absent optional value is `null` (the interim) or omitted
     (as the frontmatter does).
  6. `page_files_readable` (`rovo.allium` 50): the interim is every written page's file
     exists and decodes as UTF-8; and whether the index pass should read anything from
     the page files beyond that check (the interim takes every field from the manifest,
     so a hand-edited page file does not move its index entry).
  7. Whether a directory under `_indexes/` left empty by the deletion of stale files is
     removed (the interim) or kept.
- **`links.jsonl` belongs here.** The task's capability sentence lists four of the five
  index files; `BuildIndexes` writes the fifth, and T09 and T10 deferred it to this
  slice (Facts). If the maintainer meant another slice to own it, that slice's ticket
  takes the five `LinkIndexEntry`-related rows of this one.
- **`DeterministicIndexes` across a second sync.** Only `rovo index` can rebuild the
  indexes over an unchanged mirror in this slice; the incremental slice extends the
  guarantee's test to a second sync under `UnchangedRunIsStable`.
- **`NotInThisSlice`.** A development guard, not product behaviour: each later slice
  removes the raises it implements, and the last slice's review confirms none is left.
  This slice removes none, because T09's `BuildIndexes` deviation was never a raise.
