"""Politeness on unit inputs: the timer seam, retry_wait, pacing, robots matching (T12).

Hand-written: the `SiteExchange` surface's `Politeness` guarantee, the retry contract of a
robots.txt try (crawl.allium FetchRobots guidance) and `SyncExitCodes`' partial cases have
no obligation id of their own. Runs are driven over a FakeFetcher wrapped in a
StampingFetcher, on a SteppingTimer: its time moves only when the limiter sleeps, so the
gap between two stamps is the wait the limiter chose, and nothing sleeps for real. The
one test of the real timer replaces `pace.time.sleep` and `pace.time.monotonic` first.
"""

import dataclasses
import itertools
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
    redirect_response,
    text_response,
    xml_response,
)
from rovo import _commands
from rovo._convert import profiles
from rovo._crawl import pace
from rovo._crawl.fetch import Validators
from rovo._crawl.model import (
    CONFIG,
    CrawlPolicy,
    DiscoveryProblem,
    FrontierStatus,
    Host,
    RenderMode,
    RobotsStance,
    Run,
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
    load_frontier,
    open_host,
    robots_allows,
    run_crawl,
    start_run,
)
from rovo._mirror.model import CrawlScope, Mirror, Operator, Tier
from rovo._mirror.state import save_mirror
from rovo._report import ExitCode, report_path
from test_crawl import NULL_DELAYS, PAST_CAP_DELAYS, PAST_CAP_IDS, TINY_DELAY, urlset
from test_crawl import new_mirror as crawl_mirror
from test_crawl import request as crawl_request

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


def test_a_robots_retry_after_past_the_cap_retires_the_host(tmp_path: Path) -> None:
    """A Retry-After past retry_after_cap on a robots.txt try retires the host.

    Re-propagated by T18 from test_a_robots_retry_after_past_the_cap_stops_the_run (T12),
    which expected NotInThisSlice("RetireHostOnLongRetryAfter"): the breaker trips, the
    429 stands as robots_refused, robots.txt is the one request (spec 86e2ec5: no
    sitemap, llms.txt or page follows), and the seed is skipped.
    """
    past = standard_policy().retry_after_cap + timedelta(seconds=1)
    busy = dataclasses.replace(text_response(ROBOTS, "", status=TOO_MANY), retry_after=past)
    fetcher = ScriptedFetcher(polite(), {ROBOTS: [busy]})
    result, _, _ = paced(tmp_path, fetcher)
    assert fetcher.requests == [ROBOTS]
    assert result.run.has_tripped_host
    assert problems(result) == {(ROBOTS, DiscoveryProblem.robots_refused)}
    assert [event.url for event in result.skipped] == [SEED]


# --- T18: a redirect hop onto a retired host (spec 86e2ec5) -------------------------------

RETIRED = "api.example"
# The origin Discover opens a host by when no seed names it (https, crawl.allium Discover).
RETIRED_SITE = f"https://{RETIRED}"
RETIRED_ROBOTS = f"{RETIRED_SITE}/robots.txt"
RETIRED_PAGE = f"{RETIRED_SITE}/guide/moved.html"
RETIRED_HOP_ERROR = "redirect to a retired host"


def with_retired_host(responses: dict[str, SiteResponse]) -> FakeFetcher:
    """`responses`, and a second allowed host whose robots.txt retires it on a long Crawl-delay.

    Discover opens api.example before docs.example (allowed hosts in name order), so it is
    retired before any docs.example request.
    """
    cap = standard_policy().retry_after_cap.total_seconds()
    retiring = text_response(RETIRED_ROBOTS, f"User-agent: *\nCrawl-delay: {cap + 1}\n")
    return FakeFetcher({**responses, RETIRED_ROBOTS: retiring})


def two_hosts(out_dir: Path, fetcher: FakeFetcher) -> CrawlResult:
    """One standard run whose scope allows docs.example and api.example."""
    mirror = crawl_mirror(out_dir, allowed_hosts=frozenset({HOST, RETIRED}))
    return run_crawl(crawl_request(mirror), None, fetcher, FixedClock())


def test_a_page_redirect_onto_a_retired_host_is_never_requested(tmp_path: Path) -> None:
    """A page's hop onto a tripped host is not made: the page fails, "redirect to a retired host".

    AttemptTier guidance (crawl.allium 1636 to 1640 at 86e2ec5): the hop is not
    requested and its robots.txt is not read again; the error answer is retried as any
    error answer is, so the seed is tried http_attempts times, then fails with it.
    """
    fetcher = with_retired_host(redirect_site(seed=redirect_response(SEED, RETIRED_PAGE)))
    result = two_hosts(tmp_path, fetcher)
    retired = result.run.host(RETIRED)
    assert retired is not None
    assert retired.breaker_tripped
    assert RETIRED_PAGE not in fetcher.requests
    assert fetcher.requests.count(RETIRED_ROBOTS) == 1
    assert fetcher.requests.count(SEED) == CONFIG.http_attempts
    assert failed_errors(result) == {SEED: RETIRED_HOP_ERROR}


def test_a_robots_redirect_onto_a_retired_host_is_never_requested(tmp_path: Path) -> None:
    """A robots.txt hop onto a tripped host is not made; the robots.txt answer is an error.

    FetchRobots guidance (crawl.allium 834 to 838 at 86e2ec5): on any fetch_resource
    redirect, robots.txt's own included, a hop onto a tripped host is not requested;
    the fetch comes back as the error "redirect to a retired host", which disallows the
    origin as an unreachable robots.txt does, so the seed is never requested.
    """
    moved = f"{RETIRED_SITE}/elsewhere/robots.txt"
    fetcher = with_retired_host(
        {
            ROBOTS: redirect_response(ROBOTS, moved),
            SEED: html_response(SEED, PAGE_HTML.format(title="Start", prose="The start.")),
        }
    )
    result = two_hosts(tmp_path, fetcher)
    assert moved not in fetcher.requests
    assert fetcher.requests.count(RETIRED_ROBOTS) == 1
    assert SEED not in fetcher.requests
    assert (ROBOTS, DiscoveryProblem.robots_unreachable) in problems(result)


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


# --- Conditional sitemap reads (T14) ----------------------------------------------------


def test_fetch_resource_sends_its_validators_on_every_try(tmp_path: Path) -> None:
    """fetch_resource passes the validators it is given to every try, and none by default.

    crawl.allium FetchSitemap: fetch_resource(url, snapshot?.etag, snapshot?.last_modified,
    run, host). A 503 is retried; the retry carries the same validators. Called without
    validators, as robots.txt and llms.txt always are, every try sends none.
    """
    maps = f"{SITE}/maps/guide.xml"
    busy = text_response(maps, "", status=SERVICE_UNAVAILABLE)
    fetcher = ScriptedFetcher(polite(), {maps: [busy, busy]})
    run = start_run(request(new_mirror(tmp_path)), FixedClock())
    assert run is not None
    assert create_frontier(run, None) is not None
    host = open_host(run, HOST, SITE, fetcher)
    assert host is not None
    validators = Validators(etag='"map-1"', last_modified="Sat, 31 Oct 2026 12:00:00 GMT")
    pace.fetch_resource(maps, run, host, fetcher, validators)
    assert fetcher.requests[1:] == [maps, maps, maps]
    assert fetcher.validators[1:] == [validators] * len(["503", "503", "answered"])
    pace.fetch_resource(maps, run, host, fetcher)
    assert fetcher.requests[-1] == maps
    assert fetcher.validators[-1] is None


# --- Redirects (T15) ----------------------------------------------------------------
#
# crawl.allium RedirectsFollowedOnlyInScope (2264 at a0814ab), the AttemptTier guidance
# (1559 to 1567) and fetch_resource's (FetchRobots guidance, 811 to 820): a page's hops
# are followed within the scope, at most discovery_max_redirects, never revisiting, each
# under the destination host name's limiter and its origin's robots.txt; fetch_resource
# follows hops within the allowed hosts. tickets/T15-lifecycle.md Facts and Open points
# items 5 to 7 state the interims.

NEW_PAGE = f"{SITE}/guide/new.html"
LOOPING = f"{SITE}/guide/loop.html"
PRIVATE = f"{SITE}/guide/private/x.html"
OFF_HOST = "http://elsewhere.example/guide/new.html"
OFF_HOST_ROBOTS = "http://elsewhere.example/robots.txt"
PORTED_PAGE = f"{PORTED}/guide/x.html"
REAL_ROBOTS = f"{SITE}/robots-real.txt"
SIDE_ROBOTS = f"{SITE}/robots-side.txt"
MAPS = f"{SITE}/maps/guide.xml"
REAL_MAPS = f"{SITE}/maps/real.xml"
FLAKY_MAPS = f"{SITE}/maps/flaky.xml"
ORPHAN = f"{SITE}/guide/orphan.html"
LISTED = f"{SITE}/guide/listed.html"
MOVED_BODY = "Moved"
SEED_ETAG = '"seed-1"'


def lone_page(title: str = "Getting started", extra: str = "") -> str:
    """A page with a title, a heading and a paragraph of prose, and `extra` after it."""
    prose = f"{title} explains one setting of the example product.{extra}"
    return PAGE_HTML.format(title=title, prose=prose)


def moved(url: str, location: str) -> SiteResponse:
    """A 301 from `url` to `location` with a short body, so its bytes can be counted."""
    return dataclasses.replace(
        redirect_response(url, location), markup=MOVED_BODY, size=len(MOVED_BODY)
    )


def redirect_site(**answers: SiteResponse) -> dict[str, SiteResponse]:
    """robots.txt disallowing /guide/private/, and `answers` by URL (keyword: a name)."""
    responses = {ROBOTS: text_response(ROBOTS, NO_DELAY)}
    responses.update({response.source_url: response for response in answers.values()})
    return responses


def failed_errors(result: CrawlResult) -> dict[str, str]:
    """Each failed URL's error."""
    return {failed.url: failed.error for failed in result.failed}


def problems(result: CrawlResult) -> set[tuple[str, DiscoveryProblem]]:
    """Each discovery problem as (url, problem)."""
    return {(failed.url, failed.problem) for failed in result.discovery_failed}


def test_RedirectsFollowedOnlyInScope_an_in_scope_hop_is_followed(tmp_path: Path) -> None:
    """A page's in-scope redirect is followed: one fetch attempt, its hop's bytes counted.

    The seed answers 301 to /guide/new.html: the hop is requested after its turn at the
    host's limiter, the page is stored as NEW_PAGE with the seed its alias, the hop adds
    no fetch attempt, and the redirect's own bytes count toward bytes_fetched.
    """
    direct, _, _ = paced(
        tmp_path / "direct",
        FakeFetcher(redirect_site(seed=html_response(SEED, lone_page()))),
    )
    fetcher = FakeFetcher(
        redirect_site(
            seed=moved(SEED, "/guide/new.html"), new=html_response(NEW_PAGE, lone_page())
        )
    )
    result, stamping, _ = paced(tmp_path / "hopped", fetcher)
    assert to_host(stamping) == [ROBOTS, *PROBES, SEED, NEW_PAGE]
    (gap,) = gaps([stamp for stamp in stamping.stamps if stamp[0] in {SEED, NEW_PAGE}])
    assert gap >= spacing() - EPSILON
    assert result.run.fetch_attempts == direct.run.fetch_attempts == 1
    assert result.run.bytes_fetched - direct.run.bytes_fetched == len(MOVED_BODY)
    mirror = result.run.target
    assert [page.identity for page in mirror.pages] == [NEW_PAGE]
    assert [(alias.url, alias.target.identity) for alias in mirror.aliases] == [(SEED, NEW_PAGE)]
    entry = result.frontier.entry(SEED)
    assert entry is not None
    assert entry.status is FrontierStatus.done


@pytest.mark.parametrize(
    ("answers", "error", "never"),
    [
        pytest.param(
            {"seed": redirect_response(SEED, OFF_HOST)},
            "redirected out of scope",
            OFF_HOST,
            id="out-of-scope",
        ),
        pytest.param(
            {
                "seed": redirect_response(SEED, "/guide/loop.html"),
                "loop": redirect_response(LOOPING, "/guide/start.html"),
            },
            "redirect loop",
            OFF_HOST,
            id="loop",
        ),
        pytest.param(
            {"seed": redirect_response(SEED, "/guide/private/x.html")},
            "redirect disallowed by robots.txt",
            PRIVATE,
            id="robots-disallowed",
        ),
    ],
)
def test_RedirectsFollowedOnlyInScope_a_stopped_hop_is_never_requested(
    tmp_path: Path, answers: dict[str, SiteResponse], error: str, never: str
) -> None:
    """A hop out of scope, back to a URL already visited or robots disallows is not made.

    The row fails with the stop's text (DisposeFetch; Open points item 5 for robots),
    and nothing past the stop is requested. A loop or an out-of-scope stop is no error,
    so no try is retried and no URL of the chain is requested twice; whether the robots
    stop, an error, is retried is HttpRetry's to say, so it is not counted here.
    """
    fetcher = FakeFetcher(redirect_site(**answers))
    result, _, _ = paced(tmp_path, fetcher)
    assert failed_errors(result) == {SEED: error}
    assert never not in fetcher.requests
    assert OFF_HOST_ROBOTS not in fetcher.requests
    hops = [url for url in fetcher.requests if url.startswith(f"{SITE}/guide/")]
    if never != PRIVATE:
        assert len(hops) == len(set(hops))


def test_RedirectsFollowedOnlyInScope_a_chain_past_the_limit_stops_at_the_limit(
    tmp_path: Path,
) -> None:
    """The hop past discovery_max_redirects is never requested; the row fails.

    The seed is the first of a chain of discovery_max_redirects + 1 redirects: the seed
    and discovery_max_redirects hops are requested, each once, and the row fails with
    "too many redirects".
    """
    limit = CONFIG.discovery_max_redirects
    urls = [SEED, *(f"{SITE}/guide/hop-{n}.html" for n in range(1, limit + 1)), NEW_PAGE]
    answers = {
        f"hop{index}": redirect_response(url, target.removeprefix(SITE))
        for index, (url, target) in enumerate(itertools.pairwise(urls))
    }
    fetcher = FakeFetcher(redirect_site(**answers, new=html_response(NEW_PAGE, lone_page())))
    result, _, _ = paced(tmp_path, fetcher)
    assert failed_errors(result) == {SEED: "too many redirects"}
    assert NEW_PAGE not in fetcher.requests
    assert [url for url in fetcher.requests if url.startswith(f"{SITE}/guide/")] == urls[:-1]


def test_RedirectsFollowedOnlyInScope_validators_go_on_the_first_request_only(
    tmp_path: Path,
) -> None:
    """A known page's conditional fetch sends its validators to its own URL, not a hop.

    Open points item 6: the second run's request for the seed carries the stored ETag;
    the hop to NEW_PAGE carries none.
    """
    mirror = new_mirror(tmp_path)
    first = FakeFetcher(
        redirect_site(seed=dataclasses.replace(html_response(SEED, lone_page()), etag=SEED_ETAG))
    )
    run_crawl(request(mirror), None, first, FixedClock())
    again = FakeFetcher(
        redirect_site(
            seed=redirect_response(SEED, "/guide/new.html"),
            new=html_response(NEW_PAGE, lone_page()),
        )
    )
    second = dataclasses.replace(request(mirror), id=2, kind=RunKind.update)
    run_crawl(second, load_frontier(mirror), again, FixedClock())
    sent = list(zip(again.requests, again.validators, strict=True))
    assert (SEED, Validators(etag=SEED_ETAG, last_modified=None)) in sent
    assert (NEW_PAGE, None) in sent
    assert again.requests.count(NEW_PAGE) == 1


def test_RedirectsFollowedOnlyInScope_a_hop_to_a_new_origin_reads_its_robots_and_waits(
    tmp_path: Path,
) -> None:
    """A hop to another origin of the host reads that origin's robots.txt first.

    Open points item 5: PORTED's robots.txt is requested before the hop, never twice,
    and its Crawl-delay of 3 s, the longest of the host name's origins, spaces the hop
    from the request before it on the host name's limiter.
    """
    fetcher = FakeFetcher(
        redirect_site(
            seed=redirect_response(SEED, PORTED_PAGE),
            robots=text_response(PORTED_ROBOTS, "User-agent: *\nCrawl-delay: 3\n"),
            ported=html_response(PORTED_PAGE, lone_page("Port page")),
        )
    )
    result, stamping, _ = paced(tmp_path, fetcher)
    urls = [url for url, _ in stamping.stamps]
    assert urls.count(PORTED_ROBOTS) == 1
    assert urls.index(SEED) < urls.index(PORTED_ROBOTS) < urls.index(PORTED_PAGE)
    assert urls.count(PORTED_PAGE) == 1
    at = dict(stamping.stamps)
    assert at[PORTED_PAGE] - at[PORTED_ROBOTS] >= SECOND_ORIGIN_DELAY - EPSILON
    assert [page.identity for page in result.run.target.pages] == [PORTED_PAGE]


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param({"robots": redirect_response(ROBOTS, OFF_HOST_ROBOTS)}, id="off-host"),
        pytest.param(
            {
                "robots": SiteResponse(
                    status=301, source_url=ROBOTS, markup="", size=0, content_type="text/plain"
                )
            },
            id="no-location",
        ),
        pytest.param(
            {
                "robots": redirect_response(ROBOTS, "/robots-side.txt"),
                "side": redirect_response(SIDE_ROBOTS, "/robots.txt"),
            },
            id="loop",
        ),
        pytest.param(
            {
                "robots": redirect_response(ROBOTS, PORTED_ROBOTS),
                "ported": redirect_response(PORTED_ROBOTS, ROBOTS),
            },
            id="to-another-origin-and-back",
        ),
    ],
)
def test_RedirectsFollowedOnlyInScope_a_robots_txt_redirect_that_stops_disallows_its_origin(
    tmp_path: Path, answers: dict[str, SiteResponse]
) -> None:
    """A robots.txt whose redirect stops, or that lacks a Location, disallows its origin.

    fetch_resource returns an error answer, which DenyAllWhenRobotsUnreachable meets: a
    robots_unreachable discovery problem and no page requested. robots.txt is not
    governed by robots.txt, so no hop reads another robots.txt, and no URL is requested
    twice, nor any off the allowed hosts.
    """
    fetcher = FakeFetcher({**answers_by_url(answers), SEED: html_response(SEED, lone_page())})
    result = run_crawl(request(new_mirror(tmp_path)), None, fetcher, FixedClock())
    assert problems(result) == {(ROBOTS, DiscoveryProblem.robots_unreachable)}
    assert SEED not in fetcher.requests
    assert OFF_HOST_ROBOTS not in fetcher.requests
    assert fetcher.requests.count(ROBOTS) == 1
    assert fetcher.requests.count(PORTED_ROBOTS) <= 1


def answers_by_url(answers: dict[str, SiteResponse]) -> dict[str, SiteResponse]:
    """`answers` keyed by each answer's own URL."""
    return {response.source_url: response for response in answers.values()}


def test_RedirectsFollowedOnlyInScope_a_robots_txt_redirected_within_its_origin_is_followed(
    tmp_path: Path,
) -> None:
    """robots.txt redirected to /robots-real.txt is followed, with no second robots read.

    The real file's rules are adopted: the seed's link to /guide/private/ is never
    requested, and discovery reports no problem.
    """
    link = ' Read <a href="/guide/private/x.html">the private notes</a>.'
    fetcher = FakeFetcher(
        {
            ROBOTS: redirect_response(ROBOTS, "/robots-real.txt"),
            REAL_ROBOTS: text_response(REAL_ROBOTS, NO_DELAY),
            SEED: html_response(SEED, lone_page(extra=link)),
        }
    )
    result = run_crawl(request(new_mirror(tmp_path)), None, fetcher, FixedClock())
    assert fetcher.requests[:2] == [ROBOTS, REAL_ROBOTS]
    assert fetcher.requests.count(ROBOTS) == 1
    assert fetcher.requests.count(REAL_ROBOTS) == 1
    assert PRIVATE not in fetcher.requests
    assert SEED in fetcher.requests
    assert result.discovery_failed == ()
    assert not robots_allows(result.run, PRIVATE)


def opened_host(out_dir: Path, fetcher: FakeFetcher) -> tuple[Run, Host]:
    """A running run whose host docs.example is open, its robots.txt read."""
    run = start_run(request(new_mirror(out_dir)), FixedClock())
    assert run is not None
    assert create_frontier(run, None) is not None
    host = open_host(run, HOST, SITE, fetcher)
    assert host is not None
    return run, host


def test_fetch_resource_follows_a_redirect_within_the_allowed_hosts(tmp_path: Path) -> None:
    """fetch_resource follows a hop on an allowed host; the size covers every hop's bytes."""
    document = urlset((ORPHAN, None))
    fetcher = FakeFetcher(
        redirect_site(maps=moved(MAPS, "/maps/real.xml"), real=xml_response(REAL_MAPS, document))
    )
    run, host = opened_host(tmp_path, fetcher)
    response = pace.fetch_resource(MAPS, run, host, fetcher)
    assert response.ok
    assert response.source_url == REAL_MAPS
    assert response.markup == document
    assert response.size == len(MOVED_BODY) + len(document.encode())
    assert fetcher.requests[1:] == [MAPS, REAL_MAPS]


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param({"maps": redirect_response(MAPS, OFF_HOST)}, id="off-host"),
        pytest.param(
            {
                "maps": SiteResponse(
                    status=302, source_url=MAPS, markup="", size=0, content_type="text/xml"
                )
            },
            id="no-location",
        ),
        pytest.param(
            {
                "maps": redirect_response(MAPS, "/maps/real.xml"),
                "real": redirect_response(REAL_MAPS, "/maps/guide.xml"),
            },
            id="loop",
        ),
    ],
)
def test_fetch_resource_returns_an_error_for_a_redirect_it_does_not_follow(
    tmp_path: Path, answers: dict[str, SiteResponse]
) -> None:
    """Off the allowed hosts, a loop or a 3xx without a Location: an error answer.

    Nothing off the allowed hosts and no URL twice is requested.
    """
    fetcher = FakeFetcher(redirect_site(**answers))
    run, host = opened_host(tmp_path, fetcher)
    response = pace.fetch_resource(MAPS, run, host, fetcher)
    assert not response.ok
    assert response.error is not None
    assert OFF_HOST not in fetcher.requests
    assert fetcher.requests.count(MAPS) == 1
    assert fetcher.requests.count(REAL_MAPS) <= 1


