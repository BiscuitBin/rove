"""convert.allium's obligations: the Fidelity operations on HTML strings, the profiles, config.

Each test is named after the obligation id `just plan-spec convert` emits, dots and
hyphens as underscores, and its docstring quotes the obligation. Everything here is
pure: no network, no file but the fixture pages, no clock.

Re-propagated by T17 (origin T09): the Fidelity contract tests, test_body_shape and
test_surface_exposure_PageConversion are extended with islands, tab panels, the declared
reductions, the normalisation flags and the devsite and mslearn selections; the
guarantees without an obligation id follow them, named after the guarantee. The devsite
markup is tests/fixtures/sites/devsite/; the mslearn markup is a unit input here, and
tests/e2e/test_mslearn_sync.py syncs it end to end.

Re-propagated by the T17 follow-up (spec 022eca4, ExtractNeverEmptyHanded): a page the
profile's selection does not match is extracted by the fallback extractor, trafilatura,
before the whole body; only a page trafilatura finds no main content in (IMAGE_ONLY) is
extracted whole. The island attributes are the union DeclaredReductions and
SanitizedMeansInert now state.
"""

import dataclasses
import inspect
import re
from collections.abc import Iterable
from pathlib import Path

import pytest

from rovo._convert import profiles
from rovo._convert.fidelity import (
    convert,
    converted_content,
    extract,
    link_destinations,
    map_destinations,
    measure,
    normalize,
    restore,
    with_fetch_flags,
)
from rovo._convert.model import (
    ConvertedContent,
    ExpectedCounts,
    ExtractedContent,
    ExtractionMethod,
    HeadingAnchorStyle,
    Island,
    NormalizedContent,
    OutputMeasurement,
    Profile,
    QualityFlag,
    QualityGate,
    QualityResult,
    VersionMapping,
)
from spec_values import spec_enum, spec_float, spec_int, spec_names

SITES = Path(__file__).resolve().parent / "fixtures" / "sites"
SEED = "http://docs.example/guide/start.html"
PAGE = (SITES / "one-page" / "guide" / "start.html").read_text(encoding="utf-8")
PAGE_HEADINGS = ("Getting started", "Install the product")
PAGE_DESCRIPTION = "How to start with the example product."

# One of every element class the gates measure, so that no gate passes unmeasured.
EVERY_CONSTRUCT = """<!doctype html>
<html lang="en">
    <head><title>Every construct</title></head>
    <body>
        <nav><a href="/guide/start.html">Start</a></nav>
        <main>
            <h1>Every construct</h1>
            <p>Prose with a <a href="/guide/other.html">link to another page</a> to cover.</p>
            <h2 id="code">Code</h2>
            <pre><code class="language-python">print("hello")
</code></pre>
            <h2>Table</h2>
            <table>
                <thead><tr><th>Name</th><th>Value</th></tr></thead>
                <tbody><tr><td>alpha</td><td>one</td></tr></tbody>
            </table>
            <h2>List</h2>
            <ul><li>first item</li><li>second item</li></ul>
            <p><img src="http://docs.example/img/diagram.png" alt="A diagram"></p>
        </main>
    </body>
</html>
"""
EVERY_CONSTRUCT_EXPECTED = {
    "code_blocks": 1,
    "tables": 1,
    "table_cells": 4,
    "headings": 4,
    "links": 1,
    "images": 1,
    "list_items": 2,
    "tab_panels": 0,
}
OTHER_PAGE = "http://docs.example/guide/other.html"

# A page with no main or article: the generic selection finds nothing.
NO_MAIN = """<!doctype html>
<html lang="en">
    <head><title>Loose page</title></head>
    <body>
        <h1>Loose page</h1>
        <p>A page whose content sits directly in the body, with no main element at all.</p>
    </body>
</html>
"""

# A page with no text at all, which the fallback extractor finds no main content in: only
# the whole body is left (ExtractNeverEmptyHanded, the T17 follow-up).
IMAGE_ONLY = """<!doctype html>
<html lang="en">
    <head><title>Picture page</title></head>
    <body><p><img src="http://docs.example/a.png" alt="A diagram"></p></body>
</html>
"""

# T17: the fixture sites' pages, and the Learn-shaped markup the mslearn profile selects.
QUALITY = SITES / "quality" / "guide"
ISLANDS_PAGE = (QUALITY / "islands.html").read_text(encoding="utf-8")
GATES_PAGE = (QUALITY / "gates.html").read_text(encoding="utf-8")
TABS_PAGE = (SITES / "devsite" / "guide" / "tabs.html").read_text(encoding="utf-8")
DEVSITE_CHROME = (
    "Example developers header",
    "Left navigation start",
    "Example developers footer",
)
GOOGLE_URL = "https://developers.google.com/example/guide/tabs"
LEARN_URL = "https://learn.microsoft.com/en-us/graph/api/user-post-users"
LEARN_CHROME = ("Microsoft Learn header", "Learn table of contents", "Microsoft Learn footer")
MSLEARN_PAGE = """<!doctype html>
<html lang="en-us">
    <head><title>Create user | Microsoft Learn</title></head>
    <body>
        <header id="ms--site-header">Microsoft Learn header</header>
        <nav id="left-container">Learn table of contents</nav>
        <main id="main" class="layout-body-main">
            <div class="content">
                <h1>Create user</h1>
                <p>Create a new user object in the directory of the organisation.</p>
                <div class="alert is-info">
                    <p class="alert-title">Note</p>
                    <p>Only an administrator can create a user.</p>
                </div>
                <h2>Request</h2>
                <div class="tabGroup" id="tabgroup_1">
                    <ul role="tablist">
                        <li role="presentation">
                            <a href="#tabpanel_1_http" role="tab" data-tab="http">HTTP</a>
                        </li>
                        <li role="presentation">
                            <a href="#tabpanel_1_csharp" role="tab" data-tab="csharp">C#</a>
                        </li>
                    </ul>
                    <section id="tabpanel_1_http" role="tabpanel" data-tab="http">
                        <pre><code class="lang-http">POST https://graph.microsoft.com/v1.0/users</code></pre>
                    </section>
                    <section
                        id="tabpanel_1_csharp" role="tabpanel" data-tab="csharp" hidden="hidden"
                    >
                        <pre><code class="lang-csharp">var user = new User();</code></pre>
                    </section>
                </div>
            </div>
        </main>
        <footer id="ms--site-footer">Microsoft Learn footer</footer>
    </body>
</html>
"""
# A page holding one construct in its main, between a heading and a sentence of prose.
CONSTRUCT_PAGE = """<!doctype html>
<html lang="en">
    <head><title>One construct</title></head>
    <body>
        <main>
            <h1>One construct</h1>
            <p>The construct below is what this page is about.</p>
            {construct}
        </main>
    </body>
</html>
"""
COMPLEX_TABLE = (
    "<table><thead><tr><th>Region</th><th>Zone</th></tr></thead><tbody>"
    '<tr><td rowspan="2">North</td><td>north-one</td></tr>'
    "<tr><td>north-two</td></tr></tbody></table>"
)
HEADERLESS_TABLE = (
    "<table><tr><td>alpha</td><td>one</td></tr><tr><td>beta</td><td>two</td></tr></table>"
)
ROW_HEADER_TABLE = (
    "<table><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody>"
    '<tr><th scope="row">alpha</th><td>one</td></tr></tbody></table>'
)
BLOCK_DL = (
    "<dl><dt>Mirror</dt><dd><p>A local copy of a site.</p>"
    "<ul><li>pages</li><li>indexes</li></ul></dd></dl>"
)
DETAILS = (
    "<details><summary>Advanced options</summary>"
    "<ul><li>first option</li><li>second option</li></ul></details>"
)
MATH_WITHOUT_TEX = "<math><mi>x</mi><mo>=</mo><mn>2</mn></math>"
ID_ANCHOR = '<p>Keep the <span id="here">note about mirrors</span> in mind.</p>'
# The construct and what its island leaves in the body (UncarryableBecomesIsland).
UNCARRYABLE = {
    "complex-table": (COMPLEX_TABLE, ("<table", 'rowspan="2"')),
    "header-less-table": (HEADERLESS_TABLE, ("<table", "<td>alpha</td>")),
    "row-header-table": (ROW_HEADER_TABLE, ("<table", 'scope="row"')),
    "block-definition-list": (BLOCK_DL, ("<dl>", "<dd>")),
    "details": (DETAILS, ("<details", "\n\n- first option\n- second option\n\n")),
    "math-without-tex": (MATH_WITHOUT_TEX, ("<math",)),
    "id-only-anchor": (ID_ANCHOR, ('<a id="here"></a>',)),
}
FENCE_OPENING = re.compile(r"^`{3,}(?P<info>\S[^\n]*)$", re.MULTILINE)

WEIGHTS = {
    QualityGate.text_coverage: "weight_text_coverage",
    QualityGate.code_blocks: "weight_code_blocks",
    QualityGate.headings: "weight_headings",
    QualityGate.links: "weight_links",
    QualityGate.tables: "weight_tables",
    QualityGate.table_cells: "weight_table_cells",
    QualityGate.code_lang_rate: "weight_code_lang_rate",
    QualityGate.images: "weight_minor",
    QualityGate.list_items: "weight_minor",
    QualityGate.tabs_expanded: "weight_minor",
}
TOLERANCE = 1e-9


def run_pipeline(
    html: str, url: str = SEED
) -> tuple[ExtractedContent, NormalizedContent, str, QualityResult]:
    """extract, normalize, convert, restore and measure under the generic profile."""
    extracted = extract(html, url, profiles.GENERIC)
    normalized = normalize(extracted, profiles.GENERIC)
    body = restore(convert(normalized.fragment), normalized.islands)
    return extracted, normalized, body, measure(extracted, normalized, body)


def pipeline(
    html: str, profile: Profile, url: str = SEED
) -> tuple[ExtractedContent, NormalizedContent, str, QualityResult]:
    """extract, normalize, convert, restore and measure under `profile`."""
    extracted = extract(html, url, profile)
    normalized = normalize(extracted, profile)
    body = restore(convert(normalized.fragment), normalized.islands)
    return extracted, normalized, body, measure(extracted, normalized, body)


def converted_by(html: str, profile: Profile, url: str = SEED) -> ConvertedContent:
    """The whole conversion under `profile`."""
    return converted_content(*pipeline(html, profile, url))


def construct_page(construct: str) -> str:
    """CONSTRUCT_PAGE holding `construct`."""
    return CONSTRUCT_PAGE.format(construct=construct)


def fence_languages(body: str) -> list[str]:
    """The first word of each opening fence's info string, in order."""
    return [match["info"].split()[0] for match in FENCE_OPENING.finditer(body)]


def in_order(text: str, parts: Iterable[str]) -> bool:
    """Every part occurs in `text`, each after the one before."""
    positions = [text.find(part) for part in parts]
    return -1 not in positions and positions == sorted(positions)


def converted(html: str, url: str = SEED) -> ConvertedContent:
    """The whole conversion, as the crawl's ConvertFetched assembles it."""
    extracted, normalized, body, measured = run_pipeline(html, url)
    return converted_content(extracted, normalized, body, measured)


def assert_fields(value: object, names: Iterable[str]) -> None:
    """Every named field or derived value is readable on `value`."""
    for name in names:
        assert hasattr(value, name), name
        getattr(value, name)


def counts(value: ExpectedCounts | OutputMeasurement) -> dict[str, int]:
    """The integer element-class counts of a measurement."""
    return {
        name: getattr(value, name)
        for name in EVERY_CONSTRUCT_EXPECTED
        if name in {field.name for field in dataclasses.fields(value)}
    }


def test_value_equality_VersionMapping() -> None:
    """Verify value type VersionMapping has structural equality."""
    mapped = profiles.MSLEARN.version_map[0]
    assert mapped == VersionMapping(raw=mapped.raw, label=mapped.label)
    assert hash(mapped) == hash(VersionMapping(raw=mapped.raw, label=mapped.label))
    assert mapped != VersionMapping(raw=mapped.raw, label=f"{mapped.label}-other")


def test_entity_fields_VersionMapping() -> None:
    """Verify all declared fields on VersionMapping are present with correct types."""
    assert profiles.MSLEARN.version_map
    for mapping in profiles.MSLEARN.version_map:
        assert isinstance(mapping, VersionMapping)
        assert isinstance(mapping.raw, str)
        assert isinstance(mapping.label, str)
    assert {(m.raw, m.label) for m in profiles.MSLEARN.version_map} >= {("graph-rest-1.0", "v1.0")}


def test_value_equality_ExpectedCounts() -> None:
    """Verify value type ExpectedCounts has structural equality."""
    first = run_pipeline(EVERY_CONSTRUCT)[1].expected
    again = run_pipeline(EVERY_CONSTRUCT)[1].expected
    assert first == again
    assert hash(first) == hash(again)
    assert first != dataclasses.replace(first, tables=first.tables + 1)


def test_entity_fields_ExpectedCounts() -> None:
    """Verify all declared fields on ExpectedCounts are present with correct types."""
    expected = run_pipeline(EVERY_CONSTRUCT)[1].expected
    assert counts(expected) == EVERY_CONSTRUCT_EXPECTED
    assert isinstance(expected.prose_words, tuple)
    assert all(isinstance(word, str) for word in expected.prose_words)
    assert "print" not in expected.prose_words  # words outside code only


def test_value_equality_Island() -> None:
    """Verify value type Island has structural equality."""
    island = Island(payload="<dl><dt>term</dt><dd><p>block</p></dd></dl>", carries_markdown=False)
    assert island == Island(payload=island.payload, carries_markdown=False)
    assert hash(island) == hash(Island(payload=island.payload, carries_markdown=False))
    assert island != Island(payload=island.payload, carries_markdown=True)
    # With no island, restore is the identity: equality is all it has to keep.
    assert restore("# Title\n", ()) == "# Title\n"


def test_entity_fields_Island() -> None:
    """Verify all declared fields on Island are present with correct types."""
    normalized = run_pipeline(EVERY_CONSTRUCT)[1]
    assert isinstance(normalized.islands, tuple)
    for island in normalized.islands:
        assert isinstance(island.payload, str)
        assert isinstance(island.carries_markdown, bool)
    island = Island(payload="<details><summary>More</summary></details>", carries_markdown=True)
    assert_fields(island, ("payload", "carries_markdown"))


def test_value_equality_NormalizedContent() -> None:
    """Verify value type NormalizedContent has structural equality."""
    first = run_pipeline(PAGE)[1]
    again = run_pipeline(PAGE)[1]
    assert first == again
    assert hash(first) == hash(again)
    assert first != run_pipeline(EVERY_CONSTRUCT)[1]


def test_entity_fields_NormalizedContent() -> None:
    """Verify all declared fields on NormalizedContent are present with correct types."""
    normalized = run_pipeline(EVERY_CONSTRUCT)[1]
    assert isinstance(normalized.fragment, str)
    assert "<main" not in normalized.fragment
    assert "Start" not in normalized.fragment  # the navigation is chrome
    assert isinstance(normalized.expected, ExpectedCounts)
    assert normalized.flags == frozenset()
    assert normalized.anchors == frozenset({"code"})
    assert normalized.headings == ("Every construct", "Code", "Table", "List")
    assert normalized.link_targets == (OTHER_PAGE,)
    assert normalized.tab_panels_emitted == 0


def test_value_equality_OutputMeasurement() -> None:
    """Verify value type OutputMeasurement has structural equality."""
    first = run_pipeline(EVERY_CONSTRUCT)[3].output
    again = run_pipeline(EVERY_CONSTRUCT)[3].output
    assert first == again
    assert hash(first) == hash(again)
    assert first != dataclasses.replace(first, images=first.images + 1)


def test_entity_fields_OutputMeasurement() -> None:
    """Verify all declared fields on OutputMeasurement are present with correct types."""
    output = run_pipeline(EVERY_CONSTRUCT)[3].output
    assert counts(output) == {
        k: v for k, v in EVERY_CONSTRUCT_EXPECTED.items() if k != "tab_panels"
    }
    assert all(isinstance(word, str) for word in output.words)
    assert output.code_language_rate == 1
    assert output.text_coverage >= profiles.CONFIG.text_coverage_gate


def test_value_equality_QualityResult() -> None:
    """Verify value type QualityResult has structural equality."""
    first = run_pipeline(PAGE)[3]
    again = run_pipeline(PAGE)[3]
    assert first == again
    assert hash(first) == hash(again)
    assert first != dataclasses.replace(first, low_confidence=not first.low_confidence)


def test_entity_fields_QualityResult() -> None:
    """Verify all declared fields on QualityResult are present with correct types."""
    quality = run_pipeline(EVERY_CONSTRUCT)[3]
    assert_fields(
        quality,
        (
            "expected",
            "output",
            "tab_panels_emitted",
            "failed",
            "score",
            "flags",
            "low_confidence",
        ),
    )
    passes = (
        quality.text_coverage_passes,
        quality.code_blocks_passes,
        quality.code_lang_rate_passes,
        quality.tables_passes,
        quality.table_cells_passes,
        quality.headings_passes,
        quality.links_passes,
        quality.images_passes,
        quality.list_items_passes,
        quality.tabs_expanded_passes,
    )
    assert all(passes)
    assert quality.all_gates_pass
    assert not quality.has_incomplete_flag
    assert quality.failed == frozenset()
    assert quality.score == 1
    assert not quality.low_confidence


def test_value_equality_ExtractedContent() -> None:
    """Verify value type ExtractedContent has structural equality."""
    first = extract(PAGE, SEED, profiles.GENERIC)
    again = extract(PAGE, SEED, profiles.GENERIC)
    assert first == again
    assert hash(first) == hash(again)
    assert first != extract(NO_MAIN, SEED, profiles.GENERIC)


def test_entity_fields_ExtractedContent() -> None:
    """Verify all declared fields on ExtractedContent are present with correct types."""
    extracted = extract(PAGE, SEED, profiles.GENERIC)
    assert isinstance(extracted.html, str)
    assert "Example docs" not in extracted.html  # the header is outside the content
    assert extracted.title == PAGE_HEADINGS[0]  # the first h1 beats <title>
    assert extracted.description == PAGE_DESCRIPTION
    assert extracted.canonical_url is None
    assert extracted.declared_locale == "en"
    assert extracted.breadcrumbs == ()
    assert extracted.navigation_targets == ()
    assert extracted.method is ExtractionMethod.profile
    assert extracted.has_text
    assert profiles.CONFIG.extracted_share_gate <= extracted.extracted_share <= 1


def test_value_equality_ConvertedContent() -> None:
    """Verify value type ConvertedContent has structural equality."""
    first = converted(PAGE)
    again = converted(PAGE)
    assert first == again
    assert hash(first) == hash(again)
    assert first != dataclasses.replace(first, body=first.body + "\n")


def test_entity_fields_ConvertedContent() -> None:
    """Verify all declared fields on ConvertedContent are present with correct types."""
    content = converted(EVERY_CONSTRUCT)
    assert content.body.startswith("# Every construct\n")
    assert f"]({OTHER_PAGE})" in content.body  # links stay absolute for the mirror
    assert content.title == "Every construct"
    assert isinstance(content.description, str)
    assert content.description
    assert content.canonical_url is None
    assert content.declared_locale == "en"
    assert content.breadcrumbs == ()
    assert content.navigation_targets == (SEED,)
    assert content.method is ExtractionMethod.profile
    assert content.anchors == frozenset({"code"})
    assert content.headings == ("Every construct", "Code", "Table", "List")
    assert content.link_targets == (OTHER_PAGE,)
    assert isinstance(content.quality, QualityResult)
    assert content.is_empty is False


def test_contract_signature_Fidelity_extract() -> None:
    """Verify implementation satisfies contract Fidelity.extract.

    extract: (html: String, url: String, profile: Profile) -> ExtractedContent, and
    ExtractNeverEmptyHanded: the generic selection finds `main`, else `article`, else the
    fallback extractor runs, else the body. Re-propagated by T17: devsite selects the
    DevSite article body and its breadcrumbs, mslearn the Learn article content, each
    without its chrome. Re-propagated by the T17 follow-up (spec 022eca4): markup a
    profile's selection does not match goes to trafilatura (method fallback), and only a
    page it finds nothing in is extracted whole.
    """
    assert list(inspect.signature(extract).parameters) == ["html", "url", "profile"]
    by_profile = extract(PAGE, SEED, profiles.GENERIC)
    assert isinstance(by_profile, ExtractedContent)
    assert by_profile.method is ExtractionMethod.profile

    article = PAGE.replace("<main>", "<article>").replace("</main>", "</article>")
    assert extract(article, SEED, profiles.GENERIC).method is ExtractionMethod.profile

    fallback = extract(NO_MAIN, SEED, profiles.GENERIC)
    assert fallback.method is ExtractionMethod.fallback
    assert fallback.has_text
    assert fallback.title == "Loose page"
    # No meta description: the first prose paragraph of what the fallback extractor kept
    # (its own choice of paragraphs), cut at description_max_chars.
    assert "A page whose content sits directly" in fallback.description
    assert len(fallback.description) <= profiles.CONFIG.description_max_chars

    whole = extract(IMAGE_ONLY, SEED, profiles.GENERIC)
    assert whole.method is ExtractionMethod.whole_body
    assert whole.title == "Picture page"
    assert 'src="http://docs.example/a.png"' in whole.html

    declared = PAGE.replace(
        "<meta charset", '<link rel="canonical" href="/guide/topic.html">\n    <meta charset'
    ).replace("<header>", '<nav><a href="/guide/a.html">A</a></nav><header>')
    page = extract(declared, SEED, profiles.GENERIC)
    assert page.canonical_url == "http://docs.example/guide/topic.html"
    assert page.navigation_targets == ("http://docs.example/guide/a.html",)

    devsite = extract(TABS_PAGE, SEED, profiles.DEVSITE)
    assert devsite.method is ExtractionMethod.profile
    assert devsite.title == "Tabs"
    assert devsite.breadcrumbs == ("Guides", "Tabs")
    for chrome in (*DEVSITE_CHROME, "Guides"):
        assert chrome not in devsite.html, chrome
    assert "pip install example-client" in devsite.html

    learn = extract(MSLEARN_PAGE, LEARN_URL, profiles.MSLEARN)
    assert learn.method is ExtractionMethod.profile
    assert learn.title == "Create user"
    assert learn.declared_locale == "en-us"
    for chrome in LEARN_CHROME:
        assert chrome not in learn.html, chrome
    assert "var user = new User();" in learn.html

    assert extract(PAGE, SEED, profiles.DEVSITE).method is ExtractionMethod.fallback
    assert extract(PAGE, SEED, profiles.MSLEARN).method is ExtractionMethod.fallback


def test_contract_signature_Fidelity_normalize() -> None:
    """Verify implementation satisfies contract Fidelity.normalize.

    normalize: (content: ExtractedContent, profile: Profile) -> NormalizedContent, with
    ExpectedCounts over the normalised tree (ExpectedAgainstSurvived). Re-propagated by
    T17: each uncarryable construct becomes an island and a token in the fragment, its
    elements counted in the expected counts; a table kept as HTML is flagged; under a
    profile with a tab selection every panel is counted and emitted, and the generic
    profile, which has none, counts no panel.
    """
    assert list(inspect.signature(normalize).parameters) == ["content", "profile"]
    normalized = normalize(extract(PAGE, SEED, profiles.GENERIC), profiles.GENERIC)
    assert isinstance(normalized, NormalizedContent)
    assert normalized.islands == ()
    assert normalized.headings == PAGE_HEADINGS
    assert normalized.link_targets == ()
    assert normalized.expected.headings == len(PAGE_HEADINGS)
    assert normalized.expected.links == 0
    assert "offline" in normalized.expected.prose_words

    islanded = normalize(extract(ISLANDS_PAGE, SEED, profiles.GENERIC), profiles.GENERIC)
    payloads = [island.payload for island in islanded.islands]
    assert sum("<table" in payload for payload in payloads) == len(("spanning", "header-less"))
    assert any('rowspan="2"' in payload for payload in payloads)
    assert any("<dl" in payload for payload in payloads)
    assert any("<math" in payload for payload in payloads)
    assert any('<a id="note"></a>' in payload for payload in payloads)
    (details,) = [island for island in islanded.islands if "<details" in island.payload]
    assert details.carries_markdown
    for construct in ("<table", "<dl", "<math", "<details"):
        assert construct not in islanded.fragment, construct
    assert QualityFlag.html_table_kept in islanded.flags
    assert "note" in islanded.anchors
    # Counted over the tree plus every island: 5 and 4 table cells, the list items of the
    # definition and of details, the h1 and the six h2.
    assert islanded.expected.tables == 2  # noqa: PLR2004  The islands page's two tables.
    assert islanded.expected.table_cells == 9  # noqa: PLR2004  Its 5 + 4 cells.
    assert islanded.expected.list_items == 4  # noqa: PLR2004  Two in dd, two in details.
    assert islanded.expected.headings == 7  # noqa: PLR2004  The h1 and six h2.
    assert islanded.expected.tab_panels == 0

    tabs = normalize(extract(TABS_PAGE, SEED, profiles.DEVSITE), profiles.DEVSITE)
    assert tabs.expected.tab_panels == 5  # noqa: PLR2004  Three code panels, two prose.
    assert tabs.tab_panels_emitted == tabs.expected.tab_panels
    learn = normalize(extract(MSLEARN_PAGE, LEARN_URL, profiles.MSLEARN), profiles.MSLEARN)
    assert learn.expected.tab_panels == 2  # noqa: PLR2004  HTTP and C#.
    assert learn.tab_panels_emitted == learn.expected.tab_panels
    plain = normalize(extract(TABS_PAGE, SEED, profiles.GENERIC), profiles.GENERIC)
    assert plain.expected.tab_panels == 0
    assert plain.tab_panels_emitted == 0


def test_contract_signature_Fidelity_convert() -> None:
    """Verify implementation satisfies contract Fidelity.convert.

    convert: (fragment: String) -> String, writing ATX headings.
    """
    assert list(inspect.signature(convert).parameters) == ["fragment"]
    markdown = convert("<h2>Install the product</h2><p>Run it once.</p>")
    assert isinstance(markdown, str)
    assert "## Install the product" in markdown
    assert "Run it once." in markdown


def test_contract_signature_Fidelity_restore() -> None:
    """Verify implementation satisfies contract Fidelity.restore.

    restore: (markdown: String, islands: List<Island>) -> String; with no island it is
    the identity. Re-propagated by T17: each island's token gives way to its payload, and
    a token the converter lost leaves its island out.
    """
    assert list(inspect.signature(restore).parameters) == ["markdown", "islands"]
    _, normalized, body, _ = run_pipeline(PAGE)
    assert normalized.islands == ()
    markdown = convert(normalized.fragment)
    assert restore(markdown, ()) == markdown
    assert isinstance(body, str)

    _, islanded, _, _ = pipeline(ISLANDS_PAGE, profiles.GENERIC)
    tokened = convert(islanded.fragment)
    restored = restore(tokened, islanded.islands)
    assert islanded.islands
    for island in islanded.islands:
        assert island.payload not in tokened
        assert island.payload in restored

    _, single, _, _ = pipeline(construct_page(HEADERLESS_TABLE), profiles.GENERIC)
    (island,) = single.islands
    tokened = convert(single.fragment)
    (token_line,) = [
        line
        for line in tokened.splitlines()
        if line and line not in restore(tokened, single.islands)
    ]
    lost = tokened.replace(f"{token_line}\n", "", 1)
    assert island.payload not in restore(lost, single.islands)


def test_contract_signature_Fidelity_measure() -> None:
    """Verify implementation satisfies contract Fidelity.measure.

    measure: (content, normalized, body) -> QualityResult. Every element class is counted
    on the body and compared with the expected counts; a lost construct fails its gate,
    the score is the weighted share of passed gates, and the whole-body method flags.
    Re-propagated by the T17 follow-up (spec 022eca4): the fallback method flags
    extractor_fallback; the whole body is IMAGE_ONLY's, which trafilatura finds nothing in.
    """
    assert list(inspect.signature(measure).parameters) == ["content", "normalized", "body"]
    extracted, normalized, body, quality = run_pipeline(EVERY_CONSTRUCT)
    expected = counts(normalized.expected)
    del expected["tab_panels"]
    assert counts(quality.output) == expected
    assert quality.failed == frozenset()
    assert quality.score == 1

    # Drop the pipe table from the body: the table gates must fire.
    lines = body.splitlines(keepends=True)
    without_table = "".join(line for line in lines if not line.lstrip().startswith("|"))
    lossy = measure(extracted, normalized, without_table)
    assert {QualityGate.tables, QualityGate.table_cells} <= lossy.failed
    assert {QualityFlag.tables, QualityFlag.table_cells} <= lossy.flags
    assert lossy.low_confidence
    assert not lossy.all_gates_pass
    lost = sum(getattr(profiles.CONFIG, WEIGHTS[gate]) for gate in lossy.failed)
    assert abs(lossy.score - (1 - lost)) < TOLERANCE

    whole = run_pipeline(IMAGE_ONLY)[3]
    assert QualityFlag.whole_body_extracted in whole.flags
    assert whole.low_confidence
    fallback = run_pipeline(NO_MAIN)[3]
    assert QualityFlag.extractor_fallback in fallback.flags
    assert QualityFlag.whole_body_extracted not in fallback.flags
    assert fallback.low_confidence

    # T17: the normalisation flags, and fidelity_loss for an island whose payload is not
    # in the body or whose token survives in it. html_table_kept alone is no failure.
    islands = pipeline(ISLANDS_PAGE, profiles.GENERIC)[3]
    assert QualityFlag.html_table_kept in islands.flags
    assert QualityFlag.fidelity_loss not in islands.flags
    assert islands.failed == frozenset()
    assert not islands.low_confidence
    gates = pipeline(GATES_PAGE, profiles.GENERIC)[3]
    assert QualityFlag.interactive_omitted in gates.flags
    assert gates.failed == frozenset({QualityGate.code_lang_rate})

    extracted, single, body, _ = pipeline(construct_page(HEADERLESS_TABLE), profiles.GENERIC)
    (island,) = single.islands
    assert QualityFlag.fidelity_loss not in measure(extracted, single, body).flags
    without_payload = body.replace(island.payload, "", 1)
    assert QualityFlag.fidelity_loss in measure(extracted, single, without_payload).flags
    tokened = convert(single.fragment)
    assert QualityFlag.fidelity_loss in measure(extracted, single, tokened).flags


def test_body_shape() -> None:
    """BodyShape (convert.allium 249): LF, one blank line, one h1, ids as {#id}, one final LF.

    Re-propagated by T17: every source id is kept as an anchor, a non-heading id as an
    anchor island before its element's content, and under the inline anchor style a
    heading's id is the same anchor island before the heading.
    """
    extra_h1 = EVERY_CONSTRUCT.replace("<h2>List</h2>", "<h1>List</h1>")
    no_h1 = PAGE.replace("<h1>Getting started</h1>", "")
    # With no h1 in the content, the title falls back to <title>, and the h1 is made from it.
    for html, title in ((extra_h1, "Every construct"), (no_h1, "Getting started | Example docs")):
        body = converted(html).body
        h1_lines = [line for line in body.splitlines() if line.startswith("# ")]
        assert h1_lines == [f"# {title}"]
        assert "\r" not in body
        assert "\n\n\n" not in body
        assert body.endswith("\n")
        assert not body.endswith("\n\n")
    assert "## Code {#code}" in converted(EVERY_CONSTRUCT).body

    anchored = converted(ISLANDS_PAGE)
    assert '<a id="note"></a>' in anchored.body
    assert "note" in anchored.anchors

    inline = dataclasses.replace(profiles.GENERIC, heading_anchor_style=HeadingAnchorStyle.inline)
    styled = converted_by(PAGE.replace("<h2>", '<h2 id="install">'), inline).body
    assert in_order(styled, ('<a id="install"></a>', "## Install the product"))
    assert "{#install}" not in styled
    assert "\n\n\n" not in styled


def test_fetch_flags_recompute_low_confidence() -> None:
    """with_fetch_flags adds the fetch flags and recomputes low_confidence (crawl.allium 1917)."""
    content = converted(PAGE)
    assert not content.quality.low_confidence
    flagged = with_fetch_flags(content, {QualityFlag.render_needed})
    assert QualityFlag.render_needed in flagged.quality.flags
    assert flagged.quality.low_confidence
    assert with_fetch_flags(content, ()) == content


def test_enum_comparable_QualityGate() -> None:
    """Verify fields typed with enum QualityGate are comparable."""
    assert tuple(gate.name for gate in QualityGate) == spec_enum("convert", "QualityGate")
    assert {gate.name for gate in QualityGate} <= {flag.name for flag in QualityFlag}
    assert QualityGate.links == QualityGate("links")
    gate: object = QualityGate.links
    assert gate != QualityFlag.links
    extracted, normalized, _, _ = run_pipeline(EVERY_CONSTRUCT)
    assert QualityGate.tables in measure(extracted, normalized, "# Every construct\n").failed


def test_enum_comparable_QualityFlag() -> None:
    """Verify fields typed with enum QualityFlag are comparable."""
    assert tuple(flag.name for flag in QualityFlag) == spec_enum("convert", "QualityFlag")
    assert QualityFlag.render_needed == QualityFlag("render_needed")
    assert QualityFlag.render_needed in profiles.CONFIG.incomplete_flags
    # Re-propagated by the T17 follow-up: NO_MAIN now goes to the fallback extractor.
    assert run_pipeline(IMAGE_ONLY)[3].flags >= {QualityFlag.whole_body_extracted}
    assert run_pipeline(NO_MAIN)[3].flags >= {QualityFlag.extractor_fallback}


def test_enum_comparable_ExtractionMethod() -> None:
    """Verify fields typed with enum ExtractionMethod are comparable."""
    names = tuple(method.name for method in ExtractionMethod)
    assert names == spec_enum("convert", "ExtractionMethod")
    by_profile = extract(PAGE, SEED, profiles.GENERIC).method
    whole = extract(NO_MAIN, SEED, profiles.GENERIC).method
    assert by_profile == ExtractionMethod.profile
    assert by_profile != whole


def test_enum_comparable_HeadingAnchorStyle() -> None:
    """Verify fields typed with enum HeadingAnchorStyle are comparable."""
    names = tuple(style.name for style in HeadingAnchorStyle)
    assert names == spec_enum("convert", "HeadingAnchorStyle")
    assert {p.heading_anchor_style for p in profiles.CATALOGUE} == {HeadingAnchorStyle.attr}
    assert len(set(HeadingAnchorStyle)) == len(spec_enum("convert", "HeadingAnchorStyle"))


def test_entity_fields_Profile() -> None:
    """Verify all declared fields on Profile are present with correct types."""
    assert profiles.CATALOGUE
    for profile in profiles.CATALOGUE:
        assert isinstance(profile, Profile)
        assert isinstance(profile.name, str)
        assert isinstance(profile.hosts, frozenset)
        assert isinstance(profile.content_selection, str)
        assert isinstance(profile.meaningful_query_params, tuple)
        assert isinstance(profile.sitemap_include, tuple)
        assert profile.version_param is None or isinstance(profile.version_param, str)
        assert all(isinstance(m, VersionMapping) for m in profile.version_map)
        assert profile.version_default is None or isinstance(profile.version_default, str)
        assert isinstance(profile.locale_codes, frozenset)
        assert isinstance(profile.heading_anchor_style, HeadingAnchorStyle)
        assert isinstance(profile.has_versions, bool)
    assert profiles.GENERIC.name == "generic"
    assert profiles.GENERIC.hosts == frozenset()
    assert profiles.MSLEARN.hosts == frozenset({"learn.microsoft.com"})
    assert profiles.DEVSITE.hosts == frozenset({"developers.google.com"})


def test_entity_optional_Profile_version_param() -> None:
    """Verify optional field Profile.version_param accepts null and non-null values."""
    assert profiles.GENERIC.version_param is None
    assert profiles.MSLEARN.version_param == "view"
    assert dataclasses.replace(profiles.GENERIC, version_param="v").version_param == "v"


def test_entity_optional_Profile_version_default() -> None:
    """Verify optional field Profile.version_default accepts null and non-null values."""
    assert profiles.GENERIC.version_default is None
    assert profiles.MSLEARN.version_default == "v1.0"
    assert dataclasses.replace(profiles.MSLEARN, version_default=None).version_default is None


def test_derived_Profile_has_versions() -> None:
    """Verify derived value Profile.has_versions computes correctly."""
    assert profiles.MSLEARN.has_versions
    assert not profiles.GENERIC.has_versions
    assert not profiles.DEVSITE.has_versions
    assert not dataclasses.replace(profiles.MSLEARN, version_param=None).has_versions


def test_config_default_text_coverage_gate() -> None:
    """Verify config parameter text_coverage_gate has its declared default."""
    assert profiles.CONFIG.text_coverage_gate == spec_float("convert", "text_coverage_gate")


def test_config_default_ratio_gate() -> None:
    """Verify config parameter ratio_gate has its declared default."""
    assert profiles.CONFIG.ratio_gate == spec_float("convert", "ratio_gate")


def test_config_default_lang_rate_gate() -> None:
    """Verify config parameter lang_rate_gate has its declared default."""
    assert profiles.CONFIG.lang_rate_gate == spec_float("convert", "lang_rate_gate")


def test_config_default_extracted_share_gate() -> None:
    """Verify config parameter extracted_share_gate has its declared default."""
    assert profiles.CONFIG.extracted_share_gate == spec_float("convert", "extracted_share_gate")


def test_config_default_weight_text_coverage() -> None:
    """Verify config parameter weight_text_coverage has its declared default."""
    assert profiles.CONFIG.weight_text_coverage == spec_float("convert", "weight_text_coverage")


def test_config_default_weight_code_blocks() -> None:
    """Verify config parameter weight_code_blocks has its declared default."""
    assert profiles.CONFIG.weight_code_blocks == spec_float("convert", "weight_code_blocks")


def test_config_default_weight_headings() -> None:
    """Verify config parameter weight_headings has its declared default."""
    assert profiles.CONFIG.weight_headings == spec_float("convert", "weight_headings")


def test_config_default_weight_links() -> None:
    """Verify config parameter weight_links has its declared default."""
    assert profiles.CONFIG.weight_links == spec_float("convert", "weight_links")


def test_config_default_weight_tables() -> None:
    """Verify config parameter weight_tables has its declared default."""
    assert profiles.CONFIG.weight_tables == spec_float("convert", "weight_tables")


def test_config_default_weight_table_cells() -> None:
    """Verify config parameter weight_table_cells has its declared default."""
    assert profiles.CONFIG.weight_table_cells == spec_float("convert", "weight_table_cells")


def test_config_default_weight_code_lang_rate() -> None:
    """Verify config parameter weight_code_lang_rate has its declared default."""
    expected = spec_float("convert", "weight_code_lang_rate")
    assert profiles.CONFIG.weight_code_lang_rate == expected


def test_config_default_weight_minor() -> None:
    """Verify config parameter weight_minor has its declared default.

    The weights sum to one (ScoreIsAFraction).
    """
    assert abs(profiles.CONFIG.weight_minor - spec_float("convert", "weight_minor")) < TOLERANCE
    total = sum(getattr(profiles.CONFIG, name) for name in WEIGHTS.values())
    assert abs(total - 1) < TOLERANCE


def test_config_default_incomplete_flags() -> None:
    """Verify config parameter incomplete_flags has its declared default."""
    names = {flag.name for flag in profiles.CONFIG.incomplete_flags}
    assert names == spec_names("convert", "incomplete_flags")


def test_config_default_description_max_chars() -> None:
    """Verify config parameter description_max_chars has its declared default."""
    expected = spec_int("convert", "description_max_chars")
    assert profiles.CONFIG.description_max_chars == expected


def test_invariant_ProfileNamesAreUnique() -> None:
    """Verify invariant ProfileNamesAreUnique holds after every state-changing rule that touches constrained entities."""  # noqa: E501  The obligation's description, quoted.
    names = [profile.name for profile in profiles.CATALOGUE]
    assert len(names) == len(set(names))
    assert set(names) == {"generic", "mslearn", "devsite"}
    for name in names:
        named = profiles.profile_named(name)
        assert named is not None
        assert named.name == name
    assert profiles.profile_named("no-such-profile") is None


def test_invariant_VersionedProfilesMapVersions() -> None:
    """Verify invariant VersionedProfilesMapVersions holds after every state-changing rule that touches constrained entities."""  # noqa: E501  The obligation's description, quoted.
    for profile in profiles.CATALOGUE:
        assert not profile.has_versions or len(profile.version_map) > 0
    assert any(profile.has_versions for profile in profiles.CATALOGUE)


def test_surface_actor_PageConversion() -> None:
    """Verify surface PageConversion is accessible only to the specified actor.

    The surface faces a Profile: every catalogue profile drives the Fidelity operations,
    and none branches on a hostname (ProfilesAreTheOnlyPlatformKnowledge).
    """
    for profile in profiles.CATALOGUE:
        extracted = extract(PAGE, SEED, profile)
        normalized = normalize(extracted, profile)
        assert isinstance(normalized, NormalizedContent)
    assert profiles.profile_for(SEED, None) == profiles.GENERIC
    assert profiles.profile_for("https://learn.microsoft.com/en-us/graph/", None) == (
        profiles.MSLEARN
    )
    assert profiles.profile_for(SEED, "devsite") == profiles.DEVSITE
    assert profiles.profile_for(SEED, "no-such-profile") is None


def test_surface_exposure_PageConversion() -> None:
    """Verify each exposed item on PageConversion is accessible."""
    exposed = (
        "name",
        "hosts",
        "content_selection",
        "meaningful_query_params",
        "sitemap_include",
        "version_param",
        "version_map",
        "version_default",
        "locale_codes",
        "heading_anchor_style",
        "has_versions",
    )
    for profile in profiles.CATALOGUE:
        assert_fields(profile, exposed)
    # T17: each catalogue profile's content selection matches the markup of its platform.
    shaped = {
        profiles.GENERIC: (PAGE, SEED),
        profiles.DEVSITE: (TABS_PAGE, GOOGLE_URL),
        profiles.MSLEARN: (MSLEARN_PAGE, LEARN_URL),
    }
    assert set(shaped) == set(profiles.CATALOGUE)
    for profile, (html, url) in shaped.items():
        assert extract(html, url, profile).method is ExtractionMethod.profile, profile.name


def test_map_destinations_rewrites_only_destinations_outside_code() -> None:
    """map_destinations (T10): identity returns the body byte for byte; code is untouched.

    link_destinations, rebuilt on it, lists the same destinations as before.
    """
    body = (
        "# Links\n"
        "\n"
        "See [b](http://docs.example/guide/b.html#x), <http://docs.example/guide/c.html> and\n"
        "![a picture](http://docs.example/guide/p.png).\n"
        "\n"
        "Inline `[b](http://docs.example/guide/b.html)` stays.\n"
        "\n"
        "```markdown\n"
        "[b](http://docs.example/guide/b.html)\n"
        "```\n"
    )
    assert map_destinations(body, lambda target: target) == body
    rewritten = map_destinations(body, lambda target: target.replace(".html", ".md"))
    assert "[b](http://docs.example/guide/b.md#x)" in rewritten
    assert "Inline `[b](http://docs.example/guide/b.html)` stays.\n" in rewritten
    assert "```markdown\n[b](http://docs.example/guide/b.html)\n```\n" in rewritten
    assert "![a picture](http://docs.example/guide/p.png)" in rewritten
    assert link_destinations(body) == (
        "http://docs.example/guide/b.html#x",
        "http://docs.example/guide/c.html",
    )


# --- T17: the gates, the islands, the tab panels and the reductions -----------------------

# Each gate failing alone: an edit of the EVERY_CONSTRUCT body that loses one construct
# class and keeps every other count and every expected word.
GATE_ALONE = {
    QualityGate.text_coverage: ("Prose with a ", ""),
    QualityGate.code_blocks: ('```python\nprint("hello")\n```\n\n', ""),
    QualityGate.code_lang_rate: ("```python\n", "```\n"),
    QualityGate.tables: (
        "| --- | --- |\n| alpha | one |",
        "| --- | --- |\n\n| alpha | one |\n| --- | --- |",
    ),
    QualityGate.table_cells: ("| alpha | one |", "| alpha | one | |"),
    QualityGate.headings: ("## List\n", "List\n"),
    QualityGate.links: (
        "[link to another page](http://docs.example/guide/other.html)",
        "link to another page",
    ),
    QualityGate.images: ("![A diagram](http://docs.example/img/diagram.png)\n", "A diagram\n"),
    QualityGate.list_items: ("- second item", "second item"),
}


@pytest.mark.parametrize("gate", list(QualityGate), ids=lambda gate: gate.value)
def test_each_gate_failing_alone_is_flagged(gate: QualityGate) -> None:
    """FailedGatesAreFlagged and ScoreIsAFraction, one gate at a time.

    The gate fails, its flag is raised, the score is one minus its weight and the page is
    low confidence. tabs_expanded cannot fail by construction (convert.allium's first
    open question, still open), so it fails here on a constructed NormalizedContent.
    """
    extracted, normalized, body, quality = run_pipeline(EVERY_CONSTRUCT)
    assert quality.failed == frozenset()
    if gate is QualityGate.tabs_expanded:
        normalized = dataclasses.replace(normalized, tab_panels_emitted=1)
    else:
        old, new = GATE_ALONE[gate]
        assert old in body, gate
        body = body.replace(old, new, 1)
    result = measure(extracted, normalized, body)
    assert result.failed == frozenset({gate})
    assert QualityFlag[gate.value] in result.flags
    weight = getattr(profiles.CONFIG, WEIGHTS[gate])
    assert abs(result.score - (1 - weight)) < TOLERANCE
    assert 0 <= result.score < 1
    assert result.low_confidence


@pytest.mark.parametrize("name", list(UNCARRYABLE))
def test_UncarryableBecomesIsland(name: str) -> None:
    """Each construct Markdown cannot carry reaches the body as an island.

    A complex, header-less or row-header table, a block definition list, details, math
    without TeX and an id-only anchor: cut out as an island, restored after conversion,
    counted on both sides, so every gate passes and nothing is lost.
    """
    construct, markers = UNCARRYABLE[name]
    extracted, normalized, body, quality = pipeline(construct_page(construct), profiles.GENERIC)
    assert normalized.islands
    for marker in markers:
        assert marker in body, (marker, body)
    assert QualityFlag.fidelity_loss not in quality.flags
    assert quality.failed == frozenset()
    assert not quality.low_confidence
    assert extracted.method is ExtractionMethod.profile


def test_SanitizedMeansInert() -> None:
    """One definition of sanitised: what an HTML island keeps and what it drops."""
    table = (
        "<table><thead><tr>"
        '<th scope="col" class="c" data-x="1">Name</th>'
        '<th colspan="2" style="color: red">Values</th>'
        "</tr></thead><tbody><tr>"
        '<td rowspan="2" id="cell" onclick="track()">'
        '<a href="javascript:alert(1)">bad link</a> '
        '<a href="vbscript:msgbox(1)">old link</a> '
        '<a href="data:text/html,hi">data link</a> '
        '<a href="http://docs.example/ok.html" title="Ok">good link</a></td>'
        '<td><img src="data:image/png;base64,AAAA" alt="dot"></td>'
        "<td>value<script>alert(2)</script><style>td { color: red }</style></td>"
        "</tr><tr><td>two</td><td>three</td></tr></tbody></table>"
    )
    normalized = pipeline(construct_page(table), profiles.GENERIC)[1]
    (island,) = normalized.islands
    payload = island.payload
    assert not island.carries_markdown
    kept = (
        'scope="col"',
        'colspan="2"',
        'rowspan="2"',
        'id="cell"',
        'href="http://docs.example/ok.html"',
        'title="Ok"',
        'src="data:image/png;base64,AAAA"',
        'alt="dot"',
    )
    for attribute in kept:
        assert attribute in payload, attribute
    dropped = ("class=", "data-x", "style=", "onclick", "javascript:", "vbscript:", "data:text")
    for attribute in dropped:
        assert attribute not in payload, attribute
    assert "<script" not in payload
    assert "<style" not in payload
    for text in ("bad link", "old link", "data link", "good link", "value", "two", "three"):
        assert text in payload, text
    assert "\n\n" not in payload.strip()

    details = pipeline(construct_page(DETAILS), profiles.GENERIC)[1]
    (shell,) = details.islands
    assert shell.carries_markdown
    assert "\n\n- first option\n- second option\n\n" in shell.payload


def test_EveryTabPanelEmitted() -> None:
    """Every panel of a tab group reaches the body in source order, inactive ones too.

    A group whose every panel is one code sample in a named language becomes labelled
    fences; any other group a heading one level below its context plus the panel.
    """
    body = converted_by(TABS_PAGE, profiles.DEVSITE).body
    assert fence_languages(body)[:3] == ["python", "java", "shell"]
    assert in_order(
        body,
        (
            "pip install example-client",
            'implementation "com.example:client:1.0"',
            "curl -O https://example.invalid/client.tar.gz",
        ),
    )
    for label in ("Python", "Java", "Shell"):
        assert label in body, label
    assert in_order(
        body,
        ("### Linux", "On Linux, write", "### Windows", "On Windows, write"),
    )
    assert in_order(body, ("## Install the client", "pip install", "## Configure the client"))

    learn = converted_by(MSLEARN_PAGE, profiles.MSLEARN, LEARN_URL).body
    assert fence_languages(learn) == ["http", "csharp"]
    assert in_order(
        learn, ("POST https://graph.microsoft.com/v1.0/users", "var user = new User();")
    )
    for label in ("HTTP", "C#"):
        assert label in learn, label


REDUCTIONS = {
    "interactive-embed": (
        '<iframe src="https://example.invalid/demo" title="Demo"></iframe>',
        ("https://example.invalid/demo",),
        ("<iframe",),
    ),
    "link-inside-code": (
        '<pre><code class="language-text">see <a href="http://docs.example/x.html">x</a></code></pre>',
        ("see x",),
        ("http://docs.example/x.html",),
    ),
    "line-number-gutter": (
        (
            '<pre><code class="language-python"><span class="linenos">1</span>print("a")\n'
            '<span class="linenos">2</span>print("b")</code></pre>'
        ),
        ('print("a")\nprint("b")',),
        ('1print("a")', '2print("b")'),
    ),
    "form-controls": (
        '<form><input type="text" name="q"><button type="submit">Search the docs</button></form>',
        ("Search the docs",),
        ("<input", "<button", "<form"),
    ),
    "layout-table": (
        (
            '<table role="presentation"><tr><td><p>Left column text.</p></td>'
            "<td><p>Right column text.</p></td></tr></table>"
        ),
        ("Left column text.", "Right column text."),
        ("<table", "| Left"),
    ),
    "footnote-back-links": (
        (
            '<p>A claim<sup id="fnref1"><a href="#fn1" class="footnote-ref">1</a></sup>.</p>'
            '<section class="footnotes"><ol><li id="fn1"><p>The source. '
            '<a href="#fnref1" class="footnote-backref">↩</a></p></li></ol></section>'
        ),
        ("[^1]", "[^1]: The source."),
        ("↩", "#fnref1"),
    ),
    "image-attributes": (
        (
            '<table><tr><td rowspan="2"><img src="http://docs.example/p.png" alt="P" title="T" '
            'id="pic" class="x" width="10" loading="lazy"></td><td>a</td></tr>'
            "<tr><td>b</td></tr></table>"
        ),
        ('src="http://docs.example/p.png"', 'alt="P"', 'title="T"', 'id="pic"'),
        ('class="x"', "width=", "loading="),
    ),
    # Re-propagated by the T17 follow-up (convert.allium 223 to 235 at 022eca4): the union,
    # the sanitiser's attributes plus class and the tab-language attributes.
    "custom-element-attributes": (
        (
            '<table><tr><td rowspan="2"><my-widget id="w" class="tabs" data-tab="py" '
            'data-language="python" language="python" title="Widget" data-extra="z" '
            'onclick="go()" style="color: red">widget text</my-widget></td><td>a</td></tr>'
            "<tr><td>b</td></tr></table>"
        ),
        (
            'id="w"',
            'class="tabs"',
            'data-tab="py"',
            'data-language="python"',
            'language="python"',
            'title="Widget"',
            "widget text",
        ),
        ("data-extra", "onclick", "style="),
    ),
}


@pytest.mark.parametrize("name", list(REDUCTIONS))
def test_DeclaredReductions(name: str) -> None:
    """The reductions normalisation makes on purpose, one case each.

    What the reduction keeps is in the body and what it removes is not; only the
    interactive embed is flagged (interactive_omitted), and none is a fidelity_loss.
    """
    construct, present, absent = REDUCTIONS[name]
    content = converted(construct_page(construct))
    for text in present:
        assert text in content.body, (text, content.body)
    for text in absent:
        assert text not in content.body, (text, content.body)
    assert (QualityFlag.interactive_omitted in content.quality.flags) is (
        name == "interactive-embed"
    )
    assert QualityFlag.fidelity_loss not in content.quality.flags


def test_construct_families_reach_the_body() -> None:
    """The guidance's families: callouts as GFM alerts, inline HTML kept, TeX, footnotes.

    sup, sub, kbd and mark stay inline HTML; math with a TeX annotation becomes TeX
    between delimiters; an inline definition list becomes bold term lines.
    """
    inline = converted(
        construct_page(
            "<p>Water is H<sub>2</sub>O, energy is mc<sup>2</sup>, press <kbd>Ctrl</kbd> "
            "and read the <mark>marked</mark> word.</p>"
        )
    ).body
    for kept in ("<sub>2</sub>", "<sup>2</sup>", "<kbd>Ctrl</kbd>", "<mark>marked</mark>"):
        assert kept in inline, kept
    tex = converted(
        construct_page(
            "<p>The value is "
            '<math><semantics><mi>x</mi><annotation encoding="application/x-tex">x = 2'
            "</annotation></semantics></math> here.</p>"
        )
    )
    assert re.search(r"\$+\s*x = 2\s*\$+", tex.body), tex.body
    assert "<math" not in tex.body
    assert not tex.quality.flags & {QualityFlag.fidelity_loss}
    terms = converted(construct_page("<dl><dt>Mirror</dt><dd>A local copy.</dd></dl>")).body
    assert "**Mirror**" in terms
    assert "<dl" not in terms

    devsite = converted_by(TABS_PAGE, profiles.DEVSITE).body
    assert in_order(devsite, ("> [!NOTE]", "> ", "reads the settings file once"))
    learn = converted_by(MSLEARN_PAGE, profiles.MSLEARN, LEARN_URL).body
    assert in_order(learn, ("> [!NOTE]", "Only an administrator can create a user."))


def test_GatesMeasureExtractedContent_and_FlagsAreComplete() -> None:
    """The gates read the extracted content; the flags say what extraction and normalisation did.

    Chrome outside the selection is never expected; extracted_share is raised under its
    gate; a fallback extraction raises extractor_fallback, which alone makes a page low
    confidence; the normalisation flags reach ConvertedContent.
    """
    chrome = " ".join(["Chrome words fill the footer of every page."] * 10)
    page = construct_page("").replace("</main>", f"</main><footer>{chrome}</footer>")
    content = converted(page)
    assert content.quality.failed == frozenset()
    assert QualityFlag.extracted_share in content.quality.flags

    extracted, normalized, body, _ = run_pipeline(PAGE)
    fallback = dataclasses.replace(extracted, method=ExtractionMethod.fallback)
    flagged = measure(fallback, normalized, body)
    assert QualityFlag.extractor_fallback in flagged.flags
    assert QualityFlag.whole_body_extracted not in flagged.flags
    assert flagged.failed == frozenset()
    assert flagged.low_confidence

    gates = converted(GATES_PAGE).quality.flags
    assert {QualityFlag.code_lang_rate, QualityFlag.interactive_omitted} <= gates
    assert QualityFlag.html_table_kept in converted(ISLANDS_PAGE).quality.flags


def test_ExtractNeverEmptyHanded() -> None:
    """The selection, then the fallback extractor, then the whole body (spec 022eca4).

    The T17 follow-up, the maintainer's answer to the batched question, item 3: the
    fallback extractor is trafilatura and runs only when the profile's selection matches
    nothing. It keeps the main content and leaves the profile's chrome out; its output is
    method fallback, flagged extractor_fallback, which alone makes the page low confidence.
    A page it finds nothing in is extracted whole and flagged whole_body_extracted.
    """
    assert extract(TABS_PAGE, GOOGLE_URL, profiles.DEVSITE).method is ExtractionMethod.profile

    unselected = TABS_PAGE.replace('class="devsite-article-body"', 'class="article-body"')
    fallback = converted_by(unselected, profiles.DEVSITE, GOOGLE_URL)
    assert fallback.method is ExtractionMethod.fallback
    assert "pip install example-client" in fallback.body
    for chrome in DEVSITE_CHROME:
        assert chrome not in fallback.body, chrome
    assert QualityFlag.extractor_fallback in fallback.quality.flags
    assert QualityFlag.whole_body_extracted not in fallback.quality.flags
    assert fallback.quality.low_confidence

    loose = converted(NO_MAIN)
    assert loose.method is ExtractionMethod.fallback
    assert "A page whose content sits directly in the body" in loose.body
    assert not loose.is_empty

    whole = converted(IMAGE_ONLY)
    assert whole.method is ExtractionMethod.whole_body
    assert QualityFlag.whole_body_extracted in whole.quality.flags
    assert QualityFlag.extractor_fallback not in whole.quality.flags
    assert whole.quality.low_confidence


def test_ProfilesAreTheOnlyPlatformKnowledge() -> None:
    """The same markup converts by the profile's selection, whatever the URL's host.

    Re-propagated by the T17 follow-up: markup another profile's selection does not match
    goes to the fallback extractor rather than the whole body.
    """
    on_example = converted_by(TABS_PAGE, profiles.DEVSITE, SEED)
    on_google = converted_by(TABS_PAGE, profiles.DEVSITE, GOOGLE_URL)
    assert on_example.body == on_google.body
    assert on_example.quality == on_google.quality
    assert on_example.breadcrumbs == on_google.breadcrumbs == ("Guides", "Tabs")

    generic = pipeline(TABS_PAGE, profiles.GENERIC, GOOGLE_URL)[1]
    assert generic.expected.tab_panels == 0
    assert extract(MSLEARN_PAGE, LEARN_URL, profiles.DEVSITE).method is ExtractionMethod.fallback
    assert extract(TABS_PAGE, GOOGLE_URL, profiles.MSLEARN).method is ExtractionMethod.fallback


@pytest.mark.parametrize(
    ("path", "profile"),
    [
        *((path, profiles.GENERIC) for path in sorted(QUALITY.glob("*.html"))),
        *((path, profiles.DEVSITE) for path in sorted((SITES / "devsite").glob("**/*.html"))),
    ],
    ids=lambda value: value.name if isinstance(value, (Path, Profile)) else str(value),
)
def test_Determinism(path: Path, profile: Profile) -> None:
    """Each fixture page converted twice under its profile is byte-identical."""
    html = path.read_text(encoding="utf-8")
    url = f"http://docs.example/guide/{path.name}"
    first = converted_by(html, profile, url)
    assert first == converted_by(html, profile, url)
    assert first.body.encode() == converted_by(html, profile, url).body.encode()
