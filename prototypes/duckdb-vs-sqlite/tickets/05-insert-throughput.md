# 05: Insert throughput

**What to build:** one command measures how fast each store takes new rows, from empty
and from a store that already holds 50,000 rows, and prints one table. The query
benchmark (03) measured writes only as 500 single-row upserts into a full 130,880-row
store, where raw SQLite and DuckDB were both slow; this ticket measures inserts on their
own, at the two sizes a crawl passes through.

Seven store variants: the five of 01 plus the two SQLite stores under
`PRAGMA journal_mode=WAL` with `PRAGMA synchronous=NORMAL` (`sqlite-raw-wal`,
`sqlite-zstd-wal`); the other SQLite variants keep the default rollback journal and
`synchronous=FULL`. Two insert modes: `single`, one transaction per row, the crawler's
pattern; `batch`, 256 rows per transaction (`executemany` for SQLite and DuckDB, one
manifest flush and fsync per batch for files). Two row mixes: `mixed`, rows spread
evenly over the whole corpus, the base and the inserted rows disjoint; `commoncrawl`,
all 9,999 Common Crawl pages inserted into a base drawn from the other four regimes (the
regime has no more pages, so that count is 9,999, not 10,000). Two scenarios: `empty`
(0 to N rows) and `populated` (50,000 to 50,000 + N). Every cell runs once.

Each measurement runs in a fresh subprocess that streams the rows from a JSON-lines
sample file (never loaded whole) and reports rows per second, raw MiB per second (HTML
plus Markdown bytes of the rows inserted), the wall seconds of the insert loop and of
the compaction (`VACUUM` or `CHECKPOINT`), its own peak RSS (`ru_maxrss`), and the
store's allocated bytes before the inserts, after them (WAL and journal files included)
and after the compaction. The child checks that the row count after the inserts is the
count before plus the rows inserted, and that no WAL, shm or journal file remains after
the compaction. The populated base is built once per (variant, mix) by the `batch`
inserter and cloned per run with `cp -Rc` (APFS clonefile), so each run starts from the
same bytes; the zstd variants compress inside the timed loop.

**Blocked by:** 01 (Tracer bullet on local data) and 02 (Corpus breadth), whose Common
Crawl regime is the second row mix. Independent of 03 and 04.

**Status:** done

- [x] `uv run prototypes/duckdb-vs-sqlite/bench_inserts.py` prints one row per
  (variant, mode, mix, scenario), 56 rows, and saves `inserts.json` under
  `ai_tmp/duckdb-vs-sqlite/results/`
- [x] The populated scenario reports on-disk size before the inserts, after them and
  after compaction
- [x] No `*-PROTOTYPE-wipe-me` directory remains after the run
- [x] `RESULTS.md` gains an "Insert throughput" section and the README names the command
- [x] `just check` is green
