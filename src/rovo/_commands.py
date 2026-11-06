"""The root's rules (rovo.allium): init, sync, verify, index, report over config, crawl, mirror.

Each command returns the ExitCode the process exits with and writes its problems to
standard error. `sync` takes the Fetcher and the Timer it runs and paces with, so tests
drive it without the network and without sleeping; `rovo.cli` builds the real ones.
Only the mirror's modules load with this one: `verify`, `index` and `report` never crawl,
so `init` and `sync` import the configuration, the crawl and the report inside their
bodies, and `rovo verify`, `rovo index` and `rovo report` load neither httpx nor
rovo._crawl.
"""

import importlib.metadata
import importlib.util
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from rovo._convert.profiles import GENERIC, profile_for
from rovo._exit import ExitCode
from rovo._mirror.finalise import finalise
from rovo._mirror.indexes import index_pass, unreadable_page_file
from rovo._mirror.model import (
    CrawlScope,
    IndexesWritten,
    Mirror,
    Operator,
    PassKind,
    Tier,
    VerificationFinished,
)
from rovo._mirror.state import (
    ManifestError,
    load_mirror,
    manifest_path,
    report_path,
    save_mirror,
    write_text,
)
from rovo._mirror.urls import hostname_of, is_http_url
from rovo._mirror.verify import verify_pass
from rovo._unfinished import NotInThisSlice

if TYPE_CHECKING:
    from rovo._config import Configuration, SyncOptions
    from rovo._convert.model import Profile
    from rovo._crawl.fetch import Fetcher
    from rovo._crawl.model import ProgressEvent, Run
    from rovo._crawl.pace import Timer
    from rovo._crawl.run import CrawlResult
    from rovo._report import CrawlReport


def init(site_url: str, out_dir: Path, profile_name: str | None = None) -> ExitCode:
    """Realises rovo.allium InitialiseMirror and RefuseInit.

    Writes rovo.toml and an empty manifest and never crawls. A mirror exists when its
    manifest does, parsable or not, or when rovo.toml does, so init never overwrites a
    file it would write.
    """
    from rovo._config import (  # noqa: PLC0415  It loads rovo._crawl, which index never needs.
        config_path,
        initial_scope,
        signature_of,
        starter_config,
    )

    if not is_http_url(site_url):
        return _refuse(f"init: {site_url!r} is not an http or https URL")
    if manifest_path(out_dir).exists() or config_path(out_dir).exists():
        return _refuse(f"init: {out_dir} already holds a mirror")
    profile = profile_for(site_url, profile_name)
    if profile is None:
        return _refuse(f"init: no profile named {profile_name!r}")
    scope = initial_scope(site_url, profile)
    mirror = Mirror(
        out_dir=out_dir,
        scope=scope,
        profile=profile,
        processing_signature=signature_of(scope, profile),
    )
    write_text(config_path(out_dir), starter_config(site_url, profile))
    save_mirror(mirror)
    return ExitCode.ok


def sync(  # noqa: PLR0913  The command's seams and one keyword per sync option.
    out_dir: Path,
    *,
    fetcher: "Fetcher",
    clock: "Timer",
    tier_installed: Callable[[Tier], bool] | None = None,
    dry_run: bool = False,
    confirmed: bool = False,
    urls: Sequence[str] = (),
    paths: Sequence[str] = (),
    overrides: Sequence[str] = (),
    json_events: bool = False,
    progress: "Callable[[ProgressEvent], None] | None" = None,
) -> ExitCode:
    """Realises rovo.allium's sync refusals in order, ReportRefusal, StartSync and the rest.

    A missing directory or a missing or unparsable manifest exits usage with no report
    (RefuseSyncWithoutDirectory). The configuration is resolved from rovo.toml, the
    process's ROVO_<SECTION>__<FIELD> variables and the `overrides` (--set). Every later
    refusal, the first that applies, writes a refused report and exits usage, with no
    request. A dry run discovers, prints the identity of each row it would fetch, one a
    line on standard output, and fetches, converts and writes no page; it saves the
    manifest, the frontier and the run, and writes the report. `progress` receives the
    run's progress events, done last. A branch a later slice implements exits partial
    and leaves the previous report in place.
    """
    from rovo._config import (  # noqa: PLC0415  It loads rovo._crawl, which index never needs.
        SyncOptions,
        resolve_config,
    )
    from rovo._report import report_refusal  # noqa: PLC0415  It loads rovo._crawl.

    installed = tier_installed or _tier_installed
    if not out_dir.is_dir():
        return _refuse(f"sync: {out_dir} is not a directory")
    try:
        mirror = load_mirror(out_dir)
    except ManifestError as error:
        return _refuse(f"sync: no mirror in {out_dir} ({error})")
    settings = resolve_config(out_dir, os.environ, overrides)
    options = SyncOptions(
        dry_run=dry_run,
        confirmed=confirmed,
        interactive=sys.stdin.isatty(),
        json_events=json_events,
        urls=tuple(urls),
        paths=tuple(paths),
    )
    problem = _start_problem(mirror, settings, options, installed)
    if problem is not None:
        reason, detail = problem
        report_refusal(mirror, Operator(), options, settings, reason, clock=clock)
        return _refuse(f"sync: {detail}")
    try:
        return _start_sync(mirror, settings, options, fetcher, clock, progress=progress)
    except NotInThisSlice as stopped:
        sys.stderr.write(f"rovo: sync stopped: {stopped}\n")
        return ExitCode.partial


def _start_problem(
    mirror: Mirror,
    settings: "Configuration",
    options: "SyncOptions",
    installed: Callable[[Tier], bool],
) -> tuple[str, str] | None:
    """The first refusal that applies, in the specification's order: (reason, detail).

    The reason is the refused report's refusal_reason; the detail is standard error's.
    """
    from rovo._crawl.model import RobotsMode  # noqa: PLC0415  Only a sync loads the crawl.

    bad_config = "invalid configuration"
    tier_missing = "configured tier is not installed"
    robots = "robots = ignore is only for an owner-testing run"
    # The resolved scope's hosts (scope_of); without a seed the refusal before it applies.
    allowed = (
        _scope(settings).allowed_hosts
        if settings.valid and settings.has_seeds
        else frozenset[str]()
    )
    off_host = [
        url for url in options.urls if not is_http_url(url) or hostname_of(url) not in allowed
    ]
    unknown = [path for path in options.paths if path not in mirror.page_paths]
    problems = (
        (not settings.valid, bad_config, f"{bad_config}: " + "; ".join(settings.problems)),
        (not settings.has_seeds, bad_config, f"{bad_config}: no root URL and no start URL"),
        (
            settings.unblocking_provider is not None,
            bad_config,
            f"{bad_config}: unblocking.provider is reserved",
        ),
        (
            settings.root_changed(mirror.recorded_root_url) and not options.confirmed,
            "changed root requires confirmation",
            "the root URL changed since the last run and needs confirmation (--yes)",
        ),
        (
            bool(off_host),
            "invalid or off-host target",
            f"not an http(s) URL on an allowed host: {', '.join(off_host)}",
        ),
        (
            bool(unknown),
            "unknown target path",
            f"not a written page's path: {', '.join(unknown)}",
        ),
        (
            settings.needs_browser and not installed(Tier.browser),
            tier_missing,
            "the configured browser tier is not installed",
        ),
        (
            settings.needs_stealth and not installed(Tier.stealth),
            tier_missing,
            "the configured stealth tier is not installed",
        ),
        (settings.robots is not RobotsMode.respect, robots, robots),
    )
    return next(
        ((reason, detail) for failed, reason, detail in problems if failed),
        None,
    )


def _profile(settings: "Configuration") -> "Profile":
    """rovo.allium's profile_for the root URL, else the first start URL."""
    seed = settings.root_url or settings.start_urls[0]
    return profile_for(seed, settings.profile_name) or GENERIC


def _scope(settings: "Configuration") -> CrawlScope:
    """rovo.allium's scope_of the settings and their profile: the hosts StartSync tests."""
    from rovo._config import scope_of  # noqa: PLC0415  Only a sync loads the configuration.

    return scope_of(settings, _profile(settings))


