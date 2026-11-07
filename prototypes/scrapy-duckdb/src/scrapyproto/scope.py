"""Ticket 04's scope: URL identity and the in-bounds test, after `CrawlScope` in docs/specs/mirror.allium.

Standard library only: the host imports this module for `--dry-run`, and `crawl.py` pastes its source
into the rendered spider, so the guest runs the same code. The spider requests a URL as discovered
(fragment removed, nothing else changed), so the request and its cache key are what ticket 03 issued.
Only scope tests and dedup use the identity.

Identity (`identity_of`): scheme and host lower-cased, the default port dropped, dot segments resolved,
a trailing `index.html` folded into `/`, only the kept query parameters kept and sorted, the fragment
dropped, a trailing slash kept. `locale` and `locale_codes` are not built: the ticket has no flag for them.

Patterns match the identity, never the raw URL. A glob is `fnmatch.fnmatchcase` over the whole identity
(`*` crosses `/`; `?` is any one character, so it also matches a literal `?`). A pattern prefixed `re:` is
`re.search`: unanchored, so `re:/user-get` matches anywhere and `^` and `$` anchor it.
"""

import fnmatch
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

DEFAULT_PORTS = {"http": 80, "https": 443}


def _remove_dot_segments(path):
    out = []
    for seg in path.split("/"):
        if seg == "..":
            if len(out) > 1:
                out.pop()
        elif seg != ".":
            out.append(seg)
    resolved = "/".join(out)
    if path.endswith(("/.", "/..")):
        resolved += "/"
    return resolved or "/"


def identity_of(url, keep_params):
    """The normalised URL that keys a page; None for a URL that is not absolute http(s)."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in DEFAULT_PORTS or not host:
        return None
    netloc = host if port in (None, DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    path = _remove_dot_segments(parts.path or "/")
    if path.endswith("/index.html"):
        path = path[: -len("index.html")]
    kept = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k in keep_params)
    query = urlencode(kept, quote_via=quote, safe="/")
    return urlunsplit((scheme, netloc, path, query, ""))


def pattern_matches(identity, pattern):
    if pattern.startswith("re:"):
        return re.search(pattern[3:], identity) is not None
    return fnmatch.fnmatchcase(identity, pattern)


def check_pattern(pattern):
    """Raise ValueError for a pattern that cannot match anything as written."""
    if pattern.startswith("re:"):
        try:
            re.compile(pattern[3:])
        except re.error as exc:
            msg = f"bad regex {pattern!r}: {exc}"
            raise ValueError(msg) from exc
    elif not pattern:
        msg = "an empty glob matches only an empty URL"
        raise ValueError(msg)


class Scope:
    """The resolved scope. `verdict(url, depth)` is None when the crawl may fetch the URL at that depth,
    else the reason it may not: off_host, off_prefix, excluded, not_included, too_deep or malformed."""

    def __init__(self, scope):
        self.start_urls = list(scope["start_urls"])
        self.allowed_hosts = set(scope["allowed_hosts"])
        self.path_prefixes = list(scope["path_prefixes"])
        self.include = list(scope["include"])
        self.exclude = list(scope["exclude"])
        self.max_depth = scope["max_depth"]
        self.keep = set(scope["meaningful_query_params"])
        self.seed_ids = {self.identity(u) for u in self.start_urls}

    def identity(self, url):
        return identity_of(url, self.keep)

    def bounds_reason(self, url):
        """`within_bounds`, with the failing clause named. A seed is always in bounds."""
        ident = self.identity(url)
        if ident is None:
            return "malformed"
        if ident in self.seed_ids:
            return None
        if (urlsplit(ident).hostname or "") not in self.allowed_hosts:
            return "off_host"
        if not any(urlsplit(ident).path.startswith(p) for p in self.path_prefixes):
            return "off_prefix"
        if any(pattern_matches(ident, p) for p in self.exclude):
            return "excluded"
        if self.include and not any(pattern_matches(ident, p) for p in self.include):
            return "not_included"
        return None

    def verdict(self, url, depth):
        """`allows(url, depth)`, with the failing clause named."""
        reason = self.bounds_reason(url)
        if reason is None and not 0 <= depth <= self.max_depth:
            return "too_deep"
        return reason
