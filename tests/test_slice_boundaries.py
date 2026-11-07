"""Where each slice stopped, now realised, and the corners the obligation tests skip.

Each slice's branches a later slice implemented raised NotInThisSlice here; the slice
that implemented a branch replaced its test with one asserting the behaviour, and T20,
the last slice, replaced the last three (owner testing), so no test here expects the
guard any more. The rest covers the black boxes' corners: the render recognisers, path
assignment, the rovo.toml readers and the page file.
"""

import dataclasses
import os
import stat
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

from fakes import FakeEngine, FakeFetcher, FixedClock, html_response, text_response, xml_response
from rovo import _commands
from rovo._config import SyncOptions, resolve_config
from rovo._convert import profiles
from rovo._convert.fidelity import convert, converted_content, extract, measure, normalize, restore
from rovo._convert.model import (
    ConvertedContent,
    ExtractionMethod,
    HeadingAnchorStyle,
    Island,
    QualityFlag,
)
from rovo._crawl.fetch import HttpxFetcher, Validators
from rovo._crawl.model import CONFIG as CRAWL
from rovo._crawl.model import (
    BlockKind,
    BlockVerdict,
    BreakerStatus,
    DiscoveryProblem,
    FrontierStatus,
    RenderMode,
    RenderReason,
    RunKind,
    RunMode,
    RunRequest,
    RunStatus,
    SiteResponse,
    StealthMode,
    standard_policy,
)
from rovo._crawl.run import (
    attempt_tier,
    classify_block,
    create_frontier,
    discover,
    enqueue_page_links,
    fetch_entry,
    load_frontier,
    prepare_run,
    render_reason_of,
    run_crawl,
    select_batch,
    start_run,
)
from rovo._mirror.finalise import finalise, keywords_of
from rovo._mirror.intake import admit_candidate, take_candidate
from rovo._mirror.model import (
    CandidateDelivered,
    CandidateOutcome,
    CandidateStatus,
    CrawlScope,
    LinksFound,
    Mirror,
    Operator,
    PageStatus,
    RemovalReason,
    StoreOutcome,
    Tier,
)
from rovo._mirror.state import ManifestError, load_mirror, manifest_path, save_mirror
from rovo._mirror.urls import assign_path, normalise_url, pattern_matches, version_label
from rovo._report import ExitCode
from test_crawl import MAPS, MAPS_INDEX, PAST_CAP_DELAYS, PAST_CAP_IDS, past_cap, sitemapindex

SITE = "http://docs.example"
HOST = "docs.example"
SEED = f"{SITE}/guide/start.html"
# page_root of the fixture host (mirror.allium MovePage guidance, at fed9ed8).
ROOT = "pages/docs.example/"
START_PATH = f"{ROOT}start.md"
ROBOTS = f"{SITE}/robots.txt"
SITES = Path(__file__).resolve().parent / "fixtures" / "sites"
PAGE = (SITES / "one-page" / "guide" / "start.html").read_text(encoding="utf-8")
DEVSITE_TABS = (SITES / "devsite" / "guide" / "tabs.html").read_text(encoding="utf-8")
FORBIDDEN = 403
SERVER_ERROR = 500
TOO_MANY = 429
SERVICE_UNAVAILABLE = 503


def scope(**changes: object) -> CrawlScope:
    """The fixture site's scope."""
    base = CrawlScope(
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
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]  # Test overrides by name.


def new_mirror(out_dir: Path, **changes: object) -> Mirror:
    """An initialised mirror of the fixture site, its manifest on disk."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mirror = Mirror(
        out_dir=out_dir,
        scope=scope(**changes),
        profile=profiles.GENERIC,
        processing_signature="signature-1",
    )
    save_mirror(mirror)
    return mirror


def request(mirror: Mirror, **changes: object) -> RunRequest:
    """A standard full run's RunRequested."""
    base = RunRequest(
        operator=Operator(),
        mirror=mirror,
        id=1,
        kind=RunKind.initial,
        mode=RunMode.standard,
        scope_hash="scope-1",
        owned_hosts=frozenset(),
        policy=standard_policy(),
        dry_run=False,
        interactive=False,
        render_mode=RenderMode.never,
        stealth_mode=StealthMode.off,
        targets=frozenset(),
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]  # Test overrides by name.


def crawl(out_dir: Path, responses: dict[str, SiteResponse], **changes: object) -> None:
    """One run over a FakeFetcher answering `responses`."""
    mirror = new_mirror(out_dir)
    run_crawl(request(mirror, **changes), None, FakeFetcher(responses), FixedClock())


# --- The guard points of the earlier slices, each now realised --------------------------


@pytest.mark.parametrize(
    ("responses", "status"),
    [
        pytest.param(
            {SEED: html_response(SEED, "", status=FORBIDDEN)},
            FrontierStatus.blocked,
            id="blocked-page",
        ),
        pytest.param(
            {SEED: html_response(SEED, PAGE.replace("</main>", '<input type="password"></main>'))},
            FrontierStatus.done,
            id="login-wall",
        ),
        pytest.param(
            {
                SEED: SiteResponse(
                    status=TOO_MANY,
                    source_url=SEED,
                    markup="",
                    size=0,
                    retry_after=standard_policy().retry_after_cap + timedelta(seconds=1),
                )
            },
            FrontierStatus.blocked,
            id="long-retry-after",
        ),
    ],
)
def test_a_blocked_page_a_login_wall_and_a_long_retry_after_settle(
    tmp_path: Path, responses: dict[str, SiteResponse], status: FrontierStatus
) -> None:
    """A 403, a login wall and a Retry-After past the cap each settle the row (T18).

    Re-propagated by T18 from test_a_later_slices_answer_stops_the_run (T09, re-propagated
    by T12, T15 and T16), whose three remaining cases stopped with NotInThisSlice and saved
    no frontier: the 403 and the long 429 are blocked, the login wall is a soft verdict
    converted and stored, and the run ends with its frontier saved.
    """
    crawl(tmp_path, responses)
    assert (tmp_path / ".rovo" / "frontier.json").exists()
    mirror = load_mirror(tmp_path)
    frontier = load_frontier(mirror)
    assert frontier is not None
    entry = frontier.entry(SEED)
    assert entry is not None
    assert entry.status is status


def test_a_429_that_survives_its_retries_is_blocked(tmp_path: Path) -> None:
    """A page answering 429 on every try is retried, then blocked with a hard verdict (T18).

    Re-propagated by T18 from test_a_429_that_survives_its_retries_stops_at_classify_block
    (T12): after http_attempts tries, the standing 429 is hard (AttemptTier guidance 1606
    to 1611), its row blocked with a UrlBlocked naming status 429, and the frontier saved.
    """
    fetcher = FakeFetcher(
        {SEED: SiteResponse(status=TOO_MANY, source_url=SEED, markup="", size=0)}
    )
    mirror = new_mirror(tmp_path)
    result = run_crawl(request(mirror), None, fetcher, FixedClock())
    assert fetcher.requests.count(SEED) == CRAWL.http_attempts
    assert [(event.url, event.status) for event in result.blocked] == [(SEED, TOO_MANY)]
    entry = result.frontier.entry(SEED)
    assert entry is not None
    assert entry.status is FrontierStatus.blocked
    assert (tmp_path / ".rovo" / "frontier.json").exists()


@pytest.mark.parametrize("written", PAST_CAP_DELAYS, ids=PAST_CAP_IDS)
def test_a_crawl_delay_past_the_cap_retires_the_host(tmp_path: Path, written: str) -> None:
    """An honoured Crawl-delay past retry_after_cap retires the host (spec 71b5b0f, T18).

    Re-propagated by T18 from
    test_a_crawl_delay_past_the_cap_stops_at_retire_host_on_long_crawl_delay (T12):
    RetireHostOnLongCrawlDelay trips the breaker right after robots.txt, however large
    the number: never an overflow, and nothing more is requested (spec 86e2ec5: no
    sitemap, llms.txt or page). The number is read as written, so 1e309 and 1e400 (too
    large for a float), the cap plus one sub-ULP step and an exponent past Decimal's
    limit retire it too (reviews T12-2-r2 C1/B1 and T12-3-r2 C1/B1). The seed is skipped
    and the frontier saved.
    """
    robots = text_response(ROBOTS, f"User-agent: *\nCrawl-delay: {written}\n")
    fetcher = FakeFetcher({ROBOTS: robots, SEED: html_response(SEED, PAGE)})
    mirror = new_mirror(tmp_path)
    result = run_crawl(request(mirror), None, fetcher, FixedClock())
    assert fetcher.requests == [ROBOTS]
    assert result.run.has_tripped_host
    assert [event.url for event in result.skipped] == [SEED]
    assert (tmp_path / ".rovo" / "frontier.json").exists()


def test_a_breaker_breach_trips_the_host(tmp_path: Path) -> None:
    """The moment a host's breaker should act, BreakerTrips trips it (T18).

    Re-propagated by T18 from test_a_breaker_breach_stops_the_run (T12), which expected
    NotInThisSlice("BreakerTrips") and no frontier. Ten seeds, three of which never
    answer: once breaker_min_outcomes walks have settled, the share of failures is past
    block_rate_threshold, so the host trips, BreakerTripped is returned and the frontier
    is saved.
    """
    count = min(CRAWL.breaker_window, CRAWL.breaker_min_outcomes)
    failing = int(count * CRAWL.block_rate_threshold) + 1
    seeds = tuple(f"{SITE}/guide/p{number}.html" for number in range(count))
    responses: dict[str, SiteResponse] = {}
    for number, url in enumerate(seeds):
        if number < failing:
            responses[url] = SiteResponse(
                status=0, source_url=url, markup="", size=0, error="connection refused"
            )
        else:
            prose = f"Page {number} explains setting {number} of the example product in full."
            responses[url] = html_response(
                url,
                PAGE.replace("<h1>Getting started</h1>", f"<h1>Page {number}</h1><p>{prose}</p>"),
            )
    mirror = new_mirror(tmp_path, start_urls=seeds)
    result = run_crawl(request(mirror), None, FakeFetcher(responses), FixedClock())
    host = result.run.host(HOST)
    assert host is not None
    assert host.breaker_tripped
    assert [event.host for event in result.tripped] == [host]
    assert (tmp_path / ".rovo" / "frontier.json").exists()


