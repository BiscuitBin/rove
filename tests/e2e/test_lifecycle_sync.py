"""End to end: a page's lifecycle across syncs (T15).

Removal and archive, revival, a move with its alias, a redirect out of scope, a
duplicate, a narrowed scope and discovery redirects, each against a site generated into
tmp_path by this module's own helper: served first, so its base URL is known, then
written, since `http.server` reads each file per request. A deleted file answers 404; a
redirect is scripted (`script=` for the answers before it, `always=` for the redirect).
The scenarios run `rovo._commands.sync` in process over the real HttpxFetcher on a
FixedClock, which never sleeps; robots.txt declares no Crawl-delay and no sitemap, and
there is no llms.txt. A page path strips the scope prefix /guide/, so <base>guide/x.html
is pages/<host>/x.md and its archived copy _removed/<host>/x.md. Not `test_mirror.py` or
`test_crawl.py`, which the unit suite names.
"""

import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import timedelta
from pathlib import Path

from conftest import Answer, SiteServer
from test_init_sync import load, markdown_files, page_root, split_page

from fakes import START, FixedClock
from rovo import _commands
from rovo._crawl.fetch import HttpxFetcher
from rovo._exit import ExitCode
from rovo._mirror.state import timestamp

PAGE_HTML = """<!doctype html>
<html lang="en">
    <head><title>{title} | Example docs</title></head>
    <body>
        <main>
            <h1>{title}</h1>
            <p>{prose}</p>
{links}        </main>
    </body>
</html>
"""
ROBOTS = "User-agent: *\n"
HTML = {"Content-Type": "text/html"}
A_MINUTE = 60
NEXT_DAY = START + timedelta(days=1)
ELSEWHERE = "http://elsewhere.invalid/away.html"
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def write(root: Path, path: str, text: str) -> None:
    """Write one file of a generated site."""
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def page_html(title: str, links: Sequence[str] = ()) -> str:
    """A page: a title, and a main holding an h1, a paragraph and a link per href."""
    anchors = "".join(f'            <p><a href="{href}">{href}</a></p>\n' for href in links)
    prose = f"{title} is described here in a sentence of plain prose."
    return PAGE_HTML.format(title=title, prose=prose, links=anchors)


def served(
    serve_site: SiteServer,
    tmp_path: Path,
    *,
    script: Mapping[str, Sequence[Answer]] | None = None,
    always: Mapping[str, Answer] | None = None,
) -> tuple[Path, str]:
    """Serve an empty directory with its robots.txt; the site's pages are written after."""
    root = tmp_path / "site"
    root.mkdir()
    base = serve_site(root, script=script, always=always)
    write(root, "robots.txt", ROBOTS)
    return root, base


def initialised(base: str, tmp_path: Path) -> Path:
    """`rovo init <base>guide/start.html <tmp>/out`, in process."""
    out = tmp_path / "out"
    assert _commands.init(f"{base}guide/start.html", out) is ExitCode.ok
    return out


def synced(out: Path, clock: FixedClock | None = None) -> ExitCode:
    """Rovo sync in process over the real HttpxFetcher, on a FixedClock."""
    with HttpxFetcher() as fetcher:
        return _commands.sync(out, fetcher=fetcher, clock=clock or FixedClock())


def requested(serve_site: SiteServer, base: str, since: int) -> list[str]:
    """The paths the server was asked for after the first `since` requests."""
    return serve_site.paths(base)[since:]


def manifest(out: Path) -> dict[str, object]:
    """.rovo/manifest.json."""
    return load(out / ".rovo" / "manifest.json")


def record(out: Path, identity: str) -> dict[str, object]:
    """The manifest's record of the page whose identity is `identity`."""
    pages = manifest(out)["pages"]
    assert isinstance(pages, list)
    (found,) = [page for page in pages if page["identity"] == identity]
    assert isinstance(found, dict)
    return found


def aliases(out: Path) -> list[tuple[str, str]]:
    """The manifest's aliases as (url, target identity), sorted."""
    rows = manifest(out)["aliases"]
    assert isinstance(rows, list)
    return sorted((row["url"], row["target"]) for row in rows)


def frontier_status(out: Path, identity: str) -> object:
    """frontier.json's status of the row for `identity`."""
    entries = load(out / ".rovo" / "frontier.json")["entries"]
    assert isinstance(entries, list)
    (row,) = [row for row in entries if row["identity"] == identity]
    return row["status"]


def changes(out: Path) -> list[dict[str, object]]:
    """crawl-report.json's changes."""
    rows = load(out / "crawl-report.json")["changes"]
    assert isinstance(rows, list)
    return rows


def removed_host(base: str) -> str:
    """_removed/<host segment>/, the archive's mirror of pages/<host segment>/."""
    return "_removed/" + page_root(base).removeprefix("pages/")


def jsonl(path: Path) -> list[dict[str, object]]:
    """Every line of a JSON Lines file."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_an_absent_page_is_archived_and_revived_in_place(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """A 404 removes and archives a page; a later sync revives it at the same path.

    RemoveAbsentPage, RetirePage and the archive under _removed/<host>/, LinkToRemovedPage
    (a dangling link), TallyRemoval; a third sync rechecks the removed page and reports
    no second removal (AcceptAbsentWithoutPage); restored, the page is revived in place
    (ReviveRemovedPage), reported added, its first_seen the reviving sync's clock.
    """
    root, base = served(serve_site, tmp_path)
    write(root, "guide/start.html", page_html("Getting started", ["gone.html"]))
    write(root, "guide/gone.html", page_html("A topic that goes away"))
    gone_html = (root / "guide" / "gone.html").read_text(encoding="utf-8")
    out = initialised(base, tmp_path)
    assert synced(out) is ExitCode.ok
    pages = page_root(base)
    gone_url, gone_path = f"{base}guide/gone.html", f"{pages}gone.md"
    archived = f"{removed_host(base)}gone.md"
    assert markdown_files(out) == [gone_path, f"{pages}start.md"]
    published = (out / gone_path).read_bytes()

    (root / "guide" / "gone.html").unlink()
    since = len(serve_site.paths(base))
    assert synced(out) is ExitCode.ok
    assert "/guide/gone.html" in requested(serve_site, base, since)
    gone = record(out, gone_url)
    assert (gone["status"], gone["removal_reason"]) == ("removed", "absent")
    assert gone["path"] == gone_path
    assert not (out / gone_path).exists()
    assert (out / archived).read_bytes() == published
    assert frontier_status(out, gone_url) == "absent"
    links = {row["url"]: row for row in jsonl(out / "links.jsonl")}
    assert links[gone_url]["kind"] == "dangling"
    frontmatter, _ = split_page((out / f"{pages}start.md").read_text(encoding="utf-8"))
    assert "dangling_inbound" in json.loads(frontmatter["quality_flags"])
    assert gone_url not in {row["identity"] for row in jsonl(out / "index.jsonl")}
    removed_rows = [row for row in changes(out) if row["kind"] == "removed"]
    assert removed_rows == [
        {"kind": "removed", "url": gone_url, "path": gone_path, "moved_from": None}
    ]

    since = len(serve_site.paths(base))
    assert synced(out) is ExitCode.ok
    assert "/guide/gone.html" in requested(serve_site, base, since)
    assert [row for row in changes(out) if row["kind"] == "removed"] == []
    assert record(out, gone_url)["status"] == "removed"

    write(root, "guide/gone.html", gone_html)
    restored = root / "guide" / "gone.html"
    later = restored.stat().st_mtime + A_MINUTE
    os.utime(restored, (later, later))
    assert synced(out, FixedClock(NEXT_DAY)) is ExitCode.ok
    revived = record(out, gone_url)
    assert revived["status"] == "written"
    assert revived["path"] == gone_path
    assert revived["first_seen"] == timestamp(NEXT_DAY)
    assert (out / gone_path).is_file()
    assert not (out / "_removed").exists()
    assert {"kind": "added", "url": gone_url, "path": gone_path, "moved_from": None} in changes(
        out
    )


def test_a_redirected_page_moves_with_an_alias(serve_site: SiteServer, tmp_path: Path) -> None:
    """A known page whose URL now redirects within the scope moves (MovePage).

    old.html answers once, then always 301 to /guide/new.html. The second sync follows
    the hop, moves the page to new.md with old.html its alias, reports it moved and not
    added, and rewrites the seed's link to new.md.
    """
    old_html = page_html("A topic that moves")
    root, base = served(
        serve_site,
        tmp_path,
        script={"/guide/old.html": [Answer(200, HTML, old_html)]},
        always={"/guide/old.html": Answer(301, {"Location": "/guide/new.html"})},
    )
    write(root, "guide/start.html", page_html("Getting started", ["old.html"]))
    write(root, "guide/new.html", old_html)
    out = initialised(base, tmp_path)
    assert synced(out) is ExitCode.ok
    pages = page_root(base)
    assert markdown_files(out) == [f"{pages}old.md", f"{pages}start.md"]

    since = len(serve_site.paths(base))
    assert synced(out) is ExitCode.ok
    hops = [
        path
        for path in requested(serve_site, base, since)
        if path in {"/guide/old.html", "/guide/new.html"}
    ]
    assert hops == ["/guide/old.html", "/guide/new.html"]
    new_url, old_url = f"{base}guide/new.html", f"{base}guide/old.html"
    moved = record(out, new_url)
    assert (moved["path"], moved["status"]) == (f"{pages}new.md", "written")
    assert not (out / f"{pages}old.md").exists()
    assert (out / f"{pages}new.md").is_file()
    assert (old_url, new_url) in aliases(out)
    rows = {row["url"]: row for row in changes(out)}
    assert rows[new_url]["kind"] == "moved"
    assert rows[new_url]["moved_from"] == f"{pages}old.md"
    assert all(row["kind"] != "added" for row in changes(out))
    _, body = split_page((out / f"{pages}start.md").read_text(encoding="utf-8"))
    assert "(new.md)" in body
    assert "old.md" not in body


def test_a_page_redirected_out_is_removed_and_a_second_url_is_a_duplicate(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """A duplicate in one sync, then a known page that redirects out of scope.

    beta always redirects to alpha: whichever is fetched first is stored, the other row
    is a duplicate and beta is alpha's alias. away answers once, then always 301 to
    elsewhere.invalid: the second sync removes it as redirected_out, recording the
    target, archives its file and settles its row done. The .invalid name never
    resolves, so a followed hop would have failed the row instead.
    """
    root, base = served(
        serve_site,
        tmp_path,
        script={"/guide/away.html": [Answer(200, HTML, page_html("A topic that leaves"))]},
        always={
            "/guide/beta.html": Answer(301, {"Location": "/guide/alpha.html"}),
            "/guide/away.html": Answer(301, {"Location": ELSEWHERE}),
        },
    )
    write(
        root,
        "guide/start.html",
        page_html("Getting started", ["alpha.html", "beta.html", "away.html"]),
    )
    write(root, "guide/alpha.html", page_html("The alpha topic"))
    out = initialised(base, tmp_path)
    assert synced(out) is ExitCode.ok
    pages = page_root(base)
    alpha, beta, away = (f"{base}guide/{name}.html" for name in ("alpha", "beta", "away"))
    assert markdown_files(out) == [f"{pages}alpha.md", f"{pages}away.md", f"{pages}start.md"]
    assert {frontier_status(out, alpha), frontier_status(out, beta)} == {"done", "duplicate"}
    assert record(out, alpha)["path"] == f"{pages}alpha.md"
    assert (beta, alpha) in aliases(out)
    _, body = split_page((out / f"{pages}start.md").read_text(encoding="utf-8"))
    assert f"{base}guide/beta.html" not in body
    assert body.count("(alpha.md)") == len(["alpha link", "beta link"])
    published = (out / f"{pages}away.md").read_bytes()

    assert synced(out) is ExitCode.ok
    gone = record(out, away)
    assert (gone["status"], gone["removal_reason"]) == ("removed", "redirected_out")
    assert gone["redirect_target"] == ELSEWHERE
    assert not (out / f"{pages}away.md").exists()
    assert (out / f"{removed_host(base)}away.md").read_bytes() == published
    assert frontier_status(out, away) == "done"
    assert [row["url"] for row in changes(out) if row["kind"] == "removed"] == [away]


def test_a_narrowed_scope_retires_pages_it_no_longer_admits(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """RetireOutOfScopePages: path_prefixes narrows to /guide/keep/ between syncs.

    The second sync never requests drop/b.html, retires it out_of_scope at
    finalisation, archives it under _removed/<host>/drop/, removes the emptied
    pages/<host>/drop/ and reports one removed row; the seed stays written.
    """
    root, base = served(serve_site, tmp_path)
    write(root, "guide/start.html", page_html("Getting started", ["keep/a.html", "drop/b.html"]))
    write(root, "guide/keep/a.html", page_html("A kept topic"))
    write(root, "guide/drop/b.html", page_html("A dropped topic"))
    out = initialised(base, tmp_path)
    assert synced(out) is ExitCode.ok
    pages = page_root(base)
    assert markdown_files(out) == [f"{pages}drop/b.md", f"{pages}keep/a.md", f"{pages}start.md"]
    published = (out / f"{pages}drop/b.md").read_bytes()
    config = out / "rovo.toml"
    text, count = re.subn(
        r"(?m)^path_prefixes = .*$",
        'path_prefixes = ["/guide/keep/"]',
        config.read_text(encoding="utf-8"),
    )
    assert count == 1
    config.write_text(text, encoding="utf-8")

    since = len(serve_site.paths(base))
    assert synced(out) is ExitCode.ok
    assert "/guide/drop/b.html" not in requested(serve_site, base, since)
    drop = f"{base}guide/drop/b.html"
    retired = record(out, drop)
    assert (retired["status"], retired["removal_reason"]) == ("removed", "out_of_scope")
    assert (out / f"{removed_host(base)}drop/b.md").read_bytes() == published
    assert not (out / f"{pages}drop").exists()
    assert [row["url"] for row in changes(out) if row["kind"] == "removed"] == [drop]
    assert record(out, f"{base}guide/start.html")["status"] == "written"
    assert markdown_files(out) == [f"{pages}keep/a.md", f"{pages}start.md"]


def test_discovery_follows_redirects_within_the_allowed_hosts(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """robots.txt and a sitemap reached through redirects (fetch_resource, T15).

    robots.txt answers 301 to /robots-real.txt, which disallows /guide/private/;
    /sitemap.xml answers 301 to /maps/site.xml, which names guide/orphan.html. The sync
    follows both, never requests the private page the seed links, writes the orphan and
    reports no discovery problem.
    """
    root, base = served(
        serve_site,
        tmp_path,
        always={
            "/robots.txt": Answer(301, {"Location": "/robots-real.txt"}),
            "/sitemap.xml": Answer(301, {"Location": "/maps/site.xml"}),
        },
    )
    write(root, "robots-real.txt", "User-agent: *\nDisallow: /guide/private/\n")
    rows = f"    <url>\n        <loc>{base}guide/orphan.html</loc>\n    </url>\n"
    write(
        root,
        "maps/site.xml",
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="{NS}">\n{rows}</urlset>\n',
    )
    write(root, "guide/start.html", page_html("Getting started", ["private/x.html"]))
    write(root, "guide/private/x.html", page_html("A private topic"))
    write(root, "guide/orphan.html", page_html("An orphan topic"))
    out = initialised(base, tmp_path)
    assert synced(out) is ExitCode.ok
    paths = serve_site.paths(base)
    assert {"/robots.txt", "/robots-real.txt", "/sitemap.xml", "/maps/site.xml"} <= set(paths)
    assert "/guide/private/x.html" not in paths
    pages = page_root(base)
    assert markdown_files(out) == [f"{pages}orphan.md", f"{pages}start.md"]
    assert load(out / "crawl-report.json")["discovery_problems"] == []


# The T15 follow-up (spec bad753c): rovo.toml's [mirror] prune, an absent row rechecked
# when a later sync names it again, and one spelling per directory.


def set_mirror_key(out: Path, key: str, value: str) -> None:
    """rovo.toml's [mirror] `key = value`: replaced if present, else added under [mirror]."""
    config = out / "rovo.toml"
    text = config.read_text(encoding="utf-8")
    line = f"{key} = {value}"
    text, count = re.subn(rf"(?m)^{re.escape(key)} = .*$", line, text)
    if not count:
        if "[mirror]\n" in text:
            text = text.replace("[mirror]\n", f"[mirror]\n{line}\n", 1)
        else:
            text = f"{text.rstrip()}\n\n[mirror]\n{line}\n"
    config.write_text(text, encoding="utf-8")


def test_mirror_prune_in_rovo_toml_deletes_a_removed_pages_file(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """rovo.toml's [mirror] prune = true reaches RetirePage (rovo.allium Configuration).

    gone.html answers 404 on the second sync: the page is removed as absent and reported
    removed, and under prune its file is deleted rather than archived, so no _removed/
    directory exists.
    """
    root, base = served(serve_site, tmp_path)
    write(root, "guide/start.html", page_html("Getting started", ["gone.html"]))
    write(root, "guide/gone.html", page_html("A topic that goes away"))
    out = initialised(base, tmp_path)
    assert synced(out) is ExitCode.ok
    pages = page_root(base)
    gone_url, gone_path = f"{base}guide/gone.html", f"{pages}gone.md"
    assert (out / gone_path).is_file()

    set_mirror_key(out, "prune", "true")
    (root / "guide" / "gone.html").unlink()
    assert synced(out) is ExitCode.ok
    gone = record(out, gone_url)
    assert (gone["status"], gone["removal_reason"]) == ("removed", "absent")
    assert not (out / gone_path).exists()
    assert not (out / "_removed").exists()
    assert [row["url"] for row in changes(out) if row["kind"] == "removed"] == [gone_url]
    assert markdown_files(out) == [f"{pages}start.md"]


def test_a_link_absent_last_sync_is_fetched_when_the_next_sync_names_it_again(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """crawl.allium PrepareRun and Enqueue (bad753c): an absent row is rechecked.

    The seed links to later.html, which does not exist on the first sync: its row is
    absent and no page is written. Before the second sync later.html is published and
    the seed changes; the seed's link names later.html again, so it is requested,
    written and reported added.
    """
    root, base = served(serve_site, tmp_path)
    write(root, "guide/start.html", page_html("Getting started", ["later.html"]))
    out = initialised(base, tmp_path)
    assert synced(out) is ExitCode.ok
    pages = page_root(base)
    later_url, later_path = f"{base}guide/later.html", f"{pages}later.md"
    assert frontier_status(out, later_url) == "absent"
    assert markdown_files(out) == [f"{pages}start.md"]

    write(root, "guide/later.html", page_html("A topic published later"))
    write(root, "guide/start.html", page_html("Getting started again", ["later.html"]))
    start = root / "guide" / "start.html"
    moved_on = start.stat().st_mtime + A_MINUTE
    os.utime(start, (moved_on, moved_on))
    since = len(serve_site.paths(base))
    assert synced(out) is ExitCode.ok
    assert "/guide/later.html" in requested(serve_site, base, since)
    assert frontier_status(out, later_url) == "done"
    assert record(out, later_url)["status"] == "written"
    assert (out / later_path).is_file()
    assert {
        "kind": "added",
        "url": later_url,
        "path": later_path,
        "moved_from": None,
    } in changes(out)


def test_a_directory_has_one_spelling_across_pages(serve_site: SiteServer, tmp_path: Path) -> None:
    """MovePage guidance (bad753c): sub/a and Sub/b land in one directory of pages/.

    Whichever page is stored first sets the directory's spelling; the other folds onto
    it, so both manifest paths share one directory and pages/<host>/ holds one directory
    entry for it.
    """
    root, base = served(serve_site, tmp_path)
    write(root, "guide/start.html", page_html("Getting started", ["sub/a.html", "Sub/b.html"]))
    write(root, "guide/sub/a.html", page_html("The a topic"))
    write(root, "guide/Sub/b.html", page_html("The b topic"))
    out = initialised(base, tmp_path)
    assert synced(out) is ExitCode.ok
    pages = page_root(base)
    a_path = str(record(out, f"{base}guide/sub/a.html")["path"])
    b_path = str(record(out, f"{base}guide/Sub/b.html")["path"])
    directory = a_path.removeprefix(pages).split("/")[0]
    assert directory.casefold() == "sub"
    assert (a_path, b_path) == (f"{pages}{directory}/a.md", f"{pages}{directory}/b.md")
    assert [entry.name for entry in (out / pages).iterdir() if entry.is_dir()] == [directory]
