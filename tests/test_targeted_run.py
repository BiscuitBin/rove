"""The targeted run (T16 follow-up, spec 9a253a4): a sync naming --url or --path targets.

crawl.allium's targeted branches of PrepareRun (647 to 717), Discover (723 to 767) and
SelectBatch (1394 to 1450), at 9a253a4: only the targets are re-pended, or created with
discovered_via named, and refetched without validators; only their hosts are opened (so
their robots.txt is read) and no seed, sitemap or llms.txt is walked; only their rows
are selected, exempt from the page budget, and every other pending row stays pending for
a later run. `derived.Run.targeted` and `transition-edge.FrontierEntry.duplicate.pending`
are named after their obligation ids; the branches have no id of their own, so their
tests are named after what they show. The owner-testing branches stay T20's
(tests/test_slice_boundaries.py::test_owner_testing_runs_stop).
"""

import dataclasses
from collections.abc import Iterable
from pathlib import Path

from fakes import FakeFetcher, FixedClock, html_response, text_response
from rovo._crawl import model
from rovo._crawl.model import (
    DiscoverySource,
    Frontier,
    FrontierEntry,
    FrontierStatus,
    Run,
    RunKind,
    RunMode,
)
from rovo._crawl.run import (
    CrawlResult,
    attach_frontier,
    begin_crawl,
    create_frontier,
    discover,
    enqueue,
    load_frontier,
    prepare_run,
    run_crawl,
    select_batch,
    start_run,
)
from rovo._mirror.model import Mirror
from test_crawl import (
    HOST,
    LINKING_PAGE,
    OTHER,
    PAGE,
    ROBOTS,
    SECOND_RUN,
    SEED,
    SITE,
    first_synced,
    new_mirror,
    request,
    seed_site,
    update_request,
)

ABSENT = f"{SITE}/guide/absent.html"
DUPLICATE = f"{SITE}/guide/duplicate.html"
FAILED = f"{SITE}/guide/failed.html"
NAMED = f"{SITE}/guide/named.html"


def targeted_run(mirror: Mirror, targets: Iterable[str], frontier: Frontier) -> Run:
    """A second, update run over `mirror` naming `targets`, attached to `frontier`."""
    request_ = dataclasses.replace(update_request(mirror), targets=frozenset(targets))
    run = start_run(request_, FixedClock())
    assert run is not None
    assert attach_frontier(run, frontier) is frontier
    return run


def row(frontier: Frontier, identity: str) -> FrontierEntry:
    """The frontier's row for `identity`."""
    entry = frontier.entry(identity)
    assert entry is not None
    return entry


def settled_rows(out_dir: Path) -> tuple[Mirror, Frontier]:
    """A first full run that wrote the seed; rows absent, duplicate and failed beside it."""
    mirror = first_synced(out_dir, seed_site())
    frontier = load_frontier(mirror)
    assert frontier is not None
    first = start_run(request(mirror), FixedClock())
    assert first is not None
    for url, status in (
        (ABSENT, FrontierStatus.absent),
        (DUPLICATE, FrontierStatus.duplicate),
        (FAILED, FrontierStatus.failed),
    ):
        enqueue(
            first, frontier, url, depth=1, via=DiscoverySource.link, priority=0
        ).status = status
    return mirror, frontier


def targeted_again(mirror: Mirror, fetcher: FakeFetcher, targets: Iterable[str]) -> CrawlResult:
    """A whole second run naming `targets`, over the mirror's saved frontier."""
    request_ = dataclasses.replace(update_request(mirror), targets=frozenset(targets))
    return run_crawl(request_, load_frontier(mirror), fetcher, FixedClock())


def test_derived_Run_targeted(tmp_path: Path) -> None:
    """Verify derived value Run.targeted computes correctly.

    targeted: mode = standard and targets.count > 0: a standard run with targets is
    targeted; one without is not; an owner-testing run with targets is not.
    """
    mirror = new_mirror(tmp_path)
    frontier = create_frontier_for(mirror)
    named = targeted_run(mirror, {SEED}, frontier)
    assert named.targeted is True
    full = targeted_run(mirror, (), frontier)
    assert full.targeted is False
    named.mode = RunMode.owner_testing
    assert named.targeted is False


def create_frontier_for(mirror: Mirror) -> Frontier:
    """A new, empty frontier for the mirror."""
    run = start_run(request(mirror), FixedClock())
    assert run is not None
    frontier = create_frontier(run, None)
    assert frontier is not None
    return frontier


def test_PrepareRun_targeted_re_pends_or_creates_only_the_targets(tmp_path: Path) -> None:
    """PrepareRun's targeted branch: the targets alone, refetched without validators.

    forced_refetch and active_urls are the targets; the seed's done row and an absent
    row named as targets are re-pended, a deferred one at the start priority; a target
    with no row gets one, depth 0, discovered_via named, the start priority, no
    attempts. No other row moves: the written page's row is not rechecked (it is not a
    target here), the failed and duplicate rows are not retried, and recheckable_urls
    stays empty. An in-progress row still returns to pending.
    """
    mirror, frontier = settled_rows(tmp_path)
    absent = row(frontier, ABSENT)
    absent.priority = model.CONFIG.deferred_priority
    stray = enqueue(
        targeted_run(mirror, (), frontier),
        frontier,
        f"{SITE}/guide/stray.html",
        depth=1,
        via=DiscoverySource.link,
        priority=0,
    )
    stray.status = FrontierStatus.in_progress
    targets = {ABSENT, NAMED}
    run = targeted_run(mirror, targets, frontier)
    assert prepare_run(run, frontier)
    assert run.forced_refetch == frozenset(targets)
    assert run.active_urls == frozenset(targets)
    assert run.recheckable_urls == frozenset()
    assert absent.status is FrontierStatus.pending
    assert absent.priority == model.CONFIG.start_priority
    named = row(frontier, NAMED)
    assert (named.status, named.depth, named.discovered_via) == (
        FrontierStatus.pending,
        0,
        DiscoverySource.named,
    )
    assert (named.priority, named.attempts, named.discovered_from) == (
        model.CONFIG.start_priority,
        0,
        None,
    )
    assert row(frontier, SEED).status is FrontierStatus.done
    assert row(frontier, FAILED).status is FrontierStatus.failed
    assert row(frontier, DUPLICATE).status is FrontierStatus.duplicate
    assert stray.status is FrontierStatus.pending


def test_transition_edge_FrontierEntry_duplicate_pending(tmp_path: Path) -> None:
    """Verify transition duplicate -> pending on FrontierEntry.status is reachable via a witnessing rule.

    PrepareRun's targeted branch: a duplicate row named as a target is re-pended (a full
    run reaches the same edge by Enqueue's rediscovered set, T15's follow-up).
    """  # noqa: E501  The obligation's description, quoted.
    mirror, frontier = settled_rows(tmp_path)
    duplicate = row(frontier, DUPLICATE)
    run = targeted_run(mirror, {DUPLICATE}, frontier)
    assert prepare_run(run, frontier)
    assert duplicate.status is FrontierStatus.pending


def test_Discover_targeted_opens_only_the_targets_hosts(tmp_path: Path) -> None:
    """Discover's targeted branch: the targets' hosts opened, nothing else walked.

    Its host is opened, so its robots.txt is the one request; no seed is enqueued and no
    sitemap or llms.txt is requested.
    """
    mirror = new_mirror(tmp_path)
    frontier = create_frontier_for(mirror)
    run = targeted_run(mirror, {OTHER}, frontier)
    assert prepare_run(run, frontier)
    fetcher = FakeFetcher({ROBOTS: text_response(ROBOTS, "User-agent: *\n")})
    assert discover(run, frontier, fetcher)
    assert fetcher.requests == [ROBOTS]
    assert run.host(HOST) is not None
    assert [entry.identity for entry in frontier.entries] == [OTHER]


def test_SelectBatch_targeted_selects_only_the_targets_rows_beyond_the_page_budget(
    tmp_path: Path,
) -> None:
    """SelectBatch's targeted branch: only the targets' pending rows; a target is exempt.

    With no page budget left, the target's row is still chosen; a pending row that is
    not a target stays pending.
    """
    mirror = new_mirror(tmp_path)
    frontier = create_frontier_for(mirror)
    run = targeted_run(mirror, {OTHER}, frontier)
    assert prepare_run(run, frontier)
    assert discover(run, frontier, FakeFetcher({}))
    other_pending = enqueue(run, frontier, SEED, depth=0, via=DiscoverySource.start, priority=0)
    assert begin_crawl(run)
    run.fetch_attempts = model.CONFIG.max_pages
    assert run.page_budget_remaining == 0
    assert select_batch(run, frontier) == [row(frontier, OTHER)]
    assert row(frontier, OTHER).status is FrontierStatus.in_progress
    assert other_pending.status is FrontierStatus.pending
    assert not run.budget_stopped


def test_a_targeted_run_refetches_its_target_and_leaves_every_other_row_pending(
    tmp_path: Path,
) -> None:
    """The targeted run through the driver: robots.txt and the target, nothing else.

    The written seed, named, is fetched without validators and stored again; the link
    its new body adds is queued pending and not requested; no seed walk, sitemap or
    llms.txt request is made; the run finishes.
    """
    mirror = first_synced(tmp_path, seed_site())
    fetcher = FakeFetcher(
        {SEED: html_response(SEED, LINKING_PAGE), OTHER: html_response(OTHER, PAGE)}
    )
    result = targeted_again(mirror, fetcher, {SEED})
    assert result.run.targeted
    assert fetcher.requests == [ROBOTS, SEED]
    assert fetcher.validators[-1] is None
    assert row(result.frontier, SEED).status is FrontierStatus.done
    assert row(result.frontier, OTHER).status is FrontierStatus.pending
    (page,) = mirror.pages
    assert page.last_stored_run == SECOND_RUN
    assert result.run.kind is RunKind.update
