"""crawl.allium's obligations: one standard run over a FakeFetcher, and the HttpxFetcher.

Each test is named after the obligation id `just plan-spec crawl` emits, dots and
hyphens as underscores, and its docstring quotes the obligation. A `rule_failure` test
makes exactly one `requires` clause false and shows that the rule does not fire: the
function returns None or False, no request is made and nothing changes. Rule functions
chain only as their docstrings say (Discover opens hosts, OpenHost reads robots.txt,
FetchEntry makes its first attempt); the run's driver, `run_crawl`, does the rest.
"""

import dataclasses
import importlib.metadata
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from fakes import (
    START,
    FakeFetcher,
    FixedClock,
    ScriptedFetcher,
    StampingFetcher,
    SteppingTimer,
    fixture_site,
    html_response,
    not_found,
    text_response,
    xml_response,
)
from rovo._convert import profiles
from rovo._convert.model import QualityFlag
from rovo._crawl import model, sitemaps
from rovo._crawl import run as run_module
from rovo._crawl.fetch import HttpxFetcher
from rovo._crawl.model import (
    BlockKind,
    BlockVerdict,
    BreakerStatus,
    CrawlPolicy,
    DiscoveryFailed,
    DiscoveryProblem,
    DiscoverySource,
    EntryFailed,
    FetchAttempt,
    Frontier,
    FrontierEntry,
    FrontierStatus,
    Host,
    LadderWalk,
    ObservedUrl,
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
    StealthMode,
    WalkStatus,
    standard_policy,
)
from rovo._crawl.run import (
    CrawlResult,
    accept_fresh_sitemap,
    adopt_robots_rules,
    allow_all_when_robots_absent,
    attach_frontier,
    attempt_tier,
    begin_crawl,
    convert_fetched,
    count_retry_after,
    create_frontier,
    deny_all_when_robots_refused,
    deny_all_when_robots_unreachable,
    discover,
    dispose_fetch,
    drop_stale_observations,
    dry_run,
    dry_run_listing,
    end_run,
    enqueue,
    enqueue_page_links,
    entry_fails,
    expand_sitemap_entries,
    feed_breaker,
    fetch_entry,
    fetch_robots,
    fetch_sitemap,
    finish_run,
    http_retry,
    load_frontier,
    load_runs,
    next_batch,
    next_run_id,
    open_host,
    open_host_for_entry,
    prepare_attempt,
    prepare_run,
    proceed_with_known_host,
    queue_sitemaps,
    read_llms_txt,
    read_robots_before_sitemap,
    read_robots_for_new_origin,
    record_observation,
    reject_non_sitemap,
    render_reason_of,
    retires_host_on_long_crawl_delay,
    robots_allows,
    run_crawl,
    save_frontier,
    select_batch,
    settle_stored_entry,
    settle_walk,
    skip_robots_disallowed,
    skip_robots_disallowed_on_new_host,
    skip_unavailable_sitemap,
    start_run,
)
from rovo._mirror.intake import admit_candidate, take_candidate
from rovo._mirror.model import (
    CandidateOutcome,
    CrawlScope,
    LinksFound,
    Mirror,
    Operator,
    Tier,
)
from rovo._mirror.state import save_mirror
from rovo._mirror.urls import hostname_of
from spec_values import spec_duration, spec_enum, spec_float, spec_int

SITE = "http://docs.example"
HOST = "docs.example"
SEED = f"{SITE}/guide/start.html"
ROBOTS = f"{SITE}/robots.txt"
OTHER = f"{SITE}/guide/other.html"
OFF_SITE = "http://elsewhere.example/guide/page.html"
SITES = Path(__file__).resolve().parent / "fixtures" / "sites"
PAGE = (SITES / "one-page" / "guide" / "start.html").read_text(encoding="utf-8")
DISALLOW_GUIDE = (SITES / "robots-disallow" / "robots.txt").read_text(encoding="utf-8")
RULES = f"User-agent: *\nDisallow: /private/\nCrawl-delay: 2\nSitemap: {SITE}/sitemap.xml\n"
CRAWL_DELAY = timedelta(seconds=2)
# A second origin of the host docs.example: another port, so its own robots.txt (T12).
PORTED = "http://docs.example:8080"
PORTED_ROBOTS = f"{PORTED}/robots.txt"
PORTED_PAGE = f"{PORTED}/guide/other.html"
ZERO_DELAY = "User-agent: *\nCrawl-delay: 0\n"
HALF_DELAY = "User-agent: *\nCrawl-delay: 0.5\n"
# Crawl-delays past retry_after_cap as written (crawl.allium robots_crawl_delay_exceeds and
# AdoptRobotsRules' guidance, 837 to 843 at fa096c4): too large for a timedelta, an
# instant after it or a float (1e309, 1e400), past the cap by less than a float can tell
# (one sub-ULP step, built from the configured cap), or with an exponent past Decimal's
# own limit (reviews T12-2-r2 C1/B1 and T12-3-r2 C1/B1).
CAP_SECONDS = Decimal(str(model.CONFIG.retry_after_cap.total_seconds()))
PAST_CAP_DELAYS = (
    f"{model.CONFIG.retry_after_cap.total_seconds() + 1:g}",
    "99999999999",
    "1e12",
    "1e15",
    "1e309",
    "1e400",
    str(CAP_SECONDS + Decimal("1e-15")),
    "1e1000000000000000000",
    "1e9999999999999999999",
)
PAST_CAP_IDS = (
    "cap-plus-one",
    "99999999999",
    "1e12",
    "1e15",
    "1e309",
    "1e400",
    "cap-plus-sub-ulp",
    "1e1000000000000000000",
    "1e9999999999999999999",
)
# Crawl-delays that are not a finite, non-negative number in protego's (float's) grammar:
# robots_crawl_delay is null and the host is not retired (review T12-3-r2 C2).
NULL_DELAYS = ("inf", "nan", "-5", "abc", "_121", "121_", "1__21", "-1e9999999999999999999")
# A number too small for Decimal's exponent is still a number: no delay (review T12-3-r2).
TINY_DELAY = "1e-9999999999999999999"
# Directive spellings protego reads as Crawl-delay 5: a space for the colon, "crawl delay",
# a trailing comment, no space after the colon.
SPELLED_DELAYS = (
    "Crawl-delay 5",
    "Crawl delay 5",
    "crawl-delay 5 # c",
    "Crawl delay: 5",
    "crawl-delay:5",
)
SPELLED_DELAY = timedelta(seconds=5)
NOSCRIPT_PAGE = """<!doctype html>
<html lang="en">
    <head><title>Console</title></head>
    <body>
        <main>
            <h1>Console</h1>
            <p>The console shows the state of every mirror the product keeps up to date.</p>
            <noscript>You need to enable JavaScript to run this app.</noscript>
        </main>
    </body>
</html>
"""
SERVER_ERROR = 500
BAD_GATEWAY = 502
SERVICE_UNAVAILABLE = 503
TOO_MANY = 429
NOT_FOUND = 404
FORBIDDEN = 403
MOVED = 301
SECOND_RUN = 2
TWO_TRIES = 2
THIRD_RUN = 3
SITEMAP = f"{SITE}/sitemap.xml"
SITEMAP_INDEX = f"{SITE}/sitemap_index.xml"
LLMS_TXT = f"{SITE}/llms.txt"
# T13: the speculative probes a host whose robots.txt allows them gets after its robots.txt, in
# order (QueueSitemaps, ReadLlmsTxt; tickets/T13-discovery.md Facts).
PROBES = [SITEMAP, SITEMAP_INDEX, LLMS_TXT]
DISCOVERY = [ROBOTS, *PROBES]
# The links fixture site served from SITE (tests/fixtures/sites/links, T10).
B_PAGE = f"{SITE}/guide/b.html"
C_PAGE = f"{SITE}/guide/deep/c.html"
D_PAGE = f"{SITE}/guide/deep/d.html"
SECRET_PAGE = f"{SITE}/guide/private/secret.html"
OUTSIDE_PAGE = f"{SITE}/outside/x.html"


def new_mirror(out_dir: Path, **changes: object) -> Mirror:
    """An initialised mirror of the fixture site, its manifest on disk."""
    crawl_scope = CrawlScope(
        root_url=f"{SITE}/guide/",
        start_urls=(SEED,),
        allowed_hosts=frozenset({HOST}),
        path_prefixes=("/guide/",),
        include=(),
        exclude=(),
        max_depth=10,
        locale=None,
        meaningful_query_params=(),
        locale_codes=frozenset(),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    mirror = Mirror(
        out_dir=out_dir,
        scope=dataclasses.replace(crawl_scope, **changes),  # type: ignore[arg-type]  # Test overrides by name.
        profile=profiles.GENERIC,
        processing_signature="signature-1",
    )
    save_mirror(mirror)
    return mirror


def request(  # noqa: PLR0913  One keyword per RunRequested field a test varies.
    mirror: Mirror,
    *,
    run_id: int = 1,
    kind: RunKind = RunKind.initial,
    mode: RunMode = RunMode.standard,
    render_mode: RenderMode = RenderMode.never,
    stealth_mode: StealthMode = StealthMode.off,
    policy: CrawlPolicy | None = None,
) -> RunRequest:
    """The RunRequested trigger StartSync raises for a standard full run."""
    return RunRequest(
        operator=Operator(),
        mirror=mirror,
        id=run_id,
        kind=kind,
        mode=mode,
        scope_hash="scope-1",
        owned_hosts=frozenset(),
        policy=policy or standard_policy(),
        dry_run=False,
        interactive=False,
        render_mode=render_mode,
        stealth_mode=stealth_mode,
        targets=frozenset(),
    )


def site(*, robots: SiteResponse | None = None, page: str = PAGE) -> FakeFetcher:
    """The fixture site: the seed page, and robots.txt when given (else a 404)."""
    responses = {SEED: html_response(SEED, page)}
    if robots is not None:
        responses[ROBOTS] = robots
    return FakeFetcher(responses)


def started(out_dir: Path, **changes: object) -> tuple[Run, Frontier]:
    """A running run with a new frontier: StartRun then CreateFrontier."""
    run = start_run(request(new_mirror(out_dir), **changes), FixedClock())  # type: ignore[arg-type]  # Test overrides by name.
    assert run is not None
    frontier = create_frontier(run, None)
    assert frontier is not None
    return run, frontier


def crawling(out_dir: Path, fetcher: FakeFetcher) -> tuple[Run, Frontier]:
    """A run through discovery: PrepareRun, Discover, DropStaleObservations, BeginCrawl."""
    run, frontier = started(out_dir)
    assert prepare_run(run, frontier)
    assert discover(run, frontier, fetcher)
    assert drop_stale_observations(run, frontier)
    assert begin_crawl(run)
    return run, frontier


def selected(out_dir: Path, fetcher: FakeFetcher) -> tuple[Run, Frontier, FrontierEntry]:
    """A crawling run whose seed row is in progress."""
    run, frontier = crawling(out_dir, fetcher)
    batch = select_batch(run, frontier)
    assert batch is not None
    (entry,) = batch
    return run, frontier, entry


def crawling_without_hosts(out_dir: Path) -> tuple[Run, Frontier, FrontierEntry]:
    """A crawling run whose seed row is in progress on a host no rule has opened."""
    run, frontier = started(out_dir)
    entry = enqueue(
        run,
        frontier,
        SEED,
        depth=0,
        via=DiscoverySource.start,
        priority=model.CONFIG.start_priority,
    )
    assert begin_crawl(run)
    assert select_batch(run, frontier) == [entry]
    return run, frontier, entry


def walked(out_dir: Path, fetcher: FakeFetcher) -> tuple[Run, Frontier, LadderWalk]:
    """The seed fetched once: FetchEntry and its first AttemptTier."""
    run, frontier, entry = selected(out_dir, fetcher)
    walk = fetch_entry(run, entry, fetcher)
    assert walk is not None
    return run, frontier, walk


def settled(out_dir: Path, fetcher: FakeFetcher) -> tuple[Run, Frontier, LadderWalk]:
    """The seed's walk settled: PrepareAttempt then SettleWalk."""
    run, frontier, walk = walked(out_dir, fetcher)
    (attempt,) = walk.attempts
    assert prepare_attempt(attempt)
    assert settle_walk(attempt)
    return run, frontier, walk


def crawl_once(out_dir: Path, fetcher: FakeFetcher, *, run_id: int = 1) -> CrawlResult:
    """One whole standard run through the driver."""
    mirror = new_mirror(out_dir)
    return run_crawl(request(mirror, run_id=run_id), load_frontier(mirror), fetcher, FixedClock())


def walk_with(
    run: Run, frontier: Frontier, tiers: tuple[Tier, ...], response: SiteResponse
) -> FetchAttempt:
    """A walking walk over `tiers` with one unblocked http attempt answering `response`."""
    entry = enqueue(run, frontier, SEED, depth=0, via=DiscoverySource.start, priority=0)
    entry.status = FrontierStatus.in_progress
    host = run.host(HOST)
    assert host is not None
    walk = LadderWalk(
        entry=entry,
        host=host,
        tiers=tiers,
        conditional=False,
        escalated=False,
        challenge_offered=False,
        status=WalkStatus.walking,
    )
    attempt = FetchAttempt(
        walk=walk,
        tier=Tier.http,
        try_=1,
        response=response,
        verdict=BlockVerdict(kind=BlockKind.none, signature=""),
        render_reason=render_reason_of(response),
    )
    walk.attempts.append(attempt)
    return attempt


def links_site() -> FakeFetcher:
    """The links fixture site, robots.txt included, served from SITE."""
    return FakeFetcher(fixture_site("links", f"{SITE}/"))


def stored_seed(out_dir: Path, fetcher: FakeFetcher) -> tuple[Run, Frontier, LinksFound]:
    """The seed fetched, converted, stored and settled; the LinksFound its storing raises."""
    run, frontier, walk = settled(out_dir, fetcher)
    assert dispose_fetch(walk)
    delivered = convert_fetched(run, walk.entry, walk)
    assert delivered is not None
    assert delivered.content is not None
    candidate = admit_candidate(delivered)
    page = take_candidate(candidate, FixedClock())
    assert page is not None
    assert settle_stored_entry(frontier, candidate)
    found = LinksFound(
        candidate=candidate,
        page=page,
        depth=walk.entry.depth,
        targets=delivered.content.link_targets,
        navigation_targets=delivered.content.navigation_targets,
    )
    return run, frontier, found


def assert_fields(value: object, names: tuple[str, ...]) -> None:
    """Every named field or derived value is readable on `value`."""
    for name in names:
        assert hasattr(value, name), name
        getattr(value, name)


# --- Starting a run -----------------------------------------------------------------


def test_rule_success_StartRun(tmp_path: Path) -> None:
    """Verify rule StartRun succeeds when all preconditions are met."""
    run = start_run(request(new_mirror(tmp_path)), FixedClock())
    assert isinstance(run, Run)
    assert run.status is RunStatus.running


def test_rule_failure_StartRun_1(tmp_path: Path) -> None:
    """Verify rule StartRun is rejected when requires clause fails.

    requires: mode = standard or (baseline != null and preceding != null and owned hosts).
    """
    owner = request(new_mirror(tmp_path), mode=RunMode.owner_testing)
    assert start_run(owner, FixedClock()) is None


def test_rule_entity_creation_StartRun_1(tmp_path: Path) -> None:
    """Verify entity creation in rule StartRun ensures clause produces the specified fields."""
    mirror = new_mirror(tmp_path)
    trigger = request(mirror)
    run = start_run(trigger, FixedClock())
    assert run is not None
    assert run.target is mirror
    assert run.operator == trigger.operator
    assert run.id == 1
    assert run.kind is RunKind.initial
    assert run.mode is RunMode.standard
    assert run.baseline is None
    assert run.preceding is None
    assert run.scope_hash == "scope-1"
    assert run.owned_hosts == frozenset()
    assert run.requested_owner_test is None
    assert run.policy == trigger.policy
    assert run.dry_run is False
    assert run.interactive is False
    assert run.render_mode is RenderMode.never
    assert run.stealth_mode is StealthMode.off
    assert run.max_age is None
    assert run.targets == frozenset()
    assert run.forced_refetch == frozenset()
    assert run.active_urls == frozenset()
    assert run.unresolved_urls == frozenset()
    assert run.error is None
    assert run.interrupt_requested is False
    assert run.crawling is False
    assert run.budget_stopped is False
    assert run.bytes_fetched == 0
    assert run.fetch_attempts == 0
    assert run.started_at == START
    assert run.status is RunStatus.running
    assert run.finished_at is None


def test_rule_success_CreateFrontier(tmp_path: Path) -> None:
    """Verify rule CreateFrontier succeeds when all preconditions are met."""
    run = start_run(request(new_mirror(tmp_path)), FixedClock())
    assert run is not None
    frontier = create_frontier(run, None)
    assert isinstance(frontier, Frontier)


def test_rule_failure_CreateFrontier_1(tmp_path: Path) -> None:
    """Verify rule CreateFrontier is rejected when requires clause fails.

    requires: not exists Frontier{mirror: run.target}.
    """
    run, frontier = started(tmp_path)
    assert create_frontier(run, frontier) is None


def test_rule_entity_creation_CreateFrontier_1(tmp_path: Path) -> None:
    """Verify entity creation in rule CreateFrontier ensures clause produces the specified fields."""  # noqa: E501  The obligation's description, quoted.
    run, frontier = started(tmp_path)
    assert frontier.mirror is run.target
    assert frontier.entries == []
    assert frontier.observed_urls == []


def test_rule_success_AttachFrontier(tmp_path: Path) -> None:
    """Verify rule AttachFrontier succeeds when all preconditions are met."""
    run, frontier = started(tmp_path)
    assert attach_frontier(run, frontier) is frontier


def test_rule_failure_AttachFrontier_1(tmp_path: Path) -> None:
    """Verify rule AttachFrontier is rejected when requires clause fails.

    requires: exists Frontier{mirror: run.target}.
    """
    run = start_run(request(new_mirror(tmp_path)), FixedClock())
    assert run is not None
    assert attach_frontier(run, None) is None


def test_rule_success_PrepareRun(tmp_path: Path) -> None:
    """Verify rule PrepareRun succeeds when all preconditions are met.

    A full standard update run re-pends the written page's row, returns in-progress rows
    to pending and retries the failed rows the scope admits; a row outside it stays.
    """
    first = crawl_once(tmp_path, site())
    frontier = first.frontier
    stray = enqueue(first.run, frontier, OTHER, depth=1, via=DiscoverySource.link, priority=0)
    stray.status = FrontierStatus.in_progress
    failed = enqueue(
        first.run,
        frontier,
        f"{SITE}/guide/failed.html",
        depth=1,
        via=DiscoverySource.link,
        priority=0,
    )
    failed.status = FrontierStatus.failed
    outside = enqueue(first.run, frontier, OFF_SITE, depth=1, via=DiscoverySource.link, priority=0)
    outside.status = FrontierStatus.failed

    second = start_run(
        request(first.run.target, run_id=SECOND_RUN, kind=RunKind.update), FixedClock()
    )
    assert second is not None
    assert attach_frontier(second, frontier) is frontier
    assert prepare_run(second, frontier)
    seed_row = frontier.entry(SEED)
    assert seed_row is not None
    assert seed_row.status is FrontierStatus.pending
    assert stray.status is FrontierStatus.pending
    assert failed.status is FrontierStatus.pending
    assert outside.status is FrontierStatus.failed
    assert second.forced_refetch == frozenset()
    assert second.active_urls == frozenset(entry.identity for entry in frontier.entries)


def test_rule_failure_PrepareRun_1(tmp_path: Path) -> None:
    """Verify rule PrepareRun is rejected when requires clause fails.

    requires: run.status = running.
    """
    run, frontier = started(tmp_path)
    row = enqueue(run, frontier, SEED, depth=0, via=DiscoverySource.start, priority=0)
    row.status = FrontierStatus.in_progress
    run.status = RunStatus.finished
    assert not prepare_run(run, frontier)
    assert row.status is FrontierStatus.in_progress


def test_rule_failure_PrepareRun_2(tmp_path: Path) -> None:
    """Verify rule PrepareRun is rejected when requires clause fails.

    requires: exists frontier.
    """
    run = start_run(request(new_mirror(tmp_path)), FixedClock())
    assert run is not None
    assert not prepare_run(run, None)
    assert run.active_urls == frozenset()


# --- Discovery ---------------------------------------------------------------------


def test_rule_success_Discover(tmp_path: Path) -> None:
    """Verify rule Discover succeeds when all preconditions are met.

    The seeds are enqueued at depth 0 and every allowed host is opened, in sorted order,
    its robots.txt read at the origin of its first seed, else https on the bare name.
    T13: after its robots.txt each host's sitemaps and llms.txt are requested at that
    origin, before the next host is opened.
    """
    fetcher = site()
    run, frontier = started(
        tmp_path,
    )
    run.target.scope = dataclasses.replace(
        run.target.scope, allowed_hosts=frozenset({HOST, "api.example"})
    )
    assert prepare_run(run, frontier)
    assert discover(run, frontier, fetcher)
    (entry,) = frontier.entries
    assert entry.identity == SEED
    assert entry.depth == 0
    assert entry.discovered_via is DiscoverySource.start
    assert entry.priority == model.CONFIG.start_priority
    assert entry.status is FrontierStatus.pending
    assert [host.name for host in run.hosts] == ["api.example", HOST]
    docs = run.host(HOST)
    api = run.host("api.example")
    assert docs is not None
    assert api is not None
    assert docs.origin == SITE
    assert api.origin == "https://api.example"
    api_discovery = [
        f"https://api.example/{path}"
        for path in ("robots.txt", "sitemap.xml", "sitemap_index.xml", "llms.txt")
    ]
    assert fetcher.requests == [*api_discovery, *DISCOVERY]


def test_rule_failure_Discover_1(tmp_path: Path) -> None:
    """Verify rule Discover is rejected when requires clause fails.

    requires: run.status = running.
    """
    fetcher = site()
    run, frontier = started(tmp_path)
    run.status = RunStatus.interrupted
    assert not discover(run, frontier, fetcher)
    assert frontier.entries == []
    assert run.hosts == []
    assert fetcher.requests == []


def test_rule_success_OpenHost(tmp_path: Path) -> None:
    """Verify rule OpenHost succeeds when all preconditions are met.

    RobotsRequested carries the origin OpenHost was given (T12): the robots.txt read is
    that origin's, port included.
    """
    fetcher = site()
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, fetcher)
    assert host is not None
    assert run.hosts == [host]
    assert fetcher.requests == [ROBOTS]  # OpenHost raises RobotsRequested

    ported = site()
    other, _ = started(tmp_path / "ported")
    opened = open_host(other, HOST, PORTED, ported)
    assert opened is not None
    assert opened.origin == PORTED
    assert ported.requests == [PORTED_ROBOTS]
    assert other.robots_policy(PORTED) is not None
    assert other.robots_policy(SITE) is None


def test_rule_failure_OpenHost_1(tmp_path: Path) -> None:
    """Verify rule OpenHost is rejected when requires clause fails.

    requires: run.status = running.
    """
    fetcher = site()
    run, _ = started(tmp_path)
    run.status = RunStatus.finished
    assert open_host(run, HOST, SITE, fetcher) is None
    assert run.hosts == []
    assert fetcher.requests == []


def test_rule_failure_OpenHost_2(tmp_path: Path) -> None:
    """Verify rule OpenHost is rejected when requires clause fails.

    requires: not exists Host{run: run, name: name}.
    """
    fetcher = site()
    run, _ = started(tmp_path)
    first = open_host(run, HOST, SITE, fetcher)
    assert open_host(run, HOST, "https://docs.example", fetcher) is None
    assert run.hosts == [first]
    assert fetcher.requests == [ROBOTS]


def test_rule_entity_creation_OpenHost_1(tmp_path: Path) -> None:
    """Verify entity creation in rule OpenHost ensures clause produces the specified fields."""
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, site())
    assert host is not None
    assert host.run is run
    assert host.name == HOST
    assert host.origin == SITE
    assert host.rate == run.policy.rate_per_host
    assert host.crawl_delay == timedelta(0)
    assert host.paused_until is None
    assert host.recent_text_lengths == []
    assert host.tiers_used == frozenset()
    assert host.fetched == 0
    assert host.blocked == 0
    assert host.render_escalations == 0
    assert host.retry_after_honored == 0
    assert host.sitemap_children_read == 0
    assert host.sitemap_entries_admitted == 0
    breaker = host.breaker
    assert breaker is not None
    assert breaker.host is host
    assert breaker.tier is run.usable_tiers[0]
    assert breaker.highest_tier is run.highest_tier
    assert breaker.outcomes == []
    assert breaker.escalations == 0
    assert breaker.since_escalation == 0
    assert breaker.status is BreakerStatus.watching


def test_rule_success_FetchRobots(tmp_path: Path) -> None:
    """Verify rule FetchRobots succeeds when all preconditions are met.

    robots.txt is read once, before the page, and its bytes count: the run requests
    /robots.txt, then the seed, then nothing. RobotsRequested names the origin (T12): a
    second origin of the host reads its own robots.txt into its own policy. An ordinary
    answer leaves the breaker alone; only a Retry-After past the cap would trip it.
    """
    robots = text_response(ROBOTS, RULES)
    fetcher = site(robots=robots)
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, fetcher)
    assert host is not None
    assert run.bytes_fetched == robots.size
    assert run.robots_policy(SITE) is not None

    ported_robots = text_response(PORTED_ROBOTS, "User-agent: *\nDisallow: /guide/\n")
    fetcher.responses[PORTED_ROBOTS] = ported_robots
    response = fetch_robots(run, HOST, PORTED, fetcher)
    assert response is not None
    assert response.source_url == PORTED_ROBOTS
    assert fetcher.requests == [ROBOTS, PORTED_ROBOTS]
    assert run.bytes_fetched == robots.size + ported_robots.size
    ported = run.robots_policy(PORTED)
    assert ported is not None
    assert ported.origin == PORTED
    assert [policy.origin for policy in run.robots_policies] == [SITE, PORTED]
    assert host.breaker is not None
    assert host.breaker.status is BreakerStatus.watching
    assert host.breaker.outcomes == []

    order = site(robots=robots)
    crawl_once(tmp_path / "order", order)
    assert order.requests == [*DISCOVERY, SEED]


def test_rule_failure_FetchRobots_1(tmp_path: Path) -> None:
    """Verify rule FetchRobots is rejected when requires clause fails.

    requires: run.status = running.
    """
    fetcher = site()
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, fetcher)
    assert host is not None
    assert host.breaker is not None
    run.robots_policies.clear()
    run.status = RunStatus.finished
    assert fetch_robots(run, HOST, SITE, fetcher) is None
    assert fetch_robots(run, HOST, PORTED, fetcher) is None
    assert fetcher.requests == [ROBOTS]
    assert run.robots_policies == []
    assert host.breaker.status is BreakerStatus.watching


def test_rule_failure_FetchRobots_2(tmp_path: Path) -> None:
    """Verify rule FetchRobots is rejected when requires clause fails.

    requires: exists host.
    """
    fetcher = site()
    run, _ = started(tmp_path)
    assert fetch_robots(run, HOST, SITE, fetcher) is None
    assert fetch_robots(run, HOST, PORTED, fetcher) is None
    assert fetcher.requests == []
    assert run.bytes_fetched == 0
    assert run.robots_policies == []


def test_rule_failure_FetchRobots_3(tmp_path: Path) -> None:
    """Verify rule FetchRobots is rejected when requires clause fails.

    requires: not exists RobotsPolicy{run: run, origin: origin}.
    """
    fetcher = site()
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, fetcher)
    assert host is not None
    assert host.breaker is not None
    assert fetch_robots(run, HOST, PORTED, fetcher) is not None
    before = run.bytes_fetched
    assert fetch_robots(run, HOST, SITE, fetcher) is None
    assert fetch_robots(run, HOST, PORTED, fetcher) is None
    assert fetcher.requests == [ROBOTS, PORTED_ROBOTS]
    assert run.bytes_fetched == before
    assert host.breaker.status is BreakerStatus.watching


def adopted_delay(out_dir: Path, written: str) -> tuple[RobotsPolicy | None, Host]:
    """AdoptRobotsRules for a second origin whose robots.txt declares Crawl-delay `written`.

    The host opens on SITE with no robots.txt, so it starts with no delay and the run's rate.
    """
    return adopted_robots(out_dir, f"User-agent: *\nCrawl-delay: {written}\n")


def adopted_robots(out_dir: Path, markup: str) -> tuple[RobotsPolicy | None, Host]:
    """AdoptRobotsRules for a second origin whose robots.txt is `markup`.

    The host opens on SITE with no robots.txt, so it starts with no delay and the run's rate.
    """
    run, _ = started(out_dir)
    host = open_host(run, HOST, SITE, site())
    assert host is not None
    assert (host.crawl_delay, host.rate) == (timedelta(0), run.policy.rate_per_host)
    robots = text_response(PORTED_ROBOTS, markup)
    return adopt_robots_rules(run, host, robots, origin=PORTED), host


def test_rule_success_AdoptRobotsRules(tmp_path: Path) -> None:
    """Verify rule AdoptRobotsRules succeeds when all preconditions are met.

    The policy is parsed for the user agent rovo, and the host takes its Crawl-delay
    (T12): crawl_delay = max(crawl_delay, delay) and rate = min(rate, 1 / delay). Of two
    origins of one host the longest delay and the lowest rate win, in either order; a
    Crawl-delay of 0 changes neither; 0.5 is read as half a second. A delay equal to
    retry_after_cap is adopted; one past it, however large, is never adopted (71b5b0f).
    """
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, site(robots=text_response(ROBOTS, RULES)))
    assert host is not None
    policy = run.robots_policy(SITE)
    assert policy is not None
    assert policy.stance is RobotsStance.rules
    assert robots_allows(run, SEED)
    assert not robots_allows(run, f"{SITE}/private/notes.html")
    rate = run.policy.rate_per_host
    assert rate is not None
    assert host.crawl_delay == CRAWL_DELAY
    assert host.rate == min(rate, 1 / CRAWL_DELAY.total_seconds())

    for name, delays in (("longer-second", (2, 3)), ("longer-first", (3, 2))):
        two, _ = started(tmp_path / name)
        fetcher = site(robots=text_response(ROBOTS, f"User-agent: *\nCrawl-delay: {delays[0]}\n"))
        fetcher.responses[PORTED_ROBOTS] = text_response(
            PORTED_ROBOTS, f"User-agent: *\nCrawl-delay: {delays[1]}\n"
        )
        shared = open_host(two, HOST, SITE, fetcher)
        assert shared is not None
        fetch_robots(two, HOST, PORTED, fetcher)
        longest = max(delays)
        assert shared.crawl_delay == timedelta(seconds=longest), name
        assert shared.rate == min(rate, 1 / longest), name

    zero, _ = started(tmp_path / "zero")
    unchanged = open_host(zero, HOST, SITE, site(robots=text_response(ROBOTS, ZERO_DELAY)))
    assert unchanged is not None
    zero_policy = zero.robots_policy(SITE)
    assert zero_policy is not None
    assert zero_policy.crawl_delay == timedelta(0)
    assert unchanged.rate == rate
    assert unchanged.crawl_delay == timedelta(0)

    half, _ = started(tmp_path / "half")
    halved = open_host(half, HOST, SITE, site(robots=text_response(ROBOTS, HALF_DELAY)))
    assert halved is not None
    half_policy = half.robots_policy(SITE)
    assert half_policy is not None
    assert half_policy.crawl_delay == timedelta(seconds=0.5)
    assert halved.crawl_delay == timedelta(seconds=0.5)
    assert halved.rate == min(rate, 1 / 0.5)

    # At 71b5b0f: a Crawl-delay equal to retry_after_cap is adopted.
    cap = run.policy.retry_after_cap
    cap_policy, slowest = adopted_delay(tmp_path / "at-cap", f"{cap.total_seconds():g}")
    assert cap_policy is not None
    assert (cap_policy.crawl_delay, slowest.crawl_delay) == (cap, cap)
    assert slowest.rate == min(rate, 1 / cap.total_seconds())

    # At 71b5b0f: a Crawl-delay past retry_after_cap is never adopted, however large; the
    # rule records no delay and leaves the host as it was, and reading it never raises.
    # (Retiring the host is RetireHostOnLongCrawlDelay's, the breaker slice's.)
    for written in PAST_CAP_DELAYS:
        adopted, kept = adopted_delay(tmp_path / f"past-{written}", written)
        assert adopted is not None, written
        assert adopted.stance is RobotsStance.rules, written
        assert adopted.crawl_delay is None, written
        assert (kept.crawl_delay, kept.rate) == (timedelta(0), rate), written


def test_rule_success_AdoptRobotsRules_reads_the_crawl_delay_as_written(tmp_path: Path) -> None:
    """AdoptRobotsRules reads Crawl-delay exactly, as protego's grammar spells it (71b5b0f).

    crawl.allium robots_crawl_delay and robots_crawl_delay_exceeds (AdoptRobotsRules'
    guidance, 837 to 843 at fa096c4): a number past retry_after_cap, however large or
    however slightly past, is never adopted and meets RetireHostOnLongCrawlDelay's guard;
    a value that is not a finite, non-negative number is no Crawl-delay, so the host is
    unchanged and not retired; a number too small for Decimal is 0, no delay. Reviews
    T12-2-r2 C1/B1 and T12-3-r2 C1/B1/C2.
    """
    rate = standard_policy().rate_per_host
    for written in PAST_CAP_DELAYS:
        adopted, kept = adopted_delay(tmp_path / f"past-{written}", written)
        assert adopted is not None, written
        assert adopted.crawl_delay is None, written
        assert (kept.crawl_delay, kept.rate) == (timedelta(0), rate), written
        assert retires_host_on_long_crawl_delay(adopted.run, adopted), written

    for number, written in enumerate(NULL_DELAYS):
        adopted, kept = adopted_delay(tmp_path / f"null-{number}", written)
        assert adopted is not None, written
        assert adopted.stance is RobotsStance.rules, written
        assert adopted.crawl_delay is None, written
        assert (kept.crawl_delay, kept.rate) == (timedelta(0), rate), written
        assert not retires_host_on_long_crawl_delay(adopted.run, adopted), written

    tiny, unchanged = adopted_delay(tmp_path / "tiny", TINY_DELAY)
    assert tiny is not None
    assert tiny.crawl_delay == timedelta(0)
    assert (unchanged.crawl_delay, unchanged.rate) == (timedelta(0), rate)
    assert not retires_host_on_long_crawl_delay(tiny.run, tiny)

    for number, line in enumerate(SPELLED_DELAYS):
        markup = f"User-agent: *\n{line}\nDisallow:/guide/private/\n"
        spelled, slowed = adopted_robots(tmp_path / f"spelled-{number}", markup)
        assert spelled is not None, line
        assert spelled.crawl_delay == SPELLED_DELAY, line
        assert slowed.crawl_delay == SPELLED_DELAY, line
        assert not robots_allows(spelled.run, f"{PORTED}/guide/private/notes.html"), line
        assert robots_allows(spelled.run, PORTED_PAGE), line


def test_rule_failure_AdoptRobotsRules_1(tmp_path: Path) -> None:
    """Verify rule AdoptRobotsRules is rejected when requires clause fails.

    requires: response.ok.
    """
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, site())
    assert host is not None
    before = list(run.robots_policies)
    assert adopt_robots_rules(run, host, not_found(ROBOTS)) is None
    assert run.robots_policies == before


def test_rule_entity_creation_AdoptRobotsRules_1(tmp_path: Path) -> None:
    """Verify entity creation in rule AdoptRobotsRules ensures clause produces the specified fields."""  # noqa: E501  The obligation's description, quoted.
    run, _ = started(tmp_path)
    open_host(run, HOST, SITE, site(robots=text_response(ROBOTS, RULES)))
    policy = run.robots_policy(SITE)
    assert policy is not None
    assert policy.run is run
    assert policy.origin == SITE
    assert policy.stance is RobotsStance.rules
    assert policy.crawl_delay == CRAWL_DELAY
    assert policy.declared_sitemaps == (f"{SITE}/sitemap.xml",)
    assert policy.problem is None

    # crawl_delay is declared_delay (71b5b0f): null for a Crawl-delay past the cap, the
    # other fields as before.
    past, _ = started(tmp_path / "past")
    host = open_host(past, HOST, SITE, site())
    assert host is not None
    long_rules = RULES.replace("Crawl-delay: 2", f"Crawl-delay: {PAST_CAP_DELAYS[-1]}")
    created = adopt_robots_rules(
        past, host, text_response(PORTED_ROBOTS, long_rules), origin=PORTED
    )
    assert created is not None
    assert created.run is past
    assert created.origin == PORTED
    assert created.stance is RobotsStance.rules
    assert created.crawl_delay is None
    assert created.declared_sitemaps == (f"{SITE}/sitemap.xml",)
    assert created.problem is None


def test_rule_success_AllowAllWhenRobotsAbsent(tmp_path: Path) -> None:
    """Verify rule AllowAllWhenRobotsAbsent succeeds when all preconditions are met."""
    run, _ = started(tmp_path)
    open_host(run, HOST, SITE, site())
    policy = run.robots_policy(SITE)
    assert policy is not None
    assert policy.stance is RobotsStance.allow_all
    assert robots_allows(run, SEED)
    assert robots_allows(run, f"{SITE}/private/notes.html")


def test_rule_failure_AllowAllWhenRobotsAbsent_1(tmp_path: Path) -> None:
    """Verify rule AllowAllWhenRobotsAbsent is rejected when requires clause fails.

    requires: not response.ok.
    """
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, site())
    assert host is not None
    before = list(run.robots_policies)
    assert allow_all_when_robots_absent(run, host, text_response(ROBOTS, RULES)) is None
    assert run.robots_policies == before


def test_rule_failure_AllowAllWhenRobotsAbsent_2(tmp_path: Path) -> None:
    """Verify rule AllowAllWhenRobotsAbsent is rejected when requires clause fails.

    requires: response.error = null and not access_refused and not server_error.
    """
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, site())
    assert host is not None
    before = list(run.robots_policies)
    unreachable = SiteResponse(status=0, source_url=ROBOTS, markup="", size=0, error="refused")
    for response in (
        unreachable,
        text_response(ROBOTS, "", status=FORBIDDEN),
        text_response(ROBOTS, "", status=SERVER_ERROR),
    ):
        assert allow_all_when_robots_absent(run, host, response) is None
    assert run.robots_policies == before


def test_rule_entity_creation_AllowAllWhenRobotsAbsent_1(tmp_path: Path) -> None:
    """Verify entity creation in rule AllowAllWhenRobotsAbsent ensures clause produces the specified fields."""  # noqa: E501  The obligation's description, quoted.
    run, _ = started(tmp_path)
    open_host(run, HOST, SITE, site())
    policy = run.robots_policy(SITE)
    assert policy is not None
    assert policy.run is run
    assert policy.origin == SITE
    assert policy.stance is RobotsStance.allow_all
    assert policy.crawl_delay is None
    assert policy.declared_sitemaps == ()
    assert policy.problem is None


def test_rule_success_Enqueue(tmp_path: Path) -> None:
    """Verify rule Enqueue succeeds when all preconditions are met.

    A new identity gets a pending row; rediscovery lowers the depth, takes a newer
    lastmod and promotes a deferred row, and never changes the status, also when the
    rediscovery comes from a stored page's links (T10).
    """
    run, frontier = started(tmp_path)
    entry = enqueue(
        run, frontier, OTHER, depth=2, via=DiscoverySource.link, priority=0, from_url=SEED
    )
    assert frontier.entries == [entry]
    assert entry.frontier is frontier
    assert entry.identity == OTHER
    assert entry.depth == SECOND_RUN
    assert entry.discovered_via is DiscoverySource.link
    assert (entry.discovered_from, entry.sitemap_lastmod) == (SEED, None)
    assert entry.priority == 0
    assert entry.attempts == 0
    assert entry.status is FrontierStatus.pending
    assert OTHER in run.active_urls

    entry.priority = model.CONFIG.deferred_priority
    again = enqueue(
        run,
        frontier,
        OTHER,
        depth=1,
        via=DiscoverySource.sitemap,
        priority=1,
        lastmod="2026-10-01",
    )
    assert again is entry
    assert frontier.entries == [entry]
    assert (entry.depth, entry.sitemap_lastmod, entry.priority) == (1, "2026-10-01", 1)
    assert entry.discovered_via is DiscoverySource.link
    assert entry.status is FrontierStatus.pending

    # T10: a page's links rediscover rows through EnqueuePageLinks. A deeper deferred
    # pending row takes the shorter route's depth and the link priority; a settled row
    # keeps its status and its discovery; no identity gets a second row.
    run, frontier, found = stored_seed(tmp_path / "links", links_site())
    deferred = enqueue(
        run,
        frontier,
        C_PAGE,
        depth=THIRD_RUN,
        via=DiscoverySource.recheck,
        priority=model.CONFIG.deferred_priority,
    )
    settled_row = enqueue(run, frontier, B_PAGE, depth=1, via=DiscoverySource.sitemap, priority=0)
    settled_row.status = FrontierStatus.done
    assert enqueue_page_links(run, frontier, found) is not None
    assert (deferred.depth, deferred.priority) == (1, model.CONFIG.link_priority)
    assert deferred.status is FrontierStatus.pending
    assert deferred.discovered_via is DiscoverySource.recheck
    assert settled_row.status is FrontierStatus.done
    assert settled_row.discovered_via is DiscoverySource.sitemap
    identities = [entry.identity for entry in frontier.entries]
    assert len(identities) == len(set(identities))
    assert SECRET_PAGE in identities


def aged_observations(frontier: Frontier, run_id: int) -> tuple[ObservedUrl, ObservedUrl]:
    """A row unseen for more than observed_url_retention_syncs runs, and one seen within."""
    retention = model.CONFIG.observed_url_retention_syncs
    stale = ObservedUrl(
        frontier=frontier,
        url=f"{SITE}/guide/stale.html",
        sources=frozenset({DiscoverySource.sitemap}),
        last_seen_run=run_id - retention - 1,
    )
    fresh = ObservedUrl(
        frontier=frontier,
        url=f"{SITE}/guide/fresh.html",
        sources=frozenset({DiscoverySource.llms_txt}),
        last_seen_run=run_id - retention,
    )
    frontier.observed_urls.extend([stale, fresh])
    return stale, fresh


def test_rule_success_DropStaleObservations(tmp_path: Path) -> None:
    """Verify rule DropStaleObservations succeeds when all preconditions are met.

    T13: a row unseen for more than observed_url_retention_syncs runs is dropped and a
    row seen within them is kept; DiscoveryDone follows either way.
    """
    run_id = model.CONFIG.observed_url_retention_syncs + 2
    run, frontier = started(tmp_path, run_id=run_id)
    _, fresh = aged_observations(frontier, run_id)
    assert drop_stale_observations(run, frontier)
    assert frontier.observed_urls == [fresh]
    empty, nothing_seen = started(tmp_path / "empty")
    assert drop_stale_observations(empty, nothing_seen)
    assert nothing_seen.observed_urls == []


def test_rule_failure_DropStaleObservations_1(tmp_path: Path) -> None:
    """Verify rule DropStaleObservations is rejected when requires clause fails.

    requires: run.status = running.
    """
    run_id = model.CONFIG.observed_url_retention_syncs + 2
    run, frontier = started(tmp_path, run_id=run_id)
    stale, fresh = aged_observations(frontier, run_id)
    run.status = RunStatus.finished
    assert not drop_stale_observations(run, frontier)
    assert frontier.observed_urls == [stale, fresh]


def test_rule_success_BeginCrawl(tmp_path: Path) -> None:
    """Verify rule BeginCrawl succeeds when all preconditions are met."""
    run, _ = started(tmp_path)
    assert begin_crawl(run)
    assert run.crawling


def test_rule_failure_BeginCrawl_1(tmp_path: Path) -> None:
    """Verify rule BeginCrawl is rejected when requires clause fails.

    requires: run.status = running.
    """
    run, _ = started(tmp_path)
    run.status = RunStatus.interrupted
    assert not begin_crawl(run)
    assert not run.crawling


# --- Scheduling ---------------------------------------------------------------------


def test_rule_success_SelectBatch(tmp_path: Path) -> None:
    """Verify rule SelectBatch succeeds when all preconditions are met.

    The pending seed row is chosen and put in progress; with nothing pending, the rule
    raises FrontierExhausted, an empty batch.
    """
    run, frontier = crawling(tmp_path, site())
    batch = select_batch(run, frontier)
    assert batch is not None
    assert [entry.identity for entry in batch] == [SEED]
    assert batch[0].status is FrontierStatus.in_progress
    batch[0].status = FrontierStatus.done
    assert select_batch(run, frontier) == []
    assert not run.budget_stopped


def test_rule_failure_SelectBatch_1(tmp_path: Path) -> None:
    """Verify rule SelectBatch is rejected when requires clause fails.

    requires: run.status = running and run.crawling.
    """
    fetcher = site()
    run, frontier = started(tmp_path)
    assert prepare_run(run, frontier)
    assert discover(run, frontier, fetcher)
    assert select_batch(run, frontier) is None
    assert [entry.status for entry in frontier.entries] == [FrontierStatus.pending]


def test_rule_success_NextBatch(tmp_path: Path) -> None:
    """Verify rule NextBatch succeeds when all preconditions are met.

    When no row is in progress, a crawling run asks for another batch; over the links
    site a second and a third batch fetch the pages the first one's links reached.
    """
    run, frontier = crawling(tmp_path, site())
    assert next_batch(run, frontier)
    select_batch(run, frontier)
    assert not next_batch(run, frontier)

    # T10: the links one batch stores are fetched in later batches, never twice: the
    # depth-0 batch, then depth 1 (the robots-disallowed row skipped unrequested), then 2.
    fetcher = links_site()
    result = crawl_once(tmp_path / "links", fetcher)
    assert fetcher.requests == [*DISCOVERY, SEED, B_PAGE, C_PAGE, D_PAGE]
    assert sorted(page.identity for page in result.run.target.pages) == sorted(
        [SEED, B_PAGE, C_PAGE, D_PAGE]
    )
    depths = {entry.identity: entry.depth for entry in result.frontier.entries}
    assert depths == {SEED: 0, B_PAGE: 1, C_PAGE: 1, SECRET_PAGE: 1, D_PAGE: 2}


def test_rule_success_SkipRobotsDisallowed(tmp_path: Path) -> None:
    """Verify rule SkipRobotsDisallowed succeeds when all preconditions are met."""
    run, _, entry = selected(tmp_path, site(robots=text_response(ROBOTS, DISALLOW_GUIDE)))
    assert skip_robots_disallowed(run, entry)
    assert entry.status is FrontierStatus.skipped_robots


def test_rule_failure_SkipRobotsDisallowed_1(tmp_path: Path) -> None:
    """Verify rule SkipRobotsDisallowed is rejected when requires clause fails.

    requires: exists run.
    """
    _, _, entry = selected(tmp_path, site(robots=text_response(ROBOTS, DISALLOW_GUIDE)))
    assert not skip_robots_disallowed(None, entry)
    assert entry.status is FrontierStatus.in_progress


def test_rule_failure_SkipRobotsDisallowed_2(tmp_path: Path) -> None:
    """Verify rule SkipRobotsDisallowed is rejected when requires clause fails.

    requires: exists host and not host.breaker_tripped.
    """
    run, _, entry = crawling_without_hosts(tmp_path)
    assert not skip_robots_disallowed(run, entry)
    assert entry.status is FrontierStatus.in_progress

    run, _, entry = selected(
        tmp_path / "tripped", site(robots=text_response(ROBOTS, DISALLOW_GUIDE))
    )
    host = run.host(HOST)
    assert host is not None
    assert host.breaker is not None
    host.breaker.status = BreakerStatus.tripped
    assert not skip_robots_disallowed(run, entry)
    assert entry.status is FrontierStatus.in_progress


def test_rule_failure_SkipRobotsDisallowed_3(tmp_path: Path) -> None:
    """Verify rule SkipRobotsDisallowed is rejected when requires clause fails.

    requires: not robots_allows(run, entry.identity).
    """
    run, _, entry = selected(tmp_path, site())
    assert not skip_robots_disallowed(run, entry)
    assert entry.status is FrontierStatus.in_progress


def test_rule_success_OpenHostForEntry(tmp_path: Path) -> None:
    """Verify rule OpenHostForEntry succeeds when all preconditions are met.

    The row's host is opened on first use and its robots.txt read before any page.
    """
    fetcher = site()
    run, _, entry = crawling_without_hosts(tmp_path)
    assert open_host_for_entry(run, entry, fetcher)
    host = run.host(HOST)
    assert host is not None
    assert host.origin == SITE
    assert fetcher.requests == [ROBOTS]


def test_rule_failure_OpenHostForEntry_1(tmp_path: Path) -> None:
    """Verify rule OpenHostForEntry is rejected when requires clause fails.

    requires: exists run.
    """
    fetcher = site()
    run, _, entry = crawling_without_hosts(tmp_path)
    assert not open_host_for_entry(None, entry, fetcher)
    assert run.hosts == []
    assert fetcher.requests == []


