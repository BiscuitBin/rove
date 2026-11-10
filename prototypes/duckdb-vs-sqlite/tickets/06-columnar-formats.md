# 06: Columnar file formats and a dictionary-zstd SQLite

**What to build:** one command builds nine more stores from the stores of 01 and 02 and
measures, for each of them and for the `sqlite-zstd` and `duckdb-zstd` references, the
on-disk size, the write cost, and the three read shapes of 03 (point lookup by identity,
a streamed scan of every Markdown body, a metadata-only select), each in a fresh
subprocess reporting its own peak RSS and wall time, warm cache, second of two runs. The
question is whether a columnar file written and read through DuckDB, or a smarter SQLite
store, beats the stores already measured on disk and in memory while querying.

The nine stores, all written from `stores/duckdb-zstd` except the last, which is written
from `stores/sqlite-raw`:

- `parquet-zstd`: `COPY ... (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 3)`,
  DuckDB's default row groups of 122,880 rows.
- `parquet-zstd-rg2k`: row groups of 2,048 rows with `DICTIONARY_SIZE_LIMIT 2048`, so
  every `identity` chunk is dictionary-coded and carries a bloom filter.
- `parquet-zstd-rg2k-sorted`: the same, rows sorted by identity, so row-group statistics
  prune a lookup too.
- `vortex`: `COPY ... (FORMAT vortex)`, store order. The writer exposes no compression,
  chunk, sort or index option; a reader can use its zone maps (statistics per 8,192
  rows) and file-level statistics. Vortex's index layout (`vortex.indexed`) is an
  experimental, writer-opt-in feature with no DuckDB or Python option, so sorting and
  splitting stand in for it.
- `vortex-sorted`: rows sorted by identity, so the zone maps prune a lookup.
- `vortex-split`: sorted and hive-partitioned into 64 files by `ntile(64)` over identity,
  read as one glob; a lookup filters on identity only, so any file skipped is file-level
  statistics at work.
- `lance`: `COPY ... (FORMAT lance, mode 'overwrite')`, a dataset directory.
- `lance-btree`: an APFS clone of `lance` plus `CREATE INDEX ... (identity) USING BTREE`;
  the index build is its write cost.
- `sqlite-zstd-dict`: the `sqlite-zstd` schema with the bodies compressed against a zstd
  dictionary trained per (regime, column) on 1,000 bodies spread by stride, 128 KiB
  each, stored in a `dictionaries` table in the same file.

The `vortex` and `lance` DuckDB extensions are installed into
`ai_tmp/duckdb-vs-sqlite/extensions/` on the first run (network, once; authorized).
DuckDB-read stores run at the default memory limit and under
`SET memory_limit = '512MB'`; point lookups use literals, not parameters, so the filter
is known at planning and pushes into the scan. One `EXPLAIN ANALYZE` of a point lookup
per DuckDB-read store is saved under `results/formats-explain/`.

**Blocked by:** 02 (Corpus breadth) and 03 (Query memory and throughput), whose stores
and query shapes it reuses. Independent of 04 and 05.

**Status:** done

- [x] `uv run prototypes/duckdb-vs-sqlite/bench_formats.py` builds the nine stores, prints
  the size table and the query table, and saves `formats.json` under
  `ai_tmp/duckdb-vs-sqlite/results/`; `--rows N` runs the same on the first N rows
- [x] Every point lookup finds its 200 rows; every scan and metadata select counts every
  row; the explain files exist for every DuckDB-read store
- [x] `RESULTS.md` gains a "Columnar file formats" section and the README names the command
- [x] `just check` is green
