"""A candidate assign_path cannot place (mirror.allium at fed9ed8, crawl.allium at e818eb0).

mirror.allium: StoreNewPage requires `new_path != null`; RefuseUnplaceableCandidate takes
a pending converted candidate with no written page and a null assign_path, accepts it
and raises CandidateDiscarded(reason: "no free path"), changing nothing else. crawl.allium
FailDiscardedEntry passes that reason on as the EntryFailed error, so the run reports the
URL as failed. The obligation tests are named after the obligation id `just plan-spec
mirror` emits; the scenarios run `rovo sync` in process on the fixed docs.example host,
where an identity's digest, and so its fallback path, is known before the run. Every page
path lies under pages/<host>/ (mirror.allium MovePage guidance, at fed9ed8).
"""

import json
from pathlib import Path

from fakes import FakeFetcher, FixedClock, html_response
from rovo import _commands
from rovo._crawl.run import convert_fetched, dispose_fetch, fail_discarded_entry
from rovo._mirror.intake import admit_candidate, refuse_unplaceable_candidate, store_new_page
from rovo._mirror.model import (
    CandidateDiscarded,
    CandidateOutcome,
    CandidateStatus,
    Mirror,
    PageCandidate,
    PageStatus,
    Tier,
)
from rovo._mirror.state import load_mirror
from rovo._mirror.urls import assign_path, digest
from rovo._report import ExitCode
from test_assign_path_fallback import PLAIN, STEM, VICTIM, full_path, hold, short_path
from test_crawl import settled, site
from test_mirror import ROOT, SECOND_RUN, delivered, new_mirror, stored

NO_FREE_PATH = "no free path"
ELSEWHERE = f"{ROOT}elsewhere.md"
# A removed record keeps its own page path under pages/<host>/ (its file is archived at
# _removed/<host>/...); a path apart from PLAIN, so another page may hold PLAIN.
ARCHIVED = f"{ROOT}archived/victim.md"


def crowded(mirror: Mirror) -> None:
    """Hold the victim's plain, short-suffixed and full-digest paths: assign_path is null."""
    hold(mirror, PLAIN, short_path(STEM, VICTIM), full_path(STEM, VICTIM))
    unplaced: str | None = assign_path(mirror, VICTIM)
    assert unplaced is None


def snapshot(mirror: Mirror) -> list[tuple[str, str, PageStatus]]:
    """Every page's identity, path and status, to show that nothing changed."""
    return [(page.identity, page.path, page.status) for page in mirror.pages]


def victim_candidate(mirror: Mirror, **changes: object) -> PageCandidate:
    """A pending converted candidate for the victim, delivered and admitted."""
    return admit_candidate(delivered(mirror, requested=VICTIM, **changes))  # type: ignore[arg-type]  # Test overrides by name.


# --- mirror.allium obligations -------------------------------------------------------


def test_rule_failure_StoreNewPage_5(tmp_path: Path) -> None:
    """Verify rule StoreNewPage is rejected when requires clause fails.

    requires: new_path != null, where new_path = assign_path(candidate.mirror, identity).
    """
    mirror = new_mirror(tmp_path)
    crowded(mirror)
    before = snapshot(mirror)
    candidate = victim_candidate(mirror)
    assert store_new_page(candidate, FixedClock()) is None
    assert snapshot(mirror) == before
    assert candidate.status is CandidateStatus.pending
    assert mirror.aliases == []


def test_rule_success_RefuseUnplaceableCandidate(tmp_path: Path) -> None:
    """Verify rule RefuseUnplaceableCandidate succeeds when all preconditions are met."""
    mirror = new_mirror(tmp_path)
    crowded(mirror)
    before = snapshot(mirror)
    candidate = victim_candidate(mirror)
    discarded = refuse_unplaceable_candidate(candidate)
    assert isinstance(discarded, CandidateDiscarded)
    assert discarded.candidate is candidate
    assert discarded.reason == NO_FREE_PATH
    assert candidate.status is CandidateStatus.accepted
    assert snapshot(mirror) == before  # no page created, moved or revived
    assert mirror.aliases == []  # no alias is recorded
    assert list(tmp_path.rglob("*.md")) == []


def test_rule_success_RefuseUnplaceableCandidate_over_a_removed_page(tmp_path: Path) -> None:
    """Verify rule RefuseUnplaceableCandidate succeeds when the target page is removed.

    requires: not exists target or target.status = removed; a removed record stays removed.
    """
    mirror = new_mirror(tmp_path)
    removed = stored(mirror, requested=VICTIM)
    removed.status = PageStatus.removed
    removed.path = ARCHIVED
    crowded(mirror)
    before = snapshot(mirror)
    candidate = victim_candidate(mirror, run_id=SECOND_RUN)
    discarded = refuse_unplaceable_candidate(candidate)
    assert discarded is not None
    assert discarded.reason == NO_FREE_PATH
    assert snapshot(mirror) == before
    assert removed.status is PageStatus.removed
    assert removed.path == ARCHIVED


def test_rule_failure_RefuseUnplaceableCandidate_1(tmp_path: Path) -> None:
    """Verify rule RefuseUnplaceableCandidate is rejected when requires clause fails.

    requires: candidate.status = pending and candidate.outcome = converted.
    """
    mirror = new_mirror(tmp_path)
    crowded(mirror)
    before = snapshot(mirror)
    unchanged = victim_candidate(mirror, outcome=CandidateOutcome.unchanged)
    assert refuse_unplaceable_candidate(unchanged) is None
    assert unchanged.status is CandidateStatus.pending
    accepted = victim_candidate(mirror)
    accepted.status = CandidateStatus.accepted
    assert refuse_unplaceable_candidate(accepted) is None
    assert snapshot(mirror) == before


def test_rule_failure_RefuseUnplaceableCandidate_2(tmp_path: Path) -> None:
    """Verify rule RefuseUnplaceableCandidate is rejected when requires clause fails.

    requires: not exists target or target.status = removed: a written page holds the
    identity, at a path none of the three candidate paths, so assign_path stays null.
    """
    mirror = new_mirror(tmp_path)
    written = stored(mirror, requested=VICTIM)
    written.path = ELSEWHERE
    crowded(mirror)
    before = snapshot(mirror)
    candidate = victim_candidate(mirror, run_id=SECOND_RUN)
    assert refuse_unplaceable_candidate(candidate) is None
    assert candidate.status is CandidateStatus.pending
    assert snapshot(mirror) == before
    assert written.status is PageStatus.written


def test_rule_failure_RefuseUnplaceableCandidate_3(tmp_path: Path) -> None:
    """Verify rule RefuseUnplaceableCandidate is rejected when requires clause fails.

    requires: assign_path(candidate.mirror, identity) = null: here the full-digest path is free.
    """
    mirror = new_mirror(tmp_path)
    hold(mirror, PLAIN, short_path(STEM, VICTIM))
    before = snapshot(mirror)
    candidate = victim_candidate(mirror)
    assert refuse_unplaceable_candidate(candidate) is None
    assert candidate.status is CandidateStatus.pending
    assert snapshot(mirror) == before


# --- crawl.allium FailDiscardedEntry: the reason is the entry's error -----------------


def test_fail_discarded_entry_passes_the_reason_as_the_error(tmp_path: Path) -> None:
    """FailDiscardedEntry: EntryFailed(run, entry, error: reason, attempts: entry.attempts)."""
    for index, reason in enumerate((NO_FREE_PATH, "no page to confirm", "any stated reason")):
        run, frontier, walk = settled(tmp_path / str(index), site())
        assert dispose_fetch(walk)
        handed = convert_fetched(run, walk.entry, walk)
        assert handed is not None
        candidate = admit_candidate(handed)
        failed = fail_discarded_entry(
            run, frontier, CandidateDiscarded(candidate=candidate, reason=reason)
        )
        assert failed is not None
        assert failed.error == reason
        assert failed.run is run
        assert failed.entry is walk.entry
        assert failed.attempts == walk.entry.attempts == 1


# --- Scenarios: rovo sync over seeds whose paths collide --------------------------------

SITE = "http://docs.example"
FIRST = f"{SITE}/guide/start.html"
VICTIM_SEED = f"{SITE}/guide/START.html"
SHORT_HOLDER = f"{SITE}/guide/START-{digest(VICTIM_SEED)[:6]}.html"
FULL_HOLDER = f"{SITE}/guide/START-{digest(VICTIM_SEED)}.html"
PAGE = """<!doctype html><html lang="en"><head><title>Start</title></head><body><main>
<h1>Getting started</h1><p>The example product mirrors documentation websites into files.</p>
</main></body></html>"""


def never_installed(tier: Tier) -> bool:
    """No engine beyond http is installed."""
    del tier
    return False


def sync_seeds(out_dir: Path, seeds: list[str]) -> ExitCode:
    """Init a mirror, give it `seeds` as its start URLs, and sync it once."""
    assert _commands.init(FIRST, out_dir) is ExitCode.ok
    config = out_dir / "rovo.toml"
    text = config.read_text(encoding="utf-8")
    line = f"start_urls = {json.dumps([FIRST])}"
    assert line in text
    config.write_text(text.replace(line, f"start_urls = {json.dumps(seeds)}"), encoding="utf-8")
    fetcher = FakeFetcher({url: html_response(url, PAGE) for url in seeds})
    return _commands.sync(
        out_dir, fetcher=fetcher, clock=FixedClock(), tier_installed=never_installed
    )


def load(path: Path) -> dict[str, object]:
    """A JSON object from a file."""
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def page_files(out_dir: Path) -> list[str]:
    """Every Markdown file in the mirror, mirror-relative: none beside the managed root files."""
    return sorted(path.relative_to(out_dir).as_posix() for path in out_dir.rglob("*.md"))


def frontier_rows(out_dir: Path) -> dict[str, str]:
    """Each frontier row's identity and status."""
    entries = load(out_dir / ".rovo" / "frontier.json")["entries"]
    assert isinstance(entries, list)
    return {row["identity"]: row["status"] for row in entries}


def test_three_seeds_take_the_full_digest_path(tmp_path: Path) -> None:
    """B2: start.html, START-<short>.html, START.html; the third takes the full digest.

    START.html's plain path pages/docs.example/START.md is held, ignoring case, by
    pages/docs.example/start.md, and its short-suffixed path by the second seed, so it is
    stored at pages/docs.example/START-<64 hex>.md and the run exits ok with three pages
    at three paths.
    """
    assert SHORT_HOLDER.endswith(f"START-{digest(VICTIM_SEED)[:6]}.html")
    out_dir = tmp_path / "out"
    assert sync_seeds(out_dir, [FIRST, SHORT_HOLDER, VICTIM_SEED]) is ExitCode.ok
    short = f"{ROOT}START-{digest(VICTIM_SEED)[:6]}.md"
    full = f"{ROOT}START-{digest(VICTIM_SEED)}.md"
    paths = {page.identity: page.path for page in load_mirror(out_dir).pages}
    assert paths == {FIRST: f"{ROOT}start.md", SHORT_HOLDER: short, VICTIM_SEED: full}
    folded = [path.casefold() for path in paths.values()]
    assert len(folded) == len(set(folded))  # UniquePagePathIgnoringCase
    assert page_files(out_dir) == sorted(paths.values())
    assert set(frontier_rows(out_dir).values()) == {"done"}
    report = load(out_dir / "crawl-report.json")
    assert report["exit_code"] == "ok"
    assert report["failed_urls"] == []


def test_an_unplaceable_seed_fails_and_the_run_is_partial(tmp_path: Path) -> None:
    """B2: a fourth seed holds START.html's full-digest path, so START.html is refused.

    RefuseUnplaceableCandidate discards it with "no free path"; FailDiscardedEntry fails
    its entry with that error; the report lists it as failed and the run exits partial.
    The other three pages are stored and published; no page, file or alias is made for it.
    """
    out_dir = tmp_path / "out"
    seeds = [FIRST, SHORT_HOLDER, FULL_HOLDER, VICTIM_SEED]
    assert sync_seeds(out_dir, seeds) is ExitCode.partial
    short = f"{ROOT}START-{digest(VICTIM_SEED)[:6]}.md"
    full = f"{ROOT}START-{digest(VICTIM_SEED)}.md"
    mirror = load_mirror(out_dir)
    paths = {page.identity: page.path for page in mirror.pages}
    assert paths == {FIRST: f"{ROOT}start.md", SHORT_HOLDER: short, FULL_HOLDER: full}
    assert mirror.aliases == []
    assert page_files(out_dir) == sorted(paths.values())
    rows = frontier_rows(out_dir)
    assert rows[VICTIM_SEED] == "failed"
    assert {rows[url] for url in (FIRST, SHORT_HOLDER, FULL_HOLDER)} == {"done"}
    report = load(out_dir / "crawl-report.json")
    assert report["exit_code"] == "partial"
    assert report["failed_urls"] == [{"url": VICTIM_SEED, "error": NO_FREE_PATH, "attempts": 1}]
    changes = report["changes"]
    assert isinstance(changes, list)
    assert {"kind": "failed", "url": VICTIM_SEED, "path": None, "moved_from": None} in changes
    added = {row["url"] for row in changes if row["kind"] == "added"}
    assert added == {FIRST, SHORT_HOLDER, FULL_HOLDER}
