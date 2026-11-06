"""Divergences the T09 weed and review found, each pinned to the statement it broke.

The obligation tests did not reach these inputs: a page whose finalisation stops, a
heading id with a Markdown character, a source attribute that looks like the heading-id
mark, code with leading blank lines, trailing whitespace or `<br>` line breaks, and an
IPv6 literal host (weed); a percent-encoded dot segment, a reserved file name in another
case, a malformed URL or configuration value, a password input quoted another way, and a
non-heading source id (review 2, ai_tmp/review/T09-2/); an IPv6 host init writes and a
huge integer max_age (review 2, round 4). T10 (implement): an autolink to a written page
and a destination that reaches into inline code; a destination with parentheses (weed 2);
link text holding brackets or an image (weed 3). T12 (review T12-1): pacing time is the
wall-clock anchor plus the monotonic delta, so a step of the wall clock changes no wait.
T12 (implement 2 and 3, weed 2 and 3): a page's raw 3xx stops at DisposeFetch while a 304
with no stored page fails; a Retry-After too long for a duration saturates, zero padding
is read, and a non-ASCII digit is no Retry-After. T12 (reviews T12-2-r2 and T12-3-r2): a
Crawl-delay is read exactly, so 1e309, 1e400, the cap plus one sub-ULP step and an
exponent past Decimal's limit are past the cap, while a value outside float's grammar is
no Crawl-delay and one too small for Decimal is no delay. T13 (planning): the report's
discovered counts the frontier's rows after discovery, and a sitemap entry or llms.txt
target with no identity is skipped (crawl.allium ExpandSitemapEntries and ReadLlmsTxt
guidance, at ecfa257). T15 (weed 1, ai_tmp/T15/weed-1.md): a move whose natural path is
unchanged keeps its path, and a redirected llms.txt's relative targets resolve against
llms_txt_url. T15 (weed 2 and 3, ai_tmp/T15/weed-3.md): a case-only move leaves the page
file in place under its new spelling. T17 (re-propagated from T09 review C2): a
non-heading source id becomes an anchor island. T17 (weed 1, ai_tmp/T17/weed-1.md): the
source id of an element normalisation replaces (a tab group, a tab panel, a callout, an
interactive embed, a layout table, a footnote section) stays an anchor; whole-body
extraction strips the profile's chrome; an unreadable page file is invalid_page_file.
T17 (weed 2, ai_tmp/T17/weed-2.md): the source id of a tab group's tab list and labels and
of an unwrapped form wrapper (form, fieldset, label, button) stays an anchor. T17
follow-up (spec 022eca4): the whole-body case is reached when the fallback extractor finds
nothing.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from fakes import (
    FakeFetcher,
    FixedClock,
    fixture_site,
    html_response,
    redirect_response,
    text_response,
    xml_response,
)
from rovo import _commands
from rovo._config import initial_scope, resolve_config, starter_config
from rovo._convert import profiles
from rovo._convert.fidelity import convert, extract, link_destinations, map_destinations, normalize
from rovo._convert.model import ExtractionMethod, Profile
from rovo._crawl import pace
from rovo._crawl.fetch import HttpxFetcher
from rovo._crawl.model import CONFIG as CRAWL_CONFIG
from rovo._crawl.model import BlockKind, EntryFailed, FrontierStatus, RunStatus
from rovo._crawl.run import (
    classify_block,
    convert_fetched,
    dispose_fetch,
    entry_fails,
    fail_discarded_entry,
    read_llms_txt,
    run_crawl,
)
from rovo._mirror import model
from rovo._mirror.finalise import finalise
from rovo._mirror.intake import admit_candidate, move_page, take_candidate
from rovo._mirror.model import (
    CandidateDiscarded,
    CandidateStatus,
    Operator,
    StoreOutcome,
    Tier,
    VerificationReason,
)
from rovo._mirror.state import load_mirror, manifest_path
from rovo._mirror.urls import assign_path, digest, hostname_of, normalise_url, origin_of
from rovo._report import ChangeKind, CrawlReportStatus, ExitCode, tally_failed_url
from rovo.cli import app
from test_commands import set_key
from test_convert import DEVSITE_CHROME, LEARN_URL, MSLEARN_PAGE, TABS_PAGE, converted_by
from test_crawl import LLMS_TXT, declaring, host_open, settled, site, urlset
from test_crawl import new_mirror as crawl_mirror
from test_crawl import request as crawl_request
from test_mirror import (
    FIRST_RUN,
    OTHER,
    OTHER_BODY,
    ROOT,
    candidate_for,
    content,
    finalised_run,
    new_mirror,
    stored,
    written_pair,
)
from test_report import crawled, opened
from test_unplaceable_candidate import crowded, victim_candidate
from test_verify import B, findings, reasons_at, synced_mirror

SITE = "http://docs.example"
SEED = f"{SITE}/guide/start.html"
LINKED = """<!doctype html><html><head><title>Start</title></head><body><main>
<h1>Getting started</h1><p>Read the <a href="next.html">next page</a> once you are done.</p>
</main></body></html>"""
UNLINKED = """<!doctype html><html><head><title>Start</title></head><body><main>
<h1>Getting started</h1><p>Read the next page once you are done with this one.</p>
</main></body></html>"""


def never_installed(tier: Tier) -> bool:
    """No engine beyond http is installed."""
    del tier
    return False


def sync(out_dir: Path, markup: str) -> ExitCode:
    """One rovo sync of the mirror, the seed answering `markup`."""
    fetcher = FakeFetcher({SEED: html_response(SEED, markup)})
    return _commands.sync(
        out_dir, fetcher=fetcher, clock=FixedClock(), tier_installed=never_installed
    )


def body_of(fragment: str) -> str:
    """The generic profile's Markdown body for an HTML fragment."""
    page = f"<html><head><title>T</title></head><body><main>{fragment}</main></body></html>"
    content = extract(page, SEED, profiles.GENERIC)
    return convert(normalize(content, profiles.GENERIC).fragment)


def test_a_stopped_finalisation_persists_no_done_row(tmp_path: Path) -> None:
    """crawl.allium SettleStoredEntry: a done row always has a page in the mirror.

    A sync whose finalisation stops saves neither the frontier nor the run, so the next
    sync fetches and stores the page again. Re-propagated by T15 (origin T09): the stop
    was next.html's 404, which T15 settles silently (AcceptAbsentWithoutPage); next.html
    then answered a non-HTML document. Re-propagated by T16 (origin T09): T16 settles a
    non-HTML answer skipped_not_html, so next.html served a login wall. Re-propagated by
    T18 (origin T09): T18 settles a login wall as a soft verdict and converts it, so
    next.html now serves an SPA shell under render_mode = auto with the browser engine
    installed, whose escalation (crawl.allium Escalate, a later slice's) still stops the
    run; the second sync renders never again.
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    set_key(out_dir, "render_mode", '"auto"')
    following = f"{SITE}/guide/next.html"
    spa_shell = '<html><body><div id="root"></div><script src="a.js"></script></body></html>'
    fetcher = FakeFetcher(
        {
            SEED: html_response(SEED, LINKED),
            following: html_response(following, spa_shell),
        }
    )
    stopped = _commands.sync(
        out_dir,
        fetcher=fetcher,
        clock=FixedClock(),
        tier_installed=lambda tier: tier is not Tier.http,
    )
    assert stopped is ExitCode.partial
    assert following in fetcher.requests
    state = out_dir / ".rovo"
    assert not (state / "frontier.json").exists()
    assert not (state / "runs.json").exists()
    set_key(out_dir, "render_mode", '"never"')
    assert sync(out_dir, UNLINKED) is ExitCode.ok
    assert len(load_mirror(out_dir).pages) == 1
    frontier = json.loads((state / "frontier.json").read_text(encoding="utf-8"))
    assert [row["status"] for row in frontier["entries"]] == ["done"]


def test_heading_ids_keep_their_characters() -> None:
    """convert.allium BodyShape: the body's heading id is the anchor normalize records."""
    fragment = '<h1>Title</h1><h2 id="get_started">Get *started*</h2><h2 id="a*b">B</h2>'
    page = f"<html><head><title>T</title></head><body><main>{fragment}</main></body></html>"
    normalized = normalize(extract(page, SEED, profiles.GENERIC), profiles.GENERIC)
    body = convert(normalized.fragment)
    assert r"## Get \*started\* {#get_started}" in body
    assert "## B {#a*b}" in body
    assert normalized.anchors == {"get_started", "a*b"}


def test_only_a_source_id_becomes_a_heading_id() -> None:
    """convert.allium BodyShape: every heading id in the body is a recorded anchor."""
    fragment = '<h1>T</h1><h2 data-rovo-anchor="zz">S</h2><h2 id="k" data-rovo-anchor="zz">K</h2>'
    page = f"<html><head><title>T</title></head><body><main>{fragment}</main></body></html>"
    normalized = normalize(extract(page, SEED, profiles.GENERIC), profiles.GENERIC)
    body = convert(normalized.fragment)
    assert "## S\n" in body
    assert "## K {#k}\n" in body
    assert "zz" not in body
    assert normalized.anchors == {"k"}


def test_a_line_break_in_code_stays_a_line_break() -> None:
    """convert.allium BodyShape: a `<br>` in a `<pre>` is a line of the fenced code."""
    assert "```\na\nb\n\nc\n```\n" in body_of("<h1>T</h1><pre>a<br>b<br/>\nc</pre>")
    assert "```\nx\ny\n```\n" in body_of("<h1>T</h1><pre><code>x<br>y</code></pre>")
    assert "```\n\nx\n```\n" in body_of("<h1>T</h1><pre><!--c-->\nx</pre>")


def test_fenced_code_is_byte_identical() -> None:
    """convert.allium BodyShape: fenced code keeps its blank lines and trailing whitespace."""
    assert "```\n\n\nx = 1\n```\n" in body_of("<h1>T</h1><pre>\n\n\nx = 1\n</pre>")
    assert "```\nx\t\n  y   \n```\n" in body_of("<h1>T</h1><pre>x\t\n  y   </pre>")
    assert "````\na_b *c* ```\n````\n" in body_of("<h1>T</h1><pre><code>a_b *c* ```</code></pre>")


def test_an_ipv6_host_keeps_its_brackets() -> None:
    """mirror.allium CrawlScope.identity_of: the identity of a URL is a URL."""
    assert normalise_url("http://[::1]:8080/a/", ()) == "http://[::1]:8080/a/"
    assert normalise_url("HTTP://[FE80::1]:80/a/", ()) == "http://[fe80::1]/a/"
    assert origin_of("http://[::1]:8080/a/") == "http://[::1]:8080"


# --- Review 2 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("/guide/%2e%2e/escape.html", "-2e-2e/escape.md", id="lower-dots"),
        pytest.param("/guide/%2E%2E/%2e%2e/x.html", "-2E-2E/-2e-2e/x.md", id="upper-dots"),
        pytest.param("/guide/a%2fb.html", "a-2fb.md", id="encoded-slash"),
    ],
)
def test_a_percent_escape_is_never_decoded(tmp_path: Path, path: str, expected: str) -> None:
    """mirror.allium MovePage guidance: each segment keeps [A-Za-z0-9._-], the rest is "-".

    The path is not decoded first, so an escaped dot segment or slash neither leaves the
    mirror nor splits a segment (review B1).
    """
    assigned = assign_path(new_mirror(tmp_path), f"{SITE}{path}")
    assert assigned == f"{ROOT}{expected}"
    assert ".." not in assigned.split("/")


def test_publishing_refuses_a_path_outside_the_mirror(tmp_path: Path) -> None:
    """A page path that leaves the mirror directory is never written (review B1).

    assign_path cannot give one; this is the finalise pass's own check.
    """
    out_dir = tmp_path / "out"
    page = stored(new_mirror(out_dir))
    page.path = "../escape.md"
    with pytest.raises(ValueError, match="outside the mirror"):
        finalise(Operator(), page.mirror, FIRST_RUN, FixedClock())
    assert not (tmp_path / "escape.md").exists()


@pytest.mark.parametrize(
    ("path", "stem"),
    [
        pytest.param("/guide/index.html", "index", id="root-index"),
        pytest.param("/guide/INDEX.html", "INDEX", id="root-index-upper-case"),
        pytest.param("/guide/_index.html", "_index", id="directory-index"),
        pytest.param("/guide/sub/_Index.html", "sub/_Index", id="nested-directory-index"),
    ],
)
def test_index_names_are_ordinary_page_names(tmp_path: Path, path: str, stem: str) -> None:
    """mirror.allium MovePage guidance at fed9ed8 (supersedes review B3).

    "No name is reserved inside pages/<host>/: _index.md and index.md there are ordinary
    page names"; the root index.md is outside pages/ and never collides with one.
    """
    assert assign_path(new_mirror(tmp_path), f"{SITE}{path}") == f"{ROOT}{stem}.md"


@pytest.mark.parametrize("url", ["http://[", "http://[bad", "https://[::1"])
def test_init_refuses_a_malformed_url(tmp_path: Path, url: str) -> None:
    """rovo.allium RefuseInit: a URL that does not parse is not an http URL (review C3, B4)."""
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(app, ["init", url, str(out_dir)])
    assert result.exit_code == ExitCode.usage.number
    assert "not an http or https URL" in result.stderr
    assert not manifest_path(out_dir).exists()


@pytest.mark.parametrize(
    ("toml", "key"),
    [
        pytest.param("[crawl]\nmax_age = inf\n", "crawl.max_age", id="max-age-inf"),
        pytest.param("[crawl]\nmax_age = nan\n", "crawl.max_age", id="max-age-nan"),
        pytest.param("[crawl]\nmax_age = 1e30\n", "crawl.max_age", id="max-age-huge"),
        pytest.param('[scope]\nallowed_hosts = ["[bad"]\n', "scope.allowed_hosts", id="host"),
        pytest.param('[scope]\nallowed_hosts = [""]\n', "scope.allowed_hosts", id="empty-host"),
        pytest.param(
            '[scope]\nallowed_hosts = ["::1]"]\n', "scope.allowed_hosts", id="half-bracketed-ipv6"
        ),
        pytest.param(
            f"[crawl]\nmax_age = {'9' * 400}\n", "crawl.max_age", id="max-age-huge-integer"
        ),
        pytest.param('[site]\nstart_urls = ["http://["]\n', "site.start_urls", id="start-url"),
        pytest.param('[site]\nroot_url = "http://["\n', "site.root_url", id="root-url"),
        pytest.param('[site]\nroot_url = "ftp://docs.example/"\n', "site.root_url", id="ftp"),
    ],
)
def test_a_bad_configuration_value_is_a_problem(tmp_path: Path, toml: str, key: str) -> None:
    """rovo.allium Configuration: a bad value makes it invalid, its key path in problems.

    These values raised OverflowError or ValueError instead (review B4; the huge integer,
    review T09-2-r4 C2, overflowed math.isfinite).
    """
    (tmp_path / "rovo.toml").write_text(toml, encoding="utf-8")
    settings = resolve_config(tmp_path)
    assert not settings.valid
    assert any(problem.startswith(f"{key}:") for problem in settings.problems)


def test_sync_refuses_a_malformed_start_url(tmp_path: Path) -> None:
    """A malformed configured seed is a usage refusal, not a traceback (review B4)."""
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    config = out_dir / "rovo.toml"
    line = f"start_urls = {json.dumps([SEED])}"
    text = config.read_text(encoding="utf-8")
    assert line in text
    config.write_text(text.replace(line, 'start_urls = ["http://["]'), encoding="utf-8")
    assert sync(out_dir, UNLINKED) is ExitCode.usage


@pytest.mark.parametrize(
    "field",
    [
        "<input type='password'>",
        "<input type=password>",
        '<input TYPE = "Password">',
        '<input name="p" type=" password ">',
    ],
)
def test_a_password_input_is_a_login_wall_however_quoted(field: str) -> None:
    """crawl.allium classify_block guidance: a password form is a login wall (review B5, C1).

    Re-propagated by T18 (origin T12), which expected NotInThisSlice: the verdict is
    soft, signed "login wall", however the attribute is quoted or cased.
    """
    markup = UNLINKED.replace("</main>", f"<form>{field}</form></main>")
    verdict = classify_block(html_response(SEED, markup), None)
    assert (verdict.kind, verdict.signature) == (BlockKind.soft, "login wall")


def test_a_text_input_is_no_login_wall() -> None:
    """Positive control: an input of another type leaves the verdict at none."""
    markup = UNLINKED.replace("</main>", "<form><input type='text' name='q'></form></main>")
    assert classify_block(html_response(SEED, markup), None).signature == ""


def test_a_non_heading_source_id_becomes_an_anchor_island() -> None:
    """convert.allium BodyShape keeps every source id as an anchor (review C2).

    Re-propagated by T17 from T09, which stopped here: UncarryableBecomesIsland makes a
    non-heading id an anchor island, so the id is an anchor and the body holds it. The
    extracted root's own id is not part of the content.
    """
    page = UNLINKED.replace("<p>", '<p id="intro">')
    islanded = converted_by(page, profiles.GENERIC)
    assert "intro" in islanded.anchors
    assert '<a id="intro"></a>' in islanded.body
    rooted = UNLINKED.replace("<main>", '<main id="content">')
    normalized = normalize(extract(rooted, SEED, profiles.GENERIC), profiles.GENERIC)
    assert normalized.anchors == frozenset()


# --- The rules the refused candidate crosses outside the owned set: their guards -----


def test_take_candidate_gives_no_page_for_a_refused_candidate(tmp_path: Path) -> None:
    """RefuseUnplaceableCandidate settles the candidate, so take_candidate gives no page."""
    mirror = new_mirror(tmp_path)
    crowded(mirror)
    candidate = victim_candidate(mirror)
    assert take_candidate(candidate, FixedClock()) is None
    assert candidate.status is CandidateStatus.accepted


def test_fail_discarded_entry_and_entry_fails_guards(tmp_path: Path) -> None:
    """crawl.allium FailDiscardedEntry and EntryFails refuse when their guards fail.

    FailDiscardedEntry needs a row in progress and a running run of the mirror;
    EntryFails needs the row in progress, then fails it.
    """
    run, frontier, walk = settled(tmp_path, site())
    assert dispose_fetch(walk)
    handed = convert_fetched(run, walk.entry, walk)
    assert handed is not None
    discarded = CandidateDiscarded(candidate=admit_candidate(handed), reason="no free path")
    assert fail_discarded_entry(None, frontier, discarded) is None
    run.status = RunStatus.finished
    assert fail_discarded_entry(run, frontier, discarded) is None
    run.status = RunStatus.running
    failed = fail_discarded_entry(run, frontier, discarded)
    assert failed is not None
    url_failed = entry_fails(failed)
    assert url_failed is not None
    assert (url_failed.url, url_failed.error, url_failed.attempts) == (SEED, "no free path", 1)
    assert walk.entry.status is FrontierStatus.failed
    assert entry_fails(failed) is None  # the row is no longer in progress
    assert fail_discarded_entry(run, frontier, discarded) is None


def test_tally_failed_url_needs_an_open_report(tmp_path: Path) -> None:
    """rovo.allium TallyFailedUrl: a failed_urls row and a failed change, on an open report."""
    run, frontier, walk = settled(tmp_path / "tally", site())
    assert dispose_fetch(walk)
    handed = convert_fetched(run, walk.entry, walk)
    assert handed is not None
    discarded = CandidateDiscarded(candidate=admit_candidate(handed), reason="no free path")
    failed = fail_discarded_entry(run, frontier, discarded)
    assert failed is not None
    url_failed = entry_fails(failed)
    assert url_failed is not None
    report = opened(run)
    assert tally_failed_url(report, url_failed)
    assert [(row.url, row.error, row.attempts) for row in report.failed_urls] == [
        (SEED, "no free path", 1)
    ]
    assert [(row.kind, row.url, row.path) for row in report.changes] == [
        (ChangeKind.failed, SEED, None)
    ]
    report.status = CrawlReportStatus.written
    assert not tally_failed_url(report, url_failed)
    other = opened(crawled(tmp_path / "other").run)
    assert not tally_failed_url(other, url_failed)


# --- Weed, resume at fed9ed8 -------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("/guide/con.", "con--.md", id="device-then-trailing-dot"),
        pytest.param("/guide/nul.md/x.html", "nul--md/x.md", id="device-then-md-directory"),
        pytest.param("/guide/con../x.html", "con---/x.md", id="device-then-dot-run"),
        pytest.param("/guide/con.txt", "con-.txt.md", id="device-before-first-dot"),
    ],
)
def test_segment_rewrites_each_read_the_sanitised_segment(
    tmp_path: Path, path: str, expected: str
) -> None:
    """mirror.allium MovePage guidance 677 to 694: each rewrite reads one segment alone.

    "They apply together, so neither the crawl order nor their own order matters": the
    device rule reads the part before the first "." of the sanitised segment, not of the
    segment another rewrite has already changed (weed, resume tick 1).
    """
    assert assign_path(new_mirror(tmp_path), f"{SITE}{path}") == f"{ROOT}{expected}"


def test_a_cut_may_leave_exactly_the_host_root(tmp_path: Path) -> None:
    """mirror.allium MovePage guidance 702 to 715: "a cut never shortens pages/<host>/".

    A stem cut to max_path_chars - 10 that is exactly pages/<host>/ shortens nothing, so
    the short-digest path is usable when it fits (weed, resume tick 1: off by one).
    """
    max_chars = model.CONFIG.max_path_chars
    room = 10  # the guidance's "max_path_chars - 10"
    host_chars = max_chars - room - len("pages/") - len("/")
    host = f"{'h' * (host_chars - len('.example'))}.example"
    identity = f"http://{host}/{'p' * max_chars}"
    root = f"pages/{host}/"
    assert len(root) == max_chars - room
    expected = f"{root}-{digest(identity)[: model.CONFIG.collision_hash_chars]}.md"
    assert assign_path(new_mirror(tmp_path), identity) == expected


def test_a_trailing_dot_host_is_allowed_by_its_own_scope() -> None:
    """mirror.allium CrawlScope: example.com. and example.com are one identity (113 to 120).

    host_allowed reads hostname_of(identity_of(url)), so the scope init derives from a
    site URL named with a trailing "." allows that URL (weed, resume tick 1).
    """
    seed = "http://Docs.Example./guide/start.html"
    scope = initial_scope(seed, profiles.GENERIC)
    assert scope.allowed_hosts == frozenset({"docs.example"})
    assert scope.host_allowed(seed)
    assert hostname_of(seed) == "docs.example"


IPV6_SEED = "http://[::1]:8080/guide/start.html"


def test_init_writes_an_ipv6_host_that_resolves(tmp_path: Path) -> None:
    """rovo.allium InitialiseMirror: rovo.toml's allowed_hosts holds the seed's host.

    For an IPv6 seed init wrote allowed_hosts = ["::1"], which resolve_config read back as
    a bad value, so sync refused a mirror init had just made (review T09-2-r4 C1 and B1).
    """
    (tmp_path / "rovo.toml").write_text(
        starter_config(IPV6_SEED, profiles.GENERIC), encoding="utf-8"
    )
    settings = resolve_config(tmp_path)
    assert settings.valid, settings.problems
    assert settings.allowed_hosts == frozenset({"::1"})
    assert hostname_of(IPV6_SEED) in settings.allowed_hosts


@pytest.mark.parametrize("host", ["::1", "[::1]", "[::1]:8080"])
def test_an_ipv6_allowed_host_resolves_bare_or_bracketed(tmp_path: Path, host: str) -> None:
    """An IPv6 literal resolves to its host name, with or without brackets (review T09-2-r4)."""
    (tmp_path / "rovo.toml").write_text(f'[scope]\nallowed_hosts = ["{host}"]\n', encoding="utf-8")
    settings = resolve_config(tmp_path)
    assert settings.valid, settings.problems
    assert settings.allowed_hosts == frozenset({"::1"})


def test_an_autolink_rewritten_becomes_an_inline_link() -> None:
    """mirror.allium RelativeLinksOnly: `<b.md>` is no link, so the URL becomes its text.

    An autolink left unchanged keeps its bytes, and a destination that runs into inline
    code is code, never a destination (CodeSamplesNeverRewritten).
    """
    url = "http://docs.example/guide/b.html"
    body = f"See <{url}> and <http://docs.example/x.html>, and [c](`{url}`).\n"
    rewritten = map_destinations(body, lambda target: "b.md" if target == url else target)
    assert rewritten == f"See [{url}](b.md) and <http://docs.example/x.html>, and [c](`{url}`).\n"
    assert link_destinations(body) == (url, "http://docs.example/x.html")


MALFORMED = "http://localhost:99999/x"
MALFORMED_LINK = f"""<!doctype html><html><head><title>Start</title></head><body><main>
<h1>Getting started</h1><p>See <a href="{MALFORMED}">the other port</a> for more.</p>
</main></body></html>"""


def test_a_malformed_url_is_out_of_bounds() -> None:
    """mirror.allium CrawlScope.within_bounds: a malformed URL is out of bounds (137).

    A port out of range made identity_of raise instead (weed, T10 tick 1).
    """
    scope = initial_scope(SEED, profiles.GENERIC)
    assert not scope.within_bounds(MALFORMED)
    assert not scope.allows(MALFORMED, 1)


def test_a_link_to_a_malformed_url_is_left_as_written(tmp_path: Path) -> None:
    """crawl.allium EnqueuePageLinks and mirror.allium FinalisePageBody: no crash.

    The link is never enqueued (scope.allows is false) and its destination stays as
    written. Whether it records an external Link, and with which target_identity, is the
    batched needs-user question; meanwhile it records none (weed, T10 tick 1).
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    assert sync(out_dir, MALFORMED_LINK) is ExitCode.ok
    mirror = load_mirror(out_dir)
    (page,) = mirror.pages
    assert f"]({MALFORMED})" in (out_dir / page.path).read_text(encoding="utf-8")
    assert all(link.target_identity != MALFORMED for link in mirror.links)
    frontier = json.loads((out_dir / ".rovo" / "frontier.json").read_text(encoding="utf-8"))
    assert len(frontier["entries"]) == 1


PAREN = f"{SITE}/guide/x_(y).html"
PAREN_LINK = """<!doctype html><html><head><title>Start</title></head><body><main>
<h1>Getting started</h1><p>Read <a href="x_(y).html">the paren page</a> next.</p>
</main></body></html>"""
PAREN_PAGE = """<!doctype html><html><head><title>Paren</title></head><body><main>
<h1>The paren page</h1><p>A page whose name holds parentheses.</p>
</main></body></html>"""


def test_a_destination_keeps_its_balanced_parentheses() -> None:
    """mirror.allium link_destinations lists each target as written (1041 to 1048).

    `[a](x_(y).html)` is one CommonMark link whose destination holds balanced
    parentheses; the first `)` cut it at `x_(y` (weed, T10 tick 2). An escaped parenthesis
    belongs to the destination, a title is passed over, and a destination whose
    parentheses close no link keeps the old reading.
    """
    body = (
        f'See [a]({PAREN}) and [b]({PAREN} "T (t)") and [c](x\\)y.html).\n'
        "Then [e](f((g)).html) and [d](u(v.html)\n"
    )
    assert link_destinations(body) == (
        PAREN,
        PAREN,
        "x\\)y.html",
        "f((g)).html",
        "u(v.html",
    )
    assert map_destinations(body, lambda target: target) == body
    rewritten = map_destinations(body, lambda target: "p.md" if target == PAREN else target)
    assert rewritten.startswith('See [a](p.md) and [b](p.md "T (t)") and')


def test_a_link_to_a_parenthesised_page_becomes_relative(tmp_path: Path) -> None:
    """mirror.allium LinkToPage and RelativeLinksOnly (1054 to 1064, 1420 to 1428).

    The page `x_(y).html` is written, so the link to it is internal and relative, and no
    uncrawled Link to `x_(y` is recorded (weed, T10 tick 2).
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    fetcher = FakeFetcher(
        {SEED: html_response(SEED, PAREN_LINK), PAREN: html_response(PAREN, PAREN_PAGE)}
    )
    synced = _commands.sync(
        out_dir, fetcher=fetcher, clock=FixedClock(), tier_installed=never_installed
    )
    assert synced is ExitCode.ok
    mirror = load_mirror(out_dir)
    pages = {page.source_url: page for page in mirror.pages}
    assert set(pages) == {SEED, PAREN}
    start = (out_dir / pages[SEED].path).read_text(encoding="utf-8")
    assert PAREN not in start
    assert "](x_-y-.md)" in start
    assert all(link.target_identity.startswith(PAREN) for link in mirror.links), mirror.links


BRACKETED = f"{SITE}/guide/b.html"
LOGO = f"{SITE}/guide/i.png"
BRACKETED_LINK = """<!doctype html><html><head><title>Start</title></head><body><main>
<h1>Getting started</h1><p>Read <a href="b.html">see [1]</a> and
<a href="b.html"><img src="i.png" alt="logo"></a> next.</p>
</main></body></html>"""
BRACKETED_PAGE = """<!doctype html><html><head><title>Bee</title></head><body><main>
<h1>The bee page</h1><p>A page linked through bracketed text and an image.</p>
</main></body></html>"""


def test_link_text_keeps_its_brackets_and_images() -> None:
    """mirror.allium link_destinations lists each target as written (1041 to 1048).

    Link text runs to the `]` balancing its `[`, as CommonMark reads it: `[see [1]](b)`
    names `b`, and `[![logo](i.png)](b)` names `b`, not the image's `i.png`; the first
    `]` hid one and swapped the other (weed, T10 tick 3). An escaped bracket, a bracket
    in a code span and an image on its own name no link; a link inside link text wins.
    """
    body = (
        "See [see [1]](b.html) and [![logo](i.png)](c.html).\n"
        "Then [a \\] b](d.html), [`]`](e.html), ![alone](f.png) and \\[g](h.html).\n"
        "Inner [x [y](i.html) z](j.html) and [open [k](l.html)\n"
    )
    assert link_destinations(body) == ("b.html", "c.html", "d.html", "e.html", "i.html", "l.html")
    assert map_destinations(body, lambda target: target) == body
    rewritten = map_destinations(body, lambda target: "p.md" if target == "c.html" else target)
    assert "[![logo](i.png)](p.md)" in rewritten


def test_a_link_with_bracketed_text_or_an_image_becomes_relative(tmp_path: Path) -> None:
    """mirror.allium LinkToPage and RelativeLinksOnly (1054 to 1064, 1420 to 1428).

    Both links to the written page `b.html` become relative, and the image `i.png` is
    recorded as no Link (weed, T10 tick 3).
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    fetcher = FakeFetcher(
        {
            SEED: html_response(SEED, BRACKETED_LINK),
            BRACKETED: html_response(BRACKETED, BRACKETED_PAGE),
        }
    )
    synced = _commands.sync(
        out_dir, fetcher=fetcher, clock=FixedClock(), tier_installed=never_installed
    )
    assert synced is ExitCode.ok
    mirror = load_mirror(out_dir)
    pages = {page.source_url: page for page in mirror.pages}
    assert set(pages) == {SEED, BRACKETED}
    start = (out_dir / pages[SEED].path).read_text(encoding="utf-8")
    assert BRACKETED not in start
    assert "[see [1]](b.md)" in start
    assert f"[![logo]({LOGO})](b.md)" in start
    assert all(link.target_identity != LOGO for link in mirror.links), mirror.links


class _JumpingClock:
    """A wall clock that steps an hour forward on every reading."""

    def __init__(self) -> None:
        self.readings = 0

    def now(self, tz: object = None) -> datetime:
        del tz
        self.readings += 1
        return datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC) + timedelta(hours=self.readings)


def test_anchored_now_ignores_a_wall_clock_jump(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review T12-1: the pacing time reads no wall clock after its anchor.

    Two readings at the same monotonic time agree although the wall clock jumped forward
    between them; the result is the anchor plus the monotonic delta.
    """
    jumping = _JumpingClock()
    monkeypatch.setattr(pace, "datetime", jumping)
    anchor = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)
    first = pace.anchored_now(anchor, 10.0, 12.5)
    jumping.now()
    second = pace.anchored_now(anchor, 10.0, 12.5)
    assert first == second == anchor + timedelta(seconds=2.5)
    assert jumping.readings == 1


# --- T12 implement 2 and 3, pinned by propagate tick 4 (witness tick 3) -------------

MOVED_STATUSES = (301, 302, 307, 308)
SERVICE_UNAVAILABLE = 503
NOT_MODIFIED = 304
NOT_FOUND = 404
# retry_after_cap in seconds, exactly, for a Crawl-delay a sub-ULP step past it.
CRAWL_DELAY_CAP = Decimal(str(CRAWL_CONFIG.retry_after_cap.total_seconds()))
TOO_LONG_FOR_A_DURATION = ("99999999999999999999", "86400000000000", "9" * 5000)


