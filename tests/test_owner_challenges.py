"""Owner challenges (T20): PrepareAttempt's offer, the three owner rules and SettleChallenge.

Each obligation test is named after the id `just plan-spec crawl` emits (at 941e02d,
unchanged in id at 39c1f9c), dots and hyphens as underscores, and its docstring quotes
the obligation. A `rule_failure` test makes exactly one `requires` clause false. No
recogniser ships (crawl.allium open question 2670) and no prompt ships (open question
2671): every challenge verdict here is constructed, and the owner answers through the
ChallengePrompt seam, `FakeChallengePrompt`, which steps a SteppingTimer instead of
sleeping and never reads standard input. The guarantees: no offer at http, outside
owner testing, to a non-interactive run, on an unselected host, after a redirect to an
unselected host, or twice in a walk; a resolved challenge re-requests the same tier at
try 1 and a fresh response decides the page; an abandoned or timed-out one keeps the
blocked result and climbs no further; an interrupt abandons a waiting challenge; and,
under the one-row-at-a-time interim (crawl.allium open question 2668), nothing else is
requested and the breaker is not fed while a challenge waits (T20 item 9, decided).
"""

import dataclasses
from datetime import timedelta
from pathlib import Path

import pytest

from fakes import (
    START,
    FakeChallengePrompt,
    FakeEngine,
    FakeFetcher,
    SteppingTimer,
    html_response,
)
from rovo._crawl import run as run_module
from rovo._crawl.model import (
    CONFIG,
    BlockKind,
    BlockVerdict,
    ChallengeSettled,
    ChallengeStatus,
    CrawlPolicy,
    FetchAttempt,
    Frontier,
    OwnerChallenge,
    RunStatus,
    SiteResponse,
    WalkStatus,
    standard_policy,
)
from rovo._crawl.run import (
    create_frontier,
    drive_run,
    interrupt_run,
    owner_abandons_challenge,
    owner_challenge_times_out,
    owner_completes_challenge,
    prepare_attempt,
    settle_challenge,
    settle_walk,
    start_run,
)
from rovo._mirror.model import Tier
from spec_values import spec_duration
from test_crawl import HOST, PAGE, SEED, SITE, new_mirror, request
from test_owner_testing import (
    CHALLENGE_PAGE,
    CHALLENGING,
    OTHER_HOST,
    OTHER_SEED,
    OWNED,
    challenge_walk,
    challenged_attempt,
    finished_run,
    owner_host,
    owner_request,
    owner_started,
)

CHALLENGE_MARKER = "Checking your browser."
# A second follow-up seed that sorts after the seed, so it is fetched after it.
LATER = f"{SITE}/guide/z-later.html"
FRESH_PAGE = PAGE
TIMEOUT = CHALLENGING.challenge_timeout
SECOND = timedelta(seconds=1)


def challenged(
    out_dir: Path,
    *,
    policy: CrawlPolicy = CHALLENGING,
    interactive: bool = True,
    tier: Tier = Tier.browser,
    source_url: str | None = None,
    **scope: object,
) -> tuple[SteppingTimer, Frontier, FetchAttempt]:
    """An interactive owner run with challenges, its owned host open, and a challenge attempt."""
    timer = SteppingTimer()
    run, frontier = owner_started(
        out_dir,
        clock=timer,
        policy=policy,
        interactive=interactive,
        **scope,  # type: ignore[arg-type]  # Test overrides by name.
    )
    owner_host(run)
    walk = challenge_walk(run, frontier)
    return timer, frontier, challenged_attempt(walk, tier=tier, source_url=source_url)


def offered(out_dir: Path) -> tuple[SteppingTimer, Frontier, FetchAttempt, OwnerChallenge]:
    """A challenge PrepareAttempt offered on a constructed browser-tier challenge verdict."""
    timer, frontier, attempt = challenged(out_dir)
    assert prepare_attempt(attempt) is False
    (challenge,) = attempt.challenges
    return timer, frontier, attempt, challenge


def assert_no_offer(attempt: FetchAttempt) -> None:
    """PrepareAttempt raised AttemptReady (True) with no challenge, the walk not marked."""
    assert prepare_attempt(attempt) is True
    assert attempt.challenges == []
    assert attempt.walk.challenge_offered is False


def assert_waiting(challenge: OwnerChallenge) -> None:
    """InteractiveChallengeIsOwnerOnly for a waiting challenge."""
    run = challenge.attempt.walk.host.run
    assert run.is_owner_testing
    assert run.policy.interactive_challenges
    assert run.interactive
    assert challenge.attempt.walk.host.name in run.owned_hosts


def status_of(challenge: OwnerChallenge) -> ChallengeStatus:
    """The challenge's status as it stands now (a call, so no earlier check narrows it)."""
    return challenge.status


def fresh(url: str = SEED) -> SiteResponse:
    """The page as it answers once the owner has completed the challenge."""
    return html_response(url, FRESH_PAGE)


# --- FetchAttempt.challenges and OwnerChallenge ----------------------------------------


def test_entity_relationship_FetchAttempt_challenges(tmp_path: Path) -> None:
    """Verify relationship FetchAttempt.challenges navigates to the correct related entities.

    OwnerChallenge with attempt = this: the offered challenge is the attempt's, and only
    its; unsuccessful_challenge follows its status (abandoned or timed out).
    """
    _, _, attempt, challenge = offered(tmp_path)
    assert challenge.attempt is attempt
    assert attempt.challenges == [challenge]
    other = challenged_attempt(attempt.walk)
    assert other.challenges == []
    expected = {
        ChallengeStatus.waiting: False,
        ChallengeStatus.abandoned: True,
        ChallengeStatus.timed_out: True,
        ChallengeStatus.resolved: False,
    }
    for status, unsuccessful in expected.items():
        challenge.status = status
        assert attempt.unsuccessful_challenge is unsuccessful, status


def test_entity_fields_OwnerChallenge(tmp_path: Path) -> None:
    """Verify all declared fields on OwnerChallenge are present with correct types.

    attempt, a FetchAttempt; expires_at, a Timestamp (the offer's time plus the policy's
    challenge_timeout); status, waiting when offered.
    """
    _, _, attempt, challenge = offered(tmp_path)
    assert isinstance(challenge.attempt, FetchAttempt)
    assert challenge.attempt is attempt
    assert challenge.expires_at == START + TIMEOUT
    assert challenge.expires_at.tzinfo is not None
    assert challenge.status is ChallengeStatus.waiting


def test_config_default_owner_challenge_timeout(tmp_path: Path) -> None:
    """Verify config parameter owner_challenge_timeout has its declared default.

    The default is the specification's and the standard policy's challenge_timeout; a
    challenge offered under it expires that long after the offer.
    """
    assert spec_duration("crawl", "owner_challenge_timeout") == CONFIG.owner_challenge_timeout
    assert standard_policy().challenge_timeout == CONFIG.owner_challenge_timeout
    assert CHALLENGING.challenge_timeout == CONFIG.owner_challenge_timeout
    _, _, _, challenge = offered(tmp_path)
    assert challenge.expires_at == START + CONFIG.owner_challenge_timeout


# --- OwnerChallenge.status ---------------------------------------------------------------


def test_transition_edge_OwnerChallenge_waiting_resolved(tmp_path: Path) -> None:
    """Verify transition waiting -> resolved on OwnerChallenge.status is reachable.

    The obligation: it is reachable via a witnessing rule.

    OwnerCompletesChallenge raises ChallengeSettled(resolved); SettleChallenge resolves it.
    """
    _, _, attempt, challenge = offered(tmp_path)
    settled = owner_completes_challenge(challenge)
    assert settled == ChallengeSettled(challenge=challenge, outcome=ChallengeStatus.resolved)
    fetcher = FakeFetcher({SEED: fresh()})
    assert settle_challenge(settled, fetcher, FakeEngine()) is not False
    assert challenge.status is ChallengeStatus.resolved
    assert attempt.walk.status is WalkStatus.walking


def test_transition_edge_OwnerChallenge_waiting_abandoned(tmp_path: Path) -> None:
    """Verify transition waiting -> abandoned on OwnerChallenge.status is reachable.

    The obligation: it is reachable via a witnessing rule.

    OwnerAbandonsChallenge raises ChallengeSettled(abandoned); SettleChallenge abandons it.
    """
    _, _, _, challenge = offered(tmp_path)
    settled = owner_abandons_challenge(challenge)
    assert settled == ChallengeSettled(challenge=challenge, outcome=ChallengeStatus.abandoned)
    assert settle_challenge(settled, FakeFetcher({})) is True
    assert challenge.status is ChallengeStatus.abandoned


def test_transition_edge_OwnerChallenge_waiting_timed_out(tmp_path: Path) -> None:
    """Verify transition waiting -> timed_out on OwnerChallenge.status is reachable.

    The obligation: it is reachable via a witnessing rule.

    At expires_at OwnerChallengeTimesOut raises ChallengeSettled(timed_out); SettleChallenge
    times it out.
    """
    timer, _, _, challenge = offered(tmp_path)
    timer.sleep(TIMEOUT.total_seconds())
    settled = owner_challenge_times_out(challenge)
    assert settled == ChallengeSettled(challenge=challenge, outcome=ChallengeStatus.timed_out)
    assert settle_challenge(settled, FakeFetcher({})) is True
    assert challenge.status is ChallengeStatus.timed_out


def assert_stays(challenge: OwnerChallenge, status: ChallengeStatus) -> None:
    """No rule moves a settled challenge: every rule declines and the status stays."""
    timer = challenge.attempt.walk.host.run.timer
    assert isinstance(timer, SteppingTimer)
    assert owner_completes_challenge(challenge) is None
    assert owner_abandons_challenge(challenge) is None
    timer.sleep(TIMEOUT.total_seconds())
    assert owner_challenge_times_out(challenge) is None
    for outcome in (
        ChallengeStatus.resolved,
        ChallengeStatus.abandoned,
        ChallengeStatus.timed_out,
    ):
        settled = ChallengeSettled(challenge=challenge, outcome=outcome)
        assert settle_challenge(settled, FakeFetcher({})) is False
    assert challenge.status is status


def test_transition_rejected_OwnerChallenge_status(tmp_path: Path) -> None:
    """Verify undeclared transitions on OwnerChallenge.status are rejected.

    Only waiting has outbound edges: a resolved challenge cannot become abandoned, timed
    out or waiting again; SettleChallenge refuses a second settlement.
    """
    _, _, _, challenge = offered(tmp_path)
    settled = owner_completes_challenge(challenge)
    assert settled is not None
    assert settle_challenge(settled, FakeFetcher({SEED: fresh()}), FakeEngine()) is not False
    assert_stays(challenge, ChallengeStatus.resolved)


@pytest.mark.parametrize(
    "status",
    [ChallengeStatus.resolved, ChallengeStatus.abandoned, ChallengeStatus.timed_out],
    ids=lambda status: status.value,
)
def test_transition_terminal_OwnerChallenge_status(
    tmp_path: Path, status: ChallengeStatus
) -> None:
    """Verify terminal states on OwnerChallenge.status have no outbound transitions.

    resolved, abandoned and timed_out: no rule fires on a challenge in any of them.
    """
    _, _, _, challenge = offered(tmp_path)
    challenge.status = status
    assert_stays(challenge, status)


# --- OwnerCompletesChallenge -------------------------------------------------------------


def test_rule_success_OwnerCompletesChallenge(tmp_path: Path) -> None:
    """Verify rule OwnerCompletesChallenge succeeds when all preconditions are met.

    A waiting challenge, before expires_at, in a running owner run, its walk walking on
    an owned host: ChallengeSettled(resolved), the challenge still waiting until settled.
    """
    timer, _, _, challenge = offered(tmp_path)
    timer.sleep((TIMEOUT - SECOND).total_seconds())
    settled = owner_completes_challenge(challenge)
    assert settled == ChallengeSettled(challenge=challenge, outcome=ChallengeStatus.resolved)
    assert challenge.status is ChallengeStatus.waiting


def test_rule_failure_OwnerCompletesChallenge_1(tmp_path: Path) -> None:
    """Verify rule OwnerCompletesChallenge is rejected when requires clause fails.

    requires: challenge.status = waiting: an abandoned challenge is not completed.
    """
    _, _, _, challenge = offered(tmp_path)
    challenge.status = ChallengeStatus.abandoned
    assert owner_completes_challenge(challenge) is None
    assert challenge.status is ChallengeStatus.abandoned


def test_rule_failure_OwnerCompletesChallenge_2(tmp_path: Path) -> None:
    """Verify rule OwnerCompletesChallenge is rejected when requires clause fails.

    requires: now < challenge.expires_at: a completion at expires_at is no completion.
    """
    timer, _, _, challenge = offered(tmp_path)
    timer.sleep(TIMEOUT.total_seconds())
    assert owner_completes_challenge(challenge) is None
    assert challenge.status is ChallengeStatus.waiting


def test_rule_failure_OwnerCompletesChallenge_3(tmp_path: Path) -> None:
    """Verify rule OwnerCompletesChallenge is rejected when requires clause fails.

    requires: run.status = running and run.is_owner_testing: a challenge of a run that
    has ended is not completed.
    """
    _, _, attempt, challenge = offered(tmp_path)
    attempt.walk.host.run.status = RunStatus.interrupted
    assert owner_completes_challenge(challenge) is None
    assert challenge.status is ChallengeStatus.waiting


def test_rule_failure_OwnerCompletesChallenge_4(tmp_path: Path) -> None:
    """Verify rule OwnerCompletesChallenge is rejected when requires clause fails.

    requires: attempt.walk.status = walking: a challenge of a settled walk is not completed.
    """
    _, _, attempt, challenge = offered(tmp_path)
    attempt.walk.status = WalkStatus.settled
    assert owner_completes_challenge(challenge) is None
    assert challenge.status is ChallengeStatus.waiting


def test_rule_failure_OwnerCompletesChallenge_5(tmp_path: Path) -> None:
    """Verify rule OwnerCompletesChallenge is rejected when requires clause fails.

    requires: attempt.walk.host.name in run.owned_hosts: a challenge whose walk's host is
    no longer owned by the run is not completed.
    """
    _, _, attempt, challenge = offered(tmp_path)
    attempt.walk.host.run.owned_hosts = frozenset({OTHER_HOST})
    assert owner_completes_challenge(challenge) is None
    assert challenge.status is ChallengeStatus.waiting


# --- OwnerAbandonsChallenge and OwnerChallengeTimesOut ---------------------------------


def test_rule_success_OwnerAbandonsChallenge(tmp_path: Path) -> None:
    """Verify rule OwnerAbandonsChallenge succeeds when all preconditions are met.

    A waiting challenge of a running run: ChallengeSettled(abandoned).
    """
    _, _, _, challenge = offered(tmp_path)
    settled = owner_abandons_challenge(challenge)
    assert settled == ChallengeSettled(challenge=challenge, outcome=ChallengeStatus.abandoned)


def test_rule_failure_OwnerAbandonsChallenge_1(tmp_path: Path) -> None:
    """Verify rule OwnerAbandonsChallenge is rejected when requires clause fails.

    requires: challenge.status = waiting: a resolved challenge is not abandoned.
    """
    _, _, _, challenge = offered(tmp_path)
    challenge.status = ChallengeStatus.resolved
    assert owner_abandons_challenge(challenge) is None
    assert challenge.status is ChallengeStatus.resolved


def test_rule_failure_OwnerAbandonsChallenge_2(tmp_path: Path) -> None:
    """Verify rule OwnerAbandonsChallenge is rejected when requires clause fails.

    requires: challenge.attempt.walk.host.run.status = running: a finished run's challenge
    is not abandoned by the owner.
    """
    _, _, attempt, challenge = offered(tmp_path)
    attempt.walk.host.run.status = RunStatus.finished
    assert owner_abandons_challenge(challenge) is None
    assert challenge.status is ChallengeStatus.waiting


def test_rule_success_OwnerChallengeTimesOut(tmp_path: Path) -> None:
    """Verify rule OwnerChallengeTimesOut succeeds when all preconditions are met.

    A waiting challenge whose expires_at has passed: ChallengeSettled(timed_out).
    """
    timer, _, _, challenge = offered(tmp_path)
    timer.sleep((TIMEOUT + SECOND).total_seconds())
    settled = owner_challenge_times_out(challenge)
    assert settled == ChallengeSettled(challenge=challenge, outcome=ChallengeStatus.timed_out)


def test_temporal_OwnerChallengeTimesOut(tmp_path: Path) -> None:
    """Verify temporal trigger in OwnerChallengeTimesOut fires at deadline, not before.

    The obligation: it fires at the deadline, not before, and does not re-fire.

    Through the SteppingTimer: waiting a second before expires_at, timed out at it, and
    once settled it does not fire again.
    """
    timer, _, _, challenge = offered(tmp_path)
    timer.sleep((TIMEOUT - SECOND).total_seconds())
    assert owner_challenge_times_out(challenge) is None
    assert challenge.status is ChallengeStatus.waiting
    timer.sleep(SECOND.total_seconds())
    assert timer.now() == challenge.expires_at
    settled = owner_challenge_times_out(challenge)
    assert settled is not None
    assert settle_challenge(settled, FakeFetcher({})) is True
    timer.sleep(TIMEOUT.total_seconds())
    assert owner_challenge_times_out(challenge) is None
    assert status_of(challenge) is ChallengeStatus.timed_out


def test_rule_failure_OwnerChallengeTimesOut_1(tmp_path: Path) -> None:
    """Verify rule OwnerChallengeTimesOut is rejected when requires clause fails.

    requires: challenge.status = waiting: an abandoned challenge past its deadline does
    not time out.
    """
    timer, _, _, challenge = offered(tmp_path)
    challenge.status = ChallengeStatus.abandoned
    timer.sleep((TIMEOUT + SECOND).total_seconds())
    assert owner_challenge_times_out(challenge) is None
    assert challenge.status is ChallengeStatus.abandoned


# --- SettleChallenge -------------------------------------------------------------------


def test_rule_success_SettleChallenge(tmp_path: Path) -> None:
    """Verify rule SettleChallenge succeeds when all preconditions are met.

    Resolved: the same tier is requested again at try 1 (TierRequested), a fresh render;
    abandoned: AttemptReady with the blocked attempt, nothing requested.
    """
    _, _, attempt, challenge = offered(tmp_path / "resolved")
    fetcher = FakeFetcher({SEED: fresh()})
    engine = FakeEngine()
    retried = settle_challenge(
        ChallengeSettled(challenge=challenge, outcome=ChallengeStatus.resolved), fetcher, engine
    )
    assert isinstance(retried, FetchAttempt)
    assert retried.tier is attempt.tier
    assert retried.try_ == 1
    assert retried is attempt.walk.attempts[-1]
    assert engine.renders == [SEED]
    _, _, blocked, other = offered(tmp_path / "abandoned")
    quiet = FakeFetcher({})
    settled = ChallengeSettled(challenge=other, outcome=ChallengeStatus.abandoned)
    assert settle_challenge(settled, quiet) is True
    assert quiet.requests == []
    assert blocked.walk.attempts[-1] is blocked


def test_rule_failure_SettleChallenge_1(tmp_path: Path) -> None:
    """Verify rule SettleChallenge is rejected when requires clause fails.

    requires: challenge.status = waiting: a challenge already settled is not settled
    again, and nothing is requested.
    """
    _, _, attempt, challenge = offered(tmp_path)
    challenge.status = ChallengeStatus.abandoned
    fetcher = FakeFetcher({SEED: fresh()})
    settled = ChallengeSettled(challenge=challenge, outcome=ChallengeStatus.resolved)
    assert settle_challenge(settled, fetcher, FakeEngine()) is False
    assert fetcher.requests == []
    assert challenge.status is ChallengeStatus.abandoned
    assert attempt.walk.attempts == [attempt]


# --- InteractiveChallengeIsOwnerOnly -----------------------------------------------------


def test_invariant_InteractiveChallengeIsOwnerOnly(tmp_path: Path) -> None:
    """Verify invariant InteractiveChallengeIsOwnerOnly holds after every state-changing rule.

    The obligation: it holds after every state-changing rule that touches constrained
    entities. Every waiting challenge belongs to an interactive owner run with
    interactive challenges, on an owned host: after the offer it holds; a run missing
    any one of the four creates none; after every settlement none waits.
    """
    _, _, attempt, challenge = offered(tmp_path / "offered")
    assert_waiting(challenge)
    settled = owner_abandons_challenge(challenge)
    assert settled is not None
    assert settle_challenge(settled, FakeFetcher({})) is True
    assert all(c.status is not ChallengeStatus.waiting for c in attempt.challenges)
    no_challenges = dataclasses.replace(CHALLENGING, interactive_challenges=False)
    for case, changes in (
        ("not-interactive", {"interactive": False}),
        ("no-interactive-challenges", {"policy": no_challenges}),
        ("unowned-host", {"owned": frozenset({OTHER_HOST})}),
    ):
        _, _, other = challenged(
            tmp_path / case,
            allowed_hosts=frozenset({HOST, OTHER_HOST}),
            **changes,
        )
        assert_no_offer(other)
    timer = SteppingTimer()
    standard = start_run(request(new_mirror(tmp_path / "standard")), timer)
    assert standard is not None
    frontier = create_frontier(standard, None)
    assert frontier is not None
    owner_host(standard)
    assert_no_offer(challenged_attempt(challenge_walk(standard, frontier)))


# --- Guarantees: where no challenge is offered -------------------------------------------


def test_no_challenge_is_offered_at_http(tmp_path: Path) -> None:
    """PrepareAttempt offers no challenge for an http attempt, even a challenge verdict."""
    _, _, attempt = challenged(tmp_path, tier=Tier.http)
    assert_no_offer(attempt)


def test_no_challenge_is_offered_twice_in_one_walk(tmp_path: Path) -> None:
    """A walk is offered one challenge at most: its second challenge verdict is ready."""
    _, _, attempt, _ = offered(tmp_path)
    assert attempt.walk.challenge_offered is True
    again = challenged_attempt(attempt.walk)
    assert prepare_attempt(again) is True
    assert again.challenges == []


def test_no_challenge_is_offered_after_a_redirect_to_an_unselected_host(tmp_path: Path) -> None:
    """offer_challenge's second host conjunct: the answer's source host must be owned too.

    The walk's host is selected and owned, but the challenge answered from an allowed,
    unselected host after a redirect: no OwnerChallenge, challenge_offered stays false,
    and AttemptReady is raised with the blocked result. InteractiveChallengeIsOwnerOnly
    checks the walk's host only, so this conjunct has its own test.
    """
    _, _, attempt = challenged(
        tmp_path, source_url=OTHER_SEED, allowed_hosts=frozenset({HOST, OTHER_HOST})
    )
    assert attempt.walk.host.name in OWNED
    assert_no_offer(attempt)
    assert attempt.verdict.kind is BlockKind.challenge


# --- Guarantees: what a settled challenge leaves ------------------------------------------


def test_a_resolved_challenge_lets_a_fresh_response_decide_the_page(tmp_path: Path) -> None:
    """NoAutomaticSolving: a completion triggers a fresh response check, which decides.

    The same tier is requested again at try 1; the fresh render is unblocked, and the walk
    settles on it, not on the challenge.
    """
    _, _, attempt, challenge = offered(tmp_path)
    fetcher = FakeFetcher({SEED: fresh()})
    settled = owner_completes_challenge(challenge)
    assert settled is not None
    retried = settle_challenge(settled, fetcher, FakeEngine())
    assert isinstance(retried, FetchAttempt)
    assert retried.verdict == BlockVerdict(kind=BlockKind.none, signature="")
    assert prepare_attempt(retried) is True
    assert settle_walk(retried)
    assert attempt.walk.standing is retried


@pytest.mark.parametrize("outcome", ["abandoned", "timed_out"])
def test_an_unsuccessful_challenge_keeps_the_blocked_result(tmp_path: Path, outcome: str) -> None:
    """Abandonment or expiry keeps the blocked result: no further escalation, settled blocked.

    Even with a higher tier usable (stealth, constructed), unsuccessful_challenge stops
    wants_escalation, and SettleWalk settles on the challenge attempt.
    """
    timer, _, attempt, challenge = offered(tmp_path)
    if outcome == "abandoned":
        settled = owner_abandons_challenge(challenge)
    else:
        timer.sleep(TIMEOUT.total_seconds())
        settled = owner_challenge_times_out(challenge)
    assert settled is not None
    assert settle_challenge(settled, FakeFetcher({})) is True
    attempt.walk.tiers = (Tier.http, Tier.browser, Tier.stealth)
    assert attempt.unsuccessful_challenge is True
    assert attempt.wants_escalation is False
    assert settle_walk(attempt)
    assert attempt.walk.standing is attempt
    assert attempt.walk.standing.verdict.kind is BlockKind.challenge


def test_an_interrupt_abandons_a_waiting_challenge(tmp_path: Path) -> None:
    """InterruptRun settles every waiting challenge of a walking walk as abandoned."""
    _, frontier, attempt, challenge = offered(tmp_path)
    run = attempt.walk.host.run
    run.interrupt_requested = True
    assert interrupt_run(run, frontier)
    assert challenge.status is ChallengeStatus.abandoned
    assert attempt.unsuccessful_challenge is True


def test_no_other_request_and_no_breaker_feed_while_a_challenge_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T20 item 9, decided: a challenge never waits while its host trips.

    Under the one-row-at-a-time interim (crawl.allium open question 2668), while the
    seed's challenge waits no other row is fetched and the waiting walk's host breaker
    has not been fed by it, so no rule can trip the host under it. The run's challenge
    verdict is constructed: classify_block is wrapped to call the challenge page a
    challenge, since no recogniser ships. The owner abandons it; the other seed is then
    fetched.
    """
    original = run_module.classify_block

    def constructed(response: SiteResponse, median_text: float | None) -> BlockVerdict:
        if CHALLENGE_MARKER in response.markup:
            return BlockVerdict(kind=BlockKind.challenge, signature="challenge")
        return original(response, median_text)

    monkeypatch.setattr(run_module, "classify_block", constructed)
    timer = SteppingTimer()
    mirror = new_mirror(tmp_path)
    base = finished_run(mirror, unresolved=frozenset({SEED, LATER}))
    fetcher = FakeFetcher(
        {
            SEED: html_response(SEED, "", status=403),
            LATER: html_response(LATER, PAGE),
        }
    )
    engine = FakeEngine({SEED: CHALLENGE_PAGE})
    seen: list[tuple[list[str], int]] = []

    def probe(challenge: OwnerChallenge) -> None:
        host = challenge.attempt.walk.host
        assert host.breaker is not None
        seen.append((list(fetcher.requests), len(host.breaker.outcomes)))

    prompt = FakeChallengePrompt([(ChallengeStatus.abandoned, SECOND)], timer=timer, on_ask=probe)
    result = drive_run(
        owner_request(mirror, baseline=base, policy=CHALLENGING, interactive=True),
        None,
        fetcher,
        timer,
        engine=engine,
        challenge_prompt=prompt,
    )
    assert len(prompt.asked) == 1
    ((requests_then, outcomes_then),) = seen
    assert requests_then[-1] == SEED
    assert LATER not in requests_then
    assert outcomes_then == 0
    (challenge,) = prompt.asked
    assert challenge.status is ChallengeStatus.abandoned
    assert LATER in fetcher.requests
    assert not result.run.has_tripped_host
