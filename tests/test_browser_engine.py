"""The browser engine seam (T19): the crawl's request callback and PlaywrightEngine.

Two halves. The request callback a render is answered through is the crawl's: through
`FakeEngine` (tests/fakes.py), a render under render_mode = always makes its navigation
through `pace.follow`, waits at the host's limiter, reads an allowed origin's robots.txt
before a subrequest to it, aborts a subrequest robots.txt disallows or that leaves the
allowed hosts (decided for now at e0f0c44, crawl.allium's open question on subresources
outside the allowed hosts its interim) without requesting it, counts every
response toward the render's size, never retries a subrequest and lets its Retry-After
pause the host but never retire it; a navigation with no response is an answer with
status 0 and the error set. `PlaywrightEngine` is driven over a stub
`playwright.sync_api` module put in `sys.modules`, shaped on playwright 1.64.1's sync
API (`sync_playwright().start()`, `chromium.launch`, `route`, `Route.fulfill`,
`Route.abort`, `Page.goto`, `Page.content`): it fulfils every request from the callback
and never lets the browser make one itself, waits for the `load` state capped at
CONFIG.render_max_wait (decided at e0f0c44), and leaves a redirected page at
the URL its content came from, so a relative subrequest resolves against it. Nothing
here launches a browser or sleeps.
"""

import inspect
import subprocess
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from urllib.parse import urljoin

import httpx
import pytest
from bs4 import BeautifulSoup

from fakes import (
    FakeEngine,
    FakeFetcher,
    FixedClock,
    StampingFetcher,
    SteppingTimer,
    gaps,
    html_response,
    text_response,
)
from rovo._crawl import browser, model
from rovo._crawl.browser import PlaywrightEngine, chromium_executable, missing_browser_piece
from rovo._crawl.fetch import Fetcher, HttpxFetcher
from rovo._crawl.model import FetchAttempt, RenderMode, Run, SiteResponse
from rovo._crawl.pace import Timer
from rovo._crawl.run import (
    begin_crawl,
    create_frontier,
    discover,
    drop_stale_observations,
    fetch_entry,
    prepare_run,
    select_batch,
    start_run,
)
from rovo._mirror.model import Tier
from test_crawl import HOST, PAGE, PORTED, PORTED_ROBOTS, ROBOTS, SEED, SITE, new_mirror, request

CRAWL = model.CONFIG
STYLE = f"{SITE}/guide/style.css"
TRACKER = f"{SITE}/private/tracker.js"
OFF_HOST_SCRIPT = "http://cdn.example/lib.js"
PORTED_STYLE = f"{PORTED}/guide/theme.css"
ROBOTS_TEXT = "User-agent: *\nDisallow: /private/\n"
CSS = "main { max-width: 40em; }"
RENDERED = PAGE.replace("Getting started", "Rendered guide")
SERVICE_UNAVAILABLE = 503


def css_response(url: str, text: str = CSS) -> SiteResponse:
    """A stylesheet answer from `url`."""
    return SiteResponse(
        status=200, source_url=url, markup=text, size=len(text.encode()), content_type="text/css"
    )


def site(**extra: SiteResponse) -> dict[str, SiteResponse]:
    """The fixture site: robots.txt disallowing /private/, the seed, and its stylesheets."""
    responses = {
        ROBOTS: text_response(ROBOTS, ROBOTS_TEXT),
        SEED: html_response(SEED, PAGE),
        STYLE: css_response(STYLE),
        TRACKER: text_response(TRACKER, "track();"),
        OFF_HOST_SCRIPT: text_response(OFF_HOST_SCRIPT, "lib();"),
        PORTED_STYLE: css_response(PORTED_STYLE),
    }
    responses.update(extra)
    return responses


def rendered(
    out_dir: Path, fetcher: Fetcher, engine: FakeEngine, timer: Timer
) -> tuple[Run, FetchAttempt]:
    """The seed's walk under render_mode = always: its one attempt, the render."""
    mirror = new_mirror(out_dir)
    run = start_run(request(mirror, render_mode=RenderMode.always), timer)
    assert run is not None
    frontier = create_frontier(run, None)
    assert prepare_run(run, frontier)
    assert discover(run, frontier, fetcher)
    assert drop_stale_observations(run, frontier)
    assert begin_crawl(run)
    batch = select_batch(run, frontier)
    assert batch is not None
    (entry,) = batch
    walk = fetch_entry(run, entry, fetcher, engine)
    assert walk is not None
    (attempt,) = walk.attempts
    assert attempt.tier is Tier.browser
    return run, attempt


# --- The crawl's request callback ----------------------------------------------------------


def test_the_navigation_is_made_through_the_crawl_with_no_validators(tmp_path: Path) -> None:
    """A render's navigation is the crawl's request: after robots.txt, with no validators."""
    fetcher = FakeFetcher(site())
    engine = FakeEngine({SEED: RENDERED})
    _, attempt = rendered(tmp_path, fetcher, engine, FixedClock())
    assert engine.renders == [SEED]
    assert fetcher.requests[0] == ROBOTS
    assert fetcher.requests[-1] == SEED
    assert fetcher.validators[-1] is None
    assert attempt.response.ok
    assert "Rendered guide" in attempt.response.markup
    assert attempt.response.source_url == SEED


def test_the_navigation_carries_the_rovo_user_agent(tmp_path: Path) -> None:
    """The navigation goes out on the run's http session, whose User-Agent names rovo."""
    agents: dict[str, str] = {}

    def answer(sent: httpx.Request) -> httpx.Response:
        agents[str(sent.url)] = sent.headers.get("user-agent", "")
        if sent.url.path == "/guide/start.html":
            return httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})
        return httpx.Response(404)

    engine = FakeEngine({SEED: RENDERED})
    with HttpxFetcher(transport=httpx.MockTransport(answer)) as fetcher:
        rendered(tmp_path, fetcher, engine, FixedClock())
    assert engine.renders == [SEED]
    assert agents[SEED].startswith("rovo/")


def test_a_subrequest_to_an_allowed_origin_is_made_after_its_robots_txt(tmp_path: Path) -> None:
    """A subrequest to another origin of an allowed host reads that origin's robots.txt first.

    Its answer is handed to the engine, and its bytes join the render's size.
    """
    fetcher = FakeFetcher(site())
    engine = FakeEngine({SEED: RENDERED}, subrequests={SEED: [STYLE, PORTED_STYLE]})
    run, attempt = rendered(tmp_path, fetcher, engine, FixedClock())
    render_requests = fetcher.requests[fetcher.requests.index(SEED) :]
    assert render_requests == [SEED, STYLE, PORTED_ROBOTS, PORTED_STYLE]
    assert engine.aborted == []
    answered = {url: got for url, navigation, got in engine.answers if not navigation}
    assert answered[STYLE] == fetcher.responses[STYLE]
    expected = sum(fetcher.responses[url].size for url in (SEED, STYLE, PORTED_STYLE))
    assert attempt.response.size == expected
    assert run.bytes_fetched >= expected


@pytest.mark.parametrize(
    "url",
    [
        pytest.param(TRACKER, id="disallowed"),
        pytest.param(OFF_HOST_SCRIPT, id="off-host"),
    ],
)
def test_a_disallowed_or_off_host_subrequest_is_aborted_unrequested(
    tmp_path: Path, url: str
) -> None:
    """A subrequest robots.txt disallows, or to a host outside the allowed hosts, is aborted.

    It is never requested (no robots.txt is read for the off-host origin either); the
    render goes on and stands.
    """
    fetcher = FakeFetcher(site())
    engine = FakeEngine({SEED: RENDERED}, subrequests={SEED: [url, STYLE]})
    _, attempt = rendered(tmp_path, fetcher, engine, FixedClock())
    assert engine.aborted == [url]
    assert url not in fetcher.requests
    assert "http://cdn.example/robots.txt" not in fetcher.requests
    assert STYLE in fetcher.requests
    assert attempt.response.ok


def test_every_request_a_render_causes_waits_at_the_hosts_limiter(tmp_path: Path) -> None:
    """The navigation and each subrequest to the host start at least 1 / rate apart."""
    timer = SteppingTimer()
    fetcher = StampingFetcher(FakeFetcher(site()), timer)
    engine = FakeEngine({SEED: RENDERED}, subrequests={SEED: [STYLE]})
    run, _ = rendered(tmp_path, fetcher, engine, timer)
    stamps = [stamp for stamp in fetcher.stamps if stamp[0] in {ROBOTS, SEED, STYLE}]
    assert [url for url, _ in stamps] == [ROBOTS, SEED, STYLE]
    rate = run.policy.rate_per_host
    assert rate is not None
    spacing = timedelta(seconds=1 / rate)
    assert all(gap >= spacing for gap in gaps(stamps))


def test_a_subrequests_retry_after_pauses_the_host_and_is_never_retried(tmp_path: Path) -> None:
    """AttemptTier guidance (e0f0c44): a subrequest's Retry-After pauses, never retires.

    The subrequest is never retried; its Retry-After pauses its host, at most
    retry_after_cap, and never retires it; the render stands.
    """
    past_cap = CRAWL.retry_after_cap + timedelta(seconds=1)
    busy = SiteResponse(
        status=SERVICE_UNAVAILABLE,
        source_url=STYLE,
        markup="",
        size=0,
        retry_after=past_cap,
    )
    fetcher = FakeFetcher(site(**{STYLE: busy}))
    clock = FixedClock()
    engine = FakeEngine({SEED: RENDERED}, subrequests={SEED: [STYLE]})
    run, attempt = rendered(tmp_path, fetcher, engine, clock)
    assert fetcher.requests.count(STYLE) == 1
    host = run.host(HOST)
    assert host is not None
    assert not host.breaker_tripped
    assert host.paused_until is not None
    assert clock.instant < host.paused_until <= clock.instant + run.policy.retry_after_cap
    assert attempt.response.ok


def test_a_render_with_no_response_is_status_0_with_the_error_set(tmp_path: Path) -> None:
    """A navigation that never reaches its load state is an answer with status 0 and an error."""
    fetcher = FakeFetcher(site())
    engine = FakeEngine({SEED: None})
    _, attempt = rendered(tmp_path, fetcher, engine, FixedClock())
    assert attempt.response.status == 0
    assert attempt.response.error
    assert attempt.failed_outright
    assert attempt.render_reason is None


def test_the_crawl_imports_no_playwright() -> None:
    """Only opening a PlaywrightEngine imports playwright: the crawl and its seam do not."""
    probe = (
        "import sys, rovo, rovo._crawl.run, rovo._crawl.browser, rovo._commands, rovo.cli; "
        "print(sorted(m for m in sys.modules if m.split('.')[0] == 'playwright'))"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "[]"


# --- PlaywrightEngine over a stub playwright.sync_api ----------------------------------------


class StubTimeoutError(Exception):
    """playwright.sync_api.TimeoutError."""


class StubError(Exception):
    """playwright.sync_api.Error."""


@dataclass
class StubRequest:
    """playwright Request: its URL and whether it is a navigation."""

    url: str
    navigation: bool
    resource_type: str = "document"
    method: str = "GET"

    def is_navigation_request(self) -> bool:
        """Whether the request navigates the page."""
        return self.navigation


@dataclass
class StubResponse:
    """playwright Response: the navigation's status, URL and headers."""

    status: int
    url: str
    headers: dict[str, str] = field(default_factory=dict)

    def all_headers(self) -> dict[str, str]:
        """Every header, lower-cased names."""
        return dict(self.headers)


@dataclass
class StubRoute:
    """playwright Route: fulfilled, aborted or (never) continued."""

    request: StubRequest
    fulfilled: dict[str, object] | None = None
    aborted: bool = False

    def fulfill(  # noqa: PLR0913  playwright's own keyword parameters.
        self,
        *,
        body: str | bytes | None = None,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
        json: object = None,
        path: str | Path | None = None,
        response: object = None,
        status: int | None = None,
    ) -> None:
        """Fulfil the request with the given answer."""
        del json, path, response
        text = body.decode() if isinstance(body, bytes) else body or ""
        self.fulfilled = {
            "status": 200 if status is None else status,
            "headers": {name.lower(): value for name, value in (headers or {}).items()},
            "content_type": content_type,
            "body": text,
        }

    def abort(self, error_code: str | None = None) -> None:
        """Abort the request: it is never made."""
        del error_code
        self.aborted = True

    def continue_(self, **_: object) -> None:
        """Let the browser make the request itself: a render must never do this."""
        pytest.fail(f"the browser was let make a request itself: {self.request.url}")

    def fallback(self, **_: object) -> None:
        """Hand the request to the browser's own handling: never, as continue_."""
        pytest.fail(f"the browser was let make a request itself: {self.request.url}")

    def fetch(self, **_: object) -> None:
        """Fetch the request outside the crawl: never."""
        pytest.fail(f"a request was made outside the crawl: {self.request.url}")


@dataclass
class Scenario:
    """What the stub browser does: subrequests, load time, the DOM a script writes."""

    # Each document URL's subrequests, as written in the page (relative or absolute).
    subrequests: dict[str, list[str]] = field(default_factory=dict)
    # How long the page takes to reach its load state.
    load_takes: timedelta = timedelta(seconds=1)
    # The DOM the page's script leaves, by document URL; else the fulfilled body.
    dom: dict[str, str] = field(default_factory=dict)
    # When False, goto returns None: the navigation got no response.
    respond: bool = True
    # The path playwright reports for its Chromium; starting playwright fails when set.
    executable: str = "/stub/ms-playwright/chromium/chrome"
    start_fails: bool = False
    # What happened: each routed request and its route, launches, closes.
    routes: list[StubRoute] = field(default_factory=list)
    launches: list[dict[str, object]] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)


# The statuses a browser follows as a redirect when the answer carries a Location.
REDIRECTS = frozenset({301, 302, 303, 307, 308})
# playwright's own default timeout for a navigation, when none is set.
PLAYWRIGHT_DEFAULT_TIMEOUT = timedelta(seconds=30)


def as_duration(timeout: float | timedelta | None) -> timedelta | None:
    """A playwright timeout (milliseconds, or a timedelta) as a timedelta."""
    if timeout is None or isinstance(timeout, timedelta):
        return timeout
    return timedelta(milliseconds=timeout)


class StubPage:
    """playwright Page: routes every request through its handler, as a browser would."""

    def __init__(self, scenario: Scenario, context: "StubContext") -> None:
        """A blank page of `context`."""
        self.scenario = scenario
        self.context = context
        self.handler: Callable[..., object] | None = None
        self.default_timeout: timedelta | None = None
        self.url = "about:blank"
        self.body = ""
        self.loaded = False
        self.load_takes = scenario.load_takes

    def route(self, url: object, handler: Callable[..., object], **_: object) -> None:
        """Route every request (the stub ignores the pattern) through `handler`."""
        del url
        self.handler = handler

    def set_default_timeout(self, timeout: float) -> None:
        """Every wait's default cap, in milliseconds."""
        self.default_timeout = as_duration(timeout)

    def set_default_navigation_timeout(self, timeout: float) -> None:
        """A navigation's default cap, in milliseconds."""
        self.default_timeout = as_duration(timeout)

    def _routed(self, url: str, *, navigation: bool) -> StubRoute:
        handler = self.handler or self.context.handler
        assert handler is not None, "a request was made with no route handler"
        stub_request = StubRequest(
            url=url, navigation=navigation, resource_type="document" if navigation else "other"
        )
        route = StubRoute(request=stub_request)
        self.scenario.routes.append(route)
        if len(inspect.signature(handler).parameters) >= len(["route", "request"]):
            handler(route, stub_request)
        else:
            handler(route)
        assert route.fulfilled is not None or route.aborted, f"unanswered request: {url}"
        return route

    def _cap(self, timeout: float | timedelta | None) -> timedelta:
        return (
            as_duration(timeout)
            or self.default_timeout
            or self.context.default_timeout
            or PLAYWRIGHT_DEFAULT_TIMEOUT
        )

    def _navigate(self, url: str) -> tuple[int, dict[str, str], str]:
        """One navigation request: the status, headers and body it was fulfilled with."""
        route = self._routed(url, navigation=True)
        if route.fulfilled is None:
            msg = f"net::ERR_FAILED at {url}"
            raise StubError(msg)
        status, headers, body = (
            route.fulfilled["status"],
            route.fulfilled["headers"],
            route.fulfilled["body"],
        )
        assert isinstance(status, int)
        assert isinstance(headers, dict)
        assert isinstance(body, str)
        return status, {str(name): str(value) for name, value in headers.items()}, body

    def goto(
        self,
        url: str,
        *,
        referer: str | None = None,
        timeout: float | timedelta | None = None,
        wait_until: str | None = None,
    ) -> StubResponse | None:
        """Navigate: follow fulfilled redirects, load the subrequests, wait for the state."""
        del referer
        status, headers, body = self._navigate(url)
        while status in REDIRECTS and "location" in headers:
            url = urljoin(url, headers["location"])
            status, headers, body = self._navigate(url)
        self.url = url
        self.body = body
        base_tag = BeautifulSoup(body, "lxml").find("base", href=True)
        base = urljoin(url, str(base_tag["href"])) if base_tag is not None else url
        for written in self.scenario.subrequests.get(url, []):
            self._routed(urljoin(base, written), navigation=False)
        if wait_until in {None, "load", "networkidle"}:
            self.wait_for_load_state("load", timeout=timeout)
        if not self.scenario.respond:
            return None
        return StubResponse(status=status, url=url, headers=headers)

    def wait_for_load_state(
        self, state: str | None = None, *, timeout: float | timedelta | None = None
    ) -> None:
        """Reach the state within the cap, or raise TimeoutError."""
        if state not in {None, "load"}:
            return
        if self.load_takes > self._cap(timeout):
            msg = f"Timeout exceeded waiting for load at {self.url}"
            raise StubTimeoutError(msg)
        self.loaded = True

    def content(self) -> str:
        """The DOM: what the page's script wrote, else the body it was given."""
        return self.scenario.dom.get(self.url, self.body)

    def close(self) -> None:
        """Close the page."""
        self.scenario.closed.append("page")


