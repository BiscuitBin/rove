"""Regression tests for the final whole-branch review's valid findings, one per finding.

Each test names the verdict it pins (ai_tmp/review/final/verdicts-<area>.md, finding id).
The file is hash-pinned in .allium-loop/T20-owner-testing.json, the latest slice's ledger.
"""

import dataclasses
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

import test_browser_engine
from fakes import FakeFetcher, FixedClock, html_response, redirect_response, text_response
from rovo import _report
from rovo._config import resolve_config, resolve_fetch_config
from rovo._convert import profiles
from rovo._convert.fidelity import convert, extract, measure, normalize, restore
from rovo._crawl.browser import PlaywrightEngine
from rovo._crawl.fetch import HttpxFetcher
from rovo._crawl.model import (
    FrontierStatus,
    RobotsPolicy,
    RobotsStance,
    RunStatus,
    SiteResponse,
    WalkStatus,
    standard_policy,
)
from rovo._crawl.run import (
    retires_host_on_long_crawl_delay,
    run_crawl,
    stop_walk_on_tripped_host,
)
from rovo._exit import ExitCode
from rovo._mirror.finalise import apply_file_effects
from rovo._mirror.indexes import write_index_files
from rovo._mirror.model import FileEffect, FileEffectKind
from test_blocks import opened_host, trip, walking_attempt
from test_browser_engine import Answers, Scenario
from test_commands import initialised, report, synced
from test_commands import site as command_site
from test_crawl import PAGE, SEED, SITE, request, site
from test_crawl import new_mirror as crawl_mirror
from test_fetch_command import fetched
from test_mirror import new_mirror

PAGE_URL = "https://example.com/page"
# test_browser_engine's stub playwright fixture (`scenario`), registered here by this name.
stub_playwright = test_browser_engine.scenario
SECOND_RUN = 2


def converted(html: str) -> tuple[str, frozenset[str]]:
    """The Markdown body and anchors of `html` at PAGE_URL under the generic profile."""
    extracted = extract(html, PAGE_URL, profiles.GENERIC)
    normalized = normalize(extracted, profiles.GENERIC)
    body = restore(convert(normalized.fragment), normalized.islands)
    measure(extracted, normalized, body)
    return body, normalized.anchors


# --- mirror-breakage MB-1: no file mutation follows a symlink out of the mirror ------


def test_mb1_a_symlinked_host_directory_is_never_deleted_or_archived_through(
    tmp_path: Path,
) -> None:
    """A deletion or archive under pages/<host> refuses a host directory leading outside."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.md").write_text("victim")
    (outside / "b.md").write_text("victim-b")
    mirror = new_mirror(tmp_path / "mirror")
    (mirror.out_dir / "pages").mkdir()
    (mirror.out_dir / "pages" / "example.com").symlink_to(outside)
    for kind, name in ((FileEffectKind.deleted, "a.md"), (FileEffectKind.archived, "b.md")):
        mirror.file_effects[:] = [FileEffect(kind=kind, path=f"pages/example.com/{name}")]
        with pytest.raises(ValueError, match="outside the mirror"):
            apply_file_effects(mirror)
    assert sorted(path.name for path in outside.iterdir()) == ["a.md", "b.md"]
    assert not (mirror.out_dir / "_removed").exists()


def test_mb1_an_archive_into_a_symlinked_removed_directory_is_refused(tmp_path: Path) -> None:
    """The archive's destination is checked too: _removed/ leading outside is refused."""
    outside = tmp_path / "outside"
    outside.mkdir()
    mirror = new_mirror(tmp_path / "mirror")
    page = mirror.out_dir / "pages" / "example.com" / "a.md"
    page.parent.mkdir(parents=True)
    page.write_text("page")
    (mirror.out_dir / "_removed").symlink_to(outside)
    mirror.file_effects[:] = [
        FileEffect(kind=FileEffectKind.archived, path="pages/example.com/a.md")
    ]
    with pytest.raises(ValueError, match="outside the mirror"):
        apply_file_effects(mirror)
    assert page.read_text() == "page"
    assert list(outside.iterdir()) == []


def test_mb1_index_files_are_never_written_through_a_symlinked_indexes_directory(
    tmp_path: Path,
) -> None:
    """_indexes/ leading outside the mirror is refused; the outside file is untouched."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "index.md").write_text("precious")
    mirror = new_mirror(tmp_path / "mirror")
    (mirror.out_dir / "_indexes").symlink_to(outside)
    with pytest.raises(ValueError, match="outside the mirror"):
        write_index_files(mirror, {"_indexes/index.md": "overwritten\n"})
    assert (outside / "index.md").read_text() == "precious"


def test_mb1_a_plain_mirror_still_archives_and_deletes(tmp_path: Path) -> None:
    """The containment check passes every path inside the mirror."""
    mirror = new_mirror(tmp_path / "mirror")
    pages = mirror.out_dir / "pages" / "example.com"
    pages.mkdir(parents=True)
    (pages / "a.md").write_text("a")
    (pages / "b.md").write_text("b")
    mirror.file_effects[:] = [
        FileEffect(kind=FileEffectKind.deleted, path="pages/example.com/a.md"),
        FileEffect(kind=FileEffectKind.archived, path="pages/example.com/b.md"),
    ]
    apply_file_effects(mirror)
    assert not (pages / "a.md").exists()
    assert (mirror.out_dir / "_removed" / "example.com" / "b.md").read_text() == "b"


# --- convert-breakage B3: a malformed URL never makes extract or normalize raise -----

MALFORMED = ("http://[", "http://[::1/x", "https://[bad]host/")


@pytest.mark.parametrize("href", MALFORMED)
def test_b3_a_malformed_href_in_content_nav_canonical_or_footnote_is_kept(href: str) -> None:
    """ExtractNeverEmptyHanded (convert.allium 187): extract always returns content.

    The malformed href is left as it is in the content, skipped among the navigation
    targets, no canonical URL, and no footnote reference; the link text stays.
    """
    html = (
        f'<html><head><link rel="canonical" href="{href}"></head><body>'
        f'<nav><a href="{href}">Nav</a><a href="/ok">Ok</a></nav>'
        f'<main><h1>T</h1><p>Valid content <a href="{href}">link</a></p>'
        f'<table><tr><td><a href="{href}">cell</a></td></tr></table>'
        f'<ol class="footnotes"><li id="fn1">Note</li></ol></main></body></html>'
    )
    extracted = extract(html, PAGE_URL, profiles.GENERIC)
    assert extracted.canonical_url is None
    assert extracted.navigation_targets == ("https://example.com/ok",)
    body, _ = converted(html)
    assert "link" in body
    assert "Valid content" in body


def test_b3_a_page_with_a_malformed_href_is_stored_not_crashed_on(tmp_path: Path) -> None:
    """A sync run converts the page and stores it; one bad href aborts nothing."""
    page = (
        "<html><head><title>T</title></head><body><main><h1>Start</h1>"
        '<p>Some words <a href="http://[">broken</a> here.</p></main></body></html>'
    )
    mirror = crawl_mirror(tmp_path)
    result = run_crawl(request(mirror), None, site(page=page), FixedClock())
    assert result.run.status is RunStatus.finished
    rows = {row.identity: row.status for row in result.frontier.entries}
    assert rows[SEED] is FrontierStatus.done
    assert [page.source_url for page in mirror.written_pages] == [SEED]


# --- convert-breakage B2 / convert-conformance C3: math with TeX keeps its ids --------


def test_b2_c3_math_with_a_tex_annotation_keeps_its_own_and_descendant_ids() -> None:
    """BodyShape (convert.allium 250 to 258): every source id is kept as an anchor.

    The ids of the math element and of its descendants are held before the TeX.
    """
    html = (
        "<main><h1>T</h1><p>See <math id='formula'><semantics><mi id='var'>x</mi>"
        "<annotation encoding='application/x-tex'>x</annotation></semantics></math>"
        " here.</p></main>"
    )
    body, anchors = converted(html)
    assert {"formula", "var"} <= anchors
    assert '<a id="formula"></a><a id="var"></a>$x$' in body
    assert "See" in body
    assert "here." in body


def test_b2_c3_block_math_keeps_its_id_on_a_line_of_its_own() -> None:
    """Display math's id holder is a block, as a callout's is."""
    html = (
        "<main><h1>T</h1><math id='eq' display='block'><semantics><mi>y</mi>"
        "<annotation encoding='application/x-tex'>y</annotation></semantics></math></main>"
    )
    body, anchors = converted(html)
    assert "eq" in anchors
    assert '<a id="eq"></a>' in body
    assert "y" in body


# --- convert-conformance C1: chrome is stripped from profile-selected content ---------


def test_c1_profile_selected_content_has_its_chrome_stripped() -> None:
    """ExtractedContent.html is the content, chrome stripped (convert.allium 144, 190-191).

    A nav inside the selected element leaves the body and counts as navigation outside
    the content, so its links still reach the navigation targets.
    """
    html = (
        "<html><body><main><nav><a href='/guide/next.html'>Navigation chrome</a></nav>"
        "<h1>Guide</h1><p>Body</p><footer>Footer chrome</footer></main></body></html>"
    )
    extracted = extract(html, PAGE_URL, profiles.GENERIC)
    assert extracted.method.name == "profile"
    assert "chrome" not in extracted.html
    assert extracted.navigation_targets == ("https://example.com/guide/next.html",)
    body, _ = converted(html)
    assert body == "# Guide\n\nBody\n"


# --- command-breakage B2: an empty unknown section of rovo.toml is refused -------------


def test_b2_an_empty_unknown_section_is_refused_by_fetch_and_sync(tmp_path: Path) -> None:
    """RefuseFetchOnBadConfig (rovo.allium 929 to 932): an unknown section is refused.

    An empty table has no key, so it is checked as a section of its own.
    """
    path = tmp_path / "rovo.toml"
    path.write_text("[typo]\n", encoding="utf-8")
    fetched = resolve_fetch_config(path)
    assert not fetched.valid
    assert fetched.problems == ("typo: unknown section",)
    assert "typo: unknown section" in resolve_config(tmp_path).problems


def test_b2_an_empty_known_section_stays_valid(tmp_path: Path) -> None:
    """An empty known section sets nothing and is no problem; an empty [fetch] neither."""
    path = tmp_path / "rovo.toml"
    path.write_text("[crawl]\n[fetch]\n", encoding="utf-8")
    fetched = resolve_fetch_config(path)
    assert fetched.valid
    assert fetched.problems == ()
    assert not any(
        "crawl" in problem or "fetch" in problem for problem in resolve_config(tmp_path).problems
    )


# --- command-conformance C1: without --config, fetch follows any path on the URL's host


def test_c1_fetch_without_config_follows_a_same_host_redirect_into_another_directory(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FetchOneUrl guidance (rovo.allium 973 to 975): the scope is the URL's own host.

    Without --config, a redirect to another directory of that host is followed and the
    page printed.
    """
    site_url = "http://docs.example"
    page_url = f"{site_url}/guide/start.html"
    moved = f"{site_url}/new/start.html"
    fetcher = FakeFetcher(
        {
            f"{site_url}/robots.txt": text_response(f"{site_url}/robots.txt", ""),
            page_url: redirect_response(page_url, moved),
            moved: html_response(moved, "<main><h1>Moved guide</h1><p>Words.</p></main>"),
        }
    )
    assert fetched(page_url, fetcher) is ExitCode.ok
    assert moved in fetcher.requests
    assert "# Moved guide" in capsys.readouterr().out


# --- command-breakage B1: a crash while the report is assembled is recorded -----------


def test_b1_a_crash_while_the_report_is_assembled_leaves_an_interrupted_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RecordCrashAfterRun (rovo.allium 795 to 798): a crash in the report is recorded.

    A crash after the run has ended, in finalisation or while the report is assembled,
    is recorded on the open report, which is written as it stands; the sync exits
    partial and the run keeps its id.
    """
    out_dir = initialised(tmp_path / "out")
    assert synced(out_dir, command_site()) is ExitCode.ok
    real = _report.summarise
    calls: list[int] = []

    def once(*args: object, **kwargs: object) -> object:
        calls.append(1)
        if len(calls) == 1:
            message = "summary"
            raise RuntimeError(message)
        return real(*args, **kwargs)  # type: ignore[arg-type]  # Passed through unchanged.

    monkeypatch.setattr(_report, "summarise", once)
    assert synced(out_dir, command_site()) is ExitCode.partial
    data = report(out_dir)
    assert data["run_id"] == SECOND_RUN
    assert data["report_status"] == "interrupted"
    assert data["error"] == "RuntimeError: summary"
    assert data["exit_code"] == "partial"
    runs = json.loads((out_dir / ".rovo" / "runs.json").read_text(encoding="utf-8"))["runs"]
    assert [row["id"] for row in runs] == [1, 2]


# --- crawl-breakage B2: a browser subrequest is fulfilled with its bytes ---------------

WASM = b"\x00asm\x01\x00\x00\x00\xff\xfe\x80"


def test_b2_the_fetcher_keeps_the_bytes_as_they_arrived() -> None:
    """A body that is not UTF-8 is kept byte for byte beside its decoded text."""

    def answer(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=WASM, headers={"content-type": "application/wasm"})

    with HttpxFetcher(transport=httpx.MockTransport(answer)) as fetcher:
        response = fetcher.fetch("http://docs.example/guide/app.wasm")
    assert response.content == WASM
    assert response.size == len(WASM)
    assert response.content_type == "application/wasm"


def test_b2_a_binary_subrequest_is_fulfilled_byte_identical(
    stub_playwright: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AttemptTier (crawl.allium 1738 to 1759): a subrequest keeps its bytes.

    It is served through the http session, and its bytes reach the browser unchanged,
    not re-encoded from decoded text.
    """
    seed = SEED
    wasm_url = f"{SITE}/guide/app.wasm"
    stub_playwright.subrequests[seed] = ["app.wasm"]
    bodies: dict[str, object] = {}
    real = test_browser_engine.StubRoute.fulfill

    def recorded(route: test_browser_engine.StubRoute, **kwargs: object) -> None:
        bodies[route.request.url] = kwargs.get("body")
        if isinstance(kwargs.get("body"), bytes):
            kwargs["body"] = "bytes"  # The stub decodes text; the bytes are recorded above.
        real(route, **kwargs)  # type: ignore[arg-type]  # playwright's keywords, passed on.

    monkeypatch.setattr(test_browser_engine.StubRoute, "fulfill", recorded)
    wasm = SiteResponse(
        status=200,
        source_url=wasm_url,
        markup=WASM.decode(errors="replace"),
        content=WASM,
        size=len(WASM),
        content_type="application/wasm",
    )
    page = PAGE
    answers = Answers({seed: html_response(seed, page), wasm_url: wasm})
    engine = PlaywrightEngine()
    try:
        assert engine.render(seed, answers) is not None
    finally:
        engine.close()
    assert bodies[wasm_url] == WASM
    assert bodies[seed] == page


# --- carried note (c): the two guard sites no test reached ---------------------------


def test_note_c_retires_host_on_long_crawl_delay_holds_its_guards(tmp_path: Path) -> None:
    """RetireHostOnLongCrawlDelay's guards: no rules, or Crawl-delay not honoured.

    Either retires nothing, however long the delay declared.
    """
    run, _, host = opened_host(tmp_path)
    long_delay = Decimal(10**9)
    adopted = RobotsPolicy(
        run=run,
        origin="http://docs.example",
        stance=RobotsStance.allow_all,
        crawl_delay=None,
        declared_sitemaps=(),
        problem=None,
        declared_delay=long_delay,
    )
    assert not retires_host_on_long_crawl_delay(run, adopted)
    run.policy = dataclasses.replace(standard_policy(), honor_crawl_delay=False)
    ruled = dataclasses.replace(adopted, stance=RobotsStance.rules, rules=object())  # type: ignore[arg-type]  # Any rules object: only its presence is read.
    assert not retires_host_on_long_crawl_delay(run, ruled)
    assert not host.breaker_tripped


def test_note_c_stop_walk_on_tripped_host_leaves_a_settled_walk_alone(tmp_path: Path) -> None:
    """StopWalkOnTrippedHost requires walk.status = walking.

    A walk already settled on a tripped host is not stopped a second time.
    """
    run, frontier, host = opened_host(tmp_path)
    attempt = walking_attempt(run, frontier, html_response(SEED, "", status=500))
    assert attempt.retryable
    trip(host)
    attempt.walk.status = WalkStatus.settled
    assert stop_walk_on_tripped_host(attempt) is None
    assert attempt.walk.entry.status is FrontierStatus.in_progress
