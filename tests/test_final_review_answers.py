"""The maintainer's final-review answers F2 and F3 (spec 9149df7), as guarantee tests.

F2 (convert.allium 143, 284 to 288): ExtractedContent carries `source_url`, the page URL
`extract` was given, and `normalize` turns only a same-page reference into a footnote:
a bare `#id`, or a link whose target without its fragment is the page URL without its
fragment. A link to another page stays a link even when its fragment matches a local
footnote id. F3 (crawl.allium 1748 to 1750): a render subrequest whose method is not GET
or HEAD is aborted, never sent, so the crawl's request callback (and its fetcher) never
sees it; a GET or HEAD subrequest is answered through the callback as before. The stub
playwright of tests/test_browser_engine.py plays the browser; nothing here launches one,
sleeps or reads stdin.
"""

import dataclasses

import pytest

import test_browser_engine
from fakes import html_response
from rovo._convert import profiles
from rovo._convert.fidelity import convert, extract, measure, normalize, restore
from rovo._convert.model import ExtractedContent
from rovo._crawl.browser import PlaywrightEngine
from test_browser_engine import Answers, Scenario, StubRequest, css_response
from test_crawl import PAGE, SEED, SITE

# test_browser_engine's stub playwright fixture (`scenario`), registered here by this name.
stub_playwright = test_browser_engine.scenario

PAGE_URL = "https://example.com/guide/page"
OTHER_PAGE = "https://example.com/guide/other"
NOTE = '<section class="footnotes"><ol><li id="fn1"><p>The note.</p></li></ol></section>'
NOTE_LINE = "[^1]: The note."


def page_with(reference: str) -> str:
    """A page at PAGE_URL whose prose holds `reference` and whose one note is fn1."""
    return (
        "<html><body><main><h1>Notes</h1>"
        f"<p>A sentence {reference} ends here.</p>{NOTE}</main></body></html>"
    )


def body_of(content: ExtractedContent) -> str:
    """The Markdown body normalize and convert make of `content` (generic profile)."""
    normalized = normalize(content, profiles.GENERIC)
    body = restore(convert(normalized.fragment), normalized.islands)
    measure(content, normalized, body)
    return body


def converted(html: str, url: str = PAGE_URL) -> str:
    """The Markdown body of `html` extracted at `url`."""
    return body_of(extract(html, url, profiles.GENERIC))


# --- F2: only a same-page reference becomes a footnote ----------------------------------


def test_f2_extract_carries_the_page_url_it_was_given() -> None:
    """ExtractedContent.source_url (convert.allium 143) is extract's URL, as given."""
    assert extract(page_with("plain"), PAGE_URL, profiles.GENERIC).source_url == PAGE_URL
    with_fragment = f"{PAGE_URL}#intro"
    extracted = extract(page_with("plain"), with_fragment, profiles.GENERIC)
    assert extracted.source_url == with_fragment


def test_f2_a_bare_fragment_reference_becomes_a_footnote() -> None:
    """A link that is a bare `#id` naming a local note is `[^n]` (convert.allium 284)."""
    body = converted(page_with('<a href="#fn1">1</a>'))
    assert "A sentence [^1] ends here." in body
    assert NOTE_LINE in body


def test_f2_a_bare_fragment_reaching_normalize_becomes_a_footnote() -> None:
    """An unresolved `#id` reaching normalize is same-page, whatever the source URL."""
    extracted = extract(page_with("plain"), PAGE_URL, profiles.GENERIC)
    bare = dataclasses.replace(
        extracted, html=extracted.html.replace("plain", '<a href="#fn1">1</a>')
    )
    body = body_of(bare)
    assert "A sentence [^1] ends here." in body
    assert NOTE_LINE in body


@pytest.mark.parametrize(
    ("page_url", "href"),
    [
        pytest.param(PAGE_URL, f"{PAGE_URL}#fn1", id="absolute"),
        pytest.param(PAGE_URL, "page#fn1", id="relative"),
        pytest.param(f"{PAGE_URL}#intro", f"{PAGE_URL}#fn1", id="page-url-with-a-fragment"),
    ],
)
def test_f2_a_full_same_page_url_reference_becomes_a_footnote(page_url: str, href: str) -> None:
    """A link whose target without fragment is the page URL without fragment is `[^n]`."""
    body = converted(page_with(f'<a href="{href}">here</a>'), page_url)
    assert "A sentence [^1] ends here." in body
    assert NOTE_LINE in body


@pytest.mark.parametrize(
    ("href", "target"),
    [
        pytest.param(f"{OTHER_PAGE}#fn1", f"{OTHER_PAGE}#fn1", id="another-page"),
        pytest.param("other#fn1", f"{OTHER_PAGE}#fn1", id="another-page-relative"),
        pytest.param("page?v=2#fn1", f"{PAGE_URL}?v=2#fn1", id="same-path-another-query"),
        pytest.param("https://example.org/guide/page#fn1", None, id="another-host"),
    ],
)
def test_f2_a_cross_document_link_matching_a_local_note_id_stays_a_link(
    href: str, target: str | None
) -> None:
    """A link to another page stays a link though its fragment names a local note.

    convert.allium 284 to 288 (decided at 9149df7): its target, made absolute, is the
    link's target in the body; the note keeps its definition and no `[^1]` reference
    stands in for the link.
    """
    body = converted(page_with(f'<a href="{href}">there</a>'))
    assert f"[there]({target or href})" in body
    assert "A sentence [^1]" not in body
    assert NOTE_LINE in body


def test_f2_same_page_and_cross_document_references_on_one_page() -> None:
    """On one page the same-page references are footnotes and the other page's a link."""
    body = converted(
        page_with(
            f'<sup><a href="#fn1">1</a></sup>, <a href="{OTHER_PAGE}#fn1">there</a>'
            f' and <a href="{PAGE_URL}#fn1">here</a>'
        )
    )
    assert f"A sentence [^1], [there]({OTHER_PAGE}#fn1) and [^1] ends here." in body
    assert NOTE_LINE in body


# --- F3: a render subrequest that is not GET or HEAD is aborted, never sent -------------

DATA = f"{SITE}/guide/data.json"
PING = f"{SITE}/guide/ping"
SUBMIT = f"{SITE}/guide/submit"
STYLE = test_browser_engine.STYLE


def with_methods(monkeypatch: pytest.MonkeyPatch, methods: dict[str, str]) -> None:
    """The stub browser's requests carry `methods[url]`, else GET (the stub's default)."""

    def request(*, url: str, navigation: bool, resource_type: str = "document") -> StubRequest:
        return StubRequest(
            url=url,
            navigation=navigation,
            resource_type=resource_type,
            method=methods.get(url, "GET"),
        )

    monkeypatch.setattr(test_browser_engine, "StubRequest", request)


def rendered_with(scenario: Scenario, answers: Answers, subrequests: list[str]) -> None:
    """Render SEED in a PlaywrightEngine whose page asks for `subrequests`."""
    scenario.subrequests[SEED] = subrequests
    engine = PlaywrightEngine()
    try:
        assert engine.render(SEED, answers) is not None
    finally:
        engine.close()


def routes_for(scenario: Scenario, url: str) -> list[test_browser_engine.StubRoute]:
    """Every route the stub browser opened for `url`."""
    return [route for route in scenario.routes if route.request.url == url]


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_f3_a_subrequest_that_is_not_get_or_head_is_aborted_never_sent(
    stub_playwright: Scenario, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    """AttemptTier guidance (crawl.allium 1748 to 1750, decided at 9149df7).

    A subrequest whose method is not GET or HEAD is aborted: the crawl's request
    callback is never asked for it, so no fetch is made, and its route is aborted, not
    fulfilled. The page's other subrequest, a GET, is still answered.
    """
    with_methods(monkeypatch, {SUBMIT: method})
    answers = Answers({SEED: html_response(SEED, PAGE), STYLE: css_response(STYLE)})
    rendered_with(stub_playwright, answers, ["submit", "style.css"])
    assert answers.calls == [(SEED, True), (STYLE, False)]
    (submit,) = routes_for(stub_playwright, SUBMIT)
    assert submit.aborted
    assert submit.fulfilled is None
    (style,) = routes_for(stub_playwright, STYLE)
    assert style.fulfilled is not None


def test_f3_get_and_head_subrequests_are_still_answered_through_the_crawl(
    stub_playwright: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GET and a HEAD subrequest reach the callback and are fulfilled from its answer.

    Beside them a POST to the same page's directory is aborted unasked.
    """
    with_methods(monkeypatch, {PING: "HEAD", SUBMIT: "POST"})
    answers = Answers(
        {
            SEED: html_response(SEED, PAGE),
            DATA: css_response(DATA, "{}"),
            PING: css_response(PING, ""),
            SUBMIT: css_response(SUBMIT, "accepted"),
        }
    )
    rendered_with(stub_playwright, answers, ["data.json", "ping", "submit"])
    assert answers.calls == [(SEED, True), (DATA, False), (PING, False)]
    for url in (DATA, PING):
        (route,) = routes_for(stub_playwright, url)
        assert route.fulfilled is not None
        assert not route.aborted
    (submit,) = routes_for(stub_playwright, SUBMIT)
    assert submit.aborted
