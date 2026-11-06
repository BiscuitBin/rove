# 01: Scaffold, `doctor`, and the first boot

**Network:** this ticket reaches PyPI once, to resolve and lock the prototype's
dependencies (`smolmachines`, `typer`). Ask before running the lock. Nothing else is
downloaded: the macOS arm64 wheel of `smolmachines` bundles libkrun, a signed boot helper
and the guest rootfs, so there is nothing else to install.

**What to build:** a standalone uv project under `prototypes/firecrawl-smolmachine/` whose
command, `fcproto`, can tell the operator whether this Mac can run local microVMs, boot
one long-lived machine, prove that a port published from the guest is reachable from the
Mac, and find that machine again from a fresh process. The prototype is throwaway code:
the `proto` in the name says so, there are no tests, no polish, and every command prints
the machine's state after it acts. This is the prefactoring for everything that follows:
it is the scaffold the other tickets build in, and it settles the one unknown that could
make the whole prototype moot.

`fcproto doctor` reports the SDK version and the result of the SDK's local-availability
probe, which checks the host without booting a machine. `fcproto up` creates one named,
persistent, detached machine with networking on, explicit resources, and one published
port; `fcproto status` and `fcproto destroy` work from a fresh process by reattaching to
the machine by name. The proof of life is a throwaway listener started inside the guest
that answers an HTTP request from the Mac on `127.0.0.1:<port>`.

The facts that decide the shape (source-backed, from the SDK's documentation at
`smolmachines==1.32.4`, which is Alpha and releases several times a week, so pin it):

- The import name is `smol`. Always pass `ConnectOptions(target="local")`: listing or
  connecting without it addresses the cloud.
- The long-lived machine is created with `MachineConfig(name=..., persistent=True,
  detach=True)`. Never manage it with a `with` block: `Machine.__exit__` deletes the
  machine. Reattach from a later process with `Machine.connect(name, local)`;
  `Machine.open` manages a machine without starting it.
- Networking is off by default: pass `network=True`. Ports are `PortSpec(host, guest)`,
  declared at create time, host side bound to `127.0.0.1`; `publish()` can add a TCP port
  to a running machine.
- Create with `wait_for_ports=False`, start what listens, then `wait_until_ready()`.
- Engine defaults are 4 vCPU, 8 GiB RAM, 20 GiB storage and a 10 GiB overlay. Set
  `ResourceSpec` explicitly and generously: the Firecrawl stack implies about 12 GB for
  the API and the browser service alone, and its Postgres sets `max_wal_size=16GB`, so
  give it more than 20 GiB of disk. The host has 64 GB of RAM and 18 cores.
- `exec(..., ExecOptions(background=True))` returns a pid at once and is how the
  listener is started; `Machine.run(image, ...)` blocks and ignores `background`.
- Local `Machine.logs()` raises `NotSupportedError`; output is read with `exec`.

The gate excludes land here, because they only matter once Python exists under
`prototypes/`: ruff, the hook configuration, typos and lychee each gain the directory,
and the prototype's own `uv.lock` is excluded by path, because the root exclude regex
matches only the root lockfile. `src/rovo/` stays untouched. `just check` must still end
with `All checks passed and the worktree is unchanged.`

**Unconfirmed, and the point of the ticket:** whether TCP port publishing works at all
from the SDK on its default network backend. The SDK offers no backend switch (the CLI's
`--net-backend` flag is not the SDK). If no published port is reachable from the Mac,
record that in `FINDINGS.md` as a negative answer for the SDK path, with what was tried,
and stop: tickets 02 to 06 are moot. Two more unknowns to note in passing if they
surface: whether the SDK can declare a guest-only disk volume, and whether a guest can
reach the Mac's loopback.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `prototypes/firecrawl-smolmachine/` is its own uv project with its own
  `pyproject.toml` and `uv.lock`, pinned to `smolmachines==1.32.4`, and a `fcproto`
  entry point; `uv run fcproto --help` lists `doctor`, `up`, `status` and `destroy`
- [ ] `uv run fcproto doctor` prints the installed SDK version and the local-availability
  probe's result without booting a machine
- [ ] `uv run fcproto up` creates a named, persistent, detached machine with networking
  on, explicit CPU, memory and disk, and one published port, and prints the machine's
  state afterwards
- [ ] A throwaway listener inside the guest answers an HTTP request from the Mac on
  `127.0.0.1:<port>` (for example with `curl`), and the output of that request is
  quoted in `FINDINGS.md`
- [ ] `uv run fcproto status` and `uv run fcproto destroy`, run in a fresh process, find
  the machine by name and act on it; `destroy` leaves no machine listed afterwards
- [ ] If the published port is not reachable from the Mac, `FINDINGS.md` records the
  negative answer with what was tried, and the hand-back says the remaining tickets are
  moot
- [ ] ruff, the hook configuration, typos and lychee exclude `prototypes/`, including the
  prototype's own `uv.lock`; `just check` ends with
  `All checks passed and the worktree is unchanged.` and `git status --short` is empty
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged
