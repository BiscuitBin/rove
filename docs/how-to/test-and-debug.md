---
title: "Test and debug"
kind: "how-to"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["test_and_debug"]
requires: []
---

# Test and debug

## Run the suites

```console
just py-test        # the suite, without coverage, for a quick run
just coverage       # the suite under coverage, with the floor enforced
just wheel-smoke    # build the wheel, install it fresh and offline, run it
```

`just py-test` passes its arguments to pytest, so the usual selection works:

```console
just py-test -k version
uv run --frozen pytest tests/test_api.py
```

The first runs every test whose name matches `version`; the second runs one file.
Framework configuration and conventions are described in
[Testing](../reference/testing.md); this page is about narrowing down a failure.

## Narrow down a failing test

1. Run the single test first, by `-k` or by file. A failure that appears only in the
   whole suite is shared state; `pytest.ini` sets `filterwarnings = error`, so a warning
   one test triggers fails it.
2. Read the assertion's left and right. A `CliRunner` test puts the command's output in
   the assertion message, so a usage error such as `No such command` is printed there.
3. `tests/test_api.py` runs its probe once, in a fresh `python -I` subprocess shared by
   its three tests. If the probe itself fails, every test there errors in the same
   fixture, and the message is the subprocess's stderr: read the traceback there, not
   pytest's.
4. Do not weaken an assertion to make it pass. Correct the code, or, when the
   expectation itself was wrong, say why in the change.

## Debug a coverage failure

`just coverage` prints the summary per file, with the missing lines, and fails below
the floor. For the lines themselves, render the HTML report from the data that run left
behind, into `target/`, which is ignored:

```console
uv run --frozen coverage html -d target/htmlcov
```

Open `target/htmlcov/index.html`. Two cases look alike and are not:

- **Untested behaviour.** Add the test. This is the common case.
- **Unreachable code.** A defensive branch no input can reach. Remove the branch, or
  make the types say so, rather than inventing a test that reaches it artificially.

Never lower `coverage_floor` in the `Justfile`; lower the complexity instead.

## Debug a wheel-smoke failure

`just wheel-smoke` empties `dist/`, builds the sdist and the wheel, and installs the
wheel into `target/wheel-smoke/venv` twice over. Its output says which step failed:

- `wheel_smoke: ...` during the first step means `import rovo`, from a wheel installed
  with no dependencies, tried to import something outside `rovo` and the standard
  library, or the installed files or metadata differ from what the wheel should carry
  (four package files, `py.typed` among them, the console script, the upload guard, no
  licence field). Look for an import added to `src/rovo/__init__.py` or to a module it
  imports, or a change to `pyproject.toml`'s build tables.
- `wheel_smoke: ...` during the second step means `python -m rovo --version` or the
  installed `rovo --version`, with the locked runtime closure installed, did not print
  `rovo <version>`, or the two printed different lines.
- `expected one wheel in dist/` means the build produced none, or more than one.

The environment stays in `target/wheel-smoke/venv` after a run, so you can run
`target/wheel-smoke/venv/bin/rovo --help` there to look.

## Debug a stale-lock failure

`just lock-check` failing means `uv.lock` disagrees with `pyproject.toml`: a dependency
or the version was edited without relocking. Read
[Maintain dependencies](maintain-dependencies.md) and relock deliberately; never relock
from inside a fix for something else.

## Related pages

- [Testing](../reference/testing.md)
- [Quality gates](../reference/quality-gates.md)
- [Troubleshooting](../operations/troubleshooting.md)