def test_rule_failure_OpenHostForEntry_2(tmp_path: Path) -> None:
    """Verify rule OpenHostForEntry is rejected when requires clause fails.

    requires: not exists Host{run: run, name: entry.host_name}.
    """
    fetcher = site()
    run, _, entry = selected(tmp_path, fetcher)
    assert not open_host_for_entry(run, entry, fetcher)
    assert len(run.hosts) == 1
    assert fetcher.requests == DISCOVERY


def test_rule_success_ProceedWithKnownHost(tmp_path: Path) -> None:
    """Verify rule ProceedWithKnownHost succeeds when all preconditions are met."""
    run, _, entry = selected(tmp_path, site())
    assert proceed_with_known_host(run, entry)
    assert entry.status is FrontierStatus.in_progress


def test_rule_failure_ProceedWithKnownHost_1(tmp_path: Path) -> None:
    """Verify rule ProceedWithKnownHost is rejected when requires clause fails.

    requires: exists run.
    """
    _, _, entry = selected(tmp_path, site())
    assert not proceed_with_known_host(None, entry)


def test_rule_failure_ProceedWithKnownHost_2(tmp_path: Path) -> None:
    """Verify rule ProceedWithKnownHost is rejected when requires clause fails.

    requires: exists host and not host.breaker_tripped.
    """
    run, _, entry = crawling_without_hosts(tmp_path)
    assert not proceed_with_known_host(run, entry)

    run, _, entry = selected(tmp_path / "tripped", site())
    host = run.host(HOST)
    assert host is not None
    assert host.breaker is not None
    host.breaker.status = BreakerStatus.tripped
    assert not proceed_with_known_host(run, entry)


def test_rule_failure_ProceedWithKnownHost_3(tmp_path: Path) -> None:
    """Verify rule ProceedWithKnownHost is rejected when requires clause fails.

    requires: robots_allows(run, entry.identity).
    """
    run, _, entry = selected(tmp_path, site(robots=text_response(ROBOTS, DISALLOW_GUIDE)))
    assert not proceed_with_known_host(run, entry)


def test_rule_success_SkipRobotsDisallowedOnNewHost(tmp_path: Path) -> None:
    """Verify rule SkipRobotsDisallowedOnNewHost succeeds when all preconditions are met."""
    fetcher = site(robots=text_response(ROBOTS, DISALLOW_GUIDE))
    run, _, entry = crawling_without_hosts(tmp_path)
    assert open_host_for_entry(run, entry, fetcher)
    assert skip_robots_disallowed_on_new_host(run, entry)
    assert entry.status is FrontierStatus.skipped_robots
    assert fetcher.requests == [ROBOTS]


def test_rule_failure_SkipRobotsDisallowedOnNewHost_1(tmp_path: Path) -> None:
    """Verify rule SkipRobotsDisallowedOnNewHost is rejected when requires clause fails.

    requires: run.status = running and entry.status = in_progress.
    """
    fetcher = site(robots=text_response(ROBOTS, DISALLOW_GUIDE))
    run, _, entry = crawling_without_hosts(tmp_path)
    assert open_host_for_entry(run, entry, fetcher)
    entry.status = FrontierStatus.pending
    assert not skip_robots_disallowed_on_new_host(run, entry)
    assert entry.status is FrontierStatus.pending
    entry.status = FrontierStatus.in_progress
    run.status = RunStatus.finished
    assert not skip_robots_disallowed_on_new_host(run, entry)
    assert entry.status is FrontierStatus.in_progress


def test_rule_failure_SkipRobotsDisallowedOnNewHost_2(tmp_path: Path) -> None:
    """Verify rule SkipRobotsDisallowedOnNewHost is rejected when requires clause fails.

    requires: not robots_allows(run, entry.identity).
    """
    fetcher = site()
    run, _, entry = crawling_without_hosts(tmp_path)
    assert open_host_for_entry(run, entry, fetcher)
    assert not skip_robots_disallowed_on_new_host(run, entry)
    assert entry.status is FrontierStatus.in_progress


# --- Fetching one entry ------------------------------------------------------------


def test_rule_success_FetchEntry(tmp_path: Path) -> None:
    """Verify rule FetchEntry succeeds when all preconditions are met."""
    fetcher = site()
    run, _, entry = selected(tmp_path, fetcher)
    walk = fetch_entry(run, entry, fetcher)
    assert isinstance(walk, LadderWalk)
    assert walk.status is WalkStatus.walking
    assert len(walk.attempts) == 1  # FetchEntry raises the first TierRequested
    assert fetcher.requests == [*DISCOVERY, SEED]
    assert fetcher.validators == [None] * len(
        [*DISCOVERY, SEED]
    )  # no known page: an unconditional fetch


def test_rule_failure_FetchEntry_1(tmp_path: Path) -> None:
    """Verify rule FetchEntry is rejected when requires clause fails.

    requires: run.status = running and entry.status = in_progress.
    """
    fetcher = site()
    run, _, entry = selected(tmp_path, fetcher)
    entry.status = FrontierStatus.pending
    assert fetch_entry(run, entry, fetcher) is None
    entry.status = FrontierStatus.in_progress
    run.status = RunStatus.finished
    assert fetch_entry(run, entry, fetcher) is None
    assert fetcher.requests == DISCOVERY
    assert entry.attempts == 0
    assert run.fetch_attempts == 0


def test_rule_failure_FetchEntry_2(tmp_path: Path) -> None:
    """Verify rule FetchEntry is rejected when requires clause fails.

    requires: robots_allows(run, entry.identity).
    """
    fetcher = site(robots=text_response(ROBOTS, DISALLOW_GUIDE))
    run, _, entry = selected(tmp_path, fetcher)
    assert fetch_entry(run, entry, fetcher) is None
    assert fetcher.requests == DISCOVERY
    assert entry.attempts == 0


def test_rule_failure_FetchEntry_3(tmp_path: Path) -> None:
    """Verify rule FetchEntry is rejected when requires clause fails.

    requires: exists host and not host.breaker_tripped.
    """
    fetcher = site()
    run, _, entry = crawling_without_hosts(tmp_path)
    assert fetch_entry(run, entry, fetcher) is None
    assert fetcher.requests == []
    assert entry.attempts == 0


def test_rule_entity_creation_FetchEntry_1(tmp_path: Path) -> None:
    """Verify entity creation in rule FetchEntry ensures clause produces the specified fields."""
    fetcher = site()
    run, _, entry = selected(tmp_path, fetcher)
    walk = fetch_entry(run, entry, fetcher)
    assert walk is not None
    assert entry.attempts == 1
    assert run.fetch_attempts == 1
    assert walk.entry is entry
    assert walk.host is run.host(HOST)
    assert walk.tiers == (Tier.http,)
    assert walk.conditional is False
    assert walk.escalated is False
    assert walk.challenge_offered is False
    assert walk.status is WalkStatus.walking
    assert walk.standing is None


def test_rule_success_AttemptTier(tmp_path: Path) -> None:
    """Verify rule AttemptTier succeeds when all preconditions are met."""
    fetcher = site()
    run, _, walk = walked(tmp_path, fetcher)
    (attempt,) = walk.attempts
    assert attempt.response.source_url == SEED
    assert attempt.response.markup == PAGE
    assert attempt.response.ok
    assert run.fetch_attempts == 1  # the first try at the first tier is FetchEntry's count


def test_rule_failure_AttemptTier_1(tmp_path: Path) -> None:
    """Verify rule AttemptTier is rejected when requires clause fails.

    requires: walk.status = walking.
    """
    fetcher = site()
    run, _, walk = settled(tmp_path, fetcher)
    before = (run.bytes_fetched, run.fetch_attempts, len(fetcher.requests))
    assert attempt_tier(walk, Tier.http, 1, fetcher) is None
    assert (run.bytes_fetched, run.fetch_attempts, len(fetcher.requests)) == before
    assert len(walk.attempts) == 1


def test_rule_failure_AttemptTier_2(tmp_path: Path) -> None:
    """Verify rule AttemptTier is rejected when requires clause fails.

    requires: walk.host.run.status = running.
    """
    fetcher = site()
    run, _, walk = walked(tmp_path, fetcher)
    run.status = RunStatus.interrupted
    assert attempt_tier(walk, Tier.http, SECOND_RUN, fetcher) is None
    assert fetcher.requests == [*DISCOVERY, SEED]
    assert len(walk.attempts) == 1


def test_rule_entity_creation_AttemptTier_1(tmp_path: Path) -> None:
    """Verify entity creation in rule AttemptTier ensures clause produces the specified fields.

    An unblocked http answer carrying a noscript notice gets its render reason.
    """
    fetcher = site(page=NOSCRIPT_PAGE)
    run, _, walk = walked(tmp_path, fetcher)
    (attempt,) = walk.attempts
    assert attempt.walk is walk
    assert attempt.tier is Tier.http
    assert attempt.try_ == 1
    assert attempt.response.markup == NOSCRIPT_PAGE
    assert attempt.verdict == BlockVerdict(kind=BlockKind.none, signature="")
    assert attempt.render_reason is RenderReason.noscript_needs_js
    assert run.bytes_fetched == fetcher.responses[SEED].size  # robots.txt was a 404


def test_rule_success_PrepareAttempt(tmp_path: Path) -> None:
    """Verify rule PrepareAttempt succeeds when all preconditions are met."""
    _, _, walk = walked(tmp_path, site())
    (attempt,) = walk.attempts
    assert prepare_attempt(attempt)
    assert walk.challenge_offered is False


def test_rule_failure_PrepareAttempt_1(tmp_path: Path) -> None:
    """Verify rule PrepareAttempt is rejected when requires clause fails.

    requires: walk.status = walking and run.status = running.
    """
    run, _, walk = walked(tmp_path, site())
    (attempt,) = walk.attempts
    run.status = RunStatus.finished
    assert not prepare_attempt(attempt)
    run.status = RunStatus.running
    walk.status = WalkStatus.settled
    assert not prepare_attempt(attempt)


def test_rule_success_SettleWalk(tmp_path: Path) -> None:
    """Verify rule SettleWalk succeeds when all preconditions are met."""
    _, _, walk = walked(tmp_path, site())
    (attempt,) = walk.attempts
    assert settle_walk(attempt)
    assert walk.status is WalkStatus.settled
    assert walk.standing is attempt
    assert walk.host.tiers_used == frozenset({Tier.http})
    assert walk.host.render_escalations == 0


def test_rule_failure_SettleWalk_1(tmp_path: Path) -> None:
    """Verify rule SettleWalk is rejected when requires clause fails.

    requires: walk.status = walking and walk.host.run.status = running.
    """
    run, _, walk = walked(tmp_path, site())
    (attempt,) = walk.attempts
    run.status = RunStatus.finished
    assert not settle_walk(attempt)
    assert walk.status is WalkStatus.walking
    assert walk.standing is None


def test_rule_failure_SettleWalk_2(tmp_path: Path) -> None:
    """Verify rule SettleWalk is rejected when requires clause fails.

    requires: not attempt.retryable and not attempt.retires_host: a 500 on the first try
    is retryable.
    """
    fetcher = FakeFetcher({SEED: html_response(SEED, "", status=SERVER_ERROR)})
    _, _, walk = walked(tmp_path, fetcher)
    (attempt,) = walk.attempts
    assert attempt.retryable
    assert not settle_walk(attempt)
    assert walk.status is WalkStatus.walking


def test_rule_failure_SettleWalk_3(tmp_path: Path) -> None:
    """Verify rule SettleWalk is rejected when requires clause fails.

    requires: not wants_escalation or no next tier or the render added nothing: an http
    answer that needs rendering, on a walk whose tiers go on to the browser.
    """
    run, frontier = crawling(tmp_path, site())
    attempt = walk_with(
        run, frontier, (Tier.http, Tier.browser), html_response(SEED, NOSCRIPT_PAGE)
    )
    assert attempt.wants_escalation
    assert not settle_walk(attempt)
    assert attempt.walk.status is WalkStatus.walking


def test_rule_success_DisposeFetch(tmp_path: Path) -> None:
    """Verify rule DisposeFetch succeeds when all preconditions are met.

    The ok-HTML branch: an unblocked HTML answer for a URL with no known page counts as
    fetched for its host and raises PageFetched; the row stays in progress.
    """
    _, _, walk = settled(tmp_path, site())
    assert dispose_fetch(walk)
    assert walk.host.fetched == 1
    assert walk.entry.status is FrontierStatus.in_progress


def test_rule_failure_DisposeFetch_1(tmp_path: Path) -> None:
    """Verify rule DisposeFetch is rejected when requires clause fails.

    requires: walk.status = settled.
    """
    _, _, walk = walked(tmp_path, site())
    assert not dispose_fetch(walk)
    assert walk.host.fetched == 0


def test_rule_failure_DisposeFetch_2(tmp_path: Path) -> None:
    """Verify rule DisposeFetch is rejected when requires clause fails.

    requires: entry.status = in_progress.
    """
    _, _, walk = settled(tmp_path, site())
    walk.entry.status = FrontierStatus.done
    assert not dispose_fetch(walk)
    assert walk.host.fetched == 0


def test_rule_success_ConvertFetched(tmp_path: Path) -> None:
    """Verify rule ConvertFetched succeeds when all preconditions are met."""
    fetcher = site()
    run, _, walk = settled(tmp_path, fetcher)
    assert dispose_fetch(walk)
    candidate = convert_fetched(run, walk.entry, walk)
    assert candidate is not None
    assert candidate.run_id == run.id
    assert candidate.mirror is run.target
    assert candidate.requested_identity == SEED
    assert candidate.source_url == SEED
    assert candidate.redirect_hops == ()
    assert candidate.depth == 0
    assert candidate.outcome is CandidateOutcome.converted
    assert candidate.tier is Tier.http
    assert candidate.raw_digest == fetcher.responses[SEED].raw_digest
    assert candidate.content is not None
    assert candidate.content.title == "Getting started"
    assert QualityFlag.render_needed not in candidate.content.quality.flags
    assert run.target.pages == []  # delivered, not yet taken by the mirror


def test_rule_failure_ConvertFetched_1(tmp_path: Path) -> None:
    """Verify rule ConvertFetched is rejected when requires clause fails.

    requires: walk.status = settled and entry.status = in_progress.
    """
    run, _, walk = walked(tmp_path, site())
    assert convert_fetched(run, walk.entry, walk) is None
    (attempt,) = walk.attempts
    assert settle_walk(attempt)
    walk.entry.status = FrontierStatus.done
    assert convert_fetched(run, walk.entry, walk) is None


def test_render_needed_under_render_mode_never(tmp_path: Path) -> None:
    """A noscript notice under render_mode = never: the walk settles on http, flagged.

    ConvertFetched adds render_needed, and the stored page is low confidence.
    """
    result = crawl_once(tmp_path, site(page=NOSCRIPT_PAGE))
    (page,) = result.run.target.pages
    assert QualityFlag.render_needed in page.flags
    assert page.low_confidence


def test_rule_success_SettleStoredEntry(tmp_path: Path) -> None:
    """Verify rule SettleStoredEntry succeeds when all preconditions are met."""
    run, frontier, walk = settled(tmp_path, site())
    assert dispose_fetch(walk)
    delivered = convert_fetched(run, walk.entry, walk)
    assert delivered is not None
    candidate = admit_candidate(delivered)
    assert take_candidate(candidate, FixedClock()) is not None
    assert settle_stored_entry(frontier, candidate)
    assert walk.entry.status is FrontierStatus.done


def test_rule_failure_SettleStoredEntry_1(tmp_path: Path) -> None:
    """Verify rule SettleStoredEntry is rejected when requires clause fails.

    requires: exists entry and entry.status = in_progress.
    """
    run, frontier, walk = settled(tmp_path, site())
    assert dispose_fetch(walk)
    delivered = convert_fetched(run, walk.entry, walk)
    assert delivered is not None
    candidate = admit_candidate(delivered)
    take_candidate(candidate, FixedClock())
    walk.entry.status = FrontierStatus.skipped_robots
    assert not settle_stored_entry(frontier, candidate)
    assert walk.entry.status is FrontierStatus.skipped_robots
    frontier.entries.clear()
    assert not settle_stored_entry(frontier, candidate)


# --- Ending a run ------------------------------------------------------------------


def test_rule_success_FinishRun(tmp_path: Path) -> None:
    """Verify rule FinishRun succeeds when all preconditions are met.

    The unresolved snapshot holds a robots-skipped seed and nothing for a stored page.
    """
    fetcher = site(robots=text_response(ROBOTS, DISALLOW_GUIDE))
    run, frontier, entry = selected(tmp_path, fetcher)
    assert skip_robots_disallowed(run, entry)
    assert select_batch(run, frontier) == []
    assert finish_run(run, frontier)
    assert run.unresolved_urls == frozenset({SEED})

    stored = crawl_once(tmp_path / "stored", site())
    assert stored.run.unresolved_urls == frozenset()


def test_rule_failure_FinishRun_1(tmp_path: Path) -> None:
    """Verify rule FinishRun is rejected when requires clause fails.

    requires: run.status = running.
    """
    fetcher = site(robots=text_response(ROBOTS, DISALLOW_GUIDE))
    run, frontier, entry = selected(tmp_path, fetcher)
    assert skip_robots_disallowed(run, entry)
    run.status = RunStatus.finished
    assert not finish_run(run, frontier)
    assert run.unresolved_urls == frozenset()


def test_rule_success_EndRun(tmp_path: Path) -> None:
    """Verify rule EndRun succeeds when all preconditions are met.

    A run ends finished, or interrupted when an interrupt was requested.
    """
    later = START + timedelta(minutes=5)
    run, _ = started(tmp_path)
    assert end_run(run, FixedClock(later))
    assert run.status is RunStatus.finished
    assert run.finished_at == later

    interrupted, _ = started(tmp_path / "interrupted")
    interrupted.interrupt_requested = True
    assert end_run(interrupted, FixedClock(later))
    assert interrupted.status is RunStatus.interrupted
    assert interrupted.finished_at == later


def test_rule_failure_EndRun_1(tmp_path: Path) -> None:
    """Verify rule EndRun is rejected when requires clause fails.

    requires: run.status = running.
    """
    run, _ = started(tmp_path)
    run.status = RunStatus.interrupted
    assert not end_run(run, FixedClock())
    assert run.status is RunStatus.interrupted
    assert run.finished_at is None


def test_transition_edge_Run_running_finished(tmp_path: Path) -> None:
    """Verify transition running -> finished on Run.status is reachable via a witnessing rule."""
    result = crawl_once(tmp_path, site())
    assert result.run.status is RunStatus.finished


def test_transition_rejected_Run_status(tmp_path: Path) -> None:
    """Verify undeclared transitions on Run.status are rejected.

    finished -> running and finished -> interrupted are undeclared.
    """
    result = crawl_once(tmp_path, site())
    run = result.run
    run.interrupt_requested = True
    assert not end_run(run, FixedClock())
    assert run.status is RunStatus.finished
    assert not prepare_run(run, result.frontier)
    assert run.status is RunStatus.finished


def test_transition_terminal_Run_status(tmp_path: Path) -> None:
    """Verify terminal states on Run.status have no outbound transitions."""
    for status in (RunStatus.finished, RunStatus.interrupted):
        run, frontier = started(tmp_path / status.name)
        run.status = status
        assert not end_run(run, FixedClock())
        assert not finish_run(run, frontier)
        assert not begin_crawl(run)
        assert run.status is status


def test_when_presence_Run_finished_at(tmp_path: Path) -> None:
    """Verify Run.finished_at is present when status in {finished, interrupted} and absent otherwise."""  # noqa: E501  The obligation's description, quoted.
    run, _ = started(tmp_path)
    running_value = run.finished_at
    assert end_run(run, FixedClock())
    assert running_value is None
    assert run.finished_at == START


def test_transition_edge_FrontierEntry_pending_in_progress(tmp_path: Path) -> None:
    """Verify transition pending -> in_progress on FrontierEntry.status is reachable via a witnessing rule."""  # noqa: E501  The obligation's description, quoted.
    run, frontier = crawling(tmp_path, site())
    (entry,) = frontier.entries
    before = entry.status
    select_batch(run, frontier)
    assert (before, entry.status) == (FrontierStatus.pending, FrontierStatus.in_progress)


def test_transition_edge_FrontierEntry_pending_skipped_limit(tmp_path: Path) -> None:
    """Verify transition pending -> skipped_limit on FrontierEntry.status is reachable via a witnessing rule."""  # noqa: E501  The obligation's description, quoted.
    run, frontier = crawling(tmp_path, site())
    run.bytes_fetched = model.CONFIG.max_bytes
    assert select_batch(run, frontier) == []
    assert [entry.status for entry in frontier.entries] == [FrontierStatus.skipped_limit]
    assert run.budget_stopped


def test_transition_edge_FrontierEntry_in_progress_done(tmp_path: Path) -> None:
    """Verify transition in_progress -> done on FrontierEntry.status is reachable via a witnessing rule."""  # noqa: E501  The obligation's description, quoted.
    result = crawl_once(tmp_path, site())
    entry = result.frontier.entry(SEED)
    assert entry is not None
    assert entry.status is FrontierStatus.done


def test_transition_edge_FrontierEntry_in_progress_skipped_robots(tmp_path: Path) -> None:
    """Verify transition in_progress -> skipped_robots on FrontierEntry.status is reachable via a witnessing rule."""  # noqa: E501  The obligation's description, quoted.
    result = crawl_once(tmp_path, site(robots=text_response(ROBOTS, DISALLOW_GUIDE)))
    entry = result.frontier.entry(SEED)
    assert entry is not None
    assert entry.status is FrontierStatus.skipped_robots
    assert result.run.target.pages == []


def test_transition_rejected_FrontierEntry_status(tmp_path: Path) -> None:
    """Verify undeclared transitions on FrontierEntry.status are rejected.

    done -> in_progress and skipped_robots -> done are undeclared.
    """
    run, frontier = crawling(tmp_path, site())
    (entry,) = frontier.entries
    entry.status = FrontierStatus.done
    assert select_batch(run, frontier) == []
    assert entry.status is FrontierStatus.done
    entry.status = FrontierStatus.skipped_robots
    assert select_batch(run, frontier) == []
    assert entry.status is FrontierStatus.skipped_robots


# --- Invariants ---------------------------------------------------------------------


def test_invariant_Run_StandardRunsStayPolite(tmp_path: Path) -> None:
    """Verify invariant StandardRunsStayPolite holds after any field mutation on Run."""
    result = crawl_once(tmp_path, site())
    assert result.run.mode is RunMode.standard
    assert result.run.policy.is_standard
    assert not dataclasses.replace(standard_policy(), robots=RobotsMode.ignore).is_standard
    assert not dataclasses.replace(standard_policy(), rate_per_host=None).is_standard


def test_invariant_Run_StealthIsOwnerOnly(tmp_path: Path) -> None:
    """Verify invariant StealthIsOwnerOnly holds after any field mutation on Run."""
    never, _ = started(tmp_path / "never")
    assert never.usable_tiers == (Tier.http,)
    assert never.highest_tier is Tier.http
    stealthy, _ = started(
        tmp_path / "auto", render_mode=RenderMode.auto, stealth_mode=StealthMode.on
    )
    assert stealthy.usable_tiers == (Tier.http, Tier.browser)
    for run in (never, stealthy):
        assert Tier.stealth not in run.usable_tiers or run.mode is RunMode.owner_testing


def test_invariant_RobotsPolicy_OnlyParsedFilesCarryDirectives(tmp_path: Path) -> None:
    """Verify invariant OnlyParsedFilesCarryDirectives holds after any field mutation on RobotsPolicy."""  # noqa: E501  The obligation's description, quoted.
    parsed, _ = started(tmp_path / "parsed")
    open_host(parsed, HOST, SITE, site(robots=text_response(ROBOTS, RULES)))
    absent, _ = started(tmp_path / "absent")
    open_host(absent, HOST, SITE, site())
    policies = [*parsed.robots_policies, *absent.robots_policies]
    assert [policy.stance for policy in policies] == [RobotsStance.rules, RobotsStance.allow_all]
    for policy in policies:
        if policy.stance is not RobotsStance.rules:
            assert policy.crawl_delay is None
            assert policy.declared_sitemaps == ()


def test_invariant_Host_BlockedWithinFetched(tmp_path: Path) -> None:
    """Verify invariant BlockedWithinFetched holds after any field mutation on Host."""
    result = crawl_once(tmp_path, site())
    (host,) = result.run.hosts
    assert host.fetched == 1
    assert host.blocked <= host.fetched


def test_invariant_OneFrontierEntryPerIdentity(tmp_path: Path) -> None:
    """Verify invariant OneFrontierEntryPerIdentity holds after every state-changing rule that touches constrained entities."""  # noqa: E501  The obligation's description, quoted.
    run, frontier = crawling(tmp_path, site())
    enqueue(run, frontier, SEED, depth=0, via=DiscoverySource.start, priority=0)
    enqueue(run, frontier, SEED, depth=1, via=DiscoverySource.link, priority=0)
    identities = [entry.identity for entry in frontier.entries]
    assert identities == [SEED]


def test_invariant_OneFrontierPerMirror(tmp_path: Path) -> None:
    """Verify invariant OneFrontierPerMirror holds after every state-changing rule that touches constrained entities."""  # noqa: E501  The obligation's description, quoted.
    fetcher = site(robots=text_response(ROBOTS, DISALLOW_GUIDE))
    first = crawl_once(tmp_path, fetcher)
    persisted = load_frontier(first.run.target)
    assert persisted is not None
    second_run = start_run(request(first.run.target, run_id=SECOND_RUN), FixedClock())
    assert second_run is not None
    assert create_frontier(second_run, persisted) is None
    assert attach_frontier(second_run, persisted) is persisted
    assert [entry.identity for entry in persisted.entries] == [SEED]
    assert sorted(p.name for p in (tmp_path / ".rovo").glob("frontier*.json")) == ["frontier.json"]


def test_invariant_RunIdentityIsUnique(tmp_path: Path) -> None:
    """Verify invariant RunIdentityIsUnique holds after every state-changing rule that touches constrained entities."""  # noqa: E501  The obligation's description, quoted.
    fetcher = site(robots=text_response(ROBOTS, DISALLOW_GUIDE))
    mirror = new_mirror(tmp_path)
    assert next_run_id(tmp_path) == 1
    for _ in range(SECOND_RUN):
        run_id = next_run_id(tmp_path)
        run_crawl(request(mirror, run_id=run_id), load_frontier(mirror), fetcher, FixedClock())
    ids = [record.id for record in load_runs(tmp_path)]
    assert ids == [1, SECOND_RUN]
    assert next_run_id(tmp_path) == THIRD_RUN
    assert (tmp_path / ".rovo" / "runs.json").is_file()


def test_invariant_OneHostPerNamePerRun(tmp_path: Path) -> None:
    """Verify invariant OneHostPerNamePerRun holds after every state-changing rule that touches constrained entities."""  # noqa: E501  The obligation's description, quoted.
    fetcher = site()
    run, _, entry = selected(tmp_path, fetcher)
    open_host(run, HOST, SITE, fetcher)
    open_host_for_entry(run, entry, fetcher)
    names = [host.name for host in run.hosts]
    assert names == [HOST]


def test_invariant_OneRobotsPolicyPerOrigin(tmp_path: Path) -> None:
    """Verify invariant OneRobotsPolicyPerOrigin holds after every state-changing rule that touches constrained entities.

    Two origins of one host each hold one policy (T12); reading either again adds none.
    """  # noqa: E501  The obligation's description, quoted.
    fetcher = site(robots=text_response(ROBOTS, RULES))
    run, _ = started(tmp_path)
    open_host(run, HOST, SITE, fetcher)
    fetch_robots(run, HOST, SITE, fetcher)
    fetch_robots(run, HOST, PORTED, fetcher)
    fetch_robots(run, HOST, PORTED, fetcher)
    origins = [policy.origin for policy in run.robots_policies]
    assert origins == [SITE, PORTED]
    assert fetcher.requests == [ROBOTS, PORTED_ROBOTS]


# --- Fields, values and derived values ------------------------------------------------


def test_entity_fields_Run(tmp_path: Path) -> None:
    """Verify all declared fields on Run are present with correct types."""
    result = crawl_once(tmp_path, site())
    run = result.run
    assert_fields(
        run,
        (
            "target",
            "operator",
            "id",
            "kind",
            "mode",
            "baseline",
            "preceding",
            "scope_hash",
            "owned_hosts",
            "requested_owner_test",
            "policy",
            "dry_run",
            "interactive",
            "render_mode",
            "stealth_mode",
            "max_age",
            "targets",
            "forced_refetch",
            "active_urls",
            "unresolved_urls",
            "error",
            "interrupt_requested",
            "crawling",
            "budget_stopped",
            "bytes_fetched",
            "fetch_attempts",
            "started_at",
            "status",
            "finished_at",
            "hosts",
        ),
    )
    assert run.tripped_hosts == []
    assert run.has_tripped_host is False
    assert run.targeted is False
    assert run.is_owner_testing is False
    assert run.usable_tiers == (Tier.http,)
    assert run.highest_tier is Tier.http
    assert run.page_budget_remaining == model.CONFIG.max_pages - run.fetch_attempts
    assert run.byte_budget_left is True
    assert run.fetch_attempts == 1
    assert run.bytes_fetched == site().responses[SEED].size


def test_entity_fields_Frontier(tmp_path: Path) -> None:
    """Verify all declared fields on Frontier are present with correct types."""
    run, frontier, entry = selected(tmp_path, site())
    assert frontier.mirror is run.target
    assert frontier.entries == [entry]
    assert frontier.observed_urls == []
    assert frontier.pending_entries == []
    assert frontier.in_progress_entries == [entry]
    assert frontier.retry_entries == []
    entry.status = FrontierStatus.failed
    assert frontier.retry_entries == [entry]
    assert frontier.batch_idle is True


def test_entity_fields_FrontierEntry(tmp_path: Path) -> None:
    """Verify all declared fields on FrontierEntry are present with correct types."""
    _, frontier, entry = selected(tmp_path, site())
    assert_fields(
        entry,
        (
            "frontier",
            "identity",
            "depth",
            "discovered_via",
            "discovered_from",
            "sitemap_lastmod",
            "priority",
            "attempts",
            "status",
        ),
    )
    assert entry.frontier is frontier
    assert entry.host_name == HOST
    assert entry.is_deferred is False


def test_entity_fields_Host(tmp_path: Path) -> None:
    """Verify all declared fields on Host are present with correct types."""
    result = crawl_once(tmp_path, site())
    (host,) = result.run.hosts
    assert_fields(
        host,
        (
            "run",
            "name",
            "origin",
            "rate",
            "crawl_delay",
            "paused_until",
            "recent_text_lengths",
            "tiers_used",
            "fetched",
            "blocked",
            "render_escalations",
            "retry_after_honored",
            "sitemap_children_read",
            "sitemap_entries_admitted",
            "breaker",
            "median_text",
            "has_text_baseline",
        ),
    )
    assert host.tiers_used == frozenset({Tier.http})
    assert host.breaker_tripped is False
    assert host.block_rate == 0
    assert host.has_text_baseline is False


def test_entity_fields_RobotsPolicy(tmp_path: Path) -> None:
    """Verify all declared fields on RobotsPolicy are present with correct types."""
    run, _ = started(tmp_path)
    open_host(run, HOST, SITE, site(robots=text_response(ROBOTS, RULES)))
    (policy,) = run.robots_policies
    assert_fields(
        policy, ("run", "origin", "stance", "crawl_delay", "declared_sitemaps", "problem")
    )
    assert isinstance(policy.declared_sitemaps, tuple)
    assert isinstance(policy.crawl_delay, timedelta)


def test_value_equality_CrawlPolicy() -> None:
    """Verify value type CrawlPolicy has structural equality."""
    assert standard_policy() == standard_policy()
    assert hash(standard_policy()) == hash(standard_policy())
    assert standard_policy() != dataclasses.replace(standard_policy(), honor_crawl_delay=False)


def test_entity_fields_CrawlPolicy() -> None:
    """Verify all declared fields on CrawlPolicy are present with correct types.

    The standard policy: every control enabled, robots respected, crawl's defaults.
    """
    policy = standard_policy()
    assert policy.robots is RobotsMode.respect
    assert policy.honor_crawl_delay is True
    assert policy.rate_per_host == model.CONFIG.rate_per_host
    assert policy.concurrency_per_host == model.CONFIG.concurrency_per_host
    assert policy.retry_backoff is True
    assert policy.backoff_base == model.CONFIG.backoff_base
    assert policy.max_backoff == model.CONFIG.max_backoff
    assert policy.honor_retry_after is True
    assert policy.retry_after_cap == model.CONFIG.retry_after_cap
    assert policy.breaker_enabled is True
    assert policy.breaker_pause == model.CONFIG.breaker_pause
    assert policy.protection_escalation is False
    assert policy.interactive_challenges is False
    assert policy.challenge_timeout == model.CONFIG.owner_challenge_timeout
    assert policy.is_standard is True


def test_value_equality_SiteResponse() -> None:
    """Verify value type SiteResponse has structural equality."""
    first = html_response(SEED, PAGE)
    again = html_response(SEED, PAGE)
    assert first == again
    assert hash(first) == hash(again)
    assert first.raw_digest == again.raw_digest
    changed = html_response(SEED, PAGE + "\n")
    assert first != changed
    assert first.raw_digest != changed.raw_digest


def test_entity_fields_SiteResponse() -> None:
    """Verify all declared fields on SiteResponse are present with correct types.

    And the derived predicates that rules read instead of the status code.
    """
    ok = html_response(SEED, PAGE)
    assert_fields(
        ok,
        (
            "status",
            "error",
            "source_url",
            "redirect_hops",
            "redirect_location",
            "redirect_stop",
            "markup",
            "content_type",
            "retry_after",
            "etag",
            "last_modified",
            "size",
            "main_text",
        ),
    )
    assert ok.ok
    assert ok.is_html
    assert not ok.not_modified
    assert not ok.unfollowed_redirect
    assert not ok.redirected_out
    assert not ok.absent
    assert not ok.access_refused
    assert not ok.server_error
    assert not ok.retryable
    assert len(ok.raw_digest) == len("0" * 64)
    assert ok.raw_digest == ok.raw_digest.lower()
    assert not_found(SEED).absent
    assert text_response(ROBOTS, "", status=FORBIDDEN).access_refused
    assert html_response(SEED, "", status=SERVER_ERROR).server_error
    assert html_response(SEED, "", status=SERVER_ERROR).retryable
    assert not text_response(ROBOTS, RULES).is_html
    failed = SiteResponse(status=0, source_url=SEED, markup="", size=0, error="timed out")
    assert not failed.ok
    assert failed.retryable


def test_derived_Run_byte_budget_left(tmp_path: Path) -> None:
    """Verify derived value Run.byte_budget_left computes correctly."""
    run, _ = started(tmp_path)
    assert run.byte_budget_left
    run.bytes_fetched = model.CONFIG.max_bytes - 1
    assert run.byte_budget_left
    run.bytes_fetched = model.CONFIG.max_bytes
    assert not run.byte_budget_left


def test_derived_Frontier_batch_idle(tmp_path: Path) -> None:
    """Verify derived value Frontier.batch_idle computes correctly."""
    run, frontier = crawling(tmp_path, site())
    idle_before = frontier.batch_idle
    select_batch(run, frontier)
    assert idle_before is True
    assert frontier.batch_idle is False

    # T10: idle again between batches, once the seed is stored and its links queued.
    run, frontier, found = stored_seed(tmp_path / "links", links_site())
    assert enqueue_page_links(run, frontier, found) is not None
    assert frontier.batch_idle is True
    assert next_batch(run, frontier)
    assert select_batch(run, frontier)
    assert frontier.batch_idle is False


def test_derived_FrontierEntry_is_deferred(tmp_path: Path) -> None:
    """Verify derived value FrontierEntry.is_deferred computes correctly."""
    run, frontier = started(tmp_path)
    entry = enqueue(
        run,
        frontier,
        SEED,
        depth=0,
        via=DiscoverySource.recheck,
        priority=model.CONFIG.deferred_priority,
    )
    deferred = entry.is_deferred
    entry.priority = 0
    assert deferred is True
    assert entry.is_deferred is False


# --- The HttpxFetcher, through httpx.MockTransport ----------------------------------


class Recorder:
    """A MockTransport handler that records each request and answers from a function."""

    def __init__(self, status: int = 200, headers: dict[str, str] | None = None) -> None:
        """Answer every request with `status` and `headers`."""
        self.requests: list[httpx.Request] = []
        self.status = status
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Record the request and answer it."""
        self.requests.append(request)
        return httpx.Response(self.status, headers=self.headers, text=PAGE)


def test_httpx_fetcher_one_request_per_fetch_with_the_rovo_user_agent() -> None:
    """One fetch is one request, sending `User-Agent: rovo/<version>` (crawl.allium 1534)."""
    recorder = Recorder()
    with HttpxFetcher(transport=httpx.MockTransport(recorder)) as fetcher:
        response = fetcher.fetch(SEED)
    assert len(recorder.requests) == 1
    agent = recorder.requests[0].headers["user-agent"]
    assert agent == f"rovo/{importlib.metadata.version('rovo')}"
    assert response.ok
    assert response.markup == PAGE
    assert response.source_url == SEED
    assert response.size == len(PAGE.encode())
    assert response.content_type == "text/html; charset=utf-8"


def test_httpx_fetcher_returns_a_redirect_unfollowed() -> None:
    """A 3xx answer comes back as it is: one request, no redirect followed."""
    recorder = Recorder(MOVED, {"location": OTHER})
    with HttpxFetcher(transport=httpx.MockTransport(recorder)) as fetcher:
        response = fetcher.fetch(SEED)
    assert len(recorder.requests) == 1
    assert response.status == MOVED
    assert not response.ok


def test_httpx_fetcher_uses_the_configured_timeout() -> None:
    """Every phase of a request is bounded by config.fetch_timeout."""
    recorder = Recorder()
    with HttpxFetcher(transport=httpx.MockTransport(recorder)) as fetcher:
        fetcher.fetch(SEED)
    timeout = recorder.requests[0].extensions["timeout"]
    seconds = model.CONFIG.fetch_timeout.total_seconds()
    assert timeout == {"connect": seconds, "read": seconds, "write": seconds, "pool": seconds}


def test_httpx_fetcher_maps_a_transport_error_to_status_zero() -> None:
    """A transport error is a response with status 0 and the error set, never an exception."""

    def refuse(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    with HttpxFetcher(transport=httpx.MockTransport(refuse)) as fetcher:
        response = fetcher.fetch(SEED)
    assert response.status == 0
    assert response.error
    assert not response.ok
    assert response.retryable


def test_httpx_fetcher_closes_its_client() -> None:
    """The client is closed when the run's fetcher is closed."""
    fetcher = HttpxFetcher(transport=httpx.MockTransport(Recorder()))
    with fetcher:
        assert not fetcher.is_closed
    assert fetcher.is_closed


# --- Config -------------------------------------------------------------------------


def test_config_default_max_pages() -> None:
    """Verify config parameter max_pages has its declared default."""
    assert model.CONFIG.max_pages == spec_int("crawl", "max_pages")


def test_config_default_max_bytes() -> None:
    """Verify config parameter max_bytes has its declared default."""
    assert model.CONFIG.max_bytes == spec_int("crawl", "max_bytes")


def test_config_default_start_priority() -> None:
    """Verify config parameter start_priority has its declared default."""
    assert model.CONFIG.start_priority == spec_int("crawl", "start_priority")


def test_config_default_recheck_priority() -> None:
    """Verify config parameter recheck_priority has its declared default."""
    assert model.CONFIG.recheck_priority == spec_int("crawl", "recheck_priority")


def test_config_default_deferred_priority() -> None:
    """Verify config parameter deferred_priority has its declared default."""
    assert model.CONFIG.deferred_priority == spec_int("crawl", "deferred_priority")


def test_config_default_batch_lookahead() -> None:
    """Verify config parameter batch_lookahead has its declared default."""
    assert model.CONFIG.batch_lookahead == spec_int("crawl", "batch_lookahead")


def test_config_default_rate_per_host() -> None:
    """Verify config parameter rate_per_host has its declared default."""
    assert model.CONFIG.rate_per_host == spec_float("crawl", "rate_per_host")


def test_config_default_concurrency_per_host() -> None:
    """Verify config parameter concurrency_per_host has its declared default."""
    assert model.CONFIG.concurrency_per_host == spec_int("crawl", "concurrency_per_host")


def test_config_default_fetch_timeout() -> None:
    """Verify config parameter fetch_timeout has its declared default."""
    assert model.CONFIG.fetch_timeout == spec_duration("crawl", "fetch_timeout")


def test_config_default_observed_url_retention_syncs() -> None:
    """Verify config parameter observed_url_retention_syncs has its declared default."""
    expected = spec_int("crawl", "observed_url_retention_syncs")
    assert model.CONFIG.observed_url_retention_syncs == expected


# --- Following links (T10) ----------------------------------------------------------


def test_rule_success_EnqueuePageLinks(tmp_path: Path) -> None:
    """Verify rule EnqueuePageLinks succeeds when all preconditions are met.

    Each content then navigation target the scope allows at depth + 1 is discovered at
    depth + 1 with the link priority, from the page; the self-link, the off-prefix page
    and the foreign host are not. Robots is the fetch's business, not discovery's.
    """
    run, frontier, found = stored_seed(tmp_path, links_site())
    assert found.targets
    assert found.navigation_targets == (B_PAGE,)
    enqueued = enqueue_page_links(run, frontier, found)
    assert enqueued is not None
    added = frontier.entries[1:]
    assert [entry.identity for entry in added] == [B_PAGE, C_PAGE, SECRET_PAGE]
    for entry in added:
        assert entry.depth == 1
        assert entry.discovered_via is DiscoverySource.link
        assert entry.discovered_from == SEED
        assert entry.priority == model.CONFIG.link_priority
        assert entry.status is FrontierStatus.pending
        assert entry.identity in run.active_urls
    assert {entry.identity for entry in enqueued} == {B_PAGE, C_PAGE, SECRET_PAGE}
    identities = {entry.identity for entry in frontier.entries}
    assert OUTSIDE_PAGE not in identities
    assert not any("example.invalid" in identity for identity in identities)
    assert frontier.entry(SEED) is not None
    assert len(frontier.entries) == len([SEED, B_PAGE, C_PAGE, SECRET_PAGE])


def test_EnqueuePageLinks_navigation_only_and_depth_bound(tmp_path: Path) -> None:
    """A navigation-only target is discovered via navigation; past max_depth, none is."""
    run, frontier, found = stored_seed(tmp_path, links_site())
    navigation = dataclasses.replace(found, targets=(), navigation_targets=(C_PAGE,))
    enqueue_page_links(run, frontier, navigation)
    row = frontier.entry(C_PAGE)
    assert row is not None
    assert row.discovered_via is DiscoverySource.navigation
    assert row.depth == 1

    deep = dataclasses.replace(
        found, depth=run.target.scope.max_depth, targets=(D_PAGE,), navigation_targets=()
    )
    enqueue_page_links(run, frontier, deep)
    assert frontier.entry(D_PAGE) is None


def test_rule_failure_EnqueuePageLinks_1(tmp_path: Path) -> None:
    """Verify rule EnqueuePageLinks is rejected when requires clause fails.

    requires: exists run and run.status = running.
    """
    run, frontier, found = stored_seed(tmp_path, links_site())
    before = list(frontier.entries)
    assert enqueue_page_links(None, frontier, found) is None
    run.status = RunStatus.finished
    assert enqueue_page_links(run, frontier, found) is None
    assert frontier.entries == before


def test_config_default_link_priority() -> None:
    """Verify config parameter link_priority has its declared default."""
    assert model.CONFIG.link_priority == spec_int("crawl", "link_priority")


def test_projection_Frontier_pending_entries(tmp_path: Path) -> None:
    """Verify projection Frontier.pending_entries filters correctly.

    After the seed's batch, the rows its links queued are the pending ones.
    """
    run, frontier, found = stored_seed(tmp_path, links_site())
    assert frontier.pending_entries == []
    enqueue_page_links(run, frontier, found)
    pending = frontier.pending_entries
    assert [entry.identity for entry in pending] == [B_PAGE, C_PAGE, SECRET_PAGE]
    assert all(entry.status is FrontierStatus.pending for entry in pending)
    seed = frontier.entry(SEED)
    assert seed is not None
    assert seed.status is FrontierStatus.done
    assert seed not in pending


def test_projection_Frontier_in_progress_entries(tmp_path: Path) -> None:
    """Verify projection Frontier.in_progress_entries filters correctly.

    The second batch puts the depth-1 rows in progress; the settled seed is not among them.
    """
    run, frontier, found = stored_seed(tmp_path, links_site())
    assert frontier.in_progress_entries == []
    enqueue_page_links(run, frontier, found)
    batch = select_batch(run, frontier)
    assert batch
    assert frontier.in_progress_entries == batch
    assert {entry.identity for entry in batch} <= {B_PAGE, C_PAGE, SECRET_PAGE}
    assert all(entry.status is FrontierStatus.in_progress for entry in batch)


# --- Robots and politeness (T12) ------------------------------------------------------


def unreachable(url: str) -> SiteResponse:
    """A transport failure: no response arrived."""
    return SiteResponse(status=0, source_url=url, markup="", size=0, error="connection refused")


def answered(url: str, status: int, *, retry_after: timedelta | None = None) -> SiteResponse:
    """An HTML answer with `status` and an optional Retry-After."""
    return dataclasses.replace(html_response(url, "", status=status), retry_after=retry_after)


def scripted(
    *scripts: tuple[str, list[SiteResponse]], robots: SiteResponse | None = None
) -> ScriptedFetcher:
    """The fixture site's seed page, answered first from `scripts`."""
    responses = {SEED: html_response(SEED, PAGE)}
    if robots is not None:
        responses[ROBOTS] = robots
    return ScriptedFetcher(responses, dict(scripts))


def attempt_on(
    walk: LadderWalk, response: SiteResponse, *, tier: Tier = Tier.http, try_: int = 1
) -> FetchAttempt:
    """A FetchAttempt of `walk` answering `response`, unblocked, appended to the walk."""
    attempt = FetchAttempt(
        walk=walk,
        tier=tier,
        try_=try_,
        response=response,
        verdict=BlockVerdict(kind=BlockKind.none, signature=""),
        render_reason=None,
    )
    walk.attempts.append(attempt)
    return attempt


def settled_on(
    run: Run, frontier: Frontier, response: SiteResponse, *, identity: str = SEED
) -> LadderWalk:
    """A settled walk of the identity's in-progress row, its only attempt standing."""
    entry = enqueue(run, frontier, identity, depth=0, via=DiscoverySource.start, priority=0)
    entry.status = FrontierStatus.in_progress
    host = run.host(hostname_of(identity))
    assert host is not None
    walk = LadderWalk(
        entry=entry,
        host=host,
        tiers=(Tier.http,),
        conditional=False,
        escalated=False,
        challenge_offered=False,
        status=WalkStatus.settled,
    )
    walk.standing = attempt_on(walk, response)
    return walk


def exhausted(out_dir: Path, response: SiteResponse) -> tuple[Run, Frontier, LadderWalk]:
    """The seed's walk settled on its last http try, answering `response`."""
    run, frontier, walk = walked(out_dir, scripted((SEED, [response])))
    last = attempt_on(walk, response, try_=model.CONFIG.http_attempts)
    assert not last.retryable
    assert settle_walk(last)
    assert walk.standing is last
    return run, frontier, walk


def in_progress(run: Run, frontier: Frontier, url: str) -> FrontierEntry:
    """The url's row, in progress, as SelectBatch leaves it."""
    entry = enqueue(run, frontier, url, depth=1, via=DiscoverySource.link, priority=0)
    entry.status = FrontierStatus.in_progress
    return entry


def jitter_bounds(wait: timedelta) -> tuple[timedelta, timedelta]:
    """The wait scaled down and up by backoff_jitter."""
    jitter = model.CONFIG.backoff_jitter
    return wait * (1 - jitter), wait * (1 + jitter)


def test_enum_comparable_RobotsMode() -> None:
    """Verify fields typed with enum RobotsMode are comparable."""
    assert tuple(mode.value for mode in RobotsMode) == spec_enum("crawl", "RobotsMode")
    policy = standard_policy()
    assert policy.robots == RobotsMode.respect
    assert len(set(RobotsMode)) == len(spec_enum("crawl", "RobotsMode"))
    assert dataclasses.replace(policy, robots=RobotsMode.ignore).robots is RobotsMode.ignore


def test_enum_comparable_RobotsStance(tmp_path: Path) -> None:
    """Verify fields typed with enum RobotsStance are comparable.

    Each stance a robots.txt answer resolves to compares equal to its own member only.
    """
    assert tuple(stance.value for stance in RobotsStance) == spec_enum("crawl", "RobotsStance")
    stances = []
    for name, robots in (
        ("rules", text_response(ROBOTS, RULES)),
        ("absent", not_found(ROBOTS)),
        ("refused", text_response(ROBOTS, "", status=FORBIDDEN)),
    ):
        run, _ = started(tmp_path / name)
        open_host(run, HOST, SITE, site(robots=robots))
        policy = run.robots_policy(SITE)
        assert policy is not None
        stances.append(policy.stance)
    assert stances == [RobotsStance.rules, RobotsStance.allow_all, RobotsStance.disallow_all]
    assert stances[0] != stances[1] != stances[2] != stances[0]


