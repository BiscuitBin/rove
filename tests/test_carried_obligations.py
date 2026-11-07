"""The carried obligations (T20): reachable since T09 to T19, assigned by no ticket.

Each test is named after the id `just plan-spec <module>` emits (crawl and mirror at
941e02d, unchanged in id at 39c1f9c), dots and hyphens as underscores, and its
docstring quotes the obligation. They pin behaviour earlier slices built, so the
ticket expects them green at the first propagate tick, each recorded so in the ledger;
`surface-provides.MirrorContents` alone depends on this slice (OperatorSavesOwnership).
"""

import dataclasses
import json
from pathlib import Path

from fakes import FakeFetcher, FixedClock, html_response
from rovo import _commands
from rovo._crawl.model import (
    DiscoverySource,
    FrontierStatus,
    Host,
    LadderWalk,
    RunKind,
    RunMode,
    WalkStatus,
)
from rovo._crawl.run import (
    create_frontier,
    enqueue,
    load_runs,
    open_host,
    prepare_attempt,
    settle_walk,
    start_run,
)
from rovo._exit import ExitCode
from rovo._mirror.intake import admit_candidate, settle_candidate
from rovo._mirror.model import CandidateDelivered, Page, StoreOutcome
from rovo._mirror.state import load_mirror, manifest_path
from rovo._mirror.urls import hostname_of
from spec_values import spec_enum
from test_crawl import (
    HOST,
    OTHER,
    PAGE,
    SEED,
    SITE,
    assert_fields,
    crawl_once,
    new_mirror,
    request,
    walked,
)
from test_mirror import content, delivered, published, stored
from test_mirror import new_mirror as mirror_of

SECOND_RUN = 2


def site() -> FakeFetcher:
    """The fixture seed, robots.txt absent."""
    return FakeFetcher({SEED: html_response(SEED, PAGE)})


def synced_mirror(out_dir: Path) -> Path:
    """Run rovo init and one standard sync that stores the seed."""
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    assert _commands.sync(out_dir, fetcher=site(), clock=FixedClock()) is ExitCode.ok
    return out_dir


# --- crawl ---------------------------------------------------------------------------------


def test_entity_fields_DocumentationSite(tmp_path: Path) -> None:
    """Verify all declared fields on DocumentationSite are present with correct types.

    The external site is known by its host, a String: SiteExchange's context is the run's
    Host whose name is the site's host, the hostname of the URLs it serves.
    """
    run = start_run(request(new_mirror(tmp_path)), FixedClock())
    assert run is not None
    host = open_host(run, HOST, SITE, FakeFetcher({}))
    assert isinstance(host, Host)
    assert isinstance(host.name, str)
    assert host.name == hostname_of(SEED)
    assert run.host(hostname_of(SEED)) is host


def test_enum_comparable_RunKind(tmp_path: Path) -> None:
    """Verify fields typed with enum RunKind are comparable.

    The values are the specification's; a run's kind compares equal to its own member
    only: initial for an empty mirror, update once it holds a page.
    """
    assert tuple(kind.value for kind in RunKind) == spec_enum("crawl", "RunKind")
    out_dir = synced_mirror(tmp_path / "out")
    assert [record.kind for record in load_runs(out_dir)] == [RunKind.initial.value]
    assert _commands.sync(out_dir, fetcher=site(), clock=FixedClock()) is ExitCode.ok
    kinds = [RunKind(record.kind) for record in load_runs(out_dir)]
    assert kinds == [RunKind.initial, RunKind.update]
    assert kinds[0] != kinds[1]


def test_enum_comparable_RunMode(tmp_path: Path) -> None:
    """Verify fields typed with enum RunMode are comparable.

    The values are the specification's; a standard run's mode is standard, never
    owner_testing.
    """
    assert tuple(mode.value for mode in RunMode) == spec_enum("crawl", "RunMode")
    out_dir = synced_mirror(tmp_path / "out")
    (record,) = load_runs(out_dir)
    assert RunMode(record.mode) is RunMode.standard
    assert RunMode(record.mode) != RunMode.owner_testing


def test_enum_comparable_FrontierStatus(tmp_path: Path) -> None:
    """Verify fields typed with enum FrontierStatus are comparable.

    The values are the specification's, in order; the statuses a run leaves compare
    equal to their own members only.
    """
    assert tuple(status.value for status in FrontierStatus) == spec_enum("crawl", "FrontierStatus")
    result = crawl_once(tmp_path, site())
    (entry,) = result.frontier.entries
    assert entry.status is FrontierStatus.done
    assert {entry.status} != {FrontierStatus.pending}
    assert len(set(FrontierStatus)) == len(spec_enum("crawl", "FrontierStatus"))


def test_entity_relationship_Run_hosts(tmp_path: Path) -> None:
    """Verify relationship Run.hosts navigates to the correct related entities.

    Host with run = this: every host a run opens is the run's, one per name, and a host
    opened by another run is not.
    """
    mirror = new_mirror(tmp_path)
    run = start_run(request(mirror), FixedClock())
    other = start_run(request(mirror, run_id=SECOND_RUN), FixedClock())
    assert run is not None
    assert other is not None
    host = open_host(run, HOST, SITE, FakeFetcher({}))
    assert host is not None
    assert run.hosts == [host]
    assert host.run is run
    assert open_host(run, HOST, SITE, FakeFetcher({})) is None
    assert other.hosts == []


def test_entity_relationship_Frontier_entries(tmp_path: Path) -> None:
    """Verify relationship Frontier.entries navigates to the correct related entities.

    FrontierEntry with frontier = this: each enqueued identity is one entry of the
    frontier, deduplicated by identity.
    """
    run = start_run(request(new_mirror(tmp_path)), FixedClock())
    assert run is not None
    frontier = create_frontier(run, None)
    assert frontier is not None
    seed = enqueue(run, frontier, SEED, depth=0, via=DiscoverySource.start, priority=0)
    other = enqueue(run, frontier, OTHER, depth=1, via=DiscoverySource.start, priority=0)
    assert enqueue(run, frontier, SEED, depth=0, via=DiscoverySource.start, priority=0) is seed
    assert frontier.entries == [seed, other]
    assert all(entry.frontier is frontier for entry in frontier.entries)
    assert frontier.entry(OTHER) is other


def test_when_presence_LadderWalk_standing(tmp_path: Path) -> None:
    """Verify LadderWalk.standing is present when status in {settled} and absent otherwise.

    A walking walk has no standing attempt; SettleWalk sets it as it settles the walk.
    """
    _, _, walk = walked(tmp_path, site())
    assert (walk.status, walk.standing) == (WalkStatus.walking, None)
    (attempt,) = walk.attempts
    assert prepare_attempt(attempt)
    assert settle_walk(attempt)
    assert (walk.status, walk.standing) == (WalkStatus.settled, attempt)


def test_transition_edge_LadderWalk_walking_settled(tmp_path: Path) -> None:
    """Verify transition walking -> settled on LadderWalk.status is reachable.

    The obligation: it is reachable via a witnessing rule.

    SettleWalk settles a walking walk on its ready, unretryable attempt.
    """
    _, _, walk = walked(tmp_path, site())
    (attempt,) = walk.attempts
    assert settle_walk(attempt)
    assert walk.status is WalkStatus.settled


def settled_walk(out_dir: Path) -> LadderWalk:
    """The seed's walk, settled on its one attempt."""
    _, _, walk = walked(out_dir, site())
    (attempt,) = walk.attempts
    assert settle_walk(attempt)
    return walk


def test_transition_rejected_LadderWalk_status(tmp_path: Path) -> None:
    """Verify undeclared transitions on LadderWalk.status are rejected.

    settled -> walking is undeclared: no rule takes a settled walk's attempt again.
    """
    walk = settled_walk(tmp_path)
    (attempt,) = walk.attempts
    assert settle_walk(attempt) is False
    assert prepare_attempt(attempt) is False
    assert walk.status is WalkStatus.settled


def test_transition_terminal_LadderWalk_status(tmp_path: Path) -> None:
    """Verify terminal states on LadderWalk.status have no outbound transitions.

    settled: its standing attempt stays, and no rule moves the walk.
    """
    walk = settled_walk(tmp_path)
    standing = walk.standing
    assert settle_walk(walk.attempts[0]) is False
    assert walk.status is WalkStatus.settled
    assert walk.standing is standing


def test_entity_relationship_LadderWalk_attempts(tmp_path: Path) -> None:
    """Verify relationship LadderWalk.attempts navigates to the correct related entities.

    FetchAttempt with walk = this: each try the walk made, in order, and only its own.
    """
    _, _, walk = walked(tmp_path / "one", site())
    _, _, other = walked(tmp_path / "two", site())
    assert len(walk.attempts) == 1
    assert all(attempt.walk is walk for attempt in walk.attempts)
    assert not set(map(id, walk.attempts)) & set(map(id, other.attempts))


def test_surface_actor_SiteExchange(tmp_path: Path) -> None:
    """Verify surface SiteExchange is accessible only to the specified actor.

    The documentation site faces the run only through the Host named for it: the
    fetcher sees requests to that host alone, robots.txt first.
    """
    fetcher = site()
    result = crawl_once(tmp_path, fetcher)
    host = result.run.host(HOST)
    assert host is not None
    assert {hostname_of(url) for url in fetcher.requests} == {HOST}
    assert fetcher.requests[0] == f"{SITE}/robots.txt"
    assert host.fetched >= 1


# --- mirror --------------------------------------------------------------------------------


def test_entity_fields_SyncRun(tmp_path: Path) -> None:
    """Verify all declared fields on SyncRun are present with correct types.

    id, an Integer, mirror-local and never reused: runs.json's rows and the candidates a
    run delivers carry it.
    """
    out_dir = synced_mirror(tmp_path / "out")
    assert _commands.sync(out_dir, fetcher=site(), clock=FixedClock()) is ExitCode.ok
    ids = [record.id for record in load_runs(out_dir)]
    assert all(isinstance(run_id, int) for run_id in ids)
    assert ids == [1, SECOND_RUN]
    candidate = delivered(new_mirror(tmp_path / "unit"))
    assert isinstance(candidate.run_id, int)


def test_entity_relationship_Mirror_pages(tmp_path: Path) -> None:
    """Verify relationship Mirror.pages navigates to the correct related entities.

    Page with mirror = this: the page a candidate stores is the mirror's, and another
    mirror holds none of it.
    """
    mirror = mirror_of(tmp_path / "one")
    other = mirror_of(tmp_path / "two")
    page = stored(mirror)
    assert mirror.pages == [page]
    assert page.mirror is mirror
    assert other.pages == []


def test_entity_optional_Page_canonical_url(tmp_path: Path) -> None:
    """Verify optional field Page.canonical_url accepts null and non-null values.

    Null when the page declared none; the declared URL when it did.
    """
    plain = stored(mirror_of(tmp_path / "plain"))
    assert plain.canonical_url is None
    declared = stored(mirror_of(tmp_path / "declared"), converted=content(canonical_url=SEED))
    assert declared.canonical_url == SEED


def test_entity_optional_Page_frontmatter(tmp_path: Path) -> None:
    """Verify optional field Page.frontmatter accepts null and non-null values.

    Null once stored, before finalisation; set when the finalise pass writes the file.
    """
    page = stored(mirror_of(tmp_path))
    assert page.frontmatter is None
    published(page.mirror, page)
    assert page.frontmatter is not None


def test_surface_actor_MirrorContents(tmp_path: Path) -> None:
    """Verify surface MirrorContents is accessible only to the specified actor.

    The operator reads the mirror on disk (its manifest) and raises its operations
    through the commands: saving ownership and rebuilding the indexes.
    """
    out_dir = synced_mirror(tmp_path / "out")
    assert load_mirror(out_dir).page_paths
    assert _commands.save_ownership(out_dir, [HOST]) is ExitCode.ok
    assert _commands.index(out_dir) is ExitCode.ok


def test_surface_exposure_MirrorContents(tmp_path: Path) -> None:
    """Verify each exposed item on MirrorContents is accessible.

    out_dir, scope, the profile's name, declared_owned_hosts, recorded_root_url,
    processing_signature, is_populated, has_declared_owner and page_paths, on the mirror
    the manifest loads.
    """
    out_dir = synced_mirror(tmp_path / "out")
    mirror = load_mirror(out_dir)
    assert_fields(
        mirror,
        (
            "out_dir",
            "scope",
            "declared_owned_hosts",
            "recorded_root_url",
            "processing_signature",
            "is_populated",
            "has_declared_owner",
            "page_paths",
        ),
    )
    assert mirror.out_dir == out_dir
    assert isinstance(mirror.profile.name, str)
    assert mirror.is_populated is True
    assert mirror.has_declared_owner is False
    assert mirror.page_paths == ["pages/docs.example/start.md"]
    manifest = json.loads(manifest_path(out_dir).read_text(encoding="utf-8"))
    assert manifest["declared_owned_hosts"] == []


def test_surface_provides_MirrorContents(tmp_path: Path) -> None:
    """Verify provided operations on MirrorContents appear/hide based on when conditions.

    OperatorSavesOwnership and PassRequested are provided unconditionally: saving
    ownership records the declaration (T20's SaveOwnership), and rovo index requests
    an index pass, each on a mirror that exists.
    """
    out_dir = synced_mirror(tmp_path / "out")
    assert _commands.save_ownership(out_dir, [HOST]) is ExitCode.ok
    assert load_mirror(out_dir).declared_owned_hosts == frozenset({HOST})
    assert _commands.index(out_dir) is ExitCode.ok
    assert (out_dir / "index.md").is_file()


def test_surface_actor_PageIntake(tmp_path: Path) -> None:
    """Verify surface PageIntake is accessible only to the specified actor.

    The run delivers candidates: each carries the run's id, and the page it stores
    records that run.
    """
    run = start_run(request(new_mirror(tmp_path)), FixedClock())
    assert run is not None
    candidate = admit_candidate(
        dataclasses.replace(delivered(run.target, run_id=run.id), mirror=run.target)
    )
    page = settle_candidate(candidate, FixedClock())
    assert isinstance(page, Page)
    assert page.last_seen_run == run.id


def test_surface_exposure_PageIntake(tmp_path: Path) -> None:
    """Verify each exposed item on PageIntake is accessible.

    The run's id, the mirror's scope and processing signature, and each written page's
    identity, digests, validators, signature, confidence and outbound links.
    """
    mirror = mirror_of(tmp_path)
    page = stored(mirror)
    assert_fields(mirror, ("scope", "processing_signature", "written_pages"))
    assert_fields(
        page,
        (
            "identity",
            "raw_digest",
            "etag",
            "last_modified",
            "sitemap_lastmod",
            "processing_signature",
            "low_confidence",
            "outbound_links",
        ),
    )
    assert mirror.written_pages == [page]
    assert isinstance(delivered(mirror).run_id, int)


def test_surface_provides_PageIntake(tmp_path: Path) -> None:
    """Verify provided operations on PageIntake appear/hide based on when conditions.

    CandidateDelivered is provided unconditionally: a delivered candidate is admitted
    and settled in the same step (EveryCandidateIsSettled), stored as new.
    """
    mirror = mirror_of(tmp_path)
    offered = delivered(mirror)
    assert isinstance(offered, CandidateDelivered)
    candidate = admit_candidate(offered)
    page = settle_candidate(candidate, FixedClock())
    assert isinstance(page, Page)
    assert page.last_outcome is StoreOutcome.added
