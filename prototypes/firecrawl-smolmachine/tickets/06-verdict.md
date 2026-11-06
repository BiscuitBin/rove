# 06: Verdict: `FINDINGS.md` answers the question

**Network:** none.

**What to build:** the answer the prototype was built for, written so that a future
decision record can cite it. `FINDINGS.md` already holds the raw notes from tickets 01
to 05; this ticket rewrites it into a document with a one-paragraph verdict at the top
and the evidence beneath, answering: can the `smolmachines` Python SDK boot and manage a
local microVM on macOS that runs self-hosted Firecrawl, well enough to fetch single URLs
as Markdown? And, on that evidence, is smolmachines plus Firecrawl a candidate for
rovo's browser fetch tier (the black box behind `fetch_or_render` in
`docs/specs/crawl.allium`), or not?

The evidence it must carry, with numbers where there are numbers:

- Cold `up` time (first boot, images pulled) and warm `up` time (stopped machine,
  nothing pulled), each to a successful scrape.
- What was pulled and how large it was, per image or package.
- The resources the machine was given (CPU, memory, disk) and what the stack actually
  used.
- The topology chosen and the attempts that failed before it.
- Every sharp edge met, from port publishing to restart cleanup, each in one or two
  sentences with the workaround.
- What the SDK could not do, including the unknowns ticket 01 named: TCP publishing on
  the default backend, a guest-only disk volume, reaching the Mac's loopback from a
  guest.
- A warm scrape time and the shape of the Markdown Firecrawl returns for a simple page.
- A recommendation: candidate, not a candidate, or candidate with conditions, and the
  conditions.

The prototype is finished when this ticket closes. Nothing is promoted to `src/rovo/`,
no specification changes, and the directory stays on its branch as evidence; whether the
branch merges is a separate decision.

**Blocked by:** 04 (`fcproto scrape <url>`), 05 (Stop and restart without rebuilding).

**Status:** ready-for-agent

- [ ] `FINDINGS.md` opens with a one-paragraph verdict that answers the question and
  gives the recommendation
- [ ] It reports cold and warm `up` times, image or package sizes, and the machine's
  resources, as numbers
- [ ] It names the topology chosen and the attempts that failed
- [ ] It lists every sharp edge met and what the SDK could not do, each with the
  workaround or the lack of one
- [ ] It is written to be cited by a decision record under `docs/decisions/`: dated,
  naming the SDK and Firecrawl versions it tested, and plain about what was not tried
- [ ] `src/rovo/`, `tests/` and `docs/specs/` are unchanged across the whole branch
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
