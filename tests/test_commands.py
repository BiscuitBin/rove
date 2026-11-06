"""rovo.allium's command obligations: init, the sync refusals, StartSync, report, crashes.

Each test is named after the obligation id `just plan-spec rovo` emits, dots and hyphens
as underscores, and its docstring quotes the obligation. `rovo._commands.sync` takes a
Fetcher and a Clock; a refused command makes no request. With no directory or no
loadable manifest it writes no report (RefuseSyncWithoutDirectory); every later refusal
writes a refused crawl-report.json (ReportRefusal), in the specification's order
(RefusalsInOrder). Re-propagated by T16 (origin T09): until T16 every failed StartSync
guard exited usage with no report.
"""

import dataclasses
import importlib.metadata
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fakes import (
    START,
    FakeFetcher,
    FixedClock,
    RaisingFetcher,
    ScriptedFetcher,
    SteppingTimer,
    fixture_site,
    html_response,
    text_response,
)
from rovo import _commands
from rovo._config import SyncOptions, initial_scope, resolve_config, scope_of, signature_of
from rovo._convert import profiles
from rovo._convert.model import QualityGate
from rovo._crawl.model import CONFIG as CRAWL
from rovo._crawl.model import ProgressEvent, Run
from rovo._crawl.run import end_run, finish_run
from rovo._mirror.finalise import request_pass
from rovo._mirror.indexes import index_pass
from rovo._mirror.model import (
    IndexesWritten,
    Operator,
    PassKind,
    Tier,
    VerificationFailure,
    VerificationReason,
)
from rovo._mirror.state import load_mirror, manifest_path
from rovo._mirror.verify import verify_pass
from rovo._report import (
    CrawlReport,
    CrawlReportStatus,
    ExitCode,
    ReportStatus,
    interrupt_sync,
    rank_and_write_report,
    record_crash,
    record_crash_after_run,
    report_path,
)
from rovo._unfinished import NotInThisSlice
from test_crawl import started
from test_report import opened

SITE = "http://docs.example"
SEED = f"{SITE}/guide/start.html"
# The seed page's mirror-relative path (mirror.allium MovePage guidance, at fed9ed8).
START_PATH = "pages/docs.example/start.md"
ROBOTS = f"{SITE}/robots.txt"
# T13: robots.txt, then the sitemaps and llms.txt of a host whose robots.txt allows them.
DISCOVERY = [ROBOTS, f"{SITE}/sitemap.xml", f"{SITE}/sitemap_index.xml", f"{SITE}/llms.txt"]
SITES = Path(__file__).resolve().parent / "fixtures" / "sites"
PAGE = (SITES / "one-page" / "guide" / "start.html").read_text(encoding="utf-8")
DISALLOW_GUIDE = (SITES / "robots-disallow" / "robots.txt").read_text(encoding="utf-8")
SERVICE_UNAVAILABLE = 503


def site() -> FakeFetcher:
    """The fixture site: the seed page, robots.txt absent."""
    return FakeFetcher({SEED: html_response(SEED, PAGE)})


def disallowing() -> FakeFetcher:
    """The fixture site with a robots.txt that disallows /guide/."""
    return FakeFetcher(
        {ROBOTS: text_response(ROBOTS, DISALLOW_GUIDE), SEED: html_response(SEED, PAGE)}
    )


def initialised(out_dir: Path) -> Path:
    """A mirror rovo init made for the seed URL."""
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    return out_dir


def synced(out_dir: Path, fetcher: FakeFetcher) -> ExitCode:
    """One rovo sync of the mirror over `fetcher`, with no browser installed."""
    return _commands.sync(
        out_dir, fetcher=fetcher, clock=FixedClock(), tier_installed=never_installed
    )


def never_installed(tier: Tier) -> bool:
    """No engine beyond http is installed."""
    del tier
    return False


def set_key(out_dir: Path, key: str, value: str) -> None:
    """Replace the one `key = ...` line of rovo.toml with `key = value`."""
    path = out_dir / "rovo.toml"
    text, count = re.subn(
        rf"(?m)^{re.escape(key)} = .*$", f"{key} = {value}", path.read_text(encoding="utf-8")
    )
    assert count == 1, key
    path.write_text(text, encoding="utf-8")


def drop_key(out_dir: Path, key: str) -> None:
    """Remove the one `key = ...` line of rovo.toml: the key takes its built-in default."""
    path = out_dir / "rovo.toml"
    text, count = re.subn(rf"(?m)^{re.escape(key)} = .*\n", "", path.read_text(encoding="utf-8"))
    assert count == 1, key
    path.write_text(text, encoding="utf-8")


def snapshot(out_dir: Path) -> dict[str, bytes]:
    """Every file under the directory, by relative path."""
    return {
        str(path.relative_to(out_dir)): path.read_bytes()
        for path in sorted(out_dir.rglob("*"))
        if path.is_file()
    }


def report(out_dir: Path) -> dict[str, object]:
    """The crawl-report.json the sync left."""
    loaded = json.loads(report_path(out_dir).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


# The refusal reasons, rovo.allium's text exactly (T16).
BAD_CONFIG = "invalid configuration"
CHANGED_ROOT = "changed root requires confirmation"
OFF_HOST = "invalid or off-host target"
UNKNOWN_PATH = "unknown target path"
MISSING_ENGINE = "configured tier is not installed"


def refused(out_dir: Path) -> dict[str, object]:
    """The refused crawl-report.json ReportRefusal wrote: no run, usage, no policy."""
    data = report(out_dir)
    assert data["report_status"] == "refused"
    assert data["run_id"] is None
    assert data["exit_code"] == "usage"
    assert data["effective_policy"] is None
    assert data["error"] is None
    return data


def with_provider(out_dir: Path) -> Path:
    """The mirror's rovo.toml with an [unblocking] provider, which is always invalid."""
    path = out_dir / "rovo.toml"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^\[unblocking\]\n(?:#.*\n|\s*\n)*", "", text)
    path.write_text(text + '\n[unblocking]\nprovider = "paid"\n', encoding="utf-8")
    return out_dir


# --- init ---------------------------------------------------------------------------


def test_rule_success_InitialiseMirror(tmp_path: Path) -> None:
    """Verify rule InitialiseMirror succeeds when all preconditions are met.

    rovo.toml and an empty manifest are written, and nothing is crawled.
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    assert (out_dir / "rovo.toml").is_file()
    assert manifest_path(out_dir).is_file()
    assert load_mirror(out_dir).pages == []
    assert list(out_dir.rglob("*.md")) == []
    assert not report_path(out_dir).exists()
    assert resolve_config(out_dir).valid


def test_rule_failure_InitialiseMirror_1(tmp_path: Path) -> None:
    """Verify rule InitialiseMirror is rejected when requires clause fails.

    requires: is_http_url(site_url).
    """
    out_dir = tmp_path / "out"
    assert _commands.init("ftp://docs.example/guide/start.html", out_dir) is ExitCode.usage
    assert _commands.init("not a url", out_dir) is ExitCode.usage
    assert not out_dir.exists() or snapshot(out_dir) == {}


def test_rule_failure_InitialiseMirror_2(tmp_path: Path) -> None:
    """Verify rule InitialiseMirror is rejected when requires clause fails.

    requires: not exists mirror/Mirror{out_dir}: a manifest, parsable or not, or an
    existing rovo.toml.
    """
    out_dir = initialised(tmp_path / "out")
    before = snapshot(out_dir)
    assert _commands.init(f"{SITE}/other/page.html", out_dir) is ExitCode.usage
    assert snapshot(out_dir) == before

    manifest_path(out_dir).write_text("{not json", encoding="utf-8")
    damaged = snapshot(out_dir)
    assert _commands.init(SEED, out_dir) is ExitCode.usage
    assert snapshot(out_dir) == damaged

    only_toml = tmp_path / "only-toml"
    only_toml.mkdir()
    (only_toml / "rovo.toml").write_text("# kept\n", encoding="utf-8")
    assert _commands.init(SEED, only_toml) is ExitCode.usage
    assert snapshot(only_toml) == {"rovo.toml": b"# kept\n"}


def test_rule_failure_InitialiseMirror_3(tmp_path: Path) -> None:
    """Verify rule InitialiseMirror is rejected when requires clause fails.

    requires: profile != null: an unknown profile name.
    """
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir, "no-such-profile") is ExitCode.usage
    assert not out_dir.exists() or snapshot(out_dir) == {}


def test_rule_entity_creation_InitialiseMirror_1(tmp_path: Path) -> None:
    """Verify entity creation in rule InitialiseMirror ensures clause produces the specified fields."""  # noqa: E501  The obligation's description, quoted.
    out_dir = initialised(tmp_path / "out")
    mirror = load_mirror(out_dir)
    scope = initial_scope(SEED, profiles.GENERIC)
    assert mirror.out_dir == out_dir
    assert mirror.scope == scope
    assert mirror.profile == profiles.GENERIC
    assert mirror.declared_owned_hosts == frozenset()
    assert mirror.recorded_root_url is None
    assert mirror.processing_signature == signature_of(scope, profiles.GENERIC)
    assert mirror.pages == []
    assert mirror.aliases == []
    settings = resolve_config(out_dir)
    assert settings.profile_name == "generic"
    assert settings.start_urls == (SEED,)

    named = initialised_with(tmp_path / "named", "devsite")
    assert load_mirror(named).profile == profiles.DEVSITE
    assert resolve_config(named).profile_name == "devsite"


def initialised_with(out_dir: Path, profile_name: str) -> Path:
    """A mirror rovo init made with a named profile."""
    assert _commands.init(SEED, out_dir, profile_name) is ExitCode.ok
    return out_dir


def test_rule_success_RefuseInit(tmp_path: Path) -> None:
    """Verify rule RefuseInit succeeds when all preconditions are met.

    Each of the three problems exits usage and writes nothing.
    """
    assert _commands.init("mailto:docs@example.com", tmp_path / "a") is ExitCode.usage
    existing = initialised(tmp_path / "b")
    before = snapshot(existing)
    assert _commands.init(SEED, existing) is ExitCode.usage
    assert snapshot(existing) == before
    assert _commands.init(SEED, tmp_path / "c", "nope") is ExitCode.usage
    for name in ("a", "c"):
        assert not (tmp_path / name / "rovo.toml").exists()


def test_rule_failure_RefuseInit_1(tmp_path: Path) -> None:
    """Verify rule RefuseInit is rejected when requires clause fails.

    requires: not http, or an existing mirror, or an unknown profile: none holds.
    """
    assert _commands.init(SEED, tmp_path / "out") is ExitCode.ok


# --- sync: the refusal this slice owns ----------------------------------------------


def test_rule_success_RefuseSyncWithoutDirectory(tmp_path: Path) -> None:
    """Verify rule RefuseSyncWithoutDirectory succeeds when all preconditions are met.

    A missing directory, a directory with no manifest and an unparsable manifest each
    exit usage, make no request and write no report.
    """
    fetcher = site()
    missing = tmp_path / "missing"
    assert synced(missing, fetcher) is ExitCode.usage
    assert not missing.exists()

    empty = tmp_path / "empty"
    empty.mkdir()
    assert synced(empty, fetcher) is ExitCode.usage
    assert not report_path(empty).exists()

    damaged = initialised(tmp_path / "damaged")
    manifest_path(damaged).write_text("{not json", encoding="utf-8")
    assert synced(damaged, fetcher) is ExitCode.usage
    assert not report_path(damaged).exists()
    assert fetcher.requests == []


def test_rule_failure_RefuseSyncWithoutDirectory_1(tmp_path: Path) -> None:
    """Verify rule RefuseSyncWithoutDirectory is rejected when requires clause fails.

    requires: not directory_exists or not exists the mirror: both exist, so the sync runs.
    """
    fetcher = site()
    out_dir = initialised(tmp_path / "out")
    assert synced(out_dir, fetcher) is ExitCode.ok
    assert fetcher.requests == [*DISCOVERY, SEED]


def test_sync_dry_run_lists_the_pending_rows_and_writes_no_page(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """T13: sync(dry_run=True) discovers, prints the pending identities and fetches no page.

    The listing is the one thing on standard output, one identity a line in next_pending
    order; the frontier, the run (dry_run true) and the report are saved; no page file,
    index or _indexes/ is written (crawl.allium DryRun guidance, at ecfa257).
    """
    llms_txt = f"{SITE}/llms.txt"
    listed = f"{SITE}/guide/listed.html"
    fetcher = site()
    fetcher.responses[llms_txt] = text_response(llms_txt, f"- [Listed]({listed})\n")
    out_dir = initialised(tmp_path / "out")
    capsys.readouterr()
    code = _commands.sync(
        out_dir,
        fetcher=fetcher,
        clock=FixedClock(),
        tier_installed=never_installed,
        dry_run=True,
    )
    assert code is ExitCode.ok
    assert capsys.readouterr().out == f"{SEED}\n{listed}\n"
    assert fetcher.requests == DISCOVERY
    for name in ("pages", "index.md", "index.jsonl", "links.jsonl", "llms.txt", "_indexes"):
        assert not (out_dir / name).exists(), name
    assert load_mirror(out_dir).pages == []
    state = out_dir / ".rovo"
    frontier = json.loads((state / "frontier.json").read_text(encoding="utf-8"))
    assert [(row["identity"], row["status"]) for row in frontier["entries"]] == [
        (SEED, "pending"),
        (listed, "pending"),
    ]
    runs = json.loads((state / "runs.json").read_text(encoding="utf-8"))["runs"]
    assert [row["dry_run"] for row in runs] == [True]
    report = json.loads(report_path(out_dir).read_text(encoding="utf-8"))
    assert report["options"]["dry_run"] is True
    assert (report["fetched"], report["discovered"], report["exit_code"]) == (0, 2, "ok")


# --- sync: StartSync ----------------------------------------------------------------


def test_rule_success_StartSync(tmp_path: Path) -> None:
    """Verify rule StartSync succeeds when all preconditions are met.

    The run starts, the seed page is published at pages/docs.example/start.md, never
    beside the managed root files, and the report is written.
    """
    out_dir = initialised(tmp_path / "out")
    assert synced(out_dir, site()) is ExitCode.ok
    assert (out_dir / START_PATH).is_file()
    pages = out_dir.glob("pages/**/*.md")
    assert sorted(path.relative_to(out_dir).as_posix() for path in pages) == [START_PATH]
    data = report(out_dir)
    assert data["run_id"] == 1
    assert data["kind"] == "initial"
    assert data["report_status"] == "finished"
    assert data["exit_code"] == "ok"
    assert data["fetched"] == 1
    assert data["converted"] == 1
    assert data["changes"] == [
        {"kind": "added", "url": SEED, "path": START_PATH, "moved_from": None}
    ]


def test_rule_failure_StartSync_1(tmp_path: Path) -> None:
    """Verify rule StartSync is rejected when requires clause fails.

    requires: directory_exists(out_dir) and exists target.
    """
    fetcher = site()
    assert synced(tmp_path / "nowhere", fetcher) is ExitCode.usage
    assert fetcher.requests == []


def test_rule_failure_StartSync_2(tmp_path: Path) -> None:
    """Verify rule StartSync is rejected when requires clause fails.

    requires: settings.valid and settings.has_seeds and no unblocking provider.
    Re-propagated by T16 (origin T09): each is refused with a refused report naming
    "invalid configuration" (RefuseSyncOnBadConfig, ReportRefusal).
    """
    fetcher = site()
    out_dir = initialised(tmp_path / "out")
    set_key(out_dir, "render_mode", '"sometimes"')
    assert synced(out_dir, fetcher) is ExitCode.usage
    assert fetcher.requests == []
    assert refused(out_dir)["refusal_reason"] == BAD_CONFIG

    no_seeds = initialised(tmp_path / "no-seeds")
    set_key(no_seeds, "start_urls", "[]")
    drop_key(no_seeds, "root_url")
    assert synced(no_seeds, fetcher) is ExitCode.usage
    assert refused(no_seeds)["refusal_reason"] == BAD_CONFIG

    provider = with_provider(initialised(tmp_path / "provider"))
    assert synced(provider, fetcher) is ExitCode.usage
    assert refused(provider)["refusal_reason"] == BAD_CONFIG
    assert fetcher.requests == []


def test_rule_failure_StartSync_3(tmp_path: Path) -> None:
    """Verify rule StartSync is rejected when requires clause fails.

    requires: not settings.root_changed(target.recorded_root_url) or options.confirmed:
    the root recorded by the last run differs and --yes was not passed. Re-propagated by
    T16 (origin T09): the refusal writes a refused report (RefuseSyncOnChangedRoot).
    """
    out_dir = initialised(tmp_path / "out")
    assert synced(out_dir, disallowing()) is ExitCode.ok
    assert load_mirror(out_dir).recorded_root_url == f"{SITE}/guide/"
    set_key(out_dir, "root_url", json.dumps(f"{SITE}/other/"))
    fetcher = disallowing()
    assert synced(out_dir, fetcher) is ExitCode.usage
    assert fetcher.requests == []
    assert refused(out_dir)["refusal_reason"] == CHANGED_ROOT


def test_rule_failure_StartSync_6(tmp_path: Path) -> None:
    """Verify rule StartSync is rejected when requires clause fails.

    requires: a configured browser or stealth tier is installed; tier_installed is
    injected, so the test does not depend on what the machine has. Re-propagated by T16
    (origin T09): ReportRefusal writes the refused report for RefuseMissingEngine too.
    """
    fetcher = site()
    out_dir = initialised(tmp_path / "out")
    set_key(out_dir, "render_mode", '"auto"')
    assert synced(out_dir, fetcher) is ExitCode.usage
    assert refused(out_dir)["refusal_reason"] == MISSING_ENGINE
    stealthy = initialised(tmp_path / "stealthy")
    set_key(stealthy, "stealth_mode", '"on"')
    assert synced(stealthy, fetcher) is ExitCode.usage
    assert refused(stealthy)["refusal_reason"] == MISSING_ENGINE
    assert fetcher.requests == []


def test_rule_failure_StartSync_7(tmp_path: Path) -> None:
    """Verify rule StartSync is rejected when requires clause fails.

    requires: owner_request_problem(...) = null; with no owner test, only robots =
    respect is accepted. Re-propagated by T16 (origin T09): ReportRefusal writes the
    refused report for RefuseInvalidOwnerRequest too, its reason the problem it names.
    """
    fetcher = site()
    out_dir = initialised(tmp_path / "out")
    set_key(out_dir, "robots", '"ignore"')
    assert synced(out_dir, fetcher) is ExitCode.usage
    assert fetcher.requests == []
    reason = refused(out_dir)["refusal_reason"]
    assert isinstance(reason, str)
    assert "robots" in reason


def test_rule_entity_creation_StartSync_1(tmp_path: Path) -> None:
    """Verify entity creation in rule StartSync ensures clause produces the specified fields.

    The mirror takes the profile, the scope, the root URL and the signature; the report
    is created with the run's id, kind, mode, configuration and policy.
    """
    out_dir = initialised(tmp_path / "out")
    assert synced(out_dir, site()) is ExitCode.ok
    settings = resolve_config(out_dir)
    mirror = load_mirror(out_dir)
    scope = scope_of(settings, profiles.GENERIC)
    assert mirror.profile == profiles.GENERIC
    assert mirror.scope == scope
    assert mirror.recorded_root_url == settings.root_url
    assert mirror.processing_signature == signature_of(scope, profiles.GENERIC)

    data = report(out_dir)
    assert data["run_id"] == 1
    assert data["kind"] == "initial"
    assert data["mode"] == "standard"
    assert data["error"] is None
    assert data["refusal_reason"] is None
    configuration = data["configuration"]
    assert isinstance(configuration, dict)
    assert configuration["hash"] == settings.hash
    options = data["options"]
    assert isinstance(options, dict)
    assert options["dry_run"] is False
    assert data["tool_version"] == importlib.metadata.version("rovo")
    assert data["targets"] == []
    assert data["declared_owned_hosts"] == []
    assert data["baseline_run_id"] is None
    assert data["preceding_run_id"] is None
    assert data["requested_owner_test"] is None
    assert isinstance(data["effective_policy"], dict)
    assert data["robots_ignored"] is False
    assert str(data["started_at"]).startswith("2026-10-31T12:00:00")


# --- index: RebuildIndex, RefuseRebuildIndex, FinishIndexCommand (T11) ----------------

INDEX_FILES = ("index.md", "index.jsonl", "links.jsonl", "llms.txt")
# The state files and the report the index command never writes.
STATE_FILES = (".rovo/manifest.json", ".rovo/frontier.json", ".rovo/runs.json")
INDEX_PAGES = ("api/ref.md", "api/v2/x.md", "b.md", "start.md")


def indexes_site(out_dir: Path) -> Path:
    """A mirror synced from the indexes fixture site: four pages, index files written."""
    initialised(out_dir)
    assert synced(out_dir, FakeFetcher(fixture_site("indexes", f"{SITE}/"))) is ExitCode.ok
    return out_dir


def untouched(out_dir: Path) -> dict[str, bytes]:
    """The state files and crawl-report.json, which an index pass never writes."""
    names = (*STATE_FILES, "crawl-report.json")
    return {name: (out_dir / name).read_bytes() for name in names if (out_dir / name).exists()}


def test_rule_success_RebuildIndex(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule RebuildIndex succeeds when all preconditions are met.

    A mirror whose page files are readable gets an index pass: the index files come
    back, and no state file, run or report is written.
    """
    out_dir = indexes_site(tmp_path / "out")
    before = untouched(out_dir)
    assert set(before) == {*STATE_FILES, "crawl-report.json"}
    written = {name: (out_dir / name).read_bytes() for name in INDEX_FILES}
    for name in INDEX_FILES:
        (out_dir / name).unlink()
    capsys.readouterr()
    assert _commands.index(out_dir) is ExitCode.ok
    assert {name: (out_dir / name).read_bytes() for name in INDEX_FILES} == written
    assert untouched(out_dir) == before
    assert capsys.readouterr().err == ""


def test_rule_failure_RebuildIndex_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule RebuildIndex is rejected when requires clause fails.

    requires: exists target and page_files_readable(target): a page file missing, or
    not UTF-8, refuses the pass, names the file and writes no index file.
    """
    out_dir = indexes_site(tmp_path / "out")
    page = out_dir / START_PATH
    for name in INDEX_FILES:
        (out_dir / name).unlink()
    page.unlink()
    capsys.readouterr()
    assert _commands.index(out_dir) is ExitCode.usage
    error = capsys.readouterr().err
    assert error.startswith("rovo: index: ")
    assert START_PATH in error
    assert not any((out_dir / name).exists() for name in INDEX_FILES)

    page.write_bytes(b"---\ntitle: \xff\xfe\n---\n")
    assert _commands.index(out_dir) is ExitCode.usage
    assert capsys.readouterr().err.startswith("rovo: index: ")
    assert not any((out_dir / name).exists() for name in INDEX_FILES)


def test_rule_success_RefuseRebuildIndex(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule RefuseRebuildIndex succeeds when all preconditions are met.

    No mirror: a missing directory, an empty one or an unparsable manifest exits usage,
    says why on standard error and writes nothing.
    """
    missing = tmp_path / "missing"
    assert _commands.index(missing) is ExitCode.usage
    assert capsys.readouterr().err.startswith("rovo: index: ")
    assert not missing.exists()

    empty = tmp_path / "empty"
    empty.mkdir()
    assert _commands.index(empty) is ExitCode.usage
    assert capsys.readouterr().err.startswith("rovo: index: ")
    assert list(empty.iterdir()) == []

    broken = initialised(tmp_path / "broken")
    manifest_path(broken).write_text("{not json", encoding="utf-8")
    before = snapshot(broken)
    assert _commands.index(broken) is ExitCode.usage
    assert capsys.readouterr().err.startswith("rovo: index: ")
    assert snapshot(broken) == before


def test_rule_failure_RefuseRebuildIndex_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule RefuseRebuildIndex is rejected when requires clause fails.

    requires: not exists target or not page_files_readable(target): an initialised
    mirror with no page, and a synced one, are not refused.
    """
    fresh = initialised(tmp_path / "fresh")
    assert _commands.index(fresh) is ExitCode.ok
    assert (fresh / "index.md").is_file()
    synced_dir = indexes_site(tmp_path / "synced")
    capsys.readouterr()
    assert _commands.index(synced_dir) is ExitCode.ok
    assert capsys.readouterr().err == ""


def test_rule_success_FinishIndexCommand(tmp_path: Path) -> None:
    """Verify rule FinishIndexCommand succeeds when all preconditions are met.

    The IndexesWritten of an index pass ends the command with ok.
    """
    out_dir = indexes_site(tmp_path / "out")
    written = index_pass(Operator(), load_mirror(out_dir))
    assert written is not None
    assert written.pass_.kind is PassKind.index
    assert _commands.finish_index_command(written) is ExitCode.ok
    assert _commands.index(out_dir) is ExitCode.ok


def test_rule_failure_FinishIndexCommand_1(tmp_path: Path) -> None:
    """Verify rule FinishIndexCommand is rejected when requires clause fails.

    requires: pass.kind = index: a finalise pass's IndexesWritten ends no command, so a
    sync goes on past the index files to write its report.
    """
    out_dir = indexes_site(tmp_path / "out")
    mirror = load_mirror(out_dir)
    operator = Operator()
    finalise_pass = request_pass(operator, mirror, PassKind.finalise, 1)
    written = IndexesWritten(mirror=mirror, pass_=finalise_pass, operator=operator)
    assert _commands.finish_index_command(written) is None
    for name in INDEX_FILES:
        assert (out_dir / name).is_file(), name
    data = report(out_dir)
    assert data["exit_code"] == "ok"
    assert data["converted"] == len(INDEX_PAGES)


# --- verify: Verify, RefuseVerify, ReportVerification (T17) ---------------------------

# A page whose second code sample names no language: it fails code_lang_rate when the
# sync measures it, so the mirror has a gate tally and no finding.
UNNAMED_CODE_PAGE = PAGE.replace(
    "</main>",
    '<pre><code class="language-python">print("named")</code></pre>'
    "<pre><code>echo unnamed</code></pre></main>",
)
REASONS = {
    "missing_file",
    "unmanaged_file",
    "invalid_page_file",
    "digest_mismatch",
    "quality_drift",
    "broken_link",
    "index_stale",
}


def finding_lines(text: str) -> list[str]:
    """The lines of verify's output that are findings: `<reason> <path> <detail>`."""
    return [line for line in text.splitlines() if line.split(" ", 1)[0] in REASONS]


def test_rule_success_Verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule Verify succeeds when all preconditions are met.

    A mirror with a manifest gets a verify pass: a fresh mirror has no finding, so it
    exits ok and prints no finding, and nothing on disk changes.
    """
    out_dir = indexes_site(tmp_path / "out")
    before = snapshot(out_dir)
    capsys.readouterr()
    assert _commands.verify(out_dir) is ExitCode.ok
    captured = capsys.readouterr()
    assert finding_lines(captured.out) == []
    assert captured.err == ""
    assert snapshot(out_dir) == before


def test_rule_failure_Verify_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule Verify is rejected when requires clause fails.

    requires: exists target and manifest_exists(target): a directory holding page files
    but no manifest gets no verify pass, so no finding is printed and nothing written.
    """
    out_dir = indexes_site(tmp_path / "out")
    manifest_path(out_dir).unlink()
    before = snapshot(out_dir)
    capsys.readouterr()
    assert _commands.verify(out_dir) is ExitCode.usage
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("rovo: verify: ")
    assert snapshot(out_dir) == before


def test_rule_success_RefuseVerify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule RefuseVerify succeeds when all preconditions are met.

    No mirror: a missing directory, an empty one or an unparsable manifest exits usage,
    says why on standard error, prints nothing on standard output and writes nothing.
    """
    missing = tmp_path / "missing"
    assert _commands.verify(missing) is ExitCode.usage
    captured = capsys.readouterr()
    assert captured.err.startswith("rovo: verify: ")
    assert captured.out == ""
    assert not missing.exists()

    empty = tmp_path / "empty"
    empty.mkdir()
    assert _commands.verify(empty) is ExitCode.usage
    assert capsys.readouterr().err.startswith("rovo: verify: ")
    assert list(empty.iterdir()) == []

    broken = initialised(tmp_path / "broken")
    manifest_path(broken).write_text("{not json", encoding="utf-8")
    before = snapshot(broken)
    assert _commands.verify(broken) is ExitCode.usage
    captured = capsys.readouterr()
    assert captured.err.startswith("rovo: verify: ")
    assert captured.out == ""
    assert snapshot(broken) == before


def test_rule_failure_RefuseVerify_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule RefuseVerify is rejected when requires clause fails.

    requires: not exists target or not manifest_exists(target): a mirror with a manifest
    is not refused, even when a page file is unreadable, which is a finding
    (invalid_page_file, quality) rather than a usage error (VerifyIndexReportExitCodes).
    """
    out_dir = indexes_site(tmp_path / "out")
    capsys.readouterr()
    assert _commands.verify(out_dir) is ExitCode.ok
    assert capsys.readouterr().err == ""

    (out_dir / START_PATH).write_bytes(b"---\ntitle: \xff\xfe\n---\n")
    assert _commands.verify(out_dir) is ExitCode.quality
    captured = capsys.readouterr()
    assert captured.err == ""
    assert f"invalid_page_file {START_PATH}" in "\n".join(finding_lines(captured.out))


def test_rule_success_ReportVerification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule ReportVerification succeeds when all preconditions are met.

    VerificationFinished reports each finding as one `<reason> <path> <detail>` line on
    standard output and exits ok with none, quality with any.
    """
    out_dir = indexes_site(tmp_path / "out")
    mirror = load_mirror(out_dir)
    operator = Operator()
    clean = verify_pass(operator, mirror)
    assert clean is not None
    capsys.readouterr()
    assert _commands.report_verification(clean) is ExitCode.ok
    assert finding_lines(capsys.readouterr().out) == []

    failures = (
        VerificationFailure(
            path=START_PATH, reason=VerificationReason.quality_drift, detail="headings"
        ),
        VerificationFailure(path="index.md", reason=VerificationReason.index_stale, detail=""),
    )
    drifted = dataclasses.replace(clean, failures=failures)
    assert _commands.report_verification(drifted) is ExitCode.quality
    lines = finding_lines(capsys.readouterr().out)
    assert len(lines) == len(failures)
    assert lines[0].split(" ")[:3] == ["quality_drift", START_PATH, "headings"]
    assert lines[1].split(" ")[:2] == ["index_stale", "index.md"]


def test_verify_prints_findings_and_gate_tallies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ReportVerification's output: the findings, then `<gate> <pages>` per failed gate.

    The tallies are over the mirror's written pages and never move the exit code: a
    mirror whose one page failed code_lang_rate when measured exits ok with the tally
    alone; with a finding beside it, quality.
    """
    out_dir = initialised(tmp_path / "out")
    fetcher = FakeFetcher({SEED: html_response(SEED, UNNAMED_CODE_PAGE)})
    assert synced(out_dir, fetcher) is ExitCode.ok
    capsys.readouterr()
    assert _commands.verify(out_dir) is ExitCode.ok
    out = capsys.readouterr().out
    assert finding_lines(out) == []
    assert "code_lang_rate 1" in out.splitlines()

    (out_dir / "index.md").write_text("# Edited\n", encoding="utf-8")
    assert _commands.verify(out_dir) is ExitCode.quality
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("index_stale index.md")
    assert "code_lang_rate 1" in lines
    assert lines.index("code_lang_rate 1") > lines.index(finding_lines("\n".join(lines))[-1])


def test_verify_tallies_are_always_printed_sorted_by_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The tallies are printed with no finding too, one line per failed gate, by gate.

    The T17 follow-up (spec 022eca4, ReportVerification guidance, rovo.allium 811 to 817),
    the maintainer's answer to the batched question, item 4: always printed, after the
    findings and whether or not there is any, sorted by gate; never the exit code.
    """
    out_dir = indexes_site(tmp_path / "out")
    mirror = load_mirror(out_dir)
    written = mirror.written_pages
    assert len(written) >= len(("first", "second"))
    failed = (
        frozenset({QualityGate.tables, QualityGate.code_lang_rate}),
        frozenset({QualityGate.headings, QualityGate.tables}),
    )
    for page, gates in zip(written, failed, strict=False):
        page.quality = dataclasses.replace(page.quality, failed=gates)
    clean = verify_pass(Operator(), mirror)
    assert clean is not None
    capsys.readouterr()
    assert _commands.report_verification(dataclasses.replace(clean, failures=())) is ExitCode.ok
    assert capsys.readouterr().out.splitlines() == ["code_lang_rate 1", "headings 1", "tables 2"]

    finding = VerificationFailure(
        path="index.md", reason=VerificationReason.index_stale, detail=""
    )
    drifted = dataclasses.replace(clean, failures=(finding,))
    assert _commands.report_verification(drifted) is ExitCode.quality
    assert capsys.readouterr().out.splitlines() == [
        "index_stale index.md",
        "code_lang_rate 1",
        "headings 1",
        "tables 2",
    ]


# --- sync paces on its timer and reports what failed (T12) ------------------------------


def test_sync_paces_on_its_timer_and_tallies_discovery_problems(tmp_path: Path) -> None:
    """Sync takes a Timer: a refused robots.txt's retries wait on it, never for real.

    Its DiscoveryFailed is tallied before CloseRun: crawl-report.json lists the robots
    URL, the exit is partial, and the report's finish is later than its start by exactly
    the waits the timer was asked for.
    """
    out = initialised(tmp_path / "out")
    fetcher = FakeFetcher(
        {ROBOTS: text_response(ROBOTS, "", status=503), SEED: html_response(SEED, PAGE)}
    )
    timer = SteppingTimer()
    code = _commands.sync(out, fetcher=fetcher, clock=timer, tier_installed=never_installed)
    assert code is ExitCode.partial
    assert fetcher.requests == [ROBOTS] * CRAWL.http_attempts
    waits = [seconds for seconds in timer.sleeps if seconds > 0]
    assert len(waits) == CRAWL.http_attempts - 1
    report = json.loads(report_path(out).read_text(encoding="utf-8"))
    assert report["exit_code"] == "partial"
    assert report["discovery_problems"] == [{"url": ROBOTS, "problem": "robots_refused"}]
    assert report["unresolved_urls"] == [SEED]
    started = datetime.fromisoformat(report["started_at"])
    finished = datetime.fromisoformat(report["finished_at"])
    assert started == START
    assert finished == timer.instant
    assert finished - started == sum((timedelta(seconds=s) for s in timer.sleeps), timedelta(0))


def test_sync_tallies_a_failed_url_before_close_run(tmp_path: Path) -> None:
    """A seed that answers 503 on every try is a failed_urls row and a failed change."""
    out = initialised(tmp_path / "out")
    fetcher = FakeFetcher({SEED: html_response(SEED, "", status=503)})
    assert synced(out, fetcher) is ExitCode.partial
    assert fetcher.requests.count(SEED) == CRAWL.http_attempts
    report = json.loads(report_path(out).read_text(encoding="utf-8"))
    assert report["exit_code"] == "partial"
    (row,) = report["failed_urls"]
    assert row["url"] == SEED
    assert row["attempts"] == CRAWL.http_attempts
    assert row["error"]
    assert report["changes"] == [{"kind": "failed", "url": SEED, "path": None, "moved_from": None}]
    assert report["fetched"] == CRAWL.http_attempts


def file_states(out_dir: Path) -> dict[str, tuple[bytes, int, int]]:
    """Every file outside .rovo/ but the report: its bytes, st_mtime_ns and st_ino."""
    states: dict[str, tuple[bytes, int, int]] = {}
    for path in sorted(out_dir.rglob("*")):
        relative = path.relative_to(out_dir)
        if not path.is_file() or relative.parts[0] == ".rovo" or path == report_path(out_dir):
            continue
        status = path.stat()
        states[relative.as_posix()] = (path.read_bytes(), status.st_mtime_ns, status.st_ino)
    return states


def test_UnchangedRunIsStable_a_second_sync_of_an_unchanged_site_rewrites_nothing(
    tmp_path: Path,
) -> None:
    """mirror.allium UnchangedRunIsStable on unit inputs: two syncs over one FakeFetcher.

    The second sync sends the seed's stored validators (it has none), gets the same raw
    document, keeps the page (its row unchanged) and exits 0; no page file and no index
    file is rewritten: same bytes, st_mtime_ns and st_ino, and no file added.
    """
    out = initialised(tmp_path / "out")
    fetcher = site()
    assert synced(out, fetcher) is ExitCode.ok
    before = file_states(out)
    assert START_PATH in before
    assert {"index.md", "index.jsonl", "links.jsonl", "llms.txt"} <= set(before)
    assert synced(out, fetcher) is ExitCode.ok
    assert fetcher.requests.count(SEED) == len(["first sync", "second sync"])
    assert file_states(out) == before
    frontier = json.loads((out / ".rovo" / "frontier.json").read_text(encoding="utf-8"))
    assert [row["status"] for row in frontier["entries"]] == ["unchanged"]
    second = report(out)
    assert second["exit_code"] == "ok"
    assert (second["converted"], second["skipped_unchanged"]) == (0, 1)
    assert second["changes"] == [
        {"kind": "unchanged", "url": SEED, "path": START_PATH, "moved_from": None}
    ]


FIRST_STAMP = "Sat, 31 Oct 2026 12:00:00 GMT"
SECOND_STAMP = "Sun, 01 Nov 2026 12:00:00 GMT"
VALIDATOR_LINE = re.compile(r"(?m)^(etag|last_modified):")


def test_UnchangedRunIsStable_a_moved_validator_rewrites_no_page_or_index_file(
    tmp_path: Path,
) -> None:
    """mirror.allium UnchangedRunIsStable and PageFileProvenance at a0814ab, unit inputs.

    The seed answers with an ETag and a Last-Modified; on the second sync the same raw
    document comes back with a new ETag and Last-Modified. Neither validator is a line of
    the page file or a key of index.jsonl, so no page or index file is rewritten, and the
    manifest under .rovo/ keeps the new validators.
    """
    out = initialised(tmp_path / "out")
    page = html_response(SEED, PAGE)
    first = dataclasses.replace(page, etag='"v1"', last_modified=FIRST_STAMP)
    fetcher = FakeFetcher({SEED: first})
    assert synced(out, fetcher) is ExitCode.ok
    assert not VALIDATOR_LINE.search((out / START_PATH).read_text(encoding="utf-8"))
    lines = (out / "index.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert rows
    assert all({"etag", "last_modified"}.isdisjoint(row) for row in rows)
    before = file_states(out)
    fetcher.responses[SEED] = dataclasses.replace(page, etag='"v2"', last_modified=SECOND_STAMP)
    assert synced(out, fetcher) is ExitCode.ok
    assert file_states(out) == before
    manifest = json.loads(manifest_path(out).read_text(encoding="utf-8"))
    (stored,) = manifest["pages"]
    assert (stored["etag"], stored["last_modified"]) == ('"v2"', SECOND_STAMP)
    assert report(out)["changes"] == [
        {"kind": "unchanged", "url": SEED, "path": START_PATH, "moved_from": None}
    ]


# --- The page lifecycle (T15) -----------------------------------------------------------

OTHER = f"{SITE}/guide/other.html"
KEEP = f"{SITE}/guide/keep/a.html"
DROP = f"{SITE}/guide/drop/b.html"


def linking(*paths: str) -> str:
    """The fixture page with one link per path appended to its main."""
    links = "".join(f'<p><a href="{path}">{path}</a></p>' for path in paths)
    return PAGE.replace("</main>", f"{links}</main>")


def manifest_page(out_dir: Path, identity: str) -> dict[str, object]:
    """The manifest's record of the page whose identity is `identity`."""
    manifest = json.loads(manifest_path(out_dir).read_text(encoding="utf-8"))
    (record,) = [page for page in manifest["pages"] if page["identity"] == identity]
    assert isinstance(record, dict)
    return record


def removed_rows(out_dir: Path) -> list[object]:
    """The report's removed changes."""
    changes = report(out_dir)["changes"]
    assert isinstance(changes, list)
    return [row for row in changes if row["kind"] == "removed"]


def test_sync_removes_and_archives_a_page_that_answers_404(tmp_path: Path) -> None:
    """Two syncs over a FakeFetcher: a page that answers 404 is removed and archived.

    RemoveAbsentPage at intake, its file archived by the finalise pass at
    _removed/<host>/<relative path>, and TallyRemoval's one removed row; the sync exits 0.
    """
    out = initialised(tmp_path / "out")
    other_path = "pages/docs.example/other.md"
    fetcher = FakeFetcher(
        {SEED: html_response(SEED, linking("other.html")), OTHER: html_response(OTHER, PAGE)}
    )
    assert synced(out, fetcher) is ExitCode.ok
    published = (out / other_path).read_bytes()
    del fetcher.responses[OTHER]
    assert synced(out, fetcher) is ExitCode.ok
    record = manifest_page(out, OTHER)
    assert (record["status"], record["removal_reason"]) == ("removed", "absent")
    assert record["path"] == other_path
    assert not (out / other_path).exists()
    assert (out / "_removed" / "docs.example" / "other.md").read_bytes() == published
    assert removed_rows(out) == [
        {"kind": "removed", "url": OTHER, "path": other_path, "moved_from": None}
    ]
    assert report(out)["exit_code"] == "ok"
    frontier = json.loads((out / ".rovo" / "frontier.json").read_text(encoding="utf-8"))
    rows = {row["identity"]: row["status"] for row in frontier["entries"]}
    assert rows[OTHER] == "absent"


def test_sync_retires_a_page_a_narrowed_scope_no_longer_admits(tmp_path: Path) -> None:
    """RetireOutOfScopePages through two syncs: path_prefixes narrows to /guide/keep/.

    The second sync never requests DROP, retires it out_of_scope at finalisation,
    archives its file, removes the emptied directory and reports one removed row; the
    seed and KEEP stay written.
    """
    out = initialised(tmp_path / "out")
    fetcher = FakeFetcher(
        {
            SEED: html_response(SEED, linking("keep/a.html", "drop/b.html")),
            KEEP: html_response(KEEP, PAGE),
            DROP: html_response(DROP, PAGE),
        }
    )
    assert synced(out, fetcher) is ExitCode.ok
    drop_path = "pages/docs.example/drop/b.md"
    published = (out / drop_path).read_bytes()
    set_key(out, "path_prefixes", '["/guide/keep/"]')
    before = len(fetcher.requests)
    assert synced(out, fetcher) is ExitCode.ok
    assert DROP not in fetcher.requests[before:]
    record = manifest_page(out, DROP)
    assert (record["status"], record["removal_reason"]) == ("removed", "out_of_scope")
    assert not (out / "pages" / "docs.example" / "drop").exists()
    assert (out / "_removed" / "docs.example" / "drop" / "b.md").read_bytes() == published
    assert removed_rows(out) == [
        {"kind": "removed", "url": DROP, "path": drop_path, "moved_from": None}
    ]
    assert manifest_page(out, SEED)["status"] == "written"
    assert manifest_page(out, KEEP)["status"] == "written"


# --- T16: SyncOptions -------------------------------------------------------------------

OTHER_PATH = "pages/docs.example/other.md"
MISSING_PATH = "pages/docs.example/missing.md"
OFF_HOST_URL = "http://elsewhere.invalid/x.html"
NOT_HTTP_URL = "ftp://docs.example/guide/x.html"
# An on-host URL outside the path prefixes: a named URL waives them (RefuseOffHostTarget).
ON_HOST_OUTSIDE = f"{SITE}/outside/x.html"


def first_synced(out_dir: Path) -> Path:
    """A mirror synced once over the fixture site: START_PATH written, the root recorded."""
    initialised(out_dir)
    assert synced(out_dir, site()) is ExitCode.ok
    return out_dir


def state_files(out_dir: Path) -> dict[str, bytes]:
    """Every file under .rovo/, which a refusal never writes."""
    return {
        str(path.relative_to(out_dir)): path.read_bytes()
        for path in sorted((out_dir / ".rovo").rglob("*"))
        if path.is_file()
    }


def requesting(  # noqa: PLR0913  One keyword per sync option a test varies.
    out_dir: Path,
    fetcher: FakeFetcher,
    *,
    confirmed: bool = False,
    urls: tuple[str, ...] = (),
    paths: tuple[str, ...] = (),
    installed: bool = False,
) -> ExitCode:
    """One rovo sync with the named options; `installed` installs every engine."""
    return _commands.sync(
        out_dir,
        fetcher=fetcher,
        clock=FixedClock(),
        tier_installed=(lambda tier: tier is not Tier.http) if installed else never_installed,
        confirmed=confirmed,
        urls=urls,
        paths=paths,
    )


def target_runs(
    out_dir: Path,
    *,
    urls: tuple[str, ...] = (),
    paths: tuple[str, ...] = (),
    expected: tuple[str, ...] = (),
) -> FakeFetcher:
    """A sync naming targets that pass the refusals runs the targeted run (9a253a4).

    It exits ok as run 2, requests robots.txt and the `expected` targets alone (no
    discovery walk), and its report lists the targets and records the options as
    targeted; runs.json gains the run. Re-propagated by the T16 follow-up (origin T16
    tick 4, target_stops: the targeted run was a later slice's, so the sync stopped at
    PrepareRun's raise with nothing requested or written).
    """
    fetcher = site()
    assert requesting(out_dir, fetcher, urls=urls, paths=paths) is ExitCode.ok
    assert sorted(fetcher.requests) == sorted([ROBOTS, *expected])
    data = report(out_dir)
    assert (data["report_status"], data["run_id"]) == ("finished", len(["first", "targeted"]))
    assert data["targets"] == sorted(expected)
    options = data["options"]
    assert isinstance(options, dict)
    assert options["targeted"] is True
    runs = json.loads((out_dir / ".rovo" / "runs.json").read_text(encoding="utf-8"))["runs"]
    assert [row["id"] for row in runs] == [1, len(["first", "targeted"])]
    return fetcher


def root_changed(out_dir: Path) -> Path:
    """The synced mirror's rovo.toml names another root URL than the one recorded."""
    set_key(out_dir, "root_url", json.dumps(f"{SITE}/other/"))
    return out_dir


def test_value_equality_SyncOptions() -> None:
    """Verify value type SyncOptions has structural equality."""
    options = SyncOptions(
        dry_run=False,
        confirmed=True,
        interactive=False,
        json_events=True,
        urls=(SEED,),
        paths=(START_PATH,),
    )
    same = SyncOptions(
        dry_run=False,
        confirmed=True,
        interactive=False,
        json_events=True,
        urls=(SEED,),
        paths=(START_PATH,),
    )
    assert options == same
    assert hash(options) == hash(same)
    assert options != dataclasses.replace(options, confirmed=False)
    assert options != dataclasses.replace(options, urls=())


def test_entity_fields_SyncOptions(tmp_path: Path) -> None:
    """Verify all declared fields on SyncOptions are present with correct types.

    The fields and the derived targeted and is_owner_testing; a sync records confirmed
    (--yes), json_events (--json), urls (--url) and paths (--path) as asked, here in the
    refused report of a sync named an unknown path.
    """
    options = SyncOptions(
        dry_run=True,
        confirmed=True,
        interactive=False,
        json_events=False,
        urls=(SEED,),
        paths=(),
    )
    assert options.dry_run is True
    assert options.confirmed is True
    assert options.interactive is False
    assert options.json_events is False
    assert options.urls == (SEED,)
    assert options.paths == ()
    assert options.owner_test is None
    assert options.targeted is True
    assert options.is_owner_testing is False
    assert dataclasses.replace(options, urls=()).targeted is False

    out_dir = first_synced(tmp_path / "out")
    code = requesting(out_dir, site(), confirmed=True, urls=(SEED,), paths=(MISSING_PATH,))
    assert code is ExitCode.usage
    recorded = refused(out_dir)["options"]
    assert isinstance(recorded, dict)
    assert recorded["confirmed"] is True
    assert recorded["json_events"] is False
    assert recorded["urls"] == [SEED]
    assert recorded["paths"] == [MISSING_PATH]
    assert recorded["targeted"] is True


# --- T16: the refusals, in order --------------------------------------------------------


def test_rule_success_RefuseSyncOnBadConfig(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify rule RefuseSyncOnBadConfig succeeds when all preconditions are met.

    An invalid configuration (a bad value from rovo.toml, from a ROVO_ variable or from
    --set), no seeds, or an unblocking provider: refused "invalid configuration", no
    request, the refused report's configuration naming the bad key, .rovo/ untouched.
    """
    fetcher = site()
    out_dir = initialised(tmp_path / "out")
    before = state_files(out_dir)
    set_key(out_dir, "max_depth", '"deep"')
    assert synced(out_dir, fetcher) is ExitCode.usage
    data = refused(out_dir)
    assert data["refusal_reason"] == BAD_CONFIG
    assert data["kind"] == "initial"
    configuration = data["configuration"]
    assert isinstance(configuration, dict)
    assert configuration["valid"] is False
    assert any("scope.max_depth" in str(problem) for problem in configuration["problems"])
    assert state_files(out_dir) == before

    variable = initialised(tmp_path / "variable")
    monkeypatch.setenv("ROVO_SCOPE__MAX_DEPTH", "deep")
    assert synced(variable, fetcher) is ExitCode.usage
    assert refused(variable)["refusal_reason"] == BAD_CONFIG
    monkeypatch.delenv("ROVO_SCOPE__MAX_DEPTH")

    flagged = initialised(tmp_path / "flagged")
    code = _commands.sync(
        flagged,
        fetcher=fetcher,
        clock=FixedClock(),
        tier_installed=never_installed,
        overrides=("scope.max_depth=deep",),
    )
    assert code is ExitCode.usage
    assert refused(flagged)["refusal_reason"] == BAD_CONFIG

    provider = with_provider(initialised(tmp_path / "provider"))
    assert synced(provider, fetcher) is ExitCode.usage
    assert refused(provider)["refusal_reason"] == BAD_CONFIG
    assert fetcher.requests == []


def test_rule_failure_RefuseSyncOnBadConfig_1(tmp_path: Path) -> None:
    """Verify rule RefuseSyncOnBadConfig is rejected when requires clause fails.

    requires: directory_exists(out_dir) and exists target: a directory holding only a bad
    rovo.toml has no mirror, so RefuseSyncWithoutDirectory exits usage and no report is
    written.
    """
    fetcher = site()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "rovo.toml").write_text('[scope]\nmax_depth = "deep"\n', encoding="utf-8")
    assert synced(out_dir, fetcher) is ExitCode.usage
    assert not report_path(out_dir).exists()
    assert fetcher.requests == []


def test_rule_failure_RefuseSyncOnBadConfig_2(tmp_path: Path) -> None:
    """Verify rule RefuseSyncOnBadConfig is rejected when requires clause fails.

    requires: not settings.valid or not has_seeds or an unblocking provider: a valid
    configuration with seeds and no provider is not refused; the run's report is no
    refusal.
    """
    out_dir = initialised(tmp_path / "out")
    assert synced(out_dir, site()) is ExitCode.ok
    data = report(out_dir)
    assert data["report_status"] == "finished"
    assert data["refusal_reason"] is None


def test_rule_success_RefuseSyncOnChangedRoot(tmp_path: Path) -> None:
    """Verify rule RefuseSyncOnChangedRoot succeeds when all preconditions are met.

    The root URL differs from the one recorded and --yes was not passed: refused
    "changed root requires confirmation", no request, .rovo/ untouched, kind update.
    """
    out_dir = root_changed(first_synced(tmp_path / "out"))
    before = state_files(out_dir)
    fetcher = site()
    assert synced(out_dir, fetcher) is ExitCode.usage
    data = refused(out_dir)
    assert data["refusal_reason"] == CHANGED_ROOT
    assert data["kind"] == "update"
    assert fetcher.requests == []
    assert state_files(out_dir) == before


def test_rule_failure_RefuseSyncOnChangedRoot_1(tmp_path: Path) -> None:
    """Verify rule RefuseSyncOnChangedRoot is rejected when requires clause fails.

    requires: directory_exists(out_dir) and exists target: no directory, no report.
    """
    missing = tmp_path / "missing"
    assert requesting(missing, site(), confirmed=False) is ExitCode.usage
    assert not missing.exists()


def test_rule_failure_RefuseSyncOnChangedRoot_2(tmp_path: Path) -> None:
    """Verify rule RefuseSyncOnChangedRoot is rejected when requires clause fails.

    requires: settings valid, with seeds and no provider: a bad configuration with a
    changed root is refused for the configuration, the earlier refusal.
    """
    out_dir = root_changed(first_synced(tmp_path / "out"))
    set_key(out_dir, "max_depth", '"deep"')
    assert synced(out_dir, site()) is ExitCode.usage
    assert refused(out_dir)["refusal_reason"] == BAD_CONFIG


def test_rule_failure_RefuseSyncOnChangedRoot_3(tmp_path: Path) -> None:
    """Verify rule RefuseSyncOnChangedRoot is rejected when requires clause fails.

    requires: settings.root_changed(recorded) and not options.confirmed: with --yes the
    changed root is accepted, the run starts and records the new root.
    """
    out_dir = root_changed(first_synced(tmp_path / "out"))
    set_key(out_dir, "path_prefixes", '["/guide/", "/other/"]')
    assert requesting(out_dir, site(), confirmed=True) is ExitCode.ok
    data = report(out_dir)
    assert data["report_status"] == "finished"
    assert data["run_id"] == len(["first", "confirmed"])
    assert load_mirror(out_dir).recorded_root_url == f"{SITE}/other/"


def test_rule_success_RefuseOffHostTarget(tmp_path: Path) -> None:
    """Verify rule RefuseOffHostTarget succeeds when all preconditions are met.

    A named URL that is not http(s), or not on an allowed host: refused "invalid or
    off-host target", no request, .rovo/ untouched, the options as asked.
    """
    out_dir = first_synced(tmp_path / "out")
    before = state_files(out_dir)
    fetcher = site()
    for url in (OFF_HOST_URL, NOT_HTTP_URL):
        assert requesting(out_dir, fetcher, urls=(SEED, url)) is ExitCode.usage
        data = refused(out_dir)
        assert data["refusal_reason"] == OFF_HOST
        options = data["options"]
        assert isinstance(options, dict)
        assert options["urls"] == sorted([SEED, url])
    assert fetcher.requests == []
    assert state_files(out_dir) == before


def test_rule_failure_RefuseOffHostTarget_1(tmp_path: Path) -> None:
    """Verify rule RefuseOffHostTarget is rejected when requires clause fails.

    requires: directory_exists(out_dir) and exists target: no directory, no report.
    """
    missing = tmp_path / "missing"
    assert requesting(missing, site(), urls=(OFF_HOST_URL,)) is ExitCode.usage
    assert not missing.exists()


def test_rule_failure_RefuseOffHostTarget_2(tmp_path: Path) -> None:
    """Verify rule RefuseOffHostTarget is rejected when requires clause fails.

    requires: settings valid, with seeds and no provider: refused for the configuration.
    """
    out_dir = with_provider(first_synced(tmp_path / "out"))
    assert requesting(out_dir, site(), urls=(OFF_HOST_URL,)) is ExitCode.usage
    assert refused(out_dir)["refusal_reason"] == BAD_CONFIG


def test_rule_failure_RefuseOffHostTarget_3(tmp_path: Path) -> None:
    """Verify rule RefuseOffHostTarget is rejected when requires clause fails.

    requires: not root_changed or options.confirmed: a changed root without --yes is
    refused for the root, the earlier refusal.
    """
    out_dir = root_changed(first_synced(tmp_path / "out"))
    assert requesting(out_dir, site(), urls=(OFF_HOST_URL,)) is ExitCode.usage
    assert refused(out_dir)["refusal_reason"] == CHANGED_ROOT


def test_rule_failure_RefuseOffHostTarget_4(tmp_path: Path) -> None:
    """Verify rule RefuseOffHostTarget is rejected when requires clause fails.

    requires: some named URL is not http(s) on an allowed host: every URL here is, one of
    them outside the path prefixes, which a named URL waives. The sync is not refused:
    StartSync hands the targets to the run, which fetches them alone. Re-propagated by
    T16 tick 3 (weed tick 2: the targets were dropped) and by the T16 follow-up (origin
    T16 tick 4: the targeted run stopped at PrepareRun; 9a253a4 runs it).
    """
    out_dir = first_synced(tmp_path / "out")
    target_runs(out_dir, urls=(SEED, ON_HOST_OUTSIDE), expected=(SEED, ON_HOST_OUTSIDE))


def test_a_url_on_the_first_seeds_host_is_allowed_when_allowed_hosts_is_empty(
    tmp_path: Path,
) -> None:
    """RefuseOffHostTarget and StartSync read the resolved scope's hosts (9a253a4).

    rovo.toml leaves allowed_hosts out, so the scope's allowed hosts are the first
    seed's (scope_of): a --url on that host is not refused and runs the targeted run; a
    --url on another host is still refused "invalid or off-host target", no request made.
    """
    out_dir = first_synced(tmp_path / "out")
    drop_key(out_dir, "allowed_hosts")
    assert resolve_config(out_dir).allowed_hosts == frozenset()
    fetcher = site()
    assert requesting(out_dir, fetcher, urls=(OFF_HOST_URL,)) is ExitCode.usage
    assert refused(out_dir)["refusal_reason"] == OFF_HOST
    assert fetcher.requests == []
    target_runs(out_dir, urls=(SEED,), expected=(SEED,))


def test_a_path_named_with_allowed_hosts_empty_is_not_refused_as_off_host(
    tmp_path: Path,
) -> None:
    """The later guards read the same resolved hosts: a --url and a --path together.

    With allowed_hosts left out, a --url on the first seed's host passes
    RefuseOffHostTarget, and RefuseUnknownTargetPath then judges the --path alone: an
    unknown path is refused "unknown target path", not "invalid or off-host target".
    """
    out_dir = first_synced(tmp_path / "out")
    drop_key(out_dir, "allowed_hosts")
    code = requesting(out_dir, site(), urls=(SEED,), paths=(MISSING_PATH,))
    assert code is ExitCode.usage
    assert refused(out_dir)["refusal_reason"] == UNKNOWN_PATH


def test_rule_success_RefuseUnknownTargetPath(tmp_path: Path) -> None:
    """Verify rule RefuseUnknownTargetPath succeeds when all preconditions are met.

    A named path that is no written page's mirror-relative path, a removed page's path
    included: refused "unknown target path", no request, .rovo/ untouched.
    """
    out_dir = initialised(tmp_path / "out")
    fetcher = FakeFetcher(
        {SEED: html_response(SEED, linking("other.html")), OTHER: html_response(OTHER, PAGE)}
    )
    assert synced(out_dir, fetcher) is ExitCode.ok
    del fetcher.responses[OTHER]
    assert synced(out_dir, fetcher) is ExitCode.ok
    assert manifest_page(out_dir, OTHER)["status"] == "removed"
    before = state_files(out_dir)
    asked = len(fetcher.requests)
    for path in (MISSING_PATH, OTHER_PATH, "start.md"):
        assert requesting(out_dir, fetcher, paths=(START_PATH, path)) is ExitCode.usage
        assert refused(out_dir)["refusal_reason"] == UNKNOWN_PATH
    assert len(fetcher.requests) == asked
    assert state_files(out_dir) == before


def test_rule_failure_RefuseUnknownTargetPath_1(tmp_path: Path) -> None:
    """Verify rule RefuseUnknownTargetPath is rejected when requires clause fails.

    requires: directory_exists(out_dir) and exists target: no directory, no report.
    """
    missing = tmp_path / "missing"
    assert requesting(missing, site(), paths=(MISSING_PATH,)) is ExitCode.usage
    assert not missing.exists()


def test_rule_failure_RefuseUnknownTargetPath_2(tmp_path: Path) -> None:
    """Verify rule RefuseUnknownTargetPath is rejected when requires clause fails.

    requires: settings valid, with seeds and no provider: refused for the configuration.
    """
    out_dir = first_synced(tmp_path / "out")
    set_key(out_dir, "max_depth", '"deep"')
    assert requesting(out_dir, site(), paths=(MISSING_PATH,)) is ExitCode.usage
    assert refused(out_dir)["refusal_reason"] == BAD_CONFIG


def test_rule_failure_RefuseUnknownTargetPath_3(tmp_path: Path) -> None:
    """Verify rule RefuseUnknownTargetPath is rejected when requires clause fails.

    requires: not root_changed or options.confirmed: refused for the changed root.
    """
    out_dir = root_changed(first_synced(tmp_path / "out"))
    assert requesting(out_dir, site(), paths=(MISSING_PATH,)) is ExitCode.usage
    assert refused(out_dir)["refusal_reason"] == CHANGED_ROOT


def test_rule_failure_RefuseUnknownTargetPath_4(tmp_path: Path) -> None:
    """Verify rule RefuseUnknownTargetPath is rejected when requires clause fails.

    requires: every named URL is http(s) on an allowed host: an off-host URL is refused
    for the URL, the earlier refusal.
    """
    out_dir = first_synced(tmp_path / "out")
    code = requesting(out_dir, site(), urls=(OFF_HOST_URL,), paths=(MISSING_PATH,))
    assert code is ExitCode.usage
    assert refused(out_dir)["refusal_reason"] == OFF_HOST


def test_rule_failure_RefuseUnknownTargetPath_5(tmp_path: Path) -> None:
    """Verify rule RefuseUnknownTargetPath is rejected when requires clause fails.

    requires: some named path is not a written page's path: START_PATH is one, so the
    sync is not refused; the targeted run fetches the page that holds it, the seed.
    Re-propagated by T16 tick 3 (weed tick 2: the targets were dropped) and by the T16
    follow-up (origin T16 tick 4: the targeted run stopped at PrepareRun; 9a253a4 runs it).
    """
    out_dir = first_synced(tmp_path / "out")
    target_runs(out_dir, paths=(START_PATH,), expected=(SEED,))


def test_rule_failure_StartSync_4(tmp_path: Path) -> None:
    """Verify rule StartSync is rejected when requires clause fails.

    requires: options.urls.all(u => is_http_url(u) and hostname_of(u) in allowed_hosts):
    an off-host URL starts no run, makes no request and records no run.
    """
    out_dir = first_synced(tmp_path / "out")
    runs = (out_dir / ".rovo" / "runs.json").read_bytes()
    fetcher = site()
    assert requesting(out_dir, fetcher, urls=(OFF_HOST_URL,)) is ExitCode.usage
    assert fetcher.requests == []
    assert (out_dir / ".rovo" / "runs.json").read_bytes() == runs
    assert refused(out_dir)["refusal_reason"] == OFF_HOST


def test_rule_failure_StartSync_5(tmp_path: Path) -> None:
    """Verify rule StartSync is rejected when requires clause fails.

    requires: options.paths.all(p => p in target.page_paths): an unknown path starts no
    run, makes no request and records no run.
    """
    out_dir = first_synced(tmp_path / "out")
    runs = (out_dir / ".rovo" / "runs.json").read_bytes()
    fetcher = site()
    assert requesting(out_dir, fetcher, paths=(MISSING_PATH,)) is ExitCode.usage
    assert fetcher.requests == []
    assert (out_dir / ".rovo" / "runs.json").read_bytes() == runs
    assert refused(out_dir)["refusal_reason"] == UNKNOWN_PATH


@pytest.mark.parametrize(
    ("problems", "reason"),
    [
        pytest.param(("bad-config", "changed-root"), BAD_CONFIG, id="config-before-root"),
        pytest.param(("changed-root", "off-host"), CHANGED_ROOT, id="root-before-url"),
        pytest.param(("off-host", "unknown-path"), OFF_HOST, id="url-before-path"),
        pytest.param(("unknown-path", "no-engine"), UNKNOWN_PATH, id="path-before-engine"),
        pytest.param(("no-engine", "robots-ignore"), MISSING_ENGINE, id="engine-before-owner"),
    ],
)
def test_RefusalsInOrder_a_sync_is_refused_once_for_its_first_problem(
    tmp_path: Path, problems: tuple[str, str], reason: str
) -> None:
    """rovo.allium RefusalsInOrder: each adjacent pair of refusals, both problems at once.

    The sync is refused for the first, makes no request and leaves .rovo/ untouched.
    """
    out_dir = first_synced(tmp_path / "out")
    urls: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    for problem in problems:
        if problem == "bad-config":
            set_key(out_dir, "max_depth", '"deep"')
        elif problem == "changed-root":
            root_changed(out_dir)
        elif problem == "off-host":
            urls = (OFF_HOST_URL,)
        elif problem == "unknown-path":
            paths = (MISSING_PATH,)
        elif problem == "no-engine":
            set_key(out_dir, "render_mode", '"auto"')
        else:
            set_key(out_dir, "robots", '"ignore"')
    before = state_files(out_dir)
    fetcher = site()
    assert requesting(out_dir, fetcher, urls=urls, paths=paths) is ExitCode.usage
    assert refused(out_dir)["refusal_reason"] == reason
    assert fetcher.requests == []
    assert state_files(out_dir) == before


def test_RefusalsInOrder_no_directory_comes_first_and_writes_no_report(tmp_path: Path) -> None:
    """RefuseSyncWithoutDirectory before RefuseSyncOnBadConfig: no manifest, no report."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "rovo.toml").write_text('[unblocking]\nprovider = "paid"\n', encoding="utf-8")
    fetcher = site()
    assert requesting(out_dir, fetcher, urls=(OFF_HOST_URL,)) is ExitCode.usage
    assert not report_path(out_dir).exists()
    assert fetcher.requests == []


# --- T16: interrupts and crashes ----------------------------------------------------------

THIRD = f"{SITE}/guide/third.html"


def two_link_site() -> FakeFetcher:
    """The seed linking other.html and third.html, both pages."""
    return FakeFetcher(
        {
            SEED: html_response(SEED, linking("other.html", "third.html")),
            OTHER: html_response(OTHER, PAGE),
            THIRD: html_response(THIRD, PAGE),
        }
    )


def raising_sync(out_dir: Path, fetcher: RaisingFetcher) -> ExitCode:
    """One sync over `fetcher`; an operator interrupt escaping the sync fails the test."""
    try:
        return _commands.sync(
            out_dir, fetcher=fetcher, clock=FixedClock(), tier_installed=never_installed
        )
    except KeyboardInterrupt:
        pytest.fail("the operator interrupt escaped the sync")


def frontier_rows(out_dir: Path) -> dict[str, str]:
    """frontier.json's status by identity."""
    frontier = json.loads((out_dir / ".rovo" / "frontier.json").read_text(encoding="utf-8"))
    return {row["identity"]: row["status"] for row in frontier["entries"]}


def ended_run(tmp_path: Path) -> tuple[Run, CrawlReport]:
    """A finished run of the fixture site and the open report StartSync made for it."""
    run, frontier = started(tmp_path)
    assert finish_run(run, frontier)
    assert end_run(run, FixedClock())
    return run, opened(run)


def test_rule_success_InterruptSync(tmp_path: Path) -> None:
    """Verify rule InterruptSync succeeds when all preconditions are met.

    A running run of the mirror: interrupt_requested becomes true. Through the command,
    an operator interrupt (KeyboardInterrupt) during a fetch ends the run interrupted:
    exit partial, a report with report_status interrupted and no error, the stored seed
    published, the interrupted row back to pending.
    """
    run, _ = started(tmp_path / "unit")
    assert interrupt_sync(run.target, run)
    assert run.interrupt_requested is True
    assert run.error is None

    out_dir = initialised(tmp_path / "out")
    fetcher = RaisingFetcher(two_link_site(), OTHER, KeyboardInterrupt())
    assert raising_sync(out_dir, fetcher) is ExitCode.partial
    assert fetcher.raised == [OTHER]
    data = report(out_dir)
    assert data["report_status"] == "interrupted"
    assert data["error"] is None
    assert data["exit_code"] == "partial"
    assert data["run_id"] == 1
    assert (out_dir / START_PATH).is_file()
    assert frontier_rows(out_dir)[OTHER] == "pending"


def test_rule_failure_InterruptSync_1(tmp_path: Path) -> None:
    """Verify rule InterruptSync is rejected when requires clause fails.

    requires: exists target: no mirror, nothing changes.
    """
    run, _ = started(tmp_path)
    assert not interrupt_sync(None, run)
    assert run.interrupt_requested is False


def test_rule_failure_InterruptSync_2(tmp_path: Path) -> None:
    """Verify rule InterruptSync is rejected when requires clause fails.

    requires: exists run and run.status = running: no run, or one that has ended.
    """
    run, _ = ended_run(tmp_path)
    assert not interrupt_sync(run.target, None)
    assert not interrupt_sync(run.target, run)
    assert run.interrupt_requested is False


def test_rule_success_RecordCrash(tmp_path: Path) -> None:
    """Verify rule RecordCrash succeeds when all preconditions are met.

    A running run: its error is recorded and interrupt_requested becomes true. Through the
    command, an uncaught error during a fetch ends the run interrupted with the error
    text "<ExceptionType>: <message>", exit partial, the stored seed published.
    """
    run, _ = started(tmp_path / "unit")
    assert record_crash(run.target, run, "RuntimeError: boom")
    assert run.error == "RuntimeError: boom"
    assert run.interrupt_requested is True

    out_dir = initialised(tmp_path / "out")
    fetcher = RaisingFetcher(two_link_site(), OTHER, RuntimeError("boom"))
    assert raising_sync(out_dir, fetcher) is ExitCode.partial
    data = report(out_dir)
    assert data["report_status"] == "interrupted"
    assert data["error"] == "RuntimeError: boom"
    assert data["exit_code"] == "partial"
    assert (out_dir / START_PATH).is_file()
    assert frontier_rows(out_dir)[OTHER] == "pending"


class FailingOnce:
    """A progress sink that raises `error` on its first event and records every later one."""

    def __init__(self, error: BaseException) -> None:
        """Raise `error` once, on the first event."""
        self.error: BaseException | None = error
        self.events: list[ProgressEvent] = []

    def __call__(self, event: ProgressEvent) -> None:
        """Raise the error the first time; record the event every later time."""
        if self.error is not None:
            error, self.error = self.error, None
            raise error
        self.events.append(event)


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (BrokenPipeError("pipe closed"), "BrokenPipeError: pipe closed"),
        (KeyboardInterrupt(), None),
    ],
    ids=["crash", "interrupt"],
)
def test_an_error_on_the_start_event_is_recorded_and_the_report_written(
    tmp_path: Path, error: BaseException, text: str | None
) -> None:
    """RecordCrash and InterruptSync from the moment the run exists (ReportOnEveryExit).

    The start event's sink fails (`rovo sync --json | true`) or the operator interrupts
    there, before the frontier is attached: the run still ends interrupted, no request is
    made, crawl-report.json records it (the crash's error text) and done comes last.
    Added by T16 tick 3 (weed tick 2): the error escaped drive_run and left no report.
    """
    out_dir = initialised(tmp_path / "out")
    fetcher = site()
    sink = FailingOnce(error)
    try:
        code = _commands.sync(
            out_dir,
            fetcher=fetcher,
            clock=FixedClock(),
            tier_installed=never_installed,
            json_events=True,
            progress=sink,
        )
    except KeyboardInterrupt:
        pytest.fail("the operator interrupt escaped the sync")
    assert code is ExitCode.partial
    assert fetcher.requests == []
    data = report(out_dir)
    assert (data["run_id"], data["report_status"], data["error"]) == (1, "interrupted", text)
    assert data["exit_code"] == "partial"
    assert [event.event for event in sink.events][-1:] == ["done"]


def test_rule_failure_RecordCrash_1(tmp_path: Path) -> None:
    """Verify rule RecordCrash is rejected when requires clause fails.

    requires: exists target: no mirror, nothing changes.
    """
    run, _ = started(tmp_path)
    assert not record_crash(None, run, "RuntimeError: boom")
    assert run.error is None
    assert run.interrupt_requested is False


def test_rule_failure_RecordCrash_2(tmp_path: Path) -> None:
    """Verify rule RecordCrash is rejected when requires clause fails.

    requires: exists run and run.status = running: no run, or one that has ended.
    """
    run, _ = ended_run(tmp_path)
    assert not record_crash(run.target, None, "RuntimeError: boom")
    assert not record_crash(run.target, run, "RuntimeError: boom")
    assert run.error is None
    assert run.interrupt_requested is False


def test_rule_success_RecordCrashAfterRun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify rule RecordCrashAfterRun succeeds when all preconditions are met.

    No running run, an open report with a run id and its ended run: the report records
    the error and becomes interrupted, and RankAndWriteReport ranks it partial. Through
    the command, an error in the finalise pass leaves that report (exit partial), writes
    no page file, and records the run in runs.json so its id is never reused.
    """
    run, report_open = ended_run(tmp_path / "unit")
    assert record_crash_after_run(run.target, run, report_open, "RuntimeError: late")
    assert report_open.error == "RuntimeError: late"
    assert report_open.report_status is ReportStatus.interrupted
    assert rank_and_write_report(report_open, run, FixedClock()) is ExitCode.partial

    def late(*args: object) -> None:
        del args
        message = "late"
        raise RuntimeError(message)

    out_dir = initialised(tmp_path / "out")
    monkeypatch.setattr(_commands, "finalise", late)
    assert synced(out_dir, site()) is ExitCode.partial
    data = report(out_dir)
    assert data["report_status"] == "interrupted"
    assert data["error"] == "RuntimeError: late"
    assert data["exit_code"] == "partial"
    assert data["run_id"] == 1
    assert not (out_dir / "pages").exists()
    runs = json.loads((out_dir / ".rovo" / "runs.json").read_text(encoding="utf-8"))["runs"]
    assert [row["id"] for row in runs] == [1]
    monkeypatch.undo()
    assert synced(out_dir, site()) is ExitCode.ok
    assert report(out_dir)["run_id"] == len(["crashed", "next"])


def test_rule_failure_RecordCrashAfterRun_1(tmp_path: Path) -> None:
    """Verify rule RecordCrashAfterRun is rejected when requires clause fails.

    requires: exists target: no mirror, the report does not change.
    """
    run, report_open = ended_run(tmp_path)
    assert not record_crash_after_run(None, run, report_open, "RuntimeError: late")
    assert report_open.error is None
    assert report_open.report_status is ReportStatus.finished


def test_rule_failure_RecordCrashAfterRun_2(tmp_path: Path) -> None:
    """Verify rule RecordCrashAfterRun is rejected when requires clause fails.

    requires: not exists a running run of the mirror: a crash during the run is
    RecordCrash's.
    """
    run, _ = started(tmp_path)
    report_open = opened(run)
    assert not record_crash_after_run(run.target, run, report_open, "RuntimeError: late")
    assert report_open.error is None
    assert report_open.report_status is ReportStatus.finished


def test_rule_failure_RecordCrashAfterRun_3(tmp_path: Path) -> None:
    """Verify rule RecordCrashAfterRun is rejected when requires clause fails.

    requires: exists report and report.run_id != null: no open report (written), or one
    with no run id.
    """
    run, report_open = ended_run(tmp_path)
    report_open.status = CrawlReportStatus.written
    assert not record_crash_after_run(run.target, run, report_open, "RuntimeError: late")
    assert report_open.error is None
    no_run = opened(run)
    no_run.run_id = None
    assert not record_crash_after_run(run.target, run, no_run, "RuntimeError: late")
    assert no_run.error is None
    assert not record_crash_after_run(run.target, run, None, "RuntimeError: late")


def test_rule_failure_RecordCrashAfterRun_4(tmp_path: Path) -> None:
    """Verify rule RecordCrashAfterRun is rejected when requires clause fails.

    requires: exists run (Run{target, id: report.run_id}): no run, or another run.
    """
    run, report_open = ended_run(tmp_path)
    assert not record_crash_after_run(run.target, None, report_open, "RuntimeError: late")
    report_open.run_id = run.id + 1
    assert not record_crash_after_run(run.target, run, report_open, "RuntimeError: late")
    assert report_open.error is None
    assert report_open.report_status is ReportStatus.finished


def test_a_later_slices_stop_inside_the_run_still_propagates_with_no_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NotInThisSlice is a development guard, not a crash: it passes every handler.

    The sync stops (exit partial), the previous report stays in place and no run is
    recorded; the guard is not taken for RecordCrash or RecordCrashAfterRun.
    """
    out_dir = first_synced(tmp_path / "out")
    previous = report_path(out_dir).read_bytes()
    runs = (out_dir / ".rovo" / "runs.json").read_bytes()

    def stopped(*args: object) -> None:
        del args
        raise NotInThisSlice(rule="AnyLaterRule")

    monkeypatch.setattr(_commands, "finalise", stopped)
    assert synced(out_dir, site()) is ExitCode.partial
    assert report_path(out_dir).read_bytes() == previous
    assert (out_dir / ".rovo" / "runs.json").read_bytes() == runs


@pytest.mark.parametrize(
    ("error", "status", "error_text"),
    [
        pytest.param(KeyboardInterrupt(), "interrupted", None, id="interrupted"),
        pytest.param(RuntimeError("boom"), "interrupted", "RuntimeError: boom", id="crashed"),
    ],
)
def test_ReportableOutcome_no_fetch_starts_after_an_interrupt_and_the_next_sync_retries(
    tmp_path: Path, error: BaseException, status: str, error_text: str | None
) -> None:
    """crawl.allium ReportableOutcome and NoResume through the command.

    The interrupt or crash on other.html is the last request of the run (no fetch starts
    after it), no row is left in progress, and the next sync, with no resume flag,
    fetches other.html again and finishes.
    """
    out_dir = initialised(tmp_path / "out")
    fetcher = RaisingFetcher(two_link_site(), OTHER, error)
    assert raising_sync(out_dir, fetcher) is ExitCode.partial
    assert fetcher.requests[-1] == OTHER
    assert fetcher.raised == [OTHER]
    data = report(out_dir)
    assert (data["report_status"], data["error"]) == (status, error_text)
    rows = frontier_rows(out_dir)
    assert "in_progress" not in rows.values()
    assert rows[OTHER] == "pending"
    again = two_link_site()
    assert synced(out_dir, again) is ExitCode.ok
    assert OTHER in again.requests
    assert report(out_dir)["report_status"] == "finished"
    assert (out_dir / OTHER_PATH).is_file()


@pytest.mark.parametrize("kind", ["refused", "dry", "interrupted", "crashed", "crashed-after"])
def test_ReportOnEveryExit_every_sync_of_a_mirror_leaves_a_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """rovo.allium ReportOnEveryExit: refused, dry, interrupted, crashed in or after the run.

    Each leaves crawl-report.json with its exit code, run kind, status and, for a crash,
    the error text.
    """
    out_dir = initialised(tmp_path / "out")
    expected: tuple[str, str, str, str | None]
    if kind == "refused":
        set_key(out_dir, "max_depth", '"deep"')
        code = synced(out_dir, site())
        expected = ("usage", "initial", "refused", None)
    elif kind == "dry":
        code = _commands.sync(
            out_dir,
            fetcher=site(),
            clock=FixedClock(),
            tier_installed=never_installed,
            dry_run=True,
        )
        expected = ("ok", "initial", "finished", None)
    elif kind in {"interrupted", "crashed"}:
        error = KeyboardInterrupt() if kind == "interrupted" else RuntimeError("boom")
        code = raising_sync(out_dir, RaisingFetcher(two_link_site(), OTHER, error))
        text = None if kind == "interrupted" else "RuntimeError: boom"
        expected = ("partial", "initial", "interrupted", text)
    else:

        def late(*args: object) -> None:
            del args
            message = "late"
            raise RuntimeError(message)

        monkeypatch.setattr(_commands, "finalise", late)
        code = synced(out_dir, site())
        expected = ("partial", "initial", "interrupted", "RuntimeError: late")
    data = report(out_dir)
    assert code.value == expected[0]
    assert (data["exit_code"], data["kind"], data["report_status"], data["error"]) == expected


# --- T16: progress ------------------------------------------------------------------------


def test_ProgressOnRequest_the_sink_gets_start_page_backoff_and_one_done_last(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """rovo.allium ProgressOnRequest and AnnounceBackoff, live, through the command.

    The seed answers 503 once, then the page: the sink receives start first, a
    host_backoff naming the host with its until, a page event per settled row, and
    exactly one done, last. url is null on every event but page, which names the row's
    URL (9a253a4). Nothing is printed: the sink is the caller's. Re-propagated by the T16
    follow-up (origin T16): the event gains url.
    """
    out_dir = initialised(tmp_path / "out")
    fetcher = ScriptedFetcher(
        {SEED: html_response(SEED, PAGE)},
        {SEED: [html_response(SEED, "", status=SERVICE_UNAVAILABLE)]},
    )
    events: list[ProgressEvent] = []
    capsys.readouterr()
    code = _commands.sync(
        out_dir,
        fetcher=fetcher,
        clock=SteppingTimer(),
        tier_installed=never_installed,
        json_events=True,
        progress=events.append,
    )
    assert code is ExitCode.ok
    kinds = [event.event for event in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "done"
    assert kinds.count("done") == 1
    assert "page" in kinds
    backoffs = [event for event in events if event.event == "host_backoff"]
    assert backoffs
    assert {event.host for event in backoffs} == {"docs.example"}
    assert all(event.until is not None for event in backoffs)
    assert [event.url for event in events if event.event == "page"] == [SEED]
    assert all(event.url is None for event in events if event.event != "page")
    assert capsys.readouterr().out == ""
    options = report(out_dir)["options"]
    assert isinstance(options, dict)
    assert options["json_events"] is True


def test_rule_success_AnnounceStart(tmp_path: Path) -> None:
    """Verify rule AnnounceStart succeeds when all preconditions are met.

    When the run is created: exactly one start event, the first, raised before any
    request, its host, until and url null.
    """
    out_dir = initialised(tmp_path / "out")
    fetcher = site()
    seen: list[tuple[ProgressEvent, int]] = []

    def sink(event: ProgressEvent) -> None:
        seen.append((event, len(fetcher.requests)))

    code = _commands.sync(
        out_dir,
        fetcher=fetcher,
        clock=FixedClock(),
        tier_installed=never_installed,
        json_events=True,
        progress=sink,
    )
    assert code is ExitCode.ok
    start = ProgressEvent(event="start", host=None, until=None, url=None)
    assert seen[0] == (start, 0)
    assert [event for event, _ in seen].count(start) == 1
    assert [event.event for event, _ in seen].count("start") == 1


def test_rule_success_AnnouncePage(tmp_path: Path) -> None:
    """Verify rule AnnouncePage succeeds when all preconditions are met.

    When a LadderWalk settles: one page event per settled row, naming the walk's host and
    the row's URL, until null. The seed links OTHER, which answers 404: two rows settle,
    so two page events, in fetch order; robots.txt, sitemaps and llms.txt raise none.
    """
    out_dir = initialised(tmp_path / "out")
    fetcher = FakeFetcher({SEED: html_response(SEED, linking("other.html"))})
    events: list[ProgressEvent] = []
    code = _commands.sync(
        out_dir,
        fetcher=fetcher,
        clock=FixedClock(),
        tier_installed=never_installed,
        json_events=True,
        progress=events.append,
    )
    assert code is ExitCode.ok
    assert OTHER in fetcher.requests
    assert [event for event in events if event.event == "page"] == [
        ProgressEvent(event="page", host="docs.example", until=None, url=SEED),
        ProgressEvent(event="page", host="docs.example", until=None, url=OTHER),
    ]


def test_ProgressOnRequest_no_sink_prints_nothing_and_a_dry_run_still_lists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without json_events nothing is printed; a dry run's listing stays plain text.

    With a sink, the dry run's events end with its one done event, and its listing is
    still the identities, one a line, on standard output.
    """
    out_dir = initialised(tmp_path / "out")
    capsys.readouterr()
    assert synced(out_dir, site()) is ExitCode.ok
    assert capsys.readouterr().out == ""

    dry = initialised(tmp_path / "dry")
    events: list[ProgressEvent] = []
    capsys.readouterr()
    code = _commands.sync(
        dry,
        fetcher=site(),
        clock=FixedClock(),
        tier_installed=never_installed,
        dry_run=True,
        json_events=True,
        progress=events.append,
    )
    assert code is ExitCode.ok
    assert capsys.readouterr().out == f"{SEED}\n"
    assert [event.event for event in events].count("done") == 1
    assert events[-1].event == "done"


def test_a_refusal_raises_no_progress_event(tmp_path: Path) -> None:
    """A refused sync starts no run: the sink receives nothing, not even done."""
    out_dir = initialised(tmp_path / "out")
    set_key(out_dir, "max_depth", '"deep"')
    events: list[ProgressEvent] = []
    code = _commands.sync(
        out_dir,
        fetcher=site(),
        clock=FixedClock(),
        tier_installed=never_installed,
        json_events=True,
        progress=events.append,
    )
    assert code is ExitCode.usage
    assert events == []


# --- T16: rovo report ---------------------------------------------------------------------


def test_rule_success_ShowReport(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule ShowReport succeeds when all preconditions are met.

    A mirror with a report: its JSON is printed on standard output as written, with a
    final newline, nothing on standard error, exit ok.
    """
    out_dir = first_synced(tmp_path / "out")
    capsys.readouterr()
    assert _commands.report(out_dir) is ExitCode.ok
    printed = capsys.readouterr()
    assert printed.err == ""
    assert printed.out.endswith("\n")
    assert json.loads(printed.out) == report(out_dir)


def test_rule_failure_ShowReport_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule ShowReport is rejected when requires clause fails.

    requires: exists target: a report file in a directory with no manifest is not shown.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    report_path(out_dir).write_text('{"run_id": 1}\n', encoding="utf-8")
    capsys.readouterr()
    assert _commands.report(out_dir) is ExitCode.usage
    assert capsys.readouterr().out == ""


def test_rule_failure_ShowReport_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule ShowReport is rejected when requires clause fails.

    requires: latest_report(target) != null: no report file, or one that is not JSON.
    """
    out_dir = initialised(tmp_path / "out")
    capsys.readouterr()
    assert _commands.report(out_dir) is ExitCode.usage
    assert capsys.readouterr().out == ""
    report_path(out_dir).write_text("{not json", encoding="utf-8")
    assert _commands.report(out_dir) is ExitCode.usage
    assert capsys.readouterr().out == ""


def test_rule_success_RefuseShowReport(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule RefuseShowReport succeeds when all preconditions are met.

    No mirror (no directory, no manifest, an unparsable one) or no readable report: exit
    usage, the problem on standard error, nothing on standard output, nothing written.
    """
    missing = tmp_path / "missing"
    empty = tmp_path / "empty"
    empty.mkdir()
    damaged = first_synced(tmp_path / "damaged")
    manifest_path(damaged).write_text("{not json", encoding="utf-8")
    fresh = initialised(tmp_path / "fresh")
    for out_dir in (missing, empty, damaged, fresh):
        before = snapshot(out_dir) if out_dir.exists() else {}
        capsys.readouterr()
        assert _commands.report(out_dir) is ExitCode.usage, out_dir
        printed = capsys.readouterr()
        assert printed.out == ""
        assert printed.err.startswith("rovo: report: ")
        assert (snapshot(out_dir) if out_dir.exists() else {}) == before
    assert not missing.exists()


def test_rule_failure_RefuseShowReport_1(tmp_path: Path) -> None:
    """Verify rule RefuseShowReport is rejected when requires clause fails.

    requires: not exists target or latest_report(target) = null: a mirror with a report,
    a refused one included, is shown.
    """
    out_dir = first_synced(tmp_path / "out")
    assert _commands.report(out_dir) is ExitCode.ok
    set_key(out_dir, "max_depth", '"deep"')
    assert synced(out_dir, site()) is ExitCode.usage
    assert _commands.report(out_dir) is ExitCode.ok
