"""Configuration layers for the command (rovo.allium): serves the command and the root.

The layers are the built-in defaults, `<out>/rovo.toml`, the ROVO_<SECTION>__<FIELD>
environment variables and the --set flags, a later layer winning key by key. May import the
modules below it; never rovo._commands or rovo.cli.
"""

import enum
import hashlib
import ipaddress
import json
import math
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from rovo._convert.model import Profile
from rovo._convert.profiles import profile_for, profile_named
from rovo._crawl.model import (
    CrawlPolicy,
    RenderMode,
    RobotsMode,
    StealthMode,
    standard_policy,
)
from rovo._mirror.model import CONFIG as MIRROR_CONFIG
from rovo._mirror.model import CrawlScope
from rovo._mirror.urls import hostname_of, is_http_url

_HASH_CHARS = 16
_CONFIG_FILE = "rovo.toml"
_ENV_PREFIX = "ROVO_"


@dataclass(frozen=True, kw_only=True)
class RootConfig:
    """rovo.allium's config block."""

    report_percentile: float
    render_mode: RenderMode
    max_depth: int
    fail_on_low_quality: bool
    refollow_unchanged_links: bool


# rovo.allium's config block (rovo.allium 254 to 263), the one copy in code.
CONFIG = RootConfig(
    report_percentile=0.10,
    render_mode=RenderMode.never,
    max_depth=10,
    fail_on_low_quality=False,
    refollow_unchanged_links=True,
)


@dataclass(frozen=True, kw_only=True)
class Configuration:
    """The resolved configuration of one mirror (rovo.allium 73)."""

    valid: bool
    problems: tuple[str, ...]
    hash: str
    root_url: str | None
    start_urls: tuple[str, ...]
    allowed_hosts: frozenset[str]
    path_prefixes: tuple[str, ...]
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    max_depth: int
    locale: str | None
    meaningful_query_params: tuple[str, ...]
    profile_name: str
    robots: RobotsMode
    render_mode: RenderMode
    stealth_mode: StealthMode
    max_age: timedelta | None
    fail_on_low_quality: bool
    unblocking_provider: str | None
    refollow_unchanged_links: bool = CONFIG.refollow_unchanged_links
    prune: bool = MIRROR_CONFIG.prune

    @property
    def has_seeds(self) -> bool:
        """A root URL or a start URL."""
        return self.root_url is not None or bool(self.start_urls)

    def root_changed(self, recorded: str | None) -> bool:
        """A recorded root URL that differs from this one."""
        return recorded is not None and recorded != self.root_url

    @property
    def needs_browser(self) -> bool:
        """render_mode is not never."""
        return self.render_mode is not RenderMode.never

    @property
    def needs_stealth(self) -> bool:
        """stealth_mode is on."""
        return self.stealth_mode is StealthMode.on


@dataclass(frozen=True, kw_only=True)
class SyncOptions:
    """What one sync invocation asked for, beyond the configuration (rovo.allium 103)."""

    dry_run: bool
    confirmed: bool
    interactive: bool
    json_events: bool
    urls: tuple[str, ...]
    paths: tuple[str, ...]
    owner_test: None = None

    @property
    def targeted(self) -> bool:
        """URLs or paths were named."""
        return bool(self.urls) or bool(self.paths)

    @property
    def is_owner_testing(self) -> bool:
        """An owner-testing request."""
        return self.owner_test is not None


def config_path(out_dir: Path) -> Path:
    """<out>/rovo.toml."""
    return out_dir / _CONFIG_FILE


def starter_config(site_url: str, profile: Profile) -> str:
    """The rovo.toml init writes: every section and key, with its default.

    The standard library reads TOML and writes none, so this is a template; every
    string is written JSON-quoted, which TOML reads as a basic string.
    """
    scope = initial_scope(site_url, profile)
    return f"""# The configuration of one rovo mirror. A key left out takes its built-in default.

[site]
root_url = {_toml(scope.root_url)}
start_urls = {_toml(list(scope.start_urls))}

[scope]
allowed_hosts = {_toml(sorted(scope.allowed_hosts))}
path_prefixes = {_toml(list(scope.path_prefixes))}
include = []
exclude = []
max_depth = {scope.max_depth}
# locale = "en"  # Pin one locale; absent, no locale is pinned.
meaningful_query_params = []

[conversion]
profile = {_toml(profile.name)}

[crawl]
robots = {_toml(RobotsMode.respect.value)}
render_mode = {_toml(CONFIG.render_mode.value)}
stealth_mode = {_toml(StealthMode.off.value)}
# max_age = 86400  # Seconds before a page is refetched unconditionally; absent, never.
refollow_unchanged_links = {_toml(CONFIG.refollow_unchanged_links)}

[quality]
fail_on_low_quality = {_toml(CONFIG.fail_on_low_quality)}

[mirror]
prune = {_toml(MIRROR_CONFIG.prune)}  # Delete a removed page's file instead of archiving it.

[unblocking]
# provider is reserved: any value is a configuration problem.
"""


def resolve_config(
    out_dir: Path,
    environ: Mapping[str, str] | None = None,
    overrides: Sequence[str] = (),
) -> Configuration:
    """Realises rovo.allium resolve_config: defaults, rovo.toml, variables, then flags.

    The layers merge key by key, a later one winning: the built-in defaults, rovo.toml,
    each `ROVO_<SECTION>__<FIELD>` variable of `environ` (section and field matched
    case-insensitively; a ROVO_ name without `__` is not a configuration variable), then
    each `SECTION.FIELD=VALUE` override (--set). A variable or flag value is read as one
    TOML value, else as the raw string. Invalid, with every bad key path in `problems`,
    for an unreadable or unparsable file, an unknown section or key, a value of the
    wrong type or outside its enum from any layer, a malformed --set, or a profile the
    catalogue lacks.
    """
    problems: list[str] = []
    try:
        document = tomllib.loads(config_path(out_dir).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        document = {}
        problems.append(f"{_CONFIG_FILE}: {error}")
    entries = [*_file_entries(document), *_variable_entries(environ or {})]
    entries.extend(_flag_entries(overrides, problems))
    values = _read_entries(entries, problems)
    settings = _with_defaults(values)
    if profile_named(settings["profile_name"]) is None:
        problems.append(f"conversion.profile: no profile named {settings['profile_name']!r}")
    return Configuration(
        valid=not problems,
        problems=tuple(problems),
        hash=_digest(settings),
        **settings,
    )


def initial_scope(site_url: str, profile: Profile) -> CrawlScope:
    """rovo.allium initial_scope: the scope init derives from the site URL.

    The root URL keeps the locale (a first segment the profile lists as one) and the
    first product segment; start_urls holds the given URL; allowed_hosts its host;
    path_prefixes its directory.
    """
    parts = urlsplit(site_url)
    directory = _directory(parts.path)
    segments = [segment for segment in directory.split("/") if segment]
    kept = 2 if segments and segments[0] in profile.locale_codes else 1
    root_path = "/" + "".join(f"{segment}/" for segment in segments[:kept])
    return CrawlScope(
        root_url=f"{parts.scheme}://{parts.netloc}{root_path}",
        start_urls=(site_url,),
        allowed_hosts=frozenset({hostname_of(site_url)}),
        path_prefixes=(directory,),
        include=(),
        exclude=(),
        max_depth=CONFIG.max_depth,
        locale=None,
        meaningful_query_params=profile.meaningful_query_params,
        locale_codes=profile.locale_codes,
    )


def scope_of(settings: Configuration, profile: Profile) -> CrawlScope:
    """rovo.allium scope_of: the one CrawlScope a configuration and its profile give.

    allowed_hosts and path_prefixes default to the first seed's host and directory; the
    profile's meaningful query parameters apply when the configuration names none.
    """
    first = settings.start_urls[0] if settings.start_urls else settings.root_url or ""
    return CrawlScope(
        root_url=settings.root_url,
        start_urls=settings.start_urls,
        allowed_hosts=settings.allowed_hosts or frozenset({hostname_of(first)}),
        path_prefixes=settings.path_prefixes or (_directory(urlsplit(first).path),),
        include=settings.include,
        exclude=settings.exclude,
        max_depth=settings.max_depth,
        locale=settings.locale,
        meaningful_query_params=(
            settings.meaningful_query_params or profile.meaningful_query_params
        ),
        locale_codes=profile.locale_codes,
    )


def signature_of(scope: CrawlScope, profile: Profile) -> str:
    """rovo.allium signature_of: the digest of the conversion settings and the profile.

    The profile and the pinned locale, which reaches every page's frontmatter; never
    budgets or seeds.
    """
    return _digest({"profile": asdict(profile), "locale": scope.locale})


def scope_hash(scope: CrawlScope) -> str:
    """rovo.allium scope_hash: root and start URLs, hosts, filters, locale, depth."""
    return _digest(
        {
            "root_url": scope.root_url,
            "start_urls": list(scope.start_urls),
            "allowed_hosts": sorted(scope.allowed_hosts),
            "path_prefixes": list(scope.path_prefixes),
            "include": list(scope.include),
            "exclude": list(scope.exclude),
            "meaningful_query_params": list(scope.meaningful_query_params),
            "locale": scope.locale,
            "max_depth": scope.max_depth,
        }
    )


def effective_policy(settings: Configuration) -> CrawlPolicy:
    """rovo.allium effective_policy, with no owner options: the standard policy afresh."""
    del settings  # Only owner options change the policy, and this slice has none.
    return standard_policy()


def encode_configuration(settings: Configuration) -> dict[str, object]:
    """A Configuration as JSON: sets sorted, enums by value, max_age in seconds."""
    return {
        "valid": settings.valid,
        "problems": list(settings.problems),
        "hash": settings.hash,
        **_jsonable(_settings_of(settings)),
    }


# --- Reading rovo.toml ----------------------------------------------------------------

_BAD = object()


# One layer's setting: its section, its key (None for a section that is no table), its value.
_Entry = tuple[str, str | None, object]


def _file_entries(document: dict[str, Any]) -> list[_Entry]:
    """rovo.toml's settings, in file order."""
    entries: list[_Entry] = []
    for section, table in document.items():
        if isinstance(table, dict):
            entries.extend((section, key, value) for key, value in table.items())
        else:
            entries.append((section, None, table))
    return entries


def _variable_entries(environ: Mapping[str, str]) -> list[_Entry]:
    """Each ROVO_<SECTION>__<FIELD> variable; any other name is ignored."""
    entries: list[_Entry] = []
    for name, raw in environ.items():
        section, separator, key = name.partition("__")
        if separator and section.upper().startswith(_ENV_PREFIX):
            entries.append((section[len(_ENV_PREFIX) :].lower(), key.lower(), _value(raw)))
    return entries


def _flag_entries(overrides: Sequence[str], problems: list[str]) -> list[_Entry]:
    """Each --set SECTION.FIELD=VALUE; a malformed one is a problem."""
    entries: list[_Entry] = []
    for flag in overrides:
        path, equals, raw = flag.partition("=")
        section, dot, key = path.partition(".")
        if equals and dot:
            entries.append((section, key, _value(raw)))
        else:
            problems.append(f"--set {flag!r}: expected SECTION.FIELD=VALUE")
    return entries


def _read_entries(entries: Sequence[_Entry], problems: list[str]) -> dict[str, Any]:
    """The settings by field, a later entry winning; each bad one named in `problems`."""
    values: dict[str, Any] = {}
    for section, key, value in entries:
        keys = _SCHEMA.get(section)
        if keys is None or key is None:
            problems.append(f"{section}: unknown section")
            continue
        reader = keys.get(key)
        parsed = reader[1](value) if reader is not None else _BAD
        if reader is None:
            problems.append(f"{section}.{key}: unknown key")
        elif parsed is _BAD:
            problems.append(f"{section}.{key}: invalid value {value!r}")
        else:
            values[reader[0]] = parsed
    return values


def _value(raw: str) -> object:
    """A variable's or flag's value: one TOML value, else the raw string."""
    try:
        return tomllib.loads(f"value = {raw}")["value"]
    except tomllib.TOMLDecodeError:
        return raw


def _string(value: object) -> object:
    return value if isinstance(value, str) else _BAD


def _strings(value: object) -> object:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    return _BAD


def _url(value: object) -> object:
    """An http or https URL with a host."""
    return value if isinstance(value, str) and is_http_url(value) else _BAD


def _urls(value: object) -> object:
    if not isinstance(value, list) or any(_url(item) is _BAD for item in value):
        return _BAD
    return tuple(value)


def _host_url(host: str) -> str:
    """An http URL for a configured host; a bare IPv6 literal goes back in brackets.

    `rovo init` writes the seed's `hostname_of`, which drops an IPv6 literal's brackets.
    """
    try:
        ipaddress.IPv6Address(host)
    except ValueError:
        return f"http://{host}"
    return f"http://[{host}]"


def _hosts(value: object) -> object:
    """Host names, lower-cased, port dropped; one that does not parse is bad."""
    if _strings(value) is _BAD or not isinstance(value, list):
        return _BAD
    urls = [_host_url(host) for host in value]
    if not all(is_http_url(url) for url in urls):
        return _BAD
    return frozenset(hostname_of(url) for url in urls)


def _integer(value: object) -> object:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else _BAD


def _boolean(value: object) -> object:
    return value if isinstance(value, bool) else _BAD


def _seconds(value: object) -> object:
    """A finite, non-negative number of seconds that fits a timedelta."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return _BAD
    if (isinstance(value, float) and not math.isfinite(value)) or value < 0:
        return _BAD
    try:
        return timedelta(seconds=value)
    except OverflowError:
        return _BAD


def _member(kind: type[enum.Enum]) -> Callable[[object], object]:
    def read(value: object) -> object:
        names = {member.value for member in kind}
        return kind(value) if isinstance(value, str) and value in names else _BAD

    return read


# Each section's keys: the Configuration field and the reader of its value.
_SCHEMA: dict[str, dict[str, tuple[str, Callable[[object], object]]]] = {
    "site": {"root_url": ("root_url", _url), "start_urls": ("start_urls", _urls)},
    "scope": {
        "allowed_hosts": ("allowed_hosts", _hosts),
        "path_prefixes": ("path_prefixes", _strings),
        "include": ("include", _strings),
        "exclude": ("exclude", _strings),
        "max_depth": ("max_depth", _integer),
        "locale": ("locale", _string),
        "meaningful_query_params": ("meaningful_query_params", _strings),
    },
    "conversion": {"profile": ("profile_name", _string)},
    "crawl": {
        "robots": ("robots", _member(RobotsMode)),
        "render_mode": ("render_mode", _member(RenderMode)),
        "stealth_mode": ("stealth_mode", _member(StealthMode)),
        "max_age": ("max_age", _seconds),
        "refollow_unchanged_links": ("refollow_unchanged_links", _boolean),
    },
    "quality": {"fail_on_low_quality": ("fail_on_low_quality", _boolean)},
    "mirror": {"prune": ("prune", _boolean)},
    "unblocking": {"provider": ("unblocking_provider", _string)},
}


def _with_defaults(values: dict[str, Any]) -> dict[str, Any]:
    """The built-in defaults, overridden key by key by the file's values."""
    start_urls: tuple[str, ...] = values.get("start_urls", ())
    root_url: str | None = values.get("root_url")
    seed = start_urls[0] if start_urls else root_url
    default_profile = profile_for(seed, None) if seed is not None else None
    defaults: dict[str, Any] = {
        "root_url": None,
        "start_urls": (),
        "allowed_hosts": frozenset(),
        "path_prefixes": (),
        "include": (),
        "exclude": (),
        "max_depth": CONFIG.max_depth,
        "locale": None,
        "meaningful_query_params": (),
        "profile_name": "generic" if default_profile is None else default_profile.name,
        "robots": RobotsMode.respect,
        "render_mode": CONFIG.render_mode,
        "stealth_mode": StealthMode.off,
        "max_age": None,
        "refollow_unchanged_links": CONFIG.refollow_unchanged_links,
        "fail_on_low_quality": CONFIG.fail_on_low_quality,
        "unblocking_provider": None,
        "prune": MIRROR_CONFIG.prune,
    }
    return defaults | values


def _settings_of(settings: Configuration) -> dict[str, Any]:
    return {
        name: value
        for name, value in vars(settings).items()
        if name not in {"valid", "problems", "hash"}
    }


def _jsonable(values: dict[str, Any]) -> dict[str, object]:
    return {name: _canonical(value) for name, value in values.items()}


def _canonical(value: object) -> object:
    """A value as JSON: sets sorted, tuples as lists, enums by value, durations in seconds."""
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (frozenset, set)):
        return sorted((_canonical(item) for item in value), key=json.dumps)
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _digest(values: dict[str, Any]) -> str:
    """The first 16 hex digits of the SHA-256 of the values as canonical JSON."""
    canonical = json.dumps(_jsonable(values), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:_HASH_CHARS]


def _directory(path: str) -> str:
    """The directory of a URL path, with a trailing slash."""
    if not path or path.endswith("/"):
        return path or "/"
    parent = str(PurePosixPath(path).parent)
    return parent if parent.endswith("/") else f"{parent}/"


def _toml(value: object) -> str:
    """One TOML value: JSON's strings, lists and booleans are TOML's."""
    return json.dumps(value, ensure_ascii=False)
