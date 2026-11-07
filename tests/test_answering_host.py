"""The answering host (T20, spec fc9ad9f): a redirected answer is judged by the host that answered.

crawl.allium at fc9ad9f (the maintainer's answers 10 to 14, ai_tmp/T20/spec-answers):
every per-host control reads the host's request policy (Host.policy); an answer is judged
by the request policy of the host that answered it, FetchAttempt.answering_host_name, the
host of its source_url (for an error, of the URL last requested): its Retry-After pause,
CountRetryAfter, the past-cap retirement (RetireHostOnLongRetryAfter), HttpRetry's pause,
PauseHostOnRenderRetryAfter and wants_escalation fall on and read that host, while the
walk still settles as it stands and its own host keeps tiers_used and its tallies.
FeedAnsweringBreaker feeds the answering host's breaker one outcome for a redirected
answer, beside the walk host's FeedBreaker. robots.txt, sitemap and llms.txt fetches judge
a past-cap answer by the answering host when it is open (`judged`), else the fetching
host; adopted robots rules stay with the requesting origin. An answer that was not
redirected is judged by the walk's own host, as before.

The obligation tests are named after the ids `just plan-spec crawl` emits at fc9ad9f
(rule-success.FeedAnsweringBreaker and rule-failure.FeedAnsweringBreaker.1 to .4), dots
and hyphens as underscores; each rule_failure test makes exactly one requires clause
false. The rest are the redirect guarantees. The walk's host A is docs.example, owned and
relaxed in an owner run; the answering host B is api.example, allowed but unselected, so
under the standard policy. Nothing here sleeps: time is a FixedClock.
"""

import dataclasses
from datetime import timedelta
from pathlib import Path

import pytest

from fakes import (
    START,
    FakeEngine,
    FakeFetcher,
    FixedClock,
    ScriptedFetcher,
    html_response,
    redirect_response,
    xml_response,
)
from rovo._crawl import pace
from rovo._crawl.model import (
    BlockKind,
    BlockVerdict,
    BreakerStatus,
    CrawlPolicy,
    DiscoverySource,
    FetchAttempt,
    Frontier,
    FrontierStatus,
    Host,
    LadderWalk,
    RenderMode,
    RobotsStance,
    Run,
    SiteResponse,
    WalkStatus,
    standard_policy,
)
from rovo._crawl.run import (
    _Render,
    count_retry_after,
    create_frontier,
    drive_run,
    enqueue,
    feed_answering_breaker,
    feed_breaker,
    fetch_sitemap,
    http_retry,
    open_host,
    pause_host_on_render_retry_after,
    read_llms_txt,
    retire_host_on_long_retry_after,
    start_run,
)
from rovo._mirror.model import Tier
from test_crawl import (
    FORBIDDEN,
    HOST,
    OTHER,
    PAGE,
    ROBOTS,
    SEED,
    SERVICE_UNAVAILABLE,
    SITE,
    TOO_MANY,
    answered,
    new_mirror,
    request,
    unreachable,
)
from test_owner_testing import (
    COUNT,
    ESCALATING,
    OTHER_HOST,
    OTHER_SITE,
    OWNED,
    finished_run,
    owner_host,
    owner_request,
    owner_started,
    the_breaker,
)

TWO_HOSTS = frozenset({HOST, OTHER_HOST})
CAP = standard_policy().retry_after_cap
PAST_CAP = CAP + timedelta(seconds=1)
UNDER_CAP = timedelta(seconds=4)
# A's owner policy: Retry-After not honoured, or honoured under a cap longer than B's.
IGNORING = dataclasses.replace(ESCALATING, honor_retry_after=False)
LONG_CAP = dataclasses.replace(ESCALATING, retry_after_cap=PAST_CAP * 2)
MOVED = f"{OTHER_SITE}/guide/moved.html"
MOVED_OTHER = f"{OTHER_SITE}/guide/moved-other.html"
MAPS = f"{SITE}/sitemap.xml"
MOVED_MAPS = f"{OTHER_SITE}/maps/site.xml"
LLMS = f"{SITE}/llms.txt"
MOVED_LLMS = f"{OTHER_SITE}/docs/llms.txt"
MOVED_ROBOTS = f"{OTHER_SITE}/policy/robots.txt"
NONE = BlockVerdict(kind=BlockKind.none, signature="")
HARD = BlockVerdict(kind=BlockKind.hard, signature="403 Forbidden")
TEXT = 120


# --- Helpers ---------------------------------------------------------------------------


def two_hosts(
    out_dir: Path, *, policy: CrawlPolicy = ESCALATING, owned: frozenset[str] = OWNED
) -> tuple[Run, Frontier, Host, Host]:
    """An owner run over A and B, both opened (no robots.txt): A owned, B allowed only."""
    run, frontier = owner_started(out_dir, policy=policy, owned=owned, allowed_hosts=TWO_HOSTS)
    return run, frontier, owner_host(run), owner_host(run, OTHER_HOST, OTHER_SITE)


def standard_two_hosts(out_dir: Path) -> tuple[Run, Frontier, Host, Host]:
    """A standard run over A and B, both opened (no robots.txt)."""
    run = start_run(request(new_mirror(out_dir, allowed_hosts=TWO_HOSTS)), FixedClock())
    assert run is not None
    frontier = create_frontier(run, None)
    assert frontier is not None
    return run, frontier, owner_host(run), owner_host(run, OTHER_HOST, OTHER_SITE)


def walking(run: Run, frontier: Frontier, identity: str = SEED) -> LadderWalk:
    """A walking walk of A's in-progress row `identity`, over http and the browser."""
    entry = enqueue(run, frontier, identity, depth=0, via=DiscoverySource.named, priority=0)
    entry.status = FrontierStatus.in_progress
    host = run.host(HOST)
    assert host is not None
    return LadderWalk(
        entry=entry,
        host=host,
        tiers=(Tier.http, Tier.browser),
        conditional=False,
        escalated=False,
        challenge_offered=False,
        status=WalkStatus.walking,
    )


def redirected(response: SiteResponse) -> SiteResponse:
    """`response` as the final answer of the seed's redirect: SEED left behind."""
    return dataclasses.replace(response, redirect_hops=(SEED,))


def attempt_of(
    walk: LadderWalk,
    response: SiteResponse,
    *,
    tier: Tier = Tier.http,
    try_: int = 1,
    verdict: BlockVerdict = NONE,
) -> FetchAttempt:
    """A FetchAttempt of `walk` answering `response`, appended to the walk."""
    attempt = FetchAttempt(
        walk=walk, tier=tier, try_=try_, response=response, verdict=verdict, render_reason=None
    )
    walk.attempts.append(attempt)
    return attempt


def settled_walk(
    run: Run,
    frontier: Frontier,
    response: SiteResponse,
    *,
    verdict: BlockVerdict = NONE,
    identity: str = SEED,
) -> LadderWalk:
    """A settled walk of A's row `identity`, its one attempt standing."""
    walk = walking(run, frontier, identity)
    walk.standing = attempt_of(walk, response, verdict=verdict)
    walk.status = WalkStatus.settled
    return walk


def blocked_on_b() -> SiteResponse:
    """B's 403 at the end of the seed's redirect."""
    return redirected(answered(MOVED, FORBIDDEN))


def tallies(host: Host) -> tuple[object, ...]:
    """Every page tally FeedAnsweringBreaker leaves alone."""
    return (
        host.fetched,
        host.blocked,
        host.tiers_used,
        host.render_escalations,
        list(host.recent_text_lengths),
        host.retry_after_honored,
    )


def untouched(host: Host) -> None:
    """The host's breaker was not fed."""
    breaker = the_breaker(host)
    assert breaker.outcomes == []
    assert breaker.since_escalation == 0


# --- FetchAttempt.answering_host_name and answering_policy ----------------------------------


def test_an_answer_is_judged_by_the_host_that_answered(tmp_path: Path) -> None:
    """FetchAttempt.answering_host_name and answering_policy (crawl.allium 514 to 524).

    The host of the response's source_url and its request policy: the walk's own host for
    an answer that was not redirected, the destination for one that was. On an error the
    answering host is the host of the URL last requested (SiteResponse.source_url): a
    transport failure at the hop is B's, one at the seed and a hop refused before it was
    requested are A's.
    """
    run, frontier, _, _ = two_hosts(tmp_path, policy=IGNORING)
    walk = walking(run, frontier)
    own = attempt_of(walk, answered(SEED, TOO_MANY))
    moved = attempt_of(walk, redirected(answered(MOVED, TOO_MANY)))
    assert own.answering_host_name == HOST
    assert own.answering_policy == IGNORING
    assert moved.answering_host_name == OTHER_HOST
    assert moved.answering_policy == standard_policy()
    failed_at_hop = attempt_of(walk, redirected(unreachable(MOVED)))
    assert failed_at_hop.answering_host_name == OTHER_HOST
    assert attempt_of(walk, unreachable(SEED)).answering_host_name == HOST
    refused = dataclasses.replace(redirect_response(SEED, MOVED), error=pace.RETIRED_HOP)
    assert attempt_of(walk, refused).answering_host_name == HOST


# --- Item 11: a redirected answer's Retry-After, pause and escalation -----------------------


@pytest.mark.parametrize(
    "policy",
    [pytest.param(IGNORING, id="retry-after-ignored"), pytest.param(LONG_CAP, id="longer-cap")],
)
def test_a_redirected_retry_after_past_the_cap_retires_the_answering_host(
    tmp_path: Path, policy: CrawlPolicy
) -> None:
    """Owned A redirects to unselected B, which answers 429 past B's cap: B retires, not A.

    retires_host reads answering_policy (crawl.allium 531 to 535): A's relaxed policy
    would not retire on this answer, B's standard one does. RetireHostOnLongRetryAfter
    trips B's breaker (BreakerTripped(host: answering)); the walk settles with the 429
    standing and A's tiers_used gains its tier; A stays watching and B gains no tier.
    """
    run, frontier, a, b = two_hosts(tmp_path, policy=policy)
    walk = walking(run, frontier)
    own = attempt_of(walk, answered(SEED, TOO_MANY, retry_after=PAST_CAP))
    assert own.retires_host is False
    moved = attempt_of(walk, redirected(answered(MOVED, TOO_MANY, retry_after=PAST_CAP)))
    assert moved.retires_host is True
    tripped = retire_host_on_long_retry_after(moved)
    assert not isinstance(tripped, bool)
    assert tripped.host is b
    assert b.breaker_tripped
    assert not a.breaker_tripped
    assert [trip.host for trip in run.trips] == [b]
    assert walk.status is WalkStatus.settled
    assert walk.standing is moved
    assert a.tiers_used == frozenset({Tier.http})
    assert b.tiers_used == frozenset()


def test_a_redirected_retry_after_is_counted_on_the_answering_host(tmp_path: Path) -> None:
    """CountRetryAfter (crawl.allium 1898 to 1913): counted on B, under B's policy.

    A ignores Retry-After (owned, relaxed); B, unselected, honours it: the redirected
    503's Retry-After counts on B, the same answer from A itself counts nowhere.
    """
    run, frontier, a, b = two_hosts(tmp_path, policy=IGNORING)
    walk = walking(run, frontier)
    assert not count_retry_after(
        attempt_of(walk, answered(SEED, SERVICE_UNAVAILABLE, retry_after=UNDER_CAP))
    )
    moved = attempt_of(
        walk, redirected(answered(MOVED, SERVICE_UNAVAILABLE, retry_after=UNDER_CAP))
    )
    assert count_retry_after(moved)
    assert b.retry_after_honored == 1
    assert a.retry_after_honored == 0


def test_a_redirected_retry_pauses_the_answering_host(tmp_path: Path) -> None:
    """HttpRetry (crawl.allium 1844 to 1868): the pause falls on B under B's policy.

    The redirected 503 with a Retry-After is retried: the walk's request again (a second
    http try of the seed), B paused until now + retry_wait under B's standard policy (at
    least the Retry-After, which B honours and A does not), A not paused.
    """
    run, frontier, a, b = two_hosts(tmp_path, policy=IGNORING)
    walk = walking(run, frontier)
    fetcher = FakeFetcher(
        {SEED: redirect_response(SEED, MOVED), MOVED: html_response(MOVED, PAGE)}
    )
    moved = attempt_of(
        walk, redirected(answered(MOVED, SERVICE_UNAVAILABLE, retry_after=UNDER_CAP))
    )
    assert moved.retryable
    backed_off = http_retry(moved, fetcher)
    assert backed_off is not None
    assert backed_off.host is b
    assert backed_off.until >= START + UNDER_CAP
    assert b.paused_until == backed_off.until
    assert a.paused_until is None
    assert [pause.host for pause in run.backoffs] == [b]
    assert walk.attempts[-1].try_ == moved.try_ + 1
    assert fetcher.requests == [SEED, MOVED]


def test_a_redirected_render_retry_after_pauses_the_answering_host(tmp_path: Path) -> None:
    """PauseHostOnRenderRetryAfter (crawl.allium 1919 to 1931): B paused, not A.

    A render's navigation answer redirected to B with a Retry-After under the cap pauses
    B as HttpRetry's wait would, under B's policy; A, which ignores Retry-After, is not
    paused.
    """
    run, frontier, a, b = two_hosts(tmp_path, policy=IGNORING)
    walk = walking(run, frontier)
    rendered = attempt_of(
        walk,
        redirected(answered(MOVED, SERVICE_UNAVAILABLE, retry_after=UNDER_CAP)),
        tier=Tier.browser,
    )
    backed_off = pause_host_on_render_retry_after(rendered)
    assert backed_off is not None
    assert backed_off.host is b
    assert backed_off.until >= START + UNDER_CAP
    assert b.paused_until == backed_off.until
    assert a.paused_until is None


def test_a_redirected_block_escalates_only_under_the_answering_hosts_policy(
    tmp_path: Path,
) -> None:
    """wants_escalation reads answering_policy.protection_escalation (crawl.allium 545 to 551).

    A, owned, escalates on a block (protection_escalation); a block answered by B, whose
    standard policy does not escalate, asks for no further tier.
    """
    run, frontier, _, _ = two_hosts(tmp_path)
    walk = walking(run, frontier)
    assert attempt_of(walk, answered(SEED, FORBIDDEN), verdict=HARD).wants_escalation is True
    moved = attempt_of(walk, blocked_on_b(), verdict=HARD)
    assert moved.wants_escalation is False


def test_an_answer_that_was_not_redirected_is_judged_by_the_walks_host(tmp_path: Path) -> None:
    """The non-redirect case is unchanged: the walk's own host is paused, counted and retired.

    A standard run over A and B: a 503 with a Retry-After from A itself counts on A and
    pauses A; a 429 past the cap from A retires A; B is never touched, and its breaker is
    never fed.
    """
    run, frontier, a, b = standard_two_hosts(tmp_path)
    walk = walking(run, frontier)
    busy = attempt_of(walk, answered(SEED, SERVICE_UNAVAILABLE, retry_after=UNDER_CAP))
    assert busy.answering_host_name == HOST
    assert count_retry_after(busy)
    backed_off = http_retry(busy, FakeFetcher({SEED: html_response(SEED, PAGE)}))
    assert backed_off is not None
    assert backed_off.host is a
    past = attempt_of(walk, answered(SEED, TOO_MANY, retry_after=PAST_CAP))
    tripped = retire_host_on_long_retry_after(past)
    assert not isinstance(tripped, bool)
    assert tripped.host is a
    assert a.retry_after_honored == 1
    assert b.retry_after_honored == 0
    assert b.paused_until is None
    assert not b.breaker_tripped
    assert not feed_answering_breaker(walk)
    untouched(b)


# --- Item 12: FeedAnsweringBreaker ----------------------------------------------------------


