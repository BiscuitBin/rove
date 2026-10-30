set positional-arguments := true
set shell := ["sh", "-eu", "-c"]

# uv owns Python and every tool in .venv (gitignored); uv.lock is the pin and
# pyproject.toml the manifest. .python-version makes 3.14 the tooling
# interpreter; the package's floor is requires-python (3.13). Every tool runs
# through `uv run --frozen`, which never resolves and never rewrites the lock.

# Coverage floor over src/rovo/**: coverage's total, lines and branches
# combined (fail-under), not a separate floor for each. Lower the complexity,
# not the number.
coverage_floor := "90"

default:
    @just --list

# ------------------------------------------------------------------ setup ---

# One explicit first-run command. Never stages, commits, tags, or pushes.
initialize:
    sh scripts/initialize.sh

# The environment exactly as uv.lock pins it. Network on a cold cache.
sync:
    uv sync --frozen

lock:
    uv lock

# Moves every locked version within pyproject.toml's constraints: typer's
# tree, B's commit at its tag, and the transitive dependencies of the exact dev
# pins, which themselves hold still.
lock-upgrade:
    uv lock --upgrade

# Offline, like every gate recipe: a stale lock fails rather than resolving.
lock-check:
    uv lock --check --offline

# The shim, then every hook environment, then lychee's binary, so that
# `just check` never fetches.
install-hooks: && warm-lychee
    git rev-parse --is-inside-work-tree >/dev/null
    test -x .venv/bin/prek || { printf '%s\n' 'the environment is not installed; run just initialize first' >&2; exit 2; }
    uv run --frozen prek install --overwrite --hook-type=pre-commit --prepare-hooks
    uv run --frozen prek prepare-hooks --config .pre-commit-fix.yaml

