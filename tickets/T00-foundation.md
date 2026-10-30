---
id: T00
title: "Foundation: a tracer bullet that is green on its first commit"
status: open
depends_on: []
parallel_with: []
branch: ticket/t00-foundation
estimated_size: L
---

# T00: Foundation: a tracer bullet that is green on its first commit

## Context

`BiscuitBin/rove` holds a stub `README.md` and, once the bootstrap pull request merges,
this `tickets/` directory. Every later lane replaces a stub this ticket creates, and
every lane's definition of done is `just check` green, which only this ticket can make
true first (`README.md`, "Dependency graph"). So this ticket builds the thinnest path
through every layer: a `pyproject.toml` and `uv.lock`, a package with a placeholder API
and a Typer command, one test of each, a `Justfile` whose `just check` passes, a wheel
that builds and runs `rovo --version` from an isolated environment offline, and a stub
for every page, record, skill and bridge B's validators expect.

A's T00 built the same shape for a Rust-and-pyo3 wheel (A `tickets/T00-foundation.md`).
Its hook configuration, dotfiles, handbook manifest and agent stubs carry across with the
deltas `CONVENTIONS.md` §5 to §7 state; its pixi, maturin and Rust files do not. The
uv-and-hatchling files have no original, so `CONVENTIONS.md` §2, §4 and §9 state them in
full: write them as stated.

## Goal

On a fresh clone of the ticket branch, `just initialize` then `just check` ends with
`All checks passed and the worktree is unchanged.`; `rovo --version` runs from a wheel
installed into an empty venv with the network denied; every path `CONVENTIONS.md` §3
gives to T00 exists; and the files `CONVENTIONS.md` §11 freezes are final.

## Non-goals

- No product behaviour. The API is `rovo.__version__`; the command is `--version` and
  `version`.
- No final prose: handbook pages, decision records, skills and `AGENTS.md` are stubs
  that pass B's validators (T03, T04 write them).
- No CI beyond a one-job stub; no repository settings (T01).
- No `LICENSE` and no licence metadata (`CONVENTIONS.md` §1 decision 6).
- No push, no pull request. Both are separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `pyproject.toml` | final (frozen in wave 1) | `CONVENTIONS.md` §2, verbatim, pins re-read on the day |
| `uv.lock` | generated | `uv lock` |
| `.python-version` | final (frozen) | `3.14` |
| `Justfile` | final (frozen in wave 1) | `CONVENTIONS.md` §4, verbatim |
| `scripts/initialize.sh` | final (frozen) | `CONVENTIONS.md` §5, from A `scripts/initialize.sh` |
| `scripts/wheel_smoke.py` | working -> T02 | `CONVENTIONS.md` §9 |
| `src/rovo/__init__.py` | working -> T02 | `CONVENTIONS.md` §9 |
| `src/rovo/__main__.py` | final (frozen) | `CONVENTIONS.md` §9 |
| `src/rovo/cli.py` | working -> T02 | `CONVENTIONS.md` §9 |
| `src/rovo/py.typed` | final (frozen) | empty |
| `tests/test_api.py` | working -> T02 | `CONVENTIONS.md` §9 |
| `tests/test_cli.py` | working -> T02 | `CONVENTIONS.md` §9 |
| `tests/fixtures/py-lint-violation/ruff.py` | working -> T02 | A `tests/fixtures/py-lint-violation/ruff.py`: an unused import (F401) and a line over 99 characters (E501) |
| `tests/fixtures/py-lint-violation/mypy.py` | working -> T02 | A `tests/fixtures/py-lint-violation/mypy.py` |
| `ruff.toml` | working -> T02 | `CONVENTIONS.md` §9 "Tool settings" |
| `mypy.ini` | working -> T02 | `CONVENTIONS.md` §9 |
| `pytest.ini` | working -> T02 | `CONVENTIONS.md` §9 |
| `.coveragerc` | working -> T02 | `CONVENTIONS.md` §9 |
| `.pre-commit-config.yaml` | working -> T02 | `CONVENTIONS.md` §5, from A `.pre-commit-config.yaml` |
| `.pre-commit-fix.yaml` | working -> T02 | `CONVENTIONS.md` §5, from A `.pre-commit-fix.yaml` |
| `.markdownlint-cli2.jsonc` | working -> T02 | A `.markdownlint-cli2.jsonc`, `CONVENTIONS.md` §5 |
| `_typos.toml` | working -> T02 | A `_typos.toml`, `CONVENTIONS.md` §5 |
| `lychee.toml` | working -> T02 | A `lychee.toml`, `CONVENTIONS.md` §5 |
| `.editorconfig` | working -> T02 | A `.editorconfig`, `CONVENTIONS.md` §5 |
| `.gitattributes` | final (frozen) | A `.gitattributes`, `CONVENTIONS.md` §5 |
| `.gitignore` | final (frozen) | `CONVENTIONS.md` §5 |
| `.github/actions/setup/action.yml` | stub -> T01 | setup-uv, just, `just sync`, the prek cache, `just install-hooks` (`CONVENTIONS.md` §10), SHA-pinned |
| `.github/workflows/ci.yml` | stub -> T01 | one job `check` on `ubuntu-latest` that runs the setup action and `just check`; A's `permissions` and `persist-credentials: false` |
| `README.md` | stub -> T04 | one paragraph: what rovo is, that it is pre-release, the licence sentence of `CONVENTIONS.md` §1 decision 6 |
| `CHANGELOG.md` | stub -> T04 | an `Unreleased` heading and one line |
| `SECURITY.md` | stub -> T04 | private vulnerability reporting on GitHub; no supported release yet |
| `AGENTS.md` | stub -> T03 | the six phrases of `CONVENTIONS.md` §1 fact 2 in true sentences, the six invariants of §7, the project map; under 400 words |
| `CLAUDE.md` | final (frozen) | `@AGENTS.md` and a newline |
| `.github/copilot-instructions.md` | final (frozen) | B's adapter string, byte for byte |
| `.agents/skills/<6>/SKILL.md` | stub -> T03 | final frontmatter (`CONVENTIONS.md` §7), a body of numbered steps that names the recipes |
| `.claude/skills/<6>/SKILL.md`, `.codex/skills/<6>/SKILL.md` | final (frozen) | the canonical frontmatter and B's `BRIDGE_BODY` |
| `docs/manifest.yml` | final (frozen in wave 1) | `CONVENTIONS.md` §6, every page and decisions 0001 to 0007 |
| `docs/README.md` | final (frozen in wave 1) | the map, linking every page; decisions through `decisions/README.md` |
| `docs/**/*.md` (every other page of `CONVENTIONS.md` §6 and §8) | stub -> T04 | frontmatter equal to the manifest entry, a matching H1, at least 40 words naming what the page will say and that T04 writes it |

## Steps

1. Create the worktree (`README.md`, "How to pick up a ticket"). There is no `Justfile`
   yet, so no baseline: quote `git log --oneline -3` and `ls -A` instead.
2. **Re-read the pins.** For each package in `CONVENTIONS.md` §1 fact 7, read
   `https://pypi.org/pypi/<name>/json` (`.info.version`), and `uv --version`,
   `just --version`. If a pin moved, stop and hand back a `CONVENTIONS.md` §2 pull
   request on `main`: this ticket writes the pins that document states.
3. **The package and the manifest.** Write `pyproject.toml`, `.python-version`,
   `src/rovo/`, `tests/test_api.py`, `tests/test_cli.py` and `scripts/wheel_smoke.py`
   as `CONVENTIONS.md` §2 and §9 state. `uv lock` (network, authorised), then
   `uv sync --locked`. Prove `CONVENTIONS.md` §12 claim 1 here: quote the
   `[package.group-requires-python]` table and the `biscuit-games-tooling` marker from
   `uv.lock`, and `UV_PYTHON=3.13 UV_NO_GROUP=tooling uv run --frozen python -c
   'import sys, rovo; print(sys.version_info[:2], rovo.__version__)'`.
4. **The tool settings and fixtures.** `ruff.toml`, `mypy.ini`, `pytest.ini`,
   `.coveragerc` and the two positive-control fixtures (`CONVENTIONS.md` §9). The
   fixtures' violations are exactly F401 and E501 for ruff and one type error for mypy.
5. **The `Justfile` and `scripts/initialize.sh`**, verbatim from `CONVENTIONS.md` §4 and
   §5. Run, in order, quoting each tail and exit status: `just lock-check`,
   `just py-lint`, `just py-typecheck`, `just coverage`, `just wheel-smoke`. Then prove
   the controls fire (`CONVENTIONS.md` §12 claim 7): in a scratch copy of each fixture
   (§11 "Scratch"), remove F401's import, then E501's line, then the mypy error, and
   quote the recipe failing each time with the control's message; restore. Save each
   backup under a non-Python name (`ai_tmp/scratch/ruff.py.orig`,
   `ai_tmp/scratch/mypy.py.orig`): `.gitignore` arrives only in step 7, so until then
   `ruff check .` lints a `.py` file under `ai_tmp/` and fails before the control runs.
6. **The offline proof** (`CONVENTIONS.md` §12 claims 3, 4, 5). Under §11's network
   denial, with its negative control quoted: `just wheel-smoke`. Claim 5 is a
   before-and-after comparison, because nothing is committed yet and `.gitignore`
   arrives in step 7. Just before the run, outside the denial, write
   `git status --porcelain -- . ':!ai_tmp' > ai_tmp/scratch/status-before` and
   `shasum -a 256 uv.lock > ai_tmp/scratch/lock-before`. After the run, write the same
   two files with `-after`. `diff` each pair prints nothing and exits 0; quote both. As
   the positive control, `touch stray-file` between two snapshots makes the status
   `diff` show `?? stray-file`; quote it, then delete `stray-file`. An empty
   `git status --short` is green's test after the commit (steps 11 and 12), not this
   step's. Read the wheel's file list (`python -m zipfile -l dist/*.whl`)
   and quote it: `rovo/__init__.py`, `rovo/__main__.py`, `rovo/cli.py`, `rovo/py.typed`,
   the `.dist-info` files, and no `tests/`.

   **Adversarial review** (`CONVENTIONS.md` §14): `pyproject.toml`, `uv.lock`,
   `.python-version` and the `Justfile`, before they freeze. Ask: does any recipe reach
   the network under `just check`; can `wheel-smoke` pass on a stale or a second wheel,
   or with typer imported by the API; does `lock-check` fail on a stale lock (claim 2,
   shown with a pin edited in a scratch copy); does anything in these files assume
   pixi, maturin or Rust; would the 3.13 leg of `CONVENTIONS.md` §10 run every recipe
   it names without B.
