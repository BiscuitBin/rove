"""convert.allium's obligations: the Fidelity operations on HTML strings, the profiles, config.

Each test is named after the obligation id `just plan-spec convert` emits, dots and
hyphens as underscores, and its docstring quotes the obligation. Everything here is
pure: no network, no file but the fixture page, no clock.
"""

import dataclasses
import inspect
from collections.abc import Iterable
from pathlib import Path

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
    ExtractNeverEmptyHanded's profile and whole-body branches (the fallback extractor is
    not chosen yet): the generic selection finds `main`, else `article`, else the body.
    """
    assert list(inspect.signature(extract).parameters) == ["html", "url", "profile"]
    by_profile = extract(PAGE, SEED, profiles.GENERIC)
    assert isinstance(by_profile, ExtractedContent)
    assert by_profile.method is ExtractionMethod.profile

    article = PAGE.replace("<main>", "<article>").replace("</main>", "</article>")
    assert extract(article, SEED, profiles.GENERIC).method is ExtractionMethod.profile

    whole = extract(NO_MAIN, SEED, profiles.GENERIC)
    assert whole.method is ExtractionMethod.whole_body
    assert whole.has_text
    assert whole.title == "Loose page"
    # No meta description: the first prose paragraph, cut at description_max_chars.
    assert whole.description.startswith("A page whose content sits directly")
    assert len(whole.description) <= profiles.CONFIG.description_max_chars

    declared = PAGE.replace(
        "<meta charset", '<link rel="canonical" href="/guide/topic.html">\n    <meta charset'
    ).replace("<header>", '<nav><a href="/guide/a.html">A</a></nav><header>')
    page = extract(declared, SEED, profiles.GENERIC)
    assert page.canonical_url == "http://docs.example/guide/topic.html"
    assert page.navigation_targets == ("http://docs.example/guide/a.html",)


def test_contract_signature_Fidelity_normalize() -> None:
    """Verify implementation satisfies contract Fidelity.normalize.

    normalize: (content: ExtractedContent, profile: Profile) -> NormalizedContent, with
    ExpectedCounts over the normalised tree (ExpectedAgainstSurvived).
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
    the identity.
    """
    assert list(inspect.signature(restore).parameters) == ["markdown", "islands"]
    _, normalized, body, _ = run_pipeline(PAGE)
    assert normalized.islands == ()
    markdown = convert(normalized.fragment)
    assert restore(markdown, ()) == markdown
    assert isinstance(body, str)


def test_contract_signature_Fidelity_measure() -> None:
    """Verify implementation satisfies contract Fidelity.measure.

    measure: (content, normalized, body) -> QualityResult. Every element class is counted
    on the body and compared with the expected counts; a lost construct fails its gate,
    the score is the weighted share of passed gates, and the whole-body method flags.
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

    whole = run_pipeline(NO_MAIN)[3]
    assert QualityFlag.whole_body_extracted in whole.flags
    assert whole.low_confidence


def test_body_shape() -> None:
    """BodyShape (convert.allium 236): LF, one blank line, one h1, ids as {#id}, one final LF."""
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
    assert run_pipeline(NO_MAIN)[3].flags >= {QualityFlag.whole_body_extracted}


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
