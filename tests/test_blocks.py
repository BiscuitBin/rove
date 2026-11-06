"""Blocks and the breaker (T18): crawl.allium's block verdicts, breaker and retirements.

Each obligation test is named after the id `just plan-spec crawl` emits (at 86e2ec5,
unchanged from 663fb9a; the T18-2 answers' nine at 7d01367), dots and hyphens as
underscores, and its docstring quotes the obligation. A `rule_failure` test makes
exactly one `requires` clause false. The rest are the ticket's hand-written guarantees:
classify_block (AttemptTier guidance, crawl.allium 1597 to 1611), the main-text length,
FeedBreaker's text history, DisposeFetch's branch order, a soft verdict converted, each
retirement path, BreakerStopsTheRun (no request of any kind to a tripped host, 2376),
BlockedWithinFetched, BrowserRendersContentNeverAnswersBlocks, the targeted sweep, host
isolation, config rather than literals, and a block keeping a mirrored page. Every
count, ratio and cap is read from CONFIG or the run's policy.
"""

import dataclasses
from datetime import timedelta
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from fakes import (
    FakeFetcher,
    FixedClock,
    html_response,
    redirect_response,
    text_response,
    xml_response,
)
from rovo import _commands
from rovo._convert import fidelity, profiles
from rovo._convert.fidelity import main_text_length
from rovo._convert.model import QualityFlag
from rovo._crawl import model, pace
from rovo._crawl import run as run_module
from rovo._crawl.model import (
    BlockKind,
    BlockVerdict,
    Breaker,
    BreakerStatus,
    BreakerTripped,
    DiscoveryProblem,
    DiscoverySource,
    FetchAttempt,
    Frontier,
    FrontierStatus,
    Host,
    LadderWalk,
    ProgressEvent,
    RenderMode,
    RenderReason,
    Run,
    RunStatus,
    SiteResponse,
    UrlBlocked,
    UrlSkippedBlocked,
    WalkStatus,
    standard_policy,
)
from rovo._crawl.run import (
    CrawlResult,
    breaker_trips,
    classify_block,
    dispose_fetch,
    drive_run,
    enqueue,
    feed_breaker,
    load_frontier,
    open_host,
    open_host_for_entry,
    prepare_run,
    retire_host_on_long_crawl_delay,
    retire_host_on_long_retry_after,
    run_crawl,
    select_batch,
    skip_robots_disallowed_on_new_host,
    skip_tripped_host,
    skip_tripped_host_after_ready,
    status_text,
    stop_walk_on_tripped_host,
)
from rovo._exit import ExitCode
from rovo._mirror.model import Mirror, Tier
from rovo._mirror.state import load_mirror
from rovo._unfinished import NotInThisSlice
from spec_values import spec_enum, spec_float, spec_int
from test_crawl import (
    DISALLOW_GUIDE,
    HOST,
    NOSCRIPT_PAGE,
    OTHER,
    PAGE,
    PORTED_PAGE,
    PORTED_ROBOTS,
    ROBOTS,
    SEED,
    SITE,
    assert_fields,
    attempt_on,
    crawling,
    crawling_without_hosts,
    in_progress,
    new_mirror,
    request,
    settled_on,
    started,
    update_request,
    walk_with,
)

CRAWL = model.CONFIG
# The outcomes a breaker needs before it may act, and the fewest blocked among them that
# put its block rate past block_rate_threshold (Breaker.over_threshold).
COUNT = min(CRAWL.breaker_window, CRAWL.breaker_min_outcomes)
BLOCKING = int(COUNT * CRAWL.block_rate_threshold) + 1
CAP = standard_policy().retry_after_cap
PAST_CAP = CAP + timedelta(seconds=1)
FORBIDDEN = 403
UNAUTHORIZED = 401
TOO_MANY = 429
NOT_FOUND = 404
SERVICE_UNAVAILABLE = 503
OTHER_HOST = "api.example"
OTHER_SITE = f"http://{OTHER_HOST}"
LOGIN_FORM = '<form><input type="text" name="user"><input type="password" name="pw"></form>'
SITEMAP_ONE = f"{SITE}/maps/one.xml"
SITEMAP_TWO = f"{SITE}/maps/two.xml"
SOFT_SITE = Path(__file__).resolve().parent / "fixtures" / "sites" / "soft"


def page_url(number: int, site: str = SITE) -> str:
    """The guide's numbered page on `site`."""
    return f"{site}/guide/p{number:02}.html"


def prose_page(number: int, *, extra: str = "") -> str:
    """The one-page fixture's page, retitled and given a sentence of its own."""
    prose = f"Page {number} explains setting {number} of the example product in full."
    return PAGE.replace("<h1>Getting started</h1>", f"<h1>Page {number}</h1><p>{prose}</p>{extra}")


def thin_page() -> str:
    """A page whose main text is a word or two: far under any prose page's."""
    return (
        "<!doctype html><html><head><title>Notes</title></head>"
        "<body><main><h1>Notes</h1><p>Soon.</p></main></body></html>"
    )


def blocked_answer(url: str, status: int) -> SiteResponse:
    """A block answered with `status` and an HTML body."""
    return html_response(url, "<html><body><p>Access denied.</p></body></html>", status=status)


def long_retry_after(url: str, status: int = TOO_MANY) -> SiteResponse:
    """A retryable answer whose Retry-After is one second past the standard cap."""
    return dataclasses.replace(html_response(url, "", status=status), retry_after=PAST_CAP)


def breach_responses(total: int, *, site: str = SITE) -> dict[str, SiteResponse]:
    """`total` numbered pages: the first BLOCKING answer 403, the rest prose pages."""
    responses: dict[str, SiteResponse] = {}
    for number in range(1, total + 1):
        url = page_url(number, site)
        responses[url] = (
            blocked_answer(url, FORBIDDEN)
            if number <= BLOCKING
            else html_response(url, prose_page(number))
        )
    return responses


def seeded_mirror(out_dir: Path, seeds: tuple[str, ...], **changes: object) -> Mirror:
    """The fixture mirror, its start URLs `seeds`."""
    return new_mirror(out_dir, start_urls=seeds, **changes)


def crawl_seeds(
    out_dir: Path,
    seeds: tuple[str, ...],
    fetcher: FakeFetcher,
    **changes: object,
) -> CrawlResult:
    """One standard full run whose seeds are `seeds`, over `fetcher`."""
    mirror = seeded_mirror(out_dir, seeds)
    return run_crawl(request(mirror, **changes), None, fetcher, FixedClock())  # type: ignore[arg-type]  # Test overrides by name.


def breached(out_dir: Path, total: int = COUNT + 3) -> tuple[CrawlResult, FakeFetcher]:
    """A run of `total` seeds whose first BLOCKING answer 403: it trips on the COUNTth walk."""
    seeds = tuple(page_url(number) for number in range(1, total + 1))
    fetcher = FakeFetcher(breach_responses(total))
    return crawl_seeds(out_dir, seeds, fetcher), fetcher


def the_host(run: Run, name: str = HOST) -> Host:
    """The run's host `name`."""
    host = run.host(name)
    assert host is not None
    return host


def the_breaker(host: Host) -> Breaker:
    """The host's breaker."""
    assert host.breaker is not None
    return host.breaker


def opened_host(out_dir: Path, fetcher: FakeFetcher | None = None) -> tuple[Run, Frontier, Host]:
    """A started run with its host opened (robots.txt read from `fetcher`, else absent)."""
    run, frontier = started(out_dir)
    host = open_host(run, HOST, SITE, fetcher or FakeFetcher({}))
    assert host is not None
    return run, frontier, host


def over_threshold(breaker: Breaker) -> None:
    """Fill the breaker's window with COUNT outcomes, BLOCKING of them blocks."""
    breaker.outcomes = [index < BLOCKING for index in range(COUNT)]
    assert breaker.should_act


def walking_attempt(run: Run, frontier: Frontier, response: SiteResponse) -> FetchAttempt:
    """A walking walk of the seed's in-progress row whose one http attempt answered `response`."""
    entry = in_progress(run, frontier, SEED)
    walk = LadderWalk(
        entry=entry,
        host=the_host(run),
        tiers=(Tier.http,),
        conditional=False,
        escalated=False,
        challenge_offered=False,
        status=WalkStatus.walking,
    )
    return attempt_on(walk, response)


def with_verdict(walk: LadderWalk, kind: BlockKind, signature: str) -> FetchAttempt:
    """The walk's standing attempt, its verdict replaced by `kind`."""
    standing = walk.standing
    assert standing is not None
    standing.verdict = BlockVerdict(kind=kind, signature=signature)
    return standing


def skipped_urls(result: CrawlResult) -> list[str]:
    """The URLs of the run's UrlSkippedBlocked events, in order."""
    return [event.url for event in result.skipped]


def status_of(frontier: Frontier, identity: str) -> FrontierStatus:
    """The frontier row's status."""
    entry = frontier.entry(identity)
    assert entry is not None
    return entry.status


@pytest.fixture
def altered_config(monkeypatch: pytest.MonkeyPatch) -> model.CrawlConfig:
    """CONFIG with non-default breaker and soft-verdict values, in every crawl module."""
    altered = dataclasses.replace(
        CRAWL,
        breaker_min_outcomes=4,
        block_rate_threshold=0.5,
        soft_block_ratio=0.5,
        median_min_pages=2,
    )
    for module in (model, run_module, pace):
        if hasattr(module, "CONFIG"):
            monkeypatch.setattr(module, "CONFIG", altered)
    return altered


# --- Values, enums and derived values ---------------------------------------------------


def test_value_equality_BlockVerdict() -> None:
    """Verify value type BlockVerdict has structural equality.

    Two verdicts with the same kind and signature are equal and hash alike; either field
    differing makes them unequal; classify_block gives equal verdicts for equal answers.
    """
    verdict = BlockVerdict(kind=BlockKind.hard, signature="403 Forbidden")
    same = BlockVerdict(kind=BlockKind.hard, signature="403 Forbidden")
    assert verdict == same
    assert hash(verdict) == hash(same)
    assert verdict != dataclasses.replace(verdict, kind=BlockKind.challenge)
    assert verdict != dataclasses.replace(verdict, signature="401 Unauthorized")
    forbidden = blocked_answer(SEED, FORBIDDEN)
    assert classify_block(forbidden, None) == classify_block(forbidden, None) == verdict


def test_entity_fields_BlockVerdict() -> None:
    """Verify all declared fields on BlockVerdict are present with correct types.

    kind, signature and the derived counts_against_host (hard or challenge), on the
    verdicts classify_block gives.
    """
    for response in (html_response(SEED, PAGE), blocked_answer(SEED, FORBIDDEN)):
        verdict = classify_block(response, None)
        assert_fields(verdict, ("kind", "signature", "counts_against_host"))
        assert isinstance(verdict.kind, BlockKind)
        assert isinstance(verdict.signature, str)
        assert isinstance(verdict.counts_against_host, bool)
    for kind in BlockKind:
        verdict = BlockVerdict(kind=kind, signature="")
        assert verdict.counts_against_host is (kind in {BlockKind.hard, BlockKind.challenge})


def test_enum_comparable_BlockKind() -> None:
    """Verify fields typed with enum BlockKind are comparable.

    The enum's values are the specification's, in order; each verdict classify_block
    gives compares equal to its own member only.
    """
    assert tuple(kind.value for kind in BlockKind) == spec_enum("crawl", "BlockKind")
    kinds = [
        classify_block(html_response(SEED, PAGE), None).kind,
        classify_block(blocked_answer(SEED, FORBIDDEN), None).kind,
        classify_block(html_response(SEED, prose_page(1, extra=LOGIN_FORM)), None).kind,
    ]
    assert kinds == [BlockKind.none, BlockKind.hard, BlockKind.soft]
    assert kinds[1] != BlockKind.challenge
    assert len(set(kinds)) == len(kinds)


def test_projection_Run_tripped_hosts(tmp_path: Path) -> None:
    """Verify projection Run.tripped_hosts filters correctly.

    Of two hosts, only the one whose breaker tripped is listed; after a run whose host
    breaches the threshold, that host is.
    """
    run, _, host = opened_host(tmp_path / "unit")
    other = open_host(run, OTHER_HOST, OTHER_SITE, FakeFetcher({}))
    assert other is not None
    assert run.tripped_hosts == []
    the_breaker(other).status = BreakerStatus.tripped
    assert run.tripped_hosts == [other]
    assert host not in run.tripped_hosts
    result, _ = breached(tmp_path / "run")
    assert result.run.tripped_hosts == [the_host(result.run)]


def test_derived_Run_has_tripped_host(tmp_path: Path) -> None:
    """Verify derived value Run.has_tripped_host computes correctly.

    has_tripped_host: tripped_hosts.count > 0: false for a run whose host serves its
    pages, true for one whose host breached the threshold.
    """
    run, _, host = opened_host(tmp_path / "unit")
    seen = [run.has_tripped_host]
    the_breaker(host).status = BreakerStatus.tripped
    seen.append(run.has_tripped_host)
    assert seen == [False, True]
    healthy = crawl_seeds(
        tmp_path / "healthy", (SEED,), FakeFetcher({SEED: html_response(SEED, PAGE)})
    )
    assert healthy.run.has_tripped_host is False
    result, _ = breached(tmp_path / "run")
    assert result.run.has_tripped_host is True


def test_derived_Host_has_text_baseline(tmp_path: Path) -> None:
    """Verify derived value Host.has_text_baseline computes correctly.

    recent_text_lengths.count >= config.median_min_pages: one short is false, exactly
    that many is true; a run of that many prose pages gives its host a baseline, each
    length the page's main text.
    """
    _, _, host = opened_host(tmp_path / "unit")
    host.recent_text_lengths = [1] * (CRAWL.median_min_pages - 1)
    seen = [host.has_text_baseline]
    host.recent_text_lengths = [1] * CRAWL.median_min_pages
    seen.append(host.has_text_baseline)
    assert seen == [False, True]
    seeds = tuple(page_url(number) for number in range(1, CRAWL.median_min_pages + 1))
    fetcher = FakeFetcher(
        {url: html_response(url, prose_page(n)) for n, url in enumerate(seeds, 1)}
    )
    result = crawl_seeds(tmp_path / "run", seeds, fetcher)
    ran = the_host(result.run)
    assert ran.recent_text_lengths == [
        main_text_length(prose_page(number), profiles.GENERIC)
        for number in range(1, CRAWL.median_min_pages + 1)
    ]
    assert ran.has_text_baseline is True


def test_derived_Host_breaker_tripped(tmp_path: Path) -> None:
    """Verify derived value Host.breaker_tripped computes correctly.

    breaker?.status = tripped: false with no breaker or a watching one, true once it has
    tripped; true for the host of a run that breached the threshold.
    """
    _, _, host = opened_host(tmp_path / "unit")
    breaker = the_breaker(host)
    seen = [host.breaker_tripped]
    host.breaker = None
    seen.append(host.breaker_tripped)
    host.breaker = breaker
    breaker.status = BreakerStatus.tripped
    seen.append(host.breaker_tripped)
    assert seen == [False, False, True]
    result, _ = breached(tmp_path / "run")
    assert the_host(result.run).breaker_tripped is True


def test_derived_Breaker_should_act(tmp_path: Path) -> None:
    """Verify derived value Breaker.should_act computes correctly.

    status = watching and over_threshold and (tier != highest_tier or escalations = 0 or
    since_escalation >= config.breaker_window): each conjunct and each disjunct alone.
    """
    _, _, host = opened_host(tmp_path)
    breaker = the_breaker(host)
    breaker.outcomes = [index < BLOCKING for index in range(COUNT - 1)]
    seen = [breaker.should_act]  # Too few outcomes.
    breaker.outcomes = [index < BLOCKING - 1 for index in range(COUNT)]
    seen.append(breaker.should_act)  # Rate not past the threshold.
    breaker.outcomes = [index < BLOCKING for index in range(COUNT)]
    assert breaker.tier is breaker.highest_tier
    assert breaker.escalations == 0
    seen.append(breaker.should_act)  # Over the threshold, never escalated.
    breaker.escalations = 1
    breaker.since_escalation = CRAWL.breaker_window - 1
    seen.append(breaker.should_act)  # At the highest tier, waiting out an escalation.
    breaker.since_escalation = CRAWL.breaker_window
    seen.append(breaker.should_act)  # The escalation waited out.
    breaker.since_escalation = 0
    breaker.highest_tier = Tier.browser
    seen.append(breaker.should_act)  # Below the highest tier.
    breaker.status = BreakerStatus.tripped
    seen.append(breaker.should_act)  # Tripped.
    assert seen == [False, False, True, False, True, True, False]


def test_projection_LadderWalk_soft_suspect(tmp_path: Path) -> None:
    """Verify projection LadderWalk.soft_suspect filters correctly.

    attempts where verdict.kind = soft and render_reason = null: a soft attempt with no
    render reason is listed; a soft one with a render reason, a hard one and an
    unblocked one are not.
    """
    run, frontier, _ = opened_host(tmp_path)
    attempt = walking_attempt(run, frontier, html_response(SEED, PAGE))
    walk = attempt.walk
    attempt.verdict = BlockVerdict(kind=BlockKind.soft, signature="login wall")
    rendered = attempt_on(walk, html_response(SEED, PAGE), try_=2)
    rendered.verdict = BlockVerdict(kind=BlockKind.soft, signature="login wall")
    rendered.render_reason = RenderReason.thin_text
    hard = attempt_on(walk, blocked_answer(SEED, FORBIDDEN), try_=3)
    hard.verdict = BlockVerdict(kind=BlockKind.hard, signature="403 Forbidden")
    attempt_on(walk, html_response(SEED, PAGE), try_=4)
    assert walk.soft_suspect == [attempt]


def test_config_default_soft_block_ratio() -> None:
    """Verify config parameter soft_block_ratio has its declared default."""
    assert CRAWL.soft_block_ratio == spec_float("crawl", "soft_block_ratio")


def test_config_default_median_min_pages() -> None:
    """Verify config parameter median_min_pages has its declared default."""
    assert CRAWL.median_min_pages == spec_int("crawl", "median_min_pages")


# --- Frontier edges -------------------------------------------------------------------


def test_transition_edge_FrontierEntry_pending_skipped_blocked(tmp_path: Path) -> None:
    """Verify transition pending -> skipped_blocked on FrontierEntry.status is reachable via a witnessing rule.

    SelectBatch's all-tripped branch: every pending row is on a tripped host, so each
    becomes skipped_blocked with a UrlSkippedBlocked and the frontier is exhausted. In a
    run, BreakerTrips sweeps the host's rows still pending.
    """  # noqa: E501  The obligation's description, quoted.
    run, frontier = crawling(tmp_path / "unit", FakeFetcher({SEED: html_response(SEED, PAGE)}))
    (entry,) = frontier.entries
    before = entry.status
    the_breaker(the_host(run)).status = BreakerStatus.tripped
    assert select_batch(run, frontier) == []
    assert (before, entry.status) == (FrontierStatus.pending, FrontierStatus.skipped_blocked)
    total = COUNT + CRAWL.concurrency_per_host + 1
    result, _ = breached(tmp_path / "run", total)
    last = page_url(total)
    assert status_of(result.frontier, last) is FrontierStatus.skipped_blocked
    assert last in skipped_urls(result)


def test_transition_edge_FrontierEntry_in_progress_blocked(tmp_path: Path) -> None:
    """Verify transition in_progress -> blocked on FrontierEntry.status is reachable via a witnessing rule.

    DisposeFetch's hard branch: a 403 settles the row blocked and raises UrlBlocked with
    its status, signature and tier.
    """  # noqa: E501  The obligation's description, quoted.
    run, frontier, _ = opened_host(tmp_path)
    walk = settled_on(run, frontier, blocked_answer(SEED, FORBIDDEN))
    with_verdict(walk, BlockKind.hard, "403 Forbidden")
    blocked = dispose_fetch(walk)
    assert blocked == UrlBlocked(
        run=run, url=SEED, status=FORBIDDEN, signature="403 Forbidden", tier=Tier.http
    )
    assert walk.entry.status is FrontierStatus.blocked


def test_transition_edge_FrontierEntry_in_progress_skipped_blocked(tmp_path: Path) -> None:
    """Verify transition in_progress -> skipped_blocked on FrontierEntry.status is reachable via a witnessing rule.

    SkipTrippedHost: a row that comes into progress on a tripped host is skipped. In a
    run, the rows of the tripping batch not yet started meet it.
    """  # noqa: E501  The obligation's description, quoted.
    run, frontier, _ = opened_host(tmp_path / "unit")
    entry = in_progress(run, frontier, SEED)
    the_breaker(the_host(run)).status = BreakerStatus.tripped
    assert skip_tripped_host(run, entry) == UrlSkippedBlocked(run=run, url=SEED)
    assert entry.status is FrontierStatus.skipped_blocked
    result, _ = breached(tmp_path / "run", COUNT + 1)
    after = page_url(COUNT + 1)
    assert status_of(result.frontier, after) is FrontierStatus.skipped_blocked
    assert skipped_urls(result) == [after]


def test_transition_edge_FrontierEntry_blocked_pending(tmp_path: Path) -> None:
    """Verify transition blocked -> pending on FrontierEntry.status is reachable via a witnessing rule.

    PrepareRun retries a blocked row: a run blocks the seed, the next run re-pends it.
    """  # noqa: E501  The obligation's description, quoted.
    mirror = new_mirror(tmp_path)
    fetcher = FakeFetcher({SEED: blocked_answer(SEED, FORBIDDEN)})
    first = run_crawl(request(mirror), None, fetcher, FixedClock())
    assert status_of(first.frontier, SEED) is FrontierStatus.blocked
    persisted = load_frontier(mirror)
    assert persisted is not None
    assert status_of(persisted, SEED) is FrontierStatus.blocked
    second = run_module.start_run(update_request(mirror), FixedClock())
    assert second is not None
    frontier = run_module.attach_frontier(second, persisted)
    assert prepare_run(second, frontier)
    assert status_of(frontier, SEED) is FrontierStatus.pending


def test_transition_edge_FrontierEntry_skipped_blocked_pending(tmp_path: Path) -> None:
    """Verify transition skipped_blocked -> pending on FrontierEntry.status is reachable via a witnessing rule.

    PrepareRun retries a skipped_blocked row: a run whose host retires on a long
    Crawl-delay skips the seed, the next run re-pends it.
    """  # noqa: E501  The obligation's description, quoted.
    mirror = new_mirror(tmp_path)
    robots = text_response(ROBOTS, f"User-agent: *\nCrawl-delay: {CAP.total_seconds() + 1}\n")
    first = run_crawl(request(mirror), None, FakeFetcher({ROBOTS: robots}), FixedClock())
    assert status_of(first.frontier, SEED) is FrontierStatus.skipped_blocked
    persisted = load_frontier(mirror)
    assert persisted is not None
    second = run_module.start_run(update_request(mirror), FixedClock())
    assert second is not None
    frontier = run_module.attach_frontier(second, persisted)
    assert prepare_run(second, frontier)
    assert status_of(frontier, SEED) is FrontierStatus.pending


# --- The breaker's status -------------------------------------------------------------


def test_transition_edge_Breaker_watching_tripped(tmp_path: Path) -> None:
    """Verify transition watching -> tripped on Breaker.status is reachable via a witnessing rule.

    BreakerTrips on a breaker that should act; in a run, the COUNTth settled walk trips it.
    """
    _, frontier, host = opened_host(tmp_path / "unit")
    breaker = the_breaker(host)
    over_threshold(breaker)
    assert breaker_trips(breaker, frontier) == BreakerTripped(host=host)
    assert breaker.status is BreakerStatus.tripped
    result, _ = breached(tmp_path / "run")
    ran = the_host(result.run)
    assert the_breaker(ran).status is BreakerStatus.tripped
    assert result.tripped == (BreakerTripped(host=ran),)


def test_transition_rejected_Breaker_status(tmp_path: Path) -> None:
    """Verify undeclared transitions on Breaker.status are rejected.

    tripped -> watching is undeclared: a tripped breaker takes no outcome, BreakerTrips
    does not fire again, and it stays tripped for the run.
    """
    run, frontier, host = opened_host(tmp_path)
    breaker = the_breaker(host)
    over_threshold(breaker)
    assert breaker_trips(breaker, frontier) is not None
    outcomes = list(breaker.outcomes)
    walk = settled_on(run, frontier, html_response(SEED, PAGE))
    assert not feed_breaker(walk)
    assert breaker.outcomes == outcomes
    assert breaker_trips(breaker, frontier) is None
    assert breaker.status is BreakerStatus.tripped


def test_transition_terminal_Breaker_status(tmp_path: Path) -> None:
    """Verify terminal states on Breaker.status have no outbound transitions.

    Once tripped, no rule moves the breaker: BreakerTrips, RetireHostOnLongCrawlDelay
    and RetireHostOnLongRetryAfter raise no second BreakerTripped and it stays tripped.
    """
    run, frontier, host = opened_host(tmp_path)
    breaker = the_breaker(host)
    breaker.status = BreakerStatus.tripped
    over_threshold_outcomes = [index < BLOCKING for index in range(COUNT)]
    breaker.outcomes = over_threshold_outcomes
    assert breaker_trips(breaker, frontier) is None
    robots = text_response(ROBOTS, f"User-agent: *\nCrawl-delay: {CAP.total_seconds() + 1}\n")
    assert retire_host_on_long_crawl_delay(run, host, robots) is None
    attempt = walking_attempt(run, frontier, long_retry_after(SEED))
    assert retire_host_on_long_retry_after(attempt) is True
    assert breaker.status is BreakerStatus.tripped


# --- RetireHostOnLongCrawlDelay --------------------------------------------------------


def long_delay_robots() -> SiteResponse:
    """robots.txt declaring a Crawl-delay one second past the standard cap."""
    return text_response(ROBOTS, f"User-agent: *\nCrawl-delay: {CAP.total_seconds() + 1}\n")


def test_rule_success_RetireHostOnLongCrawlDelay(tmp_path: Path) -> None:
    """Verify rule RetireHostOnLongCrawlDelay succeeds when all preconditions are met.

    An ok robots.txt whose honoured Crawl-delay is past retry_after_cap trips the
    watching breaker and raises BreakerTripped. In a run, robots.txt is the only request:
    no sitemap, llms.txt or page follows (FetchRobots guidance 858 to 864), the seed is
    skipped and the run returns the trip.
    """
    run, _, host = opened_host(tmp_path / "unit")
    assert retire_host_on_long_crawl_delay(run, host, long_delay_robots()) == BreakerTripped(
        host=host
    )
    assert host.breaker_tripped
    fetcher = FakeFetcher({ROBOTS: long_delay_robots(), SEED: html_response(SEED, PAGE)})
    result = crawl_seeds(tmp_path / "run", (SEED,), fetcher)
    assert fetcher.requests == [ROBOTS]
    assert result.tripped == (BreakerTripped(host=the_host(result.run)),)
    assert skipped_urls(result) == [SEED]


def test_rule_failure_RetireHostOnLongCrawlDelay_1(tmp_path: Path) -> None:
    """Verify rule RetireHostOnLongCrawlDelay is rejected when requires clause fails.

    requires: response.ok: a robots.txt answering 404 with the same body retires nothing.
    """
    run, _, host = opened_host(tmp_path)
    refused = dataclasses.replace(long_delay_robots(), status=NOT_FOUND)
    assert retire_host_on_long_crawl_delay(run, host, refused) is None
    assert not host.breaker_tripped


def test_rule_failure_RetireHostOnLongCrawlDelay_2(tmp_path: Path) -> None:
    """Verify rule RetireHostOnLongCrawlDelay is rejected when requires clause fails.

    requires: run.policy.honor_crawl_delay: with Crawl-delay ignored, however large, the
    host is not retired and the seed is fetched.
    """
    ignoring = dataclasses.replace(standard_policy(), honor_crawl_delay=False)
    run, _, host = opened_host(tmp_path / "unit")
    run.policy = ignoring
    assert retire_host_on_long_crawl_delay(run, host, long_delay_robots()) is None
    assert not host.breaker_tripped
    fetcher = FakeFetcher({ROBOTS: long_delay_robots(), SEED: html_response(SEED, PAGE)})
    result = crawl_seeds(tmp_path / "run", (SEED,), fetcher, policy=ignoring)
    assert SEED in fetcher.requests
    assert not result.run.has_tripped_host


def test_rule_failure_RetireHostOnLongCrawlDelay_3(tmp_path: Path) -> None:
    """Verify rule RetireHostOnLongCrawlDelay is rejected when requires clause fails.

    requires: robots_crawl_delay_exceeds(response, run.policy.retry_after_cap): a
    Crawl-delay at the cap exactly is not past it.
    """
    run, _, host = opened_host(tmp_path)
    at_cap = text_response(ROBOTS, f"User-agent: *\nCrawl-delay: {CAP.total_seconds()}\n")
    assert retire_host_on_long_crawl_delay(run, host, at_cap) is None
    assert not host.breaker_tripped


# --- SkipTrippedHost ------------------------------------------------------------------


def test_rule_success_SkipTrippedHost(tmp_path: Path) -> None:
    """Verify rule SkipTrippedHost succeeds when all preconditions are met.

    A row in progress on a tripped host of the running run becomes skipped_blocked and
    UrlSkippedBlocked names it.
    """
    run, frontier, host = opened_host(tmp_path)
    entry = in_progress(run, frontier, SEED)
    the_breaker(host).status = BreakerStatus.tripped
    assert skip_tripped_host(run, entry) == UrlSkippedBlocked(run=run, url=SEED)
    assert entry.status is FrontierStatus.skipped_blocked


def test_rule_failure_SkipTrippedHost_1(tmp_path: Path) -> None:
    """Verify rule SkipTrippedHost is rejected when requires clause fails.

    requires: exists run (the mirror's running run): with the run finished, nothing.
    """
    run, frontier, host = opened_host(tmp_path)
    entry = in_progress(run, frontier, SEED)
    the_breaker(host).status = BreakerStatus.tripped
    run.status = RunStatus.finished
    assert skip_tripped_host(run, entry) is None
    assert skip_tripped_host(None, entry) is None
    assert entry.status is FrontierStatus.in_progress


def test_rule_failure_SkipTrippedHost_2(tmp_path: Path) -> None:
    """Verify rule SkipTrippedHost is rejected when requires clause fails.

    requires: exists host and host.breaker_tripped: a watching host's row, and a row on a
    host the run has not opened, are not skipped.
    """
    run, frontier, _ = opened_host(tmp_path)
    entry = in_progress(run, frontier, SEED)
    assert skip_tripped_host(run, entry) is None
    assert entry.status is FrontierStatus.in_progress
    unopened = in_progress(run, frontier, page_url(1, OTHER_SITE))
    assert skip_tripped_host(run, unopened) is None
    assert unopened.status is FrontierStatus.in_progress


# --- RetireHostOnLongRetryAfter -------------------------------------------------------


def test_rule_success_RetireHostOnLongRetryAfter(tmp_path: Path) -> None:
    """Verify rule RetireHostOnLongRetryAfter succeeds when all preconditions are met.

    An attempt whose Retry-After is past the cap trips the watching breaker
    (BreakerTripped), settles the walk with the attempt standing and adds its tier to
    the host's tiers_used. In a run, the 429 is asked once, is blocked, and every other
    row of the host is skipped.
    """
    run, frontier, host = opened_host(tmp_path / "unit")
    attempt = walking_attempt(run, frontier, long_retry_after(SEED))
    assert attempt.retires_host
    assert retire_host_on_long_retry_after(attempt) == BreakerTripped(host=host)
    assert host.breaker_tripped
    assert attempt.walk.status is WalkStatus.settled
    assert attempt.walk.standing is attempt
    assert Tier.http in host.tiers_used
    seeds = (page_url(1), page_url(2), page_url(3))
    fetcher = FakeFetcher(
        {
            seeds[0]: long_retry_after(seeds[0]),
            seeds[1]: html_response(seeds[1], prose_page(2)),
            seeds[2]: html_response(seeds[2], prose_page(3)),
        }
    )
    result = crawl_seeds(tmp_path / "run", seeds, fetcher)
    assert fetcher.requests.count(seeds[0]) == 1
    assert [(event.url, event.status) for event in result.blocked] == [(seeds[0], TOO_MANY)]
    assert skipped_urls(result) == list(seeds[1:])
    assert seeds[1] not in fetcher.requests


def test_rule_failure_RetireHostOnLongRetryAfter_1(tmp_path: Path) -> None:
    """Verify rule RetireHostOnLongRetryAfter is rejected when requires clause fails.

    requires: attempt.retires_host: a Retry-After at the cap exactly does not retire.
    """
    run, frontier, host = opened_host(tmp_path)
    at_cap = dataclasses.replace(long_retry_after(SEED), retry_after=CAP)
    attempt = walking_attempt(run, frontier, at_cap)
    assert retire_host_on_long_retry_after(attempt) is False
    assert not host.breaker_tripped
    assert attempt.walk.status is WalkStatus.walking


def test_rule_failure_RetireHostOnLongRetryAfter_2(tmp_path: Path) -> None:
    """Verify rule RetireHostOnLongRetryAfter is rejected when requires clause fails.

    requires: attempt.walk.status = walking and attempt.walk.host.run.status = running:
    a settled walk, or a run no longer running, retires nothing.
    """
    run, frontier, host = opened_host(tmp_path)
    attempt = walking_attempt(run, frontier, long_retry_after(SEED))
    attempt.walk.status = WalkStatus.settled
    assert retire_host_on_long_retry_after(attempt) is False
    assert not host.breaker_tripped
    attempt.walk.status = WalkStatus.walking
    run.status = RunStatus.finished
    assert retire_host_on_long_retry_after(attempt) is False
    assert not host.breaker_tripped
    assert attempt.walk.standing is None


def test_when_set_RetireHostOnLongRetryAfter_LadderWalk_standing(tmp_path: Path) -> None:
    """Verify rule RetireHostOnLongRetryAfter sets LadderWalk.standing when transitioning status to settled (entering when set {settled}).

    Walking, the walk has no standing attempt; the rule settles it and sets standing to
    the retiring attempt, also when the breaker had already tripped.
    """  # noqa: E501  The obligation's description, quoted.
    run, frontier, host = opened_host(tmp_path)
    attempt = walking_attempt(run, frontier, long_retry_after(SEED))
    before = attempt.walk.standing
    assert retire_host_on_long_retry_after(attempt)
    assert before is None
    assert attempt.walk.status is WalkStatus.settled
    assert attempt.walk.standing is attempt
    again = walking_attempt(run, frontier, long_retry_after(SEED))
    assert host.breaker_tripped
    assert retire_host_on_long_retry_after(again) is True
    assert again.walk.standing is again


# --- BreakerTrips ---------------------------------------------------------------------


def test_rule_success_BreakerTrips(tmp_path: Path) -> None:
    """Verify rule BreakerTrips succeeds when all preconditions are met.

    A watching breaker that should act, breaker enabled, in a standard run: it trips,
    every pending row of its host becomes skipped_blocked, a pending row of another host
    stays pending, and BreakerTripped names the host. In a run, each swept row raises a
    UrlSkippedBlocked and none of them is requested.
    """
    run, frontier, host = opened_host(tmp_path / "unit")
    mine = enqueue(run, frontier, page_url(1), depth=1, via=DiscoverySource.link, priority=0)
    other = enqueue(
        run, frontier, page_url(1, OTHER_SITE), depth=1, via=DiscoverySource.link, priority=0
    )
    breaker = the_breaker(host)
    over_threshold(breaker)
    assert breaker_trips(breaker, frontier) == BreakerTripped(host=host)
    assert breaker.status is BreakerStatus.tripped
    assert mine.status is FrontierStatus.skipped_blocked
    assert other.status is FrontierStatus.pending
    total = COUNT + CRAWL.concurrency_per_host + 2
    result, fetcher = breached(tmp_path / "run", total)
    swept = [page_url(number) for number in range(COUNT + 1, total + 1)]
    assert sorted(skipped_urls(result)) == swept
    for url in swept:
        assert url not in fetcher.requests


def test_rule_failure_BreakerTrips_1(tmp_path: Path) -> None:
    """Verify rule BreakerTrips is rejected when requires clause fails.

    requires: breaker.status = watching: a tripped breaker over the threshold sweeps
    nothing and raises nothing.
    """
    run, frontier, host = opened_host(tmp_path)
    mine = enqueue(run, frontier, page_url(1), depth=1, via=DiscoverySource.link, priority=0)
    breaker = the_breaker(host)
    over_threshold(breaker)
    breaker.status = BreakerStatus.tripped
    assert breaker_trips(breaker, frontier) is None
    assert mine.status is FrontierStatus.pending


def test_rule_failure_BreakerTrips_2(tmp_path: Path) -> None:
    """Verify rule BreakerTrips is rejected when requires clause fails.

    requires: breaker.host.run.policy.breaker_enabled: with the breaker disabled the
    host does not trip; nor does a run under that policy, which fetches every seed.
    """
    disabled = dataclasses.replace(standard_policy(), breaker_enabled=False)
    run, frontier, host = opened_host(tmp_path / "unit")
    run.policy = disabled
    mine = enqueue(run, frontier, page_url(1), depth=1, via=DiscoverySource.link, priority=0)
    breaker = the_breaker(host)
    over_threshold(breaker)
    assert breaker_trips(breaker, frontier) is None
    assert breaker.status is BreakerStatus.watching
    assert mine.status is FrontierStatus.pending
    total = COUNT + 2
    seeds = tuple(page_url(number) for number in range(1, total + 1))
    fetcher = FakeFetcher(breach_responses(total))
    result = crawl_seeds(tmp_path / "run", seeds, fetcher, policy=disabled)
    assert not result.run.has_tripped_host
    assert all(url in fetcher.requests for url in seeds)


def test_rule_failure_BreakerTrips_3(tmp_path: Path) -> None:
    """Verify rule BreakerTrips is rejected when requires clause fails.

    requires: breaker.tier = breaker.highest_tier or not
    breaker.host.run.policy.protection_escalation: below the highest tier with protection
    escalation on (owner testing's policy, on a constructed run), BreakerTrips does not
    fire; through a run, the breaker that should act there stops at BreakerEscalates,
    T20's rule, rather than tripping.
    """
    escalating = dataclasses.replace(standard_policy(), protection_escalation=True)
    run, frontier, host = opened_host(tmp_path / "unit")
    run.policy = escalating
    breaker = the_breaker(host)
    breaker.highest_tier = Tier.browser
    over_threshold(breaker)
    assert breaker_trips(breaker, frontier) is None
    assert breaker.status is BreakerStatus.watching
    total = COUNT + 1
    seeds = tuple(page_url(number) for number in range(1, total + 1))
    responses = {
        url: (
            SiteResponse(status=0, source_url=url, markup="", size=0, error="connection refused")
            if number <= BLOCKING
            else html_response(url, prose_page(number))
        )
        for number, url in enumerate(seeds, 1)
    }
    mirror = seeded_mirror(tmp_path / "run", seeds)
    escalating_run = request(mirror, render_mode=RenderMode.auto, policy=escalating)
    with pytest.raises(NotInThisSlice) as stopped:
        run_crawl(escalating_run, None, FakeFetcher(responses), FixedClock())
    assert stopped.value.rule == "BreakerEscalates"


# --- classify_block, the main text and FeedBreaker (guarantees) ------------------------


@pytest.mark.parametrize(
    ("status", "signature"),
    [
        pytest.param(UNAUTHORIZED, "401 Unauthorized", id="401"),
        pytest.param(FORBIDDEN, "403 Forbidden", id="403"),
        pytest.param(TOO_MANY, "429 Too Many Requests", id="429"),
    ],
)
def test_classify_block_a_status_block_is_hard(status: int, signature: str) -> None:
    """A 401, 403 or 429 is hard, its signature the status text, whatever the body."""
    for body in ("", PAGE, prose_page(1, extra=LOGIN_FORM)):
        response = html_response(SEED, body, status=status)
        verdict = classify_block(response, None)
        assert verdict == BlockVerdict(kind=BlockKind.hard, signature=signature)
        assert verdict.signature == status_text(response)
        assert classify_block(response, 1000.0) == verdict


def test_classify_block_a_429_is_hard_at_every_try() -> None:
    """classify_block cannot see the try: a 429 is hard with or without Retry-After."""
    for retry_after in (None, timedelta(seconds=1), PAST_CAP):
        response = dataclasses.replace(
            html_response(SEED, "", status=TOO_MANY), retry_after=retry_after
        )
        assert classify_block(response, None).kind is BlockKind.hard


def test_classify_block_a_login_wall_is_soft() -> None:
    """A password input on an ok HTML answer is a login wall: soft, signed "login wall"."""
    verdict = classify_block(html_response(SEED, prose_page(1, extra=LOGIN_FORM)), None)
    assert verdict == BlockVerdict(kind=BlockKind.soft, signature="login wall")
    assert not verdict.counts_against_host
    not_html = text_response(SEED, LOGIN_FORM)
    assert classify_block(not_html, None).kind is BlockKind.none


def test_classify_block_thin_text_is_soft_only_with_a_baseline() -> None:
    """A main text under soft_block_ratio of the host's median is soft, never without one.

    The signature names both lengths; at the ratio exactly, or on an answer that is not
    ok, the verdict is none.
    """
    median = 1000.0
    under = int(median * CRAWL.soft_block_ratio) - 1
    thin = dataclasses.replace(html_response(SEED, thin_page()), main_text=under)
    verdict = classify_block(thin, median)
    assert verdict.kind is BlockKind.soft
    assert str(under) in verdict.signature
    assert str(int(median)) in verdict.signature
    assert classify_block(thin, None).kind is BlockKind.none
    at_ratio = dataclasses.replace(thin, main_text=int(median * CRAWL.soft_block_ratio))
    assert classify_block(at_ratio, median).kind is BlockKind.none
    missing = dataclasses.replace(thin, status=NOT_FOUND)
    assert classify_block(missing, median).kind is BlockKind.none


def test_classify_block_order_when_two_checks_hold() -> None:
    """The guidance's order: a status block before a soft check, thin text before a login wall."""
    walled = html_response(SEED, prose_page(1, extra=LOGIN_FORM), status=FORBIDDEN)
    assert classify_block(walled, None) == BlockVerdict(
        kind=BlockKind.hard, signature="403 Forbidden"
    )
    median = 1000.0
    thin_wall = dataclasses.replace(
        html_response(SEED, prose_page(1, extra=LOGIN_FORM)), main_text=1
    )
    verdict = classify_block(thin_wall, median)
    assert verdict.kind is BlockKind.soft
    assert verdict.signature != "login wall"


def test_classify_block_recognises_no_challenge() -> None:
    """No challenge recogniser is specified (AttemptTier guidance 1603 to 1605): none is given."""
    for markup in (
        "<html><body><p>Checking your browser before accessing the site.</p></body></html>",
        "<html><body><p>Access denied. Reference #18.2f3e</p></body></html>",
    ):
        for status in (200, FORBIDDEN):
            kind = classify_block(html_response(SEED, markup, status=status), None).kind
            assert kind is not BlockKind.challenge


def collapsed(text: str) -> int:
    """The length of `text` with its whitespace collapsed, as rendered prose reads."""
    return len(" ".join(text.split()))


def test_main_text_length_is_the_selections_visible_text() -> None:
    """The length of the profile's content selection's text, chrome outside it not counted."""
    markup = (
        "<html><body><header>Site header words</header><nav>Many navigation words</nav>"
        "<main><h1>Alpha</h1>\n<p>beta   gamma</p></main><footer>Footer</footer></body></html>"
    )
    main = BeautifulSoup(markup, "lxml").find("main")
    assert main is not None
    assert main_text_length(markup, profiles.GENERIC) == collapsed(main.get_text(" "))


def test_main_text_length_falls_back_to_the_whole_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no selection, the whole body's text, and never the fallback extractor."""

    def no_fallback(html: str, url: str) -> None:
        """Fail the test if the fallback extractor runs."""
        pytest.fail(f"the fallback extractor ran on {url} ({len(html)} bytes)")

    monkeypatch.setattr(fidelity, "_fallback", no_fallback)
    markup = "<html><body><div><p>Alpha beta</p>\n<p>gamma</p></div></body></html>"
    body = BeautifulSoup(markup, "lxml").body
    assert body is not None
    assert main_text_length(markup, profiles.GENERIC) == collapsed(body.get_text(" "))


def test_an_attempt_carries_the_main_text_of_an_ok_html_answer(tmp_path: Path) -> None:
    """AttemptTier sets main_text on an ok HTML answer; a non-HTML or failed answer keeps 0."""
    seeds = (page_url(1), page_url(2), page_url(3))
    fetcher = FakeFetcher(
        {
            seeds[0]: html_response(seeds[0], prose_page(1)),
            seeds[1]: text_response(seeds[1], "Plain text, not HTML."),
            seeds[2]: html_response(seeds[2], "", status=NOT_FOUND),
        }
    )
    result = crawl_seeds(tmp_path, seeds, fetcher)
    assert the_host(result.run).recent_text_lengths == [
        main_text_length(prose_page(1), profiles.GENERIC)
    ]


def test_feed_breaker_keeps_host_text_history_lengths(tmp_path: Path) -> None:
    """FeedBreaker appends each unblocked page's main text, keeping the last host_text_history."""
    run, frontier, host = opened_host(tmp_path)
    lengths = list(range(1, CRAWL.host_text_history + 3))
    for length in lengths:
        walk = settled_on(
            run,
            frontier,
            dataclasses.replace(html_response(SEED, PAGE), main_text=length),
            identity=f"{SITE}/guide/t{length}.html",
        )
        assert feed_breaker(walk)
    assert host.recent_text_lengths == lengths[-CRAWL.host_text_history :]


# --- DisposeFetch and conversion (guarantees) -----------------------------------------


def test_dispose_fetch_absent_before_a_block_and_a_challenge_blocked(tmp_path: Path) -> None:
    """DisposeFetch's branch order (1922): absent before a hard or challenge verdict.

    A 404 carrying a hard verdict is absent; a challenge verdict (constructed: none is
    recognised yet) on an ok answer is blocked with its signature and counts the host's
    blocked and fetched once each.
    """
    run, frontier, host = opened_host(tmp_path)
    absent = settled_on(run, frontier, html_response(SEED, "", status=NOT_FOUND))
    with_verdict(absent, BlockKind.hard, "403 Forbidden")
    assert not isinstance(dispose_fetch(absent), UrlBlocked)
    assert absent.entry.status is FrontierStatus.absent
    challenged_url = page_url(1)
    challenged = settled_on(
        run, frontier, html_response(challenged_url, PAGE), identity=challenged_url
    )
    with_verdict(challenged, BlockKind.challenge, "challenge page")
    assert dispose_fetch(challenged) == UrlBlocked(
        run=run, url=challenged_url, status=200, signature="challenge page", tier=Tier.http
    )
    assert challenged.entry.status is FrontierStatus.blocked
    assert (host.blocked, host.fetched) == (1, 1)


def test_a_soft_verdict_is_converted_with_soft_block_suspected(tmp_path: Path) -> None:
    """A thin page after the host's baseline, and a login wall, are converted, flagged soft.

    Both pages are written with soft_block_suspected and low confidence; the prose pages
    carry no such flag; nothing is blocked and the host does not trip.
    """
    prose = tuple(page_url(number) for number in range(1, CRAWL.median_min_pages + 1))
    thin_url = f"{SITE}/guide/thin.html"
    login_url = f"{SITE}/guide/login.html"
    responses = {url: html_response(url, prose_page(n)) for n, url in enumerate(prose, 1)}
    responses[thin_url] = html_response(thin_url, thin_page())
    responses[login_url] = html_response(login_url, prose_page(9, extra=LOGIN_FORM))
    mirror = seeded_mirror(tmp_path, (*prose, thin_url, login_url))
    result = run_crawl(request(mirror), None, FakeFetcher(responses), FixedClock())
    for url in (thin_url, login_url):
        page = mirror.page(url)
        assert page is not None, url
        assert QualityFlag.soft_block_suspected in page.flags
        assert page.low_confidence
    for url in prose:
        page = mirror.page(url)
        assert page is not None
        assert QualityFlag.soft_block_suspected not in page.flags
    assert result.blocked == ()
    assert not result.run.has_tripped_host


# --- Retirement paths (guarantees) ----------------------------------------------------


def test_a_robots_retry_after_past_the_cap_retires_the_host(tmp_path: Path) -> None:
    """robots.txt answering 429 past the cap: asked once, robots_refused, the host retired.

    Nothing more is requested of the host: no sitemap, llms.txt or page.
    """
    fetcher = FakeFetcher({ROBOTS: long_retry_after(ROBOTS), SEED: html_response(SEED, PAGE)})
    result = crawl_seeds(tmp_path, (SEED,), fetcher)
    assert fetcher.requests == [ROBOTS]
    assert [(event.url, event.problem) for event in result.discovery_failed] == [
        (ROBOTS, DiscoveryProblem.robots_refused)
    ]
    assert result.run.has_tripped_host
    assert skipped_urls(result) == [SEED]


def test_a_crawl_delay_on_a_second_origin_retires_the_whole_host(tmp_path: Path) -> None:
    """Any origin of the host retires it: the second origin's long Crawl-delay stops both.

    The second origin's row, whose own readiness retired the host, is never requested
    and is skipped_blocked (SkipTrippedHostAfterReady, crawl.allium 1552 to 1566).
    """
    fetcher = FakeFetcher(
        {
            ROBOTS: text_response(ROBOTS, "User-agent: *\n"),
            SEED: html_response(SEED, PAGE),
            PORTED_ROBOTS: text_response(
                PORTED_ROBOTS, f"User-agent: *\nCrawl-delay: {CAP.total_seconds() + 1}\n"
            ),
            PORTED_PAGE: html_response(PORTED_PAGE, prose_page(2)),
        }
    )
    mirror = seeded_mirror(tmp_path, (SEED, PORTED_PAGE))
    result = run_crawl(request(mirror), None, fetcher, FixedClock())
    assert result.run.has_tripped_host
    assert PORTED_PAGE not in fetcher.requests
    assert fetcher.requests[-1] == PORTED_ROBOTS
    assert status_of(result.frontier, PORTED_PAGE) is FrontierStatus.skipped_blocked
    assert skipped_urls(result) == [PORTED_PAGE]


def test_a_page_503_past_the_cap_fails_and_retires_the_host(tmp_path: Path) -> None:
    """A 503 whose Retry-After is past the cap retires the host, and the page fails."""
    seeds = (page_url(1), page_url(2))
    fetcher = FakeFetcher(
        {
            seeds[0]: long_retry_after(seeds[0], SERVICE_UNAVAILABLE),
            seeds[1]: html_response(seeds[1], prose_page(2)),
        }
    )
    result = crawl_seeds(tmp_path, seeds, fetcher)
    assert fetcher.requests.count(seeds[0]) == 1
    assert [(event.url, event.error) for event in result.failed] == [
        (seeds[0], "503 Service Unavailable")
    ]
    assert result.blocked == ()
    assert result.run.has_tripped_host
    assert skipped_urls(result) == [seeds[1]]


def test_a_speculative_sitemap_past_the_cap_only_pauses_the_host(tmp_path: Path) -> None:
    """A well-known sitemap probe answering 429 past the cap pauses the host; no retirement."""
    sitemap = f"{SITE}/sitemap.xml"
    fetcher = FakeFetcher({sitemap: long_retry_after(sitemap), SEED: html_response(SEED, PAGE)})
    result = crawl_seeds(tmp_path, (SEED,), fetcher)
    assert not result.run.has_tripped_host
    assert SEED in fetcher.requests


def test_a_declared_sitemap_past_the_cap_leaves_the_others_unread_and_unreported(
    tmp_path: Path,
) -> None:
    """The first declared sitemap past the cap retires the host; the second is never asked.

    The one asked stands as sitemap_unavailable; the one left unread has no row of its
    own (FetchRobots guidance 862 to 864), and nothing else is requested of the host.
    """
    robots = text_response(
        ROBOTS, f"User-agent: *\nSitemap: {SITEMAP_ONE}\nSitemap: {SITEMAP_TWO}\n"
    )
    fetcher = FakeFetcher(
        {
            ROBOTS: robots,
            SITEMAP_ONE: long_retry_after(SITEMAP_ONE),
            SITEMAP_TWO: xml_response(SITEMAP_TWO, "<urlset/>"),
            SEED: html_response(SEED, PAGE),
        }
    )
    result = crawl_seeds(tmp_path, (SEED,), fetcher)
    assert fetcher.requests == [ROBOTS, SITEMAP_ONE]
    sitemap_rows = [
        (event.url, event.problem) for event in result.discovery_failed if event.url != ROBOTS
    ]
    assert sitemap_rows == [(SITEMAP_ONE, DiscoveryProblem.sitemap_unavailable)]
    assert result.run.has_tripped_host


# --- BreakerStopsTheRun and the other guarantees --------------------------------------


def test_BreakerStopsTheRun_no_request_after_the_trip(tmp_path: Path) -> None:
    """After the trip no request of any kind reaches the host; every block and skip is returned.

    The COUNTth walk trips the breaker: the rows after it are never requested, each is
    skipped, and each blocked seed is returned with its status, signature and tier.
    """
    total = COUNT + CRAWL.concurrency_per_host + 2
    result, fetcher = breached(tmp_path, total)
    trip_at = fetcher.requests.index(page_url(COUNT))
    assert all(not url.startswith(SITE) for url in fetcher.requests[trip_at + 1 :])
    assert [
        (event.url, event.status, event.signature, event.tier) for event in result.blocked
    ] == [
        (page_url(number), FORBIDDEN, "403 Forbidden", Tier.http)
        for number in range(1, BLOCKING + 1)
    ]
    assert sorted(skipped_urls(result)) == [page_url(n) for n in range(COUNT + 1, total + 1)]
    assert len(result.tripped) == 1


def test_BlockedWithinFetched_after_a_run(tmp_path: Path) -> None:
    """Host.blocked <= Host.fetched: each block counts once in both."""
    result, _ = breached(tmp_path)
    host = the_host(result.run)
    assert host.blocked == BLOCKING
    assert host.blocked <= host.fetched
    assert host.fetched == COUNT


def test_BrowserRendersContentNeverAnswersBlocks(tmp_path: Path) -> None:
    """Under render_mode = auto a standard run's blocked attempt never climbs to the browser."""
    fetcher = FakeFetcher({SEED: blocked_answer(SEED, FORBIDDEN)})
    result = crawl_seeds(tmp_path, (SEED,), fetcher, render_mode=RenderMode.auto)
    (blocked,) = result.blocked
    assert blocked.tier is Tier.http
    assert status_of(result.frontier, SEED) is FrontierStatus.blocked


def test_a_targeted_trip_sweeps_only_the_targets(tmp_path: Path) -> None:
    """In a targeted run a trip skips the remaining targets; another pending row stays pending.

    The row that is not a target is absent from the skipped events and stays pending in
    the saved frontier (BreakerTrips 1902 to 1906).
    """
    mirror = new_mirror(tmp_path)
    run_crawl(request(mirror), None, FakeFetcher({SEED: html_response(SEED, PAGE)}), FixedClock())
    frontier = load_frontier(mirror)
    assert frontier is not None
    first = run_module.start_run(request(mirror), FixedClock())
    assert first is not None
    bystander = f"{SITE}/guide/bystander.html"
    enqueue(first, frontier, bystander, depth=1, via=DiscoverySource.link, priority=0)
    total = COUNT + 2
    targets = tuple(page_url(number) for number in range(1, total + 1))
    responses = breach_responses(total)
    responses[bystander] = html_response(bystander, prose_page(99))
    targeted = dataclasses.replace(update_request(mirror), targets=frozenset(targets))
    fetcher = FakeFetcher(responses)
    result = run_crawl(targeted, frontier, fetcher, FixedClock())
    assert sorted(skipped_urls(result)) == list(targets[COUNT:])
    assert bystander not in fetcher.requests
    saved = load_frontier(mirror)
    assert saved is not None
    assert status_of(saved, bystander) is FrontierStatus.pending


def test_a_tripped_host_never_stops_a_healthy_host(tmp_path: Path) -> None:
    """Host A trips; every row of host B is still fetched and written; tallies stay apart."""
    total = COUNT + 2
    a_seeds = tuple(page_url(number) for number in range(1, total + 1))
    b_seeds = tuple(page_url(number, OTHER_SITE) for number in range(1, 4))
    responses = breach_responses(total)
    for number, url in enumerate(b_seeds, 1):
        responses[url] = html_response(url, prose_page(number))
    mirror = seeded_mirror(
        tmp_path, (*a_seeds, *b_seeds), allowed_hosts=frozenset({HOST, OTHER_HOST})
    )
    result = run_crawl(request(mirror), None, FakeFetcher(responses), FixedClock())
    for url in b_seeds:
        assert mirror.page(url) is not None, url
    assert sorted(skipped_urls(result)) == list(a_seeds[COUNT:])
    host_a, host_b = the_host(result.run), the_host(result.run, OTHER_HOST)
    assert (host_a.breaker_tripped, host_b.breaker_tripped) == (True, False)
    assert (host_a.blocked, host_b.blocked) == (BLOCKING, 0)
    assert host_b.block_rate == 0
    assert result.run.tripped_hosts == [host_a]


def test_config_moves_the_trip_point_and_the_soft_verdict(
    tmp_path: Path, altered_config: model.CrawlConfig
) -> None:
    """Non-default breaker_min_outcomes, block_rate_threshold, soft ratio and baseline size.

    The breaker trips after min(breaker_window, breaker_min_outcomes) walks of the
    altered values, where the defaults would not yet; a page under the altered ratio of a
    baseline of the altered size is soft, where the defaults give none.
    """
    count = min(altered_config.breaker_window, altered_config.breaker_min_outcomes)
    blocking = int(count * altered_config.block_rate_threshold) + 1
    assert count < COUNT
    total = count + 2
    seeds = tuple(page_url(number) for number in range(1, total + 1))
    responses = {
        url: (
            blocked_answer(url, FORBIDDEN)
            if number <= blocking
            else html_response(url, prose_page(number))
        )
        for number, url in enumerate(seeds, 1)
    }
    result = crawl_seeds(tmp_path / "trip", seeds, FakeFetcher(responses))
    assert sorted(skipped_urls(result)) == list(seeds[count:])
    prose = tuple(page_url(number) for number in range(1, altered_config.median_min_pages + 1))
    shortish_url = f"{SITE}/guide/shortish.html"
    full = main_text_length(prose_page(1), profiles.GENERIC)
    words = "word " * int(full * (altered_config.soft_block_ratio + CRAWL.soft_block_ratio) / 10)
    shortish = (
        "<!doctype html><html><head><title>Short</title></head>"
        f"<body><main><p>{words}</p></main></body></html>"
    )
    under = main_text_length(shortish, profiles.GENERIC)
    assert CRAWL.soft_block_ratio * full < under < altered_config.soft_block_ratio * full
    soft_responses = {url: html_response(url, prose_page(n)) for n, url in enumerate(prose, 1)}
    soft_responses[shortish_url] = html_response(shortish_url, shortish)
    mirror = seeded_mirror(tmp_path / "soft", (*prose, shortish_url))
    run_crawl(request(mirror), None, FakeFetcher(soft_responses), FixedClock())
    page = mirror.page(shortish_url)
    assert page is not None
    assert QualityFlag.soft_block_suspected in page.flags


def test_the_retry_after_cap_of_the_policy_moves_the_retirement(tmp_path: Path) -> None:
    """A Retry-After past a lower retry_after_cap retires; under the default it does not."""
    shorter = dataclasses.replace(standard_policy(), retry_after_cap=timedelta(seconds=10))
    wait = shorter.retry_after_cap + timedelta(seconds=1)
    assert wait < CAP
    seeds = (page_url(1), page_url(2))

    def answers() -> FakeFetcher:
        return FakeFetcher(
            {
                seeds[0]: dataclasses.replace(
                    html_response(seeds[0], "", status=TOO_MANY), retry_after=wait
                ),
                seeds[1]: html_response(seeds[1], prose_page(2)),
            }
        )

    short = answers()
    retired = crawl_seeds(tmp_path / "short", seeds, short, policy=shorter)
    assert retired.run.has_tripped_host
    assert short.requests.count(seeds[0]) == 1
    default = answers()
    kept = crawl_seeds(tmp_path / "default", seeds, default)
    assert not kept.run.has_tripped_host
    assert default.requests.count(seeds[0]) == CRAWL.http_attempts
    assert [event.url for event in kept.blocked] == [seeds[0]]


def test_a_block_keeps_a_mirrored_page(tmp_path: Path) -> None:
    """A 403 on a written page leaves its file, manifest row, validators and indexes alone.

    Every file outside .rovo/ but crawl-report.json (the page file, index.md,
    index.jsonl, links.jsonl, llms.txt, rovo.toml) is byte-identical after the blocked
    sync, as it is after an unchanged one; the URL is listed in blocked_urls; the next
    sync, answered 200, refreshes the page.
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    first = FakeFetcher(
        {SEED: dataclasses.replace(html_response(SEED, PAGE), etag='"v1"', last_modified="x")}
    )
    assert _commands.sync(out_dir, fetcher=first, clock=FixedClock()) is ExitCode.ok
    before = load_mirror(out_dir).page(SEED)
    assert before is not None
    kept = {
        path: path.read_bytes()
        for path in sorted(out_dir.rglob("*"))
        if path.is_file() and ".rovo" not in path.parts and path.name != "crawl-report.json"
    }
    blocked = FakeFetcher({SEED: blocked_answer(SEED, FORBIDDEN)})
    assert _commands.sync(out_dir, fetcher=blocked, clock=FixedClock()) is ExitCode.partial
    after = load_mirror(out_dir).page(SEED)
    assert after is not None
    assert (after.path, after.etag, after.last_modified, after.raw_digest) == (
        before.path,
        before.etag,
        before.last_modified,
        before.raw_digest,
    )
    for path, content in kept.items():
        assert path.read_bytes() == content, path
    report = (out_dir / "crawl-report.json").read_text(encoding="utf-8")
    assert '"blocked_urls"' in report
    assert SEED in report.split('"blocked_urls"', 1)[1].split("]", 1)[0]
    refreshed = FakeFetcher({SEED: html_response(SEED, prose_page(7))})
    assert _commands.sync(out_dir, fetcher=refreshed, clock=FixedClock()) is ExitCode.ok
    page = load_mirror(out_dir).page(SEED)
    assert page is not None
    assert "Page 7" in (out_dir / page.path).read_text(encoding="utf-8")


def test_soft_fixture_site_has_a_baseline_before_its_thin_page() -> None:
    """The soft fixture site links at least median_min_pages prose pages before thin.html."""
    start = (SOFT_SITE / "guide" / "start.html").read_text(encoding="utf-8")
    hrefs = [anchor["href"] for anchor in BeautifulSoup(start, "lxml").find_all("a")]
    assert hrefs.index("thin.html") >= CRAWL.median_min_pages
    assert hrefs.index("login.html") > hrefs.index("thin.html")


# --- The T18-2 answers (spec 7d01367) -------------------------------------------------
# A row whose own readiness retires its host settles skipped_blocked
# (SkipTrippedHostAfterReady); a walk whose own host trips makes no further request and,
# needing one, stops with its row skipped_blocked (StopWalkOnTrippedHost), while an answer
# it already holds settles as usual (SettleWalk); a page event means a fetch settled.


def ported_long_delay() -> SiteResponse:
    """The ported origin's robots.txt, its Crawl-delay one second past the standard cap."""
    return text_response(PORTED_ROBOTS, f"User-agent: *\nCrawl-delay: {CAP.total_seconds() + 1}\n")


def walk_of(
    run: Run,
    frontier: Frontier,
    url: str,
    response: SiteResponse,
    *,
    try_: int = 1,
) -> FetchAttempt:
    """A walking http walk of the url's in-progress row; its one attempt answers `response`."""
    walk = LadderWalk(
        entry=in_progress(run, frontier, url),
        host=the_host(run),
        tiers=(Tier.http,),
        conditional=False,
        escalated=False,
        challenge_offered=False,
        status=WalkStatus.walking,
    )
    return attempt_on(walk, response, try_=try_)


def refused_hop(url: str) -> SiteResponse:
    """A redirect from `url` whose hop fetch_or_render refused: its host had tripped."""
    return dataclasses.replace(redirect_response(url, PORTED_PAGE), error=pace.RETIRED_HOP)


def trip(host: Host) -> None:
    """The host's breaker, tripped."""
    the_breaker(host).status = BreakerStatus.tripped


def test_derived_FetchAttempt_hop_refused(tmp_path: Path) -> None:
    """Verify derived value FetchAttempt.hop_refused computes correctly.

    hop_refused: response.error = "redirect to a retired host" (crawl.allium 517). A hop
    robots.txt disallows, another error, a 500 and an ok page are not refused hops.
    """
    run, frontier, _ = opened_host(tmp_path)
    attempt = walking_attempt(run, frontier, refused_hop(SEED))
    assert attempt.hop_refused is True
    walk = attempt.walk
    disallowed = dataclasses.replace(refused_hop(SEED), error=pace.DISALLOWED_HOP)
    others = (
        disallowed,
        dataclasses.replace(html_response(SEED, ""), status=0, error="connection reset"),
        html_response(SEED, "", status=500),
        html_response(SEED, PAGE),
    )
    for response in others:
        assert attempt_on(walk, response).hop_refused is False, response


# --- SkipTrippedHostAfterReady --------------------------------------------------------


def test_rule_success_SkipTrippedHostAfterReady(tmp_path: Path) -> None:
    """Verify rule SkipTrippedHostAfterReady succeeds when all preconditions are met.

    OpenHostForEntry reads robots.txt whose Crawl-delay is past the cap: the host is
    retired, and the ready row becomes skipped_blocked with its UrlSkippedBlocked. In a
    run, a row whose new origin's robots.txt (ReadRobotsForNewOrigin) retires the host is
    never requested and is skipped, so the batch goes idle and the next batch still
    fetches another host's page (crawl.allium 1552 to 1566).
    """
    run, _, entry = crawling_without_hosts(tmp_path / "unit")
    assert open_host_for_entry(run, entry, FakeFetcher({ROBOTS: long_delay_robots()}))
    assert the_host(run).breaker_tripped
    assert skip_tripped_host_after_ready(run, entry) == UrlSkippedBlocked(run=run, url=SEED)
    assert entry.status is FrontierStatus.skipped_blocked
    other_first, other_next = page_url(1, OTHER_SITE), page_url(2, OTHER_SITE)
    fetcher = FakeFetcher(
        {
            ROBOTS: text_response(ROBOTS, "User-agent: *\n"),
            SEED: html_response(SEED, prose_page(1)),
            PORTED_ROBOTS: ported_long_delay(),
            PORTED_PAGE: html_response(PORTED_PAGE, prose_page(2)),
            other_first: html_response(
                other_first, prose_page(3, extra='<p><a href="p02.html">Next</a></p>')
            ),
            other_next: html_response(other_next, prose_page(4)),
        }
    )
    mirror = seeded_mirror(
        tmp_path / "run",
        (SEED, PORTED_PAGE, other_first),
        allowed_hosts=frozenset({HOST, OTHER_HOST}),
    )
    result = run_crawl(request(mirror), None, fetcher, FixedClock())
    assert PORTED_PAGE not in fetcher.requests
    assert status_of(result.frontier, PORTED_PAGE) is FrontierStatus.skipped_blocked
    assert PORTED_PAGE in skipped_urls(result)
    assert other_next in fetcher.requests
    assert mirror.page(other_next) is not None


