# 15: The Verdict, revised for the tail

Tickets 07 to 09 live on PR #14 (`rocksdb-scrapy-duckdb-prototype`, at `63ec30e`).

**Network:** none. Everything cited was measured by tickets 01 to 06 and 10 to 14. Updating PR #13's
description is a separate outward action and needs its own authorization; this ticket does not do it.

**What to build:** the README's Verdict and Recommendations, revised so a decision record can cite
them:

- DuckDB as the store of a run's fetched pages names jsonl-tail over the smol host mount as the path,
  with its conditions (the mount set at create, one consumer per run holding its own file, the cursor
  and the rows committing together, the host never writing the guest's files), and bulk as the
  fallback for a machine without the mount.
- ZSTD on the tail is decided from ticket 11's numbers: adopt, or not, and why, with the cursor it
  would carry.
- The probes of tickets 12 to 14 move out of "What this prototype did not exercise" and "What a
  decision record citing this should not claim", each with what it showed; what they did not cover
  stays there.
- "A host killed during finalization resumes: checked offline only" is replaced by ticket 13's result.
- The finding of PR #14, that RocksDB is not a candidate over the tailed JSONL, is cited by its PR
  and section, not restated as measured here.

Facts stay facts and inferences are marked as such. Anything that was not measured is named as not
measured, not estimated.

**Review:** one moment, through the README's adversarial review loop, once the Verdict is drafted and
before the commit, with the focus: does every number trace to a quoted run or table; is every
inference marked; is the ZSTD decision supported by ticket 11's table and not by PR #14's reference
numbers; do the moved probes claim more than their runs showed; what would a decision record citing
this Verdict be wrong about. Fixes are edits to the README; a finding that needs a new measurement is
recorded as not measured, never estimated.

**Blocked by:** 11, 12, 13 and 14.

**Status:** ready-for-agent

- [ ] The Verdict is dated and names the versions and the machine resources
- [ ] The Recommendations name jsonl-tail as the path, with its conditions, and bulk as the fallback
- [ ] The ZSTD decision is stated with the numbers it rests on
- [ ] The did-not-exercise and should-not-claim lists match what tickets 12 to 14 ran
- [ ] Every number traces to a quoted run or a table; nothing is estimated
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] The adversarial review loop ran on the drafted Verdict; the hand-back lists each finding with
  its verdict and the reviewing model, and every valid finding's edit is in the commit
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged
