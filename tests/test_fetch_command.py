"""`rovo fetch URL [--tier TIER] [--config PATH]` (T19): rovo.allium's fetch rules.

Each obligation test is named after the id `just plan-spec rovo` emits at e0f0c44, dots
and hyphens as underscores, and its docstring quotes the obligation. A `rule_failure`
test makes exactly one `requires` clause false. `rovo._commands.fetch` runs in process
over a FakeFetcher on a FixedClock with `tier_installed` injected, or the engine probe
faked by `probe_engine`, so no test depends on what the machine has installed and none
reaches the network; the command line is driven through CliRunner and, once, through
the installed script, only where it refuses before any request. The rest are the
ticket's guarantees and the maintainer's answers at e0f0c44 (T19 Open points item 2):
`--config` layers the built-in defaults, the file's shared sections and its optional
[fetch] section (render_mode and profile only), never a ROVO_ variable; render_mode
means what it means for a sync (always starts at the browser, auto climbs from http
only when the page needs rendering, never is http only) and --tier runs that tier only;
the file's [scope] bounds the redirects followed, else the URL's own host does; a
missing engine is refused up front naming the missing piece and both fixes; nothing is
written, robots.txt is read before the page, and a block, a non-HTML answer, a robots
refusal or a failed fetch exits 1 with nothing printed.
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
    probe_engine,
    redirect_response,
    text_response,
    unopened_engine,
)
from rovo import _commands
from rovo._config import resolve_config, resolve_fetch_config
from rovo._crawl.model import RenderMode, SiteResponse
from rovo._exit import ExitCode
from rovo._mirror.model import Tier
from rovo.cli import app

SITE = "http://docs.example"
PAGE_URL = f"{SITE}/guide/start.html"
ROBOTS = f"{SITE}/robots.txt"
PRIVATE_URL = f"{SITE}/private/notes.html"
NOT_HTTP_URL = "ftp://docs.example/guide/start.html"
MIRROR_SITE = "http://mirror.example"
MIRROR_PAGE = f"{MIRROR_SITE}/guide/start.html"
SITES = Path(__file__).resolve().parent / "fixtures" / "sites"
PAGE = (SITES / "one-page" / "guide" / "start.html").read_text(encoding="utf-8")
SPA_SHELL = (SITES / "spa" / "guide" / "app.html").read_text(encoding="utf-8")
RENDERED = (SITES / "spa" / "guide" / "app.rendered.html").read_text(encoding="utf-8")
RENDERED_HEADING = "# Interactive guide"
ROBOTS_TEXT = "User-agent: *\nDisallow: /private/\n"
FORBIDDEN = 403
OWNER_TEST = "owner-test"
# The refusal's two ways forward and the missing pieces (rovo.allium RefuseMissingEngine
# and RefuseMissingFetchTier guidance at e0f0c44), as missing_browser_piece names them.
FIX_INSTALL = "playwright install chromium"
FIX_NEVER = "render_mode = never"
NO_PACKAGE = "the playwright package"
NO_BINARY = "the Chromium browser"
# Configurations a test writes to rovo.toml (rovo.allium resolve_fetch_config).
AUTO = '[fetch]\nrender_mode = "auto"\n'
ALWAYS = '[fetch]\nrender_mode = "always"\n'
NEVER = '[fetch]\nrender_mode = "never"\n'
UNKNOWN_FETCH_KEY = "[fetch]\nmax_depth = 3\n"
SECOND_HOST_SCOPE = (
    '[site]\nroot_url = "http://docs.example/guide/"\n'
    '[scope]\nallowed_hosts = ["docs.example", "mirror.example"]\n'
)


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
    config_path: Path | None = None,
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
        config_path=config_path,
    )


def config(directory: Path, text: str, name: str = "rovo.toml") -> Path:
    """A configuration file holding `text`, outside the directory a fetch runs in."""
    path = directory / "config" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def files_under(directory: Path) -> list[Path]:
    """Every file under the directory."""
    return sorted(path for path in directory.rglob("*") if path.is_file())


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty current directory under the test's, so a stray write would land in it."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return cwd


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


# --- RefuseFetchOnBadConfig ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "named"),
    [
        pytest.param("[fetch\nrender_mode =", "rovo.toml", id="unparsable"),
        pytest.param(None, "rovo.toml", id="missing-file"),
        pytest.param("[politeness]\nrate = 1\n", "politeness", id="unknown-section"),
        pytest.param(UNKNOWN_FETCH_KEY, "fetch.max_depth", id="unknown-fetch-key"),
        pytest.param('[fetch]\nrobots = "ignore"\n', "fetch.robots", id="crawl-key-in-fetch"),
        pytest.param('[fetch]\nrender_mode = "sometimes"\n', "fetch.render_mode", id="bad-value"),
        pytest.param('[fetch]\nprofile = "nonesuch"\n', "nonesuch", id="unknown-profile"),
        pytest.param('[unblocking]\nprovider = "vendor"\n', "unblocking.provider", id="provider"),
    ],
)
def test_rule_success_RefuseFetchOnBadConfig(
    workdir: Path,
    capsys: pytest.CaptureFixture[str],
    text: str | None,
    named: str,
) -> None:
    """Verify rule RefuseFetchOnBadConfig succeeds when all preconditions are met.

    An http URL with no owner test and no stealth tier, and a --config that is
    unreadable, unparsable, holds an unknown section or key ([fetch] holds render_mode
    and profile only, so a [crawl] key in it is unknown), a bad value, a profile the
    catalogue lacks, or an unblocking provider: exit 2, no request, no engine opened,
    nothing printed or written, the bad key path (or the file) named on standard error.
    """
    path = (
        workdir.parent / "absent" / "rovo.toml" if text is None else config(workdir.parent, text)
    )
    fetcher = site()
    code = fetched(PAGE_URL, fetcher, tier_installed=installed(Tier.browser), config_path=path)
    assert code is ExitCode.usage
    assert fetcher.requests == []
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("rovo: fetch: ")
    assert named in captured.err
    assert files_under(workdir) == []


def test_rule_failure_RefuseFetchOnBadConfig_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule RefuseFetchOnBadConfig is rejected when requires clause fails.

    requires: owner_test = null and tier != stealth and is_http_url(url): a URL that is
    not http(s), with a bad --config, is refused as RefuseOwnerTestingFetch refuses it,
    not for the configuration: its refusal does not name the bad key.
    """
    path = config(tmp_path, UNKNOWN_FETCH_KEY)
    bad_config = site()
    assert fetched(PAGE_URL, bad_config, config_path=path) is ExitCode.usage
    assert "fetch.max_depth" in capsys.readouterr().err
    not_http = site()
    assert fetched(NOT_HTTP_URL, not_http, config_path=path) is ExitCode.usage
    refused = capsys.readouterr().err
    assert bad_config.requests == not_http.requests == []
    assert refused.startswith("rovo: fetch: ")
    assert "fetch.max_depth" not in refused


def test_rule_failure_RefuseFetchOnBadConfig_2(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule RefuseFetchOnBadConfig is rejected when requires clause fails.

    requires: not settings.valid or settings.unblocking_provider != null: a valid
    --config, its shared sections and a [fetch] section with both its keys, is not
    refused; the page is fetched and printed.
    """
    path = config(
        workdir.parent, '[conversion]\nprofile = "generic"\n' + NEVER + 'profile = "generic"\n'
    )
    fetcher = site()
    assert fetched(PAGE_URL, fetcher, config_path=path) is ExitCode.ok
    assert fetcher.requests == [ROBOTS, PAGE_URL]
    assert "# Getting started" in capsys.readouterr().out
    assert files_under(workdir) == []


# --- RefuseMissingFetchTier ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("tier", "text"),
    [
        pytest.param(Tier.browser, None, id="tier-browser"),
        pytest.param(None, AUTO, id="fetch-auto"),
        pytest.param(None, ALWAYS, id="fetch-always"),
        pytest.param(None, '[crawl]\nrender_mode = "always"\n', id="crawl-always"),
    ],
)
def test_rule_success_RefuseMissingFetchTier(
    workdir: Path,
    capsys: pytest.CaptureFixture[str],
    tier: Tier | None,
    text: str | None,
) -> None:
    """Verify rule RefuseMissingFetchTier succeeds when all preconditions are met.

    With no browser engine installed: --tier browser, and no --tier under an effective
    render_mode of auto or always (from [fetch], or from the shared [crawl] section):
    exit 2, no request, no engine opened, nothing printed or written, and standard
    error names both ways forward, `playwright install chromium` and `render_mode =
    never`.
    """
    path = None if text is None else config(workdir.parent, text)
    fetcher = site()
    assert fetched(PAGE_URL, fetcher, tier=tier, config_path=path) is ExitCode.usage
    assert fetcher.requests == []
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("rovo: fetch: ")
    assert FIX_INSTALL in captured.err
    assert FIX_NEVER in captured.err
    assert files_under(workdir) == []


def test_rule_failure_RefuseMissingFetchTier_1(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule RefuseMissingFetchTier is rejected when requires clause fails.

    requires: owner_test = null and tier != stealth and is_http_url(url): a URL that is
    not http(s), with --tier browser not installed, is refused as RefuseOwnerTestingFetch
    refuses it, not as a missing tier: its refusal names neither fix.
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
    assert FIX_INSTALL not in refused


def test_rule_failure_RefuseMissingFetchTier_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify rule RefuseMissingFetchTier is rejected when requires clause fails.

    requires: settings.valid and settings.unblocking_provider = null: an invalid
    --config that also asks for a missing browser (render_mode = "auto" beside an
    unknown key, or --tier browser) is refused for the configuration: the bad key is
    named, no fix for the engine is.
    """
    path = config(tmp_path, AUTO + "max_depth = 3\n")
    for tier in (None, Tier.browser):
        fetcher = site()
        assert fetched(PAGE_URL, fetcher, tier=tier, config_path=path) is ExitCode.usage
        assert fetcher.requests == []
        err = capsys.readouterr().err
        assert "fetch.max_depth" in err
        assert FIX_INSTALL not in err


@pytest.mark.parametrize(
    ("tier", "text", "tiers"),
    [
        pytest.param(Tier.http, ALWAYS, (), id="tier-http-under-always"),
        pytest.param(None, None, (), id="no-tier-no-config"),
        pytest.param(None, NEVER, (), id="no-tier-never"),
        pytest.param(Tier.browser, None, (Tier.browser,), id="tier-browser-installed"),
        pytest.param(None, AUTO, (Tier.browser,), id="auto-installed"),
    ],
)
def test_rule_failure_RefuseMissingFetchTier_3(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    tier: Tier | None,
    text: str | None,
    tiers: tuple[Tier, ...],
) -> None:
    """Verify rule RefuseMissingFetchTier is rejected when requires clause fails.

    requires: (tier = browser or (tier = null and settings.needs_browser)) and not
    tier_installed(browser): --tier http under render_mode = "always" with nothing
    installed (--tier http never renders), no tier with no --config or under
    render_mode = "never" with nothing installed, --tier browser installed, and no tier
    under "auto" installed are not refused; the page is fetched and printed, rendered
    only where --tier browser asks.
    """
    path = None if text is None else config(tmp_path, text)
    fetcher = site()
    engine = FakeEngine()
    code = fetched(
        PAGE_URL,
        fetcher,
        tier=tier,
        tier_installed=installed(*tiers),
        engine=lambda: engine,
        config_path=path,
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


def test_rule_failure_FetchOneUrl_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule FetchOneUrl is rejected when requires clause fails.

    requires: settings.valid and settings.unblocking_provider = null: a --config with an
    unknown [fetch] key, or an unblocking provider, is not fetched: no request, no page
    printed.
    """
    for text in (UNKNOWN_FETCH_KEY, '[unblocking]\nprovider = "vendor"\n'):
        fetcher = site()
        path = config(tmp_path, text)
        assert fetched(PAGE_URL, fetcher, config_path=path) is ExitCode.usage
        assert fetcher.requests == []
        assert capsys.readouterr().out == ""


def test_rule_failure_FetchOneUrl_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify rule FetchOneUrl is rejected when requires clause fails.

    requires: tier = http or (tier = null and not settings.needs_browser) or
    tier_installed(browser): --tier browser, and no tier under render_mode = "auto",
    with no browser installed, are not fetched: no request, no page printed.
    """
    for tier, path in ((Tier.browser, None), (None, config(tmp_path, AUTO))):
        fetcher = site()
        assert fetched(PAGE_URL, fetcher, tier=tier, config_path=path) is ExitCode.usage
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
    report and fetch, which takes URL, --tier (http, browser or stealth) and, with
    OperatorFetchesUrl's config_path (e0f0c44), --config.
    """
    runner = CliRunner(env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})
    listed = runner.invoke(app, ["--help"], prog_name="rovo")
    assert listed.exit_code == 0, listed.output
    for command in ("init", "sync", "verify", "index", "report", "fetch"):
        assert command in listed.stdout, command
    helped = runner.invoke(app, ["fetch", "--help"], prog_name="rovo")
    assert helped.exit_code == 0, helped.output
    assert "Usage: rovo fetch" in helped.stdout
    for argument in ("URL", "--tier", "--config"):
        assert argument in helped.stdout, argument


# --- Guarantees: the command line ----------------------------------------------------------


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


def test_the_command_line_passes_config_to_the_fetch(workdir: Path) -> None:
    """`rovo fetch URL --config PATH` reads PATH: a bad one exits 2 before any request.

    An unknown [fetch] key is named on standard error, and a --config that names no file
    is refused too; nothing is printed or written.
    """
    runner = CliRunner()
    for path, named in (
        (config(workdir.parent, UNKNOWN_FETCH_KEY), "fetch.max_depth"),
        (workdir.parent / "absent" / "rovo.toml", "rovo.toml"),
    ):
        result = runner.invoke(app, ["fetch", PAGE_URL, "--config", str(path)], prog_name="rovo")
        assert result.exit_code == ExitCode.usage.number, result.output
        assert result.stdout == ""
        assert result.stderr.startswith("rovo: fetch: "), result.stderr
        assert named in result.stderr, result.stderr
    assert files_under(workdir) == []


def test_the_command_line_refuses_a_config_that_needs_a_missing_chromium(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`rovo fetch URL --config PATH`, [fetch] render_mode = "auto", Chromium missing: exit 2.

    The engine probe finds the playwright package but no Chromium binary (rovo.allium
    RefuseMissingFetchTier at e0f0c44: tier_installed(browser) is the package and its
    Chromium): refused before any request, naming the missing browser and both fixes.
    """
    probe_engine(monkeypatch, package=True, binary=workdir.parent / "no-chromium")
    path = config(workdir.parent, AUTO)
    result = CliRunner().invoke(app, ["fetch", PAGE_URL, "--config", str(path)], prog_name="rovo")
    assert result.exit_code == ExitCode.usage.number, result.output
    assert result.stdout == ""
    for named in (NO_BINARY, FIX_INSTALL, FIX_NEVER):
        assert named in result.stderr, named
    assert files_under(workdir) == []


# --- Guarantees: the missing engine --------------------------------------------------------


@pytest.mark.parametrize(
    ("binary", "piece"),
    [
        pytest.param(None, NO_PACKAGE, id="no-package"),
        pytest.param(None, NO_BINARY, id="no-binary-path"),
        pytest.param("absent", NO_BINARY, id="binary-not-on-disk"),
    ],
)
def test_a_missing_engine_is_refused_naming_the_missing_piece_and_both_fixes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    binary: str | None,
    piece: str,
) -> None:
    """RefuseMissingFetchTier guidance (e0f0c44): the message names the piece and both fixes.

    tier_installed is not injected: the default reads the engine probe, faked here. No
    playwright package, or the package with no Chromium binary (none reported, or one
    reported but not on disk), refuses --tier browser and no tier under render_mode =
    "always" with exit 2 and no request, standard error naming that piece,
    `playwright install chromium` and `render_mode = never`.
    """
    probe_engine(
        monkeypatch,
        package=piece != NO_PACKAGE,
        binary=None if binary is None else tmp_path / binary,
    )
    for tier, path in ((Tier.browser, None), (None, config(tmp_path, ALWAYS))):
        fetcher = site()
        code = _commands.fetch(
            PAGE_URL,
            fetcher=fetcher,
            clock=FixedClock(),
            tier=tier,
            engine=unopened_engine,
            config_path=path,
        )
        assert code is ExitCode.usage
        assert fetcher.requests == []
        err = capsys.readouterr().err
        for named in (piece, FIX_INSTALL, FIX_NEVER):
            assert named in err, named


def test_an_installed_engine_by_the_probe_renders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The probe finds the package and a Chromium binary on disk: --tier browser renders.

    tier_installed is not injected; the fetch is not refused and renders through the
    engine opened, closed when the fetch ends.
    """
    chromium = tmp_path / "chrome"
    chromium.write_text("", encoding="utf-8")
    probe_engine(monkeypatch, package=True, binary=chromium)
    engine = FakeEngine({PAGE_URL: RENDERED})
    fetcher = site(SPA_SHELL)
    code = _commands.fetch(
        PAGE_URL, fetcher=fetcher, clock=FixedClock(), tier=Tier.browser, engine=lambda: engine
    )
    assert code is ExitCode.ok
    assert engine.renders == [PAGE_URL]
    assert engine.closed
    assert RENDERED_HEADING in capsys.readouterr().out


# --- Guarantees: tiers and render_mode -----------------------------------------------------


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
    assert RENDERED_HEADING in capsys.readouterr().out
    assert files_under(workdir) == []


def test_with_no_config_render_mode_is_never_and_the_fetch_never_climbs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FetchOneUrl guidance (e0f0c44): without --config the built-in render_mode, never.

    An SPA shell answered at http is printed as it is, the engine never opened, even
    with the browser installed: never is http only.
    """
    fetcher = site(SPA_SHELL)
    code = fetched(PAGE_URL, fetcher, tier_installed=installed(Tier.browser))
    assert code is ExitCode.ok
    assert fetcher.requests == [ROBOTS, PAGE_URL]
    assert RENDERED_HEADING not in capsys.readouterr().out


def test_render_mode_auto_climbs_from_http_only_when_the_page_needs_rendering(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FetchOneUrl guidance (e0f0c44): auto starts at http and climbs when rendering is needed.

    [fetch] render_mode = "auto", browser installed: an SPA shell is fetched at http,
    then rendered (its navigation a second request for the page), and the rendered
    Markdown printed; a page that needs no rendering is fetched once and never rendered.
    """
    path = config(tmp_path, AUTO)
    engine = FakeEngine({PAGE_URL: RENDERED})
    shell = site(SPA_SHELL)
    code = fetched(
        PAGE_URL,
        shell,
        tier_installed=installed(Tier.browser),
        engine=lambda: engine,
        config_path=path,
    )
    assert code is ExitCode.ok
    assert shell.requests == [ROBOTS, PAGE_URL, PAGE_URL]
    assert engine.renders == [PAGE_URL]
    assert RENDERED_HEADING in capsys.readouterr().out
    plain_engine = FakeEngine()
    plain = site()
    code = fetched(
        PAGE_URL,
        plain,
        tier_installed=installed(Tier.browser),
        engine=lambda: plain_engine,
        config_path=path,
    )
    assert code is ExitCode.ok
    assert plain.requests == [ROBOTS, PAGE_URL]
    assert plain_engine.renders == []
    assert "# Getting started" in capsys.readouterr().out


def test_render_mode_always_starts_at_the_browser(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FetchOneUrl guidance (e0f0c44): always starts the walk at the browser, no http try.

    The [fetch] key wins over the shared [crawl] one, key by key.
    """
    path = config(tmp_path, '[crawl]\nrender_mode = "never"\n' + ALWAYS)
    engine = FakeEngine({PAGE_URL: RENDERED})
    fetcher = site(SPA_SHELL)
    code = fetched(
        PAGE_URL,
        fetcher,
        tier_installed=installed(Tier.browser),
        engine=lambda: engine,
        config_path=path,
    )
    assert code is ExitCode.ok
    assert fetcher.requests == [ROBOTS, PAGE_URL]
    assert engine.renders == [PAGE_URL]
    assert RENDERED_HEADING in capsys.readouterr().out


def test_a_fetch_section_never_overrides_a_shared_always(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """[fetch] render_mode = "never" over [crawl]'s "always": http only, never refused.

    Nothing is installed, and the fetch is neither refused nor rendered.
    """
    path = config(tmp_path, '[crawl]\nrender_mode = "always"\n' + NEVER)
    fetcher = site(SPA_SHELL)
    assert fetched(PAGE_URL, fetcher, config_path=path) is ExitCode.ok
    assert fetcher.requests == [ROBOTS, PAGE_URL]
    assert RENDERED_HEADING not in capsys.readouterr().out


def test_a_named_tier_runs_that_tier_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FetchOneUrl guidance (e0f0c44): with --tier the walk runs that tier only.

    --tier browser under [fetch] render_mode = "never" renders; --tier http under
    "auto" never climbs, even for an SPA shell with the browser installed.
    """
    rendering = FakeEngine({PAGE_URL: RENDERED})
    fetcher = site(SPA_SHELL)
    code = fetched(
        PAGE_URL,
        fetcher,
        tier=Tier.browser,
        tier_installed=installed(Tier.browser),
        engine=lambda: rendering,
        config_path=config(tmp_path, NEVER, "never.toml"),
    )
    assert code is ExitCode.ok
    assert rendering.renders == [PAGE_URL]
    assert RENDERED_HEADING in capsys.readouterr().out
    unused = FakeEngine({PAGE_URL: RENDERED})
    fetcher = site(SPA_SHELL)
    code = fetched(
        PAGE_URL,
        fetcher,
        tier=Tier.http,
        tier_installed=installed(Tier.browser),
        engine=lambda: unused,
        config_path=config(tmp_path, AUTO, "auto.toml"),
    )
    assert code is ExitCode.ok
    assert fetcher.requests == [ROBOTS, PAGE_URL]
    assert unused.renders == []
    assert RENDERED_HEADING not in capsys.readouterr().out


def test_no_rovo_variable_reaches_a_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """rovo.allium resolve_fetch_config (e0f0c44): no ROVO_ variables, with or without --config.

    ROVO_CRAWL__RENDER_MODE="always" and an unknown ROVO_FETCH__ key in the environment
    change nothing: with nothing installed the fetch is neither refused nor rendered.
    """
    monkeypatch.setenv("ROVO_CRAWL__RENDER_MODE", '"always"')
    monkeypatch.setenv("ROVO_FETCH__RENDER_MODE", '"always"')
    monkeypatch.setenv("ROVO_FETCH__NONESUCH", "1")
    for path in (None, config(tmp_path, NEVER)):
        fetcher = site(SPA_SHELL)
        assert fetched(PAGE_URL, fetcher, config_path=path) is ExitCode.ok
        assert fetcher.requests == [ROBOTS, PAGE_URL]
        assert RENDERED_HEADING not in capsys.readouterr().out
    assert resolve_fetch_config(None).render_mode is RenderMode.never


# --- Guarantees: redirects --------------------------------------------------------------------


def redirected() -> FakeFetcher:
    """The page moved to a second host, mirror.example, whose robots.txt is absent."""
    return FakeFetcher(
        {
            ROBOTS: text_response(ROBOTS, ROBOTS_TEXT),
            PAGE_URL: redirect_response(PAGE_URL, MIRROR_PAGE),
            MIRROR_PAGE: html_response(MIRROR_PAGE, PAGE),
        }
    )


def test_with_config_its_scope_decides_the_redirects_followed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FetchOneUrl guidance (e0f0c44): --config's [scope] bounds redirects, by a sync's test.

    [scope] allows docs.example and mirror.example, so the page's redirect to
    mirror.example is followed (its robots.txt read first) and the page printed.
    """
    fetcher = redirected()
    path = config(tmp_path, SECOND_HOST_SCOPE)
    assert fetched(PAGE_URL, fetcher, config_path=path) is ExitCode.ok
    assert MIRROR_PAGE in fetcher.requests
    assert fetcher.requests.index(f"{MIRROR_SITE}/robots.txt") < fetcher.requests.index(
        MIRROR_PAGE
    )
    assert "# Getting started" in capsys.readouterr().out


def test_without_config_only_the_urls_own_host_is_followed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FetchOneUrl guidance (e0f0c44): without --config the scope is the URL's own host.

    The redirect to mirror.example is not followed: nothing is printed and the exit is 1.
    """
    fetcher = redirected()
    assert fetched(PAGE_URL, fetcher) is ExitCode.partial
    assert MIRROR_PAGE not in fetcher.requests
    assert capsys.readouterr().out == ""


# --- Guarantees: resolve_fetch_config and a sync's [fetch] --------------------------------


def test_resolve_fetch_config_layers_defaults_shared_sections_then_fetch(tmp_path: Path) -> None:
    """rovo.allium resolve_fetch_config (e0f0c44): defaults, then shared sections, then [fetch].

    With no file, the built-in defaults: valid, render_mode never. With one, its shared
    sections apply ([scope] allowed_hosts, [conversion] profile, [crawl] render_mode)
    and [fetch]'s render_mode and profile override theirs key by key.
    """
    defaults = resolve_fetch_config(None)
    assert defaults.valid
    assert defaults.problems == ()
    assert defaults.render_mode is RenderMode.never
    assert defaults.unblocking_provider is None
    shared = (
        '[scope]\nallowed_hosts = ["docs.example", "mirror.example"]\n'
        '[conversion]\nprofile = "generic"\n'
        '[crawl]\nrender_mode = "auto"\n'
    )
    settings = resolve_fetch_config(config(tmp_path, shared, "shared.toml"))
    assert settings.valid
    assert settings.allowed_hosts == frozenset({"docs.example", "mirror.example"})
    assert settings.profile_name == "generic"
    assert settings.render_mode is RenderMode.auto
    layered = resolve_fetch_config(
        config(tmp_path, shared + '[fetch]\nrender_mode = "always"\nprofile = "devsite"\n')
    )
    assert layered.valid
    assert layered.allowed_hosts == frozenset({"docs.example", "mirror.example"})
    assert layered.render_mode is RenderMode.always
    assert layered.profile_name == "devsite"


def test_a_syncs_configuration_accepts_and_ignores_a_fetch_section(tmp_path: Path) -> None:
    """rovo.allium (e0f0c44): a mirror's resolve_config accepts [fetch] and ignores it.

    A rovo.toml whose [fetch] asks for render_mode = "always" and profile = "devsite"
    is valid, and the sync's render_mode and profile are its own sections' and defaults.
    """
    (tmp_path / "rovo.toml").write_text(
        '[site]\nroot_url = "http://docs.example/guide/"\n'
        '[conversion]\nprofile = "generic"\n'
        '[fetch]\nrender_mode = "always"\nprofile = "devsite"\n',
        encoding="utf-8",
    )
    settings = resolve_config(tmp_path, {})
    assert settings.valid, settings.problems
    assert settings.render_mode is RenderMode.never
    assert settings.profile_name == "generic"


# --- Guarantees: what a fetch prints ----------------------------------------------------------


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
