"""End to end: rovo sync is polite to a served site (T12).

It reads each origin's robots.txt before anything else there, skips what it disallows,
spaces its requests to one host name by its rate and the longest Crawl-delay, retries a
503 with backoff and Retry-After, and exits 1 when a page or a robots.txt fails. The
in-process scenarios run `rovo._commands.sync` over the real HttpxFetcher wrapped in a
StampingFetcher, on a SteppingTimer: the gaps are read off the stamps, the order off the
server's request log, and nothing sleeps. The command-line scenario replaces the sleep
the crawl's pacing calls; only the installed-script scenario waits, inside the `rovo`
process. Not `test_pace.py`, which the unit suite already names.
"""

import shutil
import time
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import DROP, SITES, Answer, SiteServer
from test_init_sync import load, markdown_files, page_root, rovo
from typer.testing import CliRunner

from fakes import StampingFetcher, SteppingTimer, gaps
from rovo import _commands
from rovo._crawl import pace
from rovo._crawl.fetch import HttpxFetcher
from rovo._crawl.model import CONFIG, standard_policy
from rovo._exit import ExitCode
from rovo.cli import app

FLAKY_PATH = "/guide/flaky.html"
PRIVATE_PATH = "/guide/private/secret.html"
NO_DELAY_ROBOTS = "User-agent: *\nDisallow: /guide/private/\n"
POLITE_DELAY = timedelta(seconds=3)
FIRST_ORIGIN_DELAY = timedelta(seconds=2)
SECOND_ORIGIN_DELAY = timedelta(seconds=5)
RETRY_AFTER = timedelta(seconds=4)
SERVICE_UNAVAILABLE = 503
SERVER_ERROR = 500
# timedelta keeps microseconds: a spacing of 1 / rate may round down by one.
EPSILON = timedelta(microseconds=1)
# Real time passes between the crawl setting a pause and the limiter reading the clock.
REAL_TIME_SLACK = 0.1
INSTALLED_DELAY = 2.0
INSTALLED_GAP = 1.8
PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title} | Example docs</title>
</head>
<body>
<main>
<h1>{title}</h1>
<p>{prose}</p>
</main>
</body>
</html>
"""


def page(directory: Path, path: str, title: str, prose: str) -> None:
    """Write one page of a generated site."""
    target = directory / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PAGE_HTML.format(title=title, prose=prose), encoding="utf-8")


def no_delay_copy(directory: Path) -> Path:
    """A copy of the polite site whose robots.txt declares no Crawl-delay.

    The host's spacing is then 1 / rate_per_host, below every backoff, so each wait the
    timer records before a retry is the backoff alone.
    """
    copy = shutil.copytree(SITES / "polite", directory)
    (copy / "robots.txt").write_text(NO_DELAY_ROBOTS, encoding="utf-8")
    return copy


def synced(base: str, out: Path) -> tuple[ExitCode, StampingFetcher, SteppingTimer]:
    """Rovo init on the site's guide/start.html, then rovo sync in process, stamped."""
    assert _commands.init(f"{base}guide/start.html", out) is ExitCode.ok
    timer = SteppingTimer()
    with HttpxFetcher() as fetcher:
        stamping = StampingFetcher(fetcher, timer)
        code = _commands.sync(out, fetcher=stamping, clock=timer)
    return code, stamping, timer


def statuses(out: Path) -> dict[str, str]:
    """Each frontier row's identity and status."""
    entries = load(out / ".rovo" / "frontier.json")["entries"]
    assert isinstance(entries, list)
    return {row["identity"]: row["status"] for row in entries}


def stamped(stamping: StampingFetcher, url: str) -> list[timedelta]:
    """The gaps between the requests to `url`."""
    return gaps([stamp for stamp in stamping.stamps if stamp[0] == url])


def backoff(try_: int) -> timedelta:
    """min(backoff_base * 2^(try - 1), max_backoff): the wait after try `try_`."""
    policy = standard_policy()
    wait: timedelta = min(policy.backoff_base * 2 ** (try_ - 1), policy.max_backoff)
    return wait


def jittered(try_: int) -> tuple[timedelta, timedelta]:
    """The backoff after try `try_`, scaled down and up by backoff_jitter."""
    wait = backoff(try_)
    return wait * (1 - CONFIG.backoff_jitter), wait * (1 + CONFIG.backoff_jitter)


def test_polite_sync_reads_robots_first_and_honours_its_crawl_delay(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """robots.txt first; the disallowed page never requested; every gap at least 3 s."""
    base = serve_site("polite")
    out = tmp_path / "out"
    code, stamping, _ = synced(base, out)
    assert code is ExitCode.ok
    paths = serve_site.paths(base)
    assert paths[0] == "/robots.txt"
    assert PRIVATE_PATH not in paths
    root = page_root(base)
    assert markdown_files(out) == [f"{root}a.md", f"{root}flaky.md", f"{root}start.md"]
    secret = f"{base}{PRIVATE_PATH.lstrip('/')}"
    assert statuses(out)[secret] == "skipped_robots"
    spaced = gaps(stamping.stamps)
    # T13: the two well-known sitemaps and llms.txt follow robots.txt, each spaced too.
    assert len(spaced) == len(
        ["sitemap.xml", "sitemap_index.xml", "llms.txt", "start", "a", "flaky"]
    )
    for gap in spaced:
        assert gap >= POLITE_DELAY - EPSILON
    report = load(out / "crawl-report.json")
    assert report["exit_code"] == "ok"
    assert report["unresolved_urls"] == [secret]


def test_a_503_with_retry_after_is_retried_after_the_wait(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """flaky.html answers 503 with Retry-After: 4, then the file: it is written."""
    base = serve_site(
        no_delay_copy(tmp_path / "site"),
        script={FLAKY_PATH: [Answer(SERVICE_UNAVAILABLE, {"Retry-After": "4"})]},
    )
    out = tmp_path / "out"
    code, stamping, timer = synced(base, out)
    assert code is ExitCode.ok
    assert serve_site.paths(base).count(FLAKY_PATH) == len(["503", "ok"])
    assert f"{page_root(base)}flaky.md" in markdown_files(out)
    (wait,) = stamped(stamping, f"{base}guide/flaky.html")
    assert wait >= RETRY_AFTER
    assert max(timer.sleeps) >= RETRY_AFTER.total_seconds()
    report = load(out / "crawl-report.json")
    hosts = report["per_host"]
    assert isinstance(hosts, list)
    (host,) = hosts
    assert host["retry_after_honored"] == 1
    assert report["fetched"] == len(["start", "a", "flaky", "flaky again"])
    assert report["exit_code"] == "ok"


def test_a_page_that_runs_out_of_retries_fails_and_the_sync_is_partial(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """flaky.html answers 503 every time: http_attempts tries, backed off, then failed."""
    base = serve_site(
        no_delay_copy(tmp_path / "site"), always={FLAKY_PATH: Answer(SERVICE_UNAVAILABLE)}
    )
    out = tmp_path / "out"
    code, stamping, _ = synced(base, out)
    assert code is ExitCode.partial
    assert serve_site.paths(base).count(FLAKY_PATH) == CONFIG.http_attempts
    flaky = f"{base}guide/flaky.html"
    waits = stamped(stamping, flaky)
    assert len(waits) == CONFIG.http_attempts - 1
    for try_, wait in enumerate(waits, start=1):
        low, high = jittered(try_)
        assert low - EPSILON <= wait <= high + EPSILON, try_
    report = load(out / "crawl-report.json")
    assert report["exit_code"] == "partial"
    failed = report["failed_urls"]
    assert isinstance(failed, list)
    (row,) = failed
    assert row["url"] == flaky
    assert row["attempts"] == CONFIG.http_attempts
    assert row["error"]
    changes = report["changes"]
    assert isinstance(changes, list)
    assert {"kind": "failed", "url": flaky, "path": None, "moved_from": None} in changes
    root = page_root(base)
    assert markdown_files(out) == [f"{root}a.md", f"{root}start.md"]
    assert statuses(out)[flaky] == "failed"


@pytest.mark.parametrize(
    ("answer", "problem"),
    [
        pytest.param(Answer(SERVER_ERROR), "robots_refused", id="refused"),
        pytest.param(DROP, "robots_unreachable", id="unreachable"),
    ],
)
def test_a_refused_or_unreachable_robots_txt_disallows_its_origin(
    serve_site: SiteServer, tmp_path: Path, answer: Answer, problem: str
) -> None:
    """robots.txt answering 500, or never answering, every time: no page is requested."""
    base = serve_site(no_delay_copy(tmp_path / "site"), always={"/robots.txt": answer})
    out = tmp_path / "out"
    code, _, _ = synced(base, out)
    assert code is ExitCode.partial
    assert serve_site.paths(base) == ["/robots.txt"] * CONFIG.http_attempts
    assert statuses(out) == {f"{base}guide/start.html": "skipped_robots"}
    assert markdown_files(out) == []
    report = load(out / "crawl-report.json")
    assert report["exit_code"] == "partial"
    assert report["discovery_problems"] == [{"url": f"{base}robots.txt", "problem": problem}]
    assert report["failed_urls"] == []


def test_rovo_sync_exits_1_through_the_command_line_when_robots_is_refused(
    serve_site: SiteServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through the command line, with the pacing sleep replaced: exit 1, the waits seen.

    The real timer reaches the replaced sleep, so the backoff between the robots.txt
    tries is recorded, never slept.
    """
    base = serve_site(
        no_delay_copy(tmp_path / "site"), always={"/robots.txt": Answer(SERVER_ERROR)}
    )
    out = tmp_path / "out"
    slept: list[float] = []
    runner = CliRunner()
    assert runner.invoke(app, ["init", f"{base}guide/start.html", str(out)]).exit_code == 0
    monkeypatch.setattr(pace.time, "sleep", slept.append)
    result = runner.invoke(app, ["sync", str(out)])
    assert result.exit_code == ExitCode.partial.number, result.output
    report = load(out / "crawl-report.json")
    assert report["exit_code"] == "partial"
    assert report["discovery_problems"] == [
        {"url": f"{base}robots.txt", "problem": "robots_refused"}
    ]
    waits = [seconds for seconds in slept if seconds > 0]
    assert len(waits) == CONFIG.http_attempts - 1
    for try_, wait in enumerate(waits, start=1):
        low, high = jittered(try_)
        assert low.total_seconds() - REAL_TIME_SLACK <= wait <= high.total_seconds(), try_


def two_origin_sites(serve_site: SiteServer, directory: Path) -> tuple[str, str]:
    """Two sites on two ports of 127.0.0.1: one host name, two origins.

    The second is served first, so the first's seed can link it by absolute URL.
    """
    second = directory / "second"
    second.mkdir(parents=True)
    (second / "robots.txt").write_text(
        "User-agent: *\nCrawl-delay: 5\nDisallow: /guide/closed/\n", encoding="utf-8"
    )
    page(
        second, "guide/open.html", "Open topic", "The open topic is mirrored from the second port."
    )
    page(second, "guide/closed/x.html", "Closed topic", "The closed topic is never requested.")
    second_base = serve_site(second)
    first = directory / "first"
    first.mkdir(parents=True)
    (first / "robots.txt").write_text("User-agent: *\nCrawl-delay: 2\n", encoding="utf-8")
    page(
        first,
        "guide/start.html",
        "Getting started",
        f'Read <a href="{second_base}guide/open.html">the open topic</a> and '
        f'<a href="{second_base}guide/closed/x.html">the closed topic</a> next.',
    )
    return serve_site(first), second_base


def test_two_origins_of_one_host_read_their_own_robots_and_share_its_pacing(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """The second origin's robots.txt is read once, before its pages; the longer delay wins."""
    first, second = two_origin_sites(serve_site, tmp_path / "sites")
    out = tmp_path / "out"
    code, stamping, _ = synced(first, out)
    assert code is ExitCode.ok
    assert serve_site.paths(second) == ["/robots.txt", "/guide/open.html"]
    urls = [url for url, _ in stamping.stamps]
    second_robots = urls.index(f"{second}robots.txt")
    assert urls.index(f"{first}robots.txt") < second_robots
    assert urls.count(f"{second}robots.txt") == 1
    spaced = gaps(stamping.stamps)
    assert spaced[:second_robots]
    assert spaced[second_robots:]
    for gap in spaced[:second_robots]:
        assert gap >= FIRST_ORIGIN_DELAY - EPSILON
    for gap in spaced[second_robots:]:
        assert gap >= SECOND_ORIGIN_DELAY - EPSILON
    rows = statuses(out)
    assert rows[f"{second}guide/open.html"] == "done"
    assert rows[f"{second}guide/closed/x.html"] == "skipped_robots"
    assert f"{page_root(second)}open.md" in markdown_files(out)
    assert load(out / "crawl-report.json")["exit_code"] == "ok"


def test_the_installed_script_waits_out_the_crawl_delay(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """Through the installed rovo, a Crawl-delay of 2 s spaces the seed and its page."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "robots.txt").write_text("User-agent: *\nCrawl-delay: 2\n", encoding="utf-8")
    page(site, "guide/start.html", "Getting started", 'Read <a href="page.html">the page</a>.')
    page(site, "guide/page.html", "The page", "The page explains one setting of the product.")
    base = serve_site(site)
    out = tmp_path / "out"
    init = rovo("init", f"{base}guide/start.html", str(out))
    assert init.returncode == 0, init.stderr
    began = time.monotonic()
    sync = rovo("sync", str(out))
    elapsed = time.monotonic() - began
    assert sync.returncode == 0, sync.stderr
    log = serve_site.log(base)
    assert [path for path, _ in log] == [
        "/robots.txt",
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/llms.txt",
        "/guide/start.html",
        "/guide/page.html",
    ]
    assert log[-1][1] - log[-2][1] >= INSTALLED_GAP
    assert elapsed >= INSTALLED_DELAY
