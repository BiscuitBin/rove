"""The generated indexes (mirror.allium 1283 to 1391): BuildIndexes and RebuildIndexes.

Every index is a pure function of the written pages, their links and the config, and no
index carries a wall-clock time, so rebuilding from unchanged input rewrites nothing. The
index pass reads no page body: every field comes from the manifest, and the page files
are only checked to be readable. Paths an index records are mirror-relative
(`pages/<host>/...`); links are relative to the index file. The exact text of each file
and the JSON Lines encoding are BuildIndexes' guidance (mirror.allium 1316 to 1390),
which docs/reference/mirror.md restates.
"""

import json
import os
import posixpath
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import fields
from pathlib import Path

from rovo._mirror.links import relative_path
from rovo._mirror.model import (
    CONFIG,
    Alias,
    DirectoryIndex,
    Index,
    IndexBuildDue,
    IndexEntry,
    IndexesWritten,
    IndexFilesWritten,
    Link,
    LinkIndexEntry,
    LinkKind,
    Mirror,
    MirrorPass,
    Operator,
    Page,
    PassKind,
    PassStatus,
)
from rovo._mirror.state import write_text

INDEX_MD = "index.md"
INDEX_JSONL = "index.jsonl"
LINKS_JSONL = "links.jsonl"
LLMS_TXT = "llms.txt"
INDEXES_DIRECTORY = "_indexes"
_PAGES = "pages"
_TITLE = "# Index"
_LOW_CONFIDENCE = " (low confidence)"
# pages/<host>/<name>: a page at a host's top level has three path segments.
_TOP_LEVEL_SEGMENTS = 3


def index_entries(pages: Iterable[Page]) -> list[IndexEntry]:
    """One IndexEntry per written page, in path order.

    word_count is the length of the measured word list outside code (mirror.allium
    IndexEntry.word_count); the link counts are the page's over Mirror.links.
    """
    chosen = sorted(pages, key=lambda page: page.path)
    outbound, inbound = _internal_counts(chosen)
    return [
        IndexEntry(
            path=page.path,
            identity=page.identity,
            source_url=page.source_url,
            title=page.title,
            description=page.description,
            keywords=tuple(page.keywords),
            headings=tuple(page.headings),
            quality_score=page.quality.score,
            low_confidence=page.low_confidence,
            quality_flags=frozenset(page.flags),
            content_digest=page.content_digest,
            version=page.version,
            locale=page.locale,
            word_count=len(page.quality.output.words),
            outbound_internal=outbound[page],
            inbound_internal=inbound[page],
        )
        for page in chosen
    ]


def link_index_entries(pages: Iterable[Page], aliases: Iterable[Alias]) -> list[LinkIndexEntry]:
    """One LinkIndexEntry per identity the pages cite, sorted by URL.

    The kind is the one link resolution gave; path is the holder's only for an internal
    link; cited_by is the citing pages' sorted, distinct paths.
    """
    del aliases  # Link resolution already followed every alias to its page (Link.target).
    cited: dict[str, set[str]] = {}
    first: dict[str, Link] = {}
    for link in _links_from(list(pages)):
        cited.setdefault(link.target_identity, set()).add(link.source.path)
        first.setdefault(link.target_identity, link)
    return [
        LinkIndexEntry(
            url=url,
            kind=first[url].kind,
            path=_holder_path(first[url]),
            cited_by=tuple(sorted(cited[url])),
        )
        for url in sorted(cited)
    ]


def directory_indexes_for(entries: Iterable[IndexEntry], threshold: int) -> list[DirectoryIndex]:
    """A DirectoryIndex per directory below a host's top level holding over `threshold`.

    Pages are counted directly, not recursively; directories that differ only in case
    form one group, named in lower case. Sorted by path.
    """
    groups: dict[str, list[IndexEntry]] = {}
    for entry in entries:
        if not _top_level(entry):
            groups.setdefault(posixpath.dirname(entry.path).lower(), []).append(entry)
    indexes = [
        DirectoryIndex(
            directory=directory,
            path=f"{INDEXES_DIRECTORY}/{_below_pages(directory)}.md",
            heading=_below_pages(directory),
            entries=tuple(sorted(members, key=lambda entry: entry.path)),
        )
        for directory, members in groups.items()
        if len(members) > threshold
    ]
    return sorted(indexes, key=lambda index: index.path)


def llms_summary(mirror: Mirror, entries: Iterable[IndexEntry]) -> str:
    """The first start URL's page's description, else the root URL's, else the first by path.

    A URL names the page whose identity, or an alias of which, is the URL's identity
    under the scope; start URLs are tried in the scope's order. An empty mirror gives "".
    """
    ordered = sorted(entries, key=lambda entry: entry.path)
    root_url = mirror.scope.root_url
    candidates = [*mirror.scope.start_urls, *([] if root_url is None else [root_url])]
    for url in candidates:
        entry = _entry_named(mirror, ordered, url)
        if entry is not None:
            return entry.description
    return ordered[0].description if ordered else ""


def _entry_named(mirror: Mirror, entries: list[IndexEntry], url: str) -> IndexEntry | None:
    """The entry whose identity, or an alias of which, is the URL's identity."""
    try:
        identity = mirror.scope.identity_of(url)
    except ValueError:  # normalise_url cannot parse it; it names no page.
        return None
    alias = mirror.alias(identity)
    path = None if alias is None else alias.target.path
    named = next((entry for entry in entries if entry.identity == identity), None)
    if named is not None:
        return named
    return next((entry for entry in entries if entry.path == path), None)


def index_files(index: Index, llms_txt_cap: int) -> dict[str, str]:
    """Every index file's text by its mirror-relative path."""
    files = {
        INDEX_MD: _index_md(index),
        INDEX_JSONL: _jsonl(_entry_row(entry) for entry in index.entries),
        LINKS_JSONL: _jsonl(_link_row(entry) for entry in index.link_entries),
        LLMS_TXT: _llms_txt(index, llms_txt_cap),
    }
    for directory_index in index.directory_indexes:
        files[directory_index.path] = _directory_index_md(directory_index, index.directory_indexes)
    return files


def rebuild_indexes(pass_: MirrorPass) -> IndexBuildDue | None:
    """Realises mirror.allium RebuildIndexes; None when its guard does not hold."""
    if pass_.status is not PassStatus.pending or pass_.kind is not PassKind.index:
        return None
    return IndexBuildDue(pass_=pass_)


def build_indexes(due: IndexBuildDue) -> IndexesWritten | None:
    """Realises mirror.allium BuildIndexes; None when its guard does not hold.

    The one Index is created or updated, the index files are written, each only when
    its text differs, and stale files under _indexes/ are deleted; then the pass
    completes.
    """
    pass_ = due.pass_
    if pass_.status is not PassStatus.pending:
        return None
    mirror = pass_.mirror
    entries = index_entries(mirror.written_pages)
    link_entries = link_index_entries(mirror.written_pages, mirror.aliases)
    directory_indexes = directory_indexes_for(entries, CONFIG.hierarchical_index_threshold)
    summary = llms_summary(mirror, entries)
    index = mirror.index
    if index is not None:
        index.entries = entries
        index.link_entries = link_entries
        index.directory_indexes = directory_indexes
        index.summary = summary
    else:
        index = Index(
            mirror=mirror,
            entries=entries,
            link_entries=link_entries,
            directory_indexes=directory_indexes,
            summary=summary,
        )
        mirror.index = index
    write_index_files(mirror, index_files(index, CONFIG.llms_txt_cap))
    pass_.status = PassStatus.completed
    return IndexesWritten(mirror=mirror, pass_=pass_, operator=pass_.operator)


def write_index_files(mirror: Mirror, files: dict[str, str]) -> IndexFilesWritten:
    """Delete stale files under _indexes/, then write each file whose bytes differ.

    A directory under _indexes/ left empty is removed, and _indexes/ itself when empty.
    """
    root = mirror.out_dir
    _delete_stale(root / INDEXES_DIRECTORY, {root / name for name in files})
    for name, text in sorted(files.items()):
        path = root / name
        if not _current(path, text):
            write_text(path, text)
    return IndexFilesWritten(mirror=mirror)


def unreadable_page_file(mirror: Mirror) -> str | None:
    """The path of the first written page, by path, whose file is missing or not UTF-8."""
    for page in sorted(mirror.written_pages, key=lambda page: page.path):
        try:
            (mirror.out_dir / page.path).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return page.path
    return None


