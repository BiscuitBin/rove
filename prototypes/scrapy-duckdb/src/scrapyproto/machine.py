"""The smol wrapper: constants, create/open/connect, the Scrapy install and the state block.

Nothing here deletes a machine, and nothing uses a `with` block: `Machine.__exit__` deletes.
"""

from smol import ConnectOptions, ExecOptions, Machine, MachineConfig, ResourceSpec, SmolError

from scrapyproto import state

MACHINE_NAME = "scrapy-proto"
IMAGE = "python:3.12"
SCRAPY_VERSION = "2.20.0"  # A guest pin, never a host dependency.
# Without target="local" the SDK may address the cloud.
LOCAL = ConnectOptions(target="local")
# Explicit: the engine's defaults are 4 vCPU, 8 GiB, 20 GiB storage and a 10 GiB overlay, and
# the guest disk must hold the HTTP cache and the feeds.
RESOURCES = ResourceSpec(network=True, cpus=4, memory_mb=4096, storage_gb=20, overlay_gb=10)
INSTALL_TIMEOUT_S = 600.0
CHECK_TIMEOUT_S = 60.0


def create() -> Machine:
    """Create and boot the machine; returns once the guest agent is up. Raises if the name is taken."""
    config = MachineConfig(
        name=MACHINE_NAME,
        image=IMAGE,
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


def connect_existing() -> Machine:
    """Reopen the named machine, starting it if stopped; never one this checkout does not own."""
    if state.load() is None:
        msg = f"{MACHINE_NAME}: no state file at {state.path()}, another checkout's? Refusing to connect."
        raise RuntimeError(msg)
    return Machine.connect(MACHINE_NAME, LOCAL)


def scrapy_version(mach: Machine) -> str:
    """The Scrapy version the guest reports; raises when it cannot report one."""
    r = mach.exec(["scrapy", "version"], ExecOptions(timeout=CHECK_TIMEOUT_S))
    if r.exit_code != 0:
        msg = f"`scrapy version` exited {r.exit_code}: {(r.stderr or r.stdout).strip()[-200:]}"
        raise RuntimeError(msg)
    return r.stdout.strip().removeprefix("Scrapy ")


def install_scrapy(mach: Machine) -> str:
    """Ladder rung 1: pip-install the pin onto the machine's disk. Returns pip's output tail."""
    argv = ["pip", "install", "--no-input", "--root-user-action=ignore", f"scrapy=={SCRAPY_VERSION}"]
    r = mach.exec(argv, ExecOptions(timeout=INSTALL_TIMEOUT_S))
    if r.exit_code != 0:
        msg = f"pip exited {r.exit_code}: {(r.stderr or r.stdout).strip()[-800:]}"
        raise RuntimeError(msg)
    return r.stdout.strip()[-800:]


def state_block(mach: Machine | None, open_error: str | None = None) -> str:
    """The full state, printed at the end of every command; every field is always present."""
    lines = [f"machine:    {MACHINE_NAME}"]
    running = False
    if open_error:
        lines.append(f"state:      error: {open_error}")
    elif mach is None:
        lines.append("state:      (no machine)")
    else:
        try:
            current = mach.state()
        except SmolError as exc:
            lines.append(f"state:      error: {exc}")
        else:
            running = current == "running"
            lines.append(f"state:      {current}")
    if running:
        try:
            lines.append(f"scrapy:     {scrapy_version(mach)}")
        except (SmolError, RuntimeError) as exc:
            lines.append(f"scrapy:     error: {exc}")
    else:
        lines.append("scrapy:     unknown (the machine is not running)")
    present = "present" if state.path().exists() else "absent"
    lines.append(f"state file: {present} ({state.path()})")
    return "\n".join(lines)
