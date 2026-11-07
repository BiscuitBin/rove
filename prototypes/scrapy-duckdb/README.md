# Scrapy in a Smol Machines microVM, pages in DuckDB

**PROTOTYPE: throwaway, not part of rovo.** This directory is a standalone uv project on
the `scrapy-duckdb-prototype` branch and is never merged to `main`. It shares nothing
with the `rovo` package: not its lockfile, not its source, not its tests. The command is
called `scrapyproto`, there are no tests and no polish, and nothing here is imported by
anything else.

## The question

Two parts, answered together by ticket 06:

1. Is Scrapy, running inside a Smol Machines microVM on macOS (Apple Silicon) and driven
   from a host-side Typer command that takes seed URLs and guiding and filtering
   parameters, a candidate engine for rovo's http fetch tier? `docs/specs/crawl.allium`
   treats the HTTP client behind `fetch_or_render` as a black box.
2. Is DuckDB a candidate store for a run's fetched pages, raw HTML plus metadata? The
   `duckdb-column-compression-of-html-and-md-efficacy` branch found DuckDB wins on disk
   and loses on per-row writes and point lookups, recommended SQLite with zstd for the
   temporary store, and named DuckDB as an append-once archive written in bulk after a
   run as the follow-up worth measuring. This prototype measures both paths: a host-side
   bulk load of the spider's JSONL feed after each run, and a per-item write from inside
   the Scrapy item pipeline.

The target sites are the Microsoft Graph REST API reference under
`https://learn.microsoft.com/en-us/graph/api/` and the Google Workspace API reference
under `https://developers.google.com/workspace/`. The page record is raw HTML plus
metadata; there is no Markdown and no converter in this prototype.

The sibling prototypes are the templates: `crawl4AI-smolmachine-prototype` for the
machine wrapper, the state file and the `vm` command group; `firecrawl-smolmachine-prototype`
for the per-ticket network notice; the DuckDB study for the measurements.

## Design

- The guest is a `python:3.12` image with Scrapy installed by `pip` at first create and
  persisted on the machine's own disk. Ticket 01 climbs a ladder if that does not hold:
  a community Scrapy image, then a venv on the ext4 disk.
- One machine, named `scrapy-proto`, created persistent, detached and with networking
  on, so separate processes reopen it by name. It is stopped, not deleted, between
  sessions. It is never managed with a `with` block, because `Machine.__exit__` deletes
  the machine.
- The host renders a spider and its settings into the guest with `write_file`, runs
  Scrapy with `exec`, and reads the JSONL feed back with `read_file`. The guest keeps an
  HTTP cache on its disk; `crawl --replay` serves a run from it and drops any request
  it does not hold, so a replay never touches the site.
- Polite defaults are baked in and robots.txt is always obeyed: there is no ignore flag.
  The User-Agent names the prototype.
- The store is one DuckDB file, `ai_tmp/scrapy-duckdb/prototype.duckdb` at the
  repository root, with a `runs` table and a `pages` table whose `html` column is
  declared `USING COMPRESSION ZSTD`. `--store bulk` (the default) loads the feed on the
  host after the run; `--store per-item` writes each page from the item pipeline into a
  DuckDB file on the guest disk, pulled back afterwards.
- Flags use the specification's vocabulary (`CrawlScope` in `docs/specs/mirror.allium`,
  `Configuration` in `docs/specs/rovo.allium`): `--start-url`, `--allowed-host`,
  `--path-prefix`, `--include`, `--exclude`, `--max-depth`, `--max-pages`,
  `--keep-query-param`, plus politeness `--delay`, `--concurrency`, `--user-agent`.
- Scratch state (the state file, the feeds, the DuckDB file) lives under
  `ai_tmp/scrapy-duckdb/` at the repository root, gitignored. Every command ends by
  printing the state block.
- Pins: `smolmachines==1.32.4`, and `scrapy` and `duckdb` at the versions current on the
  day ticket 01 locks, recorded in that ticket's hand-back and in the Verdict.
- macOS on Apple Silicon only.

## How to run

```sh
cd prototypes/scrapy-duckdb
uv sync
uv run python spike.py                                   # ticket 01: boot, crawl example.com, stop
uv run scrapyproto vm up                                 # ticket 02: create or reconnect
uv run scrapyproto vm status                             # from any shell
uv run scrapyproto crawl --start-url https://example.com --max-pages 25   # ticket 03
uv run scrapyproto runs
uv run scrapyproto sql "select status, count(*) from pages group by 1"
uv run scrapyproto crawl --start-url URL --exclude 'glob' --dry-run        # ticket 04
uv run scrapyproto crawl --start-url URL --store per-item                 # ticket 05
uv run scrapyproto vm down                               # stop; `vm up` reconnects
uv run scrapyproto vm destroy                            # delete the machine and the state file
```

## Tickets

The tickets under `tickets/` are numbered in dependency order and written in the
lightweight per-ticket form: what to build, what blocks it, an acceptance checklist.
Each ticket that reaches the network says so at the top; a future agent asks before
pulling or crawling anything. Each ticket is picked up in a fresh context, in order;
04 and 05 are independent once 03 lands. Each ticket names its review moments, at which
the agent runs the adversarial review loop below.

| Ticket | Title | Blocked by |
| --- | --- | --- |
| `01-scaffold-spike-scrapy-in-smol.md` | Scaffold and spike: Scrapy runs inside a smol microVM and its feed reaches the host | none |
| `02-vm-lifecycle-across-invocations.md` | Drive the microVM's lifecycle from separate invocations | 01 |
| `03-tracer-seeds-to-duckdb.md` | Tracer: seeds in, pages in DuckDB out | 02 |
| `04-guiding-and-filtering-parameters.md` | Guiding and filtering parameters, proven on Graph and Workspace | 03 |
| `05-per-item-duckdb-versus-bulk-load.md` | The per-item DuckDB path, compared with the bulk load | 03 |
| `06-verdict.md` | Verdict | 04, 05 |

## Adversarial review

Every ticket names one or two review moments. At each one the agent runs this loop. It
is the prototype's second pair of eyes, from a different model, and the one place a
throwaway gets challenged on its design and its claims rather than its style. The loop
is written for Claude Code with the Codex plugin installed; another executor runs the
same command and plays the three roles with its own subtasks.

1. **Review, by one subagent.** With the slice in the working tree (or, if it is already
   committed, with `--base <the commit before it>` in place of `--scope working-tree`),
   spawn one general-purpose subagent whose only job is to run the Codex adversarial
   review and save its output verbatim. The review is the Codex plugin's runtime, run by
   Bash from the installed plugin directory, with the moment's focus text from the ticket:

   ```sh
   node ~/.claude/plugins/cache/openai-codex/codex/<version>/scripts/codex-companion.mjs \
     adversarial-review --wait --model gpt-6-astra --scope working-tree "<focus text>"
   ```

   Astra (`gpt-6-astra`) is the preferred reviewer. If Codex rejects the model, rerun
   without `--model` and record which model answered. The `codex:codex-rescue` subagent
   forwards tasks only and refuses reviews, so a general-purpose subagent runs the
   command, with its Bash timeout at the maximum, since an Astra review of a multi-file
   slice outlives the default; if the run outlives that too, it reruns with
   `--background` and reads `result <job-id>` from the same script. The review reads git
   state only: a gitignored path under `ai_tmp/` never reaches the reviewer, so a moment
   that reviews rendered output puts it in an untracked file inside
   `prototypes/scrapy-duckdb/` for the duration of the review and deletes it before
   `just check`. The subagent writes the output to
   `ai_tmp/scrapy-duckdb/reviews/<ticket>-<moment>.md` and returns that path and
   nothing else: no opinion, no fix.
2. **Triage, by other subagents.** For each finding spawn a fresh subagent, one per
   finding and in parallel, given the finding, the ticket and the code, and no opinion
   from the main thread. It returns one verdict with its evidence: valid, with the
   smallest fix applied and the check it ran; invalid, with the evidence; or out of
   scope. The scope rule is the prototype's own: no tests, no polish, throwaway, so a
   finding that asks for those is out of scope, while a wrong measurement, an impolite
   or unbounded request, a lost or duplicated page, a lifecycle hole, a deleted machine
   or an unsupported claim in the README is in. A fix is applied only to a valid finding.
   Verdicts run in parallel, fixes do not collide: findings that touch the same file go
   to one subagent, or the fixes are applied serially once every verdict is in. The
   ticket is the authorization the plugin's result-handling rule asks for before a
   review finding is fixed.
3. **Reconcile, in the main thread.** Read every verdict and diff, reverse any fix that
   changed what the ticket asked for, rerun the slice's own command and `just check`,
   and commit the slice with its fixes, naming the findings fixed in the message.
4. **Record.** The hand-back lists each finding in one line with its verdict, names the
   model that reviewed, and gives the saved output's path. A second round at the same
   moment runs only when a fix changed a design choice.

## Verdict

Ticket 06 writes the final Verdict. Until then, the rungs, timings and sample runs from
tickets 01 to 05 accumulate here as each lands.

### Ticket 01: the spike

Measured on one Mac, with `scrapy-proto` at 4 vCPU, 4 GiB RAM and 20 GiB storage. Anything
not marked as inference or not measured was printed by a run.

**Ladder.** Rung 1, `python:3.12` plus `pip install scrapy==2.20.0`, worked. Rungs 2 and 3
were not tried, because rung 1 did not fail, so nothing is known about them.

**Pins.**

- Guest: Scrapy 2.20.0. It reports Python 3.12.16.
- Host: DuckDB 2.0.0, `smolmachines` 1.32.4 and typer 0.27.3.
- `uv.lock` lists a cp312 manylinux aarch64 wheel for DuckDB. Installing it in the guest is
  ticket 05's and is not measured.
- The `python:3.12` tag floats and no digest was recorded, so a recreated machine may boot a
  different image.

**First boot.**

| Step | Time |
| --- | --- |
| `Machine.create` | 20.2 s |
| `pip install` (118M of site-packages) | 21.8 s |
| `scrapy runspider` (exit 0) | 2.2 s |
| Whole run up to the final stop, including a deliberate 5 s wait after create | 51.0 s |

Whether the image was already cached on this host at that boot is not measured, so 20.2 s is
not a known cold-pull time. The log's label, "image pull and boot", is the spike's wording, not
evidence of a pull. The item read back was `https://example.com/`, status 200, title "Example
Domain", 577 HTML bytes. The fetch made two requests: robots.txt (a 404) and the page.

**Feed round trip.** Only guest to host was measured. The 187-byte feed took 0.003 s with
`read_file`. A 20971520-byte random file, read three times in each of three runs, matched its
hash all nine times at 0.094 to 0.122 s, or 171.6 to 223.4 MB/s. So `exec`'s output cap does
not limit `read_file`, at least at this size. Not measured: `write_file` speed, a real feed of
this size, a file larger than this, and a file not freshly written.

**`exec`.**

- **Buffering:** blocking `exec` hands back its output only at exit. `exec_stream` is live: 20
  stdout events over 20 s at a constant 0.108 s lag, clock skew included.
- **Long runs:** commands of 660 s exited 0 with no timeout and with `timeout=900`. No implicit
  timeout appeared up to 660 s; longer is not measured.
- **Timeout:** `timeout=5` on a 60 s command does not raise. It returned exit 124 at 5.0 s, with
  partial stdout and stderr kept and `command timed out after 5000ms` appended to stderr.
  A background child was gone and the `TERM` trap never ran. Inference: this is SIGKILL or
  equivalent, so Scrapy would get no graceful close, and `CLOSESPIDER_TIMEOUT` has to be the
  guard. That setting closing a real run is not measured.
- **Long output:** captured stdout stopped at 11534336 bytes (11 MiB) and stderr at 11542528 in
  its one measurement. 8 MiB on each stream at once arrived whole. Past the cap the writer gets
  SIGPIPE (141), and `exec` gives no truncation flag: a script that carries on can still exit
  0. `exec_stream` ends with an `error` event naming the cap.
- **Host SIGKILL during `exec` or `exec_stream`:** the guest command died too, at 6 of 20 ticks
  in both. The machine stayed `running` and Scrapy stayed intact.
- **`background=True`:** returned in 0.005 s with a pid, outlived a starter that exited
  normally, and ran 660 s to its done marker. A `stop` killed it: pid gone, no marker. Surviving
  a host SIGKILL of the starter is not measured, and the case for using it depends on that.
- **Two processes:** nothing serialises them. A second process connected, ran `exec` and read a
  file during a running `exec`. `stop()` during an `exec` raised `SmolError code=INTERRUPTED`;
  that stop came from the same process, so a stop from another process doing the same is
  inference.

Inference, for ticket 03 to decide: `background=True` with a polled done marker fits a crawl of
minutes better than blocking `exec` with a raised timeout, because it gives progress, avoids the
capture cap and need not hold a host connection.

**Scrapy across `stop` then `connect`.** It survived in all three main-path runs, reporting
2.20.0 with no `pip` run after a fresh boot (guest uptime 0.39, 0.45 and 0.49 s), and from a
fresh process in the last two. A file written with no sync just before `stop` was intact each
time. `/out`, `/usr/local`, `/var/lib`, `/root` and `/workspace` kept a marker; `/tmp` did not,
so nothing durable goes there. Connect from stopped took 0.1 s. Inference: this holds by design,
since the root overlay's upper layer is `/storage/overlays/persistent-scrapy-proto/upper` on
the `/dev/vda` ext4 disk. Not measured: SIGKILL of the VM process, a host reboot, and a `stop`
during a `pip install`.

**Corrections from measurement.** Both contradict or qualify what the tickets assumed; the
ticket text stays as written.

- **Something in the guest does listen.** Ticket 01 says nothing does. Scrapy 2.20 enables
  `REMOTE_CONTROL_ENABLED` by default, and the spider's log shows `Remote control HTTP server
  listening on port 39763`. The spike leaves it on and publishes no port. Its bind address and
  whether anything outside the guest can reach it are not measured. Ticket 03's settings should
  set it to `False`; the effect of that is not measured.
- **`CLOSESPIDER_PAGECOUNT` counts the robots.txt response.** With the limit at 1 the stats show
  `response_received_count: 2`, and the log shows `Closing spider (closespider_pagecount)` at
  07:49:35, before the page's `fetched_at` of 07:49:36.98. Scrapy's `closespider.py:63` counts
  on `response_received`. Inference: the page arrived only because its request had already been
  dequeued. Ticket 03's `--max-pages` cannot treat this setting as an exact page count.

**After review moment 1.**

- Two fixes landed after the runs above: the state file is saved only after `create` returns,
  and `connect_existing` refuses when there is no state file.
- The main path then reran on the existing machine: 2.0 s, no `pip`, no fetch, ending stopped.
  That run exercises the connect path only; the changed `create` path and the refusal were
  checked with the SDK stubbed, never live.
- Ownership is still only the state file's presence, so a stale file can accept a machine that
  another checkout recreated. Ticket 02 inherits this.
