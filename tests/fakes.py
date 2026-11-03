"""Test doubles for the seams: a Fetcher that answers from a map, a Clock that stands still.

`FakeFetcher` records every request in order, so a test can prove what was fetched and
when; a URL it has no answer for comes back 404, as the fixture server would answer.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from rovo._crawl.fetch import Validators
from rovo._crawl.model import SiteResponse

# The instant every FixedClock reads unless told otherwise: timezone-aware UTC.
START = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)

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


class FixedClock:
    """A clock that reads the same instant every time."""

    def __init__(self, now: datetime = START) -> None:
        """Stand still at `now`."""
        self.instant = now

    def now(self) -> datetime:
        """The fixed instant."""
        return self.instant
