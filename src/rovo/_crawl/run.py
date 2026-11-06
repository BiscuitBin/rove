"""One standard run, RunRequested to RunEnded (crawl.allium 611 to 2191).

Each function realises the rule its docstring names and returns without effect when
the rule's guards do not hold. Rules chain only where their docstrings say: Discover
opens hosts and reads their sitemaps and llms.txt, OpenHost reads robots.txt, FetchEntry
makes its first attempt. `run_crawl`
drives the rest in the specification's order, one frontier row after another, and
stops with NotInThisSlice where a later slice's branch would be taken. Every request,
each redirect hop included, waits its turn at its host name's limiter (rovo._crawl.pace)
on the run's timer.
"""

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import MAX_EMAX, Decimal, InvalidOperation
from http import HTTPStatus
from pathlib import Path
from typing import Any, overload

from bs4 import BeautifulSoup
from protego import Protego

from rovo._convert.fidelity import (
    convert,
    converted_content,
    extract,
    measure,
    normalize,
    restore,
    with_fetch_flags,
)
from rovo._convert.model import QualityFlag
from rovo._crawl import sitemaps
from rovo._crawl.fetch import Fetcher, Validators
from rovo._crawl.model import (
    CONFIG,
    BlockKind,
    BlockVerdict,
    Breaker,
    BreakerStatus,
    DiscoveryFailed,
    DiscoveryProblem,
    DiscoverySource,
    EntryFailed,
    FetchAttempt,
    Frontier,
    FrontierEntry,
    FrontierStatus,
    Host,
    HostBackedOff,
    LadderWalk,
    ObservedUrl,
    ProgressEvent,
    RedirectStop,
    RenderMode,
    RenderReason,
    RobotsMode,
    RobotsPolicy,
    RobotsStance,
    Run,
    RunKind,
    RunMode,
    RunRequest,
    RunStatus,
    SitemapEntry,
    SitemapSnapshot,
    SiteResponse,
    UrlFailed,
    WalkStatus,
)
from rovo._crawl.pace import (
    STOP_ERRORS,
    Timer,
    back_off,
    fetch_resource,
    follow,
    past_cap,
    pause_for_cap,
)
from rovo._mirror.intake import admit_candidate, links_found, settle_candidate
from rovo._mirror.model import (
    CandidateDelivered,
    CandidateDiscarded,
    CandidateDuplicate,
    CandidateOutcome,
    CrawlScope,
    LinksFound,
    Mirror,
    Page,
    PageCandidate,
    PageRemoved,
    Tier,
)
from rovo._mirror.state import Clock, read_json, state_path, timestamp, write_json
from rovo._mirror.urls import hostname_of, origin_of
from rovo._unfinished import NotInThisSlice

USER_AGENT = "rovo"
_FRONTIER = "frontier.json"
_SITEMAPS = "sitemaps.json"
_RUNS = "runs.json"
_ACCESS_DENIED = frozenset({401, 403})
_CRAWL_DELAY = "crawl-delay"
_SECONDS_PER_DAY = 86400
_MICROSECONDS = 6
# A Crawl-delay written with an exponent past Decimal's limit, such as 1e1000000000000000000:
# kept as the largest power of ten Decimal holds, past every cap.
_PAST_EVERY_CAP = Decimal(f"1e{MAX_EMAX}")
_TOO_MANY_REQUESTS = 429
_SPA_ROOTS = ("root", "app", "__next", "__nuxt")
# The rows a full run notes for a recheck when its discovery names them again (PrepareRun).
_RECHECKABLE = frozenset(
    {
        FrontierStatus.absent,
        FrontierStatus.duplicate,
        FrontierStatus.done,
        FrontierStatus.skipped_not_html,
    }
)
_UNRESOLVED = frozenset(
    {
        FrontierStatus.pending,
        FrontierStatus.in_progress,
        FrontierStatus.failed,
        FrontierStatus.blocked,
        FrontierStatus.skipped_robots,
        FrontierStatus.skipped_blocked,
        FrontierStatus.skipped_limit,
    }
)


@dataclass(frozen=True, kw_only=True)
class RunRecord:
    """One row of <out>/.rovo/runs.json."""

    id: int
    kind: str
    mode: str
    status: str
    scope_hash: str
    dry_run: bool
    started_at: str
    finished_at: str | None
    unresolved_urls: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class CrawlResult:
    """What one run leaves: the ended run, its frontier and the events the root takes."""

    run: Run
    frontier: Frontier
    failed: tuple[UrlFailed, ...] = ()
    discovery_failed: tuple[DiscoveryFailed, ...] = ()
    backed_off: tuple[HostBackedOff, ...] = ()
    # The intake's PageRemoved events (RemoveAbsentPage, RemoveRedirectedOutPage, a merge).
    removed: tuple[PageRemoved, ...] = ()


# --- Starting a run -------------------------------------------------------------------


def start_run(request: RunRequest, clock: Timer) -> Run | None:
    """Realises crawl.allium StartRun; the run paces on `clock` and draws its own jitter."""
    owner_ready = (
        request.baseline is not None and request.preceding is not None and request.owned_hosts
    )
    if request.mode is not RunMode.standard and not owner_ready:
        return None
    return Run(
        target=request.mirror,
        operator=request.operator,
        id=request.id,
        kind=request.kind,
        mode=request.mode,
        baseline=request.baseline,
        preceding=request.preceding,
        scope_hash=request.scope_hash,
        owned_hosts=request.owned_hosts,
        requested_owner_test=request.requested_owner_test,
        policy=request.policy,
        dry_run=request.dry_run,
        interactive=request.interactive,
        render_mode=request.render_mode,
        stealth_mode=request.stealth_mode,
        max_age=request.max_age,
        refollow_unchanged_links=request.refollow_unchanged_links,
        targets=request.targets,
        forced_refetch=frozenset(),
        active_urls=frozenset(),
        recheckable_urls=frozenset(),
        unresolved_urls=frozenset(),
        error=None,
        interrupt_requested=False,
        crawling=False,
        budget_stopped=False,
        bytes_fetched=0,
        fetch_attempts=0,
        started_at=clock.now(),
        status=RunStatus.running,
        timer=clock,
        # Jitter spreads retries; it needs no cryptographic strength, only its own source.
        draw=random.Random().uniform,  # noqa: S311  Backoff jitter, not a secret.
    )


@overload
def create_frontier(run: Run, existing: None) -> Frontier: ...
@overload
def create_frontier(run: Run, existing: Frontier) -> None: ...
def create_frontier(run: Run, existing: Frontier | None) -> Frontier | None:
    """Realises crawl.allium CreateFrontier: a new frontier, or None when one exists."""
    if existing is not None:
        return None
    return Frontier(mirror=run.target)


@overload
def attach_frontier(run: Run, existing: None) -> None: ...
@overload
def attach_frontier(run: Run, existing: Frontier) -> Frontier: ...
def attach_frontier(run: Run, existing: Frontier | None) -> Frontier | None:
    """Realises crawl.allium AttachFrontier: the existing frontier, or None."""
    del run  # The frontier is the run's mirror's; FrontierAttached names the run.
    return existing


def prepare_run(run: Run, frontier: Frontier | None) -> bool:
    """Realises crawl.allium PrepareRun (the standard full and targeted branches).

    In-progress rows return to pending. A targeted run re-pends only its targets, a
    deferred one at the start priority, or creates a row for one with none (discovered
    via named); they are refetched without validators. A full run re-pends the row of
    every written page the scope admits, rechecks removed pages last and retries the
    failed, blocked and skipped rows the scope admits; its absent, duplicate, done and
    skipped_not_html rows, as they stood before, are noted in recheckable_urls for
    Enqueue to re-pend once if discovery names one again. The owner-testing branch is a
    later slice's.
    """
    if run.status is not RunStatus.running or frontier is None:
        return False
    if run.is_owner_testing:
        raise NotInThisSlice(rule="PrepareRun")
    for entry in frontier.in_progress_entries:
        entry.status = FrontierStatus.pending
    if run.targets:
        _prepare_targets(run, frontier)
    else:
        _prepare_full(run, frontier)
    return True


def _prepare_full(run: Run, frontier: Frontier) -> None:
    """PrepareRun's full branch: rechecks, removed pages last, retries, recheckable rows."""
    mirror = run.target
    run.forced_refetch = _stale_pages(run) if run.kind is RunKind.update else frozenset()
    run.active_urls = frozenset(entry.identity for entry in frontier.entries)
    run.recheckable_urls = frozenset(
        entry.identity for entry in frontier.entries if entry.status in _RECHECKABLE
    )
    for page in mirror.written_pages:
        if mirror.scope.within_bounds(page.source_url):
            _pend(frontier, page.identity, CONFIG.recheck_priority, page.sitemap_lastmod)
    for page in mirror.removed_pages:
        if mirror.scope.within_bounds(page.identity):
            row = _pend(frontier, page.identity, CONFIG.deferred_priority, None)
            row.priority = CONFIG.deferred_priority
    for entry in frontier.retry_entries:
        if mirror.scope.within_bounds(entry.identity):
            entry.status = FrontierStatus.pending


def _prepare_targets(run: Run, frontier: Frontier) -> None:
    """PrepareRun's targeted branch: each target re-pended, or created as named."""
    run.forced_refetch = run.targets
    run.active_urls = run.targets
    for identity in sorted(run.targets):
        row = frontier.entry(identity)
        if row is None:
            frontier.entries.append(
                FrontierEntry(
                    frontier=frontier,
                    identity=identity,
                    depth=0,
                    discovered_via=DiscoverySource.named,
                    discovered_from=None,
                    sitemap_lastmod=None,
                    priority=CONFIG.start_priority,
                    attempts=0,
                    status=FrontierStatus.pending,
                )
            )
            continue
        row.status = FrontierStatus.pending
        if row.is_deferred:
            row.priority = CONFIG.start_priority


# --- Discovery and robots.txt -------------------------------------------------------


def discover(run: Run, frontier: Frontier, fetcher: Fetcher) -> bool:
    """Realises crawl.allium Discover: the seeds enqueued, then each allowed host's discovery.

    Hosts are visited in sorted order: each is opened (its robots.txt read), then its
    sitemaps are queued and read (QueueSitemaps), then its llms.txt (ReadLlmsTxt), so
    every host is opened before any sitemap, llms.txt or page request to it. A targeted
    run opens only its targets' hosts and walks no seed, sitemap or llms.txt; the
    owner-testing branch is a later slice's.
    """
    if run.status is not RunStatus.running:
        return False
    if run.is_owner_testing:
        raise NotInThisSlice(rule="Discover")
    if run.targeted:
        for target in sorted(run.targets):
            open_host(run, hostname_of(target), origin_of(target), fetcher)
        return True
    scope = run.target.scope
    for url in scope.seeds:
        enqueue(
            run,
            frontier,
            scope.identity_of(url),
            depth=0,
            via=DiscoverySource.start,
            priority=CONFIG.start_priority,
        )
    for name in sorted(scope.allowed_hosts):
        open_host(run, name, _host_origin(scope, name), fetcher)
        _read_sitemaps(run, frontier, name, queue_sitemaps(run, name) or [], fetcher)
        read_llms_txt(run, name, frontier, fetcher)
    return True


def open_host(run: Run, name: str, origin: str, fetcher: Fetcher) -> Host | None:
    """Realises crawl.allium OpenHost, then its RobotsRequested.

    A robots.txt hop that reached the name before it opened leaves its last start, from
    which the host's first request is spaced.
    """
    if run.status is not RunStatus.running or run.host(name) is not None:
        return None
    host = Host(
        run=run,
        name=name,
        origin=origin,
        rate=run.policy.rate_per_host,
        crawl_delay=timedelta(0),
        paused_until=None,
        recent_text_lengths=[],
        tiers_used=frozenset(),
        fetched=0,
        blocked=0,
        render_escalations=0,
        retry_after_honored=0,
        sitemap_children_read=0,
        sitemap_entries_admitted=0,
    )
    pending = run.pending_limiters.pop(name, None)
    host.last_started = None if pending is None else pending.last_started
    host.breaker = Breaker(
        host=host,
        tier=run.usable_tiers[0],
        highest_tier=run.highest_tier,
        outcomes=[],
        escalations=0,
        since_escalation=0,
        status=BreakerStatus.watching,
    )
    run.hosts.append(host)
    fetch_robots(run, name, host.origin, fetcher)
    return host


def fetch_robots(run: Run, name: str, origin: str, fetcher: Fetcher) -> SiteResponse | None:
    """Realises crawl.allium FetchRobots for `origin`, then its RobotsAnswered.

    The request goes through `fetch_resource`, under the host's limiter, with a page's
    retries; the answer ends in exactly one of AdoptRobotsRules, DenyAllWhenRobotsRefused,
    DenyAllWhenRobotsUnreachable or AllowAllWhenRobotsAbsent. Redirects within the
    allowed hosts are followed with no robots.txt read for a hop; one not followed comes
    back as an error, which disallows the origin. Retiring the host (retires_host: a
    Retry-After past the cap, which ends fetch_resource's tries) or on an honoured
    Crawl-delay past it (RetireHostOnLongCrawlDelay), which stops once the rules are
    adopted, is a later slice's branch.
    """
    host = run.host(name)
    if run.status is not RunStatus.running or host is None:
        return None
    if run.robots_policy(origin) is not None:
        return None
    response = fetch_resource(robots_url(origin), run, host, fetcher)
    run.bytes_fetched += response.size
    if past_cap(response, run.policy):
        raise NotInThisSlice(rule="RetireHostOnLongRetryAfter")
    adopted = adopt_robots_rules(run, host, response, origin=origin)
    if adopted is not None:
        if retires_host_on_long_crawl_delay(run, adopted):
            raise NotInThisSlice(rule="RetireHostOnLongCrawlDelay")
        return response
    failed = deny_all_when_robots_refused(
        run, host, response, origin=origin
    ) or deny_all_when_robots_unreachable(run, host, response, origin=origin)
    if failed is not None:
        run.discovery_failures.append(failed)
    else:
        allow_all_when_robots_absent(run, host, response, origin=origin)
    return response


def robots_url(origin: str) -> str:
    """crawl.allium robots_url: the origin's /robots.txt."""
    return f"{origin}/robots.txt"


def adopt_robots_rules(
    run: Run, host: Host, response: SiteResponse, *, origin: str | None = None
) -> RobotsPolicy | None:
    """Realises crawl.allium AdoptRobotsRules; `origin` defaults to the host's.

    The file is parsed with protego for the user agent rovo. A Crawl-delay past
    retry_after_cap is never adopted (past_cap): the policy records none and the host is
    unchanged. Otherwise, while Crawl-delay is honoured and the group declares one, the
    host keeps the longest delay of its origins and, for a delay above zero, the lowest
    rate: min(rate, 1 / delay).
    """
    if not response.ok:
        return None
    rules, declared = parse_robots(response.markup)
    past_cap = robots_crawl_delay_exceeds(declared, run.policy.retry_after_cap)
    delay = None if past_cap else robots_crawl_delay(declared)
    policy = RobotsPolicy(
        run=run,
        origin=host.origin if origin is None else origin,
        stance=RobotsStance.rules,
        crawl_delay=delay,
        declared_sitemaps=tuple(rules.sitemaps),
        problem=None,
        rules=rules,
        declared_delay=declared,
    )
    run.robots_policies.append(policy)
    if run.policy.honor_crawl_delay and delay is not None:
        host.crawl_delay = max(host.crawl_delay, delay)
        if host.rate is not None and delay > timedelta(0):
            host.rate = min(host.rate, 1 / delay.total_seconds())
    return policy


def parse_robots(markup: str) -> tuple[Protego, Decimal | None]:
    """Parse robots.txt with protego, keeping the rovo group's Crawl-delay as written.

    protego reads a Crawl-delay as a float, which turns '1e400' into no delay and
    '120.000000000000001' into 120. So each Crawl-delay line's value is replaced by its
    ordinal before protego reads the file and kept as an exact Decimal; protego still
    chooses the group and the last valid directive in it, and its answer is mapped back.
    A value that is not a finite, non-negative number in protego's (float's) grammar is
    replaced by one protego drops; a number too large for Decimal is kept past every cap.
    """
    declared: list[Decimal] = []
    lines: list[str] = []
    for line in markup.splitlines():
        value = _crawl_delay_value(line)
        if value is None:
            lines.append(line)
            continue
        number = _decimal_seconds(value)
        if number is None:
            lines.append("Crawl-delay: -")
            continue
        lines.append(f"Crawl-delay: {len(declared)}")
        declared.append(number)
    rules = Protego.parse("\n".join(lines))
    ordinal = rules.crawl_delay(USER_AGENT)
    return rules, None if ordinal is None else declared[int(ordinal)]


def _crawl_delay_value(line: str) -> str | None:
    """The value of a Crawl-delay directive line, read as protego reads directives.

    A comment is cut and the line stripped; 'field: value' is a Crawl-delay when the
    field is 'crawl-delay' or 'crawl delay', and a line whose colon does not separate a
    known field is read as whitespace-separated words, as protego's parser does.
    """
    line = line.split("#", 1)[0].strip()
    if ":" in line:
        name, raw = line.split(":", 1)
        if name.strip().lower() in {_CRAWL_DELAY, "crawl delay"}:
            return raw.strip() or None
        if not raw or raw[0].isspace():
            return None
    words = line.split()
    lowered = [word.lower() for word in words[:2]]
    if lowered[:1] == [_CRAWL_DELAY]:
        return " ".join(words[1:]) or None
    if lowered == ["crawl", "delay"]:
        return " ".join(words[2:]) or None
    return None


def _decimal_seconds(value: str) -> Decimal | None:
    """A Crawl-delay value as an exact number of seconds; null when it is not a number.

    A number is what protego reads, Python's float grammar ('1_000' and surrounding
    blanks included, '_121' or '1__21' not), so the value is checked with float() before
    Decimal() reads it exactly. A finite number whose exponent is past Decimal's limit
    is still a number: a positive one too large is kept past every cap, one too small
    (or a zero) is 0. inf, nan and negative values are null.
    """
    try:
        float(value)
    except ValueError:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return _beyond_decimal_range(value)
    if not number.is_finite() or number < 0:
        return None
    return number


def _beyond_decimal_range(value: str) -> Decimal | None:
    """A float-grammar number Decimal cannot hold: its exponent is past Decimal's limit."""
    mantissa, _, exponent = value.strip().lower().partition("e")
    significand = Decimal(mantissa)
    if significand < 0:
        return None
    if significand == 0 or exponent.lstrip().startswith("-"):
        return Decimal(0)
    return _PAST_EVERY_CAP


def robots_crawl_delay(declared: Decimal | None) -> timedelta | None:
    """crawl.allium robots_crawl_delay: the rovo group's Crawl-delay as decimal seconds.

    Null when the group declares none or its value is not a number. Read only when
    robots_crawl_delay_exceeds is false, so the number always fits a timedelta.
    """
    return None if declared is None else timedelta(seconds=float(declared))


def robots_crawl_delay_exceeds(declared: Decimal | None, cap: timedelta) -> bool:
    """crawl.allium robots_crawl_delay_exceeds: the rovo group's Crawl-delay is past `cap`.

    The number is compared exactly as written, as a Decimal against the cap's seconds,
    and never becomes a float or a timedelta: '1e400' and '120.000000000000001' are past
    a 120-second cap rather than no delay, an overflow or a rounding to the cap, and so is
    a number whose exponent is past Decimal's own limit ('1e1000000000000000000').
    """
    if declared is None:
        return False
    whole = Decimal(cap.days * _SECONDS_PER_DAY + cap.seconds)
    return declared > whole + Decimal(cap.microseconds).scaleb(-_MICROSECONDS)


def retires_host_on_long_crawl_delay(run: Run, adopted: RobotsPolicy) -> bool:
    """Whether crawl.allium RetireHostOnLongCrawlDelay's guards hold for an adopted policy.

    The robots.txt answered ok (AdoptRobotsRules created `adopted`), Crawl-delay is
    honoured, and its Crawl-delay is past retry_after_cap. The trip itself is the breaker
    slice's, so the caller stops there.
    """
    if adopted.rules is None or not run.policy.honor_crawl_delay:
        return False
    return robots_crawl_delay_exceeds(adopted.declared_delay, run.policy.retry_after_cap)


def allow_all_when_robots_absent(
    run: Run, host: Host, response: SiteResponse, *, origin: str | None = None
) -> RobotsPolicy | None:
    """Realises crawl.allium AllowAllWhenRobotsAbsent; `origin` defaults to the host's."""
    if response.ok or response.error is not None:
        return None
    if response.access_refused or response.server_error:
        return None
    policy = RobotsPolicy(
        run=run,
        origin=host.origin if origin is None else origin,
        stance=RobotsStance.allow_all,
        crawl_delay=None,
        declared_sitemaps=(),
        problem=None,
    )
    run.robots_policies.append(policy)
    return policy


def deny_all_when_robots_refused(
    run: Run, host: Host, response: SiteResponse, *, origin: str | None = None
) -> DiscoveryFailed | None:
    """Realises crawl.allium DenyAllWhenRobotsRefused; `origin` defaults to the host's."""
    if response.ok or not (response.access_refused or response.server_error):
        return None
    where = host.origin if origin is None else origin
    return _deny_all(run, where, DiscoveryProblem.robots_refused)


def deny_all_when_robots_unreachable(
    run: Run, host: Host, response: SiteResponse, *, origin: str | None = None
) -> DiscoveryFailed | None:
    """Realises crawl.allium DenyAllWhenRobotsUnreachable; `origin` defaults to the host's."""
    if response.ok or response.error is None:
        return None
    where = host.origin if origin is None else origin
    return _deny_all(run, where, DiscoveryProblem.robots_unreachable)


def _deny_all(run: Run, origin: str, problem: DiscoveryProblem) -> DiscoveryFailed:
    """A disallow_all policy for the origin, and the DiscoveryFailed naming its robots.txt."""
    run.robots_policies.append(
        RobotsPolicy(
            run=run,
            origin=origin,
            stance=RobotsStance.disallow_all,
            crawl_delay=None,
            declared_sitemaps=(),
            problem=problem,
        )
    )
    return DiscoveryFailed(run=run, url=robots_url(origin), problem=problem)


def robots_allows(run: Run, url: str) -> bool:
    """crawl.allium robots_allows, for the user agent rovo, by the URL's own origin.

    True under robots = ignore and for an origin whose stance is allow_all, false under
    disallow_all or before the origin's robots.txt is known, else the parsed rules'
    answer: RFC 9309 matching as protego 0.7 implements it, the index.html fold and the
    literal-$ copy included (crawl.allium 1070 to 1110).
    """
    if run.policy.robots is RobotsMode.ignore:
        return True
    policy = run.robots_policy(origin_of(url))
    if policy is None or policy.stance is RobotsStance.disallow_all:
        return False
    if policy.rules is None:
        return policy.stance is RobotsStance.allow_all
    return policy.rules.can_fetch(url, USER_AGENT)


def enqueue(  # noqa: PLR0913  The UrlDiscovered trigger's parameters.
    run: Run,
    frontier: Frontier,
    url: str,
    *,
    depth: int,
    via: DiscoverySource,
    priority: int,
    from_url: str | None = None,
    lastmod: str | None = None,
) -> FrontierEntry:
    """Realises crawl.allium Enqueue: dedup by identity.

    A row's status changes only when an owner-testing run newly admits it, or when a full
    run's discovery names a row PrepareRun noted as recheckable and no page has its
    identity (re-pended once: the URL leaves recheckable_urls).
    """
    newly_admitted = run.is_owner_testing and url not in run.active_urls
    run.active_urls = run.active_urls | {url}
    existing = frontier.entry(url)
    rediscovered = (
        url in run.recheckable_urls
        and existing is not None
        and existing.status in _RECHECKABLE
        and run.target.page(url) is None
    )
    run.recheckable_urls = run.recheckable_urls - {url}
    if existing is None:
        entry = FrontierEntry(
            frontier=frontier,
            identity=url,
            depth=depth,
            discovered_via=via,
            discovered_from=from_url,
            sitemap_lastmod=lastmod,
            priority=priority,
            attempts=0,
            status=FrontierStatus.pending,
        )
        frontier.entries.append(entry)
        return entry
    if newly_admitted or rediscovered:
        existing.status = FrontierStatus.pending
    existing.depth = min(existing.depth, depth)
    if lastmod is not None:
        existing.sitemap_lastmod = lastmod
    if existing.status is FrontierStatus.pending and existing.is_deferred:
        existing.priority = priority
    return existing


def enqueue_page_links(
    run: Run | None, frontier: Frontier, found: LinksFound
) -> list[FrontierEntry] | None:
    """Realises crawl.allium EnqueuePageLinks; None when its guard does not hold.

    Each content, then navigation, target that is not the page itself and that the scope
    allows at depth + 1 is raised as UrlDiscovered with the link priority, from the page.
    The owner-testing branch (owner_link_needed) is a later slice's.
    """
    if run is None or run.status is not RunStatus.running:
        return None
    if run.mode is not RunMode.standard:
        raise NotInThisSlice(rule="EnqueuePageLinks")
    scope = found.candidate.mirror.scope
    depth = found.depth + 1
    discovered: list[FrontierEntry] = []
    for via, targets in (
        (DiscoverySource.link, found.targets),
        (DiscoverySource.navigation, found.navigation_targets),
    ):
        for url in targets:
            if not scope.allows(url, depth):
                continue  # Tested first: a malformed URL is out of bounds, with no identity.
            identity = scope.identity_of(url)
            if identity != found.page.identity:
                discovered.append(
                    enqueue(
                        run,
                        frontier,
                        identity,
                        depth=depth,
                        via=via,
                        priority=CONFIG.link_priority,
                        from_url=found.page.identity,
                    )
                )
    return discovered


def refollow_unchanged_links(
    run: Run | None, frontier: Frontier, candidate: PageCandidate, page: Page
) -> list[FrontierEntry] | None:
    """Realises crawl.allium RefollowUnchangedLinks; None when its guard does not hold.

    Each of the page's stored outbound links, every kind, is tested again against the
    scope in force as EnqueuePageLinks tests a content link, so a link external under an
    older scope is queued once the scope admits it. Navigation links are not stored.
    """
    if candidate.outcome is not CandidateOutcome.unchanged:
        return None
    if run is None or run.status is not RunStatus.running or not run.refollow_unchanged_links:
        return None
    if run.mode is not RunMode.standard:
        raise NotInThisSlice(rule="RefollowUnchangedLinks")
    scope = candidate.mirror.scope
    depth = candidate.depth + 1
    discovered: list[FrontierEntry] = []
    for link in page.outbound_links:
        if not scope.allows(link.target_identity, depth):
            continue  # Tested first, as EnqueuePageLinks does.
        identity = scope.identity_of(link.target_identity)
        if identity != page.identity:
            discovered.append(
                enqueue(
                    run,
                    frontier,
                    identity,
                    depth=depth,
                    via=DiscoverySource.link,
                    priority=CONFIG.link_priority,
                    from_url=page.identity,
                )
            )
    return discovered


# --- Sitemaps and llms.txt ----------------------------------------------------------


def queue_sitemaps(run: Run, name: str) -> list[tuple[str, bool]] | None:
    """Realises crawl.allium QueueSitemaps: each SitemapDue as (url, declared), in order.

    The declared sitemaps of RobotsPolicy{origin: host.origin}, then each of
    well_known_sitemaps(host.origin) not declared; None when the rule does not fire.
    """
    host = run.host(name)
    if run.status is not RunStatus.running or host is None:
        return None
    policy = run.robots_policy(host.origin)
    declared = policy.declared_sitemaps if policy is not None else ()
    due = [(url, True) for url in declared]
    well_known = sitemaps.well_known_sitemaps(host.origin)
    due.extend((url, False) for url in well_known if url not in declared)
    return due


def read_robots_before_sitemap(run: Run, name: str, url: str, fetcher: Fetcher) -> bool:
    """Realises crawl.allium ReadRobotsBeforeSitemap: True when it read the origin's robots.txt.

    The sitemap is then due again (the caller hands it to fetch_sitemap).
    """
    if not _sitemap_wanted(run, name, url) or run.robots_policy(origin_of(url)) is not None:
        return False
    fetch_robots(run, name, origin_of(url), fetcher)
    return True


def fetch_sitemap(  # noqa: PLR0913  The SitemapDue trigger's parameters, and the frontier.
    run: Run,
    name: str,
    url: str,
    fetcher: Fetcher,
    *,
    declared: bool = False,
    frontier: Frontier | None = None,
) -> SiteResponse | None:
    """Realises crawl.allium FetchSitemap: the SitemapAnswered response, else None.

    Each sitemap is read at most once per run, through fetch_resource, its bytes counted.
    A snapshot the frontier holds for the URL sends its validators and is stamped with
    the run (last_requested_run), whatever the answer. A Retry-After
    past the cap retires the host of a declared sitemap (the breaker slice's trip) and
    pauses it for retry_after_cap after a speculative probe, whose answer then stands.
    Redirects within the allowed hosts are followed, each hop's origin's robots.txt read
    first; one not followed comes back as an error.
    """
    host = run.host(name)
    if host is None or not _sitemap_wanted(run, name, url):
        return None
    if not robots_allows(run, url) or run.robots_policy(origin_of(url)) is None:
        return None
    if url in run.sitemaps_read:
        return None
    run.sitemaps_read.add(url)
    snapshot = None if frontier is None else _snapshot(frontier, url)
    validators = (
        None
        if snapshot is None
        else Validators(etag=snapshot.etag, last_modified=snapshot.last_modified)
    )
    response = fetch_resource(url, run, host, fetcher, validators, ready=_hop_host(run, fetcher))
    run.bytes_fetched += response.size
    if snapshot is not None:
        snapshot.last_requested_run = run.id
    if past_cap(response, run.policy):
        if declared:
            raise NotInThisSlice(rule="RetireHostOnLongRetryAfter")
        pause_for_cap(host)
    return response


def accept_fresh_sitemap(
    run: Run, frontier: Frontier, url: str, response: SiteResponse
) -> SitemapSnapshot | None:
    """Realises crawl.allium AcceptFreshSitemap: the snapshot created or updated, else None.

    The snapshot's is_index and entries are SitemapEntriesFound's; one created is
    stamped with the run.
    """
    if not response.ok or not sitemaps.is_sitemap_document(response):
        return None
    is_index = sitemaps.sitemap_is_index(response)
    entries = sitemaps.sitemap_entries(response)
    snapshot = _snapshot(frontier, url)
    if snapshot is None:
        snapshot = SitemapSnapshot(
            frontier=frontier,
            url=url,
            etag=response.etag,
            last_modified=response.last_modified,
            is_index=is_index,
            entries=entries,
            last_requested_run=run.id,
        )
        frontier.sitemap_snapshots.append(snapshot)
        return snapshot
    snapshot.etag = response.etag
    snapshot.last_modified = response.last_modified
    snapshot.is_index = is_index
    snapshot.entries = entries
    return snapshot


def reuse_unchanged_sitemap(
    run: Run, frontier: Frontier, url: str, response: SiteResponse
) -> SitemapSnapshot | None:
    """Realises crawl.allium ReuseUnchangedSitemap: the snapshot reused, else None.

    Its is_index and entries are the SitemapEntriesFound's; the snapshot is unchanged.
    """
    del run  # SitemapEntriesFound names the run; the snapshot is the frontier's.
    if not response.not_modified:
        return None
    return _snapshot(frontier, url)


def _snapshot(frontier: Frontier, url: str) -> SitemapSnapshot | None:
    """SitemapSnapshot{frontier: frontier, url: url}."""
    return next((kept for kept in frontier.sitemap_snapshots if kept.url == url), None)


def _drop_snapshot(frontier: Frontier | None, url: str) -> None:
    """Drop SitemapSnapshot{frontier: frontier, url: url}: the rules' `not exists`."""
    if frontier is not None:
        frontier.sitemap_snapshots = [
            kept for kept in frontier.sitemap_snapshots if kept.url != url
        ]


def reject_non_sitemap(
    run: Run,
    url: str,
    response: SiteResponse,
    *,
    declared: bool,
    frontier: Frontier | None = None,
) -> DiscoveryFailed | None:
    """Realises crawl.allium RejectNonSitemap: not_a_sitemap for a declared sitemap.

    The URL's snapshot in `frontier`, declared or not, is dropped.
    """
    if not response.ok or sitemaps.is_sitemap_document(response):
        return None
    _drop_snapshot(frontier, url)
    if not declared:
        return None
    return DiscoveryFailed(run=run, url=url, problem=DiscoveryProblem.not_a_sitemap)


def skip_unavailable_sitemap(
    run: Run,
    url: str,
    response: SiteResponse,
    *,
    declared: bool,
    frontier: Frontier | None = None,
) -> DiscoveryFailed | None:
    """Realises crawl.allium SkipUnavailableSitemap: a declared, not absent failure's problem.

    An absent answer (404 or 410) drops the URL's snapshot in `frontier`, declared or
    not; an unavailable or unreachable one keeps it.
    """
    if response.ok or response.not_modified:
        return None
    if response.absent:
        _drop_snapshot(frontier, url)
    if not declared or response.absent:
        return None
    problem = (
        DiscoveryProblem.sitemap_unavailable
        if response.error is None
        else DiscoveryProblem.sitemap_unreachable
    )
    return DiscoveryFailed(run=run, url=url, problem=problem)


def expand_sitemap_entries(  # noqa: PLR0913  The SitemapEntriesFound trigger's parameters.
    run: Run,
    frontier: Frontier,
    host: Host,
    url: str,
    entries: Sequence[SitemapEntry],
    *,
    is_index: bool,
) -> list[str] | None:
    """Realises crawl.allium ExpandSitemapEntries: the child sitemaps now due, else None.

    An index's children on the host that served it, at most sitemap_max_children per
    host (the open question's interim: no child on another host); a urlset's entries
    observed, and admitted at sitemap_depth when in scope, at most
    max_pages * sitemap_cap_multiplier per host. An entry or a child with no identity is
    skipped silently and uncounted. Each child is due with its index's declared.
    """
    if run.status is not RunStatus.running:
        return None
    scope = run.target.scope
    due: list[str] = []
    for entry in entries:
        target = _resolved_or_none(url, entry.loc)
        if target is None:
            continue
        if is_index:
            if (
                host.sitemap_children_read < CONFIG.sitemap_max_children
                and _normalisable(target)
                and hostname_of(target) == host.name
            ):
                host.sitemap_children_read += 1
                due.append(target)
            continue
        identity = _identity_or_none(scope, target)
        if identity is None:
            continue
        record_observation(run, frontier, identity, DiscoverySource.sitemap)
        if (
            scope.allows(target, CONFIG.sitemap_depth)
            and host.sitemap_entries_admitted < CONFIG.max_pages * CONFIG.sitemap_cap_multiplier
        ):
            host.sitemap_entries_admitted += 1
            enqueue(
                run,
                frontier,
                identity,
                depth=CONFIG.sitemap_depth,
                via=DiscoverySource.sitemap,
                priority=CONFIG.sitemap_priority,
                from_url=url,
                lastmod=entry.lastmod,
            )
    return due


def read_llms_txt(
    run: Run, name: str, frontier: Frontier, fetcher: Fetcher
) -> SiteResponse | None:
    """Realises crawl.allium ReadLlmsTxt: the answer, else None when the rule does not fire.

    Never conditional, and silent when absent or unreachable; a Retry-After past the cap
    pauses the host for retry_after_cap and the probe ends unavailable. A target with no
    identity is skipped, and a target is resolved against llms_txt_url, the URL requested.
    Redirects are followed as a sitemap's are.
    """
    host = run.host(name)
    if run.status is not RunStatus.running or host is None:
        return None
    url = sitemaps.llms_txt_url(host.origin)
    if not robots_allows(run, url):
        return None
    response = fetch_resource(url, run, host, fetcher, ready=_hop_host(run, fetcher))
    run.bytes_fetched += response.size
    if past_cap(response, run.policy):
        pause_for_cap(host)
    if not response.ok:
        return response
    scope = run.target.scope
    for target in sitemaps.llms_txt_targets(response, url):
        identity = _identity_or_none(scope, target)
        if identity is None:
            continue
        record_observation(run, frontier, identity, DiscoverySource.llms_txt)
        if scope.allows(target, CONFIG.llms_txt_depth):
            enqueue(
                run,
                frontier,
                identity,
                depth=CONFIG.llms_txt_depth,
                via=DiscoverySource.llms_txt,
                priority=CONFIG.llms_txt_priority,
                from_url=url,
            )
    return response


def record_observation(
    run: Run, frontier: Frontier, url: str, via: DiscoverySource
) -> ObservedUrl:
    """Realises crawl.allium RecordObservation: the observation created or updated."""
    seen = next((observed for observed in frontier.observed_urls if observed.url == url), None)
    if seen is None:
        seen = ObservedUrl(
            frontier=frontier, url=url, sources=frozenset({via}), last_seen_run=run.id
        )
        frontier.observed_urls.append(seen)
        return seen
    seen.sources = seen.sources | {via}
    seen.last_seen_run = run.id
    return seen


def drop_stale_observations(run: Run, frontier: Frontier) -> bool:
    """Realises crawl.allium DropStaleObservations, then records the discovered count.

    A row unseen, or a sitemap snapshot unrequested, for more than
    observed_url_retention_syncs runs is dropped. The frontier's row count now is
    rovo.allium CloseRun's discovered_count.
    """
    if run.status is not RunStatus.running:
        return False
    frontier.observed_urls = [
        observed
        for observed in frontier.observed_urls
        if observed.last_seen_run + CONFIG.observed_url_retention_syncs >= run.id
    ]
    frontier.sitemap_snapshots = [
        snapshot
        for snapshot in frontier.sitemap_snapshots
        if snapshot.last_requested_run + CONFIG.observed_url_retention_syncs >= run.id
    ]
    run.discovered_count = len(frontier.entries)
    return True


def dry_run(run: Run) -> bool:
    """Realises crawl.allium DryRun: True when it raised RunEnding."""
    return run.status is RunStatus.running and run.dry_run


def dry_run_listing(run: Run, frontier: Frontier) -> list[str]:
    """The identities of the rows SelectBatch would consider, in next_pending order.

    What a dry run lists (DryRun guidance).
    """
    pending = [entry for entry in frontier.pending_entries if _selectable(run, entry)]
    return [entry.identity for entry in _next_pending(pending, len(pending))]


def _read_sitemaps(
    run: Run, frontier: Frontier, name: str, due: list[tuple[str, bool]], fetcher: Fetcher
) -> None:
    """Each SitemapDue in turn, an index's children read depth first as they fall due.

    ReadRobotsBeforeSitemap, then FetchSitemap; the answer meets exactly one of
    ReuseUnchangedSitemap or AcceptFreshSitemap (each then ExpandSitemapEntries),
    RejectNonSitemap or SkipUnavailableSitemap, and a 304 with no snapshot meets none.
    """
    stack = list(reversed(due))
    while stack:
        url, declared = stack.pop()
        read_robots_before_sitemap(run, name, url, fetcher)
        response = fetch_sitemap(run, name, url, fetcher, declared=declared, frontier=frontier)
        host = run.host(name)
        if response is None or host is None:
            continue
        snapshot = reuse_unchanged_sitemap(run, frontier, url, response) or accept_fresh_sitemap(
            run, frontier, url, response
        )
        if snapshot is not None:
            children = expand_sitemap_entries(
                run, frontier, host, url, snapshot.entries, is_index=snapshot.is_index
            )
            stack.extend((child, declared) for child in reversed(children or []))
            continue
        failed = reject_non_sitemap(
            run, url, response, declared=declared, frontier=frontier
        ) or skip_unavailable_sitemap(run, url, response, declared=declared, frontier=frontier)
        if failed is not None:
            run.discovery_failures.append(failed)


def _sitemap_wanted(run: Run, name: str, url: str) -> bool:
    """The guards ReadRobotsBeforeSitemap and FetchSitemap share."""
    return (
        run.status is RunStatus.running
        and run.host(name) is not None
        and _normalisable(url)
        and hostname_of(url) == name
        and sitemaps.sitemap_admitted(url, run.target.profile, run.target.scope)
    )


def _normalisable(url: str) -> bool:
    """normalise_url can normalise the URL; a sitemap whose URL it cannot is skipped."""
    try:
        origin_of(url)
    except ValueError:  # A port out of range or an unclosed IPv6 bracket.
        return False
    return True


def _resolved_or_none(base: str, loc: str) -> str | None:
    """resolve_url(base, loc), or None where urljoin cannot parse it (no identity)."""
    try:
        return sitemaps.resolve_url(base, loc)
    except ValueError:  # An unclosed IPv6 bracket.
        return None


def _identity_or_none(scope: CrawlScope, url: str) -> str | None:
    """scope.identity_of(url), or None where normalise_url cannot normalise it."""
    try:
        return scope.identity_of(url)
    except ValueError:  # A port out of range: identity_of is null (mirror.allium 113).
        return None


def begin_crawl(run: Run) -> bool:
    """Realises crawl.allium BeginCrawl."""
    if run.status is not RunStatus.running or run.dry_run:
        return False
    run.crawling = True
    return True


# --- Scheduling ---------------------------------------------------------------------


def select_batch(run: Run, frontier: Frontier) -> list[FrontierEntry] | None:
    """Realises crawl.allium SelectBatch.

    None when the rule does not fire; an empty list when it raised FrontierExhausted;
    otherwise the chosen rows, now in progress.
    """
    if run.status is not RunStatus.running or not run.crawling:
        return None
    pending = [entry for entry in frontier.pending_entries if _selectable(run, entry)]
    open_rows = [entry for entry in pending if not _host_tripped(run, entry)]
    if not run.byte_budget_left:
        return _stop_on_budget(run, pending)
    if not pending:
        return []
    if not open_rows:
        raise NotInThisSlice(rule="SelectBatch")
    hosts = max(1, len(run.target.scope.allowed_hosts))
    concurrency = (run.policy.concurrency_per_host or max(1, len(open_rows))) * hosts
    lookahead = _next_pending(open_rows, concurrency * CONFIG.batch_lookahead)
    chosen = _choose_batch(lookahead, run.page_budget_remaining, run.targets, concurrency)
    if not chosen:
        return _stop_on_budget(run, pending)
    for entry in chosen:
        entry.status = FrontierStatus.in_progress
    return chosen


def next_batch(run: Run, frontier: Frontier) -> bool:
    """Realises crawl.allium NextBatch: True when another BatchRequested is due."""
    return (
        run.status is RunStatus.running
        and run.crawling
        and frontier.mirror is run.target
        and frontier.batch_idle
    )


# --- Handling one frontier entry ----------------------------------------------------


def skip_robots_disallowed(run: Run | None, entry: FrontierEntry) -> bool:
    """Realises crawl.allium SkipRobotsDisallowed."""
    host = _entry_host(run, entry)
    if run is None or host is None or host.breaker_tripped:
        return False
    if robots_allows(run, entry.identity) or not _origin_read(run, entry):
        return False
    entry.status = FrontierStatus.skipped_robots
    return True


def open_host_for_entry(run: Run | None, entry: FrontierEntry, fetcher: Fetcher) -> bool:
    """Realises crawl.allium OpenHostForEntry: True when it raised EntryHostReady."""
    if not _running_for(run, entry) or run is None or run.host(entry.host_name) is not None:
        return False
    open_host(run, entry.host_name, origin_of(entry.identity), fetcher)
    return True


def proceed_with_known_host(run: Run | None, entry: FrontierEntry) -> bool:
    """Realises crawl.allium ProceedWithKnownHost: True when it raised EntryHostReady."""
    host = _entry_host(run, entry)
    if run is None or host is None or host.breaker_tripped:
        return False
    return robots_allows(run, entry.identity) and _origin_read(run, entry)


def read_robots_for_new_origin(run: Run | None, entry: FrontierEntry, fetcher: Fetcher) -> bool:
    """Realises crawl.allium ReadRobotsForNewOrigin: True when it raised EntryHostReady.

    A row on a known host at an origin whose robots.txt is unread reads it first.
    """
    host = _entry_host(run, entry)
    if run is None or host is None or host.breaker_tripped or _origin_read(run, entry):
        return False
    fetch_robots(run, host.name, origin_of(entry.identity), fetcher)
    return True


def skip_robots_disallowed_on_new_host(run: Run, entry: FrontierEntry) -> bool:
    """Realises crawl.allium SkipRobotsDisallowedOnNewHost."""
    if run.status is not RunStatus.running or entry.status is not FrontierStatus.in_progress:
        return False
    if robots_allows(run, entry.identity):
        return False
    entry.status = FrontierStatus.skipped_robots
    return True


def fetch_entry(run: Run, entry: FrontierEntry, fetcher: Fetcher) -> LadderWalk | None:
    """Realises crawl.allium FetchEntry, then its first TierRequested.

    A known page is fetched conditionally, sending its stored validators, unless a
    refresh is forced. No tier hint is learned in this slice, so the walk starts at http.
    """
    if run.status is not RunStatus.running or entry.status is not FrontierStatus.in_progress:
        return None
    host = run.host(entry.host_name)
    if not robots_allows(run, entry.identity) or host is None or host.breaker_tripped:
        return None
    known = run.target.known_page(entry.identity)
    tiers = _start_from(run.usable_tiers, _starting_tier(run))
    entry.attempts += 1
    run.fetch_attempts += 1
    walk = LadderWalk(
        entry=entry,
        host=host,
        tiers=tiers,
        escalated=False,
        challenge_offered=False,
        status=WalkStatus.walking,
        conditional=(
            run.mode is RunMode.standard
            and known is not None
            and entry.identity not in run.forced_refetch
            and known.processing_signature == run.target.processing_signature
            and entry.sitemap_lastmod in {None, known.sitemap_lastmod}
        ),
    )
    attempt_tier(walk, tiers[0], 1, fetcher)
    return walk


def attempt_tier(walk: LadderWalk, tier: Tier, try_: int, fetcher: Fetcher) -> FetchAttempt | None:
    """Realises crawl.allium AttemptTier (the http tier, one try).

    fetch_or_render follows in-scope redirects (`pace.follow`): a hop's origin's
    robots.txt is read first when the run has not, and a hop it disallows is not made.
    """
    run = walk.host.run
    if walk.status is not WalkStatus.walking or run.status is not RunStatus.running:
        return None
    if tier is not Tier.http:
        raise NotInThisSlice(rule="AttemptTier")
    host = walk.host
    response = follow(
        walk.entry.identity,
        host,
        fetcher,
        _validators(walk),
        admits=run.target.scope.within_bounds,
        ready=_hop_host(run, fetcher),
    )
    if try_ > 1 or tier is not walk.tiers[0]:
        run.fetch_attempts += 1
    run.bytes_fetched += response.size
    verdict = classify_block(response, host.median_text if host.has_text_baseline else None)
    unblocked = response.ok and verdict.kind is BlockKind.none
    attempt = FetchAttempt(
        walk=walk,
        tier=tier,
        try_=try_,
        response=response,
        verdict=verdict,
        render_reason=render_reason_of(response) if unblocked else None,
    )
    walk.attempts.append(attempt)
    count_retry_after(attempt)
    survived = not attempt.retryable and not attempt.retires_host
    if response.status == _TOO_MANY_REQUESTS and survived:
        # classify_block: a 429 that survived its retries is a hard verdict.
        raise NotInThisSlice(rule="classify_block")
    return attempt


def prepare_attempt(attempt: FetchAttempt) -> bool:
    """Realises crawl.allium PrepareAttempt: True when it raised AttemptReady.

    A challenge is offered only in an owner-testing run, so a standard run's attempt is
    always ready.
    """
    walk = attempt.walk
    return walk.status is WalkStatus.walking and walk.host.run.status is RunStatus.running


def http_retry(attempt: FetchAttempt, fetcher: Fetcher) -> HostBackedOff | None:
    """Realises crawl.allium HttpRetry, then its TierRequested: the HostBackedOff it raised.

    The host is paused until now + retry_wait, never shortening a pause it had, and the
    next http try waits that pause out at the limiter; the rate is never raised.
    """
    walk = attempt.walk
    if not attempt.retryable:
        return None
    if walk.status is not WalkStatus.walking or walk.host.run.status is not RunStatus.running:
        return None
    backed_off = back_off(walk.host, attempt.try_, attempt.response.retry_after)
    attempt_tier(walk, Tier.http, attempt.try_ + 1, fetcher)
    return backed_off


def count_retry_after(attempt: FetchAttempt) -> bool:
    """Realises crawl.allium CountRetryAfter: True when it counted the Retry-After."""
    host = attempt.walk.host
    response = attempt.response
    if host.run.status is not RunStatus.running or attempt.tier is not Tier.http:
        return False
    if response.retry_after is None or not response.retryable:
        return False
    if not host.run.policy.honor_retry_after:
        return False
    host.retry_after_honored += 1
    return True


def settle_walk(attempt: FetchAttempt) -> bool:
    """Realises crawl.allium SettleWalk (the no-escalation case).

    No attempt is soft-suspected in this slice, so the attempt itself stands.
    """
    walk = attempt.walk
    if walk.status is not WalkStatus.walking or walk.host.run.status is not RunStatus.running:
        return False
    if attempt.retryable or attempt.retires_host:
        return False
    if attempt.wants_escalation and _next_tier(walk.tiers, attempt.tier) is not None:
        return False
    walk.status = WalkStatus.settled
    walk.standing = attempt
    walk.host.tiers_used = walk.host.tiers_used | {attempt.tier}
    if walk.escalated:
        walk.host.render_escalations += 1
    return True


def feed_breaker(walk: LadderWalk) -> bool:
    """Realises crawl.allium FeedBreaker: True when it fed the host's breaker.

    One outcome per settled walk, counted when the standing attempt was a hard block, a
    challenge or failed outright; an ok, unblocked page with main text joins the host's
    text history. Both lists keep only their last config-sized run.
    """
    host = walk.host
    breaker = host.breaker
    standing = walk.standing
    if walk.status is not WalkStatus.settled or standing is None:
        return False
    if breaker is None or breaker.status is not BreakerStatus.watching:
        return False
    if not host.run.policy.breaker_enabled:
        return False
    counted = standing.verdict.counts_against_host or standing.failed_outright
    breaker.outcomes = [*breaker.outcomes, counted][-CONFIG.breaker_window :]
    breaker.since_escalation += 1
    response = standing.response
    if response.ok and standing.verdict.kind is BlockKind.none and response.main_text > 0:
        lengths = [*host.recent_text_lengths, response.main_text]
        host.recent_text_lengths = lengths[-CONFIG.host_text_history :]
    return True


# --- What a settled fetch becomes ---------------------------------------------------


def dispose_fetch(walk: LadderWalk) -> EntryFailed | CandidateDelivered | bool:
    """Realises crawl.allium DisposeFetch, in its branch order: what the settled fetch is.

    The EntryFailed for a walk that failed outright (its error), for an unfollowed
    redirect (its stop's text) or for an answer that is not ok (its status text); a
    CandidateDelivered, its row settled, for a 304 on a known page or an unchanged raw
    document (unchanged), a 404 or 410 (absent, no validators) or a known page redirected
    out of scope (redirected_out, done, the target carried) or a known page that now
    answers non-HTML (absent, its row skipped_not_html: retired as absent); True when
    any other ok, unblocked HTML answer counts as fetched and raises PageFetched; False
    when the guards do not hold, or when an ok answer that is not HTML, for a URL with
    no page, counts as fetched and settles its row skipped_not_html. A block verdict and
    a soft verdict are later slices'.
    """
    attempt = walk.standing
    entry = walk.entry
    if (
        walk.status is not WalkStatus.settled
        or attempt is None
        or entry.status is not FrontierStatus.in_progress
    ):
        return False
    run = walk.host.run
    response = attempt.response
    known = run.target.known_page(entry.identity)
    if attempt.failed_outright:
        error = response.error or "no response"
        return EntryFailed(run=run, entry=entry, error=error, attempts=attempt.try_)
    settled = _settled_answer(walk, attempt, known)
    if settled is not None:
        return settled
    if response.unfollowed_redirect or not response.ok:
        error = (
            STOP_ERRORS[response.redirect_stop or RedirectStop.out_of_scope]
            if response.unfollowed_redirect
            else status_text(response)
        )
        return EntryFailed(run=run, entry=entry, error=error, attempts=attempt.try_)
    raw_unchanged = (
        known is not None
        and known.raw_digest == response.raw_digest
        and known.processing_signature == run.target.processing_signature
        and not response.redirect_hops
    )
    unchanged = (
        raw_unchanged and entry.identity not in run.forced_refetch and run.mode is RunMode.standard
    )
    # A soft verdict is a later slice's (classify_block, T18).
    if attempt.verdict.kind is not BlockKind.none:
        raise NotInThisSlice(rule="DisposeFetch")
    walk.host.fetched += 1
    if unchanged:
        return _unchanged(walk, attempt, response.raw_digest)
    return response.is_html or _not_html(walk, attempt, known)


def _not_html(
    walk: LadderWalk, attempt: FetchAttempt, known: Page | None
) -> CandidateDelivered | bool:
    """DisposeFetch's non-HTML branch: the row skipped_not_html; a known page is absent."""
    walk.entry.status = FrontierStatus.skipped_not_html
    return False if known is None else _delivered(walk, attempt, CandidateOutcome.absent)


def _settled_answer(
    walk: LadderWalk, attempt: FetchAttempt, known: Page | None
) -> CandidateDelivered | None:
    """DisposeFetch's branches that settle the row: not modified, absent, redirected out.

    A hard or challenge verdict, whose branch sits between absent and redirected out, is
    never given in this slice: classify_block stops the run instead (T18).
    """
    response = attempt.response
    if response.not_modified and known is not None:
        return _unchanged(walk, attempt, known.raw_digest)
    if response.absent:
        walk.entry.status = FrontierStatus.absent
        return _delivered(walk, attempt, CandidateOutcome.absent)
    if response.redirected_out and known is not None:
        walk.entry.status = FrontierStatus.done
        return _delivered(walk, attempt, CandidateOutcome.redirected_out)
    return None


def _delivered(
    walk: LadderWalk, attempt: FetchAttempt, outcome: CandidateOutcome
) -> CandidateDelivered:
    """DisposeFetch's absent and redirected_out candidates: no content, no validators."""
    response = attempt.response
    run = walk.host.run
    return CandidateDelivered(
        run_id=run.id,
        mirror=run.target,
        requested_identity=walk.entry.identity,
        source_url=response.source_url,
        redirect_hops=response.redirect_hops,
        redirect_target=(
            response.redirect_location if outcome is CandidateOutcome.redirected_out else None
        ),
        depth=walk.entry.depth,
        outcome=outcome,
        tier=attempt.tier,
        sitemap_lastmod=walk.entry.sitemap_lastmod,
        raw_digest=response.raw_digest,
    )


def _unchanged(walk: LadderWalk, attempt: FetchAttempt, raw_digest: str) -> CandidateDelivered:
    """DisposeFetch's unchanged branches: the row settled, the unchanged candidate delivered."""
    entry = walk.entry
    run = walk.host.run
    response = attempt.response
    entry.status = FrontierStatus.unchanged
    return CandidateDelivered(
        run_id=run.id,
        mirror=run.target,
        requested_identity=entry.identity,
        source_url=response.source_url,
        redirect_hops=response.redirect_hops,
        depth=entry.depth,
        outcome=CandidateOutcome.unchanged,
        tier=attempt.tier,
        etag=response.etag,
        last_modified=response.last_modified,
        sitemap_lastmod=entry.sitemap_lastmod,
        raw_digest=raw_digest,
    )


def convert_fetched(run: Run, entry: FrontierEntry, walk: LadderWalk) -> CandidateDelivered | None:
    """Realises crawl.allium ConvertFetched: the candidate it delivers to the mirror.

    Calls the Fidelity operations with the mirror's profile, whichever it is, then adds
    the fetch flags.
    """
    attempt = walk.standing
    if walk.status is not WalkStatus.settled or attempt is None:
        return None
    if entry.status is not FrontierStatus.in_progress:
        return None
    profile = run.target.profile
    response = attempt.response
    extracted = extract(response.markup, response.source_url, profile)
    normalized = normalize(extracted, profile)
    body = restore(convert(normalized.fragment), normalized.islands)
    measured = measure(extracted, normalized, body)
    fetch_flags = set()
    if walk.render_needed and attempt.tier is Tier.http:
        fetch_flags.add(QualityFlag.render_needed)
    if attempt.verdict.kind is BlockKind.soft:
        fetch_flags.add(QualityFlag.soft_block_suspected)
    content = with_fetch_flags(
        converted_content(extracted, normalized, body, measured), fetch_flags
    )
    return CandidateDelivered(
        run_id=run.id,
        mirror=run.target,
        requested_identity=entry.identity,
        source_url=response.source_url,
        redirect_hops=response.redirect_hops,
        depth=entry.depth,
        outcome=CandidateOutcome.converted,
        content=content,
        tier=attempt.tier,
        etag=response.etag,
        last_modified=response.last_modified,
        sitemap_lastmod=entry.sitemap_lastmod,
        raw_digest=response.raw_digest,
    )


def settle_stored_entry(frontier: Frontier, candidate: PageCandidate) -> bool:
    """Realises crawl.allium SettleStoredEntry."""
    entry = frontier.entry(candidate.requested_identity)
    if entry is None or entry.status is not FrontierStatus.in_progress:
        return False
    entry.status = FrontierStatus.done
    return True


def settle_duplicate_entry(frontier: Frontier, duplicate: CandidateDuplicate) -> bool:
    """Realises crawl.allium SettleDuplicateEntry; False when its guard does not hold."""
    entry = frontier.entry(duplicate.candidate.requested_identity)
    if entry is None or entry.status is not FrontierStatus.in_progress:
        return False
    entry.status = FrontierStatus.duplicate
    return True


def fail_discarded_entry(
    run: Run | None, frontier: Frontier, discarded: CandidateDiscarded
) -> EntryFailed | None:
    """Realises crawl.allium FailDiscardedEntry; None when its guards do not hold.

    The discard's reason is the entry's error.
    """
    candidate = discarded.candidate
    entry = frontier.entry(candidate.requested_identity)
    if entry is None or entry.status is not FrontierStatus.in_progress:
        return None
    if run is None or run.target is not candidate.mirror or run.status is not RunStatus.running:
        return None
    return EntryFailed(run=run, entry=entry, error=discarded.reason, attempts=entry.attempts)


def entry_fails(failed: EntryFailed) -> UrlFailed | None:
    """Realises crawl.allium EntryFails; None when its guard does not hold."""
    entry = failed.entry
    if entry.status is not FrontierStatus.in_progress:
        return None
    entry.status = FrontierStatus.failed
    return UrlFailed(
        run=failed.run, url=entry.identity, error=failed.error, attempts=failed.attempts
    )


# --- Ending a run -------------------------------------------------------------------


def finish_run(run: Run, frontier: Frontier) -> bool:
    """Realises crawl.allium FinishRun: the unresolved snapshot, then RunEnding."""
    if run.status is not RunStatus.running:
        return False
    run.unresolved_urls = _unresolved_urls(run, frontier)
    return True


def interrupt_run(run: Run, frontier: Frontier) -> bool:
    """Realises crawl.allium InterruptRun; False when the run is not running.

    Every in-progress row returns to pending and the unresolved snapshot is taken; the
    caller then ends the run (EndRun), interrupted. No challenge waits in this slice.
    """
    if run.status is not RunStatus.running:
        return False
    for entry in frontier.in_progress_entries:
        entry.status = FrontierStatus.pending
    run.unresolved_urls = _unresolved_urls(run, frontier)
    return True


def end_run(run: Run, clock: Clock) -> bool:
    """Realises crawl.allium EndRun."""
    if run.status is not RunStatus.running:
        return False
    run.status = RunStatus.interrupted if run.interrupt_requested else RunStatus.finished
    run.finished_at = clock.now()
    return True


# --- Black boxes ----------------------------------------------------------------------


def status_text(response: SiteResponse) -> str:
    """crawl.allium status_text: the status code and its reason phrase."""
    try:
        return f"{response.status} {HTTPStatus(response.status).phrase}"
    except ValueError:
        return f"HTTP status {response.status}"


