---
title: "Testing"
kind: "reference"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["testing_reference"]
requires: []
---

# Testing

Tests distinguish the API, the command line and the installed distribution.
[Test and debug](../how-to/test-and-debug.md) describes iteration; this page owns the
frameworks, the scope and the conventions.

## pytest

`pytest.ini` configures the suite: `testpaths = tests`, and
`addopts = -ra --strict-config --strict-markers`, so an unknown marker or configuration
key is an error rather than a silent no-op. `xfail_strict = true` makes an unexpected
pass fail, and `filterwarnings = error` turns every warning into a failure. Tests live
directly under `tests/`, one file per surface, with no package and no `conftest.py`
today. Test names state the behaviour, and each test has a docstring, because ruff's
rules apply to tests too.

## The API

`tests/test_api.py` runs its probe in a fresh `python -I` subprocess, so nothing the
test session has already imported can make typer look absent or present. The probe
imports `rovo` and asserts that `rovo.__version__` equals
`importlib.metadata.version("rovo")` and that `typer` is not in `sys.modules`. A new
public name gets an asserting test here, beside the boundary check.

## The command line

`tests/test_cli.py` drives `rovo.cli.app` in-process through
`typer.testing.CliRunner`, with `prog_name="rovo"`, and asserts the exit code and the
exact output; `--version` and `version` are one parametrized test. The console script
itself, as installed from the wheel, is exercised by the wheel smoke, below.

## The wheel smoke

`just wheel-smoke` empties `dist/`, builds the sdist and the wheel, requires exactly
one wheel, creates a fresh environment under `target/wheel-smoke/` with no Python
download, and installs the wheel with `--offline --no-index --no-deps`. Then
`scripts/wheel_smoke.py api`, under `python -I`, imports `rovo` with a recording import
finder in place and fails on any import outside `rovo` and the standard library; it
also checks that typer is not importable, that the version matches the metadata, and
that `py.typed` was installed. Next it installs the runtime closure `uv export` writes
from `uv.lock`, offline and with `--require-hashes`, runs `scripts/wheel_smoke.py cli`,
which checks `python -m rovo --version`, and finally runs the installed `rovo --version`.
A build on every gate is the cost of testing the artefact that will ship.

## Coverage

`just coverage` runs the suite under coverage and fails when the total over the `rovo`
package (`source_pkgs = rovo`), lines and branches combined (`branch = True`), falls
below 90 per cent. The floor lives in the `Justfile` as `coverage_floor`, never also in
`.coveragerc`. `parallel = True` gives each process its own data file, and the recipe
combines them. `.coveragerc` excludes the usual unreachable lines, including the
`if __name__ == "__main__":` block, which is why `src/rovo/__main__.py` reports no
statements. Subprocesses are not measured today, so `tests/test_api.py`'s probe adds
nothing to the total. The recipe also writes `target/coverage.xml`.

Coverage counts a line as covered when a test ran it; that establishes no behaviour.
Every guarantee needs its own asserting test. Delete unreachable defensive code rather
than contrive a way to cover it.

## The positive controls

`tests/fixtures/py-lint-violation/` holds `ruff.py` and `mypy.py`, deliberately broken
files the lint and type gates must reject. They are not tests: pytest does not collect
them, `ruff.toml` and `mypy.ini` exclude them from normal discovery, and the fixer
configuration leaves them alone. [Quality gates](quality-gates.md) describes what each
must produce.

## Related pages

- [Test and debug](../how-to/test-and-debug.md)
- [Quality gates](quality-gates.md)
- [Configuration](configuration.md)
