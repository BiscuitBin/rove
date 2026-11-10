# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = [
#   "duckdb==2.0.0",
#   "zstandard==0.25.0",
# ]
# ///
"""PROTOTYPE, throwaway: load the corpus into every store and print the size table.

Reads `ai_tmp/duckdb-vs-sqlite/corpus.jsonl` and builds, under
`ai_tmp/duckdb-vs-sqlite/stores/` (wiped first), the plain-files store, SQLite with raw
TEXT, SQLite with per-row zstd BLOBs, DuckDB with its default column compression and
DuckDB with zstd forced on the two body columns. Each store is compacted (VACUUM or
CHECKPOINT) and closed before it is measured.

With `--per-regime`, each (regime, store) pair is then built on its own into a scratch
directory, measured and deleted, so the per-regime table reports exact on-disk bytes
without doubling the disk the overall stores take.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import zstandard

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT / "ai_tmp" / "duckdb-vs-sqlite"
CORPUS = SCRATCH / "corpus.jsonl"
STORES = SCRATCH / "stores"
RESULTS = SCRATCH / "results"

ZSTD_LEVEL = 3
COLUMNS = [
    "identity",
    "source_url",
    "regime",
    "title",
    "raw_digest",
    "content_digest",
    "fetched_at",
    "html",
    "markdown",
    "html_bytes",
    "markdown_bytes",
]
META_COLUMNS = [c for c in COLUMNS if c not in {"html", "markdown"}]
SQLITE_BATCH = 256
DUCKDB_TYPES = {
    "identity": "VARCHAR",
    "source_url": "VARCHAR",
    "regime": "VARCHAR",
    "title": "VARCHAR",
    "raw_digest": "VARCHAR",
    "content_digest": "VARCHAR",
    "fetched_at": "VARCHAR",
    "html": "VARCHAR",
    "markdown": "VARCHAR",
    "html_bytes": "BIGINT",
    "markdown_bytes": "BIGINT",
}


def rows(corpus: Path, regime: str | None = None) -> Iterator[dict[str, Any]]:
    """Stream the corpus one page at a time, optionally one regime only."""
    with corpus.open(encoding="utf-8") as handle:
        for line in handle:
            if regime is not None and f'"regime": "{regime}"' not in line:
                continue
            page = json.loads(line)
            if regime is None or page["regime"] == regime:
                yield page


def tree_bytes(path: Path) -> tuple[int, int]:
    """Apparent and allocated bytes of a file or a tree (APFS allocates 4 KB blocks)."""
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    stats = [p.stat() for p in files]
    return sum(s.st_size for s in stats), sum(s.st_blocks * 512 for s in stats)


# ---------------------------------------------------------------- stores ---


def load_files(corpus: Path, target: Path, regime: str | None) -> str:
    """One HTML file and one Markdown file per page, plus a JSON-lines manifest."""
    target.mkdir(parents=True)
    with (target / "manifest.jsonl").open("w", encoding="utf-8") as manifest:
        for n, page in enumerate(rows(corpus, regime)):
            directory = target / page["regime"] / f"{n // 1000:04d}"
            directory.mkdir(parents=True, exist_ok=True)
            stem = page["content_digest"][:16]
            if page["html"] is not None:
                (directory / f"{stem}.html").write_text(page["html"], encoding="utf-8")
            (directory / f"{stem}.md").write_text(page["markdown"], encoding="utf-8")
            meta = {c: page[c] for c in META_COLUMNS}
            meta["path"] = (directory / stem).relative_to(target).as_posix()
            manifest.write(json.dumps(meta, ensure_ascii=False) + "\n")
    return "manifest.jsonl + <regime>/<n>/<digest>.html|.md"


def sqlite_schema(body_type: str) -> str:
    """The shared schema with the two body columns as TEXT or BLOB."""
    return (
        "CREATE TABLE pages ("
        "identity TEXT PRIMARY KEY, source_url TEXT, regime TEXT, title TEXT,"
        " raw_digest TEXT, content_digest TEXT, fetched_at TEXT,"
        f" html {body_type}, markdown {body_type}, html_bytes INTEGER, markdown_bytes INTEGER)"
    )


def load_sqlite(corpus: Path, target: Path, regime: str | None, *, zstd: bool) -> str:
    """SQLite, raw TEXT bodies or per-row zstd BLOBs, then VACUUM."""
    target.mkdir(parents=True)
    compressor = zstandard.ZstdCompressor(level=ZSTD_LEVEL) if zstd else None
    connection = sqlite3.connect(target / "pages.sqlite")
    connection.execute(sqlite_schema("BLOB" if zstd else "TEXT"))
    placeholders = ",".join("?" * len(COLUMNS))
    insert = f"INSERT INTO pages ({','.join(COLUMNS)}) VALUES ({placeholders})"  # noqa: S608  fixed column names
    batch: list[tuple[Any, ...]] = []

    def body(text: str | None) -> bytes | str | None:
        if text is None or compressor is None:
            return text
        return compressor.compress(text.encode())

    for page in rows(corpus, regime):
        values = tuple(body(page[c]) if c in {"html", "markdown"} else page[c] for c in COLUMNS)
        batch.append(values)
        if len(batch) >= SQLITE_BATCH:
            connection.executemany(insert, batch)
            batch.clear()
    if batch:
        connection.executemany(insert, batch)
    connection.commit()
    connection.execute("VACUUM")
    connection.close()
    return f"per-row zstd level {ZSTD_LEVEL}, BLOB" if zstd else "TEXT, no compression"


def load_duckdb(corpus: Path, target: Path, regime: str | None, *, zstd: bool) -> str:
    """DuckDB VARCHAR, default compression or zstd forced on the bodies, then CHECKPOINT."""
    target.mkdir(parents=True)
    connection = duckdb.connect(str(target / "pages.duckdb"))
    columns = []
    for name, kind in DUCKDB_TYPES.items():
        forced = " USING COMPRESSION ZSTD" if zstd and name in {"html", "markdown"} else ""
        key = " PRIMARY KEY" if name == "identity" else ""
        columns.append(f"{name} {kind}{forced}{key}")
    connection.execute(f"CREATE TABLE pages ({', '.join(columns)})")
    json_columns = ", ".join(f"{name}: '{kind}'" for name, kind in DUCKDB_TYPES.items())
    where = " WHERE regime = ?" if regime is not None else ""
    connection.execute(
        f"INSERT INTO pages SELECT * FROM read_ndjson(?, columns = {{{json_columns}}},"  # noqa: S608  fixed column names
        f" maximum_object_size = 268435456){where}",
        [str(corpus)] + ([regime] if regime is not None else []),
    )
    connection.execute("CHECKPOINT")
    chosen = connection.execute(
        "SELECT column_name, compression, count(*) FROM pragma_storage_info('pages')"
        " WHERE column_name IN ('html', 'markdown') GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    connection.close()
    wal = target / "pages.duckdb.wal"
    if wal.exists():
        msg = f"WAL still present after CHECKPOINT: {wal}"
        raise RuntimeError(msg)
    summary = "; ".join(f"{col} {comp} x{n}" for col, comp, n in chosen)
    return f"segments: {summary}"


LOADERS: dict[str, Callable[[Path, Path, str | None], str]] = {
    "files": load_files,
    "sqlite-raw": lambda c, t, r: load_sqlite(c, t, r, zstd=False),
    "sqlite-zstd": lambda c, t, r: load_sqlite(c, t, r, zstd=True),
    "duckdb-default": lambda c, t, r: load_duckdb(c, t, r, zstd=False),
    "duckdb-zstd": lambda c, t, r: load_duckdb(c, t, r, zstd=True),
}


# ----------------------------------------------------------------- report ---


def raw_totals(corpus: Path) -> dict[str, tuple[int, int]]:
    """Row count and raw body bytes (HTML plus Markdown) per regime, plus "all"."""
    totals: dict[str, tuple[int, int]] = {}
    for page in rows(corpus):
        for key in ("all", page["regime"]):
            count, raw = totals.get(key, (0, 0))
            totals[key] = (count + 1, raw + page["html_bytes"] + page["markdown_bytes"])
    return totals


def load_one(
    corpus: Path, target: Path, name: str, regime: str | None, raw: tuple[int, int]
) -> dict[str, Any]:
    """Build one store into `target` and measure it."""
    note = LOADERS[name](corpus, target, regime)
    apparent, allocated = tree_bytes(target)
    count, raw_bytes = raw
    return {
        "store": name,
        "regime": regime or "all",
        "rows": count,
        "raw_bytes": raw_bytes,
        "apparent_bytes": apparent,
        "allocated_bytes": allocated,
        "ratio": allocated / raw_bytes if raw_bytes else 0.0,
        "note": note,
    }


def load_all(corpus: Path, stores_dir: Path, *, per_regime: bool) -> list[dict[str, Any]]:
    """Wipe and rebuild every store from the corpus; return one record per (store, regime)."""
    shutil.rmtree(stores_dir, ignore_errors=True)
    stores_dir.mkdir(parents=True)
    totals = raw_totals(corpus)
    records: list[dict[str, Any]] = []
    for name in LOADERS:
        records.append(load_one(corpus, stores_dir / name, name, None, totals["all"]))
        print(f"loaded {name}: {records[-1]['allocated_bytes'] / 2**20:.1f} MiB", file=sys.stderr)
    if per_regime:
        scratch = stores_dir / "per-regime-PROTOTYPE-wipe-me"
        for regime in sorted(k for k in totals if k != "all"):
            for name in LOADERS:
                shutil.rmtree(scratch, ignore_errors=True)
                records.append(load_one(corpus, scratch, name, regime, totals[regime]))
                print(
                    f"loaded {regime}/{name}: {records[-1]['allocated_bytes'] / 2**20:.1f} MiB",
                    file=sys.stderr,
                )
        shutil.rmtree(scratch, ignore_errors=True)
    return records


def print_table(records: list[dict[str, Any]], title: str) -> None:
    """A Markdown table of the size records."""
    print(f"\n{title}\n")
    print(
        "| regime | store | rows | raw MiB | apparent MiB | allocated MiB | allocated/raw | note |"
    )
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |")
    for r in records:
        print(
            f"| {r['regime']} | {r['store']} | {r['rows']} | {r['raw_bytes'] / 2**20:.1f}"
            f" | {r['apparent_bytes'] / 2**20:.1f} | {r['allocated_bytes'] / 2**20:.1f}"
            f" | {r['ratio']:.3f} | {r['note']} |"
        )


def main() -> None:
    """Load every store and print the size table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-regime", action="store_true", help="also size each regime alone")
    args = parser.parse_args()
    if not CORPUS.exists():
        sys.exit(f"no corpus at {CORPUS}; run build_corpus.py first")
    records = load_all(CORPUS, STORES, per_regime=args.per_regime)
    n = records[0]["rows"]
    title = f"Store sizes, {n} rows (zstd level {ZSTD_LEVEL}, duckdb {duckdb.__version__})"
    print_table([r for r in records if r["regime"] == "all"], title)
    if args.per_regime:
        print_table([r for r in records if r["regime"] != "all"], "Store sizes per regime")
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "sizes.json").write_text(json.dumps(records, indent=2) + "\n")
    print(f"\nsaved {RESULTS / 'sizes.json'}")


if __name__ == "__main__":
    main()
