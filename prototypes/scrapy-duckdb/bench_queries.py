"""PROTOTYPE, throwaway: ticket 05's measurements of the bulk and the per-item DuckDB stores.

Run from `prototypes/scrapy-duckdb` with `uv run --offline python bench_queries.py <mode> ...`:

- `wall -- <command ...>`: run one command, pass its output through, and print the seconds from just
    before the process is spawned to the moment its summary's `store:` line is printed.
- `compare A_DB A_RUN B_DB B_RUN`: row counts, URL and `content_hash` sets, and `html` storage segments
    of one run in each of two DuckDB files, both opened read-only.
- `bench --repeats N --urls-from DB --scratch DIR FILE ...`: point lookup by URL and full scan of `html` on each
    file, each in a fresh child process that prints its own peak RSS (`ru_maxrss`, bytes on macOS), the
    way the DuckDB study's `bench_queries.py` does. One discarded warm-up child per (query, file) first,
    then N measured rounds, the files interleaved within each round, so every file is equally warm.
- `edges DIR --rows-from DB`: the per-item path's sharp edges, measured on scratch files in DIR, which must not
    exist yet: two writers on one file, a reader beside a writer, and a writer SIGKILLed before CHECKPOINT.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import duckdb

FETCH_MANY = 64
NO_EXTENSIONS = {"autoinstall_known_extensions": False, "autoload_known_extensions": False}


def digest(text: str | None) -> None:
    """Touch every byte of a body, as a consumer would, without keeping it."""
    hashlib.sha256((text or "").encode()).digest()


# ---------------------------------------------------------------- wall ---


def wall(argv: list[str]) -> int:
    """Spawn the command, echo its output line by line, time spawn to the summary's `store:` line."""
    t0 = time.perf_counter()
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # noqa: S603  our own command
    in_summary = False
    summary_at = None
    assert proc.stdout is not None
    for line in proc.stdout:
        now = time.perf_counter()
        sys.stdout.write(line)
        sys.stdout.flush()
        if line.startswith("---- summary"):
            in_summary = True
        elif in_summary and summary_at is None and line.startswith("store: "):
            summary_at = now - t0
    code = proc.wait()
    total = time.perf_counter() - t0
    shown = f"{summary_at:.3f}s" if summary_at is not None else "no summary printed"
    print(f"[wall] process start to summary printed: {shown}; to process exit: {total:.3f}s; exit {code}")
    return code


# ------------------------------------------------------------- compare ---


def compare(a_db: Path, a_run: str, b_db: Path, b_run: str) -> int:
    """Same rows, same URLs, same content hashes? And did html land in ZSTD segments in each file?"""
    found = {}
    for label, db, run in (("A", a_db, a_run), ("B", b_db, b_run)):
        con = duckdb.connect(str(db), read_only=True, config=NO_EXTENSIONS)
        rows = con.execute("SELECT count(*) FROM pages WHERE run_id = ?", [run]).fetchall()[0][0]
        urls = {r[0] for r in con.execute("SELECT url FROM pages WHERE run_id = ?", [run]).fetchall()}
        hashes = sorted(r[0] for r in con.execute("SELECT content_hash FROM pages WHERE run_id = ?", [run]).fetchall())
        pairs = set(con.execute("SELECT url, content_hash, md5(html) FROM pages WHERE run_id = ?", [run]).fetchall())
        segs = con.execute(
            "SELECT compression, count(*) FROM pragma_storage_info('pages') WHERE column_name = 'html' "
            "GROUP BY 1 ORDER BY 1"
        ).fetchall()
        con.close()
        found[label] = (rows, urls, hashes, pairs)
        print(f"{label}: {db} run {run}: {rows} rows, {len(urls)} distinct URLs, {len(set(hashes))} distinct "
            f"content_hash; html segments {segs}")
    (ra, ua, ha, pa), (rb, ub, hb, pb) = found["A"], found["B"]
    print(f"row counts equal: {ra == rb} ({ra} vs {rb})")
    print(f"URL sets equal: {ua == ub} (only A {len(ua - ub)}, only B {len(ub - ua)})")
    print(f"content_hash multisets equal: {ha == hb}; sets equal: {set(ha) == set(hb)}")
    print(f"(url, content_hash, md5(html)) sets equal: {pa == pb}")
    return 0 if ra == rb and set(ha) == set(hb) else 1


# --------------------------------------------------------------- bench ---


def child(query: str, target: str, urls_file: str) -> None:
    """One measurement in this fresh process; prints one JSON line."""
    started = time.perf_counter()
    items = 0
    open_s = 0.0
    if query != "baseline":
        con = duckdb.connect(target, read_only=True, config=NO_EXTENSIONS)
        open_s = time.perf_counter() - started
        if query == "point":
            for url in json.loads(Path(urls_file).read_text()):
                row = con.execute("SELECT html FROM pages WHERE url = ?", [url]).fetchall()
                digest(row[0][0])
                items += 1
        else:
            cursor = con.execute("SELECT html FROM pages")
            while batch := cursor.fetchmany(FETCH_MANY):
                for (html,) in batch:
                    digest(html)
                items += len(batch)
        con.close()
    wall_s = time.perf_counter() - started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS
    print(json.dumps({"query": query, "target": target, "items": items, "wall_s": wall_s, "open_s": open_s,
        "rss_bytes": rss}))


def run_child(query: str, target: str, urls_file: str) -> dict[str, Any]:
    done = subprocess.run(  # noqa: S603  this same script
        [sys.executable, __file__, "--child", query, target, urls_file], check=True, capture_output=True, text=True,
    )
    return json.loads(done.stdout.strip().splitlines()[-1])


def spread(values: list[float]) -> str:
    return f"median {statistics.median(values):.4f}, min {min(values):.4f}, max {max(values):.4f}"


def bench(files: list[str], urls_from: str, repeats: int, scratch: Path) -> None:
    url_sets = []
    for f in [urls_from, *files]:  # Every file must hold one run with one row per URL, and the same URLs.
        con = duckdb.connect(f, read_only=True, config=NO_EXTENSIONS)
        runs, rows, distinct = con.execute(
            "SELECT count(DISTINCT run_id), count(*), count(DISTINCT url) FROM pages").fetchall()[0]
        url_sets.append({r[0] for r in con.execute("SELECT url FROM pages").fetchall()})
        con.close()
        if runs != 1 or rows != distinct:
            sys.exit(f"bench: {f} holds {runs} runs, {rows} rows, {distinct} URLs; isolate one run first "
                "(scrapyproto load <run_id> --db <run_id>-bulk.duckdb)")
    if any(s != url_sets[0] for s in url_sets):
        sys.exit("bench: the files do not hold the same URLs; point lookups would not be like for like")
    urls = sorted(url_sets[0])
    scratch.mkdir(parents=True, exist_ok=True)
    urls_file = scratch / "bench-urls.json"
    urls_file.write_text(json.dumps(urls))
    for f in files:
        print(f"file {f}: {os.path.getsize(f)} bytes; wal present: {os.path.exists(f + '.wal')}")
    print(f"point lookup: {len(urls)} URLs from {urls_from}, one SELECT html ... WHERE url = ? each")
    jobs = [("baseline", "-")] + [(q, f) for q in ("point", "scan") for f in files]
    for q, f in jobs:  # warm-up, discarded
        run_child(q, f, str(urls_file))
    results: dict[tuple[str, str], list[dict[str, Any]]] = {job: [] for job in jobs}
    for n in range(repeats):
        order = jobs if n % 2 == 0 else [jobs[0], *reversed(jobs[1:])]  # alternate which file goes first
        for q, f in order:
            r = run_child(q, f, str(urls_file))
            results[(q, f)].append(r)
            print(json.dumps(r))
    print(f"\n{repeats} measured runs each, after one discarded warm-up run; a fresh process per run")
    for (q, f), rs in results.items():
        walls = [r["wall_s"] for r in rs]
        opens = [r["open_s"] for r in rs]
        rss = [r["rss_bytes"] / 2**20 for r in rs]
        print(f"{q:8} {Path(f).name}: items {rs[0]['items']}; wall s {spread(walls)}; open s {spread(opens)}; "
            f"peak RSS MiB {spread(rss)}")


# --------------------------------------------------------------- edges ---




def edge_child(role: str, path: str, rows_from: str) -> None:
    """The writer and the probes that run beside it, each in its own process."""
    if role in {"writer", "crash"}:
        from scrapyproto import store  # noqa: PLC0415  only the children that write need it

        src = duckdb.connect(rows_from, read_only=True, config=NO_EXTENSIONS)
        rows = src.execute(
            "SELECT run_id, url, final_url, status, content_type, depth, referrer, outlinks, "
            "CAST(fetched_at AS VARCHAR), content_hash, html FROM pages ORDER BY fetched_at"
        ).fetchall()
        src.close()
        con = duckdb.connect(path, config=NO_EXTENSIONS)
        con.execute(store.SCHEMA)
        for row in rows:  # One autocommit INSERT per page, as the pipeline does.
            con.execute(
                "INSERT OR IGNORE INTO pages (run_id, url, final_url, status, content_type, depth, referrer, "
                "outlinks, fetched_at, content_hash, html) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS TIMESTAMPTZ), "
                "?, ?)",
                list(row),
            )
        print(f"inserted {len(rows)}", flush=True)
        sys.stdin.readline()  # Hold the file open, uncheckpointed, until the parent kills or releases us.
        con.close()
        return
    try:
        con = duckdb.connect(path, read_only=(role == "reader"), config=NO_EXTENSIONS)
        n = con.execute("SELECT count(*) FROM pages").fetchall()[0][0]
        con.close()
        print(f"{role}: opened, {n} rows")
    except duckdb.Error as exc:
        print(f"{role}: {type(exc).__name__}: {' '.join(str(exc).split())[:300]}")


