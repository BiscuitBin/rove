# 14: Two runs on one mount, and a crawl past 200 pages

Tickets 07 to 09 live on PR #14 (`rocksdb-scrapy-duckdb-prototype`, at `63ec30e`).

**Network:** creating the second machine (image pull and guest `pip install`), seeding its HTTP cache
with a live crawl if the concurrent runs replay, and one live crawl of about 1,000 pages, which takes
roughly 20 minutes at the 1 s delay. Ask before the create and before each crawl.

**What to build:** two probes.

*Two runs on one mount.* The guest crawl lock allows one crawl per machine, so two runs at once means
two machines mounting the same host directory, `ai_tmp/scrapy-duckdb/queue`. The `vm` commands and
`crawl` gain a way to name the machine (for example `--machine NAME`, default `tail-proto`), each
machine with its own `--state-dir`. Both machines run a jsonl-tail crawl at the same time, each writing
`/queue/<run_id>/` and consumed by its own host process into its own `<run_id>-jsonl-tail.duckdb`. The
probe shows:

- no cross-talk: each run's file holds only its own pages, each equal under
  `bench_queries.py compare` to the same seeds run alone;
- each consumer holds only its own run file, and neither blocks the other while the runs are going;
- what happens when both reach `record_isolated` on the shared `prototype.duckdb` at once, under
  DuckDB's one-writer lock: the second waits, retries or fails, and a run that fails to record is
  left resumable by `consume`, never lost.

*A crawl past 200 pages.* One live jsonl-tail crawl of about 1,000 pages on one site, under the
polite defaults, which shows whether the consumer keeps up over time. 1,000 is the prototype's own
`--max-pages` ceiling, and `CLOSESPIDER_TIMEOUT` and the host deadline already scale with the cap, so
nothing needs raising; a site with fewer in-scope pages than that ends early, which the README says. Sampled at fixed intervals
during the run and recorded as a table in the README: the pages the guest has emitted against the rows
committed on the host (the tick lag), the feed's bytes on the mount, the spider's RSS, and the host
consumer's RSS. The run's `latency` line is quoted, and its cache is kept for replays.

**Review:** one moment, through the README's adversarial review loop, once both probes have run and
before the commit, with the focus: could the two runs have touched each other's directory or file
without the probe seeing it; were they really concurrent; is the record race shown or only argued;
does the long crawl's lag grow, and is the sampling itself a load on the consumer.

**Blocked by:** 10 (the tail and `consume`).

**Status:** ready-for-agent

- [ ] Two machines ran jsonl-tail crawls on the same mount at once, and each run's file equals the
  same seeds run alone
- [ ] The concurrent record into the shared store was exercised, and its outcome is recorded
- [ ] One live crawl of about 1,000 pages ran, and its lag, bytes and RSS over time are in the README
- [ ] Every crawl's real output is quoted in the README
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] The adversarial review loop ran at its moment; the hand-back lists each finding with its
  verdict and the reviewing model, and every valid finding's fix is in the commit
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged
