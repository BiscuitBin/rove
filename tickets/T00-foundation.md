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

## Open points

- Whether `rovo` with no arguments should print help and exit 0 or 2. Typer's
  `no_args_is_help` decides it today; T02 pins the behaviour in a test and records
  which.
