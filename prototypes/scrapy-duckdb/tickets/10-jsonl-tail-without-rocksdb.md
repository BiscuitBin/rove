# 10: The JSONL tail, ported without RocksDB (tracer)

Tickets 07 to 09 live on PR #14 (`rocksdb-scrapy-duckdb-prototype`); their numbers are kept there,
which is why this series starts at 10.

**Network:** the first `vm up` creates a new machine, `tail-proto`, so the guest image pull and the
guest `pip install scrapy` (and `vm install-duckdb`) recur. The HTTP cache lives on each machine's
guest disk, so `tail-proto` starts with none: three live crawls seed it, ticket 03's 25-page Graph
command and ticket 04's Graph and Workspace 200-page commands, as the README records them. The
200-page caches are what make the probes below possible: `--crash-after 100` must be below
`--max-pages`, and a 25-page replay lasts about 0.3 s in the guest, too short to kill the host in.
Ask before the create, and before each crawl.

**What to build:** the jsonl-tail arm from the rocks branch at `63ec30e`, carried over by module and
name, with RocksDB cut out, and made the default store:

- `machine.create()` gains the `MountSpec` of `QUEUE_HOST_DIR` (`ai_tmp/scrapy-duckdb/queue`) at
  `QUEUE_GUEST_DIR` (`/queue`), and `MACHINE_NAME` becomes `tail-proto`. smol takes a mount only at
  create, so `scrapy-proto` stays as it is, as the README records, and is not reached from here.
- In the spider source, `TailFileStorage` (the `tailfile://` feed storage) and `_LineFlushed`, so each
  page reaches `/queue/<run_id>/feed.jsonl` whole as soon as it is exported.
- In `queue.py`, `Consumer`, `JsonlTail`, `arm_db`, `host_queue_dir`, the `consumer_offsets`,
  `arrivals` and `clock` tables, `measure_offset` and `latency`, with the 100 ms `TICK_S`.
- In `store.py`, `runs_row`, `record_isolated`, `run_file`, and in the command line `sql --run`, so
  the run's own file `<run_id>-jsonl-tail.duckdb` is recorded in the shared store and readable by run.
- In `crawl.py`, `Plan.live_arms`, the `plan.json` written on the host, and `Plan.crash_after` with the
  spider's SIGKILL of itself after N items, behind `crawl --crash-after N`.
- In the command line, `_follow`, `_drain`, and `scrapyproto consume RUN_ID`, which resumes a run's
  consumer from its committed cursor after the host process died.

The tangles to cut, each named so it is not carried by accident:

- `Consumer.finish()` reads `meta:closed` (the `closed` field); the tail's completeness is the feed
  ending on a line, so `finish()` keeps only the check that rows plus duplicates equal the spider's
  `proto/pages`, and refuses, recording nothing, otherwise.
- `queue.make()` branches on the arm's name, and falls through to `RocksTail`; it builds a `JsonlTail`
  or refuses an unknown arm.
- `_held` and the `unconsumed` check in `_follow` test for `RocksTail`; they keep the `JsonlTail` half
  (bytes past the last complete line).
- The `all` arm in `_follow` and `crawl`, and `load(resume=…)`, which only `all` needed. Comparing the
  tail with bulk takes two `--replay` runs.
- The module-top `rocksdict` import in `queue.py`, `RocksTail`, `ARMS`'s `rocks-queue`, `PAGE_KEY`,
  `CLOSED_KEY`, `SECONDARY_DIR`, `ROCKSDICT_VERSION`, `latency_bulk`, the pipeline's written-bytes
  count, and `spike_rocks.py`. `rocksdict` is not a dependency, and `requires-python` stays `>=3.13`:
  only `rocksdict` forced `<3.15`.

`--store` defaults to `jsonl-tail`; `bulk` and `per-item` work as they do today, and bulk is the
fallback for a machine without the mount. A `crawl --store jsonl-tail` on a machine whose `/queue` is
not the host mount exits 1 before any request, naming `--store bulk`. The README's Design and How to
run sections name `tail-proto`, the default and `consume`, and the README gains a "Ticket 10" section
with the quoted runs.

**Review:** one moment, through the README's adversarial review loop, once the probes below have run
and before the commit, with the focus: what the port left behind or brought along; does any RocksDB
path, name or import survive; is the cursor committed in the same transaction as its rows; can
`finish()` record a run whose rows do not reconcile; does `consume` resume from the committed cursor
with no duplicate and no gap; can a partial line ever be read; does the mount check catch a machine
without it before any request.

**Blocked by:** none. Builds on this branch at `97e40da`.

**Status:** ready-for-agent

- [ ] `vm up` creates `tail-proto` with the mount, and `vm status` shows it; `scrapy-proto` is untouched
- [ ] A crawl with no `--store` uses `jsonl-tail`, puts each page in host DuckDB during the run, and
  `scrapyproto runs` lists it with its store kind; `sql --run` reads its pages
- [ ] A jsonl-tail replay and a bulk replay of the same cache are equal under
  `bench_queries.py compare` in rows, URLs and `content_hash`, and neither made a site request
- [ ] `--crash-after 100` on a 200-page cache leaves 99 rows on the host, the run unrecorded, and 0
  bytes past the last complete line
- [ ] A host SIGKILLed mid-run on the Workspace 200-page replay, then `consume`, ends with 200 rows,
  0 duplicates, and the run recorded once
- [ ] `crawl --store jsonl-tail` on a machine without the mount exits 1 before any request
- [ ] No `rocksdict`, `RocksTail`, `meta:closed` or `all` arm remains in `src/scrapyproto/`, and
  `requires-python` is `>=3.13`
- [ ] The README's "Ticket 10" section quotes the runs above
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] The adversarial review loop ran at its moment; the hand-back lists each finding with its
  verdict and the reviewing model, and every valid finding's fix is in the commit
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged
