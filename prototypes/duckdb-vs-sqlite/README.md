# Prototype: DuckDB against SQLite as the temporary page store

A throwaway prototype, never production code. It answers one question for the
documentation mirror decision 0012 describes: **does DuckDB's column compression make it
a better temporary store than SQLite for each page's raw HTML and converted Markdown, on
disk and in memory while querying?** The temporary store holds every page between fetch
and finalisation. The raw HTML is kept so a page can be converted again when the
processing signature changes without a refetch, and so a low-quality conversion can be
debugged against its input. The specifications exclude storage mechanics, so the answer
is an implementation decision and no specification changes.

The results of the full run are in [RESULTS.md](RESULTS.md).

## What is compared

Five stores, each holding the same rows with the same schema:

| Store | How the bodies are held |
| --- | --- |
| files | one HTML and one Markdown file per page, plus a JSON manifest |
| sqlite-raw | SQLite, `TEXT` columns |
| sqlite-zstd | SQLite, `BLOB` columns compressed per row with zstd level 3 |
| duckdb-default | DuckDB, `VARCHAR` columns under its default column compression |
| duckdb-zstd | DuckDB, `VARCHAR` columns declared `USING COMPRESSION ZSTD` |

Nine more stores are built from these and compared on size and the read shapes: Parquet
(zstd level 3; default row groups; 2,048-row groups with bloom filters on `identity`;
the same sorted by identity), Vortex (default; sorted by identity; sorted and split into
64 files), Lance (default; with a BTREE index on `identity`), and SQLite with per-row
zstd against a dictionary trained per regime and column. Parquet, Vortex and Lance are
written and read through DuckDB; the `vortex` and `lance` extensions are installed into
`ai_tmp/duckdb-vs-sqlite/extensions/` on the first run.

Six Apache Avro container files join them: one written by DuckDB's `avro` extension
(deflate), four by fastavro (deflate and zstd level 3, each with 16,000-byte and 1 MiB
blocks) and one by the official `avro` package (deflate). Each carries a sidecar SQLite
index from identity to block offset, since Avro has none. They are read through DuckDB's
`read_avro` and through fastavro, and the zstd fastavro store also joins the insert
benchmark, appending to the file with an fsync per write. Ticket 08 adds the zstd 1 MiB
store and the dictionary SQLite store to the insert benchmark and measures upserts on
both.

Ticket 09 adds three RocksDB stores, RocksDB 9.8.4 through the `rocksdict` binding:
three column families keyed by identity (metadata JSON, HTML, Markdown), the same with
the two bodies in blob files, and one packed value per row. Each is measured on size
overall and per regime and on the read shapes, joins the insert benchmark with its
write-ahead log synced per write and not, and runs the upserts.

Four query shapes: point lookup by identity, a full scan of every Markdown body, a
metadata-only select, and an upsert of one row at a time. Each measurement runs in a
fresh subprocess and reports the child's own peak RSS and wall time. DuckDB queries run
twice, at the default memory limit and under a 512 MB limit.

Insert throughput is measured separately, on the five stores plus the two SQLite stores
in WAL mode, and later on Avro, the dictionary SQLite store in WAL mode and the six
RocksDB variants: 10,000 rows inserted one transaction at a time and 256 rows at a
time, into an empty store and into one already holding 50,000 rows, with two row
mixes. The results page's "Insert throughput" section has the table.

## The corpus

Five labelled regimes, between 20k and 150k rows and about 2 GB raw in total:

1. **rust**: the Rust documentation installed under rustup on this machine, about 62k
   pages. No download.
2. **sphinx**: the HTML archives of python 3.12, 3.13 and 3.14, numpy 2.2, pandas
   2.2.3, django 5.1 and the sqlite documentation, about 9.8k pages.
3. **wikipedia**: article HTML from the Wikimedia Enterprise dump of Simple English
   Wikipedia, run `20250320`, streamed and stopped at about 30k articles. That run is
   about twenty months old, so it samples article markup, not current content.
4. **commoncrawl**: HTML responses from the first WARC file of `CC-MAIN-2026-43`,
   streamed and stopped at about 10k pages. Full site chrome.
5. **github**: issue and comment bodies from ten GH Archive hourly files (the first ten
   hours of 2026-10-01), about 19k Markdown bodies with a null HTML column.

HTML-only regimes get their Markdown from a throwaway converter.

## How to run

Each script carries a PEP 723 header and runs with `uv run`, which resolves its own
environment on the first run (Python 3.14, duckdb, zstandard, warcio, the converter,
fastavro, avro and rocksdict).
Nothing is added to the project's dependencies.

```sh
uv run prototypes/duckdb-vs-sqlite/build_corpus.py --sources rust --limit 2000
uv run prototypes/duckdb-vs-sqlite/load_stores.py
uv run prototypes/duckdb-vs-sqlite/bench_queries.py
uv run prototypes/duckdb-vs-sqlite/bench_inserts.py
uv run prototypes/duckdb-vs-sqlite/bench_formats.py
uv run prototypes/duckdb-vs-sqlite/bench_formats.py --only avro
uv run prototypes/duckdb-vs-sqlite/bench_inserts.py --variants avro-zstd,sqlite-zstd-wal,duckdb-zstd --suffix avro
uv run prototypes/duckdb-vs-sqlite/bench_inserts.py --variants avro-zstd-1m,sqlite-zstd-dict-wal,sqlite-zstd-wal --suffix gaps
uv run prototypes/duckdb-vs-sqlite/bench_formats.py --upserts
uv run prototypes/duckdb-vs-sqlite/bench_formats.py --only rocksdb --per-regime
uv run prototypes/duckdb-vs-sqlite/bench_formats.py --upserts --only rocksdb
uv run prototypes/duckdb-vs-sqlite/bench_inserts.py --variants rocksdb-zstd-sync,rocksdb-zstd-nosync,rocksdb-blob-sync,rocksdb-blob-nosync,rocksdb-packed-sync,rocksdb-packed-nosync,sqlite-zstd,sqlite-zstd-wal,sqlite-zstd-dict-wal --suffix rocksdb
```

The fourth command needs only the corpus, not the stores, and accepts `--populate` and
`--insert` to run at smaller sizes (the results file is then named after them). The
fifth needs the stores, reaches the network once for the three DuckDB extensions, and
accepts `--rows N` to build from the first N rows. The sixth builds and measures only
the Avro family, beside `parquet-zstd`, `sqlite-zstd-dict` and `duckdb-zstd`, which the
fifth must have built first, and saves `formats-avro.json`. The seventh runs the insert
benchmark on three variants only and names its results file `inserts-avro.json`. The
eighth runs it on Avro zstd in 1 MiB blocks (single-row inserts buffered into blocks)
and on the dictionary SQLite store in WAL mode, which needs the dictionary store the
fifth built, and saves `inserts-gaps.json`. The ninth runs 500 upserts on `sqlite-zstd`,
`sqlite-zstd-dict`, `avro-zstd` and `avro-zstd-1m`, compacts each, checks the result,
and saves `formats-upserts.json`; it reaches no network. The tenth builds the three
RocksDB stores, and each regime of each on its own (built, measured, deleted), reads
them beside `parquet-zstd`, `sqlite-zstd-dict` and `duckdb-zstd`, which the fifth must
have built, and saves `formats-rocksdb.json`. The eleventh runs the 500 upserts on
clones of the three RocksDB stores the tenth built, synced and unsynced, beside
`sqlite-zstd` and `sqlite-zstd-dict`, which the fifth built, and saves
`formats-upserts-rocksdb.json`. The twelfth runs the insert benchmark on the six RocksDB
variants and three SQLite references, which needs the dictionary store the fifth built,
and saves `inserts-rocksdb.json`. None of the three reaches the network once `uv` has
fetched rocksdict. The first command accepts any subset of
`rust,sphinx,wikipedia,commoncrawl,github` and a per-source cap. Data, downloads,
databases and raw results all land under `ai_tmp/duckdb-vs-sqlite/`, which is gitignored
and excluded from every hook; a full build needs roughly 39 GB there: the corpus file,
the five stores, the nine format stores, the six Avro stores (4.3 GB), the three RocksDB
stores (2.4 GB) and the three extensions, the download cache and the insert benchmark's
four row-sample files (5 GB), plus about 5 GB more while that benchmark runs, for the
base store and its clone. Rerunning a script wipes and rebuilds its outputs, except the
row samples, which the insert benchmark keeps and reuses.

The prototype's Python and Markdown pass the repository gate; the data never does.
The tickets are under `tickets/` in this directory.
