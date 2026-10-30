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
directly under `tests/`, one file per surface, with no package and no `conftest.py`.
Test names state the behaviour, and each test has a docstring, because ruff's
rules apply to tests too.

## The API

`tests/test_api.py` runs its probe once, in a fresh `python -I` subprocess, so nothing
the test session has already imported can make a module look absent or present. The
probe imports `rovo` and prints, as JSON, what that import left behind: `sys.modules`,
`rovo.__all__`, `rovo.__version__` and the installed metadata's version. One test per
invariant judges the report: no module whose first component is `typer`, `rich` or
`click` was loaded (invariant 1); `__all__` is exactly `["__version__"]` (invariant 2);
and `rovo.__version__` equals `importlib.metadata.version("rovo")` (invariant 3). A new
public name changes the second test, deliberately.

## The command line

`tests/test_cli.py` tests the command two ways. In-process, it drives `rovo.cli.app`
through `typer.testing.CliRunner`, with `prog_name="rovo"` and a 200-column terminal so
that rich's output does not wrap, and asserts the exit code, standard output and
standard error separately: `--version` and `version` (one parametrized test), `--help`,
no arguments (help on stdout, exit 2) and an unknown command (stderr, exit 2). Out of
process, it runs the `rovo` console script installed beside the test interpreter and
`python -I -m rovo`, each with `--version`, and asserts the version line.

## The wheel smoke

`just wheel-smoke` empties `dist/`, builds the sdist and the wheel, requires exactly
one wheel, creates a fresh environment under `target/wheel-smoke/` with no Python
download, and installs the wheel with `--offline --no-index --no-deps`. Then
`scripts/wheel_smoke.py api`, under `python -I`, imports `rovo` with a recording import
finder in place and fails on any import outside `rovo` and the standard library. It
also checks that typer is not importable, that the version matches the metadata, that
the wheel installed exactly the four package files (`py.typed` among them) and the
console script, and that the metadata has `Requires-Python: >=3.13`, the upload-guard
classifier, no licence field and exactly the one entry point. Next it installs the
runtime closure `uv export` writes from `uv.lock`, offline and with `--require-hashes`,
runs `scripts/wheel_smoke.py cli`, which checks that `python -m rovo --version` and the
console script print the same version line, and finally runs the installed
`rovo --version`.
A build on every gate is the cost of testing the artefact that will ship.

## Coverage

`just coverage` runs the suite under coverage and fails when the total over the `rovo`
package (`source_pkgs = rovo`), lines and branches combined (`branch = True`), falls
below 90 per cent. The floor lives in the `Justfile` as `coverage_floor`, never also in
`.coveragerc`. `parallel = True` gives each process its own data file, and the recipe
combines them. `.coveragerc` excludes the usual unreachable lines, including the
`if __name__ == "__main__":` block, which is why `src/rovo/__main__.py` reports no
statements. `patch = subprocess` measures the Python subprocesses the tests start (the
API probe, the console script and `python -m rovo`), so their lines count toward the
total too. The recipe also writes `target/coverage.xml`.

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
