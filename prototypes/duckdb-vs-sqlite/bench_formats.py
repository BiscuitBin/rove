# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = [
#   "avro==1.12.2",
#   "duckdb==2.0.0",
#   "fastavro==1.13.1",
#   "rocksdict==0.3.29",
#   "zstandard==0.25.0",
# ]
# ///
"""PROTOTYPE, throwaway: file formats through DuckDB, Apache Avro, a dictionary-zstd SQLite.

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
DuckDB-read store is saved beside the results. The vortex, lance and avro extensions are
installed into `ai_tmp/duckdb-vs-sqlite/extensions/` (network, once).

Six Apache Avro container files join them: one written by DuckDB's `COPY ... (FORMAT
avro)`, four by fastavro (deflate and zstd level 3, each with 16,000-byte and 1 MiB
blocks) and one by the official `avro` package. Each gets a sidecar SQLite index from
identity to (block offset, position in block), built in one pass over the block headers
after the write. Avro stores are read three ways: through DuckDB's `read_avro` at both
limits (a point lookup there reads the whole file, so only every 40th identity is looked
up) and through fastavro, seeking to the indexed block for a lookup. `--only avro`
builds and measures one family against three references and saves `formats-avro.json`.

`--upserts` measures the 500 upserts `bench_queries.py` prepared on four stores
(`sqlite-zstd`, `sqlite-zstd-dict`, `avro-zstd`, `avro-zstd-1m`), each on an APFS clone
in a fresh child, twice, both runs saved: SQLite runs `bench_queries`'s
`INSERT ... ON CONFLICT DO UPDATE` and then `VACUUM`; Avro appends each record as one
block with an fsync, repoints the sidecar index, and compacts by rewriting the file with
only the records the index points to, then rebuilding the index. Each child checks the
row count and the 500 changed Markdown bodies afterwards. It saves `formats-upserts.json`.

Three RocksDB stores (RocksDB 9.8.4 through rocksdict 0.3.29) join them under `--only
rocksdb`: `rocksdb-zstd` keeps three column families keyed by identity (`meta` as compact
JSON, `html`, `markdown`), `rocksdb-blob` adds blob files for the two bodies, and
`rocksdb-packed` packs each row into one value of the default column family. Every
store uses block zstd level 3, 16 KiB blocks in one 128 MiB LRU cache and 32 MiB
memtables capped at 128 MiB in all, and is fully compacted and closed before it is
measured. `--per-regime` then builds each regime of each store on its own, measures it
and deletes it. `--upserts --only rocksdb` runs the upserts on the three stores, synced
and unsynced, with `sqlite-zstd` and `sqlite-zstd-dict` as in-run references, and saves
`formats-upserts-rocksdb.json`.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import re
import resource
import shutil
import sqlite3
import stat
import struct
import subprocess
import sys
import time
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import fastavro
import rocksdict
import zstandard
from bench_queries import (
    DUCKDB_LIMIT,
    FETCH_MANY,
    META_SQL,
    POINT_LOOKUPS,
    digest,
    store_bytes,
    upsert_rows,
)
from load_stores import COLUMNS, META_COLUMNS, RESULTS, SCRATCH, STORES, ZSTD_LEVEL, sqlite_schema

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from typing import BinaryIO

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
    "avro-duckdb",
    "avro-deflate",
    "avro-deflate-1m",
    "avro-zstd",
    "avro-zstd-1m",
    "avro-deflate-pyavro",
    "rocksdb-zstd",
    "rocksdb-blob",
    "rocksdb-packed",
]
REFERENCES = ["sqlite-zstd", "duckdb-zstd"]
ONLY_REFERENCES = ["parquet-zstd", "sqlite-zstd-dict", "duckdb-zstd"]
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
FASTAVRO = "fastavro"
AVRO_LOOKUPS = 5
AVRO_SYNC = 16000
AVRO_BLOCK_1M = 1 << 20
NULLABLE_COLUMNS = {"raw_digest", "html"}
UPSERT_VARIANTS = ["sqlite-zstd", "sqlite-zstd-dict", "avro-zstd", "avro-zstd-1m"]
UPSERT_RUNS = 2
ROCKSDB_VERSION = "9.8.4"
ROCKS_FAMILIES = ["meta", "html", "markdown"]
ROCKS_CACHE = 128 << 20
ROCKS_BLOCK = 16 << 10
ROCKS_WRITE_BUFFER = 32 << 20
ROCKS_DB_WRITE_BUFFER = 128 << 20
ROCKS_JOBS = 2
ROCKS_BLOOM_BITS = 10
ROCKS_ZSTD_WINDOW = -14
ROCKS_MIN_BLOB = 4096
ROCKS_BLOB_FILE = 64 << 20
ROCKS_LIMIT = "128 MiB block cache"
ROCKS_CAPS = "128 MiB block cache; 32 MiB memtables, two per column family, 128 MiB in all"
PACKED_HEADER = struct.Struct(">II")
NO_HTML = 0xFFFFFFFF
DURABILITY = ("sync", "nosync")
ROCKSDB_UPSERTS = [
    "sqlite-zstd",
    "sqlite-zstd-dict",
    *(f"rocksdb-{layout}-{d}" for layout in ("zstd", "blob", "packed") for d in DURABILITY),
]


def avro_type(column: str) -> str | list[str]:
    """The Avro type of a column: long for the sizes, a null union where the corpus has nulls."""
    if column.endswith("_bytes"):
        return "long"
    return ["null", "string"] if column in NULLABLE_COLUMNS else "string"


AVRO_SCHEMA = {
    "type": "record",
    "name": "page",
    "fields": [{"name": c, "type": avro_type(c)} for c in COLUMNS],
}
AVRO_PARSED = fastavro.parse_schema(AVRO_SCHEMA)


def family(variant: str) -> str:
    """The format family of a variant: parquet, vortex, lance, avro, sqlite or duckdb."""
    return variant.split("-", maxsplit=1)[0]


def store_of(variant: str) -> str:
    """The store a variant runs on: a RocksDB upsert variant without its durability suffix."""
    return variant.removesuffix("-sync").removesuffix("-nosync")


def target_of(variant: str) -> Path:
    """Where a variant lives: the existing store for a reference, `formats/` otherwise."""
    store = store_of(variant)
    return STORES / store if store in REFERENCES else FORMATS / store


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
    if family(variant) == "avro":
        return f"read_avro('{target / 'pages.avro'}')"
    return "pages"


def connect(variant: str, target: Path, setting: str = "default") -> duckdb.DuckDBPyConnection:
    """A DuckDB connection with the extension directory, the extension and the limit set."""
    database = str(target / "pages.duckdb") if variant == "duckdb-zstd" else ":memory:"
    connection = duckdb.connect(database)
    connection.execute(f"SET extension_directory = '{EXTENSIONS}'")
    if family(variant) in {"vortex", "lance", "avro"}:
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


def avro_rows(rows: int | None, regime: str | None = None) -> Iterator[dict[str, Any]]:
    """Stream sqlite-raw in rowid order, or its first `rows` rows, one page dict at a time.

    With `regime`, only that regime's rows, still in rowid order.
    """
    source = sqlite3.connect(f"file:{SQLITE_SOURCE}?mode=ro", uri=True)
    where = " WHERE regime = ?" if regime else ""
    limit = f" LIMIT {rows}" if rows else ""
    sql = f"SELECT {COLUMN_LIST} FROM pages{where} ORDER BY rowid{limit}"  # noqa: S608  fixed column names
    try:
        for row in source.execute(sql, (regime,) if regime else ()):
            yield dict(zip(COLUMNS, row, strict=True))
    finally:
        source.close()


def write_fastavro(variant: str, path: Path, rows: int | None) -> str:
    """fastavro, deflate at its default level or zstd level 3, 16,000-byte or 1 MiB blocks."""
    codec = "zstandard" if "zstd" in variant else "deflate"
    level = ZSTD_LEVEL if codec == "zstandard" else None
    sync = AVRO_BLOCK_1M if variant.endswith("-1m") else AVRO_SYNC
    with path.open("wb") as out:
        fastavro.writer(
            out,
            AVRO_PARSED,
            avro_rows(rows),
            codec=codec,
            codec_compression_level=level,
            sync_interval=sync,
        )
    return f"fastavro {codec} level {level or 'default'}, sync {sync} B"


def write_pyavro(path: Path, rows: int | None) -> str:
    """The official avro package, deflate, its default sync interval."""
    import avro.datafile  # noqa: PLC0415  only this builder needs the package
    import avro.io  # noqa: PLC0415  only this builder needs the package
    import avro.schema  # noqa: PLC0415  only this builder needs the package

    schema = avro.schema.parse(json.dumps(AVRO_SCHEMA))
    writer = avro.datafile.DataFileWriter(
        path.open("wb"), avro.io.DatumWriter(), schema, codec="deflate"
    )
    for record in avro_rows(rows):
        writer.append(record)
    writer.close()
    return f"official avro deflate, sync {avro.datafile.SYNC_INTERVAL} B"


def write_duckdb_avro(variant: str, path: Path, rows: int | None) -> str:
    """DuckDB's COPY to Avro, deflate; the writer sets its own block size."""
    connection = connect(variant, path.parent)
    attach_source(connection, rows)
    connection.execute(
        f"COPY (SELECT * FROM pages) TO '{path}' (FORMAT avro, CODEC 'deflate')"  # noqa: S608  fixed path
    )
    connection.close()
    return "DuckDB COPY deflate, writer's own blocks"


def build_avro_index(target: Path) -> str:
    """The sidecar index: identity to (block offset, position in block), one pass."""
    started = time.perf_counter()
    index = sqlite3.connect(target / "pages.index.sqlite")
    index.execute(
        "CREATE TABLE lookup (identity TEXT PRIMARY KEY, block_offset INTEGER, position INTEGER)"
    )
    blocks = records = block_bytes = 0
    with (target / "pages.avro").open("rb") as source:
        for block in fastavro.block_reader(source):
            blocks += 1
            records += block.num_records
            block_bytes += block.size
            index.executemany(
                "INSERT INTO lookup VALUES (?, ?, ?)",
                [(r["identity"], block.offset, n) for n, r in enumerate(block)],
            )
    index.commit()
    index.close()
    took = time.perf_counter() - started
    mib = (target / "pages.index.sqlite").stat().st_size / 2**20
    return (
        f"{blocks} blocks, {records / max(blocks, 1):.1f} rows and"
        f" {block_bytes / max(blocks, 1) / 1024:.0f} KiB per block;"
        f" index {records} rows, {mib:.1f} MiB, {took:.1f} s"
    )


def build_avro(variant: str, target: Path, rows: int | None) -> str:
    """One Avro container file, written by DuckDB, fastavro or the official package; its index."""
    path = target / "pages.avro"
    if variant == "avro-duckdb":
        written = write_duckdb_avro(variant, path, rows)
    elif variant.endswith("-pyavro"):
        written = write_pyavro(path, rows)
    else:
        written = write_fastavro(variant, path, rows)
    return f"{written}; {build_avro_index(target)}"


# --------------------------------------------------------------- rocksdb ---


