# 08: Closing the gaps

**What to build:** the three measurements the Avro write-up left open, so the final
report can weigh Avro zstd with 1 MiB blocks against the dictionary SQLite store on
every axis.

1. **Avro appends in 1 MiB blocks.** `avro-zstd-1m` joins the insert benchmark: fastavro
   with `sync_interval` of 1 MiB. `batch` appends 256 rows with one fsync, as
   `avro-zstd` does. `single` buffers rows until about 1 MiB of raw body bytes are held,
   writes them as one block with one fsync, and flushes the remainder at the end; its
   rows are not durable one at a time, so its results say `durability: "buffered"`.
2. **The dictionary SQLite store through the insert benchmark.** `sqlite-zstd-dict-wal`
   is `sqlite-zstd-wal` (WAL, `synchronous=NORMAL`) whose bodies are compressed against
   the per-(regime, column) dictionaries `bench_formats.py` trained, copied into each
   fresh store from `formats/sqlite-zstd-dict/pages.sqlite`, with plain zstd as the
   fallback. The dictionaries were trained on the whole corpus, the inserted rows
   included, which flatters the ratio slightly. The script exits naming
   `bench_formats.py` when that store is missing.
3. **Upserts on Avro and on the dictionary store.** `bench_formats.py --upserts` runs
   the 500 upserts `bench_queries.py` prepared (`results/bench-upserts.jsonl`: existing
   identities with a changed Markdown body), one transaction each, on an APFS clone
   (`cp -Rc`) in a fresh child, twice, both runs saved: `sqlite-zstd` (the in-run
   reference, `bench_queries`'s `INSERT ... ON CONFLICT DO UPDATE`), `sqlite-zstd-dict`
   (the same, compressed with the store's dictionaries), `avro-zstd` and `avro-zstd-1m`.
   An Avro upsert appends the record as one block (zstd level 3), fsyncs, and repoints
   the identity in the sidecar index. Compaction is `VACUUM` for SQLite; for Avro it
   rewrites the file with only the records the index points to, in the store's block
   size, and rebuilds the index. Each child checks the row count and the 500 changed
   Markdown bodies after compaction (Avro also before it, through the live index).

Run the insert benchmark on `avro-zstd-1m`, `sqlite-zstd-dict-wal` and
`sqlite-zstd-wal` (the in-run reference). Prototype rules hold: no project dependency,
no specification change, data under `ai_tmp/duckdb-vs-sqlite/`.

**Blocked by:** 05 (Insert throughput), 06 (Columnar file formats) and 07 (Apache Avro),
whose insert harness, dictionary store and Avro stores it extends.

**Status:** done

- [x] `uv run prototypes/duckdb-vs-sqlite/bench_inserts.py --variants
  avro-zstd-1m,sqlite-zstd-dict-wal,sqlite-zstd-wal --suffix gaps` saves
  `inserts-gaps.json`, 24 records, every row-count check passing
- [x] `uv run prototypes/duckdb-vs-sqlite/bench_formats.py --upserts` saves
  `formats-upserts.json`, 8 records, every check passing
- [x] `RESULTS.md` gains a "Closing the gaps" section and the README names the commands
- [x] `just check` is green
