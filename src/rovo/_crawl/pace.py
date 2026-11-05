"""The timer seam, the per-host limiter, retry_wait and fetch_resource (crawl.allium).

Every request a run makes, robots.txt, page tries and retries alike, first waits its turn
at its host name's limiter: the host's pause, then its rate slot, folded into one wait.
There is no burst: the starts of two requests to one host name are at least
`1 / host.rate` apart, and at least `host.crawl_delay` apart when Crawl-delay is honoured
(AttemptTier guidance). The wait is computed once from the timer and never looped on, so
a timer that stands still cannot hang a run.

`time` is imported as a module and its functions are called as attributes, so a test
can replace `pace.time.sleep` and `pace.time.monotonic`.
"""

import dataclasses
import time as time  # noqa: PLC0414  Re-exported: tests patch pace.time.sleep and .monotonic.
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from rovo._crawl.fetch import Fetcher, Validators
from rovo._crawl.model import CONFIG, CrawlPolicy, Host, HostBackedOff, Run, SiteResponse


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
    run = host.run
    until = run.timer.now() + run.policy.retry_after_cap
    host.paused_until = until if host.paused_until is None else max(host.paused_until, until)
    backed_off = HostBackedOff(host=host, until=until)
    run.backoffs.append(backed_off)
    return backed_off


def fetch_resource(
    url: str,
    run: Run,
    host: Host,
    fetcher: Fetcher,
    validators: Validators | None = None,
) -> SiteResponse:
    """crawl.allium fetch_resource: the http tier under the host's limiter, with retries.

    Its tries are a page's http tries (FetchRobots guidance): a retryable answer is
    retried while try < http_attempts, each retry pausing the host and raising a
    HostBackedOff; every try whose retryable answer carries a Retry-After while
    honor_retry_after holds adds one to the host's retry_after_honored. A Retry-After
    past retry_after_cap ends the tries with that answer, with no wait and no pause;
    whether it retires or pauses the host is the caller's to say. Every try sends the
    validators given, which only a sitemap with a snapshot has. No redirect is
    followed. The size covers every try's bytes; no try counts as a fetch attempt.
    """
    policy = run.policy
    received = 0
    try_ = 1
    while True:
        wait_turn(host)
        response = fetcher.fetch(url, validators=validators)
        received += response.size
        if response.retryable and response.retry_after is not None and policy.honor_retry_after:
            host.retry_after_honored += 1
        if past_cap(response, policy) or not response.retryable or try_ >= CONFIG.http_attempts:
            return dataclasses.replace(response, size=received)
        back_off(host, try_, response.retry_after)
        try_ += 1
