"""The browser tier (T19): render reasons, escalation, learned tiers, the climb's settlement.

Each obligation test is named after the id `just plan-spec <module>` emits at 7d01367,
dots and hyphens as underscores, and its docstring quotes the obligation. A
`rule_failure` test makes exactly one `requires` clause false. The rest are the ticket's
hand-written guarantees: the starting tier (FetchEntry guidance), `path_pattern` (T19
Open points item 5's interim), SettleWalk's fallback and its one render escalation per
climbing walk, BrowserRendersContentNeverAnswersBlocks with the browser tier usable,
StopWalkOnTrippedHost's escalation disjunct, a render's bytes, and a TierHint round trip
through frontier.json. Renders go through `FakeEngine` (tests/fakes.py), which answers
every request through the crawl's callback, so the requests a render causes are the
FakeFetcher's. Every count, cap and ratio is read from CONFIG.
"""

import dataclasses
import json
from pathlib import Path

import pytest

from fakes import FakeEngine, FakeFetcher, FixedClock, ScriptedFetcher, html_response
from rovo import _commands
from rovo._convert.model import QualityFlag
from rovo._crawl import model
from rovo._crawl.model import (
    BlockKind,
    BlockVerdict,
    FetchAttempt,
    Frontier,
    FrontierStatus,
    LadderWalk,
    RenderMode,
    RenderReason,
    Run,
    RunStatus,
    SiteResponse,
    TierHint,
    WalkStatus,
    standard_policy,
)
from rovo._crawl.run import (
    CrawlResult,
    begin_crawl,
    convert_fetched,
    discover,
    dispose_fetch,
    drop_stale_observations,
    escalate,
    fetch_entry,
    load_frontier,
    path_pattern,
    prepare_run,
    remember_render_tier,
    render_reason_of,
    run_crawl,
    save_frontier,
    select_batch,
    settle_walk,
    stop_walk_on_tripped_host,
)
from rovo._exit import ExitCode
from rovo._mirror.model import Mirror, Operator, Tier
from spec_values import spec_duration, spec_enum, spec_float, spec_int
from test_commands import set_key
from test_crawl import (
    HOST,
    NOSCRIPT_PAGE,
    PAGE,
    SEED,
    SITE,
    assert_fields,
    attempt_on,
    new_mirror,
    request,
    started,
    walk_with,
)

CRAWL = model.CONFIG
FORBIDDEN = 403
LOGIN_FORM = '<form><input type="text" name="user"><input type="password" name="pw"></form>'
# An SPA shell: an empty application root and almost no text (render reason spa_shell).
SPA_SHELL = (
    "<!doctype html><html><head><title>App</title></head>"
    '<body><div id="root"></div><script src="app.js"></script></body></html>'
)
# The DOM a render of the shell gives: a main element, a heading and enough prose.
RENDERED = PAGE.replace("Getting started", "Rendered guide")
# A page with no main or article element (render reason main_selector_absent).
NO_MAIN = PAGE.replace("<main>", "<div>").replace("</main>", "</div>")
STYLE = f"{SITE}/guide/style.css"
# Thin text on a page over large_raw_html bytes, inside a main (render reason thin_text).
THIN_LARGE = (
    "<html><body><main><p>Thin.</p></main>" + " " * CRAWL.large_raw_html + "</body></html>"
)
LATER_RUN = 7


def spa_site(page: str = SPA_SHELL) -> FakeFetcher:
    """The fixture site whose seed answers `page` at http; robots.txt absent."""
    return FakeFetcher({SEED: html_response(SEED, page)})


def crawling(
    out_dir: Path, fetcher: FakeFetcher, *, render_mode: RenderMode = RenderMode.auto
) -> tuple[Run, Frontier]:
    """A run under `render_mode` through discovery, its seed host open."""
    run, frontier = started(out_dir, render_mode=render_mode)
    assert prepare_run(run, frontier)
    assert discover(run, frontier, fetcher)
    assert drop_stale_observations(run, frontier)
    assert begin_crawl(run)
    return run, frontier


def walked(
    out_dir: Path,
    fetcher: FakeFetcher,
    engine: FakeEngine,
    *,
    render_mode: RenderMode = RenderMode.auto,
) -> tuple[Run, Frontier, LadderWalk]:
    """The seed's walk after FetchEntry and its first AttemptTier, with `engine`."""
    run, frontier = crawling(out_dir, fetcher, render_mode=render_mode)
    batch = select_batch(run, frontier)
    assert batch is not None
    (entry,) = batch
    walk = fetch_entry(run, entry, fetcher, engine)
    assert walk is not None
    return run, frontier, walk


def spa_attempt(
    out_dir: Path, fetcher: FakeFetcher, *, tiers: tuple[Tier, ...] = (Tier.http, Tier.browser)
) -> FetchAttempt:
    """A walking walk over `tiers` whose one http attempt answered the SPA shell."""
    run, frontier = crawling(out_dir, fetcher)
    attempt = walk_with(run, frontier, tiers, html_response(SEED, SPA_SHELL))
    assert attempt.render_reason is RenderReason.spa_shell
    assert attempt.wants_escalation
    return attempt


def climbed(
    out_dir: Path, *, first: str = SPA_SHELL, render: str | None = RENDERED, run_id: int = 1
) -> tuple[Run, Frontier, LadderWalk]:
    """A settled walk that escalated: its http attempt answered `first`, its render `render`.

    Constructed attempt by attempt, so RememberRenderTier is tried on its own: the
    browser attempt answers the rendered DOM (status 0 with an error when `render` is
    None, a render that failed outright) and stands.
    """
    run, frontier = started(out_dir, render_mode=RenderMode.auto, run_id=run_id)
    assert prepare_run(run, frontier)
    assert discover(run, frontier, spa_site(first))
    attempt = walk_with(run, frontier, (Tier.http, Tier.browser), html_response(SEED, first))
    walk = attempt.walk
    answer = (
        html_response(SEED, render)
        if render is not None
        else SiteResponse(status=0, source_url=SEED, markup="", size=0, error="render failed")
    )
    rendered = attempt_on(walk, answer, tier=Tier.browser)
    walk.escalated = True
    walk.status = WalkStatus.settled
    walk.standing = rendered
    return run, frontier, walk


def wants_escalation(attempt: FetchAttempt) -> bool:
    """The attempt's wants_escalation, read afresh."""
    return attempt.wants_escalation


def hint_for(frontier: Frontier, identity: str = SEED) -> TierHint | None:
    """The frontier's TierHint for the identity's host and path pattern."""
    pattern = path_pattern(identity)
    return next(
        (h for h in frontier.tier_hints if h.host_name == HOST and h.path_pattern == pattern),
        None,
    )


def crawl_auto(  # noqa: PLR0913  The run's seams and the request fields a test varies.
    out_dir: Path,
    fetcher: FakeFetcher,
    engine: FakeEngine,
    *,
    render_mode: RenderMode = RenderMode.auto,
    run_id: int = 1,
    mirror: Mirror | None = None,
) -> CrawlResult:
    """One whole standard run under `render_mode` with `engine`, saved."""
    target = mirror or new_mirror(out_dir)
    return run_crawl(
        request(target, render_mode=render_mode, run_id=run_id),
        load_frontier(target),
        fetcher,
        FixedClock(),
        engine=engine,
    )


def stored_page_tier(result: CrawlResult, identity: str = SEED) -> Tier:
    """The tier of the run's stored page for `identity`."""
    (page,) = [page for page in result.run.target.pages if page.identity == identity]
    return page.tier


# --- Enums, fields and derived values ----------------------------------------------------


def test_enum_comparable_RenderReason() -> None:
    """Verify fields typed with enum RenderReason are comparable.

    The enum's values are the specification's, in order; each recogniser of
    render_reason_of gives its own member, and an ordinary page none.
    """
    assert tuple(reason.value for reason in RenderReason) == spec_enum("crawl", "RenderReason")
    reasons = [
        render_reason_of(html_response(SEED, SPA_SHELL)),
        render_reason_of(html_response(SEED, NOSCRIPT_PAGE)),
        render_reason_of(html_response(SEED, NO_MAIN)),
        render_reason_of(html_response(SEED, THIN_LARGE)),
    ]
    assert reasons == list(RenderReason)
    assert render_reason_of(html_response(SEED, PAGE)) is None
    assert reasons[0] != RenderReason.noscript_needs_js


def test_enum_comparable_RenderMode(tmp_path: Path) -> None:
    """Verify fields typed with enum RenderMode are comparable.

    The enum's values are the specification's; a run's render_mode is the one it was
    requested with, and only never keeps the browser out of its usable tiers.
    """
    assert tuple(mode.value for mode in RenderMode) == spec_enum("crawl", "RenderMode")
    tiers = {}
    for mode in RenderMode:
        run, _ = started(tmp_path / mode.value, render_mode=mode)
        assert run.render_mode is mode
        assert run.render_mode == mode
        tiers[mode] = run.usable_tiers
    assert tiers[RenderMode.never] == (Tier.http,)
    assert tiers[RenderMode.auto] == tiers[RenderMode.always] == (Tier.http, Tier.browser)


def test_enum_comparable_Tier(tmp_path: Path) -> None:
    """Verify fields typed with enum Tier are comparable (mirror.allium).

    The enum's values are the specification's; a page stored from a render has tier
    browser, which compares unequal to http.
    """
    assert tuple(tier.value for tier in Tier) == spec_enum("mirror", "Tier")
    engine = FakeEngine({SEED: RENDERED})
    result = crawl_auto(tmp_path, spa_site(), engine)
    tiers = [stored_page_tier(result), Tier.http]
    assert tiers[0] == Tier.browser
    assert tiers[0] != tiers[1]


def test_entity_fields_TierHint(tmp_path: Path) -> None:
    """Verify all declared fields on TierHint are present with correct types.

    frontier, host_name, path_pattern, tier and learned_in_run, and reprobe_due(run_id),
    which holds once config.reprobe_every_syncs runs have passed since it was learned.
    """
    _, frontier = started(tmp_path)
    hint = TierHint(
        frontier=frontier,
        host_name=HOST,
        path_pattern="/guide/start.html",
        tier=Tier.browser,
        learned_in_run=1,
    )
    assert_fields(hint, ("frontier", "host_name", "path_pattern", "tier", "learned_in_run"))
    assert hint.frontier is frontier
    assert isinstance(hint.host_name, str)
    assert isinstance(hint.path_pattern, str)
    assert isinstance(hint.tier, Tier)
    assert isinstance(hint.learned_in_run, int)
    due = 1 + CRAWL.reprobe_every_syncs
    assert hint.reprobe_due(due)
    assert not hint.reprobe_due(due - 1)


def test_projection_LadderWalk_ok_http(tmp_path: Path) -> None:
    """Verify projection LadderWalk.ok_http filters correctly.

    After a climb, the walk's ok render is not listed: only its ok, unblocked http
    attempt is; a blocked http attempt is not.
    """
    fetcher = spa_site()
    engine = FakeEngine({SEED: RENDERED})
    _, _, walk = walked(tmp_path, fetcher, engine)
    (http,) = walk.attempts
    rendered = escalate(http, fetcher, engine)
    assert rendered is not None
    assert rendered.response.ok
    assert walk.ok_http == [http]
    http.verdict = BlockVerdict(kind=BlockKind.hard, signature="403 Forbidden")
    assert walk.ok_http == []


def test_derived_LadderWalk_render_needed(tmp_path: Path) -> None:
    """Verify derived value LadderWalk.render_needed computes correctly.

    A walk whose standing attempt has a render reason needs rendering: the http answer
    under render_mode = never, or the http answer a failed render fell back to; a walk
    whose render stands does not.
    """
    fetcher = spa_site()
    never = FakeEngine()
    _, _, unrendered = walked(tmp_path / "never", fetcher, never, render_mode=RenderMode.never)
    assert settle_walk(unrendered.attempts[0])
    assert unrendered.render_needed
    engine = FakeEngine({SEED: RENDERED})
    climbing = spa_site()
    _, _, walk = walked(tmp_path / "auto", climbing, engine)
    rendered = escalate(walk.attempts[0], climbing, engine)
    assert rendered is not None
    assert settle_walk(rendered)
    assert walk.standing is rendered
    assert not walk.render_needed
    failing = FakeEngine({SEED: None})
    falling = spa_site()
    _, _, fallen = walked(tmp_path / "failed", falling, failing)
    failed = escalate(fallen.attempts[0], falling, failing)
    assert failed is not None
    assert settle_walk(failed)
    assert fallen.standing is fallen.attempts[0]
    assert fallen.render_needed


def test_entity_optional_FetchAttempt_render_reason(tmp_path: Path) -> None:
    """Verify optional field FetchAttempt.render_reason accepts null and non-null values.

    An unblocked http answer that needs a browser carries its reason; the render's
    attempt never has one; an http answer that needs none has none.
    """
    fetcher = spa_site()
    engine = FakeEngine({SEED: RENDERED})
    _, _, walk = walked(tmp_path / "spa", fetcher, engine)
    (http,) = walk.attempts
    assert http.render_reason is RenderReason.spa_shell
    rendered = escalate(http, fetcher, engine)
    assert rendered is not None
    assert rendered.tier is Tier.browser
    assert rendered.render_reason is None
    _, _, plain = walked(tmp_path / "plain", spa_site(PAGE), FakeEngine())
    assert plain.attempts[0].render_reason is None


def test_derived_FetchAttempt_wants_escalation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify derived value FetchAttempt.wants_escalation computes correctly.

    An http answer with a render reason, verdict none, ok HTML and no 304 wants it; an
    answer with no reason and no verdict does not; a verdict other than none only under
    protection_escalation (constructed: owner testing is T20's); not for an ok non-HTML
    answer, a 304, or an unsuccessful challenge (constructed); never for an ok render.
    """
    attempt = spa_attempt(tmp_path / "constructed", spa_site())
    walk = attempt.walk
    run = walk.host.run
    assert attempt.wants_escalation
    plain = attempt_on(walk, html_response(SEED, PAGE))
    assert not plain.wants_escalation
    blocked = attempt_on(walk, html_response(SEED, "", status=FORBIDDEN))
    blocked.verdict = BlockVerdict(kind=BlockKind.hard, signature="403 Forbidden")
    standard = blocked.wants_escalation
    run.policy = dataclasses.replace(standard_policy(), protection_escalation=True)
    assert (standard, blocked.wants_escalation) == (False, True)
    run.policy = standard_policy()
    non_html = SiteResponse(
        status=200, source_url=SEED, markup="%PDF", size=4, content_type="application/pdf"
    )
    pdf = attempt_on(walk, non_html)
    pdf.render_reason = RenderReason.spa_shell
    assert not pdf.wants_escalation
    unchanged = attempt_on(walk, html_response(SEED, "", status=304))
    unchanged.render_reason = RenderReason.spa_shell
    assert not unchanged.wants_escalation
    with monkeypatch.context() as patched:
        patched.setattr(FetchAttempt, "unsuccessful_challenge", property(lambda _: True))
        challenged = wants_escalation(attempt)
    assert not challenged
    fetcher = spa_site()
    engine = FakeEngine({SEED: RENDERED})
    _, _, climbing = walked(tmp_path / "climbing", fetcher, engine)
    rendered = escalate(climbing.attempts[0], fetcher, engine)
    assert rendered is not None
    assert rendered.response.ok
    assert not rendered.wants_escalation


def test_config_default_render_min_text_chars() -> None:
    """Verify config parameter render_min_text_chars has its declared default."""
    assert CRAWL.render_min_text_chars == spec_int("crawl", "render_min_text_chars")


def test_config_default_render_max_wait() -> None:
    """Verify config parameter render_max_wait has its declared default."""
    assert CRAWL.render_max_wait == spec_duration("crawl", "render_max_wait")


def test_config_default_large_raw_html() -> None:
    """Verify config parameter large_raw_html has its declared default."""
    assert CRAWL.large_raw_html == spec_int("crawl", "large_raw_html")


def test_config_default_reprobe_every_syncs() -> None:
    """Verify config parameter reprobe_every_syncs has its declared default."""
    assert CRAWL.reprobe_every_syncs == spec_int("crawl", "reprobe_every_syncs")


def test_config_default_soft_render_gain() -> None:
    """Verify config parameter soft_render_gain has its declared default."""
    assert CRAWL.soft_render_gain == spec_float("crawl", "soft_render_gain")


# --- Escalate ------------------------------------------------------------------------------


def test_rule_success_Escalate(tmp_path: Path) -> None:
    """Verify rule Escalate succeeds when all preconditions are met.

    An ok http answer with a render reason, on a walking walk whose tiers go on to the
    browser: the walk is escalated and the browser tier is requested, try 1. The render's
    navigation is made through the crawl (the fetcher's second request for the seed, with
    no validators), and its attempt answers the rendered DOM.
    """
    fetcher = spa_site()
    engine = FakeEngine({SEED: RENDERED})
    _, _, walk = walked(tmp_path, fetcher, engine)
    (http,) = walk.attempts
    rendered = escalate(http, fetcher, engine)
    assert rendered is not None
    assert walk.escalated
    assert walk.status is WalkStatus.walking
    assert walk.attempts == [http, rendered]
    assert (rendered.tier, rendered.try_) == (Tier.browser, 1)
    assert rendered.response.ok
    assert "Rendered guide" in rendered.response.markup
    assert engine.renders == [SEED]
    assert fetcher.requests.count(SEED) == len(["http", "render"])
    assert fetcher.validators[-1] is None


@pytest.mark.parametrize("broken", ["settled", "run-ended", "host-tripped"])
def test_rule_failure_Escalate_1(tmp_path: Path, broken: str) -> None:
    """Verify rule Escalate is rejected when requires clause fails.

    requires: walk.status = walking and walk.host.run.status = running and not
    walk.host.breaker_tripped: the walk settled, the run ended, and the host tripped,
    each alone. No render, no request, the walk not escalated.
    """
    fetcher = spa_site()
    engine = FakeEngine({SEED: RENDERED})
    attempt = spa_attempt(tmp_path, fetcher)
    walk = attempt.walk
    if broken == "settled":
        walk.status = WalkStatus.settled
    elif broken == "run-ended":
        walk.host.run.status = RunStatus.finished
    else:
        assert walk.host.breaker is not None
        walk.host.breaker.status = model.BreakerStatus.tripped
    requests = list(fetcher.requests)
    assert escalate(attempt, fetcher, engine) is None
    assert not walk.escalated
    assert walk.attempts == [attempt]
    assert engine.renders == []
    assert fetcher.requests == requests


def test_rule_failure_Escalate_2(tmp_path: Path) -> None:
    """Verify rule Escalate is rejected when requires clause fails.

    requires: not attempt.retryable and not attempt.retires_host: a retryable http
    answer (a 503 on try 1, constructed with a render reason so that it still wants
    escalation) is retried, not escalated.
    """
    fetcher = spa_site()
    engine = FakeEngine({SEED: RENDERED})
    attempt = spa_attempt(tmp_path, fetcher)
    walk = attempt.walk
    busy = attempt_on(walk, html_response(SEED, SPA_SHELL, status=503))
    busy.render_reason = RenderReason.spa_shell
    assert busy.retryable
    assert busy.wants_escalation
    assert escalate(busy, fetcher, engine) is None
    assert not walk.escalated
    assert engine.renders == []


def test_rule_failure_Escalate_3(tmp_path: Path) -> None:
    """Verify rule Escalate is rejected when requires clause fails.

    requires: attempt.wants_escalation: an ok page with no render reason and no verdict.
    """
    fetcher = spa_site(PAGE)
    engine = FakeEngine()
    run, frontier = crawling(tmp_path, fetcher)
    attempt = walk_with(run, frontier, (Tier.http, Tier.browser), html_response(SEED, PAGE))
    assert not attempt.wants_escalation
    assert escalate(attempt, fetcher, engine) is None
    assert not attempt.walk.escalated
    assert engine.renders == []


def test_rule_failure_Escalate_4(tmp_path: Path) -> None:
    """Verify rule Escalate is rejected when requires clause fails.

    requires: next_tier(walk.tiers, attempt.tier) != null: a walk whose tiers are http
    alone (render_mode = never) has nowhere to climb.
    """
    fetcher = spa_site()
    engine = FakeEngine({SEED: RENDERED})
    attempt = spa_attempt(tmp_path, fetcher, tiers=(Tier.http,))
    assert escalate(attempt, fetcher, engine) is None
    assert not attempt.walk.escalated
    assert engine.renders == []


def test_rule_failure_Escalate_5(tmp_path: Path) -> None:
    """Verify rule Escalate is rejected when requires clause fails.

    requires: not render_added_nothing(walk.soft_suspect, attempt), on a constructed
    walk (a soft verdict wants escalation only under owner testing): an earlier attempt
    was soft-suspected, and this ok attempt's main text is under soft_render_gain times
    that one's, so the suspected copy would stand.
    """
    fetcher = spa_site()
    engine = FakeEngine({SEED: RENDERED})
    attempt = spa_attempt(tmp_path, fetcher)
    walk = attempt.walk
    suspect_text = 100
    attempt.verdict = BlockVerdict(kind=BlockKind.soft, signature="thin text")
    attempt.render_reason = None
    attempt.response = dataclasses.replace(html_response(SEED, PAGE), main_text=suspect_text)
    assert walk.soft_suspect == [attempt]
    again = attempt_on(walk, html_response(SEED, SPA_SHELL), try_=2)
    again.render_reason = RenderReason.spa_shell
    gained = int(suspect_text * CRAWL.soft_render_gain) - 1
    again.response = dataclasses.replace(html_response(SEED, SPA_SHELL), main_text=gained)
    assert again.wants_escalation
    assert not again.retryable
    assert escalate(again, fetcher, engine) is None
    assert not walk.escalated
    assert engine.renders == []


# --- RememberRenderTier ----------------------------------------------------------------------


def test_rule_success_RememberRenderTier(tmp_path: Path) -> None:
    """Verify rule RememberRenderTier succeeds when all preconditions are met.

    A settled walk that escalated, whose ok, unblocked render stands and whose first
    render reason is spa_shell: a TierHint is created for the host and the path pattern,
    its tier the standing tier and learned_in_run the run's id. A later run's walk on
    the same pattern, its first reason noscript_needs_js, updates that hint rather than
    adding one.
    """
    run, frontier, walk = climbed(tmp_path / "first")
    hint = remember_render_tier(walk)
    assert hint is not None
    assert frontier.tier_hints == [hint]
    assert hint.frontier is frontier
    assert (hint.host_name, hint.path_pattern) == (HOST, path_pattern(SEED))
    assert (hint.tier, hint.learned_in_run) == (Tier.browser, run.id)
    later, later_frontier, later_walk = climbed(
        tmp_path / "later", first=NOSCRIPT_PAGE, run_id=LATER_RUN
    )
    existing = TierHint(
        frontier=later_frontier,
        host_name=HOST,
        path_pattern=path_pattern(SEED),
        tier=Tier.browser,
        learned_in_run=1,
    )
    later_frontier.tier_hints.append(existing)
    updated = remember_render_tier(later_walk)
    assert updated is existing
    assert later_frontier.tier_hints == [existing]
    assert (existing.tier, existing.learned_in_run) == (Tier.browser, later.id)


def test_rule_failure_RememberRenderTier_1(tmp_path: Path) -> None:
    """Verify rule RememberRenderTier is rejected when requires clause fails.

    requires: walk.status = settled: a walk still walking teaches nothing.
    """
    _, frontier, walk = climbed(tmp_path)
    walk.status = WalkStatus.walking
    assert remember_render_tier(walk) is None
    assert frontier.tier_hints == []


def test_rule_failure_RememberRenderTier_2(tmp_path: Path) -> None:
    """Verify rule RememberRenderTier is rejected when requires clause fails.

    requires: walk.escalated and walk.standing.tier != http: a walk that started at the
    browser (render_mode = always) never escalated, and a failed render that fell back
    to its http answer stands at http.
    """
    _, frontier, started_there = climbed(tmp_path / "always")
    started_there.escalated = False
    assert remember_render_tier(started_there) is None
    assert frontier.tier_hints == []
    _, fallen_frontier, fallen = climbed(tmp_path / "fallen")
    fallen.standing = fallen.attempts[0]
    assert fallen.standing.tier is Tier.http
    assert remember_render_tier(fallen) is None
    assert fallen_frontier.tier_hints == []


def test_rule_failure_RememberRenderTier_3(tmp_path: Path) -> None:
    """Verify rule RememberRenderTier is rejected when requires clause fails.

    requires: walk.standing.response.ok and walk.standing.verdict.kind = none: a render
    that stands blocked (a 403 at its navigation), and one that failed outright with no
    http answer to fall back to.
    """
    _, frontier, walk = climbed(tmp_path / "blocked")
    assert walk.standing is not None
    walk.standing.response = html_response(SEED, "", status=FORBIDDEN)
    walk.standing.verdict = BlockVerdict(kind=BlockKind.hard, signature="403 Forbidden")
    assert remember_render_tier(walk) is None
    assert frontier.tier_hints == []
    _, failed_frontier, failed = climbed(tmp_path / "failed", render=None)
    assert remember_render_tier(failed) is None
    assert failed_frontier.tier_hints == []


@pytest.mark.parametrize(
    "first",
    [pytest.param(NO_MAIN, id="main_selector_absent"), pytest.param("thin", id="thin_text")],
)
def test_rule_failure_RememberRenderTier_4(tmp_path: Path, first: str) -> None:
    """Verify rule RememberRenderTier is rejected when requires clause fails.

    requires: first_render_reason(walk.attempts) in {spa_shell, noscript_needs_js}: a
    walk that climbed for main_selector_absent or thin_text renders but learns nothing.
    """
    page = THIN_LARGE if first == "thin" else first
    _, frontier, walk = climbed(tmp_path, first=page)
    assert walk.attempts[0].render_reason in {
        RenderReason.main_selector_absent,
        RenderReason.thin_text,
    }
    assert remember_render_tier(walk) is None
    assert frontier.tier_hints == []


# --- LearnedTierIsNeverHttp ------------------------------------------------------------------


def test_invariant_LearnedTierIsNeverHttp(tmp_path: Path) -> None:
    """Verify invariant LearnedTierIsNeverHttp holds after every state-changing rule.

    After RememberRenderTier creates and updates a hint, after a whole run that learns
    one and after a failed render that falls back to http (which learns none), and after
    a frontier.json round trip: no TierHint's tier is http.
    """
    _, frontier, walk = climbed(tmp_path / "unit")
    assert remember_render_tier(walk) is not None
    assert remember_render_tier(walk) is not None
    assert all(h.tier is not Tier.http for h in frontier.tier_hints)
    result = crawl_auto(tmp_path / "run", spa_site(), FakeEngine({SEED: RENDERED}))
    assert result.frontier.tier_hints
    assert all(h.tier is not Tier.http for h in result.frontier.tier_hints)
    fallen = crawl_auto(tmp_path / "fallen", spa_site(), FakeEngine({SEED: None}))
    assert fallen.frontier.tier_hints == []
    reloaded = load_frontier(result.run.target)
    assert reloaded is not None
    assert reloaded.tier_hints
    assert all(h.tier is not Tier.http for h in reloaded.tier_hints)


# --- SyncControl -------------------------------------------------------------------------------


def test_surface_actor_SyncControl(tmp_path: Path) -> None:
    """Verify surface SyncControl is accessible only to the specified actor.

    The operator's sync raises RunRequested through SyncControl: the run's operator is
    the request's, and a run the root started under render_mode = auto renders through
    the one engine the root opened for it, closed when the run ends.
    """
    operator = Operator()
    mirror = new_mirror(tmp_path / "unit")
    engine = FakeEngine({SEED: RENDERED})
    run_request = dataclasses.replace(
        request(mirror, render_mode=RenderMode.auto), operator=operator
    )
    result = run_crawl(run_request, None, spa_site(), FixedClock(), engine=engine)
    assert result.run.operator is operator
    assert engine.renders == [SEED]
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    set_key(out_dir, "render_mode", '"auto"')
    opened: list[FakeEngine] = []

    def open_engine() -> FakeEngine:
        opened.append(FakeEngine({SEED: RENDERED}))
        return opened[-1]

    code = _commands.sync(
        out_dir,
        fetcher=spa_site(),
        clock=FixedClock(),
        tier_installed=lambda tier: tier is Tier.browser,
        engine=open_engine,
    )
    assert code is ExitCode.ok
    assert len(opened) == 1
    assert opened[0].renders == [SEED]
    assert opened[0].closed


def test_surface_provides_SyncControl(tmp_path: Path) -> None:
    """Verify provided operations on SyncControl appear/hide based on when conditions.

    RunRequested is raised only once every refusal has been checked: a configured
    browser tier with no engine installed raises none (no run, no request, no engine;
    EnginesRefusedBeforeRequests), and an installed one raises it with the
    configuration's render_mode, which reaches the run.
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    set_key(out_dir, "render_mode", '"always"')
    opened: list[FakeEngine] = []

    def open_engine() -> FakeEngine:
        opened.append(FakeEngine())
        return opened[-1]

    fetcher = spa_site(PAGE)
    refused = _commands.sync(
        out_dir,
        fetcher=fetcher,
        clock=FixedClock(),
        tier_installed=lambda tier: tier is Tier.http,
        engine=open_engine,
    )
    assert refused is ExitCode.usage
    assert fetcher.requests == []
    assert opened == []
    assert not (out_dir / ".rovo" / "runs.json").exists()
    code = _commands.sync(
        out_dir,
        fetcher=fetcher,
        clock=FixedClock(),
        tier_installed=lambda tier: tier is Tier.browser,
        engine=open_engine,
    )
    assert code is ExitCode.ok
    (engine,) = opened
    assert engine.renders == [SEED]
    runs = json.loads((out_dir / ".rovo" / "runs.json").read_text(encoding="utf-8"))["runs"]
    assert [row["id"] for row in runs] == [1]


# --- Guarantees: the starting tier ---------------------------------------------------------


def test_render_mode_always_starts_every_walk_at_the_browser(tmp_path: Path) -> None:
    """FetchEntry guidance: under render_mode = always the walk starts at the browser.

    It has no http attempt, its render's navigation sends no validators, and it never
    counts a render escalation.
    """
    fetcher = spa_site(PAGE)
    engine = FakeEngine()
    _, _, walk = walked(tmp_path, fetcher, engine, render_mode=RenderMode.always)
    (first,) = walk.attempts
    assert first.tier is Tier.browser
    assert walk.tiers == (Tier.browser,)
    assert engine.renders == [SEED]
    assert fetcher.validators[-1] is None
    assert settle_walk(first)
    assert walk.host.render_escalations == 0
    assert walk.host.tiers_used == frozenset({Tier.browser})


def learned(frontier: Frontier, learned_in_run: int) -> TierHint:
    """A browser TierHint for the seed's pattern, learned in `learned_in_run`, kept."""
    hint = TierHint(
        frontier=frontier,
        host_name=HOST,
        path_pattern=path_pattern(SEED),
        tier=Tier.browser,
        learned_in_run=learned_in_run,
    )
    frontier.tier_hints.append(hint)
    return hint


def test_a_learned_tier_starts_the_walk_at_the_browser(tmp_path: Path) -> None:
    """FetchEntry guidance: a hint not yet reprobe_due starts the walk at its tier.

    The seed is rendered with no http try before it; a breaker tier is ignored outside
    owner testing (a standard run's breaker never raises it, so it is set by hand).
    """
    run_id = CRAWL.reprobe_every_syncs
    mirror = new_mirror(tmp_path)
    frontier = Frontier(mirror=mirror)
    learned(frontier, run_id - CRAWL.reprobe_every_syncs + 1)
    save_frontier(frontier)
    fetcher = spa_site()
    engine = FakeEngine({SEED: RENDERED})
    result = crawl_auto(tmp_path, fetcher, engine, run_id=run_id, mirror=mirror)
    assert engine.renders == [SEED]
    assert fetcher.requests.count(SEED) == 1
    assert stored_page_tier(result) is Tier.browser
    assert result.run.hosts[0].render_escalations == 0


def test_a_breaker_tier_is_ignored_outside_owner_testing(tmp_path: Path) -> None:
    """FetchEntry guidance: outside owner testing starting_tier ignores a breaker tier."""
    fetcher = spa_site(PAGE)
    engine = FakeEngine()
    run, frontier = crawling(tmp_path, fetcher)
    host = run.host(HOST)
    assert host is not None
    assert host.breaker is not None
    host.breaker.tier = Tier.browser
    batch = select_batch(run, frontier)
    assert batch is not None
    (entry,) = batch
    walk = fetch_entry(run, entry, fetcher, engine)
    assert walk is not None
    assert walk.attempts[0].tier is Tier.http
    assert engine.renders == []


def test_a_reprobe_due_hint_probes_http_and_a_reprobe_that_does_not_climb_keeps_it(
    tmp_path: Path,
) -> None:
    """FetchEntry guidance: once reprobe_due(run.id), the walk probes http again.

    A reprobe whose http answer needs no render leaves the hint as it was (no rule
    deletes one), so the next run probes http again; a reprobe that escalates again
    renews learned_in_run.
    """
    run_id = 1 + CRAWL.reprobe_every_syncs
    mirror = new_mirror(tmp_path)
    frontier = Frontier(mirror=mirror)
    learned(frontier, 1)
    save_frontier(frontier)
    plain = spa_site(PAGE)
    engine = FakeEngine()
    result = crawl_auto(tmp_path, plain, engine, run_id=run_id, mirror=mirror)
    assert engine.renders == []
    assert stored_page_tier(result) is Tier.http
    (kept,) = result.frontier.tier_hints
    assert (kept.tier, kept.learned_in_run) == (Tier.browser, 1)
    again = FakeEngine({SEED: RENDERED})
    renewed = crawl_auto(tmp_path, spa_site(), again, run_id=run_id + 1, mirror=mirror)
    assert again.renders == [SEED]
    (hint,) = renewed.frontier.tier_hints
    assert (hint.tier, hint.learned_in_run) == (Tier.browser, run_id + 1)


@pytest.mark.parametrize(
    ("identity", "pattern"),
    [
        pytest.param(f"{SITE}/guide/app.html", "/guide/app.html", id="two-segments"),
        pytest.param(f"{SITE}/a/b/c.html", "/a/b", id="three-segments"),
        pytest.param(f"{SITE}/a/b/c/d/", "/a/b", id="four-segments"),
        pytest.param(f"{SITE}/", "/", id="root"),
        pytest.param(f"{SITE}/a.html", "/a.html", id="one-segment"),
        pytest.param(f"{SITE}/a/b/c.html?tab=x", "/a/b", id="query"),
    ],
)
def test_path_pattern_keeps_the_first_two_segments(identity: str, pattern: str) -> None:
    """T19 Open points item 5's interim: the identity's path cut to two segments."""
    assert path_pattern(identity) == pattern


# --- Guarantees: SettleWalk across tiers -------------------------------------------------------


def test_an_ok_render_stands_with_tier_browser_and_counts_one_escalation(
    tmp_path: Path,
) -> None:
    """SettleWalk: the ok render stands, tiers_used gains browser alone, one escalation.

    The page is stored with tier browser and no render_needed flag, and the hint learned.
    """
    engine = FakeEngine({SEED: RENDERED})
    result = crawl_auto(tmp_path, spa_site(), engine)
    host = result.run.hosts[0]
    assert host.render_escalations == 1
    assert host.tiers_used == frozenset({Tier.browser})
    (page,) = result.run.target.pages
    assert page.tier is Tier.browser
    assert QualityFlag.render_needed not in page.flags
    assert result.frontier.entry(SEED) is not None
    assert hint_for(result.frontier) is not None


def test_a_render_that_failed_outright_falls_back_to_the_http_answer(tmp_path: Path) -> None:
    """SettleWalk: a browser attempt that failed outright stands latest(walk.ok_http).

    The page is stored from its http answer with tier http, flagged render_needed and
    low confidence; the walk still counts its render escalation; no tier is learned.
    """
    engine = FakeEngine({SEED: None})
    result = crawl_auto(tmp_path, spa_site(), engine)
    assert engine.renders == [SEED]
    (page,) = result.run.target.pages
    assert page.tier is Tier.http
    assert QualityFlag.render_needed in page.flags
    assert page.low_confidence
    host = result.run.hosts[0]
    assert host.tiers_used == frozenset({Tier.http})
    assert host.render_escalations == 1
    assert result.frontier.tier_hints == []


def test_a_blocked_render_stands_blocked_and_never_falls_back(tmp_path: Path) -> None:
    """SettleWalk: a render whose navigation is answered 403 stands, blocked, at the browser."""
    fetcher = ScriptedFetcher(
        {SEED: html_response(SEED, "", status=FORBIDDEN)},
        {SEED: [html_response(SEED, SPA_SHELL)]},
    )
    engine = FakeEngine()
    result = crawl_auto(tmp_path, fetcher, engine)
    assert engine.renders == [SEED]
    (blocked,) = result.blocked
    assert blocked.tier is Tier.browser
    assert result.frontier.entry(SEED) is not None
    entry = result.frontier.entry(SEED)
    assert entry is not None
    assert entry.status is FrontierStatus.blocked
    assert result.run.target.pages == []
    assert result.frontier.tier_hints == []


def test_converting_a_render_gives_tier_browser(tmp_path: Path) -> None:
    """ConvertFetched over a settled climb: the candidate's tier is browser, unflagged."""
    fetcher = spa_site()
    engine = FakeEngine({SEED: RENDERED})
    run, _, walk = walked(tmp_path, fetcher, engine)
    rendered = escalate(walk.attempts[0], fetcher, engine)
    assert rendered is not None
    assert settle_walk(rendered)
    assert dispose_fetch(walk)
    candidate = convert_fetched(run, walk.entry, walk)
    assert candidate is not None
    assert candidate.tier is Tier.browser
    assert candidate.content is not None
    assert QualityFlag.render_needed not in candidate.content.quality.flags


# --- Guarantees: blocks, tripped hosts and bytes ------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(html_response(SEED, "", status=FORBIDDEN), id="403"),
        pytest.param(
            html_response(SEED, PAGE.replace("</main>", LOGIN_FORM + "</main>")), id="soft"
        ),
    ],
)
def test_BrowserRendersContentNeverAnswersBlocks_with_the_browser_usable(
    tmp_path: Path, answer: SiteResponse
) -> None:
    """SiteExchange BrowserRendersContentNeverAnswersBlocks under render_mode = auto.

    A blocked http answer, hard or soft, never climbs in a standard run: no render.
    """
    engine = FakeEngine({SEED: RENDERED})
    result = crawl_auto(tmp_path, FakeFetcher({SEED: answer}), engine)
    assert engine.renders == []
    assert result.run.hosts[0].render_escalations == 0


def test_a_walk_whose_host_trips_before_its_climb_is_skipped_unrendered(tmp_path: Path) -> None:
    """StopWalkOnTrippedHost's escalation disjunct: no render on a tripped host.

    The walk's http answer wants escalation; its host trips before the climb; Escalate
    does not fire, the engine is never called and the row is skipped_blocked.
    """
    fetcher = spa_site()
    engine = FakeEngine({SEED: RENDERED})
    _, _, walk = walked(tmp_path, fetcher, engine)
    (http,) = walk.attempts
    assert walk.host.breaker is not None
    walk.host.breaker.status = model.BreakerStatus.tripped
    assert escalate(http, fetcher, engine) is None
    skipped = stop_walk_on_tripped_host(http)
    assert skipped is not None
    assert walk.entry.status is FrontierStatus.skipped_blocked
    assert engine.renders == []


def test_a_renders_subrequests_count_toward_the_bytes_fetched(tmp_path: Path) -> None:
    """AttemptTier guidance: every response a render receives counts toward max_bytes.

    The render's size is its navigation's and its stylesheet's; run.bytes_fetched gains
    both on top of the http try's.
    """
    style = "main { max-width: 40em; }"
    fetcher = FakeFetcher(
        {
            SEED: html_response(SEED, SPA_SHELL),
            STYLE: SiteResponse(
                status=200,
                source_url=STYLE,
                markup=style,
                size=len(style.encode()),
                content_type="text/css",
            ),
        }
    )
    engine = FakeEngine({SEED: RENDERED}, subrequests={SEED: [STYLE]})
    run, _, walk = walked(tmp_path, fetcher, engine)
    before = run.bytes_fetched
    rendered = escalate(walk.attempts[0], fetcher, engine)
    assert rendered is not None
    expected = fetcher.responses[SEED].size + fetcher.responses[STYLE].size
    assert rendered.response.size == expected
    assert run.bytes_fetched == before + expected
    assert STYLE in fetcher.requests


