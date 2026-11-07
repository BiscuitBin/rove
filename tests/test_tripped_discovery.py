"""A discovery fetch whose own host trips while it is under way (T19 follow-up, e0f0c44).

The maintainer's answer to T19 Open points item 1 (carried from T18-3 item 1): once a
`fetch_resource`'s own host has tripped, its next retry or hop is not made, so no
further request goes to the host, and the fetch ends with the answer it holds: the
error "redirect to a retired host" for a refused hop, the retryable answer itself for a
retry not made (crawl.allium FetchRobots guidance, 868 to 875 at e0f0c44, as
StopWalkOnTrippedHost holds it for a page's walk, BreakerStopsTheRun). A hop onto a
second host, whose own breaker trips, still leaves the source's fetch retried
(tests/test_blocks_regressions.py's C4 tests, unchanged). Hash-pinned in
.allium-loop/T19-browser-tier.json.
"""

import dataclasses
from datetime import timedelta
from pathlib import Path

from fakes import FakeFetcher, FixedClock, html_response, redirect_response, text_response
from rovo._crawl import pace
from rovo._crawl.fetch import Validators
from rovo._crawl.model import RETIRED_HOP, BreakerStatus, Host, SiteResponse, standard_policy
from rovo._crawl.run import run_crawl
from test_pace import (
    HOST,
    NO_DELAY,
    PAGE_HTML,
    PORTED,
    PORTED_ROBOTS,
    ROBOTS,
    SEED,
    SITE,
    new_mirror,
    opened_host,
    request,
)

MAPS = f"{SITE}/maps/guide.xml"
PORTED_MAPS = f"{PORTED}/maps/guide.xml"
SERVICE_UNAVAILABLE = 503


def test_a_sitemap_hop_whose_robots_read_retires_its_own_host_is_not_retried(
    tmp_path: Path,
) -> None:
    """FetchRobots guidance (e0f0c44): the refused hop ends the fetch, with no retry.

    robots.txt declares /maps/guide.xml, which redirects to a second origin of the same
    host, docs.example:8080, whose robots.txt has a Crawl-delay past the cap: reading it
    before the hop retires docs.example (any origin trips the whole host). The hop is
    then onto a tripped host, so it is not made, and the sitemap's fetch, whose own host
    that is, is not retried: /maps/guide.xml is requested once, the second origin's
    robots.txt once, its sitemap never, and no page of the host is requested.
    """
    cap = standard_policy().retry_after_cap.total_seconds()
    fetcher = FakeFetcher(
        {
            ROBOTS: text_response(ROBOTS, f"{NO_DELAY}Sitemap: {MAPS}\n"),
            MAPS: redirect_response(MAPS, PORTED_MAPS),
            PORTED_ROBOTS: text_response(
                PORTED_ROBOTS, f"User-agent: *\nCrawl-delay: {cap + 1}\n"
            ),
            SEED: html_response(SEED, PAGE_HTML.format(title="Start", prose="Start.")),
        }
    )
    result = run_crawl(request(new_mirror(tmp_path)), None, fetcher, FixedClock())
    host = result.run.host(HOST)
    assert host is not None
    assert host.breaker_tripped
    assert fetcher.requests.count(MAPS) == 1
    assert fetcher.requests.count(PORTED_ROBOTS) == 1
    assert PORTED_MAPS not in fetcher.requests
    assert SEED not in fetcher.requests


class TrippingFetcher(FakeFetcher):
    """A FakeFetcher that trips `host`'s breaker as it answers `url`: another walk tripped it."""

    def __init__(self, responses: dict[str, SiteResponse], url: str) -> None:
        """Answer from `responses`; trip the host given later when `url` is requested."""
        super().__init__(responses)
        self.url = url
        self.host: Host | None = None

    def fetch(self, url: str, *, validators: Validators | None = None) -> SiteResponse:
        """Record the request; trip the host on `url`; answer from the map."""
        if url == self.url and self.host is not None and self.host.breaker is not None:
            self.host.breaker.status = BreakerStatus.tripped
        return super().fetch(url, validators=validators)


def test_a_retry_is_not_made_once_the_fetch_host_has_tripped(tmp_path: Path) -> None:
    """FetchRobots guidance (e0f0c44): a retry not made ends the fetch with that answer.

    The sitemap answers 503 with a Retry-After, and its host trips meanwhile (as another
    fetch or walk trips it): fetch_resource returns the 503 itself, makes no second
    request, and neither pauses the host nor raises a HostBackedOff for a retry it does
    not make.
    """
    busy = dataclasses.replace(
        text_response(MAPS, "", status=SERVICE_UNAVAILABLE), retry_after=timedelta(seconds=2)
    )
    fetcher = TrippingFetcher({ROBOTS: text_response(ROBOTS, NO_DELAY), MAPS: busy}, MAPS)
    run, host = opened_host(tmp_path, fetcher)
    fetcher.host = host
    paused_until = host.paused_until
    backoffs = list(run.backoffs)
    response = pace.fetch_resource(MAPS, run, host, fetcher)
    assert host.breaker_tripped
    assert response.status == SERVICE_UNAVAILABLE
    assert fetcher.requests.count(MAPS) == 1
    assert host.paused_until == paused_until
    assert run.backoffs == backoffs


def test_a_refused_hop_onto_the_fetch_host_once_tripped_ends_the_fetch(tmp_path: Path) -> None:
    """FetchRobots guidance (e0f0c44): the refused hop's error is the fetch's response.

    The sitemap redirects to another origin of its own host, and the host trips as the
    redirect is answered: the hop is not made and fetch_resource returns the error
    "redirect to a retired host" with no retry.
    """
    fetcher = TrippingFetcher(
        {ROBOTS: text_response(ROBOTS, NO_DELAY), MAPS: redirect_response(MAPS, PORTED_MAPS)},
        MAPS,
    )
    run, host = opened_host(tmp_path, fetcher)
    fetcher.host = host
    response = pace.fetch_resource(MAPS, run, host, fetcher, ready=lambda _: host)
    assert response.error == RETIRED_HOP
    assert fetcher.requests.count(MAPS) == 1
    assert PORTED_MAPS not in fetcher.requests
