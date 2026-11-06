"""Divergences the T15 review found (ai_tmp/review/T15-2/ and T15-3/), each pinned.

A page moved once or twice and then retired in one run keeps its file in the removed
area (RetirePage, RemovedAreaKeepsPath); a robots.txt redirect to an allowed host not
yet open is spaced by that host name's limiter (Politeness); and
RefuseUnplaceableCandidate does not count the page a move would move as another page
holding its path (mirror.allium 742).
"""

import dataclasses
from pathlib import Path

import pytest

from fakes import (
    FakeFetcher,
    FixedClock,
    StampingFetcher,
    SteppingTimer,
    html_response,
    redirect_response,
    text_response,
)
from rovo._crawl.run import run_crawl
from rovo._mirror.intake import move_page, settle_candidate
from rovo._mirror.model import CandidateDiscarded, CandidateOutcome, PageRemoved
from test_mirror import (
    OTHER,
    OTHER_BODY,
    ROOT,
    candidate_for,
    content,
    finalised_run,
    replace_mirror_config,
    written_pair,
)
from test_pace import HOST, SEED, request, spacing
from test_pace import new_mirror as pace_mirror

OTHER_HOST = "www.example"
OTHER_ROBOTS = f"https://{OTHER_HOST}/robots.txt"


@pytest.mark.parametrize("prune", [False, True], ids=["archive", "prune"])
def test_a_page_moved_then_retired_in_one_run_keeps_its_file_in_the_removed_area(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, prune: bool
) -> None:
    """Review T15-2 C1/B1: PageFileMoved(old, new), then PageFileArchived(new).

    OTHER moves to renamed.html, whose own answer is then a 404. Applied in order, the
    events leave the old file's bytes at _removed/<host>/renamed.md, or nothing under
    prune; the old file is gone either way.
    """
    replace_mirror_config(monkeypatch, prune=prune)
    mirror, _, other = written_pair(tmp_path)
    old_path = other.path
    published = (tmp_path / old_path).read_bytes()
    renamed = OTHER.replace("other.html", "renamed.html")
    moved = candidate_for(
        mirror, requested=OTHER, source=renamed, hops=(OTHER,), converted=content(body=OTHER_BODY)
    )
    assert move_page(moved, FixedClock()) is other
    gone = candidate_for(mirror, requested=renamed, outcome=CandidateOutcome.absent)
    assert isinstance(settle_candidate(gone, FixedClock()), PageRemoved)
    assert other.path == f"{ROOT}renamed.md"
    finalised_run(mirror)
    assert not (tmp_path / old_path).exists()
    assert not (tmp_path / other.path).exists()
    archived = tmp_path / "_removed" / HOST / "renamed.md"
    if prune:
        assert not (tmp_path / "_removed").exists()
    else:
        assert archived.read_bytes() == published


@pytest.mark.parametrize("prune", [False, True], ids=["archive", "prune"])
def test_a_page_moved_twice_then_retired_in_one_run_keeps_its_published_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, prune: bool
) -> None:
    """Review T15-3 C1/B1: PageFileMoved twice, then PageFileArchived, applied in order.

    OTHER moves to middle.html, then to last.html, whose own answer is a 404. No file
    moves before finalisation, so the archive takes the published file: its bytes end at
    _removed/<host>/last.md, or nowhere under prune, and no path of the page remains.
    """
    replace_mirror_config(monkeypatch, prune=prune)
    mirror, _, other = written_pair(tmp_path)
    old_path = other.path
    published = (tmp_path / old_path).read_bytes()
    requested = OTHER
    for name in ("middle.html", "last.html"):
        moved_to = OTHER.replace("other.html", name)
        moved = candidate_for(
            mirror,
            requested=requested,
            source=moved_to,
            hops=(requested,),
            converted=content(body=OTHER_BODY),
        )
        assert move_page(moved, FixedClock()) is other
        requested = moved_to
    gone = candidate_for(mirror, requested=requested, outcome=CandidateOutcome.absent)
    assert isinstance(settle_candidate(gone, FixedClock()), PageRemoved)
    assert other.path == f"{ROOT}last.md"
    finalised_run(mirror)
    for path in (old_path, f"{ROOT}middle.md", other.path):
        assert not (tmp_path / path).exists()
    archived = tmp_path / "_removed" / HOST / "last.md"
    if prune:
        assert not (tmp_path / "_removed").exists()
    else:
        assert archived.read_bytes() == published


def test_a_robots_redirect_to_a_host_not_yet_open_is_spaced_by_that_hosts_limiter(
    tmp_path: Path,
) -> None:
    """Review T15-2 C2/B2, crawl.allium Politeness: limits are kept per host name.

    docs.example's robots.txt redirects to www.example's, which disallows everything. When
    www.example opens, its own robots.txt read is its second request: it starts at least
    1 / rate_per_host after the redirected hop, never on docs.example's limiter.
    """
    mirror = pace_mirror(tmp_path)
    scope = dataclasses.replace(mirror.scope, allowed_hosts=frozenset({HOST, OTHER_HOST}))
    mirror = dataclasses.replace(mirror, scope=scope)
    fetcher = FakeFetcher(
        {
            f"http://{HOST}/robots.txt": redirect_response(
                f"http://{HOST}/robots.txt", OTHER_ROBOTS
            ),
            OTHER_ROBOTS: text_response(OTHER_ROBOTS, "User-agent: *\nDisallow: /\n"),
            SEED: html_response(SEED, "<html><body><main><h1>Start</h1></main></body></html>"),
        }
    )
    timer = SteppingTimer()
    stamping = StampingFetcher(fetcher, timer)
    run_crawl(request(mirror), None, stamping, timer)
    starts = [at for url, at in stamping.stamps if url == OTHER_ROBOTS]
    assert len(starts) == 2  # noqa: PLR2004  The redirected hop, then www.example's own read.
    assert starts[1] - starts[0] >= spacing()


def test_a_move_whose_only_path_is_its_own_is_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review T15-2 C3/B3, mirror.allium 742: a path held by another page is a collision.

    With max_path_chars leaving room for the plain path alone, OTHER redirecting from
    http to https settles through MovePage, keeping its path, rather than being refused
    for want of a free path: the page being moved holds that path, and it is not another
    page.
    """
    mirror, _, other = written_pair(tmp_path)
    old_path = other.path
    replace_mirror_config(monkeypatch, max_path_chars=len(old_path))
    secure = OTHER.replace("http://", "https://", 1)
    candidate = candidate_for(
        mirror, requested=OTHER, source=secure, hops=(OTHER,), converted=content(body=OTHER_BODY)
    )
    settled = settle_candidate(candidate, FixedClock())
    assert not isinstance(settled, CandidateDiscarded)
    assert settled is other
    assert (other.identity, other.path) == (secure, old_path)
