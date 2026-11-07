"""The root's rules (rovo.allium): init, sync, verify, index, report and fetch.

Each command returns the ExitCode the process exits with and writes its problems to
standard error. `sync` and `fetch` take the Fetcher and the Timer they run and pace with,
and the factory of the browser engine they render with, so tests drive them without the
network, a browser or sleeping; `rovo.cli` builds the real ones.
Only the mirror's modules load with this one: `verify`, `index` and `report` never crawl,
so `init`, `sync` and `fetch` import the configuration, the crawl and the report inside
their bodies, and `rovo verify`, `rovo index` and `rovo report` load neither httpx nor
rovo._crawl. Owner testing has no command-line spelling yet (rovo.allium open question):
`save_ownership` and `sync(owner_test=...)` are reached in process only, and no terminal
prompt ships for a challenge (crawl.allium open question), so nothing here reads
standard input.
"""

import importlib.metadata
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from rovo._convert.profiles import GENERIC, profile_for, profile_named
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
    from rovo._crawl.browser import BrowserEngine, EngineFactory
    from rovo._crawl.fetch import Fetcher
    from rovo._crawl.model import (
        BreakerTripped,
        CrawlPolicy,
        OwnerTestingWarningIssued,
        OwnerTestOptions,
        ProgressEvent,
        Run,
    )
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
    engine: "EngineFactory | None" = None,
    dry_run: bool = False,
    confirmed: bool = False,
    urls: Sequence[str] = (),
    paths: Sequence[str] = (),
    overrides: Sequence[str] = (),
    json_events: bool = False,
    progress: "Callable[[ProgressEvent], None] | None" = None,
    owner_test: "OwnerTestOptions | None" = None,
    interactive: bool | None = None,
) -> ExitCode:
    """Realises rovo.allium's sync refusals in order, ReportRefusal, StartSync and the rest.

    A missing directory or a missing or unparsable manifest exits usage with no report
    (RefuseSyncWithoutDirectory). The configuration is resolved from rovo.toml, the
    process's ROVO_<SECTION>__<FIELD> variables and the `overrides` (--set). Every later
    refusal, the first that applies, writes a refused report and exits usage, with no
    request. A dry run discovers, prints the identity of each row it would fetch, one a
    line on standard output, and fetches, converts and writes no page; it saves the
    manifest, the frontier and the run, and writes the report. `progress` receives the
    run's progress events, done last. A run that may use the browser tier opens one
    engine from `engine` (by default PlaywrightEngine) after every refusal, and closes it
    when the run ends. `interactive` is whether a person is at the terminal (by default
    whether standard input is one; nothing reads it). `owner_test` makes the sync an
    owner-testing request (in process only): RefuseInvalidOwnerRequest follows the
    engine refusals, every refusal of it is in owner mode with the owner warning on
    standard error, and the run it starts warns there, and as the owner_testing_warning
    event, before its first request. The NotInThisSlice guard, which no branch raises
    any more, still exits partial and leaves the previous report in place.
    """
    from rovo._config import (  # noqa: PLC0415  It loads rovo._crawl, which index never needs.
        SyncOptions,
        resolve_config,
    )
    from rovo._report import report_refusal  # noqa: PLC0415  It loads rovo._crawl.

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
        interactive=sys.stdin.isatty() if interactive is None else interactive,
        json_events=json_events,
        urls=tuple(urls),
        paths=tuple(paths),
        owner_test=owner_test,
    )
    problem = _start_problem(mirror, settings, options, tier_installed)
    if problem is not None:
        reason, detail = problem
        report_refusal(mirror, Operator(), options, settings, reason, clock=clock)
        if owner_test is not None:  # OwnerRefusalWarned.
            _warn_owner(owner_test.hosts, _owner_policy(settings, owner_test))
        return _refuse(f"sync: {detail}")
    opened = _open_engine(engine) if settings.needs_browser else None
    try:
        return _start_sync(mirror, settings, options, (fetcher, clock, opened), progress=progress)
    except NotInThisSlice as stopped:
        sys.stderr.write(f"rovo: sync stopped: {stopped}\n")
        return ExitCode.partial
    finally:
        if opened is not None:
            opened.close()


def save_ownership(out_dir: Path, hosts: Iterable[str]) -> ExitCode:
    """Realises mirror.allium SaveOwnership for the operator, in process (no CLI spelling).

    The hosts, normalised as URL hosts, replace the manifest's declared_owned_hosts (an
    empty set revokes them), saved atomically; no run starts and no request is made. A
    missing mirror or a host outside the scope's allowed hosts exits usage, unchanged.
    """
    try:
        mirror = load_mirror(out_dir)
    except ManifestError as error:
        return _refuse(f"ownership: no mirror in {out_dir} ({error})")
    wanted = frozenset(hosts)
    if not mirror.save_ownership(wanted):
        named = ", ".join(sorted(wanted))
        return _refuse(f"ownership: not every host is an allowed host of the mirror: {named}")
    save_mirror(mirror)
    return ExitCode.ok


# The owner warning (crawl.allium PrepareRun guidance), on standard error.
_OWNER_WARNING = (
    "rovo: owner testing: these settings are only for websites you own; do not use them "
    "on third-party websites. Ownership is self-declared, not verified."
)


def _warn_owner(hosts: frozenset[str], policy: "CrawlPolicy") -> None:
    """The owner warning on standard error: the selected hosts and settings displayed."""
    from rovo._crawl.model import standard_policy  # noqa: PLC0415  Only a sync loads the crawl.

    standard = vars(standard_policy())
    settings = ", ".join(
        f"{name}={getattr(value, 'value', value)}"
        for name, value in vars(policy).items()
        if value != standard[name]
    )
    sys.stderr.write(
        f"{_OWNER_WARNING} Hosts: {', '.join(sorted(hosts)) or 'none'}."
        f" Settings: {settings or 'standard'}.\n"
    )


def _owner_policy(settings: "Configuration", owner_test: "OwnerTestOptions") -> "CrawlPolicy":
    """The policy an owner request asks for, as effective_policy builds it."""
    from rovo._config import effective_policy  # noqa: PLC0415  Only a sync loads the configuration.

    return effective_policy(settings, owner_test)


def _open_engine(engine: "EngineFactory | None") -> "BrowserEngine":
    """One engine from the factory, by default PlaywrightEngine (which starts lazily)."""
    from rovo._crawl.browser import PlaywrightEngine  # noqa: PLC0415  Only a render loads it.

    return (engine or PlaywrightEngine)()


def fetch(  # noqa: PLR0913  The command's seams and its options.
    url: str,
    *,
    fetcher: "Fetcher",
    clock: "Timer",
    tier: Tier | None = None,
    owner_test: object | None = None,
    tier_installed: Callable[[Tier], bool] | None = None,
    engine: "EngineFactory | None" = None,
    config_path: Path | None = None,
) -> ExitCode:
    """Realises rovo.allium's fetch rules: RefuseOwnerTestingFetch, then the rest.

    RefuseFetchOnBadConfig, RefuseMissingFetchTier and FetchOneUrl follow. An owner
    test, the stealth tier or a URL that is not http(s) exits usage, then a configuration
    that is invalid or names an unblocking provider does, then a walk that could render
    with the browser engine missing does, each with no request. The
    configuration is resolve_fetch_config's: the built-in defaults, then, with
    `config_path`, that file's shared sections and its [fetch] section. The walk runs
    `tier` only when one is named, else by the effective render_mode as a sync's does
    (always starts at the browser, auto climbs from http, never is http only).
    fetch_one fetches the page under the standard policy and the configured profile;
    the scope is the file's (scope_of, its seeds by default the URL) with `config_path`,
    else the URL's own (initial_scope). Nothing is written. Its Markdown body, without
    frontmatter, goes to standard output and the exit is ok; nothing is printed and the
    exit is partial when it gave none. A walk that may render does so through one engine
    from `engine`, closed when the fetch ends.
    """
    from rovo._config import (  # noqa: PLC0415  It loads rovo._crawl.
        initial_scope,
        resolve_fetch_config,
        scope_of,
        signature_of,
    )
    from rovo._crawl.model import RenderMode  # noqa: PLC0415  Only a fetch loads the crawl.
    from rovo._crawl.run import fetch_one  # noqa: PLC0415  Only a fetch loads the crawl.

    if owner_test is not None or tier is Tier.stealth or not is_http_url(url):
        return _refuse(f"fetch: owner testing, the stealth tier or a non-http URL: {url}")
    settings = resolve_fetch_config(config_path, url)
    if not settings.valid or settings.unblocking_provider is not None:
        problems = settings.problems or ("unblocking.provider is reserved",)
        return _refuse("fetch: invalid configuration: " + "; ".join(problems))
    render_mode = {
        None: settings.render_mode,
        Tier.http: RenderMode.never,
        Tier.browser: RenderMode.always,
    }[tier]
    missing = (
        None if render_mode is RenderMode.never else _missing_engine(Tier.browser, tier_installed)
    )
    if missing is not None:
        return _refuse(f"fetch: the browser tier is not installed ({missing}); {_ENGINE_FIX}")
    profile = profile_named(settings.profile_name) or GENERIC
    if config_path is None:
        scope = initial_scope(url, profile)
    else:
        seeded = settings if settings.has_seeds else replace(settings, start_urls=(url,))
        scope = scope_of(seeded, profile)
    mirror = Mirror(
        out_dir=Path(),
        scope=scope,
        profile=profile,
        processing_signature=signature_of(scope, profile),
    )
    opened = None if render_mode is RenderMode.never else _open_engine(engine)
    try:
        body = fetch_one(mirror, url, render_mode, (fetcher, clock, opened))
    finally:
        if opened is not None:
            opened.close()
    if body is None:
        return ExitCode.partial
    sys.stdout.write(body if body.endswith("\n") else f"{body}\n")
    return ExitCode.ok


def _start_problem(
    mirror: Mirror,
    settings: "Configuration",
    options: "SyncOptions",
    tier_installed: Callable[[Tier], bool] | None,
) -> tuple[str, str] | None:
    """The first refusal that applies, in the specification's order: (reason, detail).

    The reason is the refused report's refusal_reason; the detail is standard error's.
    The browser engine is probed only when every earlier refusal passed and the
    configuration may render. owner_request_problem comes last: with no owner test, its
    robots = ignore refusal; with one, the owner request's first problem (that clause
    then accepts and ignores robots = ignore, decided).
    """
    from rovo._config import OwnerRequest, owner_request_problem, scope_hash  # noqa: PLC0415  Only a sync loads the configuration.
    from rovo._crawl.model import RobotsMode  # noqa: PLC0415  Only a sync loads the crawl.
    from rovo._crawl.run import load_runs  # noqa: PLC0415  Only a sync loads the crawl.

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
    earlier = (
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
    )
    problem = _first_problem(earlier)
    if problem is not None or not settings.needs_browser:
        missing = None
    else:
        missing = _missing_engine(Tier.browser, tier_installed)
    engines = _first_problem(
        (
            (
                missing is not None,
                tier_missing,
                f"the configured browser tier is not installed ({missing}); {_ENGINE_FIX}",
            ),
            (
                settings.needs_stealth
                and _missing_engine(Tier.stealth, tier_installed) is not None,
                tier_missing,
                "the configured stealth tier is not installed",
            ),
        )
    )
    if problem is not None or engines is not None:
        return problem or engines
    if options.owner_test is None:
        return _first_problem(((settings.robots is not RobotsMode.respect, robots, robots),))
    owner = owner_request_problem(
        OwnerRequest(
            options=options,
            allowed_hosts=allowed,
            declared_owned_hosts=mirror.declared_owned_hosts,
            scope_hash=scope_hash(_scope(settings)),
            runs={record.id: record for record in load_runs(mirror.out_dir)},
            interactive_renders=settings.needs_browser,
            browser_installed=lambda: _missing_engine(Tier.browser, tier_installed) is None,
        )
    )
    return None if owner is None else (owner, owner)


def _first_problem(problems: Sequence[tuple[bool, str, str]]) -> tuple[str, str] | None:
    """The (reason, detail) of the first problem that failed, else None."""
    return next(((reason, detail) for failed, reason, detail in problems if failed), None)


def _profile(settings: "Configuration") -> "Profile":
    """rovo.allium's profile_for the root URL, else the first start URL."""
    seed = settings.root_url or settings.start_urls[0]
    return profile_for(seed, settings.profile_name) or GENERIC


def _scope(settings: "Configuration") -> CrawlScope:
    """rovo.allium's scope_of the settings and their profile: the hosts StartSync tests."""
    from rovo._config import scope_of  # noqa: PLC0415  Only a sync loads the configuration.

    return scope_of(settings, _profile(settings))


def _start_sync(
    mirror: Mirror,
    settings: "Configuration",
    options: "SyncOptions",
    seams: "tuple[Fetcher, Timer, BrowserEngine | None]",
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
        lineage_run,
        load_frontier,
        next_run_id,
        record_run,
    )
    from rovo._report import (  # noqa: PLC0415  It loads rovo._crawl, which index never needs.
        CrawlReport,
        CrawlReportStatus,
        ReportStatus,
        announce_backoff,
        announce_trip,
        rank_and_write_report,
        record_crash_after_run,
    )

    fetcher, clock, engine = seams
    operator = Operator()
    profile = _profile(settings)
    scope = scope_of(settings, profile)
    run_id = next_run_id(mirror.out_dir)
    kind = RunKind.update if mirror.is_populated else RunKind.initial
    owner_test = options.owner_test
    policy = effective_policy(settings, owner_test)
    mode = RunMode.standard if owner_test is None else RunMode.owner_testing
    owned = frozenset[str]() if owner_test is None else owner_test.hosts
    preceding = (
        None if owner_test is None else lineage_run(mirror, owner_test.preceding_run_id, clock)
    )
    baseline = (
        None
        if preceding is None
        else preceding
        if preceding.mode is RunMode.standard
        else preceding.baseline
    )
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
        mode=mode,
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
        declared_owned_hosts=owned,
        baseline_run_id=None if baseline is None else baseline.id,
        preceding_run_id=None if preceding is None else preceding.id,
        requested_owner_test=owner_test,
    )
    request = RunRequest(
        operator=operator,
        mirror=mirror,
        id=run_id,
        kind=kind,
        mode=mode,
        baseline=baseline,
        preceding=preceding,
        scope_hash=scope_hash(scope),
        owned_hosts=owned,
        requested_owner_test=owner_test,
        policy=policy,
        dry_run=options.dry_run,
        interactive=options.interactive,
        render_mode=settings.render_mode,
        stealth_mode=settings.stealth_mode,
        max_age=settings.max_age,
        refollow_unchanged_links=settings.refollow_unchanged_links,
        targets=targets,
    )

    def warn(issued: "OwnerTestingWarningIssued") -> None:  # AnnounceOwnerWarning.
        _warn_owner(issued.hosts, issued.policy)
        if progress is not None:
            progress(ProgressEvent(event="owner_testing_warning", host=None, until=None, url=None))

    def trip(tripped: "BreakerTripped") -> None:  # AnnounceTrip, live.
        event = announce_trip(report, tripped)
        if event is not None and progress is not None:
            progress(event)

    result = drive_run(
        request,
        load_frontier(mirror),
        fetcher,
        clock,
        progress=progress,
        on_backoff=None if progress is None else lambda event: progress(announce_backoff(event)),
        on_failure=_failure_handler(mirror),
        on_trip=trip,
        engine=engine,
        on_owner_warning=warn,
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
        tally_finalised_page,
        tally_removal,
    )

    mirror = report.mirror
    _tally_run(report, result)
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


def _tally_run(report: "CrawlReport", result: "CrawlResult") -> None:
    """The run's events tallied into its open report, as each Tally rule does.

    BreakerTripped is not among them: AnnounceTrip ran live, through drive_run's on_trip.
    """
    from rovo._report import (  # noqa: PLC0415  It loads rovo._crawl, which index never needs.
        tally_blocked_url,
        tally_discovery_problem,
        tally_failed_url,
        tally_removal,
        tally_skipped_url,
    )

    for problem in result.discovery_failed:
        tally_discovery_problem(report, problem)
    for failed in result.failed:
        tally_failed_url(report, failed)
    for blocked in result.blocked:
        tally_blocked_url(report, blocked)
    for skipped in result.skipped:
        tally_skipped_url(report, skipped)
    for removed in result.removed:
        tally_removal(report, removed)


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


# The two ways forward from a missing browser engine (rovo.allium RefuseMissingEngine).
_ENGINE_FIX = "install it (playwright install chromium) or set render_mode = never"


def _missing_engine(tier: Tier, tier_installed: Callable[[Tier], bool] | None) -> str | None:
    """rovo.allium tier_installed(tier): what of the tier's engine is missing, else None.

    `tier_installed`, when given, decides; by default the browser tier is the playwright
    package and its Chromium binary (the engine probe, missing_browser_piece), and the
    stealth tier has no engine yet.
    """
    if tier_installed is not None:
        return None if tier_installed(tier) else f"the {tier.value} engine is missing"
    if tier is Tier.stealth:
        return "the stealth engine is missing"
    from rovo._crawl.browser import missing_browser_piece  # noqa: PLC0415  Only a render probes.

    piece = missing_browser_piece()
    return None if piece is None else f"{piece} is missing"


def _refuse(problem: str) -> ExitCode:
    sys.stderr.write(f"rovo: {problem}\n")
    return ExitCode.usage