class StubContext:
    """playwright BrowserContext."""

    def __init__(self, scenario: Scenario) -> None:
        """A fresh context."""
        self.scenario = scenario
        self.handler: Callable[..., object] | None = None
        self.default_timeout: timedelta | None = None

    def route(self, url: object, handler: Callable[..., object], **_: object) -> None:
        """Route every request of every page through `handler`."""
        del url
        self.handler = handler

    def set_default_timeout(self, timeout: float) -> None:
        """Every page's default cap, in milliseconds."""
        self.default_timeout = as_duration(timeout)

    def set_default_navigation_timeout(self, timeout: float) -> None:
        """Every page's navigation cap, in milliseconds."""
        self.default_timeout = as_duration(timeout)

    def new_page(self) -> StubPage:
        """A new page in this context."""
        return StubPage(self.scenario, self)

    def close(self) -> None:
        """Close the context."""
        self.scenario.closed.append("context")


class StubBrowser:
    """playwright Browser."""

    def __init__(self, scenario: Scenario) -> None:
        """A launched browser."""
        self.scenario = scenario

    def new_context(self, **_: object) -> StubContext:
        """A new context."""
        return StubContext(self.scenario)

    def new_page(self, **_: object) -> StubPage:
        """A new page in a new context."""
        return StubContext(self.scenario).new_page()

    def close(self) -> None:
        """Close the browser."""
        self.scenario.closed.append("browser")


class StubBrowserType:
    """playwright BrowserType (chromium)."""

    def __init__(self, scenario: Scenario) -> None:
        """Chromium."""
        self.scenario = scenario

    @property
    def executable_path(self) -> str:
        """Where playwright expects its Chromium binary, whether or not it is there."""
        return self.scenario.executable

    def launch(self, **options: object) -> StubBrowser:
        """Launch the browser, recording its options."""
        self.scenario.launches.append(options)
        return StubBrowser(self.scenario)


class StubPlaywright:
    """The started playwright object."""

    def __init__(self, scenario: Scenario) -> None:
        """Its chromium browser type."""
        self.scenario = scenario
        self.chromium = StubBrowserType(scenario)

    def stop(self) -> None:
        """Stop playwright."""
        self.scenario.closed.append("playwright")


class StubManager:
    """What sync_playwright() returns: started with start(), or used as a context manager."""

    def __init__(self, scenario: Scenario) -> None:
        """The manager of one playwright."""
        self.scenario = scenario
        self.playwright = StubPlaywright(scenario)

    def start(self) -> StubPlaywright:
        """Start playwright; fails as playwright does when its driver cannot start."""
        if self.scenario.start_fails:
            msg = "the driver did not start"
            raise StubError(msg)
        return self.playwright

    def __enter__(self) -> StubPlaywright:
        """Start playwright."""
        return self.playwright

    def __exit__(self, *_: object) -> None:
        """Stop playwright."""
        self.playwright.stop()


