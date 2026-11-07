# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = [
#   "duckdb==2.0.0",
#   "zstandard==0.25.0",
# ]
# ///
"""PROTOTYPE, throwaway: columnar file formats through DuckDB, and a dictionary-zstd SQLite.

Builds, from the stores `load_stores.py` made, nine more: Parquet (zstd level 3; default
row groups; 2,048-row groups with bloom filters on `identity`; the same sorted by
identity), Vortex (default; sorted by identity; sorted and split into 64 files), Lance
(default; with a BTREE index on `identity`) and SQLite with per-row zstd BLOBs compressed
against a dictionary trained per (regime, column). Each build runs in a fresh child that
reports its wall time and peak RSS, then the parent measures the allocated bytes. The
three read shapes of `bench_queries.py` (point lookup, Markdown scan, metadata select)
then run on every new store and on the `sqlite-zstd` and `duckdb-zstd` references, each
in a fresh child, twice, keeping the second (warm cache); DuckDB-read stores run at the
default memory limit and under 512 MB. One `EXPLAIN ANALYZE` of a point lookup per
DuckDB-read store is saved beside the results. The vortex and lance extensions are
installed into `ai_tmp/duckdb-vs-sqlite/extensions/` (network, once).
"""

from __future__ import annotations

import argparse
import json
import resource
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import zstandard
from bench_queries import DUCKDB_LIMIT, FETCH_MANY, META_SQL, POINT_LOOKUPS, digest, store_bytes
from load_stores import COLUMNS, META_COLUMNS, RESULTS, SCRATCH, STORES, ZSTD_LEVEL, sqlite_schema

if TYPE_CHECKING:
    from collections.abc import Callable

DUCKDB_SOURCE = STORES / "duckdb-zstd" / "pages.duckdb"
SQLITE_SOURCE = STORES / "sqlite-raw" / "pages.sqlite"
FORMATS = SCRATCH / "formats"
EXTENSIONS = SCRATCH / "extensions"
IDS_FILE = RESULTS / "formats-ids.json"
EXPLAIN_DIR = RESULTS / "formats-explain"
NEW_VARIANTS = [
    "parquet-zstd",
    "parquet-zstd-rg2k",
    "parquet-zstd-rg2k-sorted",
    "vortex",
    "vortex-sorted",
    "vortex-split",
    "lance",
    "lance-btree",
    "sqlite-zstd-dict",
]
REFERENCES = ["sqlite-zstd", "duckdb-zstd"]
QUERIES = ["point", "scan", "meta"]
BUCKETS = 64
ROW_GROUP = 2048
DICT_SIZE = 131072
DICT_SAMPLES = 1000
SQLITE_BATCH = 256
PARQUET = "FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 3"
PARQUET_SMALL = f"{PARQUET}, ROW_GROUP_SIZE {ROW_GROUP}, DICTIONARY_SIZE_LIMIT {ROW_GROUP}"
COLUMN_LIST = ", ".join(COLUMNS)
BODY_COLUMNS = {"html", "markdown"}


def family(variant: str) -> str:
    """The format family of a variant: parquet, vortex, lance, sqlite or duckdb."""
    return variant.split("-", maxsplit=1)[0]


def target_of(variant: str) -> Path:
    """Where a variant lives: the existing store for a reference, `formats/` otherwise."""
    return STORES / variant if variant in REFERENCES else FORMATS / variant


def source_sql(variant: str, target: Path) -> str:
    """The FROM clause that reads a DuckDB-read variant."""
    if family(variant) == "parquet":
        return f"read_parquet('{target / 'pages.parquet'}')"
    if variant == "vortex-split":
        return f"read_vortex('{target / 'pages'}/**/*.vortex', hive_partitioning = true)"
    if family(variant) == "vortex":
        return f"read_vortex('{target / 'pages.vortex'}')"
    if family(variant) == "lance":
        return f"'{target / 'pages.lance'}'"
    return "pages"


def connect(variant: str, target: Path, setting: str = "default") -> duckdb.DuckDBPyConnection:
    """A DuckDB connection with the extension directory, the extension and the limit set."""
    database = str(target / "pages.duckdb") if variant == "duckdb-zstd" else ":memory:"
    connection = duckdb.connect(database)
    connection.execute(f"SET extension_directory = '{EXTENSIONS}'")
    if family(variant) in {"vortex", "lance"}:
        connection.execute(f"LOAD {family(variant)}")
    if setting != "default":
        connection.execute(f"SET memory_limit = '{setting}'")
    return connection


def literal(text: str) -> str:
    """A single-quoted SQL literal, so the filter is a constant at planning time."""
    return "'" + text.replace("'", "''") + "'"


# ---------------------------------------------------------------- builds ---


def attach_source(connection: duckdb.DuckDBPyConnection, rows: int | None) -> None:
    """Expose the duckdb-zstd store, or its first `rows` rows, as the view `pages`."""
    connection.execute(f"ATTACH '{DUCKDB_SOURCE}' AS src (READ_ONLY)")
    limit = f" LIMIT {rows}" if rows else ""
    connection.execute(f"CREATE VIEW pages AS SELECT * FROM src.pages{limit}")  # noqa: S608  fixed limit


def parquet_note(connection: duckdb.DuckDBPyConnection, path: Path) -> str:
    """Row groups and bloom filters on `identity`, from the file's own metadata."""
    groups, blooms, chunks = connection.execute(
        "SELECT count(DISTINCT row_group_id),"
        " count(*) FILTER (WHERE path_in_schema = 'identity' AND bloom_filter_offset IS NOT NULL),"
        " count(*) FILTER (WHERE path_in_schema = 'identity')"
        " FROM parquet_metadata(?)",
        [str(path)],
    ).fetchone() or (0, 0, 0)
    return f"{groups} row groups; bloom filter on identity in {blooms}/{chunks} chunks"


def build_parquet(variant: str, target: Path, rows: int | None) -> str:
    """One Parquet file; the rg2k variants have small row groups and dictionary-coded identity."""
    connection = connect(variant, target)
    attach_source(connection, rows)
    options = PARQUET if variant == "parquet-zstd" else PARQUET_SMALL
    order = " ORDER BY identity" if variant.endswith("sorted") else ""
    path = target / "pages.parquet"
    connection.execute(f"COPY (SELECT * FROM pages{order}) TO '{path}' ({options})")  # noqa: S608  fixed options
    note = parquet_note(connection, path)
    connection.close()
    return note


def build_vortex(variant: str, target: Path, rows: int | None) -> str:
    """One Vortex file, or 64 hive-partitioned files over identity for the split variant."""
    connection = connect(variant, target)
    attach_source(connection, rows)
    if variant == "vortex-split":
        connection.execute(
            f"COPY (SELECT *, ntile({BUCKETS}) OVER (ORDER BY identity) AS bucket FROM pages)"  # noqa: S608  fixed bucket count
            f" TO '{target / 'pages'}' (FORMAT vortex, PARTITION_BY (bucket))"
        )
        files = len(list((target / "pages").rglob("*.vortex")))
        note = f"{files} files, hive-partitioned by ntile({BUCKETS}) over identity"
    else:
        order = " ORDER BY identity" if variant == "vortex-sorted" else ""
        connection.execute(
            f"COPY (SELECT * FROM pages{order}) TO '{target / 'pages.vortex'}' (FORMAT vortex)"  # noqa: S608  fixed order
        )
        note = "1 file, sorted by identity" if order else "1 file, store order"
    connection.close()
    return note


def build_lance(variant: str, target: Path, rows: int | None) -> str:
    """A Lance dataset; the btree variant clones the plain one and adds the index."""
    dataset = target / "pages.lance"
    connection = connect(variant, target)
    if variant == "lance-btree":
        subprocess.run(
            ["cp", "-Rc", str(FORMATS / "lance" / "pages.lance"), str(dataset)], check=True
        )
        connection.execute(f"CREATE INDEX identity_idx ON '{dataset}' (identity) USING BTREE")
    else:
        attach_source(connection, rows)
        connection.execute(
            f"COPY (SELECT * FROM pages) TO '{dataset}' (FORMAT lance, mode 'overwrite')"  # noqa: S608  fixed path
        )
    indexes = connection.execute(f"SHOW INDEXES ON '{dataset}'").fetchall()
    connection.close()
    files = len(list((dataset / "data").glob("*.lance")))
    return f"{files} data files; indexes: {[row[0] for row in indexes] or 'none'}"


def train_dictionaries(connection: sqlite3.Connection) -> dict[tuple[str, str], bytes]:
    """One zstd dictionary per (regime, column), trained on DICT_SAMPLES bodies by stride."""
    dictionaries: dict[tuple[str, str], bytes] = {}
    for regime, count in connection.execute("SELECT regime, count(*) FROM pages GROUP BY regime"):
        stride = max(1, count // DICT_SAMPLES)
        for column in sorted(BODY_COLUMNS):
            samples = [
                row[0].encode()
                for row in connection.execute(
                    f"SELECT {column} FROM pages WHERE regime = ? AND {column} IS NOT NULL"  # noqa: S608  fixed column names
                    " AND (rowid - 1) % ? = 0 LIMIT ?",
                    (regime, stride, DICT_SAMPLES),
                )
            ]
            if len(samples) < DICT_SAMPLES // 10:
                continue
            trained = zstandard.train_dictionary(DICT_SIZE, samples, level=ZSTD_LEVEL)
            dictionaries[regime, column] = trained.as_bytes()
    return dictionaries


def build_sqlite_dict(variant: str, target: Path, rows: int | None) -> str:
    """SQLite, per-row zstd BLOBs against a per-(regime, column) dictionary, then VACUUM."""
    source = sqlite3.connect(f"file:{SQLITE_SOURCE}?mode=ro", uri=True)
    dictionaries = train_dictionaries(source)
    compressors = {
        key: zstandard.ZstdCompressor(
            level=ZSTD_LEVEL, dict_data=zstandard.ZstdCompressionDict(data)
        )
        for key, data in dictionaries.items()
    }
    connection = sqlite3.connect(target / "pages.sqlite")
    connection.execute(sqlite_schema("BLOB"))
    connection.execute(
        "CREATE TABLE dictionaries (regime TEXT, column TEXT, data BLOB,"
        " PRIMARY KEY (regime, column))"
    )
    connection.executemany(
        "INSERT INTO dictionaries VALUES (?, ?, ?)",
        [(r, c, d) for (r, c), d in dictionaries.items()],
    )
    placeholders = ",".join("?" * len(COLUMNS))
    insert = f"INSERT INTO pages ({COLUMN_LIST}) VALUES ({placeholders})"  # noqa: S608  fixed column names
    limit = f" LIMIT {rows}" if rows else ""
    batch: list[tuple[Any, ...]] = []
    for row in source.execute(f"SELECT {COLUMN_LIST} FROM pages ORDER BY rowid{limit}"):  # noqa: S608  fixed column names
        page = dict(zip(COLUMNS, row, strict=True))
        for column in BODY_COLUMNS:
            if page[column] is not None:
                page[column] = compressors[page["regime"], column].compress(page[column].encode())
        batch.append(tuple(page[c] for c in COLUMNS))
        if len(batch) >= SQLITE_BATCH:
            connection.executemany(insert, batch)
            batch.clear()
    if batch:
        connection.executemany(insert, batch)
    connection.commit()
    connection.execute("VACUUM")
    connection.close()
    source.close()
    total = sum(len(d) for d in dictionaries.values())
    return (
        f"{len(dictionaries)} dictionaries, {total / 1024:.0f} KiB, level {ZSTD_LEVEL}, {variant}"
    )


BUILDERS: dict[str, Callable[[str, Path, int | None], str]] = {
    "parquet": build_parquet,
    "vortex": build_vortex,
    "lance": build_lance,
    "sqlite": build_sqlite_dict,
}


def build_child(variant: str, target: Path, rows: int | None) -> None:
    """Build one variant into `target` and print wall, RSS and the layout note."""
    target.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    note = BUILDERS[family(variant)](variant, target, rows)
    wall = time.perf_counter() - started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS
    print(json.dumps({"variant": variant, "wall_s": wall, "rss_bytes": rss, "note": note}))


# --------------------------------------------------------------- queries ---


def duckdb_query(variant: str, query: str, setting: str, target: Path) -> dict[str, Any]:
    """The three read shapes through DuckDB on a file format or the duckdb-zstd store."""
    connection = connect(variant, target, setting)
    source = source_sql(variant, target)
    limit = connection.execute("SELECT current_setting('memory_limit')").fetchone()
    threads = connection.execute("SELECT current_setting('threads')").fetchone()
    items = 0
    if query == "point":
        for identity in json.loads(IDS_FILE.read_text()):
            row = connection.execute(
                f"SELECT html, markdown FROM {source} WHERE identity = {literal(identity)}"  # noqa: S608  fixed column names
            ).fetchone()
            if row is not None:
                digest(row[0] or "")
                digest(row[1])
                items += 1
    else:
        columns = "markdown" if query == "scan" else ", ".join(META_COLUMNS)
        cursor = connection.execute(f"SELECT {columns} FROM {source}")  # noqa: S608  fixed column names
        while batch := cursor.fetchmany(FETCH_MANY):
            if query == "scan":
                for (markdown,) in batch:
                    digest(markdown)
            items += len(batch)
    connection.close()
    return {
        "items": items,
        "memory_limit": limit[0] if limit else None,
        "threads": threads[0] if threads else None,
    }


def sqlite_query(variant: str, query: str, target: Path) -> dict[str, Any]:
    """The three read shapes on sqlite-zstd or sqlite-zstd-dict; dictionaries loaded at open."""
    connection = sqlite3.connect(target / "pages.sqlite")
    decompressors: dict[tuple[str, str], zstandard.ZstdDecompressor] = {}
    if variant == "sqlite-zstd-dict":
        for regime, column, data in connection.execute(
            "SELECT regime, column, data FROM dictionaries"
        ):
            decompressors[regime, column] = zstandard.ZstdDecompressor(
                dict_data=zstandard.ZstdCompressionDict(data)
            )
    plain = zstandard.ZstdDecompressor()

    def body(regime: str, column: str, value: bytes | None) -> bytes:
        if value is None:
            return b""
        return decompressors.get((regime, column), plain).decompress(value)

    items = 0
    if query == "point":
        for identity in json.loads(IDS_FILE.read_text()):
            row = connection.execute(
                "SELECT regime, html, markdown FROM pages WHERE identity = ?", (identity,)
            ).fetchone()
            digest(body(row[0], "html", row[1]))
            digest(body(row[0], "markdown", row[2]))
            items += 1
    elif query == "scan":
        for regime, markdown in connection.execute("SELECT regime, markdown FROM pages"):
            digest(body(regime, "markdown", markdown))
            items += 1
    else:
        for _ in connection.execute(META_SQL):
            items += 1
    connection.close()
    return {"items": items, "memory_limit": None, "threads": None}


def query_child(variant: str, query: str, setting: str, target: Path) -> None:
    """Run one measurement and print its JSON line."""
    started = time.perf_counter()
    if family(variant) == "sqlite":
        found = sqlite_query(variant, query, target)
    else:
        found = duckdb_query(variant, query, setting, target)
    wall = time.perf_counter() - started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS
    report = {
        "variant": variant,
        "query": query,
        "setting": setting,
        "rss_bytes": rss,
        "wall_s": wall,
    }
    print(json.dumps({**report, **found}))


def explain_child(variant: str, target: Path) -> None:
    """Save EXPLAIN ANALYZE of one point lookup, the evidence of what the scan pruned."""
    connection = connect(variant, target)
    identity = json.loads(IDS_FILE.read_text())[0]
    rows = connection.execute(
        f"EXPLAIN ANALYZE SELECT length(html), length(markdown) FROM {source_sql(variant, target)}"  # noqa: S608  fixed column names
        f" WHERE identity = {literal(identity)}"
    ).fetchall()
    connection.close()
    EXPLAIN_DIR.mkdir(parents=True, exist_ok=True)
    out = EXPLAIN_DIR / f"{variant}.txt"
    out.write_text("\n".join(str(row[1]) for row in rows) + "\n")
    print(json.dumps({"variant": variant, "saved": str(out)}))


# ---------------------------------------------------------------- parent ---


def install_extensions() -> None:
    """Install vortex and lance into the scratch extension directory (network, once)."""
    EXTENSIONS.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute(f"SET extension_directory = '{EXTENSIONS}'")
    for name in ("vortex", "lance"):
        (installed,) = connection.execute(
            "SELECT installed FROM duckdb_extensions() WHERE extension_name = ?", [name]
        ).fetchone() or (False,)
        connection.execute(f"INSTALL {name}")
        print(f"extension {name}: {'present' if installed else 'installed'}", file=sys.stderr)
    connection.close()


def prepare(rows: int | None) -> int:
    """Pick the lookup identities as bench_queries does; return the raw bytes of the rows."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(f"file:{SQLITE_SOURCE}?mode=ro", uri=True)
    (count,) = connection.execute("SELECT count(*) FROM pages").fetchone()
    count = min(count, rows) if rows else count
    stride = max(1, count // POINT_LOOKUPS)
    picked = connection.execute(
        "SELECT identity FROM pages WHERE rowid <= ? AND (rowid - 1) % ? = 0"
        " ORDER BY rowid LIMIT ?",
        (count, stride, POINT_LOOKUPS),
    ).fetchall()
    IDS_FILE.write_text(json.dumps([row[0] for row in picked]))
    (raw,) = connection.execute(
        "SELECT sum(html_bytes + markdown_bytes) FROM pages WHERE rowid <= ?", (count,)
    ).fetchone()
    connection.close()
    print(
        f"prepared {len(picked)} lookups over {count} rows, {raw / 2**20:.0f} MiB raw",
        file=sys.stderr,
    )
    return int(raw)


def run_child(args: list[str]) -> dict[str, Any]:
    """Spawn one child and parse its JSON line; a failed child yields its error line."""
    completed = subprocess.run(
        [sys.executable, __file__, "--child", *args], check=False, capture_output=True, text=True
    )
    if completed.returncode != 0:
        lines = [line for line in completed.stderr.splitlines() if "Exception" in line]
        error = (lines or completed.stderr.strip().splitlines() or ["exit"])[-1]
        return {"error": error[:200], "items": 0, "rss_bytes": 0, "wall_s": 0.0}
    return json.loads(completed.stdout.strip().splitlines()[-1])


def build(variant: str, rows: int | None, raw: int) -> dict[str, Any]:
    """Wipe and build one variant in a child; measure it afterwards."""
    target = target_of(variant)
    shutil.rmtree(target, ignore_errors=True)
    found = run_child(["build", variant, str(target), str(rows or 0)])
    if "error" in found:
        sys.exit(f"build of {variant} failed: {found['error']}")
    allocated = store_bytes(target)
    files = sum(1 for p in target.rglob("*") if p.is_file())
    record = {**found, "files": files, "allocated_bytes": allocated, "ratio": allocated / raw}
    print(
        f"built {variant}: {allocated / 2**20:.0f} MiB ({record['ratio']:.3f}),"
        f" {found['wall_s']:.1f} s, {found['rss_bytes'] / 2**20:.0f} MiB; {found['note']}",
        file=sys.stderr,
    )
    return record


def measure(variant: str, query: str, setting: str) -> dict[str, Any]:
    """Run one (variant, query, setting) twice in fresh children and keep the second."""
    target = target_of(variant)
    result: dict[str, Any] = {}
    for _ in range(2):
        result = run_child(["query", variant, query, setting, str(target)])
        if "error" in result:
            break
    result = {"variant": variant, "query": query, "setting": setting, **result}
    result.setdefault("memory_limit", setting if setting != "default" else None)
    result.setdefault("threads", None)
    summary = result.get("error") or (
        f"{result['rss_bytes'] / 2**20:.0f} MiB, {result['wall_s']:.2f} s, {result['items']} items"
    )
    print(f"{variant} {query} {setting}: {summary}", file=sys.stderr)
    return result


def print_tables(sizes: list[dict[str, Any]], queries: list[dict[str, Any]]) -> None:
    """The size table and the query table, Markdown."""
    print("\nColumnar formats and the dictionary store: size and write cost\n")
    print(
        "| variant | files | allocated MiB | allocated/raw | write s | write peak RSS MiB | note |"
    )
    print("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
    for s in sizes:
        print(
            f"| {s['variant']} | {s['files']} | {s['allocated_bytes'] / 2**20:.0f}"
            f" | {s['ratio']:.3f} | {s['wall_s']:.1f} | {s['rss_bytes'] / 2**20:.0f}"
            f" | {s['note']} |"
        )
    print("\nQuery memory and wall time, warm cache (second of two runs, a fresh process each)\n")
    print("| variant | query | memory limit | peak RSS MiB | wall s | ms per item | items |")
    print("| --- | --- | --- | ---: | ---: | ---: | ---: |")
    for q in queries:
        limit = q["memory_limit"] or "SQLite default"
        if "error" in q:
            print(f"| {q['variant']} | {q['query']} | {limit} | failed: {q['error']} | | | |")
            continue
        per_item = q["wall_s"] * 1000 / q["items"] if q["items"] else 0.0
        print(
            f"| {q['variant']} | {q['query']} | {limit} | {q['rss_bytes'] / 2**20:.0f}"
            f" | {q['wall_s']:.3f} | {per_item:.2f} | {q['items']} |"
        )


def main() -> None:
    """Parent: install, prepare, build, measure, explain, print the tables, save the JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", nargs="+", metavar="ARG")
    parser.add_argument("--rows", type=int, help="build from the first N rows only (smoke)")
    args = parser.parse_args()
    if args.child:
        kind, variant, *rest = args.child
        if kind == "build":
            build_child(variant, Path(rest[0]), int(rest[1]) or None)
        elif kind == "query":
            query_child(variant, rest[0], rest[1], Path(rest[2]))
        else:
            explain_child(variant, Path(rest[0]))
        return
    for needed in (DUCKDB_SOURCE, SQLITE_SOURCE, STORES / "sqlite-zstd" / "pages.sqlite"):
        if not needed.exists():
            sys.exit(f"no store at {needed}; run load_stores.py first")
    install_extensions()
    raw = prepare(args.rows)
    FORMATS.mkdir(parents=True, exist_ok=True)
    sizes = [build(variant, args.rows, raw) for variant in NEW_VARIANTS]
    queries = []
    for variant in NEW_VARIANTS + REFERENCES:
        settings = ["default"] if family(variant) == "sqlite" else ["default", DUCKDB_LIMIT]
        queries += [measure(variant, query, setting) for query in QUERIES for setting in settings]
        if family(variant) != "sqlite":
            run_child(["explain", variant, str(target_of(variant))])
    print_tables(sizes, queries)
    suffix = f"-{args.rows}" if args.rows else ""
    out = RESULTS / f"formats{suffix}.json"
    out.write_text(
        json.dumps({"raw_bytes": raw, "sizes": sizes, "queries": queries}, indent=2) + "\n"
    )
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
