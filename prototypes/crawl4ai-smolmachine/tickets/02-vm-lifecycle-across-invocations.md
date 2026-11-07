# 02: Drive the microVM's lifecycle from separate command invocations

**What to build:** a `vm` command group with `up`, `status`, `down` and `destroy`, each
a separate process that finds the same machine by name. `up` creates the machine
(persistent, detached, named) or reconnects to an existing one, waits for health and
prints the state, the endpoint and the health body. `status` from a fresh process
reopens the machine by name without starting it. `down` stops it. `destroy` deletes it
and clears the prototype's local state. The generated API token is stored in a state
file so later processes can call the authenticated API. Every command ends by printing
the full state block: machine name, machine state, endpoint, health body or error, and
whether a token is present.

**Blocked by:** 01 (the spike proves the direct boot and fixes the machine settings).

**Status:** done

- [x] `vm up` in one shell, then `vm status` in another, shows `running` and a healthy
      health body.
- [x] `vm down` then `vm status` shows `stopped`.
- [x] `vm up` again reconnects to the stopped machine without re-pulling the image.
- [x] `vm destroy` leaves nothing in the machine registry and removes the state file.
- [x] Every command ends with the full state block.
