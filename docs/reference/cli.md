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
under `docs/specs/` is under way: `rovo init` creates a mirror, `rovo sync` mirrors
its seed pages, the pages its sitemaps and `llms.txt` name and the pages they link to
over HTTP and writes the mirror's indexes, and
`rovo index` rebuilds the indexes offline; the later commands (`verify`, `report`,
`fetch`) arrive with their slices. Every example on this page was run from a checkout as
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

| Argument or option | Effect |
| --- | --- |
| `OUT_DIR` | The mirror's directory, made by `rovo init`. |
| `--dry-run` | Discover as a sync does, print the pages it would fetch and fetch none of them. |

`rovo sync OUT_DIR` reads `rovo.toml`, reads each allowed host's `/robots.txt`, fetches
each seed page the robots rules allow once over HTTP with the user agent
`rovo/<version>`, converts it to Markdown with the generic profile and publishes it as
a page file at its assigned path. It follows links: each stored page's content and
navigation links that the scope (`max_depth`, `include`, `exclude`, the path prefixes
and the allowed hosts) allows one level deeper are queued and fetched in later batches,
shallowest first, each URL once. In every page file a link to a mirrored page is
rewritten as a relative path between page files, across hosts too, and every other link
stays absolute; links in code are never touched (the
[mirror reference](mirror.md#links) has the rules). It then saves the manifest, the frontier and the run
history under `OUT_DIR/.rovo/`, writes the indexes (`index.md`, `index.jsonl`,
`links.jsonl`, `llms.txt` and `_indexes/`, as [`rovo index`](#rovo-index) does), writes
`OUT_DIR/crawl-report.json` and exits with the
report's exit code. A page robots.txt disallows is skipped, not fetched. A page the
mirror has no free path for is refused: its URL is reported as failed with the error
`no free path` and the sync exits 1 (the [mirror reference](mirror.md#page-files) says
when that happens).

A later `rovo sync` of the same mirror is incremental. Every page already in the mirror
is fetched again, conditionally: the request carries the page's stored `ETag` as
`If-None-Match` and its `Last-Modified` as `If-Modified-Since`, unless the page was last
seen more than `crawl.max_age` seconds before the sync started, the processing settings
changed, or a sitemap now gives it a newer `<lastmod>`, when it is fetched without them.
A page answered `304`, or answered with the same raw document under the same settings
and with no redirect, is kept as it is: its row in the frontier is `unchanged`, its body
is not converted again and its links are not followed again; only the validators and the
sitemap `<lastmod>` the answer carries replace the stored ones. A page whose raw
document changed, or that `max_age` forces, is converted again and its page file
rewritten only when its text differs. A sitemap read before is requested with its saved
validators, and a `304` reuses the entries saved for it (`.rovo/sitemaps.json`, in the
[mirror reference](mirror.md#rovofrontierjson-and-rovorunsjson)). Against a site that
has not changed, a sync rewrites no page file and no index and exits 0. In
`crawl-report.json`, `fetched` counts every page request, `304` answers included;
`per_host`'s `fetched` counts only pages answered with a document; `converted` counts
the pages whose body changed and `skipped_unchanged` the pages seen whose body did not.

Before any page, `rovo sync` discovers pages beyond the seeds, host by host in sorted
order, once each host's robots.txt is read. It reads the sitemaps that host's robots.txt
declares (`Sitemap:` lines), in order, then `/sitemap.xml` and `/sitemap_index.xml`
where robots.txt does not declare them, then `/llms.txt`, each once per run and only
where robots.txt allows it. A sitemap is an XML `urlset` or `sitemapindex` in any
namespace; a gzip or plain-text sitemap is not one. A sitemap index's child sitemaps
are read as they come, only on the host that served the index (a child on another
host is never requested), in document order, at most `sitemap_max_children` (40) per
host; a child is declared exactly when its index is. Every URL a
sitemap lists, or an inline Markdown link of `llms.txt` points at, is recorded under
`observed_urls` in the frontier, in scope or not, and forgotten once it goes
unseen for more than `observed_url_retention_syncs` (3) syncs. Those the scope
allows are queued at depth 1 (`sitemap_depth`, `llms_txt_depth`) with the priorities
`sitemap_priority` (50) and `llms_txt_priority` (40), after the seeds and before links,
at most `max_pages * sitemap_cap_multiplier` (20000) sitemap entries per host; a
sitemap's `<lastmod>` is kept on the page as `sitemap_lastmod`. A URL that cannot be
normalised (a port out of range or an unclosed IPv6 bracket) is skipped, and so is a
declared or child sitemap whose URL cannot be, with no problem raised. A declared sitemap that answers with an
error other than 404 or 410, its retries spent, is listed under `discovery_problems` as
`sitemap_unavailable`, one that never
answers as `sitemap_unreachable`, and one that answers but is not a sitemap as
`not_a_sitemap`, and each makes the sync exit 1; a declared sitemap that is missing
(404 or 410) is silent, and so is every failure of `/sitemap.xml`, `/sitemap_index.xml`
and `/llms.txt` where robots.txt does not declare them, and of the children of an index
it does not declare.

`rovo sync --dry-run OUT_DIR` makes the same discovery requests, robots.txt, the
sitemaps and `llms.txt`, and then stops: it fetches, converts and writes no page and
writes or rewrites no index. It prints on standard output, one per line and nothing
else, the URL of each queued page it would fetch, in the order the sync would take them:
the seeds first, then shallowest, then highest priority, then in discovery order. It
saves the manifest, the frontier (so a later sync starts from the rows it queued) and a
row in the run history with `dry_run: true`, writes `crawl-report.json` with
`options.dry_run: true` and `fetched: 0`, and exits 1 for a discovery problem, else 0.

`rovo sync` is polite to the site. It reads each origin's `/robots.txt` (scheme, host
and port, as RFC 9309 scopes it) before anything else there, a second port of a host
included, and judges every URL by its own origin's file with RFC 9309 matching as
`protego` 0.7 implements it: the longest matching path wins, `Allow` wins a tie, `*`
matches any run of characters and a final `$` anchors the end of the path. Two
consequences of that matcher differ from literal RFC 9309. An `Allow` path ending in
`/index.html` (no final `$`) also allows its directory, so `/private/` is allowed under
`Disallow: /private/` and `Allow: /private/index.html`. A line whose path ends in `$`
also matches as a prefix with that `$` read as `%24`, so under `Disallow: /private/`,
`Allow: /private/$` allows `/private/$secret` (and `/private/%24secret`) as well as
`/private/`, and `Disallow: /x$` disallows `/x$y` as well as `/x`. A
robots.txt that answers 401, 403, 429 or 5xx is refused, and one that never answers is
unreachable: either disallows that whole origin, is listed under `discovery_problems`
in `crawl-report.json` and makes the sync exit 1; a missing robots.txt (404) allows
everything. Requests to one host name are spaced, with no burst, by at least
`1 / rate_per_host` (2 per second) and by the longest `Crawl-delay` any of its origins
declares for `rovo`, read as decimal seconds; `Crawl-delay: 0` adds no delay, and one
past `retry_after_cap` (120 s), however large, is never adopted. A
transport error, a 429 or a 5xx is retried, robots.txt, sitemaps and `llms.txt` included, up to `http_attempts`
(5) tries in all, waiting `backoff_base * 2^(try - 1)` capped at `max_backoff` (1 s
doubling to 16 s), with 25% jitter either way, and at least the `Retry-After` an answer
gives in seconds or as an HTTP date; nothing is requested from the host before that wait
ends, and the host's `retry_after_honored` counts each honoured `Retry-After` that came with a 429
or a 5xx. A `Retry-After` past `retry_after_cap` (120 s) on `/sitemap.xml`,
`/sitemap_index.xml`, `/llms.txt` or a child of an undeclared index ends that request
silently, with no retry, and pauses the host for `retry_after_cap` (never shortening a
longer pause); the sync then carries on. A page
whose tries run out is listed under `failed_urls` with its tries and makes the sync exit
1; a page robots.txt disallows is listed under `unresolved_urls` but alone leaves the
exit 0. Retries and waits print nothing; progress output is a later slice's.

It exits 2 and writes no report when `OUT_DIR` is not a directory, holds no manifest or
holds one that does not parse, or when the configuration is invalid (a value of the
wrong type, a root or start URL that is not an http or https URL, a host that does not
parse, a `max_age` that is not a finite number of seconds), names no root or
start URL, sets `unblocking.provider`, changes the root URL the last run recorded,
needs a browser or stealth engine that is not installed, or sets `robots = "ignore"`.
The refusal is printed on standard error; the specification's refused report arrives
with a later slice. When a run reaches a branch a later slice implements (a redirect,
robots.txt's, a sitemap's and `llms.txt`'s included, a 404, a block, a 429 that survives its retries, a `Retry-After`
past `retry_after_cap` (120 s), however large, on a page, robots.txt or a declared sitemap, a `Crawl-delay` past it, which retires
the host as soon as its robots.txt is read, a host whose failures trip its breaker, a
canonical URL that moves a page in the mirror onto another page, a non-HTML answer for a
page in the mirror, a link to a missing page or to a URL that answers
with a redirect or a non-HTML file, a profile other
than `generic` or one whose sitemap filter holds a `{section}` or `{locale}` placeholder,
a login form, a source id on an element that is not a heading), the sync stops, names the rule on standard error, exits 1 and leaves the
previous report in place.

## `rovo index`

```text
Usage: rovo index [OPTIONS] OUT_DIR

Rebuild index.md, index.jsonl, links.jsonl, llms.txt and _indexes/ offline.
```

`rovo index OUT_DIR` rebuilds the mirror's indexes from its manifest and exits 0. It
makes no request, re-resolves no link and reads nothing from the page files but that
each exists and is UTF-8: every index entry comes from the manifest. It writes each
index file only when its text differs, deletes every file under `_indexes/` the indexes
no longer hold, and writes no manifest, frontier, run or report. Run over an unchanged
mirror, it changes no file. The [mirror reference](mirror.md#indexes) gives each file's
text.

It exits 2, writing nothing, when `OUT_DIR` is not a directory, holds no manifest or
holds one that does not parse, or when a written page's file is missing or is not
UTF-8; standard error names the problem, and the page file's path.

## Exit codes

| Status | Meaning |
| --- | --- |
| 0 | Success: a version line or help was printed, a mirror was created, a sync finished with nothing to report, or the indexes were rebuilt. |
| 1 | Partial: a sync recorded a failure, or stopped at a branch a later slice implements. |
| 2 | Usage error: no command given (the help goes to standard output; standard error is empty), an unknown command (`No such command`), an unknown option (`No such option`), a missing or extra argument, or a refused `init`, `sync` or `index`; for the parser's errors, the usage line and the error go to standard error. |
| 3 | Blocked: a host's breaker tripped (reached by a later slice). |
| 4 | Quality: `fail_on_low_quality` is set and a page touched this run is low confidence, or a relative link in a page file is broken. |

The exit code of a sync is the most severe that applies, in the order of the table.

Help is rendered by rich, in boxes sized to the terminal; the plain usage lines above
are their text.

## Related pages

- [Install and run](../how-to/install-and-run.md)
- [The mirror on disk](mirror.md)
- [API reference](api.md)
- [Decision 0003: The command line](../decisions/0003-typer-cli-and-lazy-import.md)
