"""The mirror's values, entities and enumerations (mirror.allium).

Entities are mutable dataclasses compared by identity; values are frozen and compared by
value. A relationship the specification declares (`pages: Page with mirror = this`) is a
list on the owning entity.
"""

import enum
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rovo._convert.model import (
    ConvertedContent,
    ExtractionMethod,
    Profile,
    QualityFlag,
    QualityResult,
)
from rovo._mirror.urls import (
    first_path_segment,
    hostname_of,
    normalise_url,
    path_of,
    pattern_matches,
    scheme_of,
)


class Tier(enum.Enum):
    """The fetch tiers."""

    http = "http"
    browser = "browser"
    stealth = "stealth"


class RemovalReason(enum.Enum):
    """Why a page was removed."""

    absent = "absent"
    redirected_out = "redirected_out"
    out_of_scope = "out_of_scope"
    merged = "merged"


class CandidateOutcome(enum.Enum):
    """What one settled fetch delivers."""

    converted = "converted"
    unchanged = "unchanged"
    absent = "absent"
    redirected_out = "redirected_out"


class StoreOutcome(enum.Enum):
    """What finalisation found a page to be, relative to the last run."""

    added = "added"
    changed = "changed"
    unchanged = "unchanged"
    moved = "moved"


class LinkKind(enum.Enum):
    """internal: a written page holds the target; uncrawled: in bounds, no page.

    dangling: the target is a removed page; external: anything else.
    """

    internal = "internal"
    uncrawled = "uncrawled"
    dangling = "dangling"
    external = "external"


class BrokenLinkReason(enum.Enum):
    """Why a relative link in a page file is broken."""

    missing_file = "missing_file"
    outside_mirror = "outside_mirror"
    fragment_not_found = "fragment_not_found"


class VerificationReason(enum.Enum):
    """Why verify reports a finding (mirror.allium VerificationReason)."""

    missing_file = "missing_file"
    unmanaged_file = "unmanaged_file"
    invalid_page_file = "invalid_page_file"
    digest_mismatch = "digest_mismatch"
    quality_drift = "quality_drift"
    broken_link = "broken_link"
    index_stale = "index_stale"


class PassKind(enum.Enum):
    """The kinds of job over the mirror."""

    finalise = "finalise"
    index = "index"
    verify = "verify"


class PageStatus(enum.Enum):
    """Page.status."""

    written = "written"
    removed = "removed"


class CandidateStatus(enum.Enum):
    """PageCandidate.status."""

    pending = "pending"
    accepted = "accepted"
    duplicate = "duplicate"


class PassStatus(enum.Enum):
    """MirrorPass.status."""

    pending = "pending"
    completed = "completed"


class FileEffectKind(enum.Enum):
    """The file events of the lifecycle rules (mirror.allium RetirePage, MovePage, revival)."""

    archived = "archived"  # PageFileArchived: pages/<p> to _removed/<p>
    deleted = "deleted"  # PageFileDeleted: pages/<p> deleted (prune)
    moved = "moved"  # PageFileMoved: pages/<p> deleted once the new path is published
    archived_copy_deleted = "archived_copy_deleted"  # ArchivedCopyDeleted: _removed/<p>
    archived_copy_moved = "archived_copy_moved"  # ArchivedCopyMoved: _removed/<p> to <source>


@dataclass(frozen=True)
class Operator:
    """The person or script running a command; it has no state."""


@dataclass(frozen=True, kw_only=True)
class MirrorConfig:
    """mirror.allium's config block."""

    max_path_chars: int
    collision_hash_chars: int
    keywords_per_page: int
    keywords_min: int
    hierarchical_index_threshold: int
    llms_txt_cap: int
    prune: bool


# mirror.allium's config block (mirror.allium 495 to 503), the one copy in code.
CONFIG = MirrorConfig(
    max_path_chars=200,
    collision_hash_chars=6,
    keywords_per_page=8,
    keywords_min=5,
    hierarchical_index_threshold=200,
    llms_txt_cap=2000,
    prune=False,
)
_WEB_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True, kw_only=True)
class FileEffect:
    """One file event a lifecycle rule raised at intake; the finalise pass applies it.

    `path` is the page path the event names (for a move, the old one). `source` is, for
    a move or an archived copy's move, the new path; for an archive or a deletion, the
    file that holds the page now when that is not `path`: a page moved this run and not
    yet published is still at the path it was last published at.
    """

    kind: FileEffectKind
    path: str
    source: str | None = None


@dataclass(frozen=True, kw_only=True)
class CrawlScope:
    """The one URL scope of a mirror (mirror.allium 101)."""

    root_url: str | None
    start_urls: tuple[str, ...]
    allowed_hosts: frozenset[str]
    path_prefixes: tuple[str, ...]
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    max_depth: int
    locale: str | None
    meaningful_query_params: tuple[str, ...]
    locale_codes: frozenset[str]

    def identity_of(self, url: str) -> str:
        """The URL's identity under this scope's meaningful query parameters."""
        return normalise_url(url, self.meaningful_query_params)

    def host_allowed(self, url: str) -> bool:
        """The identity's host is an allowed host."""
        return hostname_of(self.identity_of(url)) in self.allowed_hosts

    def foreign_locale(self, url: str) -> bool:
        """The first path segment is a locale other than the pinned one."""
        segment = first_path_segment(self.identity_of(url))
        return self.locale is not None and segment in self.locale_codes and segment != self.locale

    @property
    def seeds(self) -> tuple[str, ...]:
        """The start URLs, else the root URL, else nothing."""
        if self.start_urls:
            return self.start_urls
        return (self.root_url,) if self.root_url is not None else ()

    def is_seed(self, url: str) -> bool:
        """The URL's identity is a seed's identity."""
        identity = self.identity_of(url)
        return any(self.identity_of(seed) == identity for seed in self.seeds)

    def within_bounds(self, url: str) -> bool:
        """In bounds without regard to depth; a malformed URL is out of bounds."""
        try:
            identity = self.identity_of(url)
        except ValueError:  # normalise_url cannot parse it (a port out of range).
            return False
        if self.is_seed(url):
            return True
        return (
            scheme_of(identity) in _WEB_SCHEMES
            and self.host_allowed(url)
            and any(path_of(identity).startswith(prefix) for prefix in self.path_prefixes)
            and not any(pattern_matches(identity, pattern) for pattern in self.exclude)
            and (not self.include or any(pattern_matches(identity, p) for p in self.include))
            and not self.foreign_locale(url)
        )

    def allows(self, url: str, depth: int) -> bool:
        """Within bounds and within the depth limit."""
        return self.within_bounds(url) and 0 <= depth <= self.max_depth

    def page_identity(self, source_url: str, canonical_url: str | None) -> str:
        """The declared canonical's identity when its host is allowed, else the source's."""
        if canonical_url is not None and self.host_allowed(canonical_url):
            return self.identity_of(canonical_url)
        return self.identity_of(source_url)


@dataclass(frozen=True, kw_only=True)
class Frontmatter:
    """The YAML block at the top of every page file; the validators live in .rovo/ alone."""

    source_url: str
    title: str
    content_digest: str
    quality_score: float
    low_confidence: bool
    quality_flags: frozenset[QualityFlag]
    tier: Tier
    method: ExtractionMethod
    profile: str
    keywords: tuple[str, ...]
    description: str | None = None
    canonical_url: str | None = None
    breadcrumbs: tuple[str, ...] | None = None
    sitemap_lastmod: str | None = None
    version: str | None = None
    locale: str | None = None


@dataclass(frozen=True, kw_only=True)
class BrokenLink:
    """A relative link in a page file that reaches no file or no anchor."""

    from_path: str
    href: str
    reason: BrokenLinkReason


@dataclass(frozen=True, kw_only=True)
class VerificationFailure:
    """One finding of verify: the gate, link or digest concerned is its detail."""

    path: str
    reason: VerificationReason
    detail: str


@dataclass(frozen=True, kw_only=True)
class IndexEntry:
    """One line of index.jsonl, and the source of index.md and llms.txt lines."""

    path: str
    identity: str
    source_url: str
    title: str
    description: str
    keywords: tuple[str, ...]
    headings: tuple[str, ...]
    quality_score: float
    low_confidence: bool
    quality_flags: frozenset[QualityFlag]
    content_digest: str
    version: str | None
    locale: str | None
    word_count: int
    outbound_internal: int
    inbound_internal: int


@dataclass(frozen=True, kw_only=True)
class LinkIndexEntry:
    """One line of links.jsonl: a URL some page links to."""

    url: str
    kind: LinkKind
    path: str | None
    cited_by: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class DirectoryIndex:
    """A generated per-directory index, _indexes/<host>/<dir>.md."""

    directory: str
    path: str
    heading: str
    entries: tuple[IndexEntry, ...]


@dataclass(kw_only=True, eq=False)
class Mirror:
    """An output directory and its manifest."""

    out_dir: Path
    scope: CrawlScope
    profile: Profile
    processing_signature: str
    declared_owned_hosts: frozenset[str] = frozenset()
    recorded_root_url: str | None = None
    pages: list["Page"] = field(default_factory=list)
    aliases: list["Alias"] = field(default_factory=list)
    links: list["Link"] = field(default_factory=list)
    index: "Index | None" = None
    # In memory only, never in the manifest: config.prune as the resolved configuration
    # sets it (rovo.toml's [mirror] prune), the file events recorded since the last
    # finalise pass applied them, and every PageRemoved RetirePage raised on this object.
    prune: bool = field(default_factory=lambda: CONFIG.prune)
    file_effects: list[FileEffect] = field(default_factory=list)
    removals: list["PageRemoved"] = field(default_factory=list)

    @property
    def written_pages(self) -> list["Page"]:
        """The pages whose status is written."""
        return [page for page in self.pages if page.status is PageStatus.written]

    @property
    def removed_pages(self) -> list["Page"]:
        """The pages whose status is removed."""
        return [page for page in self.pages if page.status is PageStatus.removed]

    @property
    def page_paths(self) -> list[str]:
        """The written pages' paths."""
        return [page.path for page in self.written_pages]

    @property
    def is_populated(self) -> bool:
        """The mirror holds a written page."""
        return bool(self.written_pages)

    @property
    def has_declared_owner(self) -> bool:
        """The operator has declared an owned host."""
        return bool(self.declared_owned_hosts)

    def page(self, identity: str) -> "Page | None":
        """Page{mirror: this, identity: identity}, whatever its status."""
        return next((page for page in self.pages if page.identity == identity), None)

    def alias(self, url: str) -> "Alias | None":
        """Alias{mirror: this, url: url}."""
        return next((alias for alias in self.aliases if alias.url == url), None)

    def record_file_effect(self, effect: FileEffect) -> None:
        """Record a file event for the next finalise pass, composed per page path.

        A page revived this run and retired again (RetirePage's guidance): the archive of
        the path its archived copy is at cancels that copy's pending deletion and is not
        recorded, since the archive still holds the last published bytes; the copy's move
        to the page's new path cancels the deletion too, and is recorded.
        """
        if effect.kind is FileEffectKind.archived and effect.source is not None:
            self.file_effects.append(effect)  # A moved page: no archived copy at its path.
            return
        if effect.kind in {FileEffectKind.archived, FileEffectKind.archived_copy_moved}:
            for pending in self.file_effects:
                if (
                    pending.kind is FileEffectKind.archived_copy_deleted
                    and pending.path == effect.path
                ):
                    self.file_effects.remove(pending)
                    if effect.kind is FileEffectKind.archived:
                        return
                    break
        self.file_effects.append(effect)

    def known_page(self, url: str) -> "Page | None":
        """The written page whose identity is the URL, else an alias's written target."""
        page = self.page(url)
        if page is not None and page.status is PageStatus.written:
            return page
        alias = self.alias(url)
        if alias is not None and alias.target.status is PageStatus.written:
            return alias.target
        return None


@dataclass(kw_only=True, eq=False)
class Page:
    """A page of the mirror: written, or removed at the source."""

    mirror: Mirror
    identity: str
    path: str
    canonical_url: str | None
    source_url: str
    title: str
    description: str
    method: ExtractionMethod
    tier: Tier
    quality: QualityResult
    flags: frozenset[QualityFlag]
    low_confidence: bool
    anchors: frozenset[str]
    headings: tuple[str, ...]
    keywords: tuple[str, ...]
    breadcrumbs: tuple[str, ...]
    locale: str | None
    version: str | None
    raw_digest: str
    content_digest: str
    previous_digest: str | None
    moved_from: str | None
    etag: str | None
    last_modified: str | None
    sitemap_lastmod: str | None
    processing_signature: str
    converted_body: str
    body: str
    frontmatter: Frontmatter | None
    last_outcome: StoreOutcome
    last_seen_run: int
    last_stored_run: int
    first_seen: datetime
    fetched_at: datetime
    last_seen: datetime
    last_changed: datetime
    status: PageStatus
    removed_at: datetime | None = None
    removal_reason: RemovalReason | None = None
    redirect_target: str | None = None
    revived_from: str | None = None

    @property
    def outbound_links(self) -> tuple["Link", ...]:
        """The links whose source is this page."""
        return tuple(link for link in self.mirror.links if link.source is self)

    @property
    def inbound_links(self) -> tuple["Link", ...]:
        """The links whose target is this page."""
        return tuple(link for link in self.mirror.links if link.target is self)

    @property
    def aliases(self) -> list["Alias"]:
        """The aliases whose target is this page."""
        return [alias for alias in self.mirror.aliases if alias.target is self]

    @property
    def internal_outbound(self) -> tuple["Link", ...]:
        """Outbound links of kind internal."""
        return tuple(link for link in self.outbound_links if link.kind is LinkKind.internal)

    @property
    def internal_inbound(self) -> tuple["Link", ...]:
        """Inbound links of kind internal."""
        return tuple(link for link in self.inbound_links if link.kind is LinkKind.internal)

    @property
    def outbound_internal(self) -> int:
        """The count of internal outbound links."""
        return len(self.internal_outbound)

    @property
    def inbound_internal(self) -> int:
        """The count of internal inbound links."""
        return len(self.internal_inbound)

    @property
    def has_uncrawled_link(self) -> bool:
        """An outbound link is uncrawled."""
        return any(link.kind is LinkKind.uncrawled for link in self.outbound_links)

    @property
    def has_dangling_link(self) -> bool:
        """An outbound link is dangling."""
        return any(link.kind is LinkKind.dangling for link in self.outbound_links)

    @property
    def has_unresolved_fragment(self) -> bool:
        """An outbound link's fragment is unresolved."""
        return any(not link.fragment_resolved for link in self.outbound_links)

    @property
    def is_new_this_run(self) -> bool:
        """previous_digest is null."""
        return self.previous_digest is None

    @property
    def was_moved(self) -> bool:
        """moved_from is set."""
        return self.moved_from is not None


@dataclass(kw_only=True, eq=False)
class Alias:
    """A URL that resolves to a page."""

    mirror: Mirror
    url: str
    target: Page


@dataclass(kw_only=True, eq=False)
class Link:
    """One outbound link of a page, as resolved at the last finalisation."""

    source: Page
    target_identity: str
    fragment: str | None
    kind: LinkKind
    target: Page | None
    fragment_resolved: bool


@dataclass(frozen=True, kw_only=True)
class CandidateDelivered:
    """The trigger the crawl raises through PageIntake (mirror.allium 1627)."""

    run_id: int
    mirror: Mirror
    requested_identity: str
    source_url: str
    redirect_hops: tuple[str, ...]
    depth: int
    outcome: CandidateOutcome
    tier: Tier
    raw_digest: str
    redirect_target: str | None = None
    content: ConvertedContent | None = None
    etag: str | None = None
    last_modified: str | None = None
    sitemap_lastmod: str | None = None


@dataclass(kw_only=True, eq=False)
class PageCandidate:
    """What one settled fetch delivers to the mirror."""

    mirror: Mirror
    run_id: int
    requested_identity: str
    source_url: str
    redirect_hops: tuple[str, ...]
    redirect_target: str | None
    depth: int
    outcome: CandidateOutcome
    content: ConvertedContent | None
    tier: Tier
    etag: str | None
    last_modified: str | None
    sitemap_lastmod: str | None
    raw_digest: str
    status: CandidateStatus


@dataclass(frozen=True, kw_only=True)
class CandidateDiscarded:
    """The trigger a discarded candidate raises (mirror.allium CandidateDiscarded)."""

    candidate: PageCandidate
    reason: str


@dataclass(frozen=True, kw_only=True)
class CandidateDuplicate:
    """The trigger RejectDuplicateCandidate raises (mirror.allium CandidateDuplicate)."""

    candidate: PageCandidate
    page: Page


@dataclass(frozen=True, kw_only=True)
class PageRemoved:
    """The trigger RetirePage raises (mirror.allium PageRemoved); candidate when one asked."""

    mirror: Mirror
    page: Page
    reason: RemovalReason
    candidate: PageCandidate | None = None


@dataclass(kw_only=True, eq=False)
class MirrorPass:
    """One job over the mirror."""

    mirror: Mirror
    operator: Operator
    kind: PassKind
    run_id: int | None
    failures: list[VerificationFailure]
    broken_links: list[BrokenLink]
    status: PassStatus


@dataclass(kw_only=True, eq=False)
class Index:
    """The generated indexes, regenerated from scratch by every pass that writes them."""

    mirror: Mirror
    entries: list[IndexEntry]
    link_entries: list[LinkIndexEntry]
    directory_indexes: list[DirectoryIndex]
    summary: str


@dataclass(frozen=True, kw_only=True)
class IndexBuildDue:
    """The trigger FinishLinkPass and RebuildIndexes raise (mirror.allium 1269, 1287)."""

    pass_: MirrorPass


@dataclass(frozen=True, kw_only=True)
class IndexFilesWritten:
    """The trigger BuildIndexes raises once the index files are on disk."""

    mirror: Mirror


@dataclass(frozen=True, kw_only=True)
class IndexesWritten:
    """The trigger BuildIndexes raises when it completes the pass (mirror.allium 1314)."""

    mirror: Mirror
    pass_: MirrorPass
    operator: Operator


@dataclass(frozen=True, kw_only=True)
class LinksFound:
    """The trigger RefreshPage raises (mirror.allium 896): the stored page's targets."""

    candidate: PageCandidate
    page: Page
    depth: int
    targets: tuple[str, ...]
    navigation_targets: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class LinksRewritten:
    """The trigger FinishLinkPass raises (mirror.allium 1268)."""

    mirror: Mirror
    pass_: MirrorPass
    operator: Operator
    broken: tuple[BrokenLink, ...]


@dataclass(frozen=True, kw_only=True)
class PageFinalised:
    """The trigger PublishPage raises (mirror.allium 1247)."""

    pass_: MirrorPass
    page: Page
    outcome: StoreOutcome
    previous_path: str | None
    seen_this_run: bool


@dataclass(frozen=True, kw_only=True)
class VerificationFinished:
    """The trigger VerifyPages raises (mirror.allium VerifyPages)."""

    mirror: Mirror
    pass_: MirrorPass
    operator: Operator
    failures: tuple[VerificationFailure, ...]
