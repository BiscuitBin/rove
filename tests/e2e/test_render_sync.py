"""End to end: the browser tier with a fake engine (T19), run by `just check`.

The committed fixture site `spa` is served on 127.0.0.1 by `serve_site`: start.html links
an SPA shell, app.html (an empty #root its script fills), and a prose page, plain.html;
robots.txt disallows /private/. `rovo init` runs through CliRunner; each sync runs
`rovo._commands.sync`, and each fetch `rovo._commands.fetch`, in process over the real
HttpxFetcher on a FixedClock, which never sleeps, with `tier_installed` injected and
`FakeEngine` (tests/fakes.py) as the engine: it renders app.html as the committed
app.rendered.html, making the render's navigation through the crawl, so it reaches the
server's log. Requests are read off that log. A page path strips the scope prefix
/guide/, so <base>guide/x.html is pages/<host>/x.md. The real-browser scenarios are
`test_browser_sync.py`; no unit test is named `test_render_sync.py`.
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import SITES, SiteServer
from test_init_sync import load, page_root, split_page
from typer.testing import CliRunner

from fakes import FakeEngine, FixedClock, unopened_engine
from rovo import _commands
from rovo._crawl.fetch import HttpxFetcher, Validators
from rovo._crawl.model import SiteResponse
from rovo._exit import ExitCode
from rovo._mirror.model import Tier
from rovo.cli import app
from test_commands import set_key

RENDERED = (SITES / "spa" / "guide" / "app.rendered.html").read_text(encoding="utf-8")
APP_PATH = "/guide/app.html"
ROBOTS_PATH = "/robots.txt"
HOST = "127.0.0.1"


class Recording:
    """Wraps the real fetcher and records each request's URL and validators."""

    def __init__(self, fetcher: HttpxFetcher) -> None:
        """Pass every request to `fetcher`."""
        self.fetcher = fetcher
        self.sent: list[tuple[str, Validators | None]] = []

    def fetch(self, url: str, *, validators: Validators | None = None) -> SiteResponse:
        """Record the request, then pass it on."""
        self.sent.append((url, validators))
        return self.fetcher.fetch(url, validators=validators)


def initialised(base: str, out: Path, render_mode: str) -> Path:
    """`rovo init <base>guide/start.html <out>` through CliRunner, then crawl.render_mode."""
    result = CliRunner().invoke(
        app, ["init", f"{base}guide/start.html", str(out)], prog_name="rovo"
    )
    assert result.exit_code == 0, result.output
    set_key(out, "render_mode", json.dumps(render_mode))
    return out


def browser_installed(tier: Tier) -> bool:
    """The browser engine is installed; the stealth engine is not."""
    return tier is Tier.browser


def nothing_installed(tier: Tier) -> bool:
    """No engine beyond http is installed."""
    del tier
    return False


def synced(
    out: Path,
    engine: Callable[[], FakeEngine],
    *,
    installed: Callable[[Tier], bool] = browser_installed,
) -> tuple[ExitCode, Recording]:
    """One rovo sync in process over the real HttpxFetcher, recorded; the code."""
    with HttpxFetcher() as fetcher:
        recording = Recording(fetcher)
        code = _commands.sync(
            out,
            fetcher=recording,
            clock=FixedClock(),
            tier_installed=installed,
            engine=engine,
        )
    return code, recording


def page(out: Path, base: str, name: str) -> tuple[dict[str, object], str]:
    """The page file of <base>guide/<name>.html: its frontmatter, JSON-decoded, and body."""
    raw, body = split_page((out / f"{page_root(base)}{name}.md").read_text(encoding="utf-8"))
    return {key: json.loads(value) for key, value in raw.items()}, body


def host_row(out: Path) -> dict[str, object]:
    """crawl-report.json's per-host row for the fixture server's host."""
    rows = load(out / "crawl-report.json")["per_host"]
    assert isinstance(rows, list)
    (row,) = [row for row in rows if row["host"] == HOST]
    assert isinstance(row, dict)
    return row


def tier_hints(out: Path) -> list[object]:
    """frontier.json's tier_hints."""
    hints = load(out / ".rovo" / "frontier.json")["tier_hints"]
    assert isinstance(hints, list)
    return hints


def files_under(directory: Path) -> list[Path]:
    """Every file under the directory."""
    return sorted(path for path in directory.rglob("*") if path.is_file())


def test_an_spa_shell_is_rendered_and_its_tier_learned(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """render_mode = "auto": app.html climbs to the browser, is stored rendered, is learned.

    The sync exits 0; app.md holds the rendered heading with tier browser and no
    render_needed; start.md and plain.md have tier http; the host's report row counts
    one render escalation and both tiers; frontier.json's tier_hints holds one row for the
    host with the run's id; the server saw app.html twice (the http try, then the
    render's navigation), after robots.txt. A second sync starts app.html at the browser:
    one more request for it, rendered, with no http try before it.
    """
    base = serve_site("spa")
    app_url = f"{base}guide/app.html"
    out = initialised(base, tmp_path / "out", "auto")
    first = FakeEngine({app_url: RENDERED})
    code, _ = synced(out, lambda: first)
    assert code is ExitCode.ok
    assert first.renders == [app_url]
    assert first.closed
    frontmatter, body = page(out, base, "app")
    assert "# Interactive guide" in body
    assert frontmatter["tier"] == "browser"
    flags = frontmatter["quality_flags"]
    assert isinstance(flags, list)
    assert "render_needed" not in flags
    for name in ("start", "plain"):
        assert page(out, base, name)[0]["tier"] == "http", name
    row = host_row(out)
    assert row["render_escalations"] == 1
    assert row["tiers_used"] == ["browser", "http"]
    (hint,) = tier_hints(out)
    assert isinstance(hint, dict)
    assert (hint["host_name"], hint["tier"], hint["learned_in_run"]) == (HOST, "browser", 1)
    paths = serve_site.paths(base)
    assert paths.count(APP_PATH) == len(["http try", "render"])
    assert paths.index(ROBOTS_PATH) < paths.index(APP_PATH)
    second = FakeEngine({app_url: RENDERED})
    code, recording = synced(out, lambda: second)
    assert code is ExitCode.ok
    assert second.renders == [app_url]
    assert serve_site.paths(base).count(APP_PATH) == len(["http try", "render", "render"])
    assert [validators for url, validators in recording.sent if url == app_url] == [None]
    assert host_row(out)["render_escalations"] == 0


def test_render_mode_never_stores_the_http_answer_flagged(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """render_mode = "never": no engine is opened; app.md is the http answer, flagged.

    The sync exits 0 with nothing installed; app.md has tier http, render_needed in its
    quality_flags and low_confidence true; frontier.json's tier_hints is empty.
    """
    base = serve_site("spa")
    out = initialised(base, tmp_path / "out", "never")
    code, _ = synced(out, unopened_engine, installed=nothing_installed)
    assert code is ExitCode.ok
    frontmatter, _ = page(out, base, "app")
    assert frontmatter["tier"] == "http"
    flags = frontmatter["quality_flags"]
    assert isinstance(flags, list)
    assert "render_needed" in flags
    assert frontmatter["low_confidence"] is True
    assert tier_hints(out) == []
    assert serve_site.paths(base).count(APP_PATH) == 1


def test_render_mode_always_renders_every_page(serve_site: SiteServer, tmp_path: Path) -> None:
    """render_mode = "always": every page is rendered and has tier browser.

    No walk climbed, so render_escalations is 0. On a second sync every navigation goes
    out without validators: a conditional fetch is http only.
    """
    base = serve_site("spa")
    pages = [f"{base}guide/{name}.html" for name in ("start", "app", "plain")]
    out = initialised(base, tmp_path / "out", "always")
    first = FakeEngine({f"{base}guide/app.html": RENDERED})
    code, _ = synced(out, lambda: first)
    assert code is ExitCode.ok
    assert sorted(first.renders) == sorted(pages)
    for name in ("start", "app", "plain"):
        assert page(out, base, name)[0]["tier"] == "browser", name
    assert host_row(out)["render_escalations"] == 0
    second = FakeEngine({f"{base}guide/app.html": RENDERED})
    code, recording = synced(out, lambda: second)
    assert code is ExitCode.ok
    assert sorted(second.renders) == sorted(pages)
    sent = [validators for url, validators in recording.sent if url in pages]
    assert len(sent) == len(pages)
    assert all(validators is None for validators in sent)
    assert host_row(out)["render_escalations"] == 0


def test_a_sync_needing_a_missing_engine_is_refused(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """render_mode = "auto" with the browser engine absent: exit 2 before any request.

    crawl-report.json is refused with "configured tier is not installed", no engine is
    opened, and the server's log is empty.
    """
    base = serve_site("spa")
    out = initialised(base, tmp_path / "out", "auto")
    code, _ = synced(out, unopened_engine, installed=nothing_installed)
    assert code is ExitCode.usage
    data = load(out / "crawl-report.json")
    assert data["report_status"] == "refused"
    assert data["refusal_reason"] == "configured tier is not installed"
    assert serve_site.paths(base) == []


def test_rovo_fetch_prints_one_page_and_writes_nothing(
    serve_site: SiteServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`rovo fetch` prints one page's Markdown body and writes no file.

    plain.html: its <h1> as a heading, no frontmatter, exit 0, robots.txt then the page.
    A URL under /private/ exits 1, prints nothing and is never requested; --tier stealth
    and an ftp: URL exit 2 with no request; --tier browser with the browser absent exits
    2 with no request.
    """
    monkeypatch.chdir(tmp_path)
    base = serve_site("spa")

    def fetch(
        url: str, tier: Tier | None = None, installed: Callable[[Tier], bool] = browser_installed
    ) -> ExitCode:
        with HttpxFetcher() as fetcher:
            return _commands.fetch(
                url,
                fetcher=fetcher,
                clock=FixedClock(),
                tier=tier,
                tier_installed=installed,
                engine=unopened_engine,
            )

    assert fetch(f"{base}guide/plain.html") is ExitCode.ok
    out = capsys.readouterr().out
    assert not out.startswith("---")
    assert "# Plain guide" in out
    assert serve_site.paths(base) == [ROBOTS_PATH, "/guide/plain.html"]
    assert fetch(f"{base}private/notes.html") is ExitCode.partial
    assert capsys.readouterr().out == ""
    assert "/private/notes.html" not in serve_site.paths(base)
    before = serve_site.paths(base)
    assert fetch(f"{base}guide/plain.html", Tier.stealth) is ExitCode.usage
    assert fetch("ftp://127.0.0.1/guide/plain.html") is ExitCode.usage
    assert fetch(f"{base}guide/plain.html", Tier.browser, nothing_installed) is ExitCode.usage
    assert capsys.readouterr().out == ""
    assert serve_site.paths(base) == before
    assert files_under(tmp_path) == []
