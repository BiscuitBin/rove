"""The finalise pass (mirror.allium 538, 1094 to 1261): bodies, frontmatter, page files.

A page file is `---`, the frontmatter as YAML with its keys sorted and absent values
omitted, `---`, then the body. Strings and string lists are JSON-quoted, which YAML
reads as double-quoted scalars and flow sequences; the score keeps at most four places.
No wall-clock time reaches a page file: fetch times live in the manifest.
"""

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, fields
from pathlib import Path

from rovo._convert.fidelity import prose_lines
from rovo._convert.model import CONFIG as CONVERT
from rovo._convert.model import QualityFlag
from rovo._mirror.indexes import build_indexes
from rovo._mirror.intake import retire_page
from rovo._mirror.links import finish_link_pass, resolve_mirror_links, rewrite_destinations
from rovo._mirror.model import (
    CONFIG,
    FileEffectKind,
    Frontmatter,
    IndexBuildDue,
    IndexesWritten,
    LinksRewritten,
    Mirror,
    MirrorPass,
    Operator,
    Page,
    PageFinalised,
    PageRemoved,
    PassKind,
    PassStatus,
    RemovalReason,
    StoreOutcome,
)
from rovo._mirror.state import Clock, contained, write_text
from rovo._mirror.urls import digest

PAGES_DIRECTORY = "pages"
REMOVED_DIRECTORY = "_removed"
_SCORE_PLACES = 4
_MIN_KEYWORD_LETTERS = 3
_KEYWORD = re.compile(r"[^\W\d_]+")
# Markup that is not prose: a link's destination and a heading's id suffix.
_NOT_PROSE = re.compile(r"\]\([^)]*\)|\{#[^}]*\}|<https?://[^>\s]+>")
# Common English words that say nothing about a page; keywords_of skips them.
_STOP_WORDS = frozenset(
    {
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "also",
        "and",
        "any",
        "are",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "can",
        "could",
        "did",
        "does",
        "doing",
        "done",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "her",
        "here",
        "hers",
        "him",
        "his",
        "how",
        "into",
        "its",
        "itself",
        "just",
        "more",
        "most",
        "not",
        "now",
        "off",
        "once",
        "only",
        "other",
        "our",
        "ours",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "too",
        "under",
        "until",
        "use",
        "used",
        "using",
        "very",
        "was",
        "way",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
    }
)


@dataclass(frozen=True, kw_only=True)
class Finalisation:
    """What one finalise pass produced, in order."""

    pass_: MirrorPass
    finalised: tuple[PageFinalised, ...]
    # FinishLinkPass's LinksRewritten; the pass is pending then, so it always fires.
    rewritten: LinksRewritten | None
    # BuildIndexes' IndexesWritten; FinishLinkPass's IndexBuildDue always reaches it.
    indexes: IndexesWritten | None = None
    # RetireOutOfScopePages' PageRemoved events, in the order the pages were retired.
    removed: tuple[PageRemoved, ...] = ()


def request_pass(
    operator: Operator, mirror: Mirror, kind: PassKind, run_id: int | None
) -> MirrorPass:
    """Realises mirror.allium RequestPass."""
    return MirrorPass(
        mirror=mirror,
        operator=operator,
        kind=kind,
        run_id=run_id,
        failures=[],
        broken_links=[],
        status=PassStatus.pending,
    )


def retire_out_of_scope_pages(pass_: MirrorPass, clock: Clock) -> list[PageRemoved] | None:
    """Realises mirror.allium RetireOutOfScopePages: the pages retired; None when it fails.

    A written page whose source URL the scope no longer admits is retired out_of_scope,
    unless the run the pass follows stored it; a pass with no run retires every such page.
    """
    if pass_.status is not PassStatus.pending or pass_.kind is not PassKind.finalise:
        return None
    mirror = pass_.mirror
    retired = [
        retire_page(page, RemovalReason.out_of_scope, clock)
        for page in mirror.written_pages
        if not mirror.scope.within_bounds(page.source_url)
        and (pass_.run_id is None or page.last_stored_run != pass_.run_id)
    ]
    return [removed for removed in retired if removed is not None]


def apply_file_effects(mirror: Mirror) -> None:
    """Apply the file events recorded since the last pass, in order, then forget them.

    Each is idempotent: a missing source is a no-op and an existing destination is
    replaced. An archive takes pages/<host>/<p> to _removed/<host>/<p>; a deletion and an
    archived copy's deletion remove one file; an archived copy's move takes
    _removed/<host>/<p> to _removed/<host>/<source>. An archive or a deletion of a page moved
    this run takes the file from the path it was last published at (`source`). A move's
    old file is deleted by `delete_moved_files` once PublishPage has written the new one.
    """
    root = mirror.out_dir
    for effect in mirror.file_effects:
        source = contained(root, effect.source or effect.path)
        if effect.kind is FileEffectKind.archived and source.is_file():
            target = contained(root, archived_path(effect.path))
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
        elif effect.kind is FileEffectKind.deleted:
            source.unlink(missing_ok=True)
        elif effect.kind is FileEffectKind.archived_copy_deleted:
            contained(root, archived_path(effect.path)).unlink(missing_ok=True)
        elif effect.kind is FileEffectKind.archived_copy_moved:
            _move_archived_copy(root, effect.path, effect.source or effect.path)


def _move_archived_copy(root: Path, path: str, to_path: str) -> None:
    """Move the archived copy of `path` to that of `to_path`, when it exists."""
    copy = contained(root, archived_path(path))
    if copy.is_file():
        target = contained(root, archived_path(to_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        copy.replace(target)


def delete_moved_files(mirror: Mirror) -> None:
    """Delete each moved page's old file, unless a written page's file is that file now.

    Held paths compare ignoring case, as assign_path does; a held path that differs only
    in case is the same file on a case-insensitive file system, which keeps the old
    spelling when written over, so that file is renamed to the held spelling rather than
    deleted. Then every directory left empty under pages/ and _removed/ goes, the roots
    included.
    """
    held = {path.casefold(): path for path in mirror.page_paths}
    for effect in mirror.file_effects:
        held_path = held.get(effect.path.casefold())
        if effect.kind is not FileEffectKind.moved or held_path == effect.path:
            continue
        old = contained(mirror.out_dir, effect.path)
        if held_path is not None and _same_file(old, mirror.out_dir / held_path):
            old.rename(contained(mirror.out_dir, held_path))
        else:
            old.unlink(missing_ok=True)
    mirror.file_effects.clear()
    for namespace in (PAGES_DIRECTORY, REMOVED_DIRECTORY):
        _remove_empty_directories(mirror.out_dir / namespace)


def _same_file(first: Path, second: Path) -> bool:
    """Both paths exist and name one file."""
    return first.exists() and second.exists() and first.samefile(second)


def archived_path(path: str) -> str:
    """The archived copy of a page path: pages/<host>/<p> is kept at _removed/<host>/<p>."""
    return f"{REMOVED_DIRECTORY}/{path.removeprefix(PAGES_DIRECTORY + '/')}"


def finalise_page_body(pass_: MirrorPass, page: Page) -> None:
    """Realises mirror.allium FinalisePageBody.

    The body is the converted body with its destinations rewritten; the link flags, the
    low-confidence verdict and the keywords are recomputed from scratch.
    """
    del pass_  # The pass only orders the rule after PageLinksResolved.
    page.body = rewrite_destinations(page.converted_body, page)
    link_flags = {
        flag
        for flag, raised in (
            (QualityFlag.uncrawled_internal, page.has_uncrawled_link),
            (QualityFlag.unresolved_fragment, page.has_unresolved_fragment),
            (QualityFlag.dangling_inbound, page.has_dangling_link),
        )
        if raised
    }
    page.content_digest = digest(page.body)
    page.flags = page.quality.flags | link_flags
    page.low_confidence = page.quality.low_confidence or not link_flags.isdisjoint(
        CONVERT.incomplete_flags
    )
    page.keywords = keywords_of(page.body, CONFIG.keywords_per_page, CONFIG.keywords_min)


def publish_page(pass_: MirrorPass, page: Page, clock: Clock) -> PageFinalised:
    """Realises mirror.allium PublishPage: the page file is written only when it differs."""
    if page.was_moved:
        outcome = StoreOutcome.moved
    elif page.is_new_this_run:
        outcome = StoreOutcome.added
    elif page.previous_digest != page.content_digest:
        outcome = StoreOutcome.changed
    else:
        outcome = StoreOutcome.unchanged
    previous_path = page.moved_from
    page.frontmatter = frontmatter_of(page)
    page.last_outcome = outcome
    if outcome is not StoreOutcome.unchanged:
        page.last_changed = clock.now()
    page.previous_digest = page.content_digest
    page.moved_from = None
    page.revived_from = None
    if not page_file_current(page):
        write_text(page_file(page), page_file_text(page))
    return PageFinalised(
        pass_=pass_,
        page=page,
        outcome=outcome,
        previous_path=previous_path,
        seen_this_run=page.last_seen_run == pass_.run_id,
    )


def finalise(operator: Operator, mirror: Mirror, run_id: int, clock: Clock) -> Finalisation:
    """Run one finalise pass, RequestPass to IndexesWritten.

    RetireOutOfScopePages retires the pages the scope no longer admits; the file events
    recorded since the last pass are applied; ResolveMirrorLinks resolves every written
    page's links; then every body is finalised and published in path order, the moved
    pages' old files are deleted, FinishLinkPass reads the files back, and BuildIndexes
    writes the index files and completes the pass.
    """
    pass_ = request_pass(operator, mirror, PassKind.finalise, run_id)
    removed = tuple(retire_out_of_scope_pages(pass_, clock) or ())
    apply_file_effects(mirror)
    pages = sorted(mirror.written_pages, key=lambda page: page.path)
    resolve_mirror_links(pass_)
    for page in pages:
        finalise_page_body(pass_, page)
    finalised = tuple(publish_page(pass_, page, clock) for page in pages)
    delete_moved_files(mirror)
    rewritten = finish_link_pass(pass_)
    indexes = None if rewritten is None else build_indexes(IndexBuildDue(pass_=pass_))
    return Finalisation(
        pass_=pass_, finalised=finalised, rewritten=rewritten, indexes=indexes, removed=removed
    )


def frontmatter_of(page: Page) -> Frontmatter:
    """The page's frontmatter from its current fields; empty optional values are absent."""
    return Frontmatter(
        source_url=page.source_url,
        title=page.title,
        content_digest=page.content_digest,
        quality_score=page.quality.score,
        low_confidence=page.low_confidence,
        quality_flags=page.flags,
        tier=page.tier,
        method=page.method,
        profile=page.mirror.profile.name,
        keywords=page.keywords,
        description=page.description or None,
        canonical_url=page.canonical_url,
        breadcrumbs=page.breadcrumbs or None,
        sitemap_lastmod=page.sitemap_lastmod,
        version=page.version,
        locale=page.locale,
    )


def keywords_of(body: str, limit: int, minimum: int) -> tuple[str, ...]:
    """Up to `limit` distinctive terms of one body; a pure function of the body.

    Lower-cased words of at least three letters outside code, link destinations and
    heading ids, not stop words, ranked by count then first occurrence. Every distinct
    word is a candidate, so the list reaches `minimum` whenever the body has that many.
    """
    del minimum  # Ranking every distinct word already tops the list up when it can be.
    words = [
        word
        for line in prose_lines(body)
        for word in _KEYWORD.findall(_NOT_PROSE.sub(" ", line).lower())
        if len(word) >= _MIN_KEYWORD_LETTERS and word not in _STOP_WORDS
    ]
    counts = Counter(words)
    first = {word: index for index, word in reversed(list(enumerate(words)))}
    ranked = sorted(counts, key=lambda word: (-counts[word], first[word]))
    return tuple(ranked[:limit])


def page_file_text(page: Page) -> str:
    """The page file: `---`, the frontmatter as sorted YAML, `---`, the body."""
    frontmatter = frontmatter_of(page)
    lines = [
        f"{field.name}: {_yaml_value(value)}"
        for field in sorted(fields(Frontmatter), key=lambda field: field.name)
        if (value := getattr(frontmatter, field.name)) is not None
    ]
    return "---\n" + "\n".join(lines) + "\n---\n" + page.body


def page_file(page: Page) -> Path:
    """<out>/<page.path>; a ValueError when that resolves outside the mirror directory.

    assign_path never gives such a path; this guards the write and the read against one.
    """
    root = page.mirror.out_dir.resolve()
    path = root / page.path
    if not path.resolve().is_relative_to(root):
        msg = f"page path {page.path!r} is outside the mirror {root}"
        raise ValueError(msg)
    return path


def page_file_current(page: Page) -> bool:
    """The page file exists and its text equals page_file_text(page)."""
    path = page_file(page)
    return path.is_file() and path.read_text(encoding="utf-8") == page_file_text(page)


def _remove_empty_directories(directory: Path) -> None:
    """Remove every empty directory under `directory`, then `directory` itself when empty."""
    if directory.is_symlink() or not directory.is_dir():
        return
    for current, directories, _ in os.walk(directory, topdown=False):
        for name in directories:
            below = Path(current) / name
            if not below.is_symlink() and not any(below.iterdir()):
                below.rmdir()
    if not any(directory.iterdir()):
        directory.rmdir()


def _yaml_value(value: object) -> str:
    """One frontmatter value: booleans bare, the score as a decimal, the rest JSON-quoted."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        text = f"{value:.{_SCORE_PLACES}f}".rstrip("0")
        return f"{text}0" if text.endswith(".") else text
    if isinstance(value, frozenset):
        return json.dumps(sorted(getattr(item, "value", item) for item in value))
    if isinstance(value, tuple):
        return json.dumps(list(value), ensure_ascii=False)
    return json.dumps(getattr(value, "value", value), ensure_ascii=False)
