"""One standard run, RunRequested to RunEnded (crawl.allium 596 to 1746).

Each function realises the rule its docstring names and returns without effect when
the rule's guards do not hold. Rules chain only where their docstrings say: Discover
opens hosts, OpenHost reads robots.txt, FetchEntry makes its first attempt. `run_crawl`
drives the rest in the specification's order, one frontier row after another, and
stops with NotInThisSlice where a later slice's branch would be taken.
"""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, overload
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

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
from rovo._convert.profiles import GENERIC
from rovo._crawl.fetch import Fetcher, Validators
from rovo._crawl.model import (
    CONFIG,
    BlockKind,
    BlockVerdict,
    Breaker,
    BreakerStatus,
    DiscoverySource,
    EntryFailed,
    FetchAttempt,
    Frontier,
    FrontierEntry,
    FrontierStatus,
    Host,
    LadderWalk,
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
    SiteResponse,
    UrlFailed,
    WalkStatus,
)
from rovo._mirror.intake import admit_candidate, links_found, settle_candidate
from rovo._mirror.model import (
    CandidateDelivered,
    CandidateDiscarded,
    CandidateOutcome,
    CrawlScope,
    LinksFound,
    Mirror,
    Page,
    PageCandidate,
    Tier,
)
from rovo._mirror.state import Clock, read_json, state_path, timestamp, write_json
from rovo._mirror.urls import hostname_of, origin_of
from rovo._unfinished import NotInThisSlice

USER_AGENT = "rovo"
_FRONTIER = "frontier.json"
_RUNS = "runs.json"
_ACCESS_DENIED = frozenset({401, 403})
_REDIRECTS = range(300, 400)
_SPA_ROOTS = ("root", "app", "__next", "__nuxt")
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
    """What one run leaves: the ended run and its frontier."""

    run: Run
    frontier: Frontier
    failed: tuple[UrlFailed, ...] = ()


# --- Starting a run -------------------------------------------------------------------


def start_run(request: RunRequest, clock: Clock) -> Run | None:
    """Realises crawl.allium StartRun."""
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
        targets=request.targets,
        forced_refetch=frozenset(),
        active_urls=frozenset(),
        unresolved_urls=frozenset(),
        error=None,
        interrupt_requested=False,
        crawling=False,
        budget_stopped=False,
        bytes_fetched=0,
        fetch_attempts=0,
        started_at=clock.now(),
        status=RunStatus.running,
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
    """Realises crawl.allium PrepareRun (the standard full-run branches).

    Re-pends the row of every written page the scope admits, returns in-progress rows to
    pending, rechecks removed pages last and retries the failed, blocked and skipped rows
    the scope admits.
    """
    if run.status is not RunStatus.running or frontier is None:
        return False
    if run.is_owner_testing or run.targets:
        raise NotInThisSlice(rule="PrepareRun")
    mirror = run.target
    run.forced_refetch = _stale_pages(run) if run.kind is RunKind.update else frozenset()
    run.active_urls = frozenset(entry.identity for entry in frontier.entries)
    for entry in frontier.in_progress_entries:
        entry.status = FrontierStatus.pending
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
    return True


# --- Discovery and robots.txt -------------------------------------------------------


def discover(run: Run, frontier: Frontier, fetcher: Fetcher) -> bool:
    """Realises crawl.allium Discover: the seeds are enqueued and every allowed host opened.

    Hosts are opened in sorted order. Sitemaps and llms.txt are the discovery slice's.
    """
    if run.status is not RunStatus.running:
        return False
    if run.is_owner_testing or run.targeted:
        raise NotInThisSlice(rule="Discover")
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
    return True


def open_host(run: Run, name: str, origin: str, fetcher: Fetcher) -> Host | None:
    """Realises crawl.allium OpenHost, then its RobotsRequested."""
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
    fetch_robots(run, name, fetcher)
    return host


def fetch_robots(run: Run, name: str, fetcher: Fetcher) -> SiteResponse | None:
    """Realises crawl.allium FetchRobots, then its RobotsAnswered.

    One http request, no retry and no redirect followed in this slice; a 3xx answer, a
    refusal and an unreachable robots.txt are later slices' branches.
    """
    host = run.host(name)
    if run.status is not RunStatus.running or host is None:
        return None
    if run.robots_policy(host.origin) is not None:
        return None
    response = fetcher.fetch(f"{host.origin}/robots.txt")
    run.bytes_fetched += response.size
    if response.status in _REDIRECTS:
        raise NotInThisSlice(rule="FetchRobots")
    adopted = adopt_robots_rules(run, host, response)
    if adopted is None and allow_all_when_robots_absent(run, host, response) is None:
        raise NotInThisSlice(rule="DenyAllWhenRobotsRefused")
    return response


def adopt_robots_rules(run: Run, host: Host, response: SiteResponse) -> RobotsPolicy | None:
    """Realises crawl.allium AdoptRobotsRules (the host-rate effect deferred).

    The file is parsed with urllib.robotparser for the user agent rovo; pacing the host
    by its Crawl-delay is the politeness slice's.
    """
    if not response.ok:
        return None
    rules = RobotFileParser()
    rules.parse(response.markup.splitlines())
    delay = rules.crawl_delay(USER_AGENT)
    policy = RobotsPolicy(
        run=run,
        origin=host.origin,
        stance=RobotsStance.rules,
        crawl_delay=None if delay is None else timedelta(seconds=float(delay)),
        declared_sitemaps=tuple(rules.site_maps() or ()),
        problem=None,
        rules=rules,
    )
    run.robots_policies.append(policy)
    return policy


def allow_all_when_robots_absent(
    run: Run, host: Host, response: SiteResponse
) -> RobotsPolicy | None:
    """Realises crawl.allium AllowAllWhenRobotsAbsent."""
    if response.ok or response.error is not None:
        return None
    if response.access_refused or response.server_error:
        return None
    policy = RobotsPolicy(
        run=run,
        origin=host.origin,
        stance=RobotsStance.allow_all,
        crawl_delay=None,
        declared_sitemaps=(),
        problem=None,
    )
    run.robots_policies.append(policy)
    return policy


def robots_allows(run: Run, url: str) -> bool:
    """crawl.allium robots_allows, for the user agent rovo.

    True under robots = ignore and for a host whose stance is allow_all, false under
    disallow_all or before the host's robots.txt is known, else the parsed rules' answer.
    """
    if run.policy.robots is RobotsMode.ignore:
        return True
    host = run.host(hostname_of(url))
    policy = None if host is None else run.robots_policy(host.origin)
    if policy is None or policy.stance is RobotsStance.disallow_all:
        return False
    if policy.rules is None:
        return policy.stance is RobotsStance.allow_all
    return policy.rules.can_fetch(USER_AGENT, url)


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
    """Realises crawl.allium Enqueue: dedup by identity, never changing a row's status."""
    newly_admitted = run.is_owner_testing and url not in run.active_urls
    run.active_urls = run.active_urls | {url}
    existing = frontier.entry(url)
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
    if newly_admitted:
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


def drop_stale_observations(run: Run, frontier: Frontier) -> bool:
    """Realises crawl.allium DropStaleObservations; nothing is observed in this slice."""
    if run.status is not RunStatus.running:
        return False
    del frontier  # Sitemaps and llms.txt, which observe URLs, are the discovery slice's.
    return True


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
    if robots_allows(run, entry.identity):
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
    return robots_allows(run, entry.identity)


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
    """Realises crawl.allium AttemptTier (the http tier, one try)."""
    run = walk.host.run
    if walk.status is not WalkStatus.walking or run.status is not RunStatus.running:
        return None
    if tier is not Tier.http:
        raise NotInThisSlice(rule="AttemptTier")
    response = fetcher.fetch(walk.entry.identity, validators=_validators(walk))
    if try_ > 1 or tier is not walk.tiers[0]:
        run.fetch_attempts += 1
    run.bytes_fetched += response.size
    host = walk.host
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
    return attempt


def prepare_attempt(attempt: FetchAttempt) -> bool:
    """Realises crawl.allium PrepareAttempt: True when it raised AttemptReady.

    A challenge is offered only in an owner-testing run, so a standard run's attempt is
    always ready.
    """
    walk = attempt.walk
    return walk.status is WalkStatus.walking and walk.host.run.status is RunStatus.running


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


# --- What a settled fetch becomes ---------------------------------------------------


def dispose_fetch(walk: LadderWalk) -> bool:
    """Realises crawl.allium DisposeFetch, the ok-HTML branch: True when PageFetched.

    An ok, unblocked HTML answer with no redirect for a URL with no known page counts as
    fetched for its host and raises PageFetched. Every other branch is a later slice's.
    """
    attempt = walk.standing
    if walk.status is not WalkStatus.settled or attempt is None:
        return False
    if walk.entry.status is not FrontierStatus.in_progress:
        return False
    response = attempt.response
    known = walk.host.run.target.known_page(walk.entry.identity)
    if (
        attempt.failed_outright
        or not response.ok
        or attempt.verdict.kind is not BlockKind.none
        or response.redirect_hops
        or response.unfollowed_redirect
        or not response.is_html
        or known is not None
    ):
        raise NotInThisSlice(rule="DisposeFetch")
    walk.host.fetched += 1
    return True