7. **Hooks and dotfiles** (`CONVENTIONS.md` §5). Copy A's files with the stated deltas
   and no others; diff each against A's and quote the diff summary in the hand-back
   notes. `just install-hooks` (network, authorised; primary checkout only, per
   `scripts/initialize.sh` — in a secondary worktree run `uv run --frozen prek
   prepare-hooks` for both configs and then `uv run --frozen prek run lychee --files
   README.md` instead, because lychee downloads its binary at first run, not at prepare
   (`CONVENTIONS.md` §4 `install-hooks`), so that `just lint` is offline) and quote
   claim 6's outcome. Then `uv run --frozen prek run --all-files --skip validate-docs
   --skip validate-agents`: both hooks fire on `pyproject.toml`, and B's validators fail
   until steps 8 and 9 create the agent files and `docs/manifest.yml`. The full
   `just lint` runs at the end of step 9.
8. **The agent stubs** (`CONVENTIONS.md` §7). `AGENTS.md`, the six skills with final
   frontmatter, twelve bridges, the two adapters. `just check-agents` must print
   `Validated AGENTS.md, 2 adapters, and 6 skills.` (claim 10).
9. **The handbook stubs** (`CONVENTIONS.md` §6, §8). `docs/manifest.yml` in A
   `docs/manifest.yml`'s JSON-compatible form; `docs/README.md` final; every page and
   decisions 0001 to 0007 as stubs; `docs/decisions/README.md` with seven rows.
   `just check-docs`, then `just lint`, now with every hook.
10. **README, CHANGELOG, SECURITY stubs; the CI stub** (Files touched). The setup
    action's and `ci.yml`'s `uses:` lines are SHA-pinned with a version comment, read
    with `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`.
11. `just check` on the whole tree; quote the last ten lines. Commit.
12. **The fresh clone.** `git clone` the worktree into `ai_tmp/fresh/` (a local clone,
    no network), `just initialize` there (network, authorised), `just check`, quote
    the last line and `git status --short`. Delete `ai_tmp/fresh/`.

    **Adversarial review** (`CONVENTIONS.md` §14): the whole tree, before the final
    commit. Ask: does any path differ from `CONVENTIONS.md` §3; is any stub something a
    lane will have to rename or reclassify; does every positive control fire; is the
    upload guard in the built wheel's `METADATA`; is any A-specific text (pixi, cargo,
    allium, maturin) left in a copied file.
13. Commit the review's fixes; rerun step 11 and step 12, requote.
    **Authorisation required**: push the branch (no pull request; see Non-goals).

## Acceptance criteria

- `just check` ends with `All checks passed and the worktree is unchanged.` in the
  worktree and in a fresh clone, quoted with the commit.
- `just wheel-smoke` passes under the network denial with its negative control quoted,
  and its first install step has no typer.
- Each positive control was shown firing (step 5).
- `just check-agents` prints `Validated AGENTS.md, 2 adapters, and 6 skills.`
- `CONVENTIONS.md` §12 claims 1 to 8 and 10 have outcomes in the hand-back notes; claim
  9's first half has one.
- No `LICENSE` file; `rg -n -i 'licen[cs]e' pyproject.toml` matches only comments.
- The two adversarial reviews ran and every valid finding is fixed or handed back.

## Verification

```sh
git rev-parse --short HEAD
{ just check 2>&1; echo "exit $?"; } | tail -4
git status --short
uv run --frozen python -I -c 'import rovo, sys; print(rovo.__version__, "typer" in sys.modules)'
target/wheel-smoke/venv/bin/rovo --version
target/wheel-smoke/venv/bin/python -I -m rovo version
unzip -p dist/rovo-*.whl 'rovo-*.dist-info/METADATA' | rg -n 'Classifier: Private|License'
just check-agents
UV_PYTHON=3.13 UV_NO_GROUP=tooling just py-lint py-typecheck coverage wheel-smoke; echo "exit $?"
```

The third command prints `0.0.0 False`. The `METADATA` read prints the `Private :: Do
Not Upload` classifier and no `License` line. The last line passes on 3.13 without B.

## Hand-back notes

To be written by the executing agent: the pins read on the day, each `CONVENTIONS.md`
§12 claim's outcome, the diff of each copied file against A's, the offline proof with
its negative control, the fresh-clone run, the review record for each checkpoint, and
every place this ticket departed from `CONVENTIONS.md` and why.

### Part 1 evidence (uncommitted tree, base 61f2357)

Steps 1 to 6, taken on 2026-10-29 at `61f2357` with uncommitted changes, on branch
`bootstrap` in a linked worktree. Raw logs are under `ai_tmp/T00/`. Nothing is committed:
the first commit is step 11's.

**Step 1.** No `Justfile` yet, so no baseline.

```text
$ git log --oneline -3
61f2357 Merge pull request #1 from BiscuitBin/bootstrap-tickets
28eb228 tickets: address review findings on T00 scratch, early lint and T06 relock proof
57df217 tickets: bootstrap ticket set for rovo
$ ls -A
.git  README.md  tickets
```

**Step 2, the pins.** Re-read against PyPI on 2026-10-29 by the orchestrator and
unchanged from `CONVENTIONS.md` §1 fact 7 (typer 0.27.3, hatchling 1.33.0, ruff 0.17.3,
mypy 2.4.1, pytest 9.2.0, coverage 7.17.0, prek 0.5.7, uv 0.13.6, rust-just 1.59.0), so
no §2 hand-back. Locally `uv --version` prints `uv 0.13.6 (aarch64-apple-darwin)` and
`just --version` prints `just 1.59.0` (resolved at `/Users/scutting/.pixi/bin/just`).

**Step 3, the package and the manifest.** `pyproject.toml` is byte-identical to the
§2 block (`diff <(sed -n '133,212p' tickets/CONVENTIONS.md) pyproject.toml` printed
nothing). `uv lock` (network): `Resolved 23 packages`, exit 0. `uv sync --locked`:
exit 0, `.venv` on Python 3.14.8. The tests were written first: `tests/test_api.py`
failed on `AttributeError: module 'rovo' has no attribute '__version__'`, and
`tests/test_cli.py` on `ModuleNotFoundError: No module named 'rovo.cli'`; both pass
after the §9 package (`3 passed`).

Claim 1, from `uv.lock`:

```text
469:[package.group-requires-python]
470-tooling = ">=3.14"
466:    { name = "biscuit-games-tooling", marker = "python_full_version >= '3.14'" },
483:tooling = [{ name = "biscuit-games-tooling", marker = "python_full_version >= '3.14'", git = "https://github.com/steven-cutting/biscuit_games_tooling?tag=v0.3.0" }]
```

The 3.13 runs used `UV_PROJECT_ENVIRONMENT=ai_tmp/T00/venv313`, so that `.venv` stayed
on 3.14. Their first sync downloaded mypy's cp313 wheel, so they are not part of the
offline claims.

```text
$ uv sync --frozen --python 3.13
error: The requested interpreter resolved to Python 3.13.13, which is incompatible with the project's Python requirement: `>=3.14` (from `tool.uv.dependency-groups.tooling.requires-python`).
exit 2
$ UV_PYTHON=3.13 UV_NO_GROUP=tooling uv run --frozen python -c 'import sys, rovo; print(sys.version_info[:2], rovo.__version__)'
(3, 13) 0.0.0
exit 0
$ UV_PYTHON=3.13 UV_NO_GROUP=tooling just lock-check py-lint py-typecheck coverage wheel-smoke
...
TOTAL                     17      0      2      0   100%
wheel_smoke api: rovo 0.0.0, no CLI module imported, py.typed shipped
wheel_smoke cli: rovo 0.0.0
rovo 0.0.0
exit 0
```

Claim 1 holds: the group floor locks, syncs on 3.14, refuses 3.13 naming the floor, and
every `floor` recipe passes on 3.13 without B.

**Step 4, tool settings and fixtures.** As §9 states, with two departures recorded
below. The ruff fixture has exactly F401 and E501 (its long line is 116 characters);
the mypy fixture has one `[assignment]` error.

**Step 5, the gates.** `Justfile` is lines 287-442 of `CONVENTIONS.md` verbatim;
`just --list` parses it. Each gate's tail:

```text
$ just lock-check
Resolved 23 packages in 13ms
exit 0
$ just py-lint
All checks passed!
16 files already formatted
exit 0
$ just py-typecheck
Success: no issues found in 6 source files
tests/fixtures/py-lint-violation/mypy.py:2: error: Incompatible types in assignment (expression has type "str", variable has type "int")  [assignment]
exit 0
$ just coverage
TOTAL                     17      0      2      0   100%
exit 0
$ just wheel-smoke
wheel_smoke cli: rovo 0.0.0
rovo 0.0.0
exit 0
```

Claim 9, first half: `coverage combine --quiet` succeeds with data from one process
(`just coverage` above).

Claim 7, each control removed in turn from the fixture (backups at
`ai_tmp/scratch/ruff.py.orig` and `ai_tmp/scratch/mypy.py.orig`, restored after, `cmp`
clean):

```text
## ruff.py without F401
tests/fixtures/py-lint-violation/ruff.py:4:100: E501 Line too long (116 > 99)
py-lint: the positive control did not fire (exit 1 naming F401 and E501)
exit 1
## ruff.py without E501
tests/fixtures/py-lint-violation/ruff.py:2:8: F401 [*] `os` imported but unused
py-lint: the positive control did not fire (exit 1 naming F401 and E501)
exit 1
## mypy.py without the error
py-typecheck: the positive control did not fire
exit 1
```

Claim 7 holds for T00: ruff and mypy lint an explicitly named, config-excluded file.

Claim 2, in a scratch copy at `ai_tmp/T00/stale/` (`pyproject.toml`, `uv.lock`,
`.python-version`, `README.md`, `src/rovo/`): `uv lock --check --offline` exits 0 as
copied, then with `pytest==9.2.0` edited to `pytest==9.1.1`:

```text
error: The lockfile at `uv.lock` needs to be updated, but `--check` was provided.
exit 1
```

That is uv's staleness message, not an offline-resolution error. Claim 2 holds.

**Step 6, the offline proof.** One `sandbox-exec -p '(version 1)(allow default)(deny
network*)' /bin/sh -c ...` invocation ran the negative control and then
`/Users/scutting/.pixi/bin/just wheel-smoke`:

```text
## negative control
curl: (6) Could not resolve host: pypi.org
curl exit 6
## just wheel-smoke
rm -rf dist
uv build --offline --out-dir dist
Successfully built dist/rovo-0.0.0.tar.gz
Successfully built dist/rovo-0.0.0-py3-none-any.whl
 + rovo==0.0.0 (from file:///Users/scutting/.supacode/repos/rove/bootstrap/dist/rovo-0.0.0-py3-none-any.whl)
wheel_smoke api: rovo 0.0.0, no CLI module imported, py.typed shipped
Installed 7 packages in 10ms
 + typer==0.27.3
wheel_smoke cli: rovo 0.0.0
rovo 0.0.0
wheel-smoke exit 0
```

Claims 3 and 4 hold: hatchling came from the cache, and both installs ran offline; the
first install step installed `rovo` alone, with no typer. The console script's
`rovo --version` is the last line (claim 8, below).

Claim 5, snapshots taken outside the denial just before and after the run
(`.gitignore` already existed, so `':!ai_tmp'` is redundant but kept as the step
writes it):

```text
$ diff ai_tmp/scratch/status-before ai_tmp/scratch/status-after
exit 0
$ diff ai_tmp/scratch/lock-before ai_tmp/scratch/lock-after
exit 0
2d1a0cbd924460e4ba606dbf06e8928c5f7a11fbd708fc8f9e29c5e43115d85e  uv.lock
## stray-file control
10a11
> ?? stray-file
exit 1
```

`stray-file` was deleted after. The §14 review (B3) found that this evidence is too weak.
With nothing tracked, `git status --porcelain` lists untracked paths by name only and
collapses `scripts/`, `src/` and `tests/`, so a file rewritten in place or a new file
inside those directories would not show up. A re-run under the same denial (negative
control `curl exit 6`, `wheel-smoke exit 0`, same output as above) took snapshots
outside the denial, just before and just after the run. It used
`git status --porcelain --untracked-files=all -- . ':!ai_tmp'` (21 lines) and
`git ls-files -z --cached --others --exclude-standard -- . ':!ai_tmp' | xargs -0 shasum -a 256`
(30 files, `uv.lock` included):

```text
$ diff status-b3-before status-b3-after
exit 0
$ diff content-b3-before content-b3-after
exit 0
## status control: touch scripts/stray-file between snapshots
10a11
> ?? scripts/stray-file
exit 1
## content control: stray-file rewritten x -> y between snapshots
15c15
< 2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881  stray-file
---
> a1fce4363854ff888cff4b8e7875d600c2682390412a8cf79b37d0b11148b0fa  stray-file
exit 1
```

The status diff for the content control was empty (exit 0), so only the content snapshot
catches an in-place rewrite. Both stray files were deleted afterwards. Claim 5 holds.
The step 6 commands in the ticket body still prescribe the weaker snapshot; that text
is not hand-back notes, so it stays as written. The wheel:

```text
rovo/__init__.py
rovo/__main__.py
rovo/cli.py
rovo/py.typed
rovo-0.0.0.dist-info/METADATA
rovo-0.0.0.dist-info/WHEEL
rovo-0.0.0.dist-info/entry_points.txt
rovo-0.0.0.dist-info/RECORD
```

No `tests/`. `METADATA` matches `6:Classifier: Private :: Do Not Upload` and no
`License` line. The sdist holds `src/rovo/`, `tests/`, `README.md`, `pyproject.toml`,
`PKG-INFO` and `.gitignore`; hatchling skipped the missing `CHANGELOG.md` silently.

