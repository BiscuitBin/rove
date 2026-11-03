---
title: "Command-line reference"
kind: "reference"
audience: ["user", "contributor", "maintainer", "agent"]
canonical_for: ["cli_reference"]
requires: []
---

# Command-line reference

The `rovo` command is the Typer application `rovo.cli:app`. `python -m rovo` runs the
same application under the same program name. The implementation of the specification
under `docs/specs/` is under way: `rovo init` creates a mirror and `rovo sync` mirrors
its seed pages over HTTP; the later commands (`verify`, `index`, `report`, `fetch`)
arrive with their slices. Every example on this page was run from a checkout as
`uv run --frozen rovo ...`; an installed command behaves the same.

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

## `rovo init`

```text
Usage: rovo init [OPTIONS] SITE_URL OUT_DIR

Create a mirror: write rovo.toml and an empty manifest. Nothing is fetched.
```

| Argument or option | Effect |
| --- | --- |
| `SITE_URL` | The documentation page the mirror starts from: an `http` or `https` URL. |
| `OUT_DIR` | The directory the mirror is made in; created when absent. |
| `--profile NAME` | A catalogue profile (`generic`, `mslearn`, `devsite`). By default the URL's host picks one, else `generic`. |

`rovo init` writes `OUT_DIR/rovo.toml`, every key with its default, and an empty
manifest at `OUT_DIR/.rovo/manifest.json`, and makes no request. The scope it writes
keeps the URL's host, its directory as the path prefix and, as the root URL, its first
path segment. It exits 2, writing nothing, when the URL is not an http or https URL
that parses (`http://[` is not one), the
profile name is unknown, or the directory already holds a mirror: a manifest, readable
or not, or a `rovo.toml`. The [mirror reference](mirror.md) describes each file.

## `rovo sync`

```text
Usage: rovo sync [OPTIONS] OUT_DIR

Fetch the mirror's pages, publish them as Markdown and write crawl-report.json.
```

`rovo sync OUT_DIR` reads `rovo.toml`, reads each allowed host's `/robots.txt`, fetches
each seed page the robots rules allow once over HTTP with the user agent
`rovo/<version>`, converts it to Markdown with the generic profile and publishes it as
a page file at its assigned path. It then saves the manifest, the frontier and the run
history under `OUT_DIR/.rovo/`, writes `OUT_DIR/crawl-report.json` and exits with the
report's exit code. A page robots.txt disallows is skipped, not fetched. A page the
mirror has no free path for is refused: its URL is reported as failed with the error
`no free path` and the sync exits 1 (the [mirror reference](mirror.md#page-files) says
when that happens).

It exits 2 and writes no report when `OUT_DIR` is not a directory, holds no manifest or
holds one that does not parse, or when the configuration is invalid (a value of the
wrong type, a root or start URL that is not an http or https URL, a host that does not
parse, a `max_age` that is not a finite number of seconds), names no root or
start URL, sets `unblocking.provider`, changes the root URL the last run recorded,
needs a browser or stealth engine that is not installed, or sets `robots = "ignore"`.
The refusal is printed on standard error; the specification's refused report arrives
with a later slice. When a run reaches a branch a later slice implements (a redirect, a
404, a block, a retry, a page already in the mirror, a page with links, a profile other
than `generic`, a login form, a source id on an element that is not a heading), the sync stops, names the rule on standard error, exits 1 and leaves the
previous report in place.

## Exit codes

| Status | Meaning |
| --- | --- |
| 0 | Success: a version line or help was printed, a mirror was created, or a sync finished with nothing to report. |
| 1 | Partial: a sync recorded a failure, or stopped at a branch a later slice implements. |
| 2 | Usage error: no command given (the help goes to standard output; standard error is empty), an unknown command (`No such command`), an unknown option (`No such option`), a missing or extra argument, or a refused `init` or `sync`; for the parser's errors, the usage line and the error go to standard error. |
| 3 | Blocked: a host's breaker tripped (reached by a later slice). |
| 4 | Quality: `fail_on_low_quality` is set and a page touched this run is low confidence. |

The exit code of a sync is the most severe that applies, in the order of the table.

Help is rendered by rich, in boxes sized to the terminal; the plain usage lines above
are their text.

## Related pages

- [Install and run](../how-to/install-and-run.md)
- [The mirror on disk](mirror.md)
- [API reference](api.md)
- [Decision 0003: The command line](../decisions/0003-typer-cli-and-lazy-import.md)
