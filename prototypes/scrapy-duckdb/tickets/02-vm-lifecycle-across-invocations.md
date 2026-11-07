# 02: Drive the microVM's lifecycle from separate invocations

**Network:** none, if the `scrapy-proto` machine ticket 01 stopped still exists. If it
is absent, `vm up` creates it, which pulls the guest image and runs the guest
`pip install scrapy` again; ask first in that case.

**What to build:** a `vm` command group with `up`, `status`, `down` and `destroy`, each
a fresh process that finds `scrapy-proto` by name (`Machine.open` for `status`, which
never starts it; `Machine.connect` for `up`). `up` creates the machine (persistent,
detached, named, networking on) or reconnects to an existing one, is idempotent and
never deletes; it guarantees Scrapy is installed in the guest, installing on first
create only and otherwise checking `scrapy version` with `exec`. `down` stops the
machine. `destroy` deletes it and removes the state file. Every command ends by
printing the full state block: machine name, machine state, the Scrapy version in the
guest or the error that stood in for it, and whether the state file is present. A smol
failure prints a one-line reason and the state block, then exits 1.

The machine registry is host-global while the state file is per checkout, so follow the
crawl4AI branch: an existing machine with no state file here is reported, not deleted,
with a pointer to `vm destroy`.

**Blocked by:** 01 (the spike fixes the image, the install rung and the machine
settings).

**Status:** ready-for-agent

- [ ] `vm up` in one shell, then `vm status` in another, shows `running` and the Scrapy
  version read from the guest
- [ ] `vm down` then `vm status` shows `stopped`
- [ ] `vm up` again reconnects to the stopped machine without reinstalling Scrapy, and
  the time to `running` is recorded in the README
- [ ] `vm destroy` leaves nothing in the machine registry and removes the state file
- [ ] Every command ends with the full state block; a sample of each is in the README
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged
