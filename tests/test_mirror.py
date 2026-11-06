"""mirror.allium's obligations: the scope, intake, aliases, the finalise pass, paths, config.

Each test is named after the obligation id `just plan-spec mirror` emits, dots and
hyphens as underscores, and its docstring quotes the obligation. A `rule_failure` test
makes exactly one `requires` clause false and shows that the rule does not fire: the
function returns None or False and nothing changes.
"""

import dataclasses
import hashlib
import json
import re
import sys
from collections.abc import Callable, Iterable
from datetime import timedelta
from pathlib import Path

import pytest

from fakes import START, FixedClock, xml_response
from rovo._convert import profiles
from rovo._convert.model import (
    ConvertedContent,
    ExpectedCounts,
    ExtractionMethod,
    OutputMeasurement,
    QualityFlag,
    QualityGate,
    QualityResult,
)
from rovo._mirror import model
from rovo._mirror.finalise import (
    Finalisation,
    finalise,
    finalise_page_body,
    frontmatter_of,
    keywords_of,
    page_file_current,
    page_file_text,
    publish_page,
    request_pass,
    retire_out_of_scope_pages,
)
from rovo._mirror.indexes import (
    build_indexes,
    directory_indexes_for,
    index_entries,
    index_pass,
    link_index_entries,
    rebuild_indexes,
)
from rovo._mirror.intake import (
    accept_absent_without_page,
    accept_redirected_out_without_page,
    admit_candidate,
    discard_unchanged_without_page,
    drop_alias_of_own_identity,
    move_page,
    record_alias,
    record_unchanged,
    refresh_page,
    refuse_unplaceable_candidate,
    reject_duplicate_candidate,
    remove_absent_page,
    remove_redirected_out_page,
    retire_page,
    revive_removed_page,
    rewrite_known_page,
    settle_candidate,
    store_new_page,
    take_candidate,
)
from rovo._mirror.links import (
    find_broken_links,
    finish_link_pass,
    link_to_external_page,
    link_to_page,
    link_to_removed_page,
    link_to_uncrawled_page,
    resolve_mirror_links,
)
from rovo._mirror.model import (
    Alias,
    BrokenLink,
    BrokenLinkReason,
    CandidateDelivered,
    CandidateDiscarded,
    CandidateDuplicate,
    CandidateOutcome,
    CandidateStatus,
    CrawlScope,
    DirectoryIndex,
    Frontmatter,
    Index,
    IndexBuildDue,
    IndexEntry,
    IndexesWritten,
    Link,
    LinkIndexEntry,
    LinksFound,
    Mirror,
    MirrorPass,
    Operator,
    Page,
    PageCandidate,
    PageRemoved,
    PageStatus,
    PassKind,
    PassStatus,
    RemovalReason,
    StoreOutcome,
    Tier,
)
from rovo._mirror.state import load_mirror, save_mirror, write_json
from rovo._mirror.urls import assign_path, digest
from spec_values import spec_bool, spec_enum, spec_int
from test_crawl import LASTMOD, MAPS, declaring, stored_seed, urlset
from test_crawl import SEED as CRAWL_SEED
from test_crawl import site as crawl_site

SITE = "http://docs.example"
# page_root of the fixture host: every page path lies under pages/<host>/ (mirror.allium,
# MovePage guidance and PagePathsAvoidManagedNames, at fed9ed8).
ROOT = "pages/docs.example/"
SEED = f"{SITE}/guide/start.html"
TOPIC = f"{SITE}/guide/topic.html"
OTHER = f"{SITE}/guide/other.html"
SIGNATURE = "signature-1"
RAW_DIGEST = hashlib.sha256(b"<html>raw</html>").hexdigest()
ETAG = '"etag-1"'
LAST_MODIFIED = "Sat, 31 Oct 2026 12:00:00 GMT"
LATER = START + timedelta(hours=1)
FIRST_RUN = 1
SECOND_RUN = 2
LOW_SCORE = 0.9
ISO_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
HEX_SUFFIX = re.compile(r"-[0-9a-f]+\.md$")
# PagePathsAvoidManagedNames' name sets and MaxPathCharsInRange's bounds (mirror.allium
# 1307 and 1329, at fed9ed8): invariant text, not config defaults.
DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)
MANAGED_ROOT_FILES = frozenset(
    {"llms.txt", "index.jsonl", "links.jsonl", "crawl-report.json", "rovo.toml"}
)
# The index files BuildIndexes writes at the mirror's root (its guidance, mirror.allium
# 1229 to 1262, and the managed root files of PagePathsAvoidManagedNames).
INDEX_FILES = ("index.md", "index.jsonl", "links.jsonl", "llms.txt")
MAX_PATH_CHARS_FLOOR = 128
MAX_PATH_CHARS_CEILING = 240

BODY = (
    "# Getting started\n"
    "\n"
    "The example product mirrors documentation websites into Markdown files that agents\n"
    "and people can read offline.\n"
    "\n"
    "## Install the product\n"
    "\n"
    "Download the installer, run it once, and open the dashboard to finish the setup.\n"
)
HEADINGS = ("Getting started", "Install the product")


def scope(**changes: object) -> CrawlScope:
    """The fixture site's scope: one host, the /guide/ prefix, the seed as start URL."""
    base = CrawlScope(
        root_url=f"{SITE}/guide/",
        start_urls=(SEED,),
        allowed_hosts=frozenset({"docs.example"}),
        path_prefixes=("/guide/",),
        include=(),
        exclude=(),
        max_depth=10,
        locale=None,
        meaningful_query_params=(),
        locale_codes=frozenset(),
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]  # Test overrides by name.


def new_mirror(out_dir: Path, **changes: object) -> Mirror:
    """An empty mirror over the fixture scope, as init leaves it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    return Mirror(
        out_dir=out_dir,
        scope=scope(**changes),
        profile=profiles.GENERIC,
        processing_signature=SIGNATURE,
    )


def quality(
    *,
    failed: Iterable[QualityGate] = (),
    flags: Iterable[QualityFlag] = (),
    score: float = 1.0,
    low_confidence: bool = False,
) -> QualityResult:
    """A measured result whose counts match: the gates named in `failed` failed."""
    expected = ExpectedCounts(
        code_blocks=0,
        tables=0,
        table_cells=0,
        headings=2,
        links=0,
        images=0,
        list_items=0,
        tab_panels=0,
        prose_words=("example", "product"),
    )
    output = OutputMeasurement(
        code_blocks=0,
        tables=0,
        table_cells=0,
        headings=2,
        links=0,
        images=0,
        list_items=0,
        words=("example", "product"),
        code_language_rate=1.0,
        text_coverage=1.0,
    )
    return QualityResult(
        expected=expected,
        output=output,
        tab_panels_emitted=0,
        failed=frozenset(failed),
        score=score,
        flags=frozenset(flags),
        low_confidence=low_confidence,
    )


def content(  # noqa: PLR0913  One keyword per content field a test varies.
    *,
    body: str = BODY,
    canonical_url: str | None = None,
    measured: QualityResult | None = None,
    link_targets: tuple[str, ...] = (),
    navigation_targets: tuple[str, ...] = (),
    anchors: frozenset[str] = frozenset(),
) -> ConvertedContent:
    """Converted content for the fixture page, as the crawl hands it over."""
    return ConvertedContent(
        body=body,
        title="Getting started",
        description="How to start with the example product.",
        canonical_url=canonical_url,
        declared_locale="en",
        breadcrumbs=(),
        navigation_targets=navigation_targets,
        method=ExtractionMethod.profile,
        anchors=anchors,
        headings=HEADINGS,
        link_targets=link_targets,
        quality=measured or quality(),
        is_empty=False,
    )


def delivered(  # noqa: PLR0913  One keyword per candidate field a test varies.
    mirror: Mirror,
    *,
    requested: str = SEED,
    source: str | None = None,
    run_id: int = FIRST_RUN,
    outcome: CandidateOutcome = CandidateOutcome.converted,
    converted: ConvertedContent | None = None,
    without_content: bool = False,
    depth: int = 0,
) -> CandidateDelivered:
    """A CandidateDelivered for one settled http fetch of `requested`."""
    return CandidateDelivered(
        run_id=run_id,
        mirror=mirror,
        requested_identity=requested,
        source_url=source or requested,
        redirect_hops=(),
        depth=depth,
        outcome=outcome,
        tier=Tier.http,
        raw_digest=RAW_DIGEST,
        content=None if without_content else (converted or content()),
        etag=ETAG,
        last_modified=LAST_MODIFIED,
    )


def stored(mirror: Mirror, **changes: object) -> Page:
    """Deliver, admit and store one new page; the page StoreNewPage created."""
    candidate = admit_candidate(delivered(mirror, **changes))  # type: ignore[arg-type]  # Test overrides by name.
    page = store_new_page(candidate, FixedClock())
    assert page is not None
    return page


def published(mirror: Mirror, page: Page) -> MirrorPass:
    """Finalise and publish one page, as the finalise pass does."""
    pass_ = request_pass(Operator(), mirror, PassKind.finalise, page.last_seen_run)
    finalise_page_body(pass_, page)
    publish_page(pass_, page, FixedClock())
    return pass_


def frontmatter_lines(text: str) -> list[str]:
    """The lines between the opening and the closing `---`."""
    assert text.startswith("---\n")
    head, separator, _ = text[len("---\n") :].partition("---\n")
    assert separator
    return head.splitlines()


def assert_fields(value: object, names: Iterable[str]) -> None:
    """Every named field or derived value is readable on `value`."""
    for name in names:
        assert hasattr(value, name), name
        getattr(value, name)


def test_rule_success_AdmitCandidate(tmp_path: Path) -> None:
    """Verify rule AdmitCandidate succeeds when all preconditions are met."""
    mirror = new_mirror(tmp_path)
    candidate = admit_candidate(delivered(mirror))
    assert isinstance(candidate, PageCandidate)
    assert candidate.status is CandidateStatus.pending
    assert mirror.pages == []


def test_rule_entity_creation_AdmitCandidate_1(tmp_path: Path) -> None:
    """Verify entity creation in rule AdmitCandidate ensures clause produces the specified fields."""  # noqa: E501  The obligation's description, quoted.
    mirror = new_mirror(tmp_path)
    trigger = delivered(mirror)
    candidate = admit_candidate(trigger)
    assert candidate.mirror is mirror
    assert candidate.run_id == trigger.run_id
    assert candidate.requested_identity == SEED
    assert candidate.source_url == SEED
    assert candidate.redirect_hops == ()
    assert candidate.redirect_target is None
    assert candidate.depth == 0
    assert candidate.outcome is CandidateOutcome.converted
    assert candidate.content == trigger.content
    assert candidate.tier is Tier.http
    assert candidate.etag == ETAG
    assert candidate.last_modified == LAST_MODIFIED
    assert candidate.sitemap_lastmod is None
    assert candidate.raw_digest == RAW_DIGEST
    assert candidate.status is CandidateStatus.pending


def test_rule_success_RequestPass(tmp_path: Path) -> None:
    """Verify rule RequestPass succeeds when all preconditions are met."""
    mirror = new_mirror(tmp_path)
    pass_ = request_pass(Operator(), mirror, PassKind.finalise, FIRST_RUN)
    assert isinstance(pass_, MirrorPass)
    assert pass_.status is PassStatus.pending


def test_rule_entity_creation_RequestPass_1(tmp_path: Path) -> None:
    """Verify entity creation in rule RequestPass ensures clause produces the specified fields."""
    mirror = new_mirror(tmp_path)
    operator = Operator()
    pass_ = request_pass(operator, mirror, PassKind.finalise, FIRST_RUN)
    assert pass_.mirror is mirror
    assert pass_.operator == operator
    assert pass_.kind is PassKind.finalise
    assert pass_.run_id == FIRST_RUN
    assert pass_.failures == []
    assert pass_.broken_links == []
    assert pass_.status is PassStatus.pending


def test_rule_success_StoreNewPage(tmp_path: Path) -> None:
    """Verify rule StoreNewPage succeeds when all preconditions are met."""
    mirror = new_mirror(tmp_path)
    candidate = admit_candidate(delivered(mirror))
    page = store_new_page(candidate, FixedClock())
    assert page is not None
    assert mirror.pages == [page]
    assert page.identity == SEED
    assert page.path == f"{ROOT}start.md"
    assert candidate.status is CandidateStatus.accepted
    assert not (tmp_path / ROOT / "start.md").exists()  # no file before finalisation
    assert not (tmp_path / "start.md").exists()


def test_rule_failure_StoreNewPage_1(tmp_path: Path) -> None:
    """Verify rule StoreNewPage is rejected when requires clause fails.

    requires: candidate.status = pending and candidate.outcome = converted.
    """
    mirror = new_mirror(tmp_path)
    unchanged = admit_candidate(delivered(mirror, outcome=CandidateOutcome.unchanged))
    assert store_new_page(unchanged, FixedClock()) is None
    accepted = admit_candidate(delivered(mirror))
    accepted.status = CandidateStatus.accepted
    assert store_new_page(accepted, FixedClock()) is None
    assert mirror.pages == []


def test_rule_failure_StoreNewPage_2(tmp_path: Path) -> None:
    """Verify rule StoreNewPage is rejected when requires clause fails.

    requires: not exists previous, the known page of the requested identity.
    """
    mirror = new_mirror(tmp_path)
    first = stored(mirror)
    again = admit_candidate(delivered(mirror, run_id=SECOND_RUN))
    assert store_new_page(again, FixedClock()) is None
    assert mirror.pages == [first]
    assert again.status is CandidateStatus.pending


def test_rule_failure_StoreNewPage_3(tmp_path: Path) -> None:
    """Verify rule StoreNewPage is rejected when requires clause fails.

    requires: not exists target, the page holding the identity: a removed page holds it.
    """
    mirror = new_mirror(tmp_path)
    removed = stored(mirror)
    removed.status = PageStatus.removed
    assert mirror.known_page(SEED) is None
    again = admit_candidate(delivered(mirror, run_id=SECOND_RUN))
    assert store_new_page(again, FixedClock()) is None
    assert mirror.pages == [removed]


def test_rule_failure_StoreNewPage_4(tmp_path: Path) -> None:
    """Verify rule StoreNewPage is rejected when requires clause fails.

    requires: content != null.
    """
    mirror = new_mirror(tmp_path)
    empty = admit_candidate(delivered(mirror, without_content=True))
    assert store_new_page(empty, FixedClock()) is None
    assert mirror.pages == []


def test_rule_entity_creation_StoreNewPage_1(tmp_path: Path) -> None:
    """Verify entity creation in rule StoreNewPage ensures clause produces the specified fields."""
    mirror = new_mirror(tmp_path)
    measured = quality()
    page = stored(mirror, converted=content(measured=measured))
    assert page.mirror is mirror
    assert page.identity == SEED
    assert page.path == f"{ROOT}start.md"
    assert page.canonical_url is None
    assert page.source_url == SEED
    assert page.title == "Getting started"
    assert page.description == "How to start with the example product."
    assert page.method is ExtractionMethod.profile
    assert page.tier is Tier.http
    assert page.quality == measured
    assert page.flags == measured.flags
    assert page.low_confidence is measured.low_confidence
    assert page.anchors == frozenset()
    assert page.headings == HEADINGS
    assert page.keywords == ()
    assert page.breadcrumbs == ()
    assert page.locale == "en"  # scope.locale ?? the declared locale
    assert page.version is None
    assert page.raw_digest == RAW_DIGEST
    assert page.content_digest == hashlib.sha256(BODY.encode()).hexdigest()
    assert page.previous_digest is None
    assert page.moved_from is None
    assert page.etag == ETAG
    assert page.last_modified == LAST_MODIFIED
    assert page.sitemap_lastmod is None
    assert page.processing_signature == SIGNATURE
    assert page.converted_body == BODY
    assert page.body == BODY
    assert page.frontmatter is None
    assert page.last_outcome is StoreOutcome.added
    assert page.last_seen_run == FIRST_RUN
    assert page.last_stored_run == FIRST_RUN
    assert page.first_seen == page.fetched_at == page.last_seen == page.last_changed == START
    assert page.status is PageStatus.written
    assert page.redirect_target is None


def test_rule_success_RefreshPage(tmp_path: Path) -> None:
    """Verify rule RefreshPage succeeds when all preconditions are met.

    The content fields are refreshed; T10: the page's outbound links are dropped and
    LinksFound carries the content's targets at the candidate's depth.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    changed_body = BODY.replace("once", "twice")
    later = admit_candidate(
        delivered(mirror, run_id=SECOND_RUN, converted=content(body=changed_body))
    )
    assert refresh_page(later, page, FixedClock(LATER))
    assert page.converted_body == changed_body
    assert page.last_seen_run == SECOND_RUN
    assert page.last_stored_run == SECOND_RUN
    assert page.fetched_at == LATER
    assert page.last_seen == LATER
    assert page.first_seen == START
    assert later.status is CandidateStatus.accepted
    assert mirror.aliases == []

    # T10: the page's previous links are dropped, and LinksFound carries the content's
    # link and navigation targets at the candidate's depth.
    stale = Link(
        source=page,
        target_identity=NEW,
        fragment=None,
        kind=model.LinkKind.uncrawled,
        target=None,
        fragment_resolved=True,
    )
    mirror.links.append(stale)
    linked = content(
        body=LINKED_BODY,
        link_targets=(OTHER, f"{OTHER}#setup", NEW),
        navigation_targets=(TOPIC,),
    )
    third = admit_candidate(
        delivered(mirror, run_id=SECOND_RUN + 1, converted=linked, depth=SECOND_RUN)
    )
    found = links_found(refresh_page(third, page, FixedClock(LATER)))
    assert found.candidate is third
    assert found.page is page
    assert found.depth == SECOND_RUN
    assert found.targets == linked.link_targets
    assert found.navigation_targets == linked.navigation_targets
    assert stale not in mirror.links
    assert page.outbound_links == ()
    assert page.converted_body == LINKED_BODY


def test_rule_failure_RefreshPage_1(tmp_path: Path) -> None:
    """Verify rule RefreshPage is rejected when requires clause fails.

    requires: candidate.status = pending.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    later = admit_candidate(
        delivered(mirror, run_id=SECOND_RUN, converted=content(body=BODY + "More.\n"))
    )
    later.status = CandidateStatus.accepted
    assert not refresh_page(later, page, FixedClock(LATER))
    assert page.converted_body == BODY
    assert page.last_seen_run == FIRST_RUN


def test_rule_failure_RefreshPage_2(tmp_path: Path) -> None:
    """Verify rule RefreshPage is rejected when requires clause fails.

    requires: content != null.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    empty = admit_candidate(delivered(mirror, run_id=SECOND_RUN, without_content=True))
    assert not refresh_page(empty, page, FixedClock(LATER))
    assert page.last_seen_run == FIRST_RUN
    assert empty.status is CandidateStatus.pending


def test_rule_success_RecordAlias(tmp_path: Path) -> None:
    """Verify rule RecordAlias succeeds when all preconditions are met.

    A same-host canonical moves the page identity: the page is stored at the canonical,
    its path is assigned from it, and the seed becomes an alias of the page. Recording
    the alias again retargets it rather than adding a second.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror, converted=content(canonical_url=TOPIC))
    assert page.identity == TOPIC
    assert page.path == f"{ROOT}topic.md"
    assert [(alias.url, alias.target) for alias in mirror.aliases] == [(SEED, page)]
    assert mirror.known_page(SEED) is page

    other = stored(mirror, requested=OTHER)
    alias = record_alias(mirror, SEED, other)
    assert alias is not None
    assert [(a.url, a.target) for a in mirror.aliases] == [(SEED, other)]


def test_rule_failure_RecordAlias_1(tmp_path: Path) -> None:
    """Verify rule RecordAlias is rejected when requires clause fails.

    requires: not exists own or own.status = removed: a written page's identity is never
    an alias.
    """
    mirror = new_mirror(tmp_path)
    seed_page = stored(mirror)
    other = stored(mirror, requested=OTHER)
    assert record_alias(mirror, seed_page.identity, other) is None
    assert mirror.aliases == []


def test_rule_failure_RecordAlias_cross_host_canonical(tmp_path: Path) -> None:
    """A canonical on a host the scope does not allow keeps the source identity: no alias."""
    mirror = new_mirror(tmp_path)
    page = stored(mirror, converted=content(canonical_url="http://elsewhere.example/start"))
    assert page.identity == SEED
    assert mirror.aliases == []


def test_rule_success_DropAliasOfOwnIdentity(tmp_path: Path) -> None:
    """Verify rule DropAliasOfOwnIdentity succeeds when all preconditions are met."""
    mirror = new_mirror(tmp_path)
    seed_page = stored(mirror)
    other = stored(mirror, requested=OTHER)
    mirror.aliases.append(Alias(mirror=mirror, url=OTHER, target=seed_page))
    assert drop_alias_of_own_identity(mirror, OTHER, seed_page)
    assert mirror.aliases == []
    assert mirror.known_page(OTHER) is other


def test_rule_failure_DropAliasOfOwnIdentity_1(tmp_path: Path) -> None:
    """Verify rule DropAliasOfOwnIdentity is rejected when requires clause fails.

    requires: exists own and own.status = written.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror, converted=content(canonical_url=TOPIC))
    assert mirror.page(SEED) is None
    assert not drop_alias_of_own_identity(mirror, SEED, page)
    assert [alias.url for alias in mirror.aliases] == [SEED]


def test_entity_fields_Alias(tmp_path: Path) -> None:
    """Verify all declared fields on Alias are present with correct types."""
    mirror = new_mirror(tmp_path)
    page = stored(mirror, converted=content(canonical_url=TOPIC))
    (alias,) = mirror.aliases
    assert isinstance(alias, Alias)
    assert alias.mirror is mirror
    assert alias.url == SEED
    assert alias.target is page
    assert page.aliases == [alias]


def test_invariant_Alias_AliasIsNotItsTarget(tmp_path: Path) -> None:
    """Verify invariant AliasIsNotItsTarget holds after any field mutation on Alias."""
    mirror = new_mirror(tmp_path)
    stored(mirror, converted=content(canonical_url=TOPIC))
    stored(mirror, requested=OTHER)
    assert mirror.aliases
    for alias in mirror.aliases:
        assert alias.url != alias.target.identity


def test_invariant_OneAliasPerUrl(tmp_path: Path) -> None:
    """Verify invariant OneAliasPerUrl holds after every state-changing rule that touches constrained entities."""  # noqa: E501  The obligation's description, quoted.
    mirror = new_mirror(tmp_path)
    topic = stored(mirror, converted=content(canonical_url=TOPIC))
    other = stored(mirror, requested=OTHER)
    record_alias(mirror, SEED, other)
    record_alias(mirror, SEED, topic)
    urls = [alias.url for alias in mirror.aliases]
    assert urls == [SEED]
    assert len(urls) == len(set(urls))


def test_invariant_AliasesPointAtWrittenPages(tmp_path: Path) -> None:
    """Verify invariant AliasesPointAtWrittenPages holds after every state-changing rule that touches constrained entities."""  # noqa: E501  The obligation's description, quoted.
    mirror = new_mirror(tmp_path)
    stored(mirror, converted=content(canonical_url=TOPIC))
    assert mirror.aliases
    for alias in mirror.aliases:
        assert alias.target.status is PageStatus.written
        assert alias.target in mirror.written_pages


def test_rule_success_FinalisePageBody(tmp_path: Path) -> None:
    """Verify rule FinalisePageBody succeeds when all preconditions are met.

    Over a body with no links: the body is the converted body, no link flag is added,
    and keywords are recomputed from the body. Over a body with links (T10): the body is
    rewritten, its digest, link flags, low-confidence verdict and keywords recomputed.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    pass_ = request_pass(Operator(), mirror, PassKind.finalise, FIRST_RUN)
    finalise_page_body(pass_, page)
    assert page.body == page.converted_body == BODY
    assert page.content_digest == hashlib.sha256(BODY.encode()).hexdigest()
    assert page.flags == page.quality.flags
    assert page.low_confidence is page.quality.low_confidence
    assert page.keywords == keywords_of(
        BODY, model.CONFIG.keywords_per_page, model.CONFIG.keywords_min
    )
    assert page.keywords

    # T10: over a body with links, each internal destination becomes a relative path
    # between page files (a self-link a bare fragment), every other destination and
    # every code sample stays as written, and the link flags are recomputed.
    linked, start, _ = linked_mirror(tmp_path / "linked")
    linked_pass = resolved(linked)
    finalise_page_body(linked_pass, start)
    assert start.converted_body == LINKED_BODY
    assert start.body == REWRITTEN_BODY
    assert start.content_digest == hashlib.sha256(REWRITTEN_BODY.encode()).hexdigest()
    link_flags = {QualityFlag.uncrawled_internal, QualityFlag.unresolved_fragment}
    assert start.flags == start.quality.flags | link_flags
    assert QualityFlag.dangling_inbound not in start.flags
    incomplete = profiles.CONFIG.incomplete_flags
    assert start.low_confidence is (
        start.quality.low_confidence or any(flag in incomplete for flag in link_flags)
    )
    assert start.keywords == keywords_of(
        REWRITTEN_BODY, model.CONFIG.keywords_per_page, model.CONFIG.keywords_min
    )


def test_rule_success_PublishPage(tmp_path: Path) -> None:
    """Verify rule PublishPage succeeds when all preconditions are met.

    The page file is written once, as frontmatter with sorted keys and no wall-clock time
    followed by the body; a second publish of the same body is unchanged.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    pass_ = request_pass(Operator(), mirror, PassKind.finalise, FIRST_RUN)
    finalise_page_body(pass_, page)
    assert not page_file_current(page)
    event = publish_page(pass_, page, FixedClock(LATER))
    assert event.pass_ is pass_
    assert event.page is page
    assert event.outcome is StoreOutcome.added
    assert event.previous_path is None
    assert event.seen_this_run
    assert page.frontmatter == frontmatter_of(page)
    assert page.last_outcome is StoreOutcome.added
    assert page.last_changed == LATER
    assert page.previous_digest == page.content_digest
    assert page.moved_from is None
    assert page_file_current(page)

    text = (tmp_path / ROOT / "start.md").read_text(encoding="utf-8")
    assert not (tmp_path / "start.md").exists()  # never beside the managed root files
    assert text == page_file_text(page)
    lines = frontmatter_lines(text)
    keys = [line.split(":", 1)[0] for line in lines]
    assert keys == sorted(keys)
    assert 'title: "Getting started"' in lines
    assert f"source_url: {json.dumps(SEED)}" in lines
    assert "low_confidence: false" in lines
    assert not ISO_TIMESTAMP.search(text)
    assert text.endswith(BODY)

    again = publish_page(pass_, page, FixedClock(LATER + timedelta(hours=1)))
    assert again.outcome is StoreOutcome.unchanged
    assert page.last_changed == LATER


def test_transition_edge_PageCandidate_pending_accepted(tmp_path: Path) -> None:
    """Verify transition pending -> accepted on PageCandidate.status is reachable via a witnessing rule."""  # noqa: E501  The obligation's description, quoted.
    mirror = new_mirror(tmp_path)
    candidate = admit_candidate(delivered(mirror))
    before = candidate.status
    page = take_candidate(candidate, FixedClock())
    assert page is not None
    assert (before, candidate.status) == (CandidateStatus.pending, CandidateStatus.accepted)


def test_transition_rejected_PageCandidate_status(tmp_path: Path) -> None:
    """Verify undeclared transitions on PageCandidate.status are rejected."""
    mirror = new_mirror(tmp_path)
    candidate = admit_candidate(delivered(mirror))
    page = take_candidate(candidate, FixedClock())
    assert page is not None
    # accepted -> pending and accepted -> duplicate are undeclared: nothing moves it back.
    assert take_candidate(candidate, FixedClock()) is None
    assert not refresh_page(candidate, page, FixedClock())
    assert candidate.status is CandidateStatus.accepted
    assert mirror.pages == [page]


def test_transition_terminal_PageCandidate_status(tmp_path: Path) -> None:
    """Verify terminal states on PageCandidate.status have no outbound transitions."""
    mirror = new_mirror(tmp_path)
    candidate = admit_candidate(delivered(mirror))
    take_candidate(candidate, FixedClock())
    assert candidate.status is CandidateStatus.accepted
    assert store_new_page(candidate, FixedClock()) is None
    assert candidate.status is CandidateStatus.accepted


def test_transition_edge_MirrorPass_pending_completed(tmp_path: Path) -> None:
    """Verify transition pending -> completed on MirrorPass.status is reachable via a witnessing rule."""  # noqa: E501  The obligation's description, quoted.
    mirror = new_mirror(tmp_path)
    stored(mirror)
    result = finalise(Operator(), mirror, FIRST_RUN, FixedClock())
    assert result.pass_.status is PassStatus.completed
    assert result.pass_.kind is PassKind.finalise
    assert [event.page.path for event in result.finalised] == [f"{ROOT}start.md"]
    # T11: BuildIndexes completes the pass, raising IndexesWritten after the index files.
    assert result.indexes is not None
    assert result.indexes.pass_ is result.pass_
    assert result.indexes.mirror is mirror
    for name in INDEX_FILES:
        assert (tmp_path / name).is_file(), name


def test_transition_rejected_MirrorPass_status(tmp_path: Path) -> None:
    """Verify undeclared transitions on MirrorPass.status are rejected."""
    mirror = new_mirror(tmp_path)
    stored(mirror)
    first = finalise(Operator(), mirror, FIRST_RUN, FixedClock())
    second = finalise(Operator(), mirror, FIRST_RUN, FixedClock())
    assert second.pass_ is not first.pass_
    assert first.pass_.status is PassStatus.completed


def test_transition_terminal_MirrorPass_status(tmp_path: Path) -> None:
    """Verify terminal states on MirrorPass.status have no outbound transitions."""
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    result = finalise(Operator(), mirror, FIRST_RUN, FixedClock())
    finalise_page_body(result.pass_, page)
    publish_page(result.pass_, page, FixedClock())
    assert result.pass_.status is PassStatus.completed


def test_value_equality_CrawlScope() -> None:
    """Verify value type CrawlScope has structural equality."""
    assert scope() == scope()
    assert hash(scope()) == hash(scope())
    assert scope() != scope(max_depth=3)
    assert scope().seeds == scope().seeds == (SEED,)


def test_entity_fields_CrawlScope() -> None:
    """Verify all declared fields on CrawlScope are present with correct types.

    And the derived functions (mirror.allium 112 to 152, at fed9ed8) on the fixture scope.
    """
    crawl_scope = scope(meaningful_query_params=("view",), locale_codes=frozenset({"en", "de"}))
    assert_fields(
        crawl_scope,
        (
            "root_url",
            "start_urls",
            "allowed_hosts",
            "path_prefixes",
            "include",
            "exclude",
            "max_depth",
            "locale",
            "meaningful_query_params",
            "locale_codes",
            "seeds",
        ),
    )
    assert crawl_scope.identity_of("HTTP://Docs.Example:80/guide/./start.html#intro") == SEED
    assert crawl_scope.identity_of(f"{SITE}/guide/index.html") == f"{SITE}/guide/"
    assert crawl_scope.identity_of(f"{TOPIC}?utm_source=x&view=b") == f"{TOPIC}?view=b"
    assert crawl_scope.host_allowed(TOPIC)
    assert not crawl_scope.host_allowed("http://elsewhere.example/guide/")
    assert crawl_scope.is_seed(f"{SEED}#top")
    assert crawl_scope.within_bounds(TOPIC)
    assert not crawl_scope.within_bounds(f"{SITE}/blog/post.html")
    assert crawl_scope.allows(TOPIC, 0)
    assert not crawl_scope.allows(TOPIC, crawl_scope.max_depth + 1)
    pinned = dataclasses.replace(crawl_scope, locale="en", path_prefixes=("/",))
    assert pinned.foreign_locale(f"{SITE}/de/guide.html")
    assert not pinned.foreign_locale(f"{SITE}/en/guide.html")
    assert crawl_scope.page_identity(SEED, TOPIC) == TOPIC
    assert crawl_scope.page_identity(SEED, "http://elsewhere.example/x") == SEED
    assert crawl_scope.page_identity(SEED, None) == SEED
    assert scope(start_urls=()).seeds == (f"{SITE}/guide/",)


def test_value_equality_Frontmatter(tmp_path: Path) -> None:
    """Verify value type Frontmatter has structural equality."""
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    published(mirror, page)
    assert frontmatter_of(page) == frontmatter_of(page)
    assert hash(frontmatter_of(page)) == hash(frontmatter_of(page))
    assert frontmatter_of(page) != dataclasses.replace(frontmatter_of(page), title="Other")


# mirror.allium Frontmatter's fields at a0814ab: the validators live in .rovo/ alone.
FRONTMATTER_FIELDS = {
    "source_url",
    "title",
    "content_digest",
    "quality_score",
    "low_confidence",
    "quality_flags",
    "tier",
    "method",
    "profile",
    "keywords",
    "description",
    "canonical_url",
    "breadcrumbs",
    "sitemap_lastmod",
    "version",
    "locale",
}
VALIDATOR_KEYS = {"etag", "last_modified"}


def test_entity_fields_Frontmatter(tmp_path: Path) -> None:
    """Verify all declared fields on Frontmatter are present with correct types.

    Re-propagated by T14 at a0814ab: the declared fields lose etag and last_modified,
    which the page keeps in .rovo/ state alone, so neither is a field nor a line of the
    page file, though the page was stored with both.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    published(mirror, page)
    assert (page.etag, page.last_modified) == (ETAG, LAST_MODIFIED)
    frontmatter = frontmatter_of(page)
    assert isinstance(frontmatter, Frontmatter)
    assert frontmatter.source_url == SEED
    assert frontmatter.title == "Getting started"
    assert frontmatter.content_digest == page.content_digest
    assert frontmatter.quality_score == page.quality.score
    assert frontmatter.low_confidence is page.low_confidence
    assert frontmatter.quality_flags == page.flags
    assert frontmatter.tier is Tier.http
    assert frontmatter.method is ExtractionMethod.profile
    assert frontmatter.profile == "generic"
    assert frontmatter.keywords == page.keywords
    assert frontmatter.description == page.description
    assert frontmatter.canonical_url is None
    assert frontmatter.sitemap_lastmod is None
    assert frontmatter.version is None
    assert frontmatter.locale == "en"
    assert_fields(frontmatter, ("breadcrumbs",))
    assert {field.name for field in dataclasses.fields(Frontmatter)} == FRONTMATTER_FIELDS
    text = (tmp_path / page.path).read_text(encoding="utf-8")
    keys = {line.split(":", 1)[0] for line in frontmatter_lines(text)}
    assert keys.isdisjoint(VALIDATOR_KEYS)


def test_entity_fields_Mirror(tmp_path: Path) -> None:
    """Verify all declared fields on Mirror are present with correct types."""
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    assert mirror.out_dir == tmp_path
    assert mirror.scope == scope()
    assert mirror.profile == profiles.GENERIC
    assert mirror.declared_owned_hosts == frozenset()
    assert mirror.recorded_root_url is None
    assert mirror.processing_signature == SIGNATURE
    assert mirror.pages == [page]
    assert mirror.aliases == []
    assert mirror.index is None
    assert mirror.written_pages == [page]
    assert mirror.removed_pages == []
    assert mirror.page_paths == [f"{ROOT}start.md"]
    assert mirror.is_populated
    assert not mirror.has_declared_owner


def sitemap_named_seed(out_dir: Path, lastmod: str | None) -> LinksFound:
    """The crawl's seed stored after a sitemap named it with `lastmod` (T13), or none named it."""
    fetcher = crawl_site(robots=declaring(MAPS))
    if lastmod is not None:
        fetcher.responses[MAPS] = xml_response(MAPS, urlset((CRAWL_SEED, lastmod)))
    _, _, found = stored_seed(out_dir, fetcher)
    return found


def test_entity_optional_PageCandidate_sitemap_lastmod(tmp_path: Path) -> None:
    """Verify optional field PageCandidate.sitemap_lastmod accepts null and non-null values.

    A sitemap entry's lastmod reaches the candidate from its frontier row (crawl.allium
    ConvertFetched); a page no sitemap names has none.
    """
    named = sitemap_named_seed(tmp_path / "named", LASTMOD)
    unnamed = sitemap_named_seed(tmp_path / "unnamed", None)
    assert named.candidate.sitemap_lastmod == LASTMOD
    assert unnamed.candidate.sitemap_lastmod is None


def test_entity_optional_Page_sitemap_lastmod(tmp_path: Path) -> None:
    """Verify optional field Page.sitemap_lastmod accepts null and non-null values.

    The stored page keeps the candidate's lastmod and its frontmatter carries it.
    """
    named = sitemap_named_seed(tmp_path / "named", LASTMOD)
    unnamed = sitemap_named_seed(tmp_path / "unnamed", None)
    assert named.page.sitemap_lastmod == LASTMOD
    assert frontmatter_of(named.page).sitemap_lastmod == LASTMOD
    assert unnamed.page.sitemap_lastmod is None
    assert frontmatter_of(unnamed.page).sitemap_lastmod is None


def test_entity_optional_Page_version(tmp_path: Path) -> None:
    """Verify optional field Page.version accepts null and non-null values.

    T17: a page of a profile without versions has none. No run stores a versioned page
    while assign_path stops for a version label (the T17 batched question, item 2), so
    the labelled page is a constructed record: its frontmatter and the manifest carry
    the label, and a page without one has no version key.
    """
    plain = stored(new_mirror(tmp_path / "plain"))
    assert plain.version is None
    published(plain.mirror, plain)
    lines = frontmatter_lines((plain.mirror.out_dir / plain.path).read_text(encoding="utf-8"))
    assert not any(line.startswith("version:") for line in lines)

    labelled = stored(new_mirror(tmp_path / "labelled"))
    labelled.version = "v1.0"
    published(labelled.mirror, labelled)
    path = labelled.mirror.out_dir / labelled.path
    assert 'version: "v1.0"' in frontmatter_lines(path.read_text(encoding="utf-8"))
    save_mirror(labelled.mirror)
    loaded = load_mirror(labelled.mirror.out_dir).page(labelled.identity)
    assert loaded is not None
    assert loaded.version == "v1.0"


def test_entity_optional_Page_locale(tmp_path: Path) -> None:
    """Verify optional field Page.locale accepts null and non-null values.

    The pinned locale wins over the declared one; without a pin the page declares its
    own, and a page declaring none has none.
    """
    pinned = stored(new_mirror(tmp_path / "pinned", locale="de"))
    assert pinned.locale == "de"
    declared = stored(new_mirror(tmp_path / "declared"))
    assert declared.locale == "en"
    undeclared = stored(
        new_mirror(tmp_path / "undeclared"),
        converted=dataclasses.replace(content(), declared_locale=None),
    )
    assert undeclared.locale is None
    published(undeclared.mirror, undeclared)
    path = undeclared.mirror.out_dir / undeclared.path
    lines = frontmatter_lines(path.read_text(encoding="utf-8"))
    assert not any(line.startswith("locale:") for line in lines)
    published(pinned.mirror, pinned)
    path = pinned.mirror.out_dir / pinned.path
    assert 'locale: "de"' in frontmatter_lines(path.read_text(encoding="utf-8"))


def test_entity_optional_Mirror_recorded_root_url(tmp_path: Path) -> None:
    """Verify optional field Mirror.recorded_root_url accepts null and non-null values.

    Both survive the manifest's save and load.
    """
    unset = new_mirror(tmp_path / "unset")
    save_mirror(unset)
    assert load_mirror(unset.out_dir).recorded_root_url is None
    recorded = new_mirror(tmp_path / "recorded")
    recorded.recorded_root_url = f"{SITE}/guide/"
    save_mirror(recorded)
    assert load_mirror(recorded.out_dir).recorded_root_url == f"{SITE}/guide/"


def test_derived_Mirror_is_populated(tmp_path: Path) -> None:
    """Verify derived value Mirror.is_populated computes correctly."""
    mirror = new_mirror(tmp_path)
    empty = mirror.is_populated
    page = stored(mirror)
    populated = mirror.is_populated
    page.status = PageStatus.removed
    emptied = mirror.is_populated
    assert (empty, populated, emptied) == (False, True, False)


def test_projection_Mirror_written_pages(tmp_path: Path) -> None:
    """Verify projection Mirror.written_pages filters correctly."""
    mirror = new_mirror(tmp_path)
    kept = stored(mirror)
    gone = stored(mirror, requested=OTHER)
    gone.status = PageStatus.removed
    assert mirror.written_pages == [kept]
    assert mirror.removed_pages == [gone]
    assert mirror.page_paths == [kept.path]


def test_entity_fields_Page(tmp_path: Path) -> None:
    """Verify all declared fields on Page are present with correct types.

    Re-propagated by the T16 follow-up (origin T09, extended since): 9a253a4 adds
    revived_from, null on a stored page.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    fields = {field.name for field in dataclasses.fields(Page)}
    assert fields >= {
        "mirror",
        "identity",
        "path",
        "canonical_url",
        "source_url",
        "title",
        "description",
        "method",
        "tier",
        "quality",
        "flags",
        "low_confidence",
        "anchors",
        "headings",
        "keywords",
        "breadcrumbs",
        "locale",
        "version",
        "raw_digest",
        "content_digest",
        "previous_digest",
        "moved_from",
        "revived_from",
        "etag",
        "last_modified",
        "sitemap_lastmod",
        "processing_signature",
        "converted_body",
        "body",
        "frontmatter",
        "last_outcome",
        "last_seen_run",
        "last_stored_run",
        "first_seen",
        "fetched_at",
        "last_seen",
        "last_changed",
        "status",
        "removed_at",
        "removal_reason",
        "redirect_target",
    }
    # No link exists in this slice: the link-derived values are empty.
    assert len(page.outbound_links) == 0
    assert len(page.inbound_links) == 0
    assert page.aliases == []
    assert len(page.internal_outbound) == 0
    assert len(page.internal_inbound) == 0
    assert page.outbound_internal == 0
    assert page.inbound_internal == 0
    assert not page.has_uncrawled_link
    assert not page.has_dangling_link
    assert not page.has_unresolved_fragment
    assert page.is_new_this_run
    assert not page.was_moved
    assert page.removed_at is None
    assert page.removal_reason is None
    assert page.revived_from is None


def test_entity_fields_PageCandidate(tmp_path: Path) -> None:
    """Verify all declared fields on PageCandidate are present with correct types."""
    mirror = new_mirror(tmp_path)
    candidate = admit_candidate(delivered(mirror))
    assert_fields(
        candidate,
        (
            "mirror",
            "run_id",
            "requested_identity",
            "source_url",
            "redirect_hops",
            "redirect_target",
            "depth",
            "outcome",
            "content",
            "tier",
            "etag",
            "last_modified",
            "sitemap_lastmod",
            "raw_digest",
            "status",
        ),
    )
    assert isinstance(candidate.content, ConvertedContent)
    assert isinstance(candidate.redirect_hops, tuple)


def test_entity_fields_MirrorPass(tmp_path: Path) -> None:
    """Verify all declared fields on MirrorPass are present with correct types."""
    mirror = new_mirror(tmp_path)
    pass_ = request_pass(Operator(), mirror, PassKind.finalise, None)
    assert_fields(pass_, ("mirror", "operator", "kind", "run_id", "failures", "broken_links"))
    assert pass_.run_id is None
    assert isinstance(pass_.status, PassStatus)


def test_derived_Page_is_new_this_run(tmp_path: Path) -> None:
    """Verify derived value Page.is_new_this_run computes correctly."""
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    new = (page.previous_digest, page.is_new_this_run)
    published(mirror, page)
    assert new == (None, True)
    assert page.previous_digest == page.content_digest
    assert not page.is_new_this_run


def low_and_high(mirror: Mirror) -> list[Page]:
    """Three finalised pages: all gates pass; a gate failed; a whole-body extraction."""
    failing = quality(
        failed={QualityGate.links},
        flags={QualityFlag.links},
        score=LOW_SCORE,
        low_confidence=True,
    )
    whole = quality(flags={QualityFlag.whole_body_extracted}, low_confidence=True)
    pages = [
        stored(mirror),
        stored(mirror, requested=OTHER, converted=content(measured=failing)),
        stored(mirror, requested=TOPIC, converted=content(measured=whole)),
    ]
    for page in pages:
        published(mirror, page)
    return pages


def test_invariant_Page_ScoreIsAFraction(tmp_path: Path) -> None:
    """Verify invariant ScoreIsAFraction holds after any field mutation on Page."""
    for page in low_and_high(new_mirror(tmp_path)):
        assert 0 <= page.quality.score <= 1


def test_invariant_Page_FullScoreIffAllGatesPass(tmp_path: Path) -> None:
    """Verify invariant FullScoreIffAllGatesPass holds after any field mutation on Page."""
    pages = low_and_high(new_mirror(tmp_path))
    for page in pages:
        assert page.quality.all_gates_pass == (page.quality.score == 1)
    assert [page.quality.all_gates_pass for page in pages] == [True, False, True]


def test_invariant_Page_FailedGatesAreFlagged(tmp_path: Path) -> None:
    """Verify invariant FailedGatesAreFlagged holds after any field mutation on Page."""
    for page in low_and_high(new_mirror(tmp_path)):
        for gate in page.quality.failed:
            assert QualityFlag[gate.name] in page.flags


def test_invariant_Page_LowConfidenceDefinition(tmp_path: Path) -> None:
    """Verify invariant LowConfidenceDefinition holds after any field mutation on Page."""
    pages = low_and_high(new_mirror(tmp_path))
    incomplete = profiles.CONFIG.incomplete_flags
    for page in pages:
        expected = not page.quality.all_gates_pass or any(f in incomplete for f in page.flags)
        assert page.low_confidence is expected
    assert [page.low_confidence for page in pages] == [False, True, True]


def test_invariant_Page_KeywordsAreBounded(tmp_path: Path) -> None:
    """Verify invariant KeywordsAreBounded holds after any field mutation on Page.

    keywords_of: lower-cased words outside code, at least three letters, no stop word,
    ranked by count then first occurrence; a pure function of the body.
    """
    long_body = (
        "# Keywords\n\n"
        + " ".join(f"term{chr(ord('a') + n)}" * 1 for n in range(20))
        + "\n\nThe the the and and mirror mirror mirror Mirror pages pages.\n\n"
        + "```python\nsecretcode secretcode secretcode secretcode\n```\n"
    )
    limit = model.CONFIG.keywords_per_page
    keywords = keywords_of(long_body, limit, model.CONFIG.keywords_min)
    assert keywords == keywords_of(long_body, limit, model.CONFIG.keywords_min)
    assert len(keywords) == limit
    assert len(set(keywords)) == len(keywords)
    assert keywords[0] == "mirror"
    assert keywords[1] == "pages"
    assert "the" not in keywords
    assert "secretcode" not in keywords
    assert all(word == word.lower() for word in keywords)
    for page in low_and_high(new_mirror(tmp_path)):
        assert len(page.keywords) <= limit
        assert len(set(page.keywords)) == len(page.keywords)


def test_invariant_UniquePageIdentity(tmp_path: Path) -> None:
    """Verify invariant UniquePageIdentity holds after every state-changing rule that touches constrained entities."""  # noqa: E501  The obligation's description, quoted.
    mirror = new_mirror(tmp_path)
    stored(mirror)
    duplicate = admit_candidate(delivered(mirror, source=f"{SEED}#again"))
    assert store_new_page(duplicate, FixedClock()) is None
    identities = [page.identity for page in mirror.pages]
    assert identities == [SEED]


def test_invariant_UniquePagePathIgnoringCase(tmp_path: Path) -> None:
    """Verify invariant UniquePagePathIgnoringCase holds after every state-changing rule that touches constrained entities."""  # noqa: E501  The obligation's description, quoted.
    mirror = new_mirror(tmp_path)
    stored(mirror)
    upper = f"{SITE}/guide/Start.html"
    page = stored(mirror, requested=upper)
    paths = [p.path.casefold() for p in mirror.pages]
    assert len(paths) == len(set(paths))
    digest = hashlib.sha256(upper.encode()).hexdigest()[: model.CONFIG.collision_hash_chars]
    assert page.path == f"{ROOT}Start-{digest}.md"
    assert assign_path(mirror, upper) == page.path  # the suffix depends on the identity alone


def assert_avoids_managed_names(path: str, root: str) -> None:
    """PagePathsAvoidManagedNames over one path whose page_root is `root` (fed9ed8, 1307)."""
    assert path.startswith(root), path
    assert path.endswith(".md"), path
    for segment in path.removeprefix("pages/").split("/"):
        assert segment.split(".", 1)[0].casefold() not in DEVICE_NAMES, path
    below = path.removeprefix(root).split("/")
    for segment in below:
        assert segment, path
        assert not segment.startswith("."), path
        assert not segment.endswith("."), path
    for directory in below[:-1]:
        assert directory.casefold() not in MANAGED_ROOT_FILES, path
        assert not directory.casefold().endswith(".md"), path


def test_invariant_PagePathsAvoidManagedNames(tmp_path: Path) -> None:
    """Verify invariant PagePathsAvoidManagedNames holds after every state-changing rule that touches constrained entities."""  # noqa: E501  The obligation's description, quoted.
    mirror = new_mirror(tmp_path)
    assert assign_path(mirror, SEED) == f"{ROOT}start.md"
    assert assign_path(mirror, f"{SITE}/guide/a b/c.htm") == f"{ROOT}a-b/c.md"
    # index.md and _index.md inside pages/<host>/ are ordinary page names now.
    assert assign_path(mirror, f"{SITE}/guide/") == f"{ROOT}index.md"
    assert assign_path(mirror, f"{SITE}/guide/_index.html") == f"{ROOT}_index.md"
    same_host = (
        f"{SITE}/guide/",
        f"{SITE}/guide/_index.html",
        f"{SITE}/guide/.hidden/page.html",
        f"{SITE}/guide/trailing./page.html",
        f"{SITE}/guide/.../page.html",
        f"{SITE}/guide/llms.txt/page.html",
        f"{SITE}/guide/Rovo.TOML/page.html",
        f"{SITE}/guide/notes.md/page.html",
        f"{SITE}/guide/con/aux.txt",
        f"{SITE}/guide/Lpt1.json/x.html",
        f"{SITE}/guide/a//b/page.html",
        f"{SITE}/guide/{'x' * (model.CONFIG.max_path_chars + 1)}.html",
    )
    for identity in same_host:
        path = assign_path(mirror, identity)
        assert path is not None, identity
        assert_avoids_managed_names(path, ROOT)
        assert len(path) <= model.CONFIG.max_path_chars
    long_path = assign_path(mirror, same_host[-1])
    assert long_path is not None
    assert HEX_SUFFIX.search(long_path), long_path
    other_hosts = {
        "http://CON:8080/guide/x.html": "pages/con-_8080/",
        "http://nul.example/guide/x.html": "pages/nul-.example/",
        "http://Docs.Example./guide/x.html": ROOT,
    }
    for identity, root in other_hosts.items():
        path = assign_path(mirror, identity)
        assert path is not None, identity
        assert_avoids_managed_names(path, root)
    for page in [stored(mirror, requested=identity) for identity in same_host]:
        assert_avoids_managed_names(page.path, ROOT)


def test_invariant_MaxPathCharsInRange() -> None:
    """Verify invariant MaxPathCharsInRange holds after every state-changing rule that touches constrained entities.

    config.max_path_chars >= 128 and config.max_path_chars <= 240 (mirror.allium 1329, at
    fed9ed8): the mirror's own parameter, which no rule changes.
    """  # noqa: E501  The obligation's description, quoted.
    assert MAX_PATH_CHARS_FLOOR <= model.CONFIG.max_path_chars <= MAX_PATH_CHARS_CEILING


def test_invariant_PageProcessedUnderOneSignature(tmp_path: Path) -> None:
    """Verify invariant PageProcessedUnderOneSignature holds after every state-changing rule that touches constrained entities."""  # noqa: E501  The obligation's description, quoted.
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    assert page.last_stored_run <= page.last_seen_run
    assert page.processing_signature == mirror.processing_signature
    published(mirror, page)
    assert page.last_stored_run <= page.last_seen_run


def test_manifest_round_trip(tmp_path: Path) -> None:
    """The manifest saves and loads a stored page and an alias (decision 0013's encoding)."""
    mirror = new_mirror(tmp_path)
    page = stored(mirror, converted=content(canonical_url=TOPIC))
    published(mirror, page)
    save_mirror(mirror)
    manifest = tmp_path / ".rovo" / "manifest.json"
    text = manifest.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert json.dumps(json.loads(text), sort_keys=True, indent=2) + "\n" == text
    loaded = load_mirror(tmp_path)
    (again,) = loaded.pages
    assert again.identity == TOPIC
    assert again.path == f"{ROOT}topic.md"
    assert again.quality == page.quality
    assert again.first_seen == page.first_seen
    assert again.frontmatter == page.frontmatter
    assert [(alias.url, alias.target.identity) for alias in loaded.aliases] == [(SEED, TOPIC)]
    assert loaded.scope == mirror.scope
    assert loaded.profile == mirror.profile


def test_write_json_is_sorted_and_leaves_no_temporary(tmp_path: Path) -> None:
    """write_json: UTF-8, keys sorted, indent 2, one trailing LF, replaced atomically."""
    target = tmp_path / ".rovo" / "state.json"
    target.parent.mkdir()
    write_json(target, {"b": 1, "a": ["x"]})
    assert target.read_bytes() == b'{\n  "a": [\n    "x"\n  ],\n  "b": 1\n}\n'
    assert sorted(p.name for p in target.parent.iterdir()) == ["state.json"]


def test_config_default_max_path_chars() -> None:
    """Verify config parameter max_path_chars has its declared default."""
    assert model.CONFIG.max_path_chars == spec_int("mirror", "max_path_chars")


def test_config_default_collision_hash_chars() -> None:
    """Verify config parameter collision_hash_chars has its declared default."""
    assert model.CONFIG.collision_hash_chars == spec_int("mirror", "collision_hash_chars")


def test_config_default_keywords_per_page() -> None:
    """Verify config parameter keywords_per_page has its declared default."""
    assert model.CONFIG.keywords_per_page == spec_int("mirror", "keywords_per_page")


def test_config_default_keywords_min() -> None:
    """Verify config parameter keywords_min has its declared default."""
    assert model.CONFIG.keywords_min == spec_int("mirror", "keywords_min")


# --- Links (T10): resolution, rewriting and the link pass -----------------------------

NEW = f"{SITE}/guide/new.html"
OUTSIDE = f"{SITE}/outside/x.html"
OLD = f"{SITE}/guide/old.html"
OLD_OUTSIDE = f"{SITE}/outside/old.html"
ALIAS_URL = f"{SITE}/guide/other-alias.html"
UNIDENTIFIABLE = f"{SITE}:99999/guide/x.html"  # a port out of range: no identity
LINKED_BODY = (
    "# Getting started\n"
    "\n"
    "## Introduction {#intro}\n"
    "\n"
    f"Read the [other page]({OTHER}), its [setup step]({OTHER}#setup) and a\n"
    f"[missing step]({OTHER}#missing).\n"
    "\n"
    f"Back to the [introduction]({SEED}#intro), on to a [new page]({NEW}) or out to\n"
    f"the [outside page]({OUTSIDE}).\n"
    "\n"
    f"Write to [us](mailto:docs@example.invalid) and see ![a diagram]({SITE}/guide/d.png).\n"
    "\n"
    f"Inline code `[other]({OTHER})` stays as written.\n"
    "\n"
    "```markdown\n"
    f"[other]({OTHER})\n"
    "```\n"
)
REWRITTEN_BODY = (
    "# Getting started\n"
    "\n"
    "## Introduction {#intro}\n"
    "\n"
    "Read the [other page](other.md), its [setup step](other.md#setup) and a\n"
    "[missing step](other.md#missing).\n"
    "\n"
    f"Back to the [introduction](#intro), on to a [new page]({NEW}) or out to\n"
    f"the [outside page]({OUTSIDE}).\n"
    "\n"
    f"Write to [us](mailto:docs@example.invalid) and see ![a diagram]({SITE}/guide/d.png).\n"
    "\n"
    f"Inline code `[other]({OTHER})` stays as written.\n"
    "\n"
    "```markdown\n"
    f"[other]({OTHER})\n"
    "```\n"
)
OTHER_BODY = (
    "# Other page\n"
    "\n"
    "The other page explains the example product's configuration.\n"
    "\n"
    "## Setup {#setup}\n"
    "\n"
    "Run the installer and follow the prompts.\n"
)
# What LINKED_BODY resolves to: (target identity, fragment, kind, fragment resolved).
LINKED_ROWS = {
    (OTHER, None, model.LinkKind.internal, True),
    (OTHER, "setup", model.LinkKind.internal, True),
    (OTHER, "missing", model.LinkKind.internal, False),
    (SEED, "intro", model.LinkKind.internal, True),
    (NEW, None, model.LinkKind.uncrawled, True),
    (OUTSIDE, None, model.LinkKind.external, True),
}


def linked_mirror(out_dir: Path, **changes: object) -> tuple[Mirror, Page, Page]:
    """Two written pages: the seed, whose body links widely, and the page it links to."""
    mirror = new_mirror(out_dir, **changes)
    start = stored(
        mirror,
        converted=content(
            body=LINKED_BODY,
            anchors=frozenset({"intro"}),
            link_targets=(OTHER, f"{OTHER}#setup", f"{OTHER}#missing", NEW, OUTSIDE),
        ),
    )
    other = stored(
        mirror,
        requested=OTHER,
        converted=content(body=OTHER_BODY, anchors=frozenset({"setup"})),
    )
    return mirror, start, other


def removed(mirror: Mirror, url: str) -> Page:
    """A page record for `url` whose status is removed (constructed: no run removes one)."""
    page = stored(mirror, requested=url)
    page.status = PageStatus.removed
    page.removed_at = START
    page.removal_reason = RemovalReason.absent
    return page


def link_pass(mirror: Mirror) -> MirrorPass:
    """A pending finalise pass over the mirror."""
    return request_pass(Operator(), mirror, PassKind.finalise, FIRST_RUN)


def resolved(mirror: Mirror) -> MirrorPass:
    """A finalise pass that has resolved every written page's links."""
    pass_ = link_pass(mirror)
    assert resolve_mirror_links(pass_)
    return pass_


def finalised_pass(mirror: Mirror) -> MirrorPass:
    """ResolveMirrorLinks, then FinalisePageBody and PublishPage for each page by path."""
    pass_ = resolved(mirror)
    pages = sorted(mirror.written_pages, key=lambda page: page.path)
    for page in pages:
        finalise_page_body(pass_, page)
    for page in pages:
        publish_page(pass_, page, FixedClock())
    return pass_


def rows(links: Iterable[Link]) -> set[tuple[str, str | None, model.LinkKind, bool]]:
    """Each link as (target identity, fragment, kind, fragment resolved)."""
    return {
        (link.target_identity, link.fragment, link.kind, link.fragment_resolved) for link in links
    }


def links_found(result: object) -> LinksFound:
    """RefreshPage's LinksFound, whatever the function's declared return type."""
    assert isinstance(result, LinksFound), result
    return result


def test_rule_success_ResolveMirrorLinks(tmp_path: Path) -> None:
    """Verify rule ResolveMirrorLinks succeeds when all preconditions are met.

    Every written page's previous links are dropped and its destinations resolved:
    images, mailto: targets, inline code and fenced code never become links.
    """
    mirror, start, other = linked_mirror(tmp_path)
    stale = Link(
        source=start,
        target_identity=TOPIC,
        fragment=None,
        kind=model.LinkKind.uncrawled,
        target=None,
        fragment_resolved=True,
    )
    mirror.links.append(stale)
    pass_ = link_pass(mirror)
    assert resolve_mirror_links(pass_)
    assert stale not in mirror.links
    assert rows(start.outbound_links) == LINKED_ROWS
    assert len(start.outbound_links) == len(LINKED_ROWS)
    assert other.outbound_links == ()
    assert all(link.source is start for link in mirror.links)
    assert pass_.status is PassStatus.pending


def test_rule_failure_ResolveMirrorLinks_1(tmp_path: Path) -> None:
    """Verify rule ResolveMirrorLinks is rejected when requires clause fails.

    requires: pass.status = pending.
    """
    mirror, start, _ = linked_mirror(tmp_path)
    stale = Link(
        source=start,
        target_identity=TOPIC,
        fragment=None,
        kind=model.LinkKind.uncrawled,
        target=None,
        fragment_resolved=True,
    )
    mirror.links.append(stale)
    pass_ = link_pass(mirror)
    pass_.status = PassStatus.completed
    assert not resolve_mirror_links(pass_)
    assert mirror.links == [stale]


def test_rule_success_LinkToPage(tmp_path: Path) -> None:
    """Verify rule LinkToPage succeeds when all preconditions are met.

    A destination made absolute against the source URL, held by a written page directly
    or through an alias, is an internal link to that page.
    """
    mirror, start, other = linked_mirror(tmp_path)
    record_alias(mirror, ALIAS_URL, other)
    pass_ = link_pass(mirror)
    direct = link_to_page(pass_, start, "other.html", None)
    aliased = link_to_page(pass_, start, ALIAS_URL, "setup")
    assert direct is not None
    assert aliased is not None
    assert (direct.kind, direct.target, direct.target_identity) == (
        model.LinkKind.internal,
        other,
        OTHER,
    )
    assert (aliased.kind, aliased.target, aliased.target_identity) == (
        model.LinkKind.internal,
        other,
        ALIAS_URL,
    )
    assert mirror.links == [direct, aliased]


def test_rule_failure_LinkToPage_1(tmp_path: Path) -> None:
    """Verify rule LinkToPage is rejected when requires clause fails.

    requires: exists holder.
    """
    mirror, start, _ = linked_mirror(tmp_path)
    assert link_to_page(link_pass(mirror), start, NEW, None) is None
    assert mirror.links == []


def test_rule_entity_creation_LinkToPage_1(tmp_path: Path) -> None:
    """Verify entity creation in rule LinkToPage ensures clause produces the specified fields."""
    mirror, start, other = linked_mirror(tmp_path)
    pass_ = link_pass(mirror)
    found = link_to_page(pass_, start, OTHER, "setup")
    missing = link_to_page(pass_, start, OTHER, "missing")
    bare = link_to_page(pass_, start, OTHER, None)
    assert found is not None
    assert missing is not None
    assert bare is not None
    assert found.source is start
    assert found.target_identity == OTHER
    assert found.fragment == "setup"
    assert found.kind is model.LinkKind.internal
    assert found.target is other
    assert found.fragment_resolved is True
    assert (missing.fragment, missing.fragment_resolved) == ("missing", False)
    assert (bare.fragment, bare.fragment_resolved) == (None, True)


def test_rule_success_LinkToRemovedPage(tmp_path: Path) -> None:
    """Verify rule LinkToRemovedPage succeeds when all preconditions are met."""
    mirror, start, _ = linked_mirror(tmp_path)
    removed(mirror, OLD)
    link = link_to_removed_page(link_pass(mirror), start, OLD, "gone")
    assert link is not None
    assert link.kind is model.LinkKind.dangling
    assert mirror.links == [link]


def test_rule_failure_LinkToRemovedPage_1(tmp_path: Path) -> None:
    """Verify rule LinkToRemovedPage is rejected when requires clause fails.

    requires: not exists known_page(page.mirror, identity).
    """
    mirror, start, _ = linked_mirror(tmp_path)
    assert link_to_removed_page(link_pass(mirror), start, OTHER, None) is None
    assert mirror.links == []


def test_rule_failure_LinkToRemovedPage_2(tmp_path: Path) -> None:
    """Verify rule LinkToRemovedPage is rejected when requires clause fails.

    requires: exists holder and holder.status = removed.
    """
    mirror, start, _ = linked_mirror(tmp_path)
    assert link_to_removed_page(link_pass(mirror), start, NEW, None) is None
    assert mirror.links == []


def test_rule_entity_creation_LinkToRemovedPage_1(tmp_path: Path) -> None:
    """Verify entity creation in rule LinkToRemovedPage ensures clause produces the specified fields."""  # noqa: E501  The obligation's description, quoted.
    mirror, start, _ = linked_mirror(tmp_path)
    removed(mirror, OLD)
    link = link_to_removed_page(link_pass(mirror), start, "old.html", "gone")
    assert link is not None
    assert link.source is start
    assert link.target_identity == OLD
    assert link.fragment == "gone"
    assert link.kind is model.LinkKind.dangling
    assert link.target is None
    assert link.fragment_resolved is True


def test_rule_success_LinkToUncrawledPage(tmp_path: Path) -> None:
    """Verify rule LinkToUncrawledPage succeeds when all preconditions are met."""
    mirror, start, _ = linked_mirror(tmp_path)
    link = link_to_uncrawled_page(link_pass(mirror), start, NEW, None)
    assert link is not None
    assert link.kind is model.LinkKind.uncrawled
    assert mirror.links == [link]


def test_rule_failure_LinkToUncrawledPage_1(tmp_path: Path) -> None:
    """Verify rule LinkToUncrawledPage is rejected when requires clause fails.

    requires: not exists known_page(page.mirror, identity).
    """
    mirror, start, _ = linked_mirror(tmp_path)
    assert link_to_uncrawled_page(link_pass(mirror), start, OTHER, None) is None
    assert mirror.links == []


def test_rule_failure_LinkToUncrawledPage_2(tmp_path: Path) -> None:
    """Verify rule LinkToUncrawledPage is rejected when requires clause fails.

    requires: not exists Page{mirror: page.mirror, identity: identity}.
    """
    mirror, start, _ = linked_mirror(tmp_path)
    removed(mirror, OLD)
    assert link_to_uncrawled_page(link_pass(mirror), start, OLD, None) is None
    assert mirror.links == []


def test_rule_failure_LinkToUncrawledPage_3(tmp_path: Path) -> None:
    """Verify rule LinkToUncrawledPage is rejected when requires clause fails.

    requires: page.mirror.scope.within_bounds(identity).
    """
    mirror, start, _ = linked_mirror(tmp_path)
    assert link_to_uncrawled_page(link_pass(mirror), start, OUTSIDE, None) is None
    assert mirror.links == []


def test_rule_entity_creation_LinkToUncrawledPage_1(tmp_path: Path) -> None:
    """Verify entity creation in rule LinkToUncrawledPage ensures clause produces the specified fields."""  # noqa: E501  The obligation's description, quoted.
    mirror, start, _ = linked_mirror(tmp_path)
    link = link_to_uncrawled_page(link_pass(mirror), start, "new.html", "part")
    assert link is not None
    assert link.source is start
    assert link.target_identity == NEW
    assert link.fragment == "part"
    assert link.kind is model.LinkKind.uncrawled
    assert link.target is None
    assert link.fragment_resolved is True


def test_rule_success_LinkToExternalPage(tmp_path: Path) -> None:
    """Verify rule LinkToExternalPage succeeds when all preconditions are met.

    Off the path prefixes, off the allowed hosts, or excluded: each is external.
    """
    mirror, start, _ = linked_mirror(tmp_path, exclude=("*/guide/excluded*",))
    pass_ = link_pass(mirror)
    targets = [OUTSIDE, "https://elsewhere.example/guide/page.html", f"{SITE}/guide/excluded.html"]
    links = [link_to_external_page(pass_, start, target, None) for target in targets]
    assert all(link is not None and link.kind is model.LinkKind.external for link in links)
    assert mirror.links == links


def test_rule_failure_LinkToExternalPage_1(tmp_path: Path) -> None:
    """Verify rule LinkToExternalPage is rejected when requires clause fails.

    requires: identity != null. The port is out of range on an allowed host and prefix,
    so only the missing identity keeps the destination from being a link (32f2210).
    """
    mirror, start, _ = linked_mirror(tmp_path)
    in_bounds = f"{SITE}:8080/guide/x.html"
    assert link_to_external_page(link_pass(mirror), start, in_bounds, None) is None
    assert mirror.links == []  # within bounds: the guard below is the null identity alone
    assert link_to_external_page(link_pass(mirror), start, UNIDENTIFIABLE, None) is None
    assert mirror.links == []


def test_rule_failure_LinkToExternalPage_2(tmp_path: Path) -> None:
    """Verify rule LinkToExternalPage is rejected when requires clause fails.

    requires: not exists known_page(page.mirror, identity).
    """
    mirror, start, other = linked_mirror(tmp_path)
    other.source_url = OUTSIDE  # the holder is known by its identity, wherever it came from
    record_alias(mirror, OUTSIDE, other)
    assert link_to_external_page(link_pass(mirror), start, OUTSIDE, None) is None
    assert mirror.links == []


def test_rule_failure_LinkToExternalPage_3(tmp_path: Path) -> None:
    """Verify rule LinkToExternalPage is rejected when requires clause fails.

    requires: not exists Page{mirror: page.mirror, identity: identity}.
    """
    mirror, start, _ = linked_mirror(tmp_path)
    removed(mirror, OLD_OUTSIDE)
    assert link_to_external_page(link_pass(mirror), start, OLD_OUTSIDE, None) is None
    assert mirror.links == []


def test_rule_failure_LinkToExternalPage_4(tmp_path: Path) -> None:
    """Verify rule LinkToExternalPage is rejected when requires clause fails.

    requires: not page.mirror.scope.within_bounds(identity).
    """
    mirror, start, _ = linked_mirror(tmp_path)
    assert link_to_external_page(link_pass(mirror), start, NEW, None) is None
    assert mirror.links == []


def test_rule_entity_creation_LinkToExternalPage_1(tmp_path: Path) -> None:
    """Verify entity creation in rule LinkToExternalPage ensures clause produces the specified fields."""  # noqa: E501  The obligation's description, quoted.
    mirror, start, _ = linked_mirror(tmp_path)
    link = link_to_external_page(link_pass(mirror), start, "/outside/x.html", "top")
    assert link is not None
    assert link.source is start
    assert link.target_identity == OUTSIDE
    assert link.fragment == "top"
    assert link.kind is model.LinkKind.external
    assert link.target is None
    assert link.fragment_resolved is True


def test_rule_success_FinishLinkPass(tmp_path: Path) -> None:
    """Verify rule FinishLinkPass succeeds when all preconditions are met.

    After a complete finalisation no relative link is broken; when a page file is gone
    the pass's broken links name it.
    """
    mirror, start, other = linked_mirror(tmp_path)
    pass_ = finalised_pass(mirror)
    rewritten = finish_link_pass(pass_)
    assert rewritten is not None
    assert rewritten.mirror is mirror
    assert rewritten.pass_ is pass_
    assert rewritten.operator is pass_.operator
    assert list(rewritten.broken) == pass_.broken_links == []

    again = finalised_pass(mirror)
    (tmp_path / other.path).unlink()
    found = finish_link_pass(again)
    assert found is not None
    missing = BrokenLink(
        from_path=start.path, href="other.md", reason=BrokenLinkReason.missing_file
    )
    assert missing in found.broken
    assert missing in again.broken_links


def test_rule_failure_FinishLinkPass_1(tmp_path: Path) -> None:
    """Verify rule FinishLinkPass is rejected when requires clause fails.

    requires: pass.status = pending.
    """
    mirror, _, other = linked_mirror(tmp_path)
    pass_ = finalised_pass(mirror)
    (tmp_path / other.path).unlink()
    pass_.status = PassStatus.completed
    assert finish_link_pass(pass_) is None
    assert pass_.broken_links == []


def broken_files(out_dir: Path) -> tuple[Mirror, Page]:
    """A finalised mirror whose seed file gains one link of each broken kind."""
    mirror, start, _ = linked_mirror(out_dir)
    finalised_pass(mirror)
    path = out_dir / start.path
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n[gone](gone.md) [up](../../../x.md) [nowhere](other.md#nope)\n",
        encoding="utf-8",
    )
    return mirror, start


def test_value_equality_BrokenLink(tmp_path: Path) -> None:
    """Verify value type BrokenLink has structural equality."""
    mirror, start = broken_files(tmp_path)
    found = find_broken_links(mirror)
    expected = BrokenLink(
        from_path=start.path, href="gone.md", reason=BrokenLinkReason.missing_file
    )
    same = BrokenLink(from_path=start.path, href="gone.md", reason=BrokenLinkReason.missing_file)
    assert expected == same
    assert expected is not same
    assert expected in found
    assert dataclasses.replace(expected, href="other.md") != expected


def test_entity_fields_BrokenLink(tmp_path: Path) -> None:
    """Verify all declared fields on BrokenLink are present with correct types."""
    mirror, start = broken_files(tmp_path)
    found = find_broken_links(mirror)
    assert found
    for row in found:
        assert_fields(row, ("from_path", "href", "reason"))
        assert row.from_path == start.path
        assert isinstance(row.href, str)
        assert isinstance(row.reason, BrokenLinkReason)


def test_enum_comparable_BrokenLinkReason(tmp_path: Path) -> None:
    """Verify fields typed with enum BrokenLinkReason are comparable."""
    mirror, _ = broken_files(tmp_path)
    reasons = {row.href: row.reason for row in find_broken_links(mirror)}
    assert reasons == {
        "gone.md": BrokenLinkReason.missing_file,
        "../../../x.md": BrokenLinkReason.outside_mirror,
        "other.md#nope": BrokenLinkReason.fragment_not_found,
    }
    assert {reason.value for reason in BrokenLinkReason} == set(
        spec_enum("mirror", "BrokenLinkReason")
    )


def test_enum_comparable_LinkKind(tmp_path: Path) -> None:
    """Verify fields typed with enum LinkKind are comparable."""
    mirror, start, _ = linked_mirror(tmp_path)
    removed(mirror, OLD)
    pass_ = link_pass(mirror)
    kinds = [
        link.kind
        for link in (
            link_to_page(pass_, start, OTHER, None),
            link_to_uncrawled_page(pass_, start, NEW, None),
            link_to_removed_page(pass_, start, OLD, None),
            link_to_external_page(pass_, start, OUTSIDE, None),
        )
        if link is not None
    ]
    assert kinds == [
        model.LinkKind.internal,
        model.LinkKind.uncrawled,
        model.LinkKind.dangling,
        model.LinkKind.external,
    ]
    assert kinds[0] == model.LinkKind.internal
    assert kinds[0] != kinds[1]
    assert {kind.value for kind in model.LinkKind} == set(spec_enum("mirror", "LinkKind"))


def test_invariant_Page_LinkFlagsAgreeWithLinks(tmp_path: Path) -> None:
    """Verify invariant LinkFlagsAgreeWithLinks holds after any field mutation on Page."""
    mirror, start, other = linked_mirror(tmp_path)
    removed(mirror, OLD)
    start.converted_body += f"\nAn [archived page]({OLD}).\n"
    finalised_pass(mirror)
    for page in mirror.written_pages:
        assert (QualityFlag.uncrawled_internal in page.flags) is page.has_uncrawled_link
        assert (QualityFlag.dangling_inbound in page.flags) is page.has_dangling_link
        assert (QualityFlag.unresolved_fragment in page.flags) is page.has_unresolved_fragment
    assert (start.has_uncrawled_link, start.has_dangling_link, start.has_unresolved_fragment) == (
        True,
        True,
        True,
    )
    assert (other.has_uncrawled_link, other.has_dangling_link, other.has_unresolved_fragment) == (
        False,
        False,
        False,
    )


def test_invariant_Link_OnlyInternalLinksHaveTargets(tmp_path: Path) -> None:
    """Verify invariant OnlyInternalLinksHaveTargets holds after any field mutation on Link."""
    mirror, _, _ = linked_mirror(tmp_path)
    removed(mirror, OLD)
    resolved(mirror)
    assert {link.kind for link in mirror.links} >= {
        model.LinkKind.internal,
        model.LinkKind.uncrawled,
        model.LinkKind.external,
    }
    for link in mirror.links:
        assert (link.kind is model.LinkKind.internal) == (link.target is not None)


def test_entity_fields_Link(tmp_path: Path) -> None:
    """Verify all declared fields on Link are present with correct types."""
    mirror, start, other = linked_mirror(tmp_path)
    resolved(mirror)
    assert mirror.links
    for link in mirror.links:
        assert_fields(
            link, ("source", "target_identity", "fragment", "kind", "target", "fragment_resolved")
        )
        assert link.source is start
        assert isinstance(link.target_identity, str)
        assert link.fragment is None or isinstance(link.fragment, str)
        assert isinstance(link.kind, model.LinkKind)
        assert link.target in {None, start, other}
        assert isinstance(link.fragment_resolved, bool)


def test_entity_optional_Link_fragment(tmp_path: Path) -> None:
    """Verify optional field Link.fragment accepts null and non-null values."""
    mirror, start, _ = linked_mirror(tmp_path)
    resolved(mirror)
    fragments = {link.fragment for link in start.outbound_links}
    assert None in fragments
    assert {"setup", "missing", "intro"} <= fragments


def test_entity_optional_Link_target(tmp_path: Path) -> None:
    """Verify optional field Link.target accepts null and non-null values."""
    mirror, start, other = linked_mirror(tmp_path)
    resolved(mirror)
    targets = {link.target_identity: link.target for link in start.outbound_links}
    assert targets[OTHER] is other
    assert targets[SEED] is start
    assert targets[NEW] is None
    assert targets[OUTSIDE] is None


def test_entity_relationship_Page_outbound_links(tmp_path: Path) -> None:
    """Verify relationship Page.outbound_links navigates to the correct related entities."""
    mirror, start, other = linked_mirror(tmp_path)
    other.converted_body += f"\nBack to the [start]({SEED}).\n"
    resolved(mirror)
    assert set(start.outbound_links) == {link for link in mirror.links if link.source is start}
    assert len(start.outbound_links) == len(LINKED_ROWS)
    assert rows(other.outbound_links) == {(SEED, None, model.LinkKind.internal, True)}


def test_entity_relationship_Page_inbound_links(tmp_path: Path) -> None:
    """Verify relationship Page.inbound_links navigates to the correct related entities."""
    mirror, start, other = linked_mirror(tmp_path)
    resolved(mirror)
    assert set(other.inbound_links) == {link for link in mirror.links if link.target is other}
    assert len(other.inbound_links) == len(("", "setup", "missing"))
    assert all(link.source is start for link in other.inbound_links)
    assert rows(start.inbound_links) == {(SEED, "intro", model.LinkKind.internal, True)}


def test_projection_Page_internal_outbound(tmp_path: Path) -> None:
    """Verify projection Page.internal_outbound filters correctly."""
    mirror, start, _ = linked_mirror(tmp_path)
    resolved(mirror)
    internal = [link for link in start.outbound_links if link.kind is model.LinkKind.internal]
    assert list(start.internal_outbound) == internal
    assert start.outbound_internal == len(internal) == len(("", "setup", "missing", "intro"))
    assert len(start.outbound_links) > len(internal)


def test_projection_Page_internal_inbound(tmp_path: Path) -> None:
    """Verify projection Page.internal_inbound filters correctly."""
    mirror, start, other = linked_mirror(tmp_path)
    other.converted_body += f"\nBack to the [start]({SEED}) and [new]({NEW}).\n"
    resolved(mirror)
    assert {link.source for link in start.internal_inbound} == {start, other}
    assert all(link.kind is model.LinkKind.internal for link in start.internal_inbound)
    assert start.inbound_internal == len(start.internal_inbound) == len(("self", "other"))
    assert other.inbound_internal == len(("", "setup", "missing"))


# --- Indexes (T11): BuildIndexes, RebuildIndexes and the index values ---------------

OTHER_TITLE = "Other page"
OTHER_DESCRIPTION = "What the other page configures."
INDEX_FIELDS = (
    "path",
    "identity",
    "source_url",
    "title",
    "description",
    "keywords",
    "headings",
    "quality_score",
    "low_confidence",
    "quality_flags",
    "content_digest",
    "version",
    "locale",
    "word_count",
    "outbound_internal",
    "inbound_internal",
)


def index_entry(path: str, **changes: object) -> IndexEntry:
    """An IndexEntry for a page at the mirror-relative `path`, constructed directly."""
    stem = path.removesuffix(".md").rsplit("/", 1)[-1]
    base = IndexEntry(
        path=path,
        identity=f"{SITE}/guide/{stem}.html",
        source_url=f"{SITE}/guide/{stem}.html",
        title=stem.capitalize(),
        description=f"About {stem}.",
        keywords=("example",),
        headings=(stem.capitalize(),),
        quality_score=1.0,
        low_confidence=False,
        quality_flags=frozenset(),
        content_digest=digest_of(path),
        version=None,
        locale="en",
        word_count=2,
        outbound_internal=0,
        inbound_internal=0,
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]  # Test overrides by name.


def digest_of(text: str) -> str:
    """A content digest stand-in: the SHA-256 of `text`."""
    return hashlib.sha256(text.encode()).hexdigest()


def indexed_mirror(out_dir: Path) -> tuple[Mirror, Page, Page, MirrorPass]:
    """linked_mirror, finalised and published, its pages titled apart; the pass pending."""
    mirror, start, other = linked_mirror(out_dir)
    other.title = OTHER_TITLE
    other.description = OTHER_DESCRIPTION
    pass_ = finalised_pass(mirror)
    return mirror, start, other, pass_


def index_of(mirror: Mirror) -> Index | None:
    """Mirror.index, read afresh: a rule may have set it since the last read."""
    return mirror.index


def built(pass_: MirrorPass) -> IndexesWritten:
    """BuildIndexes for the pending pass; it fires."""
    written = build_indexes(IndexBuildDue(pass_=pass_))
    assert written is not None
    return written


def test_rule_success_RebuildIndexes(tmp_path: Path) -> None:
    """Verify rule RebuildIndexes succeeds when all preconditions are met.

    A pending index pass raises IndexBuildDue for itself and writes nothing yet.
    """
    mirror, _, _ = linked_mirror(tmp_path)
    pass_ = request_pass(Operator(), mirror, PassKind.index, None)
    due = rebuild_indexes(pass_)
    assert isinstance(due, IndexBuildDue)
    assert due.pass_ is pass_
    assert pass_.status is PassStatus.pending
    assert mirror.index is None
    assert not (tmp_path / "index.md").exists()


def test_rule_failure_RebuildIndexes_1(tmp_path: Path) -> None:
    """Verify rule RebuildIndexes is rejected when requires clause fails.

    requires: pass.status = pending.
    """
    mirror, _, _ = linked_mirror(tmp_path)
    pass_ = request_pass(Operator(), mirror, PassKind.index, None)
    pass_.status = PassStatus.completed
    assert rebuild_indexes(pass_) is None
    assert mirror.index is None


def test_rule_failure_RebuildIndexes_2(tmp_path: Path) -> None:
    """Verify rule RebuildIndexes is rejected when requires clause fails.

    requires: pass.kind = index: a finalise pass and a verify pass raise nothing.
    """
    mirror, _, _ = linked_mirror(tmp_path)
    for kind in (PassKind.finalise, PassKind.verify):
        pass_ = request_pass(Operator(), mirror, kind, FIRST_RUN)
        assert rebuild_indexes(pass_) is None
        assert pass_.status is PassStatus.pending
    assert mirror.index is None


def test_rule_success_BuildIndexes(tmp_path: Path) -> None:
    """Verify rule BuildIndexes succeeds when all preconditions are met.

    The create branch makes the Index, the update branch sets the existing one; both
    write the index files, complete the pass and raise IndexesWritten.
    """
    mirror, start, other, pass_ = indexed_mirror(tmp_path)
    assert index_of(mirror) is None
    written = built(pass_)
    assert written.mirror is mirror
    assert written.pass_ is pass_
    assert written.operator is pass_.operator
    assert pass_.status is PassStatus.completed
    index = index_of(mirror)
    assert isinstance(index, Index)
    assert index.mirror is mirror
    assert index.entries == index_entries(mirror.written_pages)
    assert [entry.path for entry in index.entries] == [other.path, start.path]
    assert index.link_entries == link_index_entries(mirror.written_pages, mirror.aliases)
    assert index.directory_indexes == directory_indexes_for(
        index.entries, model.CONFIG.hierarchical_index_threshold
    )
    assert index.directory_indexes == []  # both pages lie at the host's top level
    assert index.summary == start.description  # the start URL's page, not the first by path
    for name in INDEX_FILES:
        assert (tmp_path / name).is_file(), name
    assert not (tmp_path / "_indexes").exists()

    other.title = "Other page, renamed"
    again = request_pass(Operator(), mirror, PassKind.index, None)
    built(again)
    assert mirror.index is index  # the update branch keeps the one Index
    assert again.status is PassStatus.completed
    assert [entry.title for entry in index.entries] == ["Other page, renamed", start.title]
    assert "Other page, renamed" in (tmp_path / "index.md").read_text(encoding="utf-8")


def test_rule_failure_BuildIndexes_1(tmp_path: Path) -> None:
    """Verify rule BuildIndexes is rejected when requires clause fails.

    requires: pass.status = pending: a completed pass builds nothing.
    """
    mirror, _, _, pass_ = indexed_mirror(tmp_path)
    pass_.status = PassStatus.completed
    assert build_indexes(IndexBuildDue(pass_=pass_)) is None
    assert mirror.index is None
    for name in INDEX_FILES:
        assert not (tmp_path / name).exists(), name


def test_value_equality_IndexEntry(tmp_path: Path) -> None:
    """Verify value type IndexEntry has structural equality."""
    mirror, _, _, _ = indexed_mirror(tmp_path)
    first = index_entries(mirror.written_pages)
    second = index_entries(mirror.written_pages)
    assert first == second
    assert first[0] is not second[0]
    assert hash(first[0]) == hash(second[0])
    assert dataclasses.replace(first[0], word_count=first[0].word_count + 1) != first[0]
    assert index_entry(f"{ROOT}a.md") == index_entry(f"{ROOT}a.md")


def test_entity_fields_IndexEntry(tmp_path: Path) -> None:
    """Verify all declared fields on IndexEntry are present with correct types.

    Every field comes from the written page; word_count is the measured word list's
    length (the ticket's interim) and the counts are the page's over Mirror.links.
    Re-propagated by T14 at a0814ab: last_modified is no longer a field, since the
    validators live in .rovo/ state alone.
    """
    mirror, start, other, _ = indexed_mirror(tmp_path)
    assert {field.name for field in dataclasses.fields(IndexEntry)} == set(INDEX_FIELDS)
    entries = {entry.path: entry for entry in index_entries(mirror.written_pages)}
    assert set(entries) == {start.path, other.path}
    for page in (start, other):
        entry = entries[page.path]
        assert_fields(entry, INDEX_FIELDS)
        assert entry.identity == page.identity
        assert entry.source_url == page.source_url
        assert entry.title == page.title
        assert entry.description == page.description
        assert list(entry.keywords) == list(page.keywords)
        assert list(entry.headings) == list(page.headings)
        assert entry.quality_score == page.quality.score
        assert isinstance(entry.quality_score, float)
        assert entry.low_confidence is page.low_confidence
        assert set(entry.quality_flags) == set(page.flags)
        assert entry.content_digest == page.content_digest
        assert entry.version == page.version
        assert entry.locale == page.locale
        assert entry.word_count == len(page.quality.output.words)
        assert entry.outbound_internal == page.outbound_internal
        assert entry.inbound_internal == page.inbound_internal
    assert entries[start.path].outbound_internal > 0
    assert entries[other.path].inbound_internal > 0


def test_value_equality_LinkIndexEntry(tmp_path: Path) -> None:
    """Verify value type LinkIndexEntry has structural equality."""
    mirror, _, _, _ = indexed_mirror(tmp_path)
    first = link_index_entries(mirror.written_pages, mirror.aliases)
    second = link_index_entries(mirror.written_pages, mirror.aliases)
    assert first
    assert first == second
    assert first[0] is not second[0]
    assert hash(first[0]) == hash(second[0])
    assert dataclasses.replace(first[0], url=f"{first[0].url}x") != first[0]


def test_entity_fields_LinkIndexEntry(tmp_path: Path) -> None:
    """Verify all declared fields on LinkIndexEntry are present with correct types.

    One entry per cited identity, without fragment, sorted by URL; path only for an
    internal one; cited_by the sorted paths of the linking pages.
    """
    mirror, start, other, _ = indexed_mirror(tmp_path)
    entries = link_index_entries(mirror.written_pages, mirror.aliases)
    for entry in entries:
        assert_fields(entry, ("url", "kind", "path", "cited_by"))
        assert isinstance(entry.kind, model.LinkKind)
        assert list(entry.cited_by) == sorted(set(entry.cited_by))
    assert [entry.url for entry in entries] == sorted({OTHER, SEED, NEW, OUTSIDE})
    rows = {entry.url: (entry.kind, entry.path, list(entry.cited_by)) for entry in entries}
    assert rows == {
        OTHER: (model.LinkKind.internal, other.path, [start.path]),
        SEED: (model.LinkKind.internal, start.path, [start.path]),
        NEW: (model.LinkKind.uncrawled, None, [start.path]),
        OUTSIDE: (model.LinkKind.external, None, [start.path]),
    }


def test_value_equality_DirectoryIndex() -> None:
    """Verify value type DirectoryIndex has structural equality."""
    entries = [index_entry(f"{ROOT}api/{name}.md") for name in ("a", "b")]
    first = directory_indexes_for(entries, 1)
    second = directory_indexes_for(entries, 1)
    assert len(first) == 1
    assert first == second
    assert first[0] is not second[0]
    assert hash(first[0]) == hash(second[0])
    assert dataclasses.replace(first[0], heading="other") != first[0]


def test_entity_fields_DirectoryIndex() -> None:
    """Verify all declared fields on DirectoryIndex are present with correct types.

    pages/docs.example/api gives _indexes/docs.example/api.md, its directory lower-cased
    and its entries in path order.
    """
    entries = [index_entry(f"{ROOT}api/{name}.md") for name in ("b", "a")]
    (directory_index,) = directory_indexes_for(entries, 1)
    assert isinstance(directory_index, DirectoryIndex)
    assert_fields(directory_index, ("directory", "path", "heading", "entries"))
    assert directory_index.directory == "pages/docs.example/api"
    assert directory_index.path == "_indexes/docs.example/api.md"
    assert directory_index.heading == "docs.example/api"
    assert [entry.path for entry in directory_index.entries] == [
        f"{ROOT}api/a.md",
        f"{ROOT}api/b.md",
    ]


def test_entity_fields_Index(tmp_path: Path) -> None:
    """Verify all declared fields on Index are present with correct types."""
    mirror, _, _, pass_ = indexed_mirror(tmp_path)
    built(pass_)
    index = mirror.index
    assert index is not None
    assert_fields(index, ("mirror", "entries", "link_entries", "directory_indexes", "summary"))
    assert all(isinstance(entry, IndexEntry) for entry in index.entries)
    assert all(isinstance(entry, LinkIndexEntry) for entry in index.link_entries)
    assert all(isinstance(entry, DirectoryIndex) for entry in index.directory_indexes)
    assert isinstance(index.summary, str)
    assert [entry.path for entry in index.entries] == sorted(mirror.page_paths)
    assert [entry.url for entry in index.link_entries] == sorted(
        entry.url for entry in index.link_entries
    )


def test_entity_relationship_Mirror_index(tmp_path: Path) -> None:
    """Verify relationship Mirror.index navigates to the correct related entities."""
    mirror = new_mirror(tmp_path)
    stored(mirror)
    assert index_of(mirror) is None
    finalise(Operator(), mirror, FIRST_RUN, FixedClock())
    index = index_of(mirror)
    assert index is not None
    assert index.mirror is mirror
    assert [entry.path for entry in index.entries] == mirror.page_paths
    other = new_mirror(tmp_path / "other")
    assert other.index is None  # one Index per mirror, never shared


def test_enum_comparable_PassKind(tmp_path: Path) -> None:
    """Verify fields typed with enum PassKind are comparable."""
    mirror = new_mirror(tmp_path)
    stored(mirror)
    finalised = finalise(Operator(), mirror, FIRST_RUN, FixedClock())
    rebuilt = index_pass(Operator(), mirror)
    assert rebuilt is not None
    kinds = [finalised.pass_.kind, rebuilt.pass_.kind]
    assert kinds == [PassKind.finalise, PassKind.index]
    assert kinds[1] == PassKind.index
    assert kinds[0] != kinds[1]
    assert {kind.value for kind in PassKind} == set(spec_enum("mirror", "PassKind"))


def test_entity_optional_MirrorPass_run_id(tmp_path: Path) -> None:
    """Verify optional field MirrorPass.run_id accepts null and non-null values.

    A finalise pass follows its run; an index pass answers a command and has none.
    """
    mirror = new_mirror(tmp_path)
    stored(mirror)
    finalised = finalise(Operator(), mirror, FIRST_RUN, FixedClock())
    rebuilt = index_pass(Operator(), mirror)
    assert rebuilt is not None
    assert finalised.pass_.run_id == FIRST_RUN
    assert rebuilt.pass_.run_id is None
    assert rebuilt.pass_.status is PassStatus.completed


def test_config_default_hierarchical_index_threshold() -> None:
    """Verify config parameter hierarchical_index_threshold has its declared default."""
    assert model.CONFIG.hierarchical_index_threshold == spec_int(
        "mirror", "hierarchical_index_threshold"
    )


def test_config_default_llms_txt_cap() -> None:
    """Verify config parameter llms_txt_cap has its declared default."""
    assert model.CONFIG.llms_txt_cap == spec_int("mirror", "llms_txt_cap")


# --- Unchanged and rewritten known pages (T14) ------------------------------------------

NEW_ETAG = '"etag-2"'
NEW_LAST_MODIFIED = "Sun, 01 Nov 2026 12:00:00 GMT"
NEW_LASTMOD = "2026-10-02"
NEW_BODY = f"{BODY}\nThe dashboard now shows a summary of every installed product.\n"
NO_PAGE_TO_CONFIRM = "no page to confirm"


def unchanged_candidate(
    mirror: Mirror,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    sitemap_lastmod: str | None = None,
    run_id: int = SECOND_RUN,
) -> PageCandidate:
    """An unchanged candidate for the seed (a 304 or the same raw document), admitted."""
    trigger = dataclasses.replace(
        delivered(mirror, run_id=run_id, outcome=CandidateOutcome.unchanged, without_content=True),
        etag=etag,
        last_modified=last_modified,
        sitemap_lastmod=sitemap_lastmod,
    )
    return admit_candidate(trigger)


def rewritten_candidate(mirror: Mirror, *, run_id: int = SECOND_RUN) -> PageCandidate:
    """A converted candidate for the seed whose body changed, admitted."""
    return admit_candidate(delivered(mirror, run_id=run_id, converted=content(body=NEW_BODY)))


def without_validators(mirror: Mirror) -> Page:
    """The seed stored from an answer that carried no ETag and no Last-Modified."""
    trigger = dataclasses.replace(delivered(mirror), etag=None, last_modified=None)
    page = store_new_page(admit_candidate(trigger), FixedClock())
    assert page is not None
    return page


def test_rule_success_RecordUnchanged(tmp_path: Path) -> None:
    """Verify rule RecordUnchanged succeeds when all preconditions are met.

    The known page is seen again: last_seen and last_seen_run move, a validator or
    lastmod the candidate carries replaces the stored one and a null one keeps it; the
    body, the measurement and every other field are carried, and PageStored names the
    page.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    before = dataclasses.replace(page)
    candidate = unchanged_candidate(mirror, etag=NEW_ETAG, sitemap_lastmod=NEW_LASTMOD)
    kept = record_unchanged(candidate, FixedClock(LATER))
    assert kept is page
    assert candidate.status is CandidateStatus.accepted
    assert mirror.pages == [page]
    assert (page.last_seen, page.last_seen_run) == (LATER, SECOND_RUN)
    assert (page.etag, page.last_modified) == (NEW_ETAG, LAST_MODIFIED)
    assert page.sitemap_lastmod == NEW_LASTMOD
    moved = {"last_seen", "last_seen_run", "etag", "sitemap_lastmod"}
    for field in dataclasses.fields(Page):
        if field.name not in moved:
            assert getattr(page, field.name) == getattr(before, field.name), field.name


def test_rule_failure_RecordUnchanged_1(tmp_path: Path) -> None:
    """Verify rule RecordUnchanged is rejected when requires clause fails.

    requires: candidate.status = pending and candidate.outcome = unchanged.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    converted = rewritten_candidate(mirror)
    assert record_unchanged(converted, FixedClock(LATER)) is None
    accepted = unchanged_candidate(mirror, etag=NEW_ETAG)
    accepted.status = CandidateStatus.accepted
    assert record_unchanged(accepted, FixedClock(LATER)) is None
    assert converted.status is CandidateStatus.pending
    assert (page.last_seen, page.last_seen_run, page.etag) == (START, FIRST_RUN, ETAG)


def test_rule_failure_RecordUnchanged_2(tmp_path: Path) -> None:
    """Verify rule RecordUnchanged is rejected when requires clause fails.

    requires: exists previous, the known page of the requested identity: none was
    stored, or the one stored was removed.
    """
    mirror = new_mirror(tmp_path / "empty")
    candidate = unchanged_candidate(mirror)
    assert record_unchanged(candidate, FixedClock(LATER)) is None
    assert candidate.status is CandidateStatus.pending
    assert mirror.pages == []

    removed_mirror = new_mirror(tmp_path / "removed")
    removed = stored(removed_mirror)
    removed.status = PageStatus.removed
    candidate = unchanged_candidate(removed_mirror)
    assert record_unchanged(candidate, FixedClock(LATER)) is None
    assert candidate.status is CandidateStatus.pending
    assert (removed.last_seen, removed.last_seen_run) == (START, FIRST_RUN)


def test_a_moved_validator_over_an_unchanged_body_rewrites_no_page_file(
    tmp_path: Path,
) -> None:
    """UnchangedRunIsStable and PageFileProvenance at a0814ab: validators stay out of files.

    The published seed is recorded unchanged with a new ETag and Last-Modified: the
    page keeps both in its state, and publishing it again is unchanged, the file's bytes
    the same.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    published(mirror, page)
    path = tmp_path / page.path
    before = path.read_bytes()
    candidate = unchanged_candidate(
        mirror, etag=NEW_ETAG, last_modified=NEW_LAST_MODIFIED, run_id=SECOND_RUN
    )
    assert record_unchanged(candidate, FixedClock(LATER)) is page
    assert (page.etag, page.last_modified) == (NEW_ETAG, NEW_LAST_MODIFIED)
    pass_ = request_pass(Operator(), mirror, PassKind.finalise, SECOND_RUN)
    finalise_page_body(pass_, page)
    event = publish_page(pass_, page, FixedClock(LATER))
    assert event.outcome is StoreOutcome.unchanged
    assert path.read_bytes() == before


def test_rule_success_DiscardUnchangedWithoutPage(tmp_path: Path) -> None:
    """Verify rule DiscardUnchangedWithoutPage succeeds when all preconditions are met.

    An unchanged candidate with no known page is accepted and discarded with the reason
    "no page to confirm"; the mirror is unchanged (unit inputs: DisposeFetch's unchanged
    branches both require a known page).
    """
    mirror = new_mirror(tmp_path)
    candidate = unchanged_candidate(mirror)
    discarded = discard_unchanged_without_page(candidate)
    assert discarded is not None
    assert discarded.candidate is candidate
    assert discarded.reason == NO_PAGE_TO_CONFIRM
    assert candidate.status is CandidateStatus.accepted
    assert mirror.pages == []
    assert mirror.aliases == []


def test_rule_failure_DiscardUnchangedWithoutPage_1(tmp_path: Path) -> None:
    """Verify rule DiscardUnchangedWithoutPage is rejected when requires clause fails.

    requires: candidate.status = pending and candidate.outcome = unchanged.
    """
    mirror = new_mirror(tmp_path)
    converted = admit_candidate(delivered(mirror))
    assert discard_unchanged_without_page(converted) is None
    accepted = unchanged_candidate(mirror)
    accepted.status = CandidateStatus.accepted
    assert discard_unchanged_without_page(accepted) is None
    assert converted.status is CandidateStatus.pending
    assert mirror.pages == []


def test_rule_failure_DiscardUnchangedWithoutPage_2(tmp_path: Path) -> None:
    """Verify rule DiscardUnchangedWithoutPage is rejected when requires clause fails.

    requires: not exists known_page(candidate.mirror, candidate.requested_identity).
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    candidate = unchanged_candidate(mirror)
    assert discard_unchanged_without_page(candidate) is None
    assert candidate.status is CandidateStatus.pending
    assert mirror.pages == [page]


def test_rule_success_RewriteKnownPage(tmp_path: Path) -> None:
    """Verify rule RewriteKnownPage succeeds when all preconditions are met.

    The requested page is its own target (previous = target): its content digest becomes
    its previous digest and RefreshPage refreshes it from the candidate, at its path, no
    page retired and no alias recorded.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    old_digest = page.content_digest
    candidate = rewritten_candidate(mirror)
    target = rewrite_known_page(candidate, FixedClock(LATER))
    assert target is page
    assert mirror.pages == [page]
    assert page.status is PageStatus.written
    assert page.path == f"{ROOT}start.md"
    assert page.previous_digest == old_digest
    assert page.converted_body == NEW_BODY
    assert (page.last_seen_run, page.last_stored_run) == (SECOND_RUN, SECOND_RUN)
    assert (page.fetched_at, page.last_seen) == (LATER, LATER)
    assert page.first_seen == START
    assert candidate.status is CandidateStatus.accepted
    assert mirror.aliases == []


def test_rule_failure_RewriteKnownPage_1(tmp_path: Path) -> None:
    """Verify rule RewriteKnownPage is rejected when requires clause fails.

    requires: candidate.status = pending and candidate.outcome = converted.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    unchanged = unchanged_candidate(mirror)
    assert rewrite_known_page(unchanged, FixedClock(LATER)) is None
    accepted = rewritten_candidate(mirror)
    accepted.status = CandidateStatus.accepted
    assert rewrite_known_page(accepted, FixedClock(LATER)) is None
    assert unchanged.status is CandidateStatus.pending
    assert page.previous_digest is None
    assert page.converted_body == BODY
    assert page.last_stored_run == FIRST_RUN


def test_rule_failure_RewriteKnownPage_2(tmp_path: Path) -> None:
    """Verify rule RewriteKnownPage is rejected when requires clause fails.

    requires: exists target and target.status = written and target.last_stored_run !=
    candidate.run_id: no page at the identity, a removed one, or one stored this run.
    """
    empty = new_mirror(tmp_path / "empty")
    candidate = rewritten_candidate(empty)
    assert rewrite_known_page(candidate, FixedClock(LATER)) is None
    assert candidate.status is CandidateStatus.pending
    assert empty.pages == []

    removed_mirror = new_mirror(tmp_path / "removed")
    removed = stored(removed_mirror)
    removed.status = PageStatus.removed
    candidate = rewritten_candidate(removed_mirror)
    assert rewrite_known_page(candidate, FixedClock(LATER)) is None
    assert candidate.status is CandidateStatus.pending
    assert removed.previous_digest is None

    same_run = new_mirror(tmp_path / "same-run")
    page = stored(same_run)
    candidate = rewritten_candidate(same_run, run_id=FIRST_RUN)
    assert rewrite_known_page(candidate, FixedClock(LATER)) is None
    assert candidate.status is CandidateStatus.pending
    assert page.previous_digest is None
    assert page.converted_body == BODY


def test_entity_optional_Page_previous_digest(tmp_path: Path) -> None:
    """Verify optional field Page.previous_digest accepts null and non-null values.

    Null on a page StoreNewPage created; its content digest before the rewrite once
    RewriteKnownPage stored it again.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    assert page.previous_digest is None
    first_digest = page.content_digest
    assert rewrite_known_page(rewritten_candidate(mirror), FixedClock(LATER)) is page
    assert page.previous_digest == first_digest


def test_entity_optional_Page_etag(tmp_path: Path) -> None:
    """Verify optional field Page.etag accepts null and non-null values.

    A page stored from an answer with no ETag has none, one with an ETag keeps it; an
    unchanged candidate with no ETag keeps the stored value, null or not (RecordUnchanged).
    """
    bare = without_validators(new_mirror(tmp_path / "bare"))
    assert bare.etag is None
    assert record_unchanged(unchanged_candidate(bare.mirror), FixedClock(LATER)) is bare
    assert bare.etag is None

    tagged = stored(new_mirror(tmp_path / "tagged"))
    assert tagged.etag == ETAG
    assert record_unchanged(unchanged_candidate(tagged.mirror), FixedClock(LATER)) is tagged
    assert tagged.etag == ETAG


def test_entity_optional_Page_last_modified(tmp_path: Path) -> None:
    """Verify optional field Page.last_modified accepts null and non-null values.

    As Page.etag: null from an answer with none, kept by an unchanged candidate with
    none, replaced by one that carries a new value (RecordUnchanged).
    """
    bare = without_validators(new_mirror(tmp_path / "bare"))
    assert bare.last_modified is None
    assert record_unchanged(unchanged_candidate(bare.mirror), FixedClock(LATER)) is bare
    assert bare.last_modified is None

    dated = stored(new_mirror(tmp_path / "dated"))
    assert dated.last_modified == LAST_MODIFIED
    assert record_unchanged(unchanged_candidate(dated.mirror), FixedClock(LATER)) is dated
    assert dated.last_modified == LAST_MODIFIED
    renewed = unchanged_candidate(dated.mirror, last_modified=NEW_LAST_MODIFIED, run_id=3)
    assert record_unchanged(renewed, FixedClock(LATER)) is dated
    assert dated.last_modified == NEW_LAST_MODIFIED


def test_entity_optional_PageCandidate_etag(tmp_path: Path) -> None:
    """Verify optional field PageCandidate.etag accepts null and non-null values.

    An unchanged candidate carries the answer's ETag, or none; RecordUnchanged takes a
    non-null one and ignores a null one.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    bare = unchanged_candidate(mirror)
    assert bare.etag is None
    assert record_unchanged(bare, FixedClock(LATER)) is page
    assert page.etag == ETAG
    tagged = unchanged_candidate(mirror, etag=NEW_ETAG, run_id=3)
    assert tagged.etag == NEW_ETAG
    assert record_unchanged(tagged, FixedClock(LATER)) is page
    assert page.etag == NEW_ETAG


def test_entity_optional_PageCandidate_last_modified(tmp_path: Path) -> None:
    """Verify optional field PageCandidate.last_modified accepts null and non-null values.

    As PageCandidate.etag, for the answer's Last-Modified.
    """
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    bare = unchanged_candidate(mirror)
    assert bare.last_modified is None
    assert record_unchanged(bare, FixedClock(LATER)) is page
    assert page.last_modified == LAST_MODIFIED
    dated = unchanged_candidate(mirror, last_modified=NEW_LAST_MODIFIED, run_id=3)
    assert dated.last_modified == NEW_LAST_MODIFIED
    assert record_unchanged(dated, FixedClock(LATER)) is page
    assert page.last_modified == NEW_LAST_MODIFIED


# --- The page lifecycle (T15) ---------------------------------------------------------
#
# Removal, archive, moves, revival and duplicates (mirror.allium RejectDuplicateCandidate
# to RetireOutOfScopePages at a0814ab). A removed page's file is archived at
# _removed/<host>/<relative path>, mirroring pages/ (RetirePage), and no file moves at
# intake: the finalise pass applies every file effect before it publishes
# (tickets/T15-lifecycle.md Facts, Open points items 1 and 2).

THIRD_RUN = 3
LATEST = START + timedelta(days=1)
AWAY = "http://elsewhere.example/away.html"
B_URL = f"{SITE}/guide/b.html"
KEEP = f"{SITE}/guide/keep/a.html"
DROP = f"{SITE}/guide/drop/b.html"
FRESH = f"{SITE}/guide/drop/c.html"
LIFECYCLE_HOLDERS = (
    f"{SITE}/guide/holder-one.html",
    f"{SITE}/guide/holder-two.html",
    f"{SITE}/guide/holder-three.html",
)


def archived(path: str) -> str:
    """The archived copy of a page path: pages/<host>/<p> is kept at _removed/<host>/<p>."""
    return "_removed/" + path.removeprefix("pages/")


def candidate_for(  # noqa: PLR0913  One keyword per candidate field a test varies.
    mirror: Mirror,
    *,
    requested: str = SEED,
    source: str | None = None,
    outcome: CandidateOutcome = CandidateOutcome.converted,
    converted: ConvertedContent | None = None,
    run_id: int = SECOND_RUN,
    hops: tuple[str, ...] = (),
    redirect_target: str | None = None,
) -> PageCandidate:
    """A pending candidate for `requested`, admitted.

    An absent or redirected-out candidate carries no validators and no content, as
    DisposeFetch delivers it; an unchanged one carries no content.
    """
    trigger = delivered(
        mirror,
        requested=requested,
        source=source,
        run_id=run_id,
        outcome=outcome,
        converted=converted,
        without_content=outcome is not CandidateOutcome.converted,
    )
    if outcome in {CandidateOutcome.absent, CandidateOutcome.redirected_out}:
        trigger = dataclasses.replace(trigger, etag=None, last_modified=None)
    return admit_candidate(
        dataclasses.replace(trigger, redirect_hops=hops, redirect_target=redirect_target)
    )


def absent_candidate(mirror: Mirror, url: str = SEED, run_id: int = SECOND_RUN) -> PageCandidate:
    """A 404 or 410 for `url`, delivered and admitted."""
    return candidate_for(mirror, requested=url, outcome=CandidateOutcome.absent, run_id=run_id)


def redirected_out_candidate(
    mirror: Mirror, url: str = SEED, run_id: int = SECOND_RUN
) -> PageCandidate:
    """`url` redirecting out of scope to AWAY, delivered and admitted."""
    return candidate_for(
        mirror,
        requested=url,
        outcome=CandidateOutcome.redirected_out,
        run_id=run_id,
        redirect_target=AWAY,
    )


def moved_candidate(mirror: Mirror, run_id: int = SECOND_RUN) -> PageCandidate:
    """OTHER now redirecting to NEW, which answers: the hop OTHER, the source NEW."""
    return candidate_for(
        mirror,
        requested=OTHER,
        source=NEW,
        hops=(OTHER,),
        run_id=run_id,
        converted=content(body=OTHER_BODY),
    )


def written_mirror(out_dir: Path, *urls: str) -> tuple[Mirror, list[Page]]:
    """A mirror whose first run stored and published one page per URL, in order."""
    mirror = new_mirror(out_dir)
    pages = [stored(mirror, requested=url, converted=content(body=OTHER_BODY)) for url in urls]
    finalise(Operator(), mirror, FIRST_RUN, FixedClock())
    return mirror, pages


def written_pair(out_dir: Path) -> tuple[Mirror, Page, Page]:
    """The seed and OTHER, stored and published by the first run."""
    mirror, (seed, other) = written_mirror(out_dir, SEED, OTHER)
    return mirror, seed, other


def finalised_run(
    mirror: Mirror, run_id: int = SECOND_RUN, clock: FixedClock | None = None
) -> Finalisation:
    """The finalise pass that follows run `run_id`."""
    return finalise(Operator(), mirror, run_id, clock or FixedClock(LATER))


def crowd(mirror: Mirror, identity: str, stem: str) -> None:
    """Hold the plain, short-suffixed and full-digest paths of `identity`: no free path."""
    full = digest(identity)
    paths = (
        f"{stem}.md",
        f"{stem}-{full[: model.CONFIG.collision_hash_chars]}.md",
        f"{stem}-{full}.md",
    )
    for holder, path in zip(LIFECYCLE_HOLDERS, paths, strict=True):
        stored(mirror, requested=holder).path = path
    assert assign_path(mirror, identity) is None


def replace_mirror_config(monkeypatch: pytest.MonkeyPatch, **changes: object) -> None:
    """Replace the mirror's CONFIG in every loaded module that binds it."""
    original = model.CONFIG
    replaced = dataclasses.replace(original, **changes)  # type: ignore[arg-type]  # Test overrides by name.
    for module in list(sys.modules.values()):
        if getattr(module, "CONFIG", None) is original:
            monkeypatch.setattr(module, "CONFIG", replaced)


def fires(answer: object) -> bool:
    """A rule fired: it answered something other than None or False."""
    return answer is not None and answer is not False


def reread[T](value: T) -> T:
    """`value` itself: a field read through it is not narrowed by an earlier assertion."""
    return value


def alias_rows(mirror: Mirror) -> list[tuple[str, str]]:
    """Every alias as (url, target identity), sorted."""
    return sorted((alias.url, alias.target.identity) for alias in mirror.aliases)


# Obligations: enumerations, relationships, projections and optional fields.


def test_enum_comparable_RemovalReason(tmp_path: Path) -> None:
    """Verify fields typed with enum RemovalReason are comparable."""
    mirror, pages = written_mirror(tmp_path, SEED, OTHER, TOPIC, NEW)
    for page, reason in zip(pages, RemovalReason, strict=True):
        assert retire_page(page, reason, FixedClock(LATER)) is not None
    assert [page.removal_reason for page in pages] == list(RemovalReason)
    assert pages[0].removal_reason == RemovalReason.absent
    assert pages[0].removal_reason != pages[1].removal_reason
    assert mirror.removed_pages == pages
    assert {reason.value for reason in RemovalReason} == set(spec_enum("mirror", "RemovalReason"))


def test_enum_comparable_CandidateOutcome(tmp_path: Path) -> None:
    """Verify fields typed with enum CandidateOutcome are comparable.

    Each outcome meets its own rules: converted and unchanged answer a stored page,
    absent and redirected_out a removal.
    """
    mirror, _, _ = written_pair(tmp_path)
    candidates = [
        candidate_for(mirror, requested=B_URL),
        candidate_for(mirror, outcome=CandidateOutcome.unchanged),
        absent_candidate(mirror, OTHER),
        redirected_out_candidate(mirror),
    ]
    answers = {
        candidate.outcome: type(settle_candidate(candidate, FixedClock(LATER)))
        for candidate in candidates
    }
    assert answers == {
        CandidateOutcome.converted: Page,
        CandidateOutcome.unchanged: Page,
        CandidateOutcome.absent: PageRemoved,
        CandidateOutcome.redirected_out: PageRemoved,
    }
    assert candidates[2].outcome == CandidateOutcome.absent
    assert candidates[2].outcome != candidates[3].outcome
    assert {outcome.value for outcome in CandidateOutcome} == set(
        spec_enum("mirror", "CandidateOutcome")
    )


def test_enum_comparable_StoreOutcome(tmp_path: Path) -> None:
    """Verify fields typed with enum StoreOutcome are comparable.

    The second run keeps the seed, rewrites TOPIC, moves OTHER to NEW and stores B_URL:
    its finalisation finds them unchanged, changed, moved and added.
    """
    mirror, _ = written_mirror(tmp_path, SEED, OTHER, TOPIC)
    clock = FixedClock(LATER)
    for candidate in (
        candidate_for(mirror, outcome=CandidateOutcome.unchanged),
        candidate_for(mirror, requested=TOPIC, converted=content(body=NEW_BODY)),
        moved_candidate(mirror),
        candidate_for(mirror, requested=B_URL),
    ):
        assert isinstance(settle_candidate(candidate, clock), Page)
    finalisation = finalised_run(mirror)
    outcomes = {event.page.identity: event.outcome for event in finalisation.finalised}
    assert outcomes == {
        SEED: StoreOutcome.unchanged,
        TOPIC: StoreOutcome.changed,
        NEW: StoreOutcome.moved,
        B_URL: StoreOutcome.added,
    }
    assert outcomes[NEW] == StoreOutcome.moved
    assert outcomes[NEW] != outcomes[B_URL]
    assert {outcome.value for outcome in StoreOutcome} == set(spec_enum("mirror", "StoreOutcome"))


def test_entity_relationship_Mirror_aliases(tmp_path: Path) -> None:
    """Verify relationship Mirror.aliases navigates to the correct related entities.

    A move leaves the old URL an alias of the moved page; retiring the page drops it.
    """
    mirror, seed, other = written_pair(tmp_path)
    assert mirror.aliases == []
    assert move_page(moved_candidate(mirror), FixedClock(LATER)) is other
    (alias,) = mirror.aliases
    assert (alias.mirror, alias.url, alias.target) == (mirror, OTHER, other)
    assert seed.aliases == []
    assert retire_page(other, RemovalReason.absent, FixedClock(LATER)) is not None
    assert mirror.aliases == []


def test_projection_Mirror_removed_pages(tmp_path: Path) -> None:
    """Verify projection Mirror.removed_pages filters correctly."""
    mirror, seed, other = written_pair(tmp_path)
    assert mirror.removed_pages == []
    assert remove_absent_page(absent_candidate(mirror, OTHER), FixedClock(LATER)) is not None
    assert mirror.removed_pages == [other]
    assert mirror.written_pages == [seed]
    revived = candidate_for(mirror, requested=OTHER, run_id=THIRD_RUN)
    assert revive_removed_page(revived, FixedClock(LATEST)) is other
    assert mirror.removed_pages == []
    assert mirror.written_pages == [seed, other]


def test_when_presence_Page_removed_at(tmp_path: Path) -> None:
    """Verify Page.removed_at is present when status in {removed} and absent otherwise."""
    mirror, _, other = written_pair(tmp_path)
    assert other.removed_at is None
    assert retire_page(other, RemovalReason.absent, FixedClock(LATER)) is not None
    assert other.status is PageStatus.removed
    assert other.removed_at == LATER
    revived = candidate_for(mirror, requested=OTHER, run_id=THIRD_RUN)
    assert revive_removed_page(revived, FixedClock(LATEST)) is other
    assert reread(other).status is PageStatus.written
    assert reread(other).removed_at is None


def test_when_presence_Page_removal_reason(tmp_path: Path) -> None:
    """Verify Page.removal_reason is present when status in {removed} and absent otherwise."""
    mirror, _, other = written_pair(tmp_path)
    assert other.removal_reason is None
    assert retire_page(other, RemovalReason.out_of_scope, FixedClock(LATER)) is not None
    assert reread(other).removal_reason is RemovalReason.out_of_scope
    revived = candidate_for(mirror, requested=OTHER, run_id=THIRD_RUN)
    assert revive_removed_page(revived, FixedClock(LATEST)) is other
    assert reread(other).removal_reason is None


def test_transition_edge_Page_written_removed(tmp_path: Path) -> None:
    """Verify transition written -> removed on Page.status is reachable via a witnessing rule.

    RetirePage, raised by RemoveAbsentPage for a 404 on a written page.
    """
    mirror, _, other = written_pair(tmp_path)
    candidate = absent_candidate(mirror, OTHER)
    answer = settle_candidate(candidate, FixedClock(LATER))
    assert answer == PageRemoved(
        mirror=mirror, page=other, reason=RemovalReason.absent, candidate=candidate
    )
    assert other.status is PageStatus.removed


def test_transition_edge_Page_removed_written(tmp_path: Path) -> None:
    """Verify transition removed -> written on Page.status is reachable via a witnessing rule.

    ReviveRemovedPage: the removed page answers again.
    """
    mirror, _, other = written_pair(tmp_path)
    assert retire_page(other, RemovalReason.absent, FixedClock(LATER)) is not None
    candidate = candidate_for(mirror, requested=OTHER, run_id=THIRD_RUN)
    assert settle_candidate(candidate, FixedClock(LATEST)) is other
    assert other.status is PageStatus.written


def test_transition_rejected_Page_status(tmp_path: Path) -> None:
    """Verify undeclared transitions on Page.status are rejected.

    removed -> removed: RetirePage does not fire on a removed page, which keeps its first
    removal. written -> written: ReviveRemovedPage does not fire on a written target.
    """
    mirror, seed, other = written_pair(tmp_path)
    assert retire_page(other, RemovalReason.absent, FixedClock(LATER)) is not None
    assert retire_page(other, RemovalReason.out_of_scope, FixedClock(LATEST)) is None
    assert (other.status, other.removed_at) == (PageStatus.removed, LATER)
    assert other.removal_reason is RemovalReason.absent
    again = candidate_for(mirror, run_id=THIRD_RUN, converted=content(body=NEW_BODY))
    assert revive_removed_page(again, FixedClock(LATEST)) is None
    assert seed.status is PageStatus.written
    assert again.status is CandidateStatus.pending


def test_entity_optional_Page_moved_from(tmp_path: Path) -> None:
    """Verify optional field Page.moved_from accepts null and non-null values.

    Null on a stored page; the old path while a move awaits finalisation; null again once
    PublishPage has published the move.
    """
    mirror, _, other = written_pair(tmp_path)
    old_path = other.path
    assert other.moved_from is None
    assert move_page(moved_candidate(mirror), FixedClock(LATER)) is other
    assert reread(other).moved_from == old_path
    finalised_run(mirror)
    assert reread(other).moved_from is None


def test_entity_optional_Page_redirect_target(tmp_path: Path) -> None:
    """Verify optional field Page.redirect_target accepts null and non-null values.

    Null on a stored page; the out-of-scope target once it redirected out; null again
    once revived.
    """
    mirror, seed, _ = written_pair(tmp_path)
    assert seed.redirect_target is None
    removal = remove_redirected_out_page(redirected_out_candidate(mirror), FixedClock(LATER))
    assert removal is not None
    assert reread(seed).redirect_target == AWAY
    revived = candidate_for(mirror, run_id=THIRD_RUN)
    assert revive_removed_page(revived, FixedClock(LATEST)) is seed
    assert reread(seed).redirect_target is None


def test_entity_relationship_Page_aliases(tmp_path: Path) -> None:
    """Verify relationship Page.aliases navigates to the correct related entities.

    Two URLs that resolve to TOPIC in the run that stored it, by a redirect and by a
    canonical, become its aliases; the seed has none.
    """
    mirror = new_mirror(tmp_path)
    seed = stored(mirror)
    topic = stored(mirror, requested=TOPIC)
    for candidate in (
        candidate_for(mirror, requested=OTHER, source=TOPIC, hops=(OTHER,), run_id=FIRST_RUN),
        candidate_for(
            mirror, requested=B_URL, converted=content(canonical_url=TOPIC), run_id=FIRST_RUN
        ),
    ):
        assert isinstance(settle_candidate(candidate, FixedClock()), CandidateDuplicate)
    assert sorted(alias.url for alias in topic.aliases) == [B_URL, OTHER]
    assert all(alias.target is topic for alias in topic.aliases)
    assert seed.aliases == []


def test_derived_Page_was_moved(tmp_path: Path) -> None:
    """Verify derived value Page.was_moved computes correctly."""
    mirror, seed, other = written_pair(tmp_path)
    assert not other.was_moved
    assert move_page(moved_candidate(mirror), FixedClock(LATER)) is other
    assert reread(other).was_moved
    assert not seed.was_moved
    finalised_run(mirror)
    assert not reread(other).was_moved


def test_transition_edge_PageCandidate_pending_duplicate(tmp_path: Path) -> None:
    """Verify transition pending -> duplicate on PageCandidate.status is reachable via a witnessing rule.

    RejectDuplicateCandidate: a second URL resolving to the page this run stored.
    """  # noqa: E501  The obligation's description, quoted.
    mirror = new_mirror(tmp_path)
    topic = stored(mirror, requested=TOPIC, run_id=SECOND_RUN)
    candidate = candidate_for(mirror, requested=OTHER, source=TOPIC, hops=(OTHER,))
    assert candidate.status is CandidateStatus.pending
    answer = settle_candidate(candidate, FixedClock(LATER))
    assert answer == CandidateDuplicate(candidate=candidate, page=topic)
    assert reread(candidate).status is CandidateStatus.duplicate


def test_entity_optional_PageCandidate_redirect_target(tmp_path: Path) -> None:
    """Verify optional field PageCandidate.redirect_target accepts null and non-null values.

    Null on a converted candidate, whose page records none; the out-of-scope target on a
    redirected-out one, which the removed page records.
    """
    mirror = new_mirror(tmp_path)
    plain = candidate_for(mirror, run_id=FIRST_RUN)
    assert plain.redirect_target is None
    page = settle_candidate(plain, FixedClock())
    assert isinstance(page, Page)
    assert page.redirect_target is None
    out = redirected_out_candidate(mirror)
    assert out.redirect_target == AWAY
    removal = settle_candidate(out, FixedClock(LATER))
    assert isinstance(removal, PageRemoved)
    assert removal.page is page
    assert page.redirect_target == AWAY


def test_entity_optional_PageCandidate_content(tmp_path: Path) -> None:
    """Verify optional field PageCandidate.content accepts null and non-null values.

    Present on a converted candidate, which stores a page; null on an absent one, which
    removes it.
    """
    mirror = new_mirror(tmp_path)
    converted = candidate_for(mirror, run_id=FIRST_RUN)
    assert converted.content is not None
    page = settle_candidate(converted, FixedClock())
    assert isinstance(page, Page)
    gone = absent_candidate(mirror)
    assert gone.content is None
    removal = settle_candidate(gone, FixedClock(LATER))
    assert isinstance(removal, PageRemoved)
    assert removal.page is page


def test_config_default_prune(tmp_path: Path) -> None:
    """Verify config parameter prune has its declared default.

    The default, false, archives a retired page's file rather than deleting it.
    """
    assert model.CONFIG.prune == spec_bool("mirror", "prune")
    assert model.CONFIG.prune is False
    mirror, _, other = written_pair(tmp_path)
    published_bytes = (tmp_path / other.path).read_bytes()
    assert retire_page(other, RemovalReason.absent, FixedClock(LATER)) is not None
    finalised_run(mirror)
    assert not (tmp_path / other.path).exists()
    assert (tmp_path / archived(other.path)).read_bytes() == published_bytes


# Obligations: the intake rules.


def test_rule_success_RejectDuplicateCandidate(tmp_path: Path) -> None:
    """Verify rule RejectDuplicateCandidate succeeds when all preconditions are met.

    OTHER, written by the first run, now redirects to TOPIC, which this run stored: the
    first store's content stands, OTHER is merged into TOPIC and becomes its alias, and
    the candidate is marked a duplicate.
    """
    mirror = new_mirror(tmp_path)
    older = stored(mirror, requested=OTHER)
    topic = stored(mirror, requested=TOPIC, run_id=SECOND_RUN)
    candidate = candidate_for(
        mirror, requested=OTHER, source=TOPIC, hops=(OTHER,), converted=content(body=NEW_BODY)
    )
    answer = reject_duplicate_candidate(candidate)
    assert answer == CandidateDuplicate(candidate=candidate, page=topic)
    assert candidate.status is CandidateStatus.duplicate
    assert topic.converted_body == BODY
    assert topic.last_stored_run == SECOND_RUN
    assert older.status is PageStatus.removed
    assert older.removal_reason is RemovalReason.merged
    assert alias_rows(mirror) == [(OTHER, TOPIC)]


def test_rule_failure_RejectDuplicateCandidate_1(tmp_path: Path) -> None:
    """Verify rule RejectDuplicateCandidate is rejected when requires clause fails.

    requires: candidate.status = pending and candidate.outcome = converted.
    """
    mirror = new_mirror(tmp_path)
    topic = stored(mirror, requested=TOPIC, run_id=SECOND_RUN)
    unchanged = candidate_for(mirror, requested=TOPIC, outcome=CandidateOutcome.unchanged)
    assert reject_duplicate_candidate(unchanged) is None
    accepted = candidate_for(mirror, requested=OTHER, source=TOPIC, hops=(OTHER,))
    accepted.status = CandidateStatus.accepted
    assert reject_duplicate_candidate(accepted) is None
    assert unchanged.status is CandidateStatus.pending
    assert accepted.status is CandidateStatus.accepted
    assert topic.aliases == []


def test_rule_failure_RejectDuplicateCandidate_2(tmp_path: Path) -> None:
    """Verify rule RejectDuplicateCandidate is rejected when requires clause fails.

    requires: exists target and target.status = written and target.last_stored_run =
    candidate.run_id: no page at the identity, a removed one, or one an earlier run
    stored.
    """
    empty = new_mirror(tmp_path / "empty")
    candidate = candidate_for(empty, requested=OTHER, source=TOPIC, hops=(OTHER,))
    assert reject_duplicate_candidate(candidate) is None
    assert candidate.status is CandidateStatus.pending

    gone = new_mirror(tmp_path / "removed")
    removed(gone, TOPIC).last_stored_run = SECOND_RUN
    candidate = candidate_for(gone, requested=OTHER, source=TOPIC, hops=(OTHER,))
    assert reject_duplicate_candidate(candidate) is None
    assert candidate.status is CandidateStatus.pending

    earlier = new_mirror(tmp_path / "earlier")
    topic = stored(earlier, requested=TOPIC)
    candidate = candidate_for(earlier, requested=OTHER, source=TOPIC, hops=(OTHER,))
    assert reject_duplicate_candidate(candidate) is None
    assert candidate.status is CandidateStatus.pending
    assert topic.aliases == []


def test_rule_success_MovePage(tmp_path: Path) -> None:
    """Verify rule MovePage succeeds when all preconditions are met.

    OTHER now redirects to NEW, which no page holds: the page keeps its record and
    history, takes NEW's identity and path, keeps its old path as moved_from and its
    digest as previous_digest, and OTHER becomes its alias. No file moves at intake; the
    finalisation moves it and reports moved with the old path.
    """
    mirror, seed, other = written_pair(tmp_path)
    old_path, old_digest = other.path, other.content_digest
    candidate = moved_candidate(mirror)
    assert move_page(candidate, FixedClock(LATER)) is other
    assert mirror.pages == [seed, other]
    assert (other.identity, other.path) == (NEW, f"{ROOT}new.md")
    assert other.moved_from == old_path
    assert other.previous_digest == old_digest
    assert other.first_seen == START
    assert (other.last_stored_run, other.fetched_at) == (SECOND_RUN, LATER)
    assert candidate.status is CandidateStatus.accepted
    assert alias_rows(mirror) == [(OTHER, NEW)]
    assert (tmp_path / old_path).is_file()
    assert not (tmp_path / other.path).exists()
    finalisation = finalised_run(mirror)
    (event,) = [event for event in finalisation.finalised if event.page is other]
    assert (event.outcome, event.previous_path) == (StoreOutcome.moved, old_path)
    assert not (tmp_path / old_path).exists()
    assert (tmp_path / other.path).is_file()


def test_rule_failure_MovePage_1(tmp_path: Path) -> None:
    """Verify rule MovePage is rejected when requires clause fails.

    requires: candidate.status = pending and candidate.outcome = converted.
    """
    mirror, _, other = written_pair(tmp_path)
    unchanged = candidate_for(
        mirror, requested=OTHER, source=NEW, hops=(OTHER,), outcome=CandidateOutcome.unchanged
    )
    assert move_page(unchanged, FixedClock(LATER)) is None
    accepted = moved_candidate(mirror)
    accepted.status = CandidateStatus.accepted
    assert move_page(accepted, FixedClock(LATER)) is None
    assert (other.identity, other.moved_from) == (OTHER, None)
    assert unchanged.status is CandidateStatus.pending


def test_rule_failure_MovePage_2(tmp_path: Path) -> None:
    """Verify rule MovePage is rejected when requires clause fails.

    requires: exists previous: no known page for the requested identity, none stored or
    only a removed one.
    """
    empty = new_mirror(tmp_path / "empty")
    candidate = moved_candidate(empty)
    assert move_page(candidate, FixedClock(LATER)) is None
    assert candidate.status is CandidateStatus.pending
    assert empty.pages == []

    gone = new_mirror(tmp_path / "removed")
    page = removed(gone, OTHER)
    candidate = moved_candidate(gone)
    assert move_page(candidate, FixedClock(LATER)) is None
    assert (page.identity, page.status) == (OTHER, PageStatus.removed)


def test_rule_failure_MovePage_3(tmp_path: Path) -> None:
    """Verify rule MovePage is rejected when requires clause fails.

    requires: not exists target or target.status = removed: OTHER's new canonical names
    the seed, a written page.
    """
    mirror, seed, other = written_pair(tmp_path)
    candidate = candidate_for(mirror, requested=OTHER, converted=content(canonical_url=SEED))
    assert move_page(candidate, FixedClock(LATER)) is None
    assert (other.identity, other.path, other.moved_from) == (OTHER, f"{ROOT}other.md", None)
    assert seed.previous_digest == seed.content_digest  # untouched since its publication
    assert candidate.status is CandidateStatus.pending


def test_rule_failure_MovePage_4(tmp_path: Path) -> None:
    """Verify rule MovePage is rejected when requires clause fails.

    requires: new_path != null: every path assign_path could give NEW is held.
    """
    mirror, _, other = written_pair(tmp_path)
    crowd(mirror, NEW, f"{ROOT}new")
    candidate = moved_candidate(mirror)
    assert move_page(candidate, FixedClock(LATER)) is None
    assert (other.identity, other.path, other.moved_from) == (OTHER, f"{ROOT}other.md", None)
    assert candidate.status is CandidateStatus.pending
    assert mirror.aliases == []


def test_rule_success_ReviveRemovedPage(tmp_path: Path) -> None:
    """Verify rule ReviveRemovedPage succeeds when all preconditions are met.

    A page removed and archived by the second run answers again in the third: it is
    written at its old path, its removal fields cleared, new again (previous_digest
    null, first_seen now), and its archived copy leaves the removed area.
    """
    mirror, _, other = written_pair(tmp_path)
    assert retire_page(other, RemovalReason.absent, FixedClock(LATER)) is not None
    finalised_run(mirror)
    assert (tmp_path / archived(other.path)).is_file()
    candidate = candidate_for(
        mirror, requested=OTHER, run_id=THIRD_RUN, converted=content(body=OTHER_BODY)
    )
    assert revive_removed_page(candidate, FixedClock(LATEST)) is other
    assert other.status is PageStatus.written
    assert (other.removed_at, other.removal_reason, other.redirect_target) == (None, None, None)
    assert other.path == f"{ROOT}other.md"
    assert other.previous_digest is None
    assert other.first_seen == LATEST
    assert candidate.status is CandidateStatus.accepted
    finalisation = finalised_run(mirror, THIRD_RUN, FixedClock(LATEST))
    (event,) = [event for event in finalisation.finalised if event.page is other]
    assert event.outcome is StoreOutcome.added
    assert (tmp_path / other.path).is_file()
    assert not (tmp_path / archived(other.path)).exists()


def test_rule_failure_ReviveRemovedPage_1(tmp_path: Path) -> None:
    """Verify rule ReviveRemovedPage is rejected when requires clause fails.

    requires: candidate.status = pending and candidate.outcome = converted.
    """
    mirror = new_mirror(tmp_path)
    page = removed(mirror, OTHER)
    unchanged = candidate_for(mirror, requested=OTHER, outcome=CandidateOutcome.unchanged)
    assert revive_removed_page(unchanged, FixedClock(LATER)) is None
    accepted = candidate_for(mirror, requested=OTHER)
    accepted.status = CandidateStatus.accepted
    assert revive_removed_page(accepted, FixedClock(LATER)) is None
    assert page.status is PageStatus.removed
    assert unchanged.status is CandidateStatus.pending


def test_rule_failure_ReviveRemovedPage_2(tmp_path: Path) -> None:
    """Verify rule ReviveRemovedPage is rejected when requires clause fails.

    requires: not exists previous: OTHER's record is removed, but OTHER is an alias of
    the written seed, so the requested identity has a known page.
    """
    mirror = new_mirror(tmp_path)
    seed = stored(mirror)
    page = removed(mirror, OTHER)
    assert record_alias(mirror, OTHER, seed) is not None
    candidate = candidate_for(mirror, requested=OTHER)
    assert revive_removed_page(candidate, FixedClock(LATER)) is None
    assert page.status is PageStatus.removed
    assert candidate.status is CandidateStatus.pending


def test_rule_failure_ReviveRemovedPage_3(tmp_path: Path) -> None:
    """Verify rule ReviveRemovedPage is rejected when requires clause fails.

    requires: exists target and target.status = removed: no record at the identity.
    """
    mirror = new_mirror(tmp_path)
    candidate = candidate_for(mirror, requested=OTHER)
    assert revive_removed_page(candidate, FixedClock(LATER)) is None
    assert mirror.pages == []
    assert candidate.status is CandidateStatus.pending


def test_rule_failure_ReviveRemovedPage_4(tmp_path: Path) -> None:
    """Verify rule ReviveRemovedPage is rejected when requires clause fails.

    requires: new_path != null: the removed record's old path and both fallbacks are
    held by other pages, so the record stays removed.
    """
    mirror = new_mirror(tmp_path)
    page = removed(mirror, NEW)
    page.path = f"{ROOT}archived/new.md"
    crowd(mirror, NEW, f"{ROOT}new")
    candidate = candidate_for(mirror, requested=NEW)
    assert revive_removed_page(candidate, FixedClock(LATER)) is None
    assert (page.status, page.path) == (PageStatus.removed, f"{ROOT}archived/new.md")
    assert candidate.status is CandidateStatus.pending


def test_rule_success_RemoveAbsentPage(tmp_path: Path) -> None:
    """Verify rule RemoveAbsentPage succeeds when all preconditions are met.

    A 404 on a written page retires it with reason absent; a 404 on a URL that is only
    an alias retires the page the alias names.
    """
    mirror, seed, other = written_pair(tmp_path)
    candidate = absent_candidate(mirror, OTHER)
    answer = remove_absent_page(candidate, FixedClock(LATER))
    assert answer == PageRemoved(
        mirror=mirror, page=other, reason=RemovalReason.absent, candidate=candidate
    )
    assert candidate.status is CandidateStatus.accepted
    assert (other.status, other.removal_reason) == (PageStatus.removed, RemovalReason.absent)
    assert (other.removed_at, other.path) == (LATER, f"{ROOT}other.md")
    assert record_alias(mirror, OLD, seed) is not None
    via_alias = absent_candidate(mirror, OLD)
    removal = remove_absent_page(via_alias, FixedClock(LATER))
    assert removal is not None
    assert removal.page is seed
    assert seed.status is PageStatus.removed


def test_rule_failure_RemoveAbsentPage_1(tmp_path: Path) -> None:
    """Verify rule RemoveAbsentPage is rejected when requires clause fails.

    requires: candidate.status = pending and candidate.outcome = absent.
    """
    mirror, seed, _ = written_pair(tmp_path)
    out = redirected_out_candidate(mirror)
    assert remove_absent_page(out, FixedClock(LATER)) is None
    accepted = absent_candidate(mirror)
    accepted.status = CandidateStatus.accepted
    assert remove_absent_page(accepted, FixedClock(LATER)) is None
    assert seed.status is PageStatus.written
    assert out.status is CandidateStatus.pending


def test_rule_failure_RemoveAbsentPage_2(tmp_path: Path) -> None:
    """Verify rule RemoveAbsentPage is rejected when requires clause fails.

    requires: exists previous: no page was stored, or the one stored is removed already.
    """
    empty = new_mirror(tmp_path / "empty")
    candidate = absent_candidate(empty)
    assert remove_absent_page(candidate, FixedClock(LATER)) is None
    assert candidate.status is CandidateStatus.pending

    gone = new_mirror(tmp_path / "removed")
    page = removed(gone, SEED)
    candidate = absent_candidate(gone)
    assert remove_absent_page(candidate, FixedClock(LATER)) is None
    assert (page.removed_at, page.removal_reason) == (START, RemovalReason.absent)


def test_rule_success_AcceptAbsentWithoutPage(tmp_path: Path) -> None:
    """Verify rule AcceptAbsentWithoutPage succeeds when all preconditions are met.

    A 404 on a URL with no written page, never stored or removed already, is accepted
    and changes nothing.
    """
    empty = new_mirror(tmp_path / "empty")
    candidate = absent_candidate(empty)
    assert accept_absent_without_page(candidate) is True
    assert candidate.status is CandidateStatus.accepted
    assert empty.pages == []

    gone = new_mirror(tmp_path / "removed")
    page = removed(gone, SEED)
    candidate = absent_candidate(gone)
    assert accept_absent_without_page(candidate) is True
    assert candidate.status is CandidateStatus.accepted
    assert (page.removed_at, page.removal_reason) == (START, RemovalReason.absent)


def test_rule_failure_AcceptAbsentWithoutPage_1(tmp_path: Path) -> None:
    """Verify rule AcceptAbsentWithoutPage is rejected when requires clause fails.

    requires: candidate.status = pending and candidate.outcome = absent.
    """
    mirror = new_mirror(tmp_path)
    out = redirected_out_candidate(mirror)
    assert accept_absent_without_page(out) is False
    accepted = absent_candidate(mirror)
    accepted.status = CandidateStatus.accepted
    assert accept_absent_without_page(accepted) is False
    assert out.status is CandidateStatus.pending


def test_rule_failure_AcceptAbsentWithoutPage_2(tmp_path: Path) -> None:
    """Verify rule AcceptAbsentWithoutPage is rejected when requires clause fails.

    requires: not exists known_page(candidate.mirror, candidate.requested_identity).
    """
    mirror, seed, _ = written_pair(tmp_path)
    candidate = absent_candidate(mirror)
    assert accept_absent_without_page(candidate) is False
    assert candidate.status is CandidateStatus.pending
    assert seed.status is PageStatus.written


def test_rule_success_RemoveRedirectedOutPage(tmp_path: Path) -> None:
    """Verify rule RemoveRedirectedOutPage succeeds when all preconditions are met.

    A written page that now redirects out of scope is retired with reason
    redirected_out, and the target is recorded on its record.
    """
    mirror, seed, _ = written_pair(tmp_path)
    candidate = redirected_out_candidate(mirror)
    answer = remove_redirected_out_page(candidate, FixedClock(LATER))
    assert answer == PageRemoved(
        mirror=mirror, page=seed, reason=RemovalReason.redirected_out, candidate=candidate
    )
    assert candidate.status is CandidateStatus.accepted
    assert seed.status is PageStatus.removed
    assert (seed.removal_reason, seed.redirect_target) == (RemovalReason.redirected_out, AWAY)


def test_rule_failure_RemoveRedirectedOutPage_1(tmp_path: Path) -> None:
    """Verify rule RemoveRedirectedOutPage is rejected when requires clause fails.

    requires: candidate.status = pending and candidate.outcome = redirected_out.
    """
    mirror, seed, _ = written_pair(tmp_path)
    gone = absent_candidate(mirror)
    assert remove_redirected_out_page(gone, FixedClock(LATER)) is None
    accepted = redirected_out_candidate(mirror)
    accepted.status = CandidateStatus.accepted
    assert remove_redirected_out_page(accepted, FixedClock(LATER)) is None
    assert (seed.status, seed.redirect_target) == (PageStatus.written, None)
    assert gone.status is CandidateStatus.pending


def test_rule_failure_RemoveRedirectedOutPage_2(tmp_path: Path) -> None:
    """Verify rule RemoveRedirectedOutPage is rejected when requires clause fails.

    requires: exists previous: no known page for the requested identity.
    """
    mirror = new_mirror(tmp_path)
    candidate = redirected_out_candidate(mirror)
    assert remove_redirected_out_page(candidate, FixedClock(LATER)) is None
    assert candidate.status is CandidateStatus.pending
    assert mirror.pages == []


def test_rule_success_AcceptRedirectedOutWithoutPage(tmp_path: Path) -> None:
    """Verify rule AcceptRedirectedOutWithoutPage succeeds when all preconditions are met.

    Unit inputs: DisposeFetch delivers redirected_out only for a known page.
    """
    mirror = new_mirror(tmp_path)
    candidate = redirected_out_candidate(mirror)
    assert accept_redirected_out_without_page(candidate) is True
    assert candidate.status is CandidateStatus.accepted
    assert mirror.pages == []


def test_rule_failure_AcceptRedirectedOutWithoutPage_1(tmp_path: Path) -> None:
    """Verify rule AcceptRedirectedOutWithoutPage is rejected when requires clause fails.

    requires: candidate.status = pending and candidate.outcome = redirected_out.
    """
    mirror = new_mirror(tmp_path)
    gone = absent_candidate(mirror)
    assert accept_redirected_out_without_page(gone) is False
    accepted = redirected_out_candidate(mirror)
    accepted.status = CandidateStatus.accepted
    assert accept_redirected_out_without_page(accepted) is False
    assert gone.status is CandidateStatus.pending


def test_rule_failure_AcceptRedirectedOutWithoutPage_2(tmp_path: Path) -> None:
    """Verify rule AcceptRedirectedOutWithoutPage is rejected when requires clause fails.

    requires: not exists known_page(candidate.mirror, candidate.requested_identity).
    """
    mirror, seed, _ = written_pair(tmp_path)
    candidate = redirected_out_candidate(mirror)
    assert accept_redirected_out_without_page(candidate) is False
    assert candidate.status is CandidateStatus.pending
    assert seed.status is PageStatus.written


def test_rule_success_RetirePage(tmp_path: Path) -> None:
    """Verify rule RetirePage succeeds when all preconditions are met.

    The page keeps its record and path; its aliases and outbound links go; its file
    stays where it is until the finalise pass archives it at _removed/<host>/.
    """
    mirror, start, _ = linked_mirror(tmp_path)
    finalised_pass(mirror)
    assert start.outbound_links
    assert record_alias(mirror, OLD, start) is not None
    published_bytes = (tmp_path / start.path).read_bytes()
    answer = retire_page(start, RemovalReason.absent, FixedClock(LATER))
    assert answer == PageRemoved(mirror=mirror, page=start, reason=RemovalReason.absent)
    assert start.status is PageStatus.removed
    assert (start.removed_at, start.removal_reason) == (LATER, RemovalReason.absent)
    assert (start.redirect_target, start.moved_from) == (None, None)
    assert (start.identity, start.path) == (SEED, f"{ROOT}start.md")
    assert start in mirror.pages
    assert start.aliases == []
    assert start.outbound_links == ()
    assert (tmp_path / start.path).read_bytes() == published_bytes
    finalised_run(mirror)
    assert not (tmp_path / start.path).exists()
    assert (tmp_path / archived(start.path)).read_bytes() == published_bytes


def test_rule_failure_RetirePage_1(tmp_path: Path) -> None:
    """Verify rule RetirePage is rejected when requires clause fails.

    requires: page.status = written.
    """
    mirror = new_mirror(tmp_path)
    page = removed(mirror, SEED)
    assert retire_page(page, RemovalReason.out_of_scope, FixedClock(LATER)) is None
    assert (page.removed_at, page.removal_reason) == (START, RemovalReason.absent)
    assert page.status is PageStatus.removed


def test_when_set_RetirePage_Page_removed_at(tmp_path: Path) -> None:
    """Verify rule RetirePage sets Page.removed_at when transitioning status from written to removed (entering when set {removed})."""  # noqa: E501  The obligation's description, quoted.
    _, seed, _ = written_pair(tmp_path)
    assert seed.removed_at is None
    assert retire_page(seed, RemovalReason.merged, FixedClock(LATEST)) is not None
    assert seed.removed_at == LATEST


def test_when_set_RetirePage_Page_removal_reason(tmp_path: Path) -> None:
    """Verify rule RetirePage sets Page.removal_reason when transitioning status from written to removed (entering when set {removed})."""  # noqa: E501  The obligation's description, quoted.
    _, seed, other = written_pair(tmp_path)
    assert (seed.removal_reason, other.removal_reason) == (None, None)
    redirected = retire_page(
        seed, RemovalReason.redirected_out, FixedClock(LATER), redirect_target=AWAY
    )
    assert redirected is not None
    assert (seed.removal_reason, seed.redirect_target) == (RemovalReason.redirected_out, AWAY)
    assert retire_page(other, RemovalReason.merged, FixedClock(LATER)) is not None
    assert other.removal_reason is RemovalReason.merged


def narrowed(out_dir: Path) -> tuple[Mirror, Page, Page, Page, Page]:
    """The seed, KEEP, DROP and FRESH published; then the prefix narrows to /guide/keep/.

    FRESH was stored by the second run, so a finalisation following that run keeps it.
    """
    mirror = new_mirror(out_dir)
    seed = stored(mirror)
    keep = stored(mirror, requested=KEEP)
    drop = stored(mirror, requested=DROP)
    fresh = stored(mirror, requested=FRESH, run_id=SECOND_RUN)
    finalise(Operator(), mirror, FIRST_RUN, FixedClock())
    mirror.scope = scope(path_prefixes=("/guide/keep/",))
    return mirror, seed, keep, drop, fresh


def test_rule_success_RetireOutOfScopePages(tmp_path: Path) -> None:
    """Verify rule RetireOutOfScopePages succeeds when all preconditions are met.

    A finalisation following the second run retires DROP, whose source URL the narrowed
    scope no longer admits; the seed stays (a seed is always in bounds), KEEP is in
    bounds, and FRESH was stored by that run. A command's pass (run_id null) retires
    FRESH too.
    """
    mirror, seed, keep, drop, fresh = narrowed(tmp_path)
    pass_ = request_pass(Operator(), mirror, PassKind.finalise, SECOND_RUN)
    retired = retire_out_of_scope_pages(pass_, FixedClock(LATER))
    assert retired == [PageRemoved(mirror=mirror, page=drop, reason=RemovalReason.out_of_scope)]
    assert (drop.status, drop.removal_reason) == (PageStatus.removed, RemovalReason.out_of_scope)
    assert mirror.written_pages == [seed, keep, fresh]
    command = request_pass(Operator(), mirror, PassKind.finalise, None)
    retired = retire_out_of_scope_pages(command, FixedClock(LATER))
    assert retired == [PageRemoved(mirror=mirror, page=fresh, reason=RemovalReason.out_of_scope)]
    assert mirror.written_pages == [seed, keep]


def test_rule_failure_RetireOutOfScopePages_1(tmp_path: Path) -> None:
    """Verify rule RetireOutOfScopePages is rejected when requires clause fails.

    requires: pass.status = pending.
    """
    mirror, _, _, drop, _ = narrowed(tmp_path)
    pass_ = request_pass(Operator(), mirror, PassKind.finalise, SECOND_RUN)
    pass_.status = PassStatus.completed
    assert retire_out_of_scope_pages(pass_, FixedClock(LATER)) is None
    assert drop.status is PageStatus.written


def test_rule_failure_RetireOutOfScopePages_2(tmp_path: Path) -> None:
    """Verify rule RetireOutOfScopePages is rejected when requires clause fails.

    requires: pass.kind = finalise.
    """
    mirror, _, _, drop, _ = narrowed(tmp_path)
    pass_ = request_pass(Operator(), mirror, PassKind.index, SECOND_RUN)
    assert retire_out_of_scope_pages(pass_, FixedClock(LATER)) is None
    assert drop.status is PageStatus.written


# Guarantees and black boxes (no obligation id; tickets/T15-lifecycle.md step 3).


def case_store(out_dir: Path) -> PageCandidate:
    """StoreNewPage's case: a converted URL with no record."""
    return candidate_for(new_mirror(out_dir))


def case_refuse(out_dir: Path) -> PageCandidate:
    """RefuseUnplaceableCandidate's case: no free path for a new identity."""
    mirror = new_mirror(out_dir)
    crowd(mirror, NEW, f"{ROOT}new")
    return candidate_for(mirror, requested=NEW)


def case_duplicate(out_dir: Path) -> PageCandidate:
    """RejectDuplicateCandidate's case: a redirect to the page this run stored."""
    mirror = new_mirror(out_dir)
    stored(mirror, requested=TOPIC, run_id=SECOND_RUN)
    return candidate_for(mirror, requested=OTHER, source=TOPIC, hops=(OTHER,))


def case_rewrite(out_dir: Path) -> PageCandidate:
    """RewriteKnownPage's case: a known page reconverted by a later run."""
    mirror = new_mirror(out_dir)
    stored(mirror)
    return candidate_for(mirror, converted=content(body=NEW_BODY))


def case_move(out_dir: Path) -> PageCandidate:
    """MovePage's case: a known page whose identity moves to a URL no page holds."""
    mirror = new_mirror(out_dir)
    stored(mirror, requested=OTHER)
    return moved_candidate(mirror)


def case_revive(out_dir: Path) -> PageCandidate:
    """ReviveRemovedPage's case: a removed page answers again."""
    mirror = new_mirror(out_dir)
    removed(mirror, SEED)
    return candidate_for(mirror)


def case_unchanged(out_dir: Path) -> PageCandidate:
    """RecordUnchanged's case: a known page confirmed unchanged."""
    mirror = new_mirror(out_dir)
    stored(mirror)
    return candidate_for(mirror, outcome=CandidateOutcome.unchanged)


def case_discard(out_dir: Path) -> PageCandidate:
    """DiscardUnchangedWithoutPage's case: unchanged with no page."""
    return candidate_for(new_mirror(out_dir), outcome=CandidateOutcome.unchanged)


def case_remove_absent(out_dir: Path) -> PageCandidate:
    """RemoveAbsentPage's case: a 404 on a written page."""
    mirror = new_mirror(out_dir)
    stored(mirror)
    return absent_candidate(mirror)


def case_accept_absent(out_dir: Path) -> PageCandidate:
    """AcceptAbsentWithoutPage's case: a 404 with no page."""
    return absent_candidate(new_mirror(out_dir))


def case_remove_redirected_out(out_dir: Path) -> PageCandidate:
    """RemoveRedirectedOutPage's case: a written page redirecting out of scope."""
    mirror = new_mirror(out_dir)
    stored(mirror)
    return redirected_out_candidate(mirror)


def case_accept_redirected_out(out_dir: Path) -> PageCandidate:
    """AcceptRedirectedOutWithoutPage's case: redirected out with no page."""
    return redirected_out_candidate(new_mirror(out_dir))


INTAKE_RULES: tuple[tuple[str, Callable[[PageCandidate], object]], ...] = (
    ("StoreNewPage", lambda candidate: store_new_page(candidate, FixedClock(LATER))),
    ("RefuseUnplaceableCandidate", refuse_unplaceable_candidate),
    ("RejectDuplicateCandidate", reject_duplicate_candidate),
    ("RewriteKnownPage", lambda candidate: rewrite_known_page(candidate, FixedClock(LATER))),
    ("MovePage", lambda candidate: move_page(candidate, FixedClock(LATER))),
    ("ReviveRemovedPage", lambda candidate: revive_removed_page(candidate, FixedClock(LATER))),
    ("RecordUnchanged", lambda candidate: record_unchanged(candidate, FixedClock(LATER))),
    ("DiscardUnchangedWithoutPage", discard_unchanged_without_page),
    ("RemoveAbsentPage", lambda candidate: remove_absent_page(candidate, FixedClock(LATER))),
    ("AcceptAbsentWithoutPage", accept_absent_without_page),
    (
        "RemoveRedirectedOutPage",
        lambda candidate: remove_redirected_out_page(candidate, FixedClock(LATER)),
    ),
    ("AcceptRedirectedOutWithoutPage", accept_redirected_out_without_page),
)


@pytest.mark.parametrize(
    ("build", "rule", "answer"),
    [
        pytest.param(case_store, "StoreNewPage", Page, id="store"),
        pytest.param(case_refuse, "RefuseUnplaceableCandidate", CandidateDiscarded, id="refuse"),
        pytest.param(
            case_duplicate, "RejectDuplicateCandidate", CandidateDuplicate, id="duplicate"
        ),
        pytest.param(case_rewrite, "RewriteKnownPage", Page, id="rewrite"),
        pytest.param(case_move, "MovePage", Page, id="move"),
        pytest.param(case_revive, "ReviveRemovedPage", Page, id="revive"),
        pytest.param(case_unchanged, "RecordUnchanged", Page, id="unchanged"),
        pytest.param(
            case_discard, "DiscardUnchangedWithoutPage", CandidateDiscarded, id="discard"
        ),
        pytest.param(case_remove_absent, "RemoveAbsentPage", PageRemoved, id="remove-absent"),
        pytest.param(case_accept_absent, "AcceptAbsentWithoutPage", None, id="accept-absent"),
        pytest.param(
            case_remove_redirected_out,
            "RemoveRedirectedOutPage",
            PageRemoved,
            id="remove-redirected-out",
        ),
        pytest.param(
            case_accept_redirected_out,
            "AcceptRedirectedOutWithoutPage",
            None,
            id="accept-redirected-out",
        ),
    ],
)
def test_EveryCandidateIsSettled_exactly_one_intake_rule_fires(
    tmp_path: Path,
    build: Callable[[Path], PageCandidate],
    rule: str,
    answer: type | None,
) -> None:
    """mirror.allium EveryCandidateIsSettled: the intake partition is total and exclusive.

    Each of the twelve cases, built afresh for every rule, is taken by exactly one rule.
    settle_candidate answers that rule's event: PageStored's page, CandidateDiscarded,
    CandidateDuplicate or PageRemoved; the two Accept...WithoutPage rules accept the
    candidate and answer none (Open points item 8). No candidate is left pending.
    """
    fired = [
        name
        for index, (name, rule_of) in enumerate(INTAKE_RULES)
        if fires(rule_of(build(tmp_path / f"rule-{index}")))
    ]
    assert fired == [rule]
    candidate = build(tmp_path / "settled")
    settled = settle_candidate(candidate, FixedClock(LATER))
    if answer is None:
        assert settled is None
    else:
        assert isinstance(settled, answer)
    assert candidate.status is not CandidateStatus.pending


def test_RetirePage_a_removed_page_is_never_reported_removed_twice(tmp_path: Path) -> None:
    """RetirePage guidance: the first removal is kept and is the only one reported.

    A second 404 on the removed page meets AcceptAbsentWithoutPage, since known_page
    skips removed pages: no PageRemoved, and the first removal's fields stay.
    """
    mirror, _, other = written_pair(tmp_path)
    first = settle_candidate(absent_candidate(mirror, OTHER), FixedClock(LATER))
    assert isinstance(first, PageRemoved)
    again = absent_candidate(mirror, OTHER, run_id=THIRD_RUN)
    assert remove_absent_page(again, FixedClock(LATEST)) is None
    assert settle_candidate(again, FixedClock(LATEST)) is None
    assert again.status is CandidateStatus.accepted
    assert (other.removed_at, other.removal_reason) == (LATER, RemovalReason.absent)


def test_RemovedAreaKeepsPath_the_archive_mirrors_pages_and_revival_is_in_place(
    tmp_path: Path,
) -> None:
    """mirror.allium RemovedAreaKeepsPath: removed at its path, archived, revived in place.

    The removed page keeps its record and path; its file is archived at
    _removed/<host>/<relative path>; revived, it is written at that same path and the
    removed area, emptied, is gone.
    """
    mirror, _, other = written_pair(tmp_path)
    path = other.path
    published_bytes = (tmp_path / path).read_bytes()
    assert settle_candidate(absent_candidate(mirror, OTHER), FixedClock(LATER)) is not None
    finalised_run(mirror)
    assert other in mirror.removed_pages
    assert other.path == path
    assert (tmp_path / "_removed" / "docs.example" / "other.md").read_bytes() == published_bytes
    assert not (tmp_path / path).exists()
    revived = candidate_for(mirror, requested=OTHER, run_id=THIRD_RUN)
    assert settle_candidate(revived, FixedClock(LATEST)) is other
    finalised_run(mirror, THIRD_RUN, FixedClock(LATEST))
    assert other.path == path
    assert (tmp_path / path).is_file()
    assert not (tmp_path / "_removed").exists()


def test_file_effects_are_applied_by_finalise_idempotently_and_empty_directories_go(
    tmp_path: Path,
) -> None:
    """The finalise pass applies the file effects; a second pass changes nothing more.

    Retiring DROP moves no file at intake. The next finalisation archives it at
    _removed/docs.example/drop/b.md and removes the emptied pages/docs.example/drop/
    (Open points item 2); a further finalisation leaves every file as it was.
    """
    mirror, (seed, drop) = written_mirror(tmp_path, SEED, DROP)
    published_bytes = (tmp_path / drop.path).read_bytes()
    assert retire_page(drop, RemovalReason.absent, FixedClock(LATER)) is not None
    assert (tmp_path / drop.path).read_bytes() == published_bytes
    assert not (tmp_path / "_removed").exists()
    finalised_run(mirror)
    assert not (tmp_path / ROOT / "drop").exists()
    assert (tmp_path / archived(drop.path)).read_bytes() == published_bytes
    files = sorted(path for path in tmp_path.rglob("*") if path.is_file())
    finalised_run(mirror, THIRD_RUN, FixedClock(LATEST))
    assert sorted(path for path in tmp_path.rglob("*") if path.is_file()) == files
    assert (tmp_path / archived(drop.path)).read_bytes() == published_bytes
    assert (tmp_path / seed.path).is_file()


def test_prune_deletes_a_retired_pages_file_instead_of_archiving_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RetirePage's prune branch, on unit inputs only (Open points item 3): no archive."""
    replace_mirror_config(monkeypatch, prune=True)
    mirror, _, other = written_pair(tmp_path)
    assert retire_page(other, RemovalReason.absent, FixedClock(LATER)) is not None
    finalised_run(mirror)
    assert not (tmp_path / other.path).exists()
    assert not (tmp_path / "_removed").exists()
    assert other.status is PageStatus.removed


def test_an_interrupted_retirement_leaves_the_disk_as_the_last_finalisation_left_it(
    tmp_path: Path,
) -> None:
    """No file moves at intake, and the next finalisation republishes a missing file.

    The page is retired in memory and the manifest is never saved: the disk keeps the
    last finalisation's files, and the saved manifest still holds the page written. A
    crash inside the pass that archived the file before the manifest was saved is then
    repaired by the next finalisation's PublishPage, which writes the missing file.
    """
    mirror, _, other = written_pair(tmp_path)
    save_mirror(mirror)
    published_bytes = (tmp_path / other.path).read_bytes()
    assert retire_page(other, RemovalReason.absent, FixedClock(LATER)) is not None
    assert (tmp_path / other.path).read_bytes() == published_bytes
    assert not (tmp_path / "_removed").exists()
    loaded = load_mirror(tmp_path)
    (kept,) = [page for page in loaded.pages if page.identity == OTHER]
    assert kept.status is PageStatus.written
    target = tmp_path / archived(other.path)
    target.parent.mkdir(parents=True)
    (tmp_path / other.path).rename(target)
    finalise(Operator(), loaded, SECOND_RUN, FixedClock(LATER))
    assert (tmp_path / other.path).read_bytes() == published_bytes


def test_a_page_revived_and_absent_in_one_run_keeps_its_archived_copy(tmp_path: Path) -> None:
    """RemovedAreaKeepsPath and the effect composition of tickets/T15-lifecycle.md Facts.

    OTHER, removed and archived by the second run, is revived in the third through
    B_URL's canonical, then answers 404 in that same run: the archive still holds the
    bytes OTHER had, and pages/ has no file for it.
    """
    mirror, _, other = written_pair(tmp_path)
    published_bytes = (tmp_path / other.path).read_bytes()
    assert retire_page(other, RemovalReason.absent, FixedClock(LATER)) is not None
    finalised_run(mirror)
    through = candidate_for(
        mirror, requested=B_URL, run_id=THIRD_RUN, converted=content(canonical_url=OTHER)
    )
    assert settle_candidate(through, FixedClock(LATEST)) is other
    gone = absent_candidate(mirror, OTHER, run_id=THIRD_RUN)
    assert isinstance(settle_candidate(gone, FixedClock(LATEST)), PageRemoved)
    finalised_run(mirror, THIRD_RUN, FixedClock(LATEST))
    assert (tmp_path / archived(other.path)).read_bytes() == published_bytes
    assert not (tmp_path / other.path).exists()


def settled_in_order(out_dir: Path, *urls: str) -> tuple[Mirror, list[PageCandidate]]:
    """Two URLs whose identical content names TOPIC canonical, settled in `urls` order."""
    mirror = new_mirror(out_dir)
    candidates = [
        candidate_for(
            mirror, requested=url, run_id=FIRST_RUN, converted=content(canonical_url=TOPIC)
        )
        for url in urls
    ]
    for candidate in candidates:
        assert settle_candidate(candidate, FixedClock()) is not None
    finalise(Operator(), mirror, FIRST_RUN, FixedClock())
    return mirror, candidates


def test_RejectDuplicateCandidate_the_fetch_order_never_changes_the_mirror(
    tmp_path: Path,
) -> None:
    """RejectDuplicateCandidate guidance, with identical content (Open points item 9).

    OTHER and B_URL both name TOPIC canonical. Settled in either order, the mirror holds
    one page TOPIC at one path with the same body, both URLs its aliases, and one
    candidate accepted, the other a duplicate. The page's source_url is the first
    store's, so the page file is not compared (the T15 batched question, item 9).
    """
    forward, forward_candidates = settled_in_order(tmp_path / "forward", OTHER, B_URL)
    backward, backward_candidates = settled_in_order(tmp_path / "backward", B_URL, OTHER)
    for mirror, candidates in (
        (forward, forward_candidates),
        (backward, backward_candidates),
    ):
        (page,) = mirror.pages
        assert (page.identity, page.path) == (TOPIC, f"{ROOT}topic.md")
        assert alias_rows(mirror) == [(B_URL, TOPIC), (OTHER, TOPIC)]
        assert [candidate.status for candidate in candidates] == [
            CandidateStatus.accepted,
            CandidateStatus.duplicate,
        ]
        assert page.converted_body == forward.pages[0].converted_body


def test_a_merge_leaves_the_merged_url_an_alias_of_the_survivor(tmp_path: Path) -> None:
    """RewriteKnownPage's merge branch: the seed's new canonical names OTHER, written.

    The seed is removed with reason merged, OTHER is refreshed from the candidate, and
    the seed's URL becomes an alias of OTHER, so a link to either resolves to OTHER.
    """
    mirror, seed, other = written_pair(tmp_path)
    candidate = candidate_for(mirror, converted=content(canonical_url=OTHER, body=NEW_BODY))
    assert settle_candidate(candidate, FixedClock(LATER)) is other
    assert (seed.status, seed.removal_reason) == (PageStatus.removed, RemovalReason.merged)
    assert other.converted_body == NEW_BODY
    assert alias_rows(mirror) == [(SEED, OTHER)]
    assert mirror.known_page(SEED) is other
    finalised_run(mirror)
    assert not (tmp_path / seed.path).exists()
    assert (tmp_path / archived(seed.path)).is_file()


def test_a_move_drops_a_stale_alias_of_the_new_identity(tmp_path: Path) -> None:
    """MovePage: an alias the new identity held is dropped, since an identity is no alias."""
    mirror, seed, other = written_pair(tmp_path)
    assert record_alias(mirror, NEW, seed) is not None
    assert move_page(moved_candidate(mirror), FixedClock(LATER)) is other
    assert mirror.alias(NEW) is None
    assert alias_rows(mirror) == [(OTHER, NEW)]


def test_a_move_onto_a_removed_identity_replaces_its_record_and_archive(tmp_path: Path) -> None:
    """MovePage: a removed record holding the new identity leaves; its archived copy goes.

    NEW was removed and archived by the second run; in the third OTHER moves to NEW: the
    live page takes NEW's path, the removed record leaves the mirror, the archived copy
    is deleted and OTHER's old file is gone.
    """
    mirror, (seed, other, new) = written_mirror(tmp_path, SEED, OTHER, NEW)
    old_path = other.path
    assert retire_page(new, RemovalReason.absent, FixedClock(LATER)) is not None
    finalised_run(mirror)
    assert (tmp_path / archived(new.path)).is_file()
    assert move_page(moved_candidate(mirror, THIRD_RUN), FixedClock(LATEST)) is other
    assert mirror.pages == [seed, other]
    assert (other.identity, other.path) == (NEW, f"{ROOT}new.md")
    finalised_run(mirror, THIRD_RUN, FixedClock(LATEST))
    assert (tmp_path / other.path).is_file()
    assert not (tmp_path / old_path).exists()
    assert not (tmp_path / "_removed").exists()


# T15 follow-up (spec bad753c): the maintainer's answers. A directory segment folds onto
# the spelling a held path already uses (MovePage's guidance, assign_path); an alias
# rechecked by the crawl that now serves its own page moves the page it aliased; a page
# revived at a new path and retired in the same run keeps its archived copy (RetirePage).
SUB_A = f"{SITE}/guide/sub/a.html"
SUB_B_UPPER = f"{SITE}/guide/Sub/b.html"


def test_assign_path_folds_a_directory_onto_the_spelling_a_held_path_uses(
    tmp_path: Path,
) -> None:
    """MovePage guidance (bad753c): one spelling per directory, compared ignoring case.

    With pages/<host>/sub/a.md held, /Sub/b gives pages/<host>/sub/b.md, and StoreNewPage
    writes it there; a deeper directory folds too, each segment onto the spelling held
    under the same parent (sub/Deep/ for /SUB/deep/). The last segment keeps its own
    spelling and meets the collision test: /sub/A collides with sub/a.md ignoring case.
    """
    mirror = new_mirror(tmp_path)
    assert stored(mirror, requested=SUB_A).path == f"{ROOT}sub/a.md"
    assert assign_path(mirror, SUB_B_UPPER) == f"{ROOT}sub/b.md"
    assert stored(mirror, requested=SUB_B_UPPER).path == f"{ROOT}sub/b.md"
    deep = stored(mirror, requested=f"{SITE}/guide/sub/Deep/c.html")
    assert deep.path == f"{ROOT}sub/Deep/c.md"
    assert assign_path(mirror, f"{SITE}/guide/SUB/deep/d.html") == f"{ROOT}sub/Deep/d.md"
    leaf = f"{SITE}/guide/sub/A.html"
    suffix = digest(leaf)[: model.CONFIG.collision_hash_chars]
    assert assign_path(mirror, leaf) == f"{ROOT}sub/A-{suffix}.md"


def test_assign_path_takes_the_spelling_first_by_code_point_and_moves_no_page(
    tmp_path: Path,
) -> None:
    """MovePage guidance (bad753c): of several held spellings, the first by code point.

    Held paths already spell one directory Sub/ and sub/; "Sub" sorts before "sub", so a
    new page under /SUB/ goes to Sub/, and neither held page is moved.
    """
    mirror = new_mirror(tmp_path)
    lower = stored(mirror, requested=f"{SITE}/guide/x.html")
    lower.path = f"{ROOT}sub/x.md"
    upper = stored(mirror, requested=f"{SITE}/guide/y.html")
    upper.path = f"{ROOT}Sub/y.md"
    page = stored(mirror, requested=f"{SITE}/guide/SUB/z.html")
    assert page.path == f"{ROOT}Sub/z.md"
    assert (lower.path, upper.path) == (f"{ROOT}sub/x.md", f"{ROOT}Sub/y.md")


def test_a_move_to_a_url_differing_in_directory_case_keeps_the_directory(
    tmp_path: Path,
) -> None:
    """MovePage guidance (bad753c): a page at sub/x.md whose URL becomes /Sub/x keeps it.

    The page's own path is a held path, so its directory keeps its spelling and the path
    does not change: no file moves and moved_from stays null.
    """
    old_url = f"{SITE}/guide/sub/x.html"
    new_url = f"{SITE}/guide/Sub/x.html"
    mirror, (page,) = written_mirror(tmp_path, old_url)
    path = page.path
    assert path == f"{ROOT}sub/x.md"
    candidate = candidate_for(
        mirror,
        requested=old_url,
        source=new_url,
        hops=(old_url,),
        converted=content(body=OTHER_BODY),
    )
    assert move_page(candidate, FixedClock(LATER)) is page
    assert (page.identity, page.path, page.moved_from) == (new_url, path, None)
    finalised_run(mirror)
    assert (tmp_path / path).is_file()
    assert [p.name for p in (tmp_path / ROOT).iterdir() if p.is_dir()] == ["sub"]


def test_a_rechecked_alias_serving_its_own_page_moves_the_page_it_aliased(
    tmp_path: Path,
) -> None:
    """MovePage guidance (bad753c): an alias URL that now answers as itself.

    OTHER moved to NEW in the second run, leaving OTHER its alias. In the third run the
    crawl rechecks OTHER, which answers its own page: the page it aliased moves back to
    OTHER's identity and path, and OTHER is no longer an alias.
    """
    mirror, _, other = written_pair(tmp_path)
    old_path = other.path
    assert move_page(moved_candidate(mirror), FixedClock(LATER)) is other
    finalised_run(mirror)
    assert alias_rows(mirror) == [(OTHER, NEW)]
    rechecked = candidate_for(
        mirror, requested=OTHER, run_id=THIRD_RUN, converted=content(body=OTHER_BODY)
    )
    assert settle_candidate(rechecked, FixedClock(LATEST)) is other
    assert (other.identity, other.path) == (OTHER, old_path)
    assert mirror.alias(OTHER) is None
    finalised_run(mirror, THIRD_RUN, FixedClock(LATEST))
    assert (tmp_path / old_path).is_file()
    assert not (tmp_path / f"{ROOT}new.md").exists()


def revived_at_a_new_path(tmp_path: Path) -> tuple[Mirror, Page, str, bytes]:
    """OTHER retired by the second run, then revived in the third at a new path.

    The scope's path prefix is dropped between the runs, so assign_path no longer gives
    OTHER its old path; the old path, its archived copy's, and its published bytes.
    """
    mirror, _, other = written_pair(tmp_path)
    old_path = other.path
    published_bytes = (tmp_path / old_path).read_bytes()
    assert retire_page(other, RemovalReason.absent, FixedClock(LATER)) is not None
    finalised_run(mirror)
    assert (tmp_path / archived(old_path)).read_bytes() == published_bytes
    mirror.scope = dataclasses.replace(mirror.scope, path_prefixes=())
    revived = candidate_for(
        mirror, requested=OTHER, run_id=THIRD_RUN, converted=content(body=OTHER_BODY)
    )
    assert settle_candidate(revived, FixedClock(LATEST)) is other
    assert other.path != old_path
    return mirror, other, old_path, published_bytes


def removed_files(out_dir: Path) -> list[Path]:
    """Every file under _removed/."""
    return sorted(path for path in (out_dir / "_removed").rglob("*") if path.is_file())


def test_a_page_revived_at_a_new_path_and_retired_in_one_run_keeps_its_archived_copy(
    tmp_path: Path,
) -> None:
    """RetirePage (9a253a4): the record returns to the path its archived copy is at.

    OTHER, removed and archived by the second run, is revived in the third at a new path
    and answers 404 in that same run. The record goes back to its old path (revived_from),
    so the PageFileArchived of that path cancels the pending ArchivedCopyDeleted: nothing
    moves on disk, _removed/ holds the old copy alone with its last published bytes,
    pages/ has no file at the new path, and record and copy agree (RemovedAreaKeepsPath).
    Re-propagated by the T16 follow-up (origin T15 follow-up, which asserted the files
    only while the record kept the new path).
    """
    mirror, other, old_path, published_bytes = revived_at_a_new_path(tmp_path)
    new_path = other.path
    gone = absent_candidate(mirror, OTHER, run_id=THIRD_RUN)
    assert isinstance(settle_candidate(gone, FixedClock(LATEST)), PageRemoved)
    assert (other.path, other.revived_from) == (old_path, None)
    finalised_run(mirror, THIRD_RUN, FixedClock(LATEST))
    assert removed_files(tmp_path) == [tmp_path / archived(old_path)]
    assert (tmp_path / archived(other.path)).read_bytes() == published_bytes
    assert not (tmp_path / new_path).exists()
    assert other.status is PageStatus.removed


def test_a_revived_page_whose_old_path_was_taken_moves_its_archived_copy_when_retired(
    tmp_path: Path,
) -> None:
    """RetirePage's ArchivedCopyMoved (9a253a4): another page now holds the old path.

    OTHER is revived in the third run at a new path; a new page, {SITE}/other.html, is
    then stored at OTHER's old path; OTHER answers 404 in the same run. The record keeps
    its new path and its archived copy moves from _removed/<old path> to _removed/<new
    path>, cancelling the pending ArchivedCopyDeleted: the copy keeps its last published
    bytes, nothing is left at the old archived path, and the newcomer is published at
    pages/<old path>. Record and copy agree, and no two pages share a path.
    """
    mirror, other, old_path, published_bytes = revived_at_a_new_path(tmp_path)
    new_path = other.path
    newcomer = stored(
        mirror, requested=f"{SITE}/other.html", run_id=THIRD_RUN, converted=content()
    )
    assert newcomer.path == old_path
    gone = absent_candidate(mirror, OTHER, run_id=THIRD_RUN)
    assert isinstance(settle_candidate(gone, FixedClock(LATEST)), PageRemoved)
    assert (other.path, other.revived_from) == (new_path, None)
    finalised_run(mirror, THIRD_RUN, FixedClock(LATEST))
    assert removed_files(tmp_path) == [tmp_path / archived(new_path)]
    assert (tmp_path / archived(new_path)).read_bytes() == published_bytes
    assert (tmp_path / old_path).is_file()
    assert (tmp_path / old_path).read_bytes() != published_bytes
    assert not (tmp_path / new_path).exists()
    assert len({page.path.casefold() for page in mirror.pages}) == len(mirror.pages)


def test_under_prune_a_revived_page_whose_old_path_was_taken_moves_nothing_when_retired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RetirePage's guidance (9a253a4): under prune the pending ArchivedCopyDeleted wins.

    As the collision case, with prune set: the record keeps its new path, nothing is
    moved or archived, the old archived copy is deleted, and the newcomer is published.
    """
    mirror, other, old_path, _ = revived_at_a_new_path(tmp_path)
    new_path = other.path
    replace_mirror_config(monkeypatch, prune=True)
    mirror.prune = True
    stored(mirror, requested=f"{SITE}/other.html", run_id=THIRD_RUN, converted=content())
    gone = absent_candidate(mirror, OTHER, run_id=THIRD_RUN)
    assert isinstance(settle_candidate(gone, FixedClock(LATEST)), PageRemoved)
    assert (other.path, other.revived_from) == (new_path, None)
    finalised_run(mirror, THIRD_RUN, FixedClock(LATEST))
    assert not (tmp_path / "_removed").exists()
    assert (tmp_path / old_path).is_file()
    assert not (tmp_path / new_path).exists()


def test_entity_optional_Page_revived_from(tmp_path: Path) -> None:
    """Verify optional field Page.revived_from accepts null and non-null values.

    Null on a stored page (StoreNewPage); a revived page's removed path, where its
    archived copy is, until finalisation: the old path itself when the page is revived
    there, the old path when it is revived at a new one (ReviveRemovedPage); null again
    once PublishPage has published the page.
    """
    mirror, _, other = written_pair(tmp_path)
    assert other.revived_from is None
    path = other.path
    assert retire_page(other, RemovalReason.absent, FixedClock(LATER)) is not None
    finalised_run(mirror)
    again = candidate_for(
        mirror, requested=OTHER, run_id=THIRD_RUN, converted=content(body=OTHER_BODY)
    )
    assert settle_candidate(again, FixedClock(LATEST)) is other
    assert (reread(other).path, reread(other).revived_from) == (path, path)
    finalised_run(mirror, THIRD_RUN, FixedClock(LATEST))
    assert reread(other).revived_from is None

    elsewhere, moved_other, old_path, _ = revived_at_a_new_path(tmp_path / "elsewhere")
    assert moved_other.revived_from == old_path
    assert moved_other.path != old_path
    finalised_run(elsewhere, THIRD_RUN, FixedClock(LATEST))
    assert reread(moved_other).revived_from is None
    assert (tmp_path / "elsewhere" / moved_other.path).is_file()
