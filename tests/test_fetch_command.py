"""`rovo fetch URL [--tier TIER]` (T19): rovo.allium's fetch rules and MirrorCommands.

Each obligation test is named after the id `just plan-spec rovo` emits at 7d01367, dots
and hyphens as underscores, and its docstring quotes the obligation. A `rule_failure`
test makes exactly one `requires` clause false. `rovo._commands.fetch` runs in process
over a FakeFetcher on a FixedClock with `tier_installed` injected, so no test depends on
what the machine has installed and none reaches the network; the command line is
driven through CliRunner and, once, through the installed script, only where it refuses
before any request. The rest are the ticket's guarantees: nothing written, robots.txt
read before the page, a block, a non-HTML answer, a robots refusal or a failed fetch
exiting 1 with nothing printed, `--tier browser` rendering through `FakeEngine`, and the
interim of T19 Open points item 2 (no climb: an http answer that needs a browser is
printed as it is).
"""

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fakes import (
    FakeEngine,
    FakeFetcher,
    FixedClock,
    html_response,
    text_response,
    unopened_engine,
)
from rovo import _commands
from rovo._crawl.model import SiteResponse
from rovo._exit import ExitCode
from rovo._mirror.model import Tier
from rovo.cli import app

SITE = "http://docs.example"
PAGE_URL = f"{SITE}/guide/start.html"
ROBOTS = f"{SITE}/robots.txt"
PRIVATE_URL = f"{SITE}/private/notes.html"
NOT_HTTP_URL = "ftp://docs.example/guide/start.html"
SITES = Path(__file__).resolve().parent / "fixtures" / "sites"
PAGE = (SITES / "one-page" / "guide" / "start.html").read_text(encoding="utf-8")
SPA_SHELL = (SITES / "spa" / "guide" / "app.html").read_text(encoding="utf-8")
RENDERED = (SITES / "spa" / "guide" / "app.rendered.html").read_text(encoding="utf-8")
ROBOTS_TEXT = "User-agent: *\nDisallow: /private/\n"
FORBIDDEN = 403
OWNER_TEST = "owner-test"


def site(page: str = PAGE, *, status: int = 200) -> FakeFetcher:
    """The fixture site: robots.txt disallowing /private/, and the page at PAGE_URL."""
    return FakeFetcher(
        {
            ROBOTS: text_response(ROBOTS, ROBOTS_TEXT),
            PAGE_URL: html_response(PAGE_URL, page, status=status),
            PRIVATE_URL: html_response(PRIVATE_URL, PAGE),
        }
    )


def installed(*tiers: Tier) -> Callable[[Tier], bool]:
    """A tier_installed that reports exactly `tiers` installed."""
    return lambda tier: tier in tiers


def fetched(  # noqa: PLR0913  The command's seams and its options, one keyword each.
    url: str,
    fetcher: FakeFetcher,
    *,
    tier: Tier | None = None,
    owner_test: object | None = None,
    tier_installed: Callable[[Tier], bool] | None = None,
    engine: Callable[[], FakeEngine] = unopened_engine,
) -> ExitCode:
    """One `rovo fetch` in process; by default no tier but http is installed."""
    return _commands.fetch(
        url,
        fetcher=fetcher,
        clock=FixedClock(),
        tier=tier,
        owner_test=owner_test,
        tier_installed=tier_installed or installed(),
        engine=engine,
    )


def files_under(directory: Path) -> list[Path]:
    """Every file under the directory."""
    return sorted(path for path in directory.rglob("*") if path.is_file())


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The test's directory as the current directory, so a stray write would land in it."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- RefuseOwnerTestingFetch ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "tier", "owner_test"),
    [
        pytest.param(PAGE_URL, Tier.stealth, None, id="stealth-tier"),
        pytest.param(NOT_HTTP_URL, None, None, id="not-http"),
        pytest.param(PAGE_URL, None, OWNER_TEST, id="owner-test"),
    ],
)
def test_rule_success_RefuseOwnerTestingFetch(
    workdir: Path,
    capsys: pytest.CaptureFixture[str],
    url: str,
    tier: Tier | None,
    owner_test: object | None,
) -> None:
    """Verify rule RefuseOwnerTestingFetch succeeds when all preconditions are met.

    --tier stealth, a URL that is not http(s), and an owner test, each alone: exit 2
    (usage), no request, nothing printed, nothing written; every tier is installed, so
    no later refusal could be the cause.
    """
    fetcher = site()
    code = fetched(
        url,
        fetcher,
        tier=tier,
        owner_test=owner_test,
        tier_installed=installed(Tier.browser, Tier.stealth),
    )
    assert code is ExitCode.usage
    assert fetcher.requests == []
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("rovo: fetch: ")
    assert files_under(workdir) == []


def test_rule_failure_RefuseOwnerTestingFetch_1(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule RefuseOwnerTestingFetch is rejected when requires clause fails.

    requires: owner_test != null or tier = stealth or not is_http_url(url): an http URL
    with no owner test and no tier is not refused; it is fetched and printed.
    """
    fetcher = site()
    assert fetched(PAGE_URL, fetcher) is ExitCode.ok
    assert PAGE_URL in fetcher.requests
    assert "# Getting started" in capsys.readouterr().out
    assert files_under(workdir) == []


# --- RefuseMissingFetchTier ---------------------------------------------------------------


def test_rule_success_RefuseMissingFetchTier(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule RefuseMissingFetchTier succeeds when all preconditions are met.

    --tier browser for an http URL with no browser engine installed: exit 2, no request,
    no engine opened, nothing printed or written.
    """
    fetcher = site()
    assert fetched(PAGE_URL, fetcher, tier=Tier.browser) is ExitCode.usage
    assert fetcher.requests == []
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("rovo: fetch: ")
    assert files_under(workdir) == []


def test_rule_failure_RefuseMissingFetchTier_1(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule RefuseMissingFetchTier is rejected when requires clause fails.

    requires: owner_test = null and tier != stealth and is_http_url(url): a URL that is
    not http(s), with --tier browser not installed, is refused as RefuseOwnerTestingFetch
    refuses it, not as a missing tier: its refusal names another problem.
    """
    missing_tier = site()
    assert fetched(PAGE_URL, missing_tier, tier=Tier.browser) is ExitCode.usage
    missing = capsys.readouterr().err
    not_http = site()
    assert fetched(NOT_HTTP_URL, not_http, tier=Tier.browser) is ExitCode.usage
    refused = capsys.readouterr().err
    assert missing_tier.requests == not_http.requests == []
    assert refused.startswith("rovo: fetch: ")
    assert refused != missing


@pytest.mark.parametrize(
    "tier",
    [
        pytest.param(None, id="no-tier"),
        pytest.param(Tier.http, id="http"),
        pytest.param(Tier.browser, id="browser-installed"),
    ],
)
def test_rule_failure_RefuseMissingFetchTier_2(
    capsys: pytest.CaptureFixture[str], tier: Tier | None
) -> None:
    """Verify rule RefuseMissingFetchTier is rejected when requires clause fails.

    requires: tier != null and tier != http and not tier_installed(tier): no tier, the
    http tier with nothing installed, and an installed browser are not refused.
    """
    fetcher = site()
    engine = FakeEngine()
    code = fetched(
        PAGE_URL,
        fetcher,
        tier=tier,
        tier_installed=installed(Tier.browser) if tier is Tier.browser else installed(),
        engine=lambda: engine,
    )
    assert code is ExitCode.ok
    assert PAGE_URL in fetcher.requests
    assert "# Getting started" in capsys.readouterr().out
    assert engine.renders == ([PAGE_URL] if tier is Tier.browser else [])


# --- FetchOneUrl --------------------------------------------------------------------------


def test_rule_success_FetchOneUrl(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule FetchOneUrl succeeds when all preconditions are met.

    The URL's origin's robots.txt is read, then the page; its Markdown body is printed
    with no frontmatter, its <h1> a heading; exit 0; no file is written anywhere.
    """
    fetcher = site()
    assert fetched(PAGE_URL, fetcher) is ExitCode.ok
    assert fetcher.requests == [ROBOTS, PAGE_URL]
    out = capsys.readouterr().out
    assert not out.startswith("---")
    assert out.lstrip().startswith("# Getting started")
    assert "Download the installer" in out
    assert files_under(workdir) == []


def test_rule_failure_FetchOneUrl_1(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule FetchOneUrl is rejected when requires clause fails.

    requires: owner_test = null and tier != stealth and is_http_url(url): a URL that is
    not http(s) is not fetched: no request, no page printed.
    """
    fetcher = site()
    assert fetched(NOT_HTTP_URL, fetcher) is ExitCode.usage
    assert fetcher.requests == []
    assert capsys.readouterr().out == ""


def test_rule_failure_FetchOneUrl_2(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule FetchOneUrl is rejected when requires clause fails.

    requires: tier = null or tier = http or tier_installed(tier): --tier browser with no
    browser installed is not fetched: no request, no page printed.
    """
    fetcher = site()
    assert fetched(PAGE_URL, fetcher, tier=Tier.browser) is ExitCode.usage
    assert fetcher.requests == []
    assert capsys.readouterr().out == ""


# --- MirrorCommands ----------------------------------------------------------------------


def test_surface_actor_MirrorCommands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify surface MirrorCommands is accessible only to the specified actor.

    The operator reaches OperatorFetchesUrl through the command line: `rovo fetch` of a
    URL that is not http(s), and `--tier stealth`, exit 2 with the command's own refusal
    on standard error (not Click's "No such command"), and nothing printed or written.
    """
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    for arguments in (["fetch", NOT_HTTP_URL], ["fetch", PAGE_URL, "--tier", "stealth"]):
        result = runner.invoke(app, arguments, prog_name="rovo")
        assert result.exit_code == ExitCode.usage.number, result.output
        assert result.stdout == ""
        assert result.stderr.startswith("rovo: fetch: "), result.stderr
    assert files_under(tmp_path) == []


def test_surface_provides_MirrorCommands() -> None:
    """Verify provided operations on MirrorCommands appear/hide based on when conditions.

    Every operation an operator raises has its command: init, sync, verify, index,
    report and, with this slice, fetch, which takes URL and --tier (http, browser or
    stealth).
    """
    runner = CliRunner(env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})
    listed = runner.invoke(app, ["--help"], prog_name="rovo")
    assert listed.exit_code == 0, listed.output
    for command in ("init", "sync", "verify", "index", "report", "fetch"):
        assert command in listed.stdout, command
    helped = runner.invoke(app, ["fetch", "--help"], prog_name="rovo")
    assert helped.exit_code == 0, helped.output
    assert "Usage: rovo fetch" in helped.stdout
    for argument in ("URL", "--tier"):
        assert argument in helped.stdout


# --- Guarantees --------------------------------------------------------------------------


def test_rovo_fetch_through_the_installed_script_refuses_a_non_http_url(tmp_path: Path) -> None:
    """The installed `rovo` script runs `rovo fetch`: a non-http URL exits 2, nothing written."""
    script = shutil.which("rovo", path=str(Path(sys.executable).parent))
    assert script is not None, f"no rovo console script beside {sys.executable}"
    completed = subprocess.run(
        [script, "fetch", NOT_HTTP_URL],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert completed.returncode == ExitCode.usage.number, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr.startswith("rovo: fetch: ")
    assert files_under(tmp_path) == []


@pytest.mark.parametrize(
    ("url", "answer"),
    [
        pytest.param(PAGE_URL, html_response(PAGE_URL, "", status=FORBIDDEN), id="blocked"),
        pytest.param(
            PAGE_URL,
            SiteResponse(
                status=200,
                source_url=PAGE_URL,
                markup="%PDF-1.7",
                size=8,
                content_type="application/pdf",
            ),
            id="not-html",
        ),
        pytest.param(
            PAGE_URL,
            SiteResponse(status=0, source_url=PAGE_URL, markup="", size=0, error="refused"),
            id="failed",
        ),
    ],
)
def test_a_block_a_non_html_answer_or_a_failed_fetch_exits_1_printing_nothing(
    workdir: Path, capsys: pytest.CaptureFixture[str], url: str, answer: SiteResponse
) -> None:
    """FetchOneUrl guidance: a block, a non-HTML answer or a failed fetch prints no page.

    Exit 1 (partial), nothing on standard output, nothing written; robots.txt was read
    before the page.
    """
    fetcher = site()
    fetcher.responses[url] = answer
    assert fetched(url, fetcher) is ExitCode.partial
    assert fetcher.requests[0] == ROBOTS
    assert url in fetcher.requests
    assert capsys.readouterr().out == ""
    assert files_under(workdir) == []


def test_a_robots_refusal_exits_1_and_never_requests_the_page(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FetchOneUrl guidance: a URL robots.txt disallows is never requested; exit 1."""
    fetcher = site()
    assert fetched(PRIVATE_URL, fetcher) is ExitCode.partial
    assert fetcher.requests == [ROBOTS]
    assert capsys.readouterr().out == ""
    assert files_under(workdir) == []


def test_tier_browser_renders_through_the_engine(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--tier browser renders the page: the engine is opened once, renders, and is closed.

    The render's navigation is made through the crawl (robots.txt first, then the page,
    with no http try before it), and the printed Markdown is the rendered DOM's.
    """
    fetcher = site(SPA_SHELL)
    opened: list[FakeEngine] = []

    def open_engine() -> FakeEngine:
        opened.append(FakeEngine({PAGE_URL: RENDERED}))
        return opened[-1]

    code = fetched(
        PAGE_URL,
        fetcher,
        tier=Tier.browser,
        tier_installed=installed(Tier.browser),
        engine=open_engine,
    )
    assert code is ExitCode.ok
    (engine,) = opened
    assert engine.renders == [PAGE_URL]
    assert engine.closed
    assert fetcher.requests == [ROBOTS, PAGE_URL]
    assert "# Interactive guide" in capsys.readouterr().out
    assert files_under(workdir) == []


def test_an_http_fetch_never_climbs_to_the_browser(capsys: pytest.CaptureFixture[str]) -> None:
    """T19 Open points item 2's interim: with no tier the walk is [http], with no climb.

    An SPA shell answered at http is printed as it is, the engine never opened, even
    with the browser installed.
    """
    fetcher = site(SPA_SHELL)
    code = fetched(PAGE_URL, fetcher, tier_installed=installed(Tier.browser))
    assert code is ExitCode.ok
    assert fetcher.requests == [ROBOTS, PAGE_URL]
    assert "# Interactive guide" not in capsys.readouterr().out
