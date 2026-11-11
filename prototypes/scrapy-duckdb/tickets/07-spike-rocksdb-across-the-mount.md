# 07: Spike: RocksDB across a smol host mount

**Network:** the `python:3.12` image pull for a new machine, the guest `pip install scrapy==2.20.0
rocksdict==0.3.29`, and the host `uv lock` that adds `rocksdict==0.3.29` and pins the host to
Python 3.14 (rocksdict 0.3.29 has no cp315 wheel). Authorized with the plan; nothing is crawled.

**Why:** tickets 01 to 06 carry a run's pages from the guest to the host only after the run: a JSONL
feed pulled with `read_file` and bulk-loaded. The question for 07 to 09 is whether RocksDB can be a
*live queue* instead: the spider appends pages to RocksDB and the host consumes them into DuckDB while
the crawl runs. The python-rocksdb binding the question named is source-only and last released in
2019; `rocksdict` is used instead.

**What to build:** `spike_rocks.py`, which creates a second machine, `rocks-proto`, from `python:3.12`
with the same resources as `scrapy-proto` plus one writable, unstaged host mount,
`<repo>/ai_tmp/scrapy-duckdb/queue` at `/queue`. `scrapy-proto` and its state are never touched. The
spike installs both guest pins and then shows, or refutes:

1. A guest primary that puts N keys, with no sync and `flush_wal`, is seen by a host secondary
   instance after `try_catch_up_with_primary()`; the put-to-visible latency, measured.
2. RocksDB's `LOCK` and fsync work on the mount in the guest.
3. A guest primary SIGKILLed mid-write: the host secondary still reads every put the writer
   reported, and a host read-write open afterwards recovers the WAL.
4. A JSONL line appended on the mount is visible to a host tail, and how soon.

If (1) fails, climb the ladder and record which rung held: (2) the primary on the guest disk with
periodic checkpoints into `/queue`, opened read-only on the host; (3) no mount, checkpoints pulled
file by file with `read_file`, new immutable SSTs only.

**Review:** one moment, once the spike's output is recorded in the README, with the focus: does the
latency measure what it says (clocks, polling), does the crash probe kill the writer and not the
agent, is anything read from a file the host could only see because of a stop or a sync.

**Blocked by:** 06.

**Status:** ready-for-agent

- [ ] `rocks-proto` exists, stopped, with the mount; `scrapy-proto` untouched
- [ ] Each of the four probes is recorded in the README with its numbers, or the rung that replaced it
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] The adversarial review loop ran; the hand-back lists each finding with its verdict
