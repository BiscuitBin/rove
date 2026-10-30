"""The command line: in-process through CliRunner, and out of process as installed."""

import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer import rich_utils
from typer.testing import CliRunner

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
