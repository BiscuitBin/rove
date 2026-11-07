# Results: DuckDB against SQLite as the temporary page store

Measured on 2026-11-06 with the four commands below, on an Apple M5 Pro (18 cores, 64 GB)
running macOS 26.4 on APFS, Python 3.14.8, duckdb 2.0.0, zstandard 0.25.0 and SQLite
3.53.1 as bundled with that Python. Every number on this page comes from one run of the
four commands below, except the tracer-bullet figures named in the first caveat:

```sh
uv run prototypes/duckdb-vs-sqlite/build_corpus.py --sources rust,sphinx,wikipedia,commoncrawl,github
uv run prototypes/duckdb-vs-sqlite/load_stores.py --per-regime
uv run prototypes/duckdb-vs-sqlite/bench_queries.py
uv run prototypes/duckdb-vs-sqlite/bench_inserts.py
```

The raw output of the last three commands is kept beside the data, under
`ai_tmp/duckdb-vs-sqlite/results/` (`sizes.json`, `queries.json`, `inserts.json`), which
is gitignored.

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
  SQLite's bytes. A probe (one more 10,000-row batch build of each, inspected with
  `pragma_storage_info` and `pragma_database_size`) showed one ZSTD segment per body
  column in both, so the compression did run; but after `CHECKPOINT` more than half of
  each file is free blocks (`duckdb-default`: 437 blocks of 256 KiB, 188 in use;
  `duckdb-zstd`: 724, 373 in use), and the forced-ZSTD store's blocks in use are twice
  the default's (93 MiB against 47 MiB) for the same segment layout. The file grows at
  `CHECKPOINT` (82 to 112 MiB and 124 to 192 MiB on the empty-store batch runs) the way
  the upsert rows grew: blocks are rewritten and the old ones kept free for reuse, and
  DuckDB has no `VACUUM`, so the file never shrinks. Why forced ZSTD holds twice the live
  blocks of the default was not inspected.

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
- **No concurrency.** One writer and no readers at a time; the mirror's real access
  pattern (a crawler writing while a converter reads) was not exercised.

## Recommendation

For the temporary page store, use **SQLite with per-row zstd on the two body columns**
(level 3 measured; the level is a tuning knob). It costs about twice the disk of DuckDB
(1.0 GB against 0.56 GB for 4.4 GB of raw bodies) and in return keeps every query shape
under 92 MiB and serves single-row writes and point lookups at SQLite speed, which is
the access pattern a crawl has. The insert measurements leave that in place and add WAL
mode: SQLite with per-row zstd under `journal_mode=WAL` and `synchronous=NORMAL` takes
6,000 single-row inserts a second on typical pages (200 MiB/s) at under 180 MiB of RSS,
as fast as batching, while DuckDB written a row at a time is five times slower and loses
the disk advantage that was its case (0.57 of raw against 0.23). A later decision record
can cite these numbers directly.

Two follow-ups are worth measuring if disk becomes the constraint:

- A zstd dictionary trained per host (or per crawl) for SQLite's per-row compression,
  which recovers some of the shared-chrome win DuckDB gets for free; the `zstandard`
  package supports it and nothing here measured it.
- DuckDB as an append-once archive of raw HTML written in bulk after a run and read by
  scans, where its compression is the whole point and its write and lookup costs do not
  apply. That is a different store from the temporary one, not a replacement for it.

If DuckDB is ever used for bodies, declare `USING COMPRESSION ZSTD` on the body columns
or lower `zstd_min_string_length`; the default leaves Markdown under 4 KB uncompressed.