def _start_sync(  # noqa: PLR0913  StartSync's inputs, the seams and the progress sink.
    mirror: Mirror,
    settings: "Configuration",
    options: "SyncOptions",
    fetcher: "Fetcher",
    clock: "Timer",
    *,
    progress: "Callable[[ProgressEvent], None] | None",
) -> ExitCode:
    """StartSync, then the run, CloseRun, the finalise pass and RankAndWriteReport.

    An operator interrupt or an error during the run ends it interrupted (InterruptSync,
    RecordCrash); one after it (RecordCrashAfterRun) writes the open report as it stands,
    saves neither the manifest nor the frontier, and records the run in runs.json.
    """
    # Only a sync loads the configuration, the crawl and the report (rovo index never).
    from rovo._config import (  # noqa: PLC0415  Only a sync loads the crawl.
        effective_policy,
        scope_hash,
        scope_of,
        signature_of,
    )
    from rovo._crawl.model import (  # noqa: PLC0415  Only a sync loads the crawl.
        ProgressEvent,
        RobotsMode,
        RunKind,
        RunMode,
        RunRequest,
    )
    from rovo._crawl.run import (  # noqa: PLC0415  Only a sync loads the crawl.
        drive_run,
        load_frontier,
        next_run_id,
        record_run,
    )
    from rovo._report import (  # noqa: PLC0415  It loads rovo._crawl, which index never needs.
        CrawlReport,
        CrawlReportStatus,
        ReportStatus,
        announce_backoff,
        rank_and_write_report,
        record_crash_after_run,
    )

    operator = Operator()
    profile = _profile(settings)
    scope = scope_of(settings, profile)
    run_id = next_run_id(mirror.out_dir)
    kind = RunKind.update if mirror.is_populated else RunKind.initial
    policy = effective_policy(settings)
    mirror.profile = profile
    mirror.scope = scope
    mirror.recorded_root_url = settings.root_url
    mirror.prune = settings.prune
    mirror.processing_signature = signature_of(scope, profile)
    held = {page.path: page.identity for page in mirror.written_pages}
    targets = frozenset(scope.identity_of(url) for url in options.urls) | frozenset(
        held[path] for path in options.paths
    )  # resolve_targets: each named URL normalised, each named path its page's identity.
    report = CrawlReport(
        mirror=mirror,
        operator=operator,
        run_id=run_id,
        kind=kind,
        mode=RunMode.standard,
        report_status=ReportStatus.finished,
        exit_code=ExitCode.ok,
        configuration=settings,
        options=options,
        tool_version=importlib.metadata.version("rovo"),
        started_at=clock.now(),
        status=CrawlReportStatus.open,
        effective_policy=policy,
        robots_ignored=policy.robots is RobotsMode.ignore,
        targets=targets,
    )
    request = RunRequest(
        operator=operator,
        mirror=mirror,
        id=run_id,
        kind=kind,
        mode=RunMode.standard,
        scope_hash=scope_hash(scope),
        owned_hosts=frozenset(),
        policy=policy,
        dry_run=options.dry_run,
        interactive=options.interactive,
        render_mode=settings.render_mode,
        stealth_mode=settings.stealth_mode,
        max_age=settings.max_age,
        refollow_unchanged_links=settings.refollow_unchanged_links,
        targets=targets,
    )
    result = drive_run(
        request,
        load_frontier(mirror),
        fetcher,
        clock,
        progress=progress,
        on_backoff=None if progress is None else lambda event: progress(announce_backoff(event)),
        on_failure=_failure_handler(mirror),
    )
    saved = False
    try:
        saved = _after_run(report, result, clock)
    except NotInThisSlice:
        raise
    except (KeyboardInterrupt, Exception) as error:  # RecordCrashAfterRun's guidance.
        if not record_crash_after_run(mirror, result.run, report, _error_text(error)):
            raise
        if not saved:
            record_run(result.run)
    code = rank_and_write_report(report, result.run, clock)
    if code is not None and progress is not None:
        progress(ProgressEvent(event="done", host=None, until=None, url=None))
    return ExitCode.partial if code is None else code


def _after_run(report: "CrawlReport", result: "CrawlResult", clock: "Timer") -> bool:
    """The run's events tallied, CloseRun, the finalise pass and the saves.

    True once the run is saved (save_run), so a later crash does not record it twice.
    """
    from rovo._crawl.run import (  # noqa: PLC0415  Only a sync loads the crawl.
        dry_run_listing,
        save_run,
    )
    from rovo._report import (  # noqa: PLC0415  It loads rovo._crawl, which index never needs.
        close_run,
        finalise_run_report,
        take_broken_links,
        tally_discovery_problem,
        tally_failed_url,
        tally_finalised_page,
        tally_removal,
    )

    mirror = report.mirror
    for problem in result.discovery_failed:
        tally_discovery_problem(report, problem)
    for failed in result.failed:
        tally_failed_url(report, failed)
    for removed in result.removed:
        tally_removal(report, removed)
    close_run(report, result.run, result.frontier)
    if report.options.dry_run:  # CloseRun raised ReportReady at once; the listing is printed.
        sys.stdout.writelines(
            f"{identity}\n" for identity in dry_run_listing(result.run, result.frontier)
        )
        save_mirror(mirror)
        save_run(result)
        return True
    finalised = finalise(report.operator, mirror, result.run.id, clock)  # CloseRun's pass.
    for removed in finalised.removed:
        tally_removal(report, removed)
    for event in finalised.finalised:
        tally_finalised_page(report, event)
    if finalised.rewritten is not None:  # FinishLinkPass fires on every pending pass.
        take_broken_links(report, finalised.rewritten)
    if finalised.indexes is not None:  # BuildIndexes completes every pending pass.
        finalise_run_report(finalised.indexes.pass_, result.run)
    save_mirror(mirror)
    save_run(result)  # Only now: a done frontier row must have its page saved.
    return True


def _failure_handler(mirror: Mirror) -> "Callable[[Run, BaseException], None]":
    """The root's InterruptSync and RecordCrash, as the run's failure callable."""
    from rovo._report import interrupt_sync, record_crash  # noqa: PLC0415  It loads rovo._crawl.

    def handle(run: "Run", error: BaseException) -> None:
        if isinstance(error, KeyboardInterrupt):
            interrupt_sync(mirror, run)
        else:
            record_crash(mirror, run, _error_text(error))

    return handle


def _error_text(error: BaseException) -> str:
    """The crash's error text: "<ExceptionType>: <message>"."""
    return f"{type(error).__name__}: {error}"


def index(out_dir: Path) -> ExitCode:
    """Realises rovo.allium RebuildIndex, RefuseRebuildIndex and FinishIndexCommand.

    A missing directory, a manifest that does not load, or a written page whose file is
    missing or not UTF-8 exits usage and writes nothing. Otherwise an index pass with no
    run rebuilds the index files offline from the manifest: links are not re-resolved,
    and no state file, run or report is written.
    """
    if not out_dir.is_dir():
        return _refuse(f"index: {out_dir} is not a directory")
    try:
        mirror = load_mirror(out_dir)
    except ManifestError as error:
        return _refuse(f"index: no mirror in {out_dir} ({error})")
    unreadable = unreadable_page_file(mirror)
    if unreadable is not None:
        return _refuse(f"index: the page file {unreadable} is missing or not UTF-8")
    code = finish_index_command(index_pass(Operator(), mirror))
    return ExitCode.partial if code is None else code


def report(out_dir: Path) -> ExitCode:
    """Realises rovo.allium ShowReport and RefuseShowReport.

    Prints crawl-report.json as written, with a final newline, on standard output. With
    no directory, no loadable manifest, or no report file that reads as JSON
    (latest_report is null), the problem goes to standard error and it exits usage.
    """
    if not out_dir.is_dir():
        return _refuse(f"report: {out_dir} is not a directory")
    try:
        load_mirror(out_dir)
    except ManifestError as error:
        return _refuse(f"report: no mirror in {out_dir} ({error})")
    path = report_path(out_dir)
    try:
        text = path.read_text(encoding="utf-8")
        json.loads(text)
    except (OSError, ValueError) as error:
        return _refuse(f"report: no readable report at {path} ({error})")
    sys.stdout.write(text if text.endswith("\n") else f"{text}\n")
    return ExitCode.ok


def verify(out_dir: Path) -> ExitCode:
    """Realises rovo.allium Verify and RefuseVerify.

    With no directory or no loadable manifest the problem goes to standard error and it
    exits usage. Otherwise a verify pass with no run checks the mirror on disk offline
    and ReportVerification prints what it found; nothing is written.
    """
    if not out_dir.is_dir():
        return _refuse(f"verify: {out_dir} is not a directory")
    try:
        mirror = load_mirror(out_dir)
    except ManifestError as error:
        return _refuse(f"verify: no mirror in {out_dir} ({error})")
    finished = verify_pass(Operator(), mirror)
    return ExitCode.partial if finished is None else report_verification(finished)


def report_verification(finished: VerificationFinished) -> ExitCode:
    """Realises rovo.allium ReportVerification: the findings, the tallies, the exit code.

    One `<reason> <path> <detail>` line per finding on standard output, then one
    `<gate> <pages>` line per gate that failed on any written page when it was measured,
    sorted by gate. It exits ok with no finding and quality with any; the tallies never
    move the exit code.
    """
    for failure in finished.failures:
        line = f"{failure.reason.value} {failure.path} {failure.detail}"
        sys.stdout.write(f"{line.rstrip()}\n")
    tallies = Counter(
        gate.value for page in finished.mirror.written_pages for gate in page.quality.failed
    )
    for gate, pages in sorted(tallies.items()):
        sys.stdout.write(f"{gate} {pages}\n")
    return ExitCode.quality if finished.failures else ExitCode.ok


def finish_index_command(written: IndexesWritten | None) -> ExitCode | None:
    """Realises rovo.allium FinishIndexCommand: ok after an index pass, else None."""
    if written is None or written.pass_.kind is not PassKind.index:
        return None
    return ExitCode.ok


def _tier_installed(tier: Tier) -> bool:
    """The browser tier needs playwright; the stealth tier has no engine yet."""
    return tier is Tier.browser and importlib.util.find_spec("playwright") is not None


def _refuse(problem: str) -> ExitCode:
    sys.stderr.write(f"rovo: {problem}\n")
    return ExitCode.usage