def test_escalation_to_the_browser_renders_the_page(tmp_path: Path) -> None:
    """Under render_mode = auto a page that needs rendering climbs to the browser tier.

    Re-propagated by T19 from test_escalation_to_the_browser_stops_the_run (T09), which
    expected NotInThisSlice("Escalate"): the noscript page is requested at http, then
    rendered (its navigation the seed's second request), stored with tier browser, and
    the run ends with its frontier saved.
    """
    noscript = PAGE.replace("</main>", "<noscript>Enable JavaScript.</noscript></main>")
    fetcher = FakeFetcher({SEED: html_response(SEED, noscript)})
    engine = FakeEngine({SEED: PAGE})
    mirror = new_mirror(tmp_path)
    result = run_crawl(
        request(mirror, render_mode=RenderMode.auto), None, fetcher, FixedClock(), engine=engine
    )
    assert engine.renders == [SEED]
    assert fetcher.requests.count(SEED) == len(["http try", "render"])
    (page,) = result.run.target.pages
    assert page.tier is Tier.browser
    assert (tmp_path / ".rovo" / "frontier.json").exists()


def test_a_devsite_page_converts(tmp_path: Path) -> None:
    """A run under the devsite profile converts with its selection (T17).

    Re-propagated by T17 from T09's test_a_non_generic_profile_stops_conversion:
    ConvertFetched converts under every profile, so the devsite-shaped page is stored,
    extracted by the profile, its breadcrumbs kept and every tab panel emitted.
    """
    mirror = new_mirror(tmp_path)
    mirror.profile = profiles.DEVSITE
    fetcher = FakeFetcher({SEED: html_response(SEED, DEVSITE_TABS)})
    run_crawl(request(mirror), None, fetcher, FixedClock())
    page = mirror.page(SEED)
    assert page is not None
    assert page.method is ExtractionMethod.profile
    assert page.breadcrumbs == ("Guides", "Tabs")
    assert QualityFlag.tabs_expanded not in page.flags
    for language in ("python", "java", "shell"):
        assert f"```{language}" in page.converted_body, language
    assert "Example developers footer" not in page.converted_body


def test_an_owner_request_without_its_authority_is_a_defect(tmp_path: Path) -> None:
    """StartRun refuses an owner request with no baseline, preceding run or owned host.

    Re-propagated by T20 from test_owner_testing_and_dry_runs_stop (T09), which expected
    NotInThisSlice("StartRun") (T13 realised the dry run): the root refuses such a
    request first, so drive_run meeting one is a defect, a ValueError naming StartRun's
    requires, not a product stop; nothing is requested.
    """
    fetcher = FakeFetcher({SEED: html_response(SEED, PAGE)})
    with pytest.raises(ValueError, match="StartRun"):
        run_crawl(
            request(new_mirror(tmp_path / "owner"), mode=RunMode.owner_testing),
            None,
            fetcher,
            FixedClock(),
        )
    assert fetcher.requests == []


def test_a_sitemap_filter_placeholder_is_filled(tmp_path: Path) -> None:
    """T17 follow-up (spec 022eca4): a run under mslearn's placeholder filter proceeds.

    Re-propagated by T17 from test_a_sitemap_filter_placeholder_stops (T13, re-propagated
    by T15), which asserted NotInThisSlice("sitemap_admitted"): {section} matches as *
    does and {locale} is any of the scope's locale codes, so the well-known sitemaps,
    which the filter does not admit, are never requested, and the seed is stored. It has
    no version parameter, so its path has no label and its version is mslearn's
    version_default (StoreNewPage guidance).
    """
    mirror = new_mirror(
        tmp_path,
        meaningful_query_params=profiles.MSLEARN.meaningful_query_params,
        locale_codes=profiles.MSLEARN.locale_codes,
    )
    mirror.profile = profiles.MSLEARN
    fetcher = FakeFetcher({SEED: html_response(SEED, PAGE)})
    run_crawl(request(mirror), None, fetcher, FixedClock())
    assert SEED in fetcher.requests
    for well_known in (f"{SITE}/sitemap.xml", f"{SITE}/sitemap_index.xml"):
        assert well_known not in fetcher.requests
    page = mirror.page(SEED)
    assert page is not None
    assert page.path == START_PATH
    assert page.version == profiles.MSLEARN.version_default


@pytest.mark.parametrize("declared_by", ["robots-txt", "declared-index"])
def test_a_declared_sitemap_past_the_cap_retires_the_host(
    tmp_path: Path, declared_by: str
) -> None:
    """T13 follow-up (crawl.allium ecfa257 FetchSitemap): retires_host = declared and past_cap.

    A Retry-After past retry_after_cap on a declared sitemap, one robots.txt names or a
    declared index's child, retires the host. Re-propagated by T18 from
    test_a_declared_sitemap_past_the_cap_stops_at_retire_host (T13), which expected
    NotInThisSlice("RetireHostOnLongRetryAfter"): the host trips, the answer stands as
    sitemap_unavailable, and nothing is requested after it (spec 86e2ec5). The long
    answer ends the tries: the sitemap is asked once, and the seed is skipped.
    """
    named = MAPS if declared_by == "robots-txt" else MAPS_INDEX
    responses = {
        SEED: html_response(SEED, PAGE),
        ROBOTS: text_response(ROBOTS, f"User-agent: *\nSitemap: {named}\n"),
        MAPS_INDEX: xml_response(MAPS_INDEX, sitemapindex(MAPS)),
        MAPS: past_cap(MAPS),
    }
    fetcher = FakeFetcher(responses)
    result = run_crawl(request(new_mirror(tmp_path)), None, fetcher, FixedClock())
    assert result.run.has_tripped_host
    assert fetcher.requests[-1] == MAPS
    assert fetcher.requests.count(MAPS) == 1
    assert SEED not in fetcher.requests
    assert [event.url for event in result.skipped] == [SEED]
    assert (MAPS, DiscoveryProblem.sitemap_unavailable) in [
        (event.url, event.problem) for event in result.discovery_failed
    ]


def test_owner_testing_runs_prepare_their_follow_up_and_discover_nothing(
    tmp_path: Path,
) -> None:
    """PrepareRun and Discover realise their owner-testing branches (T20).

    Re-propagated by T20 from test_owner_testing_runs_stop (origin T09,
    test_targeted_runs_stop, re-propagated by the T16 follow-up), which expected
    NotInThisSlice from both: an owner run following a finished standard run whose seed
    was left unresolved seeds that URL alone (a named row at depth 0), refetches nothing
    by force (its targets are empty, decided), and its discovery requests nothing: no
    seed, sitemap or llms.txt, no host opened before its first fetch.
    """
    mirror = new_mirror(tmp_path)
    base = start_run(request(mirror), FixedClock())
    assert base is not None
    base.status = RunStatus.finished
    base.unresolved_urls = frozenset({SEED})
    owner = dataclasses.replace(
        request(mirror, id=2, mode=RunMode.owner_testing),
        baseline=base,
        preceding=base,
        owned_hosts=frozenset({HOST}),
    )
    run = start_run(owner, FixedClock())
    assert run is not None
    frontier = create_frontier(run, None)
    assert prepare_run(run, frontier)
    assert run.forced_refetch == frozenset()
    assert run.active_urls == frozenset({SEED})
    (entry,) = frontier.entries
    assert entry.identity == SEED
    assert entry.status is FrontierStatus.pending
    assert entry.depth == 0
    fetcher = FakeFetcher({})
    assert discover(run, frontier, fetcher)
    assert fetcher.requests == []
    assert run.hosts == []


def test_a_browser_attempt_renders_and_a_tripped_hosts_rows_are_skipped(tmp_path: Path) -> None:
    """A try at the browser tier renders the page; rows only on a tripped host are skipped.

    Re-propagated by T18 from test_a_tripped_host_and_a_browser_attempt_stop (T12): the
    tripped half is SelectBatch's all-tripped branch, so the row is skipped_blocked and
    the frontier exhausted, where it stopped at NotInThisSlice("SelectBatch").
    Re-propagated by T19 from test_a_browser_attempt_stops_and_a_tripped_hosts_rows_are_skipped
    (T12, re-propagated by T18), whose browser half expected NotInThisSlice("AttemptTier"):
    under render_mode = auto the browser attempt renders through the engine, its
    navigation the seed's second request, and joins the walk.
    """
    mirror = new_mirror(tmp_path)
    fetcher = FakeFetcher({SEED: html_response(SEED, PAGE)})
    engine = FakeEngine()
    run = start_run(request(mirror, render_mode=RenderMode.auto), FixedClock())
    assert run is not None
    frontier = create_frontier(run, None)
    assert prepare_run(run, frontier)
    assert discover(run, frontier, fetcher)
    run.crawling = True
    (entry,) = select_batch(run, frontier) or []
    walk = fetch_entry(run, entry, fetcher, engine)
    assert walk is not None
    rendered = attempt_tier(walk, Tier.browser, 1, fetcher, engine)
    assert rendered is not None
    assert rendered.tier is Tier.browser
    assert walk.attempts[-1] is rendered
    assert engine.renders == [SEED]
    assert fetcher.requests.count(SEED) == len(["http try", "render"])
    entry.status = FrontierStatus.pending
    host = run.host(HOST)
    assert host is not None
    assert host.breaker is not None
    host.breaker.status = BreakerStatus.tripped
    assert select_batch(run, frontier) == []
    assert entry.status is FrontierStatus.skipped_blocked


def test_a_second_sync_of_a_known_page_keeps_it(tmp_path: Path) -> None:
    """A known page is fetched conditionally, and its unchanged answer keeps it (T14).

    Re-propagated from T09's test_a_second_sync_of_a_known_page_stops: the second sync
    now exits 0 rather than partial, so the first report is no longer kept; the request
    still carries the page's stored validators, which the fake's answer gave none of.
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    first = FakeFetcher({SEED: html_response(SEED, PAGE)})
    assert _commands.sync(out_dir, fetcher=first, clock=FixedClock()) is ExitCode.ok
    again = FakeFetcher({SEED: html_response(SEED, PAGE)})
    assert _commands.sync(out_dir, fetcher=again, clock=FixedClock()) is ExitCode.ok
    assert again.validators[-1] == Validators(etag=None, last_modified=None)
    # An atomic write gives the mode an ordinary new file gets, not the temporary's 0600.
    mask = os.umask(0)
    os.umask(mask)
    assert stat.S_IMODE((out_dir / START_PATH).stat().st_mode) == 0o666 & ~mask


def test_a_duplicate_candidate_and_a_page_outside_the_scope_now_settle(tmp_path: Path) -> None:
    """A second candidate for a page stored this run, and a page to retire (T15).

    Re-propagated by T15 from test_mirror_branches_of_later_slices_stop, which expected
    both to stop: the same candidate delivered twice in one run is now a duplicate
    (RejectDuplicateCandidate), answering no page, and a written page whose source URL
    left the scope is retired out_of_scope by the next finalisation.
    """
    mirror = new_mirror(tmp_path)
    linked = extract(
        PAGE.replace("</main>", '<p><a href="/guide/b.html">B</a></p></main>'),
        SEED,
        profiles.GENERIC,
    )
    normalized = normalize(linked, profiles.GENERIC)
    body = restore(convert(normalized.fragment), normalized.islands)
    content = converted_content(linked, normalized, body, measure(linked, normalized, body))
    delivered = CandidateDelivered(
        run_id=1,
        mirror=mirror,
        requested_identity=SEED,
        source_url=SEED,
        redirect_hops=(),
        depth=0,
        outcome=CandidateOutcome.converted,
        tier=Tier.http,
        raw_digest="0" * 64,
        content=content,
    )
    page = take_candidate(admit_candidate(delivered), FixedClock())
    assert page is not None
    # T10 realises ResolveMirrorLinks: a page with links no longer stops the pass.
    again = admit_candidate(delivered)
    assert take_candidate(again, FixedClock()) is None
    assert again.status is CandidateStatus.duplicate
    assert mirror.pages == [page]
    page.source_url = f"{SITE}/elsewhere/page.html"
    finalisation = finalise(Operator(), mirror, 2, FixedClock())
    assert [(removal.page, removal.reason) for removal in finalisation.removed] == [
        (page, RemovalReason.out_of_scope)
    ]
    assert page.status is PageStatus.removed


def test_a_canonical_merging_a_known_page_into_another_settles(tmp_path: Path) -> None:
    """RewriteKnownPage's merge branch (previous != target), realised by T15.

    Re-propagated by T15 from test_a_canonical_merging_a_known_page_into_another_stops,
    which expected NotInThisSlice("RewriteKnownPage"): the seed's new canonical names
    another written page, so that page is rewritten and the seed is removed, merged.
    """
    mirror = new_mirror(tmp_path)
    other = f"{SITE}/guide/other.html"
    stored = []
    for url in (SEED, other):
        page = take_candidate(
            admit_candidate(
                CandidateDelivered(
                    run_id=1,
                    mirror=mirror,
                    requested_identity=url,
                    source_url=url,
                    redirect_hops=(),
                    depth=0,
                    outcome=CandidateOutcome.converted,
                    tier=Tier.http,
                    raw_digest="0" * 64,
                    content=page_content(PAGE),
                )
            ),
            FixedClock(),
        )
        assert page is not None
        stored.append(page)
    canonical = PAGE.replace("<head>", f'<head><link rel="canonical" href="{other}">')
    merging = admit_candidate(
        CandidateDelivered(
            run_id=2,
            mirror=mirror,
            requested_identity=SEED,
            source_url=SEED,
            redirect_hops=(),
            depth=0,
            outcome=CandidateOutcome.converted,
            tier=Tier.http,
            raw_digest="1" * 64,
            content=page_content(canonical),
        )
    )
    assert take_candidate(merging, FixedClock()) is stored[1]
    assert [page.status for page in stored] == [PageStatus.removed, PageStatus.written]
    assert stored[0].removal_reason is RemovalReason.merged
    assert [page.last_stored_run for page in stored] == [1, 2]
    assert mirror.known_page(SEED) is stored[1]


def test_a_known_pages_non_html_answer_settles_skipped_not_html(tmp_path: Path) -> None:
    """A known page answering with another raw document that is not HTML is retired.

    Re-propagated by T16 (origin T14, test_a_known_pages_non_html_answer_stops): DisposeFetch's
    skipped_not_html branch settles the row and no URL fails. Re-propagated by the T16
    follow-up (origin T16, which kept the page written): since 9a253a4 the known page is
    delivered absent and retired, its record removed with removal_reason absent.
    """
    mirror = new_mirror(tmp_path)
    run_crawl(request(mirror), None, FakeFetcher({SEED: html_response(SEED, PAGE)}), FixedClock())
    (page,) = mirror.pages
    again = FakeFetcher({SEED: text_response(SEED, "plain")})
    result = run_crawl(
        request(mirror, id=2, kind=RunKind.update), load_frontier(mirror), again, FixedClock()
    )
    assert again.requests[-1] == SEED
    rows = {entry.identity: entry.status for entry in result.frontier.entries}
    assert rows[SEED] is FrontierStatus.skipped_not_html
    assert result.failed == ()
    assert mirror.pages == [page]
    assert page.status is PageStatus.removed
    assert page.removal_reason is RemovalReason.absent


def page_content(html: str) -> ConvertedContent:
    """The seed's markup converted with the generic profile, as ConvertFetched does."""
    extracted = extract(html, SEED, profiles.GENERIC)
    normalized = normalize(extracted, profiles.GENERIC)
    body = restore(convert(normalized.fragment), normalized.islands)
    return converted_content(extracted, normalized, body, measure(extracted, normalized, body))


def test_enqueue_page_links_owner_branch_admits_only_owned_needed_links(tmp_path: Path) -> None:
    """EnqueuePageLinks' owner-testing branch admits an unseen link on an owned host only.

    Re-propagated by T20 from test_enqueue_page_links_owner_branch_stops (T10), which
    expected NotInThisSlice with no entry: with the link's host not owned nothing is
    admitted; once it is, the unseen link (owner_link_needed) is discovered via link.
    """
    mirror = new_mirror(tmp_path)
    run = start_run(request(mirror), FixedClock())
    assert run is not None
    frontier = create_frontier(run, None)
    assert frontier is not None
    candidate = admit_candidate(
        CandidateDelivered(
            run_id=run.id,
            mirror=mirror,
            requested_identity=SEED,
            source_url=SEED,
            redirect_hops=(),
            depth=0,
            outcome=CandidateOutcome.converted,
            tier=Tier.http,
            raw_digest="0" * 64,
            content=page_content(PAGE),
        )
    )
    page = take_candidate(candidate, FixedClock())
    assert page is not None
    found = LinksFound(
        candidate=candidate,
        page=page,
        depth=0,
        targets=(f"{SITE}/guide/b.html",),
        navigation_targets=(),
    )
    run.mode = RunMode.owner_testing
    assert enqueue_page_links(run, frontier, found) == []
    assert frontier.entries == []
    run.owned_hosts = frozenset({HOST})
    (entry,) = enqueue_page_links(run, frontier, found) or []
    assert entry.identity == f"{SITE}/guide/b.html"
    assert frontier.entries == [entry]


def test_an_island_restores_and_the_inline_style_anchors() -> None:
    """An island is restored, and the inline anchor style writes an anchor island (T17).

    Re-propagated by T17 from T09's test_convert_branches_of_later_slices_stop: restore
    puts each island's payload where its token stood, and normalize under the inline
    style writes the heading's id as an anchor island before the heading.
    """
    extracted = extract(
        PAGE.replace("</main>", "<dl><dt>Term</dt><dd><p>Block.</p><p>More.</p></dd></dl></main>"),
        SEED,
        profiles.GENERIC,
    )
    normalized = normalize(extracted, profiles.GENERIC)
    (island,) = normalized.islands
    assert isinstance(island, Island)
    assert island.payload in restore(convert(normalized.fragment), normalized.islands)
    inline = dataclasses.replace(profiles.GENERIC, heading_anchor_style=HeadingAnchorStyle.inline)
    styled = extract(PAGE.replace("<h2>", '<h2 id="install">'), SEED, inline)
    body = convert(normalize(styled, inline).fragment)
    assert '<a id="install"></a>' in body
    assert "{#install}" not in body


def test_a_versioned_path_carries_its_label(tmp_path: Path) -> None:
    """T17 follow-up (spec 022eca4): a version label is "@" and the label before ".md".

    Re-propagated by T17 from T09's test_a_dry_run_report_and_a_versioned_path_stop,
    which asserted NotInThisSlice("assign_path") (T13 realised its dry-run half). Only an
    identity carrying mslearn's version parameter is labelled; version_default never
    touches the path.
    """
    versioned = Mirror(
        out_dir=tmp_path,
        scope=scope(meaningful_query_params=("view",)),
        profile=profiles.MSLEARN,
        processing_signature="signature-1",
    )
    beta = f"{SITE}/guide/page?view=graph-rest-beta"
    assert assign_path(versioned, beta) == f"{ROOT}page@beta.md"
    assert version_label(profiles.MSLEARN, beta) == "beta"
    assert assign_path(versioned, f"{SITE}/guide/page") == f"{ROOT}page.md"


# --- The black boxes' corners --------------------------------------------------------


@pytest.mark.parametrize(
    ("markup", "reason"),
    [
        pytest.param(
            '<html><body><div id="root"></div><script src="a.js"></script></body></html>',
            RenderReason.spa_shell,
            id="spa-shell",
        ),
        pytest.param(
            "<html><body><p>No main element holds this text.</p></body></html>",
            RenderReason.main_selector_absent,
            id="no-main",
        ),
        pytest.param(
            f"<html><body><main><p>Thin.</p></main><!-- {'x' * 6000} --></body></html>",
            RenderReason.thin_text,
            id="thin-text",
        ),
    ],
)
def test_render_reasons(markup: str, reason: RenderReason) -> None:
    """render_reason_of's recognisers, in order, on unblocked http answers."""
    assert render_reason_of(html_response(SEED, markup)) is reason
    assert render_reason_of(text_response(SEED, markup)) is None


