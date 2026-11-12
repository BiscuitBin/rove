"""The smol wrapper: constants, create/open/connect, the Scrapy install and the state block.

Nothing here deletes a machine, and nothing uses a `with` block: `Machine.__exit__` deletes.
The one delete is `vm destroy` in `cli.py`.
"""

from pathlib import Path
from typing import Any

from smol import ConnectOptions, ExecOptions, Machine, MachineConfig, ResourceSpec, SmolError

from scrapyproto import state

MACHINE_NAME = "scrapy-proto"
IMAGE = "python:3.12"
SCRAPY_VERSION = "2.20.0"  # A guest pin, never a host dependency.
DUCKDB_VERSION = "2.0.0"  # Ticket 05's guest pin: the host's, from uv.lock, so both read one file format.
# Without target="local" the SDK may address the cloud.
LOCAL = ConnectOptions(target="local")
# Explicit: the engine's defaults are 4 vCPU, 8 GiB, 20 GiB storage and a 10 GiB overlay, and
# the guest disk must hold the HTTP cache and the feeds.
RESOURCES = ResourceSpec(network=True, cpus=4, memory_mb=4096, storage_gb=20, overlay_gb=10)
INSTALL_TIMEOUT_S = 600.0
CHECK_TIMEOUT_S = 60.0
# Written to the machine and the state file at create: the name alone cannot tell a replacement.
GENERATION_LABEL = "scrapyproto-generation"


class ProtoError(RuntimeError):
    """A refusal or failure the prototype itself detected."""


def one_line(reason: object) -> str:
    return " ".join(str(reason).split())


def create(generation: str | None = None) -> Machine:
    """Create and boot the machine; returns once the guest agent is up. Raises if the name is taken."""
    config = MachineConfig(
        name=MACHINE_NAME,
        image=IMAGE,
        labels={GENERATION_LABEL: generation} if generation else None,
        resources=RESOURCES,
        persistent=True,
        detach=True,
        ready_timeout_seconds=900,
    )
    return Machine.create(config, LOCAL)


def open_existing() -> Machine | None:
    """A handle to the named machine without starting it, or None when there is none."""
    try:
        return Machine.open(MACHINE_NAME, LOCAL)
    except SmolError as exc:
        if exc.code == "NOT_FOUND":
            return None
        raise


def owned(saved: dict[str, Any] | None) -> bool:
    """Whether a loaded state file records the generation this name holds now; unknown is not owned.

    Absent on both sides means ticket 01's machine and its state file, made before the label.
    """
    if saved is None or saved.get("machine") != MACHINE_NAME:
        return False
    try:
        found = [s.labels.get(GENERATION_LABEL) for s in Machine.list(LOCAL) if s.name == MACHINE_NAME]
    except SmolError:
        return False
    return found == [saved.get("generation")]


def connect_existing(state_dir: Path | None = None) -> Machine:
    """Reopen the named machine, starting it if stopped; never one this checkout does not own."""
    if not owned(state.load(state_dir)):
        msg = (
            f"{MACHINE_NAME}: no state file at {state.path(state_dir)} records this machine, "
            "another checkout's? Refusing to connect."
        )
        raise ProtoError(msg)
    return connect_owned()


def connect_owned() -> Machine:
    """Attach to the named machine, starting it if stopped; callers have checked `owned`."""
    return Machine.connect(MACHINE_NAME, LOCAL)


def scrapy_version(mach: Machine) -> str:
    """The Scrapy version the guest reports; raises when it cannot report one."""
    r = mach.exec(["scrapy", "version"], ExecOptions(timeout=CHECK_TIMEOUT_S))
    if r.exit_code != 0:
        msg = f"`scrapy version` exited {r.exit_code}: {(r.stderr or r.stdout).strip()[-200:]}"
        raise ProtoError(msg)
    return r.stdout.strip().removeprefix("Scrapy ")


def install_scrapy(mach: Machine) -> str:
    """Ladder rung 1: pip-install the pin onto the machine's disk. Returns pip's output tail."""
    argv = ["pip", "install", "--no-input", "--root-user-action=ignore", f"scrapy=={SCRAPY_VERSION}"]
    r = mach.exec(argv, ExecOptions(timeout=INSTALL_TIMEOUT_S))
    if r.exit_code != 0:
        msg = f"pip exited {r.exit_code}: {(r.stderr or r.stdout).strip()[-800:]}"
        raise ProtoError(msg)
    return r.stdout.strip()[-800:]


def duckdb_version(mach: Machine) -> str | None:
    """The DuckDB version the guest's Python imports, or None when it has none (ticket 05's per-item path)."""
    r = mach.exec(["python", "-c", "import duckdb; print(duckdb.__version__)"], ExecOptions(timeout=CHECK_TIMEOUT_S))
    return r.stdout.strip() if r.exit_code == 0 else None


def install_duckdb(mach: Machine) -> str:
    """Ticket 05: pip-install the host's DuckDB pin onto the machine's disk. Reaches the network."""
    argv = ["pip", "install", "--no-input", "--root-user-action=ignore", f"duckdb=={DUCKDB_VERSION}"]
    r = mach.exec(argv, ExecOptions(timeout=INSTALL_TIMEOUT_S))
    if r.exit_code != 0:
        msg = f"pip exited {r.exit_code}: {(r.stderr or r.stdout).strip()[-800:]}"
        raise ProtoError(msg)
    return r.stdout.strip()[-2000:]


def state_block(mach: Machine | None, open_error: str | None = None, state_dir: Path | None = None) -> str:
    """The full state, printed at the end of every command; every field is always present."""
    lines = [f"machine:    {MACHINE_NAME}"]
    running = False
    if open_error:
        lines.append(f"state:      error: {one_line(open_error)}")
    elif mach is None:
        lines.append("state:      (no machine)")
    else:
        try:
            current = mach.state()
        except SmolError as exc:
            lines.append(f"state:      error: {one_line(exc)}")
        else:
            running = current == "running"
            lines.append(f"state:      {current}")
    if running and owned(state.load(state_dir)):
        try:
            # A fresh process's `open` handle cannot exec ("expected started, got not started"), so
            # this one call attaches: only to a machine this checkout owns, only when running. A stop
            # landing between the state read above and here makes this connect boot it; the SDK has
            # no attach that does not start, and the README states the limit.
            lines.append(f"scrapy:     {scrapy_version(connect_owned())}")
        except (SmolError, ProtoError) as exc:
            lines.append(f"scrapy:     error: {one_line(exc)}")
    elif running:
        lines.append("scrapy:     unknown (not this checkout's machine, so not attached)")
    else:
        lines.append("scrapy:     unknown (the machine is not running)")
    present = "present" if state.path(state_dir).exists() else "absent"
    lines.append(f"state file: {present} ({state.path(state_dir)})")
    return "\n".join(lines)
