# 04: Guiding and filtering parameters, proven on Graph and Workspace

**Network:** two real crawls, 200 pages each, under the polite defaults: the Microsoft
Graph REST API reference and the Google Workspace API reference. Ask before each. A
dry run needs no network. The exclude test runs with `--replay` over ticket 03's HTTP
cache, which requests nothing; a replay without `--replay` may fetch pages the first
run did not reach, so it counts as a crawl and is asked for first.

**What to build:** the rest of the scope vocabulary on `scrapyproto crawl`, each flag
named after its field in `CrawlScope` (`docs/specs/mirror.allium`) or `Configuration`
(`docs/specs/rovo.allium`):

- `--start-url` and `--allowed-host`, repeatable.
- `--path-prefix`, repeatable: a URL is in scope only when its path starts with one.
- `--include` and `--exclude`, repeatable: a glob, or a regex when prefixed `re:`,
  matched against the normalised URL the way `CrawlScope.within_bounds` says: an
  exclude match keeps the URL out, and when any include is given a URL must match one.
- `--max-depth`: links beyond it are not followed.
- `--keep-query-param`, repeatable: a query parameter kept in the page identity; every
  other query parameter is dropped before scope and dedup. Default: none kept.
- `--delay`, `--concurrency`, `--user-agent`: the politeness settings, with the
  defaults ticket 03 baked in. Robots.txt stays obeyed; there is no flag to ignore it.
- `--dry-run`: print the resolved scope and the Scrapy settings the host would render,
  then exit 0 without starting the machine or crawling.

The resolved scope is stored with the run in `runs.scope`. The filter runs in the
spider, so an excluded link is never requested.

Then two recorded crawls, each with the flags it needed and a one-paragraph note in the
README naming what the site threw at the scope (locale variants in the path, query
parameters such as `?view=graph-rest-1.0` that select a version, navigation and
feedback links, redirects off the prefix) and which flag answered each:

1. The Microsoft Graph REST API reference under
   `https://learn.microsoft.com/en-us/graph/api/`.
2. The Google Workspace API reference under `https://developers.google.com/workspace/`.

**Blocked by:** 03 (the crawl command, the store and the HTTP cache).

**Status:** ready-for-agent

- [ ] `--dry-run` prints the resolved scope (hosts, prefixes, include, exclude, depth,
  page cap, kept query parameters) and the rendered settings, and crawls nothing
- [ ] An `--exclude` that matches a URL known to be in ticket 03's feed keeps that URL
  out of a new `--replay` run's feed, shown with `scrapyproto sql`, with no site request
- [ ] A `re:` pattern and a glob pattern both work, one example each in the README
- [ ] Both sites are crawled to the 200-page cap with their flags; the exact command
  lines, the summaries and the one-paragraph notes are in the README
- [ ] Pages by status for each site show whether the cap was reached with 200s or with
  redirects and errors mixed in, and the README says so
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged
