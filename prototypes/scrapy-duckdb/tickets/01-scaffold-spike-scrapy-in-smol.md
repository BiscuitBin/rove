# 01: Scaffold and spike: Scrapy runs inside a smol microVM and its feed reaches the host

**Network:** this ticket reaches the network three times, each once: `uv lock` for the
prototype's own dependencies (PyPI: `smolmachines`, `typer`, `duckdb`), the guest image
pull (`python:3.12` from Docker Hub) on the first `Machine.create`, and `pip install
scrapy` inside the guest. Ask before each. Nothing else is downloaded: the macOS arm64
wheel of `smolmachines` bundles libkrun, a signed boot helper and the guest rootfs.

**What to build:** a standalone uv project under `prototypes/scrapy-duckdb/` (own
`pyproject.toml`, own `uv.lock`, `src/scrapyproto/`, a `scrapyproto` entry point that
may be a placeholder until ticket 02), the gate exclude, and one `spike.py` that settles
the unknowns the rest of the prototype rests on. The spike boots a named, persistent,
detached machine with networking on, installs Scrapy in the guest, writes a one-page
spider into the guest with `write_file`, runs it with `exec` against
`https://example.com` with `-O /out/feed.jsonl` (after `exec mkdir -p /out`), reads the
feed back with `read_file`, prints the item, the timings and the state block, then stops
(never deletes) the machine. Reuse the shape of the crawl4AI branch's `machine.py`
(constants, `create`, `open_existing`, `connect_existing`, `state_block`) and `state.py`
(an owner-only state file under `ai_tmp/scrapy-duckdb/` at the repository root), with
the machine name `scrapy-proto` and no API token or published port, since nothing in the
guest listens.

The facts that decide the shape (source-backed, from the SDK's documentation at
`smolmachines==1.32.4`, which is Alpha and releases several times a week, so pin it; the
crawl4AI branch confirmed most of them on this Mac):

- The import name is `smol`. Always pass `ConnectOptions(target="local")`: listing or
  connecting without it addresses the cloud.
- The long-lived machine is created with `MachineConfig(name=..., persistent=True,
  detach=True)`. Never manage it with a `with` block: `Machine.__exit__` deletes the
  machine. Reattach from a later process with `Machine.connect(name, local)`;
  `Machine.open` manages a machine without starting it.
- Networking is off by default: pass `ResourceSpec(network=True)`. Engine defaults are
  4 vCPU, 8 GiB RAM, 20 GiB storage and a 10 GiB overlay; the guest disk must hold the
  HTTP cache and the feeds, so set `ResourceSpec` explicitly.
- `Machine.create` returns once the guest agent is up. `exec` runs a command in the
  guest and blocks; `ExecOptions(background=True)` returns a pid at once. Local
  `Machine.logs()` raises `NotSupportedError`; output is read with `exec` or
  `read_file`.

Ladder for getting Scrapy into the guest, each rung climbed only if the one before fails,
and each rung recorded in the README whether it worked or not:

1. The `python:3.12` image plus `pip install scrapy==<version>` at first boot,
   persisted on the machine's disk across `stop` and `connect`.
2. A community Scrapy image booted directly as the machine image.
3. A venv on the ext4 disk (for example under `/var/lib/scrapyproto/venv`) if the
   overlay loses the installation.

Pins: the host project pins `smolmachines==1.32.4`, typer at rovo's range (copy the
crawl4AI branch's `pyproject.toml`), and `duckdb` exact at the version current on the
day of the lock, even though ticket 03 is its first user, so tickets 03 and 05 need no
re-lock. Scrapy is a guest pin (`pip install scrapy==<version>`), never a host
dependency. Both versions go in the hand-back and in the README.

Unknowns this settles, each with a sentence in the README:

- Whether `exec` buffers or streams the output of a run of minutes, and what its timeout
  does to a run that outlives it (a spider run is minutes; a `CLOSESPIDER_TIMEOUT` is
  the guest-side guard).
- Whether `read_file` moves a multi-MB feed intact and at what speed (write a 20 MB file
  in the guest with `exec`, read it back, compare a hash, record the seconds).
- Whether the installed Scrapy survives `stop` then `connect`.

The gate exclude is already on this branch: `ruff.toml` excludes `prototypes` in the
commit that added these tickets, with the crawl4AI branch's comment. This ticket's only
gate job is to confirm the nested `uv.lock` passes: the crawl4AI branch committed one
under `prototypes/` with no other gate change and `just check` passed. If this
worktree's gate trips on it, exclude the lockfile by path in the hook configuration,
typos and lychee, never by weakening a gate. `src/rovo/` stays untouched. `just check`
must still end with `All checks passed and the worktree is unchanged.`

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `prototypes/scrapy-duckdb/` is its own uv project with its own `pyproject.toml`
  and `uv.lock`, pinned to `smolmachines==1.32.4` and an exact `duckdb`, and
  `uv run scrapyproto --help` runs
- [ ] `uv run python spike.py` boots `scrapy-proto` (persistent, detached, networking
  on), installs Scrapy in the guest, runs the one-page spider and prints one item for
  `https://example.com` read back from the guest feed, with the timings
- [ ] The spike ends by stopping, not deleting, the machine, under the machine name
  ticket 02 uses, and prints the state block last
- [ ] The README's Verdict records the rung that worked (and any rung that failed), the
  first-boot time, the feed round-trip time and speed, what `exec` does with long
  output and its timeout, and whether Scrapy survived `stop` then `connect`
- [ ] The Scrapy and DuckDB versions pinned are in the hand-back and the README
- [ ] The nested `uv.lock` passes the gate as committed, or is excluded by path;
  `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged
