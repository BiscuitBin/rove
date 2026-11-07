# 05: The per-item DuckDB path, compared with the bulk load

**Network:** none beyond the guest `pip install duckdb==<the host's pinned version>`;
ask before the install. The comparison replays ticket 03's HTTP cache with `--replay`,
so a request not in the cache is dropped, never fetched. The cache lives on the guest
disk of the `scrapy-proto` machine: the precondition is that the machine from ticket 03
still exists (no `vm destroy` in between). If it is gone, the 25-page crawl has to be
run again, which is network, so ask first.

**What to build:** `--store per-item` on `scrapyproto crawl`, beside the default
`--store bulk` from ticket 03. The per-item path runs the same spider with a Scrapy
item pipeline that inserts each page, as it arrives, into a DuckDB file on the guest
disk with the same `pages` schema (the `html` column `USING COMPRESSION ZSTD`), checkpoints
and closes it at `spider_closed`, after which the host pulls the file back with
`read_file` to `ai_tmp/scrapy-duckdb/<run_id>-per-item.duckdb` and records the run in the
host store's `runs` table with its store kind. The feed is not written on this path.

Both paths then run with `--replay` over the same cached crawl, which makes their page
sets identical by construction and the runs free of site requests, and the README gains
one table comparing them:

| Measure | bulk | per-item |
| --- | --- | --- |
| Wall time of the run, host process start to summary printed | | |
| Peak RSS of the spider process in the guest | | |
| Store file size after `CHECKPOINT` | | |
| Host-side point lookup by URL: time and peak RSS | | |
| Host-side full scan of `html`: time and peak RSS | | |

The spider's peak RSS comes from the guest: enable Scrapy's `MEMUSAGE_ENABLED` and log
`ru_maxrss` from `resource.getrusage` at `spider_closed`. The host-side query numbers
come from a fresh subprocess per query that reports its own peak RSS, the way the
DuckDB study's `bench_queries.py` does. Sharp edges on the per-item path (one writer
per file, the pipeline blocking the reactor, what a crashed spider leaves in the file)
go in the README.

**Review:** one moment, through the README's adversarial review loop, once the table
is filled and before it is read into a conclusion, with the focus: measurement
validity; are the two runs the same pages, was the per-item file checkpointed and
closed before the pull, is the RSS the spider process's and not the guest agent's, are
the query numbers from fresh subprocesses over equally warm files, does each row of the
table compare like with like, what a crash mid-run leaves in the DuckDB file on the
guest and whether the host can tell.

**Blocked by:** 03 (the crawl command, the schema and the HTTP cache). Independent of
04.

**Status:** ready-for-agent

- [ ] `crawl --store per-item --replay` over the cached crawl ends in a summary read
  from the pulled-back file, and `scrapyproto runs` lists it with its store kind
- [ ] The bulk store and the per-item store hold identical row counts and the same set
  of `content_hash` values for the same replayed run, and neither run made a site
  request
- [ ] The comparison table is in the README with its numbers, and the method for each
  number is stated in one line
- [ ] The sharp edges of the per-item path are listed in the README with a workaround
  or a verdict each
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] The adversarial review loop ran at its moment; the hand-back lists each finding
  with its verdict and the reviewing model, and every valid finding's fix is in the
  commit
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged
