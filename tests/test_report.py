"""rovo.allium's report obligations: the tallies, CloseRun, the ranking and crawl-report.json.

Each test is named after the obligation id `just plan-spec rovo` emits, dots and hyphens
as underscores, and its docstring quotes the obligation. A run is crawled over a
FakeFetcher, finalised, and tallied into a report built as StartSync builds it. A
`rule_failure` test makes one `requires` clause false: the rule returns False or None
and the report does not change.
"""

import dataclasses
import importlib.metadata
import json
from datetime import timedelta
from pathlib import Path

from fakes import START, FakeFetcher, FixedClock, fixture_site, html_response, text_response
from rovo import _config
from rovo._config import Configuration, SyncOptions
from rovo._convert import profiles
from rovo._convert.model import QualityFlag, QualityGate
from rovo._crawl import model
from rovo._crawl.model import (
    DiscoveryFailed,
    DiscoveryProblem,
    RenderMode,
    RobotsMode,
    Run,
    RunKind,
    RunMode,
    RunRequest,
    StealthMode,
    standard_policy,
)
from rovo._crawl.run import CrawlResult, run_crawl
from rovo._mirror.finalise import Finalisation, finalise, request_pass
from rovo._mirror.intake import retire_page
from rovo._mirror.model import (
    BrokenLink,
    BrokenLinkReason,
    CrawlScope,
    LinksRewritten,
    Mirror,
    Operator,
    PageRemoved,
    PassKind,
    RemovalReason,
    StoreOutcome,
    Tier,
)
from rovo._mirror.state import save_mirror
from rovo._report import (
    BlockedUrl,
    Change,
    ChangeKind,
    CrawlReport,
    CrawlReportStatus,
    DiscoveryProblemRow,
    ExitCode,
    FailedUrl,
    GateFailure,
    HostReport,
    LowConfidencePage,
    QualitySummary,
    ReportStatus,
    close_run,
    finalise_run_report,
    host_reports,
    most_severe,
    rank_and_write_report,
    report_path,
    summarise,
    take_broken_links,
    tally_discovery_problem,
    tally_failed_url,
    tally_finalised_page,
    tally_removal,
)
from spec_values import spec_enum, spec_float

SITE = "http://docs.example"
HOST = "docs.example"
SEED = f"{SITE}/guide/start.html"
# The seed page's mirror-relative path (mirror.allium MovePage guidance, at fed9ed8).
START_PATH = "pages/docs.example/start.md"
SITES = Path(__file__).resolve().parent / "fixtures" / "sites"
PAGE = (SITES / "one-page" / "guide" / "start.html").read_text(encoding="utf-8")
NOSCRIPT_PAGE = PAGE.replace(
    "</main>", "<noscript>Enable JavaScript to run this app.</noscript></main>"
)
LATER = START + timedelta(minutes=1)
LOW = 0.5
MIDDLE = 0.75
PERCENTILE = 0.1
FORBIDDEN = 403
SERVICE_UNAVAILABLE = 503
ROBOTS = f"{SITE}/robots.txt"

# Every CrawlReport field but the mirror, the operator and the open/written status.
REPORT_KEYS = {
    "run_id",
    "kind",
    "mode",
    "report_status",
    "exit_code",
    "error",
    "refusal_reason",
    "configuration",
    "options",
    "tool_version",
    "targets",
    "declared_owned_hosts",
    "baseline_run_id",
    "preceding_run_id",
    "requested_owner_test",
    "effective_policy",
    "unresolved_urls",
    "robots_ignored",
    "discovered",
    "fetched",
    "converted",
    "skipped_unchanged",
    "bytes_fetched",
    "budget_stopped",
    "breaker_tripped",
    "per_host",
    "quality_summary",
    "scores",
    "blocked_urls",
    "failed_urls",
    "skipped_urls",
    "discovery_problems",
    "low_confidence_pages",
    "broken_links",
    "changes",
    "started_at",
    "finished_at",
}


def configuration(*, fail_on_low_quality: bool = False) -> Configuration:
    """A valid resolved configuration of the fixture mirror."""
    return Configuration(
        valid=True,
        problems=(),
        hash="0123456789abcdef",
        root_url=f"{SITE}/guide/",
        start_urls=(SEED,),
        allowed_hosts=frozenset({HOST}),
        path_prefixes=("/guide/",),
        include=(),
        exclude=(),
        max_depth=10,
        locale=None,
        meaningful_query_params=(),
        profile_name="generic",
        robots=RobotsMode.respect,
        render_mode=RenderMode.never,
        stealth_mode=StealthMode.off,
        max_age=None,
        fail_on_low_quality=fail_on_low_quality,
        unblocking_provider=None,
    )


OPTIONS = SyncOptions(
    dry_run=False, confirmed=False, interactive=False, json_events=False, urls=(), paths=()
)


def crawled(
    out_dir: Path, page: str = PAGE, *, fetcher: FakeFetcher | None = None, dry_run: bool = False
) -> CrawlResult:
    """One standard run of the fixture site over a FakeFetcher, `fetcher` when given."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mirror = Mirror(
        out_dir=out_dir,
        scope=CrawlScope(
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
        ),
        profile=profiles.GENERIC,
        processing_signature="signature-1",
    )
    save_mirror(mirror)
    trigger = RunRequest(
        operator=Operator(),
        mirror=mirror,
        id=1,
        kind=RunKind.initial,
        mode=RunMode.standard,
        scope_hash="scope-1",
        owned_hosts=frozenset(),
        policy=standard_policy(),
        dry_run=dry_run,
        interactive=False,
        render_mode=RenderMode.never,
        stealth_mode=StealthMode.off,
        targets=frozenset(),
    )
    answers = fetcher or FakeFetcher({SEED: html_response(SEED, page)})
    return run_crawl(trigger, None, answers, FixedClock())


def opened(run: Run, *, fail_on_low_quality: bool = False) -> CrawlReport:
    """The report StartSync creates for the run, open."""
    return CrawlReport(
        mirror=run.target,
        operator=run.operator,
        run_id=run.id,
        kind=run.kind,
        mode=run.mode,
        report_status=ReportStatus.finished,
        exit_code=ExitCode.ok,
        configuration=configuration(fail_on_low_quality=fail_on_low_quality),
        options=OPTIONS,
        tool_version=importlib.metadata.version("rovo"),
        started_at=START,
        status=CrawlReportStatus.open,
        effective_policy=run.policy,
    )


def tallied(
    out_dir: Path, page: str = PAGE, *, fail_on_low_quality: bool = False
) -> tuple[CrawlReport, Run, Finalisation]:
    """Crawl, close the run, finalise the mirror and tally every finalised page."""
    result = crawled(out_dir, page)
    report = opened(result.run, fail_on_low_quality=fail_on_low_quality)
    assert close_run(report, result.run, result.frontier)
    finalised = finalise(result.run.operator, result.run.target, result.run.id, FixedClock())
    for event in finalised.finalised:
        assert tally_finalised_page(report, event)
    return report, result.run, finalised


def written(out_dir: Path) -> dict[str, object]:
    """The crawl-report.json the run left."""
    loaded = json.loads(report_path(out_dir).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_rule_success_TallyFinalisedPage(tmp_path: Path) -> None:
    """Verify rule TallyFinalisedPage succeeds when all preconditions are met."""
    report, _, finalised = tallied(tmp_path)
    (event,) = finalised.finalised
    assert event.outcome is StoreOutcome.added
    assert report.scores == [event.page.quality.score]
    assert report.converted == 1
    assert report.skipped_unchanged == 0
    assert report.changes == [
        Change(kind=ChangeKind.added, url=SEED, path=START_PATH, moved_from=None)
    ]
    assert report.low_confidence_pages == []

    flagged, _, _ = tallied(tmp_path / "flagged", NOSCRIPT_PAGE)
    (row,) = flagged.low_confidence_pages
    assert row.path == START_PATH
    assert row.url == SEED
    assert QualityFlag.render_needed in row.flags
    assert row.touched_this_run


def test_rule_failure_TallyFinalisedPage_1(tmp_path: Path) -> None:
    """Verify rule TallyFinalisedPage is rejected when requires clause fails.

    requires: pass.run_id != null.
    """
    report, run, finalised = tallied(tmp_path)
    (event,) = finalised.finalised
    command_pass = request_pass(run.operator, run.target, PassKind.finalise, None)
    assert not tally_finalised_page(report, dataclasses.replace(event, pass_=command_pass))
    assert report.converted == 1
    assert len(report.changes) == 1


def test_rule_failure_TallyFinalisedPage_2(tmp_path: Path) -> None:
    """Verify rule TallyFinalisedPage is rejected when requires clause fails.

    requires: exists report and report.status = open.
    """
    report, run, finalised = tallied(tmp_path)
    (event,) = finalised.finalised
    other = opened(run)
    other.run_id = run.id + 1
    assert not tally_finalised_page(other, event)
    assert other.converted == 0
    report.status = CrawlReportStatus.written
    assert not tally_finalised_page(report, event)
    assert report.converted == 1


def removal_of(finalised: Finalisation) -> PageRemoved:
    """The seed, published by the run, retired as absent: RetirePage's PageRemoved."""
    (event,) = finalised.finalised
    removed = retire_page(event.page, RemovalReason.absent, FixedClock(LATER))
    assert removed is not None
    return removed


