"""Test doubles for the seams: Fetchers that answer from a map or a script, and timers.

`FakeFetcher` records every request in order, so a test can prove what was fetched and
when; a URL it has no answer for comes back 404, as the fixture server would answer.
`ScriptedFetcher` answers a URL from its script first, one answer per request, then from
the map: an answer that must hold every time goes in the map, a sequence in the script.
`StampingFetcher` wraps any fetcher and stamps each request with its timer's time.
`RaisingFetcher` wraps any fetcher and raises a given exception, an operator interrupt
or a crash, on the request for a given URL.

`FakeEngine` satisfies the crawl's BrowserEngine seam (T19) without a browser: it
"renders" a page by answering its navigation through the crawl's request callback, so
the request is made, paced and logged by the crawl exactly as a real render's would be,
then asks the callback for each subrequest the page names, and returns the DOM its map
holds for the URL (else the navigation's own markup). A URL mapped to None is a render
that never reaches its load state. `unopened_engine` is an engine factory for a sync
that must open no engine. `probe_engine` makes rovo._crawl.browser's engine probe
(tier_installed(browser): the playwright package and its Chromium binary, rovo.allium
RefuseMissingEngine at e0f0c44) see a given install, so no test needs a real Chromium.

`FixedClock` and `SteppingTimer` both satisfy the crawl's Timer seam (`now()` and
`sleep(seconds)`) and both record every sleep they are asked for; neither sleeps for
real. `FixedClock` never advances, so a test's timestamps stay where they were;
`SteppingTimer` advances by exactly what each sleep asks, so gaps between stamps are the
waits the limiter chose.
"""

import itertools
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import pytest

from rovo._crawl import browser
from rovo._crawl.fetch import Fetcher, Validators
from rovo._crawl.model import SiteResponse

# The instant every FixedClock reads unless told otherwise: timezone-aware UTC.
START = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)

SITES = Path(__file__).resolve().parent / "fixtures" / "sites"

HTML = "text/html; charset=utf-8"
TEXT = "text/plain; charset=utf-8"
XML = "application/xml"
NOT_FOUND = 404
MOVED_PERMANENTLY = 301


def html_response(url: str, markup: str, *, status: int = 200) -> SiteResponse:
    """An HTML answer from `url`, its size the markup's UTF-8 length."""
    return SiteResponse(
        status=status,
        source_url=url,
        markup=markup,
        size=len(markup.encode()),
        content_type=HTML,
    )


def text_response(url: str, text: str, *, status: int = 200) -> SiteResponse:
    """A plain-text answer from `url`, such as a robots.txt."""
    return SiteResponse(
        status=status, source_url=url, markup=text, size=len(text.encode()), content_type=TEXT
    )


def xml_response(url: str, text: str, *, status: int = 200) -> SiteResponse:
    """An XML answer from `url`, such as a sitemap."""
    return SiteResponse(
        status=status, source_url=url, markup=text, size=len(text.encode()), content_type=XML
    )


def not_found(url: str) -> SiteResponse:
    """A 404 with an empty body."""
    return SiteResponse(status=NOT_FOUND, source_url=url, markup="", size=0, content_type=HTML)


def redirect_response(url: str, location: str, *, status: int = MOVED_PERMANENTLY) -> SiteResponse:
    """A 3xx from `url` whose raw Location header is `location`, with an empty body."""
    return SiteResponse(
        status=status, source_url=url, markup="", size=0, content_type=HTML, location=location
    )


def fixture_site(name: str, base: str) -> dict[str, SiteResponse]:
    """Every file of tests/fixtures/sites/<name>/ as an answer from `base` (ending in /).

    An `.html` file is an HTML answer, an `.xml` file an XML answer; any other file, such
    as robots.txt, a plain-text answer. A FakeFetcher over the map serves the site as the
    end-to-end server would.
    """
    root = SITES / name
    responses: dict[str, SiteResponse] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        url = base + path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".html":
            responses[url] = html_response(url, text)
        elif path.suffix == ".xml":
            responses[url] = xml_response(url, text)
        else:
            responses[url] = text_response(url, text)
    return responses


class FakeFetcher:
    """A URL to SiteResponse map that records every request, with its validators."""

    def __init__(self, responses: Mapping[str, SiteResponse]) -> None:
        """Answer each URL in `responses`; anything else is a 404."""
        self.responses = dict(responses)
        self.requests: list[str] = []
        self.validators: list[Validators | None] = []

    def fetch(self, url: str, *, validators: Validators | None = None) -> SiteResponse:
        """Record the request and return the mapped answer, else a 404."""
        self.requests.append(url)
        self.validators.append(validators)
        return self.responses.get(url, not_found(url))


class ScriptedFetcher(FakeFetcher):
    """A FakeFetcher that answers each scripted URL from its script before its map.

    Each request to a URL takes the next unused answer of its script; once the script is
    used up, the URL is answered from `responses`, else 404, as FakeFetcher answers.
    """

    def __init__(
        self,
        responses: Mapping[str, SiteResponse],
        scripts: Mapping[str, Sequence[SiteResponse]] | None = None,
    ) -> None:
        """Answer from `scripts` first, one answer per request, then from `responses`."""
        super().__init__(responses)
        self.scripts = {url: list(answers) for url, answers in (scripts or {}).items()}

    def fetch(self, url: str, *, validators: Validators | None = None) -> SiteResponse:
        """Record the request; the next scripted answer, else the mapped one, else a 404."""
        script = self.scripts.get(url)
        if not script:
            return super().fetch(url, validators=validators)
        self.requests.append(url)
        self.validators.append(validators)
        return script.pop(0)

    def count(self, url: str) -> int:
        """How many times `url` was requested."""
        return self.requests.count(url)


class Stamping(Protocol):
    """What StampingFetcher reads the time from."""

    def now(self) -> datetime:
        """The current time, UTC."""
        ...


class StampingFetcher:
    """Wraps a Fetcher and records `(url, timer.now())` before each request it passes on."""

    def __init__(self, fetcher: Fetcher, timer: Stamping) -> None:
        """Stamp each request to `fetcher` with `timer`'s time."""
        self.fetcher = fetcher
        self.timer = timer
        self.stamps: list[tuple[str, datetime]] = []

    def fetch(self, url: str, *, validators: Validators | None = None) -> SiteResponse:
        """Stamp the request, then pass it on."""
        self.stamps.append((url, self.timer.now()))
        return self.fetcher.fetch(url, validators=validators)


class RaisingFetcher:
    """Wraps a Fetcher and raises `error` instead of passing on the request for `url`.

    Every other request is passed on. `requests` records every request it saw, in
    order, the one that raised included, and `raised` the ones that raised, so a test
    can tell the interrupt or crash happened where it meant it to and that no request
    followed it (T16).
    """

    def __init__(self, fetcher: Fetcher, url: str, error: BaseException) -> None:
        """Pass requests to `fetcher`; raise `error` on the request for `url`."""
        self.fetcher = fetcher
        self.url = url
        self.error = error
        self.requests: list[str] = []
        self.raised: list[str] = []

    def fetch(self, url: str, *, validators: Validators | None = None) -> SiteResponse:
        """Record the request; raise the error for the URL, else pass the request on."""
        self.requests.append(url)
        if url == self.url:
            self.raised.append(url)
            raise self.error
        return self.fetcher.fetch(url, validators=validators)


class Answering(Protocol):
    """The crawl's request callback a render is answered through (rovo._crawl.browser)."""

    def __call__(self, url: str, *, navigation: bool) -> SiteResponse | None:
        """The answer to fulfil the request with, or None to abort it unrequested."""
        ...


class FakeEngine:
    """A BrowserEngine over a URL to rendered-DOM map; records every render and answer.

    `render(url, answer)` asks `answer(url, navigation=True)` for the navigation and,
    unless that is None, `answer(sub, navigation=False)` for each of `subrequests[url]`
    in order; it returns `pages[url]` when the URL is mapped (None: the load state was
    never reached), else the navigation's markup, as a browser renders a page whose
    script changes nothing.
    """

    def __init__(
        self,
        pages: Mapping[str, str | None] | None = None,
        *,
        subrequests: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        """Render each URL of `pages` as its DOM, asking for its `subrequests` first."""
        self.pages = dict(pages or {})
        self.subrequests = {url: list(urls) for url, urls in (subrequests or {}).items()}
        self.renders: list[str] = []
        self.answers: list[tuple[str, bool, SiteResponse | None]] = []
        self.closed = False

    def render(self, url: str, answer: Answering) -> str | None:
        """Navigate through `answer`, then each subrequest; the mapped DOM, else the markup."""
        self.renders.append(url)
        navigation = answer(url, navigation=True)
        self.answers.append((url, True, navigation))
        if navigation is None:
            return None
        for sub in self.subrequests.get(url, ()):
            self.answers.append((sub, False, answer(sub, navigation=False)))
        if url in self.pages:
            return self.pages[url]
        return navigation.markup

    def close(self) -> None:
        """Record that the engine was closed."""
        self.closed = True

    @property
    def aborted(self) -> list[str]:
        """The subrequests the crawl aborted (answered None), in order."""
        return [url for url, navigation, got in self.answers if not navigation and got is None]


def unopened_engine() -> FakeEngine:
    """An engine factory for a sync that must not open an engine: calling it fails."""
    msg = "no engine is opened by this sync"
    raise AssertionError(msg)


def probe_engine(monkeypatch: pytest.MonkeyPatch, *, package: bool, binary: Path | None) -> None:
    """Make the engine probe see the given install, with no real Chromium consulted.

    `package` is whether the playwright package is found; `binary` is the path
    playwright reports for its Chromium (None: it cannot say), which exists or not as
    the test arranged it. With no package, asking for the binary fails the test: the
    probe never asks for the browser of a package it does not have.
    """

    def executable() -> Path | None:
        assert package, "the Chromium binary is probed only when playwright is installed"
        return binary

    monkeypatch.setattr(browser, "playwright_importable", lambda: package)
    monkeypatch.setattr(browser, "chromium_executable", executable)


class FixedClock:
    """A clock that reads the same instant every time; a sleep is recorded, never taken."""

    def __init__(self, now: datetime = START) -> None:
        """Stand still at `now`."""
        self.instant = now
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        """The fixed instant."""
        return self.instant

    def sleep(self, seconds: float) -> None:
        """Record the requested seconds; the instant does not move."""
        self.sleeps.append(seconds)


class SteppingTimer:
    """A timer whose time moves only when it is asked to sleep, by exactly that much."""

    def __init__(self, now: datetime = START) -> None:
        """Start at `now`."""
        self.instant = now
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        """The current instant."""
        return self.instant

    def sleep(self, seconds: float) -> None:
        """Record the requested seconds and advance by them."""
        self.sleeps.append(seconds)
        self.instant += timedelta(seconds=seconds)


def gaps(stamps: Sequence[tuple[str, datetime]]) -> list[timedelta]:
    """The time between each stamp and the one before it, in order."""
    return [later[1] - earlier[1] for earlier, later in itertools.pairwise(stamps)]
