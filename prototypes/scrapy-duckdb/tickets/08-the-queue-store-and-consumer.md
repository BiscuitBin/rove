# 08: The queue store and its host consumer

**Network:** none beyond 07. Built and checked with `--replay` only after 09 fills the cache; until
then, against the spike's own data and offline stubs.

**What to build:** two new `--store` values on `scrapyproto crawl`, run on `rocks-proto`:

- `jsonl-tail`, the control: Scrapy's feed goes to `/queue/<run_id>/feed.jsonl` on the mount, and the
  host inserts each complete line past its byte offset. Without it, a win could not be credited to
  RocksDB rather than to the mount.
- `rocks-queue`: an item pipeline puts each page into RocksDB at `/queue/<run_id>/rocks` under the key
  `p:%012d`, ZSTD-compressed, and at close writes `meta:closed` with the page count and the depth
  corrections. The host follows it as a secondary instance (the rung 07 recorded).

Both consumers tick every 0.5 s inside the existing watch loop, insert their batch into
`prototype.duckdb` with a `consumer_offsets` row in the same transaction, and finish by applying the
depth corrections, writing the `runs` row with its store kind and refusing a run whose rows differ
from the spider's `proto/pages`. `scrapyproto consume <run_id>` resumes a consumer after the host
process was interrupted. `--crash-after N` (prototype only) makes the spider SIGKILL itself after N
items, for 09's crash probe. The `bulk` path is unchanged.

**Review:** one moment, before 09 measures anything, with the focus: exactly-once into DuckDB across a
host restart, a lost or duplicated page, a run recorded before its last page, the secondary reading a
half-written batch, the tail reading a half-written line.

**Blocked by:** 07.

**Status:** ready-for-agent

- [ ] `crawl --store rocks-queue --replay` and `--store jsonl-tail --replay` end in a summary read
  from DuckDB with the same pages as `--store bulk` (`bench_queries.py compare`)
- [ ] `consume <run_id>` after an interrupted host finishes the run with no duplicate and no loss
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] The adversarial review loop ran; the hand-back lists each finding with its verdict
