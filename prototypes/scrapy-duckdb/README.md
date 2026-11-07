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
uv run scrapyproto vm install-duckdb                     # ticket 05: guest DuckDB pin (network)
uv run scrapyproto crawl --start-url URL --store per-item                 # ticket 05
uv run python bench_queries.py bench --urls-from F --scratch D F1 F2      # ticket 05
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

Dated 2026-11-07, written by ticket 06 from the runs that tickets 01 to 05 recorded. No new run
was made for it. The per-ticket sections after it are the evidence it cites, and each number below
appears there or in the log it names (`ai_tmp/scrapy-duckdb/logs/`, gitignored). A sentence marked
**inference** is a reading of the evidence, not a measurement. Anything not measured is named as
not measured.

### Recommendations

1. **Scrapy in a smol sandbox as the engine of the http fetch tier: candidate with conditions.**
   What was shown: Scrapy 2.20.0 installed once into a persistent `python:3.12` microVM, survived
   every stop and reconnect, and ran three live crawls under polite defaults. One crawl was 25
   pages of Microsoft Graph. Two were 200 pages each, of Graph and Google Workspace. Each was run
   from a fresh host process with `exec(background=True)` and a polled done marker. Both 200-page
   runs filled their cap with status 200 pages and were ended by the spider's own cap, with robots.txt
   obeyed and no throttling. Every replay that was meant to stay offline made no site request. The
   conditions:
   - **The guest run is detached and watched, never a blocking `exec`.** An `exec` timeout
     SIGKILLs the command tree, and `exec` truncates at 11 MiB per stream with no flag (ticket 01).
     So the crawl must run in the background, write its output to a guest file, leave a done
     marker, and close itself with `CLOSESPIDER_TIMEOUT`. A real run being closed by
     `CLOSESPIDER_TIMEOUT` is not measured. The host's deadline, TERM and KILL path has not run.
   - **rovo owns the politeness and scope code, not Scrapy's defaults.** That means the page cap in
     the spider, the exact-host `Guard`, robots failing closed, a delay with no jitter, remote control
     off, a redirect scope check and shortest-depth tracking. Each one replaces a Scrapy 2.20
     default or behaviour that this prototype found too loose for a polite, bounded crawl (sharp
     edges below).
   - **A cache policy is decided before a live crawl relies on the cache.** The guest HTTP cache
     never expires, so a "live" crawl serves every URL it already holds without fetching it
     (ticket 04: 26 of Graph's 202 downloads were cache hits). rovo's revalidation rules are not
     built or measured here.
   - **The lifecycle paths that never ran are run before anything depends on them.** `vm destroy`,
     the `vm up` create path that writes the generation label, and a cold image pull are listed
     under "What this prototype did not exercise".
   - **Nothing in the SDK serialises two processes on one machine.** A `vm down` from another shell
     kills a running crawl. The guest crawl lock refuses a second `crawl`, but its `busy` and `stale`
     branches have not run live. rovo needs one owner per machine or its own host-side lock.
   - **The image is pinned by digest.** `python:3.12` floats and no digest was recorded.

   **Inference:** at the 1 s delay the crawl rate is set by politeness, not by the sandbox. Both
   200-page crawls sat at about one download a second, so the sandbox's own overhead did not show.
   What it costs at a higher rate is not measured.

2. **DuckDB as the store of a run's fetched pages: candidate with conditions, as a store bulk-loaded
   from the run's feed after the run. The per-item path is not part of the recommendation.** What
   was shown: the bulk path loaded every recorded run transactionally, refused a bad feed whole, and
   read back the same pages. That covers ticket 03's 25 pages and ticket 04's two 200-page runs,
   with 12346775 and 60636097 bytes of HTML. The per-item path stored the same 25 pages as the bulk
   path in each of five pairs. The conditions:
   - **One writer per file, written after the run.** On the per-item path, a writer's lock
     refused a second read-write open and a read-only open too (ticket 05). The host cannot read a
     run's pages while the spider writes them.
   - **The decision does not rest on this prototype's size or speed numbers.** Its comparison
     rests on 25 pages, where both files are five 256 KiB blocks and the `runs` row alone costs two
     of them. Disk, memory and write cost at a crawl's scale come from the DuckDB study or from a
     new measurement, not from the table below.
   - **The per-item path is not adopted.** Its own evidence does not separate it from the bulk
     load. It matched bulk at 25 pages, and it adds the one-writer lock, a reactor-blocking insert, a
     160.1 MiB spider against 88.7 MiB, and a crash that leaves the pages only in the WAL. A
     single-file pull loses all of them. The recovery, a read-write open in the guest before the
     pull, is described but not built. Adopting it would need a comparison on the 200-page caches,
     and that recovery built and run.

   **Not compared here:** SQLite, or any other store, against DuckDB. Whether DuckDB should be the
   run's working store at all is the DuckDB study's question, not this one's (see the reading under
   the table).

### The setup

- **Host:** macOS 26.4 (build 25E246) on an Apple M5 Pro, 18 cores, 64 GiB (`sw_vers`, `sysctl`).
  Host CPython 3.15.0, uv's pick under `requires-python = ">=3.13"`.
- **Pins:** `smolmachines` 1.32.4, DuckDB 2.0.0 and typer 0.27.3 on the host (`uv.lock`). Scrapy
  2.20.0 on guest Python 3.12.16. DuckDB 2.0.0 in the guest too, the cp312 abi3 manylinux aarch64
  wheel (ticket 05).
- **The machine:** one persistent, detached, networked machine, `scrapy-proto`, created from
  `python:3.12` with `ResourceSpec(cpus=4, memory_mb=4096, network=True, storage_gb=20,
  overlay_gb=10)` (`logs/01-spike-first.txt`, line 1). That is what was requested at create. The
  guest's own `nproc` and memory were not read. `df` in the guest showed 20G for `/`.

### Cold and warm `vm up`

- **Cold: 42.0 s, from ticket 01's spike, not from `vm up`.** `Machine.create` took 20.2 s and
  `pip install scrapy==2.20.0` 21.8 s. The sum is the only cold figure there is. Whether the image
  was already cached on this host at that create was not measured, so 20.2 s is not a known
  image-pull time. `vm up`'s own create path has never run (see below). The whole spike, with a
  deliberate 5 s wait and the 2.2 s example.com crawl, took 51.0 s.
- **Warm: 0.12 to 0.32 s from stopped to `running`, across 12 `vm up` runs in tickets 02 to 05.**
  The Scrapy version check after it took 0.29 to 0.39 s. No `pip` ran. The `[time]` lines time
  `Machine.connect` and `state()` only. Interpreter and `uv run` start-up were not measured.

### Feed round trip and `exec`

- **`read_file`, guest to host:** a 20971520-byte random file, read nine times, matched its hash
  every time, at 0.094 to 0.122 s (171.6 to 223.4 MB/s). The 187-byte spike feed took 0.003 s.
  Ticket 04's real feeds, 14870433 bytes for Graph and 76287696 for Workspace on the host, were
  pulled and loaded without error, but their pull was not timed. `write_file` speed was not measured.
- **Blocking `exec`** hands back output only at exit, and ran 660 s with no implicit timeout. A
  longer run was not measured. A timeout does not raise. It returns exit 124 and kills the command
  tree with no graceful close, so a `TERM` trap never ran. Output stops at 11534336 bytes on stdout
  (11542528 on stderr in its one measurement). The writer gets SIGPIPE, `exec` gives no truncation
  flag, and a script can still exit 0. A host SIGKILL during `exec` kills the guest command too.
- **`exec_stream`** is live, at a constant 0.108 s lag, and ends with an `error` event at the cap.
- **`exec(background=True)`** returned in 0.005 s and outlived a starter that exited normally. It
  is killed by a machine `stop`, which leaves no marker. Surviving a host SIGKILL of the starter is
  not measured. The crawls ran on this path: 26.5 s, 175.9 s and 204.9 s of guest wall time, with
  the 30 s progress line printed live on the 200-page runs.

### Crawl throughput

Warm machine, polite defaults: 1 s download delay with no jitter, concurrency 2, robots.txt
obeyed. One run per site, each capped at 200 pages (ticket 04). The rates count real downloads
only (`httpcache/firsthand`), never cache hits.

| | Graph `20261107T114236Z-46bf` | Workspace `20261107T114550Z-2a9f` |
| --- | --- | --- |
| Guest wall time | 175.9 s | 204.9 s |
| Real downloads (`firsthand`) | 176, all pages | 204: 200 pages, robots.txt, three 301 hops |
| Cache hits | 26: robots.txt, the seed's 301, 24 pages from ticket 03 | none |
| Real downloads per minute | 60.0 | 59.7 |
| Page downloads per minute | 60.0 | 58.6 (200 / 204.9 s, computed here) |
| Pages stored, and status 200 among them | 200 of the 200-page cap: 100% | 200 of 200: 100% |
| What ended the run | the spider's cap (`closespider_itemcount`, `proto/pages` 200) | the same |

Of Graph's 200 status 200 pages, 24 came from ticket 03's cache and 176 from the network. Not
measured: a site that throttles, a robots-forbidden path, a rate above the 1 s delay, and any
crawl longer than 200 pages.

### Bulk load against per-item writes

Ticket 05's table, unchanged. **It rests on 25 pages**: ticket 03's cached crawl, replayed five
times per path with no site request. Each cell is the median, then the range.

| Measure | bulk | per-item |
| --- | --- | --- |
| Wall time of the run, host process start to summary printed | 5.275 s [5.270 to 5.298] | 5.251 s [5.243 to 5.266] |
| Beside it: guest wall, wrapper start to Scrapy exit | 0.328 s [0.293 to 0.422] | 0.424 s [0.400 to 0.464] |
| Beside it: host, done marker seen to summary printed | 0.14 to 0.15 s | 0.07 to 0.08 s |
| Peak RSS of the spider process in the guest | 88.7 MiB [88.68 to 88.74] | 160.1 MiB [159.4 to 160.6] |
| Store file size after `CHECKPOINT` | 1323008 bytes, all 5 | 1323008 bytes, all 5 |
| Host-side point lookup by URL (25 lookups): time | 24.9 ms [24.6 to 26.5] | 24.5 ms [22.8 to 25.3] |
| Host-side point lookup by URL: peak RSS | 66.3 MiB [66.2 to 66.5] | 66.3 MiB [66.2 to 66.6] |
| Host-side full scan of `html`: time | 14.1 ms [13.0 to 14.4] | 14.0 ms [13.1 to 14.5] |
| Host-side full scan of `html`: peak RSS | 68.4 MiB [68.2 to 68.5] | 68.4 MiB [68.2 to 68.4] |

**Reading it against the DuckDB study.** The study measured 130,880 pages. It recommends SQLite
with per-row zstd against a per-host dictionary, in WAL mode, as the temporary page store. One of
its two follow-ups worth measuring is **Parquet** with zstd as an append-once archive of raw HTML written
in bulk after a run (`RESULTS.md`, "Recommendation"). This README's question names DuckDB in that
role, which is not what the study wrote. The study found DuckDB best on disk (12.7% of raw against
23.2%). It also found DuckDB worst for single-row writes: five times slower than SQLite, with its
disk advantage gone (0.57 of raw against 0.23). Its point lookups were 12.6 ms and 536 MiB against
0.05 ms and 46 MiB. **This table, on 25 pages, can confirm or contradict none of that.** Both
files are five blocks, so the size row cannot separate the paths. The study's single-row costs
were measured with about 10,000 inserts into a 50,000-row base and with 500 upserts into a copy of
the 130,880-page store. 25 rows reach neither. The wall-time row is set by the host's 5 s poll. The lookups here run at 66 MiB, with
about 10 ms of each cell spent opening the file. That is a property of a tiny file, not evidence
against the study's 536 MiB. What the table does show is that the two paths store identical pages.
The per-item spider holds 71 MiB more, and its 25 inserts took 0.049 to 0.060 s in all against a
1 s delay. That is the extent of its evidence. The one figure past 25 pages is a by-product: the
shared `prototype.duckdb` grew by 524288 bytes when Graph's 12346775 bytes of HTML loaded, and by
2097152 bytes for Workspace's 60636097. These are deltas on a file that already held other runs,
whose free blocks may have been reused. They are not isolated sizes and not compression ratios.
**Inference:** they are consistent with the study's finding that DuckDB's ZSTD compresses
templated HTML well when it is loaded in bulk. Nothing here tests SQLite.

### Sharp edges and their workarounds

#### smolmachines 1.32.4

- **`Machine.__exit__` deletes the machine.** No `with` block manages one here.
- **`Machine.connect` starts a stopped machine, and the SDK has no attach that does not start
  one.** Reports read the state through `open` first and connect only to a machine this checkout
  owns that is already running. A stop landing between the two still boots it. That window is
  inferred from the code, not measured.
- **An `open` handle cannot `exec` in a fresh process** (`expected started, got not started`). The
  version read uses `connect`.
- **The machine registry is host-global, and the SDK records no owner.** The workaround is a random
  generation in a machine label and in the checkout's state file, compared through `Machine.list`.
  The create path that writes it has not run live.
- **`exec`'s timeout kills, its output cap truncates silently, and a host SIGKILL takes the guest
  command with it.** The workaround is `background=True`, output to a guest log, and a done marker
  written through a temp file and `mv`.
- **`background=True` takes no timeout, and a `stop` leaves no marker.** Liveness checks the boot
  id and `/proc/<pid>/cmdline` against the run, since guest pids restart low after a reboot, once
  the wrapper has written its pid. A run with no pid after 120 s is treated as dead, the lock's own
  staleness rule; that branch was added in the final review, checked offline only, and no recorded
  run reached it. The host has its own deadline, and `CLOSESPIDER_TIMEOUT` is the graceful guard.
- **Nothing serialises processes.** A second process can `exec` or `stop` during a crawl, and a
  stop interrupts an `exec` with `SmolError code=INTERRUPTED`. That was measured from a thread in
  one process; across processes it is inference. The workaround is a guest crawl lock (a symlink
  taken under `flock`). Its release takes the same `flock` too; that was added in the final review
  and checked offline only. Every recorded run predates it, but every one logged `lock: taken` and
  none overlapped another, so the race it closes (a run's release undoing a `stale` takeover) never
  arose. A `vm down` from elsewhere is still not prevented.
- **`/tmp` is wiped by a stop.** Everything durable lives under `/out`.
- **`start_job` and `Job` are cloud-only** by the SDK source. They were not run.
- **What the SDK could not do:** attach to a stopped machine without starting it; record an owner;
  serialise two clients; flag a truncated `exec`; time out a background command; tell "still
  running" from "killed by a stop" without the caller's own markers; or run a local job.

#### Scrapy 2.20.0

- **`REMOTE_CONTROL_ENABLED` is on by default** and listens on a guest port. Set to `False`.
- **`CLOSESPIDER_PAGECOUNT` counts robots.txt responses** (ticket 01), though not 301 hops
  (ticket 04). The page cap lives in the spider, `CLOSESPIDER_ITEMCOUNT` equals the cap, and
  `PAGECOUNT` is a loose backstop. `proto/pages` equal to the cap shows which limit ended the run.
- **`OffsiteMiddleware` allows subdomains, and robots.txt is fetched before a later middleware
  sees the page.** The spider's `Guard` checks the exact host before its robots exemption. That
  fixed a review finding. No subdomain redirect occurred live.
- **Scrapy treats an unreadable robots.txt as allowing everything.** `Guard` fails closed for a
  missing, 429 or 5xx robots.txt. This was not met live.
- **`DOWNLOAD_DELAY_JITTER` defaults to ±50%,** which can put a gap under 1 s. Set to 0.
- **The HTTP cache never expires** (DummyPolicy, `EXPIRATION_SECS=0`). A live run reuses cached
  pages, so throughput is counted from `httpcache/firsthand`. 429 and 503 are kept out of the
  cache, so a replay of a throttled run diverges from it. That trade-off was judged in review 03-1
  and left as it is.
- **The FIFO frontier spends a small cap on the earliest seeds.** Workspace's Drive and Calendar
  seeds yielded only themselves. **Inference:** several seeds do not give several sections. The
  first depth seen is not the shortest under concurrency, so the spider tracks the shortest depth
  per identity, redirect aliases included. A row already stored kept the depth it was written
  with until the final review's fix 6; that fix lowers it at close (see the Graph depth note below).
- **Idle-issued requests skip `RefererMiddleware`.** `referrer` is set explicitly.
- **`html` is `response.text`,** lossy for a page that is not UTF-8. `content_hash` is over the raw
  body.
- **`memusage/max` samples only at start and every 60 s.** The spider records `ru_maxrss` in its
  `closed` handler.
- **An item pipeline's exception is logged and the crawl goes on.** The host reconciles
  `proto/pages` with the rows inserted and refuses a run that lost one.
- **The default `--path-prefix` (the first seed's directory) changed which links a replay
  requests.** Ticket 05's replays pass `--path-prefix /` to reproduce ticket 03's pages.
- **INFO logging does not say which link started a redirect chain.**
- **robots.txt `Crawl-delay` is not read,** and the User-Agent has no contact URL. Both were noted
  for review in ticket 03 and left as they are.

#### DuckDB 2.0.0

- **Fetching a `TIMESTAMPTZ` needs `pytz`, and an unfinished `fetchone()` blocks further work.**
  Displayed columns are cast to `VARCHAR`, and the code uses `fetchall()`.
- **A writer's lock refuses every other open, read-only included.** There is one file per run, and
  it is pulled after the done marker.
- **A crashed writer leaves its pages only in the WAL.** The host refuses to pull when `.wal`
  exists. The recovery is described but not built.
- **Extension autoload and autoinstall could reach the network.** Both are off in the guest.
- **`CHECKPOINT` can fail after `COMMIT`.** The load then warns that the run is stored, instead of
  saying nothing was written. That was checked offline only.
- **Sizes are counted in 256 KiB blocks,** so small runs cannot be told apart by size.

### What this prototype did not exercise

- **`vm destroy` has not run.** The agent's permission system refused it in ticket 02. At the end
  the maintainer chose to keep `scrapy-proto`, stopped, so its HTTP cache (ticket 03's 25 pages and
  ticket 04's two 200-page crawls) stays replayable.
- **The `vm up` create path, which writes the generation label, has not run live.** Every `vm up`
  reconnected to ticket 01's machine, which has no label. A cold image pull through `vm up` is
  therefore not measured either.
- **Ticket 03's two second-review fixes were checked offline only.** They write `run.json` before
  the feed, and they warn after a `CHECKPOINT` failure. Ticket 03's live crawl ran before them.
  Ticket 04's crawls and ticket 05's replays ran code that contains them, but on the normal path.
  The interruption and the checkpoint failure they guard against were reproduced offline only.
- **Ticket 04's last fix was checked offline only.** It shares the shortest depth and the expansion
  across a page's redirect hops, and it landed after both 200-page crawls. Neither crawl reached
  that path.
- **The stale-depth fix (final review, finding 6) was checked offline only.** It lowers, at
  close, the stored depth of a page whose shorter route was found after it was stored: the per-item
  pipeline updates its own file and the bulk load reads `proto/depth_corrections` from the stats
  beside the feed. It landed after every crawl and replay; no run has produced that stat.
- **Ticket 05's two fixes were checked offline, against the five replays' recorded stats.** They
  refuse a lost insert, and they stop `bench_queries.py edges` deleting an existing directory. Both
  landed after those replays. No crawl ran with them.
- **`bench_queries.py bench` now refuses mismatched inputs; checked offline only.** Added in the
  final review, it exits unless `--urls-from` and every benched file each hold one run, one row per
  URL, and the same URL set. The recorded bench (`logs/05-10`) ran before it, on two files that
  meet it (one run, 25 rows, 25 URLs each, the same set), so no recorded number changes.
- Also not run live: the host deadline, TERM and KILL path; the crawl lock's `busy` and `stale`
  branches; a throttled or robots-forbidden close; `CLOSESPIDER_TIMEOUT` closing a run; the
  `redirect_to_fetched`, `redirect_to_requested` and `fetched_via_redirect` paths; the per-item
  `.wal` refusal; a crash in the guest; a `vm down` mid-run; a background run surviving a host
  SIGKILL; an `exec` longer than 660 s; SIGKILL of the VM process; and a host reboot.

### What a decision record citing this should not claim

- That a cold `vm up` costs 42.0 s. The image-cache state is unknown, and the path was the spike's.
- That the sandbox sustains more than 60 pages a minute. Only the 1 s delay was measured, once per
  site, on two sites.
- That this prototype shows DuckDB beats SQLite, or loses to it, for a run's pages. It compared
  DuckDB with DuckDB on 25 pages.
- That the per-item path is safe under a crash. The recovery is not built.
- That the lifecycle is complete. `vm destroy` and the labelled create have not run.

The sections below are the evidence, one per ticket, in the order the tickets landed.

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
- Ownership was then only the state file's presence. Ticket 02 replaced that with a generation
  label on the machine, matched against the state file.

### Ticket 02: the lifecycle

Each command below ran as a fresh process (`uv run --offline scrapyproto vm ...`) on the
`scrapy-proto` that ticket 01 left stopped. All exited 0, with no `pip` run and no network.
Every command ends with the same four-field block.

`vm up`, from stopped:

```text
scrapy-proto exists (stopped); connecting
[time] stopped to running: 0.24s
[time] scrapy check, no pip run: 0.39s
---- state ----
machine:    scrapy-proto
state:      running
scrapy:     2.20.0
state file: present (.../ai_tmp/scrapy-duckdb/state.json)
```

`vm status` afterwards prints the same block, with `scrapy: 2.20.0` read from the guest. `vm down`:

```text
[time] stop: 0.01s
---- state ----
machine:    scrapy-proto
state:      stopped
scrapy:     unknown (the machine is not running)
state file: present (.../ai_tmp/scrapy-duckdb/state.json)
```

`vm status` on the stopped machine prints that block without the `[time]` line.

**Warm `up`.** Stopped to `running` took 0.12 s and the Scrapy check 0.32 s on the second `up`.
The first took 0.24 s and 0.39 s. Earlier runs before the review gave 0.12 to 0.18 s. These time
`Machine.connect` and `state()` only. Interpreter and `uv run` start-up were not measured.

**What the review changed.** One adversarial review (gpt-6-astra) raised three findings, all
judged valid and fixed:

- The block attached to, and ran `scrapy version` in, a machine this checkout did not own. It
  now attaches only to an owned, running machine.
- `vm down` stopped the machine with no ownership check. It now refuses as `up` does.
- Ownership was only the state file naming the machine. `up` now writes a random generation to
  a machine label and to the state file, and ownership compares the two via `Machine.list`.
  Ticket 01's machine has no label (`Machine.list` shows `{}`) and its state file has no
  generation, so absent on both sides still counts as owned. A state file whose generation does
  not match is refused live, exit 1 (`error: scrapy-proto exists but no state file here records
  this machine ...`). Since ticket 03 reuses this machine, a real create that writes the label
  is not exercised by tickets 02 to 05.

Remaining limit:

- `vm status` and every command's final block attach with `Machine.connect` to read Scrapy's
  version only when the machine is running and this checkout's state file claims it; otherwise
  the block says `unknown` and nothing attaches. A stop from another process landing between the
  state read and that attach boots the machine again: the SDK has no attach that does not start.
  Not measured.

**`vm destroy` was not run.** The ticket ends with `vm destroy`, but the run was refused by the
agent's permission system as an irreversible deletion. The maintainer first deferred it to the end
of the prototype, then chose to keep `scrapy-proto` stopped so its HTTP cache stays replayable. Its
code is read but not run, and ticket 03 reused this machine rather than recreating it, so no second
image pull or Scrapy install happened. There is no destroy sample.

### Ticket 03: seeds to DuckDB

One live crawl ran, on the `scrapy-proto` that ticket 02 left stopped, after review moment 1's
valid finding was fixed. Moment 1 (gpt-6-astra) raised two findings. One was valid: a robots.txt
fetch on a subdomain reached through a redirect escaped the exact-host guard, and `Guard` now
checks the host first. The other was judged invalid: it asked for 429 and 503 to be kept for
replay. Commands ran from `prototypes/scrapy-duckdb`, each through `uv run --offline` (uv makes
no request; the guest does).

```sh
scrapyproto vm up
scrapyproto crawl --start-url https://learn.microsoft.com/en-us/graph/api/overview --max-pages 25
```

The crawl's output, trimmed to the run lines, the stats and the summary:

```text
[crawl] run 20261107T111039Z-c29b: ['https://learn.microsoft.com/en-us/graph/api/overview'], hosts ['learn.microsoft.com'], max 25 pages
[crawl] lock: taken
[crawl] started in the guest with background=True (pid 114); log /out/scrapyproto/runs/20261107T111039Z-c29b/crawl.log
[crawl] 0s: alive, 0 pages in the feed
[crawl] exited 0; close reason closespider_pagecount; wall 26.5s
downloader/request_count: 27
downloader/response_status_count/200: 26
downloader/response_status_count/301: 1
httpcache/firsthand: 27
httpcache/miss: 27
httpcache/store: 27
item_scraped_count: 25
proto/frontier_left: 442
proto/pages: 25
proto/requests_issued: 25
proto/robots_status/learn.microsoft.com: 200
response_received_count: 26
robotstxt/request_count: 1
[load] feed lines 25, unique URLs 25, loaded 25
---- summary (read back from DuckDB) ----
run 20261107T111039Z-c29b: 25 pages in `pages` (25 distinct URLs), runs.pages = 25
wall time: 26.5 s (guest clock, wrapper start to Scrapy exit)
html bytes (UTF-8, as stored): 1880793 across 25 pages with html
pages by status:   200: 25
depth histogram:   0: 1, 1: 24
store: .../ai_tmp/scrapy-duckdb/prototype.duckdb, 1323008 bytes after CHECKPOINT
```

The two tables are condensed here; the log prints them as columns. Robots allowed the crawl
(robots.txt 200) and nothing was throttled. **The cap did not overshoot:** 25 pages, 25 items,
25 spider requests. The 27 downloads are those 25, robots.txt and one redirect hop: the seed
answered 301 to `...overview?view=graph-rest-1.0`, which the store keeps as `final_url`. 442 links
were left unfollowed. The 25 pages are the seed and 24 of its links (depth 1), so this is a
breadth sample, not a section of the docs.

`scrapyproto runs` lists the one run (25 pages, 26.5 s). `scrapyproto sql` over `pages`:

```text
status  depth  pages  html_bytes
------  -----  -----  ----------
200     0      1      52746
200     1      24     1828047
```

**Replay.** `crawl` with the same seed and cap plus `--replay` exited 0 in 0.3 s with close reason
`closespider_pagecount`. Its full stats file has `httpcache/hit: 27` and
`downloader/request_count: 27`, and no `httpcache/firsthand`, `httpcache/miss` or
`httpcache/ignore` key. The live run had `httpcache/firsthand: 27`. Scrapy counts
`downloader/request_count` in `DownloaderStats` (850), before `HttpCacheMiddleware` (900) answers
from the cache, so all 27 requests, robots.txt included, were cache hits. `firsthand` is counted
only for a response that came from the network. Hence no download reached the site. The replay
loaded 25 pages, all 25 URLs the same as the live run's, with the same `content_hash` and depth
(0 only-live, 0 only-replay). Inference, not measured: the cache serves each response as
recorded, so the spider sees the same links in the same order and fills the cap with the same
URLs. One 25-page run does not show that this holds for a larger crawl.
The replay loaded into the same store as a second run, `20261107T111121Z-fe04`, so `pages` now
holds 50 rows and the store is 2371584 bytes after `CHECKPOINT`.

**Stopped machine.** After `vm down`, the same `crawl` printed the following, exited 1 and left the
machine `stopped`:

```text
error: scrapy-proto is stopped; run `scrapyproto vm up` first. Nothing was requested.
```

Not shown by this run: the 30 s progress line (the crawl ended first), the deadline and kill path,
the lock's `busy` and `stale` branches, and a throttled or robots-forbidden close. The per-item
comparison in ticket 05 rests on these 25 pages.

### Ticket 04: guiding and filtering parameters

`crawl` now takes the rest of the scope vocabulary: `--path-prefix`, `--include`, `--exclude`,
`--max-depth`, `--keep-query-param`, `--delay`, `--concurrency`, `--user-agent` and `--dry-run`,
next to 03's repeatable `--start-url` and `--allowed-host`. `src/scrapyproto/scope.py` holds the
identity and the in-bounds test after `CrawlScope`. The host imports it for `--dry-run`, and its
source is pasted into the rendered spider. Patterns match the identity, never the raw URL. A glob is
`fnmatchcase` over the whole identity. A `re:` pattern is `re.search`, unanchored, so
`re:^/user-get` never matches: the identity begins `https://`. `--delay` cannot go below 03's 1 s,
and `--concurrency` is 1 to 4. The resolved scope is stored in `runs.scope`.

**Cache identity.** The spider requests a link as discovered, with only the fragment removed, as
03 did. The identity (kept query parameters only, sorted) is used for the scope test and dedup
alone. So dropping `?view=graph-rest-1.0` from the identity does not change the request or its cache
key. What does change is which links are requested. A link whose identity was already queued or
fetched is skipped. In the 25-page replays below, that left 438 links in the frontier against 03's
442. A redirect hop onto an identity already fetched or requested is dropped, and so is a hop that
leaves the scope, even from a seed. The "or requested" half (a hop onto an identity whose own request
is still in flight, which could store one identity twice) was added in the final review and checked
offline only; every recorded run predates it, and none of their stores holds a duplicated identity.
The default `--path-prefix` is the first seed's directory, `/en-us/graph/api/`, which drops 03's
`/en-us/lifecycle/...` page. That is why the replays below pass `--path-prefix /` to reproduce
03's host-only scope.

**Exclude test, no site request.** Three replays over 03's cache, on the same seed and cap
(`logs/04-03` to `04-06`):

```sh
scrapyproto crawl --start-url https://learn.microsoft.com/en-us/graph/api/overview --max-pages 25 --path-prefix / --replay
scrapyproto crawl ... --exclude '*/graph/api/user-get' --replay
scrapyproto crawl ... --exclude 're:/user-list-(manager|directreports)$' --replay
```

| Run | Exclude | Pages | `httpcache/hit` | `miss` = `ignore` | `firsthand` |
| --- | --- | --- | --- | --- | --- |
| `20261107T112648Z-5382` | none | 25 | 27 | absent | absent |
| `20261107T112700Z-f841` | glob | 24 | 26 | 26 | absent |
| `20261107T112711Z-7b76` | `re:` | 23 | 25 | 27 | absent |

`scrapyproto sql` against 03's live run `20261107T111039Z-c29b` shows the following:

- **The control replay** loads the same 25 URLs.
- **The glob replay** lacks exactly `.../graph/api/user-get?view=graph-rest-1.0`.
- **The `re:` replay** lacks exactly `user-list-manager` and `user-list-directreports`.
- **No replay** loads a URL that 03 did not, or a different `content_hash`.

Each excluded link gave its slot back. The next frontier links, such as
`section-post-pages?view=graph-rest-1.0`, were not in the cache. Each was dropped as a miss until
the spider had issued its 50 requests, and it closed `finished`. No response came from the network:
`httpcache/firsthand` is absent and every miss was ignored. The stats count the exclusions as
`proto/links/excluded: 1` and `2`.

**`CLOSESPIDER_PAGECOUNT` is now a loose backstop.** It was the cap plus the hosts. It is now
`2 * max_pages * 3 + hosts`, 1201 for a 200-page run on one host: the at most `2 * max_pages`
requests the spider issues, times the 3 downloads per request that `CLOSESPIDER_TIMEOUT` already
assumes. `CLOSESPIDER_ITEMCOUNT` stays at the cap, so a run that fills the cap closes as
`closespider_itemcount`; `proto/pages` equal to the cap is what shows the spider's own cap ended it.
Measured on all three runs below: a 301 hop is not counted. `response_received_count` is 201
against 202 downloads (Graph, one 301) and 201 against 204 (Workspace, three 301s), so the
counter saw robots.txt and the pages only.

**Replay after the review fixes, no site request** (`logs/04-replay-03-after-fixes.txt` and
`04-replay-03-after-fixes-prefix-root.txt`). Ticket 03's exact command plus `--replay`, run
`20261107T113923Z-0c5d`, loaded 24 pages, not 25: the default prefix `/en-us/graph/api/` now
drops 03's lifecycle page (`proto/links/off_prefix: 54`), and the freed slots went to links that
are not in the cache (`httpcache/miss 26` = `ignore 26`, closed `finished`). The same command
with `--path-prefix /`, run `20261107T113944Z-8d7d`, matches 03: 25 pages, `httpcache/hit 27`,
`downloader/request_count 27`, closed `closespider_itemcount`. Neither full stats file has
`httpcache/firsthand` or any `proto/guard/redirect_*` key, and both have
`response_status_count/301: 1`; the seed's feed row reads `overview` →
`overview?view=graph-rest-1.0`, status 200, depth 0. So the seed's 301 passes the stricter
redirect check. Ticket 05's replay must pass `--path-prefix /`.

#### The two 200-page crawls

Run from `prototypes/scrapy-duckdb` after `scrapyproto vm up`, once each, each through
`PYTHONUNBUFFERED=1 uv run --offline`:

```sh
scrapyproto crawl --start-url https://learn.microsoft.com/en-us/graph/api/overview --max-pages 200 --path-prefix /en-us/graph/api/ --keep-query-param view --exclude 're:[?&]view=(?!graph-rest-1\.0(&|$))' --max-depth 3
scrapyproto crawl --start-url https://developers.google.com/workspace/ --start-url https://developers.google.com/workspace/gmail/api/reference/rest --start-url https://developers.google.com/workspace/drive/api/reference/rest/v3 --start-url https://developers.google.com/workspace/calendar/api/v3/reference --max-pages 200 --path-prefix /workspace/ --keep-query-param hl --exclude 're:[?&]hl=' --max-depth 3
```

The `--dry-run` of the Graph line (`logs/04-16-dryrun-graph-final.txt`), trimmed:

```text
# scrapyproto crawl --dry-run: nothing was started and nothing was requested
- path prefixes: a URL is in scope only when its identity's path starts with one of ['/en-us/graph/api/']
- exclude: ['re:[?&]view=(?!graph-rest-1\\.0(&|$))']
- max depth: 3; a link whose shortest known route is deeper is not followed
- page cap: 200 pages, enforced in the spider; at most 400 spider requests
- kept query parameters: ['view']; every other parameter is dropped from the
- a seed is always in scope; a redirect hop must stay in scope (a seed's own redirect included),
- CLOSESPIDER_TIMEOUT 1320 s; host deadline 1440 s
  "CLOSESPIDER_PAGECOUNT": 1201,
  "CLOSESPIDER_ITEMCOUNT": 200,
```

Summaries (`logs/04-crawl-graph.txt`, `logs/04-crawl-workspace.txt`) and full stats
(`logs/04-18-graph-feed-and-stats.txt`, `logs/04-19-workspace-feed-and-stats.txt`):

| | Graph `20261107T114236Z-46bf` | Workspace `20261107T114550Z-2a9f` |
| --- | --- | --- |
| Close reason | `closespider_itemcount` | `closespider_itemcount` |
| Pages, spider requests | 200, 200 | 200, 202 |
| Pages by status | 200: 200 | 200: 200 |
| Depth histogram, as stored | 0: 1, 1: 24, 2: 40, 3: 135 (12 stale, see below) | 0: 4, 1: 196 |
| Least depth over the stored link graph | 0: 1, 1: 24, 2: 52, 3: 123 | 0: 4, 1: 196 |
| Downloads: 200 / 301 | 201 / 1 | 201 / 3 |
| `httpcache/firsthand` / `hit` | 176 / 26 | 204 / absent |
| Wall (guest clock) | 175.9 s | 204.9 s |
| Real downloads per minute | 60.0 | 59.7 |
| `robots_status` | 200 | 200 |
| `proto/links`: off-host, off-prefix | 223, 100 | 280, 701 |
| `proto/links`: excluded, too deep, depth lowered | 1, 360, 21 | absent, absent, 17 |
| `proto/guard/redirect_off_prefix` | absent | 1 |
| Frontier left | 357 | 1855 |
| HTML stored | 12346775 bytes | 60636097 bytes |

**Both runs reached the cap with 200s only:** 200 of 200 pages are status 200 in each, and
`scrapyproto sql` grouping `pages` by status agrees (`logs/04-20-crawls-sql.txt`). In each the
spider's own cap ended the run: `proto/pages` is 200, and `response_received_count` (201) is far
below the 1201 backstop. Nothing was throttled, and robots.txt answered 200 on both hosts. Pages
per minute is `httpcache/firsthand` over the wall time, so it counts robots.txt and 301 hops as
downloads and leaves out Graph's 26 cache hits: 176 / 175.9 s and 204 / 204.9 s. Both sit at the
1 s delay's ceiling of 60. The Graph hits are 03's cached robots.txt, the seed's 301 and the 24
pages the two runs share (`sql`: 24 URLs in both runs).

**Graph: what it threw at the scope.** Every on-host outlink starts with `/en-us/` (841 distinct,
`logs/04-18`), so no locale variant appeared, and `--path-prefix /en-us/graph/api/` pins the
locale. That prefix also kept out 100 off-prefix identities: Entra, Exchange and Graph concept
pages under `/en-us/graph/`. The host test kept out 223 off-host identities; the most frequent hosts are
github.com (202 distinct links), go.microsoft.com, aka.ms and techcommunity.microsoft.com.
Inference from the hosts, not read link by link: these are the edit, feedback and footer links. Version selectors: 728 distinct outlinks carry
`view=graph-rest-1.0`; `--keep-query-param view` keeps that in the identity, and the `re:` exclude
dropped the one in-prefix variant, `overview?view=graph-rest-beta&preserve-view=true`
(`proto/links/excluded: 1`; `Scope.verdict` on that URL offline returns `excluded`). The other
`view=` values (`o365-worldwide`, `exchserver-2019`, `odsp-graph-online`) are on other doc sets
and fell to the prefix. Redirects: only the seed redirected, so the expected many 301 hops from
bare links did not happen in these 200 pages. Eleven bare in-prefix links (such as
`resources/user`) were discovered and none was requested; whether they would 301 is not
measured. Depth: the cap was not reached at depth 2 as the plan guessed: 123 pages are at least
depth 3 (135 as stored; 12 were stored before a shorter route was found), and 360 links were
refused as too deep, so `--max-depth 3` shaped which 200 pages were kept. **Fact** (offline BFS
from the run's seed over the stored pages' `outlinks`, with the prototype's `scope.identity_of`):
12 Graph rows say depth 3 where the run's own link graph puts them at 2, and for each of them the
first depth-1 page linking it was parsed later than the row. `proto/links/depth_lowered` (21)
counted the lowering, but the row was not updated: a defect in the code these crawls ran, fixed
afterwards and checked offline only (final review, finding 6). **Inference:** Scrapy's scheduler
ran some depth-1 pages after their depth-3 descendants; not traced in Scrapy. The Workspace
histogram, ticket 03's `0: 1, 1: 24` and ticket 05's replays are unaffected (nothing there can sit
below depth 1).
All 200 stored URLs carry `?view=graph-rest-1.0`, and 80 are `resources/` pages.

**Workspace: what it threw at the scope.** Every Workspace flag was a guess; nothing was fetched
from the site before this run. What happened to each guess:

- **Seeds.** All four answered 200 with no redirect. Breadth first, the cap went to the first
  seeds' links: 157 pages have the Gmail reference as referrer and 38 have `/workspace/`
  (`sql` on `referrer`). No stored page has the Drive or Calendar seed as referrer, so those
  seeds yielded only themselves. The spider issued 202 requests for 200 pages and one dropped
  redirect; the fate of the remaining request is not recorded. Inference: a FIFO frontier spends a small cap on the
  earliest seeds, so several seeds do not give several sections.
- **`?hl=` locale.** No outlink carried `hl` (`logs/04-19`: no `hl` among outlink query
  parameters), and `proto/links/excluded` is absent, so `--exclude 're:[?&]hl='` and
  `--keep-query-param hl` did nothing on these pages. The starvation risk noted before the crawl
  did not occur.
- **Navigation inside the prefix.** The guess that navigation lies outside `/workspace/` was
  wrong. The `/workspace/` hub's 38 links are product landing and site pages such as
  `/workspace/terms`, `/workspace/support`, `/workspace/newsletters` and `/workspace/videos`; by
  `sql`, 155 stored URLs contain `/reference` and 45 do not. No flag in the command
  answered this. Inference, not tried since each crawl ran once: an `--include` such as
  `*/reference*` would keep these out, while the seeds stay in scope.
- **Off-prefix and off-host links.** The prefix kept out 701 identities, mostly older paths such
  as `/apps-script/` and `/admin-sdk/` (`logs/04-19`), and the host test 280, such as
  code.google.com and support.google.com. Other query parameters (`component`, `id`, `product`)
  appeared on outlinks and were dropped from the identity by default.
- **Redirects off the prefix.** `/workspace/resources-menu` redirected to `/workspace/resources`,
  which is in scope and was stored. One other redirect led to `https://developers.google.com/workspace`
  (no trailing slash), which is off `/workspace/`; Guard dropped it
  (`proto/guard/redirect_off_prefix: 1`) and the slot went back. Which link started that chain is
  not measured: the log runs at INFO.
- **Robots.** robots.txt answered 200 and no request was forbidden.

**Paths now run live.** The redirect scope check in Guard (Workspace, once), the shortest-depth
fix (`proto/links/depth_lowered` 21 and 17) and `too_deep` (Graph, 360). The lowering corrected
the frontier, but not 12 rows already stored in the Graph run; the fix for those rows came later
and has not run live. Still not run live: `redirect_to_fetched` and the `fetched_via_redirect` skip.

### Ticket 05: per-item DuckDB against the bulk load

**This comparison rests on 25 pages.** They are ticket 03's cached crawl, replayed. At this size the
DuckDB study's findings, made on 130,880 pages, are neither confirmed nor contradicted by anything
below.

`crawl --store per-item` runs the same spider with an item pipeline, `DuckDBPipeline`. It inserts each
page, as it arrives, into `/out/scrapyproto/runs/<run_id>/pages.duckdb` on the guest disk, one autocommit
`INSERT OR IGNORE` per page, using the host store's schema (`html VARCHAR USING COMPRESSION ZSTD`).
Extension autoload and autoinstall are off, so DuckDB fetches nothing. No feed is written. At close
the pipeline writes the file's `runs` row, then runs `CHECKPOINT` and closes the connection. Scrapy
calls a pipeline's `close_spider` before it sends `spider_closed` (`engine.close_spider_async`, read in
the guest, `logs/05-03`), so all of this lands before the spider's `closed` handler. That handler reads
`ru_maxrss` and dumps the stats. The host then lists the run directory and refuses to pull when
`pages.duckdb.wal` exists. Otherwise it reads the file with `read_file`, checks the byte count against
the guest's `stat`, and writes it to `ai_tmp/scrapy-duckdb/<run_id>-per-item.duckdb`. It refuses to
record a file that has no `runs` row for the run, or whose page count differs, and refuses to pull
at all when the stats show a lost page (`proto/pages` is not inserted plus duplicates, or an insert
failed: Scrapy logs a pipeline error and crawls on). Otherwise it records the
run in the host store's `runs` table with `store = 'per-item'`, and prints the summary from the pulled
file. `runs` gained `store` and `store_file`; the older runs read `bulk` (`logs/05-15`: 14 bulk, 5 per-item). Guest DuckDB is 2.0.0, the host's pin,
installed by `scrapyproto vm install-duckdb` (the cp312 abi3 manylinux aarch64 wheel, 21.7 MB, 1.25 s,
`logs/05-pip-duckdb.txt`).

**The runs.** Five replays per path, alternating bulk and per-item (`logs/05-replay-{bulk,per-item}-{1..5}.txt`).
Each one ran from `prototypes/scrapy-duckdb`, through the timing harness:

```sh
uv run --offline python bench_queries.py wall -- uv run --offline scrapyproto crawl \
    --start-url https://learn.microsoft.com/en-us/graph/api/overview --max-pages 25 --path-prefix / \
    --replay --store bulk    # or --store per-item
```

This is ticket 03's seed and cap plus `--replay`. It also needs `--path-prefix /`, which reproduces 03's
host-only scope: since ticket 04, the default prefix drops 03's lifecycle page and the replay then takes
cache misses. Every one of the ten runs closed `closespider_itemcount` with `proto/pages 25`,
`item_scraped_count 25`, `downloader/request_count 27`, `downloader/response_count 27` and
`httpcache/hit 27`. No stats file has `httpcache/firsthand`, `miss` or `ignore` (`logs/05-06`, `logs/05-15`). All 27
responses, robots.txt included, came from the cache, so **neither path made a site request**.
`scrapyproto runs` lists the five per-item runs with store `per-item` (`logs/05-09`). A per-item run's
output, trimmed:

```text
proto/ru_maxrss_kib: 163188
proto/store/checkpoint_s: 0.004872
proto/store/closed: 1
proto/store/insert_s_max: 0.004915
proto/store/insert_s_total: 0.060357
proto/store/rows: 25
proto/store/wal_after_close: False
[pull] /out/scrapyproto/runs/20261107T120906Z-f4bb/pages.duckdb -> .../20261107T120906Z-f4bb-per-item.duckdb: 1323008 bytes, the guest's size
[record] runs row for 20261107T120906Z-f4bb (store per-item, 25 pages) in .../prototype.duckdb
run 20261107T120906Z-f4bb: 25 pages in `pages` (25 distinct URLs), runs.pages = 25
store kind: per-item; pages read from .../20261107T120906Z-f4bb-per-item.duckdb
```

**Same pages.** Each of the five pairs was compared with `bench_queries.py compare` (`logs/05-08`):
the bulk run in `prototype.duckdb` against its per-item file, and the isolated bulk file against the
per-item file. Every pair has 25 rows on each side, the same 25 URLs, the same `content_hash` set
and the same `(url, content_hash, md5(html))` set. So does 03's live run `20261107T111039Z-c29b`
against the first per-item file. Every file stores `html` in a ZSTD segment, plus one Constant segment.

**The table.** Five runs per path for the run rows. Seven measured runs per query and file, after one
discarded warm-up, for the query rows. Each cell is the median, then the range in brackets.

| Measure | bulk | per-item |
| --- | --- | --- |
| Wall time of the run, host process start to summary printed | 5.275 s [5.270 to 5.298] | 5.251 s [5.243 to 5.266] |
| Beside it: guest wall, wrapper start to Scrapy exit | 0.328 s [0.293 to 0.422] | 0.424 s [0.400 to 0.464] |
| Beside it: host, done marker seen to summary printed | 0.14 to 0.15 s | 0.07 to 0.08 s |
| Peak RSS of the spider process in the guest | 88.7 MiB [88.68 to 88.74] | 160.1 MiB [159.4 to 160.6] |
| Store file size after `CHECKPOINT` | 1323008 bytes, all 5 | 1323008 bytes, all 5 |
| Host-side point lookup by URL (25 lookups): time | 24.9 ms [24.6 to 26.5] | 24.5 ms [22.8 to 25.3] |
| Host-side point lookup by URL: peak RSS | 66.3 MiB [66.2 to 66.5] | 66.3 MiB [66.2 to 66.6] |
| Host-side full scan of `html`: time | 14.1 ms [13.0 to 14.4] | 14.0 ms [13.1 to 14.5] |
| Host-side full scan of `html`: peak RSS | 68.4 MiB [68.2 to 68.5] | 68.4 MiB [68.2 to 68.4] |

How each number was taken, one line each:

- **Wall time:** `bench_queries.py wall` stamps `perf_counter` before it spawns `uv run --offline scrapyproto
  crawl ...` and again when the summary's `store:` line arrives. The host polls the guest every 5 s, so
  both paths land at about 5 s, and this row cannot tell them apart.
- **Guest wall:** `started.at` to `finished.at`, written by the guest wrapper around `scrapy runspider`
  (guest clock).
- **Host after the done marker:** the `crawl` command's own `[time] host:` line, from `time.monotonic`.
  For bulk this is the feed pull plus the load; for per-item, the `.duckdb` pull plus the check and the record.
- **Peak RSS in the guest:** `resource.getrusage(RUSAGE_SELF).ru_maxrss` (KiB on Linux, shown here in
  MiB), read in the spider's `closed` handler inside the `scrapy runspider` process. That is after the
  pipeline's CHECKPOINT and close, and it is not the guest agent's figure. Scrapy's `MEMUSAGE_ENABLED`
  is on for both paths, but its `memusage/max` samples only at engine start and then every 60 s. On a
  run of under 1 s that is the start-up figure: 80.4 MiB for bulk and 120.0 to 120.4 MiB for per-item,
  across the five runs (`logs/05-15`).
- **Store size:** `stat` bytes with no `.wal` beside the file. For per-item, the pulled file. For bulk,
  the figure is isolated from the other runs in `prototype.duckdb`. `scrapyproto load <run_id> --db
  <run_id>-bulk.duckdb` reloads that run's pulled feed into a fresh file with the same loader and its
  CHECKPOINT (`logs/05-07`). Each file then holds one run's 25 pages and its one `runs` row, like the
  per-item file. DuckDB allocates 256 KiB blocks, so this row counts blocks: 5 in each file, none free
  (`pragma_database_size`). An offline probe (`logs/05-12`) loaded the same 25 rows into four scratch
  files. It shows that the `runs` row alone costs 2 of the 5 blocks: 798720 bytes without it and
  1323008 with it, whether or not an explicit CHECKPOINT ran before the close. So at 25 pages this row
  cannot tell the two write paths apart.
- **Point lookup:** a fresh `python bench_queries.py --child point` process. It opens the file
  read-only, runs `SELECT html FROM pages WHERE url = ?` for each of the run's 25 URLs and hashes each
  `html`. The time runs from before the connect to after the close, and includes about 10 ms of open in
  every cell. The process then reports its own `ru_maxrss` (bytes on macOS). A child that only imports
  DuckDB peaks at 38.8 MiB.
- **Full scan:** the same, with `SELECT html FROM pages`, fetched 64 rows at a time, every value hashed.
- **Equal warmth:** both files sat on the same host disk. Each (query, file) pair had one discarded
  warm-up child first. Each measured round then ran both files, alternating which went first
  (`logs/05-10`). This is the DuckDB study's method, with seven runs instead of its second-of-two.

**Sharp edges of the per-item path.** These were measured offline on the host with DuckDB 2.0.0, using
the per-item file's own 25 rows (`bench_queries.py edges`, `logs/05-11`), or read from the replays' stats.

- **One writer per file.** While a writer holds the file, a second read-write open fails with `IO
  Error: Could not set lock on file ... Conflicting lock is held`, and so does a read-only open. The
  host cannot read a per-item file while the spider is running. Verdict: one file per run, in the run's
  own directory, held by the one `scrapy runspider` that the crawl lock allows; the host pulls only after
  the done marker. Two spiders sharing one file, or a host reading progress live, would need a
  different store. The progress line already counts feed lines, so on this path it reads 0.
- **The pipeline blocks the reactor.** `process_item` is synchronous, so Twisted waits for each insert.
  Over the five replays the 25 inserts took 0.049 to 0.060 s in total, at most 5 ms for one. CHECKPOINT
  took 4 to 5 ms and the open 11 to 18 ms. Against the 1 s download delay that is negligible at this
  page size. Not measured: larger pages, more pages, or a slow disk. The workaround, if it grows, is
  `deferToThread` for a single writer thread, or batching rows into one transaction per N items.
- **A crashed spider.** A writer SIGKILLed after 25 autocommit inserts, before its `runs` row and before
  CHECKPOINT, leaves `pages.duckdb` at 12288 bytes with a `pages.duckdb.wal` of 3011313 bytes. The
  `.duckdb` copied alone, which is what pulling the one file would get, has no `pages` table at all
  (`Catalog Error: Table with name pages does not exist`). Opened with its WAL beside it, it replays
  all 25 pages and 0 `runs` rows. A read-write open then folds the WAL in on close, giving 798720 bytes
  and no WAL. The host can tell, at three points:
  - The stats file lacks `proto/store/closed`, if Scrapy died before `closed` ran. A SIGKILL also
    leaves no stats file, so `crawl` exits 1 without pulling (by the code; this path was not run).
  - The guest listing shows `pages.duckdb.wal`, so `pull_store` refuses.
  - The pulled file has no `runs` row for the run, so `record_per_item` refuses.

  Verdict: a crash loses nothing that the guest's WAL holds, but a single-file pull loses all of it.
  The recovery is to open the guest file read-write in the guest, which replays the WAL, before any
  pull. That recovery is not built.

  Not measured: a crash in the guest itself (only the host probe ran), a crash during CHECKPOINT, and
  a `vm down` mid-run.
- **A gentler close.** A writer that closes without an explicit CHECKPOINT still leaves no WAL (798720
  bytes, `logs/05-11` part 1), because DuckDB checkpoints on a clean close. The explicit CHECKPOINT is
  kept so that the stats can time it.