def test_rule_success_TallyRemoval(tmp_path: Path) -> None:
    """Verify rule TallyRemoval succeeds when all preconditions are met.

    The open report of the mirror gains one removed change: the page's identity and its
    path, which a removed page keeps, and no moved_from.
    """
    report, _, finalised = tallied(tmp_path)
    removed = removal_of(finalised)
    assert tally_removal(report, removed)
    assert report.changes[-1] == Change(
        kind=ChangeKind.removed, url=SEED, path=START_PATH, moved_from=None
    )
    assert len(report.changes) == len(["added", "removed"])


def test_rule_failure_TallyRemoval_1(tmp_path: Path) -> None:
    """Verify rule TallyRemoval is rejected when requires clause fails.

    requires: exists report: the open report is another mirror's.
    """
    report, _, finalised = tallied(tmp_path / "one")
    other, _, _ = tallied(tmp_path / "other")
    removed = removal_of(finalised)
    assert not tally_removal(other, removed)
    assert [change.kind for change in other.changes] == [ChangeKind.added]
    assert [change.kind for change in report.changes] == [ChangeKind.added]


def test_rule_failure_TallyRemoval_2(tmp_path: Path) -> None:
    """Verify rule TallyRemoval is rejected when requires clause fails.

    requires: report.status = open: the report was written already.
    """
    report, _, finalised = tallied(tmp_path)
    removed = removal_of(finalised)
    report.status = CrawlReportStatus.written
    assert not tally_removal(report, removed)
    assert [change.kind for change in report.changes] == [ChangeKind.added]


def test_rule_success_CloseRun(tmp_path: Path) -> None:
    """Verify rule CloseRun succeeds when all preconditions are met.

    T13: discovered_count is the frontier's rows after discovery, not after the links a
    page added; a dry run's report is closed without requesting the finalise pass.
    """
    linked = crawled(tmp_path / "links", fetcher=FakeFetcher(fixture_site("links", f"{SITE}/")))
    linked_report = opened(linked.run)
    assert close_run(linked_report, linked.run, linked.frontier)
    assert len(linked.frontier.entries) > 1
    assert linked_report.discovered == 1
    dry = crawled(tmp_path / "dry", dry_run=True)
    dry_report = opened(dry.run)
    dry_report.options = dataclasses.replace(OPTIONS, dry_run=True)
    assert not close_run(dry_report, dry.run, dry.frontier)
    assert dry_report.report_status is ReportStatus.finished
    assert (dry_report.discovered, dry_report.fetched) == (1, 0)
    assert dry_report.unresolved_urls == frozenset()
    assert dry_report.status is CrawlReportStatus.open

    result = crawled(tmp_path / "one-page")
    report = opened(result.run)
    assert close_run(report, result.run, result.frontier)
    assert report.report_status is ReportStatus.finished
    assert report.error is None
    assert report.unresolved_urls == result.run.unresolved_urls
    assert report.per_host == host_reports(result.run.hosts, result.run.policy)
    assert report.discovered == 1
    assert report.fetched == result.run.fetch_attempts == 1
    assert report.bytes_fetched == result.run.bytes_fetched
    assert report.budget_stopped is False
    assert report.status is CrawlReportStatus.open


def test_rule_failure_CloseRun_1(tmp_path: Path) -> None:
    """Verify rule CloseRun is rejected when requires clause fails.

    requires: exists report and report.status = open.
    """
    result = crawled(tmp_path)
    report = opened(result.run)
    report.status = CrawlReportStatus.written
    assert not close_run(report, result.run, result.frontier)
    assert report.fetched == 0
    assert report.per_host == []
    other = opened(result.run)
    other.run_id = result.run.id + 1
    assert not close_run(other, result.run, result.frontier)
    assert other.fetched == 0


def test_rule_success_FinaliseRunReport(tmp_path: Path) -> None:
    """Verify rule FinaliseRunReport succeeds when all preconditions are met."""
    _, run, finalised = tallied(tmp_path)
    assert finalise_run_report(finalised.pass_, run)


def test_rule_failure_FinaliseRunReport_1(tmp_path: Path) -> None:
    """Verify rule FinaliseRunReport is rejected when requires clause fails.

    requires: pass.kind = finalise and pass.run_id != null.
    """
    _, run, _ = tallied(tmp_path)
    index_pass = request_pass(run.operator, run.target, PassKind.index, run.id)
    assert not finalise_run_report(index_pass, run)
    command_pass = request_pass(run.operator, run.target, PassKind.finalise, None)
    assert not finalise_run_report(command_pass, run)


def test_rule_failure_FinaliseRunReport_2(tmp_path: Path) -> None:
    """Verify rule FinaliseRunReport is rejected when requires clause fails.

    requires: exists run.
    """
    _, _, finalised = tallied(tmp_path)
    assert not finalise_run_report(finalised.pass_, None)


def test_rule_success_RankAndWriteReport(tmp_path: Path) -> None:
    """Verify rule RankAndWriteReport succeeds when all preconditions are met.

    The code is the most severe of the five terms: ok for a clean run, partial with a
    failure, quality when fail_on_low_quality meets a touched low-confidence page.
    """
    report, run, _ = tallied(tmp_path)
    assert rank_and_write_report(report, run, FixedClock(LATER)) is ExitCode.ok
    assert report.exit_code is ExitCode.ok
    assert report.status is CrawlReportStatus.written
    assert report.finished_at == LATER
    assert report.quality_summary == summarise(
        report.scores, report.low_confidence_pages, _config.CONFIG.report_percentile
    )
    data = written(tmp_path)
    assert data["exit_code"] == "ok"
    assert data["report_status"] == "finished"

    failing, failing_run, _ = tallied(tmp_path / "failing")
    failing.failed_urls.append(FailedUrl(url=SEED, error="boom", attempts=1))
    assert rank_and_write_report(failing, failing_run, FixedClock()) is ExitCode.partial

    strict, strict_run, _ = tallied(tmp_path / "strict", NOSCRIPT_PAGE, fail_on_low_quality=True)
    assert rank_and_write_report(strict, strict_run, FixedClock()) is ExitCode.quality

    lenient, lenient_run, _ = tallied(tmp_path / "lenient", NOSCRIPT_PAGE)
    assert rank_and_write_report(lenient, lenient_run, FixedClock()) is ExitCode.ok


def test_rule_failure_RankAndWriteReport_1(tmp_path: Path) -> None:
    """Verify rule RankAndWriteReport is rejected when requires clause fails.

    requires: exists report and report.status = open.
    """
    report, run, _ = tallied(tmp_path)
    report.status = CrawlReportStatus.written
    assert rank_and_write_report(report, run, FixedClock()) is None
    assert not report_path(tmp_path).exists()
    assert report.finished_at is None


# --- TakeBrokenLinks (T10) ------------------------------------------------------------

# Two broken links, out of order: the report keeps them and writes them sorted.
BROKEN = (
    BrokenLink(
        from_path=START_PATH, href="other.md#nope", reason=BrokenLinkReason.fragment_not_found
    ),
    BrokenLink(from_path=START_PATH, href="gone.md", reason=BrokenLinkReason.missing_file),
)


def links_rewritten(finalised: Finalisation) -> LinksRewritten:
    """The LinksRewritten FinishLinkPass raises for the pass, carrying BROKEN."""
    pass_ = finalised.pass_
    return LinksRewritten(mirror=pass_.mirror, pass_=pass_, operator=pass_.operator, broken=BROKEN)


def test_rule_success_TakeBrokenLinks(tmp_path: Path) -> None:
    """Verify rule TakeBrokenLinks succeeds when all preconditions are met.

    The report takes the pass's broken links; crawl-report.json lists them as rows sorted
    by from_path then href.
    """
    report, run, finalised = tallied(tmp_path)
    assert take_broken_links(report, links_rewritten(finalised))
    assert report.broken_links == list(BROKEN)
    assert report.quality_failed
    rank_and_write_report(report, run, FixedClock(LATER))
    assert written(tmp_path)["broken_links"] == [
        {"from_path": START_PATH, "href": "gone.md", "reason": "missing_file"},
        {"from_path": START_PATH, "href": "other.md#nope", "reason": "fragment_not_found"},
    ]


def test_rule_failure_TakeBrokenLinks_1(tmp_path: Path) -> None:
    """Verify rule TakeBrokenLinks is rejected when requires clause fails.

    requires: pass.run_id != null.
    """
    report, run, finalised = tallied(tmp_path)
    command_pass = request_pass(run.operator, run.target, PassKind.finalise, None)
    rewritten = dataclasses.replace(links_rewritten(finalised), pass_=command_pass)
    assert not take_broken_links(report, rewritten)
    assert report.broken_links == []


