# 07: Apache Avro

**What to build:** Apache Avro container files as page stores, measured on every axis
of 05 and 06: on-disk size, write cost, the three read shapes (point lookup by
identity, a streamed scan of every Markdown body, a metadata-only select) and insert
throughput. Avro is written and read through DuckDB and through Python, so the format
and the path to it can be told apart.

Six stores under `ai_tmp/duckdb-vs-sqlite/formats/`, each one `pages.avro`:

- `avro-duckdb`: `COPY ... TO 'pages.avro' (FORMAT avro, CODEC 'deflate')` from
  `stores/duckdb-zstd`, through the `avro` core extension. The writer sets its own block
  size; the layout note records blocks and bytes per block.
- `avro-deflate`: fastavro 1.13.1, deflate at its default level, its default
  `sync_interval` of 16,000 bytes (a block is flushed once that many bytes are
  buffered).
- `avro-deflate-1m`: the same with 1 MiB blocks.
- `avro-zstd`: fastavro, zstandard at level 3 (the level the SQLite stores use), 16,000
  bytes.
- `avro-zstd-1m`: the same with 1 MiB blocks.
- `avro-deflate-pyavro`: the official `avro` 1.12.2 package, deflate, its default sync
  interval; its cost is the point.

The Python writers read `stores/sqlite-raw` in rowid order. Avro files have no statistics
or index, so every store gets a sidecar `pages.index.sqlite` mapping identity to (block
offset, position in block), built in one pass over the blocks after the write; it is the
stand-in for an index, as sorting and splitting were for Vortex, and its time is in the
write cost.

Reads: DuckDB's `read_avro` at the default memory limit and under 512 MB, and fastavro.
A DuckDB point lookup reads and decodes the whole file (no projection or filter
pushdown), so it looks up 5 of the 200 identities (every 40th) and is compared per item.
fastavro looks each identity up in the sidecar index, seeks to the block and decodes it;
its scan and metadata select decode a projection of the file's own writer schema.
`parquet-zstd`, `sqlite-zstd-dict` and `duckdb-zstd` are re-measured in the same run.

Inserts: `avro-zstd` joins the insert benchmark: fastavro appends to one file opened
`a+b`, one record and one fsync per row in `single`, one fsync per 256 rows in `batch`,
as the files store fsyncs its manifest. Run against `sqlite-zstd-wal` and `duckdb-zstd`.

Prototype rules still hold: fastavro and avro are PEP 723 dependencies of the scripts,
not of the project; the `avro` DuckDB extension is installed into
`ai_tmp/duckdb-vs-sqlite/extensions/` (network, once; authorized).

**Blocked by:** 03 (Query memory and throughput), 05 (Insert throughput) and 06
(Columnar file formats), whose read shapes, insert harness and format harness it
extends.

**Status:** done

- [x] `uv run prototypes/duckdb-vs-sqlite/bench_formats.py --only avro` builds the six
  stores and their indexes, measures them with the three references, and saves
  `formats-avro.json`; without `--only` the whole benchmark includes them
- [x] Every fastavro point lookup finds 200 rows and every DuckDB one 5; every scan and
  metadata select counts every row; the explain files exist for the Avro stores
- [x] `uv run prototypes/duckdb-vs-sqlite/bench_inserts.py --variants
  avro-zstd,sqlite-zstd-wal,duckdb-zstd --suffix avro` saves `inserts-avro.json`
- [x] `RESULTS.md` gains an "Apache Avro" section and the README names the commands
- [x] `just check` is green