def test_rule_success_FeedAnsweringBreaker(tmp_path: Path) -> None:
    """Verify rule FeedAnsweringBreaker succeeds when all preconditions are met.

    A settled walk of A whose standing answer was redirected to B, open and watching under
    B's standard policy: B's breaker gains the one outcome (the 403 counts against the
    host) and since_escalation + 1, and nothing else of B moves: its page tallies,
    tiers_used, render escalations and text history stay. A's FeedBreaker still feeds A.
    An ok redirected page gives B a non-counted outcome, while its main text joins A's
    history, never B's.
    """
    run, frontier, a, b = two_hosts(tmp_path)
    before = tallies(b)
    walk = settled_walk(run, frontier, blocked_on_b(), verdict=HARD)
    assert feed_answering_breaker(walk)
    assert the_breaker(b).outcomes == [True]
    assert the_breaker(b).since_escalation == 1
    assert tallies(b) == before
    assert feed_breaker(walk)
    assert the_breaker(a).outcomes == [True]
    page = dataclasses.replace(redirected(html_response(MOVED_OTHER, PAGE)), main_text=TEXT)
    walk = settled_walk(run, frontier, page, identity=OTHER)
    assert feed_answering_breaker(walk)
    assert feed_breaker(walk)
    assert the_breaker(b).outcomes == [True, False]
    assert the_breaker(b).since_escalation == len(the_breaker(b).outcomes)
    assert b.recent_text_lengths == []
    assert a.recent_text_lengths == [TEXT]
    assert tallies(b) == before


def test_rule_failure_FeedAnsweringBreaker_1(tmp_path: Path) -> None:
    """Verify rule FeedAnsweringBreaker is rejected when requires clause fails.

    requires: walk.status = settled: a walk still walking feeds no answering breaker.
    """
    run, frontier, _, b = two_hosts(tmp_path)
    walk = settled_walk(run, frontier, blocked_on_b(), verdict=HARD)
    walk.status = WalkStatus.walking
    assert not feed_answering_breaker(walk)
    untouched(b)


def test_rule_failure_FeedAnsweringBreaker_2(tmp_path: Path) -> None:
    """Verify rule FeedAnsweringBreaker is rejected when requires clause fails.

    requires: exists answering and answering != walk.host: an answer that was not
    redirected (A answered) feeds no second breaker, A's included; a redirect onto an
    allowed host that is not open feeds nothing either.
    """
    run, frontier, a, b = two_hosts(tmp_path / "own")
    walk = settled_walk(run, frontier, answered(SEED, FORBIDDEN), verdict=HARD)
    assert not feed_answering_breaker(walk)
    untouched(a)
    untouched(b)

    run, frontier = owner_started(tmp_path / "unopened", allowed_hosts=TWO_HOSTS)
    a = owner_host(run)
    walk = settled_walk(run, frontier, blocked_on_b(), verdict=HARD)
    assert run.host(OTHER_HOST) is None
    assert not feed_answering_breaker(walk)
    untouched(a)


def test_rule_failure_FeedAnsweringBreaker_3(tmp_path: Path) -> None:
    """Verify rule FeedAnsweringBreaker is rejected when requires clause fails.

    requires: exists breaker and breaker.status = watching: B's tripped breaker, or none,
    is not fed.
    """
    run, frontier, _, b = two_hosts(tmp_path)
    breaker = the_breaker(b)
    breaker.status = BreakerStatus.tripped
    walk = settled_walk(run, frontier, blocked_on_b(), verdict=HARD)
    assert not feed_answering_breaker(walk)
    assert breaker.outcomes == []
    assert breaker.since_escalation == 0
    b.breaker = None
    assert not feed_answering_breaker(walk)


def test_rule_failure_FeedAnsweringBreaker_4(tmp_path: Path) -> None:
    """Verify rule FeedAnsweringBreaker is rejected when requires clause fails.

    requires: answering.policy.breaker_enabled: B selected and owned too, in an owner run
    whose request disables the breaker, is not fed.
    """
    disabled = dataclasses.replace(ESCALATING, breaker_enabled=False)
    run, frontier, _, b = two_hosts(tmp_path, policy=disabled, owned=TWO_HOSTS)
    assert b.request_policy.breaker_enabled is False
    walk = settled_walk(run, frontier, blocked_on_b(), verdict=HARD)
    assert not feed_answering_breaker(walk)
    untouched(b)


