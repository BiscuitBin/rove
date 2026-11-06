"""The convert value types and enumerations (convert.allium), as frozen dataclasses."""

import enum
from dataclasses import dataclass


class QualityGate(enum.Enum):
    """The ten quality gates, measured against the extracted main content."""

    text_coverage = "text_coverage"
    code_blocks = "code_blocks"
    code_lang_rate = "code_lang_rate"
    tables = "tables"
    table_cells = "table_cells"
    headings = "headings"
    links = "links"
    images = "images"
    list_items = "list_items"
    tabs_expanded = "tabs_expanded"


class QualityFlag(enum.Enum):
    """Every page flag: gate, extraction, normalisation, fetch and link flags."""

    text_coverage = "text_coverage"
    code_blocks = "code_blocks"
    code_lang_rate = "code_lang_rate"
    tables = "tables"
    table_cells = "table_cells"
    headings = "headings"
    links = "links"
    images = "images"
    list_items = "list_items"
    tabs_expanded = "tabs_expanded"
    extractor_fallback = "extractor_fallback"
    whole_body_extracted = "whole_body_extracted"
    extracted_share = "extracted_share"
    empty_content = "empty_content"
    interactive_omitted = "interactive_omitted"
    html_table_kept = "html_table_kept"
    fidelity_loss = "fidelity_loss"
    render_needed = "render_needed"
    soft_block_suspected = "soft_block_suspected"
    uncrawled_internal = "uncrawled_internal"
    unresolved_fragment = "unresolved_fragment"
    dangling_inbound = "dangling_inbound"


class ExtractionMethod(enum.Enum):
    """How the main content was found."""

    profile = "profile"
    fallback = "fallback"
    whole_body = "whole_body"


class HeadingAnchorStyle(enum.Enum):
    """How a heading's id is written."""

    attr = "attr"
    inline = "inline"


@dataclass(frozen=True, kw_only=True)
class VersionMapping:
    """One raw value to label entry of a profile's version mapping."""

    raw: str
    label: str


@dataclass(frozen=True, kw_only=True)
class ExpectedCounts:
    """What normalisation says the Markdown must carry."""

    code_blocks: int
    tables: int
    table_cells: int
    headings: int
    links: int
    images: int
    list_items: int
    tab_panels: int
    prose_words: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class Island:
    """A chunk Markdown cannot carry, cut out before conversion and restored after."""

    payload: str
    carries_markdown: bool


@dataclass(frozen=True, kw_only=True)
class NormalizedContent:
    """The normalised tree with its islands replaced by tokens."""

    fragment: str
    islands: tuple[Island, ...]
    expected: ExpectedCounts
    flags: frozenset[QualityFlag]
    anchors: frozenset[str]
    headings: tuple[str, ...]
    link_targets: tuple[str, ...]
    tab_panels_emitted: int


@dataclass(frozen=True, kw_only=True)
class OutputMeasurement:
    """The element classes counted on the produced Markdown body."""

    code_blocks: int
    tables: int
    table_cells: int
    headings: int
    links: int
    images: int
    list_items: int
    words: tuple[str, ...]
    code_language_rate: float
    text_coverage: float


@dataclass(frozen=True, kw_only=True)
class QualityResult:
    """The measured result of one conversion."""

    expected: ExpectedCounts
    output: OutputMeasurement
    tab_panels_emitted: int
    failed: frozenset[QualityGate]
    score: float
    flags: frozenset[QualityFlag]
    low_confidence: bool

    @property
    def text_coverage_passes(self) -> bool:
        """Text coverage reaches config.text_coverage_gate."""
        return self.output.text_coverage >= CONFIG.text_coverage_gate

    @property
    def code_blocks_passes(self) -> bool:
        """As many fences as expected code blocks."""
        return self.output.code_blocks == self.expected.code_blocks

    @property
    def code_lang_rate_passes(self) -> bool:
        """The share of fences naming a language reaches config.lang_rate_gate."""
        return self.output.code_language_rate >= CONFIG.lang_rate_gate

    @property
    def tables_passes(self) -> bool:
        """As many tables as expected."""
        return self.output.tables == self.expected.tables

    @property
    def table_cells_passes(self) -> bool:
        """As many table cells as expected."""
        return self.output.table_cells == self.expected.table_cells

    @property
    def headings_passes(self) -> bool:
        """As many headings as expected."""
        return self.output.headings == self.expected.headings

    @property
    def links_passes(self) -> bool:
        """No links expected, or at least config.ratio_gate of them."""
        return _ratio_passes(self.output.links, self.expected.links)

    @property
    def images_passes(self) -> bool:
        """As many images as expected."""
        return self.output.images == self.expected.images

    @property
    def list_items_passes(self) -> bool:
        """No list items expected, or at least config.ratio_gate of them."""
        return _ratio_passes(self.output.list_items, self.expected.list_items)

    @property
    def tabs_expanded_passes(self) -> bool:
        """Panels emitted equal panels found."""
        return self.tab_panels_emitted == self.expected.tab_panels

    @property
    def all_gates_pass(self) -> bool:
        """No gate failed."""
        return not self.failed

    @property
    def has_incomplete_flag(self) -> bool:
        """A flag is in config.incomplete_flags."""
        return not self.flags.isdisjoint(CONFIG.incomplete_flags)


def _ratio_passes(output: int, expected: int) -> bool:
    """None expected, or at least config.ratio_gate of the expected count survived."""
    return expected == 0 or output >= CONFIG.ratio_gate * expected


@dataclass(frozen=True, kw_only=True)
class ExtractedContent:
    """The main content of one page, as extraction found it."""

    html: str
    title: str
    description: str
    canonical_url: str | None
    declared_locale: str | None
    breadcrumbs: tuple[str, ...]
    navigation_targets: tuple[str, ...]
    method: ExtractionMethod
    has_text: bool
    extracted_share: float


@dataclass(frozen=True, kw_only=True)
class ConvertedContent:
    """The product of one conversion, before the mirror stores it."""

    body: str
    title: str
    description: str
    canonical_url: str | None
    declared_locale: str | None
    breadcrumbs: tuple[str, ...]
    navigation_targets: tuple[str, ...]
    method: ExtractionMethod
    anchors: frozenset[str]
    headings: tuple[str, ...]
    link_targets: tuple[str, ...]
    quality: QualityResult
    is_empty: bool


@dataclass(frozen=True, kw_only=True)
class Profile:
    """Platform knowledge as data."""

    name: str
    hosts: frozenset[str]
    content_selection: str
    meaningful_query_params: tuple[str, ...]
    sitemap_include: tuple[str, ...]
    version_param: str | None
    version_map: tuple[VersionMapping, ...]
    version_default: str | None
    locale_codes: frozenset[str]
    heading_anchor_style: HeadingAnchorStyle

    @property
    def has_versions(self) -> bool:
        """The profile names a version parameter."""
        return self.version_param is not None


@dataclass(frozen=True, kw_only=True)
class ConvertConfig:
    """convert.allium's config block: fixed in code; a profile cannot override a gate."""

    text_coverage_gate: float
    ratio_gate: float
    lang_rate_gate: float
    extracted_share_gate: float
    weight_text_coverage: float
    weight_code_blocks: float
    weight_headings: float
    weight_links: float
    weight_tables: float
    weight_table_cells: float
    weight_code_lang_rate: float
    weight_minor: float
    incomplete_flags: frozenset[QualityFlag]
    description_max_chars: int


# convert.allium's config block (convert.allium 346 to 368), the one copy in code.
CONFIG = ConvertConfig(
    text_coverage_gate=0.97,
    ratio_gate=0.98,
    lang_rate_gate=0.90,
    extracted_share_gate=0.30,
    weight_text_coverage=0.40,
    weight_code_blocks=0.15,
    weight_headings=0.10,
    weight_links=0.10,
    weight_tables=0.075,
    weight_table_cells=0.075,
    weight_code_lang_rate=0.05,
    weight_minor=0.05 / 3,
    incomplete_flags=frozenset(
        {
            QualityFlag.render_needed,
            QualityFlag.empty_content,
            QualityFlag.soft_block_suspected,
            QualityFlag.extractor_fallback,
            QualityFlag.whole_body_extracted,
        }
    ),
    description_max_chars=200,
)

# Each gate's weight in the score; the weights sum to one (ScoreIsAFraction).
GATE_WEIGHTS: dict[QualityGate, float] = {
    QualityGate.text_coverage: CONFIG.weight_text_coverage,
    QualityGate.code_blocks: CONFIG.weight_code_blocks,
    QualityGate.code_lang_rate: CONFIG.weight_code_lang_rate,
    QualityGate.tables: CONFIG.weight_tables,
    QualityGate.table_cells: CONFIG.weight_table_cells,
    QualityGate.headings: CONFIG.weight_headings,
    QualityGate.links: CONFIG.weight_links,
    QualityGate.images: CONFIG.weight_minor,
    QualityGate.list_items: CONFIG.weight_minor,
    QualityGate.tabs_expanded: CONFIG.weight_minor,
}
