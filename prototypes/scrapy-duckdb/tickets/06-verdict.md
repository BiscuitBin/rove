# 06: Verdict

**Network:** none. Everything cited was measured by tickets 01 to 05.

**What to build:** the README's Verdict section, answering both parts of the question
from the recorded facts, dated, naming the macOS version, the smolmachines, Scrapy and
DuckDB versions, and the machine's resources. It contains, each with its number or its
quoted output:

- Cold `vm up` (image pull, boot, guest install) and warm `vm up` (reconnect) times.
- Feed round-trip speed through `read_file`, and what `exec` did with long output and
  its timeout.
- Warm crawl throughput under the polite defaults, pages per minute on each target
  site, and the share of the 200-page cap that was 200s.
- The bulk-versus-per-item table from ticket 05, with a one-paragraph reading of it
  against the DuckDB study's recommendation.
- Every sharp edge met, with its workaround, and anything the SDK could not do.
- A recommendation for each part, one of candidate, not a candidate, candidate with
  conditions, with the conditions spelled out: Scrapy in a smol sandbox as the engine
  of the http fetch tier, and DuckDB as the store of a run's fetched pages. Written to
  be cited by a decision record under `docs/decisions/`, without writing one.

Facts stay facts and inferences are marked as such. Anything that was not measured is
named as not measured, not estimated.

**Blocked by:** 04 and 05.

**Status:** ready-for-agent

- [ ] The Verdict is dated and names the versions and the machine resources
- [ ] Both parts of the question have a recommendation of the three kinds, with the
  conditions spelled out where it is conditional
- [ ] Every number in the Verdict traces to a quoted run or a table from tickets 01 to
  05; nothing is estimated
- [ ] The sharp edges and the SDK's limits are listed with workarounds
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged
