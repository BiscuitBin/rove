"""The finalise pass (mirror.allium 528, 1025 to 1223): bodies, frontmatter, page files.

A page file is `---`, the frontmatter as YAML with its keys sorted and absent values
omitted, `---`, then the body. Strings and string lists are JSON-quoted, which YAML
reads as double-quoted scalars and flow sequences; the score keeps at most four places.
No wall-clock time reaches a page file: fetch times live in the manifest.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass, fields
from pathlib import Path

from rovo._convert.fidelity import prose_lines
from rovo._convert.model import CONFIG as CONVERT
from rovo._convert.model import QualityFlag
from rovo._mirror.indexes import build_indexes
from rovo._mirror.links import finish_link_pass, resolve_mirror_links, rewrite_destinations
from rovo._mirror.model import (
    CONFIG,
    Frontmatter,
    IndexBuildDue,
    IndexesWritten,
    LinksRewritten,
    Mirror,
    MirrorPass,
    Operator,
    Page,
    PageFinalised,
    PassKind,
    PassStatus,
    StoreOutcome,
)
from rovo._mirror.state import Clock, write_text
from rovo._mirror.urls import digest
from rovo._unfinished import NotInThisSlice

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

    RetireOutOfScopePages retires nothing in this slice: a page it would retire stops the
    pass. ResolveMirrorLinks resolves every written page's links; then every body is
    finalised and published in path order, FinishLinkPass reads the files back, and
    BuildIndexes writes the index files and completes the pass.
    """
    pass_ = request_pass(operator, mirror, PassKind.finalise, run_id)
    pages = sorted(mirror.written_pages, key=lambda page: page.path)
    if any(
        not mirror.scope.within_bounds(page.source_url) and page.last_stored_run != run_id
        for page in pages
    ):
        raise NotInThisSlice(rule="RetireOutOfScopePages")
    resolve_mirror_links(pass_)
    for page in pages:
        finalise_page_body(pass_, page)
    finalised = tuple(publish_page(pass_, page, clock) for page in pages)
    rewritten = finish_link_pass(pass_)
    indexes = None if rewritten is None else build_indexes(IndexBuildDue(pass_=pass_))
    return Finalisation(pass_=pass_, finalised=finalised, rewritten=rewritten, indexes=indexes)


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
        etag=page.etag,
        last_modified=page.last_modified,
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