def test_redirected_answers_trip_the_answering_host_while_the_owner_disables_a_breaker(
    tmp_path: Path,
) -> None:
    """B's breaker is fed by redirected answers and trips, though A's is disabled.

    An owner run whose request disables the breaker on owned A follows up COUNT + 2 pages
    of A, each redirecting to a page of unselected B that answers 403. B's breaker, under
    B's standard policy, is fed one outcome per walk and trips once it should act at its
    highest tier (http: render_mode never), BreakerTripped(host: B); no later hop goes to
    B. A's breaker is never fed and A never trips (the maintainer's answer 12).
    """
    mirror = new_mirror(tmp_path, allowed_hosts=TWO_HOSTS)
    pages = [f"{SITE}/guide/p{index:02}.html" for index in range(COUNT + 2)]
    moved = {page: page.replace(SITE, OTHER_SITE) for page in pages}
    responses = {page: redirect_response(page, target) for page, target in moved.items()}
    responses.update(
        {target: html_response(target, "", status=FORBIDDEN) for target in moved.values()}
    )
    fetcher = FakeFetcher(responses)
    base = finished_run(mirror, unresolved=frozenset(pages))
    policy = dataclasses.replace(standard_policy(), breaker_enabled=False)
    result = drive_run(
        owner_request(mirror, baseline=base, policy=policy, render_mode=RenderMode.never),
        None,
        fetcher,
        FixedClock(),
    )
    a = result.run.host(HOST)
    b = result.run.host(OTHER_HOST)
    assert a is not None
    assert b is not None
    assert b.breaker_tripped
    assert [trip.host for trip in result.tripped] == [b]
    assert not a.breaker_tripped
    assert the_breaker(a).outcomes == []
    assert sum(fetcher.requests.count(target) for target in moved.values()) == COUNT


# --- Item 13: discovery fetches -------------------------------------------------------------


def test_a_redirected_declared_sitemap_past_the_cap_retires_the_answering_host(
    tmp_path: Path,
) -> None:
    """FetchSitemap (crawl.allium 1065 to 1097): the past-cap answer is judged by B.

    A's declared sitemap redirects to B, which answers 429 past B's cap: B's breaker
    trips (BreakerTripped(host: judged)), A's does not.
    """
    run, frontier, a, b = standard_two_hosts(tmp_path)
    fetcher = FakeFetcher(
        {
            MAPS: redirect_response(MAPS, MOVED_MAPS),
            MOVED_MAPS: answered(MOVED_MAPS, TOO_MANY, retry_after=PAST_CAP),
        }
    )
    response = fetch_sitemap(run, HOST, MAPS, fetcher, declared=True, frontier=frontier)
    assert response is not None
    assert response.source_url == MOVED_MAPS
    assert b.breaker_tripped
    assert not a.breaker_tripped
    assert [trip.host for trip in run.trips] == [b]


def test_a_redirected_speculative_probe_past_the_cap_pauses_the_answering_host(
    tmp_path: Path,
) -> None:
    """FetchSitemap and ReadLlmsTxt (crawl.allium 1065 to 1097, 1298 to 1317): B paused.

    A speculative sitemap probe, and llms.txt, each redirected to B answering 429 past
    the cap, pause B for B's retry_after_cap (HostBackedOff(host: judged)); A is not
    paused and nothing trips.
    """
    run, frontier, a, b = standard_two_hosts(tmp_path / "sitemap")
    fetcher = FakeFetcher(
        {
            MAPS: redirect_response(MAPS, MOVED_MAPS),
            MOVED_MAPS: answered(MOVED_MAPS, TOO_MANY, retry_after=PAST_CAP),
        }
    )
    assert fetch_sitemap(run, HOST, MAPS, fetcher, frontier=frontier) is not None
    assert b.paused_until == START + b.request_policy.retry_after_cap
    assert a.paused_until is None
    assert [pause.host for pause in run.backoffs] == [b]
    assert not run.trips

    run, frontier, a, b = standard_two_hosts(tmp_path / "llms")
    fetcher = FakeFetcher(
        {
            LLMS: redirect_response(LLMS, MOVED_LLMS),
            MOVED_LLMS: answered(MOVED_LLMS, TOO_MANY, retry_after=PAST_CAP),
        }
    )
    assert read_llms_txt(run, HOST, frontier, fetcher) is not None
    assert b.paused_until == START + b.request_policy.retry_after_cap
    assert a.paused_until is None
    assert [pause.host for pause in run.backoffs] == [b]
    assert not run.trips


def test_a_redirected_discovery_retry_is_counted_and_paused_on_the_answering_host(
    tmp_path: Path,
) -> None:
    """FetchRobots guidance (crawl.allium 892 to 904): each try's wait is the answering host's.

    A's sitemap redirects to B, which answers 503 with a Retry-After under the cap, then
    the sitemap: the try's retry_after_honored, pause and HostBackedOff fall on B; A is
    neither counted nor paused.
    """
    run, frontier, a, b = standard_two_hosts(tmp_path)
    fetcher = ScriptedFetcher(
        {
            MAPS: redirect_response(MAPS, MOVED_MAPS),
            MOVED_MAPS: xml_response(MOVED_MAPS, "<urlset></urlset>"),
        },
        {MOVED_MAPS: [answered(MOVED_MAPS, SERVICE_UNAVAILABLE, retry_after=UNDER_CAP)]},
    )
    response = fetch_sitemap(run, HOST, MAPS, fetcher, declared=True, frontier=frontier)
    assert response is not None
    assert response.ok
    assert b.retry_after_honored == 1
    assert a.retry_after_honored == 0
    assert [pause.host for pause in run.backoffs] == [b]
    assert b.paused_until is not None
    assert a.paused_until is None


def test_a_redirected_robots_txt_past_the_cap_retires_the_open_answering_host(
    tmp_path: Path,
) -> None:
    """FetchRobots (crawl.allium 827 to 847): judged by the open host that answered.

    B is open; A's robots.txt, read as A opens, redirects to B, which answers 429 past
    the cap: B's breaker trips, not A's. The robots.txt still belongs to A's origin: its
    answer, a 429, disallows A's origin (robots_refused), and B's own origin keeps the
    stance B's robots.txt gave it.
    """
    run = start_run(request(new_mirror(tmp_path, allowed_hosts=TWO_HOSTS)), FixedClock())
    assert run is not None
    b = owner_host(run, OTHER_HOST, OTHER_SITE)
    fetcher = FakeFetcher(
        {
            ROBOTS: redirect_response(ROBOTS, MOVED_ROBOTS),
            MOVED_ROBOTS: answered(MOVED_ROBOTS, TOO_MANY, retry_after=PAST_CAP),
        }
    )
    a = open_host(run, HOST, SITE, fetcher)
    assert a is not None
    assert b.breaker_tripped
    assert not a.breaker_tripped
    assert [trip.host for trip in run.trips] == [b]
    own = run.robots_policy(SITE)
    assert own is not None
    assert own.stance is RobotsStance.disallow_all
    other = run.robots_policy(OTHER_SITE)
    assert other is not None
    assert other.stance is RobotsStance.allow_all


def test_a_robots_hop_onto_an_unopened_host_is_judged_by_the_fetching_host(
    tmp_path: Path,
) -> None:
    """FetchRobots (crawl.allium 892 to 904): with no open answering host, `judged` is A.

    A robots.txt hop opens no host, so a past-cap answer from a host the run has not
    opened is judged by the fetch's own host, which retires (the reading the lead
    accepted, T20 follow-up at fc9ad9f).
    """
    run = start_run(request(new_mirror(tmp_path, allowed_hosts=TWO_HOSTS)), FixedClock())
    assert run is not None
    fetcher = FakeFetcher(
        {
            ROBOTS: redirect_response(ROBOTS, MOVED_ROBOTS),
            MOVED_ROBOTS: answered(MOVED_ROBOTS, TOO_MANY, retry_after=PAST_CAP),
        }
    )
    a = open_host(run, HOST, SITE, fetcher)
    assert a is not None
    assert run.host(OTHER_HOST) is None
    assert a.breaker_tripped
    assert [trip.host for trip in run.trips] == [a]


# --- Item 15: a render subrequest's Retry-After pauses the host that answered it ------------

STYLE = f"{SITE}/guide/style.css"
MOVED_STYLE = f"{OTHER_SITE}/guide/style.css"


