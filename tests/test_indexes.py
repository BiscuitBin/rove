"""The generated indexes (T11): the guarantees and the hand-written cases of the ticket.

`DeterministicIndexes` and the index half of `RelativeLinksOnly` (mirror.allium 1420 and
1437) have no obligation id, so their tests are named after the guarantees. The other
tests pin `BuildIndexes`' guidance and the interim index text of the ticket's step 1,
which changes only through the maintainer's answer to the batched question. A small
threshold and cap go through the functions' parameters; no test patches CONFIG.
"""

import json
import posixpath
import re
from pathlib import Path

from rovo._mirror.finalise import request_pass
from rovo._mirror.indexes import (
    build_indexes,
    directory_indexes_for,
    index_entries,
    index_files,
    link_index_entries,
    llms_summary,
)
from rovo._mirror.links import resolve_mirror_links
from rovo._mirror.model import (
    CONFIG,
    Alias,
    Index,
    IndexBuildDue,
    IndexEntry,
    LinkKind,
    Mirror,
    MirrorPass,
    Operator,
    PassKind,
)
from test_mirror import (
    INDEX_FIELDS,
    INDEX_FILES,
    ISO_TIMESTAMP,
    NEW,
    OLD,
    OTHER,
    OTHER_DESCRIPTION,
    OTHER_TITLE,
    OUTSIDE,
    ROOT,
    SEED,
    SITE,
    finalised_pass,
    index_entry,
    indexed_mirror,
    link_pass,
    linked_mirror,
    new_mirror,
    removed,
    stored,
)

HOST = "docs.example"
API_HOST = "api.example"
MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)\)")
LOW_CONFIDENCE = " (low confidence)"
# The cap the code reads; a test that means "under the cap" passes it, never a literal.
CAP = CONFIG.llms_txt_cap


def build(mirror: Mirror) -> MirrorPass:
    """One index pass over the mirror through BuildIndexes; it completes."""
    pass_ = request_pass(Operator(), mirror, PassKind.index, None)
    assert build_indexes(IndexBuildDue(pass_=pass_)) is not None
    return pass_


def index_texts(out_dir: Path) -> dict[str, bytes]:
    """Every index file on disk: the root files and those under _indexes/."""
    names = [name for name in INDEX_FILES if (out_dir / name).exists()]
    names += [
        path.relative_to(out_dir).as_posix() for path in sorted(out_dir.glob("_indexes/**/*.md"))
    ]
    return {name: (out_dir / name).read_bytes() for name in names}


def content_lines(text: str) -> list[str]:
    """The lines that are not blank, in order."""
    return [line for line in text.splitlines() if line.strip()]


def links_of(text: str) -> list[str]:
    """Every Markdown link destination in the text, in order."""
    return MARKDOWN_LINK.findall(text)


def unit_index(mirror: Mirror, entries: list[IndexEntry], threshold: int) -> Index:
    """An Index over constructed entries, its directory indexes at `threshold`."""
    ordered = sorted(entries, key=lambda entry: entry.path)
    return Index(
        mirror=mirror,
        entries=ordered,
        link_entries=[],
        directory_indexes=directory_indexes_for(ordered, threshold),
        summary="The summary.",
    )


def nested_entries() -> list[IndexEntry]:
    """top.md at the host's top level; api (2 pages), api/v2 (1) and api/v2/ref (2)."""
    return [
        index_entry(f"{ROOT}top.md"),
        index_entry(f"{ROOT}api/a.md"),
        index_entry(f"{ROOT}api/b.md"),
        index_entry(f"{ROOT}api/v2/c.md"),
        index_entry(f"{ROOT}api/v2/ref/d.md"),
        index_entry(f"{ROOT}api/v2/ref/e.md"),
    ]


# --- The guarantees --------------------------------------------------------------------


def test_DeterministicIndexes(tmp_path: Path) -> None:
    """Rebuilding from unchanged input leaves every index file byte-identical.

    Entries are sorted by path and link entries by URL; files are LF-terminated UTF-8,
    and no index carries a wall-clock time.
    """
    mirror, _, _, pass_ = indexed_mirror(tmp_path)
    assert build_indexes(IndexBuildDue(pass_=pass_)) is not None
    first = index_texts(tmp_path)
    assert set(first) == set(INDEX_FILES)
    build(mirror)
    assert index_texts(tmp_path) == first
    for name, data in first.items():
        text = data.decode("utf-8")
        assert text.endswith("\n"), name
        assert "\r" not in text, name
        assert not ISO_TIMESTAMP.search(text), name
    index = mirror.index
    assert index is not None
    assert index_files(index, CAP) == {name: data.decode() for name, data in first.items()}
    paths = [json.loads(line)["path"] for line in first["index.jsonl"].decode().splitlines()]
    assert paths == sorted(mirror.page_paths)
    urls = [json.loads(line)["url"] for line in first["links.jsonl"].decode().splitlines()]
    assert urls == sorted(urls)
    assert len(urls) == len(set(urls))


def test_RelativeLinksOnly_generated_indexes(tmp_path: Path) -> None:
    """Every link an index holds is relative and reaches a file that exists.

    index.md and llms.txt link down into pages/ and _indexes/; a directory index links
    up and back down into pages/<host>/ and across to its nearest indexed descendants.
    """
    mirror = new_mirror(tmp_path)
    for name in ("top", "api/a", "api/b", "api/v2/ref/d", "api/v2/ref/e"):
        stored(mirror, requested=f"{SITE}/guide/{name}.html")
    finalised_pass(mirror)
    index = unit_index(mirror, index_entries(mirror.written_pages), 1)
    files = index_files(index, CAP)
    assert "_indexes/docs.example/api.md" in files
    assert "_indexes/docs.example/api/v2/ref.md" in files
    checked = 0
    for name, text in files.items():
        if not name.endswith((".md", ".txt")):
            continue
        for href in links_of(text):
            assert not href.startswith(("/", "http:", "https:")), (name, href)
            # Normalise before touching the disk: index_files writes nothing, so the
            # index file's own directory under _indexes/ need not exist yet.
            relative = posixpath.normpath(posixpath.join(posixpath.dirname(name), href))
            assert not relative.startswith(".."), (name, href)
            assert (tmp_path / relative).is_file() or relative in files, (name, href)
            checked += 1
    assert checked > 0


# --- Directory indexes on unit inputs ------------------------------------------------


def test_directory_index_threshold_boundary() -> None:
    """A directory holding exactly `threshold` pages gets no index; one more, it does."""
    threshold = 3
    at = [index_entry(f"{ROOT}api/p{n}.md") for n in range(threshold)]
    assert directory_indexes_for(at, threshold) == []
    over = [*at, index_entry(f"{ROOT}api/p{threshold}.md")]
    (directory_index,) = directory_indexes_for(over, threshold)
    assert directory_index.path == "_indexes/docs.example/api.md"
    assert len(directory_index.entries) == threshold + 1


def test_directory_index_counts_directly_not_recursively() -> None:
    """The api directory holds one page and api/v2 two: at threshold 1 only api/v2 is indexed."""
    entries = [
        index_entry(f"{ROOT}api/a.md"),
        index_entry(f"{ROOT}api/v2/b.md"),
        index_entry(f"{ROOT}api/v2/c.md"),
    ]
    (directory_index,) = directory_indexes_for(entries, 1)
    assert directory_index.directory == "pages/docs.example/api/v2"
    assert directory_index.path == "_indexes/docs.example/api/v2.md"
    assert directory_index.heading == "docs.example/api/v2"


def test_no_directory_index_for_a_host_top_level() -> None:
    """However many pages a host's top level holds, it gets no directory index."""
    entries = [index_entry(f"{ROOT}p{n}.md") for n in range(5)]
    assert directory_indexes_for(entries, 1) == []


def test_case_differing_directories_share_one_lower_case_index() -> None:
    """API/a.md and api/b.md form one group: _indexes/<host>/api.md, both entries."""
    entries = [index_entry(f"{ROOT}API/a.md"), index_entry(f"{ROOT}api/b.md")]
    (directory_index,) = directory_indexes_for(entries, 1)
    assert directory_index.directory == "pages/docs.example/api"
    assert directory_index.path == "_indexes/docs.example/api.md"
    assert [entry.path for entry in directory_index.entries] == [
        f"{ROOT}API/a.md",
        f"{ROOT}api/b.md",
    ]


