# 09: The live queue compared with the bulk load

**Network:** three polite live crawls on `rocks-proto`, which has no HTTP cache yet: ticket 03's
25-page Graph command and ticket 04's Graph and Workspace 200-page commands. Authorized with the plan.
Everything after them is an offline `--replay`.

**What to build:** the comparison, and a README section for 07 to 09.

1. The live crawls run once each with `--store rocks-queue`, the spider writing the guest-disk feed
   and the mount feed at the same time, so one crawl gives all three arms at real pace.
2. Replays: each of the three sizes, each arm, five runs, arms alternating, through
   `bench_queries.py wall`. Every replay's stats show cache hits only.
3. `bench_queries.py compare` on every replay pair against bulk: same URLs, `content_hash`, `md5(html)`.
4. Measures that can separate the arms: first page fetched to first row in host DuckDB; fetch to host
   commit, p50 and p95; done marker to summary; guest wall; spider `ru_maxrss`; bytes written across
   the boundary (RocksDB directory against JSONL, with the JSONL's gzip size beside it); host DuckDB
   size after `CHECKPOINT`, per-tick inserts against the bulk load.
5. Crash probe: `--crash-after 100` on the 200-page replays, each arm; what host DuckDB holds and what
   `consume` or `load` recovers.
6. Host-resume probe: the host `crawl` killed mid-run, then `consume`.

The dated Verdict stays as written; it gains a pointer to the new section, whose recommendation is one
of candidate, not a candidate, candidate with conditions. Facts and inferences are marked as in 06.

**Review:** one moment, once the table is filled and before it is read into a conclusion, with
ticket 05's focus plus: is the latency clock the same on both sides, is any arm favoured by the
cache, does the conclusion credit RocksDB with what the mount alone gives.

**Blocked by:** 08.

**Status:** ready-for-agent

- [ ] The table and both probes are in the README, each number with its method in one line
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] The adversarial review loop ran; the hand-back lists each finding with its verdict
