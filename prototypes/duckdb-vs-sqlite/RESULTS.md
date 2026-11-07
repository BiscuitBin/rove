# Results: DuckDB against SQLite as the temporary page store

Measured on 2026-11-06 with the three commands below, on an Apple M5 Pro (18 cores, 64 GB)
running macOS 26.4 on APFS, Python 3.14.8, duckdb 2.0.0, zstandard 0.25.0 and SQLite
3.53.1 as bundled with that Python. Every number on this page comes from one run of the
three commands below, except the tracer-bullet figures named in the first caveat:

```sh
uv run prototypes/duckdb-vs-sqlite/build_corpus.py --sources rust,sphinx,wikipedia,commoncrawl,github
uv run prototypes/duckdb-vs-sqlite/load_stores.py --per-regime
uv run prototypes/duckdb-vs-sqlite/bench_queries.py
```

The raw output of the second and third commands is kept beside the data, under
`ai_tmp/duckdb-vs-sqlite/results/` (`sizes.json`, `queries.json`), which is gitignored.

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
  The memory limit column is what DuckDB reports; SQLite ran at its default 2 MB page
  cache and its default rollback journal, not WAL mode.
- **The corpus is not a crawl.** The Rust and Wikipedia pages have no site chrome and
  the Sphinx archives are one generator's output; only the Common Crawl regime looks
  like fetched pages. The Wikipedia run is from March 2025, twenty months old, chosen as
  a sample of article markup, not as current content. The Markdown comes from one
  throwaway converter and a different converter would change every Markdown ratio.
- **Loading was not measured fairly.** The loader is a prototype: DuckDB ingested the
  corpus from the JSON file in one statement and the loader process peaked at 13.8 GB
  RSS doing so, while SQLite was fed in batches of 256 rows from Python. Bulk ingestion
  memory is a separate question from the one asked here.
- **No concurrency.** One writer and no readers at a time; the mirror's real access
  pattern (a crawler writing while a converter reads) was not exercised.

## Recommendation

For the temporary page store, use **SQLite with per-row zstd on the two body columns**
(level 3 measured; the level is a tuning knob). It costs about twice the disk of DuckDB
(1.0 GB against 0.56 GB for 4.4 GB of raw bodies) and in return keeps every query shape
under 92 MiB and serves single-row writes and point lookups at SQLite speed, which is
the access pattern a crawl has. A later decision record can cite these numbers directly.

Two follow-ups are worth measuring if disk becomes the constraint:

- A zstd dictionary trained per host (or per crawl) for SQLite's per-row compression,
  which recovers some of the shared-chrome win DuckDB gets for free; the `zstandard`
  package supports it and nothing here measured it.
- DuckDB as an append-once archive of raw HTML written in bulk after a run and read by
  scans, where its compression is the whole point and its write and lookup costs do not
  apply. That is a different store from the temporary one, not a replacement for it.

If DuckDB is ever used for bodies, declare `USING COMPRESSION ZSTD` on the body columns
or lower `zstd_min_string_length`; the default leaves Markdown under 4 KB uncompressed.