def classify_block(response: SiteResponse, median_text: float | None) -> BlockVerdict:
    """crawl.allium classify_block: none for an ok HTML answer in this slice.

    An answer the specification calls a block (a 401 or 403, a login wall) needs a
    verdict this slice does not give; soft verdicts need a text baseline, which no host
    has before the breaker slice feeds it.
    """
    del median_text  # No host has a text baseline in this slice.
    if response.status in _ACCESS_DENIED:
        raise NotInThisSlice(rule="classify_block")
    if response.ok and response.is_html and _has_password_input(response.markup):
        raise NotInThisSlice(rule="classify_block")
    return BlockVerdict(kind=BlockKind.none, signature="")


def _has_password_input(markup: str) -> bool:
    """An input whose type is password, however the attribute is quoted or cased."""
    soup = BeautifulSoup(markup, "lxml")
    return any(
        str(field.get("type", "")).strip().lower() == "password"
        for field in soup.find_all("input")
    )


def render_reason_of(response: SiteResponse) -> RenderReason | None:
    """crawl.allium render_reason_of: the four recognisers of AttemptTier's guidance.

    An SPA shell (an empty application root and almost no text), a noscript notice that
    asks for JavaScript, no main or article element, or thin text on a page over
    large_raw_html bytes; independent of render_mode.
    """
    if not response.is_html:
        return None
    soup = BeautifulSoup(response.markup, "lxml")
    body = soup.body or soup
    text = " ".join(body.get_text(" ").split())
    thin = len(text) < CONFIG.render_min_text_chars
    if thin and any(_empty_root(soup, name) for name in _SPA_ROOTS):
        return RenderReason.spa_shell
    if any("javascript" in notice.get_text().lower() for notice in soup.find_all("noscript")):
        return RenderReason.noscript_needs_js
    if body.find(("main", "article")) is None:
        return RenderReason.main_selector_absent
    if thin and response.size > CONFIG.large_raw_html:
        return RenderReason.thin_text
    return None


# --- The driver ---------------------------------------------------------------------


def run_crawl(
    request: RunRequest, persisted: Frontier | None, fetcher: Fetcher, clock: Timer
) -> CrawlResult:
    """Drive one run from RunRequested to RunEnded, then save the frontier and the run."""
    result = drive_run(request, persisted, fetcher, clock)
    save_run(result)
    return result


def drive_run(  # noqa: PLR0913  The RunRequested trigger, its seams and the root's sinks.
    request: RunRequest,
    persisted: Frontier | None,
    fetcher: Fetcher,
    clock: Timer,
    *,
    progress: Callable[[ProgressEvent], None] | None = None,
    on_backoff: Callable[[HostBackedOff], None] | None = None,
    on_failure: Callable[[Run, BaseException], None] | None = None,
) -> CrawlResult:
    """Drive one run from RunRequested to RunEnded, saving nothing.

    A caller that finalises the mirror saves the run with `save_run` only once the
    mirror is saved: a done row always has a page in the mirror (SettleStoredEntry).
    `progress` receives the start event once the run exists and a page event per row a
    fetch settles; `on_backoff` receives each HostBackedOff as it is raised. Once the run
    exists, an operator interrupt or any other error but NotInThisSlice goes to
    `on_failure` (the root's InterruptSync or RecordCrash); when that requested the
    interrupt, InterruptRun and EndRun end the run interrupted, else the error escapes.
    """
    run = start_run(request, clock)
    if run is None:
        raise NotInThisSlice(rule="StartRun")
    run.progress = progress
    run.on_backoff = on_backoff
    frontier = (
        create_frontier(run, persisted) if persisted is None else attach_frontier(run, persisted)
    )
    removals = len(run.target.removals)
    failed: list[UrlFailed] = []
    try:  # From the start event on, so a failing sink is recorded too (ReportOnEveryExit).
        if progress is not None:
            progress(ProgressEvent(event="start", host=None, until=None, url=None))
        _crawl(run, frontier, fetcher, clock, failed)
    except NotInThisSlice:
        raise
    except (KeyboardInterrupt, Exception) as error:
        if on_failure is not None:
            on_failure(run, error)
        if not run.interrupt_requested or not interrupt_run(run, frontier):
            raise
    end_run(run, clock)
    return CrawlResult(
        run=run,
        frontier=frontier,
        failed=tuple(failed),
        discovery_failed=tuple(run.discovery_failures),
        backed_off=tuple(run.backoffs),
        removed=tuple(run.target.removals[removals:]),
    )


def _crawl(
    run: Run, frontier: Frontier, fetcher: Fetcher, clock: Timer, failed: list[UrlFailed]
) -> None:
    """PrepareRun to FinishRun, collecting each UrlFailed into `failed` as it is raised."""
    prepare_run(run, frontier)
    discover(run, frontier, fetcher)
    drop_stale_observations(run, frontier)
    if dry_run(run):  # DryRun raises RunEnding at once: no batch, no FinishRun.
        return
    begin_crawl(run)
    while next_batch(run, frontier):
        batch = select_batch(run, frontier)
        if not batch:
            break
        for entry in batch:
            url_failed = _handle_entry(run, frontier, entry, fetcher, clock)
            if url_failed is not None:
                failed.append(url_failed)
    finish_run(run, frontier)


def save_run(result: CrawlResult) -> None:
    """Save the ended run's frontier to frontier.json and append it to runs.json."""
    save_frontier(result.frontier)
    record_run(result.run)


def record_run(run: Run) -> None:
    """Append the ended run to runs.json alone, so its id is never reused.

    For a sync that crashed after its run (rovo.allium RecordCrashAfterRun): its
    frontier is not saved, since its pages were not.
    """
    _append_run(run)


def _handle_entry(
    run: Run, frontier: Frontier, entry: FrontierEntry, fetcher: Fetcher, clock: Clock
) -> UrlFailed | None:
    """One row in progress: its host and origin, robots, the walk, disposal, storage.

    UrlFailed when the entry failed (its fetch, or the mirror discarded it), else None.
    """
    if open_host_for_entry(run, entry, fetcher) or read_robots_for_new_origin(run, entry, fetcher):
        if skip_robots_disallowed_on_new_host(run, entry):
            return None
    elif skip_robots_disallowed(run, entry) or not proceed_with_known_host(run, entry):
        return None
    walk = fetch_entry(run, entry, fetcher)
    if walk is None:  # EntryHostReady was raised, so FetchEntry's guards hold.
        return None
    _settle(walk, fetcher)
    if run.progress is not None:  # rovo.allium AnnouncePage: the walk has settled.
        run.progress(
            ProgressEvent(event="page", host=walk.host.name, until=None, url=walk.entry.identity)
        )
    disposed = dispose_fetch(walk)
    if isinstance(disposed, EntryFailed):
        return entry_fails(disposed)
    if isinstance(disposed, CandidateDelivered):
        # An unchanged, absent, redirected-out or non-HTML row is settled already. An unchanged
        # page raises no LinksFound (RecordUnchanged); its stored links are queued again.
        # A removal reaches CrawlResult.removed through the mirror's removals.
        candidate = admit_candidate(disposed)
        settled = settle_candidate(candidate, clock)
        if isinstance(settled, Page):
            refollow_unchanged_links(run, frontier, candidate, settled)
        return None
    # PageFetched (True); False when the row settled skipped_not_html or the guards failed.
    return _store(run, frontier, walk, clock) if disposed else None


def _settle(walk: LadderWalk, fetcher: Fetcher) -> None:
    """The walk's tries to settlement: each attempt ready, retried while it may be.

    HttpRetry while the attempt is retryable, then SettleWalk and FeedBreaker; the
    breaker acting, a host retired and an escalation are later slices' branches.
    """
    attempt = walk.attempts[-1]
    while True:
        prepare_attempt(attempt)
        if attempt.retires_host:
            raise NotInThisSlice(rule="RetireHostOnLongRetryAfter")
        if http_retry(attempt, fetcher) is None:
            break
        attempt = walk.attempts[-1]
    if not settle_walk(attempt):
        raise NotInThisSlice(rule="Escalate")
    feed_breaker(walk)
    if walk.host.breaker is not None and walk.host.breaker.should_act:
        raise NotInThisSlice(rule="BreakerTrips")


def _store(run: Run, frontier: Frontier, walk: LadderWalk, clock: Clock) -> UrlFailed | None:
    """Conversion and storage of a fetched page; UrlFailed when the mirror discards it."""
    delivered = convert_fetched(run, walk.entry, walk)
    if delivered is None:  # PageFetched was raised, so ConvertFetched's guards hold.
        return None
    candidate = admit_candidate(delivered)
    settled = settle_candidate(candidate, clock)
    if isinstance(settled, CandidateDuplicate):
        settle_duplicate_entry(frontier, settled)
        return None
    if isinstance(settled, Page):
        enqueue_page_links(run, frontier, links_found(candidate, settled))
    if not isinstance(settled, CandidateDiscarded):
        settle_stored_entry(frontier, candidate)
        return None
    entry_failed = fail_discarded_entry(run, frontier, settled)
    return None if entry_failed is None else entry_fails(entry_failed)


# --- Persistence --------------------------------------------------------------------


def load_frontier(mirror: Mirror) -> Frontier | None:
    """Read <out>/.rovo/frontier.json, or None before the first run."""
    path = state_path(mirror.out_dir, _FRONTIER)
    if not path.is_file():
        return None
    data = read_json(path)
    frontier = Frontier(mirror=mirror)
    frontier.entries = [_decode_entry(frontier, row) for row in data["entries"]]
    frontier.observed_urls = [_decode_observed(frontier, row) for row in data["observed_urls"]]
    sitemaps_path = state_path(mirror.out_dir, _SITEMAPS)
    if sitemaps_path.is_file():
        frontier.sitemap_snapshots = [
            _decode_snapshot(frontier, row) for row in read_json(sitemaps_path)["snapshots"]
        ]
    return frontier


