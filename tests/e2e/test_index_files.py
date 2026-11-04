"""End to end: rovo sync writes the indexes and rovo index rebuilds them (T11).

The installed `rovo` script beside this interpreter runs out of process against fixture
sites served on 127.0.0.1 by `serve_site`; nothing reaches the network. The file is not
`test_indexes.py`, which the unit suite's tests/test_indexes.py already names. The
large-directory site is generated into tmp_path with one page more than the threshold
the code reads, rather than committed as a fixture.
"""

import json
import os
import re
from collections.abc import Callable
from pathlib import Path

from test_init_sync import USAGE, load, page_root, rovo

from rovo._mirror.model import CONFIG

INDEX_FILES = ("index.md", "index.jsonl", "links.jsonl", "llms.txt")
UNTOUCHED = (".rovo/manifest.json", ".rovo/frontier.json", ".rovo/runs.json", "crawl-report.json")
PAGES = ("api/ref.md", "api/v2/x.md", "b.md", "start.md")
DESCRIPTION = "The example product's documentation, mirrored for offline reading."
ROOT_DESCRIPTION = "The root page of the example product's documentation."
ELSEWHERE = "https://example.invalid/"
MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)\)")
START_URLS_LINE = 'start_urls = ["{base}guide/a.html"]\n'
PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title} | Example docs</title>
</head>
<body>
<main>
<h1>{title}</h1>
<p>{prose}</p>
</main>
</body>
</html>
"""


def synced(base: str, out: Path) -> None:
    """Rovo init on the site's guide/start.html, then rovo sync; both exit 0."""
    init = rovo("init", f"{base}guide/start.html", str(out))
    assert init.returncode == 0, init.stderr
    sync = rovo("sync", str(out))
    assert sync.returncode == 0, sync.stderr


def host_segment(base: str) -> str:
    """127.0.0.1_<port>: the host segment of the fixture server."""
    return page_root(base).removeprefix("pages/").removesuffix("/")


def content_lines(text: str) -> list[str]:
    """The lines that are not blank, in order."""
    return [line for line in text.splitlines() if line.strip()]


def jsonl(path: Path) -> list[dict[str, object]]:
    """One JSON object per line."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert all(isinstance(row, dict) for row in rows)
    return rows


def index_bytes(out: Path) -> dict[str, bytes]:
    """The root index files and every file under _indexes/, by relative path."""
    names = [name for name in INDEX_FILES if (out / name).exists()]
    names += [path.relative_to(out).as_posix() for path in sorted((out / "_indexes").rglob("*"))]
    return {name: (out / name).read_bytes() for name in names if (out / name).is_file()}


def assert_links_reach_files(out: Path, name: str) -> None:
    """Every relative link in the index file reaches a file that exists."""
    text = (out / name).read_text(encoding="utf-8")
    hrefs = [href for href in MARKDOWN_LINK.findall(text) if not href.startswith("http")]
    assert hrefs, name
    for href in hrefs:
        target = os.path.normpath((out / name).parent / href)
        assert Path(target).is_file(), (name, href)


def test_sync_writes_the_indexes(serve_site: Callable[[str | Path], str], tmp_path: Path) -> None:
    """The indexes site: index.md, index.jsonl, links.jsonl and llms.txt at the root."""
    base = serve_site("indexes")
    out = tmp_path / "out"
    synced(base, out)
    host = host_segment(base)
    root = page_root(base)

    for name in INDEX_FILES:
        data = (out / name).read_bytes()
        assert data.endswith(b"\n"), name
        assert b"\r" not in data, name
        data.decode("utf-8")
    assert not (out / "_indexes").exists()  # no directory reaches the threshold

    lines = content_lines((out / "index.md").read_text(encoding="utf-8"))
    assert lines[0] == "# Index"
    assert [line for line in lines if line.startswith("## ")] == [f"## {host}"]
    assert [line for line in lines if line.startswith("### ")] == ["### api"]
    api_at = lines.index("### api")
    for path in ("start.md", "b.md"):
        assert any(f"]({root}{path})" in line for line in lines[1:api_at]), path
    for path in ("api/ref.md", "api/v2/x.md"):
        assert any(f"]({root}{path})" in line for line in lines[api_at:]), path

    entries = jsonl(out / "index.jsonl")
    assert [row["path"] for row in entries] == [f"{root}{path}" for path in PAGES]
    counts = {row["path"]: (row["outbound_internal"], row["inbound_internal"]) for row in entries}
    assert counts == {
        f"{root}api/ref.md": (1, 1),
        f"{root}api/v2/x.md": (0, 2),
        f"{root}b.md": (1, 1),
        f"{root}start.md": (3, 1),
    }

    links = jsonl(out / "links.jsonl")
    urls = [str(row["url"]) for row in links]
    assert urls == sorted(urls)
    assert len(urls) == len(set(urls))
    by_url = {row["url"]: row for row in links}
    assert by_url[ELSEWHERE] == {
        "url": ELSEWHERE,
        "kind": "external",
        "path": None,
        "cited_by": [f"{root}api/ref.md"],
    }
    assert by_url[f"{base}guide/b.html"] == {
        "url": f"{base}guide/b.html",
        "kind": "internal",
        "path": f"{root}b.md",
        "cited_by": [f"{root}start.md"],
    }

    llms = content_lines((out / "llms.txt").read_text(encoding="utf-8"))
    assert f"> {DESCRIPTION}" in llms
    page_lines = [line for line in llms if line.startswith("- [")]
    assert [MARKDOWN_LINK.findall(line) for line in page_lines] == [
        [f"{root}{path}"] for path in PAGES
    ]

    for name in ("index.md", "llms.txt"):
        assert_links_reach_files(out, name)
    report = load(out / "crawl-report.json")
    assert report["exit_code"] == "ok"
    assert report["broken_links"] == []


def test_index_rebuilds_the_same_files(
    serve_site: Callable[[str | Path], str], tmp_path: Path
) -> None:
    """Rovo index rewrites nothing unchanged, restores index.md and drops a stale file."""
    base = serve_site("indexes")
    out = tmp_path / "out"
    synced(base, out)
    indexes = index_bytes(out)
    stamps = {name: (out / name).stat().st_mtime_ns for name in INDEX_FILES}
    state = {name: (out / name).read_bytes() for name in UNTOUCHED}

    rebuilt = rovo("index", str(out))
    assert rebuilt.returncode == 0, rebuilt.stderr
    assert index_bytes(out) == indexes
    assert {name: (out / name).stat().st_mtime_ns for name in INDEX_FILES} == stamps

    (out / "index.md").unlink()
    stale = out / "_indexes" / host_segment(base) / "stale.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("# stale\n", encoding="utf-8")
    again = rovo("index", str(out))
    assert again.returncode == 0, again.stderr
    assert (out / "index.md").read_bytes() == indexes["index.md"]
    assert not stale.exists()
    assert not (out / "_indexes").exists() or not any((out / "_indexes").rglob("*"))
    assert {name: (out / name).read_bytes() for name in UNTOUCHED} == state


def test_index_refuses_without_readable_pages(
    serve_site: Callable[[str | Path], str], tmp_path: Path
) -> None:
    """A deleted page file, or no mirror at all, exits 2 and writes nothing."""
    base = serve_site("indexes")
    out = tmp_path / "out"
    synced(base, out)
    indexes = index_bytes(out)
    gone = f"{page_root(base)}b.md"
    (out / gone).unlink()
    refused = rovo("index", str(out))
    assert refused.returncode == USAGE, refused.stderr
    assert refused.stderr.startswith("rovo: index: ")
    assert gone in refused.stderr
    assert index_bytes(out) == indexes

    empty = tmp_path / "empty"
    empty.mkdir()
    nothing = rovo("index", str(empty))
    assert nothing.returncode == USAGE, nothing.stderr
    assert nothing.stderr.startswith("rovo: index: ")
    assert list(empty.iterdir()) == []


def large_directory_site(directory: Path, count: int) -> Path:
    """guide/start.html linking guide/big/p<NNN>.html for `count` pages, each with prose."""
    guide = directory / "guide"
    (guide / "big").mkdir(parents=True)
    links = " ".join(
        f'<a href="big/p{number:03d}.html">page {number}</a>' for number in range(count)
    )
    (guide / "start.html").write_text(
        PAGE_HTML.format(
            title="Getting started",
            prose=f"The example product keeps a large directory of pages: {links}.",
        ),
        encoding="utf-8",
    )
    for number in range(count):
        (guide / "big" / f"p{number:03d}.html").write_text(
            PAGE_HTML.format(
                title=f"Page {number}",
                prose=(
                    f"Page {number} of the large directory explains one setting of the "
                    "example product and the value it takes by default."
                ),
            ),
            encoding="utf-8",
        )
    return directory


def test_a_large_directory_gets_its_own_index(
    serve_site: Callable[[str | Path], str], tmp_path: Path
) -> None:
    """One page past hierarchical_index_threshold in big/ gives _indexes/<host>/big.md."""
    count = CONFIG.hierarchical_index_threshold + 1
    base = serve_site(large_directory_site(tmp_path / "site", count))
    out = tmp_path / "out"
    synced(base, out)
    host = host_segment(base)

    big = out / "_indexes" / host / "big.md"
    assert big.is_file()
    lines = content_lines(big.read_text(encoding="utf-8"))
    hrefs = [href for line in lines for href in MARKDOWN_LINK.findall(line)]
    assert hrefs == [f"../../pages/{host}/big/p{number:03d}.md" for number in range(count)]
    assert_links_reach_files(out, f"_indexes/{host}/big.md")
    index_md = (out / "index.md").read_text(encoding="utf-8")
    assert f"](_indexes/{host}/big.md)" in index_md
    assert_links_reach_files(out, "index.md")


ROOT_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="description" content="{description}">
<title>Overview | Example docs</title>
</head>
<body>
<main>
<h1>Overview</h1>
<p>The overview introduces the example product and points to <a href="a.html">its flags</a>.</p>
</main>
</body>
</html>
"""


def root_and_flags_site(directory: Path) -> Path:
    """guide/index.html (the root URL's page, described) and guide/a.html, titled with brackets."""
    guide = directory / "guide"
    guide.mkdir(parents=True)
    (guide / "index.html").write_text(
        ROOT_PAGE_HTML.format(description=ROOT_DESCRIPTION), encoding="utf-8"
    )
    (guide / "a.html").write_text(
        PAGE_HTML.format(
            title="Flags [beta] \\ options",
            prose=(
                "The flags page lists every option of the example product that is still in "
                "beta, with the value each one takes by default."
            ),
        ),
        encoding="utf-8",
    )
    return directory


def escaped(title: str) -> str:
    """BuildIndexes' link text: backslash and brackets escaped, whitespace flattened."""
    flat = " ".join(title.split())
    return flat.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def test_sync_without_start_urls_summarises_the_root_page_and_escapes_titles(
    serve_site: Callable[[str | Path], str], tmp_path: Path
) -> None:
    """With start_urls = [], llms.txt quotes the root URL's page; titles are escaped.

    a.md sorts before the root page's file, so the first page by path is not the root
    page: only the root URL fallback gives its description.
    """
    base = serve_site(root_and_flags_site(tmp_path / "site"))
    out = tmp_path / "out"
    init = rovo("init", f"{base}guide/a.html", str(out))
    assert init.returncode == 0, init.stderr
    toml = out / "rovo.toml"
    text = toml.read_text(encoding="utf-8")
    assert f'root_url = "{base}guide/"' in text
    assert START_URLS_LINE.format(base=base) in text
    toml.write_text(
        text.replace(START_URLS_LINE.format(base=base), "start_urls = []\n"), encoding="utf-8"
    )
    sync = rovo("sync", str(out))
    assert sync.returncode == 0, sync.stderr

    entries = jsonl(out / "index.jsonl")
    paths = [str(row["path"]) for row in entries]
    flags_path = f"{page_root(base)}a.md"
    assert len(paths) == len(("index", "a"))
    assert paths[0] == flags_path
    descriptions = {str(row["path"]): row["description"] for row in entries}
    assert descriptions[paths[1]] == ROOT_DESCRIPTION
    assert descriptions[flags_path] != ROOT_DESCRIPTION

    llms = content_lines((out / "llms.txt").read_text(encoding="utf-8"))
    assert llms[1] == f"> {ROOT_DESCRIPTION}"

    title = next(str(row["title"]) for row in entries if row["path"] == flags_path)
    assert "[" in title
    assert "\\" in title
    line = f"- [{escaped(title)}]({flags_path})"
    assert line in content_lines((out / "index.md").read_text(encoding="utf-8"))
    assert line in llms
