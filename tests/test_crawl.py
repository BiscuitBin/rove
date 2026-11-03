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
from datetime import timedelta
from pathlib import Path

import httpx

from fakes import START, FakeFetcher, FixedClock, html_response, not_found, text_response
from rovo._convert import profiles
from rovo._convert.model import QualityFlag
from rovo._crawl import model
from rovo._crawl.fetch import HttpxFetcher
from rovo._crawl.model import (
    BlockKind,
    BlockVerdict,
    BreakerStatus,
    CrawlPolicy,
    DiscoverySource,
    FetchAttempt,
    Frontier,
    FrontierEntry,
    FrontierStatus,
    LadderWalk,
    RenderMode,
    RenderReason,
    RobotsMode,
    RobotsStance,
    Run,
    RunKind,
    RunMode,
    RunRequest,
    RunStatus,
    SiteResponse,
    StealthMode,
    WalkStatus,
    standard_policy,
)
from rovo._crawl.run import (
    CrawlResult,
    adopt_robots_rules,
    allow_all_when_robots_absent,
    attach_frontier,
    attempt_tier,
    begin_crawl,
    convert_fetched,
    create_frontier,
    discover,
    dispose_fetch,
    drop_stale_observations,
    end_run,
    enqueue,
    fetch_entry,
    fetch_robots,
    finish_run,
    load_frontier,
    load_runs,
    next_batch,
    next_run_id,
    open_host,
    open_host_for_entry,
    prepare_attempt,
    prepare_run,
    proceed_with_known_host,
    render_reason_of,
    robots_allows,
    run_crawl,
    select_batch,
    settle_stored_entry,
    settle_walk,
    skip_robots_disallowed,
    skip_robots_disallowed_on_new_host,
    start_run,
)
from rovo._mirror.intake import admit_candidate, take_candidate
from rovo._mirror.model import (
    CandidateOutcome,
    CrawlScope,
    Mirror,
    Operator,
    Tier,
)
from rovo._mirror.state import save_mirror
from spec_values import spec_duration, spec_float, spec_int

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
FORBIDDEN = 403
MOVED = 301
SECOND_RUN = 2
THIRD_RUN = 3


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
    assert fetcher.requests == ["https://api.example/robots.txt", ROBOTS]


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
    """Verify rule OpenHost succeeds when all preconditions are met."""
    fetcher = site()
    run, _ = started(tmp_path)
    host = open_host(run, HOST, SITE, fetcher)
    assert host is not None
    assert run.hosts == [host]
    assert fetcher.requests == [ROBOTS]  # OpenHost raises RobotsRequested


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
    /robots.txt, then the seed, then nothing.
    """
    robots = text_response(ROBOTS, RULES)
    fetcher = site(robots=robots)
    run, _ = started(tmp_path)
    open_host(run, HOST, SITE, fetcher)
    assert run.bytes_fetched == robots.size
    assert run.robots_policy(SITE) is not None

    order = site(robots=robots)
    crawl_once(tmp_path / "order", order)
    assert order.requests == [ROBOTS, SEED]


def test_rule_failure_FetchRobots_1(tmp_path: Path) -> None:
    """Verify rule FetchRobots is rejected when requires clause fails.

    requires: run.status = running.
    """
    fetcher = site()
    run, _ = started(tmp_path)
    open_host(run, HOST, SITE, fetcher)
    run.robots_policies.clear()
    run.status = RunStatus.finished
    assert fetch_robots(run, HOST, fetcher) is None
    assert fetcher.requests == [ROBOTS]
    assert run.robots_policies == []


def test_rule_failure_FetchRobots_2(tmp_path: Path) -> None:
    """Verify rule FetchRobots is rejected when requires clause fails.

    requires: exists host.
    """
    fetcher = site()
    run, _ = started(tmp_path)
    assert fetch_robots(run, HOST, fetcher) is None
    assert fetcher.requests == []
    assert run.bytes_fetched == 0


def test_rule_failure_FetchRobots_3(tmp_path: Path) -> None:
    """Verify rule FetchRobots is rejected when requires clause fails.

    requires: not exists RobotsPolicy{run: run, origin: host.origin}.
    """
    fetcher = site()
    run, _ = started(tmp_path)
    open_host(run, HOST, SITE, fetcher)
    before = run.bytes_fetched
    assert fetch_robots(run, HOST, fetcher) is None
    assert fetcher.requests == [ROBOTS]
    assert run.bytes_fetched == before


def test_rule_success_AdoptRobotsRules(tmp_path: Path) -> None:
    """Verify rule AdoptRobotsRules succeeds when all preconditions are met.

    The policy is parsed for the user agent rovo; the host-rate effect is the politeness
    slice's.
    """
    run, _ = started(tmp_path)
    open_host(run, HOST, SITE, site(robots=text_response(ROBOTS, RULES)))
    policy = run.robots_policy(SITE)
    assert policy is not None
    assert policy.stance is RobotsStance.rules
    assert robots_allows(run, SEED)
    assert not robots_allows(run, f"{SITE}/private/notes.html")


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
    lastmod and promotes a deferred row, and never changes the status.
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


def test_rule_success_DropStaleObservations(tmp_path: Path) -> None:
    """Verify rule DropStaleObservations succeeds when all preconditions are met."""
    run, frontier = started(tmp_path)
    assert drop_stale_observations(run, frontier)
    assert frontier.observed_urls == []


def test_rule_failure_DropStaleObservations_1(tmp_path: Path) -> None:
    """Verify rule DropStaleObservations is rejected when requires clause fails.

    requires: run.status = running.
    """
    run, frontier = started(tmp_path)
    run.status = RunStatus.finished
    assert not drop_stale_observations(run, frontier)


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

    When no row is in progress, a crawling run asks for another batch.
    """
    run, frontier = crawling(tmp_path, site())
    assert next_batch(run, frontier)
    select_batch(run, frontier)
    assert not next_batch(run, frontier)


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
    assert fetcher.requests == [ROBOTS]


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
    assert fetcher.requests == [ROBOTS, SEED]
    assert fetcher.validators == [None, None]  # no known page: an unconditional fetch


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
    assert fetcher.requests == [ROBOTS]
    assert entry.attempts == 0
    assert run.fetch_attempts == 0


def test_rule_failure_FetchEntry_2(tmp_path: Path) -> None:
    """Verify rule FetchEntry is rejected when requires clause fails.

    requires: robots_allows(run, entry.identity).
    """
    fetcher = site(robots=text_response(ROBOTS, DISALLOW_GUIDE))
    run, _, entry = selected(tmp_path, fetcher)
    assert fetch_entry(run, entry, fetcher) is None
    assert fetcher.requests == [ROBOTS]
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
    assert fetcher.requests == [ROBOTS, SEED]
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
    """Verify invariant OneRobotsPolicyPerOrigin holds after every state-changing rule that touches constrained entities."""  # noqa: E501  The obligation's description, quoted.
    fetcher = site(robots=text_response(ROBOTS, RULES))
    run, _ = started(tmp_path)
    open_host(run, HOST, SITE, fetcher)
    fetch_robots(run, HOST, fetcher)
    origins = [policy.origin for policy in run.robots_policies]
    assert origins == [SITE]


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
    assert not ok.may_carry_retry_after
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
    """One fetch is one request, sending `User-Agent: rovo/<version>` (crawl.allium 1248)."""
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