def test_enum_comparable_DiscoveryProblem(tmp_path: Path) -> None:
    """Verify fields typed with enum DiscoveryProblem are comparable."""
    declared = spec_enum("crawl", "DiscoveryProblem")
    assert tuple(problem.value for problem in DiscoveryProblem) == declared
    problems = []
    for name, robots in (
        ("refused", text_response(ROBOTS, "", status=FORBIDDEN)),
        ("unreachable", unreachable(ROBOTS)),
    ):
        run, _ = started(tmp_path / name)
        open_host(run, HOST, SITE, site(robots=robots))
        policy = run.robots_policy(SITE)
        assert policy is not None
        problems.append(policy.problem)
    assert problems == [DiscoveryProblem.robots_refused, DiscoveryProblem.robots_unreachable]
    assert problems[0] != problems[1]


def test_entity_optional_RobotsPolicy_crawl_delay(tmp_path: Path) -> None:
    """Verify optional field RobotsPolicy.crawl_delay accepts null and non-null values.

    Null for an absent file and for a group with no Crawl-delay; a decimal duration when
    the group declares one.
    """
    absent, _ = started(tmp_path / "absent")
    open_host(absent, HOST, SITE, site())
    plain, _ = started(tmp_path / "plain")
    open_host(plain, HOST, SITE, site(robots=text_response(ROBOTS, DISALLOW_GUIDE)))
    half, _ = started(tmp_path / "half")
    open_host(half, HOST, SITE, site(robots=text_response(ROBOTS, HALF_DELAY)))
    delays = [run.robots_policy(SITE) for run in (absent, plain, half)]
    assert [policy.crawl_delay if policy else "missing" for policy in delays] == [
        None,
        None,
        timedelta(seconds=0.5),
    ]


def test_entity_optional_RobotsPolicy_problem(tmp_path: Path) -> None:
    """Verify optional field RobotsPolicy.problem accepts null and non-null values."""
    parsed, _ = started(tmp_path / "parsed")
    open_host(parsed, HOST, SITE, site(robots=text_response(ROBOTS, RULES)))
    refused, _ = started(tmp_path / "refused")
    open_host(refused, HOST, SITE, site(robots=text_response(ROBOTS, "", status=FORBIDDEN)))
    rules = parsed.robots_policy(SITE)
    denied = refused.robots_policy(SITE)
    assert rules is not None
    assert denied is not None
    assert rules.problem is None
    assert denied.problem is DiscoveryProblem.robots_refused


def test_entity_optional_Host_rate(tmp_path: Path) -> None:
    """Verify optional field Host.rate accepts null and non-null values.

    A standard run's host has a rate. With the rate control disabled (owner testing, on
    unit inputs) the host's rate is null and stays null under a Crawl-delay, which still
    sets its crawl_delay: disabling one control never disables another.
    """
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, site())
    assert host is not None
    assert host.rate == run.policy.rate_per_host
    assert host.rate is not None

    unlimited = dataclasses.replace(standard_policy(), rate_per_host=None)
    free, _ = started(tmp_path / "free", policy=unlimited)
    unpaced = open_host(free, HOST, SITE, site(robots=text_response(ROBOTS, RULES)))
    assert unpaced is not None
    assert unpaced.rate is None
    assert unpaced.crawl_delay == CRAWL_DELAY


def test_entity_optional_Host_paused_until(tmp_path: Path) -> None:
    """Verify optional field Host.paused_until accepts null and non-null values.

    Null when the host opens; an instant once HttpRetry pauses it.
    """
    fetcher = scripted((SEED, [answered(SEED, SERVICE_UNAVAILABLE)]))
    _, _, walk = walked(tmp_path, fetcher)
    host = walk.host
    assert host.paused_until is None
    backed_off = http_retry(walk.attempts[0], fetcher)
    assert backed_off is not None
    assert host.paused_until == backed_off.until
    assert backed_off.until > START


def test_entity_relationship_Host_breaker(tmp_path: Path) -> None:
    """Verify relationship Host.breaker navigates to the correct related entities.

    The host's breaker is the one Breaker with host = this, and the outcome of the host's
    settled walk is fed to it: a seed that never answers counts once.
    """
    fetcher = FakeFetcher({SEED: unreachable(SEED)})
    result = crawl_once(tmp_path, fetcher)
    (host,) = result.run.hosts
    breaker = host.breaker
    assert breaker is not None
    assert breaker.host is host
    assert breaker.outcomes == [True]
    assert breaker.since_escalation == 1


def test_entity_fields_FetchAttempt(tmp_path: Path) -> None:
    """Verify all declared fields on FetchAttempt are present with correct types."""
    _, _, walk = walked(tmp_path, site())
    (attempt,) = walk.attempts
    assert_fields(
        attempt,
        (
            "walk",
            "tier",
            "try_",
            "response",
            "verdict",
            "render_reason",
            "retires_host",
            "retryable",
            "challenges",
            "unsuccessful_challenge",
            "failed_outright",
            "wants_escalation",
        ),
    )
    assert attempt.walk is walk
    assert attempt.tier is Tier.http
    assert attempt.try_ == 1
    assert isinstance(attempt.response, SiteResponse)
    assert isinstance(attempt.verdict, BlockVerdict)
    assert attempt.retires_host is False
    assert attempt.retryable is False
    assert attempt.failed_outright is False
    assert attempt.wants_escalation is False
    assert list(getattr(attempt, "challenges", ["missing"])) == []
    assert getattr(attempt, "unsuccessful_challenge", None) is False


def test_invariant_FetchAttempt_TriesBounded(tmp_path: Path) -> None:
    """Verify invariant TriesBounded holds after any field mutation on FetchAttempt.

    A seed that answers 503 every time is tried http_attempts times, the tries counted
    from 1, every one at the http tier; then no further try is made.
    """
    fetcher = scripted(robots=None)
    fetcher.responses[SEED] = answered(SEED, SERVICE_UNAVAILABLE)
    _, _, walk = walked(tmp_path, fetcher)
    while walk.attempts[-1].retryable:
        assert http_retry(walk.attempts[-1], fetcher) is not None
    assert http_retry(walk.attempts[-1], fetcher) is None
    tries = [attempt.try_ for attempt in walk.attempts]
    assert tries == list(range(1, model.CONFIG.http_attempts + 1))
    for attempt in walk.attempts:
        assert 1 <= attempt.try_ <= model.CONFIG.http_attempts
        assert attempt.tier is Tier.http
    assert fetcher.count(SEED) == model.CONFIG.http_attempts


def test_derived_FetchAttempt_retryable(tmp_path: Path) -> None:
    """Verify derived value FetchAttempt.retryable computes correctly.

    An http error, 429 or 5xx before the last try, unless it retires the host.
    """
    _, _, walk = walked(tmp_path, site())
    last = model.CONFIG.http_attempts
    cap = standard_policy().retry_after_cap
    cases = [
        (answered(SEED, SERVICE_UNAVAILABLE), Tier.http, 1, True),
        (answered(SEED, TOO_MANY), Tier.http, last - 1, True),
        (unreachable(SEED), Tier.http, 1, True),
        (answered(SEED, SERVER_ERROR), Tier.http, last, False),
        (html_response(SEED, PAGE), Tier.http, 1, False),
        (answered(SEED, FORBIDDEN), Tier.http, 1, False),
        (answered(SEED, SERVICE_UNAVAILABLE), Tier.browser, 1, False),
        (answered(SEED, TOO_MANY, retry_after=cap + timedelta(seconds=1)), Tier.http, 1, False),
    ]
    for response, tier, try_, expected in cases:
        attempt = attempt_on(walk, response, tier=tier, try_=try_)
        assert attempt.retryable is expected, (response.status, tier, try_)


def test_derived_FetchAttempt_retires_host(tmp_path: Path) -> None:
    """Verify derived value FetchAttempt.retires_host computes correctly.

    An http answer worth a retry whose Retry-After is past retry_after_cap, while
    Retry-After is honoured; on any try.
    """
    _, _, walk = walked(tmp_path, site())
    cap = standard_policy().retry_after_cap
    past = cap + timedelta(seconds=1)
    last = model.CONFIG.http_attempts
    cases = [
        (answered(SEED, TOO_MANY, retry_after=past), Tier.http, 1, True),
        (answered(SEED, SERVICE_UNAVAILABLE, retry_after=past), Tier.http, last, True),
        (answered(SEED, TOO_MANY, retry_after=cap), Tier.http, 1, False),
        (answered(SEED, TOO_MANY), Tier.http, 1, False),
        (dataclasses.replace(html_response(SEED, PAGE), retry_after=past), Tier.http, 1, False),
        (answered(SEED, TOO_MANY, retry_after=past), Tier.browser, 1, False),
    ]
    for response, tier, try_, expected in cases:
        attempt = attempt_on(walk, response, tier=tier, try_=try_)
        assert attempt.retires_host is expected, (response.status, response.retry_after, tier)
    walk.host.run.policy = dataclasses.replace(standard_policy(), honor_retry_after=False)
    ignored = attempt_on(walk, answered(SEED, TOO_MANY, retry_after=past))
    assert ignored.retires_host is False


def test_derived_FetchAttempt_failed_outright(tmp_path: Path) -> None:
    """Verify derived value FetchAttempt.failed_outright computes correctly.

    An error, or status 0; any status the site sent is an answer, whatever it says.
    """
    _, _, walk = walked(tmp_path, site())
    no_status = SiteResponse(status=0, source_url=SEED, markup="", size=0)
    assert attempt_on(walk, unreachable(SEED)).failed_outright is True
    assert attempt_on(walk, no_status).failed_outright is True
    for status in (SERVER_ERROR, SERVICE_UNAVAILABLE, TOO_MANY, FORBIDDEN):
        assert attempt_on(walk, answered(SEED, status)).failed_outright is False
    assert attempt_on(walk, html_response(SEED, PAGE)).failed_outright is False


def test_entity_fields_Breaker(tmp_path: Path) -> None:
    """Verify all declared fields on Breaker are present with correct types."""
    result = crawl_once(tmp_path, site())
    (host,) = result.run.hosts
    breaker = host.breaker
    assert breaker is not None
    assert_fields(
        breaker,
        (
            "host",
            "tier",
            "highest_tier",
            "outcomes",
            "escalations",
            "since_escalation",
            "status",
            "block_rate",
            "over_threshold",
            "should_act",
        ),
    )
    assert breaker.host is host
    assert breaker.tier is Tier.http
    assert breaker.highest_tier is Tier.http
    assert breaker.outcomes == [False]
    assert breaker.escalations == 0
    assert breaker.since_escalation == 1
    assert breaker.status is BreakerStatus.watching
    assert breaker.block_rate == 0
    assert breaker.over_threshold is False
    assert breaker.should_act is False


def test_invariant_Breaker_WindowBounded(tmp_path: Path) -> None:
    """Verify invariant WindowBounded holds after any field mutation on Breaker.

    The window keeps the last breaker_window outcomes however many walks settle; the
    host's text history likewise keeps the last host_text_history sizes.
    """
    run, frontier = crawling(tmp_path, site())
    host = run.host(HOST)
    assert host is not None
    assert host.breaker is not None
    window = model.CONFIG.breaker_window
    history = model.CONFIG.host_text_history
    walks = max(window, history) + 3
    for number in range(walks):
        url = f"{SITE}/guide/p{number}.html"
        response = dataclasses.replace(html_response(url, PAGE), main_text=number + 1)
        assert feed_breaker(settled_on(run, frontier, response, identity=url))
        assert len(host.breaker.outcomes) <= window
        assert len(host.recent_text_lengths) <= history
    assert host.breaker.outcomes == [False] * window
    assert host.breaker.since_escalation == walks
    assert host.recent_text_lengths == list(range(walks - history + 1, walks + 1))


def test_derived_Breaker_over_threshold(tmp_path: Path) -> None:
    """Verify derived value Breaker.over_threshold computes correctly.

    At least min(breaker_window, breaker_min_outcomes) outcomes, and a share of counted
    outcomes strictly above block_rate_threshold.
    """
    run, _ = crawling(tmp_path, site())
    host = run.host(HOST)
    assert host is not None
    breaker = host.breaker
    assert breaker is not None
    needed = min(model.CONFIG.breaker_window, model.CONFIG.breaker_min_outcomes)
    threshold = model.CONFIG.block_rate_threshold
    at_threshold = round(needed * threshold)
    assert at_threshold / needed == threshold
    windows = [
        [True] * (needed - 1),  # too few outcomes, every one a block
        [True] * at_threshold + [False] * (needed - at_threshold),  # at the threshold
        [True] * (at_threshold + 1) + [False] * (needed - at_threshold - 1),  # above it
        [],
    ]
    seen = []
    for outcomes in windows:
        breaker.outcomes = outcomes
        seen.append((breaker.block_rate, breaker.over_threshold))
    assert seen == [
        (1, False),
        (threshold, False),
        ((at_threshold + 1) / needed, True),
        (0, False),
    ]


def test_projection_Frontier_retry_entries(tmp_path: Path) -> None:
    """Verify projection Frontier.retry_entries filters correctly.

    Exactly the failed, blocked, skipped_robots, skipped_blocked and skipped_limit rows.
    """
    run, frontier = started(tmp_path)
    for status in FrontierStatus:
        enqueue(
            run,
            frontier,
            f"{SITE}/guide/{status.value}.html",
            depth=1,
            via=DiscoverySource.link,
            priority=0,
        ).status = status
    retried = {entry.status for entry in frontier.retry_entries}
    assert retried == {
        FrontierStatus.failed,
        FrontierStatus.blocked,
        FrontierStatus.skipped_robots,
        FrontierStatus.skipped_blocked,
        FrontierStatus.skipped_limit,
    }
    assert len(frontier.retry_entries) == len(retried)


def test_transition_edge_FrontierEntry_in_progress_failed(tmp_path: Path) -> None:
    """Verify transition in_progress -> failed on FrontierEntry.status is reachable via a witnessing rule.

    A seed answering 503 on every try runs out of tries: DisposeFetch raises EntryFailed
    and EntryFails sets the row failed and raises UrlFailed with the tries made.
    """  # noqa: E501  The obligation's description, quoted.
    fetcher = scripted(robots=None)
    fetcher.responses[SEED] = answered(SEED, SERVICE_UNAVAILABLE)
    result = crawl_once(tmp_path, fetcher)
    entry = result.frontier.entry(SEED)
    assert entry is not None
    assert entry.status is FrontierStatus.failed
    assert entry.attempts == 1
    (failed,) = result.failed
    assert failed.url == SEED
    assert failed.error
    assert failed.attempts == model.CONFIG.http_attempts
    assert fetcher.count(SEED) == model.CONFIG.http_attempts
    assert result.run.fetch_attempts == model.CONFIG.http_attempts


def test_transition_edge_FrontierEntry_failed_pending(tmp_path: Path) -> None:
    """Verify transition failed -> pending on FrontierEntry.status is reachable via a witnessing rule.

    A row a run failed is re-pended by the next run's PrepareRun.
    """  # noqa: E501  The obligation's description, quoted.
    fetcher = FakeFetcher({SEED: unreachable(SEED)})
    first = crawl_once(tmp_path, fetcher)
    entry = first.frontier.entry(SEED)
    assert entry is not None
    assert entry.status is FrontierStatus.failed
    persisted = load_frontier(first.run.target)
    assert persisted is not None
    second = start_run(request(first.run.target, run_id=SECOND_RUN), FixedClock())
    assert second is not None
    assert prepare_run(second, persisted)
    row = persisted.entry(SEED)
    assert row is not None
    assert row.status is FrontierStatus.pending


def test_transition_edge_FrontierEntry_skipped_robots_pending(tmp_path: Path) -> None:
    """Verify transition skipped_robots -> pending on FrontierEntry.status is reachable via a witnessing rule.

    A seed skipped because its origin's robots.txt was refused is re-pended by the next
    run's PrepareRun, which reads robots.txt again.
    """  # noqa: E501  The obligation's description, quoted.
    fetcher = site(robots=text_response(ROBOTS, "", status=FORBIDDEN))
    first = crawl_once(tmp_path, fetcher)
    assert fetcher.requests == [ROBOTS]
    entry = first.frontier.entry(SEED)
    assert entry is not None
    assert entry.status is FrontierStatus.skipped_robots
    persisted = load_frontier(first.run.target)
    assert persisted is not None
    second = start_run(request(first.run.target, run_id=SECOND_RUN), FixedClock())
    assert second is not None
    assert prepare_run(second, persisted)
    row = persisted.entry(SEED)
    assert row is not None
    assert row.status is FrontierStatus.pending


def test_config_default_http_attempts() -> None:
    """Verify config parameter http_attempts has its declared default."""
    assert model.CONFIG.http_attempts == spec_int("crawl", "http_attempts")


def test_config_default_backoff_base() -> None:
    """Verify config parameter backoff_base has its declared default."""
    assert model.CONFIG.backoff_base == spec_duration("crawl", "backoff_base")
    assert standard_policy().backoff_base == model.CONFIG.backoff_base


def test_config_default_max_backoff() -> None:
    """Verify config parameter max_backoff has its declared default."""
    assert model.CONFIG.max_backoff == spec_duration("crawl", "max_backoff")
    assert standard_policy().max_backoff == model.CONFIG.max_backoff


def test_config_default_backoff_jitter() -> None:
    """Verify config parameter backoff_jitter has its declared default."""
    assert model.CONFIG.backoff_jitter == spec_float("crawl", "backoff_jitter")


def test_config_default_retry_after_cap() -> None:
    """Verify config parameter retry_after_cap has its declared default."""
    assert model.CONFIG.retry_after_cap == spec_duration("crawl", "retry_after_cap")
    assert standard_policy().retry_after_cap == model.CONFIG.retry_after_cap


def test_config_default_breaker_window() -> None:
    """Verify config parameter breaker_window has its declared default."""
    assert model.CONFIG.breaker_window == spec_int("crawl", "breaker_window")


def test_config_default_breaker_min_outcomes() -> None:
    """Verify config parameter breaker_min_outcomes has its declared default."""
    assert model.CONFIG.breaker_min_outcomes == spec_int("crawl", "breaker_min_outcomes")


def test_config_default_block_rate_threshold() -> None:
    """Verify config parameter block_rate_threshold has its declared default."""
    assert model.CONFIG.block_rate_threshold == spec_float("crawl", "block_rate_threshold")


def test_config_default_host_text_history() -> None:
    """Verify config parameter host_text_history has its declared default."""
    assert model.CONFIG.host_text_history == spec_int("crawl", "host_text_history")


def test_rule_success_DenyAllWhenRobotsRefused(tmp_path: Path) -> None:
    """Verify rule DenyAllWhenRobotsRefused succeeds when all preconditions are met.

    A 401, 403 or 429 or a 5xx robots.txt is disallow-all for its origin and raises
    DiscoveryFailed; through the driver the seed is skipped unrequested and the run
    returns the DiscoveryFailed.
    """
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, site(robots=text_response(ROBOTS, "", status=FORBIDDEN)))
    assert host is not None
    policy = run.robots_policy(SITE)
    assert policy is not None
    assert policy.stance is RobotsStance.disallow_all
    assert not robots_allows(run, SEED)
    for status in (401, FORBIDDEN, TOO_MANY, SERVER_ERROR, SERVICE_UNAVAILABLE):
        run.robots_policies.clear()
        failed = deny_all_when_robots_refused(run, host, text_response(ROBOTS, "", status=status))
        assert failed == DiscoveryFailed(
            run=run, url=ROBOTS, problem=DiscoveryProblem.robots_refused
        ), status
        assert not robots_allows(run, SEED)

    fetcher = site(robots=text_response(ROBOTS, "", status=FORBIDDEN))
    result = crawl_once(tmp_path / "driven", fetcher)
    assert fetcher.requests == [ROBOTS]
    assert result.discovery_failed == (
        DiscoveryFailed(run=result.run, url=ROBOTS, problem=DiscoveryProblem.robots_refused),
    )
    entry = result.frontier.entry(SEED)
    assert entry is not None
    assert entry.status is FrontierStatus.skipped_robots


def test_rule_failure_DenyAllWhenRobotsRefused_1(tmp_path: Path) -> None:
    """Verify rule DenyAllWhenRobotsRefused is rejected when requires clause fails.

    requires: not response.ok.
    """
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, site())
    assert host is not None
    run.robots_policies.clear()
    assert deny_all_when_robots_refused(run, host, text_response(ROBOTS, RULES)) is None
    assert run.robots_policies == []


def test_rule_failure_DenyAllWhenRobotsRefused_2(tmp_path: Path) -> None:
    """Verify rule DenyAllWhenRobotsRefused is rejected when requires clause fails.

    requires: response.access_refused or response.server_error.
    """
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, site())
    assert host is not None
    run.robots_policies.clear()
    for response in (
        not_found(ROBOTS),
        text_response(ROBOTS, "", status=410),
        unreachable(ROBOTS),
    ):
        assert deny_all_when_robots_refused(run, host, response) is None
    assert run.robots_policies == []


def test_rule_entity_creation_DenyAllWhenRobotsRefused_1(tmp_path: Path) -> None:
    """Verify entity creation in rule DenyAllWhenRobotsRefused ensures clause produces the specified fields.

    For the origin RobotsAnswered names, here a second port of the host.
    """  # noqa: E501  The obligation's description, quoted.
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, site())
    assert host is not None
    refused = text_response(PORTED_ROBOTS, "", status=SERVER_ERROR)
    failed = deny_all_when_robots_refused(run, host, refused, origin=PORTED)
    assert failed == DiscoveryFailed(
        run=run, url=PORTED_ROBOTS, problem=DiscoveryProblem.robots_refused
    )
    policy = run.robots_policy(PORTED)
    assert policy is not None
    assert policy.run is run
    assert policy.origin == PORTED
    assert policy.stance is RobotsStance.disallow_all
    assert policy.crawl_delay is None
    assert policy.declared_sitemaps == ()
    assert policy.problem is DiscoveryProblem.robots_refused
    allowed = run.robots_policy(SITE)
    assert allowed is not None
    assert allowed.stance is RobotsStance.allow_all


def test_rule_success_DenyAllWhenRobotsUnreachable(tmp_path: Path) -> None:
    """Verify rule DenyAllWhenRobotsUnreachable succeeds when all preconditions are met.

    A robots.txt that never answers is tried http_attempts times, then is disallow-all
    for its origin with a DiscoveryFailed; no robots.txt try counts as a fetch attempt.
    """
    fetcher = site(robots=unreachable(ROBOTS))
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, fetcher)
    assert host is not None
    assert fetcher.requests == [ROBOTS] * model.CONFIG.http_attempts
    assert run.fetch_attempts == 0
    policy = run.robots_policy(SITE)
    assert policy is not None
    assert policy.stance is RobotsStance.disallow_all
    assert policy.problem is DiscoveryProblem.robots_unreachable
    assert not robots_allows(run, SEED)

    run.robots_policies.clear()
    failed = deny_all_when_robots_unreachable(run, host, unreachable(ROBOTS))
    assert failed == DiscoveryFailed(
        run=run, url=ROBOTS, problem=DiscoveryProblem.robots_unreachable
    )

    driven = site(robots=unreachable(ROBOTS))
    result = crawl_once(tmp_path / "driven", driven)
    assert SEED not in driven.requests
    assert result.discovery_failed == (
        DiscoveryFailed(run=result.run, url=ROBOTS, problem=DiscoveryProblem.robots_unreachable),
    )


def test_rule_failure_DenyAllWhenRobotsUnreachable_1(tmp_path: Path) -> None:
    """Verify rule DenyAllWhenRobotsUnreachable is rejected when requires clause fails.

    requires: not response.ok.
    """
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, site())
    assert host is not None
    run.robots_policies.clear()
    assert deny_all_when_robots_unreachable(run, host, text_response(ROBOTS, RULES)) is None
    assert run.robots_policies == []


def test_rule_failure_DenyAllWhenRobotsUnreachable_2(tmp_path: Path) -> None:
    """Verify rule DenyAllWhenRobotsUnreachable is rejected when requires clause fails.

    requires: response.error != null.
    """
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, site())
    assert host is not None
    run.robots_policies.clear()
    for status in (FORBIDDEN, SERVER_ERROR, NOT_FOUND):
        response = text_response(ROBOTS, "", status=status)
        assert deny_all_when_robots_unreachable(run, host, response) is None
    assert run.robots_policies == []


def test_rule_entity_creation_DenyAllWhenRobotsUnreachable_1(tmp_path: Path) -> None:
    """Verify entity creation in rule DenyAllWhenRobotsUnreachable ensures clause produces the specified fields."""  # noqa: E501  The obligation's description, quoted.
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, site())
    assert host is not None
    failed = deny_all_when_robots_unreachable(run, host, unreachable(PORTED_ROBOTS), origin=PORTED)
    assert failed == DiscoveryFailed(
        run=run, url=PORTED_ROBOTS, problem=DiscoveryProblem.robots_unreachable
    )
    policy = run.robots_policy(PORTED)
    assert policy is not None
    assert policy.run is run
    assert policy.origin == PORTED
    assert policy.stance is RobotsStance.disallow_all
    assert policy.crawl_delay is None
    assert policy.declared_sitemaps == ()
    assert policy.problem is DiscoveryProblem.robots_unreachable


def test_rule_failure_SkipRobotsDisallowed_4(tmp_path: Path) -> None:
    """Verify rule SkipRobotsDisallowed is rejected when requires clause fails.

    requires: exists RobotsPolicy{run: run, origin: origin_of(entry.identity)}. The host's
    first origin disallows /guide/, but a row on its second origin, whose robots.txt is
    unread, is not judged by the first origin's file.
    """
    run, frontier = crawling(tmp_path, site(robots=text_response(ROBOTS, DISALLOW_GUIDE)))
    entry = in_progress(run, frontier, PORTED_PAGE)
    assert run.robots_policy(PORTED) is None
    assert not skip_robots_disallowed(run, entry)
    assert entry.status is FrontierStatus.in_progress


def test_rule_success_ReadRobotsForNewOrigin(tmp_path: Path) -> None:
    """Verify rule ReadRobotsForNewOrigin succeeds when all preconditions are met.

    A row on a known host at an unread origin reads that origin's robots.txt before its
    first page there; the host is not opened again.
    """
    fetcher = site(robots=text_response(ROBOTS, RULES))
    fetcher.responses[PORTED_ROBOTS] = text_response(PORTED_ROBOTS, DISALLOW_GUIDE)
    run, frontier = crawling(tmp_path, fetcher)
    entry = in_progress(run, frontier, PORTED_PAGE)
    assert read_robots_for_new_origin(run, entry, fetcher)
    assert fetcher.requests == [*DISCOVERY, PORTED_ROBOTS]
    assert [host.name for host in run.hosts] == [HOST]
    policy = run.robots_policy(PORTED)
    assert policy is not None
    assert policy.stance is RobotsStance.rules
    assert not robots_allows(run, PORTED_PAGE)
    assert robots_allows(run, SEED)
    assert skip_robots_disallowed_on_new_host(run, entry)
    assert entry.status is FrontierStatus.skipped_robots


def test_rule_failure_ReadRobotsForNewOrigin_1(tmp_path: Path) -> None:
    """Verify rule ReadRobotsForNewOrigin is rejected when requires clause fails.

    requires: exists run.
    """
    fetcher = site()
    run, frontier = crawling(tmp_path, fetcher)
    entry = in_progress(run, frontier, PORTED_PAGE)
    assert not read_robots_for_new_origin(None, entry, fetcher)
    run.status = RunStatus.finished
    assert not read_robots_for_new_origin(run, entry, fetcher)
    assert fetcher.requests == DISCOVERY
    assert run.robots_policy(PORTED) is None


def test_rule_failure_ReadRobotsForNewOrigin_2(tmp_path: Path) -> None:
    """Verify rule ReadRobotsForNewOrigin is rejected when requires clause fails.

    requires: exists host and not host.breaker_tripped.
    """
    fetcher = site()
    run, frontier, _ = crawling_without_hosts(tmp_path)
    entry = in_progress(run, frontier, PORTED_PAGE)
    assert not read_robots_for_new_origin(run, entry, fetcher)
    assert fetcher.requests == []

    tripped_fetcher = site()
    tripped, tripped_frontier = crawling(tmp_path / "tripped", tripped_fetcher)
    host = tripped.host(HOST)
    assert host is not None
    assert host.breaker is not None
    host.breaker.status = BreakerStatus.tripped
    row = in_progress(tripped, tripped_frontier, PORTED_PAGE)
    assert not read_robots_for_new_origin(tripped, row, tripped_fetcher)
    assert tripped_fetcher.requests == DISCOVERY
    assert tripped.robots_policy(PORTED) is None


def test_rule_failure_ReadRobotsForNewOrigin_3(tmp_path: Path) -> None:
    """Verify rule ReadRobotsForNewOrigin is rejected when requires clause fails.

    requires: not exists RobotsPolicy{run: run, origin: origin_of(entry.identity)}.
    """
    fetcher = site()
    run, _, entry = selected(tmp_path, fetcher)
    assert not read_robots_for_new_origin(run, entry, fetcher)
    assert fetcher.requests == DISCOVERY
    assert [policy.origin for policy in run.robots_policies] == [SITE]


def test_rule_failure_ProceedWithKnownHost_4(tmp_path: Path) -> None:
    """Verify rule ProceedWithKnownHost is rejected when requires clause fails.

    requires: exists RobotsPolicy{run: run, origin: origin_of(entry.identity)}. The host's
    first origin allows everything; a row on its unread second origin does not proceed.
    """
    run, frontier = crawling(tmp_path, site())
    entry = in_progress(run, frontier, PORTED_PAGE)
    assert run.robots_policy(PORTED) is None
    assert not proceed_with_known_host(run, entry)
    assert not robots_allows(run, PORTED_PAGE)


def test_rule_success_HttpRetry(tmp_path: Path) -> None:
    """Verify rule HttpRetry succeeds when all preconditions are met.

    The host is paused until now + retry_wait (backoff_base on the first try, within
    backoff_jitter; at least a Retry-After on a 503), HostBackedOff is raised, the next
    http try is made at try + 1, and the host's rate is never raised.
    """
    fetcher = scripted((SEED, [answered(SEED, SERVICE_UNAVAILABLE)]))
    run, _, walk = walked(tmp_path, fetcher)
    host = walk.host
    rate = host.rate
    (first,) = walk.attempts
    backed_off = http_retry(first, fetcher)
    assert backed_off is not None
    assert backed_off.host is host
    low, high = jitter_bounds(run.policy.backoff_base)
    assert START + low <= backed_off.until <= START + high
    assert host.paused_until == backed_off.until
    second = walk.attempts[-1]
    assert second is not first
    assert second.tier is Tier.http
    assert second.try_ == first.try_ + 1
    assert second.response.ok
    assert fetcher.count(SEED) == TWO_TRIES
    assert run.fetch_attempts == TWO_TRIES
    assert host.rate == rate

    wait = timedelta(seconds=40)
    later = scripted((SEED, [answered(SEED, SERVICE_UNAVAILABLE, retry_after=wait)]))
    _, _, waited = walked(tmp_path / "retry-after", later)
    lengthened = http_retry(waited.attempts[0], later)
    assert lengthened is not None
    assert lengthened.until >= START + wait
    assert waited.host.paused_until == lengthened.until


def test_rule_failure_HttpRetry_1(tmp_path: Path) -> None:
    """Verify rule HttpRetry is rejected when requires clause fails.

    requires: attempt.retryable.
    """
    fetcher = scripted()
    _, _, walk = walked(tmp_path, fetcher)
    (attempt,) = walk.attempts
    assert not attempt.retryable
    assert http_retry(attempt, fetcher) is None
    assert walk.host.paused_until is None
    assert walk.attempts == [attempt]
    assert fetcher.count(SEED) == 1


def test_rule_failure_HttpRetry_2(tmp_path: Path) -> None:
    """Verify rule HttpRetry is rejected when requires clause fails.

    requires: attempt.walk.status = walking and attempt.walk.host.run.status = running.
    """
    fetcher = scripted(robots=None)
    fetcher.responses[SEED] = answered(SEED, SERVICE_UNAVAILABLE)
    run, _, walk = walked(tmp_path, fetcher)
    (attempt,) = walk.attempts
    assert attempt.retryable
    walk.status = WalkStatus.settled
    assert http_retry(attempt, fetcher) is None
    walk.status = WalkStatus.walking
    run.status = RunStatus.interrupted
    assert http_retry(attempt, fetcher) is None
    assert walk.host.paused_until is None
    assert walk.attempts == [attempt]
    assert fetcher.count(SEED) == 1


def test_rule_success_CountRetryAfter(tmp_path: Path) -> None:
    """Verify rule CountRetryAfter succeeds when all preconditions are met.

    An http attempt whose retryable answer (a 429 or any 5xx) carries a Retry-After,
    while honoured, counts once: every honoured Retry-After is counted (crawl.allium
    ecfa257), a 500 and a 502 as much as a 429 or a 503.
    """
    _, _, walk = walked(tmp_path, site())
    host = walk.host
    wait = timedelta(seconds=4)
    statuses = (SERVICE_UNAVAILABLE, TOO_MANY, SERVER_ERROR, BAD_GATEWAY)
    for counted, status in enumerate(statuses, start=1):
        assert count_retry_after(attempt_on(walk, answered(SEED, status, retry_after=wait)))
        assert host.retry_after_honored == counted, status


def test_rule_failure_CountRetryAfter_1(tmp_path: Path) -> None:
    """Verify rule CountRetryAfter is rejected when requires clause fails.

    requires: attempt.walk.host.run.status = running.
    """
    run, _, walk = walked(tmp_path, site())
    attempt = attempt_on(
        walk, answered(SEED, SERVICE_UNAVAILABLE, retry_after=timedelta(seconds=4))
    )
    run.status = RunStatus.finished
    assert not count_retry_after(attempt)
    assert walk.host.retry_after_honored == 0


def test_rule_failure_CountRetryAfter_2(tmp_path: Path) -> None:
    """Verify rule CountRetryAfter is rejected when requires clause fails.

    requires: attempt.tier = http.
    """
    _, _, walk = walked(tmp_path, site())
    response = answered(SEED, SERVICE_UNAVAILABLE, retry_after=timedelta(seconds=4))
    assert not count_retry_after(attempt_on(walk, response, tier=Tier.browser))
    assert walk.host.retry_after_honored == 0


def test_rule_failure_CountRetryAfter_3(tmp_path: Path) -> None:
    """Verify rule CountRetryAfter is rejected when requires clause fails.

    requires: attempt.response.retry_after != null and attempt.response.retryable.
    A retryable answer with no Retry-After, and a Retry-After on an answer that is not
    retryable (a 200, a 404), count nothing.
    """
    _, _, walk = walked(tmp_path, site())
    wait = timedelta(seconds=4)
    for response in (
        answered(SEED, SERVICE_UNAVAILABLE),
        answered(SEED, SERVER_ERROR),
        dataclasses.replace(html_response(SEED, PAGE), retry_after=wait),
        dataclasses.replace(not_found(SEED), retry_after=wait),
    ):
        assert not count_retry_after(attempt_on(walk, response)), response.status
    assert walk.host.retry_after_honored == 0


def test_rule_failure_CountRetryAfter_4(tmp_path: Path) -> None:
    """Verify rule CountRetryAfter is rejected when requires clause fails.

    requires: attempt.walk.host.run.policy.honor_retry_after (off only in owner testing,
    here on unit inputs).
    """
    run, _, walk = walked(tmp_path, site())
    run.policy = dataclasses.replace(standard_policy(), honor_retry_after=False)
    attempt = attempt_on(walk, answered(SEED, TOO_MANY, retry_after=timedelta(seconds=4)))
    assert not count_retry_after(attempt)
    assert walk.host.retry_after_honored == 0


def test_rule_success_FeedBreaker(tmp_path: Path) -> None:
    """Verify rule FeedBreaker succeeds when all preconditions are met.

    A walk that failed outright counts as a block; an ok unblocked page does not, and its
    main text joins the host's text history. Every settled walk adds to since_escalation.
    """
    run, frontier = crawling(tmp_path, site())
    host = run.host(HOST)
    assert host is not None
    breaker = host.breaker
    assert breaker is not None
    assert feed_breaker(settled_on(run, frontier, unreachable(SEED)))
    assert breaker.outcomes == [True]
    assert breaker.since_escalation == 1
    assert host.recent_text_lengths == []
    text = 120
    other = f"{SITE}/guide/other.html"
    ok = dataclasses.replace(html_response(other, PAGE), main_text=text)
    assert feed_breaker(settled_on(run, frontier, ok, identity=other))
    assert breaker.outcomes == [True, False]
    assert breaker.since_escalation == TWO_TRIES
    assert host.recent_text_lengths == [text]
    failed = f"{SITE}/guide/failed.html"
    assert feed_breaker(settled_on(run, frontier, answered(failed, SERVER_ERROR), identity=failed))
    assert breaker.outcomes == [True, False, False]
    assert host.recent_text_lengths == [text]


def test_rule_failure_FeedBreaker_1(tmp_path: Path) -> None:
    """Verify rule FeedBreaker is rejected when requires clause fails.

    requires: walk.status = settled.
    """
    run, frontier = crawling(tmp_path, site())
    walk = settled_on(run, frontier, unreachable(SEED))
    walk.status = WalkStatus.walking
    assert not feed_breaker(walk)
    assert walk.host.breaker is not None
    assert walk.host.breaker.outcomes == []
    assert walk.host.breaker.since_escalation == 0


def test_rule_failure_FeedBreaker_2(tmp_path: Path) -> None:
    """Verify rule FeedBreaker is rejected when requires clause fails.

    requires: exists breaker and breaker.status = watching.
    """
    run, frontier = crawling(tmp_path, site())
    walk = settled_on(run, frontier, unreachable(SEED))
    breaker = walk.host.breaker
    assert breaker is not None
    breaker.status = BreakerStatus.tripped
    assert not feed_breaker(walk)
    assert breaker.outcomes == []
    walk.host.breaker = None
    assert not feed_breaker(walk)
    assert walk.host.recent_text_lengths == []


def test_rule_failure_FeedBreaker_3(tmp_path: Path) -> None:
    """Verify rule FeedBreaker is rejected when requires clause fails.

    requires: host.run.policy.breaker_enabled (off only in owner testing, here on unit
    inputs).
    """
    run, frontier = crawling(tmp_path, site())
    run.policy = dataclasses.replace(standard_policy(), breaker_enabled=False)
    walk = settled_on(run, frontier, unreachable(SEED))
    assert not feed_breaker(walk)
    assert walk.host.breaker is not None
    assert walk.host.breaker.outcomes == []
    assert walk.host.breaker.since_escalation == 0


def test_rule_success_EntryFails(tmp_path: Path) -> None:
    """Verify rule EntryFails succeeds when all preconditions are met.

    A walk settled on a transport failure: DisposeFetch raises EntryFailed with the error
    and the try, and EntryFails sets the row failed and raises UrlFailed. A 5xx that ran
    out of tries fails the same way, with its status text as the error.
    """
    run, _, walk = exhausted(tmp_path, unreachable(SEED))
    failed = dispose_fetch(walk)
    assert isinstance(failed, EntryFailed)
    assert failed.run is run
    assert failed.entry is walk.entry
    assert failed.error == "connection refused"
    assert failed.attempts == model.CONFIG.http_attempts
    url_failed = entry_fails(failed)
    assert url_failed is not None
    assert walk.entry.status is FrontierStatus.failed
    assert url_failed.run is run
    assert url_failed.url == SEED
    assert url_failed.error == "connection refused"
    assert url_failed.attempts == model.CONFIG.http_attempts
    assert walk.host.fetched == 0

    _, _, server = exhausted(tmp_path / "server", answered(SEED, SERVICE_UNAVAILABLE))
    status_failed = dispose_fetch(server)
    assert isinstance(status_failed, EntryFailed)
    assert status_failed.error  # status_text(response): a black box, its wording unpinned
    assert status_failed.error != "no response"
    assert status_failed.attempts == model.CONFIG.http_attempts
    assert entry_fails(status_failed) is not None
    assert server.entry.status is FrontierStatus.failed


def test_rule_failure_EntryFails_1(tmp_path: Path) -> None:
    """Verify rule EntryFails is rejected when requires clause fails.

    requires: entry.status = in_progress.
    """
    _, _, walk = exhausted(tmp_path, unreachable(SEED))
    failed = dispose_fetch(walk)
    assert isinstance(failed, EntryFailed)
    walk.entry.status = FrontierStatus.done
    assert entry_fails(failed) is None
    assert walk.entry.status is FrontierStatus.done


def test_invariant_HostRateNeverRises(tmp_path: Path) -> None:
    """Verify invariant HostRateNeverRises holds after every state-changing rule that touches constrained entities.

    Across many robots.txt adoptions on several origins of one host, and a retry, the
    rate only falls, never above rate_per_host: a Crawl-delay of 3 lowers it to 1/3; a
    shorter or zero delay read later does not raise it again.
    """  # noqa: E501  The obligation's description, quoted.
    rate = standard_policy().rate_per_host
    assert rate is not None
    delays = ("0.25", "3", "0", "1", "0.5")
    origins = [f"http://docs.example:{8000 + index}" for index in range(len(delays))]
    fetcher = scripted((SEED, [answered(SEED, SERVICE_UNAVAILABLE)]))
    for origin, delay in zip(origins, delays, strict=True):
        fetcher.responses[f"{origin}/robots.txt"] = text_response(
            f"{origin}/robots.txt", f"User-agent: *\nCrawl-delay: {delay}\n"
        )
    run, _, walk = walked(tmp_path, fetcher)
    host = walk.host
    seen = [host.rate]
    for origin in origins:
        fetch_robots(run, HOST, origin, fetcher)
        seen.append(host.rate)
    assert http_retry(walk.attempts[0], fetcher) is not None
    seen.append(host.rate)
    rates = [value for value in seen if value is not None]
    assert len(rates) == len(seen)
    assert all(value <= rate for value in rates)
    assert rates == sorted(rates, reverse=True)
    assert host.rate == min(rate, 1 / 3)
    assert host.crawl_delay == timedelta(seconds=3)


def test_surface_exposure_SiteExchange(tmp_path: Path) -> None:
    """Verify each exposed item on SiteExchange is accessible.

    What the site sees of one run's host: its name, the rate and Crawl-delay robots.txt
    set, its pause, tiers, tallies and the Retry-Afters it honoured.
    """
    fetcher = scripted(
        (SEED, [answered(SEED, SERVICE_UNAVAILABLE, retry_after=timedelta(seconds=4))]),
        robots=text_response(ROBOTS, RULES),
    )
    result = crawl_once(tmp_path, fetcher)
    (host,) = result.run.hosts
    rate = result.run.policy.rate_per_host
    assert rate is not None
    exposed = {
        "name": host.name,
        "rate": host.rate,
        "crawl_delay": host.crawl_delay,
        "tiers_used": host.tiers_used,
        "fetched": host.fetched,
        "blocked": host.blocked,
        "block_rate": host.block_rate,
        "render_escalations": host.render_escalations,
        "retry_after_honored": host.retry_after_honored,
    }
    assert exposed == {
        "name": HOST,
        "rate": min(rate, 1 / CRAWL_DELAY.total_seconds()),
        "crawl_delay": CRAWL_DELAY,
        "tiers_used": frozenset({Tier.http}),
        "fetched": 1,
        "blocked": 0,
        "block_rate": 0,
        "render_escalations": 0,
        "retry_after_honored": 1,
    }
    assert host.paused_until is not None
    assert host.paused_until >= START + timedelta(seconds=4)


# --- Discovery from sitemaps and llms.txt (T13) -----------------------------------------

MAPS = f"{SITE}/maps/guide.xml"
MAPS_INDEX = f"{SITE}/maps/index.xml"
ORPHAN = f"{SITE}/guide/orphan.html"
FROM_LLMS = f"{SITE}/guide/from-llms.html"
RELATIVE = f"{SITE}/guide/relative.html"
OUT_OF_SCOPE = f"{SITE}/outside/page.html"
OFF_HOST_MAP = "http://elsewhere.example/maps/child.xml"
PORTED_MAP = f"{PORTED}/maps/guide.xml"
NO_IDENTITY_MAP = f"{SITE}:99999/maps/guide.xml"
LASTMOD = "2026-10-01"
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def urlset(*entries: tuple[str, str | None]) -> str:
    """A sitemap urlset naming each (loc, lastmod)."""
    rows = "".join(
        f"    <url>\n        <loc>{loc}</loc>\n"
        + ("" if lastmod is None else f"        <lastmod>{lastmod}</lastmod>\n")
        + "    </url>\n"
        for loc, lastmod in entries
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="{SITEMAP_NS}">\n{rows}</urlset>\n'
    )


def sitemapindex(*locs: str) -> str:
    """A sitemap index naming each child sitemap."""
    rows = "".join(f"    <sitemap>\n        <loc>{loc}</loc>\n    </sitemap>\n" for loc in locs)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="{SITEMAP_NS}">\n'
        f"{rows}</sitemapindex>\n"
    )


def declaring(*sitemaps: str, disallow: str = "/guide/private/") -> SiteResponse:
    """A robots.txt that disallows `disallow` and declares each sitemap, in order."""
    lines = "".join(f"Sitemap: {url}\n" for url in sitemaps)
    return text_response(ROBOTS, f"User-agent: *\nDisallow: {disallow}\n{lines}")


def llms(*links: str) -> SiteResponse:
    """An llms.txt with one inline Markdown link per URL."""
    body = "".join(f"- [Page {n}]({url})\n" for n, url in enumerate(links, start=1))
    return text_response(LLMS_TXT, f"# Example docs\n\n{body}")


def observation(frontier: Frontier, url: str) -> ObservedUrl | None:
    """ObservedUrl{frontier: frontier, url: url}, or None."""
    return next((seen for seen in frontier.observed_urls if seen.url == url), None)


def host_open(
    out_dir: Path, fetcher: FakeFetcher, **changes: object
) -> tuple[Run, Frontier, Host]:
    """A prepared run whose host docs.example is open and its robots.txt answered."""
    run, frontier = started(out_dir, **changes)
    assert prepare_run(run, frontier)
    host = open_host(run, HOST, SITE, fetcher)
    assert host is not None
    return run, frontier, host


def dry(out_dir: Path) -> tuple[Run, Frontier]:
    """A running dry run with a new frontier."""
    mirror = new_mirror(out_dir)
    run = start_run(dataclasses.replace(request(mirror), dry_run=True), FixedClock())
    assert run is not None
    frontier = create_frontier(run, None)
    assert frontier is not None
    return run, frontier


def refuse_every_sitemap(monkeypatch: pytest.MonkeyPatch) -> None:
    """sitemap_admitted false for every sitemap, wherever the crawl looks it up."""

    def refuse(url: str, profile: object, scope: object) -> bool:
        del url, profile, scope
        return False

    monkeypatch.setattr(sitemaps, "sitemap_admitted", refuse)
    monkeypatch.setattr(run_module, "sitemap_admitted", refuse, raising=False)


def replace_config(monkeypatch: pytest.MonkeyPatch, **changes: object) -> None:
    """Replace crawl's CONFIG in every loaded module that binds it (Facts)."""
    original = model.CONFIG
    replaced = dataclasses.replace(original, **changes)  # type: ignore[arg-type]  # Test overrides by name.
    for module in list(sys.modules.values()):
        if getattr(module, "CONFIG", None) is original:
            monkeypatch.setattr(module, "CONFIG", replaced)


def discovered(out_dir: Path, fetcher: FakeFetcher) -> tuple[Run, Frontier]:
    """A run through Discover over `fetcher`."""
    run, frontier = started(out_dir)
    assert prepare_run(run, frontier)
    assert discover(run, frontier, fetcher)
    return run, frontier


def test_value_equality_SitemapEntry() -> None:
    """Verify value type SitemapEntry has structural equality."""
    entry = SitemapEntry(loc=ORPHAN, lastmod=LASTMOD)
    assert entry == SitemapEntry(loc=ORPHAN, lastmod=LASTMOD)
    assert hash(entry) == hash(SitemapEntry(loc=ORPHAN, lastmod=LASTMOD))
    assert entry != SitemapEntry(loc=ORPHAN, lastmod=None)
    assert entry != SitemapEntry(loc=OTHER, lastmod=LASTMOD)
    read = sitemaps.sitemap_entries(xml_response(MAPS, urlset((ORPHAN, LASTMOD))))
    assert read == (SitemapEntry(loc=ORPHAN, lastmod=LASTMOD),)


def test_entity_fields_SitemapEntry(tmp_path: Path) -> None:
    """Verify all declared fields on SitemapEntry are present with correct types."""
    run, frontier, _ = host_open(tmp_path, site())
    response = xml_response(MAPS, urlset((ORPHAN, LASTMOD), (OTHER, None)))
    snapshot = accept_fresh_sitemap(run, frontier, MAPS, response)
    assert snapshot is not None
    first, second = snapshot.entries
    assert (first.loc, first.lastmod) == (ORPHAN, LASTMOD)
    assert (second.loc, second.lastmod) == (OTHER, None)


