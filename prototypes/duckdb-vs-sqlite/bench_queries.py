# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = [
#   "duckdb==2.0.0",
#   "zstandard==0.25.0",
# ]
# ///
"""PROTOTYPE, throwaway: peak memory and wall time of four query shapes on every store.

For each store `load_stores.py` built, each query shape and each memory setting, the
parent spawns a fresh child process (this same script with `--child`) that runs the query
and prints one JSON line: its own peak RSS (`ru_maxrss`, bytes on macOS), wall time and
what it found. The parent never reads the children's aggregate usage. Every measurement
runs twice in a row and the second run is kept, so the page cache is warm; the table says
so. Upserts run on a copy of the store, which is deleted afterwards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import duckdb
import zstandard
from load_stores import COLUMNS, META_COLUMNS, RESULTS, STORES, ZSTD_LEVEL, tree_bytes

POINT_LOOKUPS = 200
UPSERTS = 500
FETCH_MANY = 256
DUCKDB_LIMIT = "512MB"
QUERIES = ["point", "scan", "meta", "upsert"]
SETTINGS = {
    "files": ["default"],
    "sqlite-raw": ["default"],
    "sqlite-zstd": ["default"],
    "duckdb-default": ["default", DUCKDB_LIMIT],
    "duckdb-zstd": ["default", DUCKDB_LIMIT],
}
IDS_FILE = RESULTS / "bench-ids.json"
UPSERTS_FILE = RESULTS / "bench-upserts.jsonl"
META_SQL = f"SELECT {', '.join(META_COLUMNS)} FROM pages"  # noqa: S608  fixed column names
COLUMN_LIST = ", ".join(COLUMNS)
PLACEHOLDERS = ", ".join("?" * len(COLUMNS))


def digest(data: bytes | str) -> None:
    """Touch every byte of a body, as a consumer would, without keeping it."""
    hashlib.sha256(data.encode() if isinstance(data, str) else data).digest()


def store_bytes(target: Path) -> int:
    """Allocated bytes of a store directory, WAL and journal files included."""
    return tree_bytes(target)[1]


def upsert_rows() -> list[dict[str, Any]]:
    """The rows the parent prepared for the upsert measurement."""
    with UPSERTS_FILE.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


# -------------------------------------------------------------- children ---


def files_upsert(target: Path, manifest: Path) -> int:
    """Write each body atomically and append its manifest line, one fsync per row."""
    items = 0
    with manifest.open("a", encoding="utf-8") as out:
        for page in upsert_rows():
            directory = target / page["regime"] / "upsert"
            directory.mkdir(parents=True, exist_ok=True)
            stem = directory / page["content_digest"][:16]
            for suffix, body in ((".html", page["html"]), (".md", page["markdown"])):
                if body is None:
                    continue
                partial = stem.with_suffix(suffix + ".part")
                partial.write_text(body, encoding="utf-8")
                partial.rename(stem.with_suffix(suffix))
            meta = {c: page[c] for c in META_COLUMNS}
            meta["path"] = stem.relative_to(target).as_posix()
            out.write(json.dumps(meta, ensure_ascii=False) + "\n")
            out.flush()
            os.fsync(out.fileno())
            items += 1
    return items


def files_child(target: Path, query: str) -> dict[str, Any]:
    """The plain-files store: a manifest of JSON lines beside one file per body."""
    manifest = target / "manifest.jsonl"
    items = 0
    if query == "point":
        index = {}
        with manifest.open(encoding="utf-8") as handle:
            for line in handle:
                meta = json.loads(line)
                index[meta["identity"]] = meta["path"]
        for identity in json.loads(IDS_FILE.read_text()):
            stem = target / index[identity]
            html = stem.with_suffix(".html")
            if html.exists():
                digest(html.read_bytes())
            digest(stem.with_suffix(".md").read_bytes())
            items += 1
    elif query == "scan":
        with manifest.open(encoding="utf-8") as handle:
            for line in handle:
                digest((target / json.loads(line)["path"]).with_suffix(".md").read_bytes())
                items += 1
    elif query == "meta":
        with manifest.open(encoding="utf-8") as handle:
            for line in handle:
                json.loads(line)
                items += 1
    else:
        items = files_upsert(target, manifest)
    return {"items": items}


def sqlite_upsert(
    target: Path, connection: sqlite3.Connection, *, zstd: bool
) -> tuple[int, dict[str, Any]]:
    """One transaction per row, then the sizes before, after the rows and after VACUUM."""
    compressor = zstandard.ZstdCompressor(level=ZSTD_LEVEL) if zstd else None
    assignments = ", ".join(f"{c} = excluded.{c}" for c in COLUMNS if c != "identity")
    sql = (
        f"INSERT INTO pages ({COLUMN_LIST}) VALUES ({PLACEHOLDERS})"  # noqa: S608  fixed column names
        f" ON CONFLICT(identity) DO UPDATE SET {assignments}"
    )
    extra: dict[str, Any] = {"size_before": store_bytes(target)}
    items = 0
    for page in upsert_rows():
        values = []
        for column in COLUMNS:
            value = page[column]
            if column in {"html", "markdown"} and compressor is not None and value is not None:
                value = compressor.compress(value.encode())
            values.append(value)
        with connection:
            connection.execute(sql, values)
        items += 1
    extra["size_after_upserts"] = store_bytes(target)
    connection.execute("VACUUM")
    connection.close()
    extra["size_after_compaction"] = store_bytes(target)
    return items, extra


def sqlite_child(target: Path, query: str, *, zstd: bool) -> dict[str, Any]:
    """SQLite with TEXT bodies or per-row zstd BLOBs, default cache_size and journal mode."""
    connection = sqlite3.connect(target / "pages.sqlite")
    decompressor = zstandard.ZstdDecompressor() if zstd else None

    def body(value: bytes | str | None) -> bytes | str:
        if value is None:
            return b""
        return decompressor.decompress(value) if decompressor is not None else value  # type: ignore[arg-type]  BLOB

    items = 0
    extra: dict[str, Any] = {}
    if query == "point":
        for identity in json.loads(IDS_FILE.read_text()):
            row = connection.execute(
                "SELECT html, markdown FROM pages WHERE identity = ?", (identity,)
            ).fetchone()
            digest(body(row[0]))
            digest(body(row[1]))
            items += 1
    elif query == "scan":
        for (markdown,) in connection.execute("SELECT markdown FROM pages"):
            digest(body(markdown))
            items += 1
    elif query == "meta":
        for _ in connection.execute(META_SQL):
            items += 1
    else:
        items, extra = sqlite_upsert(target, connection, zstd=zstd)
    connection.close()
    return {"items": items, **extra}


def duckdb_upsert(
    target: Path, connection: duckdb.DuckDBPyConnection
) -> tuple[int, dict[str, Any]]:
    """One transaction per row, then the sizes before, after the rows and after CHECKPOINT."""
    sql = f"INSERT OR REPLACE INTO pages ({COLUMN_LIST}) VALUES ({PLACEHOLDERS})"  # noqa: S608  fixed column names
    extra: dict[str, Any] = {"size_before": store_bytes(target)}
    items = 0
    for page in upsert_rows():
        connection.execute("BEGIN TRANSACTION")
        connection.execute(sql, [page[c] for c in COLUMNS])
        connection.execute("COMMIT")
        items += 1
    extra["size_after_upserts"] = store_bytes(target)
    connection.execute("CHECKPOINT")
    connection.close()
    extra["size_after_compaction"] = store_bytes(target)
    return items, extra


def duckdb_child(target: Path, query: str, setting: str) -> dict[str, Any]:
    """DuckDB, default or capped memory limit, streaming fetches."""
    connection = duckdb.connect(str(target / "pages.duckdb"))
    if setting != "default":
        connection.execute(f"SET memory_limit = '{setting}'")
    limit = connection.execute("SELECT current_setting('memory_limit')").fetchone()
    threads = connection.execute("SELECT current_setting('threads')").fetchone()
    extra: dict[str, Any] = {
        "memory_limit": limit[0] if limit else None,
        "threads": threads[0] if threads else None,
    }
    items = 0
    if query == "point":
        for identity in json.loads(IDS_FILE.read_text()):
            row = connection.execute(
                "SELECT html, markdown FROM pages WHERE identity = ?", [identity]
            ).fetchone()
            if row is not None:
                digest(row[0] or "")
                digest(row[1])
            items += 1
    elif query in {"scan", "meta"}:
        cursor = connection.execute("SELECT markdown FROM pages" if query == "scan" else META_SQL)
        while batch := cursor.fetchmany(FETCH_MANY):
            if query == "scan":
                for (markdown,) in batch:
                    digest(markdown)
            items += len(batch)
    else:
        items, found = duckdb_upsert(target, connection)
        extra.update(found)
    connection.close()
    return {"items": items, **extra}


def child(store: str, query: str, setting: str, target: Path) -> None:
    """Run one measurement and print its JSON line."""
    started = time.perf_counter()
    if store == "baseline":
        found: dict[str, Any] = {"items": 0}
    elif store == "files":
        found = files_child(target, query)
    elif store.startswith("sqlite"):
        found = sqlite_child(target, query, zstd=store.endswith("zstd"))
    else:
        found = duckdb_child(target, query, setting)
    wall = time.perf_counter() - started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS
    report = {"store": store, "query": query, "setting": setting, "rss_bytes": rss, "wall_s": wall}
    print(json.dumps({**report, **found}))


# ---------------------------------------------------------------- parent ---


def prepare() -> None:
    """Pick the identities to look up and the rows to upsert, from the raw SQLite store."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(STORES / "sqlite-raw" / "pages.sqlite")
    (count,) = connection.execute("SELECT count(*) FROM pages").fetchone()
    stride = max(1, count // POINT_LOOKUPS)
    picked = connection.execute(
        "SELECT identity FROM pages WHERE (rowid - 1) % ? = 0 ORDER BY rowid LIMIT ?",
        (stride, POINT_LOOKUPS),
    ).fetchall()
    IDS_FILE.write_text(json.dumps([row[0] for row in picked]))
    stride = max(1, count // UPSERTS)
    with UPSERTS_FILE.open("w", encoding="utf-8") as out:
        for row in connection.execute(
            f"SELECT {COLUMN_LIST} FROM pages WHERE (rowid - 1) % ? = 1 ORDER BY rowid LIMIT ?",  # noqa: S608  fixed column names
            (stride, UPSERTS),
        ):
            page = dict(zip(COLUMNS, row, strict=True))
            page["markdown"] = page["markdown"] + "\n\nupserted by the benchmark\n"
            page["markdown_bytes"] = len(page["markdown"].encode())
            page["content_digest"] = hashlib.sha256(page["markdown"].encode()).hexdigest()
            out.write(json.dumps(page, ensure_ascii=False) + "\n")
    connection.close()
    print(
        f"prepared {len(picked)} lookups and {UPSERTS} upserts from {count} rows", file=sys.stderr
    )


def measure(store: str, query: str, setting: str) -> dict[str, Any]:
    """Run one (store, query, setting) twice in fresh children and keep the second run."""
    result: dict[str, Any] = {}
    for _ in range(2):
        target = STORES / store
        if query == "upsert" and store != "baseline":
            target = STORES / f"{store}-upsert-PROTOTYPE-wipe-me"
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(STORES / store, target)
        completed = subprocess.run(
            [sys.executable, __file__, "--child", store, query, setting, str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        if target != STORES / store:
            shutil.rmtree(target, ignore_errors=True)
    summary = f"{result['rss_bytes'] / 2**20:.0f} MiB, {result['wall_s']:.2f} s"
    print(f"{store} {query} {setting}: {summary}", file=sys.stderr)
    return result


def print_table(results: list[dict[str, Any]]) -> None:
    """One Markdown table, warm cache."""
    print("\nQuery memory and wall time, warm cache")
    print("(second of two consecutive runs, a fresh process for each)\n")
    print(
        "| store | query | memory limit | peak RSS MiB | wall s | items |"
        " MiB before > after upserts > after compaction |"
    )
    print("| --- | --- | --- | ---: | ---: | ---: | --- |")
    for r in results:
        limit = r.get("memory_limit") or (
            "n/a" if r["store"] in {"files", "baseline"} else "sqlite default"
        )
        sizes = ""
        if "size_before" in r:
            keys = ("size_before", "size_after_upserts", "size_after_compaction")
            sizes = " > ".join(f"{r[k] / 2**20:.1f}" for k in keys)
        print(
            f"| {r['store']} | {r['query']} | {limit} | {r['rss_bytes'] / 2**20:.1f}"
            f" | {r['wall_s']:.3f} | {r['items']} | {sizes} |"
        )


def main() -> None:
    """Parent: prepare, measure every combination, print the table, save the JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", nargs=4, metavar=("STORE", "QUERY", "SETTING", "TARGET"))
    args = parser.parse_args()
    if args.child:
        store, query, setting, target = args.child
        child(store, query, setting, Path(target))
        return
    if not (STORES / "sqlite-raw" / "pages.sqlite").exists():
        sys.exit(f"no stores under {STORES}; run load_stores.py first")
    prepare()
    results = [measure("baseline", "none", "default")]
    results += [
        measure(store, query, setting)
        for store, settings in SETTINGS.items()
        for query in QUERIES
        for setting in settings
    ]
    print_table(results)
    (RESULTS / "queries.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nsaved {RESULTS / 'queries.json'}")


if __name__ == "__main__":
    main()
