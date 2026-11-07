# 03: Query memory and throughput

**What to build:** one command measures, for every store and each of four query shapes,
the peak resident set size and the wall time of the query, and prints one table. Each
measurement runs in a fresh subprocess, which reports its own peak RSS (`ru_maxrss` of
the child, bytes on macOS) and wall time as one JSON line on stdout; the parent never
reads the children's aggregate usage, which on macOS is the maximum over every child it
has waited for. The cache is warm and the output says so.

The four query shapes are: point lookup by identity; a full scan of every Markdown body
that iterates rows and hashes each body, never materialising the whole result; a
metadata-only select; and an upsert of one row at a time, run as N single-row
transactions. The upsert measurement also reports on-disk size before and after
`CHECKPOINT` or `VACUUM`. DuckDB scans use a streaming fetch so the number is the store's
memory, not Python's.

DuckDB defaults its memory limit to a large share of RAM and SQLite's page cache to
about 2 MB, so each DuckDB query runs twice, once at the default and once under
`SET memory_limit = '512MB'`; SQLite runs at its default cache size. The limit in force
is a column of the table.

**Blocked by:** 01 (Tracer bullet on local data). Independent of 02.

**Status:** done

- [x] `uv run prototypes/duckdb-vs-sqlite/bench_queries.py` on the ticket-01 corpus prints
  one row per (store, query shape, memory setting) with peak RSS, wall time and the
  memory limit in force, labelled warm cache
- [x] The upsert rows report on-disk size before and after compaction
- [x] Results are also saved as JSON under `ai_tmp/duckdb-vs-sqlite/results/`
- [x] `just check` is green