def test_enum_comparable_DiscoverySource(tmp_path: Path) -> None:
    """Verify fields typed with enum DiscoverySource are comparable.

    A seed row is discovered via start, a sitemap entry via sitemap and an llms.txt link
    via llms_txt; each compares equal to its own member only.
    """
    assert tuple(source.value for source in DiscoverySource) == spec_enum(
        "crawl", "DiscoverySource"
    )
    fetcher = site(robots=declaring(MAPS))
    fetcher.responses[MAPS] = xml_response(MAPS, urlset((ORPHAN, None)))
    fetcher.responses[LLMS_TXT] = llms(FROM_LLMS)
    _, frontier = discovered(tmp_path, fetcher)
    via = {entry.identity: entry.discovered_via for entry in frontier.entries}
    assert via == {
        SEED: DiscoverySource.start,
        ORPHAN: DiscoverySource.sitemap,
        FROM_LLMS: DiscoverySource.llms_txt,
    }
    assert via[ORPHAN] != DiscoverySource.llms_txt
    seen = observation(frontier, FROM_LLMS)
    assert seen is not None
    assert seen.sources == {DiscoverySource.llms_txt}


def test_entity_relationship_Frontier_observed_urls(tmp_path: Path) -> None:
    """Verify relationship Frontier.observed_urls navigates to the correct related entities.

    Every URL a sitemap names is observed in the run's frontier, in scope or not, and no
    other frontier holds it.
    """
    run, frontier, host = host_open(tmp_path / "one", site())
    _, other = started(tmp_path / "two")
    entries = (
        SitemapEntry(loc=ORPHAN, lastmod=None),
        SitemapEntry(loc=OUT_OF_SCOPE, lastmod=None),
    )
    assert expand_sitemap_entries(run, frontier, host, MAPS, entries, is_index=False) == []
    assert sorted(seen.url for seen in frontier.observed_urls) == [ORPHAN, OUT_OF_SCOPE]
    assert all(seen.frontier is frontier for seen in frontier.observed_urls)
    assert other.observed_urls == []


def test_entity_optional_FrontierEntry_discovered_from(tmp_path: Path) -> None:
    """Verify optional field FrontierEntry.discovered_from accepts null and non-null values.

    Null for a seed; the sitemap's URL for a sitemap entry; llms_txt_url for an llms.txt
    link.
    """
    fetcher = site(robots=declaring(MAPS))
    fetcher.responses[MAPS] = xml_response(MAPS, urlset((ORPHAN, None)))
    fetcher.responses[LLMS_TXT] = llms(FROM_LLMS)
    _, frontier = discovered(tmp_path, fetcher)
    origins = {entry.identity: entry.discovered_from for entry in frontier.entries}
    assert origins == {SEED: None, ORPHAN: MAPS, FROM_LLMS: LLMS_TXT}


def test_entity_optional_FrontierEntry_sitemap_lastmod(tmp_path: Path) -> None:
    """Verify optional field FrontierEntry.sitemap_lastmod accepts null and non-null values.

    A sitemap entry's lastmod reaches its row; an entry without one, and a seed, have none.
    """
    run, frontier, host = host_open(tmp_path, site())
    enqueue(run, frontier, SEED, depth=0, via=DiscoverySource.start, priority=0)
    entries = (SitemapEntry(loc=ORPHAN, lastmod=LASTMOD), SitemapEntry(loc=OTHER, lastmod=None))
    assert expand_sitemap_entries(run, frontier, host, MAPS, entries, is_index=False) == []
    lastmods = {entry.identity: entry.sitemap_lastmod for entry in frontier.entries}
    assert lastmods == {SEED: None, ORPHAN: LASTMOD, OTHER: None}


def test_entity_fields_ObservedUrl(tmp_path: Path) -> None:
    """Verify all declared fields on ObservedUrl are present with correct types."""
    run, frontier = started(tmp_path)
    seen = record_observation(run, frontier, OUT_OF_SCOPE, DiscoverySource.sitemap)
    assert isinstance(seen, ObservedUrl)
    assert seen.frontier is frontier
    assert seen.url == OUT_OF_SCOPE
    assert seen.sources == frozenset({DiscoverySource.sitemap})
    assert all(isinstance(source, DiscoverySource) for source in seen.sources)
    assert seen.last_seen_run == run.id
    assert frontier.observed_urls == [seen]


def test_entity_fields_SitemapSnapshot(tmp_path: Path) -> None:
    """Verify all declared fields on SitemapSnapshot are present with correct types."""
    run, frontier, _ = host_open(tmp_path, site())
    response = dataclasses.replace(
        xml_response(MAPS_INDEX, sitemapindex(MAPS)), etag='"v1"', last_modified="Sat, 31 Oct"
    )
    snapshot = accept_fresh_sitemap(run, frontier, MAPS_INDEX, response)
    assert isinstance(snapshot, SitemapSnapshot)
    assert frontier.sitemap_snapshots == [snapshot]
    assert snapshot.frontier is frontier
    assert snapshot.url == MAPS_INDEX
    assert snapshot.etag == '"v1"'
    assert snapshot.last_modified == "Sat, 31 Oct"
    assert snapshot.is_index is True
    assert snapshot.entries == (SitemapEntry(loc=MAPS, lastmod=None),)


def test_entity_optional_SitemapSnapshot_etag(tmp_path: Path) -> None:
    """Verify optional field SitemapSnapshot.etag accepts null and non-null values."""
    run, frontier, _ = host_open(tmp_path, site())
    tagged = dataclasses.replace(xml_response(MAPS, urlset((ORPHAN, None))), etag='"v1"')
    untagged = xml_response(MAPS_INDEX, sitemapindex(MAPS))
    first = accept_fresh_sitemap(run, frontier, MAPS, tagged)
    second = accept_fresh_sitemap(run, frontier, MAPS_INDEX, untagged)
    assert first is not None
    assert second is not None
    assert (first.etag, second.etag) == ('"v1"', None)


def test_entity_optional_SitemapSnapshot_last_modified(tmp_path: Path) -> None:
    """Verify optional field SitemapSnapshot.last_modified accepts null and non-null values."""
    run, frontier, _ = host_open(tmp_path, site())
    dated = dataclasses.replace(
        xml_response(MAPS, urlset((ORPHAN, None))), last_modified="Sat, 31 Oct 2026"
    )
    undated = xml_response(MAPS_INDEX, sitemapindex(MAPS))
    first = accept_fresh_sitemap(run, frontier, MAPS, dated)
    second = accept_fresh_sitemap(run, frontier, MAPS_INDEX, undated)
    assert first is not None
    assert second is not None
    assert (first.last_modified, second.last_modified) == ("Sat, 31 Oct 2026", None)


def test_transition_edge_FrontierEntry_skipped_limit_pending(tmp_path: Path) -> None:
    """Verify transition skipped_limit -> pending on FrontierEntry.status is reachable via a witnessing rule.

    PrepareRun re-pends every retry row the scope admits: a row a budget stopped is
    pending again on the next run (unit inputs: a second sync over written pages would
    refetch them conditionally, the incremental slice's).
    """  # noqa: E501  The obligation's description, quoted.
    first, frontier = started(tmp_path)
    row = enqueue(first, frontier, ORPHAN, depth=1, via=DiscoverySource.sitemap, priority=50)
    row.status = FrontierStatus.skipped_limit
    save_frontier(frontier)
    mirror = new_mirror(tmp_path)
    second = start_run(request(mirror, run_id=SECOND_RUN), FixedClock())
    assert second is not None
    persisted = load_frontier(mirror)
    assert persisted is not None
    assert prepare_run(second, persisted)
    reloaded = persisted.entry(ORPHAN)
    assert reloaded is not None
    assert reloaded.status is FrontierStatus.pending


def test_config_default_sitemap_max_children() -> None:
    """Verify config parameter sitemap_max_children has its declared default."""
    assert model.CONFIG.sitemap_max_children == spec_int("crawl", "sitemap_max_children")


def test_config_default_sitemap_cap_multiplier() -> None:
    """Verify config parameter sitemap_cap_multiplier has its declared default."""
    assert model.CONFIG.sitemap_cap_multiplier == spec_int("crawl", "sitemap_cap_multiplier")


def test_config_default_sitemap_depth() -> None:
    """Verify config parameter sitemap_depth has its declared default."""
    assert model.CONFIG.sitemap_depth == spec_int("crawl", "sitemap_depth")


def test_config_default_llms_txt_depth() -> None:
    """Verify config parameter llms_txt_depth has its declared default."""
    assert model.CONFIG.llms_txt_depth == spec_int("crawl", "llms_txt_depth")


def test_config_default_sitemap_priority() -> None:
    """Verify config parameter sitemap_priority has its declared default."""
    assert model.CONFIG.sitemap_priority == spec_int("crawl", "sitemap_priority")


def test_config_default_llms_txt_priority() -> None:
    """Verify config parameter llms_txt_priority has its declared default."""
    assert model.CONFIG.llms_txt_priority == spec_int("crawl", "llms_txt_priority")


def test_rule_success_QueueSitemaps(tmp_path: Path) -> None:
    """Verify rule QueueSitemaps succeeds when all preconditions are met.

    The declared sitemaps of the host's origin, in robots.txt order, then each
    well-known sitemap not declared; with no robots.txt, the two well-known ones.
    """
    fetcher = site(robots=declaring(MAPS, SITEMAP))
    run, _, _ = host_open(tmp_path / "declared", fetcher)
    assert queue_sitemaps(run, HOST) == [(MAPS, True), (SITEMAP, True), (SITEMAP_INDEX, False)]
    assert fetcher.requests == [ROBOTS]
    absent, _, _ = host_open(tmp_path / "absent", site())
    assert queue_sitemaps(absent, HOST) == [(SITEMAP, False), (SITEMAP_INDEX, False)]


def test_rule_failure_QueueSitemaps_1(tmp_path: Path) -> None:
    """Verify rule QueueSitemaps is rejected when requires clause fails.

    requires: run.status = running.
    """
    run, _, _ = host_open(tmp_path, site(robots=declaring(MAPS)))
    run.status = RunStatus.finished
    assert queue_sitemaps(run, HOST) is None


def test_rule_failure_QueueSitemaps_2(tmp_path: Path) -> None:
    """Verify rule QueueSitemaps is rejected when requires clause fails.

    requires: exists host.
    """
    run, _ = started(tmp_path)
    assert queue_sitemaps(run, HOST) is None


def test_rule_success_ReadRobotsBeforeSitemap(tmp_path: Path) -> None:
    """Verify rule ReadRobotsBeforeSitemap succeeds when all preconditions are met.

    A sitemap at another origin of its host reads that origin's robots.txt first; the
    sitemap is then fetched.
    """
    fetcher = site(robots=declaring(PORTED_MAP))
    fetcher.responses[PORTED_ROBOTS] = text_response(PORTED_ROBOTS, "User-agent: *\nAllow: /\n")
    fetcher.responses[PORTED_MAP] = xml_response(PORTED_MAP, urlset((PORTED_PAGE, None)))
    run, _, _ = host_open(tmp_path, fetcher)
    assert read_robots_before_sitemap(run, HOST, PORTED_MAP, fetcher)
    assert fetcher.requests == [ROBOTS, PORTED_ROBOTS]
    assert run.robots_policy(PORTED) is not None
    assert not read_robots_before_sitemap(run, HOST, PORTED_MAP, fetcher)
    assert fetch_sitemap(run, HOST, PORTED_MAP, fetcher) is not None
    assert fetcher.requests == [ROBOTS, PORTED_ROBOTS, PORTED_MAP]


def test_rule_failure_ReadRobotsBeforeSitemap_1(tmp_path: Path) -> None:
    """Verify rule ReadRobotsBeforeSitemap is rejected when requires clause fails.

    requires: run.status = running.
    """
    fetcher = site()
    run, _, _ = host_open(tmp_path, fetcher)
    run.status = RunStatus.finished
    assert not read_robots_before_sitemap(run, HOST, PORTED_MAP, fetcher)
    assert fetcher.requests == [ROBOTS]
    assert run.robots_policy(PORTED) is None


def test_rule_failure_ReadRobotsBeforeSitemap_2(tmp_path: Path) -> None:
    """Verify rule ReadRobotsBeforeSitemap is rejected when requires clause fails.

    requires: exists host.
    """
    fetcher = site()
    run, _ = started(tmp_path)
    assert not read_robots_before_sitemap(run, HOST, PORTED_MAP, fetcher)
    assert fetcher.requests == []


def test_rule_failure_ReadRobotsBeforeSitemap_3(tmp_path: Path) -> None:
    """Verify rule ReadRobotsBeforeSitemap is rejected when requires clause fails.

    requires: run.target.scope.identity_of(url) != null. A sitemap URL on the host whose
    port is out of range has no identity: nothing is requested, nothing raised, no
    problem (FetchSitemap guidance).
    """
    fetcher = site()
    run, _, _ = host_open(tmp_path, fetcher)
    assert hostname_of(NO_IDENTITY_MAP) == HOST
    assert not read_robots_before_sitemap(run, HOST, NO_IDENTITY_MAP, fetcher)
    assert fetcher.requests == [ROBOTS]
    assert [policy.origin for policy in run.robots_policies] == [SITE]
    assert run.discovery_failures == []


def test_rule_failure_ReadRobotsBeforeSitemap_4(tmp_path: Path) -> None:
    """Verify rule ReadRobotsBeforeSitemap is rejected when requires clause fails.

    requires: hostname_of(url) = name.
    """
    fetcher = site()
    run, _, _ = host_open(tmp_path, fetcher)
    assert not read_robots_before_sitemap(run, HOST, OFF_HOST_MAP, fetcher)
    assert fetcher.requests == [ROBOTS]
    assert run.robots_policy("http://elsewhere.example") is None


def test_rule_failure_ReadRobotsBeforeSitemap_5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify rule ReadRobotsBeforeSitemap is rejected when requires clause fails.

    requires: sitemap_admitted(url, run.target.profile, run.target.scope).
    """
    fetcher = site()
    run, _, _ = host_open(tmp_path, fetcher)
    refuse_every_sitemap(monkeypatch)
    assert not read_robots_before_sitemap(run, HOST, PORTED_MAP, fetcher)
    assert fetcher.requests == [ROBOTS]
    assert run.robots_policy(PORTED) is None


def test_rule_failure_ReadRobotsBeforeSitemap_6(tmp_path: Path) -> None:
    """Verify rule ReadRobotsBeforeSitemap is rejected when requires clause fails.

    requires: not exists RobotsPolicy{run: run, origin: origin_of(url)}.
    """
    fetcher = site()
    run, _, _ = host_open(tmp_path, fetcher)
    assert not read_robots_before_sitemap(run, HOST, MAPS, fetcher)
    assert fetcher.requests == [ROBOTS]
    assert [policy.origin for policy in run.robots_policies] == [SITE]


def test_rule_success_FetchSitemap(tmp_path: Path) -> None:
    """Verify rule FetchSitemap succeeds when all preconditions are met.

    The sitemap is read through fetch_resource without validators (no snapshot is ever
    loaded in this slice) and its bytes count toward the run's, not its attempts.
    """
    robots = declaring(MAPS)
    fetcher = site(robots=robots)
    fetcher.responses[MAPS] = xml_response(MAPS, urlset((ORPHAN, None)))
    run, _, _ = host_open(tmp_path, fetcher)
    response = fetch_sitemap(run, HOST, MAPS, fetcher)
    assert response == fetcher.responses[MAPS]
    assert fetcher.requests == [ROBOTS, MAPS]
    assert fetcher.validators == [None, None]
    assert run.bytes_fetched == robots.size + response.size
    assert run.fetch_attempts == 0


def test_rule_failure_FetchSitemap_1(tmp_path: Path) -> None:
    """Verify rule FetchSitemap is rejected when requires clause fails.

    requires: run.status = running.
    """
    fetcher = site()
    run, _, _ = host_open(tmp_path, fetcher)
    run.status = RunStatus.finished
    assert fetch_sitemap(run, HOST, MAPS, fetcher) is None
    assert fetcher.requests == [ROBOTS]
    assert run.bytes_fetched == 0


def test_rule_failure_FetchSitemap_2(tmp_path: Path) -> None:
    """Verify rule FetchSitemap is rejected when requires clause fails.

    requires: exists host.
    """
    fetcher = site()
    run, _ = started(tmp_path)
    assert fetch_sitemap(run, HOST, MAPS, fetcher) is None
    assert fetcher.requests == []


def test_rule_failure_FetchSitemap_3(tmp_path: Path) -> None:
    """Verify rule FetchSitemap is rejected when requires clause fails.

    requires: run.target.scope.identity_of(url) != null. A sitemap URL on the host whose
    port is out of range produces nothing and no problem, and raises nothing.
    """
    fetcher = site()
    run, _, host = host_open(tmp_path, fetcher)
    assert hostname_of(NO_IDENTITY_MAP) == HOST
    assert fetch_sitemap(run, HOST, NO_IDENTITY_MAP, fetcher) is None
    assert fetcher.requests == [ROBOTS]
    assert run.discovery_failures == []
    assert run.bytes_fetched == 0
    assert (host.paused_until, run.backoffs) == (None, [])


def test_rule_failure_FetchSitemap_4(tmp_path: Path) -> None:
    """Verify rule FetchSitemap is rejected when requires clause fails.

    requires: hostname_of(url) = name. A sitemap on another host produces nothing.
    """
    fetcher = site()
    run, _, _ = host_open(tmp_path, fetcher)
    assert fetch_sitemap(run, HOST, OFF_HOST_MAP, fetcher) is None
    assert fetcher.requests == [ROBOTS]
    assert run.discovery_failures == []


def test_rule_failure_FetchSitemap_5(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify rule FetchSitemap is rejected when requires clause fails.

    requires: sitemap_admitted(url, run.target.profile, run.target.scope).
    """
    fetcher = site()
    run, _, _ = host_open(tmp_path, fetcher)
    refuse_every_sitemap(monkeypatch)
    assert fetch_sitemap(run, HOST, MAPS, fetcher) is None
    assert fetcher.requests == [ROBOTS]


def test_rule_failure_FetchSitemap_6(tmp_path: Path) -> None:
    """Verify rule FetchSitemap is rejected when requires clause fails.

    requires: robots_allows(run, url). A disallowed sitemap produces nothing.
    """
    fetcher = site(robots=declaring(MAPS, disallow="/maps/"))
    fetcher.responses[MAPS] = xml_response(MAPS, urlset((ORPHAN, None)))
    run, _, _ = host_open(tmp_path, fetcher)
    assert fetch_sitemap(run, HOST, MAPS, fetcher) is None
    assert fetcher.requests == [ROBOTS]
    assert run.discovery_failures == []


def test_rule_failure_FetchSitemap_7(tmp_path: Path) -> None:
    """Verify rule FetchSitemap is rejected when requires clause fails.

    requires: exists RobotsPolicy{run: run, origin: origin_of(url)}.
    """
    fetcher = site()
    fetcher.responses[PORTED_MAP] = xml_response(PORTED_MAP, urlset((PORTED_PAGE, None)))
    run, _, _ = host_open(tmp_path, fetcher)
    run.policy = dataclasses.replace(run.policy, robots=RobotsMode.ignore)
    assert fetch_sitemap(run, HOST, PORTED_MAP, fetcher) is None
    assert fetcher.requests == [ROBOTS]


def test_rule_success_AcceptFreshSitemap(tmp_path: Path) -> None:
    """Verify rule AcceptFreshSitemap succeeds when all preconditions are met.

    An ok sitemap document creates its snapshot; a second answer for the same URL updates
    it in place (unit inputs: within one run each sitemap is read once).
    """
    run, frontier, _ = host_open(tmp_path, site())
    first = dataclasses.replace(xml_response(MAPS, urlset((ORPHAN, LASTMOD))), etag='"v1"')
    created = accept_fresh_sitemap(run, frontier, MAPS, first)
    assert created is not None
    assert (created.is_index, created.etag) == (False, '"v1"')
    assert created.entries == (SitemapEntry(loc=ORPHAN, lastmod=LASTMOD),)
    second = dataclasses.replace(xml_response(MAPS, sitemapindex(MAPS_INDEX)), etag='"v2"')
    updated = accept_fresh_sitemap(run, frontier, MAPS, second)
    assert updated is created
    assert frontier.sitemap_snapshots == [created]
    assert (created.is_index, created.etag, created.last_modified) == (True, '"v2"', None)
    assert created.entries == (SitemapEntry(loc=MAPS_INDEX, lastmod=None),)


def test_rule_failure_AcceptFreshSitemap_1(tmp_path: Path) -> None:
    """Verify rule AcceptFreshSitemap is rejected when requires clause fails.

    requires: response.ok and is_sitemap_document(response).
    """
    run, frontier, _ = host_open(tmp_path, site())
    failed = xml_response(MAPS, urlset((ORPHAN, None)), status=SERVER_ERROR)
    assert accept_fresh_sitemap(run, frontier, MAPS, failed) is None
    assert accept_fresh_sitemap(run, frontier, MAPS, html_response(MAPS, PAGE)) is None
    assert frontier.sitemap_snapshots == []


def test_rule_success_RejectNonSitemap(tmp_path: Path) -> None:
    """Verify rule RejectNonSitemap succeeds when all preconditions are met.

    A declared sitemap that answers but is no sitemap is not_a_sitemap; a speculative
    probe that does so is silent.
    """
    run, _, _ = host_open(tmp_path, site())
    page = html_response(MAPS, PAGE)
    assert reject_non_sitemap(run, MAPS, page, declared=True) == DiscoveryFailed(
        run=run, url=MAPS, problem=DiscoveryProblem.not_a_sitemap
    )
    assert reject_non_sitemap(run, SITEMAP, html_response(SITEMAP, PAGE), declared=False) is None


def test_rule_failure_RejectNonSitemap_1(tmp_path: Path) -> None:
    """Verify rule RejectNonSitemap is rejected when requires clause fails.

    requires: response.ok and not is_sitemap_document(response).
    """
    run, _, _ = host_open(tmp_path, site())
    sitemap = xml_response(MAPS, urlset((ORPHAN, None)))
    assert reject_non_sitemap(run, MAPS, sitemap, declared=True) is None
    failed = html_response(MAPS, PAGE, status=SERVER_ERROR)
    assert reject_non_sitemap(run, MAPS, failed, declared=True) is None


def test_rule_success_SkipUnavailableSitemap(tmp_path: Path) -> None:
    """Verify rule SkipUnavailableSitemap succeeds when all preconditions are met.

    A declared sitemap that fails is sitemap_unavailable, or sitemap_unreachable when no
    answer arrived; a declared 404 and every speculative probe are silent.
    """
    run, _, _ = host_open(tmp_path, site())
    broken = xml_response(MAPS, "", status=SERVER_ERROR)
    assert skip_unavailable_sitemap(run, MAPS, broken, declared=True) == DiscoveryFailed(
        run=run, url=MAPS, problem=DiscoveryProblem.sitemap_unavailable
    )
    assert skip_unavailable_sitemap(
        run, MAPS, unreachable(MAPS), declared=True
    ) == DiscoveryFailed(run=run, url=MAPS, problem=DiscoveryProblem.sitemap_unreachable)
    assert skip_unavailable_sitemap(run, MAPS, not_found(MAPS), declared=True) is None
    assert skip_unavailable_sitemap(run, SITEMAP, broken, declared=False) is None
    assert skip_unavailable_sitemap(run, SITEMAP, unreachable(SITEMAP), declared=False) is None


def test_rule_failure_SkipUnavailableSitemap_1(tmp_path: Path) -> None:
    """Verify rule SkipUnavailableSitemap is rejected when requires clause fails.

    requires: not response.ok and not response.not_modified. A 304 with no snapshot meets
    no rule at all.
    """
    run, frontier, _ = host_open(tmp_path, site())
    sitemap = xml_response(MAPS, urlset((ORPHAN, None)))
    assert skip_unavailable_sitemap(run, MAPS, sitemap, declared=True) is None
    unchanged = xml_response(MAPS, "", status=304)
    assert skip_unavailable_sitemap(run, MAPS, unchanged, declared=True) is None
    assert reject_non_sitemap(run, MAPS, unchanged, declared=True) is None
    assert accept_fresh_sitemap(run, frontier, MAPS, unchanged) is None