def test_rule_failure_SkipTrippedHostAfterReady_1(tmp_path: Path) -> None:
    """Verify rule SkipTrippedHostAfterReady is rejected when requires clause fails.

    requires: run.status = running and entry.status = in_progress: a row no longer in
    progress, or a run no longer running, is left as it is.
    """
    run, frontier, host = opened_host(tmp_path)
    entry = in_progress(run, frontier, SEED)
    trip(host)
    entry.status = FrontierStatus.pending
    assert skip_tripped_host_after_ready(run, entry) is None
    assert entry.status is FrontierStatus.pending
    entry.status = FrontierStatus.in_progress
    run.status = RunStatus.finished
    assert skip_tripped_host_after_ready(run, entry) is None
    assert entry.status is FrontierStatus.in_progress


def test_rule_failure_SkipTrippedHostAfterReady_2(tmp_path: Path) -> None:
    """Verify rule SkipTrippedHostAfterReady is rejected when requires clause fails.

    requires: exists host and host.breaker_tripped: a row of a watching host, and a row
    of a host the run has not opened, are left in progress.
    """
    run, frontier, _ = opened_host(tmp_path)
    entry = in_progress(run, frontier, SEED)
    assert skip_tripped_host_after_ready(run, entry) is None
    assert entry.status is FrontierStatus.in_progress
    unopened = in_progress(run, frontier, page_url(1, OTHER_SITE))
    assert skip_tripped_host_after_ready(run, unopened) is None
    assert unopened.status is FrontierStatus.in_progress


def test_rule_failure_SkipRobotsDisallowedOnNewHost_3(tmp_path: Path) -> None:
    """Verify rule SkipRobotsDisallowedOnNewHost is rejected when requires clause fails.

    requires: exists host and not host.breaker_tripped (crawl.allium 1547 to 1548): the
    robots.txt OpenHostForEntry reads both disallows the row and retires the host, so the
    row is not skipped_robots; SkipTrippedHostAfterReady settles it skipped_blocked.
    """
    robots = f"{DISALLOW_GUIDE}Crawl-delay: {CAP.total_seconds() + 1}\n"
    run, frontier, entry = crawling_without_hosts(tmp_path)
    assert open_host_for_entry(run, entry, FakeFetcher({ROBOTS: text_response(ROBOTS, robots)}))
    assert the_host(run).breaker_tripped
    assert skip_robots_disallowed_on_new_host(run, entry) is False
    assert status_of(frontier, SEED) is FrontierStatus.in_progress
    assert skip_tripped_host_after_ready(run, entry) == UrlSkippedBlocked(run=run, url=SEED)
    assert status_of(frontier, SEED) is FrontierStatus.skipped_blocked


# --- StopWalkOnTrippedHost ------------------------------------------------------------


def test_rule_success_StopWalkOnTrippedHost(tmp_path: Path) -> None:
    """Verify rule StopWalkOnTrippedHost succeeds when all preconditions are met.

    In a run, the seed redirects onto another origin of its own host whose robots.txt
    has a Crawl-delay past the cap: reading it retires the host, the hop is refused
    (hop_refused), and the walk makes no further request: the seed is asked once, not
    http_attempts times, its row skipped_blocked and announced, not failed; a page event
    names it (a fetch settled), and another host's seed is still fetched. On unit inputs
    each disjunct of the last requires stops a walking walk on a tripped host: a
    retryable answer, a refused hop on the last try, and an answer that would escalate
    (a render reason on a walk whose tiers go on to the browser; a refused hop carries
    an error, never a render reason, so this disjunct is reached on constructed inputs
    only in a standard run). Each settles the walk with the attempt standing, its row
    skipped_blocked, and returns its UrlSkippedBlocked (crawl.allium 1855 to 1884).
    """
    assert CRAWL.http_attempts > 1
    other_seed = page_url(1, OTHER_SITE)
    fetcher = FakeFetcher(
        {
            ROBOTS: text_response(ROBOTS, "User-agent: *\n"),
            SEED: redirect_response(SEED, PORTED_PAGE),
            PORTED_ROBOTS: ported_long_delay(),
            PORTED_PAGE: html_response(PORTED_PAGE, prose_page(2)),
            other_seed: html_response(other_seed, prose_page(3)),
        }
    )
    mirror = seeded_mirror(
        tmp_path / "run", (SEED, other_seed), allowed_hosts=frozenset({HOST, OTHER_HOST})
    )
    events: list[ProgressEvent] = []
    result = drive_run(request(mirror), None, fetcher, FixedClock(), progress=events.append)
    assert the_host(result.run).breaker_tripped
    assert fetcher.requests.count(SEED) == 1
    assert PORTED_PAGE not in fetcher.requests
    assert fetcher.requests.count(PORTED_ROBOTS) == 1
    assert status_of(result.frontier, SEED) is FrontierStatus.skipped_blocked
    assert skipped_urls(result) == [SEED]
    assert SEED not in [event.url for event in result.failed]
    assert [event.url for event in events if event.event == "page"].count(SEED) == 1
    assert other_seed in fetcher.requests

    run, frontier, host = opened_host(tmp_path / "unit")
    retryable = walk_of(run, frontier, SEED, html_response(SEED, "", status=500))
    last_hop = walk_of(run, frontier, OTHER, refused_hop(OTHER), try_=CRAWL.http_attempts)
    assert retryable.retryable
    assert last_hop.hop_refused
    assert not last_hop.retryable
    trip(host)
    for attempt in (retryable, last_hop):
        assert stop_walk_on_tripped_host(attempt) == UrlSkippedBlocked(
            run=run, url=attempt.walk.entry.identity
        )
        assert attempt.walk.status is WalkStatus.settled
        assert attempt.walk.standing is attempt
        assert attempt.walk.entry.status is FrontierStatus.skipped_blocked

    run, frontier = crawling(tmp_path / "escalate", FakeFetcher({}))
    escalating = walk_with(
        run, frontier, (Tier.http, Tier.browser), html_response(SEED, NOSCRIPT_PAGE)
    )
    assert escalating.wants_escalation
    trip(the_host(run))
    assert stop_walk_on_tripped_host(escalating) == UrlSkippedBlocked(run=run, url=SEED)
    assert escalating.walk.status is WalkStatus.settled
    assert escalating.walk.standing is escalating
    assert escalating.walk.entry.status is FrontierStatus.skipped_blocked


def test_rule_failure_StopWalkOnTrippedHost_1(tmp_path: Path) -> None:
    """Verify rule StopWalkOnTrippedHost is rejected when requires clause fails.

    requires: walk.status = walking and walk.host.run.status = running and
    walk.host.breaker_tripped: a retryable attempt on a watching host is retried
    (HttpRetry), not stopped.
    """
    run, frontier, _ = opened_host(tmp_path)
    attempt = walking_attempt(run, frontier, html_response(SEED, "", status=500))
    assert attempt.retryable
    assert stop_walk_on_tripped_host(attempt) is None
    assert attempt.walk.status is WalkStatus.walking
    assert attempt.walk.entry.status is FrontierStatus.in_progress


def test_rule_failure_StopWalkOnTrippedHost_2(tmp_path: Path) -> None:
    """Verify rule StopWalkOnTrippedHost is rejected when requires clause fails.

    requires: not attempt.retires_host: an attempt that itself retires the host (a
    Retry-After past the cap) settles as it stands under RetireHostOnLongRetryAfter.
    """
    run, frontier, host = opened_host(tmp_path)
    attempt = walking_attempt(run, frontier, long_retry_after(SEED))
    trip(host)
    assert attempt.retires_host
    assert stop_walk_on_tripped_host(attempt) is None
    assert attempt.walk.status is WalkStatus.walking
    assert attempt.walk.entry.status is FrontierStatus.in_progress
    assert retire_host_on_long_retry_after(attempt) is True
    assert attempt.walk.standing is attempt


def test_rule_failure_StopWalkOnTrippedHost_3(tmp_path: Path) -> None:
    """Verify rule StopWalkOnTrippedHost is rejected when requires clause fails.

    requires: attempt.retryable or attempt.hop_refused or an escalation it would make:
    an answer the walk already holds when its host trips (a good 200, and a 403 on the
    last try) needs no further request, so it is not stopped; it settles as usual
    (SettleWalk) and is disposed of as usual (DisposeFetch): the 200 is PageFetched,
    the 403 blocked.
    """
    run, frontier, host = opened_host(tmp_path)
    good = walk_of(run, frontier, SEED, html_response(SEED, PAGE))
    blocked = walk_of(
        run, frontier, OTHER, blocked_answer(OTHER, FORBIDDEN), try_=CRAWL.http_attempts
    )
    blocked.verdict = BlockVerdict(kind=BlockKind.hard, signature="403 Forbidden")
    trip(host)
    for attempt in (good, blocked):
        assert not attempt.retryable
        assert not attempt.hop_refused
        assert stop_walk_on_tripped_host(attempt) is None
        assert attempt.walk.status is WalkStatus.walking
        assert run_module.settle_walk(attempt)
        assert attempt.walk.standing is attempt
    assert dispose_fetch(good.walk) is True
    assert isinstance(dispose_fetch(blocked.walk), UrlBlocked)
