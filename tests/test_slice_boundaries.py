"""Where this slice stops, and the corners of what it does that the obligation tests skip.

Every branch a later slice implements raises NotInThisSlice; these tests prove each
guard point is reached by the input that needs it, rather than a later slice's
behaviour being silently skipped. No test asserts the message, and the slice that
implements a branch replaces its test here. The rest covers the black boxes' corners:
the render recognisers, path assignment, the rovo.toml readers and the page file.
"""

import dataclasses
import os
import stat
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from fakes import FakeFetcher, FixedClock, html_response, text_response
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
    FrontierStatus,
    RenderMode,
    RenderReason,
    RunKind,
    RunMode,
    RunRequest,
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
    CrawlScope,
    LinksFound,
    Mirror,
    Operator,
    PageStatus,
    StoreOutcome,
    Tier,
)
from rovo._mirror.state import ManifestError, load_mirror, manifest_path, save_mirror
from rovo._mirror.urls import assign_path, normalise_url, pattern_matches, version_label
from rovo._report import (
    CrawlReport,
    CrawlReportStatus,
    ExitCode,
    ReportStatus,
    close_run,
    report_path,
)
from rovo._unfinished import NotInThisSlice

SITE = "http://docs.example"
HOST = "docs.example"
SEED = f"{SITE}/guide/start.html"
# page_root of the fixture host (mirror.allium MovePage guidance, at fed9ed8).
ROOT = "pages/docs.example/"
START_PATH = f"{ROOT}start.md"
ROBOTS = f"{SITE}/robots.txt"
SITES = Path(__file__).resolve().parent / "fixtures" / "sites"
PAGE = (SITES / "one-page" / "guide" / "start.html").read_text(encoding="utf-8")
FORBIDDEN = 403
MOVED = 301
SERVER_ERROR = 500
TOO_MANY = 429
NOT_FOUND = 404


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


# --- The guard points: each stops the run with NotInThisSlice ------------------------


@pytest.mark.parametrize(
    "responses",
    [
        pytest.param({ROBOTS: text_response(ROBOTS, "", status=MOVED)}, id="robots-redirect"),
        pytest.param({ROBOTS: text_response(ROBOTS, "", status=FORBIDDEN)}, id="robots-refused"),
        pytest.param({SEED: html_response(SEED, "", status=NOT_FOUND)}, id="absent-page"),
        pytest.param({SEED: html_response(SEED, "", status=FORBIDDEN)}, id="blocked-page"),
        pytest.param({SEED: html_response(SEED, "", status=SERVER_ERROR)}, id="retryable"),
        pytest.param({SEED: text_response(SEED, "plain")}, id="not-html"),
        pytest.param(
            {SEED: html_response(SEED, PAGE.replace("</main>", '<input type="password"></main>'))},
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
            id="long-retry-after",
        ),
    ],
)
def test_a_later_slices_answer_stops_the_run(
    tmp_path: Path, responses: dict[str, SiteResponse]
) -> None:
    """Robots, disposal, block and retry branches a later slice implements stop the run."""
    with pytest.raises(NotInThisSlice):
        crawl(tmp_path, responses)
    assert not (tmp_path / ".rovo" / "frontier.json").exists()


def test_escalation_to_the_browser_stops_the_run(tmp_path: Path) -> None:
    """Under render_mode = auto a page that needs rendering asks for the browser tier."""
    noscript = PAGE.replace("</main>", "<noscript>Enable JavaScript.</noscript></main>")
    with pytest.raises(NotInThisSlice):
        crawl(tmp_path, {SEED: html_response(SEED, noscript)}, render_mode=RenderMode.auto)


def test_a_non_generic_profile_stops_conversion(tmp_path: Path) -> None:
    """Extraction with a profile other than generic is a later slice's."""
    mirror = new_mirror(tmp_path)
    mirror.profile = profiles.DEVSITE
    fetcher = FakeFetcher({SEED: html_response(SEED, PAGE)})
    with pytest.raises(NotInThisSlice):
        run_crawl(request(mirror), None, fetcher, FixedClock())


def test_owner_testing_and_dry_runs_stop(tmp_path: Path) -> None:
    """An owner-testing request is refused by StartRun; a dry run is a later slice's."""
    with pytest.raises(NotInThisSlice):
        crawl(tmp_path / "owner", {}, mode=RunMode.owner_testing)
    with pytest.raises(NotInThisSlice):
        crawl(tmp_path / "dry", {}, dry_run=True)


def test_targeted_runs_stop(tmp_path: Path) -> None:
    """Named targets are a later slice's: PrepareRun and Discover stop on them."""
    mirror = new_mirror(tmp_path)
    run = start_run(request(mirror, targets=frozenset({SEED})), FixedClock())
    assert run is not None
    frontier = create_frontier(run, None)
    with pytest.raises(NotInThisSlice):
        prepare_run(run, frontier)
    with pytest.raises(NotInThisSlice):
        discover(run, frontier, FakeFetcher({}))


def test_a_tripped_host_and_a_browser_attempt_stop(tmp_path: Path) -> None:
    """Rows only on a tripped host, and a try at the browser tier, are later slices'."""
    mirror = new_mirror(tmp_path)
    fetcher = FakeFetcher({SEED: html_response(SEED, PAGE)})
    run = start_run(request(mirror), FixedClock())
    assert run is not None
    frontier = create_frontier(run, None)
    assert prepare_run(run, frontier)
    assert discover(run, frontier, fetcher)
    run.crawling = True
    (entry,) = select_batch(run, frontier) or []
    walk = fetch_entry(run, entry, fetcher)
    assert walk is not None
    with pytest.raises(NotInThisSlice):
        attempt_tier(walk, Tier.browser, 1, fetcher)
    entry.status = FrontierStatus.pending
    host = run.host(HOST)
    assert host is not None
    assert host.breaker is not None
    host.breaker.status = BreakerStatus.tripped
    with pytest.raises(NotInThisSlice):
        select_batch(run, frontier)


def test_a_second_sync_of_a_known_page_stops(tmp_path: Path) -> None:
    """A known page is fetched conditionally; the unchanged answer is a later slice's.

    The command exits partial, says why on standard error, and keeps the first report.
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    first = FakeFetcher({SEED: html_response(SEED, PAGE)})
    assert _commands.sync(out_dir, fetcher=first, clock=FixedClock()) is ExitCode.ok
    report = report_path(out_dir).read_bytes()
    again = FakeFetcher({SEED: html_response(SEED, PAGE)})
    assert _commands.sync(out_dir, fetcher=again, clock=FixedClock()) is ExitCode.partial
    assert again.validators[-1] == Validators(etag=None, last_modified=None)
    assert report_path(out_dir).read_bytes() == report
    # An atomic write gives the mode an ordinary new file gets, not the temporary's 0600.
    mask = os.umask(0)
    os.umask(mask)
    assert stat.S_IMODE((out_dir / START_PATH).stat().st_mode) == 0o666 & ~mask


def test_mirror_branches_of_later_slices_stop(tmp_path: Path) -> None:
    """A page to retire and a candidate StoreNewPage does not take (links are T10's)."""
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
    with pytest.raises(NotInThisSlice):
        take_candidate(admit_candidate(delivered), FixedClock())
    page.source_url = f"{SITE}/elsewhere/page.html"
    with pytest.raises(NotInThisSlice):
        finalise(Operator(), mirror, 2, FixedClock())


def page_content(html: str) -> ConvertedContent:
    """The seed's markup converted with the generic profile, as ConvertFetched does."""
    extracted = extract(html, SEED, profiles.GENERIC)
    normalized = normalize(extracted, profiles.GENERIC)
    body = restore(convert(normalized.fragment), normalized.islands)
    return converted_content(extracted, normalized, body, measure(extracted, normalized, body))


def test_enqueue_page_links_owner_branch_stops(tmp_path: Path) -> None:
    """EnqueuePageLinks' owner-testing branch (owner_link_needed) is a later slice's."""
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
    with pytest.raises(NotInThisSlice):
        enqueue_page_links(run, frontier, found)
    assert frontier.entries == []


def test_convert_branches_of_later_slices_stop() -> None:
    """An island to restore and the inline anchor style are later slices'."""
    with pytest.raises(NotInThisSlice):
        restore("# Title\n", (Island(payload="<dl></dl>", carries_markdown=False),))
    inline = dataclasses.replace(profiles.GENERIC, heading_anchor_style=HeadingAnchorStyle.inline)
    extracted = extract(PAGE.replace("<h2>", '<h2 id="install">'), SEED, inline)
    with pytest.raises(NotInThisSlice):
        normalize(extracted, inline)


def test_a_dry_run_report_and_a_versioned_path_stop(tmp_path: Path) -> None:
    """CloseRun's dry-run branch, and a version label in a path, are later slices'."""
    mirror = new_mirror(tmp_path)
    versioned = Mirror(
        out_dir=tmp_path,
        scope=scope(),
        profile=profiles.MSLEARN,
        processing_signature="signature-1",
    )
    with pytest.raises(NotInThisSlice):
        assign_path(versioned, f"{SITE}/guide/page?view=graph-rest-beta")
    assert version_label(profiles.MSLEARN, f"{SITE}/guide/page?view=graph-rest-beta") == "beta"
    fetcher = FakeFetcher({SEED: html_response(SEED, PAGE)})
    result = run_crawl(request(mirror), None, fetcher, FixedClock())
    settings = resolve_config(tmp_path)
    report = CrawlReport(
        mirror=mirror,
        operator=result.run.operator,
        run_id=1,
        kind=RunKind.initial,
        mode=RunMode.standard,
        report_status=ReportStatus.finished,
        exit_code=ExitCode.ok,
        configuration=settings,
        options=SyncOptions(
            dry_run=True, confirmed=False, interactive=False, json_events=False, urls=(), paths=()
        ),
        tool_version="0",
        started_at=FixedClock().now(),
        status=CrawlReportStatus.open,
    )
    with pytest.raises(NotInThisSlice):
        close_run(report, result.run, result.frontier)


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
    """An answer that is no block has verdict none, and none counts against the host."""
    verdict = classify_block(html_response(SEED, PAGE), None)
    assert verdict == BlockVerdict(kind=BlockKind.none, signature="")
    assert not verdict.counts_against_host
    with pytest.raises(NotInThisSlice):
        classify_block(html_response(SEED, "", status=FORBIDDEN), None)


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
    """A conditional fetch sends the stored validators; Retry-After in seconds is read."""
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(TOO_MANY, headers={"retry-after": "7"})

    with HttpxFetcher(transport=httpx.MockTransport(answer)) as fetcher:
        response = fetcher.fetch(SEED, validators=Validators(etag='"e"', last_modified="Sat"))
    assert seen[0].headers["if-none-match"] == '"e"'
    assert seen[0].headers["if-modified-since"] == "Sat"
    assert response.retry_after == timedelta(seconds=7)
    assert response.may_carry_retry_after
