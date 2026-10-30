"""The command line: `rovo --version` and `rovo version`."""

import importlib.metadata

import pytest
from typer.testing import CliRunner

from rovo.cli import app


@pytest.mark.parametrize("args", [["--version"], ["version"]])
def test_version_prints_the_installed_version(args: list[str]) -> None:
    """Both spellings print `rovo <version>` and exit 0."""
    result = CliRunner().invoke(app, args, prog_name="rovo")

    assert result.exit_code == 0, result.output
    assert result.output == f"rovo {importlib.metadata.version('rovo')}\n"
