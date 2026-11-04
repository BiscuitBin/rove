"""Mirror state on disk (decision 0013): the atomic writers, the clock, the manifest.

Every state file is UTF-8 JSON with sorted keys, indented two spaces and ending in one
LF, written to a temporary file in its directory, flushed, synced and moved into place.
The manifest, `<out>/.rovo/manifest.json`, holds the mirror: its scope, profile name,
signature, pages (every field, fetch times included), aliases and links.
"""

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from rovo._convert.model import (
    ExpectedCounts,
    ExtractionMethod,
    OutputMeasurement,
    QualityFlag,
    QualityGate,
    QualityResult,
)
from rovo._convert.profiles import profile_named
from rovo._mirror.model import (
    Alias,
    CrawlScope,
    Frontmatter,
    Link,
    LinkKind,
    Mirror,
    Page,
    PageStatus,
    RemovalReason,
    StoreOutcome,
    Tier,
)

STATE_DIRECTORY = ".rovo"
_MANIFEST = "manifest.json"
# The mode an ordinary new file gets before the umask: read and write for everyone.
_FILE_MODE = 0o666


class Clock(Protocol):
    """The time source: `now()` is timezone-aware UTC."""

    def now(self) -> datetime:
        """The current time, UTC."""
        ...


class SystemClock:
    """The real clock."""

    def now(self) -> datetime:
        """The current time, UTC."""
        return datetime.now(UTC)


class ManifestError(Exception):
    """The manifest is missing or does not parse."""


def write_text(path: Path, text: str) -> None:
    """Write UTF-8 text atomically: a temporary file beside it, fsync, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(handle, _FILE_MODE & ~_umask())
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            Path(temporary).unlink()
        raise


def _umask() -> int:
    """The process's file-creation mask; mkstemp's 0600 would otherwise reach every file."""
    current = os.umask(0)
    os.umask(current)
    return current


def write_json(path: Path, data: object) -> None:
    """Write UTF-8 JSON, keys sorted, indent 2, trailing LF, atomically."""
    write_text(path, json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:  # noqa: ANN401  JSON is untyped until a reader shapes it.
    """Read a UTF-8 JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def state_path(out_dir: Path, name: str) -> Path:
    """<out>/.rovo/<name>."""
    return out_dir / STATE_DIRECTORY / name


def manifest_path(out_dir: Path) -> Path:
    """<out>/.rovo/manifest.json."""
    return state_path(out_dir, _MANIFEST)


def timestamp(moment: datetime) -> str:
    """An ISO 8601 UTC timestamp."""
    return moment.astimezone(UTC).isoformat()


def load_mirror(out_dir: Path) -> Mirror:
    """Read the manifest; ManifestError when it is missing or does not parse."""
    try:
        data = read_json(manifest_path(out_dir))
        return _decode_mirror(out_dir, data)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        message = f"{manifest_path(out_dir)}: {error}"
        raise ManifestError(message) from error


def save_mirror(mirror: Mirror) -> None:
    """Write the manifest atomically."""
    write_json(manifest_path(mirror.out_dir), _encode_mirror(mirror))


def encode_scope(scope: CrawlScope) -> dict[str, object]:
    """A CrawlScope as JSON: sets sorted."""
    return {
        "root_url": scope.root_url,
        "start_urls": list(scope.start_urls),
        "allowed_hosts": sorted(scope.allowed_hosts),
        "path_prefixes": list(scope.path_prefixes),
        "include": list(scope.include),
        "exclude": list(scope.exclude),
        "max_depth": scope.max_depth,
        "locale": scope.locale,
        "meaningful_query_params": list(scope.meaningful_query_params),
        "locale_codes": sorted(scope.locale_codes),
    }


def encode_quality(quality: QualityResult) -> dict[str, object]:
    """A QualityResult as JSON: gates and flags as sorted names."""
    return {
        "expected": {**vars(quality.expected), "prose_words": list(quality.expected.prose_words)},
        "output": {**vars(quality.output), "words": list(quality.output.words)},
        "tab_panels_emitted": quality.tab_panels_emitted,
        "failed": sorted(gate.value for gate in quality.failed),
        "score": quality.score,
        "flags": sorted(flag.value for flag in quality.flags),
        "low_confidence": quality.low_confidence,
    }


def _encode_mirror(mirror: Mirror) -> dict[str, object]:
    return {
        "scope": encode_scope(mirror.scope),
        "profile": mirror.profile.name,
        "processing_signature": mirror.processing_signature,
        "declared_owned_hosts": sorted(mirror.declared_owned_hosts),
        "recorded_root_url": mirror.recorded_root_url,
        "pages": [_encode_page(page) for page in mirror.pages],
        "aliases": [
            {"url": alias.url, "target": alias.target.identity} for alias in mirror.aliases
        ],
        "links": [
            _encode_link(link)
            for link in sorted(
                mirror.links,
                key=lambda link: (link.source.identity, link.target_identity, link.fragment or ""),
            )
        ],
    }


def _encode_link(link: Link) -> dict[str, object]:
    return {
        "source": link.source.identity,
        "target_identity": link.target_identity,
        "fragment": link.fragment,
        "kind": link.kind.value,
        "target": None if link.target is None else link.target.identity,
        "fragment_resolved": link.fragment_resolved,
    }


def _encode_page(page: Page) -> dict[str, object]:
    return {
        "identity": page.identity,
        "path": page.path,
        "canonical_url": page.canonical_url,
        "source_url": page.source_url,
        "title": page.title,
        "description": page.description,
        "method": page.method.value,
        "tier": page.tier.value,
        "quality": encode_quality(page.quality),
        "flags": sorted(flag.value for flag in page.flags),
        "low_confidence": page.low_confidence,
        "anchors": sorted(page.anchors),
        "headings": list(page.headings),
        "keywords": list(page.keywords),
        "breadcrumbs": list(page.breadcrumbs),
        "locale": page.locale,
        "version": page.version,
        "raw_digest": page.raw_digest,
        "content_digest": page.content_digest,
        "previous_digest": page.previous_digest,
        "moved_from": page.moved_from,
        "etag": page.etag,
        "last_modified": page.last_modified,
        "sitemap_lastmod": page.sitemap_lastmod,
        "processing_signature": page.processing_signature,
        "converted_body": page.converted_body,
        "body": page.body,
        "frontmatter": None if page.frontmatter is None else _encode_frontmatter(page.frontmatter),
        "last_outcome": page.last_outcome.value,
        "last_seen_run": page.last_seen_run,
        "last_stored_run": page.last_stored_run,
        "first_seen": timestamp(page.first_seen),
        "fetched_at": timestamp(page.fetched_at),
        "last_seen": timestamp(page.last_seen),
        "last_changed": timestamp(page.last_changed),
        "status": page.status.value,
        "removed_at": None if page.removed_at is None else timestamp(page.removed_at),
        "removal_reason": None if page.removal_reason is None else page.removal_reason.value,
        "redirect_target": page.redirect_target,
    }


def _encode_frontmatter(frontmatter: Frontmatter) -> dict[str, object]:
    return {
        **vars(frontmatter),
        "quality_flags": sorted(flag.value for flag in frontmatter.quality_flags),
        "tier": frontmatter.tier.value,
        "method": frontmatter.method.value,
        "keywords": list(frontmatter.keywords),
        "breadcrumbs": None if frontmatter.breadcrumbs is None else list(frontmatter.breadcrumbs),
    }


def decode_scope(data: dict[str, Any]) -> CrawlScope:
    """A CrawlScope from its JSON."""
    return CrawlScope(
        root_url=data["root_url"],
        start_urls=tuple(data["start_urls"]),
        allowed_hosts=frozenset(data["allowed_hosts"]),
        path_prefixes=tuple(data["path_prefixes"]),
        include=tuple(data["include"]),
        exclude=tuple(data["exclude"]),
        max_depth=int(data["max_depth"]),
        locale=data["locale"],
        meaningful_query_params=tuple(data["meaningful_query_params"]),
        locale_codes=frozenset(data["locale_codes"]),
    )


def decode_quality(data: dict[str, Any]) -> QualityResult:
    """A QualityResult from its JSON."""
    return QualityResult(
        expected=ExpectedCounts(
            **{**data["expected"], "prose_words": tuple(data["expected"]["prose_words"])}
        ),
        output=OutputMeasurement(**{**data["output"], "words": tuple(data["output"]["words"])}),
        tab_panels_emitted=int(data["tab_panels_emitted"]),
        failed=frozenset(QualityGate(gate) for gate in data["failed"]),
        score=float(data["score"]),
        flags=frozenset(QualityFlag(flag) for flag in data["flags"]),
        low_confidence=bool(data["low_confidence"]),
    )


def _decode_mirror(out_dir: Path, data: dict[str, Any]) -> Mirror:
    profile = profile_named(data["profile"])
    if profile is None:
        message = f"unknown profile {data['profile']!r}"
        raise ValueError(message)
    mirror = Mirror(
        out_dir=out_dir,
        scope=decode_scope(data["scope"]),
        profile=profile,
        processing_signature=data["processing_signature"],
        declared_owned_hosts=frozenset(data["declared_owned_hosts"]),
        recorded_root_url=data["recorded_root_url"],
    )
    mirror.pages = [_decode_page(mirror, page) for page in data["pages"]]
    for row in data["aliases"]:
        target = mirror.page(row["target"])
        if target is None:
            message = f"alias {row['url']!r} names no page"
            raise ValueError(message)
        mirror.aliases.append(Alias(mirror=mirror, url=row["url"], target=target))
    mirror.links = [_decode_link(mirror, row) for row in data["links"]]
    return mirror


def _decode_link(mirror: Mirror, row: dict[str, Any]) -> Link:
    target = None if row["target"] is None else _linked_page(mirror, row["target"])
    return Link(
        source=_linked_page(mirror, row["source"]),
        target_identity=row["target_identity"],
        fragment=row["fragment"],
        kind=LinkKind(row["kind"]),
        target=target,
        fragment_resolved=row["fragment_resolved"],
    )


def _linked_page(mirror: Mirror, identity: str) -> Page:
    page = mirror.page(identity)
    if page is None:
        message = f"a link names no page {identity!r}"
        raise ValueError(message)
    return page


def _optional_time(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _decode_page(mirror: Mirror, data: dict[str, Any]) -> Page:
    frontmatter = data["frontmatter"]
    reason = data["removal_reason"]
    return Page(
        mirror=mirror,
        identity=data["identity"],
        path=data["path"],
        canonical_url=data["canonical_url"],
        source_url=data["source_url"],
        title=data["title"],
        description=data["description"],
        method=ExtractionMethod(data["method"]),
        tier=Tier(data["tier"]),
        quality=decode_quality(data["quality"]),
        flags=frozenset(QualityFlag(flag) for flag in data["flags"]),
        low_confidence=bool(data["low_confidence"]),
        anchors=frozenset(data["anchors"]),
        headings=tuple(data["headings"]),
        keywords=tuple(data["keywords"]),
        breadcrumbs=tuple(data["breadcrumbs"]),
        locale=data["locale"],
        version=data["version"],
        raw_digest=data["raw_digest"],
        content_digest=data["content_digest"],
        previous_digest=data["previous_digest"],
        moved_from=data["moved_from"],
        etag=data["etag"],
        last_modified=data["last_modified"],
        sitemap_lastmod=data["sitemap_lastmod"],
        processing_signature=data["processing_signature"],
        converted_body=data["converted_body"],
        body=data["body"],
        frontmatter=None if frontmatter is None else _decode_frontmatter(frontmatter),
        last_outcome=StoreOutcome(data["last_outcome"]),
        last_seen_run=int(data["last_seen_run"]),
        last_stored_run=int(data["last_stored_run"]),
        first_seen=datetime.fromisoformat(data["first_seen"]),
        fetched_at=datetime.fromisoformat(data["fetched_at"]),
        last_seen=datetime.fromisoformat(data["last_seen"]),
        last_changed=datetime.fromisoformat(data["last_changed"]),
        status=PageStatus(data["status"]),
        removed_at=_optional_time(data["removed_at"]),
        removal_reason=None if reason is None else RemovalReason(reason),
        redirect_target=data["redirect_target"],
    )


def _decode_frontmatter(data: dict[str, Any]) -> Frontmatter:
    breadcrumbs = data["breadcrumbs"]
    return Frontmatter(
        **{
            **data,
            "quality_flags": frozenset(QualityFlag(flag) for flag in data["quality_flags"]),
            "tier": Tier(data["tier"]),
            "method": ExtractionMethod(data["method"]),
            "keywords": tuple(data["keywords"]),
            "breadcrumbs": None if breadcrumbs is None else tuple(breadcrumbs),
        }
    )
