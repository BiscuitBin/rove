"""End to end: a second rovo sync is incremental (T14).

Each scenario's site is generated into tmp_path by this module's own helper: served
first, so its base URL is known, then written, since `http.server` reads each file per
request. `http.server` sends a file's mtime as Last-Modified and no ETag, and answers 304
to an If-Modified-Since its file is not newer than, so a second sync of untouched files
gets a 304 for every page and sitemap it holds validators for; a file changed between
syncs has its mtime moved a minute forward. The scenarios run `rovo._commands.sync` in
process over the real HttpxFetcher on a FixedClock, which records every wait and never
sleeps; the robots.txt declares no Crawl-delay. Not `test_crawl.py` or `test_mirror.py`,
which the unit suite names.
"""

import json
import os
import re
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

from conftest import Answer, SiteServer
from test_init_sync import load, markdown_files, page_root, split_page

from fakes import START, FixedClock
from rovo import _commands
from rovo._crawl.fetch import HttpxFetcher
from rovo._exit import ExitCode

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
PAGE_HTML = """<!doctype html>
<html lang="en">
    <head><title>{title} | Example docs</title></head>
    <body>
        <main>
            <h1>{title}</h1>
            <p>{prose}</p>
{extra}        </main>
    </body>
</html>
"""
DISCOVERY_PATHS = ["/robots.txt", "/maps/guide.xml", "/sitemap.xml", "/sitemap_index.xml"]
LLMS_PATH = "/llms.txt"
PAGES = ("start", "linked", "orphan")
NEW_PARAGRAPH = "The dashboard now shows a summary of every installed product."
A_MINUTE = 60
LATER = START + timedelta(minutes=5)
VALIDATORS = {"etag", "last_modified"}


def write(root: Path, path: str, text: str) -> None:
    """Write one file of a generated site."""
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def page_html(title: str, links: tuple[str, ...] = (), extra: str = "") -> str:
    """A page: a title, and a main holding an h1, a paragraph and a link per path."""
    anchors = "".join(f'            <p><a href="{path}">{path}</a></p>\n' for path in links)
    prose = f"{title} is described here in a sentence of plain prose."
    return PAGE_HTML.format(title=title, prose=prose, extra=anchors + extra)


def write_site(root: Path, base: str, *, plain: bool = False) -> None:
    """The base site of tickets/T14-incremental.md step 5, linking plain.html if `plain`.

    robots.txt declares maps/guide.xml, which names the orphan and the outside page; the
    seed links linked.html; no page links any other; there is no llms.txt.
    """
    write(root, "robots.txt", f"User-agent: *\nSitemap: {base}maps/guide.xml\n")
    rows = "".join(
        f"    <url>\n        <loc>{base}{path}</loc>\n    </url>\n"
        for path in ("guide/orphan.html", "outside/page.html")
    )
    head = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="{NS}">\n'
    write(root, "maps/guide.xml", f"{head}{rows}</urlset>\n")
    links = ("linked.html", "plain.html") if plain else ("linked.html",)
    write(root, "guide/start.html", page_html("Getting started", links))
    write(root, "guide/linked.html", page_html("A linked topic"))
    write(root, "guide/orphan.html", page_html("An orphan topic"))
    write(root, "outside/page.html", page_html("A page outside the guide"))


def served(
    serve_site: SiteServer, tmp_path: Path, always: Mapping[str, Answer] | None = None
) -> tuple[Path, str]:
    """Serve an empty directory, then write the base site into it."""
    root = tmp_path / "site"
    root.mkdir()
    base = serve_site(root, always=always)
    return root, base


def synced(out: Path, clock: FixedClock | None = None) -> ExitCode:
    """Rovo sync in process over the real HttpxFetcher, on a FixedClock."""
    with HttpxFetcher() as fetcher:
        return _commands.sync(out, fetcher=fetcher, clock=clock or FixedClock())


def file_states(out: Path) -> dict[str, tuple[bytes, int, int]]:
    """Every file outside .rovo/ but crawl-report.json: its bytes, st_mtime_ns, st_ino."""
    states: dict[str, tuple[bytes, int, int]] = {}
    for path in sorted(out.rglob("*")):
        relative = path.relative_to(out).as_posix()
        if not path.is_file() or relative.startswith(".rovo/") or relative == "crawl-report.json":
            continue
        status = path.stat()
        states[relative] = (path.read_bytes(), status.st_mtime_ns, status.st_ino)
    return states


def page_rows(out: Path, base: str) -> dict[str, object]:
    """frontier.json's page rows: the status of each guide page, by its name."""
    entries = load(out / ".rovo" / "frontier.json")["entries"]
    assert isinstance(entries, list)
    prefix = f"{base}guide/"
    return {
        row["identity"].removeprefix(prefix).removesuffix(".html"): row["status"]
        for row in entries
        if row["identity"].startswith(prefix)
    }


def change_kinds(report: Mapping[str, object], base: str) -> dict[str, object]:
    """The report's changes: each page's kind, by its name."""
    changes = report["changes"]
    assert isinstance(changes, list)
    prefix = f"{base}guide/"
    return {row["url"].removeprefix(prefix).removesuffix(".html"): row["kind"] for row in changes}


def host_fetched(report: Mapping[str, object]) -> object:
    """per_host's one row's fetched."""
    per_host = report["per_host"]
    assert isinstance(per_host, list)
    (row,) = per_host
    return row["fetched"]


def snapshots_of(out: Path) -> list[dict[str, object]]:
    """.rovo/sitemaps.json's snapshot rows."""
    snapshots = load(out / ".rovo" / "sitemaps.json")["snapshots"]
    assert isinstance(snapshots, list)
    return snapshots


def assert_no_validators(out: Path) -> None:
    """No page file's frontmatter and no index.jsonl row carries etag or last_modified."""
    files = markdown_files(out)
    assert files
    for path in files:
        frontmatter, _ = split_page((out / path).read_text(encoding="utf-8"))
        assert set(frontmatter).isdisjoint(VALIDATORS), path
    lines = (out / "index.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(files)
    for line in lines:
        assert set(json.loads(line)).isdisjoint(VALIDATORS), line


def test_an_unchanged_site_syncs_again_without_rewriting_a_file(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """A second sync of an unchanged site: every validator sent, every answer a 304.

    The sitemap's snapshot is saved and reused on its 304 (ReuseUnchangedSitemap), each
    page is kept (RecordUnchanged), and no page or index file is rewritten
    (UnchangedRunIsStable). Re-derived at a0814ab: the snapshot is stamped with the last
    run that requested it, and although http.server sends every page a Last-Modified, no
    page file and no index.jsonl row carries a validator.
    """
    root, base = served(serve_site, tmp_path)
    write_site(root, base)
    out = tmp_path / "out"
    assert _commands.init(f"{base}guide/start.html", out) is ExitCode.ok
    assert synced(out) is ExitCode.ok
    pages = page_root(base)
    assert markdown_files(out) == sorted(f"{pages}{name}.md" for name in PAGES)
    snapshots = load(out / ".rovo" / "sitemaps.json")["snapshots"]
    assert isinstance(snapshots, list)
    (snapshot,) = snapshots
    assert snapshot["url"] == f"{base}maps/guide.xml"
    assert snapshot["etag"] is None
    assert snapshot["last_modified"] is not None
    assert snapshot["is_index"] is False
    assert [entry["loc"] for entry in snapshot["entries"]] == [
        f"{base}guide/orphan.html",
        f"{base}outside/page.html",
    ]
    assert snapshot["last_requested_run"] == 1
    assert_no_validators(out)
    before = file_states(out)
    logged = len(serve_site.paths(base))

    assert synced(out) is ExitCode.ok
    requests = serve_site.paths(base)[logged:]
    assert requests[: len(DISCOVERY_PATHS) + 1] == [*DISCOVERY_PATHS, LLMS_PATH]
    assert sorted(requests[len(DISCOVERY_PATHS) + 1 :]) == sorted(
        f"/guide/{name}.html" for name in PAGES
    )
    assert file_states(out) == before
    assert page_rows(out, base) == dict.fromkeys(PAGES, "unchanged")
    (snapshot,) = snapshots_of(out)
    assert snapshot["last_requested_run"] == len(["first sync", "second sync"])
    observed = load(out / ".rovo" / "frontier.json")["observed_urls"]
    assert isinstance(observed, list)
    outside = next(row for row in observed if row["url"] == f"{base}outside/page.html")
    assert outside["last_seen_run"] == len(["first sync", "second sync"])
    report = load(out / "crawl-report.json")
    assert report["exit_code"] == "ok"
    assert (report["fetched"], report["converted"]) == (len(PAGES), 0)
    assert report["skipped_unchanged"] == len(PAGES)
    assert change_kinds(report, base) == dict.fromkeys(PAGES, "unchanged")
    assert report["failed_urls"] == []
    assert host_fetched(report) == 0


def test_a_second_sync_reconverts_what_changed_and_what_max_age_forces(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """A changed page is reconverted, a raw-unchanged one kept; max_age forces a refetch.

    plain.html is answered by a script with no validator, so the second sync fetches it
    whole and finds the same raw document. A third sync past max_age fetches every page
    unconditionally and reconverts it to the same body, rewriting no page file.
    """
    plain = page_html("A plain topic")
    root, base = served(
        serve_site,
        tmp_path,
        always={"/guide/plain.html": Answer(200, {"Content-Type": "text/html"}, plain)},
    )
    write_site(root, base, plain=True)
    out = tmp_path / "out"
    assert _commands.init(f"{base}guide/start.html", out) is ExitCode.ok
    assert synced(out) is ExitCode.ok
    pages = page_root(base)
    names = (*PAGES, "plain")
    assert markdown_files(out) == sorted(f"{pages}{name}.md" for name in names)
    plain_file = out / f"{pages}plain.md"
    plain_mtime = plain_file.stat().st_mtime_ns

    start = root / "guide" / "start.html"
    start.write_text(
        page_html(
            "Getting started",
            ("linked.html", "plain.html"),
            f"            <p>{NEW_PARAGRAPH}</p>\n",
        ),
        encoding="utf-8",
    )
    moved = start.stat().st_mtime + A_MINUTE
    os.utime(start, (moved, moved))
    assert synced(out) is ExitCode.ok
    assert NEW_PARAGRAPH in (out / f"{pages}start.md").read_text(encoding="utf-8")
    assert plain_file.stat().st_mtime_ns == plain_mtime
    assert page_rows(out, base) == {
        "start": "done",
        "linked": "unchanged",
        "orphan": "unchanged",
        "plain": "unchanged",
    }
    report = load(out / "crawl-report.json")
    assert report["exit_code"] == "ok"
    assert (report["converted"], report["skipped_unchanged"]) == (1, len(PAGES))
    assert change_kinds(report, base) == {
        "start": "changed",
        "linked": "unchanged",
        "orphan": "unchanged",
        "plain": "unchanged",
    }
    assert host_fetched(report) == len(["start", "plain"])

    config = out / "rovo.toml"
    text = config.read_text(encoding="utf-8")
    assert "# max_age = 86400" in text
    config.write_text(text.replace("# max_age = 86400", "max_age = 60"), encoding="utf-8")
    mtimes = {name: (out / f"{pages}{name}.md").stat().st_mtime_ns for name in names}
    assert synced(out, FixedClock(LATER)) is ExitCode.ok
    assert page_rows(out, base) == dict.fromkeys(names, "done")
    report = load(out / "crawl-report.json")
    assert report["exit_code"] == "ok"
    assert (report["converted"], report["skipped_unchanged"]) == (0, len(names))
    assert host_fetched(report) == len(names)
    assert {name: (out / f"{pages}{name}.md").stat().st_mtime_ns for name in names} == mtimes


# --- The maintainer's answers (crawl.allium and mirror.allium at a0814ab) -----------------

HTML = {"Content-Type": "text/html"}
FIRST_STAMP = "Sat, 31 Oct 2026 12:00:00 GMT"
SECOND_STAMP = "Sun, 01 Nov 2026 12:00:00 GMT"
WIDENED_PREFIXES = 'path_prefixes = ["/guide/", "/outside/"]'


def set_crawl_key(out: Path, key: str, value: str) -> None:
    """rovo.toml's [crawl] `key = value`: replaced if present, else added under [crawl]."""
    config = out / "rovo.toml"
    text = config.read_text(encoding="utf-8")
    line = f"{key} = {value}"
    text, count = re.subn(rf"(?m)^{re.escape(key)} = .*$", line, text)
    if not count:
        text = text.replace("[crawl]\n", f"[crawl]\n{line}\n", 1)
    config.write_text(text, encoding="utf-8")


def widen_to_outside(out: Path) -> None:
    """rovo.toml's path_prefixes gain /outside/ (the processing signature does not move)."""
    config = out / "rovo.toml"
    text, count = re.subn(
        r"(?m)^path_prefixes = .*$", WIDENED_PREFIXES, config.read_text(encoding="utf-8")
    )
    assert count == 1
    config.write_text(text, encoding="utf-8")


def frontier_row(out: Path, identity: str) -> dict[str, object] | None:
    """frontier.json's row for `identity`, or None."""
    entries = load(out / ".rovo" / "frontier.json")["entries"]
    assert isinstance(entries, list)
    return next((row for row in entries if row["identity"] == identity), None)


def test_an_unchanged_page_refollows_its_stored_links_unless_the_setting_is_off(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """RefollowUnchangedLinks: a widened scope reaches a page only an unchanged page links.

    The seed links linked.html and ../outside/extra.html, which no sitemap or llms.txt
    names. The first sync mirrors the guide and records the outside link as external.
    With path_prefixes widened, a second sync answers the seed 304 and still queues
    extra.html from its stored links, via link, from the seed, and mirrors it; the same
    second sync with crawl.refollow_unchanged_links = false requests nothing outside.
    """
    fetched: dict[bool, list[str]] = {}
    for refollow in (True, False):
        place = tmp_path / str(refollow).lower()
        place.mkdir()
        root, base = served(serve_site, place)
        write(root, "robots.txt", "User-agent: *\n")
        write(
            root,
            "guide/start.html",
            page_html("Getting started", ("linked.html", "../outside/extra.html")),
        )
        write(root, "guide/linked.html", page_html("A linked topic"))
        write(root, "outside/extra.html", page_html("An extra topic"))
        seed = f"{base}guide/start.html"
        extra = f"{base}outside/extra.html"
        out = place / "out"
        assert _commands.init(seed, out) is ExitCode.ok
        assert synced(out) is ExitCode.ok
        links = (out / "links.jsonl").read_text(encoding="utf-8").splitlines()
        cited = {row["url"]: row["kind"] for row in map(json.loads, links)}
        assert cited[extra] == "external"
        assert frontier_row(out, extra) is None

        widen_to_outside(out)
        set_crawl_key(out, "refollow_unchanged_links", str(refollow).lower())
        logged = len(serve_site.paths(base))
        assert synced(out) is ExitCode.ok
        fetched[refollow] = [
            path for path in serve_site.paths(base)[logged:] if path.startswith("/outside/")
        ]
        start_row = frontier_row(out, seed)
        assert start_row is not None
        assert start_row["status"] == "unchanged"
        row = frontier_row(out, extra)
        if refollow:
            assert row is not None
            assert (row["discovered_via"], row["discovered_from"], row["depth"]) == (
                "link",
                seed,
                1,
            )
            assert row["status"] == "done"
            report = load(out / "crawl-report.json")
            changes = report["changes"]
            assert isinstance(changes, list)
            assert {"kind": "added", "url": extra} in [
                {"kind": change["kind"], "url": change["url"]} for change in changes
            ]
        else:
            assert row is None
    assert fetched == {True: ["/outside/extra.html"], False: []}


def test_a_moved_validator_over_an_unchanged_body_rewrites_no_file(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """UnchangedRunIsStable at a0814ab: validators live in .rovo/ state alone.

    stamped.html answers the same body twice, with a new ETag and Last-Modified on the
    second sync (and ignores the validators sent). It is in no sitemap, so no lastmod
    moves. The second sync keeps it unchanged, rewrites no page or index file, and
    the manifest holds the new validators.
    """
    stamped = page_html("A stamped topic")
    script = {
        "/guide/stamped.html": [
            Answer(200, {**HTML, "ETag": '"v1"', "Last-Modified": FIRST_STAMP}, stamped),
            Answer(200, {**HTML, "ETag": '"v2"', "Last-Modified": SECOND_STAMP}, stamped),
        ]
    }
    root = tmp_path / "site"
    root.mkdir()
    base = serve_site(root, script=script)
    write(root, "robots.txt", "User-agent: *\n")
    write(root, "guide/start.html", page_html("Getting started", ("stamped.html",)))
    out = tmp_path / "out"
    assert _commands.init(f"{base}guide/start.html", out) is ExitCode.ok
    assert synced(out) is ExitCode.ok
    pages = page_root(base)
    assert markdown_files(out) == [f"{pages}stamped.md", f"{pages}start.md"]
    assert_no_validators(out)
    before = file_states(out)

    assert synced(out) is ExitCode.ok
    assert file_states(out) == before
    assert page_rows(out, base) == {"start": "unchanged", "stamped": "unchanged"}
    manifest = load(out / ".rovo" / "manifest.json")
    rows = manifest["pages"]
    assert isinstance(rows, list)
    validators = {
        row["identity"]: (row["etag"], row["last_modified"])
        for row in rows
        if row["identity"] == f"{base}guide/stamped.html"
    }
    assert validators == {f"{base}guide/stamped.html": ('"v2"', SECOND_STAMP)}


def test_a_sitemap_gone_since_the_last_sync_loses_its_snapshot(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """SkipUnavailableSitemap at a0814ab: a declared sitemap answering 404 is dropped.

    The first sync saves maps/guide.xml's snapshot; the file is then deleted, so the
    second sync's conditional request is answered 404, silently, and sitemaps.json no
    longer holds the snapshot.
    """
    root, base = served(serve_site, tmp_path)
    write_site(root, base)
    out = tmp_path / "out"
    assert _commands.init(f"{base}guide/start.html", out) is ExitCode.ok
    assert synced(out) is ExitCode.ok
    assert [row["url"] for row in snapshots_of(out)] == [f"{base}maps/guide.xml"]
    (root / "maps" / "guide.xml").unlink()
    assert synced(out) is ExitCode.ok
    assert snapshots_of(out) == []
    report = load(out / "crawl-report.json")
    assert report["exit_code"] == "ok"
