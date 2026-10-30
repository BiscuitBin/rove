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

## Open points

- Whether the floor should rise to 100% while the package is this small. The maintainer
  decides; the `Justfile` holds the number, so a change is a `main` pull request.
