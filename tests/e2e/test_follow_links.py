"""End to end: rovo sync follows links within the crawl scope and rewrites them (T10).

The installed `rovo` script beside this interpreter runs out of process against fixture
sites served on 127.0.0.1 by `serve_site`; nothing reaches the network. The file is not
`test_links.py`, which the unit suite's tests/test_links.py already names: two test
modules with one basename cannot be collected side by side.
"""

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from test_init_sync import load, markdown_files, page_root, rovo, split_page

from rovo._convert.model import QualityFlag

LINK_PAGES = ("start.md", "b.md", "deep/c.md", "deep/d.md")
MAX_DEPTH_LINE = "max_depth = 10\n"
TEMPLATE = "@TARGET_BASE@"


def synced(base: str, out: Path) -> None:
    """Rovo init on the site's guide/start.html, then rovo sync; both exit 0."""
    init = rovo("init", f"{base}guide/start.html", str(out))
    assert init.returncode == 0, init.stderr
    sync = rovo("sync", str(out))
    assert sync.returncode == 0, sync.stderr


def page(out: Path, base: str, path: str) -> tuple[dict[str, str], str]:
    """The frontmatter and body of the page file pages/<host segment>/<path>."""
    return split_page((out / f"{page_root(base)}{path}").read_text(encoding="utf-8"))


def flags(frontmatter: dict[str, str]) -> set[str]:
    """The page's quality_flags, as written."""
    loaded = json.loads(frontmatter["quality_flags"])
    assert isinstance(loaded, list)
    return {str(flag) for flag in loaded}


def frontier_rows(out: Path) -> dict[str, dict[str, object]]:
    """The saved frontier's rows by identity; each identity has exactly one row."""
    entries = load(out / ".rovo" / "frontier.json")["entries"]
    assert isinstance(entries, list)
    identities = [row["identity"] for row in entries]
    assert len(identities) == len(set(identities)), identities
    return {row["identity"]: row for row in entries}


def test_sync_follows_links_within_scope(
    serve_site: Callable[[str | Path], str], tmp_path: Path
) -> None:
    """The links site: four pages, links between them relative, every other link absolute."""
    base = serve_site("links")
    out = tmp_path / "out"
    synced(base, out)

    root = page_root(base)
    assert markdown_files(out) == sorted(f"{root}{path}" for path in LINK_PAGES)

    start_frontmatter, start = page(out, base, "start.md")
    for relative in ("b.md", "b.md#install", "b.md#missing", "#intro", "deep/c.md"):
        assert f"]({relative})" in start, relative
    for absolute in (
        f"{base}guide/private/secret.html",
        f"{base}outside/x.html",
        "https://example.invalid/",
        "mailto:docs@example.invalid",
    ):
        assert f"]({absolute})" in start, absolute
    assert "```markdown\n[b](b.html)\n```\n" in start
    start_flags = flags(start_frontmatter)
    assert QualityFlag.uncrawled_internal.value in start_flags
    assert QualityFlag.unresolved_fragment.value in start_flags
    assert QualityFlag.dangling_inbound.value not in start_flags

    _, deeper = page(out, base, "deep/c.md")
    assert "](d.md)" in deeper
    assert "](../start.md#intro)" in deeper

    rows = frontier_rows(out)
    depths = {identity: row["depth"] for identity, row in rows.items()}
    guide = f"{base}guide/"
    assert depths == {
        f"{guide}start.html": 0,
        f"{guide}b.html": 1,
        f"{guide}deep/c.html": 1,
        f"{guide}private/secret.html": 1,
        f"{guide}deep/d.html": 2,
    }
    assert rows[f"{guide}private/secret.html"]["status"] == "skipped_robots"
    assert all(
        row["status"] == "done"
        for identity, row in rows.items()
        if identity != f"{guide}private/secret.html"
    )

    report = load(out / "crawl-report.json")
    assert report["exit_code"] == "ok"
    assert report["converted"] == len(LINK_PAGES)
    changes = report["changes"]
    assert isinstance(changes, list)
    assert [change["kind"] for change in changes] == ["added"] * len(LINK_PAGES)
    assert report["broken_links"] == []


def test_the_depth_bound_stops_following(
    serve_site: Callable[[str | Path], str], tmp_path: Path
) -> None:
    """With scope.max_depth = 1, deep/d is neither fetched nor queued, and stays absolute."""
    base = serve_site("links")
    out = tmp_path / "out"
    init = rovo("init", f"{base}guide/start.html", str(out))
    assert init.returncode == 0, init.stderr
    toml = out / "rovo.toml"
    text = toml.read_text(encoding="utf-8")
    assert MAX_DEPTH_LINE in text
    toml.write_text(text.replace(MAX_DEPTH_LINE, "max_depth = 1\n"), encoding="utf-8")
    sync = rovo("sync", str(out))
    assert sync.returncode == 0, sync.stderr

    root = page_root(base)
    assert f"{root}deep/d.md" not in markdown_files(out)
    assert f"{root}deep/c.md" in markdown_files(out)
    assert f"{base}guide/deep/d.html" not in frontier_rows(out)
    frontmatter, deeper = page(out, base, "deep/c.md")
    assert f"]({base}guide/deep/d.html)" in deeper
    assert QualityFlag.uncrawled_internal.value in flags(frontmatter)


def test_a_link_across_hosts_climbs_to_pages(
    serve_site: Callable[[str | Path], str], tmp_path: Path
) -> None:
    """A page on one server links to a page on another as ../<other host segment>/<path>."""
    target = serve_site("cross-target")
    copy = tmp_path / "cross-host"
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "fixtures" / "sites" / "cross-host", copy
    )
    start_html = copy / "guide" / "start.html"
    templated = start_html.read_text(encoding="utf-8")
    assert TEMPLATE in templated
    start_html.write_text(templated.replace(TEMPLATE, target), encoding="utf-8")
    source = serve_site(copy)
    out = tmp_path / "out"
    synced(source, out)

    target_port = urlsplit(target).port
    assert target_port is not None
    assert (out / f"{page_root(target)}y.md").is_file()
    _, start = page(out, source, "start.md")
    assert f"](../127.0.0.1_{target_port}/y.md)" in start
    assert target not in start
