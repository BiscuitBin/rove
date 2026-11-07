"""The smol wrapper: constants, create/open/connect and the health wait."""

import time
from typing import Any

from smol import ConnectOptions, Machine, MachineConfig, PortSpec, ResourceSpec, SmolError

from c4ai_proto import api

MACHINE_NAME = "c4ai-proto"
IMAGE = "unclecode/crawl4ai:0.9.5"
GUEST_PORT = 11235
LOCAL = ConnectOptions(target="local")
LOCAL_NO_WAIT = ConnectOptions(target="local", wait_for_ports=False)


def create(token: str, host_port: int, extra_env: dict[str, str] | None = None) -> Machine:
    """Create and boot the machine. Returns once the guest agent is up; health is polled separately."""
    env = {"CRAWL4AI_API_TOKEN": token, **(extra_env or {})}
    config = MachineConfig(
        name=MACHINE_NAME,
        image=IMAGE,
        env=env,
        ports=[PortSpec(host=host_port, guest=GUEST_PORT)],
        resources=ResourceSpec(network=True),
        persistent=True,
        detach=True,
        wait_for_ports=False,
        ready_timeout_seconds=900,
    )
    return Machine.create(config, LOCAL)


def open_existing() -> Machine | None:
    """A handle to the named machine without starting it, or None when there is none."""
    try:
        return Machine.open(MACHINE_NAME, LOCAL)
    except SmolError as exc:
        if "NOT_FOUND" in str(exc) or "not found" in str(exc).lower():
            return None
        raise


def connect_existing() -> Machine:
    """Reopen the named machine by name, starting it if stopped; never waits on gunicorn."""
    return Machine.connect(MACHINE_NAME, LOCAL_NO_WAIT)


def base_url(host_port: int) -> str:
    return f"http://127.0.0.1:{host_port}"


def wait_for_health(host_port: int, deadline_s: float = 900, every_s: float = 3) -> dict[str, Any]:
    """Poll GET /health until 200 or the deadline; prints elapsed seconds as it goes."""
    base = base_url(host_port)
    start = time.monotonic()
    last = ""
    while True:
        try:
            body = api.health(base)
        except api.ApiError as exc:
            last = str(exc)
        else:
            print(f"[health] ok after {time.monotonic() - start:.0f}s")
            return body
        elapsed = time.monotonic() - start
        if elapsed > deadline_s:
            msg = f"/health not ok after {elapsed:.0f}s; last error: {last}"
            raise TimeoutError(msg)
        print(f"[health] waiting {elapsed:.0f}s: {last}", flush=True)
        time.sleep(every_s)


def state_block(
    machine: Machine | None, host_port: int, token_present: bool, open_error: str | None = None
) -> str:
    """The full state, printed at the end of every command; every field is always present."""
    lines = [f"machine:  {MACHINE_NAME}"]
    if open_error:
        lines += [f"state:    error: {open_error}", "endpoint: unknown (the machine did not open)"]
    elif machine is None:
        lines += ["state:    (no machine)", "endpoint: (no machine)"]
    else:
        try:
            lines.append(f"state:    {machine.state()}")
        except SmolError as exc:
            lines.append(f"state:    error: {exc}")
        try:
            lines.append(f"endpoint: {machine.endpoint(GUEST_PORT).http_url}")
        except SmolError as exc:
            lines.append(f"endpoint: error: {exc}")
    try:
        lines.append(f"health:   {api.health(base_url(host_port))}")
    except api.ApiError as exc:
        lines.append(f"health:   error: {exc}")
    lines.append(f"token:    {'present' if token_present else 'absent'}")
    return "\n".join(lines)
