# 11: A line-flushed streaming ZSTD feed on the tail

Tickets 07 to 09 live on PR #14 (`rocksdb-scrapy-duckdb-prototype`, at `63ec30e`).

**Network:** the guest runs Python 3.12, which has no `compression.zstd`, so the spider needs the
`zstandard` package: a guest `pip install zstandard==<exact version>`, with a dependency note in
the README naming the version and why. The host decodes with the standard library's
`compression.zstd`, which first shipped in Python 3.14; with `requires-python` at `>=3.13`, either the
floor moves to `>=3.14` (a re-lock, which may reach the network) or the host decoder refuses on 3.13
with a message. Ask before the install and before any re-lock. Everything else replays the three
caches ticket 10 seeded on `tail-proto` (Graph 25, Graph 200, Workspace 200); if they are gone,
seeding them again is network, so ask first.

**What to build:** a ZSTD codec for the jsonl-tail feed, behind a flag on `crawl` (for example
`--tail-codec raw|zstd`, default `raw`). The guest writes `/queue/<run_id>/feed.jsonl.zst` as one
ZSTD stream, flushed at the end of every line (`FLUSH_BLOCK`), so each complete page reaches the mount
without closing the frame. The host tail keeps one decompressor open across ticks, feeds it the
bytes past what it has read, and commits only complete decoded lines, as the raw tail does.

The raw tail's cursor, the offset just past the last newline in the file, does not exist in a
compressed stream, so this ticket defines one and proves it: what the cursor records (for example,
the decoded byte offset of the last committed line, with resume decoding the stream from its start
and skipping to it; or a frame boundary every N lines, resumed from the last one), what `consume`
does with it after the host died, and what the tail does with a block cut off mid-write. The
`consumer_offsets` row says which codec its cursor belongs to, and a resume with the other codec
refuses.

Measured on the three replays, five rounds per codec and size with the codecs alternated, medians
with ranges, as ticket 09 did:

| Measure | raw | zstd |
| --- | --- | --- |
| Bytes across the mount (the feed's size at close) | | |
| The raw feed under `gzip -6` and `zstd -3`, compressed whole on the host, for reference | | |
| Fetch to host commit, p50 and p95 (`latency`) | | |
| First fetch to first row | | |
| Spider peak RSS | | |
| Host consumer CPU time | | |

Page sets equal raw's under `bench_queries.py compare`, in every round. The gzip and zstd references
are measured on this branch's feeds, not copied from PR #14.

Probes: `--crash-after 100` on a 200-page cache with `--tail-codec zstd` leaves 99 rows on the host
and no partial line read, and the bytes past the last complete line are reported; a host SIGKILL
mid-run on the Workspace replay, then `consume`, ends with 200 rows and 0 duplicates.

Whether to adopt ZSTD is decided in ticket 15, not here; this ticket records the numbers.

**Review:** one moment, through the README's adversarial review loop, once the table is filled and
before it is read into a conclusion, with the focus: the cursor; is it defined so that a resume after
a host kill is exact; can a block cut off mid-write be decoded into a wrong or partial line; is the
flush per line really what reaches the mount; do the byte counts compare like with like; is the RSS
the spider's; are the two codecs' runs the same pages.

**Blocked by:** 10 (the tail, `consume`, `latency` and the seeded caches).

**Status:** ready-for-agent

- [ ] `crawl --tail-codec zstd` on each of the three replays stores the same page set as raw, with no
  site request
- [ ] The cursor's definition is written in the README, and the host-kill resume ends with 200 rows
  and 0 duplicates
- [ ] `--crash-after 100` with ZSTD leaves 99 rows and no partial line read
- [ ] The table is in the README with its numbers, the method for each number in one line
- [ ] The `zstandard` guest pin and the host's `compression.zstd` floor or guard are recorded, with
  their reasons
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] The adversarial review loop ran at its moment; the hand-back lists each finding with its
  verdict and the reviewing model, and every valid finding's fix is in the commit
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged
