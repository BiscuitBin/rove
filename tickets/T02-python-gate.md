---
id: T02
title: "Python quality gate: ruff, mypy, pytest, coverage, the wheel, the text gates"
status: open
depends_on: [T00]
parallel_with: [T01, T03, T04]
branch: ticket/t02-python-gate
estimated_size: M
---

# T02: Python quality gate: ruff, mypy, pytest, coverage, the wheel, the text gates

## Context

T00 left working tool settings that make `just check` green on a placeholder package.
This ticket makes each gate strict and proves that each one can fail: ruff with every
rule, mypy strict, pytest strict with a coverage floor on the combined line-and-branch
total, the command tested both in-process and through the installed console script, the
wheel's contents asserted, and the text gates (typos, markdownlint, editorconfig, lychee
offline) shown to fire. A's T03 did this for alliumpy's Python surface (A
`tickets/T03-python-gate.md`; the results are A `ruff.toml` and A `mypy.ini`); W
`template/pyproject.toml.jinja` holds the pytest and coverage settings this repository
adopts (`CONVENTIONS.md` §9).

The `Justfile` is frozen: every gate's recipe already exists, and this ticket changes
what the recipes read, never the recipes. A gate that cannot be made to fire without a
recipe change is handed back.

## Goal

Every file T00 marked `working -> T02` is final; each of the gates `py-lint`,
`py-typecheck`, `coverage`, `wheel-smoke` and the four text hooks has a quoted negative
control (a deliberate defect in a scratch copy makes it fail with the expected message)
next to its passing run; and the wheel smoke asserts the wheel's contents and metadata,
not just that it imports.

## Non-goals

- No new runtime dependency, no new dev tool (`CONVENTIONS.md` §11).
- No product behaviour; the API and command stay placeholders, with tests.
- No change to the hook ids the `Justfile` names (`CONVENTIONS.md` §5).

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `ruff.toml` | final | `CONVENTIONS.md` §9; every ignore commented |
| `mypy.ini` | final | `CONVENTIONS.md` §9, plus `warn_unreachable` and `warn_redundant_casts` (W) |
| `pytest.ini` | final | `CONVENTIONS.md` §9 |
| `.coveragerc` | final | `CONVENTIONS.md` §9, plus subprocess measurement if step 4 needs it |
| `src/rovo/__init__.py` | final | docstrings; unchanged behaviour |
| `src/rovo/cli.py` | final | docstrings, help text; unchanged behaviour |
| `tests/test_api.py` | final | step 3 |
| `tests/test_cli.py` | final | step 4 |
| `tests/conftest.py` | new | only if step 4 needs a fixture for the installed script |
| `scripts/wheel_smoke.py` | final | step 5 |
| `tests/fixtures/py-lint-violation/ruff.py`, `mypy.py` | final | the controls, each violation commented |
| `.pre-commit-config.yaml`, `.pre-commit-fix.yaml` | final | step 6 |
| `.markdownlint-cli2.jsonc`, `_typos.toml`, `lychee.toml`, `.editorconfig` | final | step 6 |

## Steps

1. Create the worktree; `just initialize`; `just check` baseline.
2. **ruff and mypy.** Tighten `ruff.toml` and `mypy.ini` to `CONVENTIONS.md` §9 and fix
   what they find in `src/`, `tests/` and `scripts/`. Each per-file ignore carries a
   comment saying why that rule is wrong for that path; no blanket ignore of a whole
   family. Run `just py-lint` and `just py-typecheck`.
3. **The API test.** `tests/test_api.py` asserts, in a subprocess under `python -I`, that
   `import rovo` leaves `typer`, `rich` and `click` out of `sys.modules`, that
   `rovo.__all__` is exactly `["__version__"]`, and that `rovo.__version__` equals
   `importlib.metadata.version("rovo")`. A test named for invariant 1 of
   `CONVENTIONS.md` §7.
4. **The CLI tests.** In-process through `typer.testing.CliRunner`: `--version`,
   `version`, `--help`, no arguments (pin T00's open point: the exit code Typer gives),
   an unknown command (exit 2, message on stderr). Out-of-process: the installed
   console script (`shutil.which("rovo")` inside the `.venv`, asserted non-`None`) and
   `python -m rovo`, each `--version`. If subprocess coverage needs
   `[run] patch = subprocess` in `.coveragerc` (INI syntax, not a TOML list;
   `CONVENTIONS.md` §12 claim 9), set it and quote the before and after reports.
5. **The wheel smoke.** `scripts/wheel_smoke.py api` additionally asserts, from
   `importlib.metadata`: leaving out the `.dist-info/` entries and the one generated
   console script the installer records (`../../../bin/rovo`), the file list is exactly
   the four `rovo/` files (no tests, no fixtures), and nothing else is recorded outside
   `rovo/` and `rovo-<version>.dist-info/`; `Requires-Python` is `>=3.13`; the
   `Private :: Do Not Upload` classifier is present (`CONVENTIONS.md` §9 "The upload
   guard"); no `License-Expression` and no `License-File`; the console script entry
   point `rovo = rovo.cli:app`. `cli` additionally runs the `rovo` script beside
   `sys.executable` and compares its output with `python -m rovo`'s.

   **Adversarial review** (`CONVENTIONS.md` §14): the gate settings and tests, focused
   on negative controls, before step 6. Ask, for each gate: what defect would it miss;
   is there an ignore or exclude that empties it; does the report show an untested branch
   of `cli.py` as a partial branch (the floor is a combined total, so it alone need not
   catch one); would `wheel_smoke.py` pass on a wheel that bundles `tests/` or lacks
   `py.typed`; does any test pass on 3.14 and fail on 3.13.
6. **The text gates.** Tune `.pre-commit-config.yaml`, `.pre-commit-fix.yaml` and the four
   dotfiles to this repository (A's settings are the start). Keep the hook ids the
   `Justfile` names.
7. **Negative controls.** In scratch copies (`CONVENTIONS.md` §11 "Scratch"), one at a
   time, each restored before the next, quote the failing run and its message:
   - `src/rovo/__init__.py` gains `import typer` → `just coverage` fails on the API test,
     and `just wheel-smoke` fails at its `api` step; then, instead, `try: import typer` /
     `except ModuleNotFoundError: pass` → `just wheel-smoke` still fails at its `api` step,
     naming the recorded import attempt.
   - a branch added to `cli.py` with no test → `just coverage` lists it as a partial branch
     (`->` in the Missing column), which proves branches are measured.
   - `just coverage_floor=100 coverage` on an incompletely covered scratch → it fails with
     coverage's `Coverage failure: total of ... is less than fail-under=100`, which proves
     the floor bites.
   - an `Any`-returning function in `src/` → `just py-typecheck` fails.
   - `print()` in `src/rovo/cli.py` → `just py-lint` fails naming `T201`.
   - a common misspelling (`the` with its last two letters swapped) in a docs page →
     `just check-docs` fails in typos.
   - a heading level jump in a docs page → markdownlint fails.
   - a tab-indented line in a `.py` file → editorconfig fails.
   - a relative link to a missing file in a docs page → lychee fails offline.
   - `py.typed` deleted from the build (`git mv` in the scratch) → `just wheel-smoke`
     fails.
8. `just check`; commit.

   **Adversarial review** (`CONVENTIONS.md` §14): the whole diff, before the final
   commit.

## Acceptance criteria

- Each control in step 7 failed with the named message, quoted with its exit status, and
  each restore was followed by the recipe passing again.
- `just coverage` reports line and branch coverage of `src/rovo/**`, with a combined total
  at or above the floor, with every module listed.
- `ruff.toml` keeps `select = ["ALL"]`; every ignore and per-file ignore has a comment:
  `rg -n -B1 '^\s*"[A-Z]+[0-9]*",' ruff.toml` shows a comment for each.
- `CONVENTIONS.md` §12 claims 7 and 9 have outcomes.
- The adversarial reviews ran and every valid finding is fixed or handed back.

## Verification

```sh
git rev-parse --short HEAD
just py-lint; echo "exit $?"
just py-typecheck; echo "exit $?"
{ just coverage 2>&1; echo "exit $?"; } | tail -9
{ just wheel-smoke 2>&1; echo "exit $?"; } | tail -6
just check-docs; echo "exit $?"
UV_PYTHON=3.13 UV_NO_GROUP=tooling just py-lint py-typecheck coverage wheel-smoke; echo "exit $?"
{ just check 2>&1; echo "exit $?"; } | tail -2
```

## Hand-back notes

To be written by the executing agent: each setting changed and why, each negative
control with its output, the coverage report, the outcome of T00's open point, any
recipe change handed back, and the review record for each checkpoint.

### Steps 1 to 5 (commit 048f7d1)

**Setup.** The lane's worktree branch was created from `main` (`61f2357`), not from
`bootstrap`; it was fast-forwarded to T00's tip `69f0d14` (`git merge --ff-only`)
before any work. `RUSTUP_TOOLCHAIN=stable` was exported (common-brief departure);
`just initialize` took the secondary-worktree path. Baseline `just check` at `69f0d14`,
exit 0, raw log `ai_tmp/T02/baseline.log`:

```text
All checks passed and the worktree is unchanged.
```

**Settings changed, and why.**

- `ruff.toml`: unchanged rules (they already met §9, with T00's `CPY001` hand-back);
  `[format] exclude = ["*.md"]`. T00 handed this decision over: ruff 0.17.3 formats
  Python blocks inside Markdown (`ruff format --check -v .` listed 70 files, 62 of
  them `.md`). Decision: exclude. Code blocks under `tickets/` and `docs/` are
  quotations (tickets embed verbatim content, some deliberately unformatted), docs
  pages belong to T04 and markdownlint, and `just format` must not rewrite prose or a
  frozen page. `ruff check` never read Markdown (`--show-files` lists none), so lint is
  unchanged. After: `6 files already formatted` (the six checked `.py` files).
- `mypy.ini`: `warn_unreachable = True` and `warn_redundant_casts = True` (W), each
  commented. Strict already implies the second; it is stated as W does.
- `pytest.ini`: §9's options unchanged; a comment on each.
- `.coveragerc`: `[run] patch = subprocess`, INI syntax, commented (claim 9 below).

**T00's open point, no arguments.** Pinned by
`test_no_arguments_prints_help_and_exits_2`: bare `rovo` prints the help on stdout,
nothing on stderr, and exits **2** (typer 0.27.3's `no_args_is_help`). The real
console script agrees: `.venv/bin/rovo` alone exited 2 with an empty stderr.

**Tests.** `tests/test_api.py`: one `python -I` subprocess probe (module fixture)
reports `sys.modules`, `__all__` and both versions as JSON; three tests named for
invariants 1, 2 and 3. `tests/test_cli.py`: `CliRunner` for `--version` and `version`
(stdout exactly `rovo <version>\n`, stderr empty), `--help`, no arguments, an unknown
command (exit 2, `No such command 'no-such-command'.` on stderr, stdout empty); out of
process, the console script found by `shutil.which("rovo", path=<dir of
sys.executable>)` (asserted non-`None`) and `python -I -m rovo`, each `--version`. The
runner pins `COLUMNS` and `TERMINAL_WIDTH` to 200: with either set to 30 in the caller's
environment, three tests failed on wrapped rich output before the pin and pass after.
No `tests/conftest.py` was needed. Each test was seen to fail on a deliberate defect,
then the file was restored: `import typer` in `__init__.py` failed invariant 1 (`assert
['typer', 'ty...matting', ...] == []`); an extra `__all__` name failed invariant 2;
`__all__` as the tuple `("__version__",)` failed invariant 2 on its type check
(`'tuple' == 'list'`; review T02-1 C1);
`no_args_is_help=False` failed only the no-arguments test; a changed version line failed
all four version tests.

**Claim 9.** `coverage combine` with one process's data: T00 (part 1). Subprocess
coverage, measured over only the subprocess tests
(`coverage run -m pytest -k 'console_script or python_m or invariant'`), before and
after `patch = subprocess` (raw `ai_tmp/T02/claim9-*.txt`):

```text
before: src/rovo/cli.py   14  5  2  0   56%   14-16, 33, 39
        TOTAL             17  5  2  0   63%
after:  Combined 4 files
        src/rovo/cli.py   14  2  2  1   81%   14->exit, 33, 39
        TOTAL             17  2  2  1   84%
```

The three subprocesses (the API probe under `-I`, the console script, `python -I -m
rovo`) are measured only with the patch, so the claim holds; `-I` does not stop it,
because coverage's `.pth` reads `COVERAGE_PROCESS_CONFIG`, which is not a `PYTHON*`
variable. The TOML list form `patch = ["subprocess"]` exits 1 with
`Unknown patch '["subprocess"]'`, as the claim says. `__main__.py` reports 0
statements because W's `if __name__ == .__main__.:` exclusion removes its whole body;
it is kept, because without it the never-taken false branch is a permanent partial.

**Claim 7** (raw `ai_tmp/T02/claim7.log`), each restored before the next:

```text
## ruff.py without F401 (import os removed); just py-lint
py-lint: the positive control did not fire (exit 1 naming F401 and E501)
exit 1
## ruff.py without E501 (long line shortened); just py-lint
py-lint: the positive control did not fire (exit 1 naming F401 and E501)
exit 1
## mypy.py without the error; just py-typecheck
py-typecheck: the positive control did not fire
exit 1
## restored
cmp identical
(just py-lint) exit 0
(just py-typecheck) exit 0
```

**Wheel smoke.** `api` now also asserts: the recorded files minus
`rovo-<version>.dist-info/` and `../../../bin/rovo` are exactly `rovo/__init__.py`,
`rovo/__main__.py`, `rovo/cli.py`, `rovo/py.typed`; `Requires-Python` is `>=3.13`; the
`Private :: Do Not Upload` classifier; no `License`, `License-Expression` or
`License-File`; the distribution's entry points are exactly
`console_scripts rovo = rovo.cli:app`. `cli` also runs the `rovo` beside
`sys.executable` and requires its output to equal `python -I -m rovo`'s. A control, with
`pyproject.toml`'s wheel `packages` widened to `["src/rovo", "tests"]` in a scratch copy
and restored (`git status` clean after):

```text
wheel_smoke: the installed files differ: unexpected ['tests/fixtures/py-lint-violation/mypy.py', 'tests/fixtures/py-lint-violation/ruff.py', 'tests/test_api.py', 'tests/test_cli.py'], missing []
exit 1
```

**3.13** (raw `ai_tmp/T02/py313.log`): `UV_PYTHON=3.13 UV_NO_GROUP=tooling just py-lint
py-typecheck coverage wheel-smoke` exit 0, pytest on `Python 3.13.13`, `10 passed`,
`TOTAL 17 0 2 0 100%`, both `wheel_smoke` lines. `just sync` restored the 3.14
environment afterwards; `just check` then exit 0, `All checks passed and the worktree is
unchanged.`

### Review checkpoint 1 (over `9c1eaf4`)

Run by the orchestrator under §14: Codex, `gpt-6-astra`, two fresh-context reviewers
(conformance, breakage), separate triage; records in `ai_tmp/review/T02-1/`.

| Id | Severity | Verdict | Reason | Action |
| --- | --- | --- | --- | --- |
| C1 | low | valid | the probe sent `rovo.__all__` through JSON, so a tuple `__all__` passed the "exactly `["__version__"]`" check | applied: the probe reports `type(rovo.__all__).__name__`, and the test requires `list` |
| breakage | n/a | n/a | the reviewer reported `No findings.` | none |

Triage's control: `__all__ = ("__version__",)` gave `1 failed, 2 passed` (`- list` /
`+ tuple`), then the file was restored. Nothing handed back; no high-severity finding,
so no second round. The setup fast-forward to `69f0d14` was approved by the orchestrator.

Re-run of the Verification block with the fix uncommitted on `9c1eaf4` (raw
`ai_tmp/T02/verify-cp1.log`): `py-lint` exit 0, `py-typecheck` exit 0, `just coverage`
`TOTAL 17 0 2 0 100%` exit 0, `just wheel-smoke` ending `rovo 0.0.0` exit 0,
`check-docs` exit 0, the 3.13 run exit 0, `just sync` exit 0.

### Steps 6 to 8 (commit 1e7687a)

**Step 6, the text gates.** Each of the six files was compared with A's at `c8e1a46`.
`.pre-commit-config.yaml` differs from A's only by the §5 deltas (the `exclude:`
block, the two Python hooks, `uv run --frozen` entries, the `.venv/bin/bg-ripsecrets`
entry); `.pre-commit-fix.yaml`, `.markdownlint-cli2.jsonc`, `lychee.toml` and
`.editorconfig` are T00's §5 adaptations. Each fires below, so none changed: the hook
ids the `Justfile` names are untouched. One change: `_typos.toml` keeps A's `mis` and
`als`, and the comment now says why. A scratch copy without them failed `typos` on
`tickets/T00-foundation.md:583`, which names them as A's words, and on nothing else.
They can go once T00's notes stop quoting them (T05's call).

**Step 7, the negative controls** (script `ai_tmp/T02/bin/controls.sh`, raw
`ai_tmp/T02/controls.log` and `ai_tmp/T02/controls/`). The quoted run is a re-run on
a clean worktree at `38f30ac` (the log's first line names it, and its last shows
`git status --short` empty after the run). Each file was saved to `ai_tmp/scratch/`,
edited, run, copied back (`cmp` identical), and the recipe run again, before the next
control: 1b and 3 each start from the restored file. Two changes came out of the first
pass, on the tree committed as `1e7687a`:

- An unguarded `import typer` made the smoke's `api` step die with a traceback.
  It now reports the failure and the recorded attempt (`scripts/wheel_smoke.py`).
- A branch in a function that no test calls reports as missed lines (`45-46`,
  `BrPart 0`), not as a partial branch. When the false side jumps to a missed line,
  coverage folds the arc into that line (`40`, `BrPart 1`). So the control uses a
  condition that is always true, on the path the tests run.

```text
## 1a. __init__.py gains 'import typer'
$ just coverage
FAILED tests/test_api.py::test_invariant_1_import_rovo_never_imports_the_command_line
E       AssertionError: assert ['typer', 'ty...matting', ...] == []
exit 1
$ just wheel-smoke
wheel_smoke: import rovo failed (No module named 'typer'); it tried ['typer']
exit 1
restored; $ just coverage -> exit 0
restored; $ just wheel-smoke -> exit 0
## 1b. __init__.py gains a guarded 'try: import typer'
$ just wheel-smoke
wheel_smoke: import rovo tried to import ['typer']
exit 1
restored; $ just coverage -> exit 0
restored; $ just wheel-smoke -> exit 0
## 2. an untested branch in cli.py (version_command: `if rovo.__version__.startswith("0"):`)
$ just coverage
Name                   Stmts   Miss Branch BrPart  Cover   Missing
src/rovo/cli.py           16      0      4      1    95%   39->41
TOTAL                     19      0      4      1    96%
exit 0
restored; $ just coverage -> exit 0
## 3. the same untested branch, floor 100
$ just coverage_floor=100 coverage
TOTAL                     19      0      4      1    96%
Coverage failure: total of 96 is less than fail-under=100
exit 2
restored; $ just coverage -> exit 0
## 4. an Any-returning function in src/
$ just py-typecheck
src/rovo/cli.py:46: error: Returning Any from function declared to return "int"  [no-any-return]
exit 1
restored; $ just py-typecheck -> exit 0
## 5. print() in cli.py
$ just py-lint
T201 `print` found
exit 1
restored; $ just py-lint -> exit 0
## 6. a misspelling in a docs page
$ just check-docs
typos....................................................................Failed
  error: `<t-e-h>` should be `the`
exit 1
restored; $ just check-docs -> exit 0
## 7. a heading level jump in a docs page
$ just check-docs
markdownlint.............................................................Failed
  docs/how-to/test-and-debug.md:15 error MD001/heading-increment Heading levels should only increment by one level at a time [Expected: h2; Actual: h4]
exit 1
restored; $ just check-docs -> exit 0
## 8. a tab-indented line in a .py file
$ just lint
EditorConfig.............................................................Failed
  src/rovo/cli.py:
    43: Wrong indent style found (tabs instead of spaces)
exit 1
restored; $ just lint -> exit 0
## 9. a relative link to a missing file in a docs page
$ just check-docs
lychee...................................................................Failed
  [ERROR] file://<worktree>/docs/how-to/missing-page.md (at 15:5) | File not found. Check if file exists and path is correct
exit 1
restored; $ just check-docs -> exit 0
## 10. py.typed moved out of the build with git mv
$ just wheel-smoke
wheel_smoke: rovo/py.typed is not among the installed files
exit 1
restored; $ just wheel-smoke -> exit 0
```

`<t-e-h>` stands for the misspelling typos printed, which `typos` would flag in this
file. In control 8 the `py-lint` hook failed as well (ruff on the tab), and the
`EditorConfig` hook's failure is the one quoted. Control 2 passes the 90 floor (96%),
because the floor is a combined total. The report's `39->41` is the evidence that
branches are measured, and control 3 shows that the floor bites.

**§12 outcomes.** Claim 7 holds (step 2's controls, above). Claim 9 holds: `combine`
with one process (T00), and subprocess coverage needs `patch = subprocess`
(before/after above).

**Step 8, Verification** at `2c68c1e` (raw `ai_tmp/T02/verify-final.log`; the 3.13 run
in `ai_tmp/T02/verify-313.log`, then `just sync` back to 3.14):

```text
2c68c1e
py-lint exit 0
py-typecheck exit 0
src/rovo/__init__.py       3      0      0      0   100%
src/rovo/__main__.py       0      0      0      0   100%
src/rovo/cli.py           14      0      2      0   100%
TOTAL                     17      0      2      0   100%
exit 0
wheel_smoke cli: rovo 0.0.0, from python -m rovo and the console script alike
rovo 0.0.0
exit 0
check-docs exit 0
3.13 exit 0
sync exit 0
$ just check
All checks passed and the worktree is unchanged.
exit 0
$ git status --short
exit 0
```

After that run, the two `S603` comments in `ruff.toml` were reworded, because the
tests and the smoke now also run the console script. `just py-lint` then gave exit 0,
and `just check` was run again before this commit (below). Every ignore carries a
comment, from `rg -n -B1 '^\s*"[A-Z]+[0-9]*",' ruff.toml`: `COM812`, `ISC001`,
`CPY001`, `tests/**` `S101`, `INP001`, `S603`, and `scripts/**` `INP001`, `T201`,
`S603`, each with a trailing `#` comment.

**Hand-backs from T02:** none new. The `CPY001` amendment to §9 is T00's, already
recorded. No recipe change was needed: every gate fired through the frozen `Justfile`.

### Review checkpoint 2 (whole diff, over `38f30ac`)

Run by the orchestrator under §14: Codex, `gpt-6-astra`, two fresh-context reviewers
(conformance, breakage), separate triage; records in `ai_tmp/review/T02-2/`.

| Id | Severity | Verdict | Reason | Action |
| --- | --- | --- | --- | --- |
| C1 | low | valid | controls 1a and 2 were not followed by "restore, recipe passes" before 1b and 3, though step 7 and these notes said so | applied: `controls.sh` restores and re-runs after 1a and 2; the controls were re-run on a clean `38f30ac`, and the step-7 quote and its introduction were updated |
| breakage | n/a | n/a | the reviewer finished with `No findings.` | none |

Nothing handed back; no high-severity finding, so no second round. The re-run log
(`ai_tmp/T02/controls.log`) starts `## HEAD 38f30ac`. Every control's failure matches
the quote, every `restored;` line shows exit 0, and `git status --short` was empty
after the run.

## Open points

- Whether the floor should rise to 100% while the package is this small. The maintainer
  decides; the `Justfile` holds the number, so a change is a `main` pull request.
