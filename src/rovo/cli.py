"""The rovo command line. It imports the API; the API never imports it."""

from typing import Annotated

import typer

import rovo

app = typer.Typer(name="rovo", no_args_is_help=True, add_completion=False)


def _print_version(*, requested: bool) -> None:
    """Print the version line and exit 0, when --version was given."""
    if requested:
        typer.echo(f"rovo {rovo.__version__}")
        raise typer.Exit


@app.callback()
def main(
    *,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print the version and exit.",
            is_eager=True,
            callback=lambda value: _print_version(requested=value),
        ),
    ] = False,
) -> None:
    """rovo: a Python API and the rovo command."""
    del version  # The eager callback has already acted on it.


@app.command("version")
def version_command() -> None:
    """Print the version."""
    typer.echo(f"rovo {rovo.__version__}")
