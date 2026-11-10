# 10: diskcache

**What to build:** diskcache as one more option for the temporary page store, measured
on every axis RocksDB was: disk overall and per regime, point lookup, Markdown scan,
metadata select, memory, single-row and batch inserts, and upserts with compaction. It
is judged two ways: as a rival store, and, since diskcache is SQLite in WAL mode plus a
file for any value of 32 KiB and up, as a library that could implement the recommended
dictionary SQLite store.

1. **Binding.** `diskcache==5.6.3`, pinned in the PEP 723 headers of `bench_formats.py`
   and `bench_inserts.py` only. This is the dependency note: a script-only pin, no
   project dependency. 5.6.3, released on 2023-08-31, is the latest release; the wheel
   is pure Python and declares `requires_python >=3`, but its classifiers stop at 3.9
   and upstream says it is tested to 3.10, so it is untested upstream on the Python 3.14
   these scripts require. A probe of the source and the smoke runs on 3.14.8 are the
   evidence it works there.
2. **The probe.** A 2,000-row probe and a reading of `diskcache/core.py` settled what
   the documentation leaves open: a value spills to a `.val` file when its serialized
   length is at least `disk_min_file_size`; `eviction_policy='none'` with `cull_limit=0`
   never culls, even far past `size_limit`; `len()` agrees with `count(*)`; a bare `set`
   removes an overwritten value's file after its commit, but inside an outer
   `transact()` before the outer commit; `sqlite_auto_vacuum=1` shrinks `cache.db` and
   `check(fix=True)` runs `VACUUM`; `close()` leaves no `-wal` or `-shm`; nothing in
   diskcache calls fsync; settings passed when an existing cache is opened take effect
   and persist; FanoutCache has `transact()` (it locks every shard and commits each
   apart), its `iter`, `len` and `check` cover every shard, its `iterkeys` refuses, and
   its `set` returns False on a lock timeout instead of raising.
3. **Six stores in `bench_formats.py`.** Every open passes every setting: no eviction,
   no culling, no statistics, no tag index, a `size_limit` of 2^62, diskcache's SQLite
   defaults (WAL, `synchronous=NORMAL`, auto-vacuum FULL, 8,192-page cache, 64 MiB mmap)
   and a 60 s timeout. A `PageDisk` subclass of `Disk` compresses each body as the
   SQLite stores do, the metadata plain, then hands the value to the stock `store`:
   - `diskcache-pickle`: the stock Disk, bodies as str, one pickled row per key.
   - `diskcache-zstd`: each body plain zstd level 3 (sqlite-zstd's codec).
   - `diskcache-zstd-dict`: each body against sqlite-zstd-dict's (regime, column)
     dictionary, copied beside the store (sqlite-zstd-dict's codec), the like-for-like
     match for the recommendation.
   - `diskcache-zstd-dict-inline`: the same with the spill threshold at 1 TiB, so
     nothing leaves SQLite.
   - `diskcache-zstd-dict-fanout`: the same in a FanoutCache of 8 shards.
   - `diskcache-zstd-dict-split`: three Caches, `meta/`, `html/` and `markdown/`; a page
     is written to the three in three transactions, so a crash can split it.

   Each build writes transactions of 256 rows unsynced, compacts with `check(fix=True)`,
   closes and fails if a `-wal` or `-shm` is left beside any `cache.db`; a reopen counts
   the rows by `len()` and `count(*)` outside the timed region. Reads walk the keys with
   `iter` and `get` each; a whole-row layout unpickles every row for a scan or metadata
   select. `--per-regime` builds each regime of each store on its own, with only that
   regime's dictionaries. The three read shapes run on the six stores and on
   `parquet-zstd`, `sqlite-zstd-dict` and `duckdb-zstd` as in-run references.
4. **Inserts.** `bench_inserts.py` gains `diskcache-<layout>-{sync,nosync}`: `-nosync`
   is diskcache's own WAL with `synchronous=NORMAL`, the peer of SQLite WAL and
   `rocksdb-*-nosync`; `-sync` sets `synchronous=FULL` and fsyncs every spilled file,
   its directory and the parent of any directory the write created before the commit,
   durable per write like `sqlite-zstd`, `rocksdb-*-sync` and Avro. `single` is one
   `set` per row per cache; `batch` is one `transact()` per 256 rows per cache.
   `sqlite-zstd`, `sqlite-zstd-wal` and `sqlite-zstd-dict-wal` run beside them. The
   first full run of all three commands was set aside: closing a store looked for a
   leftover `-wal` or `-shm` by walking the whole tree, so every timed close walked up
   to 30,567 `.val` files (about 0.8 s on every `diskcache-pickle` read, 0.08 to 0.17 s
   on the other spilling layouts'), inflating every read and every compaction; a profile
   found it. The check now looks beside each `cache.db` only, and the three commands
   were run again from the start. The review before the commit then found the build
   still walking the tree inside the timed build, to name the spilled files in its note
   (taking it out moved `diskcache-pickle`'s build from 17.4 to 17.3 s, and no build by
   more than 0.55 s); the note now takes them from the untimed reopen, and the formats
   command was run a third time.
5. **Upserts.** `bench_formats.py --upserts --only diskcache` runs the 500 upserts on
   APFS clones of the six stores, synced and not, one `set` per row per cache, then
   `check(fix=True)`, and checks 130,880 rows by `len()` and `count(*)` and the 500
   changed bodies through a reopen; each child reads `PRAGMA synchronous` back from
   every Cache's connection. `sqlite-zstd` and `sqlite-zstd-dict` run beside them.

Every measured path uses diskcache's public API; the `count(*)` check and the pragma
read-back reach the SQLite files and the cache's connection, as checks only. Prototype
rules hold: no project dependency, no specification change, data under
`ai_tmp/duckdb-vs-sqlite/`.

**Blocked by:** 05 (Insert throughput), 06 (Columnar file formats), 08 (Closing the
gaps) and 09 (RocksDB), whose insert harness, format stores, dictionary store, upsert
harness and key-value wiring it extends.

**Status:** done

- [x] `uv run prototypes/duckdb-vs-sqlite/bench_formats.py --only diskcache --per-regime`
  saves `formats-diskcache.json`: 6 stores, 30 regime builds, every row check passing
- [x] `uv run prototypes/duckdb-vs-sqlite/bench_formats.py --upserts --only diskcache`
  saves `formats-upserts-diskcache.json`, 28 records, every check passing
- [x] `uv run prototypes/duckdb-vs-sqlite/bench_inserts.py --variants
  diskcache-pickle-sync,diskcache-pickle-nosync,diskcache-zstd-sync,diskcache-zstd-nosync,diskcache-zstd-dict-sync,diskcache-zstd-dict-nosync,diskcache-zstd-dict-inline-sync,diskcache-zstd-dict-inline-nosync,diskcache-zstd-dict-fanout-sync,diskcache-zstd-dict-fanout-nosync,diskcache-zstd-dict-split-sync,diskcache-zstd-dict-split-nosync,sqlite-zstd,sqlite-zstd-wal,sqlite-zstd-dict-wal
  --suffix diskcache` saves `inserts-diskcache.json`, 120 records, every row-count
  check passing
- [x] `RESULTS.md` gains a "diskcache" section and the README names the commands
- [x] `just check` is green