def test_directory_indexes_are_sorted_by_path() -> None:
    """Several indexed directories come back in path order, across hosts too."""
    entries = [index_entry(f"pages/{HOST}/zeta/{name}.md") for name in ("a", "b")] + [
        index_entry(f"pages/{API_HOST}/ref/{name}.md") for name in ("a", "b")
    ]
    entries += [index_entry(f"pages/{HOST}/alpha/{name}.md") for name in ("a", "b")]
    paths = [directory_index.path for directory_index in directory_indexes_for(entries, 1)]
    assert paths == [
        "_indexes/api.example/ref.md",
        "_indexes/docs.example/alpha.md",
        "_indexes/docs.example/zeta.md",
    ]


def test_directory_index_links_nearest_indexed_descendants(tmp_path: Path) -> None:
    """With api and api/v2/ref indexed and api/v2 not, api.md links api/v2/ref.md, not v2.md.

    Its own pages are linked up and back down into pages/<host>/.
    """
    index = unit_index(new_mirror(tmp_path), nested_entries(), 1)
    assert [directory_index.path for directory_index in index.directory_indexes] == [
        "_indexes/docs.example/api.md",
        "_indexes/docs.example/api/v2/ref.md",
    ]
    files = index_files(index, CAP)
    api = files["_indexes/docs.example/api.md"]
    lines = content_lines(api)
    assert lines[0] == "# docs.example/api"
    assert "- [docs.example/api/v2/ref](api/v2/ref.md)" in lines
    assert "api/v2.md" not in links_of(api)
    assert "- [A](../../pages/docs.example/api/a.md)" in lines
    assert "- [B](../../pages/docs.example/api/b.md)" in lines
    ref = content_lines(files["_indexes/docs.example/api/v2/ref.md"])
    assert ref[0] == "# docs.example/api/v2/ref"
    assert "- [D](../../../../pages/docs.example/api/v2/ref/d.md)" in ref


# --- index.md -------------------------------------------------------------------------


def test_index_md_lists_the_host_then_its_pages(tmp_path: Path) -> None:
    """`# Index`, `## <host>`, then a line per page linking it under pages/<host>/."""
    mirror, start, other, pass_ = indexed_mirror(tmp_path)
    assert build_indexes(IndexBuildDue(pass_=pass_)) is not None
    lines = content_lines((tmp_path / "index.md").read_text(encoding="utf-8"))
    assert lines == [
        "# Index",
        f"## {HOST}",
        f"- [{OTHER_TITLE}]({other.path})",
        f"- [{start.title}]({start.path})",
    ]
    assert mirror.index is not None


def test_index_md_groups_top_level_directories_and_links_every_index(tmp_path: Path) -> None:
    """Top-level pages under the host, then `### api` with its indexes, then its pages."""
    index = unit_index(new_mirror(tmp_path), nested_entries(), 1)
    lines = content_lines(index_files(index, CAP)["index.md"])
    assert lines[:3] == ["# Index", f"## {HOST}", f"- [Top]({ROOT}top.md)"]
    assert lines[3] == "### api"
    rest = lines[4:]
    api_line = "- [docs.example/api](_indexes/docs.example/api.md)"
    ref_line = "- [docs.example/api/v2/ref](_indexes/docs.example/api/v2/ref.md)"
    assert rest.index(api_line) < rest.index(ref_line)  # nearest first
    page_lines = [f"- [{name.upper()}]({ROOT}{path}.md)" for name, path in _API_PAGES]
    for line in page_lines:
        assert line in rest, line
    assert rest.index(ref_line) < min(rest.index(line) for line in page_lines)


_API_PAGES = (("a", "api/a"), ("b", "api/b"), ("c", "api/v2/c"), ("d", "api/v2/ref/d"))


def test_index_md_marks_a_low_confidence_page(tmp_path: Path) -> None:
    """A low-confidence page's line ends with ` (low confidence)`; the others do not."""
    entries = [
        index_entry(f"{ROOT}a.md", low_confidence=True),
        index_entry(f"{ROOT}b.md"),
    ]
    files = index_files(unit_index(new_mirror(tmp_path), entries, 1), CAP)
    lines = content_lines(files["index.md"])
    assert f"- [A]({ROOT}a.md){LOW_CONFIDENCE}" in lines
    assert f"- [B]({ROOT}b.md)" in lines


def test_index_md_two_hosts_in_name_order(tmp_path: Path) -> None:
    """Two hosts: `## api.example` then `## docs.example`, each with its own pages."""
    mirror = new_mirror(tmp_path, allowed_hosts=frozenset({HOST, API_HOST}))
    stored(mirror)
    stored(mirror, requested=f"http://{API_HOST}/guide/x.html")
    finalised_pass(mirror)
    build(mirror)
    lines = content_lines((tmp_path / "index.md").read_text(encoding="utf-8"))
    hosts = [line for line in lines if line.startswith("## ")]
    assert hosts == [f"## {API_HOST}", f"## {HOST}"]
    api_at = lines.index(f"## {API_HOST}")
    docs_at = lines.index(f"## {HOST}")
    assert any(f"](pages/{API_HOST}/x.md)" in line for line in lines[api_at:docs_at])
    assert any(f"]({ROOT}start.md)" in line for line in lines[docs_at:])


# --- llms.txt -------------------------------------------------------------------------


def llms_entries() -> list[IndexEntry]:
    """top.md, api/a.md and api/b.md (indexed at threshold 1) and misc/c.md (not)."""
    return [
        index_entry(f"{ROOT}top.md"),
        index_entry(f"{ROOT}api/a.md"),
        index_entry(f"{ROOT}api/b.md"),
        index_entry(f"{ROOT}misc/c.md"),
    ]


def test_llms_txt_lists_every_page_up_to_the_cap(tmp_path: Path) -> None:
    """At the cap: `# <host>`, `> <summary>`, then every page line in path order."""
    entries = llms_entries()
    text = index_files(unit_index(new_mirror(tmp_path), entries, 1), len(entries))["llms.txt"]
    lines = content_lines(text)
    assert lines[0] == f"# {HOST}"
    assert lines[1] == "> The summary."
    assert lines[2:] == [
        f"- [A]({ROOT}api/a.md)",
        f"- [B]({ROOT}api/b.md)",
        f"- [C]({ROOT}misc/c.md)",
        f"- [Top]({ROOT}top.md)",
    ]
    assert text.endswith("\n")


def test_llms_txt_past_the_cap_lists_an_indexed_directory_once(tmp_path: Path) -> None:
    """Past the cap api is one line linking its index; top and misc/c stay listed."""
    entries = llms_entries()
    text = index_files(unit_index(new_mirror(tmp_path), entries, 1), len(entries) - 1)["llms.txt"]
    lines = content_lines(text)
    assert "- [docs.example/api](_indexes/docs.example/api.md)" in lines
    assert f"- [A]({ROOT}api/a.md)" not in lines
    assert f"- [B]({ROOT}api/b.md)" not in lines
    assert f"- [Top]({ROOT}top.md)" in lines
    assert f"- [C]({ROOT}misc/c.md)" in lines


def test_llms_txt_without_a_summary_has_no_blockquote(tmp_path: Path) -> None:
    """An empty summary writes no `>` line."""
    index = unit_index(new_mirror(tmp_path), llms_entries(), 1)
    index.summary = ""
    lines = content_lines(index_files(index, CAP)["llms.txt"])
    assert lines[0] == f"# {HOST}"
    assert not any(line.startswith(">") for line in lines)


# --- llms_summary ---------------------------------------------------------------------


def test_llms_summary_takes_the_start_url_page(tmp_path: Path) -> None:
    """The page whose identity is a start URL wins over the first page by path."""
    mirror = new_mirror(tmp_path)
    entries = [
        index_entry(f"{ROOT}a.md", identity=OTHER, description="First by path."),
        index_entry(f"{ROOT}z.md", identity=SEED, description="The start page."),
    ]
    assert llms_summary(mirror, entries) == "The start page."


def test_llms_summary_takes_a_start_url_alias(tmp_path: Path) -> None:
    """A start URL that is an alias of a page gives that page's description."""
    mirror = new_mirror(tmp_path)
    target = stored(mirror, requested=OTHER)
    mirror.aliases.append(Alias(mirror=mirror, url=SEED, target=target))
    entries = [
        index_entry(f"{ROOT}a.md", identity=f"{SITE}/guide/a.html", description="First."),
        index_entry(target.path, identity=OTHER, description="The aliased start page."),
    ]
    assert llms_summary(mirror, entries) == "The aliased start page."


def test_llms_summary_falls_back_to_the_first_page_by_path(tmp_path: Path) -> None:
    """No start URL matches: the first entry by path; no entry: the empty string."""
    mirror = new_mirror(tmp_path, start_urls=(f"{SITE}/guide/nowhere.html",))
    entries = [
        index_entry(f"{ROOT}z.md", description="Last."),
        index_entry(f"{ROOT}a.md", description="First by path."),
    ]
    assert llms_summary(mirror, entries) == "First by path."
    assert llms_summary(mirror, []) == ""


# --- links.jsonl and index.jsonl ------------------------------------------------------


def test_links_jsonl_has_an_entry_of_each_kind(tmp_path: Path) -> None:
    """An internal entry has its path; uncrawled, dangling and external have none."""
    mirror, start, other = linked_mirror(tmp_path)
    removed(mirror, OLD)
    start.converted_body += f"\nAn [archived page]({OLD}).\n"
    other.converted_body += f"\nThe [outside page]({OUTSIDE}).\n"
    assert resolve_mirror_links(link_pass(mirror))
    rows = {
        entry.url: (entry.kind, entry.path, list(entry.cited_by))
        for entry in link_index_entries(mirror.written_pages, mirror.aliases)
    }
    assert rows[OTHER] == (LinkKind.internal, other.path, [start.path])
    assert rows[NEW] == (LinkKind.uncrawled, None, [start.path])
    assert rows[OLD] == (LinkKind.dangling, None, [start.path])
    assert rows[OUTSIDE] == (LinkKind.external, None, sorted([start.path, other.path]))


def jsonl_line(row: dict[str, object]) -> str:
    """The interim encoding: sorted keys, compact separators, UTF-8 unescaped."""
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_index_jsonl_encoding(tmp_path: Path) -> None:
    """One compact, key-sorted JSON object per page; sets as sorted lists; null kept."""
    mirror, start, _, pass_ = indexed_mirror(tmp_path)
    assert build_indexes(IndexBuildDue(pass_=pass_)) is not None
    text = (tmp_path / "index.jsonl").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert len(lines) == len(mirror.written_pages)
    assert text == "".join(f"{line}\n" for line in lines)
    for line in lines:
        row = json.loads(line)
        assert isinstance(row, dict)
        assert set(row) == set(INDEX_FIELDS)
        assert line == jsonl_line(row)
        assert row["quality_flags"] == sorted(row["quality_flags"])
        assert "version" in row
        assert row["version"] is None
    by_path = {json.loads(line)["path"]: json.loads(line) for line in lines}
    assert by_path[start.path]["description"] == start.description
    assert by_path[ROOT + "other.md"]["description"] == OTHER_DESCRIPTION


def test_links_jsonl_encoding(tmp_path: Path) -> None:
    """links.jsonl is encoded as index.jsonl is; a non-internal entry's path is null."""
    _, _, _, pass_ = indexed_mirror(tmp_path)
    assert build_indexes(IndexBuildDue(pass_=pass_)) is not None
    text = (tmp_path / "links.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines()]
    assert text == "".join(f"{jsonl_line(row)}\n" for row in rows)
    assert all(set(row) == {"url", "kind", "path", "cited_by"} for row in rows)
    external = next(row for row in rows if row["url"] == OUTSIDE)
    assert external["kind"] == "external"
    assert external["path"] is None


# --- Writing --------------------------------------------------------------------------


def stamps(out_dir: Path) -> dict[str, tuple[int, int]]:
    """Each index file's inode and modification time: a replaced file changes both."""
    return {
        name: ((out_dir / name).stat().st_ino, (out_dir / name).stat().st_mtime_ns)
        for name in index_texts(out_dir)
    }


def test_a_file_is_written_only_when_its_text_differs(tmp_path: Path) -> None:
    """A second build over an unchanged mirror replaces no file; a new title moves one."""
    mirror, _, other, pass_ = indexed_mirror(tmp_path)
    assert build_indexes(IndexBuildDue(pass_=pass_)) is not None
    before = stamps(tmp_path)
    build(mirror)
    assert stamps(tmp_path) == before
    other.title = "A new title"
    build(mirror)
    after = stamps(tmp_path)
    assert after["index.md"] != before["index.md"]
    assert after["links.jsonl"] == before["links.jsonl"]


def test_a_stale_directory_index_is_deleted(tmp_path: Path) -> None:
    """A file under _indexes/ the build would not write goes, and its emptied directory."""
    mirror, _, _, pass_ = indexed_mirror(tmp_path)
    stale = tmp_path / "_indexes" / HOST / "old.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("# old\n", encoding="utf-8")
    assert build_indexes(IndexBuildDue(pass_=pass_)) is not None
    assert not stale.exists()
    assert not stale.parent.exists()
    assert mirror.index is not None
    assert mirror.index.directory_indexes == []
