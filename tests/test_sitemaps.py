"""The discovery black boxes (crawl.allium 47 to 59), as tickets/T13-discovery.md reads them.

Hand-written tables, no obligation id: `is_sitemap_document` is an XML answer whose root
is `urlset` or `sitemapindex` in any namespace, `sitemap_is_index` the latter;
`sitemap_entries` each `url` or `sitemap` child's stripped `loc` with its `lastmod`, in
order, a child without `loc` skipped; the parser expands no entity and reads no DTD.
`llms_txt_targets` is every inline Markdown link, resolved against llms.txt, each once;
`resolve_url` is `urljoin`; an empty `sitemap_include` admits every sitemap. Re-propagated
by T17 (spec 022eca4, FetchSitemap guidance, crawl.allium 1057 to 1066): a placeholder is
filled before matching, `{section}` matching as `*` does and `{locale}` the scope's pinned
locale, else any one of the scope's locale_codes, so with neither it admits nothing.
"""

import dataclasses

import pytest

from fakes import html_response, text_response, xml_response
from rovo._convert import profiles
from rovo._crawl.model import SitemapEntry, SiteResponse
from rovo._crawl.sitemaps import (
    is_sitemap_document,
    llms_txt_targets,
    llms_txt_url,
    resolve_url,
    sitemap_admitted,
    sitemap_entries,
    sitemap_is_index,
    well_known_sitemaps,
)
from rovo._mirror.model import CrawlScope

SITE = "http://docs.example"
MAP = f"{SITE}/maps/guide.xml"
LLMS = f"{SITE}/llms.txt"
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
URLSET = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{NS}">
    <url>
        <loc>
            {SITE}/guide/a.html
        </loc>
        <lastmod>2026-10-01</lastmod>
    </url>
    <url>
        <loc>{SITE}/guide/b.html</loc>
    </url>
    <url>
        <lastmod>2026-10-02</lastmod>
    </url>
    <url>
        <loc>/guide/c.html</loc>
    </url>
</urlset>
"""
INDEX = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="{NS}">
    <sitemap>
        <loc>{SITE}/maps/one.xml</loc>
        <lastmod>2026-09-30</lastmod>
    </sitemap>
    <sitemap>
        <loc>{SITE}/maps/two.xml</loc>
    </sitemap>
</sitemapindex>
"""
BARE_URLSET = f"<urlset><url><loc>{SITE}/guide/a.html</loc></url></urlset>"
OTHER_NS_INDEX = (
    f'<x:sitemapindex xmlns:x="urn:other"><x:sitemap><x:loc>{SITE}/m.xml</x:loc>'
    "</x:sitemap></x:sitemapindex>"
)
ENTITY = f"""<?xml version="1.0"?>
<!DOCTYPE urlset [
    <!ENTITY secret "http://evil.example/expanded">
    <!ENTITY outside SYSTEM "file:///etc/passwd">
]>
<urlset xmlns="{NS}">
    <url><loc>&secret;</loc></url>
    <url><loc>&outside;</loc></url>
    <url><loc>{SITE}/guide/kept.html</loc></url>
</urlset>
"""
PAGE = "<!doctype html><html><body><main><h1>A page</h1></main></body></html>"
RSS = '<?xml version="1.0"?><rss version="2.0"><channel><title>News</title></channel></rss>'
LLMS_TXT = f"""# Example docs

> Everything an assistant needs.

- [Start]({SITE}/guide/start.html): where to begin
- [Relative](guide/relative.html)
- [Start again]({SITE}/guide/start.html)
- [Rooted](/guide/rooted.html "a title")

Plain text with no link, and a bare {SITE}/guide/bare.html address.
"""


def scope() -> CrawlScope:
    """A scope of the docs site's guide."""
    return CrawlScope(
        root_url=f"{SITE}/guide/",
        start_urls=(f"{SITE}/guide/start.html",),
        allowed_hosts=frozenset({"docs.example"}),
        path_prefixes=("/guide/",),
        include=(),
        exclude=(),
        max_depth=10,
        locale=None,
        meaningful_query_params=(),
        locale_codes=frozenset(),
    )


def test_well_known_sitemaps_and_llms_txt_lie_at_the_origin() -> None:
    """/sitemap.xml, then /sitemap_index.xml, and /llms.txt, at the host's origin."""
    assert well_known_sitemaps(SITE) == (f"{SITE}/sitemap.xml", f"{SITE}/sitemap_index.xml")
    ported = "http://docs.example:8080"
    assert well_known_sitemaps(ported) == (
        f"{ported}/sitemap.xml",
        f"{ported}/sitemap_index.xml",
    )
    assert llms_txt_url(SITE) == LLMS
    assert llms_txt_url(ported) == f"{ported}/llms.txt"


@pytest.mark.parametrize(
    ("markup", "document", "index"),
    [
        pytest.param(URLSET, True, False, id="urlset"),
        pytest.param(INDEX, True, True, id="index"),
        pytest.param(BARE_URLSET, True, False, id="no-namespace"),
        pytest.param(OTHER_NS_INDEX, True, True, id="other-namespace"),
        pytest.param(RSS, False, False, id="other-xml-root"),
        pytest.param("<urlset><url><loc>broken", False, False, id="does-not-parse"),
        pytest.param("", False, False, id="empty"),
    ],
)
def test_is_sitemap_document_and_sitemap_is_index(
    markup: str, *, document: bool, index: bool
) -> None:
    """A urlset or a sitemapindex root, local name, any namespace; anything else is not."""
    response = xml_response(MAP, markup)
    assert is_sitemap_document(response) is document
    if document:
        assert sitemap_is_index(response) is index


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(html_response(MAP, PAGE), id="html-page"),
        pytest.param(text_response(MAP, f"{SITE}/guide/a.html\n{SITE}/guide/b.html\n"), id="text"),
    ],
)
def test_an_html_page_or_a_text_sitemap_is_not_a_sitemap_document(
    response: SiteResponse,
) -> None:
    """A plain-text sitemap and an HTML answer are not sitemap documents (Open points, 7)."""
    assert not is_sitemap_document(response)


def test_sitemap_entries_of_a_urlset() -> None:
    """Each url child's loc, stripped, its lastmod or None, in order; no loc, no entry."""
    assert sitemap_entries(xml_response(MAP, URLSET)) == (
        SitemapEntry(loc=f"{SITE}/guide/a.html", lastmod="2026-10-01"),
        SitemapEntry(loc=f"{SITE}/guide/b.html", lastmod=None),
        SitemapEntry(loc="/guide/c.html", lastmod=None),
    )


def test_sitemap_entries_skip_an_empty_loc_and_strip_the_lastmod() -> None:
    """AcceptFreshSitemap guidance (crawl.allium ecfa257): only a non-empty loc is an entry.

    An empty or blank loc is no entry; a lastmod is stripped as the loc is.
    """
    text = (
        f'<urlset xmlns="{NS}"><url><loc></loc></url><url><loc>  \n </loc></url>'
        f"<url><loc> {SITE}/guide/a.html </loc><lastmod>\n 2026-10-01 \n</lastmod></url>"
        "</urlset>"
    )
    assert sitemap_entries(xml_response(MAP, text)) == (
        SitemapEntry(loc=f"{SITE}/guide/a.html", lastmod="2026-10-01"),
    )


def test_sitemap_entries_of_an_index() -> None:
    """Each sitemap child's loc and lastmod, in document order."""
    assert sitemap_entries(xml_response(MAP, INDEX)) == (
        SitemapEntry(loc=f"{SITE}/maps/one.xml", lastmod="2026-09-30"),
        SitemapEntry(loc=f"{SITE}/maps/two.xml", lastmod=None),
    )
    assert sitemap_entries(xml_response(MAP, OTHER_NS_INDEX)) == (
        SitemapEntry(loc=f"{SITE}/m.xml", lastmod=None),
    )


def test_sitemap_entries_expand_no_entity_and_read_no_file() -> None:
    """An internal entity is not expanded and an external one is not read."""
    entries = sitemap_entries(xml_response(MAP, ENTITY))
    assert SitemapEntry(loc=f"{SITE}/guide/kept.html", lastmod=None) in entries
    for entry in entries:
        assert "evil.example" not in entry.loc
        assert "root:" not in entry.loc


def test_sitemap_entries_values_are_plain_strings() -> None:
    """No lxml value crosses the boundary: every loc and lastmod is a str or None."""
    for entry in sitemap_entries(xml_response(MAP, URLSET)):
        assert type(entry.loc) is str
        assert entry.lastmod is None or type(entry.lastmod) is str


def test_resolve_url_is_urljoin() -> None:
    """An absolute loc stands; a relative one resolves against the sitemap's URL."""
    assert resolve_url(MAP, f"{SITE}/guide/a.html") == f"{SITE}/guide/a.html"
    assert resolve_url(MAP, "/guide/c.html") == f"{SITE}/guide/c.html"
    assert resolve_url(MAP, "child.xml") == f"{SITE}/maps/child.xml"


def test_llms_txt_targets_are_its_inline_links_once_each() -> None:
    """Inline Markdown links, resolved against llms.txt, in order, a repeat dropped."""
    assert llms_txt_targets(text_response(LLMS, LLMS_TXT), LLMS) == (
        f"{SITE}/guide/start.html",
        f"{SITE}/guide/relative.html",
        f"{SITE}/guide/rooted.html",
    )


def test_llms_txt_with_no_link_has_no_target() -> None:
    """Text with no inline link names nothing; a bare address is not a link."""
    text = f"# Docs\n\nSee {SITE}/guide/bare.html for more.\n"
    assert llms_txt_targets(text_response(LLMS, text), LLMS) == ()
    assert llms_txt_targets(text_response(LLMS, ""), LLMS) == ()


def test_an_empty_sitemap_filter_admits_every_sitemap() -> None:
    """The generic and devsite profiles have no sitemap_include: every sitemap is admitted."""
    for profile in (profiles.GENERIC, profiles.DEVSITE):
        assert profile.sitemap_include == ()
        assert sitemap_admitted(f"{SITE}/sitemap.xml", profile, scope())
        assert sitemap_admitted("http://elsewhere.example/any/map.xml", profile, scope())


# mslearn's filter is "*/sitemapindex.xml" and "*/{section}_{locale}_*.xml".
PLACEHOLDER_CASES = {
    "index-whatever-the-locale": (None, f"{SITE}/sitemapindex.xml", True),
    "a-listed-locale": (None, f"{SITE}/maps/graph_en-us_0.xml", True),
    "another-listed-locale": (None, f"{SITE}/maps/graph_de-de_3.xml", True),
    "an-unlisted-locale": (None, f"{SITE}/maps/graph_xx-xx_0.xml", False),
    "a-well-known-name": (None, f"{SITE}/sitemap.xml", False),
    "the-other-well-known-name": (None, f"{SITE}/sitemap_index.xml", False),
    "the-pinned-locale": ("de-de", f"{SITE}/maps/graph_de-de_0.xml", True),
    "a-listed-locale-not-pinned": ("de-de", f"{SITE}/maps/graph_en-us_0.xml", False),
    "index-under-a-pinned-locale": ("de-de", f"{SITE}/sitemapindex.xml", True),
}


@pytest.mark.parametrize("name", list(PLACEHOLDER_CASES))
def test_a_sitemap_filter_placeholder_is_filled(name: str) -> None:
    """{section} matches as * does; {locale} is the pinned locale, else any listed code.

    Re-propagated by T17 from T13's test_a_sitemap_filter_placeholder_stops_at_sitemap_
    admitted (the maintainer's answer, item 1).
    """
    locale, url, admitted = PLACEHOLDER_CASES[name]
    learn = dataclasses.replace(scope(), locale=locale, locale_codes=profiles.MSLEARN.locale_codes)
    assert sitemap_admitted(url, profiles.MSLEARN, learn) is admitted


def test_a_locale_placeholder_with_no_locale_admits_nothing() -> None:
    """No pinned locale and no locale codes: a {locale} pattern admits nothing.

    A pattern without the placeholder still admits what it matches.
    """
    assert scope().locale is None
    assert scope().locale_codes == frozenset()
    assert not sitemap_admitted(f"{SITE}/maps/graph_en-us_0.xml", profiles.MSLEARN, scope())
    assert sitemap_admitted(f"{SITE}/sitemapindex.xml", profiles.MSLEARN, scope())


def test_a_section_placeholder_matches_as_a_star_does() -> None:
    """{section} matches what * matches in pattern_matches, a "/" included.

    A veto-able reading of "matches as * does", recorded in the T17 ledger: fnmatch's *
    crosses "/", so {section} does too.
    """
    rooted = dataclasses.replace(
        profiles.MSLEARN, sitemap_include=(f"{SITE}/maps/{{section}}_{{locale}}.xml",)
    )
    pinned = dataclasses.replace(scope(), locale="en-us")
    assert sitemap_admitted(f"{SITE}/maps/graph_en-us.xml", rooted, pinned)
    assert sitemap_admitted(f"{SITE}/maps/graph/beta_en-us.xml", rooted, pinned)
    assert sitemap_admitted(f"{SITE}/maps/_en-us.xml", rooted, pinned)
    assert not sitemap_admitted(f"{SITE}/maps/graph_de-de.xml", rooted, pinned)
