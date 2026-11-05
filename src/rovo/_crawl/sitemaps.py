"""The discovery black boxes of crawl.allium (47 to 59): sitemaps and llms.txt, pure.

The readings are tickets/T13-discovery.md's Facts: a sitemap document is XML whose root
is urlset or sitemapindex in any namespace, parsed by lxml with entities, DTDs and the
network off; llms.txt names every inline Markdown link. No lxml value leaves this
module: every value read from the tree becomes a str or None first.
"""

import re
from urllib.parse import urljoin

from lxml import etree  # type: ignore[import-untyped]  # lxml ships no type information.

from rovo._convert.model import Profile
from rovo._crawl.model import SitemapEntry, SiteResponse
from rovo._mirror.model import CrawlScope
from rovo._mirror.urls import pattern_matches
from rovo._unfinished import NotInThisSlice

_DOCUMENT_ROOTS = frozenset({"urlset", "sitemapindex"})
_ENTRY_TAGS = frozenset({"url", "sitemap"})
# An inline Markdown link: [text](destination) or [text](<destination> "title").
_INLINE_LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_PLACEHOLDERS = ("{section}", "{locale}")


def well_known_sitemaps(origin: str) -> tuple[str, ...]:
    """crawl.allium well_known_sitemaps: /sitemap.xml then /sitemap_index.xml at `origin`."""
    return (f"{origin}/sitemap.xml", f"{origin}/sitemap_index.xml")


def llms_txt_url(origin: str) -> str:
    """crawl.allium llms_txt_url: /llms.txt at `origin`."""
    return f"{origin}/llms.txt"


def is_sitemap_document(response: SiteResponse) -> bool:
    """XML whose root element is urlset or sitemapindex, any namespace."""
    return _read(response)[0] in _DOCUMENT_ROOTS


def sitemap_is_index(response: SiteResponse) -> bool:
    """The root element is sitemapindex."""
    return _read(response)[0] == "sitemapindex"


def sitemap_entries(response: SiteResponse) -> tuple[SitemapEntry, ...]:
    """Each url or sitemap child's loc, stripped, with its lastmod or None, in order."""
    return _read(response)[1]


def resolve_url(base: str, loc: str) -> str:
    """crawl.allium resolve_url: `loc` against `base`, as urllib.parse.urljoin."""
    return urljoin(base, loc)


def llms_txt_targets(response: SiteResponse, base: str) -> tuple[str, ...]:
    """Every inline Markdown link's destination, resolved against `base`, each once.

    A destination urljoin cannot parse has no identity and is no target (ReadLlmsTxt
    guidance).
    """
    targets: list[str] = []
    for match in _INLINE_LINK.finditer(response.markup):
        try:
            targets.append(urljoin(base, match.group(1)))
        except ValueError:  # An unclosed IPv6 bracket.
            continue
    return tuple(dict.fromkeys(targets))


def sitemap_admitted(url: str, profile: Profile, scope: CrawlScope) -> bool:
    """The profile's sitemap_include filter: an empty filter admits every sitemap.

    Filling {section} and {locale} with the scope's is unstated (CrawlScope has no
    section), so a filter holding a placeholder stops the run (FetchSitemap guidance;
    T13 follow-up question, item 4, carried to T17).
    """
    del scope  # Only the placeholders read it, and they stop first.
    patterns = profile.sitemap_include
    if any(holder in pattern for pattern in patterns for holder in _PLACEHOLDERS):
        raise NotInThisSlice(rule="sitemap_admitted")
    return not patterns or any(pattern_matches(url, pattern) for pattern in patterns)


def _read(response: SiteResponse) -> tuple[str | None, tuple[SitemapEntry, ...]]:
    """The root's local name and the entries, or (None, ()) when the answer is not XML."""
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False
    )
    try:
        root = etree.fromstring(response.markup.encode(), parser)
    except (etree.XMLSyntaxError, ValueError):
        return None, ()
    entries: list[SitemapEntry] = []
    for child in root:
        if _local_name(child.tag) not in _ENTRY_TAGS:
            continue
        values = {_local_name(field.tag): _text(field.text) for field in child}
        loc = values.get("loc")
        if loc:
            entries.append(SitemapEntry(loc=loc, lastmod=values.get("lastmod")))
    return _local_name(root.tag), tuple(entries)


def _local_name(tag: object) -> str | None:
    """An element's tag without its namespace; None for a comment or an instruction."""
    return str(etree.QName(tag).localname) if isinstance(tag, str) else None


def _text(text: object) -> str | None:
    """An element's text, stripped, as a plain str; None when it has none."""
    return (str(text).strip() or None) if isinstance(text, str) else None
