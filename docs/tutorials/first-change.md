---
title: "Make your first change"
kind: "tutorial"
audience: ["contributor", "agent"]
canonical_for: ["first_change_tutorial"]
requires: []
---

# Make your first change

About fifteen minutes after setup, from a green baseline through one small change and
its test. The first run needs the network, uv and just;
[Develop locally](../how-to/develop-locally.md) describes them. The change adds a
subcommand to the `rovo` command, test first. Work in a disposable branch or worktree:
the subcommand is an exercise, not part of the product, and is never shipped.

## 1. Get the project running

```console
just initialize
just check
```

Initialization installs the environment exactly as `uv.lock` pins it and prepares the
hook environments. It installs the Git hook only from the primary checkout, never
formats, and never stages, commits, tags or pushes. `just check` must end with
`All checks passed and the worktree is unchanged.` Start only from a green baseline.

## 2. Read the command

Open `src/rovo/cli.py`. `app` is a `typer.Typer`; the `@app.callback()` carries the
eager `--version` option, and `@app.command("version")` defines `rovo version`. Then
open `tests/test_cli.py`, which drives `app` through `typer.testing.CliRunner` without
starting a process. Note that `src/rovo/__init__.py` never imports `cli.py`: the
command imports the API, never the reverse.

## 3. Write the failing test

Append this to `tests/test_cli.py`:

```python
def test_ping_answers_pong() -> None:
    """`rovo ping` prints `pong` and exits 0."""
    result = CliRunner().invoke(app, ["ping"], prog_name="rovo")

    assert result.exit_code == 0, result.output
    assert result.output == "pong\n"
```

Run only that test:

```console
just py-test -k ping
```

It must fail: the assertion reports exit code 2, and the output says
`No such command 'ping'`. A test that is green before the change is either already
covered or vacuous.

## 4. Add the command

Append this to `src/rovo/cli.py`, after `version_command`:

```python
@app.command("ping")
def ping_command() -> None:
    """Answer pong: a tutorial exercise, not part of the product."""
    typer.echo("pong")
```

Run `just py-test -k ping` again: it passes. Check it from the shell as well:

```console
uv run --frozen rovo ping
uv run --frozen rovo --help
```

The first prints `pong`; the second lists `ping` beside `version`, with the first line
of its docstring as its help.

## 5. Run the whole gate

```console
just check
```

It runs the ten gates in order, including ruff and mypy over the new code, the
coverage floor, and the wheel smoke against a freshly built wheel, then proves the run
did not modify the worktree. Read only the first failure; later ones are often
consequences. [Troubleshooting](../operations/troubleshooting.md) covers the common
causes.

## 6. Discard the exercise

Inspect the diff, then throw it away: restore both files from Git, or remove the
disposable worktree. A real command arrives with its ticket, its tests and its page in
the [command-line reference](../reference/cli.md). Nothing is pushed without explicit
authorization.

## What you just touched

A test that drives the command in-process, a Typer command beside the placeholder, and
the gate that lints, type-checks, measures and smoke-installs it. Each step failed
before it passed. That is the loop for a real change too.

## Related pages

- [Develop locally](../how-to/develop-locally.md)
- [Test and debug](../how-to/test-and-debug.md)
- [Architecture](../explanation/architecture.md)
