"""Ticket 07 spike: RocksDB across the smol host mount, guest primary to host secondary.

    uv run --offline python -u spike_rocks.py clock        # guest/host clock offset over the mount
    uv run --offline python -u spike_rocks.py visible      # probe 1: put -> host-visible, three write modes
    uv run --offline python -u spike_rocks.py lock         # probe 2: LOCK and fsync on the mount
    uv run --offline python -u spike_rocks.py crash        # probe 3: writer SIGKILLed mid-write
    uv run --offline python -u spike_rocks.py jsonl        # probe 4: JSONL append -> host tail
    uv run --offline python -u spike_rocks.py all

Needs `rocks-proto` running (`scrapyproto vm up`). No network: nothing here fetches anything. Every probe writes
under `/queue/spike/<probe>-<stamp>/` (host: `ai_tmp/scrapy-duckdb/queue/spike/...`) and deletes nothing.
Latencies are host receive time minus guest write time, corrected by the offset `clock` measures; the offset's
uncertainty (half the best round trip) is printed beside every latency.
"""

import json
import statistics
import sys
import time
from pathlib import Path

from rocksdict import AccessType, DBCompressionType, Options, Rdict
from smol import ExecOptions, Machine

from scrapyproto import machine as m
from scrapyproto import state

GUEST_DIR = "/root/rocks-spike"  # Guest disk, persistent; the scripts live here, never on the mount.
SPIKE_GUEST = f"{m.QUEUE_GUEST_DIR}/spike"
SPIKE_HOST = m.QUEUE_HOST_DIR / "spike"
PAGE_BYTES = 75_000  # About ticket 03's mean page: 1880793 bytes over 25 pages.
TIMEOUT_S = 120.0

GUEST_COMMON = r'''
import json, os, random, signal, sys, time

def page(i, size):
    """HTML-like text of about `size` bytes: templated, as doc pages are, with some per-page variety."""
    rnd = random.Random(i)
    parts = []
    n = 0
    while n < size:
        word = "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rnd.randint(3, 9)))
        s = f'<div class="row"><a href="/en-us/graph/api/{word}-{rnd.randint(0, 999)}">{word}</a> <p>The {word} resource.</p></div>\n'
        parts.append(s)
        n += len(s)
    return "".join(parts)[:size]
'''

GUEST_WRITER = GUEST_COMMON + r'''
from rocksdict import DBCompressionType, Options, Rdict, WriteOptions

db, n, pace, size, log, kill_after, mode = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]), sys.argv[5], int(sys.argv[6]), sys.argv[7]
o = Options(raw_mode=True)
o.create_if_missing(True)
o.set_compression_type(DBCompressionType.zstd())
d = Rdict(db, o)
wo = WriteOptions()
wo.sync = mode == "sync"
bodies = [page(i, size) for i in range(min(n, 50))]
with open(log, "w") as L:
    print(f"open {time.time()}", file=L, flush=True)
    for i in range(n):
        t = time.time()
        d.put(b"p:%012d" % i, json.dumps({"i": i, "t_put": t, "html": bodies[i % len(bodies)]}).encode(), wo)
        if mode == "flushwal":
            d.flush_wal(True)
        print(f"acked {i} {time.time()}", file=L, flush=True)
        if i + 1 == kill_after:
            os.kill(os.getpid(), signal.SIGKILL)
        if pace:
            time.sleep(pace)
    d.put(b"meta:closed", json.dumps({"pages": n, "t": time.time()}).encode(), wo)
    d.close()
    print(f"closed {time.time()}", file=L, flush=True)
'''

GUEST_JSONL = GUEST_COMMON + r'''
path, n, pace, size, log = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
bodies = [page(i, size) for i in range(min(n, 50))]
with open(path, "a", encoding="utf-8") as f, open(log, "w") as L:
    for i in range(n):
        f.write(json.dumps({"i": i, "t_put": time.time(), "html": bodies[i % len(bodies)]}) + "\n")
        f.flush()  # To the OS, as a line-flushed exporter would; no fsync.
        print(f"acked {i} {time.time()}", file=L, flush=True)
        if pace:
            time.sleep(pace)
    print(f"closed {time.time()}", file=L, flush=True)
'''

