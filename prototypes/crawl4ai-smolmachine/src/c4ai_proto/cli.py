"""PROTOTYPE command line: `c4ai vm up|status|down|destroy` and `c4ai fetch <url>`."""

import enum
import json
import secrets
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from smol import Machine, SmolError

from c4ai_proto import api, machine as m, state

app = typer.Typer(name="c4ai", no_args_is_help=True, add_completion=False)
vm = typer.Typer(no_args_is_help=True)
app.add_typer(vm, name="vm", help="Drive the crawl4AI microVM across invocations.")

StateDir = Annotated[Path | None, typer.Option("--state-dir", help="Where state.json lives.")]


class Filter(enum.StrEnum):
    """The Markdown filters ticket 03 offers."""

    raw = "raw"
    fit = "fit"


def _port(saved: dict | None, port: int | None) -> int:
    return port or (saved or {}).get("port") or m.GUEST_PORT


def _finish(mach: Machine | None, port: int, saved: dict | None, open_error: str | None = None) -> None:
    typer.echo("---- state ----")
    typer.echo(m.state_block(mach, port, bool((saved or {}).get("token")), open_error))


def _die(reason: object) -> NoReturn:
    """Exit 1 with a one-line reason on stderr."""
    typer.echo(f"error: {api.one_line(reason)}", err=True)
    raise typer.Exit(1)


def _fail(
    reason: object, mach: Machine | None, port: int, saved: dict | None, open_error: str | None = None
) -> NoReturn:
    """Report a failed vm command: the reason, the state block as far as it is known, exit 1."""
    typer.echo(f"error: {api.one_line(reason)}", err=True)
    _finish(mach, port, saved, open_error)
    raise typer.Exit(1)


def _open_or_fail(port: int, saved: dict | None) -> Machine | None:
    """The named machine or None; a failure to open it still ends with the state block."""
    try:
        return m.open_existing()
    except SmolError as exc:
        reason = api.one_line(exc)
        _fail(f"cannot open machine: {reason}", None, port, saved, reason)


@vm.command("up")
def vm_up(
    state_dir: StateDir = None,
    port: Annotated[int | None, typer.Option("--port", min=1, max=65535, help="Host port, used when creating.")] = None,
) -> None:
    """Create the machine, or reconnect to it, then wait for /health."""
    saved = state.load(state_dir)
    wanted = port
    port = _port(saved, wanted)
    mach = _open_or_fail(port, saved)
    reconnect = mach is not None and saved and saved.get("token")
    published = _port(saved, None)
    if reconnect and wanted is not None and wanted != published:
        msg = f"{m.MACHINE_NAME} publishes port {published}, not {wanted}; `c4ai vm destroy` to change it"
        _fail(msg, mach, published, saved)
    if mach is not None and not reconnect:
        # The registry is host-global but the state file is per checkout: never delete from here.
        msg = f"{m.MACHINE_NAME} exists but no token is saved here; `c4ai vm destroy` to replace it"
        _fail(msg, mach, port, saved)
    try:
        if reconnect:
            typer.echo(f"{m.MACHINE_NAME} exists ({mach.state()}); connecting")
            mach = m.connect_existing()
        else:
            token = secrets.token_hex(32)
            saved = {"machine": m.MACHINE_NAME, "port": port, "token": token, "image": m.IMAGE}
            typer.echo(f"state file: {state.save(saved, state_dir)}")
            typer.echo(f"creating {m.MACHINE_NAME} from {m.IMAGE} (pulls ~2.9 GB unless cached)")
            mach = m.create(token, port)
        typer.echo(f"state={mach.state()}; waiting for /health")
    except (SmolError, OSError) as exc:
        _fail(exc, mach, port, saved)
    try:
        m.wait_for_health(port)
    except TimeoutError as exc:
        _fail(exc, mach, port, saved)
    _finish(mach, port, saved)


@vm.command("status")
def vm_status(state_dir: StateDir = None) -> None:
    """Reopen the machine by name, without starting it, and print the state."""
    saved = state.load(state_dir)
    port = _port(saved, None)
    mach = _open_or_fail(port, saved)
    try:
        if mach is not None:
            mach.state()
            mach.endpoint(m.GUEST_PORT)
    except SmolError as exc:
        _fail(exc, mach, port, saved)
    _finish(mach, port, saved)


@vm.command("down")
def vm_down(state_dir: StateDir = None) -> None:
    """Stop the machine; its disk (and the pulled image) stays."""
    saved = state.load(state_dir)
    port = _port(saved, None)
    mach = _open_or_fail(port, saved)
    try:
        if mach is None:
            typer.echo("no machine to stop")
        elif mach.state() == "stopped":
            typer.echo("already stopped")
        else:
            mach.stop()
            typer.echo("stopped")
    except SmolError as exc:
        _fail(exc, mach, port, saved)
    _finish(mach, port, saved)


@vm.command("destroy")
def vm_destroy(state_dir: StateDir = None) -> None:
    """Delete the machine and its storage, and remove the state file."""
    saved = state.load(state_dir)
    port = _port(saved, None)
    mach = _open_or_fail(port, saved)
    try:
        if mach is None:
            typer.echo("no machine to delete")
        else:
            mach.delete()
            typer.echo("deleted")
    except SmolError as exc:
        _fail(exc, mach, port, saved)
    state.clear(state_dir)
    typer.echo(f"state file removed: {state.path(state_dir)}")
    try:
        typer.echo(f"registry: {[s.name for s in m.Machine.list(m.LOCAL)]}")
    except SmolError as exc:
        _fail(f"cannot list the registry: {exc}", None, port, None)
    _finish(None, port, None)


def _crawl_failure(result: dict[str, Any]) -> str | None:
    """Why a /crawl response holds no fetched page, or None when its first result succeeded."""
    results = result.get("results")
    if not result.get("success") or not results:
        return f"crawl returned no result: {result.get('error') or 'success is false or results empty'}"
    first = results[0]
    if not first.get("success"):
        return f"fetch failed: {first.get('error_message') or 'the result reports success=false'}"
    return None


@app.command("fetch")
def fetch(
    url: Annotated[str, typer.Argument(help="The page to fetch.")],
    filt: Annotated[Filter, typer.Option("--filter", help="The Markdown filter.")] = Filter.raw,
    as_json: Annotated[bool, typer.Option("--json", help="Print the full /crawl result.")] = False,
    out: Annotated[Path | None, typer.Option("-o", "--output", help="Write here instead of stdout.")] = None,
    state_dir: StateDir = None,
) -> None:
    """Print one page's Markdown (or its full crawl result with --json)."""
    saved = state.load(state_dir)
    if not saved or not saved.get("token"):
        _die("no state file; run `c4ai vm up` first")
    port = _port(saved, None)
    try:
        mach = m.open_existing()
        st = mach.state() if mach is not None else None
    except SmolError as exc:
        _die(f"cannot open machine: {exc}")
    if st != "running":
        _die(f"machine {m.MACHINE_NAME} is {st or 'absent'}, not running; run `c4ai vm up`")
    base = m.base_url(port)
    try:
        if as_json:
            result = api.crawl(base, saved["token"], url)
            failure = _crawl_failure(result)
            if failure:
                _die(failure)
            text = json.dumps(result, indent=2)
        else:
            result = api.markdown(base, saved["token"], url, filt.value)
            text = result.get("markdown")
            if not result.get("success") or not isinstance(text, str) or not text.strip():
                _die(f"fetch failed: {result.get('error') or 'no Markdown in the response'}")
    except api.ApiError as exc:
        _die(exc)
    if out:
        try:
            out.write_text(text, encoding="utf-8")
        except OSError as exc:
            _die(f"cannot write {out}: {exc}")
    else:
        typer.echo(text)
