"""Owner testing (T20): ownership, the owner request, the relaxed policy, follow-ups.

Saved ownership, the owner-request refusal and warning, the relaxed policy on owned
hosts, follow-up runs and the breaker's climb.
Each obligation test is named after the id `just plan-spec <module>` emits (crawl, rovo
and mirror at 941e02d, unchanged in id at the spec answers 39c1f9c), dots and hyphens as
underscores, and its docstring quotes the obligation. A `rule_failure` test makes
exactly one `requires` clause false. The rest are the ticket's guarantees:
effective_policy, request_policy, followup_targets, owner_link_needed, the warning
before the first request, ExplicitOwnerTestingOnly, RelaxationsAreRecorded and
SecretsNeverSerialised, the breaker tier as an owner run's starting tier, the lineage
of runs.json and save_ownership. Owner testing is reached in process only
(`_commands.save_ownership`, `_commands.sync(owner_test=...)`; rovo.allium open
question 1138): no test drives the command line for it. Nothing here sleeps or reads
standard input: time is a FixedClock or a SteppingTimer and `interactive` is passed.
The challenge rules are in tests/test_owner_challenges.py, which shares the helpers.
"""

import dataclasses
import json
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from fakes import (
    START,
    FakeEngine,
    FakeFetcher,
    FixedClock,
    RaisingFetcher,
    SteppingTimer,
    html_response,
    redirect_response,
    text_response,
)
from rovo import _commands
from rovo._config import SyncOptions, effective_policy, resolve_config
from rovo._crawl import model
from rovo._crawl.model import (
    BlockKind,
    BlockVerdict,
    Breaker,
    BreakerStatus,
    ChallengeStatus,
    CrawlPolicy,
    DiscoverySource,
    FetchAttempt,
    Frontier,
    FrontierStatus,
    Host,
    HostBackedOff,
    LadderWalk,
    OwnerAccess,
    OwnerChallenge,
    OwnerTestingWarningIssued,
    OwnerTestOptions,
    PolitenessControl,
    ProgressEvent,
    RenderMode,
    RobotsMode,
    Run,
    RunMode,
    RunRequest,
    StealthMode,
    WalkStatus,
    standard_policy,
)
from rovo._crawl.run import (
    breaker_escalates,
    breaker_trips,
    create_frontier,
    discover,
    drive_run,
    end_run,
    enqueue,
    fetch_entry,
    followup_targets,
    open_host,
    owner_abandons_challenge,
    owner_completes_challenge,
    owner_link_needed,
    prepare_run,
    request_policy,
    robots_allows,
    start_run,
)
from rovo._exit import ExitCode
from rovo._mirror.model import Mirror, Operator, Tier
from rovo._mirror.state import load_mirror, manifest_path, report_path, save_mirror
from spec_values import spec_duration, spec_enum, spec_float
from test_crawl import (
    HOST,
    OTHER,
    PAGE,
    ROBOTS,
    SEED,
    SITE,
    assert_fields,
    new_mirror,
    request,
)

CRAWL = model.CONFIG
OWNED = frozenset({HOST})
OTHER_HOST = "api.example"
OTHER_SITE = f"http://{OTHER_HOST}"
OTHER_SEED = f"{OTHER_SITE}/guide/start.html"
OTHER_ROBOTS = f"{OTHER_SITE}/robots.txt"
UNALLOWED_HOST = "elsewhere.example"
DISALLOW_GUIDE = "User-agent: *\nDisallow: /guide/\n"
PROBES = (f"{SITE}/sitemap.xml", f"{SITE}/sitemap_index.xml", f"{SITE}/llms.txt")
START_PATH = "pages/docs.example/start.md"
PREVIOUS = 1
FOLLOW_UP = 2
THIRD = 3
MISSING_RUN = 9
FORBIDDEN = 403
# Breaker.over_threshold: the outcomes it needs, and the fewest blocked that breach it.
COUNT = min(CRAWL.breaker_window, CRAWL.breaker_min_outcomes)
BLOCKING = int(COUNT * CRAWL.block_rate_threshold) + 1
# The warning's words: ownership is self-declared, not verified (PrepareRun guidance).
WARNING_WORDS = ("self-declared", "not verified")
REFUSED_EXIT = ExitCode.usage
# Every OwnerTestOptions field, as crawl.allium declares it, and its derived value.
OPTION_FIELDS = (
    "preceding_run_id",
    "hosts",
    "disabled_controls",
    "rate_per_host",
    "concurrency_per_host",
    "backoff_base",
    "max_backoff",
    "retry_after_cap",
    "breaker_pause",
    "protection_escalation",
    "interactive_challenges",
    "challenge_timeout",
    "access",
)
ESCALATING = dataclasses.replace(standard_policy(), protection_escalation=True)
CHALLENGING = dataclasses.replace(ESCALATING, interactive_challenges=True)
CHALLENGE_PAGE = "<html><body><p>Checking your browser.</p></body></html>"


# --- Helpers: an owner run in units ----------------------------------------------------


def owner_options(**changes: object) -> OwnerTestOptions:
    """An owner request following run 1 on the fixture host, robots disabled."""
    base = OwnerTestOptions(
        preceding_run_id=PREVIOUS,
        hosts=OWNED,
        disabled_controls=frozenset({PolitenessControl.robots}),
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]  # Test overrides by name.


def finished_run(
    mirror: Mirror, *, run_id: int = PREVIOUS, unresolved: frozenset[str] = frozenset()
) -> Run:
    """A finished, non-dry, non-targeted standard run of `mirror`: StartRun then EndRun."""
    run = start_run(request(mirror, run_id=run_id), FixedClock())
    assert run is not None
    assert end_run(run, FixedClock())
    run.unresolved_urls = unresolved
    return run


def owner_request(  # noqa: PLR0913  One keyword per RunRequested field a test varies.
    mirror: Mirror,
    *,
    baseline: Run | None,
    preceding: Run | None = None,
    owned: frozenset[str] = OWNED,
    policy: CrawlPolicy = ESCALATING,
    interactive: bool = False,
    render_mode: RenderMode = RenderMode.auto,
    stealth_mode: StealthMode = StealthMode.off,
    options: OwnerTestOptions | None = None,
) -> RunRequest:
    """The RunRequested StartSync raises for an owner-testing run following `preceding`."""
    return dataclasses.replace(
        request(
            mirror,
            run_id=FOLLOW_UP,
            mode=RunMode.owner_testing,
            render_mode=render_mode,
            stealth_mode=stealth_mode,
            policy=policy,
        ),
        baseline=baseline,
        preceding=preceding if preceding is not None else baseline,
        owned_hosts=owned,
        requested_owner_test=options or owner_options(protection_escalation=True),
        interactive=interactive,
    )


def owner_started(  # noqa: PLR0913  One keyword per field a test varies.
    out_dir: Path,
    *,
    unresolved: frozenset[str] = frozenset({SEED}),
    clock: FixedClock | SteppingTimer | None = None,
    policy: CrawlPolicy = ESCALATING,
    interactive: bool = False,
    stealth_mode: StealthMode = StealthMode.off,
    owned: frozenset[str] = OWNED,
    **scope: object,
) -> tuple[Run, Frontier]:
    """A running owner run following a finished standard run that left `unresolved`."""
    mirror = new_mirror(out_dir, **scope)
    baseline = finished_run(mirror, unresolved=unresolved)
    run = start_run(
        owner_request(
            mirror,
            baseline=baseline,
            policy=policy,
            interactive=interactive,
            stealth_mode=stealth_mode,
            owned=owned,
        ),
        clock or FixedClock(),
    )
    assert run is not None
    frontier = create_frontier(run, None)
    assert frontier is not None
    return run, frontier


def owner_host(run: Run, name: str = HOST, site: str = SITE) -> Host:
    """The run's host `name`, opened with no robots.txt (a 404)."""
    host = open_host(run, name, site, FakeFetcher({}))
    assert host is not None
    return host


def the_breaker(host: Host) -> Breaker:
    """The host's breaker."""
    assert host.breaker is not None
    return host.breaker


def over_threshold(breaker: Breaker) -> None:
    """Fill the breaker's window with COUNT outcomes, BLOCKING of them blocks."""
    breaker.outcomes = [index < BLOCKING for index in range(COUNT)]
    assert breaker.should_act


def challenge_walk(run: Run, frontier: Frontier, identity: str = SEED) -> LadderWalk:
    """A walking walk of the identity's in-progress row over http and the browser."""
    entry = enqueue(run, frontier, identity, depth=0, via=DiscoverySource.named, priority=0)
    entry.status = FrontierStatus.in_progress
    host = run.host(entry.host_name)
    assert host is not None
    return LadderWalk(
        entry=entry,
        host=host,
        tiers=(Tier.http, Tier.browser),
        conditional=False,
        escalated=True,
        challenge_offered=False,
        status=WalkStatus.walking,
    )


def challenged_attempt(
    walk: LadderWalk, *, tier: Tier = Tier.browser, source_url: str | None = None
) -> FetchAttempt:
    """A constructed attempt of `walk` whose verdict is a challenge (no recogniser ships).

    The verdict is built here, never by classify_block: crawl.allium open question 2670
    leaves the challenge signals unspecified, so the rules are exercised on constructed
    attempts (the maintainer's answer, spec 39c1f9c).
    """
    url = source_url or walk.entry.identity
    attempt = FetchAttempt(
        walk=walk,
        tier=tier,
        try_=1,
        response=html_response(url, CHALLENGE_PAGE, status=FORBIDDEN),
        verdict=BlockVerdict(kind=BlockKind.challenge, signature="challenge"),
        render_reason=None,
    )
    walk.attempts.append(attempt)
    return attempt


def waiting_challenge(attempt: FetchAttempt, timer: FixedClock | SteppingTimer) -> OwnerChallenge:
    """A waiting challenge of `attempt`, as PrepareAttempt's offer creates it."""
    challenge = OwnerChallenge(
        attempt=attempt,
        expires_at=timer.now() + attempt.walk.host.run.policy.challenge_timeout,
        status=ChallengeStatus.waiting,
    )
    attempt.challenges.append(challenge)
    attempt.walk.challenge_offered = True
    return challenge


# --- Helpers: owner testing through the command ----------------------------------------


def never_installed(tier: Tier) -> bool:
    """No engine beyond http is installed."""
    del tier
    return False


def browser_installed(tier: Tier) -> bool:
    """The browser engine is installed; the stealth engine never is."""
    return tier is Tier.browser


def disallowing(*, page: str = PAGE) -> FakeFetcher:
    """The fixture site whose robots.txt disallows /guide/, so a standard sync skips the seed."""
    return FakeFetcher(
        {ROBOTS: text_response(ROBOTS, DISALLOW_GUIDE), SEED: html_response(SEED, page)}
    )


def allowing() -> FakeFetcher:
    """The fixture site with no robots.txt: a standard sync stores the seed."""
    return FakeFetcher({SEED: html_response(SEED, PAGE)})


def set_key(out_dir: Path, key: str, value: str) -> None:
    """Replace the one `key = ...` line of rovo.toml with `key = value`."""
    path = out_dir / "rovo.toml"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.startswith(f"{key} = ")]
    assert len(matches) == 1, key
    lines[matches[0]] = f"{key} = {value}\n"
    path.write_text("".join(lines), encoding="utf-8")


def standard_sync(
    out_dir: Path, fetcher: FakeFetcher, *, urls: Sequence[str] = (), dry_run: bool = False
) -> ExitCode:
    """One standard rovo sync of the mirror over `fetcher`."""
    return _commands.sync(
        out_dir,
        fetcher=fetcher,
        clock=FixedClock(),
        tier_installed=never_installed,
        urls=urls,
        dry_run=dry_run,
    )


def owner_sync(  # noqa: PLR0913  The command's seams and one keyword per sync option.
    out_dir: Path,
    fetcher: FakeFetcher | RaisingFetcher,
    options: OwnerTestOptions,
    *,
    interactive: bool = False,
    tier_installed: Callable[[Tier], bool] = never_installed,
    progress: Callable[[ProgressEvent], None] | None = None,
    urls: Sequence[str] = (),
    paths: Sequence[str] = (),
    confirmed: bool = False,
    clock: FixedClock | SteppingTimer | None = None,
) -> ExitCode:
    """One owner-testing rovo sync of the mirror, in process (no command-line spelling)."""
    return _commands.sync(
        out_dir,
        fetcher=fetcher,
        clock=clock or FixedClock(),
        tier_installed=tier_installed,
        owner_test=options,
        interactive=interactive,
        progress=progress,
        urls=urls,
        paths=paths,
        confirmed=confirmed,
    )


def declare(out_dir: Path, hosts: frozenset[str]) -> None:
    """Write `hosts` as the manifest's declared_owned_hosts (the saved declaration)."""
    mirror = load_mirror(out_dir)
    mirror.declared_owned_hosts = hosts
    save_mirror(mirror)


def baseline(
    out_dir: Path, fetcher: FakeFetcher | None = None, *, hosts: frozenset[str] = OWNED
) -> Path:
    """Run rovo init on the seed, then a standard sync whose robots.txt keeps the seed out.

    `hosts` are the allowed hosts, set before the sync so the baseline's scope hash is
    the one every later request of the test is compared with.
    """
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    if hosts != OWNED:
        set_key(out_dir, "allowed_hosts", json.dumps(sorted(hosts)))
    assert standard_sync(out_dir, fetcher or disallowing()) is ExitCode.ok
    return out_dir


def ready(
    out_dir: Path, fetcher: FakeFetcher | None = None, *, hosts: frozenset[str] = OWNED
) -> Path:
    """A baseline run 1 and a saved declaration of the fixture host."""
    baseline(out_dir, fetcher, hosts=hosts)
    declare(out_dir, OWNED)
    return out_dir


def load(path: Path) -> dict[str, object]:
    """A JSON object file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def report(out_dir: Path) -> dict[str, object]:
    """The crawl-report.json the sync left."""
    return load(report_path(out_dir))


def runs(out_dir: Path) -> list[dict[str, object]]:
    """runs.json's rows, oldest first."""
    rows = load(out_dir / ".rovo" / "runs.json")["runs"]
    assert isinstance(rows, list)
    return rows


def edit_run(out_dir: Path, run_id: int, **changes: object) -> None:
    """Rewrite one runs.json row's fields: a stored state no sync of this slice leaves."""
    path = out_dir / ".rovo" / "runs.json"
    data = load(path)
    rows = data["runs"]
    assert isinstance(rows, list)
    for row in rows:
        if row["id"] == run_id:
            row.update(changes)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def drop_run_field(out_dir: Path, run_id: int, name: str) -> None:
    """Remove one field of one runs.json row, as a row written before this slice lacks it."""
    path = out_dir / ".rovo" / "runs.json"
    data = load(path)
    rows = data["runs"]
    assert isinstance(rows, list)
    for row in rows:
        if row["id"] == run_id:
            row.pop(name, None)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def refused_owner(out_dir: Path, options: OwnerTestOptions) -> dict[str, object]:
    """The refused report of an owner request: ReportRefusal's owner mode."""
    data = report(out_dir)
    assert data["report_status"] == "refused"
    assert data["run_id"] is None
    assert data["exit_code"] == "usage"
    assert data["effective_policy"] is None
    assert data["mode"] == "owner_testing"
    assert data["declared_owned_hosts"] == []
    assert data["baseline_run_id"] is None
    assert data["preceding_run_id"] == options.preceding_run_id
    return data


def warned(text: str, hosts: frozenset[str] = OWNED) -> None:
    """The owner warning is in `text`: self-declared, not verified, naming the hosts."""
    for words in WARNING_WORDS:
        assert words in text, words
    for host in hosts:
        assert host in text, host


def statuses(out_dir: Path) -> dict[str, str]:
    """Each frontier row's identity and status."""
    entries = load(out_dir / ".rovo" / "frontier.json")["entries"]
    assert isinstance(entries, list)
    return {row["identity"]: row["status"] for row in entries}


# --- OwnerAccess, OwnerTestOptions and the enums ---------------------------------------


def test_entity_fields_OwnerAccess() -> None:
    """Verify all declared fields on OwnerAccess are present with correct types.

    host, a String; an access is a value an OwnerTestOptions holds in a set. Decided, for
    now (crawl.allium 73 to 80): no way to supply one exists, so none is ever applied.
    """
    access = OwnerAccess(host=HOST)
    assert_fields(access, ("host",))
    assert isinstance(access.host, str)
    assert access == OwnerAccess(host=HOST)
    assert len({access, OwnerAccess(host=HOST)}) == 1
    assert owner_options().access == frozenset()


def test_value_equality_OwnerTestOptions() -> None:
    """Verify value type OwnerTestOptions has structural equality.

    Two requests with the same fields are equal and hash alike; any field differing makes
    them unequal.
    """
    options = owner_options()
    same = owner_options()
    assert options == same
    assert hash(options) == hash(same)
    assert options != dataclasses.replace(options, preceding_run_id=FOLLOW_UP)
    assert options != dataclasses.replace(options, hosts=frozenset({OTHER_HOST}))
    assert options != dataclasses.replace(options, disabled_controls=frozenset())
    assert options != dataclasses.replace(options, rate_per_host=1.0)
    assert options != dataclasses.replace(options, challenge_timeout=timedelta(minutes=1))
    assert options != dataclasses.replace(options, access=frozenset({OwnerAccess(host=HOST)}))


def test_entity_fields_OwnerTestOptions() -> None:
    """Verify all declared fields on OwnerTestOptions are present with correct types.

    The thirteen fields and the derived access_within_hosts: every access names a
    selected host.
    """
    options = owner_options()
    assert_fields(options, (*OPTION_FIELDS, "access_within_hosts"))
    assert isinstance(options.preceding_run_id, int)
    assert isinstance(options.hosts, frozenset)
    assert all(isinstance(control, PolitenessControl) for control in options.disabled_controls)
    for name in (
        "rate_per_host",
        "concurrency_per_host",
        "backoff_base",
        "max_backoff",
        "retry_after_cap",
        "breaker_pause",
        "challenge_timeout",
    ):
        assert getattr(options, name) is None, name
    assert options.protection_escalation is False
    assert options.interactive_challenges is False
    assert options.access_within_hosts is True
    selected = dataclasses.replace(options, access=frozenset({OwnerAccess(host=HOST)}))
    assert selected.access_within_hosts is True
    unselected = dataclasses.replace(options, access=frozenset({OwnerAccess(host=OTHER_HOST)}))
    assert unselected.access_within_hosts is False


def test_enum_comparable_PolitenessControl(tmp_path: Path) -> None:
    """Verify fields typed with enum PolitenessControl are comparable.

    The values are the specification's, in order; each control disabled alone gives an
    effective policy of its own, unequal to the standard policy and to every other.
    """
    assert tuple(control.value for control in PolitenessControl) == spec_enum(
        "crawl", "PolitenessControl"
    )
    settings = resolve_config(baseline(tmp_path / "out"), {}, ())
    policies = [
        effective_policy(settings, owner_options(disabled_controls=frozenset({control})))
        for control in PolitenessControl
    ]
    assert standard_policy() not in policies
    assert len(set(policies)) == len(PolitenessControl)


def test_enum_comparable_StealthMode(tmp_path: Path) -> None:
    """Verify fields typed with enum StealthMode are comparable.

    The values are the specification's; stealth_mode = on adds the stealth tier only to
    an owner run with protection escalation, off never.
    """
    assert tuple(mode.value for mode in StealthMode) == spec_enum("crawl", "StealthMode")
    run, _ = owner_started(tmp_path / "on", stealth_mode=StealthMode.on)
    assert run.stealth_mode == StealthMode.on
    assert run.usable_tiers == (Tier.http, Tier.browser, Tier.stealth)
    run_off, _ = owner_started(tmp_path / "off")
    assert run_off.stealth_mode == StealthMode.off
    assert Tier.stealth not in run_off.usable_tiers


# --- Run's owner fields ------------------------------------------------------------------


def test_invariant_Run_OwnerRunHasExplicitAuthority(tmp_path: Path) -> None:
    """Verify invariant OwnerRunHasExplicitAuthority holds after any field mutation on Run.

    mode = owner_testing implies a requested owner test, owned hosts, a baseline and a
    preceding run. StartRun creates no owner run that lacks a baseline, a preceding run
    or an owned host; the run an owner sync starts records all four (its report and its
    runs.json row).
    """
    mirror = new_mirror(tmp_path / "unit")
    base = finished_run(mirror)
    run = start_run(owner_request(mirror, baseline=base), FixedClock())
    assert run is not None
    assert run.requested_owner_test is not None
    assert run.owned_hosts == OWNED
    assert run.baseline is base
    assert run.preceding is base
    for lacking in (
        dataclasses.replace(owner_request(mirror, baseline=base), baseline=None),
        dataclasses.replace(owner_request(mirror, baseline=base), preceding=None),
        owner_request(mirror, baseline=base, owned=frozenset()),
    ):
        assert start_run(lacking, FixedClock()) is None
    out_dir = ready(tmp_path / "out")
    assert owner_sync(out_dir, disallowing(), owner_options()) is ExitCode.ok
    data = report(out_dir)
    assert data["mode"] == "owner_testing"
    assert data["requested_owner_test"] is not None
    assert data["declared_owned_hosts"] == [HOST]
    assert data["baseline_run_id"] == PREVIOUS
    assert data["preceding_run_id"] == PREVIOUS
    row = runs(out_dir)[-1]
    assert row["mode"] == "owner_testing"
    assert row["owned_hosts"] == [HOST]
    assert row["baseline_run_id"] == PREVIOUS
    assert row["preceding_run_id"] == PREVIOUS


def test_entity_optional_Run_baseline(tmp_path: Path) -> None:
    """Verify optional field Run.baseline accepts null and non-null values.

    A standard run has none; an owner run has the finished standard run it follows, and
    runs.json records its id (null on the standard row).
    """
    mirror = new_mirror(tmp_path / "unit")
    base = finished_run(mirror)
    assert base.baseline is None
    run = start_run(owner_request(mirror, baseline=base), FixedClock())
    assert run is not None
    assert run.baseline is base
    out_dir = ready(tmp_path / "out")
    assert owner_sync(out_dir, disallowing(), owner_options()) is ExitCode.ok
    first, second = runs(out_dir)
    assert first["baseline_run_id"] is None
    assert second["baseline_run_id"] == PREVIOUS


def test_entity_optional_Run_preceding(tmp_path: Path) -> None:
    """Verify optional field Run.preceding accepts null and non-null values.

    A standard run has none; an owner run has the run whose unresolved URLs it retries,
    which is its baseline here or an owner run that shares it.
    """
    mirror = new_mirror(tmp_path / "unit")
    base = finished_run(mirror)
    assert base.preceding is None
    first_owner = start_run(owner_request(mirror, baseline=base), FixedClock())
    assert first_owner is not None
    assert first_owner.preceding is base
    assert end_run(first_owner, FixedClock())
    second_owner = start_run(
        owner_request(mirror, baseline=base, preceding=first_owner), FixedClock()
    )
    assert second_owner is not None
    assert second_owner.preceding is first_owner
    assert second_owner.baseline is base
    out_dir = ready(tmp_path / "out")
    assert owner_sync(out_dir, disallowing(), owner_options()) is ExitCode.ok
    first, second = runs(out_dir)
    assert first["preceding_run_id"] is None
    assert second["preceding_run_id"] == PREVIOUS


def test_entity_optional_Run_requested_owner_test(tmp_path: Path) -> None:
    """Verify optional field Run.requested_owner_test accepts null and non-null values.

    A standard run requests none; an owner run holds the options it was requested with,
    and the report publishes them (null for a standard sync).
    """
    mirror = new_mirror(tmp_path / "unit")
    base = finished_run(mirror)
    assert base.requested_owner_test is None
    options = owner_options(protection_escalation=True)
    run = start_run(owner_request(mirror, baseline=base, options=options), FixedClock())
    assert run is not None
    assert run.requested_owner_test == options
    out_dir = ready(tmp_path / "out")
    assert report(out_dir)["requested_owner_test"] is None
    assert owner_sync(out_dir, disallowing(), owner_options()) is ExitCode.ok
    requested = report(out_dir)["requested_owner_test"]
    assert isinstance(requested, dict)
    assert requested["preceding_run_id"] == PREVIOUS
    assert requested["hosts"] == [HOST]


def test_derived_Run_is_owner_testing(tmp_path: Path) -> None:
    """Verify derived value Run.is_owner_testing computes correctly.

    mode = owner_testing: true for an owner run, false for a standard one.
    """
    run, _ = owner_started(tmp_path / "owner")
    assert run.is_owner_testing is True
    standard = start_run(request(new_mirror(tmp_path / "standard")), FixedClock())
    assert standard is not None
    assert standard.is_owner_testing is False


# --- config ----------------------------------------------------------------------------


def test_config_default_min_host_rate(tmp_path: Path) -> None:
    """Verify config parameter min_host_rate has its declared default.

    The default is the specification's, and BreakerEscalates never lowers a host's rate
    below it.
    """
    assert spec_float("crawl", "min_host_rate") == CRAWL.min_host_rate
    run, _ = owner_started(tmp_path)
    host = owner_host(run)
    host.rate = CRAWL.min_host_rate * 1.5
    breaker = the_breaker(host)
    over_threshold(breaker)
    assert breaker_escalates(breaker) is not None
    assert host.rate == CRAWL.min_host_rate


def test_config_default_breaker_pause(tmp_path: Path) -> None:
    """Verify config parameter breaker_pause has its declared default.

    The default is the specification's and the standard policy's; an owner request that
    supplies none keeps it, and BreakerEscalates pauses the host for it.
    """
    assert spec_duration("crawl", "breaker_pause") == CRAWL.breaker_pause
    assert standard_policy().breaker_pause == CRAWL.breaker_pause
    settings = resolve_config(baseline(tmp_path / "out"), {}, ())
    assert effective_policy(settings, owner_options()).breaker_pause == CRAWL.breaker_pause
    run, _ = owner_started(tmp_path / "unit")
    host = owner_host(run)
    breaker = the_breaker(host)
    over_threshold(breaker)
    backed_off = breaker_escalates(breaker)
    assert backed_off == HostBackedOff(host=host, until=START + CRAWL.breaker_pause)


# --- BreakerEscalates --------------------------------------------------------------------


def test_rule_success_BreakerEscalates(tmp_path: Path) -> None:
    """Verify rule BreakerEscalates succeeds when all preconditions are met.

    A watching breaker of an owned host that should act below its highest tier, under
    breaker_enabled and protection_escalation, climbs one usable tier, counts the
    escalation, clears its outcomes, halves the host's rate (no lower than
    min_host_rate), pauses the host for breaker_pause and raises HostBackedOff;
    BreakerTrips does not fire.
    """
    run, frontier = owner_started(tmp_path)
    host = owner_host(run)
    rate = host.rate
    assert rate is not None
    breaker = the_breaker(host)
    over_threshold(breaker)
    assert breaker_trips(breaker, frontier) is None
    until = START + run.policy.breaker_pause
    assert breaker_escalates(breaker) == HostBackedOff(host=host, until=until)
    assert breaker.tier is Tier.browser
    assert breaker.escalations == 1
    assert breaker.outcomes == []
    assert breaker.since_escalation == 0
    assert breaker.status is BreakerStatus.watching
    assert host.rate == max(rate / 2, CRAWL.min_host_rate)
    assert host.paused_until == until


def escalation_ready(out_dir: Path, **changes: object) -> tuple[Run, Breaker]:
    """An owner run whose owned host's breaker should act at http."""
    run, _ = owner_started(out_dir, **changes)  # type: ignore[arg-type]  # Test overrides by name.
    breaker = the_breaker(owner_host(run))
    over_threshold(breaker)
    return run, breaker


def assert_not_escalated(breaker: Breaker, tier: Tier = Tier.http) -> None:
    """The breaker did not climb: its tier, escalations and outcomes are as they were."""
    assert breaker.tier is tier
    assert breaker.escalations == 0
    assert len(breaker.outcomes) == COUNT
    assert breaker.host.paused_until is None


def test_rule_failure_BreakerEscalates_1(tmp_path: Path) -> None:
    """Verify rule BreakerEscalates is rejected when requires clause fails.

    requires: breaker.status = watching: a tripped breaker does not climb.
    """
    _, breaker = escalation_ready(tmp_path)
    breaker.status = BreakerStatus.tripped
    assert breaker_escalates(breaker) is None
    assert_not_escalated(breaker)


def test_rule_failure_BreakerEscalates_2(tmp_path: Path) -> None:
    """Verify rule BreakerEscalates is rejected when requires clause fails.

    requires: breaker.tier != breaker.highest_tier: at the browser, the highest usable
    tier with no stealth engine, the breaker does not climb (it trips instead).
    """
    _, breaker = escalation_ready(tmp_path)
    breaker.tier = breaker.highest_tier
    assert breaker.tier is Tier.browser
    assert breaker_escalates(breaker) is None
    assert_not_escalated(breaker, Tier.browser)


def test_rule_failure_BreakerEscalates_3(tmp_path: Path) -> None:
    """Verify rule BreakerEscalates is rejected when requires clause fails.

    requires: breaker.host.run.policy.breaker_enabled: with the breaker disabled by the
    owner request, it never climbs.
    """
    disabled = dataclasses.replace(ESCALATING, breaker_enabled=False)
    _, breaker = escalation_ready(tmp_path, policy=disabled)
    assert breaker_escalates(breaker) is None
    assert_not_escalated(breaker)


def test_rule_failure_BreakerEscalates_4(tmp_path: Path) -> None:
    """Verify rule BreakerEscalates is rejected when requires clause fails.

    requires: breaker.host.run.policy.protection_escalation: an owner run without it
    never climbs.
    """
    _, breaker = escalation_ready(tmp_path, policy=standard_policy())
    assert breaker_escalates(breaker) is None
    assert_not_escalated(breaker)


# --- The owner invariants ------------------------------------------------------------------


def test_invariant_OwnerRunHasStandardBaseline(tmp_path: Path) -> None:
    """Verify invariant OwnerRunHasStandardBaseline holds after every state-changing rule.

    The obligation: it holds after every state-changing rule that touches constrained
    entities.

    Every owner run follows a finished, non-dry, non-targeted standard baseline of the
    same mirror and scope hash, and a finished, non-dry preceding run of the same scope
    hash that is the baseline or shares it. An owner sync starts one only so: a dry,
    targeted or rescoped predecessor is refused with no request, and a follow-up of a
    follow-up keeps the first baseline (runs.json rows 1 to 3).
    """
    out_dir = ready(tmp_path / "out")
    assert owner_sync(out_dir, disallowing(), owner_options()) is ExitCode.ok
    fetcher = disallowing()
    assert owner_sync(out_dir, fetcher, owner_options(preceding_run_id=FOLLOW_UP)) is ExitCode.ok
    first, second, third = runs(out_dir)
    assert first["mode"] == "standard"
    assert first["status"] == "finished"
    assert first["dry_run"] is False
    assert first["targeted"] is False
    for row in (second, third):
        assert row["mode"] == "owner_testing"
        assert row["baseline_run_id"] == PREVIOUS
        assert row["scope_hash"] == first["scope_hash"]
    assert second["preceding_run_id"] == PREVIOUS
    assert third["preceding_run_id"] == FOLLOW_UP
    assert third["id"] == THIRD

    dry = ready(tmp_path / "dry")
    assert standard_sync(dry, disallowing(), dry_run=True) is ExitCode.ok
    refused_fetcher = disallowing()
    options = owner_options(preceding_run_id=FOLLOW_UP)
    assert owner_sync(dry, refused_fetcher, options) is REFUSED_EXIT
    assert refused_fetcher.requests == []
    assert "preceding" in str(refused_owner(dry, options)["refusal_reason"])

    targeted = ready(tmp_path / "targeted")
    assert standard_sync(targeted, disallowing(), urls=(SEED,)) is ExitCode.ok
    assert owner_sync(targeted, refused_fetcher, options) is REFUSED_EXIT
    assert refused_fetcher.requests == []
    assert "baseline" in str(refused_owner(targeted, options)["refusal_reason"])


def test_invariant_OwnerAccessStaysOnSelectedHosts(tmp_path: Path) -> None:
    """Verify invariant OwnerAccessStaysOnSelectedHosts holds after every state-changing rule.

    The obligation: it holds after every state-changing rule that touches constrained
    entities.

    An owner request whose access names an unselected host is refused before any request
    (owner_request_problem), so every owner run's requested options keep their access on
    their hosts; the access an accepted run records is empty (decided, for now).
    """
    out_dir = ready(tmp_path / "out")
    stray = owner_options(access=frozenset({OwnerAccess(host=OTHER_HOST)}))
    assert stray.access_within_hosts is False
    fetcher = disallowing()
    assert owner_sync(out_dir, fetcher, stray) is REFUSED_EXIT
    assert fetcher.requests == []
    assert "access" in str(refused_owner(out_dir, stray)["refusal_reason"])
    assert owner_sync(out_dir, disallowing(), owner_options()) is ExitCode.ok
    requested = report(out_dir)["requested_owner_test"]
    assert isinstance(requested, dict)
    assert requested["access"] == []


def climb_to_the_top(run: Run) -> list[Tier]:
    """Breach the owned host's breaker until it trips; each tier it stands at, in order.

    Before each breach the breaker has waited out its last escalation: since_escalation
    is a full window, as FeedBreaker counts it over a window of outcomes, so a breaker at
    its highest tier that climbed there should act again (Breaker.should_act).
    """
    frontier = create_frontier(run, None)
    assert frontier is not None
    breaker = the_breaker(owner_host(run))
    tiers = [breaker.tier]
    while breaker.status is BreakerStatus.watching:
        breaker.since_escalation = CRAWL.breaker_window
        over_threshold(breaker)
        if breaker_escalates(breaker) is None:
            assert breaker_trips(breaker, frontier) is not None
        assert breaker.tier in run.usable_tiers
        tiers.append(breaker.tier)
    return tiers


def test_invariant_BreakerNeverPassesHighestTier(tmp_path: Path) -> None:
    """Verify invariant BreakerNeverPassesHighestTier holds after every state-changing rule.

    The obligation: it holds after every state-changing rule that touches constrained
    entities.

    After every climb the breaker's tier is a usable tier: with no stealth tier usable it
    climbs http to browser and trips there; with stealth_mode = on (constructed: no
    stealth engine is installed, rovo.allium open question 1137) it climbs to stealth
    and trips there; a standard run's breaker trips at http and never climbs.
    """
    run, _ = owner_started(tmp_path / "browser")
    assert climb_to_the_top(run) == [Tier.http, Tier.browser, Tier.browser]
    stealthy, _ = owner_started(tmp_path / "stealth", stealth_mode=StealthMode.on)
    assert climb_to_the_top(stealthy) == [Tier.http, Tier.browser, Tier.stealth, Tier.stealth]
    standard = start_run(
        request(new_mirror(tmp_path / "standard"), render_mode=RenderMode.auto), FixedClock()
    )
    assert standard is not None
    frontier = create_frontier(standard, None)
    assert frontier is not None
    breaker = the_breaker(owner_host(standard))
    over_threshold(breaker)
    assert breaker_escalates(breaker) is None
    assert breaker_trips(breaker, frontier) is not None
    assert breaker.tier is Tier.http


# --- The OwnerTesting surface ----------------------------------------------------------------


def test_surface_actor_OwnerTesting(tmp_path: Path) -> None:
    """Verify surface OwnerTesting is accessible only to the specified actor.

    DeclaredSiteOwner: an operator of a mirror with a saved declaration. Without one the
    owner request is refused (exit 2, no request, the refusal naming the missing
    declaration); once the host is declared, the same request starts an owner run.
    """
    out_dir = baseline(tmp_path / "out")
    assert load_mirror(out_dir).has_declared_owner is False
    fetcher = disallowing()
    options = owner_options()
    assert owner_sync(out_dir, fetcher, options) is REFUSED_EXIT
    assert fetcher.requests == []
    assert "declaration" in str(refused_owner(out_dir, options)["refusal_reason"])
    declare(out_dir, OWNED)
    assert load_mirror(out_dir).has_declared_owner is True
    assert owner_sync(out_dir, disallowing(), options) is ExitCode.ok
    assert report(out_dir)["mode"] == "owner_testing"


def test_surface_exposure_OwnerTesting(tmp_path: Path) -> None:
    """Verify each exposed item on OwnerTesting is accessible.

    The mirror's declared_owned_hosts (the manifest), and for each finished run its id,
    kind, mode, baseline and preceding ids, scope hash, owned hosts and unresolved URLs
    (runs.json), its requested owner test, policy, budget stop, tripped host and error
    (crawl-report.json).
    """
    out_dir = ready(tmp_path / "out")
    assert owner_sync(out_dir, disallowing(), owner_options()) is ExitCode.ok
    manifest = load(manifest_path(out_dir))
    assert manifest["declared_owned_hosts"] == [HOST]
    row = runs(out_dir)[-1]
    for name in (
        "id",
        "kind",
        "mode",
        "baseline_run_id",
        "preceding_run_id",
        "scope_hash",
        "owned_hosts",
        "unresolved_urls",
    ):
        assert name in row, name
    data = report(out_dir)
    for name in (
        "requested_owner_test",
        "effective_policy",
        "budget_stopped",
        "breaker_tripped",
        "error",
    ):
        assert name in data, name
    assert data["requested_owner_test"] is not None
    policy = data["effective_policy"]
    assert isinstance(policy, dict)
    assert policy["robots"] == "ignore"


def test_surface_provides_OwnerTesting(tmp_path: Path) -> None:
    """Verify provided operations on OwnerTesting appear/hide based on when conditions.

    OperatorCompletesChallenge and OperatorAbandonsChallenge are provided for each
    waiting challenge of an owner run of the mirror, and for no other: once the
    challenge has settled, neither has any effect.
    """
    timer = SteppingTimer()
    run, frontier = owner_started(tmp_path, clock=timer, policy=CHALLENGING, interactive=True)
    owner_host(run)
    walk = challenge_walk(run, frontier)
    first = waiting_challenge(challenged_attempt(walk), timer)
    settled = owner_completes_challenge(first)
    assert settled is not None
    assert settled.outcome is ChallengeStatus.resolved
    second = waiting_challenge(challenged_attempt(walk), timer)
    abandoned = owner_abandons_challenge(second)
    assert abandoned is not None
    assert abandoned.outcome is ChallengeStatus.abandoned
    second.status = ChallengeStatus.abandoned
    assert owner_completes_challenge(second) is None
    assert owner_abandons_challenge(second) is None


# --- RefuseInvalidOwnerRequest ---------------------------------------------------------


def no_preceding(out_dir: Path) -> OwnerTestOptions:
    """No run with the named id exists."""
    del out_dir
    return owner_options(preceding_run_id=MISSING_RUN)


def interrupted_preceding(out_dir: Path) -> OwnerTestOptions:
    """The preceding run did not finish."""
    edit_run(out_dir, PREVIOUS, status="interrupted")
    return owner_options()


def rescoped_preceding(out_dir: Path) -> OwnerTestOptions:
    """The preceding run had another scope hash."""
    edit_run(out_dir, PREVIOUS, scope_hash="another-scope")
    return owner_options()


def dry_preceding(out_dir: Path) -> OwnerTestOptions:
    """The preceding run was a dry run."""
    assert standard_sync(out_dir, disallowing(), dry_run=True) is ExitCode.ok
    return owner_options(preceding_run_id=FOLLOW_UP)


def targeted_baseline(out_dir: Path) -> OwnerTestOptions:
    """The preceding standard run, the baseline, was targeted."""
    assert standard_sync(out_dir, disallowing(), urls=(SEED,)) is ExitCode.ok
    return owner_options(preceding_run_id=FOLLOW_UP)


def pre_slice_baseline(out_dir: Path) -> OwnerTestOptions:
    """The baseline's row predates this slice: no targeted field, never a baseline."""
    drop_run_field(out_dir, PREVIOUS, "targeted")
    return owner_options()


def options_case(**changes: object) -> Callable[[Path], OwnerTestOptions]:
    """A case whose only problem is in the options themselves."""

    def make(out_dir: Path) -> OwnerTestOptions:
        del out_dir
        return owner_options(**changes)

    return make


# (case id, the options' maker, a word the refusal names, interactive, render_mode)
PROBLEMS: list[tuple[str, Callable[[Path], OwnerTestOptions], str, bool, str]] = [
    ("no-hosts", options_case(hosts=frozenset()), "host", False, "never"),
    ("unallowed-host", options_case(hosts=frozenset({UNALLOWED_HOST})), "host", False, "never"),
    (
        "undeclared-host",
        options_case(hosts=frozenset({HOST, OTHER_HOST})),
        "declaration",
        False,
        "never",
    ),
    ("no-preceding-run", no_preceding, "preceding", False, "never"),
    ("preceding-not-finished", interrupted_preceding, "preceding", False, "never"),
    ("preceding-other-scope", rescoped_preceding, "preceding", False, "never"),
    ("preceding-dry", dry_preceding, "preceding", False, "never"),
    ("baseline-targeted", targeted_baseline, "baseline", False, "never"),
    ("baseline-pre-slice-row", pre_slice_baseline, "baseline", False, "never"),
    ("rate-zero", options_case(rate_per_host=0.0), "rate_per_host", False, "never"),
    ("rate-negative", options_case(rate_per_host=-1.0), "rate_per_host", False, "never"),
    (
        "concurrency-zero",
        options_case(concurrency_per_host=0),
        "concurrency_per_host",
        False,
        "never",
    ),
    (
        "backoff-negative",
        options_case(backoff_base=timedelta(seconds=-1)),
        "backoff_base",
        False,
        "never",
    ),
    (
        "max-backoff-negative",
        options_case(max_backoff=timedelta(seconds=-1)),
        "max_backoff",
        False,
        "never",
    ),
    (
        "pause-negative",
        options_case(breaker_pause=timedelta(seconds=-1)),
        "breaker_pause",
        False,
        "never",
    ),
    (
        "retry-cap-zero",
        options_case(retry_after_cap=timedelta(0)),
        "retry_after_cap",
        False,
        "never",
    ),
    (
        "challenge-timeout-zero",
        options_case(challenge_timeout=timedelta(0)),
        "challenge_timeout",
        False,
        "never",
    ),
    (
        "challenge-timeout-negative",
        options_case(challenge_timeout=timedelta(seconds=-1)),
        "challenge_timeout",
        False,
        "never",
    ),
    (
        "rate-disabled-and-given",
        options_case(disabled_controls=frozenset({PolitenessControl.rate}), rate_per_host=1.0),
        "rate",
        False,
        "never",
    ),
    (
        "concurrency-disabled-and-given",
        options_case(
            disabled_controls=frozenset({PolitenessControl.concurrency}), concurrency_per_host=1
        ),
        "concurrency",
        False,
        "never",
    ),
    (
        "backoff-disabled-and-given",
        options_case(
            disabled_controls=frozenset({PolitenessControl.retry_backoff}),
            backoff_base=timedelta(seconds=1),
        ),
        "retry_backoff",
        False,
        "never",
    ),
    (
        "retry-after-disabled-and-given",
        options_case(
            disabled_controls=frozenset({PolitenessControl.retry_after}),
            retry_after_cap=timedelta(seconds=1),
        ),
        "retry_after",
        False,
        "never",
    ),
    (
        "pause-disabled-and-given",
        options_case(
            disabled_controls=frozenset({PolitenessControl.breaker_pause}),
            breaker_pause=timedelta(seconds=1),
        ),
        "breaker_pause",
        False,
        "never",
    ),
    (
        "challenges-without-an-operator",
        options_case(interactive_challenges=True, protection_escalation=True),
        "interactive",
        False,
        "auto",
    ),
    (
        "challenges-without-rendering",
        options_case(interactive_challenges=True, protection_escalation=True),
        "interactive",
        True,
        "never",
    ),
    (
        "challenges-without-escalation",
        options_case(interactive_challenges=True),
        "interactive",
        True,
        "auto",
    ),
    (
        "access-off-the-selected-hosts",
        options_case(access=frozenset({OwnerAccess(host=OTHER_HOST)})),
        "access",
        False,
        "never",
    ),
]


@pytest.mark.parametrize("case", [pytest.param(case, id=case[0]) for case in PROBLEMS])
def test_rule_success_RefuseInvalidOwnerRequest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: tuple[str, Callable[[Path], OwnerTestOptions], str, bool, str],
) -> None:
    """Verify rule RefuseInvalidOwnerRequest succeeds when all preconditions are met.

    Each problem of owner_request_problem, alone (rovo.allium 417 to 433): the sync exits
    2 with a refused report in owner mode naming it, the owner warning on standard error
    (OwnerRefusalWarned), no request, no run started and no row added to runs.json; the
    allowed hosts are the fixture host and api.example, only the fixture host declared.
    """
    _, make, named, interactive, render_mode = case
    out_dir = ready(tmp_path / "out", hosts=frozenset({HOST, OTHER_HOST}))
    set_key(out_dir, "render_mode", json.dumps(render_mode))
    options = make(out_dir)
    before = runs(out_dir)
    capsys.readouterr()
    fetcher = disallowing()
    code = owner_sync(
        out_dir, fetcher, options, interactive=interactive, tier_installed=browser_installed
    )
    assert code is REFUSED_EXIT
    assert fetcher.requests == []
    assert runs(out_dir) == before
    data = refused_owner(out_dir, options)
    assert named in str(data["refusal_reason"]), data["refusal_reason"]
    warned(capsys.readouterr().err, options.hosts & OWNED)


def test_an_owner_request_naming_urls_or_paths_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """owner_request_problem: an owner request names no URL and no path.

    A written page's URL and its path (both accepted by the earlier refusals) are each
    refused in owner mode with no request.
    """
    out_dir = ready(tmp_path / "out", allowing())
    assert START_PATH in load_mirror(out_dir).page_paths
    options = owner_options()
    for named in ({"urls": (SEED,)}, {"paths": (START_PATH,)}):
        capsys.readouterr()
        fetcher = allowing()
        code = owner_sync(out_dir, fetcher, options, **named)  # type: ignore[arg-type]  # urls or paths, by name.
        assert code is REFUSED_EXIT
        assert fetcher.requests == []
        reason = str(refused_owner(out_dir, options)["refusal_reason"])
        assert "url" in reason.lower() or "path" in reason.lower(), reason
        warned(capsys.readouterr().err)


def test_a_non_finite_challenge_timeout_cannot_be_requested() -> None:
    """owner_request_problem refuses a challenge timeout that is not finite and positive.

    A challenge timeout is a timedelta: an infinite or NaN one cannot be built, so no
    owner request carries one and no request is ever made with one; zero and negative
    timeouts are refused (test_rule_success_RefuseInvalidOwnerRequest).
    """
    with pytest.raises(OverflowError):
        timedelta(seconds=float("inf"))
    with pytest.raises(ValueError, match="NaN"):
        timedelta(seconds=float("nan"))


def test_rule_failure_RefuseInvalidOwnerRequest_1(tmp_path: Path) -> None:
    """Verify rule RefuseInvalidOwnerRequest is rejected when requires clause fails.

    requires: directory_exists(out_dir) and exists target: with no mirror, the earlier
    refusal (RefuseSyncWithoutDirectory) exits 2 with no report and no request.
    """
    fetcher = disallowing()
    missing = tmp_path / "nowhere"
    assert owner_sync(missing, fetcher, owner_options()) is REFUSED_EXIT
    assert fetcher.requests == []
    assert not report_path(missing).exists()


def assert_earlier_refusal(
    out_dir: Path, fetcher: FakeFetcher, err: str, reason: str, options: OwnerTestOptions
) -> None:
    """The earlier refusal applied in owner mode: its reason, ReportRefusal's owner fields."""
    assert fetcher.requests == []
    assert refused_owner(out_dir, options)["refusal_reason"] == reason
    warned(err)


def test_rule_failure_RefuseInvalidOwnerRequest_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule RefuseInvalidOwnerRequest is rejected when requires clause fails.

    requires: settings.valid and settings.has_seeds and no unblocking provider: an
    invalid configuration is refused first (RefuseSyncOnBadConfig), in owner mode.
    """
    out_dir = ready(tmp_path / "out")
    set_key(out_dir, "render_mode", '"sometimes"')
    capsys.readouterr()
    fetcher = disallowing()
    options = owner_options()
    assert owner_sync(out_dir, fetcher, options) is REFUSED_EXIT
    assert_earlier_refusal(
        out_dir, fetcher, capsys.readouterr().err, "invalid configuration", options
    )


def test_rule_failure_RefuseInvalidOwnerRequest_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule RefuseInvalidOwnerRequest is rejected when requires clause fails.

    requires: not settings.root_changed(...) or options.confirmed: a changed root is
    refused first (RefuseSyncOnChangedRoot), in owner mode.
    """
    out_dir = ready(tmp_path / "out")
    set_key(out_dir, "root_url", json.dumps(f"{SITE}/other/"))
    capsys.readouterr()
    fetcher = disallowing()
    options = owner_options()
    assert owner_sync(out_dir, fetcher, options) is REFUSED_EXIT
    assert_earlier_refusal(
        out_dir,
        fetcher,
        capsys.readouterr().err,
        "changed root requires confirmation",
        options,
    )


def test_rule_failure_RefuseInvalidOwnerRequest_4(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule RefuseInvalidOwnerRequest is rejected when requires clause fails.

    requires: options.urls.all(u => is_http_url(u) and hostname_of(u) in allowed hosts):
    an off-host URL is refused first (RefuseOffHostTarget), in owner mode.
    """
    out_dir = ready(tmp_path / "out")
    capsys.readouterr()
    fetcher = disallowing()
    options = owner_options()
    code = owner_sync(out_dir, fetcher, options, urls=(f"http://{UNALLOWED_HOST}/x.html",))
    assert code is REFUSED_EXIT
    assert_earlier_refusal(
        out_dir, fetcher, capsys.readouterr().err, "invalid or off-host target", options
    )


def test_rule_failure_RefuseInvalidOwnerRequest_5(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule RefuseInvalidOwnerRequest is rejected when requires clause fails.

    requires: options.paths.all(p => p in target.page_paths): an unknown path is refused
    first (RefuseUnknownPath), in owner mode.
    """
    out_dir = ready(tmp_path / "out")
    capsys.readouterr()
    fetcher = disallowing()
    options = owner_options()
    assert owner_sync(out_dir, fetcher, options, paths=("pages/nowhere.md",)) is REFUSED_EXIT
    assert_earlier_refusal(
        out_dir, fetcher, capsys.readouterr().err, "unknown target path", options
    )


def test_rule_failure_RefuseInvalidOwnerRequest_6(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule RefuseInvalidOwnerRequest is rejected when requires clause fails.

    requires: a configured browser or stealth tier is installed: a missing engine is
    refused first (RefuseMissingEngine), in owner mode. A stealth-needing owner request
    (stealth_mode = on with protection escalation) is refused so, with no request: no
    stealth engine is installed (rovo.allium open question 1137).
    """
    options = owner_options(protection_escalation=True)
    for key, value in (("render_mode", '"auto"'), ("stealth_mode", '"on"')):
        out_dir = ready(tmp_path / key)
        set_key(out_dir, key, value)
        capsys.readouterr()
        fetcher = disallowing()
        assert owner_sync(out_dir, fetcher, options) is REFUSED_EXIT
        assert_earlier_refusal(
            out_dir,
            fetcher,
            capsys.readouterr().err,
            "configured tier is not installed",
            options,
        )


def test_rule_failure_RefuseInvalidOwnerRequest_7(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule RefuseInvalidOwnerRequest is rejected when requires clause fails.

    requires: problem != null: a valid owner request is not refused; it starts an owner
    run (exit 0, runs.json's run 2 owner_testing) after the warning.
    """
    out_dir = ready(tmp_path / "out")
    capsys.readouterr()
    assert owner_sync(out_dir, disallowing(), owner_options()) is ExitCode.ok
    assert report(out_dir)["report_status"] == "finished"
    assert [row["mode"] for row in runs(out_dir)] == ["standard", "owner_testing"]
    warned(capsys.readouterr().err)


# --- AnnounceOwnerWarning and the report's owner fields ----------------------------------


class FirstRequestProbe:
    """A fetcher that, on its first request, records what the run had already announced."""

    def __init__(
        self, fetcher: FakeFetcher, capsys: pytest.CaptureFixture[str], events: list[str]
    ) -> None:
        """Pass requests to `fetcher`; at the first, read stderr so far and the events."""
        self.fetcher = fetcher
        self.capsys = capsys
        self.events = events
        self.err_before: str | None = None
        self.events_before: list[str] | None = None
        self.requests = fetcher.requests

    def fetch(self, url: str, *, validators: object = None) -> object:
        """Record the run's announcements at the first request, then pass it on."""
        if self.err_before is None:
            self.err_before = self.capsys.readouterr().err
            self.events_before = list(self.events)
        return self.fetcher.fetch(url, validators=validators)  # type: ignore[arg-type]  # The Fetcher's own validators.


def test_rule_success_AnnounceOwnerWarning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule AnnounceOwnerWarning succeeds when all preconditions are met.

    OwnerTestingWarningIssued becomes the owner_testing_warning progress event (host,
    until and url null), and the warning's text is on standard error (decided, rovo.allium
    624 to 630), both before the run's first request. A refused owner request warns on
    standard error with no event.
    """
    out_dir = ready(tmp_path / "out")
    capsys.readouterr()
    events: list[ProgressEvent] = []
    names: list[str] = []

    def progress(event: ProgressEvent) -> None:
        events.append(event)
        names.append(event.event)

    probe = FirstRequestProbe(disallowing(), capsys, names)
    code = owner_sync(out_dir, probe, owner_options(), progress=progress)  # type: ignore[arg-type]  # The probe is a Fetcher.
    assert code is ExitCode.ok
    assert probe.events_before is not None
    assert "owner_testing_warning" in probe.events_before
    assert probe.err_before is not None
    warned(probe.err_before)
    warning = next(event for event in events if event.event == "owner_testing_warning")
    assert warning == ProgressEvent(event="owner_testing_warning", host=None, until=None, url=None)
    assert names.index("owner_testing_warning") < names.index("page")

    refused_events: list[ProgressEvent] = []
    fetcher = disallowing()
    bad = owner_options(preceding_run_id=MISSING_RUN)
    assert owner_sync(out_dir, fetcher, bad, progress=refused_events.append) is REFUSED_EXIT
    warned(capsys.readouterr().err)
    assert refused_events == []


def test_entity_optional_CrawlReport_baseline_run_id(tmp_path: Path) -> None:
    """Verify optional field CrawlReport.baseline_run_id accepts null and non-null values.

    Null for a standard sync and on a refusal; the baseline's id for an owner run.
    """
    out_dir = ready(tmp_path / "out")
    assert report(out_dir)["baseline_run_id"] is None
    assert owner_sync(out_dir, disallowing(), owner_options()) is ExitCode.ok
    assert report(out_dir)["baseline_run_id"] == PREVIOUS
    bad = owner_options(preceding_run_id=MISSING_RUN)
    assert owner_sync(out_dir, disallowing(), bad) is REFUSED_EXIT
    assert refused_owner(out_dir, bad)["baseline_run_id"] is None


def test_entity_optional_CrawlReport_preceding_run_id(tmp_path: Path) -> None:
    """Verify optional field CrawlReport.preceding_run_id accepts null and non-null values.

    Null for a standard sync; the preceding run's id for an owner run, and on an owner
    refusal the id the request named (ReportRefusal).
    """
    out_dir = ready(tmp_path / "out")
    assert report(out_dir)["preceding_run_id"] is None
    assert owner_sync(out_dir, disallowing(), owner_options()) is ExitCode.ok
    assert report(out_dir)["preceding_run_id"] == PREVIOUS
    bad = owner_options(preceding_run_id=MISSING_RUN)
    assert owner_sync(out_dir, disallowing(), bad) is REFUSED_EXIT
    assert refused_owner(out_dir, bad)["preceding_run_id"] == MISSING_RUN


def test_entity_optional_CrawlReport_requested_owner_test(tmp_path: Path) -> None:
    """Verify optional field CrawlReport.requested_owner_test accepts null and non-null values.

    Null for a standard sync; for an owner run and an owner refusal the options as
    requested, every field, sets sorted, durations in seconds, serialised without access
    contents (an empty list).
    """
    out_dir = ready(tmp_path / "out")
    assert report(out_dir)["requested_owner_test"] is None
    options = owner_options(
        protection_escalation=True, rate_per_host=1.0, breaker_pause=timedelta(seconds=5)
    )
    for code, expected in ((ExitCode.ok, options), (REFUSED_EXIT, options)):
        if code is REFUSED_EXIT:
            set_key(out_dir, "render_mode", '"sometimes"')
        assert owner_sync(out_dir, disallowing(), expected) is code
        requested = report(out_dir)["requested_owner_test"]
        assert isinstance(requested, dict)
        assert set(requested) == set(OPTION_FIELDS)
        assert requested["preceding_run_id"] == PREVIOUS
        assert requested["hosts"] == [HOST]
        assert requested["disabled_controls"] == ["robots"]
        assert requested["rate_per_host"] == 1.0
        assert requested["breaker_pause"] == timedelta(seconds=5).total_seconds()
        assert requested["protection_escalation"] is True
        assert requested["challenge_timeout"] is None
        assert requested["access"] == []


# --- SaveOwnership and has_declared_owner (mirror) --------------------------------------


def manifest_bytes(out_dir: Path) -> bytes:
    """The manifest as it is on disk."""
    return manifest_path(out_dir).read_bytes()


def test_derived_Mirror_has_declared_owner(tmp_path: Path) -> None:
    """Verify derived value Mirror.has_declared_owner computes correctly.

    declared_owned_hosts.count > 0: false for a new mirror, true once a host is saved,
    false again once the declaration is revoked, as the manifest reloads it.
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    assert load_mirror(out_dir).has_declared_owner is False
    assert _commands.save_ownership(out_dir, [HOST]) is ExitCode.ok
    assert load_mirror(out_dir).has_declared_owner is True
    assert _commands.save_ownership(out_dir, []) is ExitCode.ok
    assert load_mirror(out_dir).has_declared_owner is False
    mirror = new_mirror(tmp_path / "unit")
    assert mirror.save_ownership(OWNED)
    assert mirror.has_declared_owner is True


def test_rule_success_SaveOwnership(tmp_path: Path) -> None:
    """Verify rule SaveOwnership succeeds when all preconditions are met.

    Saved, replaced and revoked by an empty set, each in the manifest; host names are
    normalised exactly as URL hosts; saving starts no run, makes no request and writes no
    report.
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    set_key(out_dir, "allowed_hosts", json.dumps(sorted({HOST, OTHER_HOST})))
    mirror = load_mirror(out_dir)
    mirror.scope = dataclasses.replace(mirror.scope, allowed_hosts=frozenset({HOST, OTHER_HOST}))
    save_mirror(mirror)
    assert _commands.save_ownership(out_dir, [HOST]) is ExitCode.ok
    assert load(manifest_path(out_dir))["declared_owned_hosts"] == [HOST]
    assert _commands.save_ownership(out_dir, [OTHER_HOST.upper()]) is ExitCode.ok
    assert load(manifest_path(out_dir))["declared_owned_hosts"] == [OTHER_HOST]
    assert _commands.save_ownership(out_dir, []) is ExitCode.ok
    assert load(manifest_path(out_dir))["declared_owned_hosts"] == []
    assert not (out_dir / ".rovo" / "runs.json").exists()
    assert not (out_dir / ".rovo" / "frontier.json").exists()
    assert not report_path(out_dir).exists()
    unit = new_mirror(tmp_path / "unit")
    assert unit.save_ownership(frozenset({"Docs.Example"}))
    assert unit.declared_owned_hosts == OWNED


def test_rule_failure_SaveOwnership_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule SaveOwnership is rejected when requires clause fails.

    requires: hosts.all(h => h in mirror.scope.allowed_hosts): a host outside the allowed
    hosts, or a wildcard, refuses the whole set (exit 2 on standard error), the manifest
    unchanged; a missing mirror exits 2 too.
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    assert _commands.save_ownership(out_dir, [HOST]) is ExitCode.ok
    before = manifest_bytes(out_dir)
    for hosts in ([HOST, UNALLOWED_HOST], [f"*.{HOST}"]):
        capsys.readouterr()
        assert _commands.save_ownership(out_dir, hosts) is REFUSED_EXIT
        assert capsys.readouterr().err.startswith("rovo: ")
        assert manifest_bytes(out_dir) == before
    assert _commands.save_ownership(tmp_path / "nowhere", [HOST]) is REFUSED_EXIT
    unit = new_mirror(tmp_path / "unit")
    assert not unit.save_ownership(frozenset({UNALLOWED_HOST}))
    assert unit.declared_owned_hosts == frozenset()


# --- Guarantees: effective_policy --------------------------------------------------------


# Each control, and the policy field disabling it sets, with the value it takes.
DISABLED: list[tuple[PolitenessControl, str, object]] = [
    (PolitenessControl.robots, "robots", RobotsMode.ignore),
    (PolitenessControl.crawl_delay, "honor_crawl_delay", False),
    (PolitenessControl.rate, "rate_per_host", None),
    (PolitenessControl.concurrency, "concurrency_per_host", None),
    (PolitenessControl.retry_backoff, "retry_backoff", False),
    (PolitenessControl.retry_after, "honor_retry_after", False),
    (PolitenessControl.breaker_pause, "breaker_pause", timedelta(0)),
    (PolitenessControl.breaker, "breaker_enabled", False),
]


@pytest.mark.parametrize(
    ("control", "name", "value"),
    [pytest.param(*case, id=case[0].value) for case in DISABLED],
)
def test_effective_policy_disables_each_control_alone(
    tmp_path: Path, control: PolitenessControl, name: str, value: object
) -> None:
    """effective_policy: each disabled control changes its one field and nothing else."""
    settings = resolve_config(baseline(tmp_path / "out"), {}, ())
    options = owner_options(disabled_controls=frozenset({control}))
    policy = effective_policy(settings, options)
    expected = dataclasses.replace(standard_policy(), **{name: value})  # type: ignore[arg-type]  # Test overrides by name.
    assert policy == expected


# Each supplied value, the policy field it replaces, and a value unlike the default.
SUPPLIED: list[tuple[str, str, object]] = [
    ("rate_per_host", "rate_per_host", 0.5),
    ("concurrency_per_host", "concurrency_per_host", 1),
    ("backoff_base", "backoff_base", timedelta(seconds=3)),
    ("max_backoff", "max_backoff", timedelta(seconds=7)),
    ("retry_after_cap", "retry_after_cap", timedelta(seconds=11)),
    ("breaker_pause", "breaker_pause", timedelta(seconds=13)),
    ("challenge_timeout", "challenge_timeout", timedelta(minutes=2)),
    ("protection_escalation", "protection_escalation", True),
    ("interactive_challenges", "interactive_challenges", True),
]


@pytest.mark.parametrize(
    ("option", "name", "value"), [pytest.param(*case, id=case[0]) for case in SUPPLIED]
)
def test_effective_policy_applies_each_value_alone(
    tmp_path: Path, option: str, name: str, value: object
) -> None:
    """effective_policy: each supplied value replaces its default; the rest stay standard."""
    settings = resolve_config(baseline(tmp_path / "out"), {}, ())
    options = owner_options(disabled_controls=frozenset(), **{option: value})
    expected = dataclasses.replace(standard_policy(), **{name: value})  # type: ignore[arg-type]  # Test overrides by name.
    assert effective_policy(settings, options) == expected


def test_effective_policy_without_owner_options_is_the_standard_policy(tmp_path: Path) -> None:
    """effective_policy: no owner options is the standard policy; the timeout defaults to crawl's.

    The configuration's own robots key never reaches it (decided, rovo.allium StartSync
    guidance 557 to 566): robots = "ignore" in rovo.toml leaves robots respected with or
    without owner options that do not disable robots.
    """
    out_dir = baseline(tmp_path / "out")
    settings = resolve_config(out_dir, {}, ())
    assert effective_policy(settings, None) == standard_policy()
    plain = owner_options(disabled_controls=frozenset())
    assert effective_policy(settings, plain) == standard_policy()
    assert effective_policy(settings, plain).challenge_timeout == CRAWL.owner_challenge_timeout
    set_key(out_dir, "robots", '"ignore"')
    ignoring = resolve_config(out_dir, {}, ())
    assert ignoring.robots is RobotsMode.ignore
    assert effective_policy(ignoring, plain).robots is RobotsMode.respect
    assert effective_policy(ignoring, owner_options()).robots is RobotsMode.ignore


def test_an_owner_request_accepts_and_ignores_the_configurations_robots_key(
    tmp_path: Path,
) -> None:
    """With an owner request, rovo.toml's robots = "ignore" is accepted and ignored.

    The maintainer's answer (T20 item 6, rovo.allium 417 to 433 at 39c1f9c): only
    disabled_controls holding robots relaxes robots, so the seed robots.txt disallows
    stays unrequested and the run reports robots respected.
    """
    out_dir = ready(tmp_path / "out")
    set_key(out_dir, "robots", '"ignore"')
    fetcher = disallowing()
    options = owner_options(disabled_controls=frozenset())
    assert owner_sync(out_dir, fetcher, options) is ExitCode.partial
    assert SEED not in fetcher.requests
    data = report(out_dir)
    assert data["mode"] == "owner_testing"
    assert data["robots_ignored"] is False
    assert data["unresolved_urls"] == [SEED]


# --- Guarantees: request_policy, followup_targets, owner_link_needed ----------------------


def test_request_policy_relaxes_only_an_owned_host(tmp_path: Path) -> None:
    """request_policy: run.policy for a selected owned host, the standard policy otherwise.

    An allowed but unselected host of the same owner run, and every host of a standard
    run, gets the standard policy: robots.txt is respected there.
    """
    relaxed = dataclasses.replace(ESCALATING, robots=RobotsMode.ignore, breaker_enabled=False)
    run, _ = owner_started(
        tmp_path / "owner", policy=relaxed, allowed_hosts=frozenset({HOST, OTHER_HOST})
    )
    assert request_policy(run, HOST) == relaxed
    assert request_policy(run, OTHER_HOST) == standard_policy()
    owner_host(run, OTHER_HOST, OTHER_SITE)
    assert robots_allows(run, SEED) is True
    assert robots_allows(run, OTHER_SEED) is True  # Its robots.txt was absent (a 404).
    standard = start_run(request(new_mirror(tmp_path / "standard")), FixedClock())
    assert standard is not None
    assert request_policy(standard, HOST) == standard_policy()


def test_an_owner_run_never_relaxes_an_unselected_host(tmp_path: Path) -> None:
    """No request of an owner run reaches an unselected host under the relaxed policy.

    The owned seed redirects to an allowed, unselected host whose robots.txt disallows
    the page: that host is read under the standard policy, so the hop is not made; its
    report row is standard (robots respected), the owned host's relaxed.
    """
    out_dir = ready(tmp_path / "out", hosts=frozenset({HOST, OTHER_HOST}))
    fetcher = FakeFetcher(
        {
            ROBOTS: text_response(ROBOTS, DISALLOW_GUIDE),
            SEED: redirect_response(SEED, OTHER_SEED),
            OTHER_ROBOTS: text_response(OTHER_ROBOTS, DISALLOW_GUIDE),
            OTHER_SEED: html_response(OTHER_SEED, PAGE),
        }
    )
    owner_sync(out_dir, fetcher, owner_options())
    assert SEED in fetcher.requests
    assert OTHER_SEED not in fetcher.requests
    rows = report(out_dir)["per_host"]
    assert isinstance(rows, list)
    by_host = {row["host"]: row for row in rows}
    assert by_host[HOST]["robots_ignored"] is True
    assert by_host[HOST]["effective_policy"]["robots"] == "ignore"
    assert by_host[OTHER_HOST]["robots_ignored"] is False
    assert by_host[OTHER_HOST]["effective_policy"]["robots"] == "respect"


def test_followup_targets_keeps_the_unresolved_urls_on_selected_hosts_in_scope(
    tmp_path: Path,
) -> None:
    """followup_targets: unresolved URLs on a selected host within the scope, else none.

    A URL on an unselected host and one out of scope are dropped; an empty set stays
    empty, never the seeds or a full recrawl.
    """
    mirror = new_mirror(tmp_path, allowed_hosts=frozenset({HOST, OTHER_HOST}))
    outside = f"{SITE}/outside/x.html"
    unresolved = frozenset({SEED, OTHER, OTHER_SEED, outside})
    assert followup_targets(unresolved, OWNED, mirror.scope) == frozenset({SEED, OTHER})
    assert followup_targets(frozenset(), OWNED, mirror.scope) == frozenset()
    assert followup_targets(unresolved, frozenset(), mirror.scope) == frozenset()


def test_an_owner_run_seeds_only_its_followup_targets(tmp_path: Path) -> None:
    """PrepareRun's owner branch: the follow-up targets are the seeds and the active URLs.

    forced_refetch is the run's targets, empty (decided: an owner run names none); each
    seed's row is re-pended, a deferred one at the start priority, or created named at
    depth 0; the warning is issued before any request; Discover opens no host and walks
    no seed, sitemap or llms.txt.
    """
    run, frontier = owner_started(tmp_path, unresolved=frozenset({SEED, OTHER}))
    deferred = enqueue(run, frontier, OTHER, depth=2, via=DiscoverySource.link, priority=-1)
    deferred.status = FrontierStatus.failed
    warnings: list[OwnerTestingWarningIssued] = []
    run.on_owner_warning = warnings.append
    assert prepare_run(run, frontier)
    assert run.forced_refetch == frozenset()
    assert run.active_urls == frozenset({SEED, OTHER})
    seed_row = frontier.entry(SEED)
    assert seed_row is not None
    assert seed_row.discovered_via is DiscoverySource.named
    assert seed_row.depth == 0
    assert seed_row.priority == CRAWL.start_priority
    assert deferred.status is FrontierStatus.pending
    assert deferred.priority == CRAWL.start_priority
    assert warnings == [
        OwnerTestingWarningIssued(operator=run.operator, hosts=OWNED, policy=run.policy)
    ]
    fetcher = FakeFetcher({})
    assert discover(run, frontier, fetcher)
    assert fetcher.requests == []
    assert run.hosts == []


def test_an_empty_followup_fetches_nothing(tmp_path: Path) -> None:
    """A preceding run that left nothing unresolved gives an owner run with no seed: no fetch."""
    run, frontier = owner_started(tmp_path, unresolved=frozenset())
    assert prepare_run(run, frontier)
    assert run.active_urls == frozenset()
    assert frontier.entries == []


def store_page(run: Run, identity: str, *, low: bool = False) -> None:
    """A written page for `identity` in the run's mirror, stored through the intake."""
    from rovo._mirror.intake import admit_candidate, take_candidate  # noqa: PLC0415  Only this helper.
    from rovo._mirror.model import CandidateDelivered, CandidateOutcome  # noqa: PLC0415  Only this helper.
    from test_slice_boundaries import page_content  # noqa: PLC0415  Only this helper.

    content = page_content(PAGE)
    if low:
        content = dataclasses.replace(
            content, quality=dataclasses.replace(content.quality, low_confidence=True)
        )
    candidate = admit_candidate(
        CandidateDelivered(
            run_id=run.id,
            mirror=run.target,
            requested_identity=identity,
            source_url=identity,
            redirect_hops=(),
            depth=1,
            outcome=CandidateOutcome.converted,
            tier=Tier.http,
            raw_digest="0" * 64,
            content=content,
        )
    )
    assert take_candidate(candidate, FixedClock()) is not None


# (case id, the row's status or None for unseen, a stored page and its confidence, needed)
LINK_CASES: list[tuple[str, FrontierStatus | None, str | None, bool]] = [
    ("unseen", None, None, True),
    ("absent", FrontierStatus.absent, None, False),
    ("not-html", FrontierStatus.skipped_not_html, None, False),
    ("stored-confident", FrontierStatus.done, "confident", False),
    ("stored-low-confidence", FrontierStatus.done, "low", True),
    ("failed", FrontierStatus.failed, None, True),
    ("blocked", FrontierStatus.blocked, None, True),
    ("skipped-robots", FrontierStatus.skipped_robots, None, True),
]


@pytest.mark.parametrize(
    ("status", "stored", "needed"), [pytest.param(*case[1:], id=case[0]) for case in LINK_CASES]
)
def test_owner_link_needed(
    tmp_path: Path,
    status: FrontierStatus | None,
    stored: str | None,
    needed: bool,  # noqa: FBT001  A parametrized case's flag.
) -> None:
    """owner_link_needed: false for a confirmed absent, non-HTML or stored confident URL.

    False for a confirmed absent or non-HTML URL or a stored, confident, non-challenge
    page; true for an unseen or unresolved URL.
    """
    run, frontier = owner_started(tmp_path)
    if status is not None:
        row = enqueue(run, frontier, OTHER, depth=1, via=DiscoverySource.link, priority=0)
        row.status = status
    if stored is not None:
        store_page(run, OTHER, low=stored == "low")
    assert owner_link_needed(run, frontier, OTHER) is needed


