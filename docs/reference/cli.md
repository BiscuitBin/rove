---
title: "Command-line reference"
kind: "reference"
audience: ["user", "contributor", "maintainer", "agent"]
canonical_for: ["cli_reference"]
requires: []
---

# Command-line reference

The `rovo` command is the Typer application `rovo.cli:app`. `python -m rovo` runs the
same application under the same program name. Today it is a placeholder: it prints the
version, and nothing else. The product's first ticket adds its commands here. Every
example on this page was run from a checkout as `uv run --frozen rovo ...`; an
installed command behaves the same.

## `rovo`

```text
Usage: rovo [OPTIONS] COMMAND [ARGS]...

rovo: a Python API and the rovo command.
```

| Option | Effect |
| --- | --- |
| `--version` | Print `rovo <version>`, for example `rovo 0.0.0`, and exit 0. It is eager: it acts before any command is parsed, so `rovo --version version` prints the line once and exits 0. |
| `--help` | Print the usage, the options and the commands, and exit 0. |

With no arguments, `rovo` prints the same help to standard output and exits 2, because the application
sets `no_args_is_help` and Typer treats a missing command as a usage error. Shell
completion options are not offered (`add_completion=False`).

## `rovo version`

```text
Usage: rovo version [OPTIONS]

Print the version.
```

Prints `rovo <version>` and exits 0. Its only option is `--help`. Both `rovo version`
and `rovo --version` read `rovo.__version__`, which comes from the installed
distribution's metadata, so they always agree with the installed version.

## Exit codes

| Status | Meaning |
| --- | --- |
| 0 | Success: a version line or help was printed. |
| 2 | Usage error: no command given, an unknown command (`No such command`), an unknown option (`No such option`), or an extra argument. The usage line and the error go to standard error. |

Help is rendered by rich, in boxes sized to the terminal; the plain usage lines above
are their text.

## Related pages

- [Install and run](../how-to/install-and-run.md)
- [API reference](api.md)
- [Decision 0003: The command line](../decisions/0003-typer-cli-and-lazy-import.md)
