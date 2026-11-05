"""End to end: errors and the report (T16).

The refusals in order, each with a refused crawl-report.json and no request; a non-HTML
answer settled skipped_not_html beside a URL that fails on every sync; `rovo report`; an
interrupted and a crashed sync, each with its report; --json progress; and the
environment layer. Each site is generated into tmp_path by this module's own helper:
served first, so its base URL is known, then written, since `http.server` reads each
file per request. The syncs that fetch run `rovo._commands.sync` in process over the
real HttpxFetcher (or a RaisingFetcher around it) on a FixedClock, which never sleeps;
the refusals and `rovo report` run through CliRunner and make no request. robots.txt
declares no Crawl-delay and no sitemap, and there is no llms.txt. A page path strips the
scope prefix /guide/, so <base>guide/x.html is pages/<host>/x.md. Not `test_commands.py`
or `test_report.py`, which the unit suite names.
"""

import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest
from conftest import Answer, SiteServer
from test_init_sync import load, page_root
from typer.testing import CliRunner

from fakes import FixedClock, RaisingFetcher
from rovo import _commands
from rovo._crawl.fetch import HttpxFetcher
from rovo._crawl.model import CONFIG as CRAWL
from rovo._crawl.model import ProgressEvent
from rovo._exit import ExitCode
from rovo._report import event_line
from rovo.cli import app

PAGE_HTML = """<!doctype html>
<html lang="en">
    <head><title>{title} | Example docs</title></head>
    <body>
        <main>
            <h1>{title}</h1>
            <p>{prose}</p>
{links}        </main>
    </body>
</html>
"""
ROBOTS = "User-agent: *\n"
USAGE = 2
PARTIAL = 1
SERVICE_UNAVAILABLE = 503
SERVER_ERROR = 500
OFF_HOST_URL = "http://elsewhere.invalid/x.html"


def write(root: Path, path: str, text: str) -> None:
    """Write one file of a generated site."""
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def page_html(title: str, links: Sequence[str] = ()) -> str:
    """A page: a title, and a main holding an h1, a paragraph and a link per href."""
    anchors = "".join(f'            <p><a href="{href}">{href}</a></p>\n' for href in links)
    prose = f"{title} is described here in a sentence of plain prose."
    return PAGE_HTML.format(title=title, prose=prose, links=anchors)


def served(
    serve_site: SiteServer,
    tmp_path: Path,
    pages: Mapping[str, Sequence[str]],
    *,
    script: Mapping[str, Sequence[Answer]] | None = None,
    always: Mapping[str, Answer] | None = None,
) -> tuple[Path, str]:
    """Serve a generated site: robots.txt and guide/<name>.html linking its hrefs."""
    root = tmp_path / "site"
    root.mkdir()
    base = serve_site(root, script=script, always=always)
    write(root, "robots.txt", ROBOTS)
    for name, links in pages.items():
        write(root, f"guide/{name}.html", page_html(name.title(), links))
    return root, base


def initialised(base: str, tmp_path: Path, name: str = "out") -> Path:
    """`rovo init <base>guide/start.html <tmp>/<name>`, in process."""
    out = tmp_path / name
    assert _commands.init(f"{base}guide/start.html", out) is ExitCode.ok
    return out


def synced(
    out: Path,
    *,
    confirmed: bool = False,
    json_events: bool = False,
    progress: Callable[[ProgressEvent], None] | None = None,
) -> ExitCode:
    """Rovo sync in process over the real HttpxFetcher, on a FixedClock."""
    with HttpxFetcher() as fetcher:
        return _commands.sync(
            out,
            fetcher=fetcher,
            clock=FixedClock(),
            confirmed=confirmed,
            json_events=json_events,
            progress=progress,
        )


def raising_sync(out: Path, url: str, error: BaseException) -> tuple[ExitCode, RaisingFetcher]:
    """One sync whose request for `url` raises `error`; an escaping interrupt fails the test."""
    with HttpxFetcher() as httpx_fetcher:
        fetcher = RaisingFetcher(httpx_fetcher, url, error)
        try:
            code = _commands.sync(out, fetcher=fetcher, clock=FixedClock())
        except KeyboardInterrupt:
            pytest.fail("the operator interrupt escaped the sync")
    return code, fetcher


def report(out: Path) -> dict[str, object]:
    """crawl-report.json."""
    return load(out / "crawl-report.json")


def frontier_status(out: Path, identity: str) -> object:
    """frontier.json's status of the row for `identity`."""
    entries = load(out / ".rovo" / "frontier.json")["entries"]
    assert isinstance(entries, list)
    (row,) = [row for row in entries if row["identity"] == identity]
    return row["status"]


def page_files(out: Path) -> dict[str, bytes]:
    """Every file under pages/ and _removed/, by mirror-relative path."""
    return {
        path.relative_to(out).as_posix(): path.read_bytes()
        for area in ("pages", "_removed")
        for path in sorted((out / area).rglob("*"))
        if path.is_file()
    }


def set_root_url(out: Path, root_url: str) -> None:
    """Replace rovo.toml's root_url line."""
    path = out / "rovo.toml"
    text, count = re.subn(
        r"(?m)^root_url = .*$", f"root_url = {json.dumps(root_url)}", path.read_text("utf-8")
    )
    assert count == 1
    path.write_text(text, encoding="utf-8")


def cli_sync(out: Path, *options: str, env: Mapping[str, str] | None = None) -> int:
    """`rovo sync OUT_DIR [options]` through CliRunner; its exit code."""
    result = CliRunner().invoke(app, ["sync", str(out), *options], env=dict(env or {}))
    return result.exit_code


def test_a_sync_is_refused_once_for_its_first_problem_with_a_report(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """The four refusals in order, each writing a refused report and making no request.

    RefuseSyncOnBadConfig, RefuseSyncOnChangedRoot, RefuseOffHostTarget and
    RefuseUnknownTargetPath. The root URL moves to <base> (still a prefix of the seed).
    A bad ROVO_ variable wins over the changed root; then the root; with --yes, an
    off-host --url; with --yes, an unknown --path. runs.json is unchanged across the
    four, and a confirmed sync then finishes as run 2.
    """
    _, base = served(serve_site, tmp_path, {"start": ()})
    out = initialised(base, tmp_path)
    assert synced(out) is ExitCode.ok
    set_root_url(out, base)
    runs = (out / ".rovo" / "runs.json").read_bytes()
    asked = len(serve_site.paths(base))

    assert cli_sync(out, env={"ROVO_SCOPE__MAX_DEPTH": "deep"}) == USAGE
    data = report(out)
    assert data["report_status"] == "refused"
    assert data["run_id"] is None
    assert data["exit_code"] == "usage"
    assert data["refusal_reason"] == "invalid configuration"
    assert data["effective_policy"] is None
    configuration = data["configuration"]
    assert isinstance(configuration, dict)
    assert any("scope.max_depth" in str(problem) for problem in configuration["problems"])

    assert cli_sync(out) == USAGE
    assert report(out)["refusal_reason"] == "changed root requires confirmation"
    assert cli_sync(out, "--yes", "--url", OFF_HOST_URL) == USAGE
    assert report(out)["refusal_reason"] == "invalid or off-host target"
    missing = f"{page_root(base)}guide/missing.md"
    assert cli_sync(out, "--yes", "--path", missing) == USAGE
    assert report(out)["refusal_reason"] == "unknown target path"

    assert len(serve_site.paths(base)) == asked
    assert (out / ".rovo" / "runs.json").read_bytes() == runs
    assert synced(out, confirmed=True) is ExitCode.ok
    finished = report(out)
    assert finished["report_status"] == "finished"
    assert finished["run_id"] == len(["first", "confirmed"])


def test_a_non_html_answer_is_skipped_and_a_failing_url_is_reported_every_sync(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """DisposeFetch's skipped_not_html branch beside TallyFailedUrl, over two syncs.

    data.txt is served text/plain: its row settles skipped_not_html and no page, failed
    URL or change names it. broken.html answers 500 on every try: one failed_urls row
    with every attempt and one failed change; the first sync exits 1. The second sync
    requests broken.html again (every failed row is re-pended: the specification's
    interim for its open question) and not data.txt, and exits 1 with the same row.
    """
    root, base = served(
        serve_site,
        tmp_path,
        {"start": ("data.txt", "broken.html")},
        always={"/guide/broken.html": Answer(SERVER_ERROR)},
    )
    write(root, "guide/data.txt", "Plain text, not a page.\n")
    out = initialised(base, tmp_path)
    data_url = f"{base}guide/data.txt"
    broken_url = f"{base}guide/broken.html"

    assert synced(out).number == PARTIAL
    assert frontier_status(out, data_url) == "skipped_not_html"
    first = report(out)
    expected_row = {
        "url": broken_url,
        "error": first_error(first),
        "attempts": CRAWL.http_attempts,
    }
    assert first["failed_urls"] == [expected_row]
    changes = first["changes"]
    assert isinstance(changes, list)
    assert [row for row in changes if row["url"] == data_url] == []
    assert [row["kind"] for row in changes if row["url"] == broken_url] == ["failed"]
    assert not any(path.endswith("data.md") for path in page_files(out))

    since = len(serve_site.paths(base))
    assert synced(out).number == PARTIAL
    again = serve_site.paths(base)[since:]
    assert "/guide/broken.html" in again
    assert "/guide/data.txt" not in again
    assert report(out)["failed_urls"] == [expected_row]


def first_error(data: Mapping[str, object]) -> str:
    """The error text of the report's one failed URL."""
    rows = data["failed_urls"]
    assert isinstance(rows, list)
    (row,) = rows
    error = row["error"]
    assert isinstance(error, str)
    assert error
    return error


def test_rovo_report_prints_the_last_report(serve_site: SiteServer, tmp_path: Path) -> None:
    """ShowReport and RefuseShowReport through CliRunner.

    After a sync, `rovo report <out>` exits 0 and prints JSON equal to crawl-report.json;
    on a freshly initialised mirror it exits 2 and prints nothing on standard output.
    """
    _, base = served(serve_site, tmp_path, {"start": ()})
    out = initialised(base, tmp_path)
    assert synced(out) is ExitCode.ok
    shown = CliRunner().invoke(app, ["report", str(out)])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.stdout) == report(out)

    fresh = initialised(base, tmp_path, "fresh")
    refused = CliRunner().invoke(app, ["report", str(fresh)])
    assert refused.exit_code == USAGE
    assert refused.stdout == ""


def test_an_interrupted_sync_publishes_what_it_stored_and_reports(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """InterruptSync, InterruptRun and EndRun; the finalise pass and the report follow.

    The request for b.html raises KeyboardInterrupt: exit 1, report_status interrupted
    with no error, start.md and a.md published, b.html's row pending. The next sync, with
    the plain fetcher, requests b.html, publishes it and finishes.
    """
    _, base = served(serve_site, tmp_path, {"start": ("a.html", "b.html"), "a": (), "b": ()})
    out = initialised(base, tmp_path)
    b_url = f"{base}guide/b.html"
    code, fetcher = raising_sync(out, b_url, KeyboardInterrupt())
    assert code.number == PARTIAL
    assert fetcher.raised == [b_url]
    data = report(out)
    assert (data["report_status"], data["error"]) == ("interrupted", None)
    root = page_root(base)
    assert (out / f"{root}start.md").is_file()
    assert (out / f"{root}a.md").is_file()
    assert not (out / f"{root}b.md").exists()
    assert frontier_status(out, b_url) == "pending"

    since = len(serve_site.paths(base))
    assert synced(out) is ExitCode.ok
    assert "/guide/b.html" in serve_site.paths(base)[since:]
    assert (out / f"{root}b.md").is_file()
    assert report(out)["report_status"] == "finished"


def test_a_crashed_sync_records_the_error_and_reports(
    serve_site: SiteServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RecordCrash during the run, then RecordCrashAfterRun in the finalise pass.

    A RuntimeError on b.html: exit 1, interrupted, error "RuntimeError: boom", a.md
    published. Then, with the finalise pass raising RuntimeError("late"): exit 1, error
    "RuntimeError: late", interrupted, no page file changes, and runs.json holds the run's
    id, so the next sync's run id is one higher.
    """
    _, base = served(serve_site, tmp_path, {"start": ("a.html", "b.html"), "a": (), "b": ()})
    out = initialised(base, tmp_path)
    code, _ = raising_sync(out, f"{base}guide/b.html", RuntimeError("boom"))
    assert code.number == PARTIAL
    data = report(out)
    assert (data["report_status"], data["error"]) == ("interrupted", "RuntimeError: boom")
    assert (out / f"{page_root(base)}a.md").is_file()

    def late(*args: object) -> None:
        del args
        message = "late"
        raise RuntimeError(message)

    before = page_files(out)
    monkeypatch.setattr(_commands, "finalise", late)
    assert synced(out).number == PARTIAL
    crashed = report(out)
    assert (crashed["report_status"], crashed["error"]) == ("interrupted", "RuntimeError: late")
    assert page_files(out) == before
    run_id = crashed["run_id"]
    assert isinstance(run_id, int)
    runs = load(out / ".rovo" / "runs.json")["runs"]
    assert isinstance(runs, list)
    assert run_id in [row["id"] for row in runs]
    monkeypatch.undo()
    synced(out)
    assert report(out)["run_id"] == run_id + 1


def test_json_progress_ends_with_one_done_event(
    serve_site: SiteServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ProgressOnRequest and AnnounceBackoff: flaky.html answers 503 once, then is served.

    The sink receives start first, a host_backoff naming the host, page events and
    exactly one done, last; each event is one JSON line with event, host and until.
    Without a sink nothing is printed on standard output.
    """
    _, base = served(
        serve_site,
        tmp_path,
        {"start": ("flaky.html",), "flaky": ()},
        script={"/guide/flaky.html": [Answer(SERVICE_UNAVAILABLE)]},
    )
    out = initialised(base, tmp_path)
    events: list[ProgressEvent] = []
    capsys.readouterr()
    assert synced(out, json_events=True, progress=events.append) is ExitCode.ok
    kinds = [event.event for event in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "done"
    assert kinds.count("done") == 1
    assert "page" in kinds
    assert "127.0.0.1" in {event.host for event in events if event.event == "host_backoff"}
    for event in events:
        line = event_line(event)
        assert line.rstrip("\n").count("\n") == 0
        assert set(json.loads(line)) == {"event", "host", "until"}
    assert capsys.readouterr().out == ""

    quiet = initialised(base, tmp_path, "quiet")
    assert synced(quiet) is ExitCode.ok
    assert capsys.readouterr().out == ""


def test_rovo_mirror_prune_from_the_environment_deletes_removed_files(
    serve_site: SiteServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The environment layer: ROVO_MIRROR__PRUNE=true over rovo.toml's prune = false.

    gone.html is deleted after the first sync; the second sync, with the variable in the
    environment, removes its page and deletes its file instead of archiving it.
    """
    root, base = served(serve_site, tmp_path, {"start": ("gone.html",), "gone": ()})
    out = initialised(base, tmp_path)
    assert synced(out) is ExitCode.ok
    gone_path = f"{page_root(base)}gone.md"
    assert (out / gone_path).is_file()
    (root / "guide" / "gone.html").unlink()
    monkeypatch.setenv("ROVO_MIRROR__PRUNE", "true")
    assert synced(out) is ExitCode.ok
    pages = load(out / ".rovo" / "manifest.json")["pages"]
    assert isinstance(pages, list)
    (record,) = [page for page in pages if page["identity"] == f"{base}guide/gone.html"]
    assert record["status"] == "removed"
    assert not (out / gone_path).exists()
    assert not (out / "_removed").exists()
