---
title: "Decision 0003: A Typer command line that `import rovo` never loads"
kind: "decision"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["decision_cli"]
requires: []
---

# Decision 0003: A Typer command line that `import rovo` never loads

## Context

One distribution carries two interfaces: the Python API and the `rovo` command. A
program that imports the API should not pay for the command line. Typer's runtime
closure, as `uv.lock` pins it, is typer, rich, markdown-it-py, mdurl, pygments,
shellingham and annotated-doc, plus colorama on Windows; typer 0.27 vendors click, so
click is not a separate package. Importing that tree costs start-up time, and a module
the API pulls in is one its users must have.

## Decision

The command line uses Typer and lives in `src/rovo/cli.py`, which defines `app` and
imports `rovo`. The dependency runs one way: `rovo/__init__.py` never imports
`rovo.cli`, typer or anything outside the standard library. The console script is
`rovo = "rovo.cli:app"`, and `src/rovo/__main__.py` imports the same `app`, so
`python -m rovo` and `rovo` print the same program name.

Two checks prove the boundary. `tests/test_api.py` imports `rovo` in a fresh
`python -I` subprocess and asserts that no module of typer, rich or click is in
`sys.modules`.
`just wheel-smoke` installs the built wheel with no dependencies into a new
environment, then `scripts/wheel_smoke.py api` puts a recording finder at the head of
`sys.meta_path`, imports `rovo`, and fails if any import was attempted outside `rovo`
and the standard library, so even a guarded `try: import typer` fails it. Only then
does the smoke install the locked runtime closure and run the command.

## Consequences

`import rovo` stays cheap and typer-free. The boundary is about imports, not
installation: typer is a runtime dependency, so every installation of `rovo` installs
it, including one that only uses the API.

The smoke's first step forbids every third-party import, not only typer's. When the
product's API needs a dependency of its own, that step has to change shape, in the
same pull request that adds the dependency under [decision
0005](0005-dependency-policy.md).

## What would reopen this

The API needing a third-party import at `import rovo` time, which changes the first
smoke step. A wish to install the API without typer, which would move the command line
behind an optional extra or into its own distribution. Typer being replaced: the
boundary would stay, and only `rovo.cli` would change.

## Related pages

- [Architecture](../explanation/architecture.md)
- [Command-line reference](../reference/cli.md)
- [Testing](../reference/testing.md)
