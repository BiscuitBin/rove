"""The Fetcher seam: one method, one request per call (crawl.allium fetch_or_render, http).

`HttpxFetcher` follows no redirect: a 3xx answer comes back as it is, and the crawl
decides what it means. A transport error is an answer with status 0 and the error set.
"""

import importlib.metadata
from dataclasses import dataclass
from datetime import timedelta
from types import TracebackType
from typing import Protocol, Self

import httpx

from rovo._crawl.model import CONFIG, SiteResponse


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

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        """Open the client; `transport` replaces the network in tests."""
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
            retry_after=_retry_after(response.headers.get("retry-after")),
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        )

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


def _retry_after(value: str | None) -> timedelta | None:
    """A Retry-After given in seconds; an HTTP date is left to the politeness slice."""
    if value is None or not value.strip().isdigit():
        return None
    return timedelta(seconds=int(value.strip()))
