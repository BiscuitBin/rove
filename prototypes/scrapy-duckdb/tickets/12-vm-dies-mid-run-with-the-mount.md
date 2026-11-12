# 12: The VM dies mid-run with the mount attached

Tickets 07 to 09 live on PR #14 (`rocksdb-scrapy-duckdb-prototype`, at `63ec30e`).

**Network:** none if the caches survive. These probes replay ticket 10's Workspace 200-page cache on
`tail-proto`, and they can lose the guest disk, and with it the HTTP cache and the guest's installs.
A cache that is lost has to be seeded again with a live crawl, and a machine that is lost has to be
created again (image pull and `pip install`): both are network, so ask first. Run this ticket last
of 11 to 14 for that reason.

**What to build:** three probes, each on its own replay, each killing the VM while the spider is
writing the tail feed:

1. A guest kernel crash: `echo c > /proc/sysrq-trigger` through `exec`. If the guest refuses it,
   record the refusal and what was tried instead.
2. `scrapyproto vm down` from another host process mid-run.
3. A SIGKILL of the VM's host process (found by its pid, and named in the log).

A replay runs too fast to kill at a chosen point, so the spider gains a prototype-only probe flag,
`crawl --hold-after N`, which stops emitting after N items and waits, so each kill lands at a known
row count. It sits beside `--crash-after` and is off by default. A held kill tests only the lines
already flushed: the spider is idle, so no write is in flight. The kernel crash therefore runs a
second time without the hold, fired at a fixed delay after the launch line on the Workspace replay,
with the row count recorded rather than chosen, so a write in flight and the guest's unflushed page
cache are exercised at least once. If that kill lands after the run ends, it is repeated with a
shorter delay.

For each probe the README records:

- the rows in the run's host DuckDB file, and whether the run was recorded;
- the committed cursor against the feed's bytes on the mount, and the bytes past the last complete
  line;
- whether a partial line was ever read;
- whether `consume` finishes the run or refuses it, and with what message;
- what the machine needed to come back (`vm up` as a reconnect, a reboot, or a re-create), how long
  it took, and whether the HTTP cache and the guest's installs survived;
- the guest clock offset after the restart, since a reboot resets it.

**Review:** one moment, through the README's adversarial review loop, once the three probes have run
and before the commit, with the focus: is each kill what it claims to be (a kernel crash, a clean
stop, a killed process); did the kill land at the held row count; did the un-held kernel crash land while a line was being
written; can the host tell a dead guest from
a slow one; can `consume` record a run whose guest never finished, or one with a page missing; is
anything inferred from one probe written as if all three showed it.

**Blocked by:** 10 (the tail, `consume`, `--crash-after` and the Workspace cache).

**Status:** ready-for-agent

- [ ] Each of the three probes ran held, the kernel crash ran once more without the hold, and each
  log is quoted in the README
- [ ] For each, the rows, the cursor against the mount's bytes, partial lines, `consume`'s outcome
  and the recovery are recorded
- [ ] No probe left a recorded run with a page missing or a page twice
- [ ] What each probe cost the machine (cache, installs) is stated, and any re-seed was asked for
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] The adversarial review loop ran at its moment; the hand-back lists each finding with its
  verdict and the reviewing model, and every valid finding's fix is in the commit
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged
