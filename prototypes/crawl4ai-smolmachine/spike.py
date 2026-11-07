"""Ticket 01 spike: boot unclecode/crawl4ai directly as a smol microVM and wait for /health.

Run: uv run python spike.py [--env KEY=VALUE ...] [--keep]
Ends with stop(), not delete(), to keep the machine's own disk (ticket 02 reuses the name).
"""

import secrets
import sys
import time

from smol import ExecOptions, SmolError

from c4ai_proto import api, machine as m, state

HOST_PORT = 11235


def run_exec(mach, argv):
    try:
        r = mach.exec(argv, ExecOptions(timeout=30))
        print(f"$ {' '.join(argv)}  (exit {r.exit_code})\n{r.stdout}{r.stderr}")
    except SmolError as exc:
        print(f"$ {' '.join(argv)}  -> SmolError: {exc}")


def diagnose(mach):
    print("---- diagnostic ladder ----")
    run_exec(mach, ["ps", "aux"])
    run_exec(mach, ["ss", "-ltnp"])
    run_exec(mach, ["sh", "-c", "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null | head -20"])
    run_exec(mach, ["sh", "-c", "id; hostname; ls /app 2>/dev/null | head; env | cut -d= -f1 | grep -i -E 'crawl|gunicorn'"])
    try:
        print("---- logs ----")
        print(mach.logs(tail=200))
    except (SmolError, NotImplementedError) as exc:
        print(f"logs: {exc}")


def main() -> int:
    extra_env = {}
    keep = "--keep" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--env":
            k, v = sys.argv[i + 1].split("=", 1)
            extra_env[k] = v
    existing = m.open_existing()
    saved = state.load()
    if existing is not None:
        print(f"machine {m.MACHINE_NAME} exists in state {existing.state()}; reusing it")
        token = (saved or {}).get("token", "")
        t0 = time.monotonic()
        mach = m.connect_existing()
    else:
        token = secrets.token_hex(32)
        state.save({"machine": m.MACHINE_NAME, "port": HOST_PORT, "token": token, "image": m.IMAGE})
        print(f"creating {m.MACHINE_NAME} from {m.IMAGE} with env keys {sorted({'CRAWL4AI_API_TOKEN', *extra_env})}")
        t0 = time.monotonic()
        mach = m.create(token, HOST_PORT, extra_env)
    print(f"create/connect returned after {time.monotonic() - t0:.0f}s; state={mach.state()}")
    try:
        print(f"endpoint: {mach.endpoint(m.GUEST_PORT)}")
    except SmolError as exc:
        print(f"endpoint: error {exc}")
    ok = False
    try:
        body = m.wait_for_health(HOST_PORT, deadline_s=900)
        print(f"first start to healthy: {time.monotonic() - t0:.0f}s")
        print(f"health body: {body}")
        ok = True
        # One authenticated call so the token path is proven too.
        try:
            r = api.markdown(m.base_url(HOST_PORT), token, "https://example.com", "raw")
            print(f"/md example.com: success={r.get('success')} markdown[:200]={r.get('markdown', '')[:200]!r}")
        except api.ApiError as exc:
            print(f"/md example.com failed: {exc}")
    except TimeoutError as exc:
        print(f"FAILED: {exc}")
        diagnose(mach)
    print("---- state ----")
    print(m.state_block(mach, HOST_PORT, bool(token)))
    if not keep:
        print("stopping (not deleting) ...")
        mach.stop()
        print(f"state after stop: {mach.state()}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
