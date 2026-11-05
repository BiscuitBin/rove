"""The root's rules (rovo.allium): init, sync and index, composing config, crawl, mirror, report.

Each command returns the ExitCode the process exits with and writes its problems to
standard error. `sync` takes the Fetcher and the Timer it runs and paces with, so tests
drive it without the network and without sleeping; `rovo.cli` builds the real ones.
Only the mirror's modules load with this one: `index` never crawls, so `init` and `sync`
import the configuration, the crawl and the report inside their bodies, and `rovo index`
loads neither httpx nor rovo._crawl.
"""

import importlib.metadata
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from rovo._convert.profiles import GENERIC, profile_for
from rovo._exit import ExitCode
from rovo._mirror.finalise import finalise
from rovo._mirror.indexes import index_pass, unreadable_page_file
from rovo._mirror.model import IndexesWritten, Mirror, Operator, PassKind, Tier
from rovo._mirror.state import (
    ManifestError,
    load_mirror,
    manifest_path,
    save_mirror,
    write_text,
)
from rovo._mirror.urls import is_http_url
from rovo._unfinished import NotInThisSlice

if TYPE_CHECKING:
    from rovo._config import Configuration
    from rovo._crawl.fetch import Fetcher
    from rovo._crawl.pace import Timer


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


def sync(
    out_dir: Path,
    *,
    fetcher: "Fetcher",
    clock: "Timer",
    tier_installed: Callable[[Tier], bool] | None = None,
    dry_run: bool = False,
) -> ExitCode:
    """Realises rovo.allium RefuseSyncWithoutDirectory, StartSync and the report's rules.

    A dry run discovers, prints the identity of each row it would fetch, one a line on
    standard output, and fetches, converts and writes no page; it saves the manifest,
    the frontier and the run, and writes the report. A missing directory or a missing or
    unparsable manifest exits usage with no report.
    Until the refusals slice, every other failed StartSync guard does too, rather than
    writing a refused report. A branch a later slice implements exits partial and
    leaves the previous report in place.
    """
    from rovo._config import (  # noqa: PLC0415  It loads rovo._crawl, which index never needs.
        resolve_config,
    )

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
        return _start_sync(mirror, settings, fetcher, clock, dry_run=dry_run)
    except NotInThisSlice as stopped:
        sys.stderr.write(f"rovo: sync stopped: {stopped}\n")
        return ExitCode.partial


def _start_problem(
    mirror: Mirror, settings: "Configuration", installed: Callable[[Tier], bool]
) -> str | None:
    """The first StartSync guard that fails, in the refusals' order, else None."""
    from rovo._crawl.model import RobotsMode  # noqa: PLC0415  Only a sync loads the crawl.

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
    mirror: Mirror, settings: "Configuration", fetcher: "Fetcher", clock: "Timer", *, dry_run: bool
) -> ExitCode:
    """StartSync, then the run, CloseRun, the finalise pass and RankAndWriteReport."""
    # Only a sync loads the configuration, the crawl and the report (rovo index never).
    from rovo._config import (  # noqa: PLC0415  Only a sync loads the crawl.
        SyncOptions,
        effective_policy,
        scope_hash,
        scope_of,
        signature_of,
    )
    from rovo._crawl.model import (  # noqa: PLC0415  Only a sync loads the crawl.
        RobotsMode,
        RunKind,
        RunMode,
        RunRequest,
    )
    from rovo._crawl.run import (  # noqa: PLC0415  Only a sync loads the crawl.
        drive_run,
        dry_run_listing,
        load_frontier,
        next_run_id,
        save_run,
    )
    from rovo._report import (  # noqa: PLC0415  It loads rovo._crawl, which index never needs.
        CrawlReport,
        CrawlReportStatus,
        ReportStatus,
        close_run,
        finalise_run_report,
        rank_and_write_report,
        take_broken_links,
        tally_discovery_problem,
        tally_failed_url,
        tally_finalised_page,
    )

    operator = Operator()
    options = SyncOptions(
        dry_run=dry_run,
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
    for problem in result.discovery_failed:
        tally_discovery_problem(report, problem)
    for failed in result.failed:
        tally_failed_url(report, failed)
    close_run(report, result.run, result.frontier)
    if not options.dry_run:  # CloseRun requested the finalise pass.
        finalised = finalise(operator, mirror, result.run.id, clock)
        for event in finalised.finalised:
            tally_finalised_page(report, event)
        if finalised.rewritten is not None:  # FinishLinkPass fires on every pending pass.
            take_broken_links(report, finalised.rewritten)
        save_mirror(mirror)
        save_run(result)  # Only now: a done frontier row must have its page saved.
        if finalised.indexes is not None:  # BuildIndexes completes every pending pass.
            finalise_run_report(finalised.indexes.pass_, result.run)
    else:  # CloseRun raised ReportReady at once; the dry run's listing is printed.
        sys.stdout.writelines(
            f"{identity}\n" for identity in dry_run_listing(result.run, result.frontier)
        )
        save_mirror(mirror)
        save_run(result)
    code = rank_and_write_report(report, result.run, clock)
    return ExitCode.partial if code is None else code


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
