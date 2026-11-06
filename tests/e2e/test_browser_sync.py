"""End to end in a real Chromium: the browser tier through PlaywrightEngine (T19).

Every test here is marked `browser`: `pytest.ini` deselects them from `just check` and
`just coverage`, and `just e2e-browser` runs exactly them; without the `browser` extra
each skips. The committed fixture site `spa` is served on 127.0.0.1 by `serve_site`;
app.html is an SPA shell whose script assembles its heading and prose from pieces, so no
sentence of it is in the page's source, and which asks for style.css and for
/private/tracker.js, which robots.txt disallows. `rovo init` runs through CliRunner; the
sync and the fetch run `rovo._commands` in process over the real HttpxFetcher on a
FixedClock, which never sleeps, with `PlaywrightEngine` as the engine; a render's only
wait is Chromium's own for its load state. Requests are read off the server's log. No
unit test is named `test_browser_sync.py`.
"""

import json
from pathlib import Path

import pytest
from conftest import SITES, SiteServer
from test_init_sync import load, page_root, split_page
from typer.testing import CliRunner

from fakes import FixedClock
from rovo import _commands
from rovo._crawl.browser import PlaywrightEngine
from rovo._crawl.fetch import HttpxFetcher
from rovo._exit import ExitCode
from rovo._mirror.model import Tier
from rovo.cli import app
from test_commands import set_key

pytestmark = pytest.mark.browser

SOURCE = (SITES / "spa" / "guide" / "app.html").read_text(encoding="utf-8")
HEADING = "Interactive guide"
PROSE = "The interactive guide is written by a script in the browser"
ROBOTS_PATH = "/robots.txt"


@pytest.fixture(autouse=True)
def playwright_installed() -> None:
    """Skip without the browser extra: the engine needs playwright's sync API."""
    pytest.importorskip("playwright.sync_api")


def browser_installed(tier: Tier) -> bool:
    """The browser engine is installed; the stealth engine is not."""
    return tier is Tier.browser


def test_chromium_renders_the_spa_page(serve_site: SiteServer, tmp_path: Path) -> None:
    """render_mode = "auto" with PlaywrightEngine: app.html is rendered in Chromium.

    The sync exits 0; app.md holds the heading and prose the script wrote (absent from
    app.html's source) with tier browser; tier_hints holds one row; the server saw
    style.css and never /private/tracker.js (robots.txt disallows it, so the render's
    subrequest was aborted), and every request arrived after robots.txt.
    """
    assert HEADING not in SOURCE
    assert PROSE not in SOURCE
    base = serve_site("spa")
    out = tmp_path / "out"
    result = CliRunner().invoke(
        app, ["init", f"{base}guide/start.html", str(out)], prog_name="rovo"
    )
    assert result.exit_code == 0, result.output
    set_key(out, "render_mode", '"auto"')
    with HttpxFetcher() as fetcher:
        code = _commands.sync(
            out,
            fetcher=fetcher,
            clock=FixedClock(),
            tier_installed=browser_installed,
            engine=PlaywrightEngine,
        )
    assert code is ExitCode.ok
    raw, body = split_page((out / f"{page_root(base)}app.md").read_text(encoding="utf-8"))
    assert f"# {HEADING}" in body
    assert PROSE in " ".join(body.split())
    assert json.loads(raw["tier"]) == "browser"
    hints = load(out / ".rovo" / "frontier.json")["tier_hints"]
    assert isinstance(hints, list)
    assert len(hints) == 1
    paths = serve_site.paths(base)
    assert "/guide/style.css" in paths
    assert "/private/tracker.js" not in paths
    assert paths[0] == ROBOTS_PATH


def test_rovo_fetch_renders_in_chromium(
    serve_site: SiteServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`rovo fetch --tier browser` prints the script-written heading, exit 0, no file."""
    monkeypatch.chdir(tmp_path)
    base = serve_site("spa")
    with HttpxFetcher() as fetcher:
        code = _commands.fetch(
            f"{base}guide/app.html",
            fetcher=fetcher,
            clock=FixedClock(),
            tier=Tier.browser,
            tier_installed=browser_installed,
            engine=PlaywrightEngine,
        )
    assert code is ExitCode.ok
    assert f"# {HEADING}" in capsys.readouterr().out
    assert sorted(path for path in tmp_path.rglob("*") if path.is_file()) == []
    assert serve_site.paths(base)[0] == ROBOTS_PATH
    assert "/private/tracker.js" not in serve_site.paths(base)
