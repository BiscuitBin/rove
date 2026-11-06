# 02: Topology spike: how the five services will run

**Network:** this ticket pulls one small container image (`redis:alpine`) into the guest,
and, depending on the attempt, a Docker engine package or a Redis package inside the
guest. Ask before pulling.

**What to build:** a recorded verdict in `FINDINGS.md` on how Firecrawl's five services
will run inside the machine ticket 01 boots, proven by one real service answering from the
Mac: Redis started in the guest in the chosen way, reachable on a published port, so that
`redis-cli -p <port> PING` (or an equivalent raw `PING` over TCP) from the Mac prints
`PONG`. This is a spike: the code it leaves behind may be rough, but the verdict must be
unambiguous, because tickets 03 to 06 were written before this ran and depend on it only
through `FINDINGS.md`.

Try the topologies in this order and stop at the first that works; note each that
failed, and what failed, under the verdict:

1. **Docker inside the machine.** Install or enable a Docker engine in the guest, keep
   its data directory on the ext4 disk rather than the root overlay, and run the
   container on host networking so its port is the guest's port. The SDK's documentation
   says Docker inside a machine works on macOS arm64 (as of smolvm v1.29.0), that the
   data directory must be on the ext4 disk, and that `--network=host` works. Compose
   inside a machine is undocumented, and ports that compose assigns are not reachable, so
   do not reach for compose.
2. **A bare process in the guest.** Install the service into the guest's rootfs and run
   it directly, started in the background through `exec`.
3. **One machine per service.** Each service in its own machine, wired to the others
   through ports published on the Mac. This only works if a guest can reach the Mac's
   loopback, which is unconfirmed; record the answer either way.

The proof is the same in every topology: Redis answers `PING` from the Mac through the
published port, and the output is quoted in `FINDINGS.md`. Measure and record what the
attempt cost (image or package size, time to first `PONG`), because ticket 06 cites it.

**Blocked by:** 01 (Scaffold, `doctor`, and the first boot).

**Status:** ready-for-agent

- [ ] `FINDINGS.md` names the chosen topology in one sentence, lists the attempts in
  order with what failed for each that did not work, and quotes the Mac-side `PING`
  that printed `PONG`
- [ ] Redis runs inside the machine from ticket 01 in the chosen way and answers `PING`
  from the Mac on a published port, from a fresh process after `fcproto up`
- [ ] If the chosen topology is Docker, `FINDINGS.md` records where the engine's data
  lives and confirms it is on the ext4 disk, not the overlay
- [ ] If the chosen topology needs more than one machine, `FINDINGS.md` records whether a
  guest can reach the Mac's loopback and how the machines find each other
- [ ] `FINDINGS.md` records the size of what was pulled and the time from `fcproto up`
  to the first `PONG`
- [ ] `fcproto destroy` still removes everything the spike created
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
