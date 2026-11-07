"""The Fidelity operations (convert.allium 180): pure, no clock, no network, no file.

`extract` parses a whole document with lxml and selects the content by the profile's
selection (`profiles.SELECTIONS`); `normalize` and `convert` work on the extracted
fragment with the standard library's parser, which never wraps loose text.

`normalize` makes inactive tab panels visible and emits every panel, makes the declared
reductions, turns the construct families into what Markdown carries, and cuts out what
it cannot carry as islands: each island's place holds a token, a run of Unicode
noncharacters no source keeps (normalize strips them), which `convert` carries verbatim
and `restore` replaces with the island's payload.

The body is measured line by line, with each HTML block outside fences parsed: fenced
code is skipped for every count but the fences themselves, and inline code is skipped
for links, images and words.
"""

import dataclasses
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from urllib.parse import SplitResult, urljoin, urlsplit

from bs4 import BeautifulSoup, CData, Comment, Doctype, Tag
from bs4.element import NavigableString, PageElement
from markdownify import MarkdownConverter

from rovo._convert.model import (
    CONFIG,
    GATE_WEIGHTS,
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
)
from rovo._convert.profiles import Selection, TabSelection, selection_of

# Elements that never carry content.
_NEVER_CONTENT = ("script", "style", "template")
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_CODE = ("pre", "code")
# The strings that are code text, as `get_text` takes them: no comment, no doctype.
_CODE_STRINGS = (NavigableString, CData)
_WEB_SCHEMES = frozenset({"http", "https"})

_WORD = re.compile(r"[^\W_]+")
_FENCE = re.compile(r"^ {0,3}(?P<mark>`{3,}|~{3,})(?P<info>.*)$")
_ATX_HEADING = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_TABLE_SEPARATOR = re.compile(r"^\|?(?:\s*:?-{3,}:?\s*\|)*\s*:?-{3,}:?\s*\|?$")
_CELL_BORDER = re.compile(r"(?<!\\)\|")
_INLINE_CODE = re.compile(r"(`+).+?\1")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
# A destination read up to its first `)` or whitespace, when nesting closes no link.
_FIRST_CLOSE = re.compile(r"[^)\s]*")
_AUTOLINK = re.compile(r"<(?P<target>https?://[^>\s]+)>")
# Stands in for inline code while destinations are found, so code keeps its positions.
_CODE_MASK = "\x00"
_LANGUAGE_CLASS = re.compile(r"^(?:language|lang)-(?P<name>.+)$")
_BACKTICKS = re.compile(r"`+")
# The attributes normalize marks elements with for convert; a source's own are dropped.
_MARK_PREFIX = "data-rovo-"
_ANCHOR_MARK = "data-rovo-anchor"  # A heading's id, written as a `{#id}` suffix.
_INLINE_ANCHOR_MARK = "data-rovo-inline-anchor"  # A heading's id, as an anchor before it.
_LABEL_MARK = "data-rovo-label"  # A tab panel's label, on its labelled fence.
_TEX_ELEMENT = "rovo-tex"  # Math as TeX; its `display` mark says block or inline.
_TEX_DISPLAY_MARK = "data-rovo-display"
_TEX_ENCODING = "application/x-tex"
# An island token: U+FDD0, the island's index as noncharacters U+FDD2 to U+FDDB, U+FDD1.
_TOKEN_OPEN = 0xFDD0
_TOKEN_CLOSE = 0xFDD1
_TOKEN_DIGIT = 0xFDD2
_TOKEN = re.compile("\ufdd0[\ufdd2-\ufddb]+\ufdd1")
_TOKEN_CHARACTERS = dict.fromkeys(range(_TOKEN_OPEN, _TOKEN_DIGIT + 10))
# A line break followed by a blank line, which an island writes as a reference.
_BLANK_LINE_AHEAD = re.compile(r"\n(?=[ \t]*\n)")
# SanitizedMeansInert: the attributes an island keeps, and the targets it drops.
_KEPT_ATTRIBUTES = frozenset(
    {"rowspan", "colspan", "id", "scope", "href", "src", "alt", "title", "open"}
)
_TARGET_ATTRIBUTES = ("href", "src")
_UNSAFE_SCHEMES = frozenset({"javascript", "vbscript", "data"})
_IMAGE_DATA = "data:image/"
# DeclaredReductions: a custom element also keeps its class and its tab language.
_CUSTOM_ELEMENT_ATTRIBUTES = frozenset({"class", "data-tab", "data-language", "language"})
_EMBEDS = ("iframe", "embed", "object")
_LAYOUT_TABLES = "table[role=presentation], table[role=none]"
_GUTTER_CLASSES = frozenset({"linenos", "lineno", "line-number", "line-numbers", "gutter"})
_FORM_CONTROLS = ("input", "select", "textarea")
_FORM_WRAPPERS = ("form", "button", "label", "fieldset")
_BLOCK_FORM_WRAPPERS = ("form", "fieldset")
_FOOTNOTE_SECTIONS = ".footnotes, [role=doc-endnotes]"
_BACK_LINKS = "a.footnote-backref, a[role=doc-backlink], a[rev=footnote]"
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none\s*;?", re.IGNORECASE)
# Elements whose content, when a cell or definition holds one, Markdown cannot carry.
_BLOCKS = frozenset(
    {"p", "ul", "ol", "pre", "table", "dl", "div", "blockquote", "details", "section", *_HEADINGS}
)
_TABLE_PARTS = ("table", "thead", "tbody", "tfoot", "tr")
_VOID = frozenset({"img", "br", "hr", "input", "wbr", "area", "source", "embed"})
# CommonMark's HTML block start (types 1 and 6 by name, type 7 as a lone tag line).
_HTML_BLOCK_NAMES = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "body",
        "caption",
        "center",
        "col",
        "colgroup",
        "dd",
        "details",
        "dialog",
        "dir",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "header",
        "hr",
        "html",
        "iframe",
        "legend",
        "li",
        "main",
        "menu",
        "nav",
        "ol",
        "optgroup",
        "option",
        "p",
        "pre",
        "search",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
        *_HEADINGS,
    }
)
_HTML_START = re.compile(r"^ {0,3}</?(?P<name>[A-Za-z][A-Za-z0-9-]*)(?:[\s/>]|$)")
_LONE_TAG = re.compile(r"^ {0,3}</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>\s*$")

_PASSES: dict[QualityGate, Callable[[QualityResult], bool]] = {
    QualityGate.text_coverage: lambda q: q.text_coverage_passes,
    QualityGate.code_blocks: lambda q: q.code_blocks_passes,
    QualityGate.code_lang_rate: lambda q: q.code_lang_rate_passes,
    QualityGate.tables: lambda q: q.tables_passes,
    QualityGate.table_cells: lambda q: q.table_cells_passes,
    QualityGate.headings: lambda q: q.headings_passes,
    QualityGate.links: lambda q: q.links_passes,
    QualityGate.images: lambda q: q.images_passes,
    QualityGate.list_items: lambda q: q.list_items_passes,
    QualityGate.tabs_expanded: lambda q: q.tabs_expanded_passes,
}


def extract(html: str, url: str, profile: Profile) -> ExtractedContent:
    """Realises convert.allium Fidelity.extract (ExtractNeverEmptyHanded).

    The profile's content selection first; when it matches nothing, the fallback
    extractor (`_fallback`) runs, else the whole body stands in; `measure` flags either.
    The profile's chrome is stripped from the content whichever method found it. Links
    and images in the content are made absolute against the page URL; the breadcrumbs
    are the selection's.
    """
    soup = BeautifulSoup(html, "lxml")
    body = soup.body or soup
    selection = selection_of(profile)
    document_words = _words(body.get_text(" "))
    selected = _select(body, selection)
    content: Tag | BeautifulSoup = body if selected is None else selected
    chrome = content.select(selection.chrome)
    navigation = _navigation_targets(soup, selected, url, chrome)
    breadcrumbs = _breadcrumbs(soup, selection)
    for element in chrome:
        element.extract()
    method = ExtractionMethod.profile
    if selected is None:
        found = _fallback(str(soup), url)
        method = ExtractionMethod.whole_body if found is None else ExtractionMethod.fallback
        content = content if found is None else found
    _absolutise(content, url)
    kept = _words(content.get_text(" "))
    return ExtractedContent(
        source_url=url,
        html=content.decode_contents(),
        title=_title(soup, content, url),
        description=_description(soup, content),
        canonical_url=_canonical(soup, url),
        declared_locale=_attribute(soup.html, "lang") if soup.html else None,
        breadcrumbs=breadcrumbs,
        navigation_targets=navigation,
        method=method,
        has_text=bool(kept),
        extracted_share=len(kept) / len(document_words) if document_words else 1.0,
    )


def main_text_length(html: str, profile: Profile) -> int:
    """fetch_or_render's extracted text length (crawl.allium SiteResponse.main_text).

    The whitespace-collapsed length of the visible text of the profile's content
    selection, else of the whole body; never the fallback extractor, whose cost per page
    is not worth a heuristic.
    """
    soup = BeautifulSoup(html, "lxml")
    body = soup.body or soup
    selected = _select(body, selection_of(profile))
    content = body if selected is None else selected
    return len(" ".join(content.get_text(" ").split()))


def normalize(content: ExtractedContent, profile: Profile) -> NormalizedContent:
    """Realises convert.allium Fidelity.normalize.

    In order: inactive tab panels made visible and every panel emitted
    (EveryTabPanelEmitted), the declared reductions (DeclaredReductions), the construct
    families, exactly one level-one heading, the islands' HTML sanitised
    (SanitizedMeansInert), the expected counts over the tree with its islands in place
    (ExpectedAgainstSurvived), the heading ids in the profile's anchor style, then each
    uncarryable construct and each id-only anchor cut out as an island
    (UncarryableBecomesIsland, BodyShape).
    """
    selection = selection_of(profile)
    tree = BeautifulSoup(content.html.translate(_TOKEN_CHARACTERS), "html.parser")
    for node in tree.find_all(_NEVER_CONTENT):
        node.decompose()
    for element in _tags(tree):  # A source's own mark is not normalize's.
        for name in [name for name in element.attrs if name.startswith(_MARK_PREFIX)]:
            del element.attrs[name]
    flags: set[QualityFlag] = set()
    panels = _expand_tabs(tree, selection.tabs)
    if _reduce(tree):
        flags.add(QualityFlag.interactive_omitted)
    _construct_families(tree, selection, content.source_url)
    _one_level_one_heading(tree, content.title)
    uncarryable = _uncarryable(tree)
    for element in uncarryable:
        _sanitize(element, shell=element.name == "details")
    headings = [heading for heading in tree.find_all(_HEADINGS) if isinstance(heading, Tag)]
    links = [
        link
        for link in tree.find_all("a")
        if isinstance(link, Tag) and _attribute(link, "href") and not _inside(link, _CODE)
    ]
    targets = tuple(
        href
        for link in links
        if (href := _attribute(link, "href")) and _scheme(href) in _WEB_SCHEMES
    )
    tables = tree.find_all("table")
    expected = ExpectedCounts(
        code_blocks=len(tree.find_all("pre")),
        tables=len(tables),
        table_cells=sum(len(table.find_all(("th", "td"))) for table in tables),
        headings=len(headings),
        links=len(links),
        images=sum(1 for image in tree.find_all("img") if _attribute(image, "src")),
        list_items=len(tree.find_all("li")),
        tab_panels=panels,
        prose_words=tuple(_words(_prose(tree))),
    )
    anchors = frozenset(
        anchor
        for element in tree.find_all(id=True)
        if (anchor := _attribute(element, "id")) is not None
    )
    heading_texts = tuple(_text(heading) for heading in headings)
    _write_heading_ids(
        [heading for heading in headings if not _in_html_island(heading, uncarryable)], profile
    )
    islands: list[Island] = []
    _anchor_islands(tree, uncarryable, islands)
    for element in reversed(uncarryable):  # Innermost first: an outer island holds it.
        payload = _shell(element) if element.name == "details" else _serialise(element)
        if element.name == "table":
            flags.add(QualityFlag.html_table_kept)
        _cut(element, payload, islands, inline=element.name == "math")
    return NormalizedContent(
        fragment=tree.decode(),
        islands=tuple(islands),
        expected=expected,
        flags=frozenset(flags),
        anchors=anchors,
        headings=heading_texts,
        link_targets=targets,
        tab_panels_emitted=panels,
    )


def convert(fragment: str) -> str:
    """Realises convert.allium Fidelity.convert: ATX headings, fences with a language.

    The result has BodyShape's form: LF line endings, at most one blank line in a row
    outside fences, fenced code untouched, and exactly one final LF.
    """
    markdown = _Converter(
        bullets="-",
        code_language_callback=_code_language,
    ).convert(fragment)
    return _shape(markdown)


def restore(markdown: str, islands: Sequence[Island]) -> str:
    """Realises convert.allium Fidelity.restore: each island's token gives way to its payload.

    The identity when there is no island; a token the converter lost leaves its island out.
    """
    for index, island in enumerate(islands):
        markdown = markdown.replace(_token(index), island.payload, 1)
    return markdown


def measure(content: ExtractedContent, normalized: NormalizedContent, body: str) -> QualityResult:
    """Realises convert.allium Fidelity.measure (FailedGatesAreFlagged, ScoreIsAFraction).

    Each gate compares the body with the normalised tree's expected counts; the score is
    one minus the weights of the failed gates. An island whose payload is not in the body,
    or a token left in it, is a lost construct: fidelity_loss.
    """
    probe = QualityResult(
        expected=normalized.expected,
        output=measure_body(body, normalized.expected.prose_words),
        tab_panels_emitted=normalized.tab_panels_emitted,
        failed=frozenset(),
        score=1.0,
        flags=frozenset(),
        low_confidence=False,
    )
    failed = frozenset(gate for gate, passes in _PASSES.items() if not passes(probe))
    flags = {QualityFlag[gate.value] for gate in failed} | normalized.flags
    if content.method is ExtractionMethod.whole_body:
        flags.add(QualityFlag.whole_body_extracted)
    if content.method is ExtractionMethod.fallback:
        flags.add(QualityFlag.extractor_fallback)
    if _TOKEN.search(body) or any(island.payload not in body for island in normalized.islands):
        flags.add(QualityFlag.fidelity_loss)
    if content.extracted_share < CONFIG.extracted_share_gate:
        flags.add(QualityFlag.extracted_share)
    if _is_empty(content, body):
        flags.add(QualityFlag.empty_content)
    return dataclasses.replace(
        probe,
        failed=failed,
        score=max(0.0, 1.0 - sum(GATE_WEIGHTS[gate] for gate in failed)),
        flags=frozenset(flags),
        low_confidence=_low_confidence(failed, flags),
    )


def converted_content(
    extracted: ExtractedContent,
    normalized: NormalizedContent,
    body: str,
    measured: QualityResult,
) -> ConvertedContent:
    """Assemble a ConvertedContent from the Fidelity results (crawl.allium ConvertFetched)."""
    return ConvertedContent(
        body=body,
        title=extracted.title,
        description=extracted.description,
        canonical_url=extracted.canonical_url,
        declared_locale=extracted.declared_locale,
        breadcrumbs=extracted.breadcrumbs,
        navigation_targets=extracted.navigation_targets,
        method=extracted.method,
        anchors=normalized.anchors,
        headings=normalized.headings,
        link_targets=tuple(dict.fromkeys(normalized.link_targets)),
        quality=measured,
        is_empty=_is_empty(extracted, body),
    )


def with_fetch_flags(content: ConvertedContent, flags: Iterable[QualityFlag]) -> ConvertedContent:
    """Add the fetch flags to the quality result and recompute low_confidence."""
    added = frozenset(flags)
    if added <= content.quality.flags:
        return content
    merged = content.quality.flags | added
    quality = dataclasses.replace(
        content.quality,
        flags=merged,
        low_confidence=_low_confidence(content.quality.failed, merged),
    )
    return dataclasses.replace(content, quality=quality)


def link_destinations(body: str) -> tuple[str, ...]:
    """Every link target of a Markdown body outside code, images excluded, in order."""
    targets: list[str] = []

    def record(target: str) -> str:
        targets.append(target)
        return target

    map_destinations(body, record)
    return tuple(targets)


def map_destinations(body: str, rewrite: Callable[[str], str]) -> str:
    """The body with `rewrite` applied to each link destination outside code.

    Fenced code and inline code are left as they are, and so is every byte around a
    destination: the identity mapping returns the body unchanged. Each line's inline
    links are visited before its autolinks. An autolink whose destination changes
    becomes an inline link whose text is the URL, since `<b.md>` is no autolink.
    """
    lines: list[str] = []
    fence: str | None = None
    for line in body.split("\n"):
        match = _FENCE.match(line)
        if fence is None and match:
            fence = match["mark"]
        elif fence is not None and _closes(line, fence):
            fence = None
        elif fence is None:
            line = _map_line(line, rewrite)  # noqa: PLW2901  The line, rewritten in place.
        lines.append(line)
    return "\n".join(lines)


def _map_line(line: str, rewrite: Callable[[str], str]) -> str:
    """One line outside fences with its destinations outside inline code rewritten."""
    code = [match.span() for match in _INLINE_CODE.finditer(line)]
    masked = list(line)
    for start, end in code:
        masked[start:end] = _CODE_MASK * (end - start)
    text = "".join(masked)
    edits: list[tuple[int, int, str]] = []
    for start, end in _link_targets(text):
        if _CODE_MASK not in text[start:end]:
            edits.append((start, end, rewrite(line[start:end])))
    for match in _AUTOLINK.finditer(text):
        start, end = match.span("target")
        if _CODE_MASK not in text[start:end]:
            target = line[start:end]
            mapped = rewrite(target)
            if mapped != target:
                edits.append((start - 1, end + 1, f"[{target}]({mapped})"))
    out: list[str] = []
    position = 0
    for start, end, replacement in sorted(edits):
        if start < position:
            continue
        out.extend((line[position:start], replacement))
        position = end
    out.append(line[position:])
    return "".join(out)


def _link_targets(line: str) -> Iterator[tuple[int, int]]:
    """The span of each inline link's destination in a line, images excluded, in order.

    Link text runs to the `]` that balances its `[`, as CommonMark reads it: a backslash
    escapes the next character, so `[see [1]](b)` names `b`; an image inside the text,
    as in `[![logo](i.png)](b)`, is part of the text, and an image on its own is passed
    over whole. Link text holding a link is no link: the inner one is.

    A destination runs to whitespace or to the `)` that closes the link: as CommonMark
    reads it, a backslash escapes the next character and parentheses inside it nest, so
    `[a](x_(y).html)` names `x_(y).html`. When that reading closes no link, the
    destination stops at its first `)` or whitespace instead. Whatever follows the
    destination, a title, runs to the next `)`.
    """
    search = 0
    while (opening := _next_opening(line, search)) >= 0:
        link = _inline_link(line, opening)
        image = opening > 0 and line[opening - 1] == "!" and not _escaped(line, opening - 1)
        text = line[opening + 1 : link[0]] if link else ""
        if link is None or (not image and any(_link_targets(text))):
            search = opening + 1
            continue
        _, start, end, close = link
        if not image:
            yield start, end
        search = close + 1


def _next_opening(line: str, search: int) -> int:
    """Where the next `[` not escaped by a backslash is, else -1."""
    opening = line.find("[", search)
    while opening >= 0 and _escaped(line, opening):
        opening = line.find("[", opening + 1)
    return opening


def _escaped(line: str, position: int) -> bool:
    """Whether an odd run of backslashes stands just before `position`."""
    run = len(line[:position]) - len(line[:position].rstrip("\\"))
    return run % 2 == 1


def _inline_link(line: str, opening: int) -> tuple[int, int, int, int] | None:
    """The `]` ending the text, the destination's span and the closing `)`, else None."""
    text_end = _text_end(line, opening + 1)
    if text_end is None or not line.startswith("(", text_end + 1):
        return None
    start = text_end + 2
    for end in (_balanced_end(line, start), _first_close_end(line, start)):
        close = -1 if end is None else line.find(")", end)
        if end is not None and close >= 0:
            return text_end, start, end, close
    return None


def _text_end(line: str, start: int) -> int | None:
    """Where the `]` balancing a link text's `[` is, else None when none balances it."""
    depth = 0
    position = start
    while position < len(line):
        character = line[position]
        if character == "\\":
            position += 2
            continue
        if character == "]":
            if not depth:
                return position
            depth -= 1
        elif character == "[":
            depth += 1
        position += 1
    return None


def _first_close_end(line: str, start: int) -> int:
    """Where a destination read up to its first `)` or whitespace ends."""
    match = _FIRST_CLOSE.match(line, start)
    return match.end() if match else start


def _balanced_end(line: str, start: int) -> int | None:
    """Where a destination with nested parentheses ends, else None when they never close."""
    depth = 0
    position = start
    while position < len(line) and not line[position].isspace():
        character = line[position]
        if character == "\\":
            position += 2
            continue
        if character == ")":
            if not depth:
                break
            depth -= 1
        elif character == "(":
            depth += 1
        position += 1
    return None if depth else min(position, len(line))


def prose_lines(body: str) -> list[str]:
    """The body's lines outside fenced code, with inline code removed."""
    return [_INLINE_CODE.sub("", line) for line in _outside_fences(body)[0]]


def _low_confidence(failed: frozenset[QualityGate], flags: Iterable[QualityFlag]) -> bool:
    return bool(failed) or not CONFIG.incomplete_flags.isdisjoint(flags)


def _is_empty(content: ExtractedContent, body: str) -> bool:
    return not content.has_text or not body.strip()


def _fallback(html: str, url: str) -> Tag | BeautifulSoup | None:
    """The fallback extractor's main content (ExtractNeverEmptyHanded), None for none.

    trafilatura's main-content extraction as HTML, its formatting, links, images and
    tables kept; what it keeps is its own choice. Imported here alone, so `import rovo`
    never loads it.
    """
    import trafilatura  # noqa: PLC0415  Lazy: the fallback runs only on an unmatched page.

    found = trafilatura.extract(
        html,
        url=url,
        output_format="html",
        include_comments=False,
        include_formatting=True,
        include_links=True,
        include_images=True,
        include_tables=True,
    )
    tree = BeautifulSoup(found or "", "lxml")
    content = tree.body or tree
    return content if _words(content.get_text(" ")) else None


def _select(body: Tag | BeautifulSoup, selection: Selection) -> Tag | None:
    for selector in selection.content:
        found = body.select_one(selector)
        if found is not None:
            return found
    return None


def _breadcrumbs(soup: BeautifulSoup, selection: Selection) -> tuple[str, ...]:
    """The text of each breadcrumb the selection names, in order."""
    if selection.breadcrumbs is None:
        return ()
    return tuple(text for item in soup.select(selection.breadcrumbs) if (text := _text(item)))


def _navigation_targets(
    soup: BeautifulSoup, content: Tag | None, url: str, chrome: Sequence[Tag]
) -> tuple[str, ...]:
    """Absolute web hrefs of the page's navigation outside the content, order kept.

    Navigation inside the selected content but within its chrome is stripped from the
    content, so it is outside it.
    """
    targets: list[str] = []
    for nav in soup.find_all("nav"):
        if not isinstance(nav, Tag) or (
            content is not None and _within(nav, content) and not _in_any(nav, chrome)
        ):
            continue
        for link in nav.find_all("a"):
            href = _attribute(link, "href")
            absolute = _joined(url, href) if href else None
            if absolute is not None and _scheme(absolute) in _WEB_SCHEMES:
                targets.append(absolute)
    return tuple(dict.fromkeys(targets))


def _within(element: Tag, container: Tag | BeautifulSoup) -> bool:
    return element is container or any(parent is container for parent in element.parents)


def _in_any(element: Tag, containers: Sequence[Tag]) -> bool:
    return any(_within(element, container) for container in containers)


def _absolutise(content: Tag | BeautifulSoup, url: str) -> None:
    for element, name in [(link, "href") for link in content.find_all("a")] + [
        (image, "src") for image in content.find_all("img")
    ]:
        value = _attribute(element, name)
        if value and isinstance(element, Tag):
            element[name] = _joined(url, value) or value


def _title(soup: BeautifulSoup, content: Tag | BeautifulSoup, url: str) -> str:
    """First h1 in the content, else og:title, else <title>, else the URL."""
    heading = content.find("h1")
    if isinstance(heading, Tag) and _text(heading):
        return _text(heading)
    og_title = _attribute(soup.find("meta", attrs={"property": "og:title"}), "content")
    if og_title and og_title.strip():
        return " ".join(og_title.split())
    if soup.title is not None and _text(soup.title):
        return _text(soup.title)
    return url


def _description(soup: BeautifulSoup, content: Tag | BeautifulSoup) -> str:
    """The meta description, else the first prose paragraph cut at description_max_chars."""
    meta = _attribute(soup.find("meta", attrs={"name": "description"}), "content")
    if meta and meta.strip():
        return " ".join(meta.split())
    for paragraph in content.find_all("p"):
        if isinstance(paragraph, Tag) and _text(paragraph):
            return _text(paragraph)[: CONFIG.description_max_chars].rstrip()
    return ""


def _canonical(soup: BeautifulSoup, url: str) -> str | None:
    href = _attribute(soup.find("link", attrs={"rel": "canonical"}), "href")
    return _joined(url, href) if href else None


def _parts(url: str) -> SplitResult | None:
    """Urlsplit's parts, or None for a URL it cannot take (an unclosed IPv6 bracket)."""
    try:
        return urlsplit(url)
    except ValueError:
        return None


def _unfragmented(parts: SplitResult | None) -> str | None:
    """The URL of `parts` with its fragment dropped; None for a URL urlsplit cannot take."""
    return None if parts is None else parts._replace(fragment="").geturl()


def _scheme(url: str) -> str:
    """The URL's scheme as urlsplit reads it; empty for a URL it cannot take."""
    parts = _parts(url)
    return "" if parts is None else parts.scheme


def _joined(base: str, href: str) -> str | None:
    """`href` resolved against `base`, or None when it cannot be (a malformed URL)."""
    try:
        return urljoin(base, href)
    except ValueError:
        return None


def _attribute(element: object, name: str) -> str | None:
    """A single-valued attribute of a tag, else None."""
    if not isinstance(element, Tag):
        return None
    value = element.get(name)
    return value.strip() if isinstance(value, str) else None


def _inside(element: PageElement, names: tuple[str, ...]) -> bool:
    return any(parent.name in names for parent in element.parents)


def _text(element: Tag) -> str:
    return " ".join(element.get_text(" ").split())


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _prose(tree: BeautifulSoup) -> str:
    """The tree's text outside code, comments and the doctype."""
    pieces = [
        str(string)
        for string in tree.find_all(string=True)
        if isinstance(string, NavigableString)
        and not isinstance(string, (Comment, Doctype))
        and not any(parent.name in _CODE for parent in string.parents)
    ]
    return " ".join(pieces)


def _one_level_one_heading(tree: BeautifulSoup, title: str) -> None:
    level_one = tree.find_all("h1")
    if not level_one:
        heading = tree.new_tag("h1")
        heading.string = title
        tree.insert(0, heading)
        return
    for extra in level_one[1:]:
        if isinstance(extra, Tag):
            extra.name = "h2"


def _write_heading_ids(headings: Sequence[Tag], profile: Profile) -> None:
    """Heading ids in the profile's anchor style: a `{#id}` suffix, or an anchor before it."""
    mark = (
        _ANCHOR_MARK
        if profile.heading_anchor_style is HeadingAnchorStyle.attr
        else _INLINE_ANCHOR_MARK
    )
    for heading in headings:
        anchor = _attribute(heading, "id")
        if anchor:
            heading[mark] = anchor


# --- Tab expansion (EveryTabPanelEmitted) --------------------------------------------------


def _expand_tabs(tree: BeautifulSoup, tabs: TabSelection | None) -> int:
    """Every panel of every tab group made visible and emitted in source order; their count.

    A group whose every panel is one code sample in a named language becomes one
    labelled fence per panel; any other group a heading one level below its context,
    the panel's label, then the panel.
    """
    if tabs is None:
        return 0
    groups = tree.select(tabs.groups)
    for group in groups:
        for panel in group.select(tabs.panels):
            _make_visible(panel)
    levels = [_context_level(group, groups) for group in groups]  # Before headings are added.
    emitted = 0
    for group, level in zip(groups, levels, strict=True):
        panels = group.select(tabs.panels)
        labels = _tab_labels(tree, group, panels, tabs)
        codes = [_lone_code(panel) for panel in panels]
        # The group's own id and its tab list's and labels' ids stay anchors (BodyShape).
        kept = [_attribute(part, "id") for part in _tags(group) if not _in_any(part, panels)]
        nodes: list[PageElement] = [*_id_holders(tree, kept, block=True)]
        if panels and all(code is not None for code in codes):
            for panel, code, label in zip(panels, codes, labels, strict=True):
                if code is not None:
                    code[_LABEL_MARK] = label
                    outside = [part for part in _tags(panel) if not _within(part, code)]
                    ids = [_attribute(part, "id") for part in outside]
                    nodes.extend((*_id_holders(tree, ids, block=True), code.extract()))
        else:
            for panel, label in zip(panels, labels, strict=True):
                heading = tree.new_tag(f"h{level}")
                heading.string = label
                nodes.extend((*_kept_ids(tree, panel), heading, *list(panel.extract().contents)))
        group.replace_with(*nodes)
        emitted += len(panels)
    return emitted


def _make_visible(panel: Tag) -> None:
    """Remove an inactive panel's hidden markers: `hidden`, aria-hidden, display: none."""
    for name in ("hidden", "aria-hidden"):
        panel.attrs.pop(name, None)
    style = _attribute(panel, "style")
    if style is not None:
        panel["style"] = _HIDDEN_STYLE.sub("", style)


def _tab_labels(
    tree: BeautifulSoup, group: Tag, panels: Sequence[Tag], tabs: TabSelection
) -> list[str]:
    """Each panel's label: the group's labels by position, else its first heading or title.

    A heading taken as the label leaves its id behind.
    """
    named = [_text(label) for label in group.select(tabs.labels)] if tabs.labels else []
    labels: list[str] = []
    for index, panel in enumerate(panels):
        heading = panel.find(_HEADINGS)
        if index < len(named):
            label = named[index]
        elif isinstance(heading, Tag):
            label = _text(heading)
            heading.replace_with(*_kept_ids(tree, heading))
        else:
            label = _attribute(panel, "title") or str(index + 1)
        labels.append(label)
    return labels


def _lone_code(panel: Tag) -> Tag | None:
    """The panel's one code sample when that is all it holds and it names a language."""
    blocks = panel.find_all("pre")
    if len(blocks) != 1 or not isinstance(blocks[0], Tag) or not _code_language(blocks[0]):
        return None
    return blocks[0] if _text(panel) == _text(blocks[0]) else None


def _context_level(group: Tag, groups: Sequence[Tag]) -> int:
    """One level below the last heading before the group outside every group; else two."""
    previous = next(
        (
            heading
            for heading in group.find_all_previous(_HEADINGS)
            if isinstance(heading, Tag) and not any(_within(heading, other) for other in groups)
        ),
        None,
    )
    level = int(previous.name[1]) if previous is not None else 1
    return min(level + 1, len(_HEADINGS))


# --- Declared reductions and construct families --------------------------------------------


def _reduce(tree: BeautifulSoup) -> bool:
    """DeclaredReductions, in place; whether an interactive embed was omitted."""
    embeds = [embed for embed in tree.find_all(_EMBEDS) if isinstance(embed, Tag)]
    for embed in embeds:
        note = tree.new_tag("p")
        note.string = _embed_note(embed)
        embed.replace_with(*_kept_ids(tree, embed), note)
    for link in tree.select("pre a, code a"):
        link.unwrap()
    for gutter in tree.select("pre [class]"):
        classes = gutter.get("class")
        if isinstance(classes, list) and _GUTTER_CLASSES.intersection(classes):
            gutter.decompose()
    for control in tree.find_all(_FORM_CONTROLS):
        control.decompose()
    for wrapper in tree.find_all(_FORM_WRAPPERS):
        block = wrapper.name in _BLOCK_FORM_WRAPPERS
        wrapper.insert_before(*_id_holders(tree, [_attribute(wrapper, "id")], block=block))
        wrapper.unwrap()
    for table in reversed(tree.select(_LAYOUT_TABLES)):
        cells = [cell for cell in table.find_all(("td", "th")) if _owner_table(cell) is table]
        contents = [child for cell in cells for child in list(cell.contents)]
        ids = _id_holders(tree, [_attribute(part, "id") for part in (table, *cells)], block=True)
        table.replace_with(*ids, *[child.extract() for child in contents])
    for back_link in tree.select(_BACK_LINKS):
        back_link.decompose()
    return bool(embeds)


def _embed_note(embed: Tag) -> str:
    """One line keeping the embed's label and URL."""
    url = _attribute(embed, "src") or _attribute(embed, "data") or ""
    label = _attribute(embed, "title") or _attribute(embed, "aria-label") or _text(embed)
    parts = [part for part in (label, f"({url})" if url and label else url) if part]
    return " ".join(["Interactive content:", *parts])


def _owner_table(cell: Tag) -> Tag | None:
    found = cell.find_parent("table")
    return found if isinstance(found, Tag) else None


def _construct_families(tree: BeautifulSoup, selection: Selection, page_url: str) -> None:
    """Callouts to GFM alerts, math with TeX to TeX, footnotes to `[^n]` (the guidance)."""
    for selector, kind in selection.callouts:
        for callout in tree.select(selector):
            quote = tree.new_tag("blockquote")
            marker = tree.new_tag("p")
            marker.string = f"[!{kind}]"
            quote.append(marker)
            quote.extend(list(callout.contents))
            callout.replace_with(*_kept_ids(tree, callout), quote)
    for math in [math for math in tree.find_all("math") if isinstance(math, Tag)]:
        annotation = math.find("annotation", attrs={"encoding": _TEX_ENCODING})
        if isinstance(annotation, Tag):
            tex = tree.new_tag(_TEX_ELEMENT)
            tex.string = annotation.get_text().strip()
            display = _attribute(math, "display") or "inline"
            tex[_TEX_DISPLAY_MARK] = display
            ids = [_attribute(element, "id") for element in [math, *math.find_all(id=True)]]
            math.replace_with(*_id_holders(tree, ids, block=display == "block"), tex)
    for section in tree.select(_FOOTNOTE_SECTIONS):
        _footnotes(tree, section, page_url)


def _footnotes(tree: BeautifulSoup, section: Tag, page_url: str) -> None:
    """Each same-page reference to a note of the section becomes `[^n]`, each note `[^n]: text`.

    A reference is same-page when it is a bare `#id` or its target without its fragment
    is `page_url` without its fragment (convert.allium 284 to 288); a link to another
    page stays a link even when its fragment names a local note.

    A reference's or a note's id stays an anchor (BodyShape): an empty element holding
    it, which becomes an anchor island, before the reference or on a line before the note.
    """
    notes = [note for note in section.find_all("li", id=True) if isinstance(note, Tag)]
    numbers = {_attribute(note, "id"): index for index, note in enumerate(notes, start=1)}
    for link in tree.find_all("a", href=True):
        href = _attribute(link, "href") or ""
        parts = _parts(href)
        same_page = parts is not None and (
            href.startswith("#") or _unfragmented(parts) == _unfragmented(_parts(page_url))
        )
        number = numbers.get(parts.fragment) if parts is not None and same_page else None
        if number is None or not isinstance(link, Tag) or _within(link, section):
            continue
        parent = link.parent
        reference = (
            parent
            if parent is not None and parent.name == "sup" and _text(parent) == _text(link)
            else link
        )
        ids = [_attribute(element, "id") for element in (reference, link)]
        reference.replace_with(*_id_holders(tree, ids, block=False), f"[^{number}]")
    definitions: list[PageElement] = []
    for number, note in enumerate(notes, start=1):
        definition = tree.new_tag("p")
        definition.append(f"[^{number}]: ")
        for child in list(note.contents):
            if isinstance(child, Tag) and child.name == "p":
                definition.extend(list(child.contents))
            else:
                definition.append(child.extract())
        definitions.extend((*_id_holders(tree, [_attribute(note, "id")], block=True), definition))
    section.replace_with(*_kept_ids(tree, section), *definitions)


def _kept_ids(tree: BeautifulSoup, element: Tag) -> list[Tag]:
    """The id of an element normalize replaces, held on a line of its own (BodyShape)."""
    return _id_holders(tree, [_attribute(element, "id")], block=True)


def _id_holders(tree: BeautifulSoup, ids: Sequence[str | None], *, block: bool) -> list[Tag]:
    """An empty element per id, which becomes an anchor island; a paragraph when `block`."""
    holders: list[Tag] = []
    for anchor in dict.fromkeys(anchor for anchor in ids if anchor):
        holder = tree.new_tag("span", attrs={"id": anchor})
        if block:
            paragraph = tree.new_tag("p")
            paragraph.append(holder)
            holder = paragraph
        holders.append(holder)
    return holders


# --- Islands (UncarryableBecomesIsland, SanitizedMeansInert) -------------------------------


def _uncarryable(tree: BeautifulSoup) -> list[Tag]:
    """Each construct Markdown cannot carry, in document order."""
    return [
        element
        for element in tree.find_all(("table", "dl", "details", "math"))
        if isinstance(element, Tag) and _is_uncarryable(element)
    ]


def _is_uncarryable(element: Tag) -> bool:
    """A complex, header-less or row-header table, a block definition list, details, math."""
    if element.name == "table":
        return _complex_table(element)
    if element.name == "dl":
        return any(_holds_block(part) for part in element.find_all(("dt", "dd")))
    return True  # details always; math only reaches here without its TeX.


def _complex_table(table: Tag) -> bool:
    rows = [row for row in table.find_all("tr") if _owner_table(row) is table]
    cells = [cell for row in rows for cell in row.find_all(("td", "th"), recursive=False)]
    spanning = any(
        _attribute(cell, name) not in (None, "", "1")
        for cell in cells
        for name in ("rowspan", "colspan")
    )
    header_less = not rows or rows[0].find("th", recursive=False) is None
    row_header = any(row.find("th", recursive=False) is not None for row in rows[1:])
    return spanning or header_less or row_header or any(_holds_block(cell) for cell in cells)


def _tags(root: Tag) -> list[Tag]:
    """The root and every element below it, in document order."""
    return [root, *(node for node in root.descendants if isinstance(node, Tag))]


def _holds_block(element: Tag) -> bool:
    return element.find(_BLOCKS) is not None


def _sanitize(element: Tag, *, shell: bool) -> None:
    """SanitizedMeansInert, in place: kept attributes and safe targets only, no blank line.

    A shell keeps its own attributes and its summary sanitised; its other content becomes
    Markdown, which carries no attribute.
    """
    inside = element.find_all("summary", recursive=False) if shell else [element]
    parts = [element, *(part for root in inside if isinstance(root, Tag) for part in _tags(root))]
    for part in dict.fromkeys(parts):
        custom = "-" in part.name
        for name in list(part.attrs):
            kept = name in _KEPT_ATTRIBUTES or (custom and name in _CUSTOM_ELEMENT_ATTRIBUTES)
            if not kept or (name in _TARGET_ATTRIBUTES and not _safe_target(part, name)):
                del part.attrs[name]
    if not shell:
        for string in list(element.find_all(string=True)):
            if type(string) is not NavigableString:
                string.extract()  # A comment or the like is no text, and may hold a blank line.
            elif not _inside(string, ("pre",)) and "\n" in string:
                string.replace_with(re.sub(r"\s*\n\s*", "\n", str(string)))


def _safe_target(element: Tag, name: str) -> bool:
    """Not javascript: or vbscript:, and no data: URL but an image's source."""
    value = _attribute(element, name) or ""
    parts = _parts(value)
    if parts is None:  # Unreadable, so not known safe: the attribute goes.
        return False
    if parts.scheme.lower() not in _UNSAFE_SCHEMES:
        return True
    return element.name == "img" and name == "src" and value.lower().startswith(_IMAGE_DATA)


def _in_html_island(element: Tag, islands: Sequence[Tag]) -> bool:
    """An island, or inside one whose HTML is kept as it is: not a shell's Markdown content."""
    summary = element if element.name == "summary" else element.find_parent("summary")
    return any(
        element is island
        or (
            _within(element, island)
            and (island.name != "details" or (summary is not None and _within(summary, island)))
        )
        for island in islands
    )


def _anchor_islands(
    tree: BeautifulSoup, uncarryable: Sequence[Tag], islands: list[Island]
) -> None:
    """Each id outside an HTML island and off a heading becomes an anchor island (BodyShape).

    The anchor goes before the element's content, or before the element when it holds
    none Markdown can place it in (a void element, code, a table's rows).
    """
    for element in tree.find_all(id=True):
        if (
            not isinstance(element, Tag)
            or element.name in _HEADINGS
            or _in_html_island(element, uncarryable)
        ):
            continue
        anchor = _attribute(element, "id")
        del element["id"]
        if not anchor:
            continue
        token = NavigableString(_token(len(islands)))
        islands.append(Island(payload=f'<a id="{_escape(anchor)}"></a>', carries_markdown=False))
        if element.name in _VOID or element.name in _CODE or element.name in _TABLE_PARTS:
            element.insert_before(token)
        else:
            element.insert(0, token)


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;")


def _serialise(element: Tag) -> str:
    """A sanitised island as HTML: one block, no blank line in it.

    A blank line, which only code can still hold, keeps its line break as a reference.
    """
    html = _BLANK_LINE_AHEAD.sub("&#10;", element.decode())
    return "\n".join(line for line in html.split("\n") if line.strip())


def _shell(details: Tag) -> str:
    """A details island: its summary as HTML, its other content as Markdown between blank lines."""
    attributes = "".join(
        f' {name}="{_escape(value if isinstance(value, str) else " ".join(value))}"'
        for name, value in sorted(details.attrs.items())
    )
    summaries = list(details.find_all("summary", recursive=False))
    head = "".join(summary.extract().decode() for summary in summaries)
    markdown = convert(details.decode_contents()).strip()
    return f"<details{attributes}>\n{head}\n\n{markdown}\n\n</details>"


def _cut(element: Tag, payload: str, islands: list[Island], *, inline: bool) -> None:
    """Replace the element by its island's token: a paragraph of its own, or inline."""
    expanded = restore(payload, islands)  # An island it holds is carried in its payload.
    token = _token(len(islands))
    islands.append(Island(payload=expanded, carries_markdown=element.name == "details"))
    if inline:
        element.replace_with(token)
        return
    paragraph = BeautifulSoup("", "html.parser").new_tag("p")
    paragraph.string = token
    element.replace_with(paragraph)


def _token(index: int) -> str:
    """The token standing for island `index`: noncharacters only, so no word and no source."""
    digits = "".join(chr(_TOKEN_DIGIT + int(digit)) for digit in str(index))
    return f"{chr(_TOKEN_OPEN)}{digits}{chr(_TOKEN_CLOSE)}"


class _Converter(MarkdownConverter):
    """markdownify, with ids, labels, TeX and inline HTML as normalize marked them.

    The code text is written verbatim, never escaped; sup, sub, kbd and mark stay inline
    HTML; a definition list whose definitions are inline becomes bold term lines.
    """

    def convert_hN(self, n: int, el: Tag, text: str, parent_tags: set[str]) -> str:  # noqa: N802  markdownify's hook name.
        """An ATX heading with its `{#id}` suffix, or its anchor before it, if marked."""
        if "_inline" in parent_tags:
            return text
        anchor = _attribute(el, _ANCHOR_MARK)
        suffix = "" if anchor is None else f" {{#{anchor}}}"
        inline = _attribute(el, _INLINE_ANCHOR_MARK)
        before = "" if inline is None else f'<a id="{_escape(inline)}"></a>\n\n'
        return f"\n\n{before}{'#' * max(1, min(6, n))} {' '.join(text.split())}{suffix}\n\n"

    def convert_pre(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        """A fence around the code text, longer than any backtick run in it, labelled if a tab."""
        del text, parent_tags
        code = _code_text(el)
        if not code:
            return ""
        longest = max((len(run) for run in _BACKTICKS.findall(code)), default=0)
        fence = "`" * max(3, longest + 1)
        language = _code_language(el) or ""
        label = _attribute(el, _LABEL_MARK)
        title = "" if not label else f' title="{label.replace(chr(34), chr(39))}"'
        ending = "" if code.endswith("\n") else "\n"
        return f"\n\n{fence}{language}{title}\n{code}{ending}{fence}\n\n"

    def convert_sup(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        """Kept as inline HTML."""
        return _inline_html(el, text, parent_tags)

    convert_sub = convert_sup
    convert_kbd = convert_sup
    convert_mark = convert_sup

    def convert_dt(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        """A term as a bold line."""
        del el
        term = " ".join(text.split())
        if "_inline" in parent_tags or not term:
            return f" {term} "
        return f"\n\n**{term}**\n"

    def convert_dd(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        """A definition as the line after its term."""
        del el
        definition = text.strip()
        if "_inline" in parent_tags:
            return f" {definition} "
        return f"{definition}\n\n"

    def convert_rovo_tex(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        """Math as TeX between delimiters: `$$` on lines of their own for a block."""
        del text, parent_tags
        tex = el.get_text()
        if _attribute(el, _TEX_DISPLAY_MARK) == "block":
            return f"\n\n$$\n{tex}\n$$\n\n"
        return f"${tex}$"


def _inline_html(el: Tag, text: str, parent_tags: set[str]) -> str:
    if "_noformat" in parent_tags or not text.strip():
        return text
    return f"<{el.name}>{text}</{el.name}>"


def _code_text(pre: Tag) -> str:
    """The code text as HTML reads it, each `<br>` a line break.

    A newline straight after the `<pre>` start tag is not content (lxml keeps it; HTML
    drops it).
    """
    first = pre.contents[0] if pre.contents else None
    pieces: list[str] = []
    for node in pre.descendants:
        if isinstance(node, Tag):
            pieces.append("\n" if node.name == "br" else "")
        elif type(node) in _CODE_STRINGS:
            pieces.append(str(node).removeprefix("\n") if node is first else str(node))
    return "".join(pieces)


def _code_language(pre: Tag) -> str | None:
    """The language a fence names, from a `language-x` or `lang-x` class."""
    code = pre.find("code")
    for element in (code, pre):
        classes = element.get("class") if isinstance(element, Tag) else None
        for name in classes if isinstance(classes, list) else ():
            match = _LANGUAGE_CLASS.match(name)
            if match:
                return match["name"]
    return None


def _shape(markdown: str) -> str:
    """LF endings, one blank line at most outside fences, one final LF."""
    lines: list[str] = []
    fence: str | None = None
    for line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = _FENCE.match(line)
        if fence is None and match:
            fence = match["mark"]
        elif fence is not None and _closes(line, fence):
            fence = None
        elif fence is None and not line.strip():
            if lines and lines[-1]:
                lines.append("")
            continue
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def _closes(line: str, fence: str) -> bool:
    """The line closes a fence opened with `fence`: the same mark, at least as long."""
    stripped = line.strip()
    return stripped.startswith(fence) and not stripped.strip(fence[0])


def _outside_fences(body: str) -> tuple[list[str], list[str]]:
    """The lines outside fenced code, and each fence's info string."""
    outside: list[str] = []
    infos: list[str] = []
    fence: str | None = None
    for line in body.split("\n"):
        match = _FENCE.match(line)
        if fence is None and match:
            fence = match["mark"]
            infos.append(match["info"].strip())
        elif fence is not None and _closes(line, fence):
            fence = None
        elif fence is None:
            outside.append(line)
    return outside, infos


def _tables(lines: Sequence[str]) -> tuple[int, int]:
    """Pipe tables and their cells: runs of `|` rows that hold a separator row."""
    tables = cells = 0
    run: list[str] = []
    for line in [*lines, ""]:
        if line.strip().startswith("|"):
            run.append(line.strip())
            continue
        if any(_TABLE_SEPARATOR.match(row) for row in run):
            tables += 1
            cells += sum(
                len(_CELL_BORDER.split(row)) - 2 for row in run if not _TABLE_SEPARATOR.match(row)
            )
        run = []
    return tables, cells


def measure_body(body: str, expected_words: Sequence[str]) -> OutputMeasurement:
    """The body's element classes: Markdown tokens plus the parsed HTML blocks.

    Each HTML block outside fences is parsed: its elements are counted with the Markdown
    ones and its text outside code as words, its tag and attribute names never.
    """
    outside, infos = _outside_fences(body)
    lines, blocks = _html_blocks(outside)
    prose = [_INLINE_CODE.sub("", line) for line in lines]
    tables, cells = _tables(lines)
    words = [word for line in prose for word in _words(_IMAGE.sub(" ", line))]
    html = BeautifulSoup("\n".join(blocks), "html.parser")
    html_tables = html.find_all("table")
    words += _words(_prose(html))
    return OutputMeasurement(
        code_blocks=len(infos) + len(html.find_all("pre")),
        tables=tables + len(html_tables),
        table_cells=cells + sum(len(table.find_all(("th", "td"))) for table in html_tables),
        headings=sum(1 for line in lines if _ATX_HEADING.match(line))
        + len(html.find_all(_HEADINGS)),
        links=sum(len(list(_link_targets(line))) + len(_AUTOLINK.findall(line)) for line in prose)
        + sum(
            1
            for link in html.find_all("a")
            if _attribute(link, "href") and isinstance(link, Tag) and not _inside(link, _CODE)
        ),
        images=sum(len(_IMAGE.findall(line)) for line in prose)
        + sum(1 for image in html.find_all("img") if _attribute(image, "src")),
        list_items=sum(1 for line in lines if _LIST_ITEM.match(line)) + len(html.find_all("li")),
        words=tuple(words),
        code_language_rate=sum(1 for info in infos if info) / len(infos) if infos else 1.0,
        text_coverage=_coverage(expected_words, words),
    )


def _html_blocks(outside: Sequence[str]) -> tuple[list[str], list[str]]:
    """The lines outside fences split into Markdown lines and HTML block lines.

    A block is a run of non-blank lines; it is HTML when its first line opens or closes
    a block-level element or is one tag alone (CommonMark's HTML block starts).
    """
    markdown: list[str] = []
    html: list[str] = []
    block: list[str] = []
    for line in [*outside, ""]:
        if line.strip():
            block.append(line)
            continue
        start = _HTML_START.match(block[0]) if block else None
        is_html = bool(block) and (
            (start is not None and start["name"].lower() in _HTML_BLOCK_NAMES)
            or bool(_LONE_TAG.match(block[0]))
        )
        (html if is_html else markdown).extend(block)
        markdown.append(line)
        block = []
    return markdown[:-1], html


def _coverage(expected: Sequence[str], output: Sequence[str]) -> float:
    """The multiset overlap of the output's words with the expected words."""
    if not expected:
        return 1.0
    wanted = Counter(expected)
    found = Counter(output)
    return sum(min(count, found[word]) for word, count in wanted.items()) / len(expected)
