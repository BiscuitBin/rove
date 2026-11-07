"""Regression tests for T20's weed and review findings, one per divergence or gap.

Each is hash-pinned in .allium-loop/T20-owner-testing.json. No recogniser ships
(crawl.allium open question 2670) and no prompt ships (open question 2671): a challenge
verdict is constructed by wrapping classify_block, and the owner answers through the
ChallengePrompt seam, FakeChallengePrompt, which steps a SteppingTimer instead of
sleeping and never reads standard input.
"""

import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from fakes import (
    FakeChallengePrompt,
    FakeEngine,
    FakeFetcher,
    FixedClock,
    SteppingTimer,
    html_response,
    redirect_response,
)
from rovo._crawl import run as run_module
from rovo._crawl.model import (
    BlockKind,
    BlockVerdict,
    ChallengeStatus,
    FrontierStatus,
    OwnerChallenge,
    SiteResponse,
    WalkStatus,
)
from rovo._crawl.run import (
    CrawlResult,
    _Render,
    drive_run,
    feed_answering_breaker,
    lineage_run,
)
from rovo._mirror.model import Tier
from test_answering_host import (
    IGNORING,
    MOVED,
    MOVED_STYLE,
    UNDER_CAP,
    attempt_of,
    rendered_with_subrequest,
    two_hosts,
    walking,
)
from test_crawl import FORBIDDEN, HOST, PAGE, SEED, TOO_MANY, answered, new_mirror
from test_owner_testing import (
    CHALLENGE_PAGE,
    CHALLENGING,
    OTHER_HOST,
    OWNED,
    REFUSED_EXIT,
    disallowing,
    finished_run,
    owner_options,
    owner_request,
    owner_sync,
    ready,
    refused_owner,
    runs,
    the_breaker,
    warned,
)

CHALLENGE_MARKER = "Checking your browser."
SECOND = timedelta(seconds=1)


def constructed_challenges(monkeypatch: pytest.MonkeyPatch) -> None:
    """classify_block calls the challenge page a challenge (no recogniser ships)."""
    original = run_module.classify_block

    def constructed(response: SiteResponse, median_text: float | None) -> BlockVerdict:
        if CHALLENGE_MARKER in response.markup:
            return BlockVerdict(kind=BlockKind.challenge, signature="challenge")
        return original(response, median_text)

    monkeypatch.setattr(run_module, "classify_block", constructed)


def blocked_seed() -> FakeFetcher:
    """The seed answers 403: blocked at http, and the browser's navigation is the same."""
    return FakeFetcher({SEED: html_response(SEED, "", status=FORBIDDEN)})


def challenged_run(
    out_dir: Path,
    fetcher: FakeFetcher,
    engine: FakeEngine,
    prompt: FakeChallengePrompt,
    timer: SteppingTimer,
) -> CrawlResult:
    """An interactive owner run of the seed, blocked at http and challenged at the browser."""
    mirror = new_mirror(out_dir)
    base = finished_run(mirror, unresolved=frozenset({SEED}))
    return drive_run(
        owner_request(mirror, baseline=base, policy=CHALLENGING, interactive=True),
        None,
        fetcher,
        timer,
        engine=engine,
        challenge_prompt=prompt,
    )


def test_weed_1_gap_3_a_resolved_challenge_is_retried_through_drive_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Weed T20-1 intentional gap 3: await_challenge's resolved branch, through drive_run.

    The owner solves the challenge before its deadline (the site now serves the page):
    the prompt's answer is OwnerCompletesChallenge's, SettleChallenge re-requests the browser
    tier at try 1, and the fresh render decides the page, which is done. The timer never
    reaches expires_at: nothing waits out the deadline.
    """
    constructed_challenges(monkeypatch)
    timer = SteppingTimer()
    fetcher = blocked_seed()
    engine = FakeEngine({SEED: CHALLENGE_PAGE})

    def solve(challenge: OwnerChallenge) -> None:
        del challenge
        fetcher.responses[SEED] = html_response(SEED, PAGE)
        del engine.pages[SEED]

    prompt = FakeChallengePrompt([(ChallengeStatus.resolved, SECOND)], timer=timer, on_ask=solve)
    result = challenged_run(tmp_path, fetcher, engine, prompt, timer)
    (challenge,) = prompt.asked
    assert challenge.status is ChallengeStatus.resolved
    walk = challenge.attempt.walk
    assert [(attempt.tier, attempt.verdict.kind) for attempt in walk.attempts] == [
        (Tier.http, BlockKind.hard),
        (Tier.browser, BlockKind.challenge),
        (Tier.browser, BlockKind.none),
    ]
    assert walk.attempts[-1].try_ == 1
    assert walk.standing is walk.attempts[-1]
    assert engine.renders == [SEED, SEED]
    assert timer.now() < challenge.expires_at
    entry = result.frontier.entry(SEED)
    assert entry is not None
    assert entry.status is FrontierStatus.done


def test_weed_1_gap_3_an_unanswered_challenge_times_out_through_drive_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Weed T20-1 intentional gap 3: await_challenge's timed-out branch, through drive_run.

    The prompt gives no answer: the run's timer (a SteppingTimer, never a real sleep)
    waits out the rest of challenge_timeout, OwnerChallengeTimesOut fires exactly at
    expires_at, and the blocked attempt stands with no further escalation
    (unsuccessful_challenge): the row is blocked and the engine rendered once.
    """
    constructed_challenges(monkeypatch)
    timer = SteppingTimer()
    engine = FakeEngine({SEED: CHALLENGE_PAGE})
    prompt = FakeChallengePrompt([(None, SECOND)], timer=timer)
    result = challenged_run(tmp_path, blocked_seed(), engine, prompt, timer)
    (challenge,) = prompt.asked
    assert challenge.status is ChallengeStatus.timed_out
    assert timer.now() == challenge.expires_at
    attempt = challenge.attempt
    assert attempt.unsuccessful_challenge is True
    assert attempt.walk.standing is attempt
    assert [step.tier for step in attempt.walk.attempts] == [Tier.http, Tier.browser]
    assert engine.renders == [SEED]
    entry = result.frontier.entry(SEED)
    assert entry is not None
    assert entry.status is FrontierStatus.blocked


def test_weed_1_fc9ad9f_a_render_with_no_dom_after_a_redirect_came_from_the_answering_host(
    tmp_path: Path,
) -> None:
    """Weed T20-1 at fc9ad9f, code bug: a no-DOM render reports the navigation's last URL.

    crawl.allium 148: an error's source_url is the URL last requested. The render of A's
    seed follows its redirect to B, which answers, and the load state is never reached (no
    DOM): the render's answer is an error, status 0, whose source_url is B's URL, not the
    walk's seed. Its answering host is therefore B, and FeedAnsweringBreaker feeds B's
    breaker the counted outcome.
    """
    run, frontier, _, b = two_hosts(tmp_path)
    walk = walking(run, frontier)
    fetcher = FakeFetcher(
        {SEED: redirect_response(SEED, MOVED), MOVED: html_response(MOVED, PAGE)}
    )
    answer = _Render(walk, fetcher).through(FakeEngine({SEED: None}))
    assert fetcher.requests[-2:] == [SEED, MOVED]
    assert answer.status == 0
    assert answer.error
    assert answer.source_url == MOVED
    attempt = attempt_of(walk, answer, tier=Tier.browser)
    assert attempt.failed_outright
    assert attempt.answering_host_name == OTHER_HOST
    walk.standing = attempt
    walk.status = WalkStatus.settled
    assert feed_answering_breaker(walk)
    assert the_breaker(b).outcomes == [True]


@pytest.mark.parametrize("rate", [float("nan"), float("inf")], ids=["nan", "inf"])
def test_review_r4_a_non_finite_rate_per_host_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], rate: float
) -> None:
    """Review T20-2 r4 C1/B1: owner_request_problem refuses a NaN or infinite rate.

    rovo.allium 415 to 433 asks for a positive rate, and rate_per_host is a Decimal
    (crawl.allium 117 to 121), which holds neither NaN nor infinity. NaN fails every
    comparison, so a `rate <= 0` check let it through to the limiter; an infinite rate
    would space requests by zero, turning the rate control off with no explicit
    selection (crawl.allium 112 to 114). Either is refused like a zero rate: exit 2, the
    refusal naming rate_per_host, no request and no run row.
    """
    out_dir = ready(tmp_path / "out", hosts=frozenset({HOST, OTHER_HOST}))
    options = owner_options(rate_per_host=rate)
    before = runs(out_dir)
    capsys.readouterr()
    fetcher = disallowing()
    assert owner_sync(out_dir, fetcher, options) is REFUSED_EXIT
    assert fetcher.requests == []
    assert runs(out_dir) == before
    data = refused_owner(out_dir, options)
    assert "rate_per_host" in str(data["refusal_reason"]), data["refusal_reason"]
    warned(capsys.readouterr().err, options.hosts & OWNED)


def test_review_r4_a_redirected_subrequests_retry_after_follows_the_answering_hosts_policy(
    tmp_path: Path,
) -> None:
    """Review T20-2 r4 B2: item 15 reads the answering host's own honor_retry_after.

    AttemptTier guidance (crawl.allium 1745 to 1755, spec 53687d9, item 15). B, the
    answering host, is selected and its owner policy ignores Retry-After; A, the host the
    subrequest was sent to, honours it under the standard policy. A's style sheet
    redirects to B's, which answers 429 with a Retry-After under the cap: nobody is
    paused, since B's policy decides and A never stands in for an open B.
    """
    run, frontier, a, b = two_hosts(tmp_path, policy=IGNORING, owned=frozenset({OTHER_HOST}))
    assert not b.request_policy.honor_retry_after
    assert a.request_policy.honor_retry_after
    walk = walking(run, frontier)
    rendered_with_subrequest(walk, answered(MOVED_STYLE, TOO_MANY, retry_after=UNDER_CAP))
    assert run.backoffs == []
    assert b.paused_until is None
    assert a.paused_until is None


def test_review_r4_a_long_owner_run_lineage_is_rebuilt_without_recursion(tmp_path: Path) -> None:
    """Review T20-2 r4 B3: lineage_run rebuilds a chain longer than the recursion limit.

    Only owner runs record a preceding run, so the depth of the rebuild is the length of
    an owner-run chain. runs.json holds a standard baseline (run 1) and more chained owner
    runs than sys.getrecursionlimit(), each preceding the next and sharing the baseline;
    the last is rebuilt with its preceding and baseline runs linked, never raising
    RecursionError.
    """
    mirror = new_mirror(tmp_path)
    last = sys.getrecursionlimit() + 2

    def row(run_id: int) -> dict[str, object]:
        owner = run_id > 1
        return {
            "id": run_id,
            "kind": "update",
            "mode": "owner_testing" if owner else "standard",
            "status": "finished",
            "scope_hash": "scope",
            "dry_run": False,
            "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "2026-01-01T00:00:01+00:00",
            "unresolved_urls": [],
            "targeted": False,
            "baseline_run_id": 1 if owner else None,
            "preceding_run_id": run_id - 1 if owner else None,
            "owned_hosts": [HOST] if owner else [],
        }

    path = tmp_path / ".rovo" / "runs.json"
    rows = [row(run_id) for run_id in range(1, last + 1)]
    path.write_text(json.dumps({"runs": rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run = lineage_run(mirror, last, FixedClock())
    assert run is not None
    assert run.id == last
    assert run.preceding is not None
    assert run.preceding.id == last - 1
    assert run.baseline is not None
    assert run.baseline.id == 1
    assert run.baseline.baseline is None
