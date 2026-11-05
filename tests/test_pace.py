"""Politeness on unit inputs: the timer seam, retry_wait, pacing, robots matching (T12).

Hand-written: the `SiteExchange` surface's `Politeness` guarantee, the retry contract of a
robots.txt try (crawl.allium FetchRobots guidance) and `SyncExitCodes`' partial cases have
no obligation id of their own. Runs are driven over a FakeFetcher wrapped in a
StampingFetcher, on a SteppingTimer: its time moves only when the limiter sleeps, so the
gap between two stamps is the wait the limiter chose, and nothing sleeps for real. The
one test of the real timer replaces `pace.time.sleep` and `pace.time.monotonic` first.
"""

import dataclasses
import json
from datetime import timedelta
from pathlib import Path

import pytest

from fakes import (
    START,
    FakeFetcher,
    FixedClock,
    ScriptedFetcher,
    StampingFetcher,
    SteppingTimer,
    fixture_site,
    gaps,
    html_response,
    text_response,
)
from rovo import _commands
from rovo._convert import profiles
from rovo._crawl import pace
from rovo._crawl.model import (
    CONFIG,
    CrawlPolicy,
    FrontierStatus,
    RenderMode,
    RobotsStance,
    RunKind,
    RunMode,
    RunRequest,
    RunStatus,
    SiteResponse,
    StealthMode,
    standard_policy,
)
from rovo._crawl.pace import SystemTimer, anchored_now, retry_wait
from rovo._crawl.run import (
    CrawlResult,
    create_frontier,
    open_host,
    robots_allows,
    run_crawl,
    start_run,
)
from rovo._mirror.model import CrawlScope, Mirror, Operator, Tier
from rovo._mirror.state import save_mirror
from rovo._report import ExitCode, report_path
from rovo._unfinished import NotInThisSlice
from test_crawl import NULL_DELAYS, PAST_CAP_DELAYS, PAST_CAP_IDS, TINY_DELAY

SITE = "http://docs.example"
HOST = "docs.example"
SEED = f"{SITE}/guide/start.html"
ROBOTS = f"{SITE}/robots.txt"
# T13: the sitemaps and llms.txt every host whose robots.txt allows them is asked for,
# after its robots.txt and before any page (tickets/T13-discovery.md Facts).
PROBES = [f"{SITE}/sitemap.xml", f"{SITE}/sitemap_index.xml", f"{SITE}/llms.txt"]
A_PAGE = f"{SITE}/guide/a.html"
FLAKY = f"{SITE}/guide/flaky.html"
SECRET = f"{SITE}/guide/private/secret.html"
PORTED = "http://docs.example:8080"
PORTED_ROBOTS = f"{PORTED}/robots.txt"
PORTED_PAGES = (f"{PORTED}/guide/x.html", f"{PORTED}/guide/y.html")
SERVICE_UNAVAILABLE = 503
TOO_MANY = 429
# timedelta keeps microseconds: a spacing of 1 / rate may round down by one.
EPSILON = timedelta(microseconds=1)
NO_DELAY = "User-agent: *\nDisallow: /guide/private/\n"
POLITE_DELAY = timedelta(seconds=3)
FRACTIONAL_DELAY = timedelta(seconds=1.5)
FIRST_ORIGIN_DELAY = timedelta(seconds=2)
SECOND_ORIGIN_DELAY = timedelta(seconds=3)
RETRY_AFTER = timedelta(seconds=4)
# The index.html fold (crawl.allium fa096c4): the directory /guide/private/index.html folds into.
FOLD = "Disallow: /guide/private/\nAllow: /guide/private/index.html"
FOLDED = f"{SITE}/guide/private/"
# The literal-$ copy (crawl.allium fa096c4): a line ending in $ also matches with it as %24.
DOLLAR_ALLOW = "Disallow: /guide/private/\nAllow: /guide/private/$"
DOLLAR_DENY = "Allow: /\nDisallow: /guide/x$"
PAGE_HTML = """<!doctype html>
<html lang="en">
    <head><title>{title} | Example docs</title></head>
    <body>
        <main>
            <h1>{title}</h1>
            <p>{prose}</p>
        </main>
    </body>
</html>
"""


def new_mirror(out_dir: Path) -> Mirror:
    """An initialised mirror of the polite site served from SITE."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mirror = Mirror(
        out_dir=out_dir,
        scope=CrawlScope(
            root_url=f"{SITE}/guide/",
            start_urls=(SEED,),
            allowed_hosts=frozenset({HOST}),
            path_prefixes=("/guide/",),
            include=(),
            exclude=(),
            max_depth=10,
            locale=None,
            meaningful_query_params=(),
            locale_codes=frozenset(),
        ),
        profile=profiles.GENERIC,
        processing_signature="signature-1",
    )
    save_mirror(mirror)
    return mirror


def request(mirror: Mirror, policy: CrawlPolicy | None = None) -> RunRequest:
    """A standard full run's RunRequested."""
    return RunRequest(
        operator=Operator(),
        mirror=mirror,
        id=1,
        kind=RunKind.initial,
        mode=RunMode.standard,
        scope_hash="scope-1",
        owned_hosts=frozenset(),
        policy=policy or standard_policy(),
        dry_run=False,
        interactive=False,
        render_mode=RenderMode.never,
        stealth_mode=StealthMode.off,
        targets=frozenset(),
    )


def polite(robots: str | None = NO_DELAY) -> dict[str, SiteResponse]:
    """tests/fixtures/sites/polite served from SITE, its robots.txt replaced by `robots`."""
    responses = fixture_site("polite", f"{SITE}/")
    if robots is None:
        del responses[ROBOTS]
    else:
        responses[ROBOTS] = text_response(ROBOTS, robots)
    return responses


def paced(
    out_dir: Path, fetcher: FakeFetcher, policy: CrawlPolicy | None = None
) -> tuple[CrawlResult, StampingFetcher, SteppingTimer]:
    """One standard run over `fetcher`, every request stamped on a SteppingTimer."""
    timer = SteppingTimer()
    stamping = StampingFetcher(fetcher, timer)
    result = run_crawl(request(new_mirror(out_dir), policy), None, stamping, timer)
    return result, stamping, timer


def to_host(stamping: StampingFetcher, origin: str = SITE) -> list[str]:
    """The stamped URLs on `origin`, in order."""
    return [url for url, _ in stamping.stamps if url.startswith(f"{origin}/")]


def spacing() -> timedelta:
    """1 / rate_per_host, the least gap between two requests to one host."""
    rate = standard_policy().rate_per_host
    assert rate is not None
    return timedelta(seconds=1 / rate)


def allows(out_dir: Path, robots: str, url: str) -> bool:
    """robots_allows for `url` once robots.txt answered `robots`."""
    run = start_run(request(new_mirror(out_dir)), FixedClock())
    assert run is not None
    assert create_frontier(run, None) is not None
    open_host(run, HOST, SITE, FakeFetcher({ROBOTS: text_response(ROBOTS, robots)}))
    policy = run.robots_policy(SITE)
    assert policy is not None
    assert policy.stance is RobotsStance.rules
    return robots_allows(run, url)


def two_origin_site() -> FakeFetcher:
    """A seed on SITE (Crawl-delay 2) linking two pages on PORTED (Crawl-delay 3)."""
    links = " and ".join(f'<a href="{url}">a page on the other port</a>' for url in PORTED_PAGES)
    responses = {
        ROBOTS: text_response(ROBOTS, "User-agent: *\nCrawl-delay: 2\n"),
        PORTED_ROBOTS: text_response(PORTED_ROBOTS, "User-agent: *\nCrawl-delay: 3\n"),
        SEED: html_response(
            SEED, PAGE_HTML.format(title="Getting started", prose=f"Read {links} next.")
        ),
    }
    for number, url in enumerate(PORTED_PAGES):
        prose = f"Page {number} on the second port explains one setting of the product."
        responses[url] = html_response(url, PAGE_HTML.format(title=f"Port {number}", prose=prose))
    return FakeFetcher(responses)


# --- The timer seam -------------------------------------------------------------------


def test_system_timer_delegates_to_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """SystemTimer sleeps through time.sleep and advances by exactly the monotonic delta."""
    slept: list[float] = []
    readings = [100.0, 101.0, 103.5]

    def monotonic() -> float:
        """The next reading; the last one repeats."""
        return readings.pop(0) if len(readings) > 1 else readings[0]

    monkeypatch.setattr(pace.time, "sleep", slept.append)
    monkeypatch.setattr(pace.time, "monotonic", monotonic)
    timer = SystemTimer()
    first = timer.now()
    second = timer.now()
    assert second - first == timedelta(seconds=2.5)
    assert first.tzinfo is not None
    assert first.utcoffset() == timedelta(0)
    timer.sleep(1.5)
    assert slept == [1.5]


def test_anchored_now_adds_the_monotonic_delta() -> None:
    """anchored_now is the wall-clock anchor plus the monotonic time since the anchor."""
    assert anchored_now(START, 50.0, 52.25) == START + timedelta(seconds=2.25)
    assert anchored_now(START, 50.0, 50.0) == START


# --- retry_wait -------------------------------------------------------------------------


def middle(low: float, high: float) -> float:
    """The midpoint of the jitter range: a factor of 1."""
    return (low + high) / 2


def test_retry_wait_doubles_per_try_up_to_max_backoff() -> None:
    """min(backoff_base * 2^(try - 1), max_backoff), unscaled at a jitter factor of 1."""
    policy = standard_policy()
    for try_ in range(1, CONFIG.http_attempts + 2):
        expected = min(policy.backoff_base * 2 ** (try_ - 1), policy.max_backoff)
        assert retry_wait(try_, None, policy, middle) == expected, try_
    capped = CONFIG.http_attempts + 1
    assert retry_wait(capped, None, policy, middle) == policy.max_backoff


def test_retry_wait_scales_by_a_drawn_jitter_factor() -> None:
    """The wait is scaled by a factor drawn from [1 - backoff_jitter, 1 + backoff_jitter]."""
    policy = standard_policy()
    drawn: list[tuple[float, float]] = []

    def lowest(low: float, high: float) -> float:
        drawn.append((low, high))
        return low

    def highest(low: float, high: float) -> float:
        drawn.append((low, high))
        return high

    base = policy.backoff_base * 2
    assert retry_wait(2, None, policy, lowest) == base * (1 - CONFIG.backoff_jitter)
    assert retry_wait(2, None, policy, highest) == base * (1 + CONFIG.backoff_jitter)
    bounds = (1 - CONFIG.backoff_jitter, 1 + CONFIG.backoff_jitter)
    assert drawn == [bounds, bounds]


def test_retry_wait_is_lengthened_by_a_retry_after() -> None:
    """A Retry-After lengthens the wait to at least itself; a shorter one changes nothing."""
    policy = standard_policy()
    assert retry_wait(1, RETRY_AFTER, policy, middle) >= RETRY_AFTER
    longest = policy.max_backoff
    assert retry_wait(CONFIG.http_attempts, RETRY_AFTER, policy, middle) == longest


def test_retry_wait_with_its_controls_off() -> None:
    """With a control off (owner testing only, here on unit inputs) its effect is gone.

    Without retry_backoff there is no backoff and no draw; without honor_retry_after, a
    Retry-After does not lengthen the wait.
    """
    drawn: list[tuple[float, float]] = []

    def recorded(low: float, high: float) -> float:
        drawn.append((low, high))
        return 1.0

    no_backoff = dataclasses.replace(standard_policy(), retry_backoff=False)
    assert retry_wait(3, None, no_backoff, recorded) == timedelta(0)
    assert retry_wait(3, RETRY_AFTER, no_backoff, recorded) == RETRY_AFTER
    assert drawn == []
    no_retry_after = dataclasses.replace(standard_policy(), honor_retry_after=False)
    assert retry_wait(1, RETRY_AFTER, no_retry_after, middle) == no_retry_after.backoff_base


# --- Politeness: rate, Crawl-delay, pause and robots ---------------------------------------


def test_Politeness_requests_to_a_host_are_spaced_by_its_rate(tmp_path: Path) -> None:
    """With no Crawl-delay, the starts of two requests to one host are 1 / rate apart.

    No burst: robots.txt and the first page are spaced too.
    """
    result, stamping, _ = paced(tmp_path, FakeFetcher(polite()))
    assert result.run.status is RunStatus.finished
    urls = to_host(stamping)
    assert urls[0] == ROBOTS
    assert urls == [ROBOTS, *PROBES, SEED, A_PAGE, FLAKY]
    for gap in gaps(stamping.stamps):
        assert gap >= spacing() - EPSILON


def test_Politeness_crawl_delay_spaces_requests(tmp_path: Path) -> None:
    """A Crawl-delay of 3 spaces every request to the host by at least 3 s."""
    result, stamping, _ = paced(tmp_path, FakeFetcher(polite("User-agent: *\nCrawl-delay: 3\n")))
    (host,) = result.run.hosts
    assert host.crawl_delay == POLITE_DELAY
    assert [url for url, _ in stamping.stamps] == [ROBOTS, *PROBES, SEED, A_PAGE, FLAKY, SECRET]
    for gap in gaps(stamping.stamps):
        assert gap >= POLITE_DELAY - EPSILON


def test_Politeness_a_fractional_crawl_delay_is_read_and_honoured(tmp_path: Path) -> None:
    """Crawl-delay: 1.5 is a decimal number of seconds: the gaps are at least 1.5 s."""
    fetcher = FakeFetcher(polite("User-agent: *\nCrawl-delay: 1.5\n"))
    result, stamping, _ = paced(tmp_path, fetcher)
    policy = result.run.robots_policy(SITE)
    assert policy is not None
    assert policy.crawl_delay == FRACTIONAL_DELAY
    (host,) = result.run.hosts
    assert host.crawl_delay == FRACTIONAL_DELAY
    for gap in gaps(stamping.stamps):
        assert gap >= FRACTIONAL_DELAY - EPSILON


def test_Politeness_crawl_delay_zero_adds_no_delay(tmp_path: Path) -> None:
    """Crawl-delay: 0 leaves the rate unchanged: the gaps are the rate's spacing alone."""
    fetcher = FakeFetcher(polite("User-agent: *\nCrawl-delay: 0\n"))
    result, stamping, _ = paced(tmp_path, fetcher)
    (host,) = result.run.hosts
    assert host.rate == standard_policy().rate_per_host
    assert host.crawl_delay == timedelta(0)
    for gap in gaps(stamping.stamps):
        assert spacing() - EPSILON <= gap <= spacing() + EPSILON


def test_Politeness_a_crawl_delay_equal_to_the_cap_is_honoured(tmp_path: Path) -> None:
    """A Crawl-delay equal to retry_after_cap is adopted and spaces the host (71b5b0f).

    It is not past the cap, so the host is not retired and the run finishes.
    """
    cap = standard_policy().retry_after_cap
    fetcher = FakeFetcher(polite(f"User-agent: *\nCrawl-delay: {cap.total_seconds():g}\n"))
    result, stamping, _ = paced(tmp_path, fetcher)
    assert result.run.status is RunStatus.finished
    (host,) = result.run.hosts
    assert host.crawl_delay == cap
    for gap in gaps(stamping.stamps):
        assert gap >= cap - EPSILON


@pytest.mark.parametrize("written", PAST_CAP_DELAYS, ids=PAST_CAP_IDS)
def test_Politeness_a_crawl_delay_past_the_cap_never_reaches_the_limiter(
    tmp_path: Path, written: str
) -> None:
    """A Crawl-delay past retry_after_cap is never adopted, so the limiter never sees it.

    crawl.allium AdoptRobotsRules and RetireHostOnLongCrawlDelay at 71b5b0f: the delay is
    compared as written and never becomes a Duration, whatever honor_crawl_delay says.
    With Crawl-delay not honoured (owner testing only, here on unit inputs) the host is
    not retired: the run finishes, the policy records no delay, and the gaps are the
    rate's spacing alone. No value overflows a timedelta or an instant.
    """
    ignored = dataclasses.replace(standard_policy(), honor_crawl_delay=False)
    fetcher = FakeFetcher(polite(f"User-agent: *\nCrawl-delay: {written}\n"))
    result, stamping, _ = paced(tmp_path, fetcher, ignored)
    assert result.run.status is RunStatus.finished
    policy = result.run.robots_policy(SITE)
    assert policy is not None
    assert policy.stance is RobotsStance.rules
    assert policy.crawl_delay is None
    (host,) = result.run.hosts
    assert host.crawl_delay == timedelta(0)
    assert host.rate == standard_policy().rate_per_host
    assert [url for url, _ in stamping.stamps] == [ROBOTS, *PROBES, SEED, A_PAGE, FLAKY, SECRET]
    for gap in gaps(stamping.stamps):
        assert spacing() - EPSILON <= gap <= spacing() + EPSILON


@pytest.mark.parametrize("written", [*NULL_DELAYS, TINY_DELAY])
def test_Politeness_a_crawl_delay_that_is_no_delay_leaves_the_rate_alone(
    tmp_path: Path, written: str
) -> None:
    """A Crawl-delay that is no number, or rounds to none, neither spaces nor retires the host.

    crawl.allium robots_crawl_delay (AdoptRobotsRules' guidance): null when the value is
    not a number, so inf, nan, a negative number, words and misplaced underscores are no
    Crawl-delay; a number too small for Decimal's exponent is 0, no delay. With
    Crawl-delay honoured the run finishes, nothing is retired, and the gaps are the rate's
    spacing alone (reviews T12-2-r2 C1 and T12-3-r2 C1/C2).
    """
    fetcher = FakeFetcher(polite(f"User-agent: *\nCrawl-delay: {written}\n"))
    result, stamping, _ = paced(tmp_path, fetcher)
    assert result.run.status is RunStatus.finished
    policy = result.run.robots_policy(SITE)
    assert policy is not None
    assert policy.stance is RobotsStance.rules
    assert policy.crawl_delay == (timedelta(0) if written == TINY_DELAY else None)
    (host,) = result.run.hosts
    assert host.crawl_delay == timedelta(0)
    assert host.rate == standard_policy().rate_per_host
    assert [url for url, _ in stamping.stamps] == [ROBOTS, *PROBES, SEED, A_PAGE, FLAKY, SECRET]
    for gap in gaps(stamping.stamps):
        assert spacing() - EPSILON <= gap <= spacing() + EPSILON


def test_Politeness_the_longest_crawl_delay_of_a_hosts_origins_wins(tmp_path: Path) -> None:
    """Two origins of one host name: the longer Crawl-delay spaces the host name.

    Each robots.txt is read once, before any page at its origin; once the second origin's
    longer Crawl-delay is read it spaces every request to the host name.
    """
    result, stamping, _ = paced(tmp_path, two_origin_site())
    urls = [url for url, _ in stamping.stamps]
    assert urls[: len(PROBES) + 2] == [ROBOTS, *PROBES, SEED]
    assert urls.count(PORTED_ROBOTS) == 1
    second_robots = urls.index(PORTED_ROBOTS)
    assert all(urls.index(page) > second_robots for page in PORTED_PAGES)
    spaced = gaps(stamping.stamps)
    for gap in spaced[:second_robots]:
        assert gap >= FIRST_ORIGIN_DELAY - EPSILON
    for gap in spaced[second_robots:]:
        assert gap >= SECOND_ORIGIN_DELAY - EPSILON
    (host,) = result.run.hosts
    assert host.crawl_delay == SECOND_ORIGIN_DELAY


def test_Politeness_nothing_is_requested_before_the_hosts_pause(tmp_path: Path) -> None:
    """A 503 with a Retry-After pauses the host: its next request waits it out."""
    retry = dataclasses.replace(
        html_response(SEED, "", status=SERVICE_UNAVAILABLE), retry_after=RETRY_AFTER
    )
    fetcher = ScriptedFetcher(polite(), {SEED: [retry]})
    result, stamping, timer = paced(tmp_path, fetcher)
    (backed_off,) = result.backed_off
    seed_times = [when for url, when in stamping.stamps if url == SEED]
    assert len(seed_times) == len(["503", "ok"])
    assert seed_times[1] - seed_times[0] >= RETRY_AFTER
    for _, when in stamping.stamps[stamping.stamps.index((SEED, seed_times[1])) :]:
        assert when >= backed_off.until
    assert max(timer.sleeps) >= RETRY_AFTER.total_seconds()


def test_Politeness_robots_txt_is_the_first_request_to_an_origin(tmp_path: Path) -> None:
    """robots.txt is read before anything else at its origin, on a site with no file too."""
    _, stamping, _ = paced(tmp_path, FakeFetcher(polite(None)))
    assert next(url for url, _ in stamping.stamps) == ROBOTS
    _, two, _ = paced(tmp_path / "two", two_origin_site())
    for origin in (SITE, PORTED):
        assert to_host(two, origin)[0] == f"{origin}/robots.txt"


def test_Politeness_every_request_is_one_its_origins_robots_allow(tmp_path: Path) -> None:
    """Every page requested is allowed by its own origin's policy; a disallowed one never is."""
    result, stamping, _ = paced(tmp_path, FakeFetcher(polite()))
    pages = [url for url, _ in stamping.stamps if not url.endswith("/robots.txt")]
    assert pages
    assert all(robots_allows(result.run, url) for url in pages)
    assert SECRET not in pages
    entry = result.frontier.entry(SECRET)
    assert entry is not None
    assert entry.status is FrontierStatus.skipped_robots


