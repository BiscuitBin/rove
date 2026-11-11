"""Tickets 08 and 09's host consumers: pages from the guest, through the mount, into DuckDB while the crawl runs.

Two arms, one interface. `JsonlTail` reads complete lines of the spider's feed past a byte offset; `RocksTail` follows
the pipeline's RocksDB as a secondary instance and reads the keys past a cursor. Every `tick` inserts what it found
into the run's own DuckDB file together with its cursor in `consumer_offsets`, in one transaction, so a consumer
killed at any point resumes from the last committed cursor: no page twice, none skipped. The host never opens the
RocksDB read-write while the guest writer may live: the guest's LOCK does not cross the mount (ticket 07, probe 2).
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
from rocksdict import AccessType, Options, Rdict
from smol import ExecOptions, Machine

from scrapyproto import machine as m, state, store

ARMS = ("jsonl-tail", "rocks-queue")
TICK_S = 0.1  # The consumer's poll interval; every latency below includes up to one of these.
SECONDARY_DIR = state.DEFAULT_STATE_DIR / "secondary"
PAGE_KEY = b"p:"
CLOSED_KEY = b"meta:closed"

OFFSETS = """
CREATE TABLE IF NOT EXISTS consumer_offsets (run_id VARCHAR PRIMARY KEY, arm VARCHAR, cursor VARCHAR, rows BIGINT,
    duplicates BIGINT, updated_at DOUBLE);
CREATE TABLE IF NOT EXISTS arrivals (run_id VARCHAR, url VARCHAR, committed_at DOUBLE, PRIMARY KEY (run_id, url));
"""
INSERT = (
    "INSERT OR IGNORE INTO pages (run_id, url, final_url, status, content_type, depth, referrer, outlinks, fetched_at, "
    "content_hash, html) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS TIMESTAMPTZ), ?, ?) RETURNING url"
)


def host_queue_dir(run_id: str) -> Path:
    return m.QUEUE_HOST_DIR / run_id


def arm_db(db: Path, run_id: str, arm: str) -> Path:
    """Each arm's run is its own DuckDB file beside the shared store, as ticket 05's per-item file was."""
    return db.parent / f"{run_id}-{arm}.duckdb"


@dataclass
class Consumer:
    run_id: str
    arm: str
    db_path: Path
    con: duckdb.DuckDBPyConnection = field(init=False)
    cursor: str = ""
    rows: int = 0
    duplicates: int = 0
    first_commit_at: float | None = None
    closed: dict[str, Any] | None = None
    # Ticket 09: (url, time right after its batch's COMMIT returned), kept off the cursor transaction and written to
    # `arrivals` by `latency` after the summary. A process that died loses its own; `consume` measures only its own.
    arrived: list[tuple[str, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.con = store.connect(self.db_path)
        self.con.execute(OFFSETS)
        found = self.con.execute(
            "SELECT arm, cursor, rows, duplicates FROM consumer_offsets WHERE run_id = ?", [self.run_id]
        ).fetchall()
        if found:
            arm, self.cursor, self.rows, self.duplicates = found[0]
            if arm != self.arm:
                msg = f"{self.db_path} holds {self.run_id} consumed as {arm}, not {self.arm}"
                raise store.FeedError(msg)

    def _commit(self, items: list[dict[str, Any]], cursor: str) -> int:
        """Insert a batch and move the cursor, in one transaction: both land or neither does."""
        if cursor == self.cursor:
            return 0
        now = time.time()
        new: list[str] = []
        self.con.execute("BEGIN TRANSACTION")
        try:
            for it in items:
                got = self.con.execute(INSERT, [
                    self.run_id, it["url"], it.get("final_url"), it["status"], it.get("content_type"), it["depth"],
                    it.get("referrer"), it.get("outlinks"), it["fetched_at"], it.get("content_hash"), it.get("html"),
                ]).fetchall()
                if got:
                    new.append(it["url"])
            inserted = len(new)
            rows, dups = self.rows + inserted, self.duplicates + len(items) - inserted
            self.con.execute(
                "INSERT OR REPLACE INTO consumer_offsets VALUES (?, ?, ?, ?, ?, ?)",
                [self.run_id, self.arm, cursor, rows, dups, now],
            )
            self.con.execute("COMMIT")
        except BaseException:
            self.con.execute("ROLLBACK")
            raise
        committed_at = time.time()  # The rows are visible to this connection from here.
        self.cursor, self.rows, self.duplicates = cursor, rows, dups
        self.arrived.extend((url, committed_at) for url in new)
        if inserted and self.first_commit_at is None:
            self.first_commit_at = committed_at
        return inserted

    def tick(self) -> int:
        raise NotImplementedError

    def finish(self, manifest: dict[str, Any], stats: dict[str, Any]) -> int:
        """Record the run once every page is in: depth corrections, the runs row, CHECKPOINT. Raises FeedError,
        recording nothing, when the rows do not reconcile with the spider's own count."""
        pages = stats.get("proto/pages")
        if self.closed is not None and self.closed.get("pages") != pages:
            msg = f"meta:closed says {self.closed.get('pages')} pages, the spider's stats {pages}"
            raise store.FeedError(msg)
        if not isinstance(pages, int) or self.rows + self.duplicates != pages:
            msg = (f"consumed {self.rows} rows and {self.duplicates} duplicates, the spider emitted {pages}; "
                    f"{self.db_path} keeps them, nothing recorded")
            raise store.FeedError(msg)
        corrections = (self.closed or {}).get("depth_corrections", stats.get("proto/depth_corrections", {}))
        self.con.execute("BEGIN TRANSACTION")
        try:
            for url, depth in corrections.items():
                self.con.execute("UPDATE pages SET depth = ? WHERE run_id = ? AND url = ?", [depth, self.run_id, url])
            if self.con.execute("SELECT count(*) FROM runs WHERE run_id = ?", [self.run_id]).fetchall() == [(0,)]:
                self.con.execute(store.RUNS_INSERT, store.runs_row(manifest, self.rows, self.arm, self.db_path))
            self.con.execute("COMMIT")
        except BaseException:
            self.con.execute("ROLLBACK")
            raise
        self.con.execute("CHECKPOINT")
        return self.rows

    def close(self) -> None:
        self.con.close()


class JsonlTail(Consumer):
    """The control arm: the spider's feed on the mount, line-flushed, read past the committed byte offset."""

    def __init__(self, run_id: str, db_path: Path) -> None:
        super().__init__(run_id, "jsonl-tail", db_path)
        self.feed = host_queue_dir(run_id) / "feed.jsonl"

    def tick(self) -> int:
        if not self.feed.exists():
            return 0
        offset = int(self.cursor or 0)
        with self.feed.open("rb") as f:
            f.seek(offset)
            chunk = f.read()
        end = chunk.rfind(b"\n")
        if end < 0:
            return 0  # No complete line yet: a partial line is never read.
        lines = chunk[: end + 1].splitlines()
        return self._commit([json.loads(line) for line in lines], str(offset + end + 1))

    def trailing_bytes(self) -> int:
        """Bytes past the last complete line: after the spider exited, a cut line from a crash."""
        return self.feed.stat().st_size - int(self.cursor or 0) if self.feed.exists() else 0


class RocksTail(Consumer):
    """The queue arm: a secondary instance over the guest's RocksDB, keys past the committed cursor."""

    def __init__(self, run_id: str, db_path: Path) -> None:
        super().__init__(run_id, "rocks-queue", db_path)
        self.path = host_queue_dir(run_id) / "rocks"
        self.sec: Rdict | None = None
        self.catch_up_s: list[float] = []

    def _open(self) -> Rdict | None:
        if self.sec is None and (self.path / "CURRENT").exists():
            sec_dir = SECONDARY_DIR / self.run_id
            sec_dir.mkdir(parents=True, exist_ok=True)
            self.sec = Rdict(str(self.path), Options(raw_mode=True), access_type=AccessType.secondary(str(sec_dir)))
        return self.sec

    def tick(self) -> int:
        sec = self._open()
        if sec is None:
            return 0
        t0 = time.perf_counter()
        sec.try_catch_up_with_primary()
        self.catch_up_s.append(time.perf_counter() - t0)
        start = self.cursor.encode() if self.cursor else PAGE_KEY
        items: list[dict[str, Any]] = []
        last = self.cursor
        for k, v in sec.items(from_key=start):
            if not k.startswith(PAGE_KEY):
                break
            if k.decode() == self.cursor:
                continue
            items.append(json.loads(v))
            last = k.decode()
        inserted = self._commit(items, last) if items else 0
        # Read from the same caught-up state as the pages above (a secondary moves only at a catch-up). The guest
        # writes meta:closed after its last page, so when it is visible here, every page was in that batch.
        if self.closed is None and (raw := sec.get(CLOSED_KEY)) is not None:
            self.closed = json.loads(raw)
        return inserted

    def close(self) -> None:
        if self.sec is not None:
            self.sec.close()
            self.sec = None
        super().close()




def make(arm: str, run_id: str, db_path: Path) -> Consumer:
    return JsonlTail(run_id, db_path) if arm == "jsonl-tail" else RocksTail(run_id, db_path)


# ---- the clock, and latency from the guest's fetch to the host's commit ----------------------------------

# The guest's half of ticket 07's clock probe: answer each ping on the mount with the guest's own time.
GUEST_PONG = r'''
import os, sys, time
ping, pong, rounds = sys.argv[1], sys.argv[2], int(sys.argv[3])
last = None
deadline = time.time() + 60
while time.time() < deadline:
    try:
        with open(ping) as f:
            seq = f.read().split()[0]
    except (OSError, IndexError):
        seq = None
    if seq is not None and seq != last:
        t2 = time.time()
        with open(pong + ".tmp", "w") as f:
            f.write(f"{seq} {t2}\n")
        os.replace(pong + ".tmp", pong)
        last = seq
        if int(seq) >= rounds - 1:
            break
    time.sleep(0.001)
'''
CLOCK_TABLE = "CREATE TABLE IF NOT EXISTS clock (run_id VARCHAR PRIMARY KEY, offset_s DOUBLE, err_s DOUBLE, rounds INTEGER)"


