"""The crawl report, crawl-report.json (rovo.allium): serves the command and the root.

The report is written once, by RankAndWriteReport, atomically. It holds every
CrawlReport field but the mirror, the operator and its open or written status; every
list is sorted by URL or path, sets are sorted lists, durations are seconds and times
are ISO 8601 UTC. May import the modules below it; never rovo._commands or rovo.cli.
"""

import enum
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from rovo._config import CONFIG, Configuration, SyncOptions, encode_configuration
from rovo._convert.model import QualityFlag, QualityGate
from rovo._crawl.model import (
    CrawlPolicy,
    DiscoveryFailed,
    DiscoveryProblem,
    Frontier,
    Host,
    RobotsMode,
    Run,
    RunKind,
    RunMode,
    RunStatus,
    UrlFailed,
)
from rovo._exit import ExitCode as ExitCode  # noqa: PLC0414  An explicit re-export: callers import it from here.
from rovo._mirror.model import (
    BrokenLink,
    LinksRewritten,
    Mirror,
    MirrorPass,
    Operator,
    PageFinalised,
    PageRemoved,
    PassKind,
    StoreOutcome,
    Tier,
)
from rovo._mirror.state import Clock, timestamp, write_json

_SCORE_PLACES = 4
_REPORT_FILE = "crawl-report.json"


class ChangeKind(enum.Enum):
    """The kind of one row of the report's changes."""

    added = "added"
    changed = "changed"
    unchanged = "unchanged"
    removed = "removed"
    moved = "moved"
    failed = "failed"


class ReportStatus(enum.Enum):
    """How the command ended."""

    finished = "finished"
    interrupted = "interrupted"
    refused = "refused"


class CrawlReportStatus(enum.Enum):
    """CrawlReport.status: open while the run goes, written once."""

    open = "open"
    written = "written"


@dataclass(frozen=True, kw_only=True)
class HostReport:
    """One host's row of the report."""

    host: str
    fetched: int
    blocked: int
    block_rate: float
    tiers_used: frozenset[Tier]
    breaker_tripped: bool
    robots_ignored: bool
    render_escalations: int
    retry_after_honored: int
    effective_policy: CrawlPolicy


@dataclass(frozen=True, kw_only=True)
class GateFailure:
    """Pages failing one gate."""

    gate: QualityGate
    pages: int


@dataclass(frozen=True, kw_only=True)
class QualitySummary:
    """Gate tallies count gates only, never other flags."""

    mean_score: float
    p10_score: float
    gate_failures: tuple[GateFailure, ...]


@dataclass(frozen=True, kw_only=True)
class Change:
    """One row of the report's changes."""

    kind: ChangeKind
    url: str
    path: str | None
    moved_from: str | None


@dataclass(frozen=True, kw_only=True)
class BlockedUrl:
    """A URL a block verdict stopped."""

    url: str
    status: int
    signature: str
    tier: Tier


@dataclass(frozen=True, kw_only=True)
class FailedUrl:
    """A URL whose fetch failed."""

    url: str
    error: str
    attempts: int


@dataclass(frozen=True, kw_only=True)
class DiscoveryProblemRow:
    """A problem discovery reported."""

    url: str
    problem: DiscoveryProblem


@dataclass(frozen=True, kw_only=True)
class LowConfidencePage:
    """One low-confidence page of the report."""

    path: str
    url: str
    quality_score: float
    flags: frozenset[QualityFlag]
    touched_this_run: bool


def _empty_summary() -> QualitySummary:
    return QualitySummary(mean_score=0.0, p10_score=0.0, gate_failures=())


@dataclass(kw_only=True, eq=False)
class CrawlReport:
    """The crawl report (rovo.allium 197); lists with no row type in this slice stay empty."""

    mirror: Mirror
    operator: Operator
    run_id: int | None
    kind: RunKind
    mode: RunMode
    report_status: ReportStatus
    exit_code: ExitCode
    configuration: Configuration
    options: SyncOptions
    tool_version: str
    started_at: datetime
    status: CrawlReportStatus
    error: str | None = None
    refusal_reason: str | None = None
    targets: frozenset[str] = frozenset()
    declared_owned_hosts: frozenset[str] = frozenset()
    baseline_run_id: int | None = None
    preceding_run_id: int | None = None
    requested_owner_test: None = None
    effective_policy: CrawlPolicy | None = None
    unresolved_urls: frozenset[str] = frozenset()
    robots_ignored: bool = False
    discovered: int = 0
    fetched: int = 0
    converted: int = 0
    skipped_unchanged: int = 0
    bytes_fetched: int = 0
    budget_stopped: bool = False
    breaker_tripped: bool = False
    per_host: list[HostReport] = field(default_factory=list)
    quality_summary: QualitySummary = field(default_factory=_empty_summary)
    scores: list[float] = field(default_factory=list)
    blocked_urls: list[BlockedUrl] = field(default_factory=list)
    failed_urls: list[FailedUrl] = field(default_factory=list)
    skipped_urls: list[str] = field(default_factory=list)
    discovery_problems: list[DiscoveryProblemRow] = field(default_factory=list)
    low_confidence_pages: list[LowConfidencePage] = field(default_factory=list)
    # The pass's BrokenLink rows (TakeBrokenLinks); crawl-report.json writes only those.
    broken_links: list[object] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    finished_at: datetime | None = None

    @property
    def touched_low_confidence(self) -> list[LowConfidencePage]:
        """The low-confidence pages touched this run."""
        return [page for page in self.low_confidence_pages if page.touched_this_run]

    @property
    def has_failures(self) -> bool:
        """A failed or blocked URL, or a discovery problem."""
        return bool(self.failed_urls or self.blocked_urls or self.discovery_problems)

    @property
    def quality_failed(self) -> bool:
        """A touched low-confidence page, or a broken link."""
        return bool(self.touched_low_confidence or self.broken_links)

    def is_open_for(self, mirror: Mirror, run_id: int | None) -> bool:
        """CrawlReport{mirror, run_id} exists and is open."""
        return (
            self.mirror is mirror
            and run_id is not None
            and self.run_id == run_id
            and self.status is CrawlReportStatus.open
        )


def report_path(out_dir: Path) -> Path:
    """<out>/crawl-report.json."""
    return out_dir / _REPORT_FILE


def tally_finalised_page(report: CrawlReport, finalised: PageFinalised) -> bool:
    """Realises rovo.allium TallyFinalisedPage."""
    pass_ = finalised.pass_
    if pass_.run_id is None or not report.is_open_for(pass_.mirror, pass_.run_id):
        return False
    page = finalised.page
    report.scores.append(page.quality.score)
    if page.low_confidence:
        report.low_confidence_pages.append(
            LowConfidencePage(
                path=page.path,
                url=page.identity,
                quality_score=page.quality.score,
                flags=page.flags,
                touched_this_run=finalised.seen_this_run,
            )
        )
    unchanged = finalised.outcome is StoreOutcome.unchanged
    if finalised.seen_this_run and unchanged:
        report.skipped_unchanged += 1
    if finalised.seen_this_run and not unchanged:
        report.converted += 1
    if finalised.seen_this_run or not unchanged:
        report.changes.append(
            Change(
                kind=ChangeKind(finalised.outcome.value),
                url=page.identity,
                path=page.path,
                moved_from=finalised.previous_path,
            )
        )
    return True


def tally_removal(report: CrawlReport, removed: PageRemoved) -> bool:
    """Realises rovo.allium TallyRemoval: a removed change; False when its guards fail.

    The open report of the removal's mirror gains one removed change: the page's identity
    and the path a removed page keeps.
    """
    if report.mirror is not removed.mirror or report.status is not CrawlReportStatus.open:
        return False
    page = removed.page
    report.changes.append(
        Change(kind=ChangeKind.removed, url=page.identity, path=page.path, moved_from=None)
    )
    return True


def tally_failed_url(report: CrawlReport, failed: UrlFailed) -> bool:
    """Realises rovo.allium TallyFailedUrl: a failed_urls row and a failed change."""
    if not report.is_open_for(failed.run.target, failed.run.id):
        return False
    report.failed_urls.append(
        FailedUrl(url=failed.url, error=failed.error, attempts=failed.attempts)
    )
    report.changes.append(
        Change(kind=ChangeKind.failed, url=failed.url, path=None, moved_from=None)
    )
    return True


def tally_discovery_problem(report: CrawlReport, failed: DiscoveryFailed) -> bool:
    """Realises rovo.allium TallyDiscoveryProblem: a discovery_problems row."""
    if not report.is_open_for(failed.run.target, failed.run.id):
        return False
    report.discovery_problems.append(DiscoveryProblemRow(url=failed.url, problem=failed.problem))
    return True