def rendered_with_subrequest(walk: LadderWalk, style: SiteResponse) -> FakeFetcher:
    """Render the walk's seed, whose page asks for A's style sheet, `style` answering it.

    A's style sheet redirects to B's, which answers `style`; the seed answers its page.
    The fetcher is returned with the requests it saw.
    """
    fetcher = FakeFetcher(
        {
            SEED: html_response(SEED, PAGE),
            STYLE: redirect_response(STYLE, MOVED_STYLE),
            MOVED_STYLE: style,
        }
    )
    engine = FakeEngine({SEED: PAGE}, subrequests={SEED: [STYLE]})
    answer = _Render(walk, fetcher).through(engine)
    assert answer.ok
    assert engine.aborted == []
    return fetcher


def test_a_redirected_subrequests_retry_after_pauses_the_answering_host(tmp_path: Path) -> None:
    """AttemptTier guidance (crawl.allium 1745 to 1755, spec 53687d9, item 15): B, not A.

    A render of A's seed asks for A's style sheet, which A redirects to B's; B answers
    429 with a Retry-After under the cap. The host that answered is B, the host of the
    subrequest's last request, so B is paused under its own request policy (the standard
    policy honours Retry-After), while A, the host the subrequest was sent to, whose owner
    policy ignores Retry-After, is never paused. The subrequest is not retried.
    """
    run, frontier, a, b = two_hosts(tmp_path, policy=IGNORING)
    walk = walking(run, frontier)
    fetcher = rendered_with_subrequest(
        walk, answered(MOVED_STYLE, TOO_MANY, retry_after=UNDER_CAP)
    )
    assert fetcher.requests.count(STYLE) == 1
    assert fetcher.requests.count(MOVED_STYLE) == 1
    assert [pause.host for pause in run.backoffs] == [b]
    assert b.paused_until is not None
    assert b.paused_until >= START + UNDER_CAP
    assert a.paused_until is None


def test_a_redirected_subrequests_retry_after_is_capped_by_the_answering_hosts_policy(
    tmp_path: Path,
) -> None:
    """Item 15: the pause is at most the answering host's retry_after_cap; never a retirement.

    A's owner policy honours Retry-After under a cap twice past B's; B answers 429 with a
    Retry-After past both. B is paused for at most its standard cap, never retired: no
    trip, no breaker fed (B's and A's breakers see no outcome), and A is not paused.
    """
    run, frontier, a, b = two_hosts(tmp_path, policy=LONG_CAP)
    walk = walking(run, frontier)
    rendered_with_subrequest(walk, answered(MOVED_STYLE, TOO_MANY, retry_after=PAST_CAP * 3))
    (backed_off,) = run.backoffs
    assert backed_off.host is b
    assert backed_off.until <= run.timer.now() + CAP
    assert b.paused_until == backed_off.until
    assert a.paused_until is None
    assert not b.breaker_tripped
    assert not a.breaker_tripped
    assert run.trips == []
    untouched(b)
    untouched(a)


def test_a_subrequest_answered_by_an_unopened_host_pauses_the_host_it_was_sent_to(
    tmp_path: Path,
) -> None:
    """Item 15: when the host that answered is not open, the host requested stands in.

    Only A is open. A's style sheet comes back from B's URL (its source_url, after the
    fetcher's redirect) with a Retry-After: B is not open, so A, the host the subrequest
    was sent to, is paused under A's policy, at most its cap, and B is never opened.
    """
    run, frontier = owner_started(tmp_path, allowed_hosts=TWO_HOSTS)
    a = owner_host(run)
    fetcher = FakeFetcher(
        {
            SEED: html_response(SEED, PAGE),
            STYLE: answered(MOVED_STYLE, TOO_MANY, retry_after=UNDER_CAP),
        }
    )
    walk = walking(run, frontier)
    engine = FakeEngine({SEED: PAGE}, subrequests={SEED: [STYLE]})
    assert _Render(walk, fetcher).through(engine).ok
    assert [pause.host for pause in run.backoffs] == [a]
    assert a.paused_until is not None
    assert a.paused_until <= run.timer.now() + a.request_policy.retry_after_cap
    assert run.host(OTHER_HOST) is None
    assert not a.breaker_tripped
    untouched(a)
