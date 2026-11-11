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

import inspect
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from smol import ExecOptions, Machine, SmolError

from scrapyproto import machine as m, scope as scope_mod, store as store_mod

GUEST_ROOT = "/out/scrapyproto"
RUNS_DIR = f"{GUEST_ROOT}/runs"
CACHE_DIR = f"{GUEST_ROOT}/httpcache"  # Shared by every run, so `--replay` reads what a live run stored.
LOCK = f"{GUEST_ROOT}/crawl.lock"  # A symlink naming the run that holds it: `ln -s` fails if it exists.
FLOCK = f"{GUEST_ROOT}/.lock-take"  # Serialises the check-and-take of LOCK between host processes.
# Ticket 05: host bulk load of the feed, or the item pipeline's DuckDB file. Ticket 08: two live arms over the host
# mount, consumed while the crawl runs (queue.py), and `all`, which runs both live arms and the bulk feed at once.
STORES = ("bulk", "per-item", "jsonl-tail", "rocks-queue", "all")
LIVE_ARMS = {"jsonl-tail": ["jsonl-tail"], "rocks-queue": ["rocks-queue"], "all": ["rocks-queue", "jsonl-tail"]}
GUEST_DB_FILE = "pages.duckdb"  # The per-item store, in the run's directory on the guest disk.
SPIDER_FILE = "proto_spider.py"  # `runspider` imports it as module `proto_spider`; the middleware path uses that.

USER_AGENT = f"scrapy-duckdb-prototype/0.0 (rovo prototype crawler; Scrapy {m.SCRAPY_VERSION}; robots.txt obeyed)"
DOWNLOAD_DELAY_S = 1.0  # Ticket 03's default, and the floor: --delay can only slow the crawl down.
CONCURRENCY = 2
MAX_CONCURRENCY = 4
MAX_DEPTH = 5  # The spec names no default; a guard, since breadth-first fills a 200-page cap far sooner.
POLL_EVERY_S = 5.0
PROGRESS_EVERY_S = 30.0
DEADLINE_GRACE_S = 120.0  # The host deadline is CLOSESPIDER_TIMEOUT plus this.
KILL_GRACE_S = 30.0
STALE_LOCK_S = 120  # A lock whose run never wrote a pid is stale after this long.
EXEC_TIMEOUT_S = 60.0


def closespider_timeout(max_pages: int, delay: float = DOWNLOAD_DELAY_S) -> int:
    """The guest-side wall-clock guard. With DOWNLOAD_DELAY set, Scrapy starts one download per delay on
    a slot whatever the concurrency, so the downloads are what take the time. The spider issues at most
    2 * max_pages requests; each may add a retry or a redirect hop, so 3 downloads per issued request,
    one delay apart, plus 120 s for start-up and robots.txt. 200 pages at 1 s: 1320 s, against about
    200 to 250 s expected (ticket 03 measured 27 downloads in 26.5 s)."""
    return 120 + int(2 * max_pages * 3 * max(delay, DOWNLOAD_DELAY_S))


@dataclass(frozen=True)
class Plan:
    """One crawl's inputs; everything the guest receives is rendered from this."""

    run_id: str
    start_urls: list[str]
    allowed_hosts: list[str]
    max_pages: int
    replay: bool
    path_prefixes: list[str] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    max_depth: int = MAX_DEPTH
    keep_query_params: list[str] = field(default_factory=list)
    delay: float = DOWNLOAD_DELAY_S
    concurrency: int = CONCURRENCY
    user_agent: str = USER_AGENT
    store: str = "bulk"
    crash_after: int = 0  # Ticket 08, prototype only: the spider SIGKILLs itself after this many items.

    @property
    def live_arms(self) -> list[str]:
        return LIVE_ARMS.get(self.store, [])

    @property
    def writes_guest_feed(self) -> bool:
        return self.store in {"bulk", "all"}

    @property
    def queue_dir(self) -> str:
        """The run's directory on the host mount (ticket 08)."""
        return f"{m.QUEUE_GUEST_DIR}/{self.run_id}"

    @property
    def queue_feed(self) -> str:
        return f"{self.queue_dir}/feed.jsonl"

    @property
    def queue_db(self) -> str:
        return f"{self.queue_dir}/rocks"

    @property
    def run_dir(self) -> str:
        return f"{RUNS_DIR}/{self.run_id}"

    @property
    def guest_db(self) -> str:
        return f"{self.run_dir}/{GUEST_DB_FILE}"

    @property
    def feed(self) -> str:
        return f"{self.run_dir}/feed.jsonl"

    def crawl_scope(self) -> dict[str, object]:
        """The `CrawlScope` fields the spider's `Scope` reads, in the spec's names."""
        return {
            "start_urls": self.start_urls,
            "allowed_hosts": self.allowed_hosts,
            "path_prefixes": self.path_prefixes,
            "include": self.include,
            "exclude": self.exclude,
            "max_depth": self.max_depth,
            "meaningful_query_params": self.keep_query_params,
        }

    def scope(self) -> dict[str, object]:
        """The `runs.scope` JSON: the `CrawlScope` fields, the cap, the politeness settings, the mode."""
        return {
            **self.crawl_scope(),
            "max_pages": self.max_pages,
            "replay": self.replay,
            "delay_s": self.delay,
            "concurrency": self.concurrency,
            "user_agent": self.user_agent,
            "robots": "obey",
            "store": self.store,
            "crash_after": self.crash_after,
            "patterns": "glob: fnmatchcase over the whole identity; re: re.search, unanchored",
        }


def new_run_id() -> str:
    """Sortable and unique enough for one machine: UTC time to the second plus 4 random hex digits."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + os.urandom(2).hex()


def plan(  # noqa: PLR0913, C901, PLR0912  one flag per argument; one check per flag
    run_id: str,
    start_urls: list[str],
    allowed_hosts: list[str],
    max_pages: int,
    *,
    replay: bool,
    path_prefixes: list[str] | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    max_depth: int = MAX_DEPTH,
    keep_query_params: list[str] | None = None,
    delay: float = DOWNLOAD_DELAY_S,
    concurrency: int = CONCURRENCY,
    user_agent: str = USER_AGENT,
    store: str = "bulk",
    crash_after: int = 0,
) -> Plan:
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
    # The spec's default prefix: the first start URL's directory (its path up to the last slash).
    first_path = urlsplit(start_urls[0]).path or "/"
    prefixes = list(path_prefixes) if path_prefixes else [first_path[: first_path.rfind("/") + 1]]
    bad = [x for x in prefixes if not x.startswith("/")]
    if bad:
        msg = f"--path-prefix must start with '/': {bad}"
        raise ValueError(msg)
    for pattern in [*(include or []), *(exclude or [])]:
        scope_mod.check_pattern(pattern)
    if not 0 <= max_depth <= 100:  # noqa: PLR2004  the prototype's own ceiling
        msg = f"--max-depth must be 0 to 100, got {max_depth}"
        raise ValueError(msg)
    if not DOWNLOAD_DELAY_S <= delay <= 60:  # noqa: PLR2004  a minute between requests is the ceiling
        msg = f"--delay must be {DOWNLOAD_DELAY_S} to 60 seconds (ticket 03's polite default is the floor), got {delay}"
        raise ValueError(msg)
    if not 1 <= concurrency <= MAX_CONCURRENCY:
        msg = f"--concurrency must be 1 to {MAX_CONCURRENCY}, got {concurrency}"
        raise ValueError(msg)
    if not user_agent.strip() or not user_agent.isprintable() or not user_agent.isascii():
        msg = f"--user-agent must be non-empty printable ASCII, got {user_agent!r}"
        raise ValueError(msg)
    if store not in STORES:
        msg = f"--store must be one of {list(STORES)}, got {store!r}"
        raise ValueError(msg)
    if not 0 <= crash_after < max_pages:
        msg = f"--crash-after must be 0 (off) to below --max-pages, got {crash_after}"
        raise ValueError(msg)
    keep = sorted({k.strip() for k in keep_query_params or [] if k.strip()})
    return Plan(
        run_id, list(start_urls), allowed, max_pages, replay,
        path_prefixes=prefixes, include=list(include or []), exclude=list(exclude or []),
        max_depth=max_depth, keep_query_params=keep, delay=delay, concurrency=concurrency,
        user_agent=user_agent, store=store, crash_after=crash_after,
    )


def settings(p: Plan) -> dict[str, object]:
    """Scrapy's settings for the run. The spider adds only its downloader middleware to these."""
    return {
        # Politeness. robots.txt is always obeyed; there is no flag to turn it off.
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": p.user_agent,
        "CONCURRENT_REQUESTS": p.concurrency,
        "CONCURRENT_REQUESTS_PER_DOMAIN": p.concurrency,
        "DOWNLOAD_DELAY": p.delay,
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
        # The page cap is enforced in the spider. These are backstops only. PAGECOUNT counts robots.txt
        # responses (one per host) and may count other responses that never become a page, so it is set
        # loose enough never to bind before the spider's own cap: the 2 * max_pages requests the spider
        # may issue, times the 3 downloads per request the timeout assumes, plus the hosts. ITEMCOUNT is
        # the cap itself, so a run that reaches the cap closes as closespider_itemcount.
        "CLOSESPIDER_PAGECOUNT": 2 * p.max_pages * 3 + len(p.allowed_hosts),
        "CLOSESPIDER_ITEMCOUNT": p.max_pages,
        "CLOSESPIDER_TIMEOUT": closespider_timeout(p.max_pages, p.delay),
        # The cache on the guest disk captures the run for `--replay`. DummyPolicy (the default) stores
        # every response, robots.txt included, and serves it without revalidation; nothing expires.
        "HTTPCACHE_ENABLED": True,
        "HTTPCACHE_DIR": CACHE_DIR,
        "HTTPCACHE_EXPIRATION_SECS": 0,
        "HTTPCACHE_IGNORE_HTTP_CODES": [429, 503],
        # A replay drops any request not in the cache instead of fetching it.
        "HTTPCACHE_IGNORE_MISSING": p.replay,
        # The per-item path writes no feed (ticket 05): its pipeline writes the DuckDB file instead. The jsonl-tail
        # arm's feed is on the host mount, through `tailfile://`, a line-flushed FileFeedStorage (ticket 08); the
        # guest-disk feed keeps Scrapy's own buffered file, as tickets 03 to 05 ran it.
        "FEEDS": feeds(p),
        "FEED_STORAGES": {"tailfile": "proto_spider.TailFileStorage"},
        "FEED_EXPORT_ENCODING": "utf-8",
        # Ticket 05, both paths: Scrapy's own memory stat. It samples ru_maxrss at engine start and every
        # 60 s, so a short run's memusage/max is the start-up figure; the spider logs ru_maxrss at close too.
        "MEMUSAGE_ENABLED": True,
        "MEMUSAGE_LIMIT_MB": 0,
        "MEMUSAGE_WARNING_MB": 0,
        # Nothing in the guest listens: Scrapy 2.20 starts a remote-control HTTP server by default.
        "REMOTE_CONTROL_ENABLED": False,
        "TELNETCONSOLE_ENABLED": False,
        "LOG_LEVEL": "INFO",
    }


def feeds(p: Plan) -> dict[str, dict[str, object]]:
    spec = {"format": "jsonlines", "encoding": "utf8", "overwrite": True}
    out: dict[str, dict[str, object]] = {}
    if p.writes_guest_feed:
        out[p.feed] = spec
    if "jsonl-tail" in p.live_arms:
        out[f"tailfile://{p.queue_feed}"] = spec
    return out


def config(p: Plan) -> dict[str, object]:
    """What the spider reads besides the settings."""
    return {
        "run_id": p.run_id,
        "start_urls": p.start_urls,
        "allowed_hosts": p.allowed_hosts,
        "scope": p.crawl_scope(),
        "max_pages": p.max_pages,
        "replay": p.replay,
        "stats_path": f"{p.run_dir}/stats.json",
        "store": p.store,
        "store_path": p.guest_db,
        "queue_db": p.queue_db,
        "crash_after": p.crash_after,
        "schema": store_mod.SCHEMA,
    }


SPIDER_TEMPLATE = '''\
"""PROTOTYPE spider rendered by scrapyproto for one run: a breadth-first crawl from the seeds, in scope.

The page cap is enforced here, not by CLOSESPIDER_PAGECOUNT: a request is issued only while
pages yielded plus requests in flight stay under max_pages, so at most max_pages pages are yielded.
A request that ends without a page (filtered, robots-forbidden, failed, or a redirect onto a URL already
fetched) gives its slot back, and total requests issued by the spider stop at twice the cap.

Scope (ticket 04): a link is enqueued only when `Scope.verdict` allows it at its depth, so an excluded
link is never requested. Dedup is by identity (the normalised URL); the request carries the URL as
discovered, fragment removed, so its cache key is the one ticket 03 issued for the same link.
"""

import hashlib
import json
import os
import resource
import signal
import time
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urldefrag, urlsplit

import scrapy
from scrapy import signals
from scrapy.exceptions import CloseSpider, DontCloseSpider, IgnoreRequest
from scrapy.extensions.feedexport import FileFeedStorage
from scrapy.http import HtmlResponse, TextResponse
from scrapy.linkextractors import LinkExtractor

CONFIG = json.loads(__CONFIG__)
SETTINGS = json.loads(__SETTINGS__)
THROTTLED = (429, 503)

# ---- scrapyproto/scope.py, pasted verbatim by the host ----
__SCOPE_LIB__
# ---- end of scope.py ----

SCOPE = Scope(CONFIG["scope"])


def on_host(url, hosts):
    """Exact host match on http(s): the offsite middleware also allows subdomains, this does not."""
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and (parts.hostname or "") in hosts


class Guard:
    """Downloader middleware placed after robots.txt (100). It sees every request the downloader gets,
    redirects, retries and robots.txt requests included, and drops one that is off the allowed hosts
    (so a subdomain redirect never fetches that subdomain's robots.txt), or a page request whose host's
    robots.txt did not arrive with a status under 500 (fail closed: Scrapy itself allows everything when
    robots.txt cannot be fetched). A redirect hop is also dropped when its target's identity was already
    fetched, or when its target leaves the scope (prefix, exclude, include), wherever the chain started;
    a target that is itself a seed is in scope: the link was in scope, its target is what would be stored."""

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
        redirects = request.meta.get("redirect_urls")
        if redirects and "proto_depth" in request.meta:
            target = SCOPE.identity(request.url)
            if target in spider.fetched:
                stats.inc_value("proto/guard/redirect_to_fetched")
                raise IgnoreRequest(f"redirect onto a page already fetched: {request.url}")
            own = {SCOPE.identity(u) for u in redirects}  # this chain's own hops, its origin included
            if target in spider.requested and target not in own and request.meta.get("proto_claimed") != target:
                stats.inc_value("proto/guard/redirect_to_requested")
                raise IgnoreRequest(f"redirect onto a page already requested: {request.url}")
            reason = SCOPE.bounds_reason(request.url)
            if reason is not None:
                stats.inc_value(f"proto/guard/redirect_{reason}")
                raise IgnoreRequest(f"redirect out of scope ({reason}): {redirects[0]} -> {request.url}")
            spider.requested.add(target)  # drain must not issue it again while this hop is in flight
            request.meta["proto_claimed"] = target  # a retry of this hop carries it and passes
        status = spider.robots_status.get(urlsplit(request.url).netloc)
        if status is None or status >= 500 or status == 429:
            stats.inc_value("proto/guard/robots_unavailable")
            raise IgnoreRequest(f"robots.txt unavailable ({status}) for {request.url}")
        return None


class DuckDBPipeline:
    """Ticket 05's per-item store: each page is inserted, as it arrives, into a DuckDB file on the guest
    disk, one autocommit INSERT per item, with the host store's schema (`html` USING COMPRESSION ZSTD).
    Scrapy calls close_spider before it sends spider_closed (engine.close_spider_async, read in the
    guest), so the runs row, the CHECKPOINT and the close all land before the spider's `closed` dumps the
    stats and reads ru_maxrss. A runs row in the file means the pipeline closed it; a crash leaves none.
    The insert is synchronous: the reactor waits for it, and the stats record how long."""

    def __init__(self, crawler):
        self.crawler = crawler
        self.con = None
        self.rows = 0
        self.duplicates = 0
        self.failed = 0
        self.insert_s = 0.0
        self.insert_max_s = 0.0

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def open_spider(self, spider=None):
        import duckdb  # The bulk path does not need DuckDB in the guest.

        t0 = time.perf_counter()
        # No extension may be fetched: the guest has the network, and nothing here is granted it.
        self.con = duckdb.connect(
            CONFIG["store_path"],
            config={"autoinstall_known_extensions": False, "autoload_known_extensions": False},
        )
        self.con.execute(CONFIG["schema"])
        stats = self.crawler.stats
        stats.set_value("proto/store/kind", "per-item")
        stats.set_value("proto/store/duckdb", duckdb.__version__)
        stats.set_value("proto/store/open_s", round(time.perf_counter() - t0, 6))

    def process_item(self, item, spider=None):
        t0 = time.perf_counter()
        try:
            found = self.con.execute(
                "INSERT OR IGNORE INTO pages (run_id, url, final_url, status, content_type, depth, referrer, "
                "outlinks, fetched_at, content_hash, html) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS TIMESTAMPTZ), ?, ?)",
                [
                    CONFIG["run_id"], item["url"], item["final_url"], item["status"], item["content_type"],
                    item["depth"], item["referrer"], item["outlinks"], item["fetched_at"], item["content_hash"],
                    item["html"],
                ],
            ).fetchall()
        except Exception:
            self.failed += 1  # Scrapy logs it and crawls on; the host rejects the run (cli.py).
            raise
        took = time.perf_counter() - t0
        self.insert_s += took
        self.insert_max_s = max(self.insert_max_s, took)
        if found and found[0][0] == 1:
            self.rows += 1
        else:  # The bulk load keeps a URL's earliest fetch; so does this, by arrival order.
            self.duplicates += 1
        return item

    def close_spider(self, spider=None):
        stats = self.crawler.stats
        stats.set_value("proto/store/rows_inserted", self.rows)
        stats.set_value("proto/store/duplicates_ignored", self.duplicates)
        stats.set_value("proto/store/insert_failed", self.failed)
        stats.set_value("proto/store/insert_s_total", round(self.insert_s, 6))
        stats.set_value("proto/store/insert_s_max", round(self.insert_max_s, 6))
        if self.con is None:
            return
        # A shorter route found after a page was stored lowers its depth (enqueue); apply it to the row.
        for url, depth in self.crawler.spider.depth_corrections().items():
            self.con.execute("UPDATE pages SET depth = ? WHERE run_id = ? AND url = ?", [depth, CONFIG["run_id"], url])
        rows = self.con.execute("SELECT count(*) FROM pages").fetchall()[0][0]
        self.con.execute(
            "INSERT INTO runs (run_id, start_urls, scope, pages, store, store_file) VALUES (?, ?, ?, ?, ?, ?)",
            [CONFIG["run_id"], CONFIG["start_urls"], json.dumps(CONFIG["scope"]), rows, "per-item",
                CONFIG["store_path"]],
        )
        t0 = time.perf_counter()
        self.con.execute("CHECKPOINT")
        stats.set_value("proto/store/checkpoint_s", round(time.perf_counter() - t0, 6))
        self.con.close()
        self.con = None
        path = CONFIG["store_path"]
        stats.set_value("proto/store/rows", rows)
        stats.set_value("proto/store/closed", 1)
        stats.set_value("proto/store/file_bytes", os.path.getsize(path))
        stats.set_value("proto/store/wal_after_close", os.path.exists(path + ".wal"))


class _LineFlushed:
    """A feed file that flushes after every write: the exporter writes one line per item, so each line reaches
    the mount whole as soon as it is exported (ticket 08's jsonl-tail arm). Scrapy's own file is buffered."""

    def __init__(self, f):
        self._f = f

    def write(self, data):
        n = self._f.write(data)
        self._f.flush()
        return n

    def __getattr__(self, name):
        return getattr(self._f, name)


class TailFileStorage(FileFeedStorage):
    """`tailfile://<path>`: a FileFeedStorage whose file is line-flushed; only the mount feed uses it."""

    def __init__(self, uri, *, feed_options=None):
        super().__init__(uri.removeprefix("tailfile://"), feed_options=feed_options)

    def open(self, spider):
        return _LineFlushed(super().open(spider))


class RocksQueuePipeline:
    """Ticket 08's queue: each page is put, as it arrives, into RocksDB on the host mount under `p:%012d`, the
    item's JSON as the value, so the host can follow it as a secondary while the crawl runs. The WAL is ZSTD-
    compressed (rocksdict has no setter, so the closed database's OPTIONS file is edited once at open, ticket 07),
    and so are the SSTs. At close the pipeline writes `meta:closed` with the page count and the depth corrections,
    syncs the WAL and closes: a `meta:closed` on the host means every page before it is there too."""

    def __init__(self, crawler):
        self.crawler = crawler
        self.db = None
        self.seq = 0
        self.failed = 0
        self.put_s = 0.0
        self.put_max_s = 0.0
        self.seen = {}  # Largest size seen per file other than an SST, deleted WALs included (_sample).

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def open_spider(self, spider=None):
        import glob

        from rocksdict import DBCompressionType, Options, Rdict, WriteOptions

        t0 = time.perf_counter()
        path = CONFIG["queue_db"]
        if os.path.exists(path):
            raise RuntimeError(f"{path} exists: one queue per run")
        o = Options(raw_mode=True)
        o.create_if_missing(True)
        o.set_compression_type(DBCompressionType.zstd())
        Rdict(path, o).close()
        options_file = sorted(glob.glob(path + "/OPTIONS-*"))[-1]
        text = open(options_file, encoding="utf-8").read()
        if text.count("wal_compression=kNoCompression") != 1:
            raise RuntimeError(f"{options_file}: no single wal_compression line to set")
        with open(options_file, "w", encoding="utf-8") as f:
            f.write(text.replace("wal_compression=kNoCompression", "wal_compression=kZSTD"))
        loaded, _ = Options.load_latest(path)
        loaded.enable_statistics()  # RocksDB's own byte counters, read at close.
        self.options = loaded
        self.db = Rdict(path, loaded)
        self.write_opt = WriteOptions()  # No sync per put: ticket 07 found it changes nothing the host sees.
        stats = self.crawler.stats
        stats.set_value("proto/queue/kind", "rocks-queue")
        stats.set_value("proto/queue/compression", "sst zstd, wal zstd")
        stats.set_value("proto/queue/open_s", round(time.perf_counter() - t0, 6))
        self._sample()

    def _sample(self, wal_only=False):
        """Record the largest size seen of each file in the queue directory but the SSTs, which the flush and
        compaction counters count. A WAL only grows until RocksDB switches to the next and deletes it after the
        flush, so its largest size, sampled after every put, is what was written to it; the other files are
        sampled at open and around the close only."""
        path = CONFIG["queue_db"]
        for name in os.listdir(path):
            if name.endswith(".sst") or (wal_only and not name.endswith(".log")):
                continue
            try:
                size = os.path.getsize(os.path.join(path, name))
            except OSError:
                continue  # Deleted between the listing and the stat: a flushed WAL, already sampled.
            self.seen[name] = max(self.seen.get(name, 0), size)

    def process_item(self, item, spider=None):
        t0 = time.perf_counter()
        try:
            self.db.put(b"p:%012d" % self.seq, json.dumps(dict(item)).encode("utf-8"), self.write_opt)
        except Exception:
            self.failed += 1  # Scrapy logs it and crawls on; the host's count against proto/pages catches it.
            raise
        self.seq += 1
        took = time.perf_counter() - t0
        self.put_s += took
        self.put_max_s = max(self.put_max_s, took)
        self._sample(wal_only=True)  # Outside the put's timing.
        return item

    def close_spider(self, spider=None):
        stats = self.crawler.stats
        stats.set_value("proto/queue/puts", self.seq)
        stats.set_value("proto/queue/put_failed", self.failed)
        stats.set_value("proto/queue/put_s_total", round(self.put_s, 6))
        stats.set_value("proto/queue/put_s_max", round(self.put_max_s, 6))
        if self.db is None:
            return
        closed = {
            "run_id": CONFIG["run_id"],
            "pages": self.crawler.spider.pages,
            "puts": self.seq,
            "depth_corrections": self.crawler.spider.depth_corrections(),
            "at": time.time(),
        }
        self.db.put(b"meta:closed", json.dumps(closed).encode("utf-8"), self.write_opt)
        # What crossed the mount while the run lasted: the files as they stand before the close, which may flush
        # the memtable into an SST and empty the WAL. RocksDB's wal.bytes counts before the WAL's own ZSTD.
        path = CONFIG["queue_db"]
        self._sample()
        before = {name: os.path.getsize(os.path.join(path, name)) for name in os.listdir(path)}
        stats.set_value("proto/queue/before_close/wal_bytes", sum(v for k, v in before.items() if k.endswith(".log")))
        stats.set_value("proto/queue/before_close/sst_bytes", sum(v for k, v in before.items() if k.endswith(".sst")))
        stats.set_value("proto/queue/before_close/dir_bytes", sum(before.values()))
        counters = {}
        for line in (self.options.get_statistics() or "").splitlines():
            name, _, rest = line.partition(" COUNT : ")
            if name in ("rocksdb.wal.bytes", "rocksdb.flush.write.bytes", "rocksdb.compact.write.bytes"):
                counters[name] = int(rest)
        for name, value in counters.items():
            stats.set_value(f"proto/queue/{name}_before_close", value)
        t0 = time.perf_counter()
        self.db.flush_wal(True)
        self.db.close()
        self.db = None
        stats.set_value("proto/queue/close_s", round(time.perf_counter() - t0, 6))
        stats.set_value("proto/queue/closed", 1)
        files = {name: os.path.getsize(os.path.join(path, name)) for name in os.listdir(path)}
        stats.set_value("proto/queue/dir_bytes", sum(files.values()))
        stats.set_value("proto/queue/wal_bytes", sum(v for k, v in files.items() if k.endswith(".log")))
        stats.set_value("proto/queue/sst_bytes", sum(v for k, v in files.items() if k.endswith(".sst")))
        # What was written over the run and its close, deleted files included: the per-WAL maxima, the SST bytes
        # RocksDB's flushes and compactions wrote (read after the close, so the close's flush counts) and the
        # other files' largest sizes. Not counted: the first open's files deleted at reopen, transport overhead.
        self._sample()
        after = {}
        for line in (self.options.get_statistics() or "").splitlines():
            name, _, rest = line.partition(" COUNT : ")
            if name in ("rocksdb.flush.write.bytes", "rocksdb.compact.write.bytes"):
                after[name] = int(rest)
        wal = sum(v for k, v in self.seen.items() if k.endswith(".log"))
        other = sum(v for k, v in self.seen.items() if not k.endswith(".log"))
        stats.set_value("proto/queue/written/wal_bytes", wal)
        stats.set_value("proto/queue/written/wal_files_seen", sum(1 for k in self.seen if k.endswith(".log")))
        for name, value in after.items():
            stats.set_value(f"proto/queue/written/{name}", value)
        stats.set_value("proto/queue/written/other_bytes", other)
        stats.set_value("proto/queue/written_bytes_total", wal + sum(after.values()) + other)


class ProtoSpider(scrapy.Spider):
    name = "proto"  # Fixed: HTTPCACHE_SCOPE "spider" keys the cache by it, so replays find it.
    custom_settings = {
        **SETTINGS,
        "DOWNLOADER_MIDDLEWARES": {"proto_spider.Guard": 110},
        **({"ITEM_PIPELINES": {"proto_spider.DuckDBPipeline": 300}} if CONFIG["store"] == "per-item" else {}),
        **({"ITEM_PIPELINES": {"proto_spider.RocksQueuePipeline": 300}} if CONFIG["store"] in ("rocks-queue", "all")
            else {}),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.allowed_hosts = set(CONFIG["allowed_hosts"])
        self.allowed_domains = list(CONFIG["allowed_hosts"])
        self.max_pages = CONFIG["max_pages"]
        self.max_requests = 2 * self.max_pages
        self.frontier = deque()  # (url, depth, referrer), in discovery order: breadth first
        self.seen = set()  # identities enqueued, or rejected for a reason other than depth
        self.best_depth = {}  # identity -> least depth it was queued at (crawl.allium Enqueue lowers it)
        self.requested = set()  # identities a request was issued for
        self.expanded = {}  # identity -> (outlinks, page url) of a stored 200 HTML page, for re-expansion
        self.fetched = set()  # identities of every URL a page was stored for, redirect hops included
        self.stored = {}  # stored url -> (depth written, hop identities); the first fetch wins, as in both stores
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
        """Queue the link as discovered (fragment removed) if its identity is new and in scope. Responses
        arrive out of order under concurrency, so a shorter route found later lowers the depth: a page not
        yet requested is queued again at it, a stored page's links are re-judged from it. A too_deep
        rejection is not final."""
        key = urldefrag(url)[0]
        ident = SCOPE.identity(key)
        best = self.best_depth.get(ident)
        if best is not None:
            if depth >= best:
                return
            self.best_depth[ident] = depth
            self.crawler.stats.inc_value("proto/links/depth_lowered")
            if ident in self.expanded:
                outlinks, page_url = self.expanded[ident]
                for link in outlinks:
                    self.enqueue(link, depth + 1, page_url)
            elif ident not in self.requested and ident not in self.fetched:
                self.frontier.append((key, depth, referrer))
            return
        if ident in self.seen or ident in self.fetched:
            return
        reason = "malformed" if ident is None else SCOPE.verdict(key, depth)
        if reason is not None:
            if reason != "too_deep":  # a shorter route may still admit it
                self.seen.add(ident)
            self.crawler.stats.inc_value(f"proto/links/{reason}")
            return
        self.seen.add(ident)
        self.best_depth[ident] = depth
        self.crawler.stats.inc_value("proto/links/queued")
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
            ident = SCOPE.identity(url)
            if ident in self.requested or depth > self.best_depth.get(ident, depth):
                continue  # a deeper copy left behind when a shorter route re-queued it
            if ident in self.fetched:
                # Stored already, reached through another URL's redirect while this one waited.
                self.crawler.stats.inc_value("proto/links/fetched_via_redirect")
                continue
            self.requested.add(ident)
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
        if CONFIG["crash_after"] and self.pages >= CONFIG["crash_after"]:
            # Ticket 08's crash probe: die as a crash would, with no close, no stats and no flush.
            os.kill(os.getpid(), signal.SIGKILL)
        self.pages += 1
        chain = [*response.meta.get("redirect_urls", []), response.url]
        hops = [SCOPE.identity(urldefrag(hop)[0]) for hop in chain]
        self.fetched.update(hops)
        is_html = isinstance(response, HtmlResponse)
        outlinks = [link.url for link in self.links.extract_links(response)] if is_html else []
        referrer = response.request.headers.get("Referer")
        content_type = response.headers.get("Content-Type")
        first = response.meta.get("redirect_urls", [response.url])[0]
        # Every hop is the same stored page: its depth is the least known route to any of them.
        depth = min([response.meta["proto_depth"], *(self.best_depth[h] for h in hops if h in self.best_depth)])
        for h in hops:
            self.best_depth[h] = depth
        self.stored.setdefault(first, (depth, hops))
        yield {
            "url": first,
            "final_url": response.url,
            "status": response.status,
            "content_type": content_type.decode("latin-1") if content_type else None,
            "depth": depth,
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
            for h in hops:  # a shorter route to any alias re-expands the page
                self.expanded[h] = (outlinks, response.url)
            for url in outlinks:
                self.enqueue(url, depth + 1, response.url)
        yield from self.drain()

    def depth_corrections(self):
        """Stored URLs whose least known depth fell after their item was emitted: url -> that depth."""
        out = {}
        for url, (written, hops) in self.stored.items():
            best = min(self.best_depth.get(h, written) for h in hops)
            if best < written:
                out[url] = best
        return out

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
        stats.set_value("proto/depth_corrections", self.depth_corrections())
        stats.set_value("proto/requests_issued", self.issued)
        stats.set_value("proto/frontier_left", len(self.frontier))
        stats.set_value("proto/identities_fetched", len(self.fetched))
        # Ticket 05: this process's peak RSS (Linux: KiB), read after the pipeline's close.
        stats.set_value("proto/ru_maxrss_kib", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        path = CONFIG["stats_path"]
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(stats.get_stats(), f, default=str, indent=1, sort_keys=True)
        os.replace(path + ".tmp", path)
'''


def spider_source(p: Plan) -> str:
    """The spider module, with the run's config and settings as JSON string literals and scope.py pasted."""
    return (
        SPIDER_TEMPLATE.replace("__CONFIG__", repr(json.dumps(config(p))))
        .replace("__SETTINGS__", repr(json.dumps(settings(p), indent=1)))
        .replace("__SCOPE_LIB__", inspect.getsource(scope_mod).rstrip("\n"))
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
# Release the lock only if this run still holds it, under the same flock acquire takes.
{release_script(p.run_id)}
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
    return f'( flock -w 30 9 && [ "$(readlink {LOCK})" = "{run_id}" ] && rm -f {LOCK} ) 9>{FLOCK}; true'


def poll_script(p: Plan) -> str:
    """The liveness line plus a progress count. Bulk counts the feed's lines. Per-item has no feed and
    the live DuckDB file is locked by its writer, so the count is Scrapy's own LogStats figure (INFO,
    every 60 s): 0 until the first tick, and until the log exists."""
    count = (
        f"wc -l < {p.feed} 2>/dev/null || echo 0"
        if p.store == "bulk"
        else f"grep -o 'scraped [0-9]* items' {p.run_dir}/crawl.log 2>/dev/null | tail -n 1 | grep -o '[0-9]*' || echo 0"
    )
    return f"""{STATUS_FN}
st=$(run_status {p.run_id})
count=$({count})
echo "$st|$count"
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
        f"# CLOSESPIDER_TIMEOUT={closespider_timeout(p.max_pages, p.delay)} s; host deadline "
        f"{closespider_timeout(p.max_pages, p.delay) + DEADLINE_GRACE_S:.0f} s; poll every {POLL_EVERY_S:.0f} s",
        "",
        rule,
        f"## Order of host calls (exec and write_file on {m.MACHINE_NAME})",
        rule,
        f"1. refuse unless {m.MACHINE_NAME} exists, is this checkout's (state file generation) and is running",
        f"2. exec: mkdir -p {p.run_dir} {CACHE_DIR}",
        f"3. write_file {p.run_dir}/{SPIDER_FILE} and {p.run_dir}/run.sh (below)",
        f"4. exec: take the lock {LOCK} under flock (script below); refuse if another run is alive",
        f"5. exec(background=True): {' '.join(launch_argv(p))}",
        "6. poll with one exec per interval until `done`, `dead` or the host deadline; on the deadline, TERM",
        "   Scrapy, wait, KILL",
        f"7. read_file {p.feed}, stats.json and crawl.log; bulk-load the feed into DuckDB on the host"
        if p.store == "bulk"
        else f"7. read_file stats.json and crawl.log; check {p.guest_db} is closed (no WAL), read_file it, record "
        "the run in the host store",
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


def dry_run(p: Plan) -> str:
    """`crawl --dry-run`: the resolved scope and the settings the host would render; no machine call."""
    sc = scope_mod.Scope(p.crawl_scope())
    timeout = closespider_timeout(p.max_pages, p.delay)
    lines = [
        "# scrapyproto crawl --dry-run: nothing was started and nothing was requested",
        "",
        "## Resolved scope (stored with the run in runs.scope)",
        json.dumps(p.scope(), indent=2),
        "",
        "## How the scope reads",
        f"- hosts: exact match on {p.allowed_hosts}; a subdomain is off-host",
        f"- path prefixes: a URL is in scope only when its identity's path starts with one of {p.path_prefixes}",
        f"- include: {p.include or 'none given, so every in-prefix URL passes'}",
        f"- exclude: {p.exclude or 'none'}",
        "- patterns match the identity, never the raw URL. A glob is fnmatchcase over the whole identity",
        "  (`*` crosses `/`, `?` is any one character). A `re:` pattern is re.search: unanchored, so it",
        "  matches anywhere unless it uses ^ or $.",
        f"- max depth: {p.max_depth}; a link whose shortest known route is deeper is not followed",
        "  (the seed is depth 0)",
        f"- page cap: {p.max_pages} pages, enforced in the spider; at most {2 * p.max_pages} spider requests",
        f"- kept query parameters: {p.keep_query_params or 'none'}; every other parameter is dropped from the",
        "  identity before the scope test and dedup. The request still carries the URL as discovered, fragment",
        "  removed, so a page's cache key does not change with these flags.",
        "- a seed is always in scope; a redirect hop must stay in scope (a seed's own redirect included),",
        "  and is dropped when its target's identity was already fetched",
        f"- politeness: delay {p.delay} s between downloads, concurrency {p.concurrency}, robots.txt obeyed",
        f"  (no flag turns it off), user agent {p.user_agent!r}",
        f"- replay: {p.replay} (true: served from the guest cache; a request not in it is dropped)",
        f"- store: {p.store}",
        f"- CLOSESPIDER_TIMEOUT {timeout} s; host deadline {timeout + DEADLINE_GRACE_S:.0f} s",
        "",
        "## Seeds",
    ]
    lines += [f"- {u}\n  identity {sc.identity(u)}" for u in p.start_urls]
    lines += ["", "## Scrapy settings the host would render into the spider", json.dumps(settings(p), indent=2)]
    return "\n".join(lines)


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
    code, _, err = sh(mach, f"mkdir -p {p.run_dir} {CACHE_DIR}" + (f" {p.queue_dir}" if p.live_arms else ""))
    if code != 0:
        msg = f"mkdir in the guest exited {code}: {err.strip()[-300:]}"
        raise m.ProtoError(msg)
    mach.write_file(f"{p.run_dir}/{SPIDER_FILE}", spider_source(p))
    mach.write_file(f"{p.run_dir}/run.sh", wrapper_source(p))


def acquire(mach: Machine, p: Plan) -> str:
    """Take the lock; returns the script's report. Raises when another run holds it."""
    _, out, err = sh(mach, acquire_script(p.run_id))
    lines = out.strip().splitlines()
    if not lines or lines[-1] != "taken":
        msg = f"another crawl holds {LOCK} on the guest: {out.strip() or err.strip()}"
        raise m.ProtoError(msg)
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


def watch(  # noqa: PLR0913  the ticket 08 hooks
    mach: Machine,
    p: Plan,
    say: Callable[[str], None],
    tick: Callable[[], object] | None = None,
    progress: Callable[[], str] | None = None,
    tick_s: float = POLL_EVERY_S,
) -> Outcome:
    """Poll until the done marker, a dead run or the host deadline. A SmolError (the machine stopped
    under us, say by another process's `vm down`) propagates: nothing more can be read then. Ticket 08:
    `tick` (the live consumers) runs every `tick_s` between the guest polls, which stay POLL_EVERY_S apart,
    and `progress` replaces the guest-side count in the progress line."""
    deadline = time.monotonic() + closespider_timeout(p.max_pages, p.delay) + DEADLINE_GRACE_S
    last_progress = 0.0
    unit = "pages in the feed" if p.store == "bulk" else "items scraped (Scrapy's log stats, every 60 s)"
    t0 = time.monotonic()
    while True:
        _, out, _ = sh(mach, poll_script(p))
        status, _, count = out.strip().rpartition("|")
        now = time.monotonic()
        if status.startswith("done"):
            code = int(status.split()[1])
            return Outcome(exit_code=code, why=f"exited {code}")
        if status.startswith("dead"):
            return Outcome(why=f"run is dead with no done marker ({status})")
        if status.startswith("starting") and int(status.split()[1]) >= STALE_LOCK_S:
            # pid is written before Scrapy starts; none after STALE_LOCK_S means it never ran
            # (cd failed, run.sh never started, or a reboot first). The lock calls it stale too.
            return Outcome(why=f"run never wrote a pid ({status}); dead, as the lock rule says")
        if now - last_progress >= PROGRESS_EVERY_S:
            say(f"[crawl] {now - t0:.0f}s: {status}, "
                + (progress() if progress is not None else f"{count.strip()} {unit}"))
            last_progress = now
        if now > deadline:
            say(f"[crawl] host deadline passed after {now - t0:.0f}s: stopping Scrapy")
            sh(mach, kill_script(p), timeout=KILL_GRACE_S + 30)
            _, out, _ = sh(mach, poll_script(p))
            status = out.strip().rpartition("|")[0]
            code = int(status.split()[1]) if status.startswith("done") else None
            return Outcome(exit_code=code, why=f"host deadline passed; killed ({status})")
        if tick is None:
            time.sleep(POLL_EVERY_S)
            continue
        next_poll = time.monotonic() + POLL_EVERY_S
        while time.monotonic() < next_poll:
            tick()
            time.sleep(tick_s)


def pull_store(mach: Machine, p: Plan) -> tuple[bytes, str]:
    """Ticket 05: read the per-item DuckDB file back, only once it is closed. Returns the bytes and the
    guest's `ls -l` of the run directory. Raises ProtoError when the file is missing, when a WAL sits
    beside it (the pipeline never checkpointed and closed it: a crash) or when the bytes read differ
    from the guest's size."""
    # One exec: the listing, then stat's size as the last line; the exit status is stat's.
    code, out, err = sh(mach, f"ls -l --time-style=+%s {p.run_dir}; stat -c %s {p.guest_db}")
    if code != 0:
        msg = f"no per-item store at {p.guest_db}: {err.strip()[-300:]}"
        raise m.ProtoError(msg)
    listing, _, size_line = out.rstrip().rpartition("\n")
    if f"{GUEST_DB_FILE}.wal" in listing:
        msg = f"{p.guest_db}.wal exists: the pipeline did not checkpoint and close the file; not pulled"
        raise m.ProtoError(msg)
    guest_size = int(size_line)
    data = mach.read_file(p.guest_db)
    if len(data) != guest_size:
        msg = f"read {len(data)} bytes of {p.guest_db}, the guest says {guest_size}"
        raise m.ProtoError(msg)
    return data, listing


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
