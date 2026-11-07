# 03: Tracer: seeds in, pages in DuckDB out

**Network:** one real crawl, capped at 25 pages, against one target site, under the
polite defaults below. Ticket 02 ends with `vm destroy`, so the first `vm up` here
creates the machine again: the guest image pull and the guest `pip install scrapy`
recur. Ask before the crawl and before the create.

**What to build:** `scrapyproto crawl --start-url U [--allowed-host H] --max-pages N`,
the thinnest path from seeds to queryable pages. The host renders a Scrapy spider and
its settings into the guest with `write_file` and runs it with `exec`, with the polite
defaults baked in: `ROBOTSTXT_OBEY=True`, `CONCURRENT_REQUESTS_PER_DOMAIN=2`,
`DOWNLOAD_DELAY=1`, `CLOSESPIDER_PAGECOUNT` from `--max-pages`, a User-Agent naming the
prototype, and `HTTPCACHE_ENABLED=True` with the cache directory on the guest disk so
a later run can replay this one. `--replay` sets `HTTPCACHE_IGNORE_MISSING=True` as
well, so a request not in the cache is dropped instead of fetched and the replay makes
no site request at all; without it Scrapy's default cache policy downloads whatever the
first run did not reach. `--allowed-host` defaults to the start URL's host. The spider follows same-host links only, records the depth from
the seed, and writes the feed as JSONL in the guest, one object per page: `url`,
`final_url`, `status`, `content_type`, `depth`, `referrer` (the Referer header sent),
`outlinks`, `fetched_at`, `content_hash`, `html`.

When the run ends the host pulls the feed with `read_file` into
`ai_tmp/scrapy-duckdb/feeds/<run_id>.jsonl` and bulk-loads it into
`ai_tmp/scrapy-duckdb/prototype.duckdb` with DuckDB's JSON reader: a `runs` table
(`run_id`, `started_at`, `finished_at`, `start_urls`, `scope` as JSON, `pages`,
`wall_seconds`) and a `pages` table (`run_id`, `url`, `final_url`, `status`,
`content_type`, `depth`, `referrer`, `outlinks`, `fetched_at`, `content_hash`, `html`
declared `USING COMPRESSION ZSTD`). Then it prints the run summary read back from
DuckDB: pages by status, bytes of HTML, a depth histogram, wall time, and the store
file size after `CHECKPOINT`. Two more commands read the same file: `scrapyproto runs`
lists the `runs` table, and `scrapyproto sql "<query>"` prints a query's result.

A crawl with the machine stopped or absent exits 1 before any request, naming
`scrapyproto vm up`. A spider that exits non-zero is reported with its last lines of
output and exits 1; the feed, if any, is still pulled.

**Review:** two moments, each through the README's adversarial review loop. First,
before the real crawl, with the spider and settings the host would render written to
an untracked file inside `prototypes/scrapy-duckdb/` so the working-tree review reads
them (deleted before `just check`), with the focus: would this spider make
an impolite, unbounded or off-host request; robots, delay, concurrency, the page cap,
the allowed hosts, redirects off the host, retries on 429 and 503, the cache capturing
the run for replay. This moment gates the crawl: the crawl is asked for only after its
valid findings are fixed. Second, once the bulk load and the summary work, with the
focus: data loss between feed and store; a page in the feed but not in `pages`, a
duplicate URL, a `runs` row without pages or pages without a `runs` row, a crash between
pull and load, a summary that disagrees with the table, HTML that is not UTF-8, a
spider that exits non-zero after writing a partial feed.

**Blocked by:** 02 (a machine that stays up between invocations, with Scrapy in it).

**Status:** ready-for-agent

- [ ] One crawl of 25 pages against one target site ends in a printed summary read
  from DuckDB: pages by status, bytes, depth histogram, wall time, store size
- [ ] `scrapyproto runs` lists the run; `scrapyproto sql` answers a query over `pages`
- [ ] `vm down` then `crawl` exits 1 with a message naming `vm up`, before any request
- [ ] The HTTP cache on the guest disk holds the run, so a second `crawl --replay` with
  the same seeds and cap finishes with no site request (shown by the spider's cache and
  downloader stats) and the same page count
- [ ] The crawl's real output and the summary are quoted in the README
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] The adversarial review loop ran at both moments, the first before the crawl; the
  hand-back lists each finding with its verdict and the reviewing model, and every
  valid finding's fix is in the commit
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged
