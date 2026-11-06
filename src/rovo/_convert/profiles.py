"""The profile catalogue (convert.allium 376 to 416) and convert's config block, as data.

`content_selection` is opaque by specification (convert.allium 329); `SELECTIONS` says,
keyed by that string, which elements hold a platform's content, breadcrumbs, tab groups
and callouts, as CSS selectors. No code branches on a host name
(ProfilesAreTheOnlyPlatformKnowledge): a profile's selection is data.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

from rovo._convert.model import CONFIG as CONVERT_CONFIG
from rovo._convert.model import ConvertConfig, HeadingAnchorStyle, Profile, VersionMapping

CONFIG: ConvertConfig = CONVERT_CONFIG

GENERIC = Profile(
    name="generic",
    hosts=frozenset(),
    content_selection="generic: main or article; password-form login wall",
    meaningful_query_params=(),
    sitemap_include=(),
    version_param=None,
    version_map=(),
    version_default=None,
    locale_codes=frozenset(),
    heading_anchor_style=HeadingAnchorStyle.attr,
)

MSLEARN = Profile(
    name="mslearn",
    hosts=frozenset({"learn.microsoft.com"}),
    content_selection="mslearn: Learn article content and its tab groups",
    meaningful_query_params=("view",),
    sitemap_include=("*/sitemapindex.xml", "*/{section}_{locale}_*.xml"),
    version_param="view",
    version_map=(
        VersionMapping(raw="graph-rest-1.0", label="v1.0"),
        VersionMapping(raw="graph-rest-beta", label="beta"),
    ),
    version_default="v1.0",
    locale_codes=frozenset({"en-us", "en-gb", "de-de", "fr-fr", "ja-jp", "zh-cn"}),
    heading_anchor_style=HeadingAnchorStyle.attr,
)

DEVSITE = Profile(
    name="devsite",
    hosts=frozenset({"developers.google.com"}),
    content_selection="devsite: DevSite article content and its tab selectors",
    meaningful_query_params=(),
    sitemap_include=(),
    version_param=None,
    version_map=(),
    version_default=None,
    locale_codes=frozenset({"en", "de", "fr", "ja", "zh-cn"}),
    heading_anchor_style=HeadingAnchorStyle.attr,
)

CATALOGUE: tuple[Profile, ...] = (GENERIC, MSLEARN, DEVSITE)


def profile_named(name: str) -> Profile | None:
    """The catalogue profile with this name, else None."""
    return next((profile for profile in CATALOGUE if profile.name == name), None)


def profile_for(site_url: str, profile_name: str | None) -> Profile | None:
    """Realises rovo.allium profile_for: the named profile, else the host's, else generic.

    An unknown name is None. The host is matched as data against each profile's hosts,
    never by a branch on a host name (ProfilesAreTheOnlyPlatformKnowledge).
    """
    if profile_name is not None:
        return profile_named(profile_name)
    host = (urlsplit(site_url).hostname or "").lower()
    return next((profile for profile in CATALOGUE if host in profile.hosts), GENERIC)


@dataclass(frozen=True, kw_only=True)
class TabSelection:
    """Where a platform's tab groups are, as CSS selectors.

    `panels` and `labels` are read relative to the group, in source order. With no
    `labels`, a panel's label is its first heading, else its `title` attribute.
    """

    groups: str
    panels: str
    labels: str | None


@dataclass(frozen=True, kw_only=True)
class Selection:
    """What a content selection names: content (in order), chrome, breadcrumbs, tabs, callouts.

    `chrome` is what whole-body extraction strips. Each callout pairs a selector with the
    GFM alert kind it becomes, the first match winning.
    """

    content: tuple[str, ...]
    chrome: str = "nav, header, footer"
    breadcrumbs: str | None = None
    tabs: TabSelection | None = None
    callouts: tuple[tuple[str, str], ...] = ()


# One entry per catalogue profile's content selection. The selectors follow each
# platform's published markup conventions; no profile is called supported here
# (convert.allium's third open question).
SELECTIONS: dict[str, Selection] = {
    GENERIC.content_selection: Selection(content=("main", "article")),
    DEVSITE.content_selection: Selection(
        content=(".devsite-article-body",),
        chrome="devsite-header, devsite-book-nav, devsite-footer-utility, nav, header, footer",
        breadcrumbs=".devsite-breadcrumb-list > li",
        tabs=TabSelection(groups="devsite-selector", panels=":scope > section", labels=None),
        callouts=(
            ("aside.note", "NOTE"),
            ("aside.caution", "CAUTION"),
            ("aside.warning", "WARNING"),
        ),
    ),
    MSLEARN.content_selection: Selection(
        content=("main div.content",),
        tabs=TabSelection(
            groups="div.tabGroup",
            panels=":scope > section[role=tabpanel]",
            labels=":scope [role=tab]",
        ),
        callouts=(
            ("div.alert.is-success", "TIP"),
            ("div.alert.is-primary", "IMPORTANT"),
            ("div.alert.is-warning", "WARNING"),
            ("div.alert.is-danger", "CAUTION"),
            ("div.alert", "NOTE"),
        ),
    ),
}
# A selection the table does not know selects nothing: extraction takes the whole body.
_NOTHING = Selection(content=())


def selection_of(profile: Profile) -> Selection:
    """The selection a profile's content_selection names; nothing for an unknown one."""
    return SELECTIONS.get(profile.content_selection, _NOTHING)
