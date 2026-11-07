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
over HTTP and writes the mirror's indexes, `rovo verify` checks the mirror on disk
offline, `rovo index` rebuilds the indexes offline, `rovo report` prints the last
report and `rovo fetch` prints one page's Markdown. Every example on this page was run from a checkout as
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
| `--profile NAME` | A catalogue profile (`generic`, `mslearn`, `devsite`). By default the URL's host picks one, else `generic`. `generic` takes the content from `main`, else `article`; `devsite` from the DevSite article body, with its breadcrumbs, its `devsite-selector` tab groups and its note, caution and warning callouts; `mslearn` from the Learn article content, with its `tabGroup` tab groups and its alert callouts. Under `mslearn` a sitemap is read only when its URL matches the profile's filter, `{section}` matching as `*` does and `{locale}` the scope's pinned locale, else any of the profile's locale codes, and a page whose URL carries `?view=` is stored with `@` and its version label before `.md` (the [mirror reference](mirror.md) has the path). A page none of these selections matches is taken by the fallback extractor (trafilatura), else whole. |

`rovo init` writes `OUT_DIR/rovo.toml`, every key with its default (the sections
`site`, `scope`, `conversion`, `crawl`, `quality`, `mirror` and `unblocking`), and an
empty manifest at `OUT_DIR/.rovo/manifest.json`, and makes no request. The scope it writes
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
| `--yes` | Confirm a root URL that changed since the last run (`options.confirmed`). |
| `--json` | Print progress on standard output, one JSON event a line (`options.json_events`). |
| `--url URL` | Name a URL to sync; repeatable (`options.urls`). |
| `--path PATH` | Name a written page by its mirror-relative path, `pages/<host>/...`; repeatable (`options.paths`). |
| `--set SECTION.FIELD=VALUE` | Override one `rovo.toml` key; repeatable, a later one winning. |

The configuration is resolved key by key from four layers, a later one winning: the
built-in defaults, `rovo.toml`, the environment variables named
`ROVO_<SECTION>__<FIELD>` (section and field are `rovo.toml`'s `[section] field` names,
matched case-insensitively, so `ROVO_MIRROR__PRUNE=true` sets `mirror.prune` and
`ROVO_CRAWL__REFOLLOW_UNCHANGED_LINKS=false` sets `crawl.refollow_unchanged_links`), then
each `--set`. A variable's or flag's value is read as one TOML value (`3`, `true`,
`["/a/"]`, `"x"`), and a value that is not one is the raw string. A bad value, an
unknown section or an unknown key from any layer, and a `--set` with no `=` or no `.`,
make the configuration invalid, each named by its key path in `configuration.problems`
(`scope.max_depth: invalid value 'deep'`). A `ROVO_` variable with no `__` is not a
configuration variable and is ignored. The configuration's `hash` covers the resolved
values, so it moves with a variable or a flag.

A `--url` or a `--path` that passes the refusals below names a targeted run: only the
named pages are synced. Each `--url` is normalised to its identity and each `--path`
names the written page that holds it (a directory prefix is no page's path and is
refused). The run opens only the targets' hosts, so their robots.txt is read, walks no
seed, sitemap or `llms.txt`, and fetches each target without validators, a target being
exempt from `max_pages`; a target with no frontier row gets one. Links a target's page
adds are queued pending and fetched by a later full sync; every other row is left as it
was. The report lists the `targets` and its `options` record the run as `targeted`.

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

