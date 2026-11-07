"""Link resolution and rewriting (mirror.allium 1116 to 1285): the finalise pass's links.

Every finalisation drops the written pages' links and resolves each destination of each
converted body against the whole mirror; exactly one of the four LinkTo* rules fires per
destination, their guards partitioning the cases. A body is rewritten from its converted
body, never from the published one, so rewriting is idempotent. `find_broken_links`
reads the page files back once they are written.
"""

import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from rovo._convert.fidelity import link_destinations, map_destinations, prose_lines
from rovo._mirror.model import (
    BrokenLink,
    BrokenLinkReason,
    Link,
    LinkKind,
    LinksRewritten,
    Mirror,
    MirrorPass,
    Page,
    PageStatus,
    PassStatus,
)

# Targets that are left as written and never become links (mirror.allium 1132 to 1136).
_NOT_LINKS = frozenset({"mailto", "tel", "javascript", "data"})
_FRONTMATTER = "---\n"
_FRONTMATTER_END = "\n---\n"
# A heading's anchor as the body writes it: `## Title {#id}`.
_HEADING_ANCHOR = re.compile(r"^ {0,3}#{1,6}\s.*\{#(?P<id>[^}\s]+)\}\s*$")
# An id in the body's HTML: an anchor island `<a id="x"></a>`, or one kept in an island.
_HTML_ID = re.compile(r'<[A-Za-z][A-Za-z0-9-]*\s[^<>]*?(?<![\w-])id="(?P<id>[^"]+)"')
_PARENT = ".."


@dataclass(frozen=True, kw_only=True)
class Destination:
    """One link destination of a body: the target as written, and its fragment."""

    target: str
    fragment: str | None


def destinations_of(body: str) -> tuple[Destination, ...]:
    """link_destinations' guidance: web destinations outside code, split at `#`.

    An empty target and a mailto:, tel:, javascript: or data: target are dropped (images
    are never destinations); a bare `#fragment` has the empty target, the page itself.
    """
    return tuple(
        destination
        for written in link_destinations(body)
        if (destination := _destination(written)) is not None
    )


def resolve_mirror_links(pass_: MirrorPass) -> bool:
    """Realises mirror.allium ResolveMirrorLinks; False when its guard does not hold.

    Every written page's links are dropped, then each page's destinations are resolved
    in path order.
    """
    if pass_.status is not PassStatus.pending:
        return False
    mirror = pass_.mirror
    mirror.links = [link for link in mirror.links if link.source.status is not PageStatus.written]
    for page in sorted(mirror.written_pages, key=lambda page: page.path):
        for destination in destinations_of(page.converted_body):
            _destination_found(pass_, page, destination.target, destination.fragment)
    return True


def link_to_page(pass_: MirrorPass, page: Page, target: str, fragment: str | None) -> Link | None:
    """Realises mirror.allium LinkToPage; None when its guard does not hold."""
    del pass_  # The pass only orders the rule after ScopeSettled.
    identity = _identity(page, target)
    holder = None if identity is None else page.mirror.known_page(identity)
    if identity is None or holder is None:
        return None
    return _created(
        page,
        identity,
        fragment,
        LinkKind.internal,
        holder,
        resolved=fragment is None or fragment in holder.anchors,
    )


def link_to_removed_page(
    pass_: MirrorPass, page: Page, target: str, fragment: str | None
) -> Link | None:
    """Realises mirror.allium LinkToRemovedPage; None when its guards do not hold."""
    del pass_  # The pass only orders the rule after ScopeSettled.
    identity = _identity(page, target)
    if identity is None or page.mirror.known_page(identity) is not None:
        return None
    holder = page.mirror.page(identity)
    if holder is None or holder.status is not PageStatus.removed:
        return None
    return _created(page, identity, fragment, LinkKind.dangling, None, resolved=True)


def link_to_uncrawled_page(
    pass_: MirrorPass, page: Page, target: str, fragment: str | None
) -> Link | None:
    """Realises mirror.allium LinkToUncrawledPage; None when its guards do not hold."""
    del pass_  # The pass only orders the rule after ScopeSettled.
    identity = _identity(page, target)
    if (
        identity is None
        or not _unknown(page.mirror, identity)
        or not page.mirror.scope.within_bounds(identity)
    ):
        return None
    return _created(page, identity, fragment, LinkKind.uncrawled, None, resolved=True)


def link_to_external_page(
    pass_: MirrorPass, page: Page, target: str, fragment: str | None
) -> Link | None:
    """Realises mirror.allium LinkToExternalPage; None when its guards do not hold."""
    del pass_  # The pass only orders the rule after ScopeSettled.
    identity = _identity(page, target)
    if (
        identity is None
        or not _unknown(page.mirror, identity)
        or page.mirror.scope.within_bounds(identity)
    ):
        return None
    return _created(page, identity, fragment, LinkKind.external, None, resolved=True)


def rewrite_destinations(body: str, page: Page) -> str:
    """The body with each internal destination a relative path between page files.

    A self-link with a fragment becomes the bare fragment; every other destination, and
    every byte outside the destinations, is left as written.
    """
    return map_destinations(body, _rewriter(page))


def relative_path(from_path: str, to_path: str) -> str:
    """The relative path from one mirror-relative page file to another."""
    return posixpath.relpath(to_path, posixpath.dirname(from_path) or ".")


def find_broken_links(mirror: Mirror) -> list[BrokenLink]:
    """Every relative destination in a page file that leaves the mirror or reaches nothing.

    Destinations in frontmatter and code are never verified. A fragment is broken when the
    target file holds no anchor for it (`anchors_in`) and the page holds no link that
    already records it as unresolved (unresolved_fragment). A missing page file is one
    `missing_file` finding whose href is empty.
    """
    broken: list[BrokenLink] = []
    for page in sorted(mirror.written_pages, key=lambda page: page.path):
        path = mirror.out_dir / page.path
        if not path.is_file():
            broken.append(
                BrokenLink(from_path=page.path, href="", reason=BrokenLinkReason.missing_file)
            )
            continue
        for href in link_destinations(_body_of(path)):
            reason = broken_reason(mirror, page.path, href, page)
            if reason is not None:
                broken.append(BrokenLink(from_path=page.path, href=href, reason=reason))
    return broken


def finish_link_pass(pass_: MirrorPass) -> LinksRewritten | None:
    """Realises mirror.allium FinishLinkPass; None when its guard does not hold."""
    if pass_.status is not PassStatus.pending:
        return None
    broken = find_broken_links(pass_.mirror)
    pass_.broken_links = broken
    return LinksRewritten(
        mirror=pass_.mirror, pass_=pass_, operator=pass_.operator, broken=tuple(broken)
    )


def _destination(written: str) -> Destination | None:
    """The destination as written, split at its first `#`; None when it is never a link."""
    if not written or urlsplit(written).scheme.lower() in _NOT_LINKS:
        return None
    target, _, fragment = written.partition("#")
    return Destination(target=target, fragment=fragment or None)


def _destination_found(pass_: MirrorPass, page: Page, target: str, fragment: str | None) -> None:
    """DestinationFound: the LinkTo* rules' guards partition it, so exactly one fires.

    A destination with no identity (a URL normalise_url cannot parse) fires none and
    records no Link, so rewrite_destinations leaves it as written (32f2210).
    """
    _ = (
        link_to_page(pass_, page, target, fragment)
        or link_to_removed_page(pass_, page, target, fragment)
        or link_to_uncrawled_page(pass_, page, target, fragment)
        or link_to_external_page(pass_, page, target, fragment)
    )


def _identity(page: Page, target: str) -> str | None:
    """The destination made absolute against the page's source URL, as an identity.

    None for a malformed URL (a port out of range), which is out of bounds and has none.
    """
    try:
        return page.mirror.scope.identity_of(urljoin(page.source_url, target))
    except ValueError:
        return None


def _unknown(mirror: Mirror, identity: str) -> bool:
    """No written page holds the identity, and no page record has it."""
    return mirror.known_page(identity) is None and mirror.page(identity) is None


def _created(  # noqa: PLR0913  Link.created's fields.
    page: Page,
    identity: str,
    fragment: str | None,
    kind: LinkKind,
    target: Page | None,
    *,
    resolved: bool,
) -> Link:
    link = Link(
        source=page,
        target_identity=identity,
        fragment=fragment,
        kind=kind,
        target=target,
        fragment_resolved=resolved,
    )
    page.mirror.links.append(link)
    return link


def _rewriter(page: Page) -> Callable[[str], str]:
    """The mapping rewrite_destinations applies to each destination of the page's body."""

    def rewrite(written: str) -> str:
        destination = _destination(written)
        if destination is None:
            return written
        identity = _identity(page, destination.target)
        holder = None if identity is None else page.mirror.known_page(identity)
        if holder is None:
            return written
        suffix = "" if destination.fragment is None else f"#{destination.fragment}"
        if holder is page and suffix:
            return suffix
        return relative_path(page.path, holder.path) + suffix

    return rewrite


def _body_of(path: Path) -> str:
    """A page file's text after its frontmatter."""
    text = path.read_text(encoding="utf-8")
    if text.startswith(_FRONTMATTER):
        end = text.find(_FRONTMATTER_END, len(_FRONTMATTER) - 1)
        if end != -1:
            return text[end + len(_FRONTMATTER_END) :]
    return text


def _anchors_of(path: Path) -> frozenset[str]:
    """The anchors a file's body holds: `{#id}` heading suffixes and ids in its HTML.

    A file that is not UTF-8 holds none.
    """
    try:
        body = _body_of(path)
    except (OSError, UnicodeDecodeError):
        return frozenset()
    return anchors_in(body)


def anchors_in(body: str) -> frozenset[str]:
    """The `{#id}` heading anchors and the HTML ids of a body, outside code."""
    lines = prose_lines(body)
    headings = {
        match["id"] for line in lines if (match := _HEADING_ANCHOR.match(line)) is not None
    }
    return frozenset(
        headings | {match["id"] for line in lines for match in _HTML_ID.finditer(line)}
    )


def broken_reason(
    mirror: Mirror, from_path: str, href: str, page: Page | None = None
) -> BrokenLinkReason | None:
    """Why a destination in the file at `from_path` is broken; None when absolute or sound.

    A fragment the target file does not hold is not broken when `page`, the file's page,
    holds a link that already records it as unresolved (unresolved_fragment).
    """
    parts = urlsplit(href)
    if not href or parts.scheme or parts.netloc:
        return None
    file_part, _, fragment = href.partition("#")
    target = (
        from_path
        if not file_part
        else posixpath.normpath(posixpath.join(posixpath.dirname(from_path), file_part))
    )
    if target == _PARENT or target.startswith(("../", "/")):
        return BrokenLinkReason.outside_mirror
    path = mirror.out_dir / target
    if not path.is_file():
        return BrokenLinkReason.missing_file
    if not fragment or fragment in _anchors_of(path):
        return None
    recorded = page is not None and any(
        link.source is page
        and link.target is not None
        and link.target.path == target
        and link.fragment == fragment
        and not link.fragment_resolved
        for link in mirror.links
    )
    return None if recorded else BrokenLinkReason.fragment_not_found