@pytest.mark.parametrize(
    ("robots", "url", "allowed"),
    [
        pytest.param("Disallow: /guide/\nAllow: /guide/start.html", SEED, True, id="longer-allow"),
        pytest.param("Allow: /guide/start.html\nDisallow: /guide/", SEED, True, id="allow-first"),
        pytest.param("Disallow: /guide/\nAllow: /guide/start.html", A_PAGE, False, id="shorter"),
        pytest.param("Allow: /guide/\nDisallow: /guide/private/", SECRET, False, id="longer-deny"),
        pytest.param(
            "Disallow: /guide/start.html\nAllow: /guide/start.html", SEED, True, id="tie"
        ),
        pytest.param("Disallow: /*/private/", SECRET, False, id="star"),
        pytest.param("Disallow: /*/private/", SEED, True, id="star-elsewhere"),
        pytest.param("Disallow: /guide/start.html$", SEED, False, id="dollar"),
        pytest.param("Disallow: /guide/start.html$", f"{SEED}.bak", True, id="dollar-longer"),
        pytest.param(FOLD, FOLDED, True, id="index-fold"),
        pytest.param(FOLD, f"{FOLDED}index.html", True, id="index-fold-page"),
        pytest.param(FOLD, f"{FOLDED}?a=1", False, id="index-fold-query"),
        pytest.param(FOLD, SECRET, False, id="index-fold-other-page"),
        pytest.param(
            "Disallow: /guide/private/\nAllow: /guide/private/index.htm",
            FOLDED,
            False,
            id="no-fold-index-htm",
        ),
        pytest.param(
            "Disallow: /guide/private/\nAllow: /guide/private/INDEX.HTML",
            FOLDED,
            False,
            id="no-fold-upper-case",
        ),
        pytest.param(
            "Disallow: /guide/private/\nAllow: /guide/private/index.html$",
            FOLDED,
            False,
            id="no-fold-final-dollar",
        ),
        pytest.param("Disallow: /guide/private/index.html", FOLDED, True, id="no-disallow-fold"),
        pytest.param(DOLLAR_ALLOW, FOLDED, True, id="dollar-copy-directory"),
        pytest.param(DOLLAR_ALLOW, f"{FOLDED}$secret", True, id="dollar-copy-allows-dollar"),
        pytest.param(DOLLAR_ALLOW, f"{FOLDED}%24secret", True, id="dollar-copy-allows-encoded"),
        pytest.param(DOLLAR_ALLOW, f"{FOLDED}x", False, id="dollar-copy-other-page"),
        pytest.param(DOLLAR_ALLOW, f"{FOLDED}?a=1", False, id="dollar-copy-query"),
        pytest.param(DOLLAR_DENY, f"{SITE}/guide/x", False, id="dollar-copy-denies-path"),
        pytest.param(DOLLAR_DENY, f"{SITE}/guide/x$y", False, id="dollar-copy-denies-dollar"),
        pytest.param(DOLLAR_DENY, f"{SITE}/guide/xy", True, id="dollar-copy-allows-longer"),
        pytest.param(FOLD, f"{FOLDED}$secret", False, id="no-dollar-copy-of-the-fold"),
    ],
)
def test_robots_rules_match_as_rfc_9309_says(
    tmp_path: Path, robots: str, url: str, *, allowed: bool
) -> None:
    """RFC 9309 matching as protego 0.7 implements it (crawl.allium fa096c4).

    In RFC 9309's terms the longest matching path wins, Allow wins a tie, and `*` and a
    final `$` are wildcards (crawl.allium FetchSitemap guidance, 1037 to 1077 at ecfa257).
    The index.html fold (1052 to 1060, review T12-2-r2 B2): an Allow path ending in
    "/index.html" with no final `$` also allows its directory, as though "index.html"
    were replaced by `$`, so the directory's identity is allowed while a query on it is
    not. Nothing else folds: not "index.htm", not "INDEX.HTML", not an Allow with a final
    `$`, and never a Disallow line. The literal-$ copy (1061 to 1077, review T12-2-r3 C1):
    a line ending in `$` also matches as a prefix with that `$` written "%24", and a `$`
    in a request path is compared as "%24", so "Allow: /guide/private/$" allows
    "/guide/private/$secret" and "Disallow: /guide/x$" denies "/guide/x$y"; the line the
    fold adds gets no copy.
    """
    assert allows(tmp_path, f"User-agent: *\n{robots}\n", url) is allowed


# --- A robots.txt try is retried as a page's http try --------------------------------------


def test_a_robots_txt_retry_backs_off_and_counts_its_retry_after(tmp_path: Path) -> None:
    """A robots.txt answering 503 with Retry-After, then its file, is retried as a page.

    One HostBackedOff, one honoured Retry-After, both tries' bytes counted, and no try
    counted as a fetch attempt.
    """
    busy = dataclasses.replace(
        text_response(ROBOTS, "", status=SERVICE_UNAVAILABLE), retry_after=timedelta(seconds=2)
    )
    responses = polite()
    fetcher = ScriptedFetcher(responses, {ROBOTS: [busy]})
    result, stamping, _ = paced(tmp_path, fetcher)
    assert fetcher.count(ROBOTS) == len(["503", "ok"])
    (backed_off,) = result.backed_off
    (host,) = result.run.hosts
    assert backed_off.host is host
    assert host.retry_after_honored == 1
    policy = result.run.robots_policy(SITE)
    assert policy is not None
    assert policy.stance is RobotsStance.rules
    robots_times = [when for url, when in stamping.stamps if url == ROBOTS]
    assert robots_times[1] - robots_times[0] >= timedelta(seconds=2)
    pages = [
        url for url in fetcher.requests if not url.endswith("/robots.txt") and url not in PROBES
    ]
    assert result.run.fetch_attempts == len(pages)
    page_bytes = sum(responses[url].size for url in pages)
    assert result.run.bytes_fetched == busy.size + responses[ROBOTS].size + page_bytes


def test_a_robots_retry_after_past_the_cap_stops_the_run(tmp_path: Path) -> None:
    """A Retry-After past retry_after_cap on a robots.txt try stops the run.

    It retires the host, which is the breaker slice's trip, so the run stops there
    (RetireHostOnLongRetryAfter).
    """
    past = standard_policy().retry_after_cap + timedelta(seconds=1)
    busy = dataclasses.replace(text_response(ROBOTS, "", status=TOO_MANY), retry_after=past)
    fetcher = ScriptedFetcher(polite(), {ROBOTS: [busy]})
    with pytest.raises(NotInThisSlice) as stopped:
        paced(tmp_path, fetcher)
    assert stopped.value.rule == "RetireHostOnLongRetryAfter"
    assert fetcher.requests == [ROBOTS]


# --- SyncExitCodes: what makes a sync partial --------------------------------------------


def synced(out_dir: Path, fetcher: FakeFetcher) -> tuple[ExitCode, dict[str, object]]:
    """Rovo init then rovo sync over `fetcher`; the exit code and crawl-report.json."""
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    code = _commands.sync(
        out_dir, fetcher=fetcher, clock=SteppingTimer(), tier_installed=no_engine
    )
    loaded = json.loads(report_path(out_dir).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return code, loaded


def no_engine(tier: Tier) -> bool:
    """No engine beyond http is installed."""
    del tier
    return False


def test_SyncExitCodes_a_failed_url_makes_the_sync_partial(tmp_path: Path) -> None:
    """A page that answers 503 on every try is a failed URL: exit 1, the others written."""
    responses = polite()
    responses[FLAKY] = html_response(FLAKY, "", status=SERVICE_UNAVAILABLE)
    code, report = synced(tmp_path, FakeFetcher(responses))
    assert code is ExitCode.partial
    assert report["exit_code"] == "partial"
    rows = report["failed_urls"]
    assert isinstance(rows, list)
    (row,) = rows
    assert row["url"] == FLAKY
    assert row["attempts"] == CONFIG.http_attempts
    assert isinstance(row["error"], str)
    assert row["error"]
    assert report["discovery_problems"] == []
    assert {"kind": "failed", "url": FLAKY, "path": None, "moved_from": None} in (
        report["changes"] if isinstance(report["changes"], list) else []
    )


def test_SyncExitCodes_a_discovery_problem_makes_the_sync_partial(tmp_path: Path) -> None:
    """A refused robots.txt is a discovery problem: exit 1 and no page requested."""
    responses = polite()
    responses[ROBOTS] = text_response(ROBOTS, "", status=SERVICE_UNAVAILABLE)
    fetcher = FakeFetcher(responses)
    code, report = synced(tmp_path, fetcher)
    assert code is ExitCode.partial
    assert report["exit_code"] == "partial"
    assert report["discovery_problems"] == [{"url": ROBOTS, "problem": "robots_refused"}]
    assert report["failed_urls"] == []
    assert set(fetcher.requests) == {ROBOTS}
    assert len(fetcher.requests) == CONFIG.http_attempts


def test_SyncExitCodes_a_robots_skipped_page_alone_leaves_the_sync_ok(tmp_path: Path) -> None:
    """A page robots.txt disallows is skipped and unresolved, but alone it exits 0."""
    code, report = synced(tmp_path, FakeFetcher(polite()))
    assert code is ExitCode.ok
    assert report["exit_code"] == "ok"
    assert report["unresolved_urls"] == [SECRET]
    assert report["failed_urls"] == []
    assert report["discovery_problems"] == []


def test_waits_never_hang_on_a_timer_that_stands_still(tmp_path: Path) -> None:
    """On a FixedClock every wait is computed once and recorded, never looped on."""
    fetcher = FakeFetcher(polite("User-agent: *\nCrawl-delay: 3\n"))
    clock = FixedClock()
    result = run_crawl(request(new_mirror(tmp_path)), None, fetcher, clock)
    assert result.run.status is RunStatus.finished
    assert clock.instant == START
    assert clock.sleeps
    assert len(clock.sleeps) <= len(fetcher.requests)
    assert all(0 <= seconds <= POLITE_DELAY.total_seconds() for seconds in clock.sleeps)
