"""End to end: rovo sync discovers pages from sitemaps and llms.txt (T13).

Each scenario's site is generated into tmp_path: served first, so its base URL (and
port) is known, then written, since `http.server` reads each file per request. A sitemap
`loc` is an absolute URL, and an index's child on another host carries the second
server's port: that host is `localhost`, another host name than `127.0.0.1`, and the
second server's empty request log proves the child was never fetched (the open
question's interim). The in-process scenarios run `rovo._commands.sync` over the real
HttpxFetcher on a SteppingTimer, so nothing sleeps; the command-line dry run replaces the
sleep the crawl's pacing calls. Not `test_sitemaps.py`, which the unit suite names.
"""

import dataclasses
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from conftest import DROP, Answer, SiteServer
from test_init_sync import load, markdown_files, page_root, split_page
from test_polite_sync import page
from typer.testing import CliRunner

from fakes import SteppingTimer
from rovo import _commands
from rovo._crawl import pace
from rovo._crawl.fetch import HttpxFetcher
from rovo._crawl.model import CONFIG
from rovo._exit import ExitCode
from rovo.cli import app

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
LASTMOD = "2026-10-01"
SERVER_ERROR = 500
DISCOVERY_PATHS = (
    "/maps/index.xml",
    "/maps/guide.xml",
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/llms.txt",
)
PAGE_PREFIXES = ("/guide/", "/outside/")


def urlset(entries: Sequence[tuple[str, str | None]]) -> str:
    """A sitemap urlset naming each (loc, lastmod)."""
    rows = "".join(
        f"    <url>\n        <loc>{loc}</loc>\n"
        + ("" if lastmod is None else f"        <lastmod>{lastmod}</lastmod>\n")
        + "    </url>\n"
        for loc, lastmod in entries
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="{NS}">\n{rows}</urlset>\n'


def sitemapindex(locs: Sequence[str]) -> str:
    """A sitemap index naming each child sitemap."""
    rows = "".join(f"    <sitemap>\n        <loc>{loc}</loc>\n    </sitemap>\n" for loc in locs)
    head = f'<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="{NS}">\n'
    return f"{head}{rows}</sitemapindex>\n"


def write(directory: Path, path: str, text: str) -> None:
    """Write one file of a generated site."""
    target = directory / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


@dataclasses.dataclass(frozen=True)
class Sites:
    """The served discovery site, its directory and the second server for localhost."""

    root: Path
    base: str
    other: str

    def url(self, path: str) -> str:
        """The absolute URL of `path` on the discovery site."""
        return f"{self.base}{path}"

    @property
    def child(self) -> str:
        """The index's child sitemap on another host: localhost on the second port."""
        return f"http://localhost:{urlsplit(self.other).port}/maps/child.xml"


def served(
    serve_site: SiteServer,
    directory: Path,
    *,
    script: Mapping[str, Sequence[Answer]] | None = None,
    always: Mapping[str, Answer] | None = None,
) -> Sites:
    """Serve an empty site and an empty second server; the site is written afterwards."""
    root = directory / "site"
    root.mkdir(parents=True)
    other = directory / "other"
    other.mkdir(parents=True)
    other_base = serve_site(other)
    base = serve_site(root, script=script, always=always)
    return Sites(root=root, base=base, other=other_base)


def write_base_site(
    sites: Sites,
    *,
    sitemaps: Sequence[str] = ("maps/index.xml",),
    guide: Sequence[str] | None = None,
    llms: bool = True,
) -> None:
    """The base site of tickets/T13-discovery.md step 6.

    robots.txt disallows /guide/private/ and declares `sitemaps`; maps/index.xml names
    maps/guide.xml and the localhost child; maps/guide.xml names the orphan (with a
    lastmod), the outside page and the hidden page, or the paths `guide`; llms.txt links
    the from-llms page. No page links any other.
    """
    root = sites.root
    declared = "".join(f"Sitemap: {sites.url(path)}\n" for path in sitemaps)
    write(root, "robots.txt", f"User-agent: *\nDisallow: /guide/private/\n{declared}")
    write(root, "maps/index.xml", sitemapindex([sites.url("maps/guide.xml"), sites.child]))
    entries: list[tuple[str, str | None]] = (
        [
            (sites.url("guide/orphan.html"), LASTMOD),
            (sites.url("outside/page.html"), None),
            (sites.url("guide/private/hidden.html"), None),
        ]
        if guide is None
        else [(sites.url(path), None) for path in guide]
    )
    write(root, "maps/guide.xml", urlset(entries))
    if llms:
        link = f"- [From llms]({sites.url('guide/from-llms.html')})\n"
        write(root, "llms.txt", f"# Example docs\n\n{link}")
    for path, title in (
        ("guide/start.html", "Getting started"),
        ("guide/orphan.html", "An orphan topic"),
        ("guide/from-llms.html", "A topic llms.txt names"),
        ("guide/private/hidden.html", "A hidden topic"),
        ("outside/page.html", "A page outside the guide"),
        *((path, f"Topic {path}") for path in guide or ()),
    ):
        page(root, path, title, f"{title} is described here in a sentence of plain prose.")


def synced(out: Path, *, dry_run: bool = False) -> ExitCode:
    """Rovo sync in process over the real HttpxFetcher on a SteppingTimer."""
    timer = SteppingTimer()
    with HttpxFetcher() as fetcher:
        return _commands.sync(out, fetcher=fetcher, clock=timer, dry_run=dry_run)


def initialised(sites: Sites, out: Path) -> Path:
    """Rovo init on the site's guide/start.html."""
    assert _commands.init(sites.url("guide/start.html"), out) is ExitCode.ok
    return out


def frontier_rows(out: Path) -> dict[str, dict[str, object]]:
    """frontier.json's entries by identity."""
    entries = load(out / ".rovo" / "frontier.json")["entries"]
    assert isinstance(entries, list)
    return {row["identity"]: row for row in entries}


def observed(out: Path) -> dict[str, dict[str, object]]:
    """frontier.json's observed_urls by URL, in the file's order."""
    rows = load(out / ".rovo" / "frontier.json")["observed_urls"]
    assert isinstance(rows, list)
    urls = [row["url"] for row in rows]
    assert urls == sorted(urls)
    return {row["url"]: row for row in rows}


def page_paths(paths: Sequence[str]) -> list[int]:
    """The positions of the page requests in a request log."""
    return [n for n, path in enumerate(paths) if path.startswith(PAGE_PREFIXES)]


def test_sync_reads_sitemaps_and_llms_txt_and_mirrors_what_they_name(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """Sitemaps (an index, its child on the host, the probes) and llms.txt discover pages.

    Every discovery request comes after robots.txt and before any page; the child on
    another host is never read; in-scope entries are admitted at their depth and
    priority, observations recorded whatever the scope, and the orphan's lastmod reaches
    its page file.
    """
    sites = served(serve_site, tmp_path)
    write_base_site(sites)
    out = initialised(sites, tmp_path / "out")
    assert synced(out) is ExitCode.ok
    paths = serve_site.paths(sites.base)
    assert paths[0] == "/robots.txt"
    for path in DISCOVERY_PATHS:
        assert paths.count(path) == 1, path
    first_page = min(page_paths(paths))
    assert all(paths.index(path) < first_page for path in DISCOVERY_PATHS)
    assert serve_site.paths(sites.other) == []
    assert "/outside/page.html" not in paths
    assert "/guide/private/hidden.html" not in paths
    root = page_root(sites.base)
    assert markdown_files(out) == [f"{root}from-llms.md", f"{root}orphan.md", f"{root}start.md"]

    rows = frontier_rows(out)
    orphan = rows[sites.url("guide/orphan.html")]
    assert (orphan["discovered_via"], orphan["depth"], orphan["priority"]) == (
        "sitemap",
        CONFIG.sitemap_depth,
        CONFIG.sitemap_priority,
    )
    assert (orphan["discovered_from"], orphan["sitemap_lastmod"]) == (
        sites.url("maps/guide.xml"),
        LASTMOD,
    )
    from_llms = rows[sites.url("guide/from-llms.html")]
    assert (from_llms["discovered_via"], from_llms["depth"], from_llms["priority"]) == (
        "llms_txt",
        CONFIG.llms_txt_depth,
        CONFIG.llms_txt_priority,
    )
    assert from_llms["discovered_from"] == sites.url("llms.txt")
    assert rows[sites.url("guide/private/hidden.html")]["status"] == "skipped_robots"
    assert sites.url("outside/page.html") not in rows
    assert observed(out) == {
        sites.url(path): {"url": sites.url(path), "sources": [source], "last_seen_run": 1}
        for path, source in (
            ("guide/from-llms.html", "llms_txt"),
            ("guide/orphan.html", "sitemap"),
            ("guide/private/hidden.html", "sitemap"),
            ("outside/page.html", "sitemap"),
        )
    }

    frontmatter, _ = split_page((out / f"{root}orphan.md").read_text(encoding="utf-8"))
    assert frontmatter["sitemap_lastmod"] == f'"{LASTMOD}"'
    report = load(out / "crawl-report.json")
    assert report["exit_code"] == "ok"
    assert report["discovery_problems"] == []
    assert report["discovered"] == len(["start", "orphan", "from-llms", "hidden"])


def test_declared_sitemaps_that_fail_are_reported_and_the_probes_stay_silent(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """A declared sitemap that fails is a discovery problem and exits 1; a probe never is.

    The declared 404 is silent; the declared 500, the dropped connection and the HTML
    page are reported, sorted by URL; the failing /sitemap.xml, /sitemap_index.xml and
    llms.txt say nothing; the orphan the working sitemap names is still mirrored.
    """
    sites = served(
        serve_site,
        tmp_path,
        always={
            "/maps/broken.xml": Answer(SERVER_ERROR),
            "/maps/drop.xml": DROP,
            "/sitemap.xml": Answer(SERVER_ERROR),
            "/sitemap_index.xml": DROP,
            "/llms.txt": DROP,
        },
    )
    write_base_site(
        sites,
        sitemaps=(
            "maps/missing.xml",
            "maps/broken.xml",
            "maps/page.html",
            "maps/drop.xml",
            "maps/guide.xml",
        ),
    )
    page(sites.root, "maps/page.html", "Not a sitemap", "This page is HTML, not a sitemap.")
    out = initialised(sites, tmp_path / "out")
    assert synced(out) is ExitCode.partial
    report = load(out / "crawl-report.json")
    assert report["exit_code"] == "partial"
    assert report["discovery_problems"] == [
        {"url": sites.url("maps/broken.xml"), "problem": "sitemap_unavailable"},
        {"url": sites.url("maps/drop.xml"), "problem": "sitemap_unreachable"},
        {"url": sites.url("maps/page.html"), "problem": "not_a_sitemap"},
    ]
    assert f"{page_root(sites.base)}orphan.md" in markdown_files(out)


def test_rovo_sync_dry_run_lists_what_it_would_fetch(
    serve_site: SiteServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rovo sync --dry-run discovers, lists the pending identities and fetches no page.

    The listing is next_pending's order: the seed, the two sitemap rows in discovery
    order, then the llms.txt row. The frontier, the run and the report are saved; no page
    file or index is written. An ordinary sync afterwards fetches the persisted rows.
    """
    sites = served(serve_site, tmp_path)
    write_base_site(sites)
    out = tmp_path / "out"
    runner = CliRunner()
    assert runner.invoke(app, ["init", sites.url("guide/start.html"), str(out)]).exit_code == 0
    slept: list[float] = []
    monkeypatch.setattr(pace.time, "sleep", slept.append)
    result = runner.invoke(app, ["sync", "--dry-run", str(out)])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        sites.url("guide/start.html"),
        sites.url("guide/orphan.html"),
        sites.url("guide/private/hidden.html"),
        sites.url("guide/from-llms.html"),
    ]
    paths = serve_site.paths(sites.base)
    assert paths[0] == "/robots.txt"
    assert set(paths) == {"/robots.txt", *DISCOVERY_PATHS}
    assert page_paths(paths) == []
    for name in ("pages", "index.md", "index.jsonl", "links.jsonl", "llms.txt", "_indexes"):
        assert not (out / name).exists(), name
    rows = frontier_rows(out)
    assert len(rows) == len(["start", "orphan", "hidden", "from-llms"])
    assert {row["status"] for row in rows.values()} == {"pending"}
    runs = load(out / ".rovo" / "runs.json")["runs"]
    assert isinstance(runs, list)
    assert [row["dry_run"] for row in runs] == [True]
    report = load(out / "crawl-report.json")
    options = report["options"]
    assert isinstance(options, dict)
    assert options["dry_run"] is True
    assert (report["fetched"], report["discovered"]) == (0, len(rows))
    assert (report["exit_code"], report["unresolved_urls"]) == ("ok", [])

    assert synced(out) is ExitCode.ok
    root = page_root(sites.base)
    assert markdown_files(out) == [f"{root}from-llms.md", f"{root}orphan.md", f"{root}start.md"]


def test_a_page_budget_stops_a_run_that_discovery_filled(
    serve_site: SiteServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """max_pages = 2: the seed's batch, then one row; the rest are skipped_limit, exit 1."""
    original = CONFIG
    replaced = dataclasses.replace(original, max_pages=2)
    for module in list(sys.modules.values()):
        if getattr(module, "CONFIG", None) is original:
            monkeypatch.setattr(module, "CONFIG", replaced)
    sites = served(serve_site, tmp_path)
    topics = tuple(f"guide/topic-{n}.html" for n in range(4))
    write_base_site(sites, sitemaps=("maps/guide.xml",), guide=topics, llms=False)
    out = initialised(sites, tmp_path / "out")
    assert synced(out) is ExitCode.partial
    report = load(out / "crawl-report.json")
    assert report["budget_stopped"] is True
    assert report["fetched"] == replaced.max_pages
    statuses = [row["status"] for row in frontier_rows(out).values()]
    assert statuses.count("skipped_limit") == len(topics) + 1 - replaced.max_pages


def test_observations_are_forgotten_after_the_retention_syncs(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """An observation unseen for more than observed_url_retention_syncs runs is dropped.

    Every sync is a dry run, so no page is written and none refetched. The orphan leaves
    the sitemap after the first run; it is kept for the retention runs and gone after one
    more, while the outside page, still listed, is seen by every run.
    """
    sites = served(serve_site, tmp_path)
    write_base_site(sites)
    out = initialised(sites, tmp_path / "out")
    orphan = sites.url("guide/orphan.html")
    outside = sites.url("outside/page.html")
    assert synced(out, dry_run=True) is ExitCode.ok
    assert observed(out)[orphan]["last_seen_run"] == 1
    write(
        sites.root,
        "maps/guide.xml",
        urlset([(outside, None), (sites.url("guide/private/hidden.html"), None)]),
    )
    retention = CONFIG.observed_url_retention_syncs
    for _ in range(retention):
        assert synced(out, dry_run=True) is ExitCode.ok
        assert observed(out)[orphan]["last_seen_run"] == 1
    assert synced(out, dry_run=True) is ExitCode.ok
    rows = observed(out)
    assert orphan not in rows
    assert rows[outside]["last_seen_run"] == retention + 2