def test_fetch_resource_stops_at_the_hop_limit(tmp_path: Path) -> None:
    """A chain of discovery_max_redirects + 1 redirects: the hop past the limit is not made."""
    limit = CONFIG.discovery_max_redirects
    urls = [MAPS, *(f"{SITE}/maps/hop-{n}.xml" for n in range(1, limit + 1)), REAL_MAPS]
    answers = {
        f"hop{index}": redirect_response(url, target.removeprefix(SITE))
        for index, (url, target) in enumerate(itertools.pairwise(urls))
    }
    fetcher = FakeFetcher(redirect_site(**answers, real=xml_response(REAL_MAPS, urlset())))
    run, host = opened_host(tmp_path, fetcher)
    response = pace.fetch_resource(MAPS, run, host, fetcher)
    assert not response.ok
    assert response.error is not None
    assert REAL_MAPS not in fetcher.requests
    assert fetcher.requests[1:] == urls[:-1]


def test_fetch_resource_restarts_the_chain_on_a_retry(tmp_path: Path) -> None:
    """A retryable answer at a hop ends the try; the retry starts again at the URL asked.

    The hop's 503 is retried from MAPS, whose redirect is followed again to the answer.
    """
    document = urlset((ORPHAN, None))
    fetcher = ScriptedFetcher(
        redirect_site(
            maps=redirect_response(MAPS, "/maps/flaky.xml"),
            flaky=xml_response(FLAKY_MAPS, document),
        ),
        {FLAKY_MAPS: [text_response(FLAKY_MAPS, "", status=SERVICE_UNAVAILABLE)]},
    )
    run, host = opened_host(tmp_path, fetcher)
    response = pace.fetch_resource(MAPS, run, host, fetcher)
    assert response.ok
    assert response.source_url == FLAKY_MAPS
    assert fetcher.requests[1:] == [MAPS, FLAKY_MAPS, MAPS, FLAKY_MAPS]


def test_discovery_follows_sitemap_and_llms_txt_redirects_within_the_allowed_hosts(
    tmp_path: Path,
) -> None:
    """FetchSitemap and ReadLlmsTxt read through redirects within the allowed hosts.

    /sitemap.xml answers 301 to /maps/real.xml, naming ORPHAN; /llms.txt answers 301 to
    /docs/llms.txt, linking LISTED: both pages are fetched and stored, and discovery
    reports no problem.
    """
    llms_real = f"{SITE}/docs/llms.txt"
    fetcher = FakeFetcher(
        redirect_site(
            seed=html_response(SEED, lone_page()),
            sitemap=redirect_response(f"{SITE}/sitemap.xml", "/maps/real.xml"),
            real=xml_response(REAL_MAPS, urlset((ORPHAN, None))),
            llms=redirect_response(f"{SITE}/llms.txt", "/docs/llms.txt"),
            docs=text_response(llms_real, f"# Example docs\n\n- [Listed]({LISTED})\n"),
            orphan=html_response(ORPHAN, lone_page("Orphan")),
            listed=html_response(LISTED, lone_page("Listed")),
        )
    )
    result = run_crawl(request(new_mirror(tmp_path)), None, fetcher, FixedClock())
    assert result.discovery_failed == ()
    assert {REAL_MAPS, llms_real, ORPHAN, LISTED} <= set(fetcher.requests)
    stored = sorted(page.identity for page in result.run.target.pages)
    assert stored == sorted([SEED, ORPHAN, LISTED])