def rocks_options(variant: str, column: str, cache: rocksdict.Cache) -> rocksdict.Options:
    """One column family's options, each set explicitly so no saved options file is reloaded.

    Block zstd level 3 at every level, bottommost included; 16 KiB blocks in the one
    shared LRU cache, index and filter blocks in it too; a bloom filter on the families
    that hold no body (`meta`, `default`); 32 MiB memtables under a 128 MiB cap; two
    background jobs; one old info LOG kept. The blob variant moves the two bodies into
    zstd blob files, with GC at age cutoff 1.0 so a full compaction reclaims every stale
    blob.
    """
    options = rocksdict.Options(raw_mode=True)
    options.create_if_missing(True)  # noqa: FBT003  the binding's setter takes a positional flag
    options.create_missing_column_families(True)  # noqa: FBT003  the binding's setter takes a positional flag
    zstd = rocksdict.DBCompressionType.zstd()
    options.set_compression_type(zstd)
    options.set_bottommost_compression_type(zstd)
    options.set_compression_options(ROCKS_ZSTD_WINDOW, ZSTD_LEVEL, 0, 0)
    options.set_bottommost_compression_options(ROCKS_ZSTD_WINDOW, ZSTD_LEVEL, 0, 0, True)  # noqa: FBT003  the binding's setter takes a positional flag
    table = rocksdict.BlockBasedOptions()
    table.set_block_size(ROCKS_BLOCK)
    table.set_block_cache(cache)
    table.set_cache_index_and_filter_blocks(True)
    if column not in BODY_COLUMNS:
        table.set_bloom_filter(ROCKS_BLOOM_BITS, False)  # noqa: FBT003  the binding's setter takes a positional flag
    options.set_block_based_table_factory(table)
    options.set_write_buffer_size(ROCKS_WRITE_BUFFER)
    options.set_db_write_buffer_size(ROCKS_DB_WRITE_BUFFER)
    options.set_max_background_jobs(ROCKS_JOBS)
    options.set_keep_log_file_num(1)
    if variant == "rocksdb-blob" and column in BODY_COLUMNS:
        options.set_enable_blob_files(True)
        options.set_min_blob_size(ROCKS_MIN_BLOB)
        options.set_blob_file_size(ROCKS_BLOB_FILE)
        options.set_blob_compression_type(zstd)
        options.set_enable_blob_gc(True)
        options.set_blob_gc_age_cutoff(1.0)
    return options


def unpack(value: bytes) -> tuple[bytes, bytes | None, bytes]:
    """Split a packed row into its meta JSON, its HTML (None when absent) and its Markdown."""
    meta_length, html_length = PACKED_HEADER.unpack_from(value)
    start = PACKED_HEADER.size + meta_length
    meta = value[PACKED_HEADER.size : start]
    if html_length == NO_HTML:
        return meta, None, value[start:]
    return meta, value[start : start + html_length], value[start + html_length :]


class RocksStore:
    """One open RocksDB store in its layout, with a sub-Rdict and a handle per column family.

    rocksdict keeps the database open while any sub-Rdict or handle is alive, so `close`
    drops every one of them before closing the database; only then is the lock released
    and the WAL left empty.
    """

    def __init__(self, variant: str, target: Path, *, read_only: bool = False) -> None:
        """Open or create the store, naming every column family and passing every option."""
        self.target = target
        self.packed = variant == "rocksdb-packed"
        self.cache = rocksdict.Cache(ROCKS_CACHE)
        families = (
            {}
            if self.packed
            else {c: rocks_options(variant, c, self.cache) for c in ROCKS_FAMILIES}
        )
        access = (
            rocksdict.AccessType.read_only() if read_only else rocksdict.AccessType.read_write()
        )
        self.db = rocksdict.Rdict(
            str(target),
            options=rocks_options(variant, "default", self.cache),
            column_families=families,
            access_type=access,
        )
        self.parts = {c: self.db.get_column_family(c) for c in families}
        self.handles = {c: self.db.get_column_family_handle(c) for c in families}
        self.write_options = {}
        for sync in (True, False):
            self.write_options[sync] = rocksdict.WriteOptions()
            self.write_options[sync].sync = sync

    def put(self, batch: rocksdict.WriteBatch, page: dict[str, Any]) -> None:
        """Add one page to a batch: three column families, or one packed value."""
        key = page["identity"].encode()
        meta = {c: page[c] for c in META_COLUMNS}
        meta_bytes = json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode()
        html = None if page["html"] is None else page["html"].encode()
        markdown = page["markdown"].encode()
        if self.packed:
            header = PACKED_HEADER.pack(len(meta_bytes), NO_HTML if html is None else len(html))
            batch.put(key, b"".join((header, meta_bytes, html or b"", markdown)))
            return
        batch.put(key, meta_bytes, self.handles["meta"])
        if html is None:
            batch.delete(key, self.handles["html"])
        else:
            batch.put(key, html, self.handles["html"])
        batch.put(key, markdown, self.handles["markdown"])

    def write(self, pages: Iterable[dict[str, Any]], *, sync: bool) -> None:
        """Write the pages as one atomic WriteBatch, with or without a sync of the WAL."""
        batch = rocksdict.WriteBatch(raw_mode=True)
        for page in pages:
            self.put(batch, page)
        self.db.write(batch, self.write_options[sync])

    def get(self, identity: str) -> tuple[bytes | None, bytes | None]:
        """The HTML and Markdown of one page; None for an absent body or page."""
        key = identity.encode()
        if self.packed:
            value = self.db.get(key)
            if value is None:
                return None, None
            _, html, markdown = unpack(value)
            return html, markdown
        return self.parts["html"].get(key), self.parts["markdown"].get(key)

    def markdown_bodies(self) -> Iterator[bytes]:
        """Every Markdown body in key order; the packed layout reads every value to get it."""
        if self.packed:
            for value in self.db.values():
                yield unpack(value)[2]
        else:
            yield from self.parts["markdown"].values()

    def metas(self) -> Iterator[bytes]:
        """Every row's meta JSON in key order; the packed layout reads every value to get it."""
        if self.packed:
            for value in self.db.values():
                yield unpack(value)[0]
        else:
            yield from self.parts["meta"].values()

    def count(self) -> int:
        """Rows, by iterating the keys without filling the block cache."""
        options = rocksdict.ReadOptions()
        options.fill_cache(False)  # noqa: FBT003  the binding's setter takes a positional flag
        keys = self.db if self.packed else self.parts["meta"]
        return sum(1 for _ in keys.keys(read_opt=options))

    def compact(self) -> None:
        """Flush and fully compact every column family, close, and fail if the WAL is not empty."""
        parts = [self.db, *self.parts.values()]
        for part in parts:
            part.flush()
        options = rocksdict.CompactOptions()
        options.set_bottommost_level_compaction(rocksdict.BottommostLevelCompaction.force())
        for part in parts:
            part.compact_range(None, None, options)
        self.close()
        if left := [
            p.name for p in self.target.iterdir() if p.suffix == ".log" and p.stat().st_size
        ]:
            msg = f"{self.target}: WAL left after compaction: {left}"
            raise RuntimeError(msg)

    def close(self) -> None:
        """Close the sub-Rdicts, drop the handles, close the database."""
        for part in self.parts.values():
            part.close()
        self.parts.clear()
        self.handles.clear()
        self.db.close()
        gc.collect()


def live_bytes(target: Path) -> int:
    """Allocated bytes of a store directory that may be open, every file counted.

    An open RocksDB deletes obsolete WAL, SST and blob files from background threads, so
    a file listed may be gone by the time it is measured; it then counts for nothing.
    """
    total = 0
    for path in target.rglob("*"):
        try:
            found = path.stat()
        except FileNotFoundError:
            continue
        if stat.S_ISREG(found.st_mode):
            total += found.st_blocks * 512
    return total


def allocated_bytes(target: Path, pattern: str) -> int:
    """Allocated bytes of the files in `target` matching `pattern`."""
    return sum(p.stat().st_blocks * 512 for p in target.glob(pattern))


def rocks_info(target: Path) -> dict[str, Any]:
    """The RocksDB version from the LOG header, and the bytes of LOG, SST and blob files."""
    found = re.search(r"RocksDB version: (\S+)", (target / "LOG").read_text(errors="replace"))
    version = found.group(1) if found else None
    if version != ROCKSDB_VERSION:
        msg = f"{target}: RocksDB {version}, expected {ROCKSDB_VERSION}"
        raise RuntimeError(msg)
    return {
        "rocksdb_version": version,
        "log_bytes": allocated_bytes(target, "LOG*"),
        "sst_bytes": allocated_bytes(target, "*.sst"),
        "blob_bytes": allocated_bytes(target, "*.blob"),
    }


def rocks_layout(variant: str) -> str:
    """One phrase naming a RocksDB variant's layout."""
    if variant == "rocksdb-packed":
        return "one packed value per row in the default column family"
    blobs = ", bodies in zstd blob files" if variant == "rocksdb-blob" else ""
    return f"column families meta, html, markdown{blobs}"


def build_rocksdb(
    variant: str, target: Path, rows: int | None, regime: str | None = None
) -> tuple[str, dict[str, Any]]:
    """Write the rows in unsynced WriteBatches of SQLITE_BATCH, compact fully, close."""
    store = RocksStore(variant, target)
    written = raw = 0
    batch: list[dict[str, Any]] = []
    for page in avro_rows(rows, regime):
        batch.append(page)
        written += 1
        raw += page["html_bytes"] + page["markdown_bytes"]
        if len(batch) >= SQLITE_BATCH:
            store.write(batch, sync=False)
            batch.clear()
    if batch:
        store.write(batch, sync=False)
    store.compact()
    info = rocks_info(target)
    note = (
        f"{rocks_layout(variant)}; RocksDB {info['rocksdb_version']},"
        f" LOG {info['log_bytes'] / 1024:.0f} KiB"
    )
    return note, {"rows_written": written, "raw_bytes": raw, **info}


BUILDERS: dict[str, Callable[[str, Path, int | None], str]] = {
    "parquet": build_parquet,
    "vortex": build_vortex,
    "lance": build_lance,
    "avro": build_avro,
    "sqlite": build_sqlite_dict,
}


def build_child(variant: str, target: Path, rows: int | None, regime: str | None) -> None:
    """Build one variant into `target` and print wall, RSS and the layout note.

    A RocksDB build also reports the rows it wrote, their raw bytes, the rows a read-only
    reopen counts (outside the timed region, after the RSS is read) and its file sizes.
    """
    target.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    extra: dict[str, Any] = {}
    if family(variant) == "rocksdb":
        note, extra = build_rocksdb(variant, target, rows, regime)
    else:
        note = BUILDERS[family(variant)](variant, target, rows)
    wall = time.perf_counter() - started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS
    if extra:
        store = RocksStore(variant, target, read_only=True)
        extra["rows"] = store.count()
        store.close()
    report = {"variant": variant, "wall_s": wall, "rss_bytes": rss, "note": note}
    print(json.dumps({**report, **extra}))


# --------------------------------------------------------------- queries ---


def duckdb_query(variant: str, query: str, setting: str, target: Path) -> dict[str, Any]:
    """The three read shapes through DuckDB on a file format or the duckdb-zstd store."""
    connection = connect(variant, target, setting)
    source = source_sql(variant, target)
    limit = connection.execute("SELECT current_setting('memory_limit')").fetchone()
    threads = connection.execute("SELECT current_setting('threads')").fetchone()
    items = 0
    if query == "point":
        identities = json.loads(IDS_FILE.read_text())
        if family(variant) == "avro":
            identities = identities[:: len(identities) // AVRO_LOOKUPS][:AVRO_LOOKUPS]
        for identity in identities:
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


def projection(source: BinaryIO, columns: list[str]) -> dict[str, Any]:
    """A reader schema of `columns` derived from the file's own writer schema.

    DuckDB writes a record named `root` with every field a null union, and fastavro
    refuses a reader schema whose record name differs, so the projection keeps the
    writer's name and field types and drops the other fields.
    """
    writer: dict[str, Any] = fastavro.reader(source).writer_schema
    source.seek(0)
    return {**writer, "fields": [f for f in writer["fields"] if f["name"] in columns]}


def avro_point(source: BinaryIO, target: Path) -> int:
    """Look each identity up in the sidecar index, seek to its block, decode that block."""
    index = sqlite3.connect(f"file:{target / 'pages.index.sqlite'}?mode=ro", uri=True)
    blocks = fastavro.block_reader(source)
    items = 0
    for identity in json.loads(IDS_FILE.read_text()):
        found = index.execute(
            "SELECT block_offset, position FROM lookup WHERE identity = ?", (identity,)
        ).fetchone()
        if found is None:
            continue
        source.seek(found[0])
        record = next(islice(next(blocks), found[1], None))
        digest(record["html"] or "")
        digest(record["markdown"])
        items += 1
    index.close()
    return items


def avro_query(query: str, target: Path) -> dict[str, Any]:
    """The three read shapes through fastavro; scan and meta decode a projection."""
    items = 0
    with (target / "pages.avro").open("rb") as source:
        if query == "point":
            items = avro_point(source, target)
        else:
            columns = ["markdown"] if query == "scan" else META_COLUMNS
            for record in fastavro.reader(source, reader_schema=projection(source, columns)):
                if query == "scan":
                    digest(record["markdown"])
                items += 1
    return {"items": items, "memory_limit": FASTAVRO, "threads": None}


def rocksdb_query(variant: str, query: str, target: Path) -> dict[str, Any]:
    """The three read shapes on a RocksDB store, opened read-only with its 128 MiB cache.

    `point` gets both bodies; `scan` digests every Markdown body; `meta` parses every
    row's meta JSON. The packed layout reads, and slices, the whole row for each.
    """
    store = RocksStore(variant, target, read_only=True)
    items = 0
    if query == "point":
        for identity in json.loads(IDS_FILE.read_text()):
            html, markdown = store.get(identity)
            if markdown is not None:
                digest(html or b"")
                digest(markdown)
                items += 1
    elif query == "scan":
        for markdown in store.markdown_bodies():
            digest(markdown)
            items += 1
    else:
        for meta in store.metas():
            json.loads(meta)
            items += 1
    store.close()
    return {"items": items, "memory_limit": ROCKS_LIMIT, "threads": None, "caps": ROCKS_CAPS}


def settings_of(variant: str) -> list[str]:
    """The settings a variant is measured under: its own, DuckDB's two, fastavro too."""
    if family(variant) in {"sqlite", "rocksdb"}:
        return ["default"]
    if family(variant) == "avro":
        return ["default", DUCKDB_LIMIT, FASTAVRO]
    return ["default", DUCKDB_LIMIT]


def query_child(variant: str, query: str, setting: str, target: Path) -> None:
    """Run one measurement and print its JSON line."""
    started = time.perf_counter()
    if setting == FASTAVRO:
        found = avro_query(query, target)
    elif family(variant) == "sqlite":
        found = sqlite_query(variant, query, target)
    elif family(variant) == "rocksdb":
        found = rocksdb_query(variant, query, target)
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


# --------------------------------------------------------------- upserts ---


def sqlite_compressors(
    connection: sqlite3.Connection, variant: str
) -> dict[tuple[str, str], zstandard.ZstdCompressor]:
    """The per-(regime, column) dictionary compressors of sqlite-zstd-dict; none otherwise."""
    if variant != "sqlite-zstd-dict":
        return {}
    return {
        (regime, column): zstandard.ZstdCompressor(
            level=ZSTD_LEVEL, dict_data=zstandard.ZstdCompressionDict(data)
        )
        for regime, column, data in connection.execute(
            "SELECT regime, column, data FROM dictionaries"
        )
    }


def sqlite_decompressors(
    connection: sqlite3.Connection, variant: str
) -> dict[tuple[str, str], zstandard.ZstdDecompressor]:
    """The per-(regime, column) dictionary decompressors of sqlite-zstd-dict; none otherwise."""
    if variant != "sqlite-zstd-dict":
        return {}
    return {
        (regime, column): zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(data))
        for regime, column, data in connection.execute(
            "SELECT regime, column, data FROM dictionaries"
        )
    }


def sqlite_upserts(variant: str, connection: sqlite3.Connection) -> int:
    """bench_queries's upsert, one transaction per row, bodies compressed as the store does."""
    compressors = sqlite_compressors(connection, variant)
    plain = zstandard.ZstdCompressor(level=ZSTD_LEVEL)
    assignments = ", ".join(f"{c} = excluded.{c}" for c in COLUMNS if c != "identity")
    placeholders = ",".join("?" * len(COLUMNS))
    sql = (
        f"INSERT INTO pages ({COLUMN_LIST}) VALUES ({placeholders})"  # noqa: S608  fixed column names
        f" ON CONFLICT(identity) DO UPDATE SET {assignments}"
    )
    items = 0
    for page in upsert_rows():
        values = []
        for column in COLUMNS:
            value = page[column]
            if column in BODY_COLUMNS and value is not None:
                value = compressors.get((page["regime"], column), plain).compress(value.encode())
            values.append(value)
        with connection:
            connection.execute(sql, values)
        items += 1
    return items