# --- Guarantees: frontier.json ---------------------------------------------------------------


def test_tier_hints_round_trip_through_frontier_json_sorted(tmp_path: Path) -> None:
    """Frontier: every learned tier persists in frontier.json, one sorted row per hint.

    Rows are sorted by host name, then pattern, each with host_name, path_pattern, tier
    and learned_in_run; load_frontier reads them back.
    """
    mirror = new_mirror(tmp_path)
    frontier = Frontier(mirror=mirror)
    rows = [("docs.example", "/guide/b"), ("api.example", "/v2/x"), ("docs.example", "/guide/a")]
    for number, (host_name, pattern) in enumerate(rows, 1):
        frontier.tier_hints.append(
            TierHint(
                frontier=frontier,
                host_name=host_name,
                path_pattern=pattern,
                tier=Tier.browser,
                learned_in_run=number,
            )
        )
    save_frontier(frontier)
    data = json.loads((tmp_path / ".rovo" / "frontier.json").read_text(encoding="utf-8"))
    assert [
        (row["host_name"], row["path_pattern"], row["tier"], row["learned_in_run"])
        for row in data["tier_hints"]
    ] == [
        ("api.example", "/v2/x", "browser", 2),
        ("docs.example", "/guide/a", "browser", 3),
        ("docs.example", "/guide/b", "browser", 1),
    ]
    assert all(
        sorted(row) == ["host_name", "learned_in_run", "path_pattern", "tier"]
        for row in data["tier_hints"]
    )
    loaded = load_frontier(mirror)
    assert loaded is not None
    assert sorted(
        (h.host_name, h.path_pattern, h.tier, h.learned_in_run) for h in loaded.tier_hints
    ) == [
        ("api.example", "/v2/x", Tier.browser, 2),
        ("docs.example", "/guide/a", Tier.browser, 3),
        ("docs.example", "/guide/b", Tier.browser, 1),
    ]
    assert all(h.frontier is loaded for h in loaded.tier_hints)


def test_a_climb_in_a_run_saves_its_hint_with_the_runs_id(tmp_path: Path) -> None:
    """RememberRenderTier from a run: frontier.json's tier_hints holds the learned row."""
    result = crawl_auto(tmp_path, spa_site(), FakeEngine({SEED: RENDERED}), run_id=LATER_RUN)
    data = json.loads((tmp_path / ".rovo" / "frontier.json").read_text(encoding="utf-8"))
    assert data["tier_hints"] == [
        {
            "host_name": HOST,
            "learned_in_run": result.run.id,
            "path_pattern": path_pattern(SEED),
            "tier": "browser",
        }
    ]