**Recipes not runnable yet.** `py-test` and `build` pass. `lint`, `check-docs` and
`check` exit 2 on `No prek.toml or .pre-commit-config.yaml found` (step 7);
`check-agents` exits 1 on `.agents/skills is missing` (step 8); `check` ran
`lock-check` green first. `install-hooks` and `fix` were not run: this is a secondary
worktree, and `install-hooks` would write a shim into the shared `.git/hooks`.

**Departures in part 1.**

- `ruff.toml` ignores `CPY001` too, commented: ruff 0.17.3 reports it on every file
  under `select = ["ALL"]`, and there is no notice to write while the licence is
  undecided (decision 0006). §9 lists only `COM812` and `ISC001`, and following it
  literally turns `py-lint` red, so the `CPY001` ignore is handed back under §11 as a
  `CONVENTIONS.md` §9 amendment (see Open points).
- `tests/fixtures/py-lint-violation/mypy.py` holds one error, not A's two, as step 4
  says, so removing it is a real test of the control. The ruff fixture's comment says
  99 characters, not A's 100.
- ruff 0.17.3's `ruff format` also formats Python blocks inside Markdown: the 16 files
  are the 7 Python files plus 9 under `tickets/` and `README.md`. A probe file
  `ai_tmp/T00/fmt.md` holding a `python` block with `x=1` gave `+x = 1` and
  `1 file would be reformatted`, exit 1. So `just format` can rewrite Markdown under
  `docs/` and `tickets/`; T02 decides whether `ruff.toml` should exclude it.
- `.gitignore` landed in part 1, ahead of step 7, so that `ai_tmp/` was ignored from
  the start. It is A's minus the Rust, pixi, `.tools/` and maturin blocks, with the
  `target/` and `dist/` comments reworded for the coverage report, the wheel smoke and
  `just build`, plus `.coverage`, `.coverage.*` and `coverage.xml`. Part 2 gives a
  diff summary against A with the other §5 files.
- `scripts/initialize.sh` is mode `100755`, as A's is.
- Claim 8 holds: the console script's `rovo --version` is wheel-smoke's last line, and
  bare `rovo` prints help and exits 2. Claim 6 is untouched in part 1 (no hooks yet).
- `RUSTUP_TOOLCHAIN=stable` was not needed in part 1: nothing here builds with cargo.

### Part 2 evidence (uncommitted, base 61f2357)

Step 7, taken on 2026-10-29 at `61f2357` with uncommitted changes, in the same linked
worktree. Every shell exported `RUSTUP_TOOLCHAIN=stable` unless noted. The orchestrator's
brief requires this because rustup has no default toolchain on this machine, and it
is recorded here as a departure from this ticket. Raw logs are
under `ai_tmp/T00/`. Nothing is committed.

**The copied files, diffed against A.** Each diff is
`diff <(git -C <A> show c8e1a46:<path>) <path>`. All exit 1, with §5's deltas and the
departures listed below.

`.pre-commit-config.yaml`:

```text
1,2c1,2
< # pixi.lock is YAML, so without this line the builtin check-yaml would parse
< # the whole lockfile on every commit.
---
> # uv.lock is TOML and large, so without this line the builtin check-toml would
> # parse the whole lockfile on every commit.
6c6
<     \.pixi/|
---
>     \.venv/|
9d8
<     \.tools/|
11,14c10
<     target/wheel-smoke/|
<     tests/fixtures/parity/.*\.allium$|
<     Cargo\.lock$|
<     pixi\.lock$
---
>     uv\.lock$
19,45c15,18
< (A's Rust comment, then the fmt-check, toml-check and deps-unused hooks)
---
>       # Python hooks run through `just`: a git hook does not inherit the
>       # Justfile's environment, so routing through the recipe is what lets a
>       # hook find ruff and mypy through `uv run --frozen`, and it keeps each
>       # tool's arguments and positive control in exactly one place.
62c35
<         entry: pixi run --frozen bg-validate-docs
---
>         entry: uv run --frozen bg-validate-docs
69c42
<         entry: pixi run --frozen bg-validate-agents
---
>         entry: uv run --frozen bg-validate-agents
169c142
<         entry: .pixi/envs/default/bin/bg-ripsecrets
---
>         entry: .venv/bin/bg-ripsecrets
```

`target/wheel-smoke/` is dropped because `target/` covers it and §5's exclude list
does not name it. Every third-party `rev` and comment is A's.

`.pre-commit-fix.yaml`: the same exclude delta (A already lists
`tests/fixtures/py-lint-violation/`, which stays). `cargo-fmt`, `taplo-fmt` (with its
PATH comment) and `cargo-shear-fix` are deleted. The two ruff entries change from
`.pixi/envs/default/bin/ruff` to `.venv/bin/ruff`. The header's lockfile comment is
reworded too: A's named `check-yaml`, which this config does not run, and the
exclude matters here for `end-of-file-fixer` and `trailing-whitespace`. Nothing else
changes.

Dotfiles:

```text
=== .editorconfig
11,16d10   [*.rs] section and its rustfmt/taplo comment
20,24d13   [*.allium] section and its comment
29,33d17   [LICENSE] section and its Apache-2.0 comment
=== .gitattributes
2,4d1
<
< Cargo.lock linguist-generated=true
< pixi.lock merge=binary linguist-language=YAML linguist-generated=true -diff
=== .markdownlint-cli2.jsonc
17c17
<   "ignores": ["target", ".tools", ".pixi", "ai_tmp"]
---
>   "ignores": ["target", ".venv", "ai_tmp"]
=== _typos.toml
5,6c5,6    the extend-exclude comment, reworded for one lockfile
8,12d7     tests/fixtures/parity/, Cargo.lock, pixi.lock, .pixi/, .tools/ removed
14a10      "uv.lock" added
(end)      cpy = "cpy" added to [default.extend-words], with a comment
=== lychee.toml
6c6
< exclude_path = [".git", ".pixi", "ai_tmp", "target", ".tools"]
---
> exclude_path = [".git", "ai_tmp", "target"]
```

`.gitignore` (written in part 1):

```text
25,28c25,28   the target/ comment: coverage report and wheel smoke, not cargo
31,55c31      .pixi/, .tools/, *.profraw, lcov.info, mutants.out*/, *.snap.new,
              *.pending-snap and their comments removed; dist/ comment reworded
57,58d32      crates/alliumpy/python/alliumpy/*.so and *.pyd removed
60c34         Python block comment names the uv environment and coverage data
66a41,43      .coverage, .coverage.*, coverage.xml added
```

**Departures in part 2.**

- `.editorconfig` also drops A's `[LICENSE]` section. §5 names only the Rust and Allium
  sections, but this repository has no `LICENSE` (decision 6). The section's comment
  also asserts an Apache-2.0 text that has not been decided.
- `.markdownlint-cli2.jsonc` puts `.venv` in place of `.pixi` in `ignores`, which §5
  does not state. markdownlint-cli2 appends the config's `**/*.md` glob to the
  filenames prek passes, so without the change it lints `.venv`. As a control, A's
  `ignores` were restored in a scratch copy (backup
  `ai_tmp/scratch/mdl.jsonc.orig`, restored, `cmp` clean) and
  `prek run markdownlint-cli2 --files README.md` was run:
  `Linting: 13 files`, then `MD031` and `MD012` errors in
  `.venv/lib/python3.14/site-packages/typer/.agents/skills/typer/SKILL.md`, exit 1.
  `lychee.toml` gets no `.venv`: lychee reads only the files prek passes.
- `_typos.toml` adds `cpy = "cpy"`. The `CPY001` ignore in `ruff.toml` (part 1's
  departure, handed back) and this ticket's notes about it otherwise fail `typos`
  ("`CPY` should be `COPY`, `CPU`"). The extend-exclude comment is reworded because A's
  named vendored reference and tool directories. A's `mis`/`als` words and their
  comments are kept as A has them.
- `scripts/initialize.sh`'s secondary-worktree branch now prepares the hooks (B2,
  below). This is a departure from A and from §5, and it stays handed back under Open
  points.

**B2, `scripts/initialize.sh`.** Diff against A, beyond part 1's uv-for-pixi lines:

```text
44a24,28
> # A secondary worktree skips only the shim: it still prepares both hook
> # configurations and runs lychee once, as install-hooks does, because lychee
> # downloads its binary at first run, not at prepare. Without this, the first
> # `just lint` in a fresh worktree would reach the network. lychee's exit
> # status is lint's business, not this script's.
49a34,36
>     uv run --frozen prek prepare-hooks
>     uv run --frozen prek prepare-hooks --config .pre-commit-fix.yaml
>     uv run --frozen prek run lychee --files README.md || :
```

It works from a cold cache. With an empty `PREK_HOME=$PWD/ai_tmp/T00/prek-home`,
`sh scripts/initialize.sh` ended:

```text
Secondary worktree: skipping install-hooks.
Run just install-hooks once from the primary checkout.
lychee...................................................................Passed

Ready. Next: just check.
Nothing has been formatted, staged, committed, tagged, or pushed.
initialize exit 0
```

That home then held `hooks/rust-*/bin/ripsecrets` and
`repos/909c8f3d3d713742/.cargo/bin/lychee-0.24.2`. Next, one `sandbox-exec -p
'(version 1)(allow default)(deny network*)' /bin/sh -c ...` invocation used the same
home. It ran the negative control, then
`uv run --frozen prek run --skip validate-docs --skip validate-agents --files <every
tracked and untracked, non-ignored file outside ai_tmp/>` (36 files):

```text
curl: (6) Could not resolve host: pypi.org
curl exit 6
py-lint..................................................................Passed
py-typecheck.............................................................Passed
Documentation contract..................................................Skipped
Agent instruction contract..............................................Skipped
check for added large files..............................................Passed
check for case conflicts.................................................Passed
check that executables have shebangs.....................................Passed
check json...........................................(no files to check)Skipped
check for merge conflicts................................................Passed
check that scripts with shebangs are executable..........................Passed
check toml...............................................................Passed
check yaml...............................................................Passed
detect private key.......................................................Passed
EditorConfig.............................................................Passed
markdownlint.............................................................Passed
typos....................................................................Failed
lychee...................................................................Passed
shellcheck...............................................................Passed
Lint GitHub Actions workflow files...................(no files to check)Skipped
ripsecrets...............................................................Passed
prek exit 1
```

The one `typos` error is `tickets/T02-python-gate.md:112`, an example misspelling in
another ticket (see Open points). Every hook environment came from the cache that
`initialize.sh` filled, and no hook reached the network. `sh scripts/initialize.sh`
was then run once against the default `~/.cache/prek` (`initialize exit 0`), so the
`just` recipes below use it.

Both B validators fire on `pyproject.toml`, as step 7 expects:

```text
$ uv run --frozen prek run validate-docs validate-agents --files pyproject.toml
Documentation contract...................................................Failed
  docs validation: manifest.yml: cannot read JSON-compatible YAML: [Errno 2] No such file or directory: '.../docs/manifest.yml'
Agent instruction contract...............................................Failed
  agent validation: .agents/skills is missing
exit 1
```

**Claim 6.** `just install-hooks` was not run, because this is a secondary worktree.
`ls -la` of the common `.git/hooks` (`/Users/scutting/projects/biscuitbin/rove/.git/hooks`)
was taken before and after all of part 2. `diff` printed nothing and exited 0: only the
`*.sample` files, no shim. `git config core.hooksPath` is unset (exit 1). What was
proven instead, with the same `prepare-hooks` that `install-hooks` runs:

- With `RUSTUP_TOOLCHAIN=stable` and a cold `PREK_HOME`, prek built ripsecrets with
  the machine's rustup toolchain. `hooks/rust-*/.prek-hook.json` records
  `"language_version": "1.98.1"` and
  `"toolchain": "/Users/scutting/.rustup/toolchains/stable-aarch64-apple-darwin/bin/rustc"`.
- As the negative control, the same run in a fresh `ai_tmp/T00/prek-home-neg` without
  `RUSTUP_TOOLCHAIN` also succeeded (`initialize exit 0`), but with a different
  compiler. The record says `"language_version": "1.96.0"` and
  `"toolchain": "/Users/scutting/.pixi/bin/rustc"`. Observed facts:
  `~/.cargo/bin/rustc` comes first on PATH, and `rustup default` prints
  `no default toolchain is configured`. Inferred, because `prek.log` recorded nothing:
  prek skipped the failing rustup proxy and used the pixi-global rustc later on PATH.
  So prek uses a working rustc from PATH, not specifically rustup's. No toolchain landed in either home's `tools/`
  (only `go` and `node`).

Not proven here: `just install-hooks` itself, meaning the shim and
`--prepare-hooks` through the recipe, which needs the primary checkout. The macOS and
Ubuntu runner half belongs to T01. The `rust` hook language may also download a
toolchain when the machine has none; that path was not exercised, because this
machine has one.

**`just lint`** (default prek home, no denial):

```text
py-lint..............................................(no files to check)Skipped
py-typecheck.........................................(no files to check)Skipped
Documentation contract...................................................Failed
  docs validation: manifest.yml: cannot read JSON-compatible YAML: [Errno 2] No such file or directory: '.../docs/manifest.yml'
Agent instruction contract...........................(no files to check)Skipped
(every builtin, EditorConfig, markdownlint, lychee, ripsecrets: Passed or Skipped)
typos....................................................................Failed
error: recipe `lint` failed on line 65 with exit code 1
just lint exit 1
```

`--all-files` sees only the tracked `README.md` and `tickets/` until step 11's commit,
so most hooks skip here. The `--files` run above is the real evidence. `validate-docs`
fails until step 9. `validate-agents` skips because no tracked file matches it. The
`typos` failure is the T02 ticket line.

**`just fix`.** Both fix-config passes passed every hook, then its `just lint` failed
as above: `just fix exit 1`. A content snapshot
(`git ls-files -z --cached --others --exclude-standard -- . ':!ai_tmp' | xargs -0 shasum -a 256`)
and an `-uall` status snapshot, taken before and after, both `diff` clean (exit 0), so
`fix` rewrote nothing. The fix config was also run over every file with `--files` (all
36): `ruff-format`, `ruff-fix`, `fix end of files`, `trim trailing whitespace` and
`markdownlint fix` all passed, exit 0. The content snapshot was unchanged, so the
positive-control fixtures were not stripped. `just py-lint` still exits 0 afterwards.

### Part 3 evidence (uncommitted, base 61f2357)

Steps 8 to 10, taken on 2026-10-29 at `61f2357` with uncommitted changes, in the same
linked worktree, with `RUSTUP_TOOLCHAIN=stable` exported. Raw logs are under
`ai_tmp/T00/p3-*`. Nothing is committed.

**Step 8, the agent stubs.** `CLAUDE.md`, `.github/copilot-instructions.md` and the ten
bridges of the five skills whose description is A's were written with
`git -C <A> show c8e1a46:<path> > <path>`. Each `cmp`s clean against A. `python-change`'s
two bridges carry the §7 description and B's `BRIDGE_BODY`, read from B
`src/biscuit_games_tooling/validate_agents.py` at `6c5c07f`. Each canonical skill's
frontmatter is its bridge's lines 1 to 4. Its body is a stub of numbered steps that
names its recipes, cites `AGENTS.md`, and says that T03 replaces it. `AGENTS.md` has
372 words (B wants at least 300, this ticket fewer than 400). It carries the six phrases
and a project map, and its `## Invariants` list is byte-identical to `CONVENTIONS.md`
lines 575-587 (`diff` exit 0). It has no `<important if>` blocks yet, because those are
T03's.

```text
$ just check-agents
uv run --frozen bg-validate-agents
Validated AGENTS.md, 2 adapters, and 6 skills.
exit 0
```

Claim 10 holds: there is no `.claude/settings.json`, and B accepts six skills and its
adapter strings.

**Step 9, the handbook stubs.** `docs/manifest.yml` was generated from one table in §6
and §8 order (23 pages, then the seven records, 31 entries). It is written as
`json.dumps(indent=2)` plus a newline, the form A's manifest round-trips to exactly.
Each stub's frontmatter is written from the same entry, so it cannot drift. Each stub
says what the page will cover and that it is a stub T04 writes, so T04's
`rg 'stub|T04 writes'` control fires on it. `docs/README.md` is final and links every
non-decision page. The records are reached through `decisions/README.md`, whose table
has seven rows. `rg -n -i 'stub|T04 writes' docs/README.md docs/manifest.yml` exits 1,
so the two frozen files will not trip T04's check.

```text
$ just check-docs
uv run --frozen prek run --all-files markdownlint-cli2 typos lychee
markdownlint.............................................................Passed
typos....................................................................Passed
lychee...................................................................Passed
uv run --frozen bg-validate-docs
Validated 31 pages and 31 canonical topics.
exit 0
```

`just lint` exits 0, but as part 2 noted, `--all-files` sees only tracked files, so most
hooks skip. The real evidence is every hook over
`git ls-files -z --cached --others --exclude-standard -- . ':!ai_tmp'` (93 files),
through `xargs -0 uv run --frozen prek run --files`:

```text
py-lint..................................................................Passed
py-typecheck.............................................................Passed
Documentation contract...................................................Passed
Agent instruction contract...............................................Passed
check json...........................................(no files to check)Skipped
(every other builtin, EditorConfig, markdownlint, typos, lychee, shellcheck: Passed)
Lint GitHub Actions workflow files.......................................Passed
ripsecrets...............................................................Passed
exit 0
```

`typos` passes on `tickets/T02-python-gate.md` as reworded by the orchestrator (below).
This run was not under the network denial.

**Step 10, README, CHANGELOG, SECURITY and CI.** `README.md` is one paragraph: what
rovo is, that it is pre-release, and the licence sentence of decision 6. `CHANGELOG.md`
has an `Unreleased` heading and one line. `SECURITY.md` points to private vulnerability
reporting and says there is no supported release. Each says that it is a stub T04
writes. Every remote `uses:` was read with `gh api repos/<o>/<r>/git/ref/tags/<tag>`
on 2026-10-29. The tags are the newest releases (`gh api .../releases/latest`), and all
three refs are lightweight (`object.type` is `commit`), so nothing needed
dereferencing:

```text
astral-sh/setup-uv v10.3.3  commit 68559e99cc807c1eb7e9238fd43a15bba460eec2
actions/checkout   v7.0.1   commit 3d3c42e5aac5ba805825da76410c181273ba90b1
actions/cache      v6.1.0   commit 55cc8345863c7cc4c66a329aec7e433d2d1c52a9
```

The checkout and cache SHAs equal A's. The setup action runs setup-uv (`version:
'0.13.6'`, cache on `uv.lock`), exports the `python-version` input (default `3.14`) as
`UV_PYTHON` through `env:`, installs `rust-just==1.59.0` with `uv tool install` and adds
`uv tool dir --bin` to `$GITHUB_PATH`, then runs `just sync`, caches `~/.cache/prek`
keyed on both prek configurations, and runs `just install-hooks`. `ci.yml` has one job,
`check`, on `ubuntu-latest`: the checkout with `persist-credentials: false`, the setup
action, then `just check`. It keeps A's `on`, `permissions: contents: read` and
`concurrency` block with their comments. actionlint passed it (above). Not run on a
runner: the first run is after the push (claim 11, T01).

**`just check`** on the whole uncommitted tree (`ai_tmp/T00/p3-check.log`). Every recipe
of the `recipes` list ran in order (`==> just lock-check` to `==> just check-agents`):

```text
==> just check-agents
uv run --frozen bg-validate-agents
Validated AGENTS.md, 2 adapters, and 6 skills.

==> just check-clean
uv run --frozen bg-project-check clean "$1"
The worktree matches the check baseline.

All checks passed and the worktree is unchanged.
exit 0
```

Nothing in `check-clean` failed on the untracked files: it compares against the
baseline taken at the start of the run, which already held them. So this run shows that
no recipe changed the worktree. It does not show a clean tree: `git status --short`
lists `README.md`, both edited tickets and every new path as modified or untracked. Its
`lint` step also saw only tracked files, as above. Green as §11 defines it waits for
step 11's commit. These notes were written after that run. Afterwards
`uv run --frozen prek run --files tickets/T00-foundation.md` passed every hook (exit 0).
After the run, the second paragraph of `docs/README.md` was also cut to its first
sentence. That page is frozen, and the cut sentence described the repository as it is
today. `bg-validate-docs` and the hooks on that file were re-run afterwards (below).

```text
$ uv run --frozen bg-validate-docs
Validated 31 pages and 31 canonical topics.
exit 0
$ uv run --frozen prek run --files docs/README.md tickets/T00-foundation.md
(every hook Passed or Skipped)
exit 0
```

**Departures in part 3.**

- `tickets/T02-python-gate.md:112` was reworded by the orchestrator, not by this
  ticket. The deliberate misspelling example is now described ("`the` with its last two
  letters swapped") instead of written out. `typos` flagged the literal word, and
  allow-listing it in `_typos.toml` would stop T02's negative control from firing. The
  edit is to another lane's file, before that lane starts.
- Three manifest choices §6 and §8 leave open freeze with the manifest. Titles are A's
  for every page whose path A has. `reference/cli.md`, which A lacks, is titled
  `Command-line reference` and takes `reference/api.md`'s audiences. Record titles are
  `Decision NNNN: <§8 title>`, and 0004's is `Hook runner and checkers`, without §8's
  "(adapted from A's 0002)" note. `decisions/README.md` takes A's slug,
  `decision_index`, and the seven records take A's record audiences,
  `[contributor, maintainer, agent]`.
- `README.md` replaces the repository's `# rove` stub, and its heading is `# rovo`, the
  distribution's name. It is also the wheel's `readme`, so the wheel's `METADATA` now
  carries it.
- The CI stub's `check` job sets `timeout-minutes: 30`, a value §10 does not state. The
  setup action keeps A's comment on `install-hooks`.

## Open points

- Whether `rovo` with no arguments should print help and exit 0 or 2. Typer's
  `no_args_is_help` decides it today; T02 pins the behaviour in a test and records
  which.
- Hand-back, `CONVENTIONS.md` §9 (§14 review C2/B4): change the ruff bullet to
  `ignore = ["COM812", "ISC001", "CPY001"]`. Comment the last entry "no copyright notice
  while the licence is undecided (decision 0006)", add it to the "Deltas from A", and
  have the release ticket that adds the licence lift it. `ruff.toml` already carries it.
- Hand-back, `CONVENTIONS.md` §4 `install-hooks` (§14 review C1/B1, inherited from A):
  the leading `-` on `uv run --frozen prek run lychee --files README.md` also hides a
  failed first-run download, so `install-hooks` can succeed with no lychee binary and
  the next `just lint` needs the network (§11). Proposed: keep the line, and after it
  fail when no `repos/*/.cargo/bin/lychee-<LYCHEE_VERSION>` executable exists under
  `prek cache dir`. Say in the comment that this checks that the binary is present, not
  what lychee reports, and that the version must equal `LYCHEE_VERSION` in
  `.pre-commit-config.yaml`. T00 copies the amended §4 recipe verbatim.
- Hand-back, `CONVENTIONS.md` §5 `scripts/initialize.sh` (§14 review B2, inherited from
  A). Applied in T00's `scripts/initialize.sh` in part 2: the secondary-worktree branch
  keeps A's two messages, then runs `uv run --frozen prek prepare-hooks`, the same with
  `--config .pre-commit-fix.yaml`, and `uv run --frozen prek run lychee --files
  README.md || :` (evidence under part 2). It stays a hand-back because §5 prescribes
  that branch as A's, and §5 wins over this ticket. The §5 text should say: "in a
  secondary worktree, skip only the shim; prepare both hook configurations and run
  lychee once, as `install-hooks` does". Optional §4 amendment: a shared
  `prepare-hooks` recipe that both `install-hooks` and this branch call. If C1/B1's
  lychee-binary check lands, add it to this branch too, because `|| :` hides a failed
  download here just as the recipe's `-` does.
- For the orchestrator (not T00's file): `tickets/T02-python-gate.md:112` writes a
  deliberate misspelling of "the" as its example. `typos` flags it, so `just lint` and
  `just check-docs` stay red until that line changes. §13 says ticket prose must pass
  typos. This is the only `typos` finding left in the tree.
- `just lint` before step 11's commit: `prek run --all-files` lists files with Git, so
  it sees only tracked files (`README.md` and `tickets/`). Every hook on the untracked
  files skips with "no files to check". Part 2 therefore proves the hooks with
  `--files` over `git ls-files --cached --others --exclude-standard`. The real
  `just lint` evidence comes after the commit.
