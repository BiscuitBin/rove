"""Test doubles for the seams: Fetchers that answer from a map or a script, and timers.

`FakeFetcher` records every request in order, so a test can prove what was fetched and
when; a URL it has no answer for comes back 404, as the fixture server would answer.
`ScriptedFetcher` answers a URL from its script first, one answer per request, then from
the map: an answer that must hold every time goes in the map, a sequence in the script.
`StampingFetcher` wraps any fetcher and stamps each request with its timer's time.

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

from rovo._crawl.fetch import Fetcher, Validators
from rovo._crawl.model import SiteResponse

# The instant every FixedClock reads unless told otherwise: timezone-aware UTC.
START = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)

SITES = Path(__file__).resolve().parent / "fixtures" / "sites"

HTML = "text/html; charset=utf-8"
TEXT = "text/plain; charset=utf-8"
NOT_FOUND = 404


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


def not_found(url: str) -> SiteResponse:
    """A 404 with an empty body."""
    return SiteResponse(status=NOT_FOUND, source_url=url, markup="", size=0, content_type=HTML)


def fixture_site(name: str, base: str) -> dict[str, SiteResponse]:
    """Every file of tests/fixtures/sites/<name>/ as an answer from `base` (ending in /).

    An `.html` file is an HTML answer; any other file, such as robots.txt, a plain-text
    answer. A FakeFetcher over the map serves the site as the end-to-end server would.
    """
    root = SITES / name
    responses: dict[str, SiteResponse] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        url = base + path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        responses[url] = (
            html_response(url, text) if path.suffix == ".html" else text_response(url, text)
        )
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
