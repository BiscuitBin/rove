---
title: "Purpose and scope"
kind: "project"
audience: ["user", "contributor", "maintainer", "agent"]
canonical_for: ["project_purpose"]
requires: []
---

# Purpose and scope

`rovo` is one pure-Python distribution with two interfaces: an importable package,
`rovo`, which is the Python API, and a Typer command of the same name. The
[architecture](../explanation/architecture.md) describes how the two are separated;
[Python packaging](../explanation/packaging.md) explains the wheel they ship in.

## What it does today

The product is specified under `docs/specs/` and its implementation is under way: rovo
turns a product's documentation website into a local, self-linking Markdown mirror that
re-syncs with one command and reports how well every page converted
([decision 0012](../decisions/0012-rovo-is-a-documentation-mirror.md)). What works
today is a thin path: `rovo init` creates a mirror, and `rovo sync` fetches the
seed pages robots.txt allows over HTTP, then the pages they link to within the crawl
scope, converts each to Markdown with its profile, publishes it as a page file
whose links to other mirrored pages are relative, writes the mirror's indexes and writes
`crawl-report.json`; `rovo verify` checks the mirror on disk offline, `rovo index`
rebuilds the indexes offline, and `rovo report` prints the last report; a sync naming
`--url` or `--path` targets syncs those pages alone. A blocked page is reported, and a
host whose breaker trips or that is retired gets no further request and makes the sync
exit 3. Under `render_mode = "auto"` or `"always"` a page that needs JavaScript is
rendered in headless Chromium (the `browser` extra) and its tier is learned, and
`rovo fetch URL` prints one page's Markdown and writes nothing. A branch a later slice
implements (owner testing) stops the sync with exit 1. The API still exports `rovo.__version__` and nothing else. Around the
product the repository runs everything a change needs: lint and type gates with
positive controls, a coverage floor, a wheel built and smoke-installed offline on every
`just check`, the documentation and agent contracts, and CI. Each implementation ticket
lands on a gate that already proves everything around it.

## What it deliberately does not do

It does not invent the product: the specifications say what `rovo` does, and a page,
test or command that says otherwise is a defect until a specification change says so. Nothing is released: the package is not on PyPI, and a
`Private :: Do Not Upload` classifier makes PyPI refuse an accidental upload. There is
no licence yet ([decision 0006](../decisions/0006-licence-deferred.md)), so the
repository grants no rights beyond GitHub's terms of service, and a release waits for
that decision.

## Who it is for

Contributors and agents who will build the product on this skeleton, and the
maintainer who decides what it becomes. Users of the Python API and of the command
arrive with the first release; until then the only way to run `rovo` is from a
checkout ([Install and run](../how-to/install-and-run.md)).

## Related pages

- [Repository map](repository-map.md)
- [Terminology](terminology.md)
- [Decision 0007: The PyPI name](../decisions/0007-pypi-name-rovo.md)
