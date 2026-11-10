# 09: RocksDB

**What to build:** RocksDB as one more option for the temporary page store, measured on
every axis the other options were: disk overall and per regime, point lookup, Markdown
scan, metadata select, memory, single-row and batch inserts, and upserts with
compaction, so the final report can weigh it against the dictionary SQLite store.

1. **Binding.** `rocksdict==0.3.29`, pinned in the PEP 723 headers of
   `bench_formats.py` and `bench_inserts.py` only; it ships a cp314 macOS arm64 wheel
   that bundles RocksDB 9.8.4 and zstd 1.5.7. This is the dependency note: a script-only
   pin, no project dependency. python-rocksdb, the binding RocksDB's site links to, was
   archived in June 2025, has had no release since 2019 and ships no wheels. Speedb is
   dropped: its only binding, speedict 0.3.12, stops at Python 3.12, and Speedb has not
   released since January 2024.
2. **Three stores in `bench_formats.py`.** Every store uses block zstd level 3 at every
   level, 16 KiB blocks in one 128 MiB LRU cache shared by every column family, index
   and filter blocks in that cache, 32 MiB memtables capped at 128 MiB in all, two
   background jobs and one old info LOG; every option is passed on every open, never
   reloaded from the saved file. The application compresses nothing itself.
   - `rocksdb-zstd`: three column families keyed by identity: `meta` (compact JSON of
     the metadata columns, with a 10-bit bloom filter), `html` (absent when the page has
     none) and `markdown`; one `WriteBatch` writes a row across all three atomically.
   - `rocksdb-blob`: the same, with the two bodies in zstd blob files (minimum 4 KiB,
     64 MiB files) and blob GC at age cutoff 1.0, so a full compaction reclaims every
     stale blob.
   - `rocksdb-packed`: one value per row in the default column family, a two-length
     header then the meta JSON, the HTML and the Markdown; a scan or metadata select
     reads every whole row, by design.

   Each build writes `WriteBatch`es of 256 rows unsynced, then flushes and compacts every
   column family with bottommost compaction forced, closes, and fails if a WAL file of
   nonzero size remains; a read-only reopen counts the rows outside the timed region.
   `--per-regime` builds each regime of each store on its own, checks its rows and raw
   bytes against `sizes.json`, measures it and deletes it. The three read shapes run on
   the three stores and on `parquet-zstd`, `sqlite-zstd-dict` and `duckdb-zstd` as
   in-run references.
3. **Inserts.** `bench_inserts.py` gains `rocksdb-{zstd,blob,packed}-{sync,nosync}`:
   one `WriteBatch` per row or per 256 rows, the WAL synced per write (`sync`, the
   durability peer of the rollback-journal `sqlite-zstd`) or not (`nosync`, durable to
   a process crash only, the peer of SQLite WAL with `synchronous=NORMAL`). Compaction
   is the build's. `sqlite-zstd`, `sqlite-zstd-wal` and `sqlite-zstd-dict-wal` run
   beside them as in-run references. The first full run stopped on a race: measuring
   an open store listed a log file that a background job deleted before it was
   measured. `live_bytes` skips such a file, and the run was redone from the start. The
   upsert run had finished before the fix. The old helper counted the same files the
   same way and differed only in stopping on such a file, so a run that finished
   measured what `live_bytes` would have.
4. **Upserts.** `bench_formats.py --upserts --only rocksdb` runs the 500 upserts on APFS
   clones of the three stores, synced and not, one `WriteBatch` per row, then the full
   compaction, and checks 130,880 rows and the 500 changed bodies through a read-only
   reopen; `sqlite-zstd` and `sqlite-zstd-dict` run beside them on their existing paths.

Prototype rules hold: no project dependency, no specification change, data under
`ai_tmp/duckdb-vs-sqlite/`.

**Blocked by:** 05 (Insert throughput), 06 (Columnar file formats) and 08 (Closing the
gaps), whose insert harness, format stores, dictionary store and upsert harness it
extends.

**Status:** done

- [x] `uv run prototypes/duckdb-vs-sqlite/bench_formats.py --only rocksdb --per-regime`
  saves `formats-rocksdb.json`: 3 stores, 15 regime builds, every row check passing,
  RocksDB 9.8.4 in every LOG
- [x] `uv run prototypes/duckdb-vs-sqlite/bench_formats.py --upserts --only rocksdb`
  saves `formats-upserts-rocksdb.json`, 16 records, every check passing
- [x] `uv run prototypes/duckdb-vs-sqlite/bench_inserts.py --variants
  rocksdb-zstd-sync,rocksdb-zstd-nosync,rocksdb-blob-sync,rocksdb-blob-nosync,rocksdb-packed-sync,rocksdb-packed-nosync,sqlite-zstd,sqlite-zstd-wal,sqlite-zstd-dict-wal
  --suffix rocksdb` saves `inserts-rocksdb.json`, 72 records, every row-count check
  passing
- [x] `RESULTS.md` gains a "RocksDB" section and the README names the commands
- [x] `just check` is green
