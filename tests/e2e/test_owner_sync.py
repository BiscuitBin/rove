"""End to end: an owner-testing sync of a served site (T20).

Each scenario runs `rovo init` through CliRunner, then a standard sync, the baseline, in
process: robots.txt disallows the seed, so run 1 finishes with the seed skipped_robots
and unresolved. Owner testing has no command-line spelling (rovo.allium open question
1138), so ownership is saved with `rovo._commands.save_ownership` and the owner sync is
`rovo._commands.sync(owner_test=...)`, over the real HttpxFetcher on a SteppingTimer,
which never sleeps; the requests are read off the server's log. Nothing reads standard
input. Not `test_owner_testing.py`, which the unit suite already names.
"""

import json
from pathlib import Path

import pytest
from conftest import SiteServer
from test_init_sync import load, page_root
from typer.testing import CliRunner

from fakes import SteppingTimer
from rovo import _commands
from rovo._crawl.fetch import Fetcher, HttpxFetcher, Validators
from rovo._crawl.model import OwnerTestOptions, PolitenessControl, ProgressEvent, SiteResponse
from rovo._exit import ExitCode
from rovo._mirror.model import Tier
from rovo.cli import app

SEED_PATH = "/guide/start.html"
HEADING = "# Getting started"
WARNING_WORDS = ("self-declared", "not verified")
PROBES = ("/sitemap.xml", "/sitemap_index.xml", "/llms.txt")
BASELINE = 1
FOLLOW_UP = 2


def never_installed(tier: Tier) -> bool:
    """No engine beyond http is installed."""
    del tier
    return False


def initialised(base: str, out: Path) -> str:
    """Run rovo init on the site's guide/start.html; the host the mirror allows."""
    result = CliRunner().invoke(app, ["init", f"{base}guide/start.html", str(out)])
    assert result.exit_code == 0, result.output
    hosts = load(out / ".rovo" / "manifest.json")["scope"]
    assert isinstance(hosts, dict)
    (host,) = hosts["allowed_hosts"]
    assert isinstance(host, str)
    return host


def sync(out: Path, fetcher: Fetcher, **options: object) -> ExitCode:
    """One rovo sync in process over `fetcher`, on a SteppingTimer."""
    return _commands.sync(
        out,
        fetcher=fetcher,
        clock=SteppingTimer(),
        tier_installed=never_installed,
        **options,  # type: ignore[arg-type]  # The sync's options, by name.
    )


def baseline(serve_site: SiteServer, out: Path) -> tuple[str, str, int]:
    """The site served, rovo init and the baseline standard sync: base, host, its requests."""
    base = serve_site("robots-disallow")
    host = initialised(base, out)
    with HttpxFetcher() as fetcher:
        assert sync(out, fetcher) is ExitCode.ok
    paths = serve_site.paths(base)
    assert SEED_PATH not in paths
    (row,) = runs(out)
    assert row["mode"] == "standard"
    assert row["status"] == "finished"
    assert row["dry_run"] is False
    assert row["unresolved_urls"] == [f"{base}guide/start.html"]
    return base, host, len(paths)


def runs(out: Path) -> list[dict[str, object]]:
    """runs.json's rows."""
    rows = load(out / ".rovo" / "runs.json")["runs"]
    assert isinstance(rows, list)
    return rows


def report(out: Path) -> dict[str, object]:
    """crawl-report.json."""
    return load(out / "crawl-report.json")


def options(host: str) -> OwnerTestOptions:
    """An owner request following the baseline on the served host, robots disabled."""
    return OwnerTestOptions(
        preceding_run_id=BASELINE,
        hosts=frozenset({host}),
        disabled_controls=frozenset({PolitenessControl.robots}),
    )


class WarnedBeforeRequest:
    """A Fetcher that, at its first request, records standard error so far."""

    def __init__(self, fetcher: Fetcher, capsys: pytest.CaptureFixture[str]) -> None:
        """Pass requests to `fetcher`; at the first, read what standard error holds."""
        self.fetcher = fetcher
        self.capsys = capsys
        self.err_before: str | None = None

    def fetch(self, url: str, *, validators: Validators | None = None) -> SiteResponse:
        """Record standard error at the first request, then pass the request on."""
        if self.err_before is None:
            self.err_before = self.capsys.readouterr().err
        return self.fetcher.fetch(url, validators=validators)


def warned(text: str, host: str) -> None:
    """The owner warning: self-declared, not verified, naming the host."""
    for words in WARNING_WORDS:
        assert words in text, words
    assert host in text


def test_an_owner_testing_sync_mirrors_a_page_robots_disallows(
    serve_site: SiteServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An owner-testing sync mirrors what robots.txt kept out, after the warning.

    save_ownership makes no request; the owner sync exits 0, the warning (the
    owner_testing_warning event and standard error) arrives before any request of the
    run, the seed is requested and stored, no sitemap or llms.txt is requested, and the
    report and runs.json record the owner run, its lineage and its relaxed policy, with
    no access contents.
    """
    out = tmp_path / "out"
    base, host, before = baseline(serve_site, out)
    assert _commands.save_ownership(out, [host]) is ExitCode.ok
    assert len(serve_site.paths(base)) == before
    seen_at_warning: list[int] = []
    events: list[ProgressEvent] = []

    def progress(event: ProgressEvent) -> None:
        events.append(event)
        if event.event == "owner_testing_warning":
            seen_at_warning.append(len(serve_site.paths(base)))

    capsys.readouterr()
    with HttpxFetcher() as real:
        probe = WarnedBeforeRequest(real, capsys)
        code = sync(out, probe, owner_test=options(host), json_events=True, progress=progress)
    assert code is ExitCode.ok
    assert seen_at_warning == [before]
    assert probe.err_before is not None
    warned(probe.err_before, host)
    run_paths = serve_site.paths(base)[before:]
    assert SEED_PATH in run_paths
    assert not set(PROBES) & set(run_paths)
    page = out / page_root(base) / "start.md"
    assert HEADING in page.read_text(encoding="utf-8")
    data = report(out)
    assert data["mode"] == "owner_testing"
    assert data["declared_owned_hosts"] == [host]
    assert data["baseline_run_id"] == BASELINE
    assert data["preceding_run_id"] == BASELINE
    requested = data["requested_owner_test"]
    assert isinstance(requested, dict)
    assert requested["hosts"] == [host]
    assert requested["disabled_controls"] == ["robots"]
    assert requested["access"] == []
    assert data["robots_ignored"] is True
    rows = data["per_host"]
    assert isinstance(rows, list)
    (row,) = rows
    assert row["effective_policy"]["robots"] == "ignore"
    assert data["unresolved_urls"] == []
    second = runs(out)[-1]
    assert second["id"] == FOLLOW_UP
    assert second["mode"] == "owner_testing"
    assert second["baseline_run_id"] == BASELINE
    assert second["preceding_run_id"] == BASELINE


def test_an_owner_request_without_a_declaration_is_refused(
    serve_site: SiteServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no saved ownership the owner request exits 2: the warning, no request, no run.

    The refused report is in owner mode with no run id and no policy, naming the missing
    declaration; runs.json gains no row; the server sees nothing after the baseline.
    """
    out = tmp_path / "out"
    base, host, before = baseline(serve_site, out)
    capsys.readouterr()
    with HttpxFetcher() as fetcher:
        assert sync(out, fetcher, owner_test=options(host)) is ExitCode.usage
    warned(capsys.readouterr().err, host)
    data = report(out)
    assert data["report_status"] == "refused"
    assert data["mode"] == "owner_testing"
    assert data["run_id"] is None
    assert data["effective_policy"] is None
    assert "declaration" in str(data["refusal_reason"])
    assert len(runs(out)) == 1
    assert len(serve_site.paths(base)) == before


def test_a_saved_declaration_alone_never_relaxes_a_standard_sync(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """A saved declaration alone relaxes nothing: a standard sync still skips the seed.

    It exits as the baseline did, the seed skipped_robots and never requested, robots
    respected.
    """
    out = tmp_path / "out"
    base, host, before = baseline(serve_site, out)
    assert _commands.save_ownership(out, [host]) is ExitCode.ok
    with HttpxFetcher() as fetcher:
        assert sync(out, fetcher) is ExitCode.ok
    assert SEED_PATH not in serve_site.paths(base)[before:]
    data = report(out)
    assert data["mode"] == "standard"
    assert data["robots_ignored"] is False
    entries = load(out / ".rovo" / "frontier.json")["entries"]
    assert isinstance(entries, list)
    statuses = {row["identity"]: row["status"] for row in entries}
    assert statuses[f"{base}guide/start.html"] == "skipped_robots"
    assert json.loads((out / ".rovo" / "manifest.json").read_text(encoding="utf-8"))[
        "declared_owned_hosts"
    ] == [host]