def test_rule_success_ExpandSitemapEntries(tmp_path: Path) -> None:
    """Verify rule ExpandSitemapEntries succeeds when all preconditions are met.

    A urlset's entries are each observed; the in-scope ones are admitted at sitemap_depth
    with sitemap_priority, from the sitemap, with their lastmod, resolved against it. An
    index's children on the host that served it are due; one on another host is not, and
    is not counted.
    """
    run, frontier, host = host_open(tmp_path, site())
    entries = (
        SitemapEntry(loc=ORPHAN, lastmod=LASTMOD),
        SitemapEntry(loc=OUT_OF_SCOPE, lastmod=None),
        SitemapEntry(loc="relative.html", lastmod=None),
    )
    guide = f"{SITE}/guide/map.xml"
    assert expand_sitemap_entries(run, frontier, host, guide, entries, is_index=False) == []
    assert host.sitemap_entries_admitted == len([ORPHAN, RELATIVE])
    rows = {
        entry.identity: (
            entry.depth,
            entry.priority,
            entry.discovered_via,
            entry.discovered_from,
            entry.sitemap_lastmod,
            entry.status,
        )
        for entry in frontier.entries
    }
    sitemap_row = (
        model.CONFIG.sitemap_depth,
        model.CONFIG.sitemap_priority,
        DiscoverySource.sitemap,
    )
    assert rows == {
        ORPHAN: (*sitemap_row, guide, LASTMOD, FrontierStatus.pending),
        RELATIVE: (*sitemap_row, guide, None, FrontierStatus.pending),
    }
    observed = {seen.url: (seen.sources, seen.last_seen_run) for seen in frontier.observed_urls}
    sighting = (frozenset({DiscoverySource.sitemap}), run.id)
    assert observed == {ORPHAN: sighting, OUT_OF_SCOPE: sighting, RELATIVE: sighting}

    children = (
        SitemapEntry(loc=MAPS, lastmod=None),
        SitemapEntry(loc=OFF_HOST_MAP, lastmod=None),
        SitemapEntry(loc="other.xml", lastmod=None),
    )
    due = expand_sitemap_entries(run, frontier, host, MAPS_INDEX, children, is_index=True)
    assert due == [MAPS, f"{SITE}/maps/other.xml"]
    assert host.sitemap_children_read == len(due)
    assert observation(frontier, MAPS) is None
    assert frontier.entry(MAPS) is None


def test_rule_failure_ExpandSitemapEntries_1(tmp_path: Path) -> None:
    """Verify rule ExpandSitemapEntries is rejected when requires clause fails.

    requires: run.status = running.
    """
    run, frontier, host = host_open(tmp_path, site())
    run.status = RunStatus.finished
    entries = (SitemapEntry(loc=ORPHAN, lastmod=None),)
    assert expand_sitemap_entries(run, frontier, host, MAPS, entries, is_index=False) is None
    assert expand_sitemap_entries(run, frontier, host, MAPS_INDEX, entries, is_index=True) is None
    assert frontier.entries == []
    assert frontier.observed_urls == []
    assert (host.sitemap_entries_admitted, host.sitemap_children_read) == (0, 0)


def test_rule_success_ReadLlmsTxt(tmp_path: Path) -> None:
    """Verify rule ReadLlmsTxt succeeds when all preconditions are met.

    Each target is observed; the in-scope ones are admitted at llms_txt_depth with
    llms_txt_priority, from llms_txt_url. Its bytes count; its try is not an attempt.
    """
    fetcher = site()
    fetcher.responses[LLMS_TXT] = llms(FROM_LLMS, OUT_OF_SCOPE)
    run, frontier, _ = host_open(tmp_path, fetcher)
    response = read_llms_txt(run, HOST, frontier, fetcher)
    assert response == fetcher.responses[LLMS_TXT]
    assert fetcher.requests == [ROBOTS, LLMS_TXT]
    assert fetcher.validators == [None, None]
    assert run.bytes_fetched == response.size
    assert run.fetch_attempts == 0
    (row,) = frontier.entries
    assert (row.identity, row.depth, row.priority) == (
        FROM_LLMS,
        model.CONFIG.llms_txt_depth,
        model.CONFIG.llms_txt_priority,
    )
    assert (row.discovered_via, row.discovered_from, row.sitemap_lastmod) == (
        DiscoverySource.llms_txt,
        LLMS_TXT,
        None,
    )
    observed = {seen.url: seen.sources for seen in frontier.observed_urls}
    llms_only = frozenset({DiscoverySource.llms_txt})
    assert observed == {FROM_LLMS: llms_only, OUT_OF_SCOPE: llms_only}


def test_rule_failure_ReadLlmsTxt_1(tmp_path: Path) -> None:
    """Verify rule ReadLlmsTxt is rejected when requires clause fails.

    requires: run.status = running.
    """
    fetcher = site()
    fetcher.responses[LLMS_TXT] = llms(FROM_LLMS)
    run, frontier, _ = host_open(tmp_path, fetcher)
    run.status = RunStatus.finished
    assert read_llms_txt(run, HOST, frontier, fetcher) is None
    assert fetcher.requests == [ROBOTS]
    assert frontier.entries == []


def test_rule_failure_ReadLlmsTxt_2(tmp_path: Path) -> None:
    """Verify rule ReadLlmsTxt is rejected when requires clause fails.

    requires: exists host.
    """
    fetcher = site()
    fetcher.responses[LLMS_TXT] = llms(FROM_LLMS)
    run, frontier = started(tmp_path)
    assert read_llms_txt(run, HOST, frontier, fetcher) is None
    assert fetcher.requests == []


def test_rule_failure_ReadLlmsTxt_3(tmp_path: Path) -> None:
    """Verify rule ReadLlmsTxt is rejected when requires clause fails.

    requires: robots_allows(run, llms_txt_url(name)).
    """
    fetcher = site(robots=declaring(disallow="/llms.txt"))
    fetcher.responses[LLMS_TXT] = llms(FROM_LLMS)
    run, frontier, _ = host_open(tmp_path, fetcher)
    assert read_llms_txt(run, HOST, frontier, fetcher) is None
    assert fetcher.requests == [ROBOTS]
    assert frontier.observed_urls == []


def test_rule_success_RecordObservation(tmp_path: Path) -> None:
    """Verify rule RecordObservation succeeds when all preconditions are met.

    A new URL is created with its one source; a later sighting adds its source and moves
    last_seen_run to the run's id.
    """
    first, frontier = started(tmp_path)
    created = record_observation(first, frontier, OUT_OF_SCOPE, DiscoverySource.sitemap)
    assert (created.sources, created.last_seen_run) == (
        frozenset({DiscoverySource.sitemap}),
        first.id,
    )
    later = start_run(request(first.target, run_id=SECOND_RUN), FixedClock())
    assert later is not None
    updated = record_observation(later, frontier, OUT_OF_SCOPE, DiscoverySource.llms_txt)
    assert updated is created
    assert frontier.observed_urls == [created]
    assert created.sources == {DiscoverySource.sitemap, DiscoverySource.llms_txt}
    assert created.last_seen_run == SECOND_RUN


def test_rule_success_DryRun(tmp_path: Path) -> None:
    """Verify rule DryRun succeeds when all preconditions are met.

    After discovery a dry run ends: no batch is requested and no page is fetched.
    """
    run, _ = dry(tmp_path / "unit")
    assert dry_run(run)
    assert not run.crawling
    mirror = new_mirror(tmp_path / "driven")
    fetcher = site()
    result = run_crawl(
        dataclasses.replace(request(mirror), dry_run=True), None, fetcher, FixedClock()
    )
    assert result.run.status is RunStatus.finished
    assert SEED not in fetcher.requests
    assert fetcher.requests == DISCOVERY
    assert result.run.fetch_attempts == 0
    (entry,) = result.frontier.entries
    assert entry.status is FrontierStatus.pending
    assert result.run.unresolved_urls == frozenset()


def test_rule_failure_DryRun_1(tmp_path: Path) -> None:
    """Verify rule DryRun is rejected when requires clause fails.

    requires: run.status = running.
    """
    run, _ = dry(tmp_path)
    run.status = RunStatus.interrupted
    assert not dry_run(run)


def test_rule_failure_DryRun_2(tmp_path: Path) -> None:
    """Verify rule DryRun is rejected when requires clause fails.

    requires: run.dry_run.
    """
    run, _ = started(tmp_path)
    assert not dry_run(run)


def test_rule_failure_BeginCrawl_2(tmp_path: Path) -> None:
    """Verify rule BeginCrawl is rejected when requires clause fails.

    requires: not run.dry_run.
    """
    run, _ = dry(tmp_path)
    assert not begin_crawl(run)
    assert not run.crawling


# --- Discovery guarantees (T13): the open question's interim, once per run, the caps ------


def test_an_index_child_on_another_host_is_never_read(tmp_path: Path) -> None:
    """crawl.allium open question 1, its interim: children only on the index's own host.

    A child on another host is neither requested nor counted toward sitemap_children_read.
    """
    fetcher = site(robots=declaring(MAPS_INDEX))
    fetcher.responses[MAPS_INDEX] = xml_response(MAPS_INDEX, sitemapindex(OFF_HOST_MAP, MAPS))
    fetcher.responses[MAPS] = xml_response(MAPS, urlset((ORPHAN, None)))
    run, frontier = discovered(tmp_path, fetcher)
    assert OFF_HOST_MAP not in fetcher.requests
    assert "http://elsewhere.example/robots.txt" not in fetcher.requests
    host = run.host(HOST)
    assert host is not None
    assert host.sitemap_children_read == 1
    assert frontier.entry(ORPHAN) is not None
    assert run.discovery_failures == []


def test_each_sitemap_is_read_at_most_once_per_run(tmp_path: Path) -> None:
    """An index naming itself, and two indexes naming one child, read each sitemap once."""
    second_index = f"{SITE}/maps/second.xml"
    fetcher = site(robots=declaring(MAPS_INDEX, second_index))
    fetcher.responses[MAPS_INDEX] = xml_response(MAPS_INDEX, sitemapindex(MAPS_INDEX, MAPS))
    fetcher.responses[second_index] = xml_response(second_index, sitemapindex(MAPS))
    fetcher.responses[MAPS] = xml_response(MAPS, urlset((ORPHAN, None)))
    run, _ = discovered(tmp_path, fetcher)
    for url in (MAPS_INDEX, second_index, MAPS):
        assert fetcher.requests.count(url) == 1, url
    assert fetch_sitemap(run, HOST, MAPS, fetcher) is None
    assert fetcher.requests.count(MAPS) == 1


def test_discover_reads_the_sitemaps_and_llms_txt_in_order(tmp_path: Path) -> None:
    """Robots.txt, then the sitemaps, depth first, then llms.txt; all before any page.

    The declared sitemaps, each index's children read as they fall due, then the
    well-known sitemaps not declared, then llms.txt (crawl.allium Discover guidance).
    """
    fetcher = site(robots=declaring(MAPS_INDEX))
    fetcher.responses[MAPS_INDEX] = xml_response(MAPS_INDEX, sitemapindex(MAPS))
    fetcher.responses[MAPS] = xml_response(MAPS, urlset((ORPHAN, LASTMOD)))
    fetcher.responses[LLMS_TXT] = llms(FROM_LLMS)
    _, frontier = discovered(tmp_path, fetcher)
    assert fetcher.requests == [ROBOTS, MAPS_INDEX, MAPS, SITEMAP, SITEMAP_INDEX, LLMS_TXT]
    assert [entry.identity for entry in frontier.entries] == [SEED, ORPHAN, FROM_LLMS]


def test_the_index_children_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """At most sitemap_max_children child sitemaps are queued per host."""
    replace_config(monkeypatch, sitemap_max_children=2)
    run, frontier, host = host_open(tmp_path, site())
    children = tuple(SitemapEntry(loc=f"{SITE}/maps/{n}.xml", lastmod=None) for n in range(3))
    due = expand_sitemap_entries(run, frontier, host, MAPS_INDEX, children, is_index=True)
    assert due == [f"{SITE}/maps/0.xml", f"{SITE}/maps/1.xml"]
    assert host.sitemap_children_read == len(due)
    more = (SitemapEntry(loc=f"{SITE}/maps/3.xml", lastmod=None),)
    assert expand_sitemap_entries(run, frontier, host, MAPS, more, is_index=True) == []


def test_the_sitemap_entries_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """At most max_pages * sitemap_cap_multiplier entries admitted per host; all observed."""
    replace_config(monkeypatch, max_pages=1, sitemap_cap_multiplier=2)
    run, frontier, host = host_open(tmp_path, site())
    pages = [f"{SITE}/guide/{n}.html" for n in range(3)]
    entries = tuple(SitemapEntry(loc=url, lastmod=None) for url in pages)
    assert expand_sitemap_entries(run, frontier, host, MAPS, entries, is_index=False) == []
    assert [entry.identity for entry in frontier.entries] == pages[:2]
    assert host.sitemap_entries_admitted == len(pages[:2])
    assert sorted(seen.url for seen in frontier.observed_urls) == pages


def test_a_declared_sitemap_answering_404_is_silent(tmp_path: Path) -> None:
    """A declared sitemap that is absent is no discovery problem."""
    fetcher = site(robots=declaring(MAPS))
    run, _ = discovered(tmp_path, fetcher)
    assert MAPS in fetcher.requests
    assert run.discovery_failures == []


def test_the_speculative_probes_are_silent_on_every_failure(tmp_path: Path) -> None:
    """A failing /sitemap.xml, /sitemap_index.xml or llms.txt never fails the run."""
    for name, answer in (
        ("server-error", lambda url: xml_response(url, "", status=SERVER_ERROR)),
        ("unreachable", unreachable),
        ("not-a-sitemap", lambda url: html_response(url, PAGE)),
        ("refused", lambda url: html_response(url, "", status=FORBIDDEN)),
    ):
        fetcher = site()
        for url in PROBES:
            fetcher.responses[url] = answer(url)
        run, frontier = discovered(tmp_path / name, fetcher)
        assert run.discovery_failures == [], name
        assert [entry.identity for entry in frontier.entries] == [SEED], name
        assert all(url in fetcher.requests for url in PROBES), name


def test_the_dry_run_listing_is_next_pending_order(tmp_path: Path) -> None:
    """crawl.allium DryRun and rovo.allium ProgressOnRequest: the pending identities.

    Each row SelectBatch would consider, in next_pending order: non-deferred first, then
    shallowest, then highest priority, then discovery order (DryRun guidance).
    """
    run, frontier = dry(tmp_path)
    deferred = f"{SITE}/guide/removed.html"
    done = f"{SITE}/guide/done.html"
    for url, depth, via, priority in (
        (deferred, 0, DiscoverySource.recheck, model.CONFIG.deferred_priority),
        (FROM_LLMS, 1, DiscoverySource.llms_txt, model.CONFIG.llms_txt_priority),
        (ORPHAN, 1, DiscoverySource.sitemap, model.CONFIG.sitemap_priority),
        (RELATIVE, 1, DiscoverySource.sitemap, model.CONFIG.sitemap_priority),
        (SEED, 0, DiscoverySource.start, model.CONFIG.start_priority),
        (done, 0, DiscoverySource.start, model.CONFIG.start_priority),
        (OUT_OF_SCOPE, 1, DiscoverySource.link, model.CONFIG.link_priority),
    ):
        enqueue(run, frontier, url, depth=depth, via=via, priority=priority)
    finished = frontier.entry(done)
    assert finished is not None
    finished.status = FrontierStatus.done
    assert dry_run_listing(run, frontier) == [SEED, ORPHAN, RELATIVE, FROM_LLMS, deferred]


def test_the_dry_run_listing_includes_rows_on_a_retired_host(tmp_path: Path) -> None:
    """crawl.allium DryRun guidance (ecfa257): pending_rows, a retired host's included.

    The listing is every row SelectBatch's pending_rows would hold, so a row whose host
    has tripped its breaker is still listed.
    """
    run, frontier = dry(tmp_path)
    host = open_host(run, HOST, SITE, site())
    assert host is not None
    assert host.breaker is not None
    host.breaker.status = BreakerStatus.tripped
    assert host.breaker_tripped
    enqueue(
        run,
        frontier,
        SEED,
        depth=0,
        via=DiscoverySource.start,
        priority=model.CONFIG.start_priority,
    )
    assert dry_run_listing(run, frontier) == [SEED]


# --- Discovery's tries, pauses and declaredness (T13 follow-up, crawl.allium ecfa257) --


def past_cap(url: str, status: int = TOO_MANY) -> SiteResponse:
    """A retryable answer whose Retry-After is one second past retry_after_cap."""
    wait = standard_policy().retry_after_cap + timedelta(seconds=1)
    return dataclasses.replace(xml_response(url, "", status=status), retry_after=wait)


@pytest.mark.parametrize(
    ("probe", "index"),
    [
        pytest.param(SITEMAP, None, id="sitemap"),
        pytest.param(SITEMAP_INDEX, None, id="sitemap-index"),
        pytest.param(LLMS_TXT, None, id="llms-txt"),
        pytest.param(MAPS, SITEMAP_INDEX, id="speculative-index-child"),
    ],
)
def test_a_speculative_probe_past_the_cap_pauses_the_host_silently(
    tmp_path: Path, probe: str, index: str | None
) -> None:
    """FetchSitemap and ReadLlmsTxt, past_cap and not declared (crawl.allium ecfa257).

    A Retry-After past retry_after_cap on a speculative probe (an undeclared well-known
    sitemap, llms.txt, or a child of a speculative index) ends its tries with that
    answer: asked once, no retry. It never retires the host and reports no problem; the
    host is paused until retry_after_cap from then, with one HostBackedOff, so the next
    request waits that long, and the seed page is then fetched. The Retry-After is
    honoured, so it is counted.
    """
    fetcher = site()
    if index is not None:
        fetcher.responses[index] = xml_response(index, sitemapindex(probe))
    fetcher.responses[probe] = past_cap(probe, SERVICE_UNAVAILABLE)
    timer = SteppingTimer()
    stamping = StampingFetcher(fetcher, timer)
    result = run_crawl(request(new_mirror(tmp_path)), None, stamping, timer)
    run = result.run
    assert run.status is RunStatus.finished
    assert run.discovery_failures == []
    assert fetcher.requests.count(probe) == 1
    (host,) = run.hosts
    urls = [url for url, _ in stamping.stamps]
    asked = stamping.stamps[urls.index(probe)][1]
    until = asked + run.policy.retry_after_cap
    (backed_off,) = result.backed_off
    assert backed_off.host is host
    assert backed_off.until == until
    assert stamping.stamps[urls.index(probe) + 1][1] >= until
    assert SEED in urls
    assert host.retry_after_honored == 1
    assert not host.breaker_tripped


def test_a_speculative_pause_never_shortens_a_longer_one(tmp_path: Path) -> None:
    """ReadLlmsTxt (crawl.allium ecfa257): paused_until = later_of(paused_until, now + cap).

    The HostBackedOff still carries now + retry_after_cap; the probe ends unavailable and
    silent, and nothing is discovered from it.
    """
    fetcher = site()
    fetcher.responses[LLMS_TXT] = past_cap(LLMS_TXT)
    run, frontier, host = host_open(tmp_path, fetcher)
    longer = START + run.policy.retry_after_cap + timedelta(hours=1)
    host.paused_until = longer
    response = read_llms_txt(run, HOST, frontier, fetcher)
    assert response is not None
    assert not response.ok
    assert fetcher.requests == [ROBOTS, LLMS_TXT]
    assert host.paused_until == longer
    (backed_off,) = run.backoffs
    assert backed_off.until == START + run.policy.retry_after_cap
    assert frontier.entries == []
    assert run.discovery_failures == []


def test_a_long_retry_after_unhonoured_neither_pauses_nor_retires(tmp_path: Path) -> None:
    """FetchSitemap and ReadLlmsTxt guidance (ecfa257): with honor_retry_after off.

    past_cap is false: a declared sitemap and every probe are retried as any retryable
    answer is, nothing is counted, no pause reaches retry_after_cap, the host is not
    retired, and the declared sitemap ends sitemap_unavailable.
    """
    policy = dataclasses.replace(standard_policy(), honor_retry_after=False)
    fetcher = site(robots=declaring(MAPS))
    for url in (MAPS, *PROBES):
        fetcher.responses[url] = past_cap(url)
    result = run_crawl(request(new_mirror(tmp_path), policy=policy), None, fetcher, FixedClock())
    run = result.run
    assert run.status is RunStatus.finished
    assert [(failed.url, failed.problem) for failed in run.discovery_failures] == [
        (MAPS, DiscoveryProblem.sitemap_unavailable)
    ]
    for url in (MAPS, *PROBES):
        assert fetcher.requests.count(url) == model.CONFIG.http_attempts, url
    (host,) = run.hosts
    assert host.retry_after_honored == 0
    assert not host.breaker_tripped
    assert result.backed_off
    assert all(off.until < START + policy.retry_after_cap for off in result.backed_off)
    assert SEED in fetcher.requests


def test_discovery_tries_count_every_honoured_retry_after(tmp_path: Path) -> None:
    """FetchRobots guidance and CountRetryAfter (crawl.allium ecfa257).

    robots.txt, a declared sitemap, a probe and llms.txt are each retried once after a
    retryable answer carrying a Retry-After (a 500, a 502, a 503, a 429), each with a
    HostBackedOff, and every one of the four honoured Retry-Afters is counted.
    """
    wait = timedelta(seconds=2)
    busy = {
        url: dataclasses.replace(xml_response(url, "", status=status), retry_after=wait)
        for url, status in (
            (ROBOTS, SERVER_ERROR),
            (MAPS, BAD_GATEWAY),
            (SITEMAP, SERVICE_UNAVAILABLE),
            (LLMS_TXT, TOO_MANY),
        )
    }
    responses = site(robots=declaring(MAPS)).responses
    responses[MAPS] = xml_response(MAPS, urlset((ORPHAN, None)))
    responses[LLMS_TXT] = llms(FROM_LLMS)
    fetcher = ScriptedFetcher(responses, {url: [answer] for url, answer in busy.items()})
    run, frontier = discovered(tmp_path, fetcher)
    for url in busy:
        assert fetcher.count(url) == len(["busy", "answered"]), url
    host = run.host(HOST)
    assert host is not None
    assert host.retry_after_honored == len(busy)
    assert len(run.backoffs) == len(busy)
    assert run.discovery_failures == []
    assert frontier.entry(ORPHAN) is not None
    assert frontier.entry(FROM_LLMS) is not None


def test_an_index_child_is_declared_exactly_when_its_index_is(tmp_path: Path) -> None:
    """ExpandSitemapEntries (crawl.allium ecfa257, answer A): children inherit declared.

    The children of a speculative index (the undeclared /sitemap_index.xml), at any
    depth, are speculative probes: a 500 child and an HTML child report nothing. The
    same tree under a declared index reports both. The urlset child is read either way.
    """
    broken = f"{SITE}/maps/broken.xml"
    page_map = f"{SITE}/maps/page.html"

    def tree(fetcher: FakeFetcher) -> FakeFetcher:
        fetcher.responses[SITEMAP_INDEX] = xml_response(SITEMAP_INDEX, sitemapindex(MAPS_INDEX))
        fetcher.responses[MAPS_INDEX] = xml_response(
            MAPS_INDEX, sitemapindex(broken, page_map, MAPS)
        )
        fetcher.responses[broken] = xml_response(broken, "", status=SERVER_ERROR)
        fetcher.responses[page_map] = html_response(page_map, PAGE)
        fetcher.responses[MAPS] = xml_response(MAPS, urlset((ORPHAN, None)))
        return fetcher

    speculative = tree(site())
    run, frontier = discovered(tmp_path / "speculative", speculative)
    assert run.discovery_failures == []
    assert all(url in speculative.requests for url in (broken, page_map, MAPS))
    assert frontier.entry(ORPHAN) is not None

    declared = tree(site(robots=declaring(SITEMAP_INDEX)))
    run, frontier = discovered(tmp_path / "declared", declared)
    assert [(failed.url, failed.problem) for failed in run.discovery_failures] == [
        (broken, DiscoveryProblem.sitemap_unavailable),
        (page_map, DiscoveryProblem.not_a_sitemap),
    ]
    assert frontier.entry(ORPHAN) is not None


def test_a_sitemap_or_index_child_with_no_identity_is_skipped_uncounted(tmp_path: Path) -> None:
    """ReadRobotsBeforeSitemap, FetchSitemap, ExpandSitemapEntries (crawl.allium ecfa257).

    A declared sitemap and an index child whose URL has no identity (a port out of
    range, an unclosed IPv6 bracket) are skipped silently: never requested, no problem,
    and no child counted toward sitemap_children_read; nothing raises.
    """
    fetcher = site(robots=declaring(NO_IDENTITY_MAP, MAPS_INDEX))
    fetcher.responses[MAPS_INDEX] = xml_response(
        MAPS_INDEX, sitemapindex(NO_IDENTITY_MAP, "http://[", MAPS)
    )
    fetcher.responses[MAPS] = xml_response(MAPS, urlset((ORPHAN, None)))
    run, frontier = discovered(tmp_path, fetcher)
    assert fetcher.requests == [ROBOTS, MAPS_INDEX, MAPS, *PROBES]
    host = run.host(HOST)
    assert host is not None
    assert host.sitemap_children_read == 1
    assert run.discovery_failures == []
    assert frontier.entry(ORPHAN) is not None