def test_rule_failure_TakeBrokenLinks_2(tmp_path: Path) -> None:
    """Verify rule TakeBrokenLinks is rejected when requires clause fails.

    requires: exists report and report.status = open.
    """
    report, run, finalised = tallied(tmp_path)
    other = opened(run)
    other.run_id = run.id + 1
    assert not take_broken_links(other, links_rewritten(finalised))
    assert other.broken_links == []
    report.status = CrawlReportStatus.written
    assert not take_broken_links(report, links_rewritten(finalised))
    assert report.broken_links == []


def test_transition_edge_CrawlReport_open_written(tmp_path: Path) -> None:
    """Verify transition open -> written on CrawlReport.status is reachable via a witnessing rule."""  # noqa: E501  The obligation's description, quoted.
    report, run, _ = tallied(tmp_path)
    before = report.status
    rank_and_write_report(report, run, FixedClock())
    assert (before, report.status) == (CrawlReportStatus.open, CrawlReportStatus.written)


def test_transition_rejected_CrawlReport_status(tmp_path: Path) -> None:
    """Verify undeclared transitions on CrawlReport.status are rejected.

    written -> open is undeclared: a written report is never written again.
    """
    report, run, _ = tallied(tmp_path)
    rank_and_write_report(report, run, FixedClock(LATER))
    first = report_path(tmp_path).read_bytes()
    assert rank_and_write_report(report, run, FixedClock(LATER + timedelta(hours=1))) is None
    assert report.status is CrawlReportStatus.written
    assert report.finished_at == LATER
    assert report_path(tmp_path).read_bytes() == first


def test_transition_terminal_CrawlReport_status(tmp_path: Path) -> None:
    """Verify terminal states on CrawlReport.status have no outbound transitions."""
    result = crawled(tmp_path)
    report = opened(result.run)
    assert close_run(report, result.run, result.frontier)
    finalised = finalise(result.run.operator, result.run.target, result.run.id, FixedClock())
    rank_and_write_report(report, result.run, FixedClock())
    assert not close_run(report, result.run, result.frontier)
    for event in finalised.finalised:
        assert not tally_finalised_page(report, event)
    assert report.status is CrawlReportStatus.written


def test_when_presence_CrawlReport_finished_at(tmp_path: Path) -> None:
    """Verify CrawlReport.finished_at is present when status in {written} and absent otherwise."""
    report, run, _ = tallied(tmp_path)
    while_open = report.finished_at
    rank_and_write_report(report, run, FixedClock(LATER))
    assert while_open is None
    assert report.finished_at == LATER
    assert str(written(tmp_path)["finished_at"]).startswith(LATER.date().isoformat())


def test_entity_fields_CrawlReport(tmp_path: Path) -> None:
    """Verify all declared fields on CrawlReport are present with correct types.

    crawl-report.json carries every field but the mirror, the operator and the status.
    """
    report, run, _ = tallied(tmp_path)
    rank_and_write_report(report, run, FixedClock(LATER))
    data = written(tmp_path)
    assert set(data) == REPORT_KEYS
    assert data["run_id"] == 1
    assert data["kind"] == "initial"
    assert data["mode"] == "standard"
    assert data["tool_version"] == importlib.metadata.version("rovo")
    assert data["fetched"] == 1
    assert data["converted"] == 1
    assert data["changes"] == [
        {"kind": "added", "url": SEED, "path": START_PATH, "moved_from": None}
    ]
    configuration_data = data["configuration"]
    assert isinstance(configuration_data, dict)
    assert configuration_data["hash"] == report.configuration.hash
    assert isinstance(data["effective_policy"], dict)
    for name in REPORT_KEYS | {"mirror", "operator", "status"}:
        assert hasattr(report, name), name
    assert report.touched_low_confidence == []
    assert report.has_failures is False
    assert report.quality_failed is False


def test_entity_optional_CrawlReport_run_id(tmp_path: Path) -> None:
    """Verify optional field CrawlReport.run_id accepts null and non-null values."""
    report, run, _ = tallied(tmp_path)
    rank_and_write_report(report, run, FixedClock())
    assert written(tmp_path)["run_id"] == run.id
    no_run = opened(run)
    no_run.run_id = None
    result = crawled(tmp_path / "again")
    assert not close_run(no_run, result.run, result.frontier)  # no run's report is a refusal's


def test_derived_CrawlReport_has_failures(tmp_path: Path) -> None:
    """Verify derived value CrawlReport.has_failures computes correctly."""
    report, _, _ = tallied(tmp_path)
    clean = report.has_failures
    report.discovery_problems.append(
        DiscoveryProblemRow(url=f"{SITE}/robots.txt", problem=DiscoveryProblem.robots_refused)
    )
    assert clean is False
    assert report.has_failures is True
    report.discovery_problems.clear()
    report.blocked_urls.append(
        BlockedUrl(url=SEED, status=FORBIDDEN, signature="access denied", tier=Tier.http)
    )
    assert report.has_failures is True


def test_derived_CrawlReport_quality_failed(tmp_path: Path) -> None:
    """Verify derived value CrawlReport.quality_failed computes correctly."""
    clean, _, _ = tallied(tmp_path)
    assert clean.quality_failed is False
    flagged, _, _ = tallied(tmp_path / "flagged", NOSCRIPT_PAGE)
    touched = flagged.quality_failed
    flagged.low_confidence_pages[:] = [
        dataclasses.replace(row, touched_this_run=False) for row in flagged.low_confidence_pages
    ]
    untouched = flagged.quality_failed
    flagged.broken_links.append(
        {"from_path": START_PATH, "href": "x.md", "reason": "missing_file"}
    )
    assert (touched, untouched, flagged.quality_failed) == (True, False, True)


def test_projection_CrawlReport_touched_low_confidence(tmp_path: Path) -> None:
    """Verify projection CrawlReport.touched_low_confidence filters correctly."""
    report, _, _ = tallied(tmp_path, NOSCRIPT_PAGE)
    (touched,) = report.low_confidence_pages
    untouched = dataclasses.replace(
        touched, path="pages/docs.example/old.md", touched_this_run=False
    )
    report.low_confidence_pages.append(untouched)
    assert report.touched_low_confidence == [touched]


def test_value_equality_HostReport(tmp_path: Path) -> None:
    """Verify value type HostReport has structural equality."""
    result = crawled(tmp_path)
    first = host_reports(result.run.hosts, result.run.policy)
    again = host_reports(result.run.hosts, result.run.policy)
    assert first == again
    assert [hash(row) for row in first] == [hash(row) for row in again]
    assert first[0] != dataclasses.replace(first[0], fetched=first[0].fetched + 1)


def test_entity_fields_HostReport(tmp_path: Path) -> None:
    """Verify all declared fields on HostReport are present with correct types."""
    result = crawled(tmp_path)
    (row,) = host_reports(result.run.hosts, result.run.policy)
    assert isinstance(row, HostReport)
    assert row.host == HOST
    assert row.fetched == 1
    assert row.blocked == 0
    assert row.block_rate == 0
    assert row.tiers_used == frozenset({Tier.http})
    assert row.breaker_tripped is False
    assert row.robots_ignored is False
    assert row.render_escalations == 0
    assert row.retry_after_honored == 0
    assert row.effective_policy == result.run.policy


def low_confidence_rows() -> list[LowConfidencePage]:
    """Two low-confidence pages: one failed the links gate; one is a whole-body page."""
    return [
        LowConfidencePage(
            path="pages/docs.example/b.md",
            url=f"{SITE}/guide/b.html",
            quality_score=LOW,
            flags=frozenset({QualityFlag.links, QualityFlag.headings}),
            touched_this_run=True,
        ),
        LowConfidencePage(
            path="pages/docs.example/a.md",
            url=f"{SITE}/guide/a.html",
            quality_score=1.0,
            flags=frozenset({QualityFlag.whole_body_extracted, QualityFlag.links}),
            touched_this_run=False,
        ),
    ]


def test_value_equality_QualitySummary() -> None:
    """Verify value type QualitySummary has structural equality."""
    scores = [1.0, LOW, MIDDLE]
    first = summarise(scores, low_confidence_rows(), PERCENTILE)
    again = summarise(scores, low_confidence_rows(), PERCENTILE)
    assert first == again
    assert hash(first) == hash(again)
    assert first != summarise([1.0], [], PERCENTILE)


def test_entity_fields_QualitySummary() -> None:
    """Verify all declared fields on QualitySummary are present with correct types.

    The mean and the percentile at index round(p * (n - 1)) of the sorted scores, to four
    places; gate failures count gates only, by gate, over the low-confidence pages.
    """
    summary = summarise([1.0, LOW, MIDDLE], low_confidence_rows(), PERCENTILE)
    assert summary.mean_score == MIDDLE
    assert summary.p10_score == LOW
    assert summary.gate_failures == (
        GateFailure(gate=QualityGate.headings, pages=1),
        GateFailure(gate=QualityGate.links, pages=2),
    )
    empty = summarise([], [], PERCENTILE)
    assert empty == QualitySummary(mean_score=0, p10_score=0, gate_failures=())
    third = summarise([1 / 3], [], PERCENTILE)
    assert third.mean_score == round(1 / 3, 4)


