"""End to end: blocks, the breaker and host retirement (T18).

Two committed fixture sites are served on 127.0.0.1 by `serve_site`: `blocks`, whose
start.html links twelve pages, and `soft`, whose start.html links five prose pages, then a
thin page and a login wall. The blocks, the long Retry-After and the long Crawl-delay are
scripted with `always=`, their robots.txt bodies and headers built here from CONFIG,
never a literal cap. `rovo init` runs through CliRunner; each sync runs
`rovo._commands.sync` in process over the real HttpxFetcher on a FixedClock, which never
sleeps, its progress events written as `--json` writes them. Requests are read off the
server's log. A page path strips the scope prefix /guide/, so <base>guide/x.html is
pages/<host>/x.md. Not `test_blocks.py`, which the unit suite names.

The T18-2 answers (spec 7d01367) serve both sites at once: two ports on 127.0.0.1 are
two origins of one host, so the second origin's robots.txt, read on first use, retires
the whole host while the first origin's pages are being fetched.
"""

import json
from datetime import timedelta
from pathlib import Path

from bs4 import BeautifulSoup
from conftest import SITES, Answer, SiteServer
from test_init_sync import load, page_root, split_page
from typer.testing import CliRunner

from fakes import FixedClock
from rovo import _commands
from rovo._crawl.fetch import HttpxFetcher
from rovo._crawl.model import CONFIG as CRAWL
from rovo._crawl.model import standard_policy
from rovo._exit import ExitCode
from rovo._report import event_line
from rovo.cli import app
from test_commands import set_key

COUNT = min(CRAWL.breaker_window, CRAWL.breaker_min_outcomes)
BLOCKING = int(COUNT * CRAWL.block_rate_threshold) + 1
CAP = standard_policy().retry_after_cap
PAST_CAP_SECONDS = int(CAP.total_seconds() + timedelta(seconds=1).total_seconds())
DENIED = "<!doctype html><html><body><p>Access denied.</p></body></html>"
# The blocks site's pages that answer a block on every request, and their status.
BLOCKED = {"p02.html": 403, "p04.html": 401, "p06.html": 429}
ROBOTS_PATH = "/robots.txt"


def linked(site: str) -> list[str]:
    """The hrefs of the committed site's start.html, in document order."""
    start = (SITES / site / "guide" / "start.html").read_text(encoding="utf-8")
    return [str(anchor["href"]) for anchor in BeautifulSoup(start, "lxml").find_all("a")]


def initialised(base: str, out: Path) -> Path:
    """`rovo init <base>guide/start.html <out>` through CliRunner."""
    result = CliRunner().invoke(
        app, ["init", f"{base}guide/start.html", str(out)], prog_name="rovo"
    )
    assert result.exit_code == 0, result.output
    return out


def synced(out: Path) -> tuple[ExitCode, list[str]]:
    """Rovo sync --json in process over the real HttpxFetcher; the code and the event lines."""
    lines: list[str] = []
    with HttpxFetcher() as fetcher:
        code = _commands.sync(
            out,
            fetcher=fetcher,
            clock=FixedClock(),
            json_events=True,
            progress=lambda event: lines.append(event_line(event)),
        )
    return code, lines


def report(out: Path) -> dict[str, object]:
    """crawl-report.json."""
    return load(out / "crawl-report.json")


def page_file(out: Path, base: str, name: str) -> Path:
    """The page file of <base>guide/<name>.html."""
    return out / f"{page_root(base)}{name}.md"


def rows(data: dict[str, object], key: str) -> list[dict[str, object]]:
    """A list of objects in the report."""
    value = data[key]
    assert isinstance(value, list)
    return value


def test_blocks_trip_the_breaker_and_the_sync_exits_3(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """403, 401 and 429 pages are blocked; the breaker trips; the rest are skipped; exit 3.

    start.html is the first outcome, so the COUNTth settled walk is the link at index
    COUNT - 2: it trips the breaker, and every link after it is skipped and never
    requested. The 429 page is requested http_attempts times; one breaker_tripped event
    names the host before done; no blocked page has a page file.
    """
    links = linked("blocks")
    assert len(links) + 1 > COUNT
    before_trip = links[: COUNT - 1]
    assert sum(1 for href in before_trip if href in BLOCKED) >= BLOCKING
    skipped = links[COUNT - 1 :]
    base = serve_site(
        "blocks",
        always={
            f"/guide/{name}": Answer(status, {"Content-Type": "text/html"}, DENIED)
            for name, status in BLOCKED.items()
        },
    )
    out = initialised(base, tmp_path / "out")
    code, lines = synced(out)
    assert code is ExitCode.blocked
    data = report(out)
    assert data["exit_code"] == "blocked"
    assert data["breaker_tripped"] is True
    blocked = rows(data, "blocked_urls")
    assert {(row["url"], row["status"]) for row in blocked} == {
        (f"{base}guide/{name}", status) for name, status in BLOCKED.items()
    }
    assert all(row["signature"] and row["tier"] == "http" for row in blocked)
    assert data["skipped_urls"] == sorted(f"{base}guide/{href}" for href in skipped)
    (host,) = rows(data, "per_host")
    assert host["breaker_tripped"] is True
    assert host["blocked"] == len(BLOCKED)
    assert isinstance(host["fetched"], int)
    assert host["block_rate"] == len(BLOCKED) / host["fetched"]
    paths = serve_site.paths(base)
    assert paths.count("/guide/p06.html") == CRAWL.http_attempts
    for href in skipped:
        assert f"/guide/{href}" not in paths
    events = [json.loads(line) for line in lines]
    names = [event["event"] for event in events]
    assert names.count("breaker_tripped") == 1
    assert names.index("breaker_tripped") < names.index("done")
    (trip,) = [event for event in events if event["event"] == "breaker_tripped"]
    assert trip["host"] == "127.0.0.1"
    for href in before_trip:
        name = href.removesuffix(".html")
        assert page_file(out, base, name).is_file() is (href not in BLOCKED), href


def test_a_crawl_delay_past_the_cap_retires_the_host(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """robots.txt's Crawl-delay past retry_after_cap retires the host: robots.txt alone, exit 3."""
    robots = f"User-agent: *\nCrawl-delay: {PAST_CAP_SECONDS}\n"
    base = serve_site("blocks", always={ROBOTS_PATH: Answer(200, {}, robots)})
    out = initialised(base, tmp_path / "out")
    code, _ = synced(out)
    assert code is ExitCode.blocked
    data = report(out)
    assert data["breaker_tripped"] is True
    assert data["skipped_urls"] == [f"{base}guide/start.html"]
    assert serve_site.paths(base) == [ROBOTS_PATH]
    assert not (out / page_root(base)).exists() or not any((out / page_root(base)).iterdir())


def test_a_robots_retry_after_past_the_cap_retires_the_host(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """robots.txt answering 429 past the Retry-After cap: asked once, nothing else, exit 3."""
    base = serve_site(
        "blocks", always={ROBOTS_PATH: Answer(429, {"Retry-After": str(PAST_CAP_SECONDS)})}
    )
    out = initialised(base, tmp_path / "out")
    code, _ = synced(out)
    assert code is ExitCode.blocked
    data = report(out)
    assert serve_site.paths(base) == [ROBOTS_PATH]
    assert {"url": f"{base}robots.txt", "problem": "robots_refused"} in rows(
        data, "discovery_problems"
    )
    assert data["skipped_urls"] == [f"{base}guide/start.html"]


def test_a_page_retry_after_past_the_cap_blocks_it_and_retires_the_host(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """p01.html answering 429 past the cap is asked once and blocked; the other links skipped."""
    links = linked("blocks")
    first = links[0]
    base = serve_site(
        "blocks",
        always={f"/guide/{first}": Answer(429, {"Retry-After": str(PAST_CAP_SECONDS)})},
    )
    out = initialised(base, tmp_path / "out")
    code, _ = synced(out)
    assert code is ExitCode.blocked
    data = report(out)
    assert serve_site.paths(base).count(f"/guide/{first}") == 1
    assert [(row["url"], row["status"]) for row in rows(data, "blocked_urls")] == [
        (f"{base}guide/{first}", 429)
    ]
    assert data["skipped_urls"] == sorted(f"{base}guide/{href}" for href in links[1:])


def test_a_thin_page_and_a_login_wall_are_soft_blocks(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """thin.html after the baseline and login.html's password form are converted, flagged soft.

    The sync exits 0: a soft verdict never counts against the host. Both page files carry
    soft_block_suspected and low confidence; the prose pages do not; nothing is blocked.
    """
    links = linked("soft")
    assert links.index("thin.html") >= CRAWL.median_min_pages
    base = serve_site("soft")
    out = initialised(base, tmp_path / "out")
    code, _ = synced(out)
    assert code is ExitCode.ok
    for href in links:
        name = href.removesuffix(".html")
        raw, _ = split_page(page_file(out, base, name).read_text(encoding="utf-8"))
        frontmatter = {key: json.loads(value) for key, value in raw.items()}
        flags = frontmatter["quality_flags"]
        assert isinstance(flags, list)
        soft = href in {"thin.html", "login.html"}
        assert ("soft_block_suspected" in flags) is soft, href
        if soft:
            assert frontmatter["low_confidence"] is True, href
    data = report(out)
    assert data["blocked_urls"] == []
    assert data["breaker_tripped"] is False


def long_delay() -> Answer:
    """robots.txt whose Crawl-delay is past retry_after_cap."""
    return Answer(200, {}, f"User-agent: *\nCrawl-delay: {PAST_CAP_SECONDS}\n")


def page_events(lines: list[str]) -> list[object]:
    """The url of each page event, in order."""
    events = [json.loads(line) for line in lines]
    return [event["url"] for event in events if event["event"] == "page"]


def test_a_hop_whose_robots_txt_retires_its_own_host_stops_the_walk(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """A page's hop onto its own host's other origin, whose robots.txt retires the host.

    p01.html redirects to the soft site's start page, served on another port of
    127.0.0.1; that origin's robots.txt has a Crawl-delay past the cap, so reading it
    retires the host and the hop is refused. The walk makes no further request
    (StopWalkOnTrippedHost): p01.html is asked once, not http_attempts times, and is
    skipped, not failed; a page event names it, since a fetch settled; every other link
    is skipped unrequested; the sync exits 3.
    """
    assert CRAWL.http_attempts > 1
    other = serve_site("soft", always={ROBOTS_PATH: long_delay()})
    links = linked("blocks")
    first = links[0]
    base = serve_site(
        "blocks",
        always={f"/guide/{first}": Answer(301, {"Location": f"{other}guide/start.html"})},
    )
    out = initialised(base, tmp_path / "out")
    code, lines = synced(out)
    assert code is ExitCode.blocked
    data = report(out)
    assert data["breaker_tripped"] is True
    assert data["skipped_urls"] == sorted(f"{base}guide/{href}" for href in links)
    assert f"{base}guide/{first}" not in [row["url"] for row in rows(data, "failed_urls")]
    assert serve_site.paths(base).count(f"/guide/{first}") == 1
    assert serve_site.paths(other) == [ROBOTS_PATH]
    assert page_events(lines) == [f"{base}guide/start.html", f"{base}guide/{first}"]


def test_a_seed_whose_own_robots_txt_retires_the_host_is_skipped(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """A second start URL on another origin of the host, whose robots.txt retires it.

    The soft site's start page, on another port of 127.0.0.1, is a second start URL; its
    origin's robots.txt, read before its first page (ReadRobotsForNewOrigin), has a
    Crawl-delay past the cap. The row is skipped_blocked, never requested
    (SkipTrippedHostAfterReady), so the batch goes idle and the next batch's rows, the
    first site's links, are skipped as the tripped host's rows: every one is in
    skipped_urls, none requested, and only the first start page raised a page event.
    """
    other = serve_site("soft", always={ROBOTS_PATH: long_delay()})
    base = serve_site("blocks")
    out = initialised(base, tmp_path / "out")
    starts = [f"{base}guide/start.html", f"{other}guide/start.html"]
    set_key(out, "start_urls", json.dumps(starts))
    code, lines = synced(out)
    assert code is ExitCode.blocked
    data = report(out)
    links = linked("blocks")
    assert data["skipped_urls"] == sorted([starts[1], *(f"{base}guide/{href}" for href in links)])
    assert serve_site.paths(other) == [ROBOTS_PATH]
    for href in links:
        assert f"/guide/{href}" not in serve_site.paths(base)
    assert page_events(lines) == [starts[0]]
