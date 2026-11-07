"""PROTOTYPE command line: `scrapyproto vm up|status|down|destroy`, each a fresh process."""

import secrets
import time
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from smol import Machine, SmolError

from scrapyproto import machine as m, state

app = typer.Typer(name="scrapyproto", no_args_is_help=True, add_completion=False)
vm = typer.Typer(no_args_is_help=True)
app.add_typer(vm, name="vm", help="Drive the Scrapy microVM across invocations.")

StateDir = Annotated[Path | None, typer.Option("--state-dir", help="Where state.json lives.")]

NOT_OURS = (
    f"{m.MACHINE_NAME} exists but no state file here records this machine (another checkout's?); "
    "nothing touched; `scrapyproto vm destroy` deletes it"
)


@app.callback()
def main() -> None:
    """PROTOTYPE: Scrapy in a smol microVM, pages in DuckDB. Throwaway."""


def _one_line(reason: object) -> str:
    return " ".join(str(reason).split())


def _finish(state_dir: Path | None, *, failing: bool = False) -> None:
    """Print the state block, read afresh by name; an error in any field is a failed command."""
    try:
        block = m.state_block(m.open_existing(), state_dir=state_dir)
    except SmolError as exc:
        block = m.state_block(None, _one_line(exc), state_dir)
    fields = [line.split(":", 1)[-1].strip() for line in block.splitlines()]
    errors = [field for field in fields if field.startswith("error:")]
    if errors and not failing:
        typer.echo(_one_line(errors[0]), err=True)
    typer.echo("---- state ----")
    typer.echo(block)
    if errors or failing:
        raise typer.Exit(1)


def _fail(reason: object, state_dir: Path | None) -> NoReturn:
    """Report a failed vm command: the reason, the state block as far as it is known, exit 1."""
    typer.echo(f"error: {_one_line(reason)}", err=True)
    _finish(state_dir, failing=True)
    raise typer.Exit(1)


def _open_or_fail(state_dir: Path | None) -> Machine | None:
    """The named machine without starting it, or None; a failure still ends with the state block."""
    try:
        return m.open_existing()
    except SmolError as exc:
        _fail(f"cannot open machine: {exc}", state_dir)


def _create(state_dir: Path | None) -> None:
    """First create: boot, claim the name in the state file, install Scrapy. Reaches the network."""
    typer.echo(f"creating {m.MACHINE_NAME} from {m.IMAGE} (image pull and pip install: network)")
    t0 = time.monotonic()
    generation = secrets.token_hex(16)
    mach = m.create(generation)
    # Only after create returns: a create that failed or lost the name claims nothing.
    saved: dict[str, Any] = {
        "machine": m.MACHINE_NAME,
        "generation": generation,
        "image": m.IMAGE,
        "scrapy": m.SCRAPY_VERSION,
        "rung": None,
    }
    state.save(saved, state_dir)
    typer.echo(f"[time] create to {mach.state()}: {time.monotonic() - t0:.2f}s")
    t0 = time.monotonic()
    m.install_scrapy(mach)
    typer.echo(f"[time] pip install: {time.monotonic() - t0:.2f}s")
    _require_pin(mach)
    state.save({**saved, "rung": "1: python:3.12 plus pip install"}, state_dir)


def _reconnect(state_dir: Path | None, was: str) -> None:
    """Start or reattach, then check Scrapy with `exec`. Never installs: that is first create only."""
    typer.echo(f"{m.MACHINE_NAME} exists ({was}); connecting")
    t0 = time.monotonic()
    mach = m.connect_existing(state_dir)
    now = mach.state()
    typer.echo(f"[time] {was} to {now}: {time.monotonic() - t0:.2f}s")
    if now != "running":
        msg = f"{m.MACHINE_NAME} is {now} after connect, not running"
        raise RuntimeError(msg)
    t0 = time.monotonic()
    _require_pin(mach)
    typer.echo(f"[time] scrapy check, no pip run: {time.monotonic() - t0:.2f}s")


def _require_pin(mach: Machine) -> None:
    """The guest must report the pin: a lost installation fails here rather than being repaired."""
    try:
        version = m.scrapy_version(mach)
    except RuntimeError as exc:
        msg = f"scrapy check failed: {exc}; `vm up` installs on first create only, so `vm destroy` then `vm up`"
        raise RuntimeError(msg) from exc
    if version != m.SCRAPY_VERSION:
        msg = f"guest has scrapy {version}, the pin is {m.SCRAPY_VERSION}"
        raise RuntimeError(msg)


@vm.command("up")
def vm_up(state_dir: StateDir = None) -> None:
    """Create the machine, or reconnect to it; idempotent, never deletes."""
    saved = state.load(state_dir)
    mach = _open_or_fail(state_dir)
    if mach is not None and not m.owned(saved):
        # The registry is host-global but the state file is per checkout: report, never delete.
        _fail(NOT_OURS, state_dir)
    try:
        if mach is None:
            _create(state_dir)
        else:
            _reconnect(state_dir, mach.state())
    except (SmolError, RuntimeError, OSError) as exc:
        _fail(exc, state_dir)
    _finish(state_dir)


@vm.command("status")
def vm_status(state_dir: StateDir = None) -> None:
    """Reopen the machine by name, without starting it, and print the state."""
    saved = state.load(state_dir)
    mach = _open_or_fail(state_dir)
    try:
        if mach is not None:
            mach.state()
    except SmolError as exc:
        _fail(exc, state_dir)
    if mach is not None and not m.owned(saved):
        typer.echo(NOT_OURS)
    _finish(state_dir)


@vm.command("down")
def vm_down(state_dir: StateDir = None) -> None:
    """Stop the machine; its disk stays. A stop kills whatever is running in the guest."""
    saved = state.load(state_dir)
    mach = _open_or_fail(state_dir)
    if mach is not None and not m.owned(saved):
        # A stop kills whatever runs in the guest, maybe another checkout's: report, never stop.
        _fail(NOT_OURS, state_dir)
    try:
        if mach is None:
            typer.echo("no machine to stop")
        elif mach.state() == "stopped":
            typer.echo("already stopped")
        else:
            t0 = time.monotonic()
            mach.stop()
            typer.echo(f"[time] stop: {time.monotonic() - t0:.2f}s")
    except SmolError as exc:
        _fail(exc, state_dir)
    _finish(state_dir)


@vm.command("destroy")
def vm_destroy(state_dir: StateDir = None) -> None:
    """Delete the machine and its disk, and remove the state file; works with no state file."""
    mach = _open_or_fail(state_dir)
    try:
        if mach is None:
            typer.echo("no machine to delete")
        else:
            mach.delete()
            typer.echo("deleted")
        state.clear(state_dir)
        typer.echo(f"state file removed: {state.path(state_dir)}")
        typer.echo(f"registry: {[s.name for s in Machine.list(m.LOCAL)]}")
    except (SmolError, OSError) as exc:
        _fail(exc, state_dir)
    _finish(state_dir)
