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
from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path

from fakes import START, FixedClock
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
    finalise,
    finalise_page_body,
    frontmatter_of,
    keywords_of,
    page_file_current,
    page_file_text,
    publish_page,
    request_pass,
)
from rovo._mirror.intake import (
    admit_candidate,
    drop_alias_of_own_identity,
    record_alias,
    refresh_page,
    store_new_page,
    take_candidate,
)
from rovo._mirror.model import (
    Alias,
    CandidateDelivered,
    CandidateOutcome,
    CandidateStatus,
    CrawlScope,
    Frontmatter,
    Mirror,
    MirrorPass,
    Operator,
    Page,
    PageCandidate,
    PageStatus,
    PassKind,
    PassStatus,
    StoreOutcome,
    Tier,
)
from rovo._mirror.state import load_mirror, save_mirror, write_json
from rovo._mirror.urls import assign_path
from spec_values import spec_int

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


def content(
    *, body: str = BODY, canonical_url: str | None = None, measured: QualityResult | None = None
) -> ConvertedContent:
    """Converted content for the fixture page, as the crawl hands it over."""
    return ConvertedContent(
        body=body,
        title="Getting started",
        description="How to start with the example product.",
        canonical_url=canonical_url,
        declared_locale="en",
        breadcrumbs=(),
        navigation_targets=(),
        method=ExtractionMethod.profile,
        anchors=frozenset(),
        headings=HEADINGS,
        link_targets=(),
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
) -> CandidateDelivered:
    """A CandidateDelivered for one settled http fetch of `requested`."""
    return CandidateDelivered(
        run_id=run_id,
        mirror=mirror,
        requested_identity=requested,
        source_url=source or requested,
        redirect_hops=(),
        depth=0,
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
    """Verify rule RefreshPage succeeds when all preconditions are met."""
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
    and keywords are recomputed from the body.
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
    # IndexesWritten is raised without writing an index file in this slice.
    assert not (tmp_path / "index.md").exists()


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


def test_entity_fields_Frontmatter(tmp_path: Path) -> None:
    """Verify all declared fields on Frontmatter are present with correct types."""
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    published(mirror, page)
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
    assert frontmatter.etag == ETAG
    assert frontmatter.last_modified == LAST_MODIFIED
    assert frontmatter.sitemap_lastmod is None
    assert frontmatter.version is None
    assert frontmatter.locale == "en"
    assert_fields(frontmatter, ("breadcrumbs",))


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
    """Verify all declared fields on Page are present with correct types."""
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
