"""End to end: an mslearn mirror syncs through its sitemap filter (T17 follow-up).

The maintainer's answers at spec 022eca4: mslearn's sitemap_include placeholders are
filled ({section} as *, {locale} as any of the scope's locale codes when none is pinned),
a page whose identity carries ?view= is stored at foo@<label>.md, and a page the profile's
selection does not match is extracted by the fallback extractor, trafilatura.

The committed HTML of tests/fixtures/sites/mslearn/ is copied into tmp_path, served, and
then given its robots.txt and sitemaps, written once the base URL (and port) is known, as
tests/e2e/test_discovery_sync.py does: a sitemap `loc` is an absolute URL. robots.txt
declares sitemapindex.xml, whose children are an en-us sitemap the filter admits and an
xx-xx one and an unpatterned one it does not. `rovo init` runs through CliRunner and
the sync runs `rovo._commands.sync` in process over the real HttpxFetcher on a
FixedClock, which never sleeps. Not `test_version_label.py` or `test_sitemaps.py`, which
the unit suite names.
"""

import json
import shutil
from pathlib import Path

from conftest import SITES, SiteServer
from test_init_sync import load, page_root, split_page
from typer.testing import CliRunner

from fakes import FixedClock
from rovo import _commands
from rovo._crawl.fetch import HttpxFetcher
from rovo._exit import ExitCode
from rovo.cli import app

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
LEARN_CHROME = ("Microsoft Learn header", "Learn table of contents", "Microsoft Learn footer")
ADMITTED = ("/robots.txt", "/sitemapindex.xml", "/maps/graph_en-us_0.xml")
NOT_ADMITTED = ("/maps/graph_xx-xx_0.xml", "/maps/other.xml", "/sitemap.xml", "/sitemap_index.xml")


def urlset(locs: list[str]) -> str:
    """A sitemap urlset naming each loc."""
    rows = "".join(f"    <url>\n        <loc>{loc}</loc>\n    </url>\n" for loc in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="{NS}">\n{rows}</urlset>\n'


def sitemapindex(locs: list[str]) -> str:
    """A sitemap index naming each child sitemap."""
    rows = "".join(f"    <sitemap>\n        <loc>{loc}</loc>\n    </sitemap>\n" for loc in locs)
    head = f'<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="{NS}">\n'
    return f"{head}{rows}</sitemapindex>\n"


def learn_site(serve_site: SiteServer, tmp_path: Path) -> tuple[str, Path]:
    """The mslearn site served from tmp_path, its robots.txt and sitemaps written."""
    root = tmp_path / "site"
    shutil.copytree(SITES / "mslearn", root)
    base = serve_site(root)
    files = {
        "robots.txt": f"User-agent: *\nSitemap: {base}sitemapindex.xml\n",
        "sitemapindex.xml": sitemapindex(
            [
                f"{base}maps/graph_en-us_0.xml",
                f"{base}maps/graph_xx-xx_0.xml",
                f"{base}maps/other.xml",
            ]
        ),
        "maps/graph_en-us_0.xml": urlset(
            [f"{base}guide/api.html?view=graph-rest-beta", f"{base}guide/loose.html"]
        ),
        "maps/graph_xx-xx_0.xml": urlset([f"{base}guide/hidden.html"]),
        "maps/other.xml": urlset([f"{base}guide/hidden.html"]),
    }
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return base, tmp_path / "out"


def initialised(base: str, out: Path) -> None:
    """`rovo init <base>guide/start.html <out> --profile mslearn` through CliRunner."""
    arguments = ["init", f"{base}guide/start.html", str(out), "--profile", "mslearn"]
    result = CliRunner().invoke(app, arguments, prog_name="rovo")
    assert result.exit_code == 0, result.output


def synced(out: Path) -> ExitCode:
    """Rovo sync in process over the real HttpxFetcher, on a FixedClock."""
    with HttpxFetcher() as fetcher:
        return _commands.sync(out, fetcher=fetcher, clock=FixedClock())


def page(out: Path, base: str, name: str) -> tuple[dict[str, object], str]:
    """A page file's frontmatter, each value decoded from its JSON, and its body."""
    raw, body = split_page((out / f"{page_root(base)}{name}").read_text(encoding="utf-8"))
    return {key: json.loads(value) for key, value in raw.items()}, body


def test_an_mslearn_mirror_syncs_through_its_sitemap_filter(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """The filter admits the index and the en-us child; ?view= gives api@beta.md.

    Only the admitted sitemaps are requested, so hidden.html, which only the others name,
    never is. The seed has no version parameter: no label, version_default recorded.
    """
    base, out = learn_site(serve_site, tmp_path)
    initialised(base, out)
    assert synced(out) is ExitCode.ok

    requested = serve_site.paths(base)
    for path in ADMITTED:
        assert path in requested, (path, requested)
    for path in (*NOT_ADMITTED, "/guide/hidden.html"):
        assert path not in requested, (path, requested)

    frontmatter, body = page(out, base, "api@beta.md")
    assert frontmatter["version"] == "beta"
    assert frontmatter["profile"] == "mslearn"
    assert frontmatter["method"] == "profile"
    assert "POST https://graph.example.invalid/beta/users" in body
    assert "var user = new User();" in body
    for chrome in LEARN_CHROME:
        assert chrome not in body, chrome
    assert not (out / f"{page_root(base)}api.md").exists()

    start, _ = page(out, base, "start.md")
    assert start["version"] == "v1.0"
    assert not any("@" in path.name for path in (out / page_root(base)).glob("start*"))
    assert load(out / "crawl-report.json")["exit_code"] == "ok"


def test_a_page_the_selection_misses_converts_by_the_fallback_extractor(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """loose.html has no Learn article content: trafilatura extracts it, method fallback.

    The page is flagged extractor_fallback, an incomplete flag, so it is low confidence;
    its main paragraphs reach the body and the profile's chrome does not.
    """
    base, out = learn_site(serve_site, tmp_path)
    initialised(base, out)
    assert synced(out) is ExitCode.ok

    frontmatter, body = page(out, base, "loose.md")
    assert frontmatter["method"] == "fallback"
    flags = frontmatter["quality_flags"]
    assert isinstance(flags, list)
    assert "extractor_fallback" in flags
    assert "whole_body_extracted" not in flags
    assert frontmatter["low_confidence"] is True
    assert "The fallback extractor still finds this paragraph" in body
    for chrome in LEARN_CHROME:
        assert chrome not in body, chrome
