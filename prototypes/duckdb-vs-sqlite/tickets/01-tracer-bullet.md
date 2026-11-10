# 01: Tracer bullet on local data

**What to build:** one command builds a corpus of about two thousand pages from the Rust
documentation already installed under rustup (no download), loads it into every store
under `ai_tmp/duckdb-vs-sqlite/`, compacts each store (`VACUUM` for SQLite, `CHECKPOINT`
for DuckDB) and prints a size table with one row per store. The DuckDB rows report the
compression DuckDB chose per column, read from its storage information. The files row
reports both apparent bytes and allocated bytes, because APFS allocates in 4 KB blocks
and many Rust pages are about 4 KB. The sample is spread across the whole documentation
tree (a deterministic stride over the sorted file list), so `core/`, `std/` and the books
all appear.

The builder also prints its HTML to Markdown conversion rate in pages per second on this
sample, because converting about 110k pages is the schedule risk for ticket 02, which
picks its converter and its caps from that number.

The stores compared are plain files with a manifest, SQLite with raw `TEXT` columns,
SQLite with per-row zstd `BLOB` columns (level 3, recorded in the output), DuckDB
`VARCHAR` with its default column compression, and, because duckdb 2.0.0 accepts
`USING COMPRESSION ZSTD` on a column (verified against that release), DuckDB with forced
zstd as the direct counterpart of SQLite with zstd.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] `uv run prototypes/duckdb-vs-sqlite/build_corpus.py --sources rust --limit 2000` writes
  the corpus under `ai_tmp/duckdb-vs-sqlite/` with one row per page in the shared schema
  and prints the conversion rate
- [x] `uv run prototypes/duckdb-vs-sqlite/load_stores.py` prints a table with five rows
  (files, SQLite raw, SQLite zstd, DuckDB default, DuckDB zstd), the zstd level and
  DuckDB's per-column compression
- [x] Rerunning either command wipes and rebuilds its outputs
- [x] `ruff.toml` carries a `prototypes/**` per-file-ignores block, one commented line per
  rule, and `just check` is green
- [x] The README states the question, the five sources, and that a full build needs
  roughly 17 GB under `ai_tmp/duckdb-vs-sqlite/`