def save_frontier(frontier: Frontier) -> None:
    """Write <out>/.rovo/frontier.json and <out>/.rovo/sitemaps.json atomically.

    Observed URLs and sitemap snapshots are kept sorted by URL; learned tiers are empty
    in this slice. The snapshots are saved in their own file (decision 0013).
    """
    write_json(
        state_path(frontier.mirror.out_dir, _FRONTIER),
        {
            "entries": [_encode_entry(entry) for entry in frontier.entries],
            "observed_urls": [
                _encode_observed(observed)
                for observed in sorted(frontier.observed_urls, key=lambda observed: observed.url)
            ],
            "tier_hints": [],
        },
    )
    write_json(
        state_path(frontier.mirror.out_dir, _SITEMAPS),
        {
            "snapshots": [
                _encode_snapshot(snapshot)
                for snapshot in sorted(frontier.sitemap_snapshots, key=lambda kept: kept.url)
            ]
        },
    )


def load_runs(out_dir: Path) -> tuple[RunRecord, ...]:
    """Read <out>/.rovo/runs.json, oldest first; empty before the first run."""
    path = state_path(out_dir, _RUNS)
    if not path.is_file():
        return ()
    return tuple(
        RunRecord(**{**row, "unresolved_urls": tuple(row["unresolved_urls"])})
        for row in read_json(path)["runs"]
    )


def next_run_id(out_dir: Path) -> int:
    """One more than the highest run id the mirror has seen, starting at 1."""
    return max((record.id for record in load_runs(out_dir)), default=0) + 1


# --- Helpers ------------------------------------------------------------------------


def _append_run(run: Run) -> None:
    record = {
        "id": run.id,
        "kind": run.kind.value,
        "mode": run.mode.value,
        "status": run.status.value,
        "scope_hash": run.scope_hash,
        "dry_run": run.dry_run,
        "started_at": timestamp(run.started_at),
        "finished_at": None if run.finished_at is None else timestamp(run.finished_at),
        "unresolved_urls": sorted(run.unresolved_urls),
    }
    rows = [
        vars(row) | {"unresolved_urls": list(row.unresolved_urls)}
        for row in load_runs(run.target.out_dir)
    ]
    write_json(state_path(run.target.out_dir, _RUNS), {"runs": [*rows, record]})


def _encode_entry(entry: FrontierEntry) -> dict[str, object]:
    return {
        "identity": entry.identity,
        "depth": entry.depth,
        "discovered_via": entry.discovered_via.value,
        "discovered_from": entry.discovered_from,
        "sitemap_lastmod": entry.sitemap_lastmod,
        "priority": entry.priority,
        "attempts": entry.attempts,
        "status": entry.status.value,
    }


def _decode_entry(frontier: Frontier, row: dict[str, Any]) -> FrontierEntry:
    return FrontierEntry(
        frontier=frontier,
        identity=row["identity"],
        depth=int(row["depth"]),
        discovered_via=DiscoverySource(row["discovered_via"]),
        discovered_from=row["discovered_from"],
        sitemap_lastmod=row["sitemap_lastmod"],
        priority=int(row["priority"]),
        attempts=int(row["attempts"]),
        status=FrontierStatus(row["status"]),
    )


def _encode_observed(observed: ObservedUrl) -> dict[str, object]:
    return {
        "url": observed.url,
        "sources": sorted(source.value for source in observed.sources),
        "last_seen_run": observed.last_seen_run,
    }


def _decode_observed(frontier: Frontier, row: dict[str, Any]) -> ObservedUrl:
    return ObservedUrl(
        frontier=frontier,
        url=str(row["url"]),
        sources=frozenset(DiscoverySource(source) for source in row["sources"]),
        last_seen_run=int(row["last_seen_run"]),
    )


def _encode_snapshot(snapshot: SitemapSnapshot) -> dict[str, object]:
    return {
        "url": snapshot.url,
        "etag": snapshot.etag,
        "last_modified": snapshot.last_modified,
        "is_index": snapshot.is_index,
        "entries": [{"loc": entry.loc, "lastmod": entry.lastmod} for entry in snapshot.entries],
        "last_requested_run": snapshot.last_requested_run,
    }


def _decode_snapshot(frontier: Frontier, row: dict[str, Any]) -> SitemapSnapshot:
    return SitemapSnapshot(
        frontier=frontier,
        url=str(row["url"]),
        etag=row["etag"],
        last_modified=row["last_modified"],
        is_index=bool(row["is_index"]),
        entries=tuple(
            SitemapEntry(loc=str(entry["loc"]), lastmod=entry["lastmod"])
            for entry in row["entries"]
        ),
        last_requested_run=int(row["last_requested_run"]),
    )


def _stale_pages(run: Run) -> frozenset[str]:
    """Every written page last seen more than max_age before the run started."""
    if run.max_age is None:
        return frozenset()
    return frozenset(
        page.identity
        for page in run.target.written_pages
        if run.started_at - page.last_seen > run.max_age
    )


def _pend(frontier: Frontier, identity: str, priority: int, lastmod: str | None) -> FrontierEntry:
    """Re-pend the identity's row, or create it as a recheck."""
    row = frontier.entry(identity)
    if row is not None:
        row.status = FrontierStatus.pending
        return row
    row = FrontierEntry(
        frontier=frontier,
        identity=identity,
        depth=0,
        discovered_via=DiscoverySource.recheck,
        discovered_from=None,
        sitemap_lastmod=lastmod,
        priority=priority,
        attempts=0,
        status=FrontierStatus.pending,
    )
    frontier.entries.append(row)
    return row


def _hop_host(run: Run, fetcher: Fetcher) -> Callable[[str], Host | None]:
    """A redirect hop's readiness: its host name, opened and its origin's robots.txt read.

    The hop's host is opened (OpenHost reads its robots.txt) or, on a known host, its
    origin's robots.txt is read when the run has not; None when robots.txt disallows it.
    """

    def ready(target: str) -> Host | None:
        name, origin = hostname_of(target), origin_of(target)
        host = run.host(name)
        if host is None:
            host = open_host(run, name, origin, fetcher)
        elif run.robots_policy(origin) is None:
            fetch_robots(run, name, origin, fetcher)
        return host if host is not None and robots_allows(run, target) else None

    return ready


def _host_origin(scope: CrawlScope, name: str) -> str:
    """The origin of the first seed on the host, else https on the bare name."""
    for seed in scope.seeds:
        if hostname_of(seed) == name:
            return origin_of(seed)
    return f"https://{name}"


def _selectable(run: Run, entry: FrontierEntry) -> bool:
    if run.is_owner_testing:
        return entry.identity in run.active_urls
    if run.targeted:
        return entry.identity in run.targets
    scope = run.target.scope
    return scope.within_bounds(entry.identity) or run.target.known_page(entry.identity) is not None


def _host_tripped(run: Run, entry: FrontierEntry) -> bool:
    host = run.host(entry.host_name)
    return host is not None and host.breaker_tripped


def _stop_on_budget(run: Run, pending: list[FrontierEntry]) -> list[FrontierEntry]:
    run.budget_stopped = True
    for entry in pending:
        entry.status = FrontierStatus.skipped_limit
    return []


def _next_pending(rows: list[FrontierEntry], count: int) -> list[FrontierEntry]:
    """Non-deferred first, then shallowest, then highest priority, then discovery order."""
    order = {id(entry): index for index, entry in enumerate(rows)}
    ranked = sorted(
        rows, key=lambda row: (row.is_deferred, row.depth, -row.priority, order[id(row)])
    )
    return ranked[:count]


def _choose_batch(
    lookahead: list[FrontierEntry], budget: int, targets: frozenset[str], concurrency: int
) -> list[FrontierEntry]:
    """At most `concurrency` rows: targets always, others while the page budget lasts."""
    chosen: list[FrontierEntry] = []
    for row in lookahead:
        if len(chosen) == concurrency:
            break
        if chosen and chosen[0].depth == 0 and row.depth != 0:
            continue
        if row.identity in targets:
            chosen.append(row)
        elif budget > 0:
            chosen.append(row)
            budget -= 1
    return chosen


def _origin_read(run: Run, entry: FrontierEntry) -> bool:
    """RobotsPolicy{run: run, origin: origin_of(entry.identity)} exists."""
    return run.robots_policy(origin_of(entry.identity)) is not None


def _entry_host(run: Run | None, entry: FrontierEntry) -> Host | None:
    return run.host(entry.host_name) if run is not None and _running_for(run, entry) else None


def _running_for(run: Run | None, entry: FrontierEntry) -> bool:
    """Run{target: entry.frontier.mirror, status: running} is this run, on a row in progress."""
    return (
        run is not None
        and run.status is RunStatus.running
        and run.target is entry.frontier.mirror
        and entry.status is FrontierStatus.in_progress
    )


def _starting_tier(run: Run) -> Tier:
    """Browser under render_mode = always; otherwise http, since no tier hint is learned."""
    return Tier.browser if run.render_mode is RenderMode.always else Tier.http


def _start_from(tiers: tuple[Tier, ...], first: Tier) -> tuple[Tier, ...]:
    return tiers[tiers.index(first) :] if first in tiers else tiers


def _next_tier(tiers: tuple[Tier, ...], tier: Tier) -> Tier | None:
    position = tiers.index(tier) + 1
    return tiers[position] if position < len(tiers) else None


def _validators(walk: LadderWalk) -> Validators | None:
    """The stored etag and last-modified of the known page, for a conditional http try."""
    known = walk.host.run.target.known_page(walk.entry.identity)
    if not walk.conditional or known is None:
        return None
    return Validators(etag=known.etag, last_modified=known.last_modified)


def _empty_root(soup: BeautifulSoup, element_id: str) -> bool:
    root = soup.find(id=element_id)
    return root is not None and not root.get_text().strip()


def _unresolved_urls(run: Run, frontier: Frontier) -> frozenset[str]:
    """FinishRun's guidance: scoped active URLs left unresolved, and low-confidence pages."""
    scope = run.target.scope
    rows = {
        entry.identity
        for entry in frontier.entries
        if entry.identity in run.active_urls
        and scope.within_bounds(entry.identity)
        and entry.status in _UNRESOLVED
    }
    pages = {
        page.identity
        for page in run.target.written_pages
        if page.last_stored_run == run.id
        and (page.quality.low_confidence or QualityFlag.soft_block_suspected in page.quality.flags)
    }
    preceding = run.preceding.unresolved_urls if run.preceding is not None else frozenset()
    resolved = {entry.identity for entry in frontier.entries if entry.status not in _UNRESOLVED}
    return frozenset(rows | pages | (preceding - resolved))