def retry_after_of(value: bytes) -> timedelta | None:
    """The Retry-After HttpxFetcher reads from a 503 carrying the raw header `value`."""

    def answer(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(SERVICE_UNAVAILABLE, headers=[(b"retry-after", value)])

    with HttpxFetcher(transport=httpx.MockTransport(answer)) as fetcher:
        return fetcher.fetch(SEED).retry_after


@pytest.mark.parametrize("value", TOO_LONG_FOR_A_DURATION, ids=["20-digits", "14-digits", "5000"])
def test_a_retry_after_too_long_for_a_duration_is_the_longest(value: str) -> None:
    """Implement T12-3: a whole number of seconds past timedelta's range saturates.

    The value is still past retry_after_cap, so it retires the host as any long
    Retry-After does (crawl.allium RetireHostOnLongRetryAfter); reading it never raises.
    """
    read = retry_after_of(value.encode("ascii"))
    assert read == timedelta.max
    assert read > CRAWL_CONFIG.retry_after_cap


def test_a_zero_padded_retry_after_is_its_number() -> None:
    """Implement T12-3: leading zeros are dropped before the length check, not counted."""
    assert retry_after_of(b"0" * 40 + b"5") == timedelta(seconds=5)
    assert retry_after_of(b"0") == timedelta(0)


@pytest.mark.parametrize(
    "value", [b"\xb2", b"\xb9\xb2\xb3"], ids=["superscript-2", "superscripts"]
)
def test_a_non_ascii_digit_retry_after_is_unreadable(value: bytes) -> None:
    """Implement T12-3: delay-seconds is 1*DIGIT (RFC 9110), ASCII only.

    A latin-1 superscript passes str.isdigit; it is neither seconds nor an HTTP date, so
    it is no Retry-After, as an unreadable value is.
    """
    assert retry_after_of(value) is None


def test_a_saturated_retry_after_retires_the_host(tmp_path: Path) -> None:
    """Implement T12-3, end to end: a 503 with a huge Retry-After retires the host.

    Through HttpxFetcher and the driver, the honoured Retry-After past retry_after_cap
    retires the host (RetireHostOnLongRetryAfter) instead of an overflow: the seed is
    asked once and fails, and the sync exits blocked (3). Re-propagated by T18 (origin
    T12), which expected NotInThisSlice("RetireHostOnLongRetryAfter").
    """

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(NOT_FOUND)
        return httpx.Response(
            SERVICE_UNAVAILABLE, headers={"retry-after": TOO_LONG_FOR_A_DURATION[0]}
        )

    mirror = crawl_mirror(tmp_path / "run")
    with HttpxFetcher(transport=httpx.MockTransport(answer)) as fetcher:
        result = run_crawl(crawl_request(mirror), None, fetcher, FixedClock())
    assert result.run.has_tripped_host
    assert [(event.url, event.attempts) for event in result.failed] == [(SEED, 1)]
    assert retired_sync(tmp_path / "sync", answer) is ExitCode.blocked


def retired_sync(out_dir: Path, answer: Callable[[httpx.Request], httpx.Response]) -> ExitCode:
    """Rovo init then rovo sync through HttpxFetcher answering with `answer`."""
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    with HttpxFetcher(transport=httpx.MockTransport(answer)) as fetcher:
        return _commands.sync(out_dir, fetcher=fetcher, clock=FixedClock())


@pytest.mark.parametrize("status", MOVED_STATUSES)
def test_a_raw_page_redirect_without_a_location_fails_with_its_status_text(
    tmp_path: Path, status: int
) -> None:
    """Implement T12-2, re-propagated by T15: a page's 3xx with no Location fails.

    Was test_a_raw_page_redirect_is_a_later_slices, which expected
    NotInThisSlice("DisposeFetch"). T15 follows redirects; a 3xx with no usable Location
    is not followed and is not an unfollowed redirect (tickets/T15-lifecycle.md Open
    points item 6), so it reaches DisposeFetch's not-ok branch and fails the entry with
    its status text after its one try.
    """
    _, _, walk = settled(tmp_path, FakeFetcher({SEED: html_response(SEED, "", status=status)}))
    response = walk.attempts[-1].response
    assert (response.redirect_location, response.redirect_hops) == (None, ())
    failed = dispose_fetch(walk)
    assert isinstance(failed, EntryFailed)
    assert failed.error == f"{status} {HTTPStatus(status).phrase}"
    assert failed.attempts == 1
    assert walk.entry.status is FrontierStatus.in_progress


def test_a_not_modified_page_with_no_stored_page_fails(tmp_path: Path) -> None:
    """Implement T12-2: a 304 for a URL with no stored page still fails its row.

    DisposeFetch's guidance: with no page to keep, a 304 is not ok and fails the entry
    with its status text after the try that answered it.
    """
    fetcher = FakeFetcher({SEED: html_response(SEED, "", status=NOT_MODIFIED)})
    _, _, walk = settled(tmp_path, fetcher)
    failed = dispose_fetch(walk)
    assert isinstance(failed, EntryFailed)
    assert failed.error.startswith(str(NOT_MODIFIED))
    assert failed.attempts == 1


@pytest.mark.parametrize("delay", ["1e15", "1e12", "99999999999"])
def test_a_huge_crawl_delay_retires_the_host_instead_of_overflowing(
    tmp_path: Path, delay: str
) -> None:
    """Weed T12-4 code-bug 1, answered at 71b5b0f: a huge Crawl-delay never overflows.

    Through HttpxFetcher and the driver, a Crawl-delay past retry_after_cap is compared as
    written (robots_crawl_delay_exceeds), never adopted, and retires the host
    (RetireHostOnLongCrawlDelay), not an OverflowError in timedelta or the limiter, and
    not stalled waiting it out: nothing after robots.txt is requested and the sync exits
    blocked (3). Re-propagated by T18 (origin T12), which expected
    NotInThisSlice("RetireHostOnLongCrawlDelay").
    """
    paths: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=f"User-agent: *\nCrawl-delay: {delay}\n")
        return httpx.Response(NOT_FOUND)

    mirror = crawl_mirror(tmp_path / "run")
    with HttpxFetcher(transport=httpx.MockTransport(answer)) as fetcher:
        result = run_crawl(crawl_request(mirror), None, fetcher, FixedClock())
    assert result.run.has_tripped_host
    assert paths == ["/robots.txt"]
    assert retired_sync(tmp_path / "sync", answer) is ExitCode.blocked


def crawl_delay_fetcher(delay: str) -> HttpxFetcher:
    """An HttpxFetcher whose robots.txt declares Crawl-delay `delay`.

    The seed answers a page, anything else a 404.
    """

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=f"User-agent: *\nCrawl-delay: {delay}\n")
        if str(request.url) == SEED:
            return httpx.Response(200, html=UNLINKED)
        return httpx.Response(NOT_FOUND)

    return HttpxFetcher(transport=httpx.MockTransport(answer))


@pytest.mark.parametrize(
    "delay",
    [
        "1e309",
        "1e400",
        str(CRAWL_DELAY_CAP + Decimal("1e-15")),
        "1e1000000000000000000",
        "1e9999999999999999999",
    ],
    ids=["1e309", "1e400", "cap-plus-sub-ulp", "1e1000000000000000000", "1e9999999999999999999"],
)
def test_a_crawl_delay_is_compared_with_the_cap_as_written(tmp_path: Path, delay: str) -> None:
    """Reviews T12-2-r2 C1/B1 and T12-3-r2 C1/B1: the Crawl-delay number is read exactly.

    protego reads a Crawl-delay as a float, so 1e309 and 1e400 were no delay and the cap
    plus one sub-ULP step was the cap; an exponent past Decimal's own limit raised or was
    dropped. Each is past retry_after_cap as written (crawl.allium AdoptRobotsRules'
    guidance, 837 to 843 at fa096c4), so the host retires right after robots.txt
    (RetireHostOnLongCrawlDelay): the seed is skipped, and the sync exits blocked (3).
    Re-propagated by T18 (origin T12), which expected
    NotInThisSlice("RetireHostOnLongCrawlDelay").
    """
    mirror = crawl_mirror(tmp_path / "run")
    with crawl_delay_fetcher(delay) as fetcher:
        result = run_crawl(crawl_request(mirror), None, fetcher, FixedClock())
    assert result.run.has_tripped_host
    assert [event.url for event in result.skipped] == [SEED]
    assert _commands.init(SEED, tmp_path / "sync") is ExitCode.ok
    with crawl_delay_fetcher(delay) as fetcher:
        code = _commands.sync(tmp_path / "sync", fetcher=fetcher, clock=FixedClock())
    assert code is ExitCode.blocked


@pytest.mark.parametrize(
    ("delay", "adopted"),
    [
        ("_121", None),
        ("121_", None),
        ("1__21", None),
        ("-1e9999999999999999999", None),
        ("1e-9999999999999999999", timedelta(0)),
    ],
    ids=["_121", "121_", "1__21", "minus-1e9999999999999999999", "1e-9999999999999999999"],
)
def test_a_crawl_delay_outside_floats_grammar_is_no_crawl_delay(
    tmp_path: Path, delay: str, adopted: timedelta | None
) -> None:
    """Review T12-3-r2 C2 (and C1's small end): what protego cannot read is no Crawl-delay.

    A number is what protego reads, float's grammar: misplaced underscores and a negative
    number are null, and a number too small for Decimal's exponent is 0. None retires
    the host, so the run through HttpxFetcher finishes.
    """
    mirror = crawl_mirror(tmp_path)
    with crawl_delay_fetcher(delay) as fetcher:
        result = run_crawl(crawl_request(mirror), None, fetcher, FixedClock())
    assert result.run.status is RunStatus.finished
    policy = result.run.robots_policy(SITE)
    assert policy is not None
    assert policy.crawl_delay == adopted
    (host,) = result.run.hosts
    assert host.crawl_delay == timedelta(0)


# --- T13 planning: the discovered count, and a discovered URL with no identity ------------

NO_IDENTITY = f"{SITE}:99999/guide/no-identity.html"


def test_discovered_counts_the_rows_after_discovery(tmp_path: Path) -> None:
    """Planning T13: rovo.allium CloseRun's discovered_count is the rows after discovery.

    close_run counted the frontier's rows when the run closed, every row a link added
    included; the report's discovered is the count DropStaleObservations left.
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    fetcher = FakeFetcher(fixture_site("links", f"{SITE}/"))
    _commands.sync(out_dir, fetcher=fetcher, clock=FixedClock(), tier_installed=never_installed)
    state = json.loads((out_dir / ".rovo" / "frontier.json").read_text(encoding="utf-8"))
    report = json.loads((out_dir / "crawl-report.json").read_text(encoding="utf-8"))
    assert len(state["entries"]) > 1
    assert report["discovered"] == 1


def test_a_sitemap_entry_or_llms_txt_target_with_no_identity_is_skipped(tmp_path: Path) -> None:
    """T13, crawl.allium ExpandSitemapEntries (ecfa257): a URL with no identity is skipped.

    normalise_url cannot normalise a port out of range (identity_of is null in the
    specification): such a sitemap entry or llms.txt target is neither observed nor
    discovered, counts toward no cap, raises no problem, and the run finishes.
    """
    maps = f"{SITE}/maps/guide.xml"
    llms_txt = f"{SITE}/llms.txt"
    fetcher = site(robots=declaring(maps))
    fetcher.responses[maps] = xml_response(maps, urlset((NO_IDENTITY, None), (SEED, None)))
    fetcher.responses[llms_txt] = text_response(llms_txt, f"- [Gone]({NO_IDENTITY})\n")
    result = run_crawl(crawl_request(crawl_mirror(tmp_path)), None, fetcher, FixedClock())
    assert result.run.status is RunStatus.finished
    assert result.run.discovery_failures == []
    assert [seen.url for seen in result.frontier.observed_urls] == [SEED]
    assert [entry.identity for entry in result.frontier.entries] == [SEED]
    (host,) = result.run.hosts
    assert host.sitemap_entries_admitted == 1


def test_a_move_whose_natural_path_is_unchanged_keeps_its_path(tmp_path: Path) -> None:
    """Weed T15-1, mirror.allium MovePage: the file moves only if new_path != old_path.

    assign_path suffixes a path held by another page; the page being moved is not
    another page. OTHER redirecting from http to https keeps pages/<host>/other.md: no
    digest suffix, no moved_from, no moved outcome, and no file under _removed/.
    """
    mirror, _, other = written_pair(tmp_path)
    old_path, old_digest = other.path, other.content_digest
    secure = OTHER.replace("http://", "https://", 1)
    candidate = candidate_for(
        mirror, requested=OTHER, source=secure, hops=(OTHER,), converted=content(body=OTHER_BODY)
    )
    assert move_page(candidate, FixedClock()) is other
    assert (other.identity, other.path) == (secure, old_path)
    assert other.moved_from is None
    assert not other.was_moved
    assert other.previous_digest == old_digest
    assert [(alias.url, alias.target.identity) for alias in mirror.aliases] == [(OTHER, secure)]
    finalisation = finalised_run(mirror)
    assert all(event.outcome is not StoreOutcome.moved for event in finalisation.finalised)
    assert (tmp_path / old_path).is_file()
    assert sorted(path.name for path in (tmp_path / ROOT).iterdir()) == ["other.md", "start.md"]
    assert not (tmp_path / "_removed").exists()


def test_a_redirected_llms_txt_resolves_its_targets_against_llms_txt_url(tmp_path: Path) -> None:
    """Weed T15-1, crawl.allium ReadLlmsTxt: llms_txt_targets(response, llms_txt_url(name)).

    /llms.txt answers 301 to /docs/llms.txt, which links the relative guide/a.html: the
    target is resolved against the requested llms_txt_url, as a sitemap's entries are
    against the requested sitemap URL, so it is observed at /guide/a.html.
    """
    fetcher = site()
    moved = f"{SITE}/docs/llms.txt"
    fetcher.responses[LLMS_TXT] = redirect_response(LLMS_TXT, "/docs/llms.txt")
    fetcher.responses[moved] = text_response(moved, "# Example docs\n\n- [A](guide/a.html)\n")
    run, frontier, host = host_open(tmp_path, fetcher)
    response = read_llms_txt(run, host.name, frontier, fetcher)
    assert response is not None
    assert response.ok
    assert [seen.url for seen in frontier.observed_urls] == [f"{SITE}/guide/a.html"]


def test_a_case_only_move_leaves_the_file_under_its_new_spelling(tmp_path: Path) -> None:
    """Weed T15-2 and T15-3, mirror.allium MovePage: previous.path = new_path.

    OTHER redirecting to /guide/Other.html moves the page to pages/<host>/Other.md, a
    path that differs from other.md only in case. PageFileMoved(old_path, new_path) ends
    with the page file present and the directory entry spelled Other.md, as the manifest
    and every relative link name it, on a case-insensitive file system as on a
    case-sensitive one; nothing is archived.
    """
    mirror, _, other = written_pair(tmp_path)
    old_path = other.path
    mixed = OTHER.replace("other.html", "Other.html")
    candidate = candidate_for(
        mirror, requested=OTHER, source=mixed, hops=(OTHER,), converted=content(body=OTHER_BODY)
    )
    assert move_page(candidate, FixedClock()) is other
    assert (other.path, other.moved_from) == (f"{ROOT}Other.md", old_path)
    finalised_run(mirror)
    assert (tmp_path / other.path).is_file()
    assert sorted(path.name for path in (tmp_path / ROOT).iterdir()) == ["Other.md", "start.md"]
    assert not (tmp_path / "_removed").exists()


# --- T17 weed 1 (ai_tmp/T17/weed-1.md) ---------------------------------------------------

DEVSITE_PAGE = """<!doctype html>
<html lang="en">
    <head><title>Replaced elements</title></head>
    <body>
        <div class="devsite-article-body">
            <h1>Replaced elements</h1>
            <p>Each construct below is replaced by normalisation.</p>
            {construct}
            <p>A closing sentence after the construct.</p>
        </div>
    </body>
</html>
"""
REPLACED_IDS = {
    "tab-group-and-panels": (
        (
            '<devsite-selector id="grp">'
            '<section id="py"><h3>Python</h3>'
            '<pre><code class="language-python">print(1)</code></pre></section>'
            '<section id="js" hidden><h3>JavaScript</h3>'
            '<pre><code class="language-javascript">log(1)</code></pre></section>'
            "</devsite-selector>"
        ),
        ("grp", "py", "js"),
    ),
    "callout": (
        '<aside class="note" id="n1"><strong>Note:</strong> Read it once.</aside>',
        ("n1",),
    ),
    "interactive-embed": (
        '<iframe id="emb" src="https://example.invalid/demo" title="Demo"></iframe>',
        ("emb",),
    ),
    "layout-table": (
        (
            '<table role="presentation" id="lay"><tr><td><p>Left column.</p></td>'
            "<td><p>Right column.</p></td></tr></table>"
        ),
        ("lay",),
    ),
    "footnote-section": (
        (
            '<p>A claim<sup id="fnref1"><a href="#fn1" class="footnote-ref">1</a></sup>.</p>'
            '<section class="footnotes" id="notes"><ol><li id="fn1"><p>The source. '
            '<a href="#fnref1" class="footnote-backref">&#8617;</a></p></li></ol></section>'
        ),
        ("notes",),
    ),
}


@pytest.mark.parametrize("name", list(REPLACED_IDS))
def test_a_replaced_elements_source_id_stays_an_anchor(name: str) -> None:
    """Weed T17-1, convert.allium BodyShape: the body keeps every source id as an anchor.

    Tab expansion, callouts and the declared reductions replace an element; no reduction
    declares its id lost (DeclaredReductions), so each id is an anchor and an anchor
    island in the body, wherever implement places it.
    """
    construct, ids = REPLACED_IDS[name]
    content = converted_by(DEVSITE_PAGE.format(construct=construct), profiles.DEVSITE)
    for anchor in ids:
        assert anchor in content.anchors, (anchor, content.anchors)
        assert f'<a id="{anchor}"></a>' in content.body, (anchor, content.body)


def test_whole_body_extraction_strips_the_profiles_chrome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Weed T17-1, convert.allium ExtractNeverEmptyHanded: the profile's chrome goes.

    When the devsite content selection matches nothing and the fallback extractor finds no
    main content, the whole body stands in for the content and devsite's chrome (header,
    book navigation, footer) is stripped from it; the article's text stays. Re-propagated
    by the T17 follow-up (spec 022eca4): the fallback extractor, trafilatura, runs before
    the whole body, so it is made to find nothing here (the extract call is the seam);
    left alone, it extracts this page (tests/test_convert.py::test_ExtractNeverEmptyHanded).
    """
    monkeypatch.setattr("trafilatura.extract", lambda *_args, **_kwargs: None)
    unselected = TABS_PAGE.replace('class="devsite-article-body"', 'class="article-body"')
    extracted = extract(unselected, SEED, profiles.DEVSITE)
    assert extracted.method is ExtractionMethod.whole_body
    for chrome in DEVSITE_CHROME:
        assert chrome not in extracted.html, chrome
    assert "pip install example-client" in extracted.html


def test_an_unreadable_page_file_is_invalid_page_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Weed T17-1, mirror.allium VerifyPages: an unreadable page file is a finding.

    A page file that exists but cannot be read does not parse (invalid_page_file), and
    rovo verify exits quality (rovo.allium VerifyIndexReportExitCodes: 0, 4 or 2) rather
    than crash.
    """
    out_dir, _ = synced_mirror(tmp_path / "out")
    unreadable = out_dir / B
    read_text = Path.read_text

    def refusing(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if path == unreadable:
            raise PermissionError(13, "Permission denied", str(path))
        return read_text(path, encoding, errors)

    monkeypatch.setattr(Path, "read_text", refusing)
    assert VerificationReason.invalid_page_file in reasons_at(findings(out_dir), B)
    assert _commands.verify(out_dir) is ExitCode.quality


# --- T17 weed 2 (ai_tmp/T17/weed-2.md) ---------------------------------------------------

LABELLED_TABS = (
    MSLEARN_PAGE.replace('<ul role="tablist">', '<ul role="tablist" id="tablist_1">')
    .replace('role="tab" data-tab="http"', 'role="tab" data-tab="http" id="tab_1_http"')
    .replace('role="tab" data-tab="csharp"', 'role="tab" data-tab="csharp" id="tab_1_csharp"')
)
FORM_WRAPPERS = (
    '<form id="f1"><fieldset id="fs1"><label id="l1" for="q">Query</label>'
    '<input id="q" name="q"><button id="b1" type="submit">Search</button></fieldset></form>'
)


@pytest.mark.parametrize(
    ("html", "profile", "url", "ids"),
    [
        (LABELLED_TABS, profiles.MSLEARN, LEARN_URL, ("tablist_1", "tab_1_http", "tab_1_csharp")),
        (
            DEVSITE_PAGE.format(construct=FORM_WRAPPERS),
            profiles.DEVSITE,
            SEED,
            ("f1", "fs1", "l1", "b1"),
        ),
    ],
    ids=["tab-list-and-labels", "form-wrappers"],
)
def test_a_tab_label_or_form_wrappers_source_id_stays_an_anchor(
    html: str, profile: Profile, url: str, ids: tuple[str, ...]
) -> None:
    """Weed T17-2, convert.allium BodyShape: the body keeps every source id as an anchor.

    Tab expansion carries a tab label's text as its panel's label and replaces the group
    with its panels; a form wrapper unwraps (DeclaredReductions: button labels stay).
    No reduction declares the tab list's, a label's or a wrapper's id lost, so each is an
    anchor and an anchor island in the body. A form control's id goes with the control.
    """
    content = converted_by(html, profile, url)
    for anchor in ids:
        assert anchor in content.anchors, (anchor, content.anchors)
        assert f'<a id="{anchor}"></a>' in content.body, (anchor, content.body)
