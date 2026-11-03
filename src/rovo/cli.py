"""The rovo command line. It imports the API; the API never imports it.

Each mirror command imports the private modules inside its own body, so `rovo --version`
loads no runtime dependency beyond typer.
"""

from pathlib import Path
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


@app.command("init")
def init_command(
    site_url: Annotated[
        str, typer.Argument(metavar="SITE_URL", help="The documentation page to start from.")
    ],
    out_dir: Annotated[
        Path, typer.Argument(metavar="OUT_DIR", help="The directory the mirror is made in.")
    ],
    profile: Annotated[
        str | None,
        typer.Option("--profile", help="A catalogue profile; by default the URL's host picks."),
    ] = None,
) -> None:
    """Create a mirror: write rovo.toml and an empty manifest. Nothing is fetched."""
    from rovo import _commands  # noqa: PLC0415  Loaded only when the command runs.

    raise typer.Exit(_commands.init(site_url, out_dir, profile).number)


@app.command("sync")
def sync_command(
    out_dir: Annotated[Path, typer.Argument(metavar="OUT_DIR", help="The mirror's directory.")],
) -> None:
    """Fetch the mirror's pages, publish them as Markdown and write crawl-report.json."""
    from rovo import _commands  # noqa: PLC0415  Loaded only when the command runs.
    from rovo._crawl.fetch import HttpxFetcher  # noqa: PLC0415  Loaded only when the command runs.
    from rovo._mirror.state import SystemClock  # noqa: PLC0415  Loaded only when the command runs.

    with HttpxFetcher() as fetcher:
        code = _commands.sync(out_dir, fetcher=fetcher, clock=SystemClock())
    raise typer.Exit(code.number)