def sqlite_check(variant: str, target: Path) -> tuple[int, int]:
    """Rows in the store, and how many upserted rows hold their new Markdown body."""
    connection = sqlite3.connect(target / "pages.sqlite")
    decompressors = sqlite_decompressors(connection, variant)
    plain = zstandard.ZstdDecompressor()
    (rows,) = connection.execute("SELECT count(*) FROM pages").fetchone()
    changed = 0
    for page in upsert_rows():
        found = connection.execute(
            "SELECT markdown FROM pages WHERE identity = ?", (page["identity"],)
        ).fetchone()
        decompressor = decompressors.get((page["regime"], "markdown"), plain)
        if found and decompressor.decompress(found[0]).decode() == page["markdown"]:
            changed += 1
    connection.close()
    return int(rows), changed


def sqlite_upsert_child(variant: str, target: Path) -> dict[str, Any]:
    """Upsert into a SQLite store, VACUUM, check; walls and sizes of each step."""
    connection = sqlite3.connect(target / "pages.sqlite")
    (expected,) = connection.execute("SELECT count(*) FROM pages").fetchone()
    report: dict[str, Any] = {"size_before": store_bytes(target), "expected_rows": expected}
    started = time.perf_counter()
    report["items"] = sqlite_upserts(variant, connection)
    report["wall_upserts"] = time.perf_counter() - started
    report["size_after_upserts"] = store_bytes(target)
    started = time.perf_counter()
    connection.execute("VACUUM")
    connection.close()
    report["wall_compact"] = time.perf_counter() - started
    report["size_after_compaction"] = store_bytes(target)
    report["rows_after"], report["changed_found"] = sqlite_check(variant, target)
    report["compaction"] = "VACUUM"
    return report


def avro_sync(variant: str) -> int:
    """The block size an Avro store was written with."""
    return AVRO_BLOCK_1M if variant.endswith("-1m") else AVRO_SYNC


def avro_write(out: BinaryIO, records: Iterable[dict[str, Any]], sync: int) -> None:
    """Write records in the stores' codec, zstd level 3, at the given block size."""
    fastavro.writer(
        out,
        AVRO_PARSED,
        records,
        codec="zstandard",
        codec_compression_level=ZSTD_LEVEL,
        sync_interval=sync,
    )


def avro_upserts(target: Path, sync: int) -> int:
    """Per row: append one block, fsync, repoint the identity in the index, commit."""
    path = target / "pages.avro"
    index = sqlite3.connect(target / "pages.index.sqlite")
    items = 0
    for page in upsert_rows():
        offset = path.stat().st_size
        with path.open("a+b") as out:
            avro_write(out, [page], sync)
            out.flush()
            os.fsync(out.fileno())
        with index:
            updated = index.execute(
                "UPDATE lookup SET block_offset = ?, position = 0 WHERE identity = ?",
                (offset, page["identity"]),
            ).rowcount
        if updated != 1:
            msg = f"{page['identity']} is not in the index"
            raise RuntimeError(msg)
        items += 1
    index.close()
    return items


def avro_check(target: Path) -> tuple[int, int]:
    """Records in the file, and how many upserted rows the index resolves to the new body."""
    path = target / "pages.avro"
    index = sqlite3.connect(f"file:{target / 'pages.index.sqlite'}?mode=ro", uri=True)
    changed = 0
    with path.open("rb") as source:
        records = sum(block.num_records for block in fastavro.block_reader(source))
        source.seek(0)
        blocks = fastavro.block_reader(source)
        for page in upsert_rows():
            offset, position = index.execute(
                "SELECT block_offset, position FROM lookup WHERE identity = ?",
                (page["identity"],),
            ).fetchone()
            source.seek(offset)
            record = next(islice(next(blocks), position, None))
            changed += record["markdown"] == page["markdown"]
    index.close()
    return records, changed


def avro_compact(target: Path, sync: int) -> None:
    """Rewrite the file with only the records the index points to; rebuild the index."""
    path = target / "pages.avro"
    index_path = target / "pages.index.sqlite"
    index = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    keep = set(index.execute("SELECT block_offset, position FROM lookup"))
    index.close()

    def live(source: BinaryIO) -> Iterator[dict[str, Any]]:
        for block in fastavro.block_reader(source):
            for position, record in enumerate(block):
                if (block.offset, position) in keep:
                    yield record

    part = target / "pages.avro.part"
    with path.open("rb") as source, part.open("wb") as out:
        avro_write(out, live(source), sync)
        out.flush()
        os.fsync(out.fileno())
    part.replace(path)
    index_path.unlink()
    build_avro_index(target)


def avro_upsert_child(variant: str, target: Path) -> dict[str, Any]:
    """Upsert into an Avro store, check through the live index, compact, check again."""
    sync = avro_sync(variant)
    index = sqlite3.connect(f"file:{target / 'pages.index.sqlite'}?mode=ro", uri=True)
    (expected,) = index.execute("SELECT count(*) FROM lookup").fetchone()
    index.close()
    report: dict[str, Any] = {"size_before": store_bytes(target), "expected_rows": expected}
    started = time.perf_counter()
    report["items"] = avro_upserts(target, sync)
    report["wall_upserts"] = time.perf_counter() - started
    report["size_after_upserts"] = store_bytes(target)
    report["records_before_compaction"], report["changed_before_compaction"] = avro_check(target)
    started = time.perf_counter()
    avro_compact(target, sync)
    report["wall_compact"] = time.perf_counter() - started
    report["size_after_compaction"] = store_bytes(target)
    report["rows_after"], report["changed_found"] = avro_check(target)
    report["compaction"] = f"rewrite in {sync}-byte blocks, then rebuild the index"
    return report


def rocksdb_upsert_child(variant: str, target: Path) -> dict[str, Any]:
    """Upsert into a RocksDB store, one WriteBatch per row, compact fully, check read-only."""
    layout = store_of(variant)
    sync = variant.endswith("-sync")
    report: dict[str, Any] = {"size_before": store_bytes(target), "sync": sync}
    store = RocksStore(layout, target)
    report["expected_rows"] = store.count()
    started = time.perf_counter()
    items = 0
    for page in upsert_rows():
        store.write([page], sync=sync)
        items += 1
    report["items"] = items
    report["wall_upserts"] = time.perf_counter() - started
    report["size_after_upserts"] = live_bytes(target)
    started = time.perf_counter()
    store.compact()
    report["wall_compact"] = time.perf_counter() - started
    report["size_after_compaction"] = store_bytes(target)
    check = RocksStore(layout, target, read_only=True)
    report["rows_after"] = check.count()
    report["changed_found"] = sum(
        check.get(page["identity"])[1] == page["markdown"].encode() for page in upsert_rows()
    )
    check.close()
    gc_note = (
        "; blob GC at cutoff 1.0 rewrites every blob file" if layout == "rocksdb-blob" else ""
    )
    report["compaction"] = f"flush, then compact_range with bottommost force{gc_note}"
    report.update(rocks_info(target))
    return report


def upsert_child(variant: str, target: Path) -> None:
    """One upsert measurement; print its JSON line, or fail if a check does not hold."""
    if family(variant) == "avro":
        report = avro_upsert_child(variant, target)
    elif family(variant) == "rocksdb":
        report = rocksdb_upsert_child(variant, target)
    else:
        report = sqlite_upsert_child(variant, target)
    if report["rows_after"] != report["expected_rows"] or report["changed_found"] != len(
        upsert_rows()
    ):
        msg = f"{variant}: check failed: {report}"
        raise RuntimeError(msg)
    report["rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS
    report["ms_per_row"] = report["wall_upserts"] * 1000 / report["items"]
    print(json.dumps({"variant": variant, **report}))


# ---------------------------------------------------------------- parent ---


def install_extensions() -> None:
    """Install vortex, lance and avro into the scratch extension directory (network, once)."""
    EXTENSIONS.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute(f"SET extension_directory = '{EXTENSIONS}'")
    for name in ("vortex", "lance", "avro"):
        (installed,) = connection.execute(
            "SELECT installed FROM duckdb_extensions() WHERE extension_name = ?", [name]
        ).fetchone() or (False,)
        connection.execute(f"INSTALL {name}")
        print(f"extension {name}: {'present' if installed else 'installed'}", file=sys.stderr)
    connection.close()


def prepare(rows: int | None) -> tuple[int, int]:
    """Pick the lookup identities as bench_queries does; return the rows and their raw bytes."""
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
    return count, int(raw)


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


def check_rows(variant: str, found: dict[str, Any], expected: int) -> None:
    """Exit unless a RocksDB build wrote, and a reopen counted, the expected rows."""
    if "error" in found:
        sys.exit(f"build of {variant} failed: {found['error']}")
    if found.get("rows", expected) != expected or found.get("rows_written", expected) != expected:
        sys.exit(f"build of {variant}: {expected} rows expected, got {found}")


def build(variant: str, rows: int | None, raw: int, count: int) -> dict[str, Any]:
    """Wipe and build one variant in a child; measure it afterwards."""
    target = target_of(variant)
    shutil.rmtree(target, ignore_errors=True)
    found = run_child(["build", variant, str(target), str(rows or 0)])
    check_rows(variant, found, count)
    allocated = store_bytes(target)
    files = sum(1 for p in target.rglob("*") if p.is_file())
    record = {**found, "files": files, "allocated_bytes": allocated, "ratio": allocated / raw}
    print(
        f"built {variant}: {allocated / 2**20:.0f} MiB ({record['ratio']:.3f}),"
        f" {found['wall_s']:.1f} s, {found['rss_bytes'] / 2**20:.0f} MiB; {found['note']}",
        file=sys.stderr,
    )
    return record


def build_regimes(variants: list[str], rows: int | None) -> list[dict[str, Any]]:
    """Build each regime of each variant on its own, measure it, delete it.

    The regimes, their rows and their raw bytes come from `sizes.json`; a full regime
    build must write and count exactly those rows and bytes. With `rows`, each regime
    takes its first `rows` rows (a smoke) and the build's own totals stand.
    """
    totals = [
        r
        for r in json.loads((RESULTS / "sizes.json").read_text())
        if r["store"] == "sqlite-raw" and r["regime"] != "all"
    ]
    records = []
    for variant in variants:
        for total in totals:
            regime = total["regime"]
            target = FORMATS / f"{variant}-{regime}-PROTOTYPE-wipe-me"
            shutil.rmtree(target, ignore_errors=True)
            found = run_child(["build", variant, str(target), str(rows or 0), regime])
            expected = min(rows, total["rows"]) if rows else total["rows"]
            check_rows(f"{variant} {regime}", found, expected)
            if not rows and found["raw_bytes"] != total["raw_bytes"]:
                sys.exit(f"{variant} {regime}: raw bytes {found['raw_bytes']} != {total}")
            allocated = store_bytes(target)
            shutil.rmtree(target)
            record = {**found, "regime": regime, "allocated_bytes": allocated}
            record["ratio"] = allocated / found["raw_bytes"]
            records.append(record)
            print(
                f"built {variant} {regime}: {allocated / 2**20:.1f} MiB ({record['ratio']:.3f}),"
                f" {found['wall_s']:.1f} s",
                file=sys.stderr,
            )
    return records


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
    print("\nFile formats and the dictionary store: size and write cost\n")
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


def measure_upserts(variants: list[str]) -> list[dict[str, Any]]:
    """Every upsert store, twice, each run on a fresh APFS clone; both runs kept."""
    results = []
    for variant in variants:
        source = target_of(variant)
        if not source.exists():
            sys.exit(f"no {variant} store at {source}; run bench_formats.py first")
        clone = FORMATS / f"{variant}-upsert-PROTOTYPE-wipe-me"
        for run in range(1, UPSERT_RUNS + 1):
            shutil.rmtree(clone, ignore_errors=True)
            subprocess.run(["cp", "-Rc", str(source), str(clone)], check=True)
            found = run_child(["upsert", variant, str(clone)])
            shutil.rmtree(clone, ignore_errors=True)
            if "error" in found:
                sys.exit(f"upserts on {variant} failed: {found['error']}")
            results.append({**found, "run": run})
            print(
                f"{variant} run {run}: {found['ms_per_row']:.2f} ms per row,"
                f" {found['wall_compact']:.1f} s compaction, {found['rss_bytes'] / 2**20:.0f} MiB",
                file=sys.stderr,
            )
    return results


def print_upserts(results: list[dict[str, Any]]) -> None:
    """The upsert table, Markdown, the second run of each store."""
    print("\nUpserts, 500 rows one transaction each (second of two runs, a fresh process each)\n")
    print(
        "| variant | ms per row | compaction s | peak RSS MiB"
        " | MiB before > after upserts > after compaction | compaction |"
    )
    print("| --- | ---: | ---: | ---: | --- | --- |")
    for r in results:
        if r["run"] != UPSERT_RUNS:
            continue
        keys = ("size_before", "size_after_upserts", "size_after_compaction")
        sizes = " > ".join(f"{r[k] / 2**20:.1f}" for k in keys)
        print(
            f"| {r['variant']} | {r['ms_per_row']:.2f} | {r['wall_compact']:.1f}"
            f" | {r['rss_bytes'] / 2**20:.0f} | {sizes} | {r['compaction']} |"
        )


def print_regimes(records: list[dict[str, Any]]) -> None:
    """The per-regime size table, Markdown."""
    print("\nPer regime: each regime built on its own, compacted and closed\n")
    print("| variant | regime | rows | raw MiB | allocated MiB | allocated/raw | write s |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for r in records:
        print(
            f"| {r['variant']} | {r['regime']} | {r['rows']} | {r['raw_bytes'] / 2**20:.1f}"
            f" | {r['allocated_bytes'] / 2**20:.1f} | {r['ratio']:.3f} | {r['wall_s']:.1f} |"
        )


def child(argv: list[str]) -> None:
    """Child: one build, one measurement or one explain."""
    kind, variant, *rest = argv
    if kind == "build":
        target, rows, *regime = rest
        build_child(variant, Path(target), int(rows) or None, regime[0] if regime else None)
    elif kind == "query":
        query_child(variant, rest[0], rest[1], Path(rest[2]))
    elif kind == "upsert":
        upsert_child(variant, Path(rest[0]))
    else:
        explain_child(variant, Path(rest[0]))


def measure_all(variants: list[str]) -> list[dict[str, Any]]:
    """Every read shape of every variant at each setting; one EXPLAIN per DuckDB-read store."""
    queries = []
    for variant in variants:
        queries += [
            measure(variant, query, setting)
            for query in QUERIES
            for setting in settings_of(variant)
        ]
        if family(variant) not in {"sqlite", "rocksdb"}:
            run_child(["explain", variant, str(target_of(variant))])
    return queries


def run_upserts(only: str | None) -> None:
    """Measure the upserts of the first four stores, or with `only` rocksdb, of RocksDB's."""
    if only not in {None, "rocksdb"}:
        sys.exit("--upserts takes no --only but rocksdb")
    results = measure_upserts(ROCKSDB_UPSERTS if only else UPSERT_VARIANTS)
    print_upserts(results)
    out = RESULTS / ("formats-upserts-rocksdb.json" if only else "formats-upserts.json")
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nsaved {out}")


def main() -> None:
    """Parent: install, prepare, build, measure, explain, print the tables, save the JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", nargs="+", metavar="ARG")
    parser.add_argument("--rows", type=int, help="build from the first N rows only (smoke)")
    parser.add_argument(
        "--only",
        choices=sorted({family(v) for v in NEW_VARIANTS}),
        help="build and measure one family against parquet-zstd, sqlite-zstd-dict, duckdb-zstd",
    )
    parser.add_argument(
        "--upserts",
        action="store_true",
        help="measure upserts on sqlite-zstd, sqlite-zstd-dict and two Avro stores (offline);"
        " with --only rocksdb, on the RocksDB stores synced and not",
    )
    parser.add_argument(
        "--per-regime",
        action="store_true",
        help="with --only rocksdb, also build, measure and delete each regime on its own",
    )
    args = parser.parse_args()
    if args.child:
        child(args.child)
        return
    if args.upserts:
        run_upserts(args.only)
        return
    if args.per_regime and args.only != "rocksdb":
        sys.exit("--per-regime needs --only rocksdb")
    for needed in (DUCKDB_SOURCE, SQLITE_SOURCE, STORES / "sqlite-zstd" / "pages.sqlite"):
        if not needed.exists():
            sys.exit(f"no store at {needed}; run load_stores.py first")
    built = [v for v in NEW_VARIANTS if args.only in {None, family(v)}]
    references = REFERENCES
    if args.only:
        references = [v for v in ONLY_REFERENCES if v not in built]
        for variant in references:
            if not target_of(variant).exists():
                sys.exit(f"no {variant} store; run bench_formats.py without --only first")
    install_extensions()
    count, raw = prepare(args.rows)
    FORMATS.mkdir(parents=True, exist_ok=True)
    sizes = [build(variant, args.rows, raw, count) for variant in built]
    regimes = build_regimes(built, args.rows) if args.per_regime else []
    queries = measure_all(built + references)
    print_tables(sizes, queries)
    if regimes:
        print_regimes(regimes)
    suffix = (f"-{args.only}" if args.only else "") + (f"-{args.rows}" if args.rows else "")
    out = RESULTS / f"formats{suffix}.json"
    out.write_text(
        json.dumps(
            {"raw_bytes": raw, "sizes": sizes, "regimes": regimes, "queries": queries}, indent=2
        )
        + "\n"
    )
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
