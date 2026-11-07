# crawl4AI in a Smol Machines microVM

**PROTOTYPE: throwaway, not part of rovo.** This directory is a standalone uv project on
the `crawl4AI-smolmachine-prototype` branch and is never merged to `main`. It shares
nothing with the `rovo` package: not its lockfile, not its source, not its tests.

## The question

Can a Smol Machines microVM on macOS boot the crawl4AI Docker image as its workload,
serve the crawl4AI HTTP API on a published port, and be driven from a Typer command
across separate invocations, ending in a `fetch <url>` command that prints a page's
Markdown?

The answer informs whether crawl4AI in a sandbox can be rovo's fetch and browser tier:
`docs/specs/rovo.allium` gives rovo a `fetch` command that prints one page's Markdown,
and `docs/specs/crawl.allium` treats the HTTP client and the browser engine as black
boxes.

## Design

- The `unclecode/crawl4ai:0.9.5` image is booted directly as the microVM image. Smol
  Machines runs the image's entrypoint as a detached container after boot, so there is
  no Docker daemon anywhere. Docker-in-VM is the fallback only if the direct boot fails.
- crawl4AI needs an API token to bind its port to the guest's wildcard address; without
  one it binds loopback and the host sees a connection reset. The prototype generates a
  token, passes it as the machine's environment and keeps it in a state file under
  `ai_tmp/c4ai-proto/` at the repository root (gitignored, inside the worktree).
- The machine is created persistent, detached and named, so separate processes reopen
  it by name. It is stopped, not deleted, between sessions, which keeps the machine's
  own disk. The plan assumed a delete forces a 2.9 GB re-pull; it does not: ticket 02
  found the pulled image cached host-side (see "Lifecycle" below).
- `fetch` prints Markdown by default through the `/md` endpoint; `--json` prints the
  full `/crawl` result.
- macOS on Apple Silicon only. The first `vm up` writes under
  `~/Library/Application Support/smolvm` and `~/Library/Caches/smolvm`, and the guest
  pulls the image from Docker Hub.

## How to run

```sh
cd prototypes/crawl4ai-smolmachine
uv sync
uv run python spike.py                    # ticket 01: boot, wait for health, stop
uv run c4ai vm up                         # ticket 02: create or reconnect, wait for health
uv run c4ai vm status                     # from any shell: state, endpoint, health
uv run c4ai fetch https://example.com     # ticket 03: Markdown on stdout
uv run c4ai fetch https://example.com --json
uv run c4ai vm down                       # stop; `vm up` reconnects without a re-pull
uv run c4ai vm destroy                    # delete the machine and the state file
```

The tickets live in `tickets/`, numbered in dependency order.

## Verdict

**Direct boot works.** Ticket 01's spike booted `unclecode/crawl4ai:0.9.5` as the microVM
image with no Docker anywhere, and crawl4AI answered on the published port from the host.
No rung of the diagnostic ladder was needed. Recorded on 2026-11-06 on macOS 26.4,
Apple Silicon, smolmachines 1.32.4, with the engine's default sizes (4 vCPU, 8 GiB
ceiling, 20 GiB storage).

| Measure | Value |
| --- | --- |
| `Machine.create` returned (image pulled, VM booted, guest agent up) | 51 s |
| First `/health` 200 from the host, from the start of `create` | 54 s |
| Whole spike, wall clock, create to `stop()` | 66 s |

The real output of `uv run python spike.py` on the first start:

```text
creating c4ai-proto from unclecode/crawl4ai:0.9.5 with env keys ['CRAWL4AI_API_TOKEN']
create/connect returned after 51s; state=running
endpoint: PortEndpoint(http_url='http://127.0.0.1:11235', ws_url='ws://127.0.0.1:11235', headers={})
[health] waiting 0s: http://127.0.0.1:11235/health: [Errno 54] Connection reset by peer
[health] ok after 3s
first start to healthy: 54s
health body: {'status': 'ok', 'timestamp': 1794013443.728578, 'version': '0.9.5'}
/md example.com: success=True markdown[:200]='This domain is for use in documentation examples without needing permission. This is not a service; avoid relying on it for testing and monitoring purposes.\nهذا النطاق مُخصص للاستخدام في أمثلة التوثيق'
---- state ----
machine:  c4ai-proto
state:    running
endpoint: http://127.0.0.1:11235
health:   {'status': 'ok', 'timestamp': 1794013445.1209261, 'version': '0.9.5'}
token:    present
stopping (not deleting) ...
state after stop: stopped
```

Surprises and facts worth keeping:

- The pull is fast here: 2.9 GB arrived and unpacked inside the 51 s. On a slower
  connection the first start is bounded only by the 900 s readiness timeout the
  prototype passes.
- `Machine.create` returns once the guest agent is up, before gunicorn listens: the
  first health probe is a connection reset, the second (3 s later) is 200. The
  prototype polls `/health` itself and never lets smol wait on the port.
- The token path works through the port forward: `/md` for `https://example.com`
  returned `success=True` with the page's Markdown, so the IPv6-any bind the entrypoint
  uses with a token set is reachable from the host; the `GUNICORN_BIND` variant was
  not needed.
- `Machine.endpoint(11235)` returns a local `http://127.0.0.1:11235` endpoint with empty
  headers; the "cloud only" docstring is stale.
- `Machine.logs()` and `list_images()` are not usable on a stopped local machine
  (`list_images` raises `INVALID_STATE`); the ladder's exec rungs would run only on a
  started one.
- The host-side caches after one start: `~/Library/Caches/smolvm/image-seeds` 7.4 GB and
  `~/Library/Caches/smolvm/vms` 7.4 GB (sparse files; the registry reports 20 GiB
  storage). The machine survives `stop()` in the registry as `stopped`, persistent and
  detached, with its published port recorded.
- uv picked Python 3.15.0 for the prototype's own `.venv` (the smolmachines wheel is
  `abi3`); the root `.python-version` was not consulted inside the nested project.

## Sample run

Real output, 2026-11-06, trimmed only where marked.

### Lifecycle (ticket 02)

Reconnecting to the stopped machine from a fresh process takes about 3 s to healthy,
and `vm status` from another process reads the shared registry:

```text
$ uv run c4ai vm up
c4ai-proto exists (stopped); connecting
state=running; waiting for /health
[health] waiting 0s: http://127.0.0.1:11235/health: [Errno 54] Connection reset by peer
[health] ok after 3s
---- state ----
machine:  c4ai-proto
state:    running
endpoint: http://127.0.0.1:11235
health:   {'status': 'ok', 'timestamp': 1794013541.693281, 'version': '0.9.5'}
token:    present
uv run c4ai vm up  0.07s user 0.03s system 2% cpu 3.345 total

$ uv run c4ai vm status
---- state ----
machine:  c4ai-proto
state:    running
endpoint: http://127.0.0.1:11235
health:   {'status': 'ok', 'timestamp': 1794013541.7976086, 'version': '0.9.5'}
token:    present

$ uv run c4ai vm down
stopped
---- state ----
machine:  c4ai-proto
state:    stopped
endpoint: http://127.0.0.1:11235
health:   error: http://127.0.0.1:11235/health: <urlopen error [Errno 61] Connection refused>
token:    present

$ uv run c4ai vm destroy
deleted
state file removed: .../ai_tmp/c4ai-proto/state.json
registry: []
---- state ----
machine:  c4ai-proto
state:    (no machine)
health:   error: http://127.0.0.1:11235/health: <urlopen error [Errno 61] Connection refused>
token:    absent
```

After `destroy`, a fresh `vm up` through the create path took 3.8 s to healthy, not 54 s:
`~/Library/Caches/smolvm/vms` went to 0 B but `image-seeds` kept its 7.4 GB, so the
pulled image is a host-side cache, not per machine. `vm down` took between 0.7 s and
10 s (the second time, with a crawl done, gunicorn drained longer).

### Fetch (ticket 03)

```text
$ uv run c4ai fetch https://example.com
This domain is for use in documentation examples without needing permission. This is not a service; avoid relying on it for testing and monitoring purposes.
(five translations trimmed)
[Learn more](https://iana.org/help/example-domains)
exit 0   (0.98 s wall)

$ uv run c4ai fetch https://www.python.org/ --filter fit
**Notice:** This page displays a fallback because interactive scripts did not run. Possible causes include disabled JavaScript or failure to load scripts or stylesheets.
(one line trimmed: the site's security notice)
## Get Started
Whether you're new to programming or an experienced developer, it's easy to learn and use Python.
[Start with our Beginner's Guide](https://www.python.org/about/gettingstarted/)
## Download
(trimmed: the rest of the home page as Markdown, 1.18 s wall)

$ uv run c4ai fetch https://example.com --json | python -c '... results[0] ...'
{'status_code': 200, 'success': True, 'raw_markdown': 'This domain is for use in documentation examples ...', 'fit_markdown_len': 0}

$ uv run c4ai fetch https://example.com -o ../../ai_tmp/c4ai-proto/example.md
exit 0, nothing on stdout; the file is 1337 bytes

$ uv run c4ai fetch http://127.0.0.1:11235/health
error: HTTP 400 from http://127.0.0.1:11235/md: URL blocked (SSRF protection): URL blocked
exit 1

$ uv run c4ai fetch https://this-host-does-not-exist.invalid/
error: HTTP 400 from http://127.0.0.1:11235/md: URL blocked (SSRF protection): URL blocked
exit 1

$ uv run c4ai vm down && uv run c4ai fetch https://example.com
error: machine c4ai-proto is stopped, not running; run `c4ai vm up`
exit 1

$ uv run c4ai vm destroy && uv run c4ai fetch https://example.com
error: no state file; run `c4ai vm up` first
exit 1
```

Facts from the fetch runs:

- A page round trip through the microVM is about 1 s wall clock for example.com and
  python.org, measured from the host process start.
- python.org's `fit` Markdown opens with the site's own no-JavaScript fallback notice:
  crawl4AI's headless Chromium ran the page but the site's scripts did not, so a fetch
  tier built on this must expect some pages' no-script branches.
- `/crawl` returned an empty `fit_markdown` for example.com while `/md` with `f=fit`
  returned content for python.org; the raw Markdown is the reliable field.
- crawl4AI's SSRF guard rejects loopback and private URLs with HTTP 400, and reports an
  unresolvable host the same way, since it resolves the name as part of the check.
