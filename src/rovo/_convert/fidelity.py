"""The Fidelity operations (convert.allium 178): pure, no clock, no network, no file.

`extract` parses a whole document with lxml; `normalize` and `convert` work on the
extracted fragment with the standard library's parser, which never wraps loose text.
The body is measured line by line: fenced code is skipped for every count but the
fences themselves, and inline code is skipped for links, images and words.
"""

import dataclasses
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, CData, Comment, Doctype, Tag
from bs4.element import NavigableString
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
from rovo._convert.profiles import GENERIC
from rovo._unfinished import NotInThisSlice

# The elements each profile's content selection names, tried in order. A selection this
# slice does not implement names none, so extraction takes the whole body
# (ExtractNeverEmptyHanded); the crawl stops before converting with such a profile.
_CONTENT_ELEMENTS: dict[str, tuple[str, ...]] = {GENERIC.content_selection: ("main", "article")}
# What surrounds the content when the whole body stands in for it: the page's chrome.
_WHOLE_BODY_CHROME = ("nav", "header", "footer")
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
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\((?P<target>[^)\s]*)[^)]*\)")
_AUTOLINK = re.compile(r"<(?P<target>https?://[^>\s]+)>")
_LANGUAGE_CLASS = re.compile(r"^(?:language|lang)-(?P<name>.+)$")
_BACKTICKS = re.compile(r"`+")
# The attribute normalize marks a heading with when its id is written as a suffix.
_ANCHOR_MARK = "data-rovo-anchor"

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
    """Realises convert.allium Fidelity.extract (ExtractNeverEmptyHanded, in part).

    The profile's content selection first, else the whole body, flagged later by
    `measure`; the fallback extractor is not chosen yet. Links and images in the content
    are made absolute against the page URL.
    """
    soup = BeautifulSoup(html, "lxml")
    body = soup.body or soup
    document_words = _words(body.get_text(" "))
    selected = _select(body, profile)
    navigation = _navigation_targets(soup, selected, url)
    content: Tag | BeautifulSoup = body if selected is None else selected
    method = ExtractionMethod.profile
    if selected is None:
        method = ExtractionMethod.whole_body
        for chrome in content.find_all(_WHOLE_BODY_CHROME):
            chrome.extract()
    _absolutise(content, url)
    kept = _words(content.get_text(" "))
    return ExtractedContent(
        html=content.decode_contents(),
        title=_title(soup, content, url),
        description=_description(soup, content),
        canonical_url=_canonical(soup, url),
        declared_locale=_attribute(soup.html, "lang") if soup.html else None,
        breadcrumbs=(),
        navigation_targets=navigation,
        method=method,
        has_text=bool(kept),
        extracted_share=len(kept) / len(document_words) if document_words else 1.0,
    )


def normalize(content: ExtractedContent, profile: Profile) -> NormalizedContent:
    """Realises convert.allium Fidelity.normalize (ExpectedAgainstSurvived, BodyShape's h1).

    Exactly one level-one heading: made from the title when the content has none, extra
    ones demoted. The counts are taken over the normalised tree; heading ids are then
    written in the profile's anchor style. This slice's constructs need no island.
    """
    tree = BeautifulSoup(content.html, "html.parser")
    for node in tree.find_all(_NEVER_CONTENT):
        node.decompose()
    for element in tree.descendants:  # A source mark is not a heading id.
        if isinstance(element, Tag):
            element.attrs.pop(_ANCHOR_MARK, None)
    _one_level_one_heading(tree, content.title)
    headings = [heading for heading in tree.find_all(_HEADINGS) if isinstance(heading, Tag)]
    links = [
        link
        for link in tree.find_all("a")
        if isinstance(link, Tag) and _attribute(link, "href") and not _inside(link, _CODE)
    ]
    targets = tuple(
        href
        for link in links
        if (href := _attribute(link, "href")) and urlsplit(href).scheme in _WEB_SCHEMES
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
        tab_panels=0,
        prose_words=tuple(_words(_prose(tree))),
    )
    identified = [element for element in tree.find_all(id=True) if isinstance(element, Tag)]
    if any(element.name not in _HEADINGS for element in identified):
        # An id-only anchor is carried as an island, which the fidelity slice owns.
        raise NotInThisSlice(rule="UncarryableBecomesIsland")
    anchors = frozenset(
        anchor for element in identified if (anchor := _attribute(element, "id")) is not None
    )
    heading_texts = tuple(_text(heading) for heading in headings)
    _write_heading_ids(headings, profile)
    return NormalizedContent(
        fragment=tree.decode(),
        islands=(),
        expected=expected,
        flags=frozenset(),
        anchors=anchors,
        headings=heading_texts,
        link_targets=targets,
        tab_panels_emitted=0,
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
    """Realises convert.allium Fidelity.restore: the identity when there is no island."""
    if islands:
        raise NotInThisSlice(rule="UncarryableBecomesIsland")
    return markdown


def measure(content: ExtractedContent, normalized: NormalizedContent, body: str) -> QualityResult:
    """Realises convert.allium Fidelity.measure (FailedGatesAreFlagged, ScoreIsAFraction).

    Each gate compares the body with the normalised tree's expected counts; the score is
    one minus the weights of the failed gates.
    """
    probe = QualityResult(
        expected=normalized.expected,
        output=_measure_body(body, normalized.expected.prose_words),
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
    for line in _outside_fences(body)[0]:
        text = _INLINE_CODE.sub("", line)
        targets.extend(match["target"] for match in _LINK.finditer(text))
        targets.extend(match["target"] for match in _AUTOLINK.finditer(text))
    return tuple(targets)


def prose_lines(body: str) -> list[str]:
    """The body's lines outside fenced code, with inline code removed."""
    return [_INLINE_CODE.sub("", line) for line in _outside_fences(body)[0]]


def _low_confidence(failed: frozenset[QualityGate], flags: Iterable[QualityFlag]) -> bool:
    return bool(failed) or not CONFIG.incomplete_flags.isdisjoint(flags)


def _is_empty(content: ExtractedContent, body: str) -> bool:
    return not content.has_text or not body.strip()


def _select(body: Tag | BeautifulSoup, profile: Profile) -> Tag | None:
    for name in _CONTENT_ELEMENTS.get(profile.content_selection, ()):
        found = body.find(name)
        if isinstance(found, Tag):
            return found
    return None


def _navigation_targets(
    soup: BeautifulSoup, content: Tag | BeautifulSoup | None, url: str
) -> tuple[str, ...]:
    """Absolute web hrefs of the page's navigation outside the content, order kept."""
    targets: list[str] = []
    for nav in soup.find_all("nav"):
        if not isinstance(nav, Tag) or (content is not None and _within(nav, content)):
            continue
        for link in nav.find_all("a"):
            href = _attribute(link, "href")
            absolute = urljoin(url, href) if href else ""
            if urlsplit(absolute).scheme in _WEB_SCHEMES:
                targets.append(absolute)
    return tuple(dict.fromkeys(targets))


def _within(element: Tag, container: Tag | BeautifulSoup) -> bool:
    return element is container or any(parent is container for parent in element.parents)


def _absolutise(content: Tag | BeautifulSoup, url: str) -> None:
    for element, name in [(link, "href") for link in content.find_all("a")] + [
        (image, "src") for image in content.find_all("img")
    ]:
        value = _attribute(element, name)
        if value and isinstance(element, Tag):
            element[name] = urljoin(url, value)


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
    return urljoin(url, href) if href else None


def _attribute(element: object, name: str) -> str | None:
    """A single-valued attribute of a tag, else None."""
    if not isinstance(element, Tag):
        return None
    value = element.get(name)
    return value.strip() if isinstance(value, str) else None


def _inside(element: Tag, names: tuple[str, ...]) -> bool:
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
    """Heading ids in the profile's anchor style: a `{#id}` suffix for attr."""
    for heading in headings:
        anchor = _attribute(heading, "id")
        if not anchor:
            continue
        if profile.heading_anchor_style is not HeadingAnchorStyle.attr:
            raise NotInThisSlice(rule="BodyShape")
        heading[_ANCHOR_MARK] = anchor


class _Converter(MarkdownConverter):
    """markdownify, with the id suffix and the code text written verbatim, never escaped."""

    def convert_hN(self, n: int, el: Tag, text: str, parent_tags: set[str]) -> str:  # noqa: N802  markdownify's hook name.
        """An ATX heading, its `{#id}` suffix when normalize marked one."""
        if "_inline" in parent_tags:
            return text
        anchor = _attribute(el, _ANCHOR_MARK)
        suffix = "" if anchor is None else f" {{#{anchor}}}"
        return f"\n\n{'#' * max(1, min(6, n))} {' '.join(text.split())}{suffix}\n\n"

    def convert_pre(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        """A fence around the code text, longer than any backtick run in it."""
        del text, parent_tags
        code = _code_text(el)
        if not code:
            return ""
        longest = max((len(run) for run in _BACKTICKS.findall(code)), default=0)
        fence = "`" * max(3, longest + 1)
        language = _code_language(el) or ""
        ending = "" if code.endswith("\n") else "\n"
        return f"\n\n{fence}{language}\n{code}{ending}{fence}\n\n"


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


def _measure_body(body: str, expected_words: Sequence[str]) -> OutputMeasurement:
    outside, infos = _outside_fences(body)
    prose = [_INLINE_CODE.sub("", line) for line in outside]
    tables, cells = _tables(outside)
    words = [word for line in prose for word in _words(_IMAGE.sub(" ", line))]
    return OutputMeasurement(
        code_blocks=len(infos),
        tables=tables,
        table_cells=cells,
        headings=sum(1 for line in outside if _ATX_HEADING.match(line)),
        links=sum(len(_LINK.findall(line)) + len(_AUTOLINK.findall(line)) for line in prose),
        images=sum(len(_IMAGE.findall(line)) for line in prose),
        list_items=sum(1 for line in outside if _LIST_ITEM.match(line)),
        words=tuple(words),
        code_language_rate=sum(1 for info in infos if info) / len(infos) if infos else 1.0,
        text_coverage=_coverage(expected_words, words),
    )


def _coverage(expected: Sequence[str], output: Sequence[str]) -> float:
    """The multiset overlap of the output's words with the expected words."""
    if not expected:
        return 1.0
    wanted = Counter(expected)
    found = Counter(output)
    return sum(min(count, found[word]) for word, count in wanted.items()) / len(expected)
