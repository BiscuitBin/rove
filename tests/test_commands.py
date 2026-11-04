"""rovo.allium's command obligations: init, the sync refusal this slice owns, and StartSync.

Each test is named after the obligation id `just plan-spec rovo` emits, dots and hyphens
as underscores, and its docstring quotes the obligation. `rovo._commands.sync` takes a
Fetcher and a Clock; a refused command makes no request and writes no report. Until the
refusals slice, a failed StartSync guard other than the missing mirror exits usage with
no report too (the ticket's Deviation row).
"""

import importlib.metadata
import json
import re
from pathlib import Path

import pytest

from fakes import FakeFetcher, FixedClock, fixture_site, html_response, text_response
from rovo import _commands
from rovo._config import initial_scope, resolve_config, scope_of, signature_of
from rovo._convert import profiles
from rovo._mirror.finalise import request_pass
from rovo._mirror.indexes import index_pass
from rovo._mirror.model import IndexesWritten, Operator, PassKind, Tier
from rovo._mirror.state import load_mirror, manifest_path
from rovo._report import ExitCode, report_path

SITE = "http://docs.example"
SEED = f"{SITE}/guide/start.html"
# The seed page's mirror-relative path (mirror.allium MovePage guidance, at fed9ed8).
START_PATH = "pages/docs.example/start.md"
ROBOTS = f"{SITE}/robots.txt"
SITES = Path(__file__).resolve().parent / "fixtures" / "sites"
PAGE = (SITES / "one-page" / "guide" / "start.html").read_text(encoding="utf-8")
DISALLOW_GUIDE = (SITES / "robots-disallow" / "robots.txt").read_text(encoding="utf-8")


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
    assert fetcher.requests == [ROBOTS, SEED]


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
    """
    fetcher = site()
    out_dir = initialised(tmp_path / "out")
    set_key(out_dir, "render_mode", '"sometimes"')
    assert synced(out_dir, fetcher) is ExitCode.usage
    assert fetcher.requests == []
    assert not report_path(out_dir).exists()

    no_seeds = initialised(tmp_path / "no-seeds")
    set_key(no_seeds, "start_urls", "[]")
    drop_key(no_seeds, "root_url")
    assert synced(no_seeds, fetcher) is ExitCode.usage

    provider = initialised(tmp_path / "provider")
    path = provider / "rovo.toml"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^\[unblocking\]\n(?:#.*\n|\s*\n)*", "", text)
    path.write_text(text + '\n[unblocking]\nprovider = "paid"\n', encoding="utf-8")
    assert synced(provider, fetcher) is ExitCode.usage
    assert fetcher.requests == []


def test_rule_failure_StartSync_3(tmp_path: Path) -> None:
    """Verify rule StartSync is rejected when requires clause fails.

    requires: not settings.root_changed(target.recorded_root_url) or options.confirmed:
    the root recorded by the last run differs, and this slice has no --yes.
    """
    out_dir = initialised(tmp_path / "out")
    assert synced(out_dir, disallowing()) is ExitCode.ok
    assert load_mirror(out_dir).recorded_root_url == f"{SITE}/guide/"
    set_key(out_dir, "root_url", json.dumps(f"{SITE}/other/"))
    fetcher = disallowing()
    assert synced(out_dir, fetcher) is ExitCode.usage
    assert fetcher.requests == []


def test_rule_failure_StartSync_6(tmp_path: Path) -> None:
    """Verify rule StartSync is rejected when requires clause fails.

    requires: a configured browser or stealth tier is installed; tier_installed is
    injected, so the test does not depend on what the machine has.
    """
    fetcher = site()
    out_dir = initialised(tmp_path / "out")
    set_key(out_dir, "render_mode", '"auto"')
    assert synced(out_dir, fetcher) is ExitCode.usage
    stealthy = initialised(tmp_path / "stealthy")
    set_key(stealthy, "stealth_mode", '"on"')
    assert synced(stealthy, fetcher) is ExitCode.usage
    assert fetcher.requests == []


def test_rule_failure_StartSync_7(tmp_path: Path) -> None:
    """Verify rule StartSync is rejected when requires clause fails.

    requires: owner_request_problem(...) = null; with no owner test, only robots =
    respect is accepted.
    """
    fetcher = site()
    out_dir = initialised(tmp_path / "out")
    set_key(out_dir, "robots", '"ignore"')
    assert synced(out_dir, fetcher) is ExitCode.usage
    assert fetcher.requests == []


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
