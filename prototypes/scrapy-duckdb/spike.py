"""Ticket 01 spike: Scrapy in a smol microVM, its feed read back on the host.

    uv run python -u spike.py          # boot or reconnect, install, crawl example.com, stop
    uv run python -u spike.py --probes # the exec, stop and second-process measurements
    uv run python -u spike.py --output-cap  # how much output exec carries; background across stop
    uv run python -u spike.py --long   # exec against a command that outlives 10 minutes

Every path that connects ends by stopping (never deleting) scrapy-proto and printing the state block. The
single example.com fetch happens once: a rerun finds the guest's feed and re-reads it. The
only delete in this file is of the separate throwaway machine `collision_probe` creates.
"""

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time

from smol import ExecOptions, Machine, MachineConfig, ConnectOptions, SmolError

from scrapyproto import machine as m, state

FEED = "/out/feed.jsonl"
SPIDER_PATH = "/spike/one_page.py"
BIG = "/out/big.bin"
BIG_BYTES = 20 * 1024 * 1024
STOP_MARK = "/out/written-before-stop"
PROBE_DIR = "/out/probes"
COLLISION_MACHINE = "scrapy-proto-collision-probe"

SPIDER = """\
from datetime import datetime, timezone

import scrapy


class OnePage(scrapy.Spider):
    name = "one_page"
    allowed_domains = ["example.com"]
    start_urls = ["https://example.com"]
    # `runspider` has no project, so these are set here; Scrapy's own default obeys nothing.
    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": "scrapy-duckdb-prototype/0.0 (rovo prototype; single-page spike)",
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 1.0,
        "CLOSESPIDER_PAGECOUNT": 1,
        "CLOSESPIDER_TIMEOUT": 120,  # The guest-side guard, inside the exec timeout.
        "RETRY_ENABLED": False,
        "TELNETCONSOLE_ENABLED": False,
    }

    def parse(self, response):
        yield {
            "url": response.url,
            "status": response.status,
            "title": response.css("title::text").get(),
            "content_type": response.headers.get("Content-Type", b"").decode(),
            "html_bytes": len(response.body),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
"""


def say(text: str) -> None:
    print(text, flush=True)


def sh(mach: Machine, script: str, timeout: float = 60.0) -> str:
    """Run a guest shell line; returns stdout, and prints a failure rather than raising."""
    r = mach.exec(["sh", "-c", script], ExecOptions(timeout=timeout))
    if r.exit_code != 0:
        say(f"  [exit {r.exit_code}] {script}\n  {r.stderr.strip()[-300:]}")
    return r.stdout


def finish(mach: Machine | None) -> None:
    """Stop, never delete, then print the state block last."""
    if mach is not None:
        t0 = time.monotonic()
        try:
            mach.stop()
            say(f"[time] stop: {time.monotonic() - t0:.1f}s")
        except SmolError as exc:
            say(f"stop failed: {exc.code}: {exc}")
    say("---- state ----")
    say(m.state_block(mach))


# ---- the main path ---------------------------------------------------------------------------


def boot() -> tuple[Machine, bool] | None:
    existing = m.open_existing()
    saved = state.load()
    if existing is not None and saved is None:
        say(f"{m.MACHINE_NAME} exists ({existing.state()}) with no state file here: another "
            "checkout's? Refusing to touch it.")
        say(m.state_block(existing))
        return None
    t0 = time.monotonic()
    if existing is not None:
        say(f"{m.MACHINE_NAME} exists ({existing.state()}); connecting")
        try:
            mach = m.connect_existing()
        except m.ProtoError as exc:
            # The state file is here but names another generation: another checkout's machine.
            say(str(exc))
            say(m.state_block(existing))
            return None
        say(f"[time] connect: {time.monotonic() - t0:.1f}s; state={mach.state()}")
        return mach, False
    say(f"creating {m.MACHINE_NAME} from {m.IMAGE} with {m.RESOURCES}")
    mach = m.create()
    # Only after create returns: the state file is this checkout's claim, and a create that failed
    # or lost the name claims nothing. A crash in between leaves no file, so the next boot refuses.
    state.save({"machine": m.MACHINE_NAME, "image": m.IMAGE, "scrapy": m.SCRAPY_VERSION, "rung": None})
    say(f"[time] create (image pull and boot): {time.monotonic() - t0:.1f}s; state={mach.state()}")
    time.sleep(5)
    say(f"state 5s after create: {mach.state()} (the image's CMD is python3, which exits on EOF)")
    return mach, True


def describe_guest(mach: Machine) -> None:
    say("---- guest ----")
    say(sh(mach, "uname -a; python --version; pip --version; id; pwd; echo PATH=$PATH"))
    say(sh(mach, "df -h / /usr/local /tmp /var/lib 2>&1; echo; mount | grep -v -E 'proc|sysfs|cgroup|devpts|tmpfs'"))


def ensure_scrapy(mach: Machine) -> None:
    try:
        version = m.scrapy_version(mach)
    except (SmolError, RuntimeError) as exc:
        say(f"scrapy not present yet ({exc}); ladder rung 1: pip install scrapy=={m.SCRAPY_VERSION}")
        t0 = time.monotonic()
        tail = m.install_scrapy(mach)
        say(f"[time] pip install: {time.monotonic() - t0:.1f}s\n{tail}")
        version = m.scrapy_version(mach)
        saved = state.load() or {}
        state.save({**saved, "rung": "1: python:3.12 plus pip install"})
        say(sh(mach, "pip show scrapy | grep -E '^(Name|Version|Location)'; du -sh /usr/local/lib/python3.12/site-packages"))
    else:
        say(f"scrapy already installed, no pip run: {version}")
    if version != m.SCRAPY_VERSION:
        msg = f"guest has scrapy {version}, the pin is {m.SCRAPY_VERSION}"
        raise RuntimeError(msg)


def survive_stop_connect(mach: Machine) -> Machine:
    """Unknown 3: the install and an unsynced file across stop, then connect."""
    say("---- stop then connect ----")
    nonce = os.urandom(8).hex()
    # Written with no sync: stop alone must keep it.
    mach.write_file(STOP_MARK, nonce)
    t0 = time.monotonic()
    mach.stop()
    say(f"[time] stop: {time.monotonic() - t0:.1f}s; state={mach.state()}")
    t0 = time.monotonic()
    mach = m.connect_existing()
    say(f"[time] connect from stopped: {time.monotonic() - t0:.1f}s; state={mach.state()}")
    say(f"scrapy version after stop then connect: {m.scrapy_version(mach)}")
    back = mach.read_file(STOP_MARK).decode()
    say(f"unsynced file after stop then connect: {'intact' if back == nonce else f'WRONG: {back!r}'}")
    say("guest uptime: " + sh(mach, "cut -d' ' -f1 /proc/uptime").strip() + "s (a fresh boot is small)")
    return mach


def crawl_once(mach: Machine) -> None:
    say("---- the one-page spider ----")
    exists = mach.exec(["test", "-s", FEED]).exit_code == 0
    if exists:
        say(f"{FEED} is already on the guest: not fetching example.com again")
    else:
        sh(mach, "mkdir -p /out /spike")
        mach.write_file(SPIDER_PATH, SPIDER)
        t0 = time.monotonic()
        r = mach.exec(
            ["scrapy", "runspider", SPIDER_PATH, "-O", f"{FEED}:jsonlines", "-s", "LOG_LEVEL=INFO"],
            ExecOptions(timeout=180),
        )
        say(f"[time] scrapy runspider: {time.monotonic() - t0:.1f}s; exit {r.exit_code}")
        say(f"---- scrapy stderr ----\n{r.stderr}")
    t0 = time.monotonic()
    raw = mach.read_file(FEED)
    say(f"[time] read_file feed: {time.monotonic() - t0:.3f}s for {len(raw)} bytes")
    lines = raw.decode().splitlines()
    say(f"items in feed: {len(lines)}")
    for line in lines:
        say(json.dumps(json.loads(line), indent=2))


def feed_round_trip(mach: Machine) -> None:
    """Unknown 2: 20 MB of incompressible bytes, three reads, a hash each time."""
    say("---- read_file 20 MB ----")
    t0 = time.monotonic()
    guest = sh(mach, f"head -c {BIG_BYTES} /dev/urandom > {BIG} && sha256sum {BIG}").split()[0]
    say(f"[time] guest write and hash: {time.monotonic() - t0:.1f}s; guest sha256 {guest}")
    for i in range(3):
        t0 = time.monotonic()
        data = mach.read_file(BIG)
        secs = time.monotonic() - t0
        host = hashlib.sha256(data).hexdigest()
        say(f"[time] read {i + 1}: {secs:.3f}s, {len(data) / 1e6 / secs:.1f} MB/s, {len(data)} bytes, "
            f"hash {'matches' if host == guest else f'DIFFERS: {host}'}")
    sh(mach, f"rm -f {BIG}")


def main_path() -> int:
    started = time.monotonic()
    booted = boot()
    if booted is None:
        return 2
    mach, _created = booted
    ok = False
    try:
        describe_guest(mach)
        ensure_scrapy(mach)
        sh(mach, "mkdir -p /out /spike")
        mach = survive_stop_connect(mach)
        crawl_once(mach)
        feed_round_trip(mach)
        ok = True
    except (SmolError, RuntimeError, ValueError, IndexError) as exc:
        say(f"FAILED: {type(exc).__name__}: {exc}")
    say(f"[time] whole spike, up to the final stop: {time.monotonic() - started:.1f}s")
    finish(mach)
    return 0 if ok else 1


# ---- the exec measurements (`--probes`, `--long`) ----------------------------------------------


def ticker(tag: str, n: int, every: int = 1) -> str:
    """A shell loop that prints a guest timestamp to stdout and stderr, n times."""
    return (f'i=0; while [ $i -lt {n} ]; do echo "{tag} out $i $(date +%s.%N)"; '
            f'echo "{tag} err $i" >&2; i=$((i+1)); sleep {every}; done')


def probe_blocking(mach: Machine) -> None:
    say("---- exec, blocking, no timeout, 20 s of output ----")
    beats = []
    done = threading.Event()

    def heartbeat() -> None:
        while not done.wait(0.5):
            beats.append(time.monotonic())

    threading.Thread(target=heartbeat, daemon=True).start()
    t0 = time.monotonic()
    r = mach.exec(["sh", "-c", ticker("block", 20)])
    secs = time.monotonic() - t0
    done.set()
    say(f"returned after {secs:.1f}s, exit {r.exit_code}, {len(r.stdout.splitlines())} stdout lines, "
        f"{len(r.stderr.splitlines())} stderr lines; the API gives nothing before it returns")
    say(f"host thread beats during the call: {len(beats)} of about {int(secs / 0.5)} (the call releases the GIL if close)")


def probe_timeout(mach: Machine) -> None:
    say("---- exec with timeout=5 on a 60 s command: signal, partial output, children ----")
    d = f"{PROBE_DIR}/timeout"
    script = (
        f"mkdir -p {d}; rm -f {d}/*; trap 'echo term > {d}/got-term; exit 143' TERM; "
        f"(sleep 300; touch {d}/child-outlived) & echo $! > {d}/child-pid; "
        f"echo before-timeout; echo before-timeout-err >&2; touch {d}/started; "
        f"sleep 60 & wait $!; touch {d}/finished"
    )
    t0 = time.monotonic()
    try:
        r = mach.exec(["sh", "-c", script], ExecOptions(timeout=5))
    except SmolError as exc:
        say(f"after {time.monotonic() - t0:.1f}s raised {type(exc).__name__} code={exc.code}: {exc}")
        for attr in ("stdout", "stderr", "exit_code"):
            say(f"  exc.{attr} = {getattr(exc, attr, '(no such attribute)')!r}")
    else:
        say(f"after {time.monotonic() - t0:.1f}s returned exit {r.exit_code}, "
            f"stdout={r.stdout!r} stderr={r.stderr!r}")
    time.sleep(3)
    say(f"files: {sh(mach, f'ls {d}').split()}")
    say("children still alive: " + sh(mach, f"cat {d}/child-pid | xargs -I P sh -c 'kill -0 P 2>/dev/null && echo yes || echo no'").strip())
    say("guest ps:\n" + sh(mach, "ps -eo pid,ppid,etime,args | grep -v -E 'ps -eo|grep' | tail -12"))


def probe_stream(mach: Machine) -> None:
    say("---- exec_stream, 20 s: does each line arrive when printed? ----")
    t0 = time.time()
    lags = []
    kinds = {}
    with mach.exec_stream(["sh", "-c", ticker("stream", 20)]) as stream:
        for event in stream:
            now = time.time()
            kinds[event["kind"]] = kinds.get(event["kind"], 0) + 1
            if event["kind"] == "stdout":
                for line in event["data"].splitlines():
                    lags.append(now - float(line.split()[-1]))
            elif event["kind"] in ("exit", "error"):
                say(f"terminal event: {event}")
    say(f"took {time.time() - t0:.1f}s; events {kinds}; print-to-host lag in s: min {min(lags):.3f}, "
        f"max {max(lags):.3f} (includes guest and host clock skew)")


def probe_large_output(mach: Machine) -> None:
    """How much output exec carries. The first --probes run hit a wall at 11 MiB and exit 141."""
    mib = 1024 * 1024
    say("---- exec and exec_stream: output size against exit code ----")

    def fill(stream: str, n: int) -> str:
        redirect = " >&2" if stream == "stderr" else ""
        return f"head -c {n} /dev/zero | tr '\\\\0' x{redirect}; echo \"pipestatus-end $?\" > /out/cap-mark"

    for stream, size in (("stdout", 5), ("stdout", 10), ("stdout", 11), ("stdout", 12), ("stdout", 30), ("stderr", 12)):
        sh(mach, "rm -f /out/cap-mark")
        t0 = time.monotonic()
        r = mach.exec(["sh", "-c", fill(stream, size * mib)], ExecOptions(timeout=120))
        mark = mach.exec(["sh", "-c", "cat /out/cap-mark"]).stdout.strip()
        say(f"exec {stream} {size} MiB: {time.monotonic() - t0:.2f}s exit {r.exit_code}, got stdout {len(r.stdout)} "
            f"stderr {len(r.stderr)} chars, script ran to its end: {mark or 'NO'}")
    both = f"head -c {8 * mib} /dev/zero | tr '\\\\0' x; head -c {8 * mib} /dev/zero | tr '\\\\0' y >&2"
    r = mach.exec(["sh", "-c", both], ExecOptions(timeout=120))
    say(f"exec 8 MiB stdout then 8 MiB stderr: exit {r.exit_code}, stdout {len(r.stdout)}, stderr {len(r.stderr)} chars")
    t0 = time.monotonic()
    got, final = 0, None
    with mach.exec_stream(["sh", "-c", fill("stdout", 30 * mib)]) as stream:
        for event in stream:
            if event["kind"] == "stdout":
                got += len(event["data"])
            elif event["kind"] in ("exit", "error"):
                final = event
    say(f"exec_stream stdout 30 MiB: {time.monotonic() - t0:.2f}s, {got} chars, terminal {final}")


def probe_background_stop(mach: Machine) -> Machine:
    say("---- a background command across stop then connect ----")
    d = f"{PROBE_DIR}/bg-stop"
    sh(mach, f"mkdir -p {d}; rm -f {d}/*")
    r = mach.exec(["sh", "-c", f"(sleep 15; echo ok) > {d}/log 2>&1; echo $? > {d}/done"], ExecOptions(background=True))
    time.sleep(2)
    say(f"started pid {r.pid}")
    mach.stop()
    mach = m.connect_existing()
    time.sleep(16)
    say(f"16 s after connect: files {sh(mach, f'ls {d}').split()}; pid {r.pid} alive: "
        + sh(mach, f"kill -0 {r.pid} 2>/dev/null && echo yes || echo no").strip())
    return mach


def output_cap() -> int:
    mach = m.connect_existing()
    try:
        probe_large_output(mach)
        mach = probe_background_stop(mach)
    finally:
        finish(mach)
    return 0


def bg_start_child() -> int:
    """A separate host process that starts a background command and exits at once."""
    mach = m.connect_existing()
    d = f"{PROBE_DIR}/bg"
    sh(mach, f"mkdir -p {d}; rm -f {d}/*")
    script = f"(sleep 20; echo line-from-bg; exit 7) > {d}/log 2>&1; echo $? > {d}/done.tmp; mv {d}/done.tmp {d}/done"
    t0 = time.monotonic()
    r = mach.exec(["sh", "-c", script], ExecOptions(background=True))
    say(f"background exec returned in {time.monotonic() - t0:.3f}s with pid {r.pid}, exit_code {r.exit_code}; host process exits now")
    return 0


def probe_background(mach: Machine) -> None:
    say("---- background=True, started by a process that then exits, polled from this one ----")
    t0 = time.monotonic()
    subprocess.run([sys.executable, "-u", __file__, "--bg-start-child"], check=True)
    d = f"{PROBE_DIR}/bg"
    polls = 0
    while mach.exec(["test", "-f", f"{d}/done"]).exit_code != 0 and time.monotonic() - t0 < 60:
        polls += 1
        time.sleep(2)
    say(f"done marker after {time.monotonic() - t0:.1f}s and {polls} polls: "
        f"exit recorded {sh(mach, f'cat {d}/done').strip()}, log {sh(mach, f'cat {d}/log').strip()!r}")


def crash_child(kind: str) -> int:
    mach = m.connect_existing()
    d = f"{PROBE_DIR}/crash-{kind}"
    sh(mach, f"mkdir -p {d}; rm -f {d}/*")
    script = f"echo $$ > {d}/pid; i=0; while [ $i -lt 20 ]; do echo $i >> {d}/ticks; i=$((i+1)); sleep 1; done; touch {d}/finished"
    if kind == "exec":
        mach.exec(["sh", "-c", script], ExecOptions(timeout=300))
    else:
        for _ in mach.exec_stream(["sh", "-c", script]):
            pass
    return 0


def probe_crash(mach: Machine, kind: str) -> None:
    say(f"---- SIGKILL the host process during a running {kind}: machine, guest command ----")
    child = subprocess.Popen([sys.executable, "-u", __file__, "--crash-child", kind])
    d = f"{PROBE_DIR}/crash-{kind}"
    time.sleep(6)
    child.send_signal(signal.SIGKILL)
    child.wait()
    ticks_at_kill = sh(mach, f"wc -l < {d}/ticks").strip()
    say(f"host process killed; machine state {mach.state()}; ticks so far {ticks_at_kill}")
    time.sleep(22)
    say(f"22 s later: ticks {sh(mach, f'wc -l < {d}/ticks').strip()} of 20; files {sh(mach, f'ls {d}').split()}")
    again = m.connect_existing()
    say(f"fresh connect after the crash: state {again.state()}, scrapy {m.scrapy_version(again)}")


def second_process_child() -> int:
    t0 = time.monotonic()
    mach = m.connect_existing()
    say(f"  second process: connect {time.monotonic() - t0:.2f}s; state {mach.state()}; scrapy {m.scrapy_version(mach)}")
    say(f"  second process: reads a file: {mach.read_file(FEED)[:40]!r}")
    return 0


