"""The timer seam, the per-host limiter, retry_wait and fetch_resource (crawl.allium).

Every request a run makes, robots.txt, page tries and retries alike, first waits its turn
at its host name's limiter: the host's pause, then its rate slot, folded into one wait.
There is no burst: the starts of two requests to one host name are at least
`1 / host.rate` apart, and at least `host.crawl_delay` apart when Crawl-delay is honoured
(AttemptTier guidance). The wait is computed once from the timer and never looped on, so
a timer that stands still cannot hang a run.

`follow` is the one redirect follower: a 301, 302, 303, 307 or 308 with a Location is
followed hop by hop, each hop under its destination host name's limiter, at most
`discovery_max_redirects` hops, never revisiting a URL (by identity), and only to a
target the caller admits; validators go on the first request only. Pages
(`run.attempt_tier`) and `fetch_resource` both use it.

`time` is imported as a module and its functions are called as attributes, so a test
can replace `pace.time.sleep` and `pace.time.monotonic`.
"""

import dataclasses
import time as time  # noqa: PLC0414  Re-exported: tests patch pace.time.sleep and .monotonic.
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from rovo._crawl.fetch import Fetcher, Validators
from rovo._crawl.model import (
    CONFIG,
    CrawlPolicy,
    Host,
    HostBackedOff,
    RedirectStop,
    Run,
    SiteResponse,
)
from rovo._crawl.model import (
    RETIRED_HOP as RETIRED_HOP,  # noqa: PLC0414  Re-exported: FetchAttempt.hop_refused reads it.
)
from rovo._crawl.sitemaps import resolve_url
from rovo._mirror.urls import hostname_of

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_REDIRECTS = range(300, 400)
# DisposeFetch's errors for an unfollowed redirect, by its stop.
STOP_ERRORS = {
    RedirectStop.loop: "redirect loop",
    RedirectStop.hop_limit: "too many redirects",
    RedirectStop.out_of_scope: "redirected out of scope",
}
DISALLOWED_HOP = "redirect disallowed by robots.txt"
_NO_LOCATION = "redirect without a usable Location"


class Timer(Protocol):
    """The time source the run paces with: `now()` is timezone-aware UTC."""

    def now(self) -> datetime:
        """The current time, UTC."""
        ...

    def sleep(self, seconds: float) -> None:
        """Wait `seconds`."""
        ...


class SystemTimer:
    """The real timer: a wall-clock anchor advanced by the monotonic clock.

    The wall clock is read once, at construction; a later step of it changes no wait.
    """

    def __init__(self) -> None:
        """Anchor the wall clock to the monotonic clock once."""
        self._wall = datetime.now(UTC)
        self._mono = time.monotonic()

    def now(self) -> datetime:
        """The anchored wall-clock time, UTC."""
        return anchored_now(self._wall, self._mono, time.monotonic())

    def sleep(self, seconds: float) -> None:
        """Wait `seconds` through time.sleep."""
        time.sleep(seconds)


def anchored_now(wall: datetime, mono: float, mono_now: float) -> datetime:
    """`wall` advanced by the monotonic delta `mono_now - mono`."""
    return wall + timedelta(seconds=mono_now - mono)


def retry_wait(
    try_: int,
    retry_after: timedelta | None,
    policy: CrawlPolicy,
    draw: Callable[[float, float], float],
) -> timedelta:
    """crawl.allium retry_wait; `draw(low, high)` returns a factor in [low, high].

    `min(backoff_base * 2^(try - 1), max_backoff)` scaled by a factor drawn from
    `[1 - backoff_jitter, 1 + backoff_jitter]` while retry_backoff holds, else nothing;
    then lengthened to at least the Retry-After while honor_retry_after holds.
    """
    wait = timedelta(0)
    if policy.retry_backoff:
        backoff: timedelta = min(policy.backoff_base * 2 ** (try_ - 1), policy.max_backoff)
        wait = backoff * draw(1 - CONFIG.backoff_jitter, 1 + CONFIG.backoff_jitter)
    if policy.honor_retry_after and retry_after is not None:
        wait = max(wait, retry_after)
    return wait


def spacing(host: Host) -> timedelta:
    """The least gap between the starts of two requests to the host name.

    `1 / host.rate` when the rate control is on, and at least `host.crawl_delay` when
    Crawl-delay is honoured: disabling one control never disables another.
    """
    gap = timedelta(0) if host.rate is None else timedelta(seconds=1 / host.rate)
    if host.run.policy.honor_crawl_delay:
        gap = max(gap, host.crawl_delay)
    return gap


def wait_turn(host: Host) -> None:
    """Wait for the host's pause and its next rate slot, in one wait, then take the slot."""
    timer = host.run.timer
    now = timer.now()
    ready = now
    if host.paused_until is not None:
        ready = max(ready, host.paused_until)
    if host.last_started is not None:
        ready = max(ready, host.last_started + spacing(host))
    wait = (ready - now).total_seconds()
    if wait > 0:
        timer.sleep(wait)
    host.last_started = timer.now()


def back_off(host: Host, try_: int, retry_after: timedelta | None) -> HostBackedOff:
    """HttpRetry's effect on the host: pause it until now + retry_wait, never shortening.

    The HostBackedOff is recorded on the run, which returns it through CrawlResult.
    """
    run = host.run
    until = run.timer.now() + retry_wait(try_, retry_after, run.policy, run.draw)
    host.paused_until = until if host.paused_until is None else max(host.paused_until, until)
    backed_off = HostBackedOff(host=host, until=until)
    run.backoffs.append(backed_off)
    if run.on_backoff is not None:  # The root's AnnounceBackoff, live.
        run.on_backoff(backed_off)
    return backed_off


def past_cap(response: SiteResponse, policy: CrawlPolicy) -> bool:
    """A retryable answer whose honoured Retry-After is past retry_after_cap.

    FetchRobots' retires_host and the past_cap of FetchSitemap and ReadLlmsTxt.
    """
    return (
        response.retryable
        and response.retry_after is not None
        and policy.honor_retry_after
        and response.retry_after > policy.retry_after_cap
    )


def pause_for_cap(host: Host) -> HostBackedOff:
    """A speculative probe past the cap: pause the host until now + retry_after_cap.

    paused_until = later_of(paused_until, now + retry_after_cap), never shortening a
    longer pause; the HostBackedOff carries now + retry_after_cap and is recorded on the
    run (FetchSitemap, ReadLlmsTxt).
    """
    return pause_host(host, host.run.policy.retry_after_cap)


def pause_host(host: Host, wait: timedelta) -> HostBackedOff:
    """Pause the host until now + `wait`, never shortening a longer pause.

    The HostBackedOff carries now + `wait` and is recorded on the run and handed to the
    root's AnnounceBackoff (pause_for_cap; a browser subrequest's Retry-After).
    """
    run = host.run
    until = run.timer.now() + wait
    host.paused_until = until if host.paused_until is None else max(host.paused_until, until)
    backed_off = HostBackedOff(host=host, until=until)
    run.backoffs.append(backed_off)
    if run.on_backoff is not None:  # The root's AnnounceBackoff, live.
        run.on_backoff(backed_off)
    return backed_off


def redirect_target(response: SiteResponse, run: Run) -> str | None:
    """The redirect's target, its Location resolved against the URL that answered.

    None when the answer is not a 301, 302, 303, 307 or 308, or its Location is missing
    or gives no URL with an identity: such an answer is not followed.
    """
    if response.status not in _REDIRECT_STATUSES or not response.location:
        return None
    try:
        target = resolve_url(response.source_url, response.location.strip())
        run.target.scope.identity_of(target)
    except ValueError:  # urljoin or normalise_url cannot parse it.
        return None
    return target


def follow(  # noqa: PLR0913  One request's URL, its limiter and validators, and the hop tests.
    url: str,
    host: Host,
    fetcher: Fetcher,
    validators: Validators | None,
    *,
    admits: Callable[[str], bool],
    ready: Callable[[str], Host | None],
) -> SiteResponse:
    """One request and its redirect hops: the final answer, its size every hop's bytes.

    A hop's target that loops back (by identity), passes discovery_max_redirects or
    `admits` refuses is not requested: the last answer comes back with redirect_location
    and its redirect_stop. A hop onto a host whose breaker has tripped is not requested
    and `ready` is not asked (its robots.txt is not read): it ends as the error answer
    RETIRED_HOP, as does a hop whose host the robots.txt read `ready` makes retires
    (crawl.allium 834-838, 1636-1640). `ready(target)` gives the host name whose limiter
    the hop waits at, or None when robots.txt disallows the hop, which ends as the error
    answer DISALLOWED_HOP.
    The final answer's redirect_hops are the URLs left behind, the requested one first.
    """
    identity_of = host.run.target.scope.identity_of

    def tripped(target: str) -> bool:
        known = host.run.host(hostname_of(target))
        return known is not None and known.breaker_tripped

    wait_turn(host)
    response = fetcher.fetch(url, validators=validators)
    received = response.size
    visited = {identity_of(url)}
    hops: list[str] = []
    while (target := redirect_target(response, host.run)) is not None:
        stop = None
        if identity_of(target) in visited:
            stop = RedirectStop.loop
        elif len(hops) >= CONFIG.discovery_max_redirects:
            stop = RedirectStop.hop_limit
        elif not admits(target):
            stop = RedirectStop.out_of_scope
        destination = None if stop is not None or tripped(target) else ready(target)
        retired = stop is None and tripped(target)  # Also when ready's robots.txt read retired it.
        if destination is None or retired:
            error = RETIRED_HOP if retired else DISALLOWED_HOP
            return dataclasses.replace(
                response,
                size=received,
                redirect_hops=tuple(hops),
                redirect_location=target,
                redirect_stop=stop,
                error=None if stop is not None else error,
            )
        hops.append(response.source_url)
        visited.add(identity_of(target))
        wait_turn(destination)
        response = fetcher.fetch(target)
        received += response.size
    return dataclasses.replace(response, size=received, redirect_hops=tuple(hops))


def pending_limiter(host: Host, target: str) -> Host:
    """The limiter of a hop's host name that no host of the run holds yet.

    It spaces requests to that name as a newly opened host would (rate_per_host, no
    Crawl-delay), and OpenHost takes its last start, so limits are kept per host name
    (crawl.allium Politeness) even before the host opens.
    """
    run, name = host.run, hostname_of(target)
    if name not in run.pending_limiters:
        run.pending_limiters[name] = dataclasses.replace(
            host,
            name=name,
            rate=run.policy.rate_per_host,
            crawl_delay=timedelta(0),
            paused_until=None,
            last_started=None,
        )
    return run.pending_limiters[name]


def fetch_resource(  # noqa: PLR0913  FetchRobots' fetch, and the hop's limiter.
    url: str,
    run: Run,
    host: Host,
    fetcher: Fetcher,
    validators: Validators | None = None,
    *,
    ready: Callable[[str], Host | None] | None = None,
) -> SiteResponse:
    """crawl.allium fetch_resource: the http tier under the host's limiter, with retries.

    Its tries are a page's http tries (FetchRobots guidance): a retryable answer is
    retried while try < http_attempts, each retry pausing the host and raising a
    HostBackedOff; every try whose retryable answer carries a Retry-After while
    honor_retry_after holds adds one to the host's retry_after_honored. A Retry-After
    past retry_after_cap ends the tries with that answer, with no wait and no pause;
    whether it retires or pauses the host is the caller's to say. Every try sends the
    validators given, which only a sitemap with a snapshot has, on its first request.
    Redirects within the allowed hosts are followed (`follow`); each try starts again at
    `url`. A redirect stopped (a loop, the hop limit, out of scope) or a 3xx with no
    usable Location ends the tries as an error answer; a hop `follow` refuses as an error
    answer (a retired host, or robots.txt disallowing it) is retried as any error answer
    is (crawl.allium 834 to 845, 1742 to 1743). `ready` gives a hop's host, or None when
    robots.txt disallows it; by default the hop's open host, else its host name's pending
    limiter (`pending_limiter`), with no robots.txt read (robots.txt itself is not
    governed by robots.txt). The size covers every try's and every hop's bytes; no try
    counts as a fetch attempt.
    """
    policy = run.policy
    scope = run.target.scope
    hop_host = ready or (
        lambda target: run.host(hostname_of(target)) or pending_limiter(host, target)
    )
    received = 0
    try_ = 1
    while True:
        response = follow(
            url, host, fetcher, validators, admits=scope.host_allowed, ready=hop_host
        )
        received += response.size
        unfollowed = response.status in _REDIRECTS and not response.not_modified
        # A hop refused as an error answer (RETIRED_HOP, DISALLOWED_HOP) is retried below.
        refused = response.unfollowed_redirect and response.redirect_stop is None
        if (response.unfollowed_redirect or unfollowed) and not refused:
            error = response.error or (
                _NO_LOCATION
                if response.redirect_stop is None
                else STOP_ERRORS[response.redirect_stop]
            )
            return dataclasses.replace(response, size=received, error=error)
        if response.retryable and response.retry_after is not None and policy.honor_retry_after:
            host.retry_after_honored += 1
        if past_cap(response, policy) or not response.retryable or try_ >= CONFIG.http_attempts:
            return dataclasses.replace(response, size=received)
        back_off(host, try_, response.retry_after)
        try_ += 1
