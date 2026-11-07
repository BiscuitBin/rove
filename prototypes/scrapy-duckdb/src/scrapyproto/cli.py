"""PROTOTYPE command line: a placeholder until ticket 02 adds the `vm` group."""

import typer

app = typer.Typer(name="scrapyproto", no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """PROTOTYPE: Scrapy in a smol microVM, pages in DuckDB. Throwaway."""


@app.command()
def where() -> None:
    """Print the machine name and the state file path; touches nothing."""
    from scrapyproto import machine as m, state

    typer.echo(f"machine: {m.MACHINE_NAME}")
    typer.echo(f"state:   {state.path()}")
