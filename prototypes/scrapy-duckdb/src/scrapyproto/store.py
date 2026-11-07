"""Ticket 03's store: a pulled JSONL feed bulk-loaded into one DuckDB file on the host.

A load is all or nothing: the feed is checked line by line first (UTF-8, JSON, the page fields), then
`pages` and its `runs` row are inserted in one transaction whose row count is checked before commit. So a
crash between the pull and the load leaves the feed on the host and nothing in the store, and `scrapyproto
load <run_id>` loads it later; a run is never half in the store.
"""

import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from scrapyproto import state

DEFAULT_DB = state.DEFAULT_STATE_DIR / "prototype.duckdb"
FEEDS_DIR = state.DEFAULT_STATE_DIR / "feeds"
MAX_OBJECT_BYTES = 64 * 1024 * 1024  # Above the spider's 10 MiB page cap; DuckDB's default is 16 MiB.

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id       VARCHAR PRIMARY KEY,
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    start_urls   VARCHAR[],
    scope        JSON,
    pages        INTEGER NOT NULL,
    wall_seconds DOUBLE,
    store        VARCHAR DEFAULT 'bulk',
    store_file   VARCHAR
);
CREATE TABLE IF NOT EXISTS pages (
    run_id       VARCHAR NOT NULL,
    url          VARCHAR NOT NULL,
    final_url    VARCHAR,
    status       INTEGER,
    content_type VARCHAR,
    depth        INTEGER,
    referrer     VARCHAR,
    outlinks     VARCHAR[],
    fetched_at   TIMESTAMPTZ,
    content_hash VARCHAR,
    html         VARCHAR USING COMPRESSION ZSTD,
    PRIMARY KEY (run_id, url)
);
"""

# Types pinned, so DuckDB's sampling cannot guess a column wrong.
COLUMNS = {
    "url": "VARCHAR",
    "final_url": "VARCHAR",
    "status": "INTEGER",
    "content_type": "VARCHAR",
    "depth": "INTEGER",
    "referrer": "VARCHAR",
    "outlinks": "VARCHAR[]",
    "fetched_at": "TIMESTAMPTZ",
    "content_hash": "VARCHAR",
    "html": "VARCHAR",
}
REQUIRED = {"url": str, "status": int, "depth": int, "fetched_at": str}
# Ticket 05: a store made before `store` existed gains it; its runs are all bulk loads.
MIGRATE = """
ALTER TABLE runs ADD COLUMN IF NOT EXISTS store VARCHAR DEFAULT 'bulk';
ALTER TABLE runs ADD COLUMN IF NOT EXISTS store_file VARCHAR;
"""
RUNS_INSERT = (
    "INSERT INTO runs (run_id, started_at, finished_at, start_urls, scope, pages, wall_seconds, store, store_file) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


class FeedError(ValueError):
    """The feed cannot be loaded as it is; nothing was written."""


@dataclass(frozen=True)
class FeedCheck:
    lines: int
    unique_urls: int
    duplicate_urls: list[str]


def check_feed(feed: Path) -> FeedCheck:
    """Read the whole feed before DuckDB does; refuse it on the first line that is not a page."""
    raw = feed.read_bytes()
    seen: set[str] = set()
    dupes: list[str] = []
    lines = raw.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    for n, line in enumerate(lines, 1):
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            msg = f"{feed}: line {n} is not UTF-8 ({exc.reason} at byte {exc.start})"
            raise FeedError(msg) from exc
        try:
            obj = json.loads(text)
        except ValueError as exc:
            msg = f"{feed}: line {n} is not JSON ({exc}); a feed cut short by a killed spider looks like this"
            raise FeedError(msg) from exc
        if not isinstance(obj, dict):
            msg = f"{feed}: line {n} is not a JSON object"
            raise FeedError(msg)
        for key, kind in REQUIRED.items():
            if not isinstance(obj.get(key), kind):
                msg = f"{feed}: line {n} has no {kind.__name__} {key!r}"
                raise FeedError(msg)
        for key, value in obj.items():
            if isinstance(value, str):
                try:
                    value.encode("utf-8")
                except UnicodeEncodeError as exc:
                    msg = f"{feed}: line {n} field {key!r} holds a lone surrogate, not UTF-8 text"
                    raise FeedError(msg) from exc
        if obj["url"] in seen:
            dupes.append(obj["url"])
        seen.add(obj["url"])
    return FeedCheck(len(lines), len(seen), dupes)


def connect(db: Path, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if read_only:
        if not db.exists():
            msg = f"no store at {db}: no run has been loaded yet"
            raise FileNotFoundError(msg)
        con = duckdb.connect(str(db), read_only=True)
    else:
        db.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(db))
        con.execute(SCHEMA)
        con.execute(MIGRATE)
    con.execute("SET TimeZone = 'UTC'")  # Printed times read the same on any host.
    return con


def _ts(epoch: float | None) -> datetime | None:
    return datetime.fromtimestamp(epoch, UTC) if epoch is not None else None


def load(db: Path, manifest: dict[str, Any], feed: Path) -> tuple[int, FeedCheck]:
    """Insert one run's pages and its runs row together. Duplicate URLs keep the earliest fetch, and are
    counted and reported, never silently merged. Raises FeedError, or duckdb.Error, with nothing written."""
    check = check_feed(feed)
    run_id = manifest["run_id"]
    con = connect(db)
    try:
        if con.execute("SELECT count(*) FROM runs WHERE run_id = ?", [run_id]).fetchall() != [(0,)]:
            msg = f"run {run_id} is already in {db}; nothing loaded"
            raise FeedError(msg)
        con.execute("BEGIN TRANSACTION")
        try:
            # read_json takes the path as a literal, not a parameter; the path is ours, quoted here.
            path_sql = "'" + str(feed).replace("'", "''") + "'"
            columns_sql = "{" + ", ".join(f"'{k}': '{v}'" for k, v in COLUMNS.items()) + "}"
            con.execute(
                f"""
                INSERT INTO pages
                SELECT ? AS run_id, url, final_url, status, content_type, depth, referrer, outlinks,
                    fetched_at, content_hash, html
                FROM read_json({path_sql}, format = 'newline_delimited', columns = {columns_sql},
                    maximum_object_size = {MAX_OBJECT_BYTES})
                QUALIFY row_number() OVER (PARTITION BY url ORDER BY fetched_at, final_url) = 1
                """,  # noqa: S608  prototype: the only interpolations are our own path and constants
                [run_id],
            )
            pages = con.execute("SELECT count(*) FROM pages WHERE run_id = ?", [run_id]).fetchall()[0][0]
            if pages != check.unique_urls:
                msg = f"loaded {pages} pages but the feed has {check.unique_urls} unique URLs; rolled back"
                raise FeedError(msg)
            con.execute(RUNS_INSERT, _runs_row(manifest, pages, "bulk", db))
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        try:
            con.execute("CHECKPOINT")
        except duckdb.Error as exc:  # Committed already: the run is in the WAL and replays on the next open.
            sys.stderr.write(f"warning: run {run_id} is stored (committed), but CHECKPOINT failed: {exc}\n")
    finally:
        con.close()
    return pages, check


def _runs_row(manifest: dict[str, Any], pages: int, kind: str, file: Path) -> list[Any]:
    return [
        manifest["run_id"],
        _ts(manifest.get("started_epoch")),
        _ts(manifest.get("finished_epoch")),
        manifest["start_urls"],
        json.dumps(manifest["scope"]),
        pages,
        manifest.get("wall_seconds"),
        kind,
        str(file),
    ]


def record_per_item(db: Path, manifest: dict[str, Any], pulled: Path) -> int:
    """Ticket 05: check the pulled per-item file and record its run in the host store's runs table.

    The file must hold this run's runs row, which the pipeline writes only at close, and as many pages as
    that row says; otherwise nothing is recorded. Returns the page count."""
    run_id = manifest["run_id"]
    item = connect(pulled, read_only=True)
    try:
        found = item.execute("SELECT pages, store FROM runs WHERE run_id = ?", [run_id]).fetchall()
        rows = item.execute("SELECT count(*), count(DISTINCT url) FROM pages WHERE run_id = ?", [run_id]).fetchall()[0]
        others = item.execute("SELECT count(*) FROM pages WHERE run_id <> ?", [run_id]).fetchall()[0][0]
    finally:
        item.close()
    if found != [(rows[0], "per-item")] or rows[0] != rows[1] or others:
        msg = (f"{pulled}: runs row {found}, pages {rows[0]} ({rows[1]} distinct URLs), {others} rows of other runs;"
            " a file the pipeline did not close holds no runs row; nothing recorded")
        raise FeedError(msg)
    con = connect(db)
    try:
        if con.execute("SELECT count(*) FROM runs WHERE run_id = ?", [run_id]).fetchall() != [(0,)]:
            msg = f"run {run_id} is already in {db}; nothing recorded"
            raise FeedError(msg)
        con.execute(RUNS_INSERT, _runs_row(manifest, rows[0], "per-item", pulled))
        con.execute("CHECKPOINT")
    finally:
        con.close()
    return rows[0]


def size(db: Path) -> int:
    wal = db.with_name(db.name + ".wal")
    return db.stat().st_size + (wal.stat().st_size if wal.exists() else 0)


CELL_CHARS = 100


def _cell(value: object) -> str:
    """One display cell on one line; long values (html) are cut and their length shown."""
    text = "NULL" if value is None else " ".join(str(value).split())
    return text if len(text) <= CELL_CHARS else f"{text[:CELL_CHARS]}... ({len(str(value))} chars)"


def _table(con: duckdb.DuckDBPyConnection, query: str, params: list[Any] | None = None) -> str:
    rel = con.sql(query, params=params or None)
    if rel is None:
        return "ok"
    names = rel.columns
    # Every column as DuckDB's own text: TIMESTAMPTZ into Python would need pytz, which is not a dependency.
    quoted = ['"' + n.replace('"', '""') + '"' for n in names]
    rows = rel.project(", ".join(f"CAST({q} AS VARCHAR)" for q in quoted)).fetchall()
    cells = [names, *[[_cell(v) for v in row] for row in rows]]
    widths = [max(len(r[i]) for r in cells) for i in range(len(names))]
    out = ["  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip() for row in cells]
    out.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(out)


def summary(db: Path, run_id: str, pages_db: Path | None = None) -> str:
    """The run as the store holds it, read back from DuckDB after a CHECKPOINT. With `pages_db` (ticket
    05's pulled per-item file), the pages are read from that file and the runs row from `db`."""
    runs_con = connect(db, read_only=True)
    try:
        found = runs_con.execute(
            "SELECT pages, wall_seconds, store FROM runs WHERE run_id = ?", [run_id],
        ).fetchall()
    finally:
        runs_con.close()
    if not found:
        msg = f"run {run_id} is not in {db}"
        raise FeedError(msg)
    run = found[0]
    db = pages_db or db
    con = connect(db, read_only=True)
    try:
        rows, distinct, html_bytes, with_html = con.execute(
            "SELECT count(*), count(DISTINCT url), coalesce(sum(strlen(html)), 0), count(html) "
            "FROM pages WHERE run_id = ?",
            [run_id],
        ).fetchall()[0]
        lines = [
            f"run {run_id}: {rows} pages in `pages` ({distinct} distinct URLs), runs.pages = {run[0]}"
            + ("" if rows == run[0] else "  MISMATCH"),
            f"store kind: {run[2]}; pages read from {db}",
            f"wall time: {run[1]:.1f} s (guest clock, wrapper start to Scrapy exit)"
            if run[1] is not None
            else "wall time: not recorded",
            f"html bytes (UTF-8, as stored): {html_bytes} across {with_html} pages with html",
            "",
            "pages by status:",
            _table(con, "SELECT status, count(*) AS pages FROM pages WHERE run_id = ? GROUP BY 1 ORDER BY 1", [run_id]),
            "",
            "depth histogram:",
            _table(con, "SELECT depth, count(*) AS pages FROM pages WHERE run_id = ? GROUP BY 1 ORDER BY 1", [run_id]),
        ]
    finally:
        con.close()
    lines += ["", f"store: {db}, {size(db)} bytes after CHECKPOINT"]
    return "\n".join(lines)


def runs(db: Path) -> str:
    con = connect(db, read_only=True)
    try:
        return _table(
            con,
            "SELECT run_id, store, started_at, finished_at, pages, round(wall_seconds, 1) AS wall_s, start_urls, scope "
            "FROM runs ORDER BY started_at, run_id",
        )
    finally:
        con.close()


def sql(db: Path, query: str) -> str:
    """Any query, against the store opened read-only, so `sql` cannot change it."""
    con = connect(db, read_only=True)
    try:
        return _table(con, query)
    finally:
        con.close()


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