GUEST_PONG = r'''
import os, sys, time
ping, pong, rounds = sys.argv[1], sys.argv[2], int(sys.argv[3])
last = None
deadline = time.time() + 120
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

GUEST_LOCK = r'''
import sys
from rocksdict import Options, Rdict
o = Options(raw_mode=True)
try:
    d = Rdict(sys.argv[1], o)
    print("second primary in the guest: OPENED (no lock)")
    d.close()
except Exception as exc:
    print(f"second primary in the guest: refused: {type(exc).__name__}: {exc}")
'''


def say(text: str) -> None:
    print(text, flush=True)


def sh(mach: Machine, script: str, timeout: float = 60.0) -> str:
    r = mach.exec(["sh", "-c", script], ExecOptions(timeout=timeout))
    if r.exit_code != 0:
        say(f"  [exit {r.exit_code}] {script[:200]}\n  {r.stderr.strip()[-400:]}")
    return r.stdout


def writers(mach: Machine, gdir: str) -> tuple[list[str], list[str]]:
    """Guest processes whose argv names `gdir`/db: (python writers, every match). Raises when the scan
    itself fails, so an empty list means none, never that the scan could not run. A SIGKILLed writer not
    yet reaped is a zombie with an empty cmdline, so it counts as dead, as it is."""
    script = (f"for p in /proc/[0-9]*; do c=$(tr '\\0' ' ' < $p/cmdline 2>/dev/null) || continue; "
                f"case \"$c\" in *\"{gdir}/db\"*) echo \"${{p#/proc/}} $c\";; esac; done; echo scan-ok")
    r = mach.exec(["sh", "-c", script], ExecOptions(timeout=60.0))
    lines = r.stdout.splitlines()
    if r.exit_code != 0 or not lines or lines[-1] != "scan-ok":
        msg = f"guest process scan failed: exit {r.exit_code}, stdout {r.stdout[-300:]!r}, stderr {r.stderr[-300:]!r}"
        raise RuntimeError(msg)
    found = lines[:-1]
    # The scan's own `sh -c` line names the db too; only the writer's argv starts with python.
    return [line for line in found if line.split(" ", 1)[-1].startswith("python ")], found


def setup(mach: Machine) -> None:
    sh(mach, f"mkdir -p {GUEST_DIR} {SPIKE_GUEST}")
    for name, src in (("writer.py", GUEST_WRITER), ("jsonl.py", GUEST_JSONL), ("pong.py", GUEST_PONG),
                        ("lock.py", GUEST_LOCK)):
        mach.write_file(f"{GUEST_DIR}/{name}", src)


def fresh(probe: str) -> tuple[str, Path]:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-{time.monotonic_ns() % 10000:04d}"
    return f"{SPIKE_GUEST}/{probe}-{stamp}", SPIKE_HOST / f"{probe}-{stamp}"


def wait_for(path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > deadline:
            msg = f"{path} did not appear on the host in {timeout} s"
            raise TimeoutError(msg)
        time.sleep(0.002)


# ---- clock ----------------------------------------------------------------------------------------------


def clock(mach: Machine, rounds: int = 30) -> tuple[float, float]:
    """Offset = guest clock - host clock, NTP-style over the mount: the host writes ping (t1), the guest's
    poller writes pong (t2), the host sees it (t3). The best round trip bounds the error by half of it."""
    gdir, hdir = fresh("clock")
    sh(mach, f"mkdir -p {gdir}")
    wait_for(hdir)
    ping, pong = hdir / "ping", hdir / "pong"
    mach.exec(["python", f"{GUEST_DIR}/pong.py", f"{gdir}/ping", f"{gdir}/pong", str(rounds)],
                ExecOptions(background=True))
    time.sleep(0.5)
    samples = []
    for seq in range(rounds):
        t1 = time.time()
        tmp = hdir / "ping.tmp"
        tmp.write_text(f"{seq} {t1}\n")
        tmp.replace(ping)
        deadline = time.monotonic() + 5
        while True:
            try:
                got = pong.read_text().split()
            except OSError:
                got = []
            if got and got[0] == str(seq):
                t3 = time.time()
                break
            if time.monotonic() > deadline:
                say(f"  round {seq}: no pong in 5 s")
                t3 = None
                break
            time.sleep(0.0005)
        if t3 is not None:
            samples.append((t3 - t1, float(got[1]) - (t1 + t3) / 2))
    if not samples:
        msg = "no clock sample"
        raise RuntimeError(msg)
    rtts = sorted(s[0] for s in samples)
    best = min(samples)
    say(f"[clock] {len(samples)}/{rounds} rounds over the mount; round trip ms: min {rtts[0] * 1e3:.2f}, "
        f"median {statistics.median(rtts) * 1e3:.2f}, max {rtts[-1] * 1e3:.2f}")
    say(f"[clock] offset (guest - host) at the best round trip: {best[1] * 1e3:+.2f} ms, "
        f"+- {best[0] / 2 * 1e3:.2f} ms; median over rounds {statistics.median(s[1] for s in samples) * 1e3:+.2f} ms")
    return best[1], best[0] / 2


# ---- probe 1 and 3: guest primary, host secondary ------------------------------------------------------


def secondary(host_db: Path, sec: Path) -> Rdict:
    return Rdict(str(host_db), Options(raw_mode=True), access_type=AccessType.secondary(str(sec)))


def follow(mach: Machine, mode: str, n: int, pace: float, offset: float, err: float, *, kill_after: int = 0,
            tick: float = 0.01) -> dict[str, object]:
    """Start a guest writer, follow it from the host as a secondary, report latency and what was seen."""
    gdir, hdir = fresh(f"{mode}-{'crash' if kill_after else 'follow'}")
    sh(mach, f"mkdir -p {gdir}")
    log = f"{GUEST_DIR}/{hdir.name}.log"
    t_start = time.time()
    mach.exec(["python", f"{GUEST_DIR}/writer.py", f"{gdir}/db", str(n), str(pace), str(PAGE_BYTES), log,
                str(kill_after), mode], ExecOptions(background=True))
    wait_for(hdir / "db" / "CURRENT")
    t_open = time.time()
    sec = None
    deadline = time.monotonic() + TIMEOUT_S
    while sec is None:  # The first open can race the primary's own creation of its MANIFEST.
        try:
            sec = secondary(hdir / "db", hdir / "secondary")
        except Exception as exc:  # noqa: BLE001  prototype: report and retry
            if time.monotonic() > deadline:
                raise
            last = exc
            time.sleep(0.01)
    say(f"[{mode}] secondary open {t_open - t_start:.3f}s after launch (host clock)")
    if kill_after:
        # Positive control: the scan crash() trusts to say the writer is dead must see it while it lives.
        live, found = writers(mach, gdir)
        if not live:
            msg = f"the process scan cannot see the live writer; matches: {found}. Not trusting it after the kill"
            raise RuntimeError(msg)
        say(f"[{mode}] process scan sees the live writer: {live}")
    seen: dict[int, float] = {}
    lat: list[float] = []
    closed = False
    cursor = b"p:"
    catch_s: list[float] = []
    while time.monotonic() < deadline:
        t0 = time.perf_counter()
        sec.try_catch_up_with_primary()
        catch_s.append(time.perf_counter() - t0)
        now = time.time()
        for k, v in sec.items(from_key=cursor):
            if k == cursor:
                continue
            if k.startswith(b"meta:"):
                continue
            if not k.startswith(b"p:"):
                break
            rec = json.loads(v)
            if rec["i"] not in seen:
                seen[rec["i"]] = now
                lat.append(now - (rec["t_put"] - offset))
            cursor = k
        if sec.get(b"meta:closed") is not None:
            closed = True
            break
        if kill_after and len(seen) >= kill_after:
            time.sleep(1.0)  # Let any straggler land, then one more catch-up below.
            sec.try_catch_up_with_primary()
            seen_after = sum(1 for k in sec.keys(from_key=b"p:") if k.startswith(b"p:"))
            say(f"[{mode}] after the kill and 1 s more: {seen_after} keys via the secondary")
            break
        time.sleep(tick)
    sec.close()
    acked = [line for line in sh(mach, f"cat {log}").splitlines() if line.startswith("acked")]
    say(f"[{mode}] n {n}, pace {pace}s, page {PAGE_BYTES} B: guest acked {len(acked)}, host saw {len(seen)}, "
        f"meta:closed seen {closed}")
    if lat:
        q = statistics.quantiles(lat, n=20) if len(lat) >= 20 else [min(lat)] * 19
        say(f"[{mode}] put -> host-visible ms (offset +- {err * 1e3:.2f}): min {min(lat) * 1e3:.2f}, "
            f"p50 {statistics.median(lat) * 1e3:.2f}, p95 {q[18] * 1e3:.2f}, max {max(lat) * 1e3:.2f}; "
            f"poll tick {tick * 1e3:.0f} ms; catch-up call ms p50 {statistics.median(catch_s) * 1e3:.2f}, "
            f"max {max(catch_s) * 1e3:.2f}")
    files = sorted((p.name, p.stat().st_size) for p in (hdir / "db").iterdir())
    say(f"[{mode}] host-side db files: {files}")
    return {"gdir": gdir, "hdir": hdir, "acked": len(acked), "seen": len(seen), "lat": lat, "log": log}


def visible(mach: Machine, offset: float, err: float) -> None:
    for mode in ("plain", "flushwal", "sync"):
        follow(mach, mode, n=200, pace=0.05, offset=offset, err=err)
    say("[burst] no pace, plain mode: how far the host lags a writer going flat out")
    follow(mach, "plain", n=200, pace=0.0, offset=offset, err=err)


# ---- probe 2: LOCK and fsync ---------------------------------------------------------------------------


def lock(mach: Machine) -> None:
    gdir, hdir = fresh("lock")
    sh(mach, f"mkdir -p {gdir}")
    log = f"{GUEST_DIR}/{hdir.name}.log"
    # A writer that holds the db open for about 10 s, every put fsynced (WriteOptions.sync).
    mach.exec(["python", f"{GUEST_DIR}/writer.py", f"{gdir}/db", "100", "0.1", "1000", log, "0", "sync"],
                ExecOptions(background=True))
    wait_for(hdir / "db" / "CURRENT")
    time.sleep(1.0)
    say("[lock] " + sh(mach, f"python {GUEST_DIR}/lock.py {gdir}/db").strip())
    say(f"[lock] guest LOCK holders: {sh(mach, f'cat /proc/locks | wc -l; ls -l {gdir}/db/LOCK').strip()}")
    # Host read-write open of the same throwaway db while the guest holds it: does the lock cross virtiofs?
    try:
        d = Rdict(str(hdir / "db"), Options(raw_mode=True))
        say("[lock] host read-write open while the guest holds LOCK: OPENED. The lock does not cross the mount")
        d.close()
    except Exception as exc:  # noqa: BLE001  prototype: the outcome is what is measured
        say(f"[lock] host read-write open while the guest holds LOCK: refused: {type(exc).__name__}: "
            f"{' '.join(str(exc).split())[:300]}")
    deadline = time.monotonic() + 30
    while "closed" not in sh(mach, f"cat {log}") and time.monotonic() < deadline:
        time.sleep(0.5)
    tail = sh(mach, f"tail -n 2 {log}").strip().replace("\n", " | ")
    say(f"[lock] fsynced writer finished: {tail}")


# ---- probe 3: crash -------------------------------------------------------------------------------------


def crash(mach: Machine, offset: float, err: float) -> None:
    r = follow(mach, "plain", n=200, pace=0.02, offset=offset, err=err, kill_after=100)
    hdir: Path = r["hdir"]  # type: ignore[assignment]
    # The host must not open the db read-write while a guest writer may live: the lock does not cross the
    # mount (probe 2). Wait a bounded time for the writer to be gone; otherwise stop before any open.
    deadline = time.monotonic() + 10
    live, _ = writers(mach, r["gdir"])  # type: ignore[arg-type]
    while live and time.monotonic() < deadline:
        time.sleep(0.5)
        live, _ = writers(mach, r["gdir"])  # type: ignore[arg-type]
    say(f"[crash] writer processes left in the guest: {live or 'none'}")
    if live:
        sys.exit("[crash] the writer is still alive; refusing the host secondary and read-write open")
    files = sorted((p.name, p.stat().st_size) for p in (hdir / "db").iterdir())
    say(f"[crash] host-side files after the kill: {files}")
    fresh_sec = secondary(hdir / "db", hdir / "secondary-after")
    keys = [k for k in fresh_sec.keys(from_key=b"p:") if k.startswith(b"p:")]
    say(f"[crash] a fresh host secondary: {len(keys)} keys, meta:closed {fresh_sec.get(b'meta:closed') is not None}")
    fresh_sec.close()
    rw = Rdict(str(hdir / "db"), Options(raw_mode=True))
    keys = [k for k in rw.keys(from_key=b"p:") if k.startswith(b"p:")]
    contiguous = all(k == b"p:%012d" % i for i, k in enumerate(keys))
    say(f"[crash] host read-write open (WAL recovery on the host): {len(keys)} keys, contiguous from 0: "
        f"{contiguous}; guest acked {r['acked']}")
    rw.close()
    files = sorted((p.name, p.stat().st_size) for p in (hdir / "db").iterdir())
    say(f"[crash] host-side files after the host's recovery open and close: {files}")


# ---- probe 4: JSONL tail --------------------------------------------------------------------------------


def jsonl(mach: Machine, offset: float, err: float, pace: float = 0.05, n: int = 200) -> None:
    gdir, hdir = fresh("jsonl")
    sh(mach, f"mkdir -p {gdir}")
    log = f"{GUEST_DIR}/{hdir.name}.log"
    mach.exec(["python", f"{GUEST_DIR}/jsonl.py", f"{gdir}/feed.jsonl", str(n), str(pace), str(PAGE_BYTES), log],
                ExecOptions(background=True))
    feed = hdir / "feed.jsonl"
    wait_for(feed)
    pos = 0
    buf = b""
    lat: list[float] = []
    partial_reads = 0
    deadline = time.monotonic() + TIMEOUT_S
    while len(lat) < n and time.monotonic() < deadline:
        with feed.open("rb") as f:
            f.seek(pos)
            chunk = f.read()
        now = time.time()
        if chunk:
            pos += len(chunk)
            buf += chunk
            *lines, buf = buf.split(b"\n")
            if buf:
                partial_reads += 1
            for line in lines:
                lat.append(now - (json.loads(line)["t_put"] - offset))
        time.sleep(0.01)
    say(f"[jsonl] n {n}, pace {pace}s: host read {len(lat)} complete lines; reads that ended mid-line "
        f"{partial_reads}")
    if lat:
        q = statistics.quantiles(lat, n=20)
        say(f"[jsonl] write -> host-visible ms (offset +- {err * 1e3:.2f}): min {min(lat) * 1e3:.2f}, "
            f"p50 {statistics.median(lat) * 1e3:.2f}, p95 {q[18] * 1e3:.2f}, max {max(lat) * 1e3:.2f}; poll 10 ms")


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    # As cli._running_or_fail: only this checkout's machine, only already running; nothing is written before.
    saved = state.load()
    found = m.open_existing()
    if found is None:
        sys.exit(f"no machine {m.MACHINE_NAME}; `scrapyproto vm up` first")
    if not m.owned(saved):
        sys.exit(f"{m.MACHINE_NAME}: no state file at {state.path()} records this machine; refusing to attach")
    now = found.state()
    if now != "running":
        sys.exit(f"{m.MACHINE_NAME} is {now}; `scrapyproto vm up` first")
    mach = m.connect_owned()  # Owned and running, checked above: attaches without a boot.
    setup(mach)
    say(f"[spike] {m.MACHINE_NAME}; guest rocksdict {m.rocksdict_version(mach)}; host mount {m.QUEUE_HOST_DIR}")
    say(f"[spike] guest mount line: {sh(mach, 'grep \" /queue \" /proc/mounts | head -n 1').strip()}")
    if what == "lock":
        lock(mach)
        return
    offset, err = clock(mach)
    if what in {"visible", "all"}:
        visible(mach, offset, err)
    if what in {"lock", "all"}:
        lock(mach)
    if what in {"crash", "all"}:
        crash(mach, offset, err)
    if what in {"jsonl", "all"}:
        jsonl(mach, offset, err)
    if what == "clock":
        return


if __name__ == "__main__":
    main()
