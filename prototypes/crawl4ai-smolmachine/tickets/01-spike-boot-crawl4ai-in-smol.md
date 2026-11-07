# 01: Spike: boot the crawl4AI image as a Smol Machines microVM

**What to build:** the prototype's project skeleton and one script that boots the
crawl4AI container image directly as a Smol Machines microVM on this Mac, with the API
token, the published port and guest networking set, then waits from the host for the
crawl4AI health endpoint to answer and prints the machine state, the endpoint and the
health body. The README gains a "Verdict" section recording whether the direct boot
works or the Docker-in-VM fallback is needed, the first-start time and anything
surprising.

Before declaring the direct boot failed, the spike climbs a diagnostic ladder and
records each rung in the README:

1. Exec `ps` and `ss -ltn` inside the machine, to see whether exec lands in the workload
   container or the bare VM, and what is listening on which address.
2. Any logs method the machine handle offers (the command line has a logs subcommand for
   workload output).
3. One cheap variant: set the gunicorn bind to the IPv4 wildcard through the image's
   `GUNICORN_BIND` variable, since the entrypoint binds the IPv6 wildcard when a token
   is set and the port forward reaching an IPv6-any listener is unconfirmed.

Only after those three rungs is Docker-in-VM proposed.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] One command boots the image as a microVM, with the token in the environment, the
      API port published to the host and networking on.
- [x] The health endpoint answers 200 from the host, through the published port.
- [x] The printed machine state is `running`.
- [x] The spike ends by stopping the machine, not deleting it, under the same machine
      name ticket 02 uses. (The premise that a delete forces a 2.9 GB re-pull proved
      wrong in ticket 02: the pulled image is cached host-side. Stop is still the
      default, to keep the machine's own disk.)
- [x] The verdict, the first-start time and the diagnostic rungs climbed (if any) are
      written in the README.