def measure_offset(mach: Machine, guest_root: str, run_id: str, rounds: int = 20) -> tuple[float, float]:
    """Guest clock minus host clock over the mount, NTP-style; the error bound is half the best round trip.
    Ticket 07 found the guest clock drifts by milliseconds over minutes, so it is taken for each run."""
    script = f"{guest_root}/pong.py"
    mach.write_file(script, GUEST_PONG)
    gdir, hdir = f"{m.QUEUE_GUEST_DIR}/{run_id}/clock", host_queue_dir(run_id) / "clock"
    mach.exec(["mkdir", "-p", gdir], ExecOptions(timeout=30))
    mach.exec(["python", script, f"{gdir}/ping", f"{gdir}/pong", str(rounds)], ExecOptions(background=True))
    time.sleep(0.5)
    samples: list[tuple[float, float]] = []
    for seq in range(rounds):
        t1 = time.time()
        (hdir / "ping.tmp").write_text(f"{seq} {t1}\n")
        (hdir / "ping.tmp").replace(hdir / "ping")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                got = (hdir / "pong").read_text().split()
            except OSError:
                got = []
            if got and got[0] == str(seq):
                t3 = time.time()
                samples.append((t3 - t1, float(got[1]) - (t1 + t3) / 2))
                break
            time.sleep(0.0005)
    if not samples:
        msg = "no clock sample over the mount"
        raise store.FeedError(msg)
    rtt, offset = min(samples)
    return offset, rtt / 2


def latency(  # noqa: PLR0913, PLR0917  prototype: the clock's three numbers ride along
    db_path: Path, run_id: str, offset: float, err: float, rounds: int, arrived: list[tuple[str, float]],
) -> str:
    """Fetch (guest clock, corrected) to host commit, over every page this process's consumer inserted. The
    commit times are taken after each COMMIT returned and written to `arrivals` here, after the summary."""
    con = duckdb.connect(str(db_path))
    try:
        con.execute(OFFSETS)
        if arrived:
            con.executemany("INSERT OR IGNORE INTO arrivals VALUES (?, ?, ?)", [[run_id, u, t] for u, t in arrived])
        con.execute(CLOCK_TABLE)
        con.execute("INSERT OR REPLACE INTO clock VALUES (?, ?, ?, ?)", [run_id, offset, err, rounds])
        row = con.execute(
            """SELECT count(*), min(d), quantile_cont(d, 0.5), quantile_cont(d, 0.95), max(d), first_d
            FROM (SELECT a.committed_at - epoch(p.fetched_at) + ? AS d,
                    min(a.committed_at) OVER () - min(epoch(p.fetched_at)) OVER () + ? AS first_d
                FROM arrivals a JOIN pages p USING (run_id, url) WHERE run_id = ?)
            GROUP BY first_d""",
            [offset, offset, run_id],
        ).fetchall()
        con.execute("CHECKPOINT")
    finally:
        con.close()
    if not row:
        return f"no arrivals recorded by this process (clock offset {offset * 1e3:+.2f} +- {err * 1e3:.2f} ms)"
    n, lo, p50, p95, hi, first = row[0]
    return (f"{n} pages, fetch -> host commit ms: min {lo * 1e3:.1f}, p50 {p50 * 1e3:.1f}, p95 {p95 * 1e3:.1f}, "
            f"max {hi * 1e3:.1f}; first fetch -> first commit {first * 1e3:.1f} ms; clock offset "
            f"{offset * 1e3:+.2f} +- {err * 1e3:.2f} ms ({rounds} rounds, taken after the run); tick {TICK_S * 1e3:.0f} ms; "
            "commit = each batch's COMMIT returned, rows visible to the consumer's connection, before CHECKPOINT and "
            "close")


def latency_bulk(db_path: Path, committed_at: float, run_id: str, offset: float, err: float, rounds: int) -> str:
    """Ticket 09: the bulk arm's equivalent. Every page becomes visible on the host at the load's one commit,
    `committed_at`, taken when that COMMIT returned (before the load's CHECKPOINT and close)."""
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            """SELECT count(*), min(d), quantile_cont(d, 0.5), quantile_cont(d, 0.95), max(d)
            FROM (SELECT ? - epoch(fetched_at) + ? AS d FROM pages WHERE run_id = ?)""",
            [committed_at, offset, run_id],
        ).fetchall()[0]
    finally:
        con.close()
    n, lo, p50, p95, hi = row
    if not n:
        return "no pages"
    return (f"{n} pages, fetch -> host visible ms: min {lo * 1e3:.1f}, p50 {p50 * 1e3:.1f}, p95 {p95 * 1e3:.1f}, "
        f"max {hi * 1e3:.1f}; first fetch -> first row {hi * 1e3:.1f} ms; clock offset {offset * 1e3:+.2f} +- "
        f"{err * 1e3:.2f} ms ({rounds} rounds, taken after the run); one commit after the load; visible = the load's "
        "COMMIT returned, rows visible to the loader's connection, before CHECKPOINT and close")