@pytest.fixture
def scenario(monkeypatch: pytest.MonkeyPatch) -> Scenario:
    """A stub playwright.sync_api in sys.modules, playing out the yielded Scenario."""
    played = Scenario()
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: StubManager(played)  # type: ignore[attr-defined]  # A stub module.
    sync_api.TimeoutError = StubTimeoutError  # type: ignore[attr-defined]  # A stub module.
    sync_api.Error = StubError  # type: ignore[attr-defined]  # A stub module.
    package = types.ModuleType("playwright")
    package.sync_api = sync_api  # type: ignore[attr-defined]  # A stub module.
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    return played


class Answers:
    """A request callback over a URL map: records each call; None (abort) for any other URL."""

    def __init__(self, responses: dict[str, SiteResponse]) -> None:
        """Answer each URL of `responses`."""
        self.responses = responses
        self.calls: list[tuple[str, bool]] = []

    def __call__(self, url: str, *, navigation: bool) -> SiteResponse | None:
        """Record the call; the mapped answer, else None."""
        self.calls.append((url, navigation))
        return self.responses.get(url)


def fulfilled(scenario: Scenario, url: str) -> dict[str, object]:
    """The answer the request for `url` was fulfilled with."""
    routes = [route for route in scenario.routes if route.request.url == url]
    assert routes, url
    answer = routes[-1].fulfilled
    assert answer is not None, url
    return answer


def test_playwright_engine_launches_headless_chromium_and_fulfils_every_request(
    scenario: Scenario,
) -> None:
    """Every request the page makes is answered from the callback, never by the browser.

    Chromium is launched headless once; the navigation is fulfilled with the answer's
    status and body; the rendered DOM is what render returns; closing closes the browser
    and stops playwright.
    """
    scenario.dom[SEED] = RENDERED
    answers = Answers({SEED: html_response(SEED, PAGE)})
    engine = PlaywrightEngine()
    try:
        dom = engine.render(SEED, answers)
    finally:
        engine.close()
    assert dom == RENDERED
    assert answers.calls == [(SEED, True)]
    answer = fulfilled(scenario, SEED)
    assert answer["status"] == html_response(SEED, PAGE).status
    assert answer["body"] == PAGE
    (launch,) = scenario.launches
    assert launch.get("headless", True) is True
    assert {"browser", "playwright"} <= set(scenario.closed)


def test_playwright_engine_aborts_a_subrequest_the_callback_refuses(scenario: Scenario) -> None:
    """A subrequest the callback answers None is aborted; one it answers is fulfilled."""
    scenario.subrequests[SEED] = ["style.css", "/private/tracker.js"]
    answers = Answers({SEED: html_response(SEED, PAGE), STYLE: css_response(STYLE)})
    engine = PlaywrightEngine()
    try:
        assert engine.render(SEED, answers) is not None
    finally:
        engine.close()
    assert answers.calls == [(SEED, True), (STYLE, False), (TRACKER, False)]
    assert fulfilled(scenario, STYLE)["body"] == CSS
    (tracker,) = [route for route in scenario.routes if route.request.url == TRACKER]
    assert tracker.aborted


def test_playwright_engine_resolves_a_relative_subrequest_after_a_redirect(
    scenario: Scenario,
) -> None:
    """A redirected navigation leaves the page at the URL its content came from.

    The crawl answers the navigation for old.html with the content of new.html (its
    source_url, one redirect hop): the page's relative subrequest is asked for under
    new.html's directory, not old.html's.
    """
    old = f"{SITE}/guide/old/page.html"
    new = f"{SITE}/guide/new/page.html"
    moved = html_response(new, PAGE)
    moved = SiteResponse(
        status=moved.status,
        source_url=new,
        markup=moved.markup,
        size=moved.size,
        content_type=moved.content_type,
        redirect_hops=(old,),
    )
    scenario.subrequests[new] = ["style.css"]
    scenario.subrequests[old] = ["style.css"]
    new_style = f"{SITE}/guide/new/style.css"
    answers = Answers({old: moved, new: moved, new_style: css_response(new_style)})
    engine = PlaywrightEngine()
    try:
        assert engine.render(old, answers) is not None
    finally:
        engine.close()
    subrequests = [url for url, navigation in answers.calls if not navigation]
    assert subrequests == [new_style]


@pytest.mark.parametrize(
    ("load_takes", "renders"),
    [
        pytest.param(CRAWL.render_max_wait - timedelta(seconds=1), True, id="within-the-cap"),
        pytest.param(CRAWL.render_max_wait + timedelta(seconds=1), False, id="past-the-cap"),
    ],
)
def test_playwright_engine_waits_for_load_capped_at_render_max_wait(
    scenario: Scenario, load_takes: timedelta, *, renders: bool
) -> None:
    """AttemptTier guidance (e0f0c44): the page's load state, capped at render_max_wait.

    A page that reaches load within CONFIG.render_max_wait is rendered; one that takes
    longer (still under playwright's own 30 s default) is not: render returns None.
    """
    assert CRAWL.render_max_wait + timedelta(seconds=1) < PLAYWRIGHT_DEFAULT_TIMEOUT
    scenario.load_takes = load_takes
    scenario.dom[SEED] = RENDERED
    engine = PlaywrightEngine()
    try:
        dom = engine.render(SEED, Answers({SEED: html_response(SEED, PAGE)}))
    finally:
        engine.close()
    assert (dom == RENDERED) is renders
    assert (dom is None) is not renders


def test_playwright_engine_without_a_navigation_response_renders_nothing(
    scenario: Scenario,
) -> None:
    """A navigation that gets no response is no render: render returns None."""
    scenario.respond = False
    engine = PlaywrightEngine()
    try:
        assert engine.render(SEED, Answers({SEED: html_response(SEED, PAGE)})) is None
    finally:
        engine.close()


def test_playwright_engine_renders_many_pages_in_one_browser(scenario: Scenario) -> None:
    """One engine is one launched browser for every render of its run."""
    other = f"{SITE}/guide/other.html"
    answers = Answers({SEED: html_response(SEED, PAGE), other: html_response(other, PAGE)})
    engine = PlaywrightEngine()
    try:
        assert engine.render(SEED, answers) is not None
        assert engine.render(other, answers) is not None
    finally:
        engine.close()
    assert len(scenario.launches) == 1
    assert [url for url, navigation in answers.calls if navigation] == [SEED, other]


# --- The engine probe: tier_installed(browser) (rovo.allium RefuseMissingEngine, e0f0c44) ---


def test_chromium_executable_asks_playwright_without_launching(scenario: Scenario) -> None:
    """chromium_executable starts playwright, reads chromium.executable_path, stops it.

    No browser is launched; the path is returned as playwright reports it.
    """
    assert chromium_executable() == Path(scenario.executable)
    assert scenario.launches == []
    assert scenario.closed == ["playwright"]


def test_chromium_executable_is_none_when_playwright_cannot_say(scenario: Scenario) -> None:
    """A playwright that fails to start (its Error) gives no path, and nothing launches."""
    scenario.start_fails = True
    assert chromium_executable() is None
    assert scenario.launches == []


@pytest.mark.parametrize(
    ("package", "binary", "piece"),
    [
        pytest.param(False, None, "the playwright package", id="no-package"),
        pytest.param(True, None, "the Chromium browser", id="no-binary-path"),
        pytest.param(True, "absent", "the Chromium browser", id="binary-not-on-disk"),
        pytest.param(True, "chrome", None, id="installed"),
    ],
)
def test_missing_browser_piece_names_the_package_or_the_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    package: bool,  # noqa: FBT001  A parametrized column.
    binary: str | None,
    piece: str | None,
) -> None:
    """tier_installed(browser) holds when the playwright package and its Chromium are both there.

    missing_browser_piece is None then; else it names the package, which is asked first
    (the binary is never asked about without it), or the Chromium browser, when
    playwright reports no path or one that is not on disk.
    """
    (tmp_path / "chrome").write_text("", encoding="utf-8")
    asked: list[str] = []

    def executable() -> Path | None:
        asked.append("binary")
        return None if binary is None else tmp_path / binary

    monkeypatch.setattr(browser, "playwright_importable", lambda: package)
    monkeypatch.setattr(browser, "chromium_executable", executable)
    assert missing_browser_piece() == piece
    assert asked == (["binary"] if package else [])