def test_value_equality_Change(tmp_path: Path) -> None:
    """Verify value type Change has structural equality."""
    report, _, _ = tallied(tmp_path)
    (change,) = report.changes
    assert change == Change(kind=ChangeKind.added, url=SEED, path=START_PATH, moved_from=None)
    assert hash(change) == hash(dataclasses.replace(change))
    assert change != dataclasses.replace(change, kind=ChangeKind.changed)


def test_entity_fields_Change(tmp_path: Path) -> None:
    """Verify all declared fields on Change are present with correct types."""
    report, _, _ = tallied(tmp_path)
    (change,) = report.changes
    assert change.kind is ChangeKind.added
    assert change.url == SEED
    assert change.path == START_PATH
    assert change.moved_from is None


def test_enum_comparable_ExitCode() -> None:
    """Verify fields typed with enum ExitCode are comparable.

    Severity rises in declaration order, and the process exits with its number.
    """
    assert tuple(code.name for code in ExitCode) == spec_enum("rovo", "ExitCode")
    assert [code.number for code in ExitCode] == list(range(len(ExitCode)))
    assert most_severe([ExitCode.ok, ExitCode.quality, ExitCode.partial]) is ExitCode.quality
    assert most_severe([ExitCode.blocked, ExitCode.usage]) is ExitCode.blocked
    assert most_severe([]) is ExitCode.ok


def test_enum_comparable_ChangeKind(tmp_path: Path) -> None:
    """Verify fields typed with enum ChangeKind are comparable."""
    assert tuple(kind.name for kind in ChangeKind) == spec_enum("rovo", "ChangeKind")
    report, _, _ = tallied(tmp_path)
    assert [change.kind for change in report.changes] == [ChangeKind.added]
    assert ChangeKind("added") is ChangeKind.added


def test_enum_comparable_ReportStatus(tmp_path: Path) -> None:
    """Verify fields typed with enum ReportStatus are comparable."""
    assert tuple(status.name for status in ReportStatus) == spec_enum("rovo", "ReportStatus")
    report, run, _ = tallied(tmp_path)
    rank_and_write_report(report, run, FixedClock())
    assert report.report_status is ReportStatus.finished
    assert ReportStatus(written(tmp_path)["report_status"]) is ReportStatus.finished


def test_config_default_report_percentile() -> None:
    """Verify config parameter report_percentile has its declared default."""
    assert _config.CONFIG.report_percentile == spec_float("rovo", "report_percentile")


# --- Discovery problems and failed URLs (T12) -----------------------------------------


def refused_robots(out_dir: Path) -> CrawlResult:
    """A run whose robots.txt answers 403: the seed is skipped and discovery failed."""
    fetcher = FakeFetcher(
        {ROBOTS: text_response(ROBOTS, "", status=FORBIDDEN), SEED: html_response(SEED, PAGE)}
    )
    return crawled(out_dir, fetcher=fetcher)


def failing_seed(out_dir: Path) -> CrawlResult:
    """A run whose seed answers 503 on every try: the seed fails after its retries."""
    unavailable = html_response(SEED, "", status=SERVICE_UNAVAILABLE)
    return crawled(out_dir, fetcher=FakeFetcher({SEED: unavailable}))


def test_rule_success_TallyDiscoveryProblem(tmp_path: Path) -> None:
    """Verify rule TallyDiscoveryProblem succeeds when all preconditions are met.

    The run's DiscoveryFailed becomes a discovery_problems row, the run has failures and
    crawl-report.json lists the row; the exit is partial.
    """
    result = refused_robots(tmp_path)
    (failed,) = result.discovery_failed
    report = opened(result.run)
    assert tally_discovery_problem(report, failed)
    assert report.discovery_problems == [
        DiscoveryProblemRow(url=ROBOTS, problem=DiscoveryProblem.robots_refused)
    ]
    assert report.has_failures
    assert close_run(report, result.run, result.frontier)
    assert rank_and_write_report(report, result.run, FixedClock()) is ExitCode.partial
    assert written(tmp_path)["discovery_problems"] == [
        {"url": ROBOTS, "problem": "robots_refused"}
    ]


def test_rule_failure_TallyDiscoveryProblem_1(tmp_path: Path) -> None:
    """Verify rule TallyDiscoveryProblem is rejected when requires clause fails.

    requires: exists report and report.status = open.
    """
    result = refused_robots(tmp_path)
    (failed,) = result.discovery_failed
    other = opened(result.run)
    other.run_id = result.run.id + 1
    assert not tally_discovery_problem(other, failed)
    assert other.discovery_problems == []
    report = opened(result.run)
    report.status = CrawlReportStatus.written
    assert not tally_discovery_problem(report, failed)
    assert report.discovery_problems == []
    assert not report.has_failures


def test_value_equality_DiscoveryProblemRow() -> None:
    """Verify value type DiscoveryProblemRow has structural equality."""
    row = DiscoveryProblemRow(url=ROBOTS, problem=DiscoveryProblem.robots_refused)
    again = DiscoveryProblemRow(url=ROBOTS, problem=DiscoveryProblem.robots_refused)
    assert row == again
    assert hash(row) == hash(again)
    assert row != dataclasses.replace(row, problem=DiscoveryProblem.robots_unreachable)
    assert row != dataclasses.replace(row, url=f"{SITE}:8080/robots.txt")


def test_entity_fields_DiscoveryProblemRow(tmp_path: Path) -> None:
    """Verify all declared fields on DiscoveryProblemRow are present with correct types."""
    result = refused_robots(tmp_path)
    report = opened(result.run)
    for failed in result.discovery_failed:
        assert isinstance(failed, DiscoveryFailed)
        assert tally_discovery_problem(report, failed)
    (row,) = report.discovery_problems
    assert isinstance(row, DiscoveryProblemRow)
    assert row.url == ROBOTS
    assert isinstance(row.problem, DiscoveryProblem)
    assert row.problem is DiscoveryProblem.robots_refused


def test_rule_success_TallyFailedUrl(tmp_path: Path) -> None:
    """Verify rule TallyFailedUrl succeeds when all preconditions are met.

    A seed that ran out of retries is a failed_urls row with its tries and a failed
    change; crawl-report.json lists both and the exit is partial.
    """
    result = failing_seed(tmp_path)
    (failed,) = result.failed
    report = opened(result.run)
    assert tally_failed_url(report, failed)
    (row,) = report.failed_urls
    assert row == FailedUrl(url=SEED, error=failed.error, attempts=model.CONFIG.http_attempts)
    assert row.error
    assert report.changes == [Change(kind=ChangeKind.failed, url=SEED, path=None, moved_from=None)]
    assert close_run(report, result.run, result.frontier)
    assert rank_and_write_report(report, result.run, FixedClock()) is ExitCode.partial
    on_disk = written(tmp_path)
    assert on_disk["failed_urls"] == [
        {"url": SEED, "error": failed.error, "attempts": model.CONFIG.http_attempts}
    ]
    assert on_disk["changes"] == [
        {"kind": "failed", "url": SEED, "path": None, "moved_from": None}
    ]


def test_rule_failure_TallyFailedUrl_1(tmp_path: Path) -> None:
    """Verify rule TallyFailedUrl is rejected when requires clause fails.

    requires: exists report and report.status = open.
    """
    result = failing_seed(tmp_path)
    (failed,) = result.failed
    other = opened(result.run)
    other.run_id = result.run.id + 1
    assert not tally_failed_url(other, failed)
    report = opened(result.run)
    report.status = CrawlReportStatus.written
    assert not tally_failed_url(report, failed)
    assert report.failed_urls == []
    assert report.changes == []
    assert other.failed_urls == []


def test_value_equality_FailedUrl() -> None:
    """Verify value type FailedUrl has structural equality."""
    row = FailedUrl(url=SEED, error="503 Service Unavailable", attempts=5)
    again = FailedUrl(url=SEED, error="503 Service Unavailable", attempts=5)
    assert row == again
    assert hash(row) == hash(again)
    assert row != dataclasses.replace(row, attempts=1)
    assert row != dataclasses.replace(row, error="connection refused")


def test_entity_fields_FailedUrl(tmp_path: Path) -> None:
    """Verify all declared fields on FailedUrl are present with correct types."""
    result = failing_seed(tmp_path)
    report = opened(result.run)
    for failed in result.failed:
        assert tally_failed_url(report, failed)
    (row,) = report.failed_urls
    assert isinstance(row, FailedUrl)
    assert row.url == SEED
    assert isinstance(row.error, str)
    assert row.error
    assert row.attempts == model.CONFIG.http_attempts
