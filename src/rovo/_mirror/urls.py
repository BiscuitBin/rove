"""URL identity and path assignment (mirror.allium): pure functions."""

import fnmatch
import hashlib
import re
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

if TYPE_CHECKING:
    from rovo._convert.model import Profile
    from rovo._mirror.model import Mirror, Page

_DEFAULT_PORTS = {"http": 80, "https": 443}
_WEB_SCHEMES = frozenset(_DEFAULT_PORTS)
_SEGMENT_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
_HOST_UNSAFE = re.compile(r"[^a-z0-9.-]")
_PAGE_SUFFIXES = (".html", ".htm", ".aspx")
_PAGES_ROOT = "pages/"
# The managed root files a directory segment is never named like (ignoring case).
_MANAGED_ROOT_FILES = frozenset(
    {"llms.txt", "index.jsonl", "links.jsonl", "crawl-report.json", "rovo.toml"}
)
# Names Windows reserves for devices, compared ignoring case on the part before the
# first ".".
_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)
_SUFFIX_ROOM = 10
_PAGE_EXTENSION = ".md"
_REGEX_PREFIX = "re:"


def normalise_url(url: str, meaningful_query_params: tuple[str, ...]) -> str:
    """The URL's identity, per the identity comment (mirror.allium 113 to 118).

    Lower-case scheme and host, a host's trailing "." dropped, default port dropped, dot
    segments resolved, a trailing index.html folded into "/", only meaningful query
    parameters kept and sorted, the fragment dropped, a trailing slash kept.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower().removesuffix(".")
    if ":" in host:  # An IPv6 literal keeps the brackets urlsplit took off.
        host = f"[{host}]"
    port = parts.port
    netloc = host if port is None or _DEFAULT_PORTS.get(scheme) == port else f"{host}:{port}"
    path = _remove_dot_segments(parts.path or "/")
    if path.endswith("/index.html"):
        path = path[: -len("index.html")]
    query = urlencode(
        sorted(
            (name, value)
            for name, value in parse_qsl(parts.query, keep_blank_values=True)
            if name in meaningful_query_params
        )
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def is_http_url(url: str) -> bool:
    """rovo.allium is_http_url: an http or https URL with a host, that parses.

    A URL `urlsplit` cannot take (an unclosed IPv6 bracket) or with a port out of range
    is not one.
    """
    try:
        parts = urlsplit(url)
        _ = parts.port
    except ValueError:
        return False
    return parts.scheme.lower() in _WEB_SCHEMES and bool(parts.hostname)


def hostname_of(url: str) -> str:
    """The URL's host name, lower-cased, port and a trailing "." dropped.

    The trailing "." goes as it does from an identity (mirror.allium 113 to 120), so a
    host named with one is allowed by the scope its own identity is checked against.
    """
    return (urlsplit(url).hostname or "").lower().removesuffix(".")


def scheme_of(url: str) -> str:
    """The URL's scheme, lower-cased."""
    return urlsplit(url).scheme.lower()


def origin_of(url: str) -> str:
    """scheme://host[:port] of the URL, the default port dropped."""
    identity = normalise_url(url, ())
    parts = urlsplit(identity)
    return f"{parts.scheme}://{parts.netloc}"


def path_of(url: str) -> str:
    """The URL's path."""
    return urlsplit(url).path or "/"


def first_path_segment(url: str) -> str:
    """The first segment of the URL's path, empty for the root."""
    return path_of(url).lstrip("/").split("/", 1)[0]


def pattern_matches(identity: str, pattern: str) -> bool:
    """A glob over the identity, or a regular expression when prefixed `re:`."""
    if pattern.startswith(_REGEX_PREFIX):
        return re.search(pattern[len(_REGEX_PREFIX) :], identity) is not None
    return fnmatch.fnmatchcase(identity, pattern)


def digest(text: str) -> str:
    """The lowercase SHA-256 hex of the text's UTF-8 bytes."""
    return hashlib.sha256(text.encode()).hexdigest()


def version_label(profile: "Profile", identity: str) -> str | None:
    """Page.version for the identity (StoreNewPage guidance, mirror.allium 827 to 832).

    Null when the profile has no version_param; the path's label (`_path_label`) when the
    identity carries it; otherwise the profile's version_default.
    """
    if profile.version_param is None:
        return None
    label = _path_label(profile, identity)
    return profile.version_default if label is None else label


def _path_label(profile: "Profile", identity: str) -> str | None:
    """The label assign_path appends (MovePage guidance, mirror.allium 688 to 702).

    Only an identity carrying the profile's version_param has one: the value mapped
    through version_map, else the raw value, either one with every character outside
    [A-Za-z0-9._-] replaced with "-". The raw value is read decoded, as parse_qsl gives
    it (the T17 follow-up batched question).
    """
    if profile.version_param is None:
        return None
    query = dict(parse_qsl(urlsplit(identity).query, keep_blank_values=True))
    raw = query.get(profile.version_param)
    if raw is None:
        return None
    mapped = {mapping.raw: mapping.label for mapping in profile.version_map}
    return _SEGMENT_UNSAFE.sub("-", mapped.get(raw, raw))


def assign_path(mirror: "Mirror", identity: str, mover: "Page | None" = None) -> str | None:
    """The page path for an identity, per MovePage's guidance (mirror.allium 659 to 755).

    "pages/", the host segment, "/" and a relative path. The relative path strips the
    scope prefix, drops .html, .htm and .aspx (ignoring case), names a directory URL or
    a last segment that drop leaves empty `index`, keeps [A-Za-z0-9._-] in each segment
    and replaces the rest with "-" (a percent escape included: the path is never
    decoded), drops empty segments, applies the segment rewrites (`_rewrite_segment`),
    appends "@" and the version label when the identity carries one (`_path_label`; a
    final ".md" goes first), and appends ".md" unless the last segment ends in ".md"
    exactly. A path another page
    holds (ignoring case) or one past max_path_chars, which counts the whole path,
    becomes the stem cut to max_path_chars - 10, "-" and the first collision_hash_chars
    hex of the identity's digest; when that path is unusable too, the suffix is the full
    digest, the stem cut to fit; a cut never shortens pages/<host>/. When no option is
    usable, None (RefuseUnplaceableCandidate). `mover` is the page MovePage gives the
    identity: it is not another page, so the path it holds is usable.
    """
    from rovo._mirror.model import CONFIG  # noqa: PLC0415  The model imports this module.

    root = page_root(identity)
    plain = _fold_directories(mirror, root, _relative_path(mirror, identity))
    stem = plain.removesuffix(_PAGE_EXTENSION)
    full = digest(identity)
    max_chars = CONFIG.max_path_chars
    short = f"-{full[: CONFIG.collision_hash_chars]}{_PAGE_EXTENSION}"
    whole = f"-{full}{_PAGE_EXTENSION}"
    options = (
        plain,
        _cut(stem, max_chars - _SUFFIX_ROOM, root) + short,
        _cut(stem, max_chars - len(whole), root) + whole,
    )
    return next(
        (
            path
            for path in options
            if path.startswith(root) and _usable(mirror, identity, path, max_chars, mover)
        ),
        None,
    )


def page_root(identity: str) -> str:
    """mirror.allium page_root: "pages/", the identity's host segment and "/"."""
    return f"{_PAGES_ROOT}{host_segment(identity)}/"


def host_segment(identity: str) -> str:
    """The directory under pages/ for the identity's host (MovePage guidance, 658 to 670).

    The host lower-cased, a trailing "." dropped, every character outside [a-z0-9.-]
    replaced with "-", the device-name rewrite applied, then a non-default port appended
    as "_<port>". The host is read as the identity writes it, so an IPv6 literal keeps
    its brackets until they are replaced.
    """
    parts = urlsplit(identity)
    host = parts.netloc.rpartition("@")[2]
    if not host.startswith("[") or "]" not in host:
        host = host.partition(":")[0]
    else:
        host = host[: host.index("]") + 1]
    host = _HOST_UNSAFE.sub("-", host.lower().removesuffix("."))
    port = parts.port
    segment = _device_rewrite(host)
    if port is not None and _DEFAULT_PORTS.get(parts.scheme.lower()) != port:
        segment = f"{segment}_{port}"
    return segment