`crawl.render_mode` decides when the browser tier renders a page, in headless Chromium
through playwright (the `browser` extra, and a browser `playwright install` fetched).
Under `"never"`, the default, every page is fetched over HTTP, and a page whose answer
needs JavaScript (an empty application root, a `<noscript>` notice, no main element,
or thin text on a large page) is stored from that answer with `render_needed` among its
`quality_flags`, so it is low confidence. Under `"auto"` such a page climbs to the
browser: its HTTP answer is rendered, the page is stored from the rendered document
with `tier: "browser"`, and the host's report row counts one `render_escalations`. A
render that gets no response, or does not reach its `load` state within
`render_max_wait` (20 seconds), falls back to the HTTP answer, flagged `render_needed`;
a render that is blocked stays blocked. A blocked HTTP answer never climbs: the browser
renders content, it never answers a block. A page that climbed because of an empty
application root or a `<noscript>` notice teaches its host and path pattern (the
first two path segments) to start at the browser, kept as `tier_hints` in
`.rovo/frontier.json`: the next sync renders it with no HTTP try, until
`reprobe_every_syncs` (5) runs after it was learned, when HTTP is tried again. Under
`"always"` every page is rendered and none is fetched conditionally (validators are
HTTP only). A render makes no request of its own: its navigation is made as an HTTP
try is (robots.txt, redirects, the host's limiter, the `rovo/<version>` user agent),
and each request the page makes is made the same way only to an allowed host whose
robots.txt allows it, once, its `Retry-After` pausing the host that answered it (after
any redirect; the host it was sent to when that one is not open), under that host's
policy, for at most `retry_after_cap`, never retiring a host or feeding a breaker; any
other request, one to a CDN included, is aborted. The navigation's
own answer is an HTTP answer's equal for `Retry-After`: it pauses the host (the render is
never retried), counts toward `retry_after_honored` and, past `retry_after_cap`, retires
the host. A walk that climbed counts its `render_escalations` whatever its outcome,
one that retires its host or stops on a tripped one included. A sync whose
`render_mode` is not `"never"` is refused before any request unless both the playwright
package and its Chromium (`playwright install chromium`) are installed; the message
names the missing piece and the two ways forward, `playwright install chromium` or
`render_mode = never`. The default, `"never"`, needs neither.

A later `rovo sync` of the same mirror is incremental. Every page already in the mirror
is fetched again, conditionally: the request carries the page's stored `ETag` as
`If-None-Match` and its `Last-Modified` as `If-Modified-Since`, unless the page was last
seen more than `crawl.max_age` seconds before the sync started, the processing settings
changed, or a sitemap now gives it a newer `<lastmod>`, when it is fetched without them.
A page answered `304`, or answered with the same raw document under the same settings
and with no redirect, is kept as it is: its row in the frontier is `unchanged`, its body
is not converted again; only the validators and the sitemap `<lastmod>` the answer
carries replace the stored ones. Its stored links (the content links the last sync
resolved, not its navigation links) are tested again against the scope in force and
queued, so a scope widened since the page last changed reaches the pages it links to;
`crawl.refollow_unchanged_links = false` in `rovo.toml` turns that off. A page whose raw
document changed, or that `max_age` forces, is converted again and its page file
rewritten only when its text differs. The validators live in `.rovo/manifest.json`
alone, so a server that sends a new `ETag` or `Last-Modified` over the same document
rewrites nothing. A sitemap read before is requested with its saved validators, and a
`304` reuses the entries saved for it (`.rovo/sitemaps.json`, in the
[mirror reference](mirror.md#rovofrontierjson-and-rovorunsjson)); a sitemap that now
answers `404`, `410` or not a sitemap loses its saved entries. Against a site that has
not changed, a sync rewrites no page file and no index and exits 0. In
`crawl-report.json`, `fetched` counts every page request, `304` answers included;
`per_host`'s `fetched` counts only pages answered with a document; `converted` counts
the pages whose body changed and `skipped_unchanged` the pages seen whose body did not.

A sync keeps the mirror's pages through their lifecycle. A redirect (301, 302, 303, 307
or 308 with a `Location`) is followed when its target is within the scope, at most
`discovery_max_redirects` (5) hops, never back to a URL already visited, each hop
waiting its turn at its host name's limiter after its origin's robots.txt is read; the
validators go on the first request only. The page is stored under the URL that answered,
and every URL on the way becomes an alias of it. A redirect that loops, passes the hop
limit or leaves the scope is not followed; nor is a hop robots.txt disallows (`redirect
disallowed by robots.txt`), and a 3xx with no `Location` fails with its status. A page in
the mirror that now answers `404` or `410`, or redirects out of the scope, is removed:
its record keeps its path (`removal_reason` `absent` or `redirected_out`, the target in
`redirect_target`), its file is archived under `_removed/<host>/` at the path it had
under `pages/<host>/` (deleted instead with `mirror.prune = true` in `rovo.toml`), links
to it become `dangling`, and the report lists it once as
`removed`. A URL with no page that answers `404` or `410` is silent; one that loops,
passes the hop limit or redirects out of scope is listed under `failed_urls`. A page
whose URL now redirects to a URL no page holds moves there: it keeps its record, takes
the new path, its old file goes and the report lists it `moved` with `moved_from`; links
to the old URL are rewritten to the new file. A page whose new canonical URL names
another page in the mirror is merged into it (`removal_reason` `merged`, its URL an
alias of the page that stays). Two URLs that reach one page in the same sync give one
page: the second is a `duplicate` row in the frontier and an alias. A removed page that
answers again is written again, at its old path when that is free, and listed `added`;
its archived copy goes. A page whose source URL the scope in force no longer admits (a
narrowed `path_prefixes`, say) is not requested and is removed (`out_of_scope`) when the
sync finalises. Files move only then, after the run: an interrupted sync leaves the
pages and the archive as the last finished sync left them. A directory under `pages/` or
`_removed/` left empty is removed. A URL an earlier sync left settled with no page of
its own (one that answered `404` or `410`, a duplicate, a moved page's old URL, or one
that answered non-HTML) is
fetched again, once per sync, when a page link, a sitemap or `llms.txt` names it again;
an old URL that now answers its own page takes back the page it led to.

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
everything. A robots.txt, a sitemap or `llms.txt` that redirects is followed within the
allowed hosts, at most `discovery_max_redirects` (5) hops and never back to a URL already
visited; a robots.txt redirect is followed with no further robots.txt read. A redirect
that is not followed, or a 3xx with no `Location`, counts as unreachable: for robots.txt
it disallows the origin (`robots_unreachable`). A redirect hop onto a retired host is
never requested: the try is the error `redirect to a retired host`, retried as any error
is, so robots.txt, its tries spent, is unreachable and a page fails with that error,
unless the retired host is the page's own (below). Requests to one host name are spaced, with no burst, by at least
`1 / rate_per_host` (2 per second) and by the longest `Crawl-delay` any of its origins
declares for `rovo`, read as decimal seconds; `Crawl-delay: 0` adds no delay, and one
past `retry_after_cap` (120 s), however large, is never adopted. A
transport error, a 429 or a 5xx is retried, robots.txt, sitemaps and `llms.txt` included, up to `http_attempts`
(5) tries in all, waiting `backoff_base * 2^(try - 1)` capped at `max_backoff` (1 s
doubling to 16 s), with 25% jitter either way, and at least the `Retry-After` an answer
gives in seconds or as an HTTP date; nothing is requested from the host before that wait
ends, and the host's `retry_after_honored` counts each honoured `Retry-After` that came with a 429
or a 5xx, a render's navigation answer included. Once the host a robots.txt, sitemap or
`llms.txt` request is for has tripped, that request makes no further retry or hop and
ends with the answer it holds. A `Retry-After` past `retry_after_cap` (120 s) on `/sitemap.xml`,
`/sitemap_index.xml`, `/llms.txt` or a child of an undeclared index ends that request
silently, with no retry, and pauses the host for `retry_after_cap` (never shortening a
longer pause); the sync then carries on. A page
whose tries run out is listed under `failed_urls` with its tries and makes the sync exit
1; a page robots.txt disallows is listed under `unresolved_urls` but alone leaves the
exit 0. Retries and waits print nothing unless `--json` is given.

An ok answer that is not HTML (a `.txt` served `text/plain`, say) counts as fetched and
settles its frontier row `skipped_not_html`: no page is written and nothing is reported
for it, and the exit code is unaffected. A URL with no page that answered so is
requested again by a later sync only when a page link, a sitemap or `llms.txt` names it
again. A page in the mirror whose URL now answers so is removed as a `404` is
(`removal_reason` `absent`, its file archived under `_removed/`, a `removed` change),
and its row is still `skipped_not_html`. A page whose tries run out, or
that answers an error, is listed under `failed_urls` and as a `failed` change, and every
later sync requests it again.

A page that answers 401 or 403, or 429 once its retries are spent, is blocked: no page
is written (a page already in the mirror is kept as it is), it is listed under
`blocked_urls` with its status, the status text as its signature and its tier, and the
sync exits 1. A page answering 200 whose main text falls under `soft_block_ratio` (0.1) of the median
of its host's recent pages, once `median_min_pages` (5) of them are known, or that holds
a password form (a login wall), is converted and flagged `soft_block_suspected` and low
confidence; it never counts against the host. Each host has a breaker: once
`min(breaker_window, breaker_min_outcomes)` (10) pages have settled and more than
`block_rate_threshold` (0.2) of them were blocked or failed outright, the breaker trips.
A `Retry-After` past `retry_after_cap` (120 s), however large, on a page (rendered or
not), robots.txt or a declared sitemap, or an honoured `Crawl-delay` past it, retires the host the same way:
the answer stands (a page answering 429 is blocked, a 503 fails; robots.txt is refused;
a declared sitemap is `sitemap_unavailable`). A tripped host gets no further request of
any kind for the rest of the sync, robots.txt, sitemaps, `llms.txt` and redirect hops
included; a declared sitemap left unread is not reported. A page whose own robots.txt
read retired its host is never requested, and a page being fetched when its host trips
(a redirect hop's robots.txt retiring it included) makes no further try, retry or
redirect hop; an answer it already holds settles as usual, so a good page is still
written. These and the host's remaining pages are listed under `skipped_urls` (in a
`--url` or `--path` sync, only the targets), the report has
`breaker_tripped: true` and the host's `per_host` row its `blocked`, `block_rate` and
`breaker_tripped`, and the sync exits 3. Another host's pages are still fetched.
An answer belongs to the host that answered it: when a page, robots.txt, a sitemap or
`llms.txt` redirects to another open host, that host's `Retry-After` pause, its
`retry_after_honored` count and a retirement past `retry_after_cap` fall on that
destination host, never on the host the request began at, and a page's redirected
answer also feeds the destination host's breaker one outcome, so it can trip. The page
itself, its tallies and its `per_host` row stay with the host it began at, and a
redirected robots.txt's rules and `Crawl-delay` stay with the origin that asked for it.

With `--json`, progress goes to standard output as one JSON object a line,
`{"event": ..., "host": ..., "until": ..., "url": ...}`, keys sorted, `until` an ISO
8601 UTC timestamp or `null`, `url` `null` on every event but `page`: `start` once, when
the run is created, `page` once for each row a fetch settles (naming its host and its
URL), `host_backoff` as a host is paused for a retry (naming the host and when the pause
ends), `breaker_tripped` as a host's breaker trips (naming the host), `owner_testing_warning`
once, before the first request of an owner-testing run (every field `null`), and one
`done`, last, once the report is written. A dry
run's listing stays plain text, ahead of its `done`. Without `--json` nothing is printed
for progress, and a refused sync prints no event.

An operator interrupt (Ctrl-C) or an uncaught error during the run ends it
`interrupted`: the rows being fetched go back to pending, the pages stored so far are
published, links and indexes are rewritten, and `crawl-report.json` is written with
`report_status: interrupted`, `error` `null` for an interrupt or
`"<ExceptionType>: <message>"` for an error, and exit 1; the next sync fetches the rows
again. An error or an interrupt after the run (while finalising, saving or assembling
the report) writes the report as it stands with that `error`, `report_status:
interrupted` and exit 1; the manifest and the frontier are saved only when the
finalisation finished before it, and the run is recorded in `.rovo/runs.json`, so the
next sync takes the next run id.

It exits 2 and writes no report when `OUT_DIR` is not a directory, holds no manifest or
holds one that does not parse. Otherwise a sync is refused, once, for the first of these
problems, in this order, before any request: an invalid configuration (a value of the
wrong type, a root or start URL that is not an http or https URL, a host that does not
parse, a `max_age` that is not a finite number of seconds, a bad variable or `--set`),
no root or start URL, or `unblocking.provider` set (`"invalid configuration"`); a root
URL that differs from the one the last run recorded, without `--yes` (`"changed root
requires confirmation"`); a `--url` that is not http or https, or not on an allowed host
of the resolved scope (`allowed_hosts`, or the first seed's host when that is empty)
(`"invalid or off-host target"`); a `--path` that is not a written page's path, a removed
page's included (`"unknown target path"`); a browser or stealth engine the configuration
needs that is not installed, the browser's being the playwright package and its
Chromium (`"configured tier is not installed"`; standard error names the missing piece
and both fixes); `robots = "ignore"` in a standard sync
(`"robots = ignore is only for an owner-testing run"`), or an invalid owner-testing
request (see [Owner testing](#owner-testing)). The refusal is printed on
standard error, and `crawl-report.json` is replaced by a refused report:
`report_status: refused`, `run_id: null`, `exit_code: usage`, `refusal_reason` the text
quoted above, the resolved `configuration` (with its `problems`), the `options` asked
for, `effective_policy: null` and every count and list empty; it exits 2. A refused
sync saves no manifest, frontier or run.

### Owner testing

An owner-testing sync retries, under a relaxed policy, the URLs a finished run left
unresolved on hosts the operator has declared as their own. It has no command-line
spelling yet (the specification's open question): it is reached in process only, through
`rovo._commands.save_ownership(out_dir, hosts)`, which saves the declaration in the
manifest (an empty set revokes it; a host outside the allowed hosts exits 2, nothing
saved; no request is made), and `rovo._commands.sync(out_dir, ..., owner_test=...)`. The
declaration alone relaxes nothing: a standard sync of a declared mirror is as polite as
any. The request names a preceding run, its hosts, the politeness controls it disables
and the values it supplies; `robots = "ignore"` in `rovo.toml` is accepted and ignored,
and only disabling the `robots` control ignores robots.txt. It is refused, with exit 2
and no request, after the refusals above and in this order: a `--url` or `--path`; no
host, or a host outside the allowed hosts; a host without a saved declaration; no
finished, non-dry preceding run of the current scope in `.rovo/runs.json`; no finished,
non-dry, non-targeted standard baseline of that scope (the preceding run, or the one it
followed); a rate or concurrency that is not positive, a backoff or pause that is
negative, a retry cap or challenge timeout that is not positive; a control both disabled
and given a value; interactive challenges without a person at the terminal, rendering,
protection escalation and an installed browser; access naming an unselected host.
`--yes` waives none of it. Its refused report is in `mode: owner_testing`, with the
requested options and the preceding run's id.

Every owner-testing run and every owner refusal prints a warning on standard error,
before any request: the settings are only for websites the operator owns, ownership is
self-declared, not verified, and the selected hosts and settings. The run seeds only the
preceding run's unresolved URLs on the selected hosts within the scope (none means no
fetch, never a full recrawl), reads no sitemap or `llms.txt`, and follows only links on
those hosts that are unseen or unresolved. The relaxed policy applies to the selected
hosts alone; every other host is fetched under the standard policy, and an answer a
selected host's request is redirected to on another host is judged by that host's
standard policy: its pause, its retirement and its breaker, which stays on even when the
request disables the breaker. With protection
escalation a host's breaker climbs a tier (pausing the host and lowering its rate)
before it trips. No stealth engine exists, so a request that needs the stealth tier is
refused, and no challenge is recognised or prompted for (both open questions). The run
exits 1 when it leaves URLs unresolved; its report records the declared hosts, the
baseline and preceding runs, the requested options (access never) and each host's
effective policy.

## `rovo fetch`

```text
Usage: rovo fetch [OPTIONS] URL

Print one page's Markdown. Nothing is written.
```

| Argument or option | Effect |
| --- | --- |
| `URL` | The page to fetch, an http or https URL. |
| `--tier TIER` | Fetch at this tier only, `http`, `browser` or `stealth`; by default `render_mode` decides. |
| `--config PATH` | Read this `rovo.toml`: its shared sections, then its `[fetch]` section. |

`rovo fetch URL` fetches one page and prints its Markdown body, without frontmatter, on
standard output, and exits 0. It needs no mirror. Without `--config` it uses the
built-in defaults: the profile is the one the catalogue picks by the URL's host, the
scope is the URL's own host, any path on it (it decides which redirects are followed),
and `render_mode` is `"never"`. With `--config PATH` it reads that file's
shared sections, then its `[fetch]` section, whose `render_mode` and `profile` override
theirs ([the mirror reference](mirror.md#rovotoml) lists the keys); no `ROVO_` variable
is read. The file's `[scope]` then decides which redirects are followed, by a sync's
test, its seeds defaulting to the URL; with no profile named, the catalogue's pick for
the URL's host applies. The policy is the standard one. The URL's `/robots.txt` is read
first, and every request is paced and retried as a sync's is. `--tier` runs that tier
only: `--tier http` is fetched over HTTP and never rendered, `--tier browser` renders the
page in the browser, as a sync does. With no `--tier`, `render_mode` means what it means
for a sync: `"never"` is HTTP only, `"auto"` starts over HTTP and climbs to the browser
only when the page needs rendering, never to answer a block, and `"always"` starts at
the browser. It writes no file: no mirror, report, frontier or run.

It exits 1 and prints nothing when robots.txt disallows the URL (the page is never
requested), or when the answer is blocked, is not HTML, is not a success, or never
came. It exits 2 with no request, the problem on standard error, for `--tier stealth`
or a URL that is not http or https (owner testing and the stealth tier need a mirror and
an owner-testing sync); for a `--config` that cannot be read or parsed, holds an unknown
section or key or a bad value, names a profile the catalogue lacks or sets
`unblocking.provider`, every bad key path named; and, when the page could be rendered
(`--tier browser`, or no `--tier` under `render_mode` `"auto"` or `"always"`), when the
playwright package or its Chromium is not installed, naming the missing piece and both
fixes, as a sync does. `--tier http` is never refused for a missing engine.

## `rovo verify`

```text
Usage: rovo verify [OPTIONS] OUT_DIR

Check the mirror on disk offline: print each finding and the gate tallies.
```

`rovo verify OUT_DIR` checks the mirror's files against its manifest, offline: it makes
no request and writes nothing, neither the manifest, the state files, the report nor a
page. Each finding is one line on standard output, `<reason> <path> <detail>`, sorted
by path, reason and detail, every path relative to `OUT_DIR`:

| Reason | Finding |
| --- | --- |
| `missing_file` | A written page's file is gone. |
| `unmanaged_file` | A Markdown file under `pages/` the manifest does not know, or under `_indexes/` the indexes would not write. Anything else at the root (`.git/`, a `README.md`) is the operator's and never reported. |
| `invalid_page_file` | A page file that is not UTF-8, has no frontmatter, a frontmatter that does not parse, or one missing a required key. |
| `digest_mismatch` | A body whose digest differs from the frontmatter's or the manifest's `content_digest`; the detail is the body's digest. |
| `quality_drift` | A gate that fails when the file's body is measured against the stored expected counts but did not fail when the page was measured; the detail is the gate. |
| `broken_link` | A relative link in a page file or a generated index that leaves the mirror, reaches no file or names a fragment the target file does not hold; the detail is the link. |
| `index_stale` | An index file whose text differs from what `rovo index` would write. |

After the findings, one `<gate> <pages>` line per gate that failed on any written page
when it was measured, sorted by gate, for example `code_lang_rate 1`. It exits 0 with no
finding and 4 with any; the tallies never move the exit code. It exits 2, printing the
problem on standard error and nothing on standard output, when `OUT_DIR` is not a
directory, holds no manifest or holds one that does not parse; an unreadable page file
is a finding, not a usage error.

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

## `rovo report`

```text
Usage: rovo report [OPTIONS] OUT_DIR

Print the mirror's last crawl-report.json.
```

`rovo report OUT_DIR` prints `OUT_DIR/crawl-report.json` as the last sync wrote it, a
refused one included, on standard output and exits 0. It exits 2, printing the problem
on standard error and nothing on standard output, when `OUT_DIR` is not a directory,
holds no manifest or holds one that does not parse, or has no report that reads as
JSON. It makes no request and writes nothing.

## Exit codes

| Status | Meaning |
| --- | --- |
| 0 | Success: a version line or help was printed, a mirror was created, a sync finished with nothing to report, a verify found nothing, the indexes were rebuilt, the report was printed, or a fetch printed its page. |
| 1 | Partial: a sync recorded a failure, was interrupted or crashed, or an owner-testing sync left URLs unresolved; or a fetch printed no page. |
| 2 | Usage error: no command given (the help goes to standard output; standard error is empty), an unknown command (`No such command`), an unknown option (`No such option`), a missing or extra argument, a refused `init`, `sync`, `verify`, `index` or `fetch`, or `report` with no report; for the parser's errors, the usage line and the error go to standard error. |
| 3 | Blocked: a host's breaker tripped, by its block rate or a host retirement. |
| 4 | Quality: `fail_on_low_quality` is set and a page touched this run is low confidence, or a relative link in a page file is broken; or `rovo verify` found anything. |

The exit code of a sync is the most severe that applies, in the order of the table.

Help is rendered by rich, in boxes sized to the terminal; the plain usage lines above
are their text.

## Related pages

- [Install and run](../how-to/install-and-run.md)
- [The mirror on disk](mirror.md)
- [API reference](api.md)
- [Decision 0003: The command line](../decisions/0003-typer-cli-and-lazy-import.md)
