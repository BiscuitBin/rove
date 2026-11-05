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
pass fail, and `filterwarnings = error` turns every warning into a failure. `markers`
registers the one marker, `browser`. Tests live directly under `tests/`, one file per
surface, with no package and no `conftest.py`; the exception is `tests/e2e/`, the
end-to-end tests, whose `conftest.py` holds the harness. No package means pytest and mypy
key each test module by its basename, so no basename under `tests/e2e/` repeats one
under `tests/`.
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

## The import direction

`tests/test_import_direction.py` reads every module under `src/rovo/` with `ast`,
without importing any of it, and collects each `import`, each `from ... import` (as the
module and as the module plus each name) and each `importlib.import_module` or
`__import__` call with a literal name, a relative `import_module` name resolved against
its package argument or the importing module's package. One test per rule: nothing
under `rovo._convert` imports `rovo._mirror`, `rovo._crawl` or `rovo.cli`; nothing under
`rovo._mirror` imports `rovo._crawl` or `rovo.cli`; nothing under `rovo._crawl` imports
`rovo.cli`, `rovo._config`, `rovo._report` or `rovo._commands`; `_config` and `_report`
import neither `_commands` nor `rovo.cli`; `rovo._unfinished` imports no rovo module;
`src/rovo/__init__.py` imports no private module, not `rovo.cli`, and nothing whose first
component is `httpx`, `bs4`, `lxml`, `markdownify`, `playwright`, `protego` or `typer`; and no
statement of `cli.py` that runs on import (inside `if`, `try`, `with`, a loop or a class
body included; a function body or an `if TYPE_CHECKING:` body excluded) imports a
private module or a dependency. A further test requires the scan to have found the root
and all seven private modules, so an emptied walk cannot pass, and positive controls feed
the helpers synthetic sources that each form must catch. A name computed at run time escapes it; the API probe and the
wheel smoke still catch what `import rovo` actually loads.

## The command line

`tests/test_cli.py` tests the command two ways. In-process, it drives `rovo.cli.app`
through `typer.testing.CliRunner`, with `prog_name="rovo"` and a 200-column terminal so
that rich's output does not wrap, and asserts the exit code, standard output and
standard error separately: `--version` and `version` (one parametrized test), `--help`,
no arguments (help on stdout, exit 2), an unknown command (stderr, exit 2), and `init`
and `sync`: their help and their usage exits. Out of
process, it runs the `rovo` console script installed beside the test interpreter and
`python -I -m rovo`, each with `--version`, and asserts the version line.

## The specification's tests

The tests for the Allium specifications are named after the obligation they discharge:
`just plan-spec <module>` lists each obligation's id, such as `rule-success.StoreNewPage`,
and its test is `test_rule_success_StoreNewPage`, one test or one parametrised case per
obligation, in `tests/test_convert.py`, `test_mirror.py`, `test_crawl.py`,
`test_config.py`, `test_report.py` and `test_commands.py` (ruff's N802 is off for tests
so the CamelCase rule name survives). A `config` default is never restated: a test reads
it from the committed `.allium` file through `tests/spec_values.py`. The loop ledger
under `.allium-loop/` pins each generated test file's hash; a later change adds tests
beside them rather than editing them. `tests/test_regressions.py` pins each divergence a
weed or review found, `tests/test_slice_boundaries.py` the points where a slice stops
with `NotInThisSlice`.

`tests/fakes.py` holds the seams' doubles: `FakeFetcher`, a URL-to-`SiteResponse` map
that records every request and answers 404 for any other URL; `ScriptedFetcher`, which
answers a scripted URL from a sequence of answers, one per request, before its map;
`StampingFetcher`, which wraps any fetcher and records `(url, timer.now())` per request;
`FixedClock`, a clock that stands still and records each `sleep` without moving;
`SteppingTimer`, a timer whose time moves only when it sleeps, by exactly that much, so
the gap between two stamps is the wait the limiter chose; and `html_response`,
`text_response` and `xml_response` to build answers (`fixture_site` answers an `.xml`
file with the last). `tests/test_sitemaps.py` pins the discovery black boxes of
`rovo._crawl.sitemaps` with hand-written tables: what is a sitemap document, its
entries, an entity never expanded, the links of `llms.txt` and the sitemap filter. `tests/test_pace.py` tests the pacing on unit inputs:
the limiter's spacing, `retry_wait`, robots matching and the robots.txt retries, and the
real `SystemTimer` only with `time.sleep` and `time.monotonic` replaced. No test sleeps
or reaches the network.

## The wheel smoke

`just wheel-smoke` empties `dist/`, builds the sdist and the wheel, requires exactly
one wheel, creates a fresh environment under `target/wheel-smoke/` with no Python
download, and installs the wheel with `--offline --no-index --no-deps`. Then
`scripts/wheel_smoke.py api`, under `python -I`, imports `rovo` with a recording import
finder in place and fails on any import outside `rovo` and the standard library. It
also checks that typer is not importable, that the version matches the metadata, that
the wheel installed exactly the twenty-seven package files (`py.typed` among them) and the
console script, and that the metadata has `Requires-Python: >=3.13`, the upload-guard
classifier, no licence field and exactly the one entry point. Next it installs the
runtime closure `uv.lock` pins, with `uv sync` aimed at the smoke environment, offline
and checked against the lock's hashes, runs `scripts/wheel_smoke.py cli`, which checks
that `python -m rovo --version` and the console script print the same version line, and
finally runs the installed `rovo --version`.
A build on every gate is the cost of testing the artefact that will ship.

## The end-to-end harness

`tests/e2e/conftest.py` provides the factory fixture `serve_site`: `serve_site("basic")`
serves `tests/fixtures/sites/basic/` with the standard library's `ThreadingHTTPServer`
and `SimpleHTTPRequestHandler`, request logging silenced, bound to an ephemeral port on
`127.0.0.1` in a background thread, and returns the base URL
(`http://127.0.0.1:<port>/`); given a `Path`, it serves that directory instead, such as
a templated copy in `tmp_path`. A path may be scripted: `script` answers its requests
from a list of `Answer`s (a status, headers and a body), one per request, before the
file; `always` answers every request to it the same way once the script is used up; and
`DROP` closes the connection without a response. Every request is logged, and
`serve_site.log(base)` gives each path with its `time.monotonic()` arrival, in order.
When the test ends, every server it started is shut down
and closed, and its threads are joined (the server joins its request threads too), so
`filterwarnings = error` sees no unclosed socket. Nothing reaches the network.

`tests/fixtures/sites/<name>/` holds the fixture sites, one directory each; `basic` is a
single `index.html`, `one-page` a single documentation page at `guide/start.html`, and
`robots-disallow` the same page under a `robots.txt` that disallows `/guide/`. `links`
is a small linked site (a seed, pages one and two links deep, a robots-disallowed page
and a page off the path prefix), and `cross-target` with `cross-host` are two sites whose
pages link across servers; `cross-host` holds the placeholder `@TARGET_BASE@`, which the
test replaces with the other server's base URL. `polite` is a seed, two pages, a page
the scripted tests make flaky and a page under a path its `robots.txt` disallows, with a
`Crawl-delay`; `tests/e2e/test_polite_sync.py` syncs it to check robots.txt, pacing,
retries and the partial exit. `tests/e2e/test_discovery_sync.py` generates its sites
into a temporary directory, since a sitemap names absolute URLs with the server's port,
and syncs them to check sitemaps, sitemap indexes, `llms.txt`, the observations, the
page budget and `rovo sync --dry-run`. `tests/e2e/test_second_sync.py` generates its
sites the same way and syncs each again: an unchanged site rewrites no file, and a
changed page, a page answered with the same document and `max_age` are each handled
incrementally.
`tests/e2e/test_harness.py` proves the harness: the basic site answers 200 with its
heading. `tests/e2e/test_init_sync.py` runs `rovo init` and `rovo sync` against the
fixture sites, as the installed command would, and `tests/e2e/test_follow_links.py`
syncs the linked sites. `tests/test_links.py` holds the hand-written link tests: the
`RelativeLinksOnly` and `CodeSamplesNeverRewritten` guarantees, broken-link detection
and a whole sync over the links site through `FakeFetcher`. The suite and `just coverage` run the end-to-end tests
with everything else.

The `browser` marker is for tests that need playwright and a browser. Without the
`browser` extra installed they skip through `pytest.importorskip`; `just e2e-browser`
runs them with the extra. Today the one such test checks that playwright's sync API
imports.

## Coverage

`just coverage` runs the suite under coverage and fails when the total over the `rovo`
package (`source_pkgs = rovo`), lines and branches combined (`branch = True`), falls
below 95 per cent. The floor lives in the `Justfile` as `coverage_floor`, never also in
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

Of `tests/fixtures/`, only `py-lint-violation/` is a positive control; `sites/` holds
the end-to-end fixture sites. `tests/fixtures/py-lint-violation/` holds `ruff.py` and `mypy.py`, deliberately broken
files the lint and type gates must reject. They are not tests: pytest does not collect
them, `ruff.toml` and `mypy.ini` exclude them from normal discovery, and the fixer
configuration leaves them alone. [Quality gates](quality-gates.md) describes what each
must produce.

## Related pages

- [Test and debug](../how-to/test-and-debug.md)
- [Quality gates](quality-gates.md)
- [Configuration](configuration.md)
