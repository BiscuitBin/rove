# 05: Stop and restart without rebuilding

**Network:** none. A restart that pulls anything is a failed acceptance criterion.

**What to build:** the machine survives being stopped and started like a laptop does, so
that the second `up` of the day is fast. `fcproto down` stops the machine. `fcproto up`
on a machine that exists but is stopped boots it again and relaunches the five services
without pulling an image or installing a package: the SDK's `stop()` then `start()`
keeps the disk, not the processes, so everything the stack put on disk is still there
and every process has to be started again. A scrape succeeds afterwards. `fcproto
destroy` removes the machine and its disk entirely, so the next `up` is a cold one.
`fcproto logs <service>` prints a service's recent output so a failed restart can be
diagnosed; the local SDK's own log call raises `NotSupportedError`, so the output is read
from inside the guest.

Ticket 03 decides how the services are started; this ticket reuses that path on a warm
disk and makes sure it tolerates the state a stopped stack leaves behind (a Postgres data
directory that is no longer empty, a queue with messages in it, stale pid files).

Record in `FINDINGS.md`: the warm `up` time to a successful scrape, next to the cold
time from ticket 03, and anything that had to be cleaned up on restart.

**Blocked by:** 03 (Firecrawl stack up and ready).

**Status:** ready-for-agent

- [ ] `uv run fcproto down` stops the machine; `uv run fcproto status` afterwards shows it
  stopped and the services not running
- [ ] `uv run fcproto up` on the stopped machine boots it and relaunches the five
  services without pulling an image or installing anything (shown by the elapsed time
  and the absence of any pull in the output)
- [ ] `uv run fcproto scrape https://example.com` succeeds after the restart
- [ ] `uv run fcproto logs <service>` prints recent output for each of the five services
  and exits non-zero with a clear message for an unknown service name
- [ ] `uv run fcproto destroy` removes the machine and its disk; `status` afterwards
  reports no machine (the next `up` would be a cold start; do not run it in this
  ticket, it pulls images)
- [ ] `FINDINGS.md` records the warm `up` time beside the cold one and anything the
  restart had to clean up
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
