# Changelog

All notable changes to `rovo` are recorded here. The format follows Keep a Changelog
(<https://keepachangelog.com/en/1.1.0/>). Nothing has been released, so there is no
version section yet; the release ticket adds the first one and states the versioning
policy.

## [Unreleased]

### Added

- The placeholder API, `rovo.__version__`, read from the installed metadata.
- The placeholder command, `rovo --version` and `rovo version`.
- `renovate.json`: Renovate proposes updates to every pin but the two Python versions
  decision 0001 owns, each held for approval on its dependency dashboard, security fixes
  aside (decision 0008).
- The Allium gate: a placeholder root module `docs/specs/rovo.allium` that declares no
  behaviour, the `check-specs` and `analyse-specs` gates over it, the `spec-change` skill
  and the seven Allium skills with their reference material (decisions 0009 to 0011).
- The product specification: four Allium modules under `docs/specs/` (`rovo`, `crawl`,
  `mirror`, `convert`) that specify rovo as a documentation mirror, elicited from the
  product brief with two prototype specifications as evidence, with the product's terms
  in the terminology page (decision 0012). Nothing of it is implemented yet.
- The product's foundation, with no specification behaviour yet: the runtime
  dependencies httpx, beautifulsoup4, lxml and markdownify and the `browser` extra
  (playwright); the private modules `_convert`, `_mirror`, `_crawl`, `_config` and
  `_report` with a test holding their import direction; the end-to-end harness serving
  fixture sites on `127.0.0.1`, the `browser` marker and `just e2e-browser`; and decision
  0013, the mirror's state as JSON under `.rovo/`, written atomically.
- The first slice of the specification: `rovo init SITE_URL OUT_DIR [--profile NAME]`
  writes `rovo.toml` and an empty manifest, and `rovo sync OUT_DIR` reads each allowed
  host's robots.txt, fetches the seed pages it allows over HTTP, converts each to
  Markdown with the generic profile, publishes it as a page file with sorted frontmatter
  and writes `crawl-report.json`. Branches later slices implement stop the sync with
  exit 1; the mirror's files are described in `docs/reference/mirror.md`.
  When a page's path and its short-digest fallback are both held, the page takes the
  full-digest path; when that is held too, the page is refused and reported as a failed
  URL (`no free path`), and the sync exits 1. A page path is never percent-decoded.
  Page files live under `pages/<host>/`, the host segment sanitised (lower case, trailing
  dot dropped, `[a-z0-9.-]`, device names suffixed `-`, a non-default port as
  `_<port>`); hidden, device-named and root-file-named segments are rewritten, `.md` is
  not doubled only for an exact lower-case `.md`, and the 200-character limit counts the
  whole path. A host's trailing dot no longer makes a separate identity. A last URL
  segment that is only a dropped `.html`, `.htm` or `.aspx` (`/guide/.html`) is named
  `index`, as a directory URL is, where `rovo sync` used to crash.
- `rovo sync` follows links: each stored page's content and navigation links that the
  crawl scope allows one level deeper (`max_depth`, `include`, `exclude`, the path
  prefixes, the allowed hosts) are queued and fetched in later batches, each URL once.
  Every finalisation resolves every page's links against the whole mirror: a link to a
  mirrored page is written as a relative path between page files (a link between hosts
  climbs to `pages/`), every other link stays absolute, code is never rewritten, the
  `uncrawled_internal`, `unresolved_fragment` and `dangling_inbound` flags follow the
  links, the manifest keeps the links, and `crawl-report.json` lists any broken
  relative link under `broken_links`. A link to a URL that cannot be parsed (a port out
  of range) is out of bounds: it is never queued, records no link and stays as written,
  where `rovo sync` used to crash. A destination with balanced parentheses
  (`x_(y).html`) is read whole, where it was cut at its first `)`, left absolute and
  recorded as an uncrawled link. Link text is read the same way: text holding
  brackets (`see [1]`) or an image no longer hides the link, or swaps in the image.
- The mirror's indexes: every `rovo sync` finalisation writes `index.md` (a heading per
  host and per top-level directory, linking every page and every directory index),
  `_indexes/<host>/<dir>.md` for a directory holding more than 200 pages directly,
  `index.jsonl` (one entry per page), `links.jsonl` (one entry per cited URL) and
  `llms.txt`, all deterministic, UTF-8 with LF line ends, linked relative to each file
  and rewritten only when their text changes; stale directory indexes are deleted. The
  new command `rovo index OUT_DIR` rebuilds them offline from the manifest, and exits 2
  without a mirror or when a page file is missing or not UTF-8. A title in an index's link
  text has its backslashes and brackets escaped and its whitespace flattened to single
  spaces, and the `llms.txt` summary falls back from the start URLs to the root URL's
  page before the first page by path.
- `rovo sync` is polite: it reads each origin's robots.txt before anything else there and
  matches it as RFC 9309 is implemented by the new runtime dependency
  `protego>=0.7.0,<0.8`, in place of `urllib.robotparser` (so an `Allow` ending in
  `/index.html` also allows its directory, and a path ending in `$` also matches as a
  prefix with the `$` read as `%24`); a refused or unreachable robots.txt disallows its
  origin, is listed under `discovery_problems` and makes the sync exit 1. Requests to
  one host name are spaced by `1 / rate_per_host` and the longest decimal `Crawl-delay`
  of its origins, with no burst (`Crawl-delay: 0` adds none; one past `retry_after_cap`,
  however large, is never adopted and stops the sync as a later slice's branch). A
  transport error, a 429 or a 5xx is retried, robots.txt included, up to `http_attempts`
  tries with exponential backoff, jitter and `Retry-After` (seconds, however many, or an
  HTTP date, on any retryable answer); a page whose tries run out on a 5xx or a
  transport error is listed under `failed_urls` and makes the sync exit 1 (a 429 that
  runs out stops the sync as a later slice's branch).
- `rovo sync` discovers pages beyond the seeds: for each allowed host, after its
  robots.txt, it reads the sitemaps robots.txt declares, then `/sitemap.xml` and
  `/sitemap_index.xml`, sitemap indexes' children only on the index's own host (at most
  `sitemap_max_children` per host), then `/llms.txt`. Every URL they name is recorded
  under `observed_urls` in `frontier.json` and forgotten after
  `observed_url_retention_syncs` syncs unseen; the ones in scope are queued at depth 1
  with their priorities, at most `max_pages * sitemap_cap_multiplier` sitemap entries
  per host, a sitemap's `lastmod` kept on the page. A declared sitemap that fails or is
  not a sitemap is listed under `discovery_problems` and makes the sync exit 1; a
  missing declared sitemap and every failing probe are silent; a child of an index is
  declared exactly when its index is. Sitemaps and `llms.txt` are retried as robots.txt
  is; a `Retry-After` past `retry_after_cap` on a probe ends it silently and pauses the
  host for `retry_after_cap`, and every honoured `Retry-After` on a 429 or a 5xx is
  counted. A URL that cannot be normalised is skipped. `crawl-report.json`'s
  `discovered` counts the frontier's rows when discovery ends.
- `rovo sync --dry-run OUT_DIR` discovers as a sync does, prints the URL of each page
  it would fetch, one per line in the order it would take them, fetches and writes no
  page or index, and saves the manifest, the frontier, the run and the report.
- A second `rovo sync` is incremental: each page already in the mirror is fetched with
  its stored `ETag` and `Last-Modified` (none once it is older than `crawl.max_age`,
  after a settings change or when a sitemap gives a newer `lastmod`); a `304` or an
  unchanged raw document keeps the page as it is (`unchanged` in the frontier and the
  report), and a changed one is converted again. Sitemaps are saved in
  `.rovo/sitemaps.json` and requested with their validators, a `304` reusing the saved
  entries. A sync against an unchanged site rewrites no page file and no index.
- An unchanged page's stored links are queued again on every sync, so a widened scope
  reaches what it links to; `crawl.refollow_unchanged_links = false` turns that off.
  A saved sitemap is dropped when it answers `404`, `410` or not a sitemap, or after
  `observed_url_retention_syncs` runs unrequested (`last_requested_run` in
  `.rovo/sitemaps.json`). The validators (`etag`, `last_modified`) live in
  `.rovo/manifest.json` alone, never in a page's frontmatter or `index.jsonl`, so a
  moved validator over an unchanged body rewrites nothing.
- `rovo sync` keeps pages through their lifecycle: redirects are followed within the
  scope (robots.txt, sitemaps and `llms.txt` within the allowed hosts), at most
  `discovery_max_redirects` hops without a revisit; a page that answers `404` or `410`
  or redirects out of scope is removed and its file archived under `_removed/<host>/`,
  mirroring `pages/`; a page whose URL redirects elsewhere moves with its old URL as an
  alias, and one whose canonical names another page is merged into it; two URLs that
  reach one page in a sync settle as one page and a `duplicate` row; a removed page that
  answers again is revived at its path; a page a narrowed scope no longer admits is
  retired at the next finalisation. The report lists each removal once as `removed`.
- `rovo.toml` gains a `[mirror]` section, written by `rovo init`: `mirror.prune = true`
  deletes a removed page's file instead of archiving it under `_removed/` (default
  `false`). A full `rovo sync` fetches again a URL an earlier sync left settled (one
  that answered `404` or `410` with no page, a duplicate, or a moved page's old URL)
  when a page link, a sitemap or `llms.txt` names it again, once per sync. A directory
  under `pages/<host>/` keeps one spelling: a new page whose directory differs only in
  case from one a page already uses takes that spelling.
- Errors and the report: `rovo sync` settles an answer that is not HTML as
  `skipped_not_html` instead of stopping; refuses, in the specification's order and
  before any request, an invalid configuration, a changed root without the new `--yes`,
  an off-host `--url` and an unknown `--path`, each with a refused `crawl-report.json`;
  ends an interrupted or crashed run `interrupted`, publishing what it stored and
  writing the report with its `error`; prints progress as JSON lines under `--json`;
  reads `ROVO_<SECTION>__<FIELD>` variables and `--set SECTION.FIELD=VALUE` flags over
  `rovo.toml`. The new `rovo report OUT_DIR` prints the last report.
- Targeted syncs: `rovo sync --url URL` and `--path PATH` sync only the named pages,
  where they stopped with exit 1: only the targets' hosts are opened (their robots.txt
  read), no seed, sitemap or `llms.txt` is walked, each target is fetched without
  validators and exempt from `max_pages`, and every other frontier row is left as it
  was. A `--url` is checked against the resolved scope's hosts, so the first seed's
  host is allowed when `allowed_hosts` is empty.
- A page in the mirror whose URL now answers non-HTML is removed as `absent` and
  archived, where it kept its file; a URL with no page that answered non-HTML is
  fetched again when a page link, a sitemap or `llms.txt` names it again. Each `--json`
  event gains `url`, the settled row's URL on `page` and `null` otherwise. A page
  revived at a new path and removed again in one sync returns to its old path, where
  its archived copy is; when another page took that path, the copy moves to the new
  path.
- Conversion quality: what Markdown cannot carry (a complex, header-less or row-header
  table, a block definition list, `details`, math without TeX, an id on an element that
  is not a heading) reaches the page as a sanitised HTML island, where a non-heading id
  stopped the sync; every tab panel reaches the page under a profile with tab groups;
  callouts become GFM alerts, `sup`, `sub`, `kbd` and `mark` stay inline, TeX math gets
  `$` delimiters and footnotes become `[^n]`; embeds, form controls, line-number gutters,
  links in code, layout tables and footnote back-links are reduced as specified, raising
  `interactive_omitted` and `html_table_kept`, and a lost island raises
  `fidelity_loss`. The id of an element normalisation replaces (a tab group or panel, a
  tab list or label, a callout, an embed, a form wrapper, a layout table, a footnote
  section) stays an anchor, and a blank
  line in code inside an island survives as a character reference. A sync converts under
  the `devsite` and `mslearn` profiles' content, chrome, breadcrumb, tab and callout
  selections, where any profile but `generic` stopped it; an
  `mslearn` sync still stops at its sitemap filter's placeholders and its version label,
  which the specification leaves open. `quality.fail_on_low_quality = true` makes a sync
  with a low-confidence page or a broken link exit 4. The new `rovo verify OUT_DIR`
  checks the mirror on disk offline (missing, unmanaged and invalid page files, digest
  mismatches, quality drift, broken links and stale indexes; an unreadable page file is
  an invalid one), prints the findings and
  the gate tallies and exits 0, 4 with a finding, or 2 without a mirror.
