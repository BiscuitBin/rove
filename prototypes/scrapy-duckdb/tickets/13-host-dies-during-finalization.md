# 13: The host dies during finalization, live

Tickets 07 to 09 live on PR #14 (`rocksdb-scrapy-duckdb-prototype`, at `63ec30e`).

**Network:** none. Every probe replays ticket 10's Graph 25-page cache on `tail-proto`; the kill
lands after the spider has finished, so the short replay is enough. If the cache is gone, seeding it
again is network, so ask first.

**What to build:** a prototype-only probe flag on `crawl` and `consume` (for example
`--die-at POINT`) that SIGKILLs the host process at one point of a jsonl-tail run's finalization.
The points follow the code, not a list of steps, since the depth corrections and the run file's
`runs` row commit in one transaction:

1. after `_drain`, before `finish()`;
2. inside `finish()`'s transaction, after the depth corrections and before the `runs` row;
3. after that transaction's COMMIT, before the run file's `CHECKPOINT`;
4. after the run file's `CHECKPOINT`, before `record_isolated` writes the shared store;
5. after `record_isolated`'s insert, before the shared store's `CHECKPOINT`.

For each point, `consume` must then complete the run exactly once: the run file holds every page and
one `runs` row, the shared store one `runs` row naming that file, the depth corrections are applied,
and `bench_queries.py compare` finds the pages equal to a clean replay's. A point where `consume`
refuses instead is a finding, recorded with its message. The flag is off by default and does nothing
on `bulk` or `per-item`.

This replaces "a host killed during finalization resumes: checked offline only" in the Verdict's
lists, which ticket 15 updates.

**Review:** one moment, through the README's adversarial review loop, once the five probes have run
and before the commit, with the focus: does each kill land where it says; can any point leave two
`runs` rows, a `runs` row without its pages, or pages whose depth was never corrected; does a resume
after point 4 or 5 trust a shared-store row it should check; is DuckDB's WAL replay on the next open
what makes a point safe, and is that said.

**Blocked by:** 10 (the tail, `consume` and `record_isolated`).

**Status:** ready-for-agent

- [ ] Each of the five points was killed live, and its log is quoted in the README
- [ ] After each, `consume` completed the run once, with no duplicate `runs` row and no lost page, or
  the refusal is recorded as a finding
- [ ] Each resumed run equals a clean replay under `bench_queries.py compare`
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] The adversarial review loop ran at its moment; the hand-back lists each finding with its
  verdict and the reviewing model, and every valid finding's fix is in the commit
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged
