"""Page intake (mirror.allium 518 to 916): candidates become pages and aliases.

Several rules share `PageCandidate.created`; their guards partition the outcomes, so
`settle_candidate` fires the one whose guards hold, exactly one per candidate. The
lifecycle rules (RetirePage, MovePage, ReviveRemovedPage) move no file here: each records
its file event on the mirror, and the next finalise pass applies it.
"""

from rovo._mirror.model import (
    Alias,
    CandidateDelivered,
    CandidateDiscarded,
    CandidateDuplicate,
    CandidateOutcome,
    CandidateStatus,
    FileEffect,
    FileEffectKind,
    LinksFound,
    Mirror,
    Page,
    PageCandidate,
    PageRemoved,
    PageStatus,
    RemovalReason,
    StoreOutcome,
)
from rovo._mirror.state import Clock, SystemClock
from rovo._mirror.urls import assign_path, digest, version_label

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
    the mirror changes. The page a move would move is not another page holding a path,
    as MovePage reads it.
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
    if assign_path(mirror, identity, mirror.known_page(candidate.requested_identity)) is not None:
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
    for url in _passed(candidate):
        if url != page.identity:
            _alias_recorded(mirror, url, page)
    candidate.status = CandidateStatus.accepted
    return links_found(candidate, page)


def links_found(candidate: PageCandidate, page: Page) -> LinksFound:
    """The LinksFound RefreshPage raises for the stored page (mirror.allium 878)."""
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

    The target keeps its content digest as its previous digest; a known page other than
    the target is merged into it (PageRetired, reason merged); then RefreshPage (raised as
    PageContentAccepted) refreshes the target and makes the merged URL its alias.
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
    target.previous_digest = target.content_digest
    if previous is not None and previous is not target:
        retire_page(previous, RemovalReason.merged, clock)
    refresh_page(candidate, target, clock)
    return target


def reject_duplicate_candidate(
    candidate: PageCandidate, clock: Clock | None = None
) -> CandidateDuplicate | None:
    """Realises mirror.allium RejectDuplicateCandidate; None when its guards do not hold.

    The target was stored by this run, so the first store's content stands: a known page
    the requested URL held is merged into it, and every URL on the way becomes its alias.
    `clock` dates that merge; the real clock when none is given.
    """
    if candidate.status is not CandidateStatus.pending:
        return None
    if candidate.outcome is not CandidateOutcome.converted:
        return None
    mirror = candidate.mirror
    target = mirror.page(_page_identity(candidate))
    if target is None or target.status is not PageStatus.written:
        return None
    if target.last_stored_run != candidate.run_id:
        return None
    previous = mirror.known_page(candidate.requested_identity)
    if previous is not None and previous is not target:
        retire_page(previous, RemovalReason.merged, clock or SystemClock())
    for url in _passed(candidate):
        if url != target.identity:
            _alias_recorded(mirror, url, target)
    candidate.status = CandidateStatus.duplicate
    return CandidateDuplicate(candidate=candidate, page=target)


def move_page(candidate: PageCandidate, clock: Clock) -> Page | None:
    """Realises mirror.allium MovePage: the moved page, refreshed; None when its guards fail.

    The known page takes the new identity; a removed record holding it leaves the mirror
    and its archived copy is deleted, and an alias the identity held is dropped. The path
    follows the identity: when it changes, the file move is recorded for finalisation.
    """
    if candidate.status is not CandidateStatus.pending:
        return None
    if candidate.outcome is not CandidateOutcome.converted:
        return None
    mirror = candidate.mirror
    identity = _page_identity(candidate)
    target = mirror.page(identity)
    previous = mirror.known_page(candidate.requested_identity)
    if previous is None:
        return None
    if target is not None and target.status is not PageStatus.removed:
        return None
    old_path = previous.path
    new_path = assign_path(mirror, identity, previous)
    if new_path is None:
        return None
    if target is not None:
        mirror.record_file_effect(
            FileEffect(kind=FileEffectKind.archived_copy_deleted, path=target.path)
        )
        mirror.pages.remove(target)
    stale = mirror.alias(identity)
    if stale is not None:
        mirror.aliases.remove(stale)
    previous.identity = identity
    previous.previous_digest = previous.content_digest
    if new_path != old_path:
        previous.moved_from = old_path
        previous.path = new_path
        mirror.record_file_effect(
            FileEffect(kind=FileEffectKind.moved, path=old_path, source=new_path)
        )
    refresh_page(candidate, previous, clock)
    return previous


def revive_removed_page(candidate: PageCandidate, clock: Clock) -> Page | None:
    """Realises mirror.allium ReviveRemovedPage: the revived page; None when its guards fail.

    The removed record is written again at a path for its identity, new again, and its
    archived copy leaves the removed area.
    """
    if candidate.status is not CandidateStatus.pending:
        return None
    if candidate.outcome is not CandidateOutcome.converted:
        return None
    mirror = candidate.mirror
    identity = _page_identity(candidate)
    target = mirror.page(identity)
    if mirror.known_page(candidate.requested_identity) is not None:
        return None
    if target is None or target.status is not PageStatus.removed:
        return None
    archived_path = target.path
    new_path = assign_path(mirror, identity)
    if new_path is None:
        return None
    target.status = PageStatus.written
    target.removed_at = None
    target.removal_reason = None
    target.redirect_target = None
    target.path = new_path
    target.previous_digest = None
    target.first_seen = clock.now()
    mirror.record_file_effect(
        FileEffect(kind=FileEffectKind.archived_copy_deleted, path=archived_path, source=new_path)
    )
    refresh_page(candidate, target, clock)
    return target


def remove_absent_page(candidate: PageCandidate, clock: Clock) -> PageRemoved | None:
    """Realises mirror.allium RemoveAbsentPage: RetirePage's PageRemoved, else None."""
    if candidate.status is not CandidateStatus.pending:
        return None
    if candidate.outcome is not CandidateOutcome.absent:
        return None
    previous = candidate.mirror.known_page(candidate.requested_identity)
    if previous is None:
        return None
    candidate.status = CandidateStatus.accepted
    return retire_page(previous, RemovalReason.absent, clock, candidate=candidate)


def accept_absent_without_page(candidate: PageCandidate) -> bool:
    """Realises mirror.allium AcceptAbsentWithoutPage; False when its guards do not hold."""
    return _accept_without_page(candidate, CandidateOutcome.absent)


def remove_redirected_out_page(candidate: PageCandidate, clock: Clock) -> PageRemoved | None:
    """Realises mirror.allium RemoveRedirectedOutPage: RetirePage's PageRemoved, else None.

    The out-of-scope target the candidate carries is recorded on the removed page.
    """
    if candidate.status is not CandidateStatus.pending:
        return None
    if candidate.outcome is not CandidateOutcome.redirected_out:
        return None
    previous = candidate.mirror.known_page(candidate.requested_identity)
    if previous is None:
        return None
    candidate.status = CandidateStatus.accepted
    return retire_page(
        previous,
        RemovalReason.redirected_out,
        clock,
        redirect_target=candidate.redirect_target,
        candidate=candidate,
    )


def accept_redirected_out_without_page(candidate: PageCandidate) -> bool:
    """Realises mirror.allium AcceptRedirectedOutWithoutPage; False when its guards fail."""
    return _accept_without_page(candidate, CandidateOutcome.redirected_out)


def retire_page(
    page: Page,
    reason: RemovalReason,
    clock: Clock,
    *,
    redirect_target: str | None = None,
    candidate: PageCandidate | None = None,
) -> PageRemoved | None:
    """Realises mirror.allium RetirePage: its PageRemoved; None when the page is not written.

    The page keeps its record and path; its aliases and outbound links go. Its file is
    archived at _removed/<host>/<relative path>, or deleted under the mirror's prune; no file
    moves here: the event is recorded and the next finalise pass applies it. A page moved
    this run and not yet published is still at its published path, which the event takes.
    """
    if page.status is not PageStatus.written:
        return None
    mirror = page.mirror
    page.status = PageStatus.removed
    page.removed_at = clock.now()
    page.removal_reason = reason
    page.redirect_target = redirect_target
    page.moved_from = None
    mirror.aliases = [alias for alias in mirror.aliases if alias.target is not page]
    mirror.links = [link for link in mirror.links if link.source is not page]
    kind = FileEffectKind.deleted if mirror.prune else FileEffectKind.archived
    source = _published_path(mirror, page.path)
    mirror.record_file_effect(FileEffect(kind=kind, path=page.path, source=source))
    removed = PageRemoved(mirror=mirror, page=page, reason=reason, candidate=candidate)
    mirror.removals.append(removed)
    return removed


def _published_path(mirror: Mirror, path: str) -> str | None:
    """The file a page at `path` is still at, when the moves recorded this run moved it.

    No file moves before finalisation, so the moves are walked back, latest first, from
    `path` to the path the page was last published at; None when no move led to `path`.
    """
    current = path
    for effect in reversed(mirror.file_effects):
        if effect.kind is FileEffectKind.moved and effect.source == current:
            current = effect.path
    return None if current == path else current


def settle_candidate(
    candidate: PageCandidate, clock: Clock
) -> Page | CandidateDiscarded | CandidateDuplicate | PageRemoved | None:
    """Settle one candidate: the one intake rule whose guards hold fires.

    In order: StoreNewPage, RefuseUnplaceableCandidate, RejectDuplicateCandidate,
    RewriteKnownPage, MovePage, ReviveRemovedPage, RecordUnchanged,
    DiscardUnchangedWithoutPage, RemoveAbsentPage, AcceptAbsentWithoutPage,
    RemoveRedirectedOutPage, AcceptRedirectedOutWithoutPage; the guards are exclusive, so
    trying the two Accept rules last changes nothing. The answer is PageStored's page,
    CandidateDiscarded, CandidateDuplicate or PageRemoved; None when the candidate is not
    pending or an Accept...WithoutPage rule took it, which raises no event.
    """
    if candidate.status is not CandidateStatus.pending:
        return None
    settled = (
        store_new_page(candidate, clock)
        or refuse_unplaceable_candidate(candidate)
        or reject_duplicate_candidate(candidate, clock)
        or rewrite_known_page(candidate, clock)
        or move_page(candidate, clock)
        or revive_removed_page(candidate, clock)
        or record_unchanged(candidate, clock)
        or discard_unchanged_without_page(candidate)
        or remove_absent_page(candidate, clock)
        or remove_redirected_out_page(candidate, clock)
    )
    # The two rules that raise no event, one per outcome.
    if settled is None and not accept_absent_without_page(candidate):
        accept_redirected_out_without_page(candidate)
    return settled


def take_candidate(candidate: PageCandidate, clock: Clock) -> Page | None:
    """Settle one candidate as `settle_candidate` does: PageStored's page, else None."""
    settled = settle_candidate(candidate, clock)
    return settled if isinstance(settled, Page) else None


def _accept_without_page(candidate: PageCandidate, outcome: CandidateOutcome) -> bool:
    """Accept a pending candidate of `outcome` whose requested URL has no known page."""
    if candidate.status is not CandidateStatus.pending or candidate.outcome is not outcome:
        return False
    if candidate.mirror.known_page(candidate.requested_identity) is not None:
        return False
    candidate.status = CandidateStatus.accepted
    return True


def _passed(candidate: PageCandidate) -> list[str]:
    """Every URL on the way to the page, as identities: each hop, the source, the request."""
    scope = candidate.mirror.scope
    return [
        *(scope.identity_of(hop) for hop in candidate.redirect_hops),
        scope.identity_of(candidate.source_url),
        candidate.requested_identity,
    ]


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
