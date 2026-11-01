---
id: T08
title: "Product foundation: the state-on-disk decision, the runtime dependencies, the private package skeleton, the end-to-end harness"
status: done
depends_on: [T07]
parallel_with: []
branch: full-final-prototype
estimated_size: M
---

# T08: Product foundation: the state-on-disk decision, the runtime dependencies, the private package skeleton, the end-to-end harness

## Context

Decision 0012 (`docs/decisions/0012-rovo-is-a-documentation-mirror.md`) defines rovo as
a documentation mirror and the four modules under `docs/specs/` specify it: `rovo.allium`
(the command) imports `crawl.allium` (one sync run), which imports `mirror.allium` (the
mirror on disk), which imports `convert.allium` (pure conversion). None of it is
implemented. The implementation arrives as tracer-bullet slices T08 to T20, each run in
this worktree on the branch `full-final-prototype`, one after another. This is slice 0.
It implements no specification behaviour: it lays down what every later slice would
otherwise have to invent mid-flight, so that each later slice changes behaviour, its test
and its documentation and nothing else.

What it lays down, and why each piece cannot wait:

- **Where the mirror keeps its state.** `mirror.allium`'s Excludes name "storage
  mechanics (the manifest's format, atomic writes)", so no specification decides them
  and a decision record must (decision 0009, `docs/decisions/0009-specs-are-the-source-of-truth.md`,
  keeps behaviour in the specifications; this is how, not what). The specifications fix
  three facts the record must agree with: `.rovo/` is a reserved name in the mirror
  (`mirror.allium`, the path-assignment rule near line 620, beside `crawl-report.json`,
  `rovo.toml` and the indexes); fetch times live in the manifest, never in a page file
  (`mirror.allium`, the comment above `value Frontmatter`, and the contract near line
  1243); and an index carries no wall-clock time (near line 1071). `crawl.allium` calls
  the frontier "the persisted queue of every identity ever discovered" (line 40) and
  holds `ObservedUrl` rows on it. `crawl-report.json` stays at the mirror's root, where
  `rovo.allium` (line 182) and the reserved-name list put it: the record does not move it
  into `.rovo/`.
- **The runtime dependencies.** Fetching (httpx), parsing (beautifulsoup4 with lxml),
  converting to Markdown (markdownify) and an optional browser tier (playwright, the
  `browser` extra) are what the specified behaviour needs. Invariant 6 and
  decision 0005 (`docs/decisions/0005-dependency-policy.md`) govern them: compatible
  ranges with a tested lower bound, `uv.lock` the pin, and a note beside each entry. The
  procedure is `docs/how-to/maintain-dependencies.md`, "Adding or moving a runtime
  dependency".
- **The private package skeleton** mirroring the import direction, so that a later slice
  adds code to a module that already exists and a test already holds the direction.
- **The end-to-end harness**: a local static site served over stdlib `http.server`, so a
  later slice can crawl something real without the network.

Invariant 1 is the hard constraint: `import rovo` never imports a CLI-only module, and
the wheel smoke's `api` step (`scripts/wheel_smoke.py`) installs the wheel with
`--no-deps` and fails on any import outside `rovo` and the standard library. The new
dependencies are imported by nothing yet, and `src/rovo/__init__.py` must never import
them or the private subpackages. That script also checks the wheel installs exactly
`PACKAGE_FILES`, today four files, so the five new modules change it (step 3); without
that, `just wheel-smoke` goes red.

## Goal

`just check` is green with: decision 0013 recording that the mirror's persistent state is
JSON under `<out>/.rovo/`, written atomically with sorted keys and no wall-clock time in
any page file; httpx, beautifulsoup4, lxml and markdownify in `[project] dependencies` and
playwright in a `browser` extra, each with its decision-0005 note, locked; the private
modules `rovo._convert`, `rovo._mirror`, `rovo._crawl`, `rovo._config` and `rovo._report`
present as docstring-only modules that the wheel ships and `import rovo` never loads; a
test that fails when an import runs against the direction; an end-to-end fixture serving
`tests/fixtures/sites/<name>/` on `127.0.0.1` with one test proving it; a registered
`browser` marker; and a `just e2e-browser` recipe that is outside `just check`.

## Non-goals

- No specification behaviour: no fetching, parsing, conversion, mirror writing or
  command. The new modules hold a docstring and nothing else; nothing imports the new
  dependencies.
- No specification change. `docs/specs/` is read, not edited.
- No change to the public API: `__all__` stays `["__version__"]`, so `docs/reference/api.md`
  does not move.
- No command-line change: `docs/reference/cli.md` does not move.
- No browser test and no `playwright install`: the browser binaries are a later slice's
  decision. The `e2e-browser` recipe exists; the only browser-marked test is the harness
  control in step 5.
- No change to decision 0005's reasoning. Its "today the one entry is typer" sentence
  goes stale; that is an open point, not an edit (records are superseded, not rewritten).
- No CI change: the `gate` and `floor` jobs already run `coverage` and `wheel-smoke`,
  which now include the end-to-end tests.
- `.allium-loop/` is already in `.gitignore`: left as it is.
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `docs/decisions/0013-mirror-state-on-disk.md` | new | step 1 |
| `docs/decisions/README.md` | shared, own lines | the 0013 row |
| `docs/manifest.yml` | shared, own lines | the 0013 entry, `canonical_for: ["decision_mirror_state"]` |
| `pyproject.toml` | shared, own lines | four runtime entries, the `browser` extra, a note beside each |
| `uv.lock` | generated | `just lock`, never hand-edited |
| `src/rovo/_convert/__init__.py`, `src/rovo/_mirror/__init__.py`, `src/rovo/_crawl/__init__.py`, `src/rovo/_config.py`, `src/rovo/_report.py` | new | a module docstring each, step 3 |
| `scripts/wheel_smoke.py` | shared, own lines | `PACKAGE_FILES` gains the five modules; "four" becomes "nine" in the verdict line |
| `tests/test_import_direction.py` | new | the AST scan, step 4 |
| `tests/e2e/conftest.py` | new | the `serve_site` factory fixture, step 5 |
| `tests/e2e/test_harness.py` | new | the served-site test and the browser-marker control, step 5 |
| `tests/fixtures/sites/basic/index.html` | new | the smallest fixture site |
| `pytest.ini` | shared, own lines | `markers = browser: ...` |
| `Justfile` | shared, own lines | `e2e-browser`, step 6 |
| `AGENTS.md` | shared, own lines | the project map's `src/rovo/` and `tests/` lines, step 7 |
| `docs/reference/testing.md` | shared, own lines | the end-to-end tests, the fixture sites, the marker, the import-direction test, "nine package files" |
| `docs/reference/commands.md` | shared, own lines | the `e2e-browser` row |
| `docs/reference/configuration.md` | shared, own lines | the runtime dependencies and the extra in the `[project]` row |
| `docs/project/repository-map.md` | shared, own lines | the tree and "Fixtures are positive controls" |
| `docs/explanation/architecture.md` | shared, own lines | one row for the private modules; the import-direction test under "The boundary" |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` entry |
| `docs/how-to/test-and-debug.md` | shared, own lines | "four package files" becomes nine (found in the step-7 review) |
| `docs/how-to/maintain-dependencies.md` | shared, own lines | the Renovate table's runtime-range row names every runtime range and the extra (found in the step-7 review) |
| `tickets/README.md`, `tickets/T08-foundation.md` | ticket | index row, graph, this ticket |

`ruff.toml`, `mypy.ini`, `.coveragerc`, `_typos.toml`, `lychee.toml` and
`.markdownlint-cli2.jsonc` are read, not changed, unless step 5 shows a hook reading the
fixture site wrongly; any such change is one line with a comment, and is added to this
table in the same change.

## Steps

0. `just check` baseline on the untouched worktree, last line quoted, headed by its
   commit. Write this ticket and the index row. Scratch output goes in `ai_tmp/T08/`.
1. **Decision 0013.** `docs/decisions/0013-mirror-state-on-disk.md`, in the shape of
   0012: the frontmatter (`title: "Decision 0013: The mirror's state on disk"`,
   `kind: "decision"`, `audience: ["contributor", "maintainer", "agent"]`,
   `canonical_for: ["decision_mirror_state"]`, `requires: []`), then Context, Decision,
   Consequences, What would reopen this, Related pages. The decision: everything the
   mirror persists between runs that is not a page file, an index or
   `crawl-report.json` (the manifest of pages, aliases and links; the frontier and its
   observed URLs; sitemap snapshots; the run history) is JSON under `<out>/.rovo/`, one
   file per kind; every write goes to a temporary file in the same directory, is
   flushed and `fsync`ed, then `os.replace`d over the target, so a reader sees the old
   file or the new one and never a torn one; keys are sorted and the encoding fixed
   (UTF-8, a stated indent, a trailing newline) so an unchanged state rewrites
   byte-identically; no wall-clock time is stored in a page file, and fetch times live
   in the manifest, as `mirror.allium` already says. Name the specification lines from
   Context that the record agrees with, and say that it fixes the how
   (`mirror.allium` Excludes) and never the what. Context says why JSON and not SQLite
   or TOML: the standard library reads and writes it, a diff reads it, and nothing here
   needs concurrent writers. Consequences name the cost: whole-file rewrites, so a
   large frontier rewrites in full on each save. Reopening conditions a reader could
   check: a measured save time or file size a later slice records, or a second writer.
   The exact file names under `.rovo/` are left to the slice that first writes each
   file; the record says so. Add the row to `docs/decisions/README.md` and the entry,
   in the JSON shape of the 0012 entry, to `docs/manifest.yml`; read "The numbering"
   paragraph and change it only if 0013 makes it false. `just check-docs`.
2. **Dependencies** (`docs/how-to/maintain-dependencies.md`, "Adding or moving a runtime
   dependency"). Under `[project] dependencies`, after typer, add `httpx`,
   `beautifulsoup4`, `lxml` and `markdownify` provisionally without bounds, and
   `[project.optional-dependencies] browser = ["playwright"]`. Run `just lock`
   (**network, authorised by this ticket**). Read each resolved version from
   `uv.lock`, then write each entry as `>=<resolved>,<next>` where `<next>` follows the
   typer pattern: the next minor while the package is at 0.x (httpx), the next major
   otherwise (expected for beautifulsoup4, lxml, markdownify and playwright; confirm
   against the resolved version, do not assume). Run `just lock` again; the resolved
   versions must not move, so the lower bounds are what the gate tests. Then
   `just sync` (**network, authorised by this ticket**) and `just lock-check`. Each
   entry gets the decision-0005 note as a comment beside it, in the shape of typer's:
   what it does here; why the standard library will not do (for example, `urllib` has
   no HTTP/2, connection pooling with limits or timeouts per phase; `html.parser` is
   slow and lenient where lxml is the tested parser; there is no stdlib HTML to
   Markdown; there is no stdlib JavaScript renderer); its licence, read from the
   installed distribution's `METADATA` under `.venv`; and its maintenance, who
   releases it and the upload date of the locked release, read from `uv.lock`'s
   `upload-time`. Quote the four facts per package in the hand-back notes with where
   each was read, so a reviewer can check them. Say in the playwright note that the
   extra installs the Python package only, not a browser. `just sync` installs no
   extra, so playwright stays absent from `.venv` and browser-marked tests skip.

   **Adversarial review** (`CONVENTIONS.md` §14) over the dependency diff and the
   notes: a bound that admits an untested floor or blocks a compatible release; a note
   whose licence or maintenance claim does not match the evidence; a wheel missing for
   3.13 or for either CI runner (the `floor` job runs `coverage` and `wheel-smoke` on
   3.13); the `wheel-smoke` closure step (`uv sync --frozen --offline
   --no-default-groups --no-install-project`) failing offline after a fresh `just sync`.
3. **The private skeleton.** Create the five modules, each holding only a module
   docstring that names its role and its place in the direction (`_convert` imports
   nothing of rovo's; `_mirror` may import `_convert`; `_crawl` may import `_mirror`
   and `_convert`; `_config` and `_report` serve the command and the root). Nothing
   imports them; `src/rovo/__init__.py` is untouched. Add the five paths to
   `PACKAGE_FILES` in `scripts/wheel_smoke.py` and change "the four package files" in
   its verdict line to nine. Run `just coverage` and quote the five rows coverage
   reports for the new files: a docstring-only module should count no statements, but
   that is to be shown, not assumed. Run `just wheel-smoke` and quote its `api` line.
4. **The import-direction test.** `tests/test_import_direction.py`, in the style of
   `tests/test_api.py` (module docstring, one test per rule, a docstring each, typed).
   It walks `src/rovo/**/*.py` with `ast`, collects every `import` and `from ... import`
   (relative imports are banned by ruff, so absolute names suffice), and asserts:
   nothing under `_convert` imports `rovo._mirror`, `rovo._crawl` or `rovo.cli`;
   nothing under `_mirror` imports `rovo._crawl` or `rovo.cli`; nothing under `_crawl`
   imports `rovo.cli`; and `src/rovo/__init__.py` imports none of `rovo._convert`,
   `rovo._mirror`, `rovo._crawl`, `rovo._config`, `rovo._report`, `rovo.cli`, nor
   `httpx`, `bs4`, `lxml`, `markdownify`, `playwright` or `typer` (matched on the first
   dotted component). It also asserts that the scan found each of the five new modules,
   so an emptied glob cannot pass. Positive control, on a scratch copy
   (`CONVENTIONS.md` §11): add `import rovo._crawl` to `src/rovo/_convert/__init__.py`,
   show the test fail naming the module, restore, show `cmp` against the saved copy
   print nothing.
5. **The end-to-end harness.** `tests/e2e/conftest.py` defines a fixture that, given a
   site name, serves `tests/fixtures/sites/<name>/` with `http.server.ThreadingHTTPServer`
   and `SimpleHTTPRequestHandler` (`functools.partial(..., directory=...)`, request
   logging silenced) bound to `("127.0.0.1", 0)`, runs `serve_forever` in a daemon
   thread, yields the base URL (`http://127.0.0.1:<port>/`), and in `finally` calls
   `shutdown()`, `server_close()` and joins the thread, so that `filterwarnings = error`
   sees no `ResourceWarning`. A test asks for a site by name (an indirect parameter or a
   factory fixture: pick one and say which). `tests/fixtures/sites/basic/index.html`
   is a minimal valid page: a title, one heading, one paragraph, two-space indentation
   and a final newline (`editorconfig-checker` reads every text file; typos reads it
   too). `tests/e2e/test_harness.py` fetches the base URL with `urllib.request` inside
   a `with`, asserts status 200 and that the body contains the page's heading; if ruff
   reports `S310` on the fixed `http://127.0.0.1` URL, suppress it on that line with
   the rule and a reason (invariant 4). The same file holds the browser-marker control:
   one test marked `browser` that calls `pytest.importorskip("playwright.sync_api")`
   and asserts `sync_playwright` is callable, so that with playwright absent it reports
   one skip, never an error. No basename under `tests/e2e/` may repeat one under
   `tests/` (no `__init__.py`, so pytest and mypy key modules by basename). Register
   the marker in `pytest.ini` (`markers =` then `browser: needs playwright and its
   browser; run with just e2e-browser`). Read the hooks in `.pre-commit-config.yaml`
   (editorconfig-checker, typos, check-added-large-files, the `local` Python hooks),
   `_typos.toml`, `lychee.toml` (lychee reads Markdown only) and
   `.markdownlint-cli2.jsonc`, and record in the hand-back notes which of them read
   `tests/fixtures/sites/` and whether any treats it as a lint positive control (the
   `py-lint` and `py-typecheck` controls name `tests/fixtures/py-lint-violation/`
   alone, and `ruff.toml` and `mypy.ini` exclude only that directory). Run
   `just py-test tests/e2e -ra` and quote one pass and one skip; run `just coverage`.
6. **The recipe.** In the `Justfile`'s check section, after `py-test`, with a comment in
   the house style: `e2e-browser *args:` running
   `uv run --frozen --offline --extra browser pytest -m browser "$@"`. `--offline`
   keeps it out of the network recipe list (`AGENTS.md`): on a cold cache it fails
   rather than fetching playwright, and the comment says that and that the browser
   binaries are not installed by any recipe yet. Do not add it to `recipes` in
   `pyproject.toml`: `just check` must need neither a browser nor the network.
   `pytest -m browser` exits 5 when it selects nothing; with the control test from
   step 5 it selects one, so the exit is 0 when playwright is present. Quote
   `just --show e2e-browser` and `just py-test -m browser -ra` (one skip, exit 0).
   Running `just e2e-browser` itself needs playwright in the uv cache, which this
   ticket does not fetch; if the cache lacks it, quote the offline failure and say so.
   Add the row to `docs/reference/commands.md`'s Check table, saying it is not a gate
   and is outside `check`.
7. **Documents.** `AGENTS.md`'s project map: `src/rovo/` also holds the private modules
   `_convert`, `_mirror`, `_crawl`, `_config` and `_report`; `tests/fixtures/` holds the
   lint positive controls and, under `sites/`, the static sites the end-to-end tests
   serve from `tests/e2e/`. Keep the six required phrases in always-visible text and run
   `just check-agents`. `docs/reference/testing.md`: the "no package and no
   `conftest.py`" sentence becomes true again for `tests/` alone and names `tests/e2e/`
   and its `conftest.py`; a section on the end-to-end harness, the fixture sites and the
   `browser` marker; the import-direction test beside the API section; "nine package
   files". `docs/project/repository-map.md`: the tree gains the five modules,
   `tests/e2e/` and `tests/fixtures/sites/`, and "Fixtures are positive controls" names
   the sites as the exception. `docs/explanation/architecture.md`: one row for the
   private modules and their direction (citing decision 0012), and the new test under
   "The boundary". `docs/reference/configuration.md`: the `[project]` row names the
   five runtime dependencies and the `browser` extra. `CHANGELOG.md` `Unreleased`, one
   entry under Added: the runtime dependencies and the `browser` extra; the private
   module skeleton and the import-direction test; the end-to-end harness and
   `just e2e-browser`; decision 0013. Each topic is added to its owning page in
   `docs/manifest.yml`, not restated. `just check-docs`.

   **Adversarial review** (`CONVENTIONS.md` §14) over the documents: decision 0013
   against the three specification facts in Context; a page now false (testing,
   repository map, architecture, configuration, `AGENTS.md`); a count that no longer
   agrees (package files, skills, gates, network recipes).
8. Hand-back notes, `status: done`, `just check`.

   **Adversarial review** (`CONVENTIONS.md` §14) over the full diff before the commit:
   whether the direction test can pass while an import runs against the direction (a
   dynamic import, `importlib`, an emptied glob); whether the end-to-end fixture leaks
   a socket or a thread under `filterwarnings = error`; whether the wheel smoke still
   proves `import rovo` loads nothing outside the standard library; whether `just check`
   or the `floor` job needs the network or a browser. Rerun `just check` if any fix
   landed. Commit on the branch.
   **Authorisation required**: pushing and opening the pull request.

## Acceptance criteria

- `docs/decisions/0013-mirror-state-on-disk.md` exists, is registered in
  `docs/decisions/README.md` and `docs/manifest.yml`, and contradicts no line of
  `docs/specs/`; `just check-docs` is green.
- `pyproject.toml` lists httpx, beautifulsoup4, lxml and markdownify as compatible
  ranges whose lower bound equals the version `uv.lock` holds, and playwright under
  `[project.optional-dependencies] browser`, each with a note giving what it does, why
  the standard library will not do, its licence and its maintenance; the evidence for
  each is quoted. `just lock-check` exits 0.
- The five private modules exist as docstrings; `src/rovo/__init__.py` is unchanged and
  `__all__` is `["__version__"]`; `just wheel-smoke` passes with nine package files and
  its `api` step reports no import outside the standard library.
- `tests/test_import_direction.py` passes, and its positive control is quoted failing.
- `just py-test tests/e2e -ra` shows the served-site test passing and the browser
  control skipped; no warning is raised.
- `just e2e-browser` exists, is outside `recipes`, and `just --show e2e-browser` is
  quoted; `docs/reference/commands.md` lists it.
- `just check-agents` prints `Validated AGENTS.md, 2 adapters, and 14 skills.`
- `just coverage` stays at or above the floor, with the new modules' rows quoted.
- `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty after the commit.
- The three adversarial reviews ran (`CONVENTIONS.md` §14), and every valid finding is
  fixed or handed back.

## Verification

```sh
just lock-check
uv run --frozen python -I -c "import rovo, sys; print(sorted(m for m in sys.modules if m.startswith('rovo')))"
just py-test tests/test_import_direction.py tests/e2e -ra
just py-test -m browser -ra
just --show e2e-browser
just coverage
just wheel-smoke
just check-docs
just check-agents
just check
git status --short
```

CI evidence (the `gate` job and the 3.13 `floor` job running the end-to-end tests and the
wheel smoke with the new dependencies) exists only after the push, which is separately
authorised; it goes in the closing pull request's notes.

## Hand-back notes

Uncommitted at hand-back: the orchestrator asked for no commit, so step 8's commit, and
`git status --short` empty after it, are left to whoever commits.

**Step 0.** Baseline on `615d093` (ticket files only uncommitted): `just check` ended
`All checks passed and the worktree is unchanged.`

**Step 1.** Decision 0013 agrees with `mirror.allium` lines 22 to 26 (Excludes: storage
mechanics), 619 and 620 and 1172 (`.rovo/` reserved), 139 to 141 and 1243 (no
wall-clock time in a page file, fetch times in the manifest), 1071 and 1256 (no
wall-clock time in an index or generated file); `crawl.allium` lines 40, 348, 357
(frontier, `ObservedUrl`, `SitemapSnapshot`); `rovo.allium` line 182
(`crawl-report.json` at the root, not moved). "The numbering" paragraph stays true and
is unchanged. `just check-docs`: `Validated 39 pages and 39 canonical topics.`

**Step 2.** First `just lock` resolved httpx 0.28.1, beautifulsoup4 4.15.0, lxml 6.1.3,
markdownify 1.2.3, playwright 1.64.1; the bounded relock left all five versions
unchanged (diffed against a saved copy). Bounds: httpx `<0.29` (0.x, next minor), the
other four next major. Evidence, per package (licence from METADATA under
`.venv/lib/python3.14/site-packages/<dist>.dist-info/`, maintenance from METADATA's
author fields and `uv.lock`'s `upload-time`):

| Package | Licence (where read) | Releaser (METADATA) | Locked upload |
| --- | --- | --- | --- |
| httpx 0.28.1 | `License: BSD-3-Clause` | `Author-email: Tom Christie`; source `github.com/encode/httpx` | 2024-12-06 |
| beautifulsoup4 4.15.0 | `License: MIT License` | `Author-email: Leonard Richardson` | 2026-06-07 |
| lxml 6.1.3 | `License: BSD-3-Clause`; `licenses/LICENSES.txt` lines 51 and 78: libxml2 MIT, libxslt MIT | `Maintainer: lxml dev team` | 2026-09-02 |
| markdownify 1.2.3 | no `License` field; `Classifier: License :: OSI Approved :: MIT License` | `Author-email: Matthew Tretter` | 2026-06-30 |
| playwright 1.64.1 | `License-Expression: Apache-2.0` | `Author: Microsoft Corporation` | 2026-10-22 |

playwright is not in `.venv` (`just sync` installs no extra), so its METADATA was read
from PyPI's PEP 658 file for the locked wheel, the `uv.lock` URL of
`playwright-1.64.1-py3-none-manylinux1_x86_64.whl` plus `.metadata`. Wheels for 3.13 on
both CI runners: httpx, beautifulsoup4 and markdownify are `py3-none-any`; lxml has
`cp313` manylinux x86_64 and macOS universal2; playwright has `py3-none` manylinux1
x86_64 and macOS arm64. `just sync` then `just lock-check` exit 0
(`Resolved 37 packages`). Review: the notes were checked against the evidence above; one
unsourced claim (a named lxml maintainer) was removed before hand-back.

**Step 3.** `just coverage` rows for the new modules, all `0 0 0 0 100%`:
`src/rovo/_config.py`, `src/rovo/_convert/__init__.py`, `src/rovo/_crawl/__init__.py`,
`src/rovo/_mirror/__init__.py`, `src/rovo/_report.py`; total 100%. `just wheel-smoke`:
`wheel_smoke api: rovo 0.0.0, no CLI module imported, exactly the nine package files and
the expected metadata`; the offline closure step installed 19 packages and the `cli`
step passed.

**Step 4.** The test also counts `importlib.import_module` and `__import__` with a
literal name, and `from rovo import _x` as `rovo._x`. Positive control: with
`import rovo._crawl` appended to `src/rovo/_convert/__init__.py`,
`test_convert_imports_nothing_above_it` failed with
`Left contains one more item: 'rovo._convert imports rovo._crawl'` (1 failed, 4
passed); restored from the saved copy, `cmp` printed nothing.

**Step 5.** A factory fixture, `serve_site(name) -> str`. The server subclass sets
`daemon_threads = False` so `server_close()` joins request threads; `serve_forever`
polls every 0.05 s so shutdown is prompt. `just py-test tests/e2e -ra` (run twice):
`1 passed, 1 skipped`, the skip
`could not import 'playwright.sync_api': No module named 'playwright'`, no warning.
`S310` is suppressed on the `urlopen` line with a reason; `PLR2004` was fixed with
`HTTPStatus.OK`. What reads `tests/fixtures/sites/`: editorconfig-checker (text files),
typos, `check-added-large-files`, `check-case-conflict`, `detect-private-key`,
`check-merge-conflict` and ripsecrets read `index.html` and pass (run on the untracked
files with `prek run --files`); markdownlint and lychee read Markdown only, and the
`py-lint` and `py-typecheck` hooks Python only. None treats it as a positive control:
`ruff.toml` and `mypy.ini` exclude only `tests/fixtures/py-lint-violation`, and the
controls name that directory alone. No configuration changed.

**Step 6.** `just --show e2e-browser`:

```text
e2e-browser *args:
    uv run --frozen --offline --extra browser pytest -m browser "$@"
```

`just py-test -m browser -ra`: `1 skipped, 16 deselected`, exit 0. `just e2e-browser`
fails offline, as intended, because the cache holds playwright's metadata but not its
wheel: `Network connectivity is disabled, but the requested data wasn't found in the
cache: .../playwright-1.64.1-py3-none-macosx_11_0_arm64.whl`. Not in `recipes`.

**Step 7.** `just check-agents`: `Validated AGENTS.md, 2 adapters, and 14 skills.`
Review: two pages outside the table were false and were fixed (added to the table):
`test-and-debug.md` ("four package files") and the Renovate row of
`maintain-dependencies.md`. Counts checked: package files nine everywhere; skills 14,
gates ten and network recipes eight unchanged.

**Step 8.** Review over the full diff: the direction test misses an import whose name is
computed at run time (said in `testing.md`; the API probe and the wheel smoke still see
what `import rovo` loads); the fixture closes the listening socket and joins every
thread; the wheel smoke's `api` step is unchanged and still fails on any non-stdlib
import; `just check` reaches only `127.0.0.1`, and the `floor` job's closure step needs
3.13 wheels, which all five packages ship. Final `just check`: see
`ai_tmp/T08/implement.md`.

## Open points

- **Decision 0005's "today" sentence.** It says the one runtime entry is typer and that
  `uv.lock` holds typer at its floor. After this ticket that is stale. A record is
  superseded rather than rewritten (`docs/decisions/README.md`); whether a factual
  "today" clause may be refreshed in place, or the sentence should move to
  `docs/reference/configuration.md`, is the maintainer's call.
- **Browser binaries.** No recipe installs playwright's browsers, and `e2e-browser` is
  offline. The slice that adds the first real browser test decides how the browser and
  the playwright wheel reach the cache, and whether that recipe joins the network list.
- **Lower bounds after a relock.** As decision 0005 says of typer, a floor is tested
  only while the lock sits on it.