def test_the_store_page_helper_stores_what_the_cases_assume(tmp_path: Path) -> None:
    """store_page writes a page whose confidence is the one asked for."""
    run, _ = owner_started(tmp_path)
    store_page(run, OTHER, low=True)
    store_page(run, SEED)
    low = run.target.page(OTHER)
    confident = run.target.page(SEED)
    assert low is not None
    assert confident is not None
    assert low.quality.low_confidence is True
    assert confident.quality.low_confidence is False


# --- Guarantees: ExplicitOwnerTestingOnly, RelaxationsAreRecorded, SecretsNeverSerialised ---


def test_a_saved_declaration_alone_never_relaxes_a_standard_sync(tmp_path: Path) -> None:
    """ExplicitOwnerTestingOnly: a declaration relaxes nothing without an owner request.

    A standard sync of a declared mirror still skips the seed robots.txt disallows and
    reports robots respected; --yes waives no part of an owner request.
    """
    out_dir = ready(tmp_path / "out")
    fetcher = disallowing()
    assert standard_sync(out_dir, fetcher) is ExitCode.ok
    assert SEED not in fetcher.requests
    data = report(out_dir)
    assert data["mode"] == "standard"
    assert data["robots_ignored"] is False
    assert statuses(out_dir)[SEED] == "skipped_robots"
    undeclared = baseline(tmp_path / "undeclared")
    confirmed = disallowing()
    options = owner_options()
    assert owner_sync(undeclared, confirmed, options, confirmed=True) is REFUSED_EXIT
    assert confirmed.requests == []
    assert "declaration" in str(refused_owner(undeclared, options)["refusal_reason"])


def assert_recorded(data: dict[str, object]) -> None:
    """RelaxationsAreRecorded: hosts, lineage and options published; access never."""
    assert data["mode"] == "owner_testing"
    assert data["declared_owned_hosts"] == [HOST]
    assert data["baseline_run_id"] == PREVIOUS
    assert data["preceding_run_id"] == PREVIOUS
    requested = data["requested_owner_test"]
    assert isinstance(requested, dict)
    assert requested["access"] == []
    assert "unresolved_urls" in data


def test_an_owner_run_records_its_relaxations_on_every_exit(tmp_path: Path) -> None:
    """RelaxationsAreRecorded and SecretsNeverSerialised: finished and interrupted alike.

    A finished owner run and one interrupted at its first page each publish the
    effective policy, the hosts, the lineage and the options, with no access contents.
    """
    finished = ready(tmp_path / "finished")
    assert owner_sync(finished, disallowing(), owner_options()) is ExitCode.ok
    data = report(finished)
    assert_recorded(data)
    assert data["unresolved_urls"] == []
    interrupted = ready(tmp_path / "interrupted")
    fetcher = RaisingFetcher(disallowing(), SEED, KeyboardInterrupt())
    owner_sync(interrupted, fetcher, owner_options())
    stopped = report(interrupted)
    assert stopped["report_status"] == "interrupted"
    assert_recorded(stopped)
    assert stopped["effective_policy"] is not None
    assert stopped["unresolved_urls"] == [SEED]


def test_an_owner_run_left_unresolved_exits_one(tmp_path: Path) -> None:
    """SyncExitCodes: an owner-testing run that left URLs unresolved exits 1 (partial)."""
    out_dir = ready(tmp_path / "out")
    fetcher = FakeFetcher(
        {ROBOTS: text_response(ROBOTS, DISALLOW_GUIDE), SEED: html_response(SEED, "", status=500)}
    )
    assert owner_sync(out_dir, fetcher, owner_options()) is ExitCode.partial
    assert report(out_dir)["unresolved_urls"] == [SEED]


# --- Guarantees: the breaker under owner testing -----------------------------------------


def test_the_breaker_tier_starts_an_owner_runs_walk(tmp_path: Path) -> None:
    """FetchEntry's starting tier: an owner run starts at its host breaker's tier.

    A breaker that climbed to the browser starts the next walk there (the hint's tier is
    http); a standard run ignores the breaker's tier (test_escalation's
    test_a_breaker_tier_is_ignored_outside_owner_testing).
    """
    run, frontier = owner_started(tmp_path)
    host = owner_host(run)
    the_breaker(host).tier = Tier.browser
    run.crawling = True
    entry = enqueue(run, frontier, SEED, depth=0, via=DiscoverySource.named, priority=0)
    entry.status = FrontierStatus.in_progress
    engine = FakeEngine()
    walk = fetch_entry(run, entry, FakeFetcher({SEED: html_response(SEED, PAGE)}), engine)
    assert walk is not None
    assert walk.tiers[0] is Tier.browser
    assert walk.attempts[0].tier is Tier.browser
    assert engine.renders == [SEED]


def test_an_owner_run_without_its_authority_is_a_defect(tmp_path: Path) -> None:
    """StartRun's None branch: drive_run raises ValueError naming StartRun's requires.

    The root refuses such a request first, so this is a defect, never a product stop.
    """
    mirror = new_mirror(tmp_path)
    lacking = dataclasses.replace(request(mirror), mode=RunMode.owner_testing)
    with pytest.raises(ValueError, match="StartRun"):
        drive_run(lacking, None, FakeFetcher({}), FixedClock())


def test_sync_options_carry_the_owner_test() -> None:
    """SyncOptions.owner_test: the request's options; is_owner_testing follows it."""
    options = owner_options()
    owner = SyncOptions(
        dry_run=False,
        confirmed=False,
        interactive=False,
        json_events=False,
        urls=(),
        paths=(),
        owner_test=options,
    )
    assert owner.owner_test == options
    assert owner.is_owner_testing is True
    assert dataclasses.replace(owner, owner_test=None).is_owner_testing is False


def test_an_owner_run_uses_the_operator_of_its_request(tmp_path: Path) -> None:
    """The run's operator is the request's (SyncControl), owner or standard alike."""
    operator = Operator()
    mirror = new_mirror(tmp_path)
    base = finished_run(mirror)
    run = start_run(
        dataclasses.replace(owner_request(mirror, baseline=base), operator=operator),
        FixedClock(),
    )
    assert run is not None
    assert run.operator is operator