def take_broken_links(report: CrawlReport, rewritten: LinksRewritten) -> bool:
    """Realises rovo.allium TakeBrokenLinks; False when its guards do not hold."""
    if not report.is_open_for(rewritten.mirror, rewritten.pass_.run_id):
        return False
    report.broken_links = list(rewritten.broken)
    return True


def close_run(report: CrawlReport, run: Run, frontier: Frontier) -> bool:
    """Realises rovo.allium CloseRun: True when it requested the finalise pass.

    discovered_count is the number of the frontier's rows after discovery, which
    DropStaleObservations recorded. A dry run's report is ready at once: False, with no
    finalise pass requested, and RankAndWriteReport follows.
    """
    del frontier  # Its rows after discovery are counted in run.discovered_count.
    if not report.is_open_for(run.target, run.id):
        return False
    report.report_status = (
        ReportStatus.interrupted if run.status is RunStatus.interrupted else ReportStatus.finished
    )
    report.error = run.error
    report.unresolved_urls = run.unresolved_urls
    report.per_host = host_reports(run.hosts, run.policy)
    report.discovered = run.discovered_count
    report.fetched = run.fetch_attempts
    report.bytes_fetched = run.bytes_fetched
    report.budget_stopped = run.budget_stopped
    return not report.options.dry_run


def finalise_run_report(pass_: MirrorPass, run: Run | None) -> bool:
    """Realises rovo.allium FinaliseRunReport: True when it raised ReportReady."""
    if pass_.kind is not PassKind.finalise or pass_.run_id is None:
        return False
    return run is not None and run.target is pass_.mirror and run.id == pass_.run_id


def rank_and_write_report(report: CrawlReport, run: Run, clock: Clock) -> ExitCode | None:
    """Realises rovo.allium RankAndWriteReport; writes <out>/crawl-report.json."""
    if not report.is_open_for(run.target, run.id):
        return None
    target_skipped = any(target in report.skipped_urls for target in run.targets)
    code = most_severe(
        [
            ExitCode.partial
            if report.has_failures
            or report.error is not None
            or run.status is RunStatus.interrupted
            or run.budget_stopped
            else ExitCode.ok,
            ExitCode.partial if target_skipped else ExitCode.ok,
            ExitCode.partial if run.is_owner_testing and run.unresolved_urls else ExitCode.ok,
            ExitCode.blocked if run.has_tripped_host else ExitCode.ok,
            ExitCode.quality
            if report.configuration.fail_on_low_quality and report.quality_failed
            else ExitCode.ok,
        ]
    )
    report.exit_code = code
    report.quality_summary = summarise(
        report.scores, report.low_confidence_pages, CONFIG.report_percentile
    )
    report.status = CrawlReportStatus.written
    report.finished_at = clock.now()
    write_json(report_path(report.mirror.out_dir), encode_report(report))
    return code


def most_severe(codes: Iterable[ExitCode]) -> ExitCode:
    """The most severe code; ok for none."""
    return max(codes, key=lambda code: code.number, default=ExitCode.ok)


def summarise(
    scores: Sequence[float], low_confidence_pages: Sequence[LowConfidencePage], percentile: float
) -> QualitySummary:
    """rovo.allium summarise: mean and percentile to four places, gate failures by gate."""
    gates = {gate.value: gate for gate in QualityGate}
    failures: dict[QualityGate, int] = {}
    for page in low_confidence_pages:
        for flag in page.flags:
            if flag.value in gates:
                failures[gates[flag.value]] = failures.get(gates[flag.value], 0) + 1
    gate_failures = tuple(
        GateFailure(gate=gate, pages=count)
        for gate, count in sorted(failures.items(), key=lambda item: item[0].value)
    )
    if not scores:
        return QualitySummary(mean_score=0.0, p10_score=0.0, gate_failures=gate_failures)
    ordered = sorted(scores)
    return QualitySummary(
        mean_score=round(sum(scores) / len(scores), _SCORE_PLACES),
        p10_score=round(ordered[round(percentile * (len(ordered) - 1))], _SCORE_PLACES),
        gate_failures=gate_failures,
    )


def host_reports(hosts: Sequence[Host], policy: CrawlPolicy) -> list[HostReport]:
    """rovo.allium host_reports: one row per host, sorted by name."""
    return [
        HostReport(
            host=host.name,
            fetched=host.fetched,
            blocked=host.blocked,
            block_rate=host.block_rate,
            tiers_used=host.tiers_used,
            breaker_tripped=host.breaker_tripped,
            robots_ignored=policy.robots is RobotsMode.ignore,
            render_escalations=host.render_escalations,
            retry_after_honored=host.retry_after_honored,
            effective_policy=policy,
        )
        for host in sorted(hosts, key=lambda host: host.name)
    ]


def encode_report(report: CrawlReport) -> dict[str, object]:
    """crawl-report.json: every field but the mirror, the operator and the status."""
    return {
        "run_id": report.run_id,
        "kind": report.kind.value,
        "mode": report.mode.value,
        "report_status": report.report_status.value,
        "exit_code": report.exit_code.value,
        "error": report.error,
        "refusal_reason": report.refusal_reason,
        "configuration": encode_configuration(report.configuration),
        "options": {
            "dry_run": report.options.dry_run,
            "confirmed": report.options.confirmed,
            "interactive": report.options.interactive,
            "json_events": report.options.json_events,
            "urls": sorted(report.options.urls),
            "paths": sorted(report.options.paths),
            "owner_test": None,
        },
        "tool_version": report.tool_version,
        "targets": sorted(report.targets),
        "declared_owned_hosts": sorted(report.declared_owned_hosts),
        "baseline_run_id": report.baseline_run_id,
        "preceding_run_id": report.preceding_run_id,
        "requested_owner_test": None,
        "effective_policy": _policy(report.effective_policy),
        "unresolved_urls": sorted(report.unresolved_urls),
        "robots_ignored": report.robots_ignored,
        "discovered": report.discovered,
        "fetched": report.fetched,
        "converted": report.converted,
        "skipped_unchanged": report.skipped_unchanged,
        "bytes_fetched": report.bytes_fetched,
        "budget_stopped": report.budget_stopped,
        "breaker_tripped": report.breaker_tripped,
        "per_host": [_host(row) for row in report.per_host],
        "quality_summary": {
            "mean_score": report.quality_summary.mean_score,
            "p10_score": report.quality_summary.p10_score,
            "gate_failures": [
                {"gate": row.gate.value, "pages": row.pages}
                for row in report.quality_summary.gate_failures
            ],
        },
        "scores": list(report.scores),
        "blocked_urls": [
            {
                "url": row.url,
                "status": row.status,
                "signature": row.signature,
                "tier": row.tier.value,
            }
            for row in sorted(report.blocked_urls, key=lambda row: row.url)
        ],
        "failed_urls": [
            {"url": row.url, "error": row.error, "attempts": row.attempts}
            for row in sorted(report.failed_urls, key=lambda row: row.url)
        ],
        "skipped_urls": sorted(report.skipped_urls),
        "discovery_problems": [
            {"url": row.url, "problem": row.problem.value}
            for row in sorted(report.discovery_problems, key=lambda row: row.url)
        ],
        "low_confidence_pages": [
            {
                "path": row.path,
                "url": row.url,
                "quality_score": row.quality_score,
                "flags": sorted(flag.value for flag in row.flags),
                "touched_this_run": row.touched_this_run,
            }
            for row in sorted(report.low_confidence_pages, key=lambda row: row.path)
        ],
        "broken_links": [
            {"from_path": row.from_path, "href": row.href, "reason": row.reason.value}
            for row in sorted(
                (row for row in report.broken_links if isinstance(row, BrokenLink)),
                key=lambda row: (row.from_path, row.href),
            )
        ],
        "changes": [
            {
                "kind": row.kind.value,
                "url": row.url,
                "path": row.path,
                "moved_from": row.moved_from,
            }
            for row in sorted(report.changes, key=lambda row: (row.path or "", row.url))
        ],
        "started_at": timestamp(report.started_at),
        "finished_at": None if report.finished_at is None else timestamp(report.finished_at),
    }


def _policy(policy: CrawlPolicy | None) -> dict[str, object] | None:
    if policy is None:
        return None
    return {
        name: value.total_seconds()
        if isinstance(value, timedelta)
        else getattr(value, "value", value)
        for name, value in vars(policy).items()
    }


def _host(row: HostReport) -> dict[str, object]:
    return {
        "host": row.host,
        "fetched": row.fetched,
        "blocked": row.blocked,
        "block_rate": row.block_rate,
        "tiers_used": sorted(tier.value for tier in row.tiers_used),
        "breaker_tripped": row.breaker_tripped,
        "robots_ignored": row.robots_ignored,
        "render_escalations": row.render_escalations,
        "retry_after_honored": row.retry_after_honored,
        "effective_policy": _policy(row.effective_policy),
    }
