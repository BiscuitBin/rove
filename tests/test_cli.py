"""The command line: in-process through CliRunner, and out of process as installed."""

import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer import rich_utils
from typer.testing import CliRunner

from rovo._exit import ExitCode
from rovo.cli import app

# Click's exit status for a usage error, and Typer's for `no_args_is_help`.
USAGE_ERROR = 2


@pytest.fixture(autouse=True)
def plain_help_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Help prints as plain text, whatever the environment says about colour.

    Typer forces a terminal, ANSI codes and boxes, when GITHUB_ACTIONS,
    FORCE_COLOR or PY_COLORS is set, read once at import into FORCE_TERMINAL,
    which every help console reads when it is built; rich reads FORCE_COLOR
    itself unless that value is False. False is what Typer's own
    _TYPER_FORCE_DISABLE_TERMINAL sets, so a CI runner prints what a local run
    prints. If Typer renames the attribute, setattr raises and the tests fail.
    """
    monkeypatch.setattr(rich_utils, "FORCE_TERMINAL", False)


def runner() -> CliRunner:
    """A runner whose output does not wrap with the caller's terminal width.

    Typer's rich output reads COLUMNS and TERMINAL_WIDTH; a narrow terminal
    would otherwise wrap the lines these tests look for.
    """
    return CliRunner(env={"COLUMNS": "200", "TERMINAL_WIDTH": "200"})


def version_line() -> str:
    """The line both version spellings print, from the installed metadata."""
    return f"rovo {importlib.metadata.version('rovo')}\n"


@pytest.mark.parametrize("args", [["--version"], ["version"]])
def test_version_prints_the_installed_version(args: list[str]) -> None:
    """Both spellings print `rovo <version>` and exit 0."""
    result = runner().invoke(app, args, prog_name="rovo")

    assert result.exit_code == 0, result.output
    assert result.stdout == version_line()
    assert result.stderr == ""


def test_help_lists_the_option_and_the_command() -> None:
    """`--help` prints usage naming `--version` and `version`, and exits 0."""
    result = runner().invoke(app, ["--help"], prog_name="rovo")

    assert result.exit_code == 0, result.output
    assert "Usage: rovo [OPTIONS] COMMAND [ARGS]..." in result.stdout
    assert "--version" in result.stdout
    assert "Print the version." in result.stdout
    assert result.stderr == ""


def test_no_arguments_prints_help_and_exits_2() -> None:
    """Bare `rovo` prints the help on stdout and exits 2, as `no_args_is_help` does."""
    result = runner().invoke(app, [], prog_name="rovo")

    assert result.exit_code == USAGE_ERROR, result.output
    assert "Usage: rovo [OPTIONS] COMMAND [ARGS]..." in result.stdout
    assert result.stderr == ""


def test_unknown_command_is_a_usage_error_on_stderr() -> None:
    """An unknown command exits 2 and names itself on stderr, printing nothing on stdout."""
    result = runner().invoke(app, ["no-such-command"], prog_name="rovo")

    assert result.exit_code == USAGE_ERROR, result.output
    assert "No such command 'no-such-command'." in result.stderr
    assert result.stdout == ""


def run_version(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run `<command> --version` out of process, without a shell."""
    return subprocess.run(
        [*command, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_console_script_prints_the_version() -> None:
    """The `rovo` script installed beside this interpreter prints the version line."""
    script = shutil.which("rovo", path=str(Path(sys.executable).parent))
    assert script is not None, f"no rovo console script beside {sys.executable}"

    result = run_version([script])

    assert result.returncode == 0, result.stderr
    assert result.stdout == version_line()


def test_python_m_rovo_prints_the_version() -> None:
    """`python -I -m rovo` prints the version line."""
    result = run_version([sys.executable, "-I", "-m", "rovo"])

    assert result.returncode == 0, result.stderr
    assert result.stdout == version_line()


@pytest.mark.parametrize(
    ("command", "arguments"),
    [
        ("init", ("SITE_URL", "OUT_DIR", "--profile")),
        # T13: --dry-run; T16: --yes, --json, --url, --path and --set.
        ("sync", ("OUT_DIR", "--dry-run", "--yes", "--json", "--url", "--path", "--set")),
        ("index", ("OUT_DIR",)),
        ("report", ("OUT_DIR",)),  # T16
    ],
)
def test_mirror_commands_have_help(command: str, arguments: tuple[str, ...]) -> None:
    """`rovo init`, `sync`, `index` and `report --help` name their arguments and options."""
    result = runner().invoke(app, [command, "--help"], prog_name="rovo")

    assert result.exit_code == 0, result.output
    assert f"Usage: rovo {command}" in result.stdout
    for argument in arguments:
        assert argument in result.stdout


@pytest.mark.parametrize("command", ["init", "sync", "index", "report"])
def test_mirror_commands_without_arguments_are_usage_errors(command: str) -> None:
    """`rovo init`, `sync`, `index` and `report` with no arguments exit 2, usage on stderr."""
    result = runner().invoke(app, [command], prog_name="rovo")

    assert result.exit_code == USAGE_ERROR, result.output
    assert "Missing argument" in result.stderr


# --- rovo index (T11) ---------------------------------------------------------------

UNUSED_URL = "http://127.0.0.1:9/guide/start.html"  # init makes no request
# Runs one command of rovo.cli in a fresh interpreter and prints its exit code and
# whether httpx and rovo._crawl were loaded.
MODULES_PROBE = """
import json, sys
from typer.testing import CliRunner
from rovo.cli import app
result = CliRunner().invoke(app, sys.argv[1:])
print(json.dumps([result.exit_code, "httpx" in sys.modules, "rovo._crawl" in sys.modules]))
"""


def initialised(out_dir: Path) -> Path:
    """`rovo init` through CliRunner; it exits 0."""
    result = runner().invoke(app, ["init", UNUSED_URL, str(out_dir)], prog_name="rovo")
    assert result.exit_code == 0, result.output
    return out_dir


def test_index_rebuilds_an_initialised_mirror(tmp_path: Path) -> None:
    """`rovo index OUT_DIR` on a mirror exits 0 and writes the index files."""
    out_dir = initialised(tmp_path / "out")
    result = runner().invoke(app, ["index", str(out_dir)], prog_name="rovo")

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    for name in ("index.md", "index.jsonl", "links.jsonl", "llms.txt"):
        assert (out_dir / name).is_file(), name


def test_index_without_a_mirror_exits_2(tmp_path: Path) -> None:
    """`rovo index` on a directory holding no mirror exits 2 and says so on stderr."""
    result = runner().invoke(app, ["index", str(tmp_path)], prog_name="rovo")

    assert result.exit_code == USAGE_ERROR, result.output
    assert result.stderr.startswith("rovo: index: ")
    assert "No such command" not in result.stderr
    assert list(tmp_path.iterdir()) == []


def probe_modules(*args: str) -> list[object]:
    """[exit code, httpx loaded, rovo._crawl loaded] after one command, out of process."""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", MODULES_PROBE, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    loaded = json.loads(completed.stdout)
    assert isinstance(loaded, list)
    return loaded


def test_index_loads_neither_httpx_nor_the_crawl(tmp_path: Path) -> None:
    """`rovo index` imports nothing for fetching; `rovo sync`, the positive control, does."""
    out_dir = initialised(tmp_path / "out")
    assert probe_modules("index", str(out_dir)) == [0, False, False]
    assert probe_modules("sync", str(tmp_path / "missing")) == [USAGE_ERROR, True, True]


# --- rovo sync's options and rovo report (T16) ----------------------------------------------

SEED_URL = "http://127.0.0.1:9/guide/start.html"
WRITTEN_REPORT = {"report_status": "finished", "run_id": 1}


def recording_sync(monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, object]]) -> None:
    """Replace rovo._commands.sync: record its keywords, raise one progress event, exit ok."""
    from rovo import _commands  # noqa: PLC0415  The module the command imports at run time.
    from rovo._crawl.model import ProgressEvent  # noqa: PLC0415  Only a sync loads the crawl.

    def fake(out_dir: Path, **keywords: object) -> ExitCode:
        calls.append({"out_dir": out_dir, **keywords})
        progress = keywords.get("progress")
        if callable(progress):
            progress(ProgressEvent(event="done", host=None, until=None))
        return ExitCode.ok

    monkeypatch.setattr(_commands, "sync", fake)


def test_sync_passes_its_options_to_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--yes, --json, --url, --path (each repeatable) and --set reach rovo._commands.sync.

    Under --json the progress sink prints each event as one JSON line on standard output.
    """
    calls: list[dict[str, object]] = []
    recording_sync(monkeypatch, calls)
    out_dir = tmp_path / "out"
    arguments = [
        "sync",
        str(out_dir),
        "--yes",
        "--json",
        "--url",
        SEED_URL,
        "--url",
        "http://127.0.0.1:9/guide/b.html",
        "--path",
        "pages/127.0.0.1_9/start.md",
        "--set",
        "scope.max_depth=3",
        "--set",
        "mirror.prune=true",
    ]
    result = runner().invoke(app, arguments, prog_name="rovo")

    assert result.exit_code == 0, result.output
    (call,) = calls
    assert call["out_dir"] == out_dir
    assert call["confirmed"] is True
    assert call["json_events"] is True
    assert strings(call["urls"]) == (SEED_URL, "http://127.0.0.1:9/guide/b.html")
    assert strings(call["paths"]) == ("pages/127.0.0.1_9/start.md",)
    assert strings(call["overrides"]) == ("scope.max_depth=3", "mirror.prune=true")
    assert callable(call["progress"])
    # Re-propagated by the T16 follow-up (origin T16): each line gains url (9a253a4).
    assert [json.loads(line) for line in result.stdout.splitlines()] == [
        {"event": "done", "host": None, "until": None, "url": None}
    ]


def test_sync_without_options_asks_for_nothing_and_prints_no_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without --json there is no sink and nothing on standard output; no option is set."""
    calls: list[dict[str, object]] = []
    recording_sync(monkeypatch, calls)
    result = runner().invoke(app, ["sync", str(tmp_path)], prog_name="rovo")

    assert result.exit_code == 0, result.output
    (call,) = calls
    assert call.get("confirmed", False) is False
    assert call.get("json_events", False) is False
    assert call.get("progress") is None
    assert strings(call.get("urls", ())) == ()
    assert strings(call.get("paths", ())) == ()
    assert strings(call.get("overrides", ())) == ()
    assert result.stdout == ""


def strings(value: object) -> tuple[str, ...]:
    """A sequence the fake recorded, as a tuple of strings."""
    assert isinstance(value, (list, tuple))
    return tuple(str(item) for item in value)


def with_report(out_dir: Path) -> Path:
    """An initialised mirror holding a crawl-report.json."""
    initialised(out_dir)
    (out_dir / "crawl-report.json").write_text(
        json.dumps(WRITTEN_REPORT, indent=1) + "\n", encoding="utf-8"
    )
    return out_dir


def test_report_prints_the_last_report(tmp_path: Path) -> None:
    """`rovo report OUT_DIR` prints crawl-report.json as JSON and exits 0."""
    out_dir = with_report(tmp_path / "out")
    result = runner().invoke(app, ["report", str(out_dir)], prog_name="rovo")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == WRITTEN_REPORT
    assert result.stderr == ""


def test_report_without_a_report_exits_2(tmp_path: Path) -> None:
    """`rovo report` on a mirror with no report exits 2, nothing on standard output."""
    out_dir = initialised(tmp_path / "out")
    result = runner().invoke(app, ["report", str(out_dir)], prog_name="rovo")

    assert result.exit_code == USAGE_ERROR, result.output
    assert result.stdout == ""
    assert result.stderr.startswith("rovo: report: ")


def test_report_runs_through_the_installed_script(tmp_path: Path) -> None:
    """The installed `rovo` script runs `rovo report` and prints the report."""
    script = shutil.which("rovo", path=str(Path(sys.executable).parent))
    assert script is not None, f"no rovo console script beside {sys.executable}"
    out_dir = with_report(tmp_path / "out")
    completed = subprocess.run(
        [script, "report", str(out_dir)], capture_output=True, text=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == WRITTEN_REPORT


def test_report_loads_neither_httpx_nor_the_crawl(tmp_path: Path) -> None:
    """`rovo report` reads the report with rovo._mirror.state alone, like `rovo index`."""
    out_dir = with_report(tmp_path / "out")
    assert probe_modules("report", str(out_dir)) == [0, False, False]