# lychee downloads its binary at first run, not at prepare, so it is run on one
# file; its exit status is lint's business, not this recipe's. What this recipe
# checks is that the binary is present: an executable lychee-<LYCHEE_VERSION>,
# the version .pre-commit-config.yaml pins, in prek's cache, or it fails. The
# download can time out (it did on a macOS runner), so it is tried three times.
# Private: install-hooks runs it, and so does initialize in a secondary worktree.
[private]
warm-lychee:
    #!/bin/sh
    set -eu
    version=$(sed -n 's/.*LYCHEE_VERSION=\([0-9][0-9.]*\).*/\1/p' .pre-commit-config.yaml | sort -u)
    case $version in ''|*[!0-9.]*) printf '%s\n' "warm-lychee: expected one LYCHEE_VERSION in .pre-commit-config.yaml, found: $version" >&2; exit 1 ;; esac
    cache=$(uv run --frozen prek cache dir)
    for attempt in 1 2 3; do
        uv run --frozen prek run lychee --files README.md || :
        for bin in "$cache"/repos/*/.cargo/bin/lychee-"$version"; do
            if [ -x "$bin" ]; then printf 'lychee %s warmed: %s\n' "$version" "$bin"; exit 0; fi
        done
        printf 'warm-lychee: no lychee-%s binary after attempt %s\n' "$version" "$attempt" >&2
    done
    exit 1

# ----------------------------------------------------------------- format ---

format:
    uv run --frozen ruff check --fix-only .
    uv run --frozen ruff format .

# Automatic repairs. The fix config runs twice because a fixer's first pass may
# itself fail on what another fixer then repairs.
fix:
    -uv run --frozen prek run --all-files --config .pre-commit-fix.yaml
    uv run --frozen prek run --all-files --config .pre-commit-fix.yaml
    just lint

# ------------------------------------------------------------------ check ---

lint:
    uv run --frozen prek run --all-files

# Gate: ruff over every Python file ruff.toml names; --show-files must list
# the package, or an exclude has emptied the gate (ruff exits 0 on no files);
# then the positive control: the fixture must fail with exit status 1 and the
# output must name F401 and E501, the fixture's own violations: under
# select = ALL the file also trips other rules, so the exit status alone would
# fire with F and E dropped. Exit 2 is a tool or usage error, not a fired
# control; a missing fixture is E902 with exit 1, so it is tested first.
py-lint:
    uv run --frozen ruff check .
    uv run --frozen ruff format --check .
    uv run --frozen ruff check --show-files . | grep -q 'src/rovo/__init__\.py$' || { printf '%s\n' 'py-lint: ruff did not see the package' >&2; exit 1; }
    test -f tests/fixtures/py-lint-violation/ruff.py || { printf '%s\n' 'py-lint: the positive control fixture is missing' >&2; exit 1; }
    status=0; out=$(uv run --frozen ruff check --quiet --output-format concise tests/fixtures/py-lint-violation/ruff.py) || status=$?; [ "$status" -eq 1 ] && printf '%s\n' "$out" | grep -q ': F401 ' && printf '%s\n' "$out" | grep -q ': E501 ' || { printf '%s\n' "$out" 'py-lint: the positive control did not fire (exit 1 naming F401 and E501)' >&2; exit 1; }

# Gate: mypy over the files mypy.ini names, then the positive control: the
# fixture must fail with exit status 1 (type errors). Exit 2 is a usage or I/O
# error, not a fired control.
py-typecheck:
    uv run --frozen mypy
    status=0; uv run --frozen mypy --no-error-summary tests/fixtures/py-lint-violation/mypy.py || status=$?; [ "$status" -eq 1 ] || { printf '%s\n' 'py-typecheck: the positive control did not fire' >&2; exit 1; }

# The suite, uncovered, for a quick local run. Not a gate: coverage runs it.
py-test *args:
    uv run --frozen pytest "$@"

# Gate: the suite under coverage, then the floor. .coveragerc sets
# parallel = true, so every process writes its own data file and combine
# always has something to merge; erase first, so no stale file counts.
coverage:
    uv run --frozen coverage erase
    uv run --frozen coverage run -m pytest
    uv run --frozen coverage combine --quiet
    uv run --frozen coverage report --fail-under {{coverage_floor}}
    mkdir -p target
    uv run --frozen coverage xml --quiet -o target/coverage.xml

# The sdist and the wheel into dist/, emptied first so a stale wheel can never
# be smoked. Offline: the build backend comes from the cache `just sync` filled.
build:
    rm -rf dist
    uv build --offline --out-dir dist

# Gate: the wheel installs and works in a fresh virtual environment, offline,
# in two steps. First the wheel alone, with no dependency: importing rovo must
# work without typer and must not even try to import typer, click or rich.
# Then the runtime closure uv.lock pins, from the cache, and the command. The
# closure goes in with `uv sync` aimed at the smoke venv, not `uv pip install
# -r`: sync fetches each file by the lock's URL and checks the lock's hash, and
# `just sync` cached those files, while pip install resolves against index
# pages that nothing caches on a fresh clone. --inexact keeps the wheel the
# first step installed.
# Exactly one wheel, which must exist (an unmatched glob is one literal
# argument). Python runs with -I so nothing in the worktree shadows the
# installed package.
wheel-smoke: build
    #!/bin/sh
    set -eu
    set -- dist/*.whl
    [ "$#" -eq 1 ] && [ -f "$1" ] || { printf 'wheel-smoke: expected one wheel in dist/, found: %s\n' "$*" >&2; exit 1; }
    rm -rf target/wheel-smoke
    mkdir -p target/wheel-smoke
    uv venv --offline --no-python-downloads --quiet target/wheel-smoke/venv
    uv pip install --python target/wheel-smoke/venv --offline --no-index --no-deps "$1"
    target/wheel-smoke/venv/bin/python -I scripts/wheel_smoke.py api
    UV_PROJECT_ENVIRONMENT=target/wheel-smoke/venv uv sync --frozen --offline --no-default-groups --no-install-project --inexact
    target/wheel-smoke/venv/bin/python -I scripts/wheel_smoke.py cli
    target/wheel-smoke/venv/bin/rovo --version

# Known vulnerabilities in the locked dependencies. Needs the network, so it
# sits outside `just check`, as check-links-online does.
audit:
    uv audit --frozen

# --------------------------------------------------------------- documents ---

check-docs:
    uv run --frozen prek run --all-files markdownlint-cli2 typos lychee
    uv run --frozen bg-validate-docs

check-agents:
    uv run --frozen bg-validate-agents

check-links-online:
    uv run --frozen prek run --all-files --hook-stage manual lychee-online

# --------------------------------------------------------------- aggregate ---

check-clean baseline="":
    uv run --frozen bg-project-check clean "$1"

# The complete gate: the recipes pyproject.toml lists, in order, with the
# worktree snapshotted between each, then check-clean. UV_OFFLINE reaches every
# recipe and hook under it, so a `uv run` that finds the environment out of
# date with uv.lock syncs from the cache or fails; it never fetches.
check:
    UV_OFFLINE=1 uv run --frozen bg-project-check run
