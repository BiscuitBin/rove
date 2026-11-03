"""The profile catalogue (convert.allium 363 to 403) and convert's config block, as data."""

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