def page_files_readable(mirror: Mirror) -> bool:
    """rovo.allium page_files_readable: every written page's file exists and is UTF-8."""
    return unreadable_page_file(mirror) is None


def index_pass(operator: Operator, mirror: Mirror) -> IndexesWritten | None:
    """RequestPass of an index pass (no run), RebuildIndexes, then BuildIndexes."""
    from rovo._mirror.finalise import (  # noqa: PLC0415  finalise imports this module.
        request_pass,
    )

    due = rebuild_indexes(request_pass(operator, mirror, PassKind.index, None))
    return None if due is None else build_indexes(due)


def _internal_counts(pages: list[Page]) -> tuple[Counter[Page], Counter[Page]]:
    """Each page's internal outbound and inbound link counts, in one walk of the links."""
    outbound: Counter[Page] = Counter()
    inbound: Counter[Page] = Counter()
    mirrors = {id(page.mirror): page.mirror for page in pages}
    for mirror in mirrors.values():
        for link in mirror.links:
            if link.kind is LinkKind.internal:
                outbound[link.source] += 1
                if link.target is not None:
                    inbound[link.target] += 1
    return outbound, inbound


def _links_from(pages: list[Page]) -> list[Link]:
    """The links whose source is one of the pages, in the mirror's order."""
    members = {id(page) for page in pages}
    mirrors = {id(page.mirror): page.mirror for page in pages}
    return [
        link for mirror in mirrors.values() for link in mirror.links if id(link.source) in members
    ]


def _holder_path(link: Link) -> str | None:
    """The written page holding an internal link's target, else None."""
    if link.kind is not LinkKind.internal or link.target is None:
        return None
    return link.target.path


def _segments(entry: IndexEntry) -> list[str]:
    return entry.path.split("/")


def _host(entry: IndexEntry) -> str:
    """The host segment: pages/<host>/..."""
    return _segments(entry)[1]


def _top_level(entry: IndexEntry) -> bool:
    """The page lies directly under pages/<host>/."""
    return len(_segments(entry)) <= _TOP_LEVEL_SEGMENTS


def _below_pages(directory: str) -> str:
    """pages/<host>/<dir> gives <host>/<dir>."""
    return directory.removeprefix(f"{_PAGES}/")


def _nearest_first(indexes: Iterable[DirectoryIndex]) -> list[DirectoryIndex]:
    """Shallower directories first, then by path."""
    return sorted(indexes, key=lambda index: (index.directory.count("/"), index.path))


def _within(directory: str, ancestor: str) -> bool:
    """The directory lies strictly below the ancestor."""
    return directory.startswith(f"{ancestor}/")


def _nearest_indexed_descendants(
    directory_index: DirectoryIndex, indexes: list[DirectoryIndex]
) -> list[DirectoryIndex]:
    """The indexes below this one with no other index between them and it."""
    below = [index for index in indexes if _within(index.directory, directory_index.directory)]
    return _nearest_first(
        index
        for index in below
        if not any(_within(index.directory, between.directory) for between in below)
    )


def _link_text(title: str) -> str:
    """A title as link text: backslash and brackets escaped, whitespace runs one space."""
    escaped = title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return re.sub(r"\s+", " ", escaped)


def _page_line(entry: IndexEntry, from_file: str) -> str:
    """`- [<title>](<relative path>)`, marked when the page is low confidence."""
    line = f"- [{_link_text(entry.title)}]({relative_path(from_file, entry.path)})"
    return line + _LOW_CONFIDENCE if entry.low_confidence else line


def _index_line(directory_index: DirectoryIndex, from_file: str) -> str:
    """`- [<heading>](<relative path>)`."""
    return f"- [{directory_index.heading}]({relative_path(from_file, directory_index.path)})"


def _document(blocks: Iterable[list[str]]) -> str:
    """The non-empty blocks of lines, a blank line between them, LF-terminated."""
    return "\n\n".join("\n".join(block) for block in blocks if block) + "\n"


def _index_md(index: Index) -> str:
    """index.md: per host its top-level pages, then per top-level directory its indexes.

    A top-level directory lists its directory indexes nearest first, then its pages.
    """
    blocks: list[list[str]] = [[_TITLE]]
    hosts: dict[str, list[IndexEntry]] = {}
    for entry in index.entries:
        hosts.setdefault(_host(entry), []).append(entry)
    for host in sorted(hosts):
        blocks.append([f"## {host}"])
        blocks.append([_page_line(entry, INDEX_MD) for entry in hosts[host] if _top_level(entry)])
        directories: dict[str, list[IndexEntry]] = {}
        for entry in hosts[host]:
            if not _top_level(entry):
                directories.setdefault(_segments(entry)[2].lower(), []).append(entry)
        for name in sorted(directories):
            top = f"{_PAGES}/{host}/{name}".lower()
            indexes = [
                directory_index
                for directory_index in index.directory_indexes
                if directory_index.directory == top or _within(directory_index.directory, top)
            ]
            blocks.append([f"### {name}"])
            blocks.append([_index_line(found, INDEX_MD) for found in _nearest_first(indexes)])
            blocks.append([_page_line(entry, INDEX_MD) for entry in directories[name]])
    return _document(blocks)


def _directory_index_md(directory_index: DirectoryIndex, indexes: list[DirectoryIndex]) -> str:
    """_indexes/<host>/<dir>.md: its heading, its nearest indexed descendants, its pages."""
    here = directory_index.path
    descendants = _nearest_indexed_descendants(directory_index, indexes)
    return _document(
        [
            [f"# {directory_index.heading}"],
            [_index_line(descendant, here) for descendant in descendants],
            [_page_line(entry, here) for entry in directory_index.entries],
        ]
    )


def _llms_txt(index: Index, cap: int) -> str:
    """llms.txt: a title, the summary, then every page in path order.

    Past the cap, a directory with its own index is one line linking it instead.
    """
    entries = index.entries
    title = f"# {_host(entries[0])}" if entries else _TITLE
    owner: dict[str, DirectoryIndex] = {}
    if len(entries) > cap:
        owner = {
            entry.path: directory_index
            for directory_index in index.directory_indexes
            for entry in directory_index.entries
        }
    lines: list[str] = []
    listed: set[str] = set()
    for entry in entries:
        directory_index = owner.get(entry.path)
        if directory_index is None:
            lines.append(_page_line(entry, LLMS_TXT))
        elif directory_index.path not in listed:
            listed.add(directory_index.path)
            lines.append(_index_line(directory_index, LLMS_TXT))
    summary = [f"> {index.summary}"] if index.summary else []
    return _document([[title], summary, lines])


def _jsonl(rows: Iterable[dict[str, object]]) -> str:
    """One compact JSON object per line, keys sorted, UTF-8 unescaped, LF after each."""
    return "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        for row in rows
    )


def _entry_row(entry: IndexEntry) -> dict[str, object]:
    """An IndexEntry as JSON: lists for tuples, the flag set as its sorted names."""
    row: dict[str, object] = {field.name: getattr(entry, field.name) for field in fields(entry)}
    row["keywords"] = list(entry.keywords)
    row["headings"] = list(entry.headings)
    row["quality_flags"] = sorted(flag.name for flag in entry.quality_flags)
    return row


def _link_row(entry: LinkIndexEntry) -> dict[str, object]:
    """A LinkIndexEntry as JSON: the kind by name, cited_by a list."""
    return {
        "url": entry.url,
        "kind": entry.kind.name,
        "path": entry.path,
        "cited_by": list(entry.cited_by),
    }


def _current(path: Path, text: str) -> bool:
    """The file holds exactly the text's UTF-8 bytes."""
    try:
        return path.read_bytes() == text.encode("utf-8")
    except OSError:
        return False


def _delete_stale(directory: Path, keep: set[Path]) -> None:
    """Delete every file under the directory not in `keep`, then the emptied directories."""
    if directory.is_symlink() or not directory.is_dir():
        return
    for current, directories, files in os.walk(directory, topdown=False):
        here = Path(current)
        for name in files:
            if here / name not in keep:
                (here / name).unlink()
        for name in directories:
            below = here / name
            if below.is_symlink():
                below.unlink()
            elif not any(below.iterdir()):
                below.rmdir()
    if not any(directory.iterdir()):
        directory.rmdir()
