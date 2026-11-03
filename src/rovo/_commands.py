"""The root's rules (rovo.allium): init and sync, composing config, crawl, mirror, report.

Each command returns the ExitCode the process exits with and writes its problems to
standard error. `sync` takes the Fetcher and the Clock it runs with, so tests drive it
without the network; `rovo.cli` builds the real ones.
"""

import importlib.metadata
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path

from rovo._config import (
    Configuration,
    SyncOptions,
    config_path,
    effective_policy,
    initial_scope,
    resolve_config,
    scope_hash,
    scope_of,
    signature_of,
    starter_config,
)
from rovo._convert.profiles import GENERIC, profile_for
from rovo._crawl.fetch import Fetcher
from rovo._crawl.model import RobotsMode, RunKind, RunMode, RunRequest
from rovo._crawl.run import drive_run, load_frontier, next_run_id, save_run
from rovo._mirror.finalise import finalise
from rovo._mirror.model import Mirror, Operator, Tier
from rovo._mirror.state import (
    Clock,
    ManifestError,
    load_mirror,
    manifest_path,
    save_mirror,
    write_text,
)
from rovo._mirror.urls import is_http_url
from rovo._report import (
    CrawlReport,
    CrawlReportStatus,
    ExitCode,
    ReportStatus,
    close_run,
    finalise_run_report,
    rank_and_write_report,
    tally_failed_url,
    tally_finalised_page,
)
from rovo._unfinished import NotInThisSlice


def init(site_url: str, out_dir: Path, profile_name: str | None = None) -> ExitCode:
    """Realises rovo.allium InitialiseMirror and RefuseInit.

    Writes rovo.toml and an empty manifest and never crawls. A mirror exists when its
    manifest does, parsable or not, or when rovo.toml does, so init never overwrites a
    file it would write.
    """
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


def sync(
    out_dir: Path,
    *,
    fetcher: Fetcher,
    clock: Clock,
    tier_installed: Callable[[Tier], bool] | None = None,
) -> ExitCode:
    """Realises rovo.allium RefuseSyncWithoutDirectory, StartSync and the report's rules.

    A missing directory or a missing or unparsable manifest exits usage with no report.
    Until the refusals slice, every other failed StartSync guard does too, rather than
    writing a refused report. A branch a later slice implements exits partial and
    leaves the previous report in place.
    """
    installed = tier_installed or _tier_installed
    if not out_dir.is_dir():
        return _refuse(f"sync: {out_dir} is not a directory")
    try:
        mirror = load_mirror(out_dir)
    except ManifestError as error:
        return _refuse(f"sync: no mirror in {out_dir} ({error})")
    settings = resolve_config(out_dir)
    problem = _start_problem(mirror, settings, installed)
    if problem is not None:
        return _refuse(f"sync: {problem}")
    try:
        return _start_sync(mirror, settings, fetcher, clock)
    except NotInThisSlice as stopped:
        sys.stderr.write(f"rovo: sync stopped: {stopped}\n")
        return ExitCode.partial


def _start_problem(
    mirror: Mirror, settings: Configuration, installed: Callable[[Tier], bool]
) -> str | None:
    """The first StartSync guard that fails, in the refusals' order, else None."""
    problems = (
        (not settings.valid, "invalid configuration: " + "; ".join(settings.problems)),
        (not settings.has_seeds, "invalid configuration: no root URL and no start URL"),
        (
            settings.unblocking_provider is not None,
            "invalid configuration: unblocking.provider is reserved",
        ),
        (
            settings.root_changed(mirror.recorded_root_url),
            "the root URL changed since the last run and needs confirmation",
        ),
        (
            settings.needs_browser and not installed(Tier.browser),
            "the configured browser tier is not installed",
        ),
        (
            settings.needs_stealth and not installed(Tier.stealth),
            "the configured stealth tier is not installed",
        ),
        (
            settings.robots is not RobotsMode.respect,
            "robots = ignore is only for an owner-testing run",
        ),
    )
    return next((problem for failed, problem in problems if failed), None)


def _start_sync(
    mirror: Mirror, settings: Configuration, fetcher: Fetcher, clock: Clock
) -> ExitCode:
    """StartSync, then the run, CloseRun, the finalise pass and RankAndWriteReport."""
    operator = Operator()
    options = SyncOptions(
        dry_run=False,
        confirmed=False,
        interactive=sys.stdin.isatty(),
        json_events=False,
        urls=(),
        paths=(),
    )
    seed = settings.root_url or settings.start_urls[0]
    profile = profile_for(seed, settings.profile_name) or GENERIC
    scope = scope_of(settings, profile)
    run_id = next_run_id(mirror.out_dir)
    kind = RunKind.update if mirror.is_populated else RunKind.initial
    policy = effective_policy(settings)
    mirror.profile = profile
    mirror.scope = scope
    mirror.recorded_root_url = settings.root_url
    mirror.processing_signature = signature_of(scope, profile)
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
        targets=frozenset(),
    )
    result = drive_run(request, load_frontier(mirror), fetcher, clock)
    for failed in result.failed:
        tally_failed_url(report, failed)
    close_run(report, result.run, result.frontier)
    finalised = finalise(operator, mirror, result.run.id, clock)
    for event in finalised.finalised:
        tally_finalised_page(report, event)
    save_mirror(mirror)
    save_run(result)  # Only now: a done frontier row must have its page saved.
    finalise_run_report(finalised.pass_, result.run)
    code = rank_and_write_report(report, result.run, clock)
    return ExitCode.partial if code is None else code


def _tier_installed(tier: Tier) -> bool:
    """The browser tier needs playwright; the stealth tier has no engine yet."""
    return tier is Tier.browser and importlib.util.find_spec("playwright") is not None


def _refuse(problem: str) -> ExitCode:
    sys.stderr.write(f"rovo: {problem}\n")
    return ExitCode.usage
