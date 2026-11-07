"""Ticket 03's guest side: render the spider, its settings and the wrapper, start them and watch the run.

The run design comes from ticket 01's measurements. Blocking `exec` returns nothing until exit, caps
captured output at 11 MiB and dies with the host process, so the crawl runs with `background=True`:
the wrapper writes the guest's boot id, its own pid, Scrapy's whole output to a per-run log and, last,
the exit code to a `done` marker through a temp file and `mv`. Everything lives under `/out`, which
survives a stop; `/tmp` does not. A stop or reboot kills the run and leaves no marker, so the poller
reads "no marker" as running only while the recorded boot id is current and the recorded pid still runs
this run's wrapper. `background=True` takes no timeout: `CLOSESPIDER_TIMEOUT` is the guest-side guard
and the host keeps its own deadline past it.
"""

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from smol import ExecOptions, Machine, SmolError

from scrapyproto import machine as m

GUEST_ROOT = "/out/scrapyproto"
RUNS_DIR = f"{GUEST_ROOT}/runs"
CACHE_DIR = f"{GUEST_ROOT}/httpcache"  # Shared by every run, so `--replay` reads what a live run stored.
LOCK = f"{GUEST_ROOT}/crawl.lock"  # A symlink naming the run that holds it: `ln -s` fails if it exists.
FLOCK = f"{GUEST_ROOT}/.lock-take"  # Serialises the check-and-take of LOCK between host processes.
SPIDER_FILE = "proto_spider.py"  # `runspider` imports it as module `proto_spider`; the middleware path uses that.

USER_AGENT = f"scrapy-duckdb-prototype/0.0 (rovo prototype crawler; Scrapy {m.SCRAPY_VERSION}; robots.txt obeyed)"
DOWNLOAD_DELAY_S = 1.0
CONCURRENCY = 2
POLL_EVERY_S = 5.0
PROGRESS_EVERY_S = 30.0
DEADLINE_GRACE_S = 120.0  # The host deadline is CLOSESPIDER_TIMEOUT plus this.
KILL_GRACE_S = 30.0
STALE_LOCK_S = 120  # A lock whose run never wrote a pid is stale after this long.
EXEC_TIMEOUT_S = 60.0


def closespider_timeout(max_pages: int) -> int:
    """The guest-side wall-clock guard: generous for a 1 s delay, two at a time, one retry each."""
    return 120 + 8 * max_pages


@dataclass(frozen=True)
class Plan:
    """One crawl's inputs; everything the guest receives is rendered from this."""

    run_id: str
    start_urls: list[str]
    allowed_hosts: list[str]
    max_pages: int
    replay: bool

    @property
    def run_dir(self) -> str:
        return f"{RUNS_DIR}/{self.run_id}"

    @property
    def feed(self) -> str:
        return f"{self.run_dir}/feed.jsonl"

    def scope(self) -> dict[str, object]:
        """The `runs.scope` JSON, in `CrawlScope`'s words where it has them."""
        return {
            "start_urls": self.start_urls,
            "allowed_hosts": self.allowed_hosts,
            "max_pages": self.max_pages,
            "replay": self.replay,
            "delay_s": DOWNLOAD_DELAY_S,
            "concurrency": CONCURRENCY,
            "user_agent": USER_AGENT,
        }


def new_run_id() -> str:
    """Sortable and unique enough for one machine: UTC time to the second plus 4 random hex digits."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + os.urandom(2).hex()


def plan(run_id: str, start_urls: list[str], allowed_hosts: list[str], max_pages: int, *, replay: bool) -> Plan:
    """Validate the flags into a plan; raises ValueError naming the bad flag."""
    if not start_urls:
        msg = "--start-url is required"
        raise ValueError(msg)
    hosts: list[str] = []
    for url in start_urls:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            msg = f"--start-url must be an absolute http(s) URL: {url!r}"
            raise ValueError(msg)
        hosts.append(parts.hostname.lower())
    allowed = sorted({h.lower().strip() for h in allowed_hosts}) if allowed_hosts else sorted(set(hosts))
    outside = [u for u, h in zip(start_urls, hosts, strict=True) if h not in allowed]
    if outside:
        msg = f"--start-url outside the allowed hosts {allowed}: {outside}"
        raise ValueError(msg)
    if not 1 <= max_pages <= 1000:  # noqa: PLR2004  the prototype's own ceiling
        msg = f"--max-pages must be 1 to 1000, got {max_pages}"
        raise ValueError(msg)
    return Plan(run_id, list(start_urls), allowed, max_pages, replay)


def settings(p: Plan) -> dict[str, object]:
    """Scrapy's settings for the run. The spider adds only its downloader middleware to these."""
    return {
        # Politeness. robots.txt is always obeyed; there is no flag to turn it off.
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": USER_AGENT,
        "CONCURRENT_REQUESTS": CONCURRENCY,
        "CONCURRENT_REQUESTS_PER_DOMAIN": CONCURRENCY,
        "DOWNLOAD_DELAY": DOWNLOAD_DELAY_S,
        # Scrapy 2.20 jitters the delay by +-50% by default (0.5 s to 1.5 s); none, so no gap is under 1 s.
        "DOWNLOAD_DELAY_JITTER": 0.0,
        "AUTOTHROTTLE_ENABLED": False,
        "COOKIES_ENABLED": False,
        # Bounds per request: 30 s, not the default 180 s, and 10 MiB, not the default 1 GiB.
        "DOWNLOAD_TIMEOUT": 30,
        "DOWNLOAD_MAXSIZE": 10 * 1024 * 1024,
        "DOWNLOAD_WARNSIZE": 5 * 1024 * 1024,
        "REDIRECT_MAX_TIMES": 5,
        # One retry, and never on 429 or 503: the default list has both, with no Retry-After. A 429 or
        # 503 page is recorded and closes the spider instead (see the spider's parse).
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 1,
        "RETRY_HTTP_CODES": [408, 500, 502, 504, 522, 524],
        # Every status reaches the spider and the feed, so "pages by status" counts 4xx and 5xx too.
        # It does not stop redirects: RedirectMiddleware only skips handle_httpstatus_* meta.
        "HTTPERROR_ALLOW_ALL": True,
        # The page cap is enforced in the spider. These are backstops only: PAGECOUNT counts robots.txt
        # responses too (one per host), so it is the cap plus the hosts; ITEMCOUNT is the cap itself.
        "CLOSESPIDER_PAGECOUNT": p.max_pages + len(p.allowed_hosts),
        "CLOSESPIDER_ITEMCOUNT": p.max_pages,
        "CLOSESPIDER_TIMEOUT": closespider_timeout(p.max_pages),
        # The cache on the guest disk captures the run for `--replay`. DummyPolicy (the default) stores
        # every response, robots.txt included, and serves it without revalidation; nothing expires.
        "HTTPCACHE_ENABLED": True,
        "HTTPCACHE_DIR": CACHE_DIR,
        "HTTPCACHE_EXPIRATION_SECS": 0,
        "HTTPCACHE_IGNORE_HTTP_CODES": [429, 503],
        # A replay drops any request not in the cache instead of fetching it.
        "HTTPCACHE_IGNORE_MISSING": p.replay,
        "FEEDS": {p.feed: {"format": "jsonlines", "encoding": "utf8", "overwrite": True}},
        "FEED_EXPORT_ENCODING": "utf-8",
        # Nothing in the guest listens: Scrapy 2.20 starts a remote-control HTTP server by default.
        "REMOTE_CONTROL_ENABLED": False,
        "TELNETCONSOLE_ENABLED": False,
        "LOG_LEVEL": "INFO",
    }


def config(p: Plan) -> dict[str, object]:
    """What the spider reads besides the settings."""
    return {
        "run_id": p.run_id,
        "start_urls": p.start_urls,
        "allowed_hosts": p.allowed_hosts,
        "max_pages": p.max_pages,
        "replay": p.replay,
        "stats_path": f"{p.run_dir}/stats.json",
    }


SPIDER_TEMPLATE = '''\
"""PROTOTYPE spider rendered by scrapyproto for one run: a same-host breadth-first crawl from the seeds.

The page cap is enforced here, not by CLOSESPIDER_PAGECOUNT: a request is issued only while
pages yielded plus requests in flight stay under max_pages, so at most max_pages pages are yielded.
A request that ends without a page (filtered, robots-forbidden, failed, or a redirect onto a URL already
fetched) gives its slot back, and total requests issued by the spider stop at twice the cap.
"""

import hashlib
import json
import os
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urldefrag, urlsplit

import scrapy
from scrapy import signals
from scrapy.exceptions import CloseSpider, DontCloseSpider, IgnoreRequest
from scrapy.http import HtmlResponse, TextResponse
from scrapy.linkextractors import LinkExtractor

CONFIG = json.loads(__CONFIG__)
SETTINGS = json.loads(__SETTINGS__)
THROTTLED = (429, 503)


def on_host(url, hosts):
    """Exact host match on http(s): the offsite middleware also allows subdomains, this does not."""
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and (parts.hostname or "") in hosts


class Guard:
    """Downloader middleware placed after robots.txt (100). It sees every request the downloader gets,
    redirects, retries and robots.txt requests included, and drops one that is off the allowed hosts
    (so a subdomain redirect never fetches that subdomain's robots.txt), or a page request whose host's
    robots.txt did not arrive with a status under 500 (fail closed: Scrapy itself allows everything when
    robots.txt cannot be fetched)."""

    def __init__(self, crawler):
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_request(self, request, spider=None):
        spider = self.crawler.spider
        stats = self.crawler.stats
        if not on_host(request.url, spider.allowed_hosts):
            stats.inc_value("proto/guard/off_host")
            raise IgnoreRequest(f"off the allowed hosts: {request.url}")
        if request.meta.get("is_robotstxt_request"):
            return None
        status = spider.robots_status.get(urlsplit(request.url).netloc)
        if status is None or status >= 500 or status == 429:
            stats.inc_value("proto/guard/robots_unavailable")
            raise IgnoreRequest(f"robots.txt unavailable ({status}) for {request.url}")
        return None


class ProtoSpider(scrapy.Spider):
    name = "proto"  # Fixed: HTTPCACHE_SCOPE "spider" keys the cache by it, so replays find it.
    custom_settings = {**SETTINGS, "DOWNLOADER_MIDDLEWARES": {"proto_spider.Guard": 110}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.allowed_hosts = set(CONFIG["allowed_hosts"])
        self.allowed_domains = list(CONFIG["allowed_hosts"])
        self.max_pages = CONFIG["max_pages"]
        self.max_requests = 2 * self.max_pages
        self.frontier = deque()  # (url, depth, referrer), in discovery order: breadth first
        self.seen = set()
        self.in_flight = 0
        self.pages = 0
        self.issued = 0
        self.robots_status = {}
        self.throttled = None
        self.links = LinkExtractor(unique=True)

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.robots_parsed, signal=signals.robots_parsed)
        crawler.signals.connect(spider.request_dropped, signal=signals.request_dropped)
        crawler.signals.connect(spider.idle, signal=signals.spider_idle)
        return spider

    def robots_parsed(self, robotparser, request, response):
        netloc = urlsplit(request.url).netloc
        self.robots_status[netloc] = response.status
        self.crawler.stats.set_value(f"proto/robots_status/{netloc}", response.status)

    def enqueue(self, url, depth, referrer):
        key = urldefrag(url)[0]
        if key in self.seen or not on_host(key, self.allowed_hosts):
            return
        self.seen.add(key)
        self.frontier.append((key, depth, referrer))

    def drain(self):
        """Issue requests from the frontier while the cap allows."""
        while (
            self.frontier
            and self.throttled is None
            and self.pages + self.in_flight < self.max_pages
            and self.issued < self.max_requests
        ):
            url, depth, referrer = self.frontier.popleft()
            self.in_flight += 1
            self.issued += 1
            yield scrapy.Request(
                url,
                callback=self.parse,
                errback=self.failed,
                headers={"Referer": referrer} if referrer else None,
                meta={"proto_depth": depth},
            )

    async def start(self):
        for url in CONFIG["start_urls"]:
            self.enqueue(url, 0, None)
        for request in self.drain():
            yield request

    def parse(self, response):
        self.in_flight -= 1
        self.pages += 1
        self.seen.add(urldefrag(response.url)[0])
        is_html = isinstance(response, HtmlResponse)
        outlinks = [link.url for link in self.links.extract_links(response)] if is_html else []
        referrer = response.request.headers.get("Referer")
        content_type = response.headers.get("Content-Type")
        yield {
            "url": response.meta.get("redirect_urls", [response.url])[0],
            "final_url": response.url,
            "status": response.status,
            "content_type": content_type.decode("latin-1") if content_type else None,
            "depth": response.meta["proto_depth"],
            "referrer": referrer.decode("latin-1") if referrer else None,
            "outlinks": outlinks,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "content_hash": hashlib.sha256(response.body).hexdigest(),
            # Decoded with the page's declared or sniffed encoding; undecodable bytes become U+FFFD.
            "html": response.text if isinstance(response, TextResponse) else None,
        }
        if response.status in THROTTLED:
            self.throttled = response.status
            raise CloseSpider(f"throttled_{response.status}")
        if response.status == 200 and is_html:
            for url in outlinks:
                self.enqueue(url, response.meta["proto_depth"] + 1, response.url)
        yield from self.drain()

    def failed(self, failure):
        self.in_flight -= 1
        self.crawler.stats.inc_value(f"proto/failed/{failure.type.__name__}")
        self.logger.info("no page: %s: %s", failure.type.__name__, failure.request.url)
        yield from self.drain()

    def request_dropped(self, request, spider=None):
        """The scheduler's duplicate filter drops a redirect onto a URL already fetched, with no errback."""
        if "proto_depth" in request.meta:
            self.in_flight -= 1
            self.crawler.stats.inc_value("proto/dropped")

    def idle(self, spider=None):
        """Nothing is in flight now; reconcile the count and issue more if the cap and frontier allow."""
        self.in_flight = 0
        issued = False
        for request in self.drain():
            self.crawler.engine.crawl(request)
            issued = True
        if issued:
            raise DontCloseSpider

    def closed(self, reason):
        stats = self.crawler.stats
        stats.set_value("proto/close_reason", reason)
        stats.set_value("proto/pages", self.pages)
        stats.set_value("proto/requests_issued", self.issued)
        stats.set_value("proto/frontier_left", len(self.frontier))
        path = CONFIG["stats_path"]
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(stats.get_stats(), f, default=str, indent=1, sort_keys=True)
        os.replace(path + ".tmp", path)
'''


def spider_source(p: Plan) -> str:
    """The spider module, with the run's config and settings as JSON string literals."""
    return SPIDER_TEMPLATE.replace("__CONFIG__", repr(json.dumps(config(p)))).replace(
        "__SETTINGS__", repr(json.dumps(settings(p), indent=1)),
    )


def wrapper_source(p: Plan) -> str:
    """The guest shell script `background=True` runs: markers first, the crawl, then the done marker."""
    d = p.run_dir
    return f"""\
#!/bin/sh
# PROTOTYPE wrapper for run {p.run_id}. Started with exec(background=True); nothing here is in /tmp.
cd {d} || exit 90
date -u +%s.%N > started.at
cat /proc/sys/kernel/random/boot_id > boot_id.tmp && mv boot_id.tmp boot_id
echo $$ > pid.tmp && mv pid.tmp pid
scrapy runspider {d}/{SPIDER_FILE} > {d}/crawl.log 2>&1
code=$?
date -u +%s.%N > finished.at
echo $code > done.tmp && mv done.tmp done
# Release the lock only if this run still holds it.
[ "$(readlink {LOCK})" = "{p.run_id}" ] && rm -f {LOCK}
exit $code
"""


def launch_argv(p: Plan) -> list[str]:
    return ["sh", f"{p.run_dir}/run.sh"]


# The liveness test, shared by the poller and the lock's staleness check. Prints one line:
# `done <code>`, `alive`, `starting <age s>` (no pid yet) or `dead <why>`.
STATUS_FN = r"""
run_status() {
    d=__RUNS__/$1
    if [ -f "$d/done" ]; then echo "done $(cat "$d/done")"; return; fi
    if [ ! -f "$d/pid" ]; then
        if [ -d "$d" ]; then echo "starting $(( $(date +%s) - $(stat -c %Y "$d") ))"; else echo "dead no-run-dir"; fi
        return
    fi
    if [ "$(cat "$d/boot_id" 2>/dev/null)" != "$(cat /proc/sys/kernel/random/boot_id)" ]; then
        echo "dead rebooted"; return
    fi
    pid=$(cat "$d/pid")
    if tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -qF -- "$1/run.sh"; then echo alive
    else echo "dead gone"; fi
}
""".replace("__RUNS__", RUNS_DIR)


def acquire_script(run_id: str) -> str:
    """Take the crawl lock for run_id, under flock; prints `taken`, `busy <run> <status>` or `stale ...`."""
    return f"""
set -u
mkdir -p {GUEST_ROOT}
{STATUS_FN}
exec 9>{FLOCK}
flock -w 30 9 || {{ echo "busy unknown flock-timeout"; exit 0; }}
if [ -L {LOCK} ]; then
    holder=$(readlink {LOCK})
    st=$(run_status "$holder")
    case "$st" in
        alive*) echo "busy $holder $st"; exit 0;;
        starting*) age=${{st#starting }}; if [ "$age" -lt {STALE_LOCK_S} ]; then echo "busy $holder $st"; exit 0; fi;;
    esac
    echo "stale $holder $st"
    rm -f {LOCK}
fi
ln -s {run_id} {LOCK} && echo taken
"""


def release_script(run_id: str) -> str:
    return f'[ "$(readlink {LOCK})" = "{run_id}" ] && rm -f {LOCK}; true'


def poll_script(p: Plan) -> str:
    return f"""{STATUS_FN}
st=$(run_status {p.run_id})
lines=$(wc -l < {p.feed} 2>/dev/null || echo 0)
echo "$st|$lines"
"""


def kill_script(p: Plan) -> str:
    """TERM Scrapy (the wrapper's child) so the wrapper still writes `done`; KILL after a grace."""
    return f"""{STATUS_FN}
pid=$(cat {p.run_dir}/pid 2>/dev/null) || exit 0
[ "$(run_status {p.run_id})" = alive ] || exit 0
pkill -TERM -P "$pid"; i=0
while [ $i -lt {int(KILL_GRACE_S)} ] && [ ! -f {p.run_dir}/done ]; do sleep 1; i=$((i+1)); done
[ -f {p.run_dir}/done ] || pkill -KILL -P "$pid"
"""


def render(p: Plan) -> str:
    """Everything the host would put in the guest and run, as one text, for review; no machine call."""
    rule = "-" * 100
    return "\n".join([
        f"# scrapyproto crawl, rendered for review (run id {p.run_id}; a real crawl draws a fresh one)",
        f"# start_urls={p.start_urls} allowed_hosts={p.allowed_hosts} max_pages={p.max_pages} replay={p.replay}",
        f"# CLOSESPIDER_TIMEOUT={closespider_timeout(p.max_pages)} s; host deadline "
        f"{closespider_timeout(p.max_pages) + DEADLINE_GRACE_S:.0f} s; poll every {POLL_EVERY_S:.0f} s",
        "",
        rule,
        "## Order of host calls (exec and write_file on scrapy-proto)",
        rule,
        "1. refuse unless scrapy-proto exists, is this checkout's (state file generation) and is running",
        f"2. exec: mkdir -p {p.run_dir} {CACHE_DIR}",
        f"3. write_file {p.run_dir}/{SPIDER_FILE} and {p.run_dir}/run.sh (below)",
        f"4. exec: take the lock {LOCK} under flock (script below); refuse if another run is alive",
        f"5. exec(background=True): {' '.join(launch_argv(p))}",
        "6. poll with one exec per interval until `done`, `dead` or the host deadline; on the deadline, TERM",
        "   Scrapy, wait, KILL",
        f"7. read_file {p.feed}, stats.json and crawl.log; bulk-load the feed into DuckDB on the host",
        "",
        rule,
        "## Settings (Scrapy), as rendered into the spider",
        rule,
        json.dumps(settings(p), indent=2),
        "",
        rule,
        f"## {p.run_dir}/{SPIDER_FILE}",
        rule,
        spider_source(p),
        rule,
        f"## {p.run_dir}/run.sh",
        rule,
        wrapper_source(p),
        rule,
        "## lock: take (exec, blocking, before launch)",
        rule,
        acquire_script(p.run_id),
        rule,
        "## poll (exec, once per interval)",
        rule,
        poll_script(p),
        rule,
        "## kill on the host deadline (exec)",
        rule,
        kill_script(p),
    ])


# ---- running it --------------------------------------------------------------------------------------


@dataclass
class Outcome:
    """What the host learned about the run."""

    exit_code: int | None = None  # None: no done marker (dead, killed with no marker, or unknown)
    why: str = ""
    started_epoch: float | None = None
    finished_epoch: float | None = None
    stats: dict[str, object] = field(default_factory=dict)
    log: bytes = b""
    feed: bytes | None = None


def sh(mach: Machine, script: str, timeout: float = EXEC_TIMEOUT_S) -> tuple[int, str, str]:
    r = mach.exec(["sh", "-c", script], ExecOptions(timeout=timeout))
    return r.exit_code, r.stdout, r.stderr


def prepare(mach: Machine, p: Plan) -> None:
    code, _, err = sh(mach, f"mkdir -p {p.run_dir} {CACHE_DIR}")
    if code != 0:
        msg = f"mkdir in the guest exited {code}: {err.strip()[-300:]}"
        raise RuntimeError(msg)
    mach.write_file(f"{p.run_dir}/{SPIDER_FILE}", spider_source(p))
    mach.write_file(f"{p.run_dir}/run.sh", wrapper_source(p))


def acquire(mach: Machine, p: Plan) -> str:
    """Take the lock; returns the script's report. Raises when another run holds it."""
    _, out, err = sh(mach, acquire_script(p.run_id))
    lines = out.strip().splitlines()
    if not lines or lines[-1] != "taken":
        msg = f"another crawl holds {LOCK} on the guest: {out.strip() or err.strip()}"
        raise RuntimeError(msg)
    return out.strip()


def release(mach: Machine, p: Plan) -> None:
    sh(mach, release_script(p.run_id))


def launch(mach: Machine, p: Plan) -> int | None:
    r = mach.exec(launch_argv(p), ExecOptions(background=True))
    return r.pid


def _epoch(mach: Machine, path: str) -> float | None:
    code, out, _ = sh(mach, f"cat {path} 2>/dev/null")
    try:
        return float(out.strip()) if code == 0 else None
    except ValueError:
        return None


def watch(mach: Machine, p: Plan, say: Callable[[str], None]) -> Outcome:
    """Poll until the done marker, a dead run or the host deadline. A SmolError (the machine stopped
    under us, say by another process's `vm down`) propagates: nothing more can be read then."""
    deadline = time.monotonic() + closespider_timeout(p.max_pages) + DEADLINE_GRACE_S
    last_progress = 0.0
    t0 = time.monotonic()
    while True:
        _, out, _ = sh(mach, poll_script(p))
        status, _, lines = out.strip().rpartition("|")
        now = time.monotonic()
        if status.startswith("done"):
            code = int(status.split()[1])
            return Outcome(exit_code=code, why=f"exited {code}")
        if status.startswith("dead"):
            return Outcome(why=f"run is dead with no done marker ({status})")
        if now - last_progress >= PROGRESS_EVERY_S:
            say(f"[crawl] {now - t0:.0f}s: {status}, {lines.strip()} pages in the feed")
            last_progress = now
        if now > deadline:
            say(f"[crawl] host deadline passed after {now - t0:.0f}s: stopping Scrapy")
            sh(mach, kill_script(p), timeout=KILL_GRACE_S + 30)
            _, out, _ = sh(mach, poll_script(p))
            status = out.strip().rpartition("|")[0]
            code = int(status.split()[1]) if status.startswith("done") else None
            return Outcome(exit_code=code, why=f"host deadline passed; killed ({status})")
        time.sleep(POLL_EVERY_S)


def collect(mach: Machine, p: Plan, outcome: Outcome) -> Outcome:
    """Read back the timings, stats, log and feed, whatever exists."""
    outcome.started_epoch = _epoch(mach, f"{p.run_dir}/started.at")
    outcome.finished_epoch = _epoch(mach, f"{p.run_dir}/finished.at")
    for name in ("stats.json", "crawl.log", "feed.jsonl"):
        try:
            data = mach.read_file(f"{p.run_dir}/{name}")
        except SmolError:
            continue
        if name == "stats.json":
            try:
                outcome.stats = json.loads(data)
            except ValueError:
                outcome.stats = {}
        elif name == "crawl.log":
            outcome.log = data
        else:
            outcome.feed = data
    return outcome