def _relative_path(mirror: "Mirror", identity: str) -> str:
    """The page path below pages/<host>/, its segment rewrites applied and ".md" ended."""
    path = path_of(identity)
    prefix = max(
        (p for p in mirror.scope.path_prefixes if path.startswith(p)), key=len, default="/"
    )
    relative = path[len(prefix) :] if path.startswith(prefix) else path.lstrip("/")
    for suffix in _PAGE_SUFFIXES:
        if relative.lower().endswith(suffix):
            relative = relative[: -len(suffix)]
            break
    # A directory URL, or a last segment the dropped suffix leaves empty, is "index".
    if not relative or relative.endswith("/"):
        relative += "index"
    names = [_SEGMENT_UNSAFE.sub("-", name) for name in relative.split("/") if name]
    last_index = len(names) - 1
    segments = [
        _rewrite_segment(name, directory=index < last_index) for index, name in enumerate(names)
    ]
    last = segments[-1]
    label = _path_label(mirror.profile, identity)
    if label is not None:
        last = f"{last.removesuffix(_PAGE_EXTENSION)}@{label}{_PAGE_EXTENSION}"
        segments[-1] = last
    if not last.endswith(_PAGE_EXTENSION):
        segments[-1] = f"{last}{_PAGE_EXTENSION}"
    return "/".join(segments)


def _fold_directories(mirror: "Mirror", root: str, relative: str) -> str:
    """`root` and `relative`, each directory spelt as a held path spells it (728 to 739).

    Level by level under the parent already folded, a directory segment takes, ignoring
    case, the spelling of the held path (every page's, its own included) that sorts first
    by code point; one no path holds keeps its own. The last segment keeps its spelling.
    """
    *directories, name = relative.split("/")
    held = sorted(page.path for page in mirror.pages)
    prefix = root
    for segment in directories:
        wanted = f"{prefix}{segment}/".casefold()
        spelt = next((path for path in held if path.casefold().startswith(wanted)), None)
        prefix += f"{segment}/" if spelt is None else spelt[len(prefix) : len(wanted)]
    return f"{prefix}{name}"


def _rewrite_segment(segment: str, *, directory: bool) -> str:
    """The segment rewrites inside pages/<host>/ (MovePage guidance, 703 to 720).

    Each reads the sanitised segment alone and they apply together, agreeing where they
    overlap: a trailing run of "." and a leading "." become "-"; a directory named,
    ignoring case, like a managed root file or ending in ".md" has its last "." replaced
    with "-"; a device name before the first "." gains "-" after it (con. gives con--).
    """
    chars = list(segment)
    kept = len(segment.rstrip("."))
    chars[kept:] = "-" * (len(segment) - kept)
    if segment.startswith("."):
        chars[0] = "-"
    folded = segment.casefold()
    if directory and (folded in _MANAGED_ROOT_FILES or folded.endswith(_PAGE_EXTENSION)):
        chars[segment.rindex(".")] = "-"
    stem = segment.partition(".")[0]
    if stem.casefold() in _DEVICE_NAMES:
        chars.insert(len(stem), "-")
    return "".join(chars)


def _device_rewrite(segment: str) -> str:
    """A segment whose part before its first "." is a device name gains "-" after it."""
    stem, dot, rest = segment.partition(".")
    return f"{stem}-{dot}{rest}" if stem.casefold() in _DEVICE_NAMES else segment


def _cut(stem: str, length: int, root: str) -> str:
    """The stem cut to `length`; empty when the cut would shorten `root` (unusable)."""
    return stem[:length] if length >= len(root) else ""


def _usable(
    mirror: "Mirror", identity: str, candidate: str, max_chars: int, mover: "Page | None"
) -> bool:
    held = any(
        page is not mover
        and page.identity != identity
        and page.path.casefold() == candidate.casefold()
        for page in mirror.pages
    )
    return not held and len(candidate) <= max_chars


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 5.2.4: resolve `.` and `..`, keeping a trailing slash."""
    output: list[str] = []
    segments = path.split("/")
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == ".":
            if last:
                output.append("")
        elif segment == "..":
            if len(output) > 1:
                output.pop()
            if last:
                output.append("")
        else:
            output.append(segment)
    resolved = "/".join(output)
    return resolved if resolved.startswith("/") else f"/{resolved}"
