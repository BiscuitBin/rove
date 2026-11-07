"""End to end in a real Chromium: a render's non-GET subrequest is aborted (spec 9149df7).

AttemptTier guidance (crawl.allium 1748 to 1750, the maintainer's final-review answer
F3): a subrequest whose method is not GET or HEAD is aborted, never sent; a GET or HEAD
subrequest is fetched through rovo. The committed fixture site `spa-methods` is served
on 127.0.0.1 by `serve_site`; guide/app.html's script makes three synchronous requests
before its load event, a GET of data.json, a HEAD of ping.txt and a POST of submit.txt,
and writes what became of each into the page. `rovo fetch --tier browser` runs
`rovo._commands.fetch` in process over the real HttpxFetcher on a FixedClock, which never
sleeps, with `PlaywrightEngine` as the engine. Marked `browser`: `just e2e-browser` runs
it; without the `browser` extra it skips. No unit test is named
`test_subrequest_methods_sync.py`.
"""

from pathlib import Path

import pytest
from conftest import SiteServer

from fakes import FixedClock
from rovo import _commands
from rovo._crawl.browser import PlaywrightEngine
from rovo._crawl.fetch import HttpxFetcher
from rovo._exit import ExitCode
from rovo._mirror.model import Tier

pytestmark = pytest.mark.browser

ROBOTS_PATH = "/robots.txt"


@pytest.fixture(autouse=True)
def playwright_installed() -> None:
    """Skip without the browser extra: the engine needs playwright's sync API."""
    pytest.importorskip("playwright.sync_api")


def browser_installed(tier: Tier) -> bool:
    """The browser engine is installed; the stealth engine is not."""
    return tier is Tier.browser


def test_a_rendered_pages_post_is_aborted_and_its_get_and_head_are_fetched(
    serve_site: SiteServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`rovo fetch --tier browser` of app.html: the POST is refused, never sent.

    Exit 0; the printed page says the data and head requests were answered and the form
    request was refused; the server saw robots.txt first, then app.html, data.json and
    ping.txt (each through rovo, as a GET), and never submit.txt.
    """
    monkeypatch.chdir(tmp_path)
    base = serve_site("spa-methods")
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
    out = " ".join(capsys.readouterr().out.split())
    assert "# Request methods" in out
    assert "The data request answered fetched by a get subrequest." in out
    assert "The head request was answered." in out
    assert "The form request was refused." in out
    paths = serve_site.paths(base)
    assert paths[0] == ROBOTS_PATH
    assert {"/guide/app.html", "/guide/data.json", "/guide/ping.txt"} <= set(paths)
    assert "/guide/submit.txt" not in paths
