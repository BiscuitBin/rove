"""The links slice's hand-written tests: the guarantees, the pass's pieces, a whole sync.

`RelativeLinksOnly` and `CodeSamplesNeverRewritten` (mirror.allium 1407 and 1429) have
no obligation id; each has a test named after it. The rest pin what the ticket's step 5
and step 6 ask: `rewrite_destinations` idempotent, `relative_path` across hosts,
`find_broken_links` firing, the manifest's links, the request order of a sync over
several batches through `FakeFetcher`, and the crawl scope's bounds as links meet them.
"""

import dataclasses
import json
from pathlib import Path

from fakes import FakeFetcher, FixedClock, html_response
from rovo import _commands
from rovo._convert.fidelity import link_destinations
from rovo._crawl.model import FrontierStatus
from rovo._crawl.run import enqueue_page_links, load_frontier, run_crawl
from rovo._mirror.finalise import finalise, finalise_page_body, page_file_text, publish_page
from rovo._mirror.links import (
    find_broken_links,
    relative_path,
    resolve_mirror_links,
    rewrite_destinations,
)
from rovo._mirror.model import BrokenLink, BrokenLinkReason, Operator, StoreOutcome
from rovo._mirror.state import load_mirror, save_mirror
from rovo._report import ExitCode, report_path
from test_crawl import (
    B_PAGE,
    C_PAGE,
    D_PAGE,
    OUTSIDE_PAGE,
    ROBOTS,
    SECRET_PAGE,
    links_site,
    request,
    stored_seed,
)
from test_crawl import SEED as CRAWL_SEED
from test_crawl import SITE as CRAWL_SITE
from test_crawl import new_mirror as crawl_mirror
from test_mirror import (
    LINKED_BODY,
    OTHER,
    REWRITTEN_BODY,
    SEED,
    UNIDENTIFIABLE,
    content,
    finalised_pass,
    link_pass,
    linked_mirror,
    new_mirror,
    rows,
    stored,
)

API = "https://api.example"
REF = f"{API}/guide/ref.html"
REF_BODY = (
    "# Reference\n"
    "\n"
    "The reference lists every call of the example product's interface.\n"
    "\n"
    "## Authentication {#auth}\n"
    "\n"
    "Send the token with every call.\n"
)
CROSS_BODY = (
    "# Getting started\n"
    "\n"
    f"See the [authentication reference]({REF}#auth) and the [whole reference]({REF}).\n"
)
CODE_LINES = (
    f"Inline code `[other]({OTHER})` stays as written.\n",
    f"[other]({OTHER})\n",
)


def two_host_mirror(out_dir: Path) -> tuple[Path, str, str]:
    """docs.example's seed links api.example's reference; both finalised and published."""
    mirror = new_mirror(out_dir, allowed_hosts=frozenset({"docs.example", "api.example"}))
    start = stored(mirror, converted=content(body=CROSS_BODY, link_targets=(f"{REF}#auth", REF)))
    ref = stored(
        mirror, requested=REF, converted=content(body=REF_BODY, anchors=frozenset({"auth"}))
    )
    finalised_pass(mirror)
    return out_dir, start.path, ref.path


def test_RelativeLinksOnly(tmp_path: Path) -> None:
    """A link to a written page is a relative path plus its fragment; others stay absolute.

    Between hosts the path climbs to pages/ and descends again.
    """
    out, start_path, ref_path = two_host_mirror(tmp_path / "hosts")
    assert start_path.startswith("pages/docs.example/")
    assert ref_path.startswith("pages/api.example/")
    climbed = relative_path(start_path, ref_path)
    assert climbed.startswith("../api.example/")
    text = (out / start_path).read_text(encoding="utf-8")
    assert f"[authentication reference]({climbed}#auth)" in text
    assert f"[whole reference]({climbed})" in text
    assert REF not in text

    mirror, start, other = linked_mirror(tmp_path / "one")
    finalised_pass(mirror)
    body = (tmp_path / "one" / start.path).read_text(encoding="utf-8")
    assert body.endswith(REWRITTEN_BODY)
    held = {SEED, OTHER}
    for destination in link_destinations(start.body):
        if destination.startswith(("http://", "https://", "mailto:")):
            assert destination.split("#", 1)[0] not in held, destination
        elif destination.startswith("#"):
            assert destination[1:] in start.anchors
        else:
            file_part = destination.split("#", 1)[0]
            assert (tmp_path / "one" / Path(start.path).parent / file_part).is_file()
    assert other.body == other.converted_body


def test_CodeSamplesNeverRewritten(tmp_path: Path) -> None:
    """Destinations in fenced and inline code are neither rewritten nor verified."""
    mirror, start, _ = linked_mirror(tmp_path)
    finalised_pass(mirror)
    for line in CODE_LINES:
        assert line in LINKED_BODY
        assert line in start.body
    path = tmp_path / start.path
    path.write_text(
        path.read_text(encoding="utf-8") + "\n`[x](gone.md)`\n\n```\n[y](../../../gone.md)\n```\n",
        encoding="utf-8",
    )
    assert find_broken_links(mirror) == []


def test_rewrite_destinations_is_idempotent(tmp_path: Path) -> None:
    """Rewriting starts from the converted body, so a second finalisation changes nothing."""
    mirror, start, _ = linked_mirror(tmp_path)
    pass_ = finalised_pass(mirror)
    first = (start.body, start.content_digest, page_file_text(start))
    assert rewrite_destinations(start.converted_body, start) == start.body
    finalised_pass(mirror)
    assert (start.body, start.content_digest, page_file_text(start)) == first
    assert publish_page(pass_, start, FixedClock()).outcome is StoreOutcome.unchanged


def test_relative_path_between_page_files() -> None:
    """Between two mirror-relative page files, from the linking file's directory."""
    assert relative_path("pages/a.example/guide/x.md", "pages/b.example/y.md") == (
        "../../b.example/y.md"
    )
    assert relative_path("pages/h/start.md", "pages/h/b.md") == "b.md"
    assert relative_path("pages/h/start.md", "pages/h/deep/c.md") == "deep/c.md"
    assert relative_path("pages/h/deep/c.md", "pages/h/start.md") == "../start.md"


def test_find_broken_links_fires(tmp_path: Path) -> None:
    """A deleted target file, a path out of the mirror and an absent fragment are found."""
    mirror, start, other = linked_mirror(tmp_path)
    finalised_pass(mirror)
    assert find_broken_links(mirror) == []
    path = tmp_path / start.path
    path.write_text(
        path.read_text(encoding="utf-8") + "\n[up](../../../x.md) [nowhere](other.md#nope)\n",
        encoding="utf-8",
    )
    (tmp_path / other.path).unlink()
    found = find_broken_links(mirror)
    assert (
        BrokenLink(from_path=start.path, href="other.md", reason=BrokenLinkReason.missing_file)
        in found
    )
    assert (
        BrokenLink(
            from_path=start.path, href="../../../x.md", reason=BrokenLinkReason.outside_mirror
        )
        in found
    )
    assert {row.reason for row in found} >= {
        BrokenLinkReason.missing_file,
        BrokenLinkReason.outside_mirror,
    }


def test_find_broken_links_absent_fragment(tmp_path: Path) -> None:
    """A fragment that is no {#id} heading anchor of the target file is broken."""
    mirror, start, _ = linked_mirror(tmp_path)
    finalised_pass(mirror)
    path = tmp_path / start.path
    path.write_text(path.read_text(encoding="utf-8") + "\n[x](other.md#nope)\n", encoding="utf-8")
    assert find_broken_links(mirror) == [
        BrokenLink(
            from_path=start.path, href="other.md#nope", reason=BrokenLinkReason.fragment_not_found
        )
    ]


def test_find_broken_links_spares_a_fragment_recorded_unresolved(tmp_path: Path) -> None:
    """A fragment the page's internal Link records unresolved is no broken link (32f2210).

    The seed links other.md#missing, absent upstream: unresolved_fragment reports it, so
    find_broken_links stays empty after a complete finalisation.
    """
    mirror, start, other = linked_mirror(tmp_path)
    pass_ = finalised_pass(mirror)
    unresolved = [link for link in start.outbound_links if not link.fragment_resolved]
    assert [(link.target, link.fragment) for link in unresolved] == [(other, "missing")]
    assert "[missing step](other.md#missing)" in (tmp_path / start.path).read_text(
        encoding="utf-8"
    )
    assert find_broken_links(mirror) == []
    assert pass_.broken_links == []


def test_find_broken_links_names_a_missing_page_file(tmp_path: Path) -> None:
    """A missing page file is one BrokenLink: its own path, href "" and missing_file."""
    mirror, start, other = linked_mirror(tmp_path)
    finalised_pass(mirror)
    (tmp_path / other.path).unlink()
    found = find_broken_links(mirror)
    assert [row for row in found if row.from_path == other.path] == [
        BrokenLink(from_path=other.path, href="", reason=BrokenLinkReason.missing_file)
    ]
    assert all(row.href for row in found if row.from_path == start.path)


def test_an_unidentifiable_destination_records_no_link_and_stays(tmp_path: Path) -> None:
    """A URL with no identity fires no LinkTo* rule and is left byte for byte (32f2210)."""
    mirror = new_mirror(tmp_path)
    body = f"# Getting started\n\nSee the [odd port]({UNIDENTIFIABLE}#top) page.\n"
    page = stored(mirror, converted=content(body=body, link_targets=(UNIDENTIFIABLE,)))
    pass_ = link_pass(mirror)
    assert resolve_mirror_links(pass_)
    assert mirror.links == []
    assert page.outbound_links == ()
    assert rewrite_destinations(body, page) == body
    finalise_page_body(pass_, page)
    assert page.body == body
    assert (page.has_uncrawled_link, page.has_dangling_link, page.has_unresolved_fragment) == (
        False,
        False,
        False,
    )


def test_manifest_keeps_the_links(tmp_path: Path) -> None:
    """The manifest's links rows load back as the same links, written sorted."""
    mirror, start, _ = linked_mirror(tmp_path)
    finalised_pass(mirror)
    save_mirror(mirror)
    data = json.loads((tmp_path / ".rovo" / "manifest.json").read_text(encoding="utf-8"))
    assert len(data["links"]) == len(mirror.links)
    loaded = load_mirror(tmp_path)
    order = [
        (link.source.identity, link.target_identity, link.fragment or "") for link in loaded.links
    ]
    assert order == sorted(order)
    again = next(page for page in loaded.pages if page.identity == start.identity)
    assert rows(again.outbound_links) == rows(start.outbound_links)
    assert {
        (link.target_identity, None if link.target is None else link.target.identity)
        for link in loaded.links
    } == {
        (link.target_identity, None if link.target is None else link.target.identity)
        for link in mirror.links
    }


def test_sync_follows_links_in_batches(tmp_path: Path) -> None:
    """A whole sync over the links site through FakeFetcher.

    robots.txt, the seed, then its in-scope links in next_pending order, then the next
    depth; no URL twice; the robots-disallowed and out-of-scope URLs never requested.
    """
    out = tmp_path / "out"
    assert _commands.init(CRAWL_SEED, out) is ExitCode.ok
    fetcher = links_site()
    assert _commands.sync(out, fetcher=fetcher, clock=FixedClock()) is ExitCode.ok
    assert fetcher.requests == [ROBOTS, CRAWL_SEED, B_PAGE, C_PAGE, D_PAGE]
    assert len(set(fetcher.requests)) == len(fetcher.requests)
    assert SECRET_PAGE not in fetcher.requests
    assert OUTSIDE_PAGE not in fetcher.requests
    report = json.loads(report_path(out).read_text(encoding="utf-8"))
    assert report["broken_links"] == []
    assert report["converted"] == len([CRAWL_SEED, B_PAGE, C_PAGE, D_PAGE])
    frontier = json.loads((out / ".rovo" / "frontier.json").read_text(encoding="utf-8"))
    statuses = {row["identity"]: row["status"] for row in frontier["entries"]}
    assert statuses[SECRET_PAGE] == FrontierStatus.skipped_robots.value


def test_two_host_names_through_fake_fetcher(tmp_path: Path) -> None:
    """Two allowed hosts: each host's robots.txt is read, and the cross-host link climbs."""
    mirror = crawl_mirror(tmp_path, allowed_hosts=frozenset({"docs.example", "api.example"}))
    seed_page = (
        "<!doctype html><html><head><title>Start</title></head><body><main>"
        "<h1>Getting started</h1><p>The example product documents its interface in the "
        f'<a href="{REF}#auth">reference</a> on another host.</p></main></body></html>'
    )
    ref_page = (
        "<!doctype html><html><head><title>Reference</title></head><body><main>"
        "<h1>Reference</h1><p>The reference lists every call of the example product.</p>"
        '<h2 id="auth">Authentication</h2><p>Send the token with every call.</p>'
        "</main></body></html>"
    )
    fetcher = FakeFetcher(
        {CRAWL_SEED: html_response(CRAWL_SEED, seed_page), REF: html_response(REF, ref_page)}
    )
    result = run_crawl(request(mirror), load_frontier(mirror), fetcher, FixedClock())
    assert f"{API}/robots.txt" in fetcher.requests
    assert ROBOTS in fetcher.requests
    assert fetcher.requests[-2:] == [CRAWL_SEED, REF]
    finalise(Operator(), mirror, result.run.id, FixedClock())
    start = mirror.known_page(CRAWL_SEED)
    ref = mirror.known_page(REF)
    assert start is not None
    assert ref is not None
    text = (tmp_path / start.path).read_text(encoding="utf-8")
    assert f"]({relative_path(start.path, ref.path)}#auth)" in text
    assert relative_path(start.path, ref.path).startswith("../api.example/")


def test_crawl_scope_bounds_as_links_meet_them(tmp_path: Path) -> None:
    """Include, exclude, prefix, another port on an allowed host, and depth."""
    run, frontier, found = stored_seed(tmp_path, links_site())
    other_port = f"{CRAWL_SITE}:8080/guide/b.html"
    run.target.scope = dataclasses.replace(
        run.target.scope, include=("*/guide/*",), exclude=("*/private/*",)
    )
    targets = (B_PAGE, C_PAGE, SECRET_PAGE, OUTSIDE_PAGE, other_port, f"{CRAWL_SITE}/x.html")
    bounded = dataclasses.replace(found, targets=targets, navigation_targets=())
    enqueue_page_links(run, frontier, bounded)
    identities = [entry.identity for entry in frontier.entries]
    assert identities == [CRAWL_SEED, B_PAGE, C_PAGE, other_port]

    run.target.scope = dataclasses.replace(run.target.scope, include=("*/deep/*",), exclude=())
    deeper = dataclasses.replace(found, targets=(D_PAGE, SECRET_PAGE), navigation_targets=())
    enqueue_page_links(run, frontier, deeper)
    assert frontier.entry(D_PAGE) is not None
    assert frontier.entry(SECRET_PAGE) is None

    too_deep = dataclasses.replace(
        found,
        depth=run.target.scope.max_depth,
        targets=(f"{CRAWL_SITE}/guide/deep/e.html",),
        navigation_targets=(),
    )
    enqueue_page_links(run, frontier, too_deep)
    assert frontier.entry(f"{CRAWL_SITE}/guide/deep/e.html") is None
