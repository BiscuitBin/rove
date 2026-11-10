# Results: DuckDB against SQLite as the temporary page store

Measured on 2026-11-06, 2026-11-07 and 2026-11-09 with the twelve commands below, on an Apple M5 Pro (18 cores, 64 GB)
running macOS 26.4 on APFS, Python 3.14.8, duckdb 2.0.0, zstandard 0.25.0 and SQLite
3.53.1 as bundled with that Python, plus fastavro 1.13.1 and avro 1.12.2 for the Avro
section and rocksdict 0.3.29 (bundling RocksDB 9.8.4) for the RocksDB section. Every
number on this page comes from one run of the twelve commands below, except the
tracer-bullet figures named in the first caveat, the block counts of the DuckDB probe
named in the insert section, the 20-row codec probe named in the Avro section, the
allocation probe named in the gaps section and the sync and cache probes named in the
RocksDB section:

```sh
uv run prototypes/duckdb-vs-sqlite/build_corpus.py --sources rust,sphinx,wikipedia,commoncrawl,github
uv run prototypes/duckdb-vs-sqlite/load_stores.py --per-regime
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

The raw output of the last eleven commands is kept beside the data, under
`ai_tmp/duckdb-vs-sqlite/results/` (`sizes.json`, `queries.json`, `inserts.json`,
`formats.json`, `formats-avro.json`, `inserts-avro.json`, `inserts-gaps.json`,
`formats-upserts.json`, `formats-rocksdb.json`, `formats-upserts-rocksdb.json`,
`inserts-rocksdb.json` and the `formats-explain/` files), which is gitignored.

## The question

Does DuckDB's column compression make it a better temporary store than SQLite for each
page's raw HTML and converted Markdown, on disk and in memory while querying? The store
holds every page between fetch and finalisation; the HTML is kept so a page can be
converted again when the processing signature changes, and so a poor conversion can be
debugged against its input.

## The corpus

The corpus is 130,880 pages in five regimes; the raw bytes are the HTML plus the Markdown
of every page, 4,422 MiB in all. Allocated bytes count APFS blocks, apparent bytes the
file lengths. Each store was compacted (`VACUUM`, `CHECKPOINT`) and closed before it was
measured; the WAL was gone.

| regime | pages | raw MiB | what the pages are |
| --- | ---: | ---: | --- |
| rust | 62,067 | 836 | rustdoc output: many 4 KB API pages, some 50 KB and more |
| sphinx | 9,703 | 593 | Sphinx-built manuals with their navigation chrome |
| wikipedia | 30,000 | 1,274 | Wikimedia Enterprise article HTML, no site chrome |
| commoncrawl | 9,999 | 1,690 | fetched pages with full site chrome, scripts and styles |
| github | 19,111 | 30 | Markdown issue and comment bodies only, HTML null |

| store | raw MiB | apparent MiB | allocated MiB | allocated / raw |
| --- | ---: | ---: | ---: | ---: |
| files | 4,422 | 4,483 | 5,123 | 1.159 |
| sqlite-raw | 4,422 | 4,551 | 4,551 | 1.029 |
| sqlite-zstd | 4,422 | 1,026 | 1,026 | 0.232 |
| duckdb-default | 4,422 | 569 | 576 | 0.130 |
| duckdb-zstd | 4,422 | 558 | 560 | 0.127 |

DuckDB's storage information, per body column, after `CHECKPOINT`:

| store | html segments | markdown segments |
| --- | --- | --- |
| duckdb-default | ZSTD 1, DICT_FSST 1, Roaring 1, Constant 1 | Uncompressed 28, ZSTD 1, Constant 2 |
| duckdb-zstd | ZSTD 2, Roaring 1, Constant 1 | ZSTD 2, Constant 2 |

The Roaring and Constant segments are validity masks and all-null runs (the GitHub rows
have no HTML). Under the default compression DuckDB chose ZSTD for the HTML column but
left 28 Markdown segments uncompressed. Its `zstd_min_string_length` setting (4,096 bytes)
enables ZSTD only on a segment whose average string is at least that long, and the
Markdown of the Rust and GitHub rows is shorter. Forcing ZSTD on both body columns
(`USING COMPRESSION ZSTD`) removes that cliff; the overall totals barely move because the
long bodies dominate the bytes, but the per-regime table below shows where it bites.

## Per regime

Each (regime, store) pair was built on its own and measured, so these are exact on-disk
sizes, not an apportioning of the overall file. Values are allocated MiB and the ratio to
the regime's raw bytes.

| regime | raw MiB | files | sqlite-raw | sqlite-zstd | duckdb-default | duckdb-zstd |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| rust | 836 | 1,240 (1.48) | 895 (1.07) | 261 (0.31) | 289 (0.35) | 60 (0.07) |
| sphinx | 593 | 644 (1.09) | 604 (1.02) | 115 (0.19) | 55 (0.09) | 56 (0.09) |
| wikipedia | 1,274 | 1,407 (1.11) | 1,306 (1.03) | 294 (0.23) | 160 (0.13) | 160 (0.13) |
| commoncrawl | 1,690 | 1,731 (1.02) | 1,703 (1.01) | 332 (0.20) | 288 (0.17) | 288 (0.17) |
| github | 30 | 90 (3.01) | 44 (1.47) | 24 (0.82) | 43 (1.43) | 14 (0.48) |

Three things stand out:

- **Shared context beats per-row compression everywhere the strings are long.** On the
  Sphinx manuals DuckDB stores the bodies in 9% of their raw size against 20% for
  per-row zstd: thousands of pages share the same navigation chrome and DuckDB's ZSTD
  compresses a whole segment at once, so the repetition across pages is found. Per-row
  zstd can only see one page at a time.
- **The default compression has a cliff.** On the Rust pages `duckdb-default` is 35% of
  raw while `duckdb-zstd` is 7%: the HTML got ZSTD, the short Markdown did not. On the
  GitHub bodies the default store is larger than raw (1.43) because the bodies sit
  uncompressed in 65 small segments; forced ZSTD brings it to 0.48.
- **Small rows cost SQLite and files little, DuckDB nothing extra.** The GitHub rows are
  1.6 KB on average; the files store spends three times their size in 4 KB blocks and
  the manifest, `sqlite-raw` 1.47 times. SQLite's per-row zstd barely helps short
  Markdown (0.82).

## Queries

Four shapes, each in a fresh process, warm cache, second of two runs. Peak RSS is the
child's own `ru_maxrss` in MiB; the `baseline` row is a child that imports duckdb and
zstandard and does nothing. Point lookup is 200 identities spread over the table; scan
reads every Markdown body and hashes it, streaming (`fetchmany` for DuckDB, never
`fetchall`); meta selects every row's nine metadata columns; upsert is 500 single-row
transactions on a copy of the store, with the on-disk size before, after the rows and
after `VACUUM` or `CHECKPOINT`. DuckDB ran at its default memory limit and again under
`SET memory_limit = '512MB'` (reported as 488.2 MiB).

| store | query | memory limit | peak RSS MiB | wall s | ms per item | MiB before > after upserts > after compaction |
| --- | --- | --- | ---: | ---: | ---: | --- |
| baseline | none | n/a | 38 | 0.000 | - | - |
| files | point | n/a | 70 | 0.220 | 1.10 | - |
| files | scan | n/a | 60 | 3.900 | 0.03 | - |
| files | meta | n/a | 38 | 0.177 | 0.00 | - |
| files | upsert | n/a | 80 | 0.218 | 0.44 | - |
| sqlite-raw | point | SQLite default | 46 | 0.012 | 0.06 | - |
| sqlite-raw | scan | SQLite default | 139 | 1.521 | 0.01 | - |
| sqlite-raw | meta | SQLite default | 41 | 0.757 | 0.01 | - |
| sqlite-raw | upsert | SQLite default | 101 | 14.657 | 29.31 | 4,551 > 4,567 > 4,551 |
| sqlite-zstd | point | SQLite default | 42 | 0.009 | 0.05 | - |
| sqlite-zstd | scan | SQLite default | 62 | 1.204 | 0.01 | - |
| sqlite-zstd | meta | SQLite default | 41 | 0.233 | 0.00 | - |
| sqlite-zstd | upsert | SQLite default | 92 | 3.656 | 7.31 | 1,026 > 1,042 > 1,026 |
| duckdb-default | point | 51.1 GiB | 535 | 2.516 | 12.58 | - |
| duckdb-default | point | 488.2 MiB | 536 | 2.644 | 13.22 | - |
| duckdb-default | scan | 51.1 GiB | 626 | 1.047 | 0.01 | - |
| duckdb-default | scan | 488.2 MiB | 626 | 0.995 | 0.01 | - |
| duckdb-default | meta | 51.1 GiB | 95 | 0.082 | 0.00 | - |
| duckdb-default | meta | 488.2 MiB | 100 | 0.093 | 0.00 | - |
| duckdb-default | upsert | 51.1 GiB | 1,652 | 15.481 | 30.96 | 569 > 573 > 745 |
| duckdb-default | upsert | 488.2 MiB | 1,552 | 15.542 | 31.08 | 569 > 573 > 745 |
| duckdb-zstd | point | 51.1 GiB | 536 | 2.531 | 12.65 | - |
| duckdb-zstd | point | 488.2 MiB | 536 | 2.484 | 12.42 | - |
| duckdb-zstd | scan | 51.1 GiB | 624 | 1.016 | 0.01 | - |
| duckdb-zstd | scan | 488.2 MiB | 631 | 1.003 | 0.01 | - |
| duckdb-zstd | meta | 51.1 GiB | 95 | 0.078 | 0.00 | - |
| duckdb-zstd | meta | 488.2 MiB | 95 | 0.080 | 0.00 | - |
| duckdb-zstd | upsert | 51.1 GiB | 1,575 | 15.676 | 31.35 | 558 > 562 > 718 |
| duckdb-zstd | upsert | 488.2 MiB | 1,519 | 15.570 | 31.14 | 558 > 562 > 718 |

What the table says:

- **DuckDB holds far more memory for every shape.** Point lookups peak at 536 MiB
  against 46 MiB for SQLite, the Markdown scan at 626 MiB against 139 MiB (raw) and
  63 MiB (zstd), and the metadata select at 95 MiB against 41 MiB. The likely cause,
  not measured here, is that a ZSTD segment is the unit of decompression, so fetching
  one page decompresses the segment around it; that would explain both the point-lookup
  memory and its 12.6 ms per lookup, against 0.05 ms for SQLite. A control run with
  `force_compression = 'uncompressed'` would confirm it. The 512 MB memory limit changed nothing measurable, because DuckDB's
  buffer pool stayed under it in every shape and the limit does not cover the rest of
  the process.
- **Single-row upserts are DuckDB's worst shape.** 500 single-row transactions took
  15.5 s and 1.5 to 1.6 GB of RSS, and the file grew by 30% at `CHECKPOINT` (569 to
  745 MiB), consistent with a row group with changed rows being rewritten while the old
  blocks wait for a later reclaim; the mechanism was not inspected. SQLite with per-row zstd did the same work in 3.7 s
  at 92 MiB and returned to its original size after `VACUUM`. Raw SQLite was slow here
  too (14.7 s): each transaction journals the pages of a 4.5 GB file it touches, and the
  rows are large.
- **Scans are a wash in time, not in memory.** DuckDB streams the 130,880 bodies in
  1.0 s, SQLite in 1.2 to 1.5 s and the files store in 3.9 s; DuckDB spends 10 times the
  memory to do it. For metadata-only reads DuckDB is the fastest (0.08 s) because it
  reads only the columns asked for, where SQLite reads rows (0.76 s raw, 0.23 s zstd,
  the compressed rows being smaller). The schema puts `html_bytes` and `markdown_bytes`
  after the two bodies, so SQLite has to traverse each row's overflow pages to reach
  them; a real store would put the small columns first, and this gap would shrink.
- **The files store is cheap on memory and slow on scans.** Its 70 MiB point-lookup peak
  is the manifest index held in Python; its scan is a `read()` per file.

## Insert throughput

Seven store variants, two insert modes, two row mixes and two scenarios, every cell run
once in a fresh process. The variants are the five stores above plus the two SQLite
stores in WAL mode (`sqlite-raw-wal`, `sqlite-zstd-wal`: `PRAGMA journal_mode=WAL` when
the file is created, `PRAGMA synchronous=NORMAL` on every open, both read back and
recorded); the other SQLite variants keep the default rollback journal and
`synchronous=FULL`. `single` is one transaction per row, the crawler's pattern: for
SQLite an implicit transaction committed per row, for DuckDB `BEGIN` and `COMMIT`
around one `INSERT`, for files the two bodies written to a `.part` name and renamed, then
the manifest line appended, flushed and fsynced (the body files themselves are not
fsynced). `batch` is 256 rows per transaction (`executemany` for SQLite and DuckDB; for
files one manifest flush and fsync per batch). The `mixed` rows are spread evenly over
the whole corpus, the 50,000-row base and the 10,000 inserted rows disjoint (335 MiB raw
inserted, 34 KB a row); `commoncrawl` inserts all 9,999 Common Crawl pages (1,690 MiB
raw, 173 KB a row) into a base of 50,000 rows spread over the other four regimes. The
base is built once per (variant, mix) by the `batch` inserter, compacted, and cloned
for each run with `cp -Rc`. The zstd variants compress inside the timed loop, and every
variant parses its rows from a JSON-lines sample file inside it. Sizes are allocated MiB
before the inserts, after them with WAL and journal files included, and after `VACUUM`
or `CHECKPOINT`, whose own wall time is the `compact s` column. Each child checked that
the row count grew by exactly the rows inserted and that no WAL, shm or journal file
remained after compaction.

### Mixed rows

| variant | mode | scenario | rows | rows/s | raw MiB/s | insert s | compact s | peak RSS MiB | MiB before > after inserts > after compaction |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| files | single | empty | 10,000 | 2,811 | 94.2 | 3.56 | 0.00 | 184 | 0 > 389 > 389 |
| files | single | populated | 10,000 | 2,804 | 94.0 | 3.57 | 0.00 | 301 | 1,949 > 2,338 > 2,338 |
| files | batch | empty | 10,000 | 3,050 | 102.3 | 3.28 | 0.00 | 373 | 0 > 389 > 389 |
| files | batch | populated | 10,000 | 2,890 | 96.9 | 3.46 | 0.00 | 486 | 1,949 > 2,338 > 2,338 |
| sqlite-raw | single | empty | 10,000 | 2,716 | 91.0 | 3.68 | 1.10 | 155 | 0 > 352 > 345 |
| sqlite-raw | single | populated | 10,000 | 2,710 | 90.9 | 3.69 | 7.26 | 156 | 1,735 > 2,087 > 2,080 |
| sqlite-raw | batch | empty | 10,000 | 8,386 | 281.2 | 1.19 | 1.08 | 425 | 0 > 355 > 345 |
| sqlite-raw | batch | populated | 10,000 | 8,826 | 295.9 | 1.13 | 7.81 | 425 | 1,735 > 2,087 > 2,080 |
| sqlite-raw-wal | single | empty | 10,000 | 5,612 | 188.2 | 1.78 | 0.98 | 163 | 0 > 369 > 360 |
| sqlite-raw-wal | single | populated | 10,000 | 5,851 | 196.2 | 1.71 | 7.77 | 162 | 1,735 > 2,093 > 2,087 |
| sqlite-raw-wal | batch | empty | 10,000 | 5,938 | 199.1 | 1.68 | 0.97 | 429 | 0 > 400 > 361 |
| sqlite-raw-wal | batch | populated | 10,000 | 5,913 | 198.3 | 1.69 | 7.02 | 432 | 1,735 > 2,142 > 2,087 |
| sqlite-zstd | single | empty | 10,000 | 2,367 | 79.4 | 4.23 | 0.31 | 173 | 0 > 81 > 78 |
| sqlite-zstd | single | populated | 10,000 | 2,256 | 75.6 | 4.43 | 2.14 | 176 | 390 > 470 > 468 |
| sqlite-zstd | batch | empty | 10,000 | 6,967 | 233.6 | 1.44 | 0.27 | 390 | 0 > 80 > 78 |
| sqlite-zstd | batch | populated | 10,000 | 6,579 | 220.6 | 1.52 | 1.89 | 397 | 390 > 470 > 468 |
| sqlite-zstd-wal | single | empty | 10,000 | 6,170 | 206.9 | 1.62 | 0.21 | 173 | 0 > 85 > 80 |
| sqlite-zstd-wal | single | populated | 10,000 | 6,256 | 209.8 | 1.60 | 1.64 | 172 | 390 > 475 > 468 |
| sqlite-zstd-wal | batch | empty | 10,000 | 6,614 | 221.8 | 1.51 | 0.23 | 405 | 0 > 91 > 81 |
| sqlite-zstd-wal | batch | populated | 10,000 | 6,908 | 231.6 | 1.45 | 1.61 | 391 | 390 > 480 > 468 |
| duckdb-default | single | empty | 10,000 | 1,167 | 39.1 | 8.57 | 0.00 | 827 | 0 > 118 > 98 |
| duckdb-default | single | populated | 10,000 | 1,232 | 41.3 | 8.12 | 0.30 | 714 | 464 > 469 > 464 |
| duckdb-default | batch | empty | 10,000 | 2,750 | 92.2 | 3.64 | 0.57 | 1,195 | 0 > 82 > 112 |
| duckdb-default | batch | populated | 10,000 | 2,516 | 84.4 | 3.97 | 0.24 | 947 | 464 > 466 > 464 |
| duckdb-zstd | single | empty | 10,000 | 1,150 | 38.6 | 8.70 | 1.01 | 592 | 0 > 140 > 191 |
| duckdb-zstd | single | populated | 10,000 | 1,033 | 34.6 | 9.68 | 0.05 | 469 | 871 > 884 > 871 |
| duckdb-zstd | batch | empty | 10,000 | 2,230 | 74.8 | 4.48 | 1.01 | 734 | 0 > 124 > 192 |
| duckdb-zstd | batch | populated | 10,000 | 1,987 | 66.6 | 5.03 | 0.54 | 636 | 871 > 883 > 871 |

### Common Crawl rows

| variant | mode | scenario | rows | rows/s | raw MiB/s | insert s | compact s | peak RSS MiB | MiB before > after inserts > after compaction |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| files | single | empty | 9,999 | 1,431 | 241.9 | 6.99 | 0.00 | 426 | 0 > 1,731 > 1,731 |
| files | single | populated | 9,999 | 1,413 | 238.8 | 7.07 | 0.00 | 542 | 1,398 > 3,129 > 3,129 |
| files | batch | empty | 9,999 | 1,503 | 254.0 | 6.65 | 0.00 | 582 | 0 > 1,731 > 1,731 |
| files | batch | populated | 9,999 | 1,507 | 254.7 | 6.63 | 0.00 | 663 | 1,398 > 3,129 > 3,129 |
| sqlite-raw | single | empty | 9,999 | 1,310 | 221.4 | 7.63 | 5.53 | 320 | 0 > 1,711 > 1,703 |
| sqlite-raw | single | populated | 9,999 | 1,227 | 207.3 | 8.15 | 10.39 | 319 | 1,178 > 2,890 > 2,880 |
| sqlite-raw | batch | empty | 9,999 | 1,969 | 332.7 | 5.08 | 4.97 | 622 | 0 > 1,707 > 1,703 |
| sqlite-raw | batch | populated | 9,999 | 1,990 | 336.3 | 5.02 | 10.39 | 628 | 1,178 > 2,890 > 2,880 |
| sqlite-raw-wal | single | empty | 9,999 | 1,448 | 244.6 | 6.91 | 4.87 | 319 | 0 > 1,723 > 1,711 |
| sqlite-raw-wal | single | populated | 9,999 | 1,453 | 245.5 | 6.88 | 10.37 | 320 | 1,178 > 2,902 > 2,890 |
| sqlite-raw-wal | batch | empty | 9,999 | 1,376 | 232.6 | 7.26 | 4.52 | 620 | 0 > 1,775 > 1,703 |
| sqlite-raw-wal | batch | populated | 9,999 | 1,386 | 234.2 | 7.21 | 9.27 | 621 | 1,178 > 2,953 > 2,880 |
| sqlite-zstd | single | empty | 9,999 | 1,083 | 182.9 | 9.24 | 1.13 | 420 | 0 > 337 > 332 |
| sqlite-zstd | single | populated | 9,999 | 1,042 | 176.0 | 9.60 | 2.17 | 421 | 287 > 623 > 619 |
| sqlite-zstd | batch | empty | 9,999 | 1,588 | 268.3 | 6.30 | 1.03 | 601 | 0 > 337 > 332 |
| sqlite-zstd | batch | populated | 9,999 | 1,554 | 262.6 | 6.43 | 2.23 | 605 | 287 > 623 > 619 |
| sqlite-zstd-wal | single | empty | 9,999 | 1,494 | 252.4 | 6.69 | 0.88 | 413 | 0 > 343 > 337 |
| sqlite-zstd-wal | single | populated | 9,999 | 1,462 | 247.1 | 6.84 | 1.99 | 418 | 287 > 630 > 623 |
| sqlite-zstd-wal | batch | empty | 9,999 | 1,485 | 250.9 | 6.73 | 0.89 | 605 | 0 > 350 > 337 |
| sqlite-zstd-wal | batch | populated | 9,999 | 1,518 | 256.6 | 6.59 | 1.80 | 597 | 287 > 636 > 623 |
| duckdb-default | single | empty | 9,999 | 205 | 34.6 | 48.83 | 0.65 | 2,838 | 0 > 453 > 440 |
| duckdb-default | single | populated | 9,999 | 211 | 35.7 | 47.32 | 0.14 | 2,283 | 277 > 521 > 507 |
| duckdb-default | batch | empty | 9,999 | 652 | 110.2 | 15.33 | 0.03 | 2,581 | 0 > 329 > 329 |
| duckdb-default | batch | populated | 9,999 | 637 | 107.6 | 15.70 | 0.03 | 2,669 | 277 > 450 > 450 |
| duckdb-zstd | single | empty | 9,999 | 208 | 35.2 | 47.96 | 1.15 | 1,953 | 0 > 675 > 674 |
| duckdb-zstd | single | populated | 9,999 | 195 | 32.9 | 51.37 | 0.41 | 2,356 | 559 > 1,148 > 1,147 |
| duckdb-zstd | batch | empty | 9,999 | 447 | 75.5 | 22.37 | 0.00 | 1,756 | 0 > 521 > 521 |
| duckdb-zstd | batch | populated | 9,999 | 372 | 62.8 | 26.89 | 0.03 | 2,376 | 559 > 1,161 > 1,161 |

What the tables say:

- **Batching is worth three times for SQLite under a rollback journal, and nothing for
  files.** On mixed rows `sqlite-raw` goes from 2,716 single-row inserts a second to
  8,386 in batches of 256, `sqlite-zstd` from 2,367 to 6,967. On the 173 KB Common Crawl
  rows the gain shrinks to 1.5 times because the bytes dominate the transaction cost.
  The files store is the same in both modes (2,811 against 3,050) because only the
  manifest is fsynced and the two body writes per page are the cost.
- **WAL doubles single-row inserts and makes batching unnecessary.** `sqlite-raw-wal`
  takes 5,612 single-row inserts a second and 5,938 batched, `sqlite-zstd-wal` 6,170 and
  6,614: about 200 MiB/s either way on mixed rows, the same as the batched
  rollback-journal store. Under `synchronous=NORMAL` a commit does not sync the WAL; the
  sync happens at checkpoint. On Common Crawl rows every SQLite variant lands between
  1,300 and 2,000 rows a second (210 to 340 MiB/s), which is write bandwidth, not
  transaction count.
- **A populated store inserts as fast as an empty one.** In every (variant, mode, mix)
  pair the empty and populated rates agree within a few percent. What grows with the
  store is `VACUUM`: 7 to 10 s on a 2 to 2.9 GB raw store, 2 s on a zstd store. Inserts
  into a fresh file append, so before and after compaction differ by under 1% and the
  `VACUUM` was part of the protocol, not something inserts need; the WAL variants show
  the WAL's size (up to 75 MiB) before the checkpoint, and the rollback-journal variants
  show nothing, because the journal is gone at each commit.
- **DuckDB is the slowest store to insert into, by the most on big rows.** On mixed rows
  it takes 1,030 to 1,230 single-row inserts a second (0.8 ms a row, not the 31 ms of
  the upsert measurement above, which replaced rows through the primary key in a store
  thirteen times larger; which of those two differences matters was not separated) and
  2,000 to 2,750 batched, a third of batched SQLite. On Common Crawl rows single-row
  inserts fall to 195 to 211 a second (35 MiB/s, 5 ms a page), seven times slower than
  any SQLite variant, and batching reaches 370 to 650. Peak RSS is 0.5 to 1.2 GB on mixed
  rows and 1.8 to 2.8 GB on Common Crawl rows, against 155 to 630 MiB for SQLite (the
  256 rows of a batch held in Python are most of SQLite's batch RSS).
- **Written a row at a time, DuckDB's compression advantage disappears.** 10,000 mixed
  rows inserted into an empty store take 98 to 112 MiB in `duckdb-default` (0.29 to 0.33
  of raw) and 191 MiB in `duckdb-zstd` (0.57), against 78 MiB (0.23) for `sqlite-zstd`;
  the batch-built 50,000-row bases are 464 MiB (default) and 871 MiB (forced ZSTD) against
  390 MiB for `sqlite-zstd`, where the bulk-loaded full corpus gave DuckDB half of
  SQLite's bytes. A probe, done by hand rather than by a committed command (one more
  10,000-row batch build of each through the script's `--child` mode, then
  `pragma_storage_info` and `pragma_database_size` on the result), showed one ZSTD
  segment per body column in both, so the compression did run; but after `CHECKPOINT` more than half of
  each file is free blocks (`duckdb-default`: 437 blocks of 256 KiB, 188 in use;
  `duckdb-zstd`: 724, 373 in use), and the forced-ZSTD store's blocks in use are twice
  the default's (93 MiB against 47 MiB) for the same segment layout. The file grows at
  `CHECKPOINT` (82 to 112 MiB and 124 to 192 MiB on the empty-store batch runs) the way
  the upsert rows grew: blocks are rewritten and the old ones kept free for reuse, and
  DuckDB has no `VACUUM`, so the file never shrinks. Why forced ZSTD holds twice the live
  blocks of the default was not inspected.

## Columnar file formats

Nine more stores, built from the stores above and measured on size, write cost and the
three read shapes, with `sqlite-zstd` and `duckdb-zstd` re-measured in the same run.
Parquet, Vortex and Lance are written and read through DuckDB (the `vortex` and `lance`
core extensions, installed once into `ai_tmp/duckdb-vs-sqlite/extensions/`); the source
is `stores/duckdb-zstd`, so each write cost includes reading that store, and for the
sorted variants sorting 4.4 GB. Parquet is zstd at level 3, the level the SQLite stores
use; the `rg2k` variants write 2,048-row row groups with `DICTIONARY_SIZE_LIMIT 2048`,
which makes DuckDB dictionary-code `identity` and write a bloom filter per chunk (at the
default row group it writes none, because the limit is a fifth of the row group and
every identity is distinct). Vortex's writer exposes no compression, chunk, sort or
index option; its index layout (`vortex.indexed`) is an experimental, writer-opt-in
feature with no DuckDB or Python option yet, so the sorted file (zone maps every 8,192
rows) and the 64-file split (file-level statistics) stand in for it. Lance gets a BTREE
scalar index on `identity` from `CREATE INDEX ... USING BTREE`. `sqlite-zstd-dict` is
the `sqlite-zstd` schema with each body compressed against a 128 KiB zstd dictionary
trained per (regime, column) on 1,000 bodies spread by stride, nine in all (the GitHub
rows have no HTML), stored in a `dictionaries` table in the same file. Point lookups
through DuckDB use literals, not parameters, so the filter is a constant at planning
and pushes into the scan; one `EXPLAIN ANALYZE` per store is kept under
`results/formats-explain/`. DuckDB-read stores ran at the default memory limit and
under `SET memory_limit = '512MB'`; a cell that failed says so.

| variant | files | allocated MiB | allocated / raw | write s | write peak RSS MiB | layout |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| parquet-zstd | 1 | 549 | 0.124 | 8.6 | 8,327 | 2 row groups, no bloom filters |
| parquet-zstd-rg2k | 1 | 546 | 0.123 | 4.6 | 15,242 | 64 row groups, bloom filter on identity in every chunk |
| parquet-zstd-rg2k-sorted | 1 | 547 | 0.124 | 5.8 | 16,316 | as above, sorted by identity |
| vortex | 1 | 1,904 | 0.431 | 29.4 | 10,629 | one file, store order |
| vortex-sorted | 1 | 1,936 | 0.438 | 34.9 | 15,875 | one file, sorted by identity |
| vortex-split | 64 | 1,859 | 0.420 | 16.5 | 16,145 | 64 files, hive-partitioned by `ntile(64)` over identity |
| lance | 4 | 929 | 0.210 | 5.1 | 4,081 | one data file, no index |
| lance-btree | 8 | 927 | 0.210 | 0.1 | 155 | the same plus `identity_idx` (BTREE); the write is the index build on an APFS clone |
| sqlite-zstd-dict | 1 | 764 | 0.173 | 26.0 | 713 | nine dictionaries, 1,121 KiB, zstd level 3, written from `sqlite-raw` in Python |
| sqlite-zstd (ref) | 1 | 1,026 | 0.232 | | | per-row zstd level 3, from the size section |
| duckdb-zstd (ref) | 1 | 560 | 0.127 | | | forced ZSTD, from the size section |

| variant | query | memory limit | peak RSS MiB | wall s | ms per item | items |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| parquet-zstd | point | 51.1 GiB | 1,390 | 23.192 | 115.96 | 200 |
| parquet-zstd | point | 488.2 MiB | failed: could not allocate block of size 521.8 MiB | | | |
| parquet-zstd | scan | 51.1 GiB | 791 | 1.083 | 0.01 | 130,880 |
| parquet-zstd | scan | 488.2 MiB | 801 | 1.151 | 0.01 | 130,880 |
| parquet-zstd | meta | 51.1 GiB | 133 | 0.112 | 0.00 | 130,880 |
| parquet-zstd | meta | 488.2 MiB | 133 | 0.111 | 0.00 | 130,880 |
| parquet-zstd-rg2k | point | 51.1 GiB | 1,023 | 5.875 | 29.37 | 200 |
| parquet-zstd-rg2k | point | 488.2 MiB | failed: failed to allocate data of size 512.0 MiB | | | |
| parquet-zstd-rg2k | scan | 51.1 GiB | 1,824 | 1.055 | 0.01 | 130,880 |
| parquet-zstd-rg2k | scan | 488.2 MiB | failed: failed to allocate data of size 32.0 MiB (481.1 MiB used) | | | |
| parquet-zstd-rg2k | meta | 51.1 GiB | 183 | 0.081 | 0.00 | 130,880 |
| parquet-zstd-rg2k | meta | 488.2 MiB | 146 | 0.086 | 0.00 | 130,880 |
| parquet-zstd-rg2k-sorted | point | 51.1 GiB | 978 | 5.701 | 28.50 | 200 |
| parquet-zstd-rg2k-sorted | point | 488.2 MiB | failed: failed to allocate data of size 512.0 MiB | | | |
| parquet-zstd-rg2k-sorted | scan | 51.1 GiB | 1,761 | 1.172 | 0.01 | 130,880 |
| parquet-zstd-rg2k-sorted | scan | 488.2 MiB | failed: failed to allocate data of size 32.0 MiB (488.1 MiB used) | | | |
| parquet-zstd-rg2k-sorted | meta | 51.1 GiB | 182 | 0.095 | 0.00 | 130,880 |
| parquet-zstd-rg2k-sorted | meta | 488.2 MiB | 145 | 0.089 | 0.00 | 130,880 |
| vortex | point | 51.1 GiB | 2,414 | 2.355 | 11.78 | 200 |
| vortex | point | 488.2 MiB | 2,414 | 2.140 | 10.70 | 200 |
| vortex | scan | 51.1 GiB | 2,272 | 1.053 | 0.01 | 130,880 |
| vortex | scan | 488.2 MiB | 2,285 | 1.039 | 0.01 | 130,880 |
| vortex | meta | 51.1 GiB | 167 | 0.106 | 0.00 | 130,880 |
| vortex | meta | 488.2 MiB | 164 | 0.107 | 0.00 | 130,880 |
| vortex-sorted | point | 51.1 GiB | 1,586 | 2.259 | 11.30 | 200 |
| vortex-sorted | point | 488.2 MiB | 1,584 | 2.288 | 11.44 | 200 |
| vortex-sorted | scan | 51.1 GiB | 2,364 | 1.092 | 0.01 | 130,880 |
| vortex-sorted | scan | 488.2 MiB | 2,385 | 1.136 | 0.01 | 130,880 |
| vortex-sorted | meta | 51.1 GiB | 169 | 0.102 | 0.00 | 130,880 |
| vortex-sorted | meta | 488.2 MiB | 169 | 0.105 | 0.00 | 130,880 |
| vortex-split | point | 51.1 GiB | 1,118 | 1.566 | 7.83 | 200 |
| vortex-split | point | 488.2 MiB | 1,118 | 1.593 | 7.96 | 200 |
| vortex-split | scan | 51.1 GiB | 1,545 | 1.038 | 0.01 | 130,880 |
| vortex-split | scan | 488.2 MiB | 1,571 | 1.070 | 0.01 | 130,880 |
| vortex-split | meta | 51.1 GiB | 149 | 0.105 | 0.00 | 130,880 |
| vortex-split | meta | 488.2 MiB | 150 | 0.108 | 0.00 | 130,880 |
| lance | point | 51.1 GiB | 163 | 0.726 | 3.63 | 200 |
| lance | point | 488.2 MiB | 162 | 0.664 | 3.32 | 200 |
| lance | scan | 51.1 GiB | 2,211 | 1.199 | 0.01 | 130,880 |
| lance | scan | 488.2 MiB | 2,229 | 1.177 | 0.01 | 130,880 |
| lance | meta | 51.1 GiB | 194 | 0.150 | 0.00 | 130,880 |
| lance | meta | 488.2 MiB | 188 | 0.153 | 0.00 | 130,880 |
| lance-btree | point | 51.1 GiB | 123 | 0.216 | 1.08 | 200 |
| lance-btree | point | 488.2 MiB | 116 | 0.252 | 1.26 | 200 |
| lance-btree | scan | 51.1 GiB | 2,173 | 1.264 | 0.01 | 130,880 |
| lance-btree | scan | 488.2 MiB | 2,231 | 1.193 | 0.01 | 130,880 |
| lance-btree | meta | 51.1 GiB | 185 | 0.153 | 0.00 | 130,880 |
| lance-btree | meta | 488.2 MiB | 192 | 0.165 | 0.00 | 130,880 |
| sqlite-zstd-dict | point | SQLite default | 45 | 0.011 | 0.05 | 200 |
| sqlite-zstd-dict | scan | SQLite default | 64 | 1.180 | 0.01 | 130,880 |
| sqlite-zstd-dict | meta | SQLite default | 44 | 0.216 | 0.00 | 130,880 |
| sqlite-zstd | point | SQLite default | 43 | 0.010 | 0.05 | 200 |
| sqlite-zstd | scan | SQLite default | 63 | 1.178 | 0.01 | 130,880 |
| sqlite-zstd | meta | SQLite default | 42 | 0.215 | 0.00 | 130,880 |
| duckdb-zstd | point | 51.1 GiB | 537 | 2.538 | 12.69 | 200 |
| duckdb-zstd | point | 488.2 MiB | 537 | 2.480 | 12.40 | 200 |
| duckdb-zstd | scan | 51.1 GiB | 624 | 0.992 | 0.01 | 130,880 |
| duckdb-zstd | scan | 488.2 MiB | 622 | 0.989 | 0.01 | 130,880 |
| duckdb-zstd | meta | 51.1 GiB | 95 | 0.081 | 0.00 | 130,880 |
| duckdb-zstd | meta | 488.2 MiB | 96 | 0.085 | 0.00 | 130,880 |

What the tables say:

- **Parquet with zstd is DuckDB's own disk figure, and nothing else gets close.** The
  three Parquet files are 0.123 to 0.124 of raw against 0.127 for `duckdb-zstd`; the row
  group size does not change it. Lance is 0.210 and Vortex 0.42 to 0.44, three and a
  half times Parquet: its lightweight encodings do not find the repetition across pages
  that a zstd segment does, and its writer offers no knob for that. The dictionary cuts
  the SQLite zstd store from 0.232 to 0.173 (1,026 to 764 MiB), a quarter off, for
  1.1 MiB of dictionaries.
- **A point lookup on a columnar file pays for the column chunk around the row.**
  `parquet-zstd` reads 549 MB per lookup (the whole HTML chunk of a 122,880-row row
  group, per `EXPLAIN ANALYZE`), 116 ms and 1.4 GB of RSS, and under the 512 MB limit it
  fails outright ("could not allocate block of size 521.8 MiB"). The 2,048-row row
  groups bring that to 5.5 MB read, "1 / 64 row groups scanned", 29 ms and about 1 GB
  (the bloom filters and statistics do their job; sorting adds nothing on top), but the
  reader still fails under 512 MB, on point lookups and on scans. Vortex has no
  counters in its plan; its lookups take 11.8 ms unsorted, 11.3 ms sorted and 7.8 ms
  split, at 2.4, 1.6 and 1.1 GB of RSS, so the zone maps and file statistics halve the
  memory and the split halves the time, and all three stay slower than `duckdb-zstd`
  (12.7 ms, 537 MiB) in memory. Lance is the one columnar store that looks up like a
  database: 3.6 ms at 163 MiB without an index and 1.1 ms at 123 MiB with the BTREE
  index, ten times faster than `duckdb-zstd` on a quarter of the memory. SQLite does it
  in 0.05 ms at 43 to 45 MiB, with or without the dictionary.
- **Scans are a wash in time and a spread in memory.** Every store streams the 130,880
  Markdown bodies in 1.0 to 1.3 s; the memory is 63 to 64 MiB for the two SQLite stores,
  624 MiB for `duckdb-zstd`, 791 MiB for `parquet-zstd`, 1.5 to 2.4 GB for the Vortex and
  Lance stores and the small-row-group Parquet files. The metadata select is 0.08 to
  0.15 s everywhere through DuckDB at 95 to 194 MiB, against 0.22 s at 42 to 44 MiB for
  SQLite.
- **The 512 MB limit governs DuckDB's buffer pool, not the extensions.** Vortex and Lance
  reads peaked at 1.1 to 2.4 GB of RSS under a limit DuckDB reported as 488.2 MiB, and
  no number moved; the Parquet reader, which is DuckDB's own, honoured it and failed
  where a single column chunk or the scan's buffers exceeded it.
- **Writing is where DuckDB's columnar paths spend memory.** Writing Parquet from the
  DuckDB store peaked at 8.3 GB of RSS unsorted and 15 to 16 GB with small row groups or
  a sort, Vortex at 10.6 to 16.1 GB and Lance at 4.1 GB, in 5 to 35 s; the Python
  dictionary store took 26 s at 713 MiB. The source read and the sort are part of those
  numbers, and a streaming writer would need less; the bulk-ingestion caveat below
  still applies.

## Apache Avro

Six Avro container files, measured on every axis above, with `parquet-zstd`,
`sqlite-zstd-dict` and `duckdb-zstd` re-measured in the same run. An Avro file is a
header and a run of blocks; each block carries its record count, its byte size and a
16-byte sync marker, so a reader can skip a block without decoding it, but there are no
statistics or index to find a row. Each store therefore has a sidecar SQLite file,
`pages.index.sqlite`, mapping identity to (block offset, position in block), built in
one pass over the blocks after the write; it is the stand-in for an index, as sorting
and splitting were for Vortex, it is a file the format does not define, and its 22 MiB
and 2 to 4 s are in each row's size and write cost.

- `avro-duckdb` is written by DuckDB's `avro` core extension, `COPY ... TO 'pages.avro'
  (FORMAT avro, CODEC 'deflate')`, from `stores/duckdb-zstd`. The writer has no block
  size option and writes one block per DuckDB chunk, about 2,048 rows.
- `avro-deflate`, `avro-deflate-1m`, `avro-zstd` and `avro-zstd-1m` are written by
  fastavro from `stores/sqlite-raw` in rowid order: deflate at its default level or
  zstandard at level 3, with fastavro's default `sync_interval` of 16,000 bytes (a block
  is flushed once that many bytes are buffered, so about two pages a block here) or
  1 MiB (about 35 pages).
- `avro-deflate-pyavro` is written by the official `avro` package, deflate, at its
  default sync interval of 64,000 bytes.

The schema is one record per page, the eleven columns of every store, `raw_digest` and
`html` as `["null", "string"]` unions (the only columns the corpus leaves null), the two
sizes as `long`. Each store is read three ways. Through DuckDB's `read_avro` at the
default memory limit and under 512 MB: the extension decodes the whole file for every
query (no projection or filter pushdown, one thread), so a DuckDB point lookup looks up
only 5 of the 200 identities, every 40th, and is compared per item. Through fastavro: a
point lookup reads the sidecar index, seeks to the block, decodes it and takes the record
at its position (one `block_reader` serves every lookup; seeking under it works); the
scan and the metadata select decode a projection of the file's own writer schema, since
DuckDB names its record `root` and makes every field nullable and fastavro refuses a
reader schema with a different record name.

The research before the run said DuckDB's Avro reader, built on Avro C, would not read
zstandard blocks. It does: this build of the extension (`345c3f4e82`) read every
fastavro zstd file, and a by-hand probe on 20 rows showed its writer accepts
`CODEC 'zstandard'` too. Snappy needs the `cramjam` package in fastavro and was not
measured.

| variant | files | allocated MiB | allocated / raw | write s | write peak RSS MiB | layout |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| avro-duckdb | 2 | 729 | 0.165 | 67.5 | 3,998 | DuckDB COPY deflate, writer's own blocks; 64 blocks, 2,045 rows and 11,237 KiB per block; index 130,880 rows, 22.6 MiB, 3.4 s |
| avro-deflate | 2 | 823 | 0.186 | 48.3 | 343 | fastavro deflate level default, sync 16,000 B; 60,314 blocks, 2.2 rows and 13 KiB per block; index 130,880 rows, 22.4 MiB, 3.5 s |
| avro-deflate-1m | 2 | 743 | 0.168 | 47.1 | 377 | fastavro deflate level default, sync 1,048,576 B; 3,724 blocks, 35.1 rows and 196 KiB per block; index 130,880 rows, 22.5 MiB, 3.2 s |
| avro-zstd | 2 | 792 | 0.179 | 12.4 | 377 | fastavro zstandard level 3, sync 16,000 B; 60,314 blocks, 2.2 rows and 13 KiB per block; index 130,880 rows, 22.4 MiB, 2.9 s |
| avro-zstd-1m | 2 | 567 | 0.128 | 11.0 | 383 | fastavro zstandard level 3, sync 1,048,576 B; 3,724 blocks, 35.1 rows and 148 KiB per block; index 130,880 rows, 22.5 MiB, 2.3 s |
| avro-deflate-pyavro | 2 | 776 | 0.175 | 48.0 | 353 | official avro deflate, sync 64,000 B; 30,693 blocks, 4.3 rows and 25 KiB per block; index 130,880 rows, 22.4 MiB, 3.4 s |

| variant | query | reader | peak RSS MiB | wall s | ms per item | items |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| avro-duckdb | point | DuckDB, 51.1 GiB | 5,931 | 4.849 | 969.79 | 5 |
| avro-duckdb | point | DuckDB, 488.2 MiB | failed: could not allocate block of size 702.2 MiB | | | |
| avro-duckdb | point | fastavro | 3,088 | 8.423 | 42.12 | 200 |
| avro-duckdb | scan | DuckDB, 51.1 GiB | 8,561 | 4.172 | 0.03 | 130,880 |
| avro-duckdb | scan | DuckDB, 488.2 MiB | failed: could not allocate block of size 702.2 MiB | | | |
| avro-duckdb | scan | fastavro | 2,257 | 3.362 | 0.03 | 130,880 |
| avro-duckdb | meta | DuckDB, 51.1 GiB | 7,850 | 2.415 | 0.02 | 130,880 |
| avro-duckdb | meta | DuckDB, 488.2 MiB | failed: could not allocate block of size 702.2 MiB | | | |
| avro-duckdb | meta | fastavro | 2,161 | 3.000 | 0.02 | 130,880 |
| avro-deflate | point | DuckDB, 51.1 GiB | 2,048 | 2.548 | 509.62 | 5 |
| avro-deflate | point | DuckDB, 488.2 MiB | failed: could not allocate block of size 789.1 MiB | | | |
| avro-deflate | point | fastavro | 49 | 0.018 | 0.09 | 200 |
| avro-deflate | scan | DuckDB, 51.1 GiB | 1,870 | 1.547 | 0.01 | 130,880 |
| avro-deflate | scan | DuckDB, 488.2 MiB | failed: could not allocate block of size 789.1 MiB | | | |
| avro-deflate | scan | fastavro | 169 | 3.563 | 0.03 | 130,880 |
| avro-deflate | meta | DuckDB, 51.1 GiB | 1,972 | 0.944 | 0.01 | 130,880 |
| avro-deflate | meta | DuckDB, 488.2 MiB | failed: could not allocate block of size 789.1 MiB | | | |
| avro-deflate | meta | fastavro | 103 | 2.984 | 0.02 | 130,880 |
| avro-deflate-1m | point | DuckDB, 51.1 GiB | 1,860 | 2.211 | 442.26 | 5 |
| avro-deflate-1m | point | DuckDB, 488.2 MiB | failed: could not allocate block of size 711.1 MiB | | | |
| avro-deflate-1m | point | fastavro | 66 | 0.167 | 0.84 | 200 |
| avro-deflate-1m | scan | DuckDB, 51.1 GiB | 2,074 | 1.390 | 0.01 | 130,880 |
| avro-deflate-1m | scan | DuckDB, 488.2 MiB | failed: could not allocate block of size 711.1 MiB | | | |
| avro-deflate-1m | scan | fastavro | 176 | 3.170 | 0.02 | 130,880 |
| avro-deflate-1m | meta | DuckDB, 51.1 GiB | 1,878 | 0.526 | 0.00 | 130,880 |
| avro-deflate-1m | meta | DuckDB, 488.2 MiB | failed: could not allocate block of size 711.1 MiB | | | |
| avro-deflate-1m | meta | fastavro | 109 | 2.609 | 0.02 | 130,880 |
| avro-zstd | point | DuckDB, 51.1 GiB | 2,039 | 1.681 | 336.26 | 5 |
| avro-zstd | point | DuckDB, 488.2 MiB | failed: could not allocate block of size 760.5 MiB | | | |
| avro-zstd | point | fastavro | 50 | 0.017 | 0.08 | 200 |
| avro-zstd | scan | DuckDB, 51.1 GiB | 1,816 | 1.416 | 0.01 | 130,880 |
| avro-zstd | scan | DuckDB, 488.2 MiB | failed: could not allocate block of size 760.5 MiB | | | |
| avro-zstd | scan | fastavro | 170 | 2.861 | 0.02 | 130,880 |
| avro-zstd | meta | DuckDB, 51.1 GiB | 1,828 | 0.750 | 0.01 | 130,880 |
| avro-zstd | meta | DuckDB, 488.2 MiB | failed: could not allocate block of size 760.5 MiB | | | |
| avro-zstd | meta | fastavro | 110 | 2.289 | 0.02 | 130,880 |
| avro-zstd-1m | point | DuckDB, 51.1 GiB | 1,607 | 1.294 | 258.80 | 5 |
| avro-zstd-1m | point | DuckDB, 488.2 MiB | failed: could not allocate block of size 538.5 MiB | | | |
| avro-zstd-1m | point | fastavro | 70 | 0.148 | 0.74 | 200 |
| avro-zstd-1m | scan | DuckDB, 51.1 GiB | 1,763 | 1.160 | 0.01 | 130,880 |
| avro-zstd-1m | scan | DuckDB, 488.2 MiB | failed: could not allocate block of size 538.5 MiB | | | |
| avro-zstd-1m | scan | fastavro | 180 | 2.433 | 0.02 | 130,880 |
| avro-zstd-1m | meta | DuckDB, 51.1 GiB | 1,576 | 0.320 | 0.00 | 130,880 |
| avro-zstd-1m | meta | DuckDB, 488.2 MiB | failed: could not allocate block of size 538.5 MiB | | | |
| avro-zstd-1m | meta | fastavro | 117 | 1.877 | 0.01 | 130,880 |
| avro-deflate-pyavro | point | DuckDB, 51.1 GiB | 1,893 | 2.378 | 475.65 | 5 |
| avro-deflate-pyavro | point | DuckDB, 488.2 MiB | failed: could not allocate block of size 738.6 MiB | | | |
| avro-deflate-pyavro | point | fastavro | 49 | 0.025 | 0.12 | 200 |
| avro-deflate-pyavro | scan | DuckDB, 51.1 GiB | 1,980 | 1.420 | 0.01 | 130,880 |
| avro-deflate-pyavro | scan | DuckDB, 488.2 MiB | failed: could not allocate block of size 738.6 MiB | | | |
| avro-deflate-pyavro | scan | fastavro | 174 | 3.391 | 0.03 | 130,880 |
| avro-deflate-pyavro | meta | DuckDB, 51.1 GiB | 1,890 | 0.703 | 0.01 | 130,880 |
| avro-deflate-pyavro | meta | DuckDB, 488.2 MiB | failed: could not allocate block of size 738.6 MiB | | | |
| avro-deflate-pyavro | meta | fastavro | 103 | 2.835 | 0.02 | 130,880 |
| parquet-zstd | point | DuckDB, 51.1 GiB | 1,392 | 22.197 | 110.98 | 200 |
| parquet-zstd | point | DuckDB, 488.2 MiB | failed: could not allocate block of size 521.8 MiB | | | |
| parquet-zstd | scan | DuckDB, 51.1 GiB | 791 | 1.056 | 0.01 | 130,880 |
| parquet-zstd | scan | DuckDB, 488.2 MiB | 791 | 1.061 | 0.01 | 130,880 |
| parquet-zstd | meta | DuckDB, 51.1 GiB | 135 | 0.101 | 0.00 | 130,880 |
| parquet-zstd | meta | DuckDB, 488.2 MiB | 135 | 0.100 | 0.00 | 130,880 |
| sqlite-zstd-dict | point | SQLite default | 47 | 0.009 | 0.05 | 200 |
| sqlite-zstd-dict | scan | SQLite default | 66 | 1.111 | 0.01 | 130,880 |
| sqlite-zstd-dict | meta | SQLite default | 46 | 0.175 | 0.00 | 130,880 |
| duckdb-zstd | point | DuckDB, 51.1 GiB | 539 | 2.457 | 12.29 | 200 |
| duckdb-zstd | point | DuckDB, 488.2 MiB | 540 | 2.447 | 12.23 | 200 |
| duckdb-zstd | scan | DuckDB, 51.1 GiB | 627 | 0.993 | 0.01 | 130,880 |
| duckdb-zstd | scan | DuckDB, 488.2 MiB | 628 | 0.982 | 0.01 | 130,880 |
| duckdb-zstd | meta | DuckDB, 51.1 GiB | 98 | 0.083 | 0.00 | 130,880 |
| duckdb-zstd | meta | DuckDB, 488.2 MiB | 98 | 0.081 | 0.00 | 130,880 |

Insert throughput: `avro-zstd` appends to one file through fastavro (zstandard level 3,
16,000-byte blocks), opening it `a+b` and writing, flushing and fsyncing once per row in
`single` and once per 256 rows in `batch`, as the files store fsyncs its manifest; there
is no compaction. Same samples and protocol as the insert section, with
`sqlite-zstd-wal` and `duckdb-zstd` run beside it.

| variant | mode | mix | scenario | rows | rows/s | raw MiB/s | insert s | compact s | peak RSS MiB | MiB before > after inserts > after compaction |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| avro-zstd | single | mixed | empty | 10,000 | 4,751 | 159.3 | 2.10 | 0.00 | 172 | 0 > 63 > 63 |
| avro-zstd | single | mixed | populated | 10,000 | 5,142 | 172.4 | 1.94 | 0.00 | 201 | 289 > 353 > 353 |
| avro-zstd | batch | mixed | empty | 10,000 | 7,481 | 250.8 | 1.34 | 0.00 | 378 | 0 > 59 > 59 |
| avro-zstd | batch | mixed | populated | 10,000 | 7,446 | 249.6 | 1.34 | 0.00 | 397 | 289 > 353 > 353 |
| avro-zstd | single | commoncrawl | empty | 9,999 | 1,462 | 247.0 | 6.84 | 0.00 | 419 | 0 > 305 > 305 |
| avro-zstd | single | commoncrawl | populated | 9,999 | 1,478 | 249.7 | 6.77 | 0.00 | 392 | 192 > 496 > 496 |
| avro-zstd | batch | commoncrawl | empty | 9,999 | 1,582 | 267.3 | 6.32 | 0.00 | 591 | 0 > 304 > 304 |
| avro-zstd | batch | commoncrawl | populated | 9,999 | 1,642 | 277.4 | 6.09 | 0.00 | 587 | 192 > 496 > 496 |
| sqlite-zstd-wal | single | mixed | empty | 10,000 | 6,256 | 209.7 | 1.60 | 0.25 | 180 | 0 > 86 > 81 |
| sqlite-zstd-wal | single | mixed | populated | 10,000 | 6,400 | 214.6 | 1.56 | 1.73 | 174 | 390 > 475 > 468 |
| sqlite-zstd-wal | batch | mixed | empty | 10,000 | 6,716 | 225.2 | 1.49 | 0.20 | 393 | 0 > 90 > 80 |
| sqlite-zstd-wal | batch | mixed | populated | 10,000 | 6,845 | 229.5 | 1.46 | 1.60 | 393 | 390 > 480 > 468 |
| sqlite-zstd-wal | single | commoncrawl | empty | 9,999 | 1,490 | 251.8 | 6.71 | 0.88 | 413 | 0 > 343 > 337 |
| sqlite-zstd-wal | single | commoncrawl | populated | 9,999 | 1,458 | 246.4 | 6.86 | 1.98 | 417 | 287 > 630 > 623 |
| sqlite-zstd-wal | batch | commoncrawl | empty | 9,999 | 1,486 | 251.1 | 6.73 | 0.89 | 600 | 0 > 350 > 337 |
| sqlite-zstd-wal | batch | commoncrawl | populated | 9,999 | 1,495 | 252.7 | 6.69 | 1.86 | 603 | 287 > 636 > 623 |
| duckdb-zstd | single | mixed | empty | 10,000 | 1,090 | 36.5 | 9.18 | 1.01 | 595 | 0 > 140 > 191 |
| duckdb-zstd | single | mixed | populated | 10,000 | 1,068 | 35.8 | 9.36 | 0.05 | 467 | 871 > 884 > 871 |
| duckdb-zstd | batch | mixed | empty | 10,000 | 2,141 | 71.8 | 4.67 | 1.03 | 742 | 0 > 124 > 192 |
| duckdb-zstd | batch | mixed | populated | 10,000 | 2,012 | 67.5 | 4.97 | 0.54 | 642 | 871 > 883 > 871 |
| duckdb-zstd | single | commoncrawl | empty | 9,999 | 208 | 35.2 | 48.02 | 1.20 | 1,925 | 0 > 675 > 674 |
| duckdb-zstd | single | commoncrawl | populated | 9,999 | 205 | 34.7 | 48.68 | 0.41 | 2,225 | 559 > 1,148 > 1,147 |
| duckdb-zstd | batch | commoncrawl | empty | 9,999 | 459 | 77.6 | 21.77 | 0.00 | 1,751 | 0 > 521 > 521 |
| duckdb-zstd | batch | commoncrawl | populated | 9,999 | 380 | 64.2 | 26.30 | 0.03 | 2,376 | 559 > 1,161 > 1,161 |

What the tables say:

- **Zstd with 1 MiB blocks is the only Avro store on DuckDB's disk figure.**
  `avro-zstd-1m` is 0.128 of raw, index included (567 MiB against 549 for `parquet-zstd`,
  560 for `duckdb-zstd` and 764 for `sqlite-zstd-dict`). The block size matters more than
  the codec: at about two pages a block zstd is 0.179 and deflate 0.186, worse than the
  dictionary SQLite store; at 1 MiB zstd drops to 0.128 and deflate only to 0.168, since
  deflate's 32 KB window cannot reach across pages as zstd's can. DuckDB's writer, with
  11 MB blocks, is 0.165, held back by deflate. Zstd also writes four times faster than
  deflate (11 to 12 s against 47 to 48 s from the same Python loop at under 400 MiB); the
  official package is no slower than fastavro with deflate (48.0 s against 48.3 s), so
  the codec, not the writer, is the cost. DuckDB's write took 68 s at 4.0 GB of RSS.
- **DuckDB reads Avro whole, and never under 512 MB.** Every one of the 18 cells under
  the limit failed at the first allocation, a block the size of the file ("could not
  allocate block of size 539 to 789 MiB"). At the default limit a point lookup costs
  259 to 970 ms per identity, two to nine times a `parquet-zstd` lookup, at 1.6 to
  5.9 GB of RSS; scans and the metadata select take 0.3 to 4.2 s at 1.6 to 8.6 GB, where
  `duckdb-zstd` scans in 1.0 s at 627 MiB. The plans show one `READ_AVRO` scan of every
  row with the filter above it. `avro-duckdb` is the worst of the six through DuckDB
  (970 ms, 5.9 GB per lookup; 8.6 GB on the scan), because its blocks are 11 MB.
- **Through fastavro and the sidecar index, a lookup costs one block.** At about two
  pages a block a lookup takes 0.08 to 0.12 ms at 49 to 50 MiB, about twice SQLite's
  0.05 ms at 47 MiB; at 35 pages a block it takes 0.74 to 0.84 ms at 66 to
  70 MiB, and on DuckDB's 2,045-row blocks 42 ms at 3.1 GB. The fastavro scan takes
  2.4 to 3.6 s at 169 to 180 MiB, two to three times SQLite's 1.1 s, and the metadata
  select 1.9 to 3.0 s at 103 to 117 MiB, eleven to seventeen times SQLite's 0.18 s: a
  projection only skips the dropped fields after each block is decompressed, so the
  metadata select still inflates every HTML body.
- **Appending to Avro is as fast as SQLite in WAL mode, but the blocks are what the
  writes make them.** Single-row appends with an fsync each ran at 4,751 to 5,142 rows/s
  on mixed rows (6,256 to 6,400 for `sqlite-zstd-wal`, 1,068 to 1,090 for `duckdb-zstd`)
  and 1,462 to 1,478 on Common Crawl rows (1,458 to 1,490 and 205 to 208); in batches
  of 256 Avro is the fastest of the three (7,446 to 7,481 rows/s on mixed rows). But a
  row appended on its own is a block on its own: 10,000 mixed rows took 63 MiB, 0.19 of
  the 335 MiB inserted, against 81 MiB (0.24) for `sqlite-zstd-wal`, nowhere near the
  0.128 of the 1 MiB file, which needs about 35 pages buffered before each write.

Avro adds no update or delete. A page fetched again is appended and the index repointed,
so the old version stays in the file until the whole file is rewritten, and the index is
a second file whose consistency with the first after a crash is the application's
problem. The sidecar index was built after the writes, never kept up to date by the
insert runs; the gaps section keeps it up to date through upserts.

## Closing the gaps

Three measurements the Avro section left open, so the two candidates for the store,
Avro zstd in 1 MiB blocks with its sidecar index and the dictionary SQLite store, are
compared on every axis.

- **Avro appends in 1 MiB blocks.** `avro-zstd-1m` joins the insert benchmark: fastavro,
  zstd level 3, `sync_interval` of 1 MiB. `batch` appends 256 rows with one fsync, as
  `avro-zstd` does. `single` buffers rows until about 1 MiB of raw body bytes are held
  (about 30 mixed pages or 6 Common Crawl pages), appends them as one block with one
  fsync, and flushes the remainder at the end; a row is durable only once its block is,
  so the table marks it `(buffered)`.
- **The dictionary store through the insert benchmark.** `sqlite-zstd-dict-wal` is
  `sqlite-zstd-wal` (WAL, `synchronous=NORMAL`) with every body compressed against the
  nine per-(regime, column) dictionaries `bench_formats.py` trained, copied into each
  fresh store, plain zstd where a (regime, column) has none. The dictionaries were
  trained on the whole corpus, the inserted rows included, which flatters its ratio a
  little.
- **Upserts on both, and on the dictionary store.** `bench_formats.py --upserts` runs
  the 500 upserts `bench_queries.py` prepared (existing identities, changed Markdown),
  one transaction each, on an APFS clone in a fresh child, twice. SQLite runs the same
  `INSERT ... ON CONFLICT DO UPDATE` as the query section, then `VACUUM`. Avro appends
  each record as its own block with an fsync and repoints the identity in the sidecar
  index; compaction rewrites the file with only the records the index points to, in the
  store's block size, and rebuilds the index, so its time includes the index. The row
  time here excludes opening and compaction, unlike the query section's upsert row.

Insert throughput, `sqlite-zstd-wal` run beside the two as the in-run reference:

| variant | mode | mix | scenario | rows | rows/s | raw MiB/s | insert s | compact s | peak RSS MiB | MiB before > after inserts > after compaction |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| avro-zstd-1m (buffered) | single | mixed | empty | 10,000 | 8,066 | 270.4 | 1.24 | 0.00 | 185 | 0 > 43.5 > 43.5 |
| avro-zstd-1m (buffered) | single | mixed | populated | 10,000 | 8,348 | 279.9 | 1.20 | 0.00 | 207 | 211.4 > 259.4 > 259.4 |
| avro-zstd-1m | batch | mixed | empty | 10,000 | 8,185 | 274.4 | 1.22 | 0.00 | 379 | 0 > 43.8 > 43.8 |
| avro-zstd-1m | batch | mixed | populated | 10,000 | 7,862 | 263.6 | 1.27 | 0.00 | 391 | 211.4 > 259.4 > 259.4 |
| avro-zstd-1m (buffered) | single | commoncrawl | empty | 9,999 | 1,631 | 275.6 | 6.13 | 0.00 | 403 | 0 > 272.2 > 272.2 |
| avro-zstd-1m (buffered) | single | commoncrawl | populated | 9,999 | 1,613 | 272.5 | 6.20 | 0.00 | 426 | 116.1 > 388.1 > 388.1 |
| avro-zstd-1m | batch | commoncrawl | empty | 9,999 | 1,609 | 271.9 | 6.21 | 0.00 | 603 | 0 > 272.2 > 272.2 |
| avro-zstd-1m | batch | commoncrawl | populated | 9,999 | 1,628 | 275.1 | 6.14 | 0.00 | 605 | 116.1 > 388.1 > 388.1 |
| sqlite-zstd-dict-wal | single | mixed | empty | 10,000 | 6,049 | 202.8 | 1.65 | 0.15 | 187 | 0 > 64.0 > 59.0 |
| sqlite-zstd-dict-wal | single | mixed | populated | 10,000 | 5,812 | 194.9 | 1.72 | 1.30 | 188 | 290.4 > 359.4 > 348.2 |
| sqlite-zstd-dict-wal | batch | mixed | empty | 10,000 | 6,419 | 215.2 | 1.56 | 0.18 | 411 | 0 > 68.8 > 59.1 |
| sqlite-zstd-dict-wal | batch | mixed | populated | 10,000 | 6,558 | 219.9 | 1.52 | 1.22 | 412 | 290.4 > 363.6 > 354.4 |
| sqlite-zstd-dict-wal | single | commoncrawl | empty | 9,999 | 1,253 | 211.7 | 7.98 | 1.19 | 416 | 0 > 327.3 > 320.3 |
| sqlite-zstd-dict-wal | single | commoncrawl | populated | 9,999 | 1,296 | 219.1 | 7.71 | 1.53 | 417 | 188.3 > 513.4 > 508.3 |
| sqlite-zstd-dict-wal | batch | commoncrawl | empty | 9,999 | 1,337 | 225.9 | 7.48 | 0.92 | 596 | 0 > 333.0 > 320.5 |
| sqlite-zstd-dict-wal | batch | commoncrawl | populated | 9,999 | 1,322 | 223.4 | 7.56 | 1.52 | 595 | 188.3 > 520.9 > 508.3 |
| sqlite-zstd-wal | single | mixed | empty | 10,000 | 5,982 | 200.6 | 1.67 | 0.20 | 175 | 0 > 85.5 > 80.4 |
| sqlite-zstd-wal | single | mixed | populated | 10,000 | 6,200 | 207.9 | 1.61 | 1.74 | 175 | 390.0 > 474.9 > 467.9 |
| sqlite-zstd-wal | batch | mixed | empty | 10,000 | 6,548 | 219.5 | 1.53 | 0.21 | 391 | 0 > 90.3 > 80.5 |
| sqlite-zstd-wal | batch | mixed | populated | 10,000 | 6,698 | 224.6 | 1.49 | 1.70 | 395 | 390.0 > 480.3 > 467.9 |
| sqlite-zstd-wal | single | commoncrawl | empty | 9,999 | 1,489 | 251.7 | 6.71 | 1.00 | 411 | 0 > 342.7 > 336.6 |
| sqlite-zstd-wal | single | commoncrawl | populated | 9,999 | 1,487 | 251.3 | 6.72 | 1.89 | 413 | 287.1 > 630.3 > 623.1 |
| sqlite-zstd-wal | batch | commoncrawl | empty | 9,999 | 1,509 | 255.1 | 6.62 | 0.94 | 599 | 0 > 349.6 > 336.6 |
| sqlite-zstd-wal | batch | commoncrawl | populated | 9,999 | 1,489 | 251.5 | 6.72 | 1.92 | 601 | 287.1 > 636.2 > 623.1 |

Upserts, 500 rows one transaction each, second of two runs (the first in brackets):

| variant | ms per row | compaction s | peak RSS MiB | MiB before > after upserts > after compaction | compaction |
| --- | ---: | ---: | ---: | --- | --- |
| sqlite-zstd | 0.77 (0.80) | 4.1 (4.3) | 96 | 1,026.3 > 1,042.3 > 1,026.3 | VACUUM |
| sqlite-zstd-dict | 1.88 (0.79) | 3.4 (3.2) | 111 | 763.9 > 779.9 > 763.9 | VACUUM |
| avro-zstd | 0.48 (0.84) | 13.1 (13.2) | 423 | 783.0 > 799.0 > 791.7 | rewrite in 16,000-byte blocks, then rebuild the index |
| avro-zstd-1m | 0.45 (0.44) | 11.0 (10.9) | 429 | 561.1 > 577.1 > 567.5 | rewrite in 1 MiB blocks, then rebuild the index |

Every insert child found the row count grown by exactly the rows inserted, and every
upsert child found 130,880 rows and all 500 changed Markdown bodies after compaction;
the Avro children also found them through the live index before compacting, with
131,380 records in the file.

What the tables say:

- **Buffered into 1 MiB blocks, Avro is the fastest single-row writer and lands at
  its bulk ratio.** 8,066 to 8,348 rows/s on mixed rows against 5,982 to 6,200 for
  `sqlite-zstd-wal` in the same run, and 1,613 to 1,631 on Common Crawl rows against
  1,487 to 1,489; 10,000 mixed rows land at 0.130 of raw (43.5 MiB), the 0.128 of the
  bulk-written file, where `avro-zstd` appending a row at a time landed at 0.188. The
  price is durability: a crash loses the rows still buffered, up to a block, and the
  crawler must fetch them again. `batch` in 1 MiB blocks is the same speed and ratio.
- **The dictionary costs nothing on typical pages and 13 to 16% on large ones.** Single-row
  inserts on mixed rows run at 5,812 to 6,049 rows/s against 5,982 to 6,200 without a
  dictionary, and land at 0.176 of raw against 0.240; on Common Crawl rows they run at
  1,253 to 1,296 against 1,487 to 1,489 and land at 0.190 against 0.199, so the
  regime's dictionary helps little on 173 KB pages from many hosts. Peak RSS is the
  same. Against buffered Avro the dictionary store writes 25 to 30% fewer rows a second
  and takes 36% more disk for the same 10,000 rows (59.0 MiB against 43.5).
- **Upserts cost under 2 ms a row on all four; compaction is what differs.** The rows
  took 0.44 to 1.88 ms (the dictionary store's two runs, 0.79 and 1.88 ms, show the
  noise of one run of 500 fsyncs). Each store grew 16 MiB. `VACUUM` returned both SQLite
  files to the exact size in 3.4 to 4.1 s at 96 to 111 MiB of peak RSS. Avro has no
  in-place reclaim: compaction rewrote the whole 539 to 761 MiB file and rebuilt the
  index in 11.0 to 13.1 s at 423 to 429 MiB, a cost that grows with the store, not with
  the garbage. The Avro rows end 6.4 to 8.7 MiB above where they started in allocated
  bytes; a by-hand probe of one `avro-zstd-1m` run found the file's own bytes 0.14 MB
  larger and its allocated blocks 5.6 MiB beyond its length right after the rewrite, so
  the difference is APFS's allocation of a freshly written file, not data.

Updated against the Avro section: the 1 MiB file's ratio is reachable a row at a time,
if the rows may wait in memory for their block; the buffered-write cost is durability,
not speed.

## RocksDB

RocksDB is an embedded log-structured key-value store: writes go to a write-ahead log
and an in-memory table, which is flushed to sorted files that background compactions
merge level by level, each file a sequence of compressed blocks. It is measured here as
one more option on every axis above.

**The binding.** `rocksdict` 0.3.29, pinned in the two scripts' PEP 723 headers only,
ships a Python 3.14 wheel for macOS arm64 that bundles RocksDB 9.8.4 and zstd 1.5.7; every
store's `LOG` header names RocksDB 9.8.4. python-rocksdb, the binding RocksDB's site
links to, was archived in June 2025, has had no release since 2019 and ships no wheels.
Speedb, the RocksDB fork, was dropped: its only binding stops at Python 3.12 and Speedb
has not released since January 2024.

**The setup.** Three stores, every option passed explicitly on every open: block zstd
level 3 at every level, 16 KiB blocks in one 128 MiB LRU cache shared by every column
family (index and filter blocks in it too), 32 MiB memtables capped at 128 MiB in all,
two background jobs, one old info `LOG` kept. The application compresses nothing; the
codec is RocksDB's, block by block.

- `rocksdb-zstd`: three column families keyed by identity: `meta` (compact JSON of the
  metadata columns, 10-bit bloom filter), `html` (no key when the page has no HTML) and
  `markdown`. One `WriteBatch` writes a row across the three atomically.
- `rocksdb-blob`: the same, with both bodies in zstd blob files (values of 4 KiB and up,
  64 MiB files) and blob garbage collection at age cutoff 1.0, so a full compaction
  rewrites every blob file and reclaims every stale blob.
- `rocksdb-packed`: one value per row in the default column family, a header of two
  lengths, then the metadata JSON, the HTML and the Markdown. A scan or a metadata select
  reads and slices every whole row; that is the layout's cost, by design.

Each build writes `WriteBatch`es of 256 rows without syncing, then flushes every column
family, compacts it fully (`compact_range` with bottommost compaction forced) and
closes; the child fails if a write-ahead log of nonzero size is left, and a read-only
reopen counts the rows outside the timed region. That full compaction is the peer of
`VACUUM`: RocksDB normally compacts incrementally in the background, and the full
compaction is what returns a store to its smallest size at a moment of the caller's
choosing. Inserts and upserts run with the log synced on every write (`sync`) and not
(`nosync`). The synced variant is the durability peer of the rollback-journal
`sqlite-zstd` and the unsynced one, durable to a process crash but not to an OS crash,
the peer of SQLite WAL with `synchronous=NORMAL`. They are durability peers, not cost
peers: SQLite under a rollback journal syncs the journal and the database file on every
commit, RocksDB syncs its log once. Neither issues `F_FULLFSYNC`. A by-hand probe on
this disk timed a synced RocksDB write of 30 KB at 0.046 ms, `os.fsync` after the same
write at 0.042 ms and `F_FULLFSYNC` at 3.7 ms; RocksDB's own statistics counted 1,000
log syncs for 1,000 synced writes. The timed write is not the same work either: a RocksDB
write appends to the log and inserts into a memtable, and the compression happens when a
memtable is flushed, on RocksDB's two background threads during the loop or in the
compaction afterwards, which is timed and reported apart; SQLite compresses every body
on the timed thread. The insert and upsert rates below are the rate a caller sees, not
the whole cost of the write. The SQLite upsert stores ran under a rollback journal with
`synchronous=FULL`, so the synced RocksDB upserts are their peers; the unsynced ones have
no measured SQLite peer, since SQLite in WAL mode was not upserted.

Size, bulk built from `sqlite-raw` in rowid order, compacted and closed (the references
below the line are from the formats run and the per-regime section; the dictionary
store's write cost is its build in the formats run, 256-row batches then `VACUUM`):

| variant | files | allocated MiB | allocated/raw | SST MiB | blob MiB | LOG KiB | write s | write peak RSS MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rocksdb-zstd | 23 | 815.7 | 0.184 | 814.8 | 0 | 840 | 25.8 | 922 |
| rocksdb-blob | 25 | 885.1 | 0.200 | 47.5 | 836.7 | 916 | 35.1 | 904 |
| rocksdb-packed | 20 | 768.9 | 0.174 | 768.1 | 0 | 672 | 22.7 | 883 |
| sqlite-zstd-dict | | 763.9 | 0.173 | | | | 26.0 | 713 |
| sqlite-zstd | | 1,026.3 | 0.232 | | | | | |
| duckdb-zstd | | 560.0 | 0.127 | | | | | |

Per regime, allocated over raw bytes, each (regime, store) pair built on its own; the
SQLite and DuckDB columns are the per-regime section's, and the dictionary store was
not built per regime:

| regime | rows | raw MiB | sqlite-zstd | duckdb-zstd | rocksdb-zstd | rocksdb-blob | rocksdb-packed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rust | 62,067 | 835.7 | 0.313 | 0.072 | 0.154 | 0.211 | 0.159 |
| sphinx | 9,703 | 593.1 | 0.195 | 0.094 | 0.172 | 0.177 | 0.157 |
| wikipedia | 30,000 | 1,273.5 | 0.230 | 0.126 | 0.196 | 0.208 | 0.182 |
| commoncrawl | 9,999 | 1,689.6 | 0.196 | 0.170 | 0.191 | 0.192 | 0.176 |
| github | 19,111 | 29.8 | 0.818 | 0.479 | 0.466 | 0.481 | 0.465 |

Reads, warm cache, second of two runs, a fresh process each, with the in-run references:

| variant | query | memory limit | peak RSS MiB | wall s | ms per item | items |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| rocksdb-zstd | point | 128 MiB block cache | 71 | 0.016 | 0.080 | 200 |
| rocksdb-zstd | scan | 128 MiB block cache | 312 | 0.845 | 0.006 | 130,880 |
| rocksdb-zstd | meta | 128 MiB block cache | 118 | 0.225 | 0.002 | 130,880 |
| rocksdb-blob | point | 128 MiB block cache | 61 | 0.018 | 0.092 | 200 |
| rocksdb-blob | scan | 128 MiB block cache | 196 | 0.873 | 0.007 | 130,880 |
| rocksdb-blob | meta | 128 MiB block cache | 118 | 0.219 | 0.002 | 130,880 |
| rocksdb-packed | point | 128 MiB block cache | 67 | 0.014 | 0.068 | 200 |
| rocksdb-packed | scan | 128 MiB block cache | 548 | 2.321 | 0.018 | 130,880 |
| rocksdb-packed | meta | 128 MiB block cache | 546 | 2.262 | 0.017 | 130,880 |
| sqlite-zstd-dict | point | SQLite default | 54 | 0.009 | 0.047 | 200 |
| sqlite-zstd-dict | scan | SQLite default | 72 | 1.104 | 0.008 | 130,880 |
| sqlite-zstd-dict | meta | SQLite default | 52 | 0.180 | 0.001 | 130,880 |
| parquet-zstd | point | 51.1 GiB | 1,395 | 22.839 | 114.19 | 200 |
| parquet-zstd | point | 512MB | failed: out of memory | | | |
| parquet-zstd | scan | 51.1 GiB | 796 | 1.144 | 0.009 | 130,880 |
| parquet-zstd | scan | 488.2 MiB | 797 | 1.096 | 0.008 | 130,880 |
| parquet-zstd | meta | 51.1 GiB | 141 | 0.105 | 0.001 | 130,880 |
| parquet-zstd | meta | 488.2 MiB | 141 | 0.104 | 0.001 | 130,880 |
| duckdb-zstd | point | 51.1 GiB | 545 | 2.462 | 12.31 | 200 |
| duckdb-zstd | point | 488.2 MiB | 545 | 2.441 | 12.20 | 200 |
| duckdb-zstd | scan | 51.1 GiB | 631 | 1.008 | 0.008 | 130,880 |
| duckdb-zstd | scan | 488.2 MiB | 629 | 0.979 | 0.007 | 130,880 |
| duckdb-zstd | meta | 51.1 GiB | 104 | 0.079 | 0.001 | 130,880 |
| duckdb-zstd | meta | 488.2 MiB | 104 | 0.078 | 0.001 | 130,880 |

Insert throughput, one run per cell, a fresh process each; the three SQLite variants run
beside them as in-run references (`sqlite-zstd` is the durability peer of `sync`, the
two WAL variants of `nosync`, and `sqlite-zstd-dict-wal` is the recommendation):

| variant | mode | mix | scenario | rows | rows/s | raw MiB/s | insert s | compact s | peak RSS MiB | MiB before > after inserts > after compaction |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| rocksdb-zstd-sync | single | mixed | empty | 10,000 | 6,911 | 231.7 | 1.45 | 1.20 | 280 | 0.0 > 429.5 > 62.6 |
| rocksdb-zstd-sync | single | mixed | populated | 10,000 | 7,436 | 249.3 | 1.34 | 7.55 | 303 | 310.9 > 767.7 > 372.5 |
| rocksdb-zstd-sync | batch | mixed | empty | 10,000 | 9,986 | 334.8 | 1.00 | 1.30 | 690 | 0.0 > 263.7 > 62.5 |
| rocksdb-zstd-sync | batch | mixed | populated | 10,000 | 10,258 | 343.9 | 0.97 | 8.46 | 702 | 310.9 > 579.1 > 372.5 |
| rocksdb-zstd-sync | single | commoncrawl | empty | 9,999 | 2,001 | 338.1 | 5.00 | 2.99 | 512 | 0.0 > 731.6 > 322.5 |
| rocksdb-zstd-sync | single | commoncrawl | populated | 9,999 | 2,073 | 350.2 | 4.82 | 7.30 | 516 | 205.1 > 2,231.9 > 527.3 |
| rocksdb-zstd-sync | batch | commoncrawl | empty | 9,999 | 2,316 | 391.4 | 4.32 | 3.00 | 996 | 0.0 > 555.8 > 322.4 |
| rocksdb-zstd-sync | batch | commoncrawl | populated | 9,999 | 2,301 | 388.8 | 4.35 | 7.34 | 1,011 | 205.1 > 1,086.9 > 527.2 |
| rocksdb-zstd-nosync (nosync) | single | mixed | empty | 10,000 | 10,045 | 336.8 | 1.00 | 1.24 | 298 | 0.0 > 419.7 > 62.6 |
| rocksdb-zstd-nosync (nosync) | single | mixed | populated | 10,000 | 10,230 | 343.0 | 0.98 | 7.62 | 307 | 310.9 > 756.7 > 372.5 |
| rocksdb-zstd-nosync (nosync) | batch | mixed | empty | 10,000 | 10,529 | 353.0 | 0.95 | 1.29 | 663 | 0.0 > 263.7 > 62.6 |
| rocksdb-zstd-nosync (nosync) | batch | mixed | populated | 10,000 | 10,699 | 358.7 | 0.93 | 8.42 | 679 | 310.9 > 579.1 > 372.5 |
| rocksdb-zstd-nosync (nosync) | single | commoncrawl | empty | 9,999 | 2,271 | 383.7 | 4.40 | 2.94 | 508 | 0.0 > 731.6 > 322.5 |
| rocksdb-zstd-nosync (nosync) | single | commoncrawl | populated | 9,999 | 2,255 | 381.1 | 4.43 | 7.40 | 528 | 205.1 > 2,230.9 > 527.3 |
| rocksdb-zstd-nosync (nosync) | batch | commoncrawl | empty | 9,999 | 2,320 | 392.1 | 4.31 | 3.00 | 1,004 | 0.0 > 555.8 > 322.4 |
| rocksdb-zstd-nosync (nosync) | batch | commoncrawl | populated | 9,999 | 2,331 | 393.8 | 4.29 | 7.29 | 1,010 | 205.1 > 989.7 > 527.2 |
| rocksdb-blob-sync | single | mixed | empty | 10,000 | 6,958 | 233.3 | 1.44 | 1.35 | 267 | 0.0 > 433.6 > 67.6 |
| rocksdb-blob-sync | single | mixed | populated | 10,000 | 7,410 | 248.4 | 1.35 | 9.41 | 270 | 336.4 > 798.4 > 403.6 |
| rocksdb-blob-sync | batch | mixed | empty | 10,000 | 10,235 | 343.2 | 0.98 | 1.45 | 670 | 0.0 > 267.5 > 67.6 |
| rocksdb-blob-sync | batch | mixed | populated | 10,000 | 10,414 | 349.2 | 0.96 | 9.82 | 674 | 336.4 > 608.4 > 403.6 |
| rocksdb-blob-sync | single | commoncrawl | empty | 9,999 | 2,050 | 346.4 | 4.88 | 2.97 | 513 | 0.0 > 734.1 > 324.9 |
| rocksdb-blob-sync | single | commoncrawl | populated | 9,999 | 1,865 | 315.1 | 5.36 | 12.42 | 518 | 232.2 > 2,441.8 > 557.7 |
| rocksdb-blob-sync | batch | commoncrawl | empty | 9,999 | 2,293 | 387.4 | 4.36 | 3.07 | 1,009 | 0.0 > 558.0 > 324.7 |
| rocksdb-blob-sync | batch | commoncrawl | populated | 9,999 | 2,308 | 390.0 | 4.33 | 10.03 | 997 | 232.2 > 1,196.5 > 557.6 |
| rocksdb-blob-nosync (nosync) | single | mixed | empty | 10,000 | 10,207 | 342.2 | 0.98 | 1.38 | 269 | 0.0 > 423.6 > 67.6 |
| rocksdb-blob-nosync (nosync) | single | mixed | populated | 10,000 | 10,228 | 342.9 | 0.98 | 9.53 | 272 | 336.4 > 787.4 > 403.6 |
| rocksdb-blob-nosync (nosync) | batch | mixed | empty | 10,000 | 10,717 | 359.3 | 0.93 | 1.43 | 666 | 0.0 > 267.5 > 67.6 |
| rocksdb-blob-nosync (nosync) | batch | mixed | populated | 10,000 | 10,478 | 351.3 | 0.95 | 9.92 | 670 | 336.4 > 608.4 > 403.6 |
| rocksdb-blob-nosync (nosync) | single | commoncrawl | empty | 9,999 | 2,304 | 389.4 | 4.34 | 2.96 | 511 | 0.0 > 734.1 > 324.9 |
| rocksdb-blob-nosync (nosync) | single | commoncrawl | populated | 9,999 | 1,962 | 331.5 | 5.10 | 11.70 | 540 | 232.2 > 2,274.4 > 557.7 |
| rocksdb-blob-nosync (nosync) | batch | commoncrawl | empty | 9,999 | 2,296 | 388.0 | 4.35 | 3.04 | 1,006 | 0.0 > 558.0 > 324.7 |
| rocksdb-blob-nosync (nosync) | batch | commoncrawl | populated | 9,999 | 2,272 | 383.9 | 4.40 | 10.07 | 1,030 | 232.2 > 1,508.6 > 557.6 |
| rocksdb-packed-sync | single | mixed | empty | 10,000 | 6,858 | 229.9 | 1.46 | 1.14 | 242 | 0.0 > 80.7 > 58.6 |
| rocksdb-packed-sync | single | mixed | populated | 10,000 | 7,442 | 249.5 | 1.34 | 7.07 | 287 | 292.2 > 372.6 > 350.2 |
| rocksdb-packed-sync | batch | mixed | empty | 10,000 | 9,863 | 330.7 | 1.01 | 1.40 | 586 | 0.0 > 89.2 > 58.6 |
| rocksdb-packed-sync | batch | mixed | populated | 10,000 | 9,942 | 333.3 | 1.01 | 7.04 | 599 | 292.2 > 368.3 > 350.2 |
| rocksdb-packed-sync | single | commoncrawl | empty | 9,999 | 2,067 | 349.3 | 4.84 | 2.74 | 471 | 0.0 > 301.1 > 298.0 |
| rocksdb-packed-sync | single | commoncrawl | populated | 9,999 | 2,076 | 350.8 | 4.82 | 7.88 | 523 | 195.4 > 496.3 > 493.2 |
| rocksdb-packed-sync | batch | commoncrawl | empty | 9,999 | 2,304 | 389.3 | 4.34 | 2.75 | 956 | 0.0 > 303.1 > 297.9 |
| rocksdb-packed-sync | batch | commoncrawl | populated | 9,999 | 2,277 | 384.8 | 4.39 | 7.96 | 952 | 195.4 > 498.3 > 493.1 |
| rocksdb-packed-nosync (nosync) | single | mixed | empty | 10,000 | 10,196 | 341.8 | 0.98 | 1.13 | 269 | 0.0 > 80.7 > 58.6 |
| rocksdb-packed-nosync (nosync) | single | mixed | populated | 10,000 | 10,513 | 352.5 | 0.95 | 7.09 | 288 | 292.2 > 372.6 > 350.2 |
| rocksdb-packed-nosync (nosync) | batch | mixed | empty | 10,000 | 10,238 | 343.3 | 0.98 | 1.40 | 587 | 0.0 > 89.2 > 58.6 |
| rocksdb-packed-nosync (nosync) | batch | mixed | populated | 10,000 | 10,297 | 345.2 | 0.97 | 7.11 | 600 | 292.2 > 368.3 > 350.2 |
| rocksdb-packed-nosync (nosync) | single | commoncrawl | empty | 9,999 | 2,235 | 377.7 | 4.47 | 2.74 | 494 | 0.0 > 301.1 > 298.0 |
| rocksdb-packed-nosync (nosync) | single | commoncrawl | populated | 9,999 | 2,318 | 391.7 | 4.31 | 7.84 | 506 | 195.4 > 496.3 > 493.2 |
| rocksdb-packed-nosync (nosync) | batch | commoncrawl | empty | 9,999 | 2,323 | 392.5 | 4.30 | 2.80 | 966 | 0.0 > 303.1 > 297.9 |
| rocksdb-packed-nosync (nosync) | batch | commoncrawl | populated | 9,999 | 2,321 | 392.2 | 4.31 | 7.89 | 950 | 195.4 > 498.3 > 493.1 |
| sqlite-zstd | single | mixed | empty | 10,000 | 2,383 | 79.9 | 4.20 | 0.30 | 179 | 0.0 > 81.0 > 77.9 |
| sqlite-zstd | single | mixed | populated | 10,000 | 2,534 | 85.0 | 3.95 | 1.92 | 179 | 390.0 > 470.0 > 467.9 |
| sqlite-zstd | batch | mixed | empty | 10,000 | 7,219 | 242.0 | 1.39 | 0.25 | 397 | 0.0 > 80.2 > 77.9 |
| sqlite-zstd | batch | mixed | populated | 10,000 | 7,117 | 238.6 | 1.41 | 1.86 | 397 | 390.0 > 470.0 > 467.9 |
| sqlite-zstd | single | commoncrawl | empty | 9,999 | 1,132 | 191.3 | 8.83 | 1.35 | 415 | 0.0 > 336.1 > 331.7 |
| sqlite-zstd | single | commoncrawl | populated | 9,999 | 1,098 | 185.6 | 9.10 | 2.24 | 416 | 287.1 > 623.1 > 618.9 |
| sqlite-zstd | batch | commoncrawl | empty | 9,999 | 1,586 | 268.1 | 6.30 | 1.04 | 605 | 0.0 > 336.6 > 331.7 |
| sqlite-zstd | batch | commoncrawl | populated | 9,999 | 1,604 | 271.1 | 6.23 | 2.14 | 603 | 287.1 > 623.1 > 618.9 |
| sqlite-zstd-wal | single | mixed | empty | 10,000 | 6,350 | 212.9 | 1.57 | 0.21 | 179 | 0.0 > 85.7 > 80.7 |
| sqlite-zstd-wal | single | mixed | populated | 10,000 | 6,411 | 215.0 | 1.56 | 1.61 | 179 | 390.0 > 474.9 > 467.9 |
| sqlite-zstd-wal | batch | mixed | empty | 10,000 | 6,669 | 223.6 | 1.50 | 0.22 | 398 | 0.0 > 90.3 > 80.2 |
| sqlite-zstd-wal | batch | mixed | populated | 10,000 | 6,868 | 230.3 | 1.46 | 1.61 | 398 | 390.0 > 480.3 > 467.9 |
| sqlite-zstd-wal | single | commoncrawl | empty | 9,999 | 1,470 | 248.3 | 6.80 | 1.13 | 420 | 0.0 > 342.4 > 336.3 |
| sqlite-zstd-wal | single | commoncrawl | populated | 9,999 | 1,506 | 254.4 | 6.64 | 1.89 | 416 | 287.1 > 630.3 > 623.1 |
| sqlite-zstd-wal | batch | commoncrawl | empty | 9,999 | 1,537 | 259.7 | 6.51 | 0.89 | 603 | 0.0 > 349.6 > 336.6 |
| sqlite-zstd-wal | batch | commoncrawl | populated | 9,999 | 1,517 | 256.3 | 6.59 | 1.79 | 602 | 287.1 > 636.2 > 623.1 |
| sqlite-zstd-dict-wal | single | mixed | empty | 10,000 | 5,805 | 194.6 | 1.72 | 0.16 | 190 | 0.0 > 64.0 > 59.0 |
| sqlite-zstd-dict-wal | single | mixed | populated | 10,000 | 6,096 | 204.4 | 1.64 | 1.22 | 190 | 290.4 > 359.4 > 348.2 |
| sqlite-zstd-dict-wal | batch | mixed | empty | 10,000 | 6,361 | 213.3 | 1.57 | 0.17 | 419 | 0.0 > 68.8 > 59.1 |
| sqlite-zstd-dict-wal | batch | mixed | populated | 10,000 | 6,591 | 221.0 | 1.52 | 1.34 | 417 | 290.4 > 363.6 > 354.4 |
| sqlite-zstd-dict-wal | single | commoncrawl | empty | 9,999 | 1,325 | 223.9 | 7.54 | 0.98 | 426 | 0.0 > 327.2 > 320.2 |
| sqlite-zstd-dict-wal | single | commoncrawl | populated | 9,999 | 1,328 | 224.5 | 7.53 | 1.53 | 418 | 188.3 > 513.4 > 508.3 |
| sqlite-zstd-dict-wal | batch | commoncrawl | empty | 9,999 | 1,344 | 227.1 | 7.44 | 0.88 | 600 | 0.0 > 333.1 > 320.7 |
| sqlite-zstd-dict-wal | batch | commoncrawl | populated | 9,999 | 1,327 | 224.3 | 7.53 | 1.42 | 600 | 188.3 > 520.9 > 508.3 |

Upserts, 500 rows one write each, second of two runs (the first in brackets):

| variant | ms per row | compaction s | peak RSS MiB | MiB before > after upserts > after compaction | compaction |
| --- | ---: | ---: | ---: | --- | --- |
| sqlite-zstd | 0.81 (0.78) | 4.2 (4.3) | 101 | 1,026.3 > 1,042.3 > 1,026.3 | VACUUM |
| sqlite-zstd-dict | 1.83 (1.84) | 3.3 (3.2) | 116 | 763.9 > 779.9 > 763.9 | VACUUM |
| rocksdb-zstd-sync | 0.14 (0.15) | 15.1 (15.1) | 212 | 815.7 > 831.6 > 815.1 | flush, then compact_range with bottommost force |
| rocksdb-zstd-nosync | 0.10 (0.10) | 15.0 (15.2) | 211 | 815.7 > 831.6 > 815.1 | flush, then compact_range with bottommost force |
| rocksdb-blob-sync | 0.16 (0.14) | 16.3 (16.3) | 181 | 884.2 > 900.1 > 884.5 | flush, then compact_range with bottommost force; blob GC at cutoff 1.0 rewrites every blob file |
| rocksdb-blob-nosync | 0.10 (0.10) | 16.2 (16.4) | 178 | 884.2 > 900.1 > 884.5 | flush, then compact_range with bottommost force; blob GC at cutoff 1.0 rewrites every blob file |
| rocksdb-packed-sync | 0.13 (0.13) | 14.3 (14.2) | 268 | 768.9 > 785.2 > 768.3 | flush, then compact_range with bottommost force |
| rocksdb-packed-nosync | 0.09 (0.10) | 14.1 (14.1) | 267 | 768.9 > 785.2 > 768.3 | flush, then compact_range with bottommost force |

Every build wrote and counted 130,880 rows (each regime build its own rows and raw
bytes, as `sizes.json` has them) and left no write-ahead log; every insert child found
the row count grown by exactly the rows inserted and no log left after compaction; every
upsert child found 130,880 rows and all 500 changed Markdown bodies after compaction.

What the tables say:

- **On disk RocksDB lands with the dictionary store, not with the column stores.**
  Packed into one value per row it is 0.174 of raw against 0.173 for the dictionary
  store; in three column families 0.184; with blob files 0.200, still under plain
  per-row zstd (0.232). A 16 KiB block holds several small pages and compresses them
  together, so RocksDB gains most on short pages (Rust: 0.154 against 0.313 for per-row
  zstd) and least on large ones, which fill a block alone (Common Crawl: 0.176 to 0.192
  against 0.196); blob files compress each body on its own and give that gain back.
  DuckDB's whole-segment compression stays ahead on every regime but GitHub, by most on
  Rust and Sphinx (0.072 and 0.094).
  Written a row at a time it keeps its ratio once compacted: 10,000 mixed rows land at
  0.175 to 0.202 after the full compaction, the dictionary store at 0.176 after
  `VACUUM`.
- **It is the fastest writer measured, as the caller sees it.** Unsynced it outruns
  buffered Avro, and synced it outruns every store that makes each write durable, with
  its compression left to background threads and the compaction. Synced per write it takes 6,858
  to 7,442 single-row inserts a second on mixed rows, against 2,383 to 2,534 for its
  durability peer `sqlite-zstd` and 5,805 to 6,096 for the dictionary store in WAL mode;
  unsynced, 10,045 to 10,513, against 6,350 to 6,411 for `sqlite-zstd-wal`. On Common
  Crawl rows it takes 1,865 to 2,318 a second, against 1,325 to 1,328 for the dictionary
  store. A 500-row upsert synced per write costs 0.13 to 0.16 ms a row, against 0.81 for
  `sqlite-zstd` and 1.83 for the dictionary store, both under a rollback journal with
  `synchronous=FULL`; unsynced it costs 0.09 to 0.10 ms. Why the dictionary store upserts
  at twice plain zstd's time was not looked into. (The dictionary store took 1.84 and 1.83 ms in this
  run's two upsert runs, so the 0.79 ms of its first run in the gaps section was the
  outlier, not the 1.88.)
- **It pays in memory, in transient disk and in compaction.** Every RocksDB process
  carries a 128 MiB block cache and up to 128 MiB of memtables by design. Point lookups
  stay small (61 to 71 MiB, 0.07 to 0.09 ms, against 54 MiB and 0.047 ms), but the scan
  peaks at 196 to 312 MiB in the column-family layouts and 548 MiB packed, against 72
  for the dictionary store; a by-hand rerun of the `rocksdb-zstd` and `rocksdb-packed`
  scans found the block cache at 120 MiB at the end, inside its cap, so the rest of
  those peaks is outside the cache. The packed
  layout reads every whole row for a scan or a metadata select: 2.3 s at 546 to 548 MiB.
  Bulk builds peaked at 883 to 922 MiB (the dictionary store's: 713 MiB), 256-row batches of Common Crawl pages at 950 to
  1,030 MiB (SQLite: 600 to 605), single-row inserts of them at 471 to 540 MiB (SQLite: 415 to 426). Before
  compaction the column-family stores held up to 2,442 MiB for 9,999 Common Crawl rows
  of 1,690 MiB raw into a base of 205 to 232 MiB, while the packed store held 498 MiB; this is
  consistent with RocksDB keeping a log file until every column family whose writes it
  holds has flushed, which the small `meta` family rarely does, but the files were not
  broken down. A full compaction rewrote the whole store: 14.1 to 16.4 s after 500
  upserts, against 3.2 to 4.3 s for `VACUUM`, and 7.0 to 12.4 s after 10,000 inserts
  into a 50,000-row base, against 1.2 to 2.2 s.

Updated against the gaps section: RocksDB is the only option that beats the dictionary
store on writes and upserts at its disk ratio with every write durable and lookups in
the same tenth of a millisecond (buffered Avro writes faster than the synced RocksDB
store, at a better ratio, but loses its buffered rows on a crash and looks up in
0.74 ms); it trades a single file and SQLite's small footprint for a directory of
about twenty files, a quarter-gigabyte of configured caches, a full compaction about
four times as long as `VACUUM` and a binding outside the standard library.

## Verdict

**On disk, yes. In memory while querying, no.**

DuckDB with ZSTD forced on the body columns stores this corpus in 12.7% of its raw size,
against 23.2% for SQLite with per-row zstd at level 3 and 103% for raw SQLite: about half
the disk of the best SQLite store, and the gap is widest where it matters for a
documentation mirror, on pages that share chrome (Sphinx: 9% against 20%) and on short
Markdown (Rust: 7% against 31%). That is the column store compressing a whole segment
with one context where per-row zstd sees one page at a time.

The same segment is what the queries pay for. Every query shape used more memory under
DuckDB, from about twice (the metadata select) to ten times (the scan) and eighteen
times (the upserts); point lookups were two hundred times slower per page,
and single-row upserts, the shape a crawler writes in, took 1.5 GB of RSS and grew the
file by 30% at checkpoint. The temporary store's working set is point lookups and
single-row writes with an occasional scan, and SQLite with per-row zstd served every one
of them in under 92 MiB (raw SQLite in under 139 MiB).

RocksDB, measured last, does not change that answer. Its block compression sees a few
pages at a time, so it lands with the dictionary SQLite store on disk (0.174 to 0.200),
not with DuckDB (0.127); it writes faster than SQLite and looks a page up in 0.07 to
0.09 ms against SQLite's 0.047, at more memory.

## Caveats

- **Compression is per segment and lands at `CHECKPOINT`.** A DuckDB row group holds
  122,880 rows, so this corpus is two row groups; a smaller store gets one, and the
  2,000-page tracer-bullet run (`build_corpus.py --sources rust --limit 2000`, then
  `load_stores.py`) measured 0.42 (default) and 0.13 (forced ZSTD) against 0.33 for
  per-row zstd. Rows inserted since the last checkpoint sit uncompressed in the
  WAL until one runs, and a mirror that writes a page at a time pays for that in the
  upsert rows above.
- **The default compression has a string-length cliff.** Below an average of 4,096
  bytes per value DuckDB does not consider ZSTD, so short Markdown stays uncompressed
  unless the column forces it. A real store should declare `USING COMPRESSION ZSTD` on
  both body columns or lower `zstd_min_string_length`.
- **DuckDB's ZSTD level is its own.** SQLite's per-row zstd ran at level 3; DuckDB does
  not expose the level it compresses segments with, so the two ZSTD rows differ in more
  than the unit of compression.
- **Warm cache, one machine.** Every query ran twice in a row in fresh processes and the
  second run is reported; the files were in the page cache. Memory is the child's own
  peak RSS (`ru_maxrss`, bytes on macOS), which includes the Python interpreter and the
  imported libraries: the `baseline` row is a child that imports them and does nothing.
- **DuckDB threads.** DuckDB ran with its default 18 threads; SQLite is single-threaded.
  The memory limit column is what DuckDB reports; in the query runs SQLite ran at its
  default 2 MB page cache and its default rollback journal, not WAL mode. The insert
  runs add the two WAL variants.
- **Insert cells ran once, and the fsync is APFS's.** The spread between the empty and
  populated cells of one (variant, mode, mix), which should agree, is the best guide to
  the noise: under 10% for every SQLite and files cell, up to 20% for DuckDB. On macOS
  `fsync()` does not flush the drive's write cache (`F_FULLFSYNC` does, and SQLite does
  not use it by default), so `synchronous=FULL` and `NORMAL` both measure the cost of
  the journal and the call, not of durable writes; the files store syncs only the
  manifest. The rows came from a warm sample file and their JSON parsing sat inside the
  timed loop for every variant alike. DuckDB's `executemany` is the only batch path
  measured; its Appender and Arrow ingestion, the bulk paths it documents, were not, so
  the DuckDB batch cells are a floor on what it can do when fed in bulk.
- **The corpus is not a crawl.** The Rust and Wikipedia pages have no site chrome and
  the Sphinx archives are one generator's output; only the Common Crawl regime looks
  like fetched pages. The Wikipedia run is from March 2025, twenty months old, chosen as
  a sample of article markup, not as current content. The Markdown comes from one
  throwaway converter and a different converter would change every Markdown ratio.
- **Loading was not measured fairly.** The loader is a prototype: DuckDB ingested the
  corpus from the JSON file in one statement and the loader process peaked at 13.8 GB
  RSS doing so, while SQLite was fed in batches of 256 rows from Python. Bulk ingestion
  memory is a separate question from the one asked here; row-at-a-time ingestion is the
  insert section.
- **The Avro index is a sidecar and DuckDB's Avro lookups are a sample.** The format
  defines no index; the sidecar SQLite file is this prototype's, and a different design
  (an index block appended to the file, a footer) would change the numbers. DuckDB point
  lookups on Avro ran 5 identities, not 200, because each reads the whole file; compare
  them per item. The DuckDB extension's zstd support was established on this build only
  (`345c3f4e82`), from the files written here and a by-hand 20-row probe of its writer.
- **RocksDB is one configuration.** The cache and memtable sizes, the 16 KiB blocks
  and the forced full compaction are this prototype's choices; RocksDB normally
  compacts in the background and the full compaction stands in for `VACUUM`. Its peak
  RSS beyond the 128 MiB block cache, and the transient disk of the column-family
  layouts before compaction, were observed, not broken down. A shared zstd dictionary
  for RocksDB's blocks (`max_dict_bytes`) was not run. Its write and upsert rates leave
  out the compression its background threads and the compaction do, and the
  recommended WAL SQLite store was not upserted beside it. The binding is a third party's
  (`rocksdict`); the one RocksDB's site links to is archived.
- **No concurrency.** One writer and no readers at a time; the mirror's real access
  pattern (a crawler writing while a converter reads) was not exercised.
- **The columnar files were written from the DuckDB store and read with literals.**
  Each write cost includes reading `stores/duckdb-zstd` and, for the sorted variants,
  sorting 4.4 GB in DuckDB, so the write RSS is DuckDB's, not the format's. Point
  lookups through DuckDB inline the identity as a literal, so the filter is a constant at
  planning; a prepared parameter may plan differently. Vortex's index layout is not
  exposed to DuckDB or Python, so only its zone maps and file statistics were exercised,
  and its plans report no pruning counters. The 512 MB memory limit governs DuckDB's
  buffer pool only: the Vortex and Lance extensions read through their own allocators
  and ignored it. The Lance BTREE index was built after the fact on an APFS clone; the
  Lance scan's use of it was inferred from the lookup time and memory, not from the plan.

## Recommendation

For the temporary page store, use **SQLite with per-row zstd on the two body columns**
(level 3 measured; the level is a tuning knob). It costs about twice the disk of DuckDB
(1.0 GB against 0.56 GB for 4.4 GB of raw bodies) and in return keeps every query shape
under 92 MiB and serves single-row writes and point lookups at SQLite speed, which is
the access pattern a crawl has. The insert measurements leave that in place and add WAL
mode: SQLite with per-row zstd under `journal_mode=WAL` and `synchronous=NORMAL` takes
6,000 single-row inserts a second on typical pages (200 MiB/s) at under 180 MiB of RSS,
as fast as batching, while DuckDB written a row at a time is five times slower and loses
the disk advantage that was its case (0.57 of raw against 0.23). The columnar files do
not change the choice: Parquet matches DuckDB's disk but a point lookup reads a whole
column chunk (116 ms and 1.4 GB, failing under 512 MB), Vortex is three and a half
times Parquet on disk, and Lance with a BTREE index is the best lookup DuckDB can offer
(1.1 ms at 123 MiB) at 0.21 of raw, still twenty times SQLite's time and three times its
memory. Avro read through DuckDB is worse than all of them (a whole-file read per lookup,
failing under 512 MB); read through fastavro with a sidecar index it looks up in under a
millisecond and, in 1 MiB zstd blocks, matches DuckDB's disk, but only as an append-only
log whose blocks must be batched to stay small. What does move is the SQLite store itself: a zstd dictionary trained per regime
and column takes it from 0.232 to 0.173 of raw at no measurable query cost, so the
recommended store is **SQLite with per-row zstd against a per-host (here per-regime)
dictionary, in WAL mode**. A later decision record can cite these numbers directly.

The gaps section measured the alternative the Avro section left standing, Avro with zstd in 1 MiB
blocks and a sidecar index, as a store a crawler writes: buffered into blocks it takes
8,000 single-row writes a second and lands at 0.130 of raw, against about 6,000 and
0.176 for the dictionary store; it upserts as fast; and it gives up per-row durability,
in-place reclaim (a compaction rewrites the whole file, 11 s for this one, against a
3.4 s `VACUUM`), lookups (0.74 ms against 0.05), the metadata select (1.9 s against
0.2) and a single file with transactions. Avro wins only where disk is the binding
constraint, losing up to a block of pages on a crash is acceptable because they can be
fetched again, one process owns the files, and old versions can wait for a periodic
rewrite. None of that holds for the temporary store as specified, so the recommendation
stands.

The RocksDB section measured the candidate closest to the dictionary store. At the same
disk (0.174 packed into one value per row, 0.184 in three column families, against
0.173) it writes faster (6,858 to 7,442 single-row inserts a second synced per write,
10,045 to 10,513 unsynced, against 5,805 to 6,096 for the dictionary store in WAL mode),
upserts faster (0.13 to 0.16 ms a row synced against 1.83 under a rollback journal; the
recommended WAL configuration was not upserted), with its compression left to background
threads and the compaction, and looks a page up in
0.07 to 0.09 ms against 0.047. It pays in memory by configuration (a 128 MiB block
cache and up to 128 MiB of memtables per process; scans at 196 to 548 MiB against 72,
bulk loads at 883 to 922 MiB against 713 and 256-row batches of large pages near 1 GiB), in transient disk (up to
2,442 MiB before compaction for 1,690 MiB of Common Crawl rows written into a base of
205 to 232 MiB, in the column-family layouts), in a full compaction about four times as long as
`VACUUM` (14 to 16 s after 500 upserts), and in operability: a directory of about twenty
files, a tuning surface of a dozen options, and a binding outside the standard library.
The recommendation stands, because what RocksDB adds is write and upsert speed beyond
what the temporary store needs: the dictionary store already commits about 6,000
single-row writes a second, which by judgement, not measurement, is well above the rate
a crawler fetching over the network produces pages. RocksDB wins where writes and
refetch upserts arrive faster than SQLite can take them, a quarter-gigabyte per process
is affordable, and a directory of files with its own compaction is acceptable; packed
into one value per row if the reads are lookups, in column families if scans and
metadata selects matter too.

Four follow-ups are worth measuring if disk or write rate becomes the constraint:

- The dictionary's scope and size: one per regime and column at 128 KiB was measured;
  per host, per crawl, larger, or retrained as a host's chrome changes were not, and the
  gain on Sphinx-like chrome should be larger than the corpus average.
- Avro with zstd in 1 MiB blocks and a sidecar index (0.128 of raw bulk-written, 0.130
  buffered a row at a time, 0.74 ms lookups at 70 MiB through fastavro, never through
  DuckDB) as an append-only log, with pages buffered into blocks before each append and
  old versions reclaimed by a whole-file rewrite. The gaps section measured both; what
  is left is the crash consistency of the file and its index, a log-structured store
  built by hand, and the dictionary SQLite store gets within 0.05 of its disk without
  one.
- RocksDB with a zstd dictionary shared by its blocks (`max_dict_bytes`, with
  `zstd_max_train_bytes`), the RocksDB counterpart of the dictionary store, and with
  `max_total_wal_size` bounding the column-family layouts' log before compaction.
- Parquet with zstd as an append-once archive of raw HTML written in bulk after a run
  and read by scans, where its compression (0.124 of raw, the same as DuckDB's) is the
  whole point and its lookup cost does not apply. That is a different store from the
  temporary one, not a replacement for it.

If DuckDB is ever used for bodies, declare `USING COMPRESSION ZSTD` on the body columns
or lower `zstd_min_string_length`; the default leaves Markdown under 4 KB uncompressed.
