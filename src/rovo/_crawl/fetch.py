"""The Fetcher seam: one method, one request per call (crawl.allium fetch_or_render, http).

`HttpxFetcher` follows no redirect: a 3xx answer comes back as it is, its raw Location
header in `location`, and the crawl's follower (rovo._crawl.pace.follow) decides what it
means. A transport error is an answer with status 0 and the error set.
"""

import importlib.metadata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Protocol, Self

import httpx

from rovo._crawl.model import CONFIG, SiteResponse
from rovo._mirror.state import Clock, SystemClock


@dataclass(frozen=True, kw_only=True)
class Validators:
    """The stored validators a conditional fetch sends."""

    etag: str | None
    last_modified: str | None


class Fetcher(Protocol):
    """Fetches one URL: exactly one request, no redirect followed."""

    def fetch(self, url: str, *, validators: Validators | None = None) -> SiteResponse:
        """One request; a transport error comes back as status 0 with error set."""
        ...


class HttpxFetcher:
    """The real fetcher: one httpx.Client per run, closed when the run ends."""

    def __init__(
        self, *, transport: httpx.BaseTransport | None = None, clock: Clock | None = None
    ) -> None:
        """Open the client; `transport` replaces the network in tests.

        `clock` dates a Retry-After given as an HTTP date when the answer has no Date.
        """
        self._clock = clock or SystemClock()
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(CONFIG.fetch_timeout.total_seconds()),
            follow_redirects=False,
            headers={"User-Agent": f"rovo/{importlib.metadata.version('rovo')}"},
        )

    def fetch(self, url: str, *, validators: Validators | None = None) -> SiteResponse:
        """One request; a transport error comes back as status 0 with error set."""
        headers: dict[str, str] = {}
        if validators is not None and validators.etag is not None:
            headers["If-None-Match"] = validators.etag
        if validators is not None and validators.last_modified is not None:
            headers["If-Modified-Since"] = validators.last_modified
        try:
            response = self._client.get(url, headers=headers)
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            return SiteResponse(
                status=0,
                source_url=url,
                markup="",
                size=0,
                error=str(error) or type(error).__name__,
            )
        return SiteResponse(
            status=response.status_code,
            source_url=url,
            markup=response.text,
            size=len(response.content),
            content_type=response.headers.get("content-type"),
            retry_after=self._retry_after(response.headers),
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
            location=response.headers.get("location"),
        )

    def _retry_after(self, headers: httpx.Headers) -> timedelta | None:
        """The answer's Retry-After, in seconds or as an HTTP date, as a duration.

        A date is measured from the answer's Date header, else from the fetcher's clock;
        a date already past is zero, and an unreadable value is no Retry-After. A number
        of seconds too large for a duration is the longest duration, still past
        retry_after_cap, so it retires the host as any long Retry-After does.
        """
        value = headers.get("retry-after")
        if value is None:
            return None
        text = value.strip()
        if text.isascii() and text.isdigit():
            return _whole_seconds(text)
        until = _http_date(text)
        if until is None:
            return None
        sent = _http_date(headers.get("date", "")) or self._clock.now()
        return max(timedelta(0), until - sent)

    @property
    def is_closed(self) -> bool:
        """The client has been closed."""
        return self._client.is_closed

    def close(self) -> None:
        """Close the client."""
        self._client.close()

    def __enter__(self) -> Self:
        """The fetcher itself."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the client."""
        self.close()


_LONGEST_SECONDS = timedelta.max // timedelta(seconds=1)


def _whole_seconds(digits: str) -> timedelta:
    """A run of ASCII digits as seconds, the longest duration when it holds no more.

    The digits are measured before they are read, so no number past the longest
    duration is ever built, however many digits the header carries.
    """
    significant = digits.lstrip("0") or "0"
    if len(significant) > len(str(_LONGEST_SECONDS)) or int(significant) > _LONGEST_SECONDS:
        return timedelta.max
    return timedelta(seconds=int(significant))


def _http_date(text: str) -> datetime | None:
    """An HTTP date as a timezone-aware datetime, None when it is not one."""
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