def probe_second_process(mach: Machine) -> None:
    say("---- a second process connects by name during a running exec ----")
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["result"] = mach.exec(["sh", "-c", "sleep 12; echo first-process-exec-finished"])
        except SmolError as exc:
            box["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(2)
    subprocess.run([sys.executable, "-u", __file__, "--second-process-child"], check=True)
    thread.join()
    result = box.get("result")
    say(f"first process's exec: {result.stdout.strip() if result else box.get('error')!r}")


def collision_probe() -> None:
    """Creating a taken name, on a throwaway bare machine so scrapy-proto is not what is at risk."""
    say(f"---- Machine.create on a taken name, using the throwaway {COLLISION_MACHINE} ----")
    local = ConnectOptions(target="local")
    config = MachineConfig(name=COLLISION_MACHINE, persistent=True, detach=True)
    first = Machine.create(config, local)
    try:
        first.write_file("/root/marker", "kept")
        try:
            Machine.create(config, local)
        except SmolError as exc:
            say(f"second create raised {type(exc).__name__} code={exc.code}: {exc}")
        else:
            say("second create did NOT raise")
        say(f"marker after the second create: {first.read_file('/root/marker')!r}")
    finally:
        first.delete()
        say(f"{COLLISION_MACHINE} deleted (this is the one delete in the spike, and not scrapy-proto)")


def probe_stop_during_exec(mach: Machine) -> Machine:
    say("---- stop() while a command is running, then connect ----")
    box: dict[str, object] = {}
    d = f"{PROBE_DIR}/stop"

    def run() -> None:
        t0 = time.monotonic()
        try:
            box["result"] = mach.exec(["sh", "-c", f"mkdir -p {d}; rm -f {d}/*; echo partial; touch {d}/started; sleep 60; touch {d}/finished"])
        except SmolError as exc:
            box["error"] = f"{type(exc).__name__} code={exc.code}: {exc}"
        box["secs"] = time.monotonic() - t0

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(3)
    t0 = time.monotonic()
    mach.stop()
    say(f"[time] stop during exec: {time.monotonic() - t0:.1f}s; state {mach.state()}")
    thread.join()
    say(f"the running exec, after {box['secs']:.1f}s: {box.get('error') or box.get('result')}")
    t0 = time.monotonic()
    mach = m.connect_existing()
    say(f"[time] connect: {time.monotonic() - t0:.1f}s; files {sh(mach, f'ls {d}').split()}; scrapy {m.scrapy_version(mach)}")
    return mach


def probe_disk_placement(mach: Machine) -> Machine:
    """Which guest paths keep a file across stop then connect, and where the writable layer lives."""
    say("---- which paths survive stop then connect ----")
    paths = ["/out/place-mark", "/usr/local/place-mark", "/var/lib/place-mark", "/root/place-mark", "/tmp/place-mark", "/workspace/place-mark"]
    for p in paths:
        mach.write_file(p, "kept")
    mach.stop()
    mach = m.connect_existing()
    for p in paths:
        say(f"{p}: {'kept' if mach.exec(['test', '-f', p]).exit_code == 0 else 'GONE'}")
    sh(mach, "rm -f " + " ".join(paths))
    say(sh(mach, "findmnt -no SOURCE,FSTYPE /storage; ls /storage/overlays 2>&1; du -sh /storage/overlays/*/upper 2>&1; df -h /storage | tail -1"))
    return mach


def probe_scrapy_source(mach: Machine) -> None:
    """Two things the first run's log raised, read from the installed Scrapy; no network."""
    say("---- installed Scrapy: remote control and the page count ----")
    pkg = "/usr/local/lib/python3.12/site-packages/scrapy"
    say(sh(mach, f"grep -n -i 'REMOTE_CONTROL' {pkg}/settings/default_settings.py"))
    say(sh(mach, f"grep -n -E 'response_received|page_count|PAGECOUNT|def ' {pkg}/extensions/closespider.py | head -30"))
    say(sh(mach, f"grep -n -E 'response_received|def ' {pkg}/core/engine.py | grep -n -B1 -A1 response_received"))
    say(sh(mach, f"grep -n -E 'engine.download|download_async|DOWNLOAD_PRIORITY' {pkg}/downloadermiddlewares/robotstxt.py"))


def probes() -> int:
    mach = m.connect_existing()
    try:
        sh(mach, f"mkdir -p {PROBE_DIR}")
        probe_scrapy_source(mach)
        mach = probe_disk_placement(mach)
        probe_blocking(mach)
        probe_timeout(mach)
        probe_stream(mach)
        probe_large_output(mach)
        probe_background(mach)
        probe_crash(mach, "exec")
        probe_crash(mach, "stream")
        probe_second_process(mach)
        collision_probe()
        mach = probe_stop_during_exec(mach)
    finally:
        finish(mach)
    return 0


def long_probe() -> int:
    """One 11-minute command at once in each mode: silent, chatty, raised timeout, streamed, background."""
    seconds = 660
    mach = m.connect_existing()
    d = f"{PROBE_DIR}/long"
    sh(mach, f"mkdir -p {d}; rm -f {d}/*")
    results: dict[str, str] = {}

    def timed(name: str, call) -> None:
        t0 = time.monotonic()
        try:
            results[name] = f"{call()} after {time.monotonic() - t0:.1f}s"
        except SmolError as exc:
            results[name] = f"{type(exc).__name__} code={exc.code} after {time.monotonic() - t0:.1f}s: {exc}"
        say(f"{name}: {results[name]}")

    def blocking(script: str, opts: ExecOptions | None):
        def call() -> str:
            r = mach.exec(["sh", "-c", script], opts)
            return f"exit {r.exit_code}, {len(r.stdout.splitlines())} stdout lines"
        return call

    def streamed() -> str:
        last, events = 0.0, 0
        gaps = 0.0
        final = None
        with mach.exec_stream(["sh", "-c", ticker("long", seconds // 5, 5)]) as stream:
            for event in stream:
                now = time.monotonic()
                gaps = max(gaps, now - last) if last else 0.0
                last, events = now, events + 1
                if event["kind"] in ("exit", "error"):
                    final = event
        return f"{final}, {events} events, largest gap {gaps:.1f}s"

    threads = [
        threading.Thread(target=timed, args=("blocking silent, no timeout", blocking(f"sleep {seconds}; echo done", None))),
        threading.Thread(target=timed, args=("blocking chatty, no timeout", blocking(ticker("chatty", seconds // 5, 5), None))),
        threading.Thread(target=timed, args=("blocking silent, timeout=900", blocking(f"sleep {seconds}; echo done", ExecOptions(timeout=900)))),
        threading.Thread(target=timed, args=("exec_stream chatty", streamed)),
    ]
    say(f"---- four {seconds} s commands at once, and one in the background ----")
    bg = mach.exec(["sh", "-c", f"({ticker('bg', seconds // 5, 5)}) > {d}/bg.log 2>&1; echo $? > {d}/bg.done"], ExecOptions(background=True))
    say(f"background pid {bg.pid}")
    t0 = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    say(f"[time] all four: {time.monotonic() - t0:.1f}s")
    say(f"background: done marker {sh(mach, f'cat {d}/bg.done').strip()!r}, log lines {sh(mach, f'wc -l < {d}/bg.log').strip()}")
    finish(mach)
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args == ["--probes"]:
        return probes()
    if args == ["--long"]:
        return long_probe()
    if args == ["--output-cap"]:
        return output_cap()
    if args == ["--bg-start-child"]:
        return bg_start_child()
    if args[:1] == ["--crash-child"]:
        return crash_child(args[1])
    if args == ["--second-process-child"]:
        return second_process_child()
    return main_path()


if __name__ == "__main__":
    sys.exit(main())
