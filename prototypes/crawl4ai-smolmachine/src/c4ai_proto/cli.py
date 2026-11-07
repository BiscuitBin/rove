"""PROTOTYPE command line: `c4ai vm up|status|down|destroy` and `c4ai fetch <url>`."""

import json
import secrets
from pathlib import Path
from typing import Annotated

import typer
from smol import SmolError

from c4ai_proto import api, machine as m, state

app = typer.Typer(name="c4ai", no_args_is_help=True, add_completion=False)
vm = typer.Typer(no_args_is_help=True)
app.add_typer(vm, name="vm", help="Drive the crawl4AI microVM across invocations.")

StateDir = Annotated[Path | None, typer.Option("--state-dir", help="Where state.json lives.")]


def _port(saved: dict | None, port: int | None) -> int:
    return port or (saved or {}).get("port") or m.GUEST_PORT


def _finish(mach, port: int, saved: dict | None) -> None:
    typer.echo("---- state ----")
    typer.echo(m.state_block(mach, port, bool((saved or {}).get("token"))))


@vm.command("up")
def vm_up(
    state_dir: StateDir = None,
    port: Annotated[int | None, typer.Option("--port", help="Host port for the API.")] = None,
) -> None:
    """Create the machine, or reconnect to it, then wait for /health."""
    saved = state.load(state_dir)
    port = _port(saved, port)
    mach = m.open_existing()
    if mach is not None and saved and saved.get("token"):
        typer.echo(f"{m.MACHINE_NAME} exists ({mach.state()}); connecting")
        mach = m.connect_existing()
    else:
        if mach is not None:
            typer.echo(f"{m.MACHINE_NAME} exists but no token is saved; deleting and recreating")
            mach.delete()
        token = secrets.token_hex(32)
        saved = {"machine": m.MACHINE_NAME, "port": port, "token": token, "image": m.IMAGE}
        typer.echo(f"state file: {state.save(saved, state_dir)}")
        typer.echo(f"creating {m.MACHINE_NAME} from {m.IMAGE} (first start pulls ~2.9 GB)")
        mach = m.create(token, port)
    typer.echo(f"state={mach.state()}; waiting for /health")
    try:
        m.wait_for_health(port)
    except TimeoutError as exc:
        typer.echo(f"error: {exc}", err=True)
        _finish(mach, port, saved)
        raise typer.Exit(1) from exc
    _finish(mach, port, saved)


@vm.command("status")
def vm_status(state_dir: StateDir = None) -> None:
    """Reopen the machine by name, without starting it, and print the state."""
    saved = state.load(state_dir)
    _finish(m.open_existing(), _port(saved, None), saved)


@vm.command("down")
def vm_down(state_dir: StateDir = None) -> None:
    """Stop the machine; its disk (and the pulled image) stays."""
    saved = state.load(state_dir)
    mach = m.open_existing()
    if mach is None:
        typer.echo("no machine to stop")
    elif mach.state() == "stopped":
        typer.echo("already stopped")
    else:
        mach.stop()
        typer.echo("stopped")
    _finish(mach, _port(saved, None), saved)


@vm.command("destroy")
def vm_destroy(state_dir: StateDir = None) -> None:
    """Delete the machine and its storage, and remove the state file."""
    saved = state.load(state_dir)
    mach = m.open_existing()
    if mach is None:
        typer.echo("no machine to delete")
    else:
        mach.delete()
        typer.echo("deleted")
    state.clear(state_dir)
    typer.echo(f"state file removed: {state.path(state_dir)}")
    typer.echo(f"registry: {[s.name for s in m.Machine.list(m.LOCAL)]}")
    _finish(None, _port(saved, None), None)


@app.command("fetch")
def fetch(
    url: Annotated[str, typer.Argument(help="The page to fetch.")],
    filt: Annotated[str, typer.Option("--filter", help="raw or fit.")] = "raw",
    as_json: Annotated[bool, typer.Option("--json", help="Print the full /crawl result.")] = False,
    out: Annotated[Path | None, typer.Option("-o", "--output", help="Write here instead of stdout.")] = None,
    state_dir: StateDir = None,
) -> None:
    """Print one page's Markdown (or its full crawl result with --json)."""
    saved = state.load(state_dir)
    if not saved or not saved.get("token"):
        typer.echo("error: no state file; run `c4ai vm up` first", err=True)
        raise typer.Exit(1)
    port = _port(saved, None)
    try:
        mach = m.open_existing()
        st = mach.state() if mach is not None else None
    except SmolError as exc:
        typer.echo(f"error: cannot open machine: {exc}", err=True)
        raise typer.Exit(1) from exc
    if st != "running":
        typer.echo(f"error: machine {m.MACHINE_NAME} is {st or 'absent'}, not running; run `c4ai vm up`", err=True)
        raise typer.Exit(1)
    base = m.base_url(port)
    try:
        if as_json:
            text = json.dumps(api.crawl(base, saved["token"], url), indent=2)
        else:
            result = api.markdown(base, saved["token"], url, filt)
            if not result.get("success") or result.get("markdown") is None:
                typer.echo(f"error: fetch failed: {result}", err=True)
                raise typer.Exit(1)
            text = result["markdown"]
    except api.ApiError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if out:
        out.write_text(text)
    else:
        typer.echo(text)