def convert_fetched(run: Run, entry: FrontierEntry, walk: LadderWalk) -> CandidateDelivered | None:
    """Realises crawl.allium ConvertFetched: the candidate it delivers to the mirror.

    Calls the Fidelity operations with the mirror's profile, then adds the fetch flags.
    """
    attempt = walk.standing
    if walk.status is not WalkStatus.settled or attempt is None:
        return None
    if entry.status is not FrontierStatus.in_progress:
        return None
    profile = run.target.profile
    if profile != GENERIC:
        raise NotInThisSlice(rule="ConvertFetched")
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


def end_run(run: Run, clock: Clock) -> bool:
    """Realises crawl.allium EndRun."""
    if run.status is not RunStatus.running:
        return False
    run.status = RunStatus.interrupted if run.interrupt_requested else RunStatus.finished
    run.finished_at = clock.now()
    return True


# --- Black boxes ----------------------------------------------------------------------


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
    request: RunRequest, persisted: Frontier | None, fetcher: Fetcher, clock: Clock
) -> CrawlResult:
    """Drive one run from RunRequested to RunEnded, then save the frontier and the run."""
    result = drive_run(request, persisted, fetcher, clock)
    save_run(result)
    return result


def drive_run(
    request: RunRequest, persisted: Frontier | None, fetcher: Fetcher, clock: Clock
) -> CrawlResult:
    """Drive one run from RunRequested to RunEnded, saving nothing.

    A caller that finalises the mirror saves the run with `save_run` only once the
    mirror is saved: a done row always has a page in the mirror (SettleStoredEntry).
    """
    run = start_run(request, clock)
    if run is None:
        raise NotInThisSlice(rule="StartRun")
    frontier = (
        create_frontier(run, persisted) if persisted is None else attach_frontier(run, persisted)
    )
    prepare_run(run, frontier)
    failed: list[UrlFailed] = []
    discover(run, frontier, fetcher)
    drop_stale_observations(run, frontier)
    if not begin_crawl(run):
        raise NotInThisSlice(rule="DryRun")
    while next_batch(run, frontier):
        batch = select_batch(run, frontier)
        if not batch:
            break
        handled = [_handle_entry(run, frontier, entry, fetcher, clock) for entry in batch]
        failed.extend(url_failed for url_failed in handled if url_failed is not None)
    finish_run(run, frontier)
    end_run(run, clock)
    return CrawlResult(run=run, frontier=frontier, failed=tuple(failed))


def save_run(result: CrawlResult) -> None:
    """Save the ended run's frontier to frontier.json and append it to runs.json."""
    save_frontier(result.frontier)
    _append_run(result.run)


def _handle_entry(
    run: Run, frontier: Frontier, entry: FrontierEntry, fetcher: Fetcher, clock: Clock
) -> UrlFailed | None:
    """One row in progress: its host, robots, the walk, disposal, conversion, storage.

    UrlFailed when the mirror discarded the candidate and the entry failed, else None.
    """
    if open_host_for_entry(run, entry, fetcher):
        if skip_robots_disallowed_on_new_host(run, entry):
            return None
    elif skip_robots_disallowed(run, entry) or not proceed_with_known_host(run, entry):
        return None
    walk = fetch_entry(run, entry, fetcher)
    if walk is None:  # EntryHostReady was raised, so FetchEntry's guards hold.
        return None
    attempt = walk.attempts[-1]
    prepare_attempt(attempt)
    if attempt.retires_host:
        raise NotInThisSlice(rule="RetireHostOnLongRetryAfter")
    if attempt.retryable:
        raise NotInThisSlice(rule="HttpRetry")
    if not settle_walk(attempt):
        raise NotInThisSlice(rule="Escalate")
    dispose_fetch(walk)
    return _store(run, frontier, walk, clock)


def _store(run: Run, frontier: Frontier, walk: LadderWalk, clock: Clock) -> UrlFailed | None:
    """Conversion and storage of a fetched page; UrlFailed when the mirror discards it."""
    delivered = convert_fetched(run, walk.entry, walk)
    if delivered is None:  # PageFetched was raised, so ConvertFetched's guards hold.
        return None
    candidate = admit_candidate(delivered)
    settled = settle_candidate(candidate, clock)
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
    return frontier


def save_frontier(frontier: Frontier) -> None:
    """Write <out>/.rovo/frontier.json atomically.

    Observed URLs and learned tiers are empty in this slice; sitemap snapshots get their
    own file with the discovery slice (decision 0013).
    """
    write_json(
        state_path(frontier.mirror.out_dir, _FRONTIER),
        {
            "entries": [_encode_entry(entry) for entry in frontier.entries],
            "observed_urls": [],
            "tier_hints": [],
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