def spawn(role: str, path: Path, rows_from: str, *, stdin: bool = False) -> subprocess.Popen[str]:
    return subprocess.Popen(  # noqa: S603  this same script
        [sys.executable, __file__, "--edge", role, str(path), rows_from],
        stdin=subprocess.PIPE if stdin else None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def listing(d: Path) -> str:
    return ", ".join(f"{p.name} {p.stat().st_size}" for p in sorted(d.iterdir())) or "(empty)"


def count_rows(path: Path) -> str:
    try:
        con = duckdb.connect(str(path), read_only=True, config=NO_EXTENSIONS)
        pages = con.execute("SELECT count(*) FROM pages").fetchall()[0][0]
        runs = con.execute("SELECT count(*) FROM runs").fetchall()[0][0]
        con.close()
    except duckdb.Error as exc:
        return f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}"
    return f"pages {pages}, runs {runs}"


def edges(scratch: Path, rows_from: str) -> None:
    if scratch.exists():
        sys.exit(f"edges: {scratch} exists; name a new directory (nothing is deleted)")
    scratch.mkdir(parents=True)
    print(f"rows from {rows_from}; duckdb {duckdb.__version__} on the host")

    print("\n1. One writer per file: a writer holds the file, uncheckpointed; then a second writer, a reader")
    d = scratch / "one-writer"
    d.mkdir()
    path = d / "pages.duckdb"
    w = spawn("writer", path, rows_from, stdin=True)
    assert w.stdout is not None
    print("writer:", w.stdout.readline().strip(), "| files:", listing(d))
    for role in ("second-writer", "reader"):
        p = spawn(role, path, rows_from)
        print(p.communicate()[0].strip())
    assert w.stdin is not None
    w.stdin.write("\n")
    w.stdin.flush()
    w.wait()
    print("after the writer closed without CHECKPOINT:", listing(d), "|", count_rows(path))

    print("\n2. A crash: the writer is SIGKILLed after its inserts, before any runs row or CHECKPOINT")
    d = scratch / "crash"
    d.mkdir()
    path = d / "pages.duckdb"
    w = spawn("crash", path, rows_from, stdin=True)
    assert w.stdout is not None
    print("writer:", w.stdout.readline().strip())
    w.send_signal(signal.SIGKILL)
    w.wait()
    print(f"killed (exit {w.returncode}); files left:", listing(d))
    alone = scratch / "crash-file-only"
    alone.mkdir()
    shutil.copy(path, alone / "pages.duckdb")
    print("the .duckdb alone, as a pull of that one file would get it:", count_rows(alone / "pages.duckdb"))
    print("the .duckdb with its .wal beside it (opened read-only):", count_rows(path))
    print("files after that read-only open:", listing(d))
    con = duckdb.connect(str(path), config=NO_EXTENSIONS)
    con.close()
    print("after a read-write open and close:", listing(d), "|", count_rows(path))


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(*sys.argv[2:5])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--edge":
        edge_child(*sys.argv[2:5])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "wall":
        argv = sys.argv[2:]
        sys.exit(wall(argv[1:] if argv[:1] == ["--"] else argv))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("a_db", type=Path)
    cmp_.add_argument("a_run")
    cmp_.add_argument("b_db", type=Path)
    cmp_.add_argument("b_run")
    b = sub.add_parser("bench")
    b.add_argument("--repeats", type=int, default=7)
    b.add_argument("--urls-from", required=True)
    b.add_argument("--scratch", type=Path, required=True)
    b.add_argument("files", nargs="+")
    e = sub.add_parser("edges")
    e.add_argument("scratch", type=Path)
    e.add_argument("--rows-from", required=True)
    args = parser.parse_args()
    if args.mode == "compare":
        sys.exit(compare(args.a_db, args.a_run, args.b_db, args.b_run))
    if args.mode == "bench":
        bench(args.files, args.urls_from, args.repeats, args.scratch)
    else:
        edges(args.scratch, args.rows_from)


if __name__ == "__main__":
    main()