def test_classify_block_gives_none_otherwise() -> None:
    """An answer that is no block has verdict none, and none counts against the host.

    Re-propagated by T18 (origin T09): a 403, which stopped at NotInThisSlice, is hard
    and counts against the host.
    """
    verdict = classify_block(html_response(SEED, PAGE), None)
    assert verdict == BlockVerdict(kind=BlockKind.none, signature="")
    assert not verdict.counts_against_host
    forbidden = classify_block(html_response(SEED, "", status=FORBIDDEN), None)
    assert forbidden == BlockVerdict(kind=BlockKind.hard, signature="403 Forbidden")
    assert forbidden.counts_against_host


def test_prepare_run_rechecks_written_and_removed_pages(tmp_path: Path) -> None:
    """An update run re-pends a written page's row it lacks and rechecks a removed page last."""
    mirror = new_mirror(tmp_path)
    fetcher = FakeFetcher({SEED: html_response(SEED, PAGE)})
    first = run_crawl(request(mirror), None, fetcher, FixedClock())
    (page,) = mirror.pages
    page.status = PageStatus.removed
    frontier = first.frontier
    frontier.entries.clear()
    run = start_run(
        request(mirror, id=2, kind=RunKind.update, max_age=timedelta(seconds=1)), FixedClock()
    )
    assert run is not None
    assert prepare_run(run, frontier)
    (row,) = frontier.entries
    assert row.priority == CRAWL.deferred_priority
    page.status = PageStatus.written
    frontier.entries.clear()
    assert prepare_run(run, frontier)
    assert [entry.status for entry in frontier.entries] == [FrontierStatus.pending]


def test_url_identity_corners() -> None:
    """Dot segments, default ports, regex patterns, device names and long names."""
    assert normalise_url("https://Docs.Example:443/a/b/../c/./", ()) == "https://docs.example/a/c/"
    assert normalise_url("http://docs.example/a/..", ()) == "http://docs.example/"
    assert normalise_url("http://docs.example:8080", ()) == "http://docs.example:8080/"
    assert pattern_matches(f"{SITE}/guide/a.html", r"re:/guide/\w\.html$")
    assert not pattern_matches(f"{SITE}/guide/a.html", "*/blog/*")
    mirror = Mirror(
        out_dir=Path(),
        scope=scope(locale="en"),
        profile=profiles.GENERIC,
        processing_signature="s",
    )
    assert assign_path(mirror, f"{SITE}/guide/con.html") == f"{ROOT}con-.md"
    assert assign_path(mirror, f"{SITE}/other/page.aspx") == f"{ROOT}other/page.md"
    seed_scope = scope(include=("re:start",), exclude=("*/private/*",))
    assert seed_scope.within_bounds(f"{SITE}/guide/start-here.html")
    assert not seed_scope.within_bounds(f"{SITE}/guide/private/start.html")


def test_rovo_toml_readers(tmp_path: Path) -> None:
    """Every reader accepts its type and names the key it rejects."""
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    path = out_dir / "rovo.toml"
    text = path.read_text(encoding="utf-8").replace(
        "# max_age = 86400", "max_age = 86400\nmystery = 1"
    )
    text = text.replace('allowed_hosts = ["docs.example"]', 'allowed_hosts = ["Docs.Example:80"]')
    path.write_text(text + '\n[surprise]\nkey = "x"\n[site.nested]\n', encoding="utf-8")
    settings = resolve_config(out_dir)
    assert settings.max_age == timedelta(seconds=86400)
    assert settings.allowed_hosts == frozenset({HOST})
    problems = " ".join(settings.problems)
    assert "crawl.mystery" in problems
    assert "surprise" in problems
    assert "site.nested" in problems
    path.write_text(
        'max_age = -1\n[crawl]\nmax_age = "soon"\n[scope]\nallowed_hosts = [1]\n',
        encoding="utf-8",
    )
    assert not resolve_config(out_dir).valid


def test_sync_options_and_tier_detection(tmp_path: Path) -> None:
    """A named URL targets the run; the default tier check needs no engine for http."""
    options = SyncOptions(
        dry_run=False,
        confirmed=False,
        interactive=False,
        json_events=False,
        urls=(SEED,),
        paths=(),
    )
    assert options.targeted
    assert not options.is_owner_testing
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    path = out_dir / "rovo.toml"
    path.write_text(path.read_text(encoding="utf-8").replace('"off"', '"on"'), encoding="utf-8")
    fetcher = FakeFetcher({})
    assert _commands.sync(out_dir, fetcher=fetcher, clock=FixedClock()) is ExitCode.usage
    assert fetcher.requests == []


def test_extraction_corners() -> None:
    """og:title and the URL as titles, no description, a fence's language on <pre>."""
    og = (
        '<html><head><meta property="og:title" content="From OG"></head>'
        "<body><main><h2>Body</h2></main></body></html>"
    )
    assert extract(og, SEED, profiles.GENERIC).title == "From OG"
    bare = "<html><body><main><ul><li>item</li></ul></main></body></html>"
    extracted = extract(bare, SEED, profiles.GENERIC)
    assert extracted.title == SEED
    assert extracted.description == ""
    assert convert('<pre class="lang-sh">ls\n</pre>').startswith("```sh\n")
    empty = extract("<html><body><main></main></body></html>", SEED, profiles.GENERIC)
    normalized = normalize(empty, profiles.GENERIC)
    quality = measure(empty, normalized, restore(convert(normalized.fragment), ()))
    assert QualityFlag.empty_content in quality.flags
    assert empty.method is ExtractionMethod.profile
    chrome = (
        "<html><body><header>Site</header><p>"
        + "word " * 2
        + "</p><footer>"
        + "chrome " * 20
        + "</footer><script>x()</script></body></html>"
    )
    whole = extract(chrome, SEED, profiles.GENERIC)
    assert (
        QualityFlag.extracted_share
        in measure(whole, normalize(whole, profiles.GENERIC), "# x\n").flags
    )


def test_page_outcomes_and_keyword_bounds(tmp_path: Path) -> None:
    """A changed body publishes changed, a moved page publishes moved."""
    mirror = new_mirror(tmp_path)
    fetcher = FakeFetcher({SEED: html_response(SEED, PAGE)})
    run_crawl(request(mirror), None, fetcher, FixedClock())
    (page,) = mirror.pages
    first = finalise(Operator(), mirror, 1, FixedClock())
    assert [event.outcome for event in first.finalised] == [StoreOutcome.added]
    page.converted_body += "\nMore text.\n"
    second = finalise(Operator(), mirror, 1, FixedClock())
    assert [event.outcome for event in second.finalised] == [StoreOutcome.changed]
    page.moved_from = f"{ROOT}old.md"
    third = finalise(Operator(), mirror, 1, FixedClock())
    assert [(e.outcome, e.previous_path) for e in third.finalised] == [
        (StoreOutcome.moved, f"{ROOT}old.md")
    ]
    assert keywords_of("```\ncode\n```\n", 3, 1) == ()


def test_manifest_errors(tmp_path: Path) -> None:
    """An unknown profile or an alias with no page is a manifest that does not parse."""
    mirror = new_mirror(tmp_path)
    text = manifest_path(tmp_path).read_text(encoding="utf-8")
    manifest_path(tmp_path).write_text(text.replace('"generic"', '"nope"'), encoding="utf-8")
    with pytest.raises(ManifestError):
        load_mirror(tmp_path)
    save_mirror(mirror)
    manifest_path(tmp_path).write_text(
        text.replace('"aliases": []', '"aliases": [{"target": "x", "url": "y"}]'),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError):
        load_mirror(tmp_path)
    assert load_frontier(mirror) is None


def test_httpx_fetcher_sends_validators_and_reads_retry_after() -> None:
    """A conditional fetch sends the stored validators; Retry-After in seconds is read.

    T12: a Retry-After given as an HTTP date is the time from the response's Date to that
    date; a date already past is zero; an unreadable value is no Retry-After. Propagate
    tick 4: seconds too many for a duration are the longest duration, past
    retry_after_cap, and a non-ASCII digit is unreadable (implement 3).
    """
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(TOO_MANY, headers={"retry-after": "7"})

    with HttpxFetcher(transport=httpx.MockTransport(answer)) as fetcher:
        response = fetcher.fetch(SEED, validators=Validators(etag='"e"', last_modified="Sat"))
    assert seen[0].headers["if-none-match"] == '"e"'
    assert seen[0].headers["if-modified-since"] == "Sat"
    assert response.retry_after == timedelta(seconds=7)
    assert response.retryable

    sent = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)
    dated = {
        "later": (sent + timedelta(seconds=90), timedelta(seconds=90)),
        "past": (sent - timedelta(seconds=30), timedelta(0)),
    }
    for name, (until, expected) in dated.items():

        def answer_dated(request: httpx.Request, until: datetime = until) -> httpx.Response:
            del request
            return httpx.Response(
                SERVICE_UNAVAILABLE,
                headers={
                    "retry-after": format_datetime(until, usegmt=True),
                    "date": format_datetime(sent, usegmt=True),
                },
            )

        with HttpxFetcher(transport=httpx.MockTransport(answer_dated)) as fetcher:
            assert fetcher.fetch(SEED).retry_after == expected, name

    def unreadable(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(SERVICE_UNAVAILABLE, headers={"retry-after": "soon"})

    with HttpxFetcher(transport=httpx.MockTransport(unreadable)) as fetcher:
        assert fetcher.fetch(SEED).retry_after is None

    edges: dict[bytes, timedelta | None] = {
        b"9" * 30: timedelta.max,
        b"\xb2": None,
    }
    for value, read in edges.items():

        def answer_edge(request: httpx.Request, value: bytes = value) -> httpx.Response:
            del request
            return httpx.Response(SERVICE_UNAVAILABLE, headers=[(b"retry-after", value)])

        with HttpxFetcher(transport=httpx.MockTransport(answer_edge)) as fetcher:
            assert fetcher.fetch(SEED).retry_after == read, value
    assert timedelta.max > CRAWL.retry_after_cap
