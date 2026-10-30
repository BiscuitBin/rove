---
name: python-change
description: Implement or review a change to the rovo package, its command line or its tests with the lint, type, coverage and wheel-smoke evidence the invariants require.
---

# Change the Python package

1. Read `AGENTS.md`, its invariants first. The product is not yet specified: build only
   the behaviour a ticket or a decision record asks for.
2. Decide where the change lands. The API is `src/rovo/__init__.py` and the modules it
   exports; the command line is `src/rovo/cli.py`. The command line imports the API,
   never the reverse (invariant 1), so a helper both need lives on the API side, and a
   CLI-only dependency is imported from `rovo.cli` alone. A public name enters `__all__`
   (invariant 2); anything else starts with `_`.
3. Write the failing test first and watch it fail. An API test goes in
   `tests/test_api.py` or a new module beside it; an import-boundary test runs in a
   fresh `python -I` subprocess, as `tests/test_api.py` does. A command-line test goes
   through `typer.testing.CliRunner`, and a new entry point is also tested through the
   installed script.
4. Make it pass with the smallest change. `just py-test` is the quick uncovered run and
   takes pytest's arguments.
5. Run `just py-lint`, `just py-typecheck`, `just coverage` and `just wheel-smoke`, in
   that order, until each passes. `just format` repairs formatting. A suppression names
   its rule and a reason (invariant 4); the coverage floor holds (invariant 5).
6. In the same change, update `docs/reference/api.md` for an API change or
   `docs/reference/cli.md` for a command-line change, and the `Unreleased` section of
   `CHANGELOG.md`.
7. Finish with `just check`, and report by `file:line` what changed in the code, the
   test and the documentation.
