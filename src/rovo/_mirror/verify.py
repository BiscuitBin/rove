"""Verify (mirror.allium VerifyPages): the mirror on disk checked offline, nothing written.

`verification_failures` reads the manifest's mirror, the page files and the index files;
it never contacts the site and never writes. Every path it reports is mirror-relative,
and the findings come back sorted by path, reason and detail.
"""

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path

from rovo._convert.fidelity import link_destinations, measure_body
from rovo._convert.model import QualityGate, QualityResult
from rovo._mirror.finalise import PAGES_DIRECTORY, request_pass
from rovo._mirror.indexes import (
    INDEXES_DIRECTORY,
    directory_indexes_for,
    index_entries,
    index_files,
    link_index_entries,
    llms_summary,
)
from rovo._mirror.links import broken_reason
from rovo._mirror.model import (
    CONFIG,
    Frontmatter,
    Index,
    Mirror,
    MirrorPass,
    Operator,
    Page,
    PassKind,
    PassStatus,
    VerificationFailure,
    VerificationFinished,
    VerificationReason,
)
from rovo._mirror.urls import digest

_FRONTMATTER = "---\n"
_FRONTMATTER_END = "\n---\n"
_MARKDOWN = ".md"
# The index files whose links are checked: the Markdown ones and llms.txt.
_LINKED_INDEX_SUFFIXES = (_MARKDOWN, ".txt")
# The frontmatter keys every page file holds: Frontmatter's fields without a default.
_REQUIRED_KEYS = frozenset(
    field.name for field in dataclasses.fields(Frontmatter) if field.default is dataclasses.MISSING
)


def verification_failures(mirror: Mirror) -> list[VerificationFailure]:
    """Every finding over the mirror's files, sorted by path, reason and detail.

    missing_file, unmanaged_file, invalid_page_file, digest_mismatch, quality_drift,
    broken_link and index_stale, as VerifyPages' guidance says; anything at the root
    that is not a managed file (.git/, a README) is the operator's and never reported.
    """
    found = list(_page_findings(mirror))
    expected = _expected_index_files(mirror)
    known = {page.path for page in mirror.written_pages}
    found += [
        VerificationFailure(path=path, reason=VerificationReason.unmanaged_file, detail="")
        for path in _markdown_files(mirror.out_dir, PAGES_DIRECTORY)
        if path not in known
    ]
    found += [
        VerificationFailure(path=path, reason=VerificationReason.unmanaged_file, detail="")
        for path in _markdown_files(mirror.out_dir, INDEXES_DIRECTORY)
        if path not in expected
    ]
    for name, text in expected.items():
        found += _index_findings(mirror, name, text)
    return sorted(found, key=lambda failure: (failure.path, failure.reason.value, failure.detail))


def verify_pages(pass_: MirrorPass) -> VerificationFinished | None:
    """Realises mirror.allium VerifyPages; None when its guard does not hold."""
    if pass_.status is not PassStatus.pending or pass_.kind is not PassKind.verify:
        return None
    failures = verification_failures(pass_.mirror)
    pass_.failures = failures
    pass_.status = PassStatus.completed
    return VerificationFinished(
        mirror=pass_.mirror, pass_=pass_, operator=pass_.operator, failures=tuple(failures)
    )


def verify_pass(operator: Operator, mirror: Mirror) -> VerificationFinished | None:
    """RequestPass of a verify pass (no run), then VerifyPages."""
    return verify_pages(request_pass(operator, mirror, PassKind.verify, None))


def _page_findings(mirror: Mirror) -> Iterator[VerificationFailure]:
    """Each written page's findings: its file, its frontmatter, its body and its links."""
    for page in mirror.written_pages:
        path = mirror.out_dir / page.path
        if not path.is_file():
            yield _failure(page.path, VerificationReason.missing_file)
            continue
        parsed = _page_file(path)
        if parsed is None:
            yield _failure(page.path, VerificationReason.invalid_page_file)
            continue
        frontmatter, body = parsed
        current = digest(body)
        if current != frontmatter["content_digest"] or current != page.content_digest:
            yield _failure(page.path, VerificationReason.digest_mismatch, current)
        for gate in _drifted_gates(page, body):
            yield _failure(page.path, VerificationReason.quality_drift, gate.value)
        for href in link_destinations(body):
            if broken_reason(mirror, page.path, href, page) is not None:
                yield _failure(page.path, VerificationReason.broken_link, href)


def _page_file(path: Path) -> tuple[dict[str, object], str] | None:
    """A page file's frontmatter and body, else None.

    None when the file cannot be read or is not UTF-8, or its frontmatter is absent, does
    not parse, or lacks a required key.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    end = text.find(_FRONTMATTER_END, len(_FRONTMATTER) - 1)
    if not text.startswith(_FRONTMATTER) or end == -1:
        return None
    frontmatter: dict[str, object] = {}
    for line in text[len(_FRONTMATTER) : end].split("\n"):
        key, separator, value = line.partition(": ")
        try:
            frontmatter[key] = json.loads(value)
        except ValueError:
            return None
        if not separator:
            return None
    if not frontmatter.keys() >= _REQUIRED_KEYS:
        return None
    return frontmatter, text[end + len(_FRONTMATTER_END) :]


def _drifted_gates(page: Page, body: str) -> list[QualityGate]:
    """The gates that fail on the body against the stored expected counts and did not."""
    stored = page.quality
    current = QualityResult(
        expected=stored.expected,
        output=measure_body(body, stored.expected.prose_words),
        tab_panels_emitted=stored.tab_panels_emitted,
        failed=frozenset(),
        score=1.0,
        flags=frozenset(),
        low_confidence=False,
    )
    return [
        gate
        for gate in QualityGate
        if not getattr(current, f"{gate.value}_passes") and gate not in stored.failed
    ]


def _expected_index_files(mirror: Mirror) -> dict[str, str]:
    """What BuildIndexes would write for the mirror as the manifest holds it."""
    entries = index_entries(mirror.written_pages)
    index = Index(
        mirror=mirror,
        entries=entries,
        link_entries=link_index_entries(mirror.written_pages, mirror.aliases),
        directory_indexes=directory_indexes_for(entries, CONFIG.hierarchical_index_threshold),
        summary=llms_summary(mirror, entries),
    )
    return index_files(index, CONFIG.llms_txt_cap)


def _index_findings(mirror: Mirror, name: str, text: str) -> list[VerificationFailure]:
    """index_stale when the file's text differs; broken_link for each link it breaks."""
    path = mirror.out_dir / name
    try:
        written = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [_failure(name, VerificationReason.index_stale)]
    found = [] if written == text else [_failure(name, VerificationReason.index_stale)]
    if name.endswith(_LINKED_INDEX_SUFFIXES):
        found += [
            _failure(name, VerificationReason.broken_link, href)
            for href in link_destinations(written)
            if broken_reason(mirror, name, href) is not None
        ]
    return found


def _markdown_files(root: Path, directory: str) -> list[str]:
    """The mirror-relative paths of the Markdown files under one directory of the root."""
    return [
        path.relative_to(root).as_posix()
        for path in sorted((root / directory).rglob(f"*{_MARKDOWN}"))
        if path.is_file()
    ]


def _failure(path: str, reason: VerificationReason, detail: str = "") -> VerificationFailure:
    return VerificationFailure(path=path, reason=reason, detail=detail)
