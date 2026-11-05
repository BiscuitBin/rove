"""Page intake (mirror.allium 515 to 896): candidates become pages and aliases.

Several rules share `PageCandidate.created`; their guards partition the outcomes, so
`settle_candidate` fires the one whose guards hold. This slice implements StoreNewPage,
RefuseUnplaceableCandidate, RecordUnchanged, DiscardUnchangedWithoutPage,
RewriteKnownPage (when the requested page is its own target), and the shared
RefreshPage with the aliases it records; a candidate that would need another rule stops
with NotInThisSlice.
"""

from rovo._mirror.model import (
    Alias,
    CandidateDelivered,
    CandidateDiscarded,
    CandidateOutcome,
    CandidateStatus,
    LinksFound,
    Mirror,
    Page,
    PageCandidate,
    PageStatus,
    StoreOutcome,
)
from rovo._mirror.state import Clock
from rovo._mirror.urls import assign_path, digest, version_label
from rovo._unfinished import NotInThisSlice

_NO_FREE_PATH = "no free path"
_NO_PAGE_TO_CONFIRM = "no page to confirm"


def admit_candidate(delivered: CandidateDelivered) -> PageCandidate:
    """Realises mirror.allium AdmitCandidate."""
    return PageCandidate(
        mirror=delivered.mirror,
        run_id=delivered.run_id,
        requested_identity=delivered.requested_identity,
        source_url=delivered.source_url,
        redirect_hops=delivered.redirect_hops,
        redirect_target=delivered.redirect_target,
        depth=delivered.depth,
        outcome=delivered.outcome,
        content=delivered.content,
        tier=delivered.tier,
        etag=delivered.etag,
        last_modified=delivered.last_modified,
        sitemap_lastmod=delivered.sitemap_lastmod,
        raw_digest=delivered.raw_digest,
        status=CandidateStatus.pending,
    )


def store_new_page(candidate: PageCandidate, clock: Clock) -> Page | None:
    """Realises mirror.allium StoreNewPage; None when its guards do not hold.

    The page is created with provisional content fields, then RefreshPage (raised as
    PageContentAccepted) sets them and records the aliases.
    """
    content = candidate.content
    if candidate.status is not CandidateStatus.pending:
        return None
    if candidate.outcome is not CandidateOutcome.converted:
        return None
    mirror = candidate.mirror
    identity = _page_identity(candidate)
    if mirror.known_page(candidate.requested_identity) is not None:
        return None
    if mirror.page(identity) is not None or content is None:
        return None
    new_path = assign_path(mirror, identity)
    if new_path is None:
        return None
    now = clock.now()
    page = Page(
        mirror=mirror,
        identity=identity,
        path=new_path,
        canonical_url=content.canonical_url,
        source_url=candidate.source_url,
        title=content.title,
        description=content.description,
        method=content.method,
        tier=candidate.tier,
        quality=content.quality,
        flags=content.quality.flags,
        low_confidence=content.quality.low_confidence,
        anchors=content.anchors,
        headings=content.headings,
        keywords=(),
        breadcrumbs=content.breadcrumbs,
        locale=_locale(mirror, candidate),
        version=version_label(mirror.profile, identity),
        raw_digest=candidate.raw_digest,
        content_digest=digest(content.body),
        previous_digest=None,
        moved_from=None,
        etag=candidate.etag,
        last_modified=candidate.last_modified,
        sitemap_lastmod=candidate.sitemap_lastmod,
        processing_signature=mirror.processing_signature,
        converted_body=content.body,
        body=content.body,
        frontmatter=None,
        last_outcome=StoreOutcome.added,
        last_seen_run=candidate.run_id,
        last_stored_run=candidate.run_id,
        first_seen=now,
        fetched_at=now,
        last_seen=now,
        last_changed=now,
        status=PageStatus.written,
        redirect_target=None,
    )
    mirror.pages.append(page)
    refresh_page(candidate, page, clock)
    return page


def refuse_unplaceable_candidate(candidate: PageCandidate) -> CandidateDiscarded | None:
    """Realises mirror.allium RefuseUnplaceableCandidate; None when its guards do not hold.

    A pending converted candidate whose identity has no page, or only a removed one, and
    for which assign_path finds no free path is accepted and discarded; nothing else in
    the mirror changes.
    """
    if candidate.status is not CandidateStatus.pending:
        return None
    if candidate.outcome is not CandidateOutcome.converted:
        return None
    mirror = candidate.mirror
    identity = _page_identity(candidate)
    target = mirror.page(identity)
    if target is not None and target.status is not PageStatus.removed:
        return None
    if assign_path(mirror, identity) is not None:
        return None
    candidate.status = CandidateStatus.accepted
    return CandidateDiscarded(candidate=candidate, reason=_NO_FREE_PATH)


def refresh_page(candidate: PageCandidate, page: Page, clock: Clock) -> LinksFound | None:
    """Realises mirror.allium RefreshPage; None when its guards do not hold.

    No file is written. Every URL on the way to the page that is not its identity (each
    redirect hop, the source URL, the requested identity) is raised as AliasRecorded.
    The page's links are dropped and re-resolved at finalisation; the LinksFound it
    raises carries the content's targets for the crawl.
    """
    content = candidate.content
    if candidate.status is not CandidateStatus.pending or content is None:
        return None
    mirror = candidate.mirror
    now = clock.now()
    page.canonical_url = content.canonical_url
    page.source_url = candidate.source_url
    page.title = content.title
    page.description = content.description
    page.method = content.method
    page.tier = candidate.tier
    page.quality = content.quality
    page.flags = content.quality.flags
    page.low_confidence = content.quality.low_confidence
    page.anchors = content.anchors
    page.headings = content.headings
    page.breadcrumbs = content.breadcrumbs
    page.locale = _locale(mirror, candidate)
    page.version = version_label(mirror.profile, page.identity)
    page.raw_digest = candidate.raw_digest
    page.etag = candidate.etag
    page.last_modified = candidate.last_modified
    page.sitemap_lastmod = candidate.sitemap_lastmod
    page.processing_signature = mirror.processing_signature
    page.converted_body = content.body
    page.last_seen_run = candidate.run_id
    page.last_stored_run = candidate.run_id
    page.fetched_at = now
    page.last_seen = now
    mirror.links = [link for link in mirror.links if link.source is not page]
    passed = [
        *(mirror.scope.identity_of(hop) for hop in candidate.redirect_hops),
        mirror.scope.identity_of(candidate.source_url),
        candidate.requested_identity,
    ]
    for url in passed:
        if url != page.identity:
            _alias_recorded(mirror, url, page)
    candidate.status = CandidateStatus.accepted
    return links_found(candidate, page)


def links_found(candidate: PageCandidate, page: Page) -> LinksFound:
    """The LinksFound RefreshPage raises for the stored page (mirror.allium 858)."""
    content = candidate.content
    return LinksFound(
        candidate=candidate,
        page=page,
        depth=candidate.depth,
        targets=() if content is None else content.link_targets,
        navigation_targets=() if content is None else content.navigation_targets,
    )


def record_alias(mirror: Mirror, url: str, page: Page) -> Alias | None:
    """Realises mirror.allium RecordAlias; None when its guard does not hold."""
    own = mirror.page(url)
    if own is not None and own.status is not PageStatus.removed:
        return None
    alias = mirror.alias(url)
    if alias is not None:
        alias.target = page
        return alias
    alias = Alias(mirror=mirror, url=url, target=page)
    mirror.aliases.append(alias)
    return alias


def drop_alias_of_own_identity(mirror: Mirror, url: str, page: Page) -> bool:
    """Realises mirror.allium DropAliasOfOwnIdentity; False when its guard does not hold."""
    del page  # The trigger's page plays no part: a written page's identity is never an alias.
    own = mirror.page(url)
    if own is None or own.status is not PageStatus.written:
        return False
    stale = mirror.alias(url)
    if stale is not None:
        mirror.aliases.remove(stale)
    return True


def record_unchanged(candidate: PageCandidate, clock: Clock) -> Page | None:
    """Realises mirror.allium RecordUnchanged: PageStored's page, else None.

    The known page is seen again: a validator or sitemap lastmod the candidate carries
    replaces the stored one, a null one keeps it; the body and the measurement stay.
    """
    if candidate.status is not CandidateStatus.pending:
        return None
    if candidate.outcome is not CandidateOutcome.unchanged:
        return None
    previous = candidate.mirror.known_page(candidate.requested_identity)
    if previous is None:
        return None
    previous.last_seen = clock.now()
    previous.last_seen_run = candidate.run_id
    if candidate.etag is not None:
        previous.etag = candidate.etag
    if candidate.last_modified is not None:
        previous.last_modified = candidate.last_modified
    if candidate.sitemap_lastmod is not None:
        previous.sitemap_lastmod = candidate.sitemap_lastmod
    candidate.status = CandidateStatus.accepted
    return previous


def discard_unchanged_without_page(candidate: PageCandidate) -> CandidateDiscarded | None:
    """Realises mirror.allium DiscardUnchangedWithoutPage; None when its guards do not hold."""
    if candidate.status is not CandidateStatus.pending:
        return None
    if candidate.outcome is not CandidateOutcome.unchanged:
        return None
    if candidate.mirror.known_page(candidate.requested_identity) is not None:
        return None
    candidate.status = CandidateStatus.accepted
    return CandidateDiscarded(candidate=candidate, reason=_NO_PAGE_TO_CONFIRM)


def rewrite_known_page(candidate: PageCandidate, clock: Clock) -> Page | None:
    """Realises mirror.allium RewriteKnownPage: the refreshed target, else None.

    The target keeps its content digest as its previous digest, then RefreshPage
    (raised as PageContentAccepted) refreshes it. The merge branch, a known page other
    than the target (PageRetired with reason merged), is a later slice's.
    """
    if candidate.status is not CandidateStatus.pending:
        return None
    if candidate.outcome is not CandidateOutcome.converted:
        return None
    mirror = candidate.mirror
    target = mirror.page(_page_identity(candidate))
    if target is None or target.status is not PageStatus.written:
        return None
    if target.last_stored_run == candidate.run_id:
        return None
    previous = mirror.known_page(candidate.requested_identity)
    if previous is not None and previous is not target:
        raise NotInThisSlice(rule="RewriteKnownPage")
    target.previous_digest = target.content_digest
    refresh_page(candidate, target, clock)
    return target


def settle_candidate(candidate: PageCandidate, clock: Clock) -> Page | CandidateDiscarded | None:
    """Settle one candidate: the rule whose guards hold fires; None when it is not pending.

    In order: StoreNewPage, RefuseUnplaceableCandidate, RecordUnchanged,
    DiscardUnchangedWithoutPage, RewriteKnownPage; a page is PageStored's, a discard
    CandidateDiscarded's. A pending candidate none takes needs a rule a later slice
    implements (RejectDuplicateCandidate, MovePage, ReviveRemovedPage, or an absent or
    redirected-out outcome).
    """
    if candidate.status is not CandidateStatus.pending:
        return None
    settled = (
        store_new_page(candidate, clock)
        or refuse_unplaceable_candidate(candidate)
        or record_unchanged(candidate, clock)
        or discard_unchanged_without_page(candidate)
        or rewrite_known_page(candidate, clock)
    )
    if settled is None:
        raise NotInThisSlice(rule="PageCandidate.created")
    return settled


def take_candidate(candidate: PageCandidate, clock: Clock) -> Page | None:
    """Settle one candidate as `settle_candidate` does: PageStored's page, else None."""
    settled = settle_candidate(candidate, clock)
    return settled if isinstance(settled, Page) else None


def _page_identity(candidate: PageCandidate) -> str:
    canonical = candidate.content.canonical_url if candidate.content is not None else None
    return candidate.mirror.scope.page_identity(candidate.source_url, canonical)


def _alias_recorded(mirror: Mirror, url: str, page: Page) -> None:
    """AliasRecorded: RecordAlias and DropAliasOfOwnIdentity partition it by guard."""
    if record_alias(mirror, url, page) is None:
        drop_alias_of_own_identity(mirror, url, page)


def _locale(mirror: Mirror, candidate: PageCandidate) -> str | None:
    """The pinned locale, else the locale the page declared."""
    if mirror.scope.locale is not None:
        return mirror.scope.locale
    return candidate.content.declared_locale if candidate.content is not None else None
