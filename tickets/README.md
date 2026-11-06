# Tickets for bootstrapping `rovo`

This directory is the work breakdown for the foundation of `BiscuitBin/rove`: one
pure-Python PyPI distribution, `rovo`, with a Python API and a Typer command whose root
is `rovo`. The product comes later. These tickets build a generic, fully gated project
around a placeholder API and command: uv and hatchling, one `just check`, the agent
contract, the handbook, CI with branch protection, and Renovate. Publishing to PyPI is
out of scope, and the licence is deliberately undecided (`CONVENTIONS.md` §1).

Each ticket is written for an AI agent with no other context, working in its own git
worktree. `CONVENTIONS.md` is the shared design every ticket obeys and cites by section;
read it first, then the ticket.

Pushing, opening pull requests, tagging, publishing, filing these as GitHub issues,
changing repository or organisation settings, installing a GitHub App, installing
anything outside the worktree and editing any other repository are separately
authorised actions (`CONVENTIONS.md` §11). Nothing here has been filed.

## Index

The `status:` field in each ticket's frontmatter is authoritative; this table is a
snapshot.

| Id | Title | File | Depends on | Parallel with | Status |
| --- | --- | --- | --- | --- | --- |
| T00 | Foundation: a tracer bullet that is green on its first commit | `T00-foundation.md` | none | none | done |
| T01 | GitHub and CI: workflows, settings, branch protection | `T01-github-and-ci.md` | T00 | T02, T03, T04 | done |
| T02 | Python quality gate: ruff, mypy, pytest, coverage, the wheel, the text gates | `T02-python-gate.md` | T00 | T01, T03, T04 | done |
| T03 | Agent contract: AGENTS.md, six house skills, the bridges | `T03-agent-contract.md` | T00 | T01, T02, T04 | done |
| T04 | Handbook and maintainer docs: every page, decisions 0001 to 0007, README | `T04-handbook.md` | T00 | T01, T02, T03 | done |
| T05 | Integration: the first green `just check` from a fresh clone and in CI | `T05-integration.md` | T01, T02, T03, T04 | none | done |
| T06 | Renovate over every pin, behind an authorised app install | `T06-renovate.md` | T05 | none | open |
| T07 | Allium gate: the placeholder module, the spec recipes, the Allium skills, the specification workflow | `T07-allium-gate.md` | T05 | none | done |
| T08 | Product foundation: the state-on-disk decision, the runtime dependencies, the private package skeleton, the end-to-end harness | `T08-foundation.md` | T07 | none | done |
| T09 | Tracer bullet: rovo init creates a mirror, rovo sync mirrors its seed page | `T09-tracer-init-sync-one-page.md` | T08 | none | open |
| T10 | Links and scope: rovo sync follows links within the crawl scope and rewrites them between page files | `T10-links-and-scope.md` | T09 | none | open |
| T11 | Indexes: every finalisation writes index.md, the directory indexes, llms.txt, index.jsonl and links.jsonl, and rovo index rebuilds them | `T11-indexes.md` | T10 | none | open |
| T12 | Robots and politeness: rovo sync reads robots.txt per origin, paces each host, retries with backoff and Retry-After, and exits partial on a failure | `T12-robots-politeness.md` | T11 | none | open |
| T13 | Discovery: rovo sync reads sitemaps and llms.txt, records what they name, keeps the sitemap budgets, and --dry-run lists what it would fetch | `T13-discovery.md` | T12 | none | open |
| T14 | Incremental sync: a second rovo sync fetches known pages conditionally, keeps what did not change, reuses unchanged sitemaps, honours max_age and rewrites nothing on an unchanged site | `T14-incremental.md` | T13 | none | open |
| T15 | Page lifecycle: rovo sync removes and archives absent pages, follows redirects within the scope, moves and merges pages with their aliases, revives returning pages, settles duplicates and retires pages a narrowed scope no longer admits | `T15-lifecycle.md` | T14 | none | open |
| T16 | Errors and the report: rovo sync skips non-HTML answers, refuses in the specified order with a refused report, survives an interrupt or a crash with a report, ranks every exit code, prints --json progress, reads ROVO_ variables and --set flags, and rovo report shows the last report | `T16-errors-report.md` | T15 | none | open |
| T17 | Conversion quality: every quality gate and flag, islands for what Markdown cannot carry, every tab panel, the mslearn and devsite profiles, fail_on_low_quality and rovo verify | `T17-quality-gates.md` | T16 | none | open |

## Dependency graph

```text
T00 ─┬─ T01 ─┐
     ├─ T02 ─┤
     ├─ T03 ─┼─ T05 ─┬─ T06
     └─ T04 ─┘       └─ T07 ─ T08 ─ T09 ─ T10 ─ T11 ─ T12 ─ T13 ─ T14 ─ T15 ─ T16 ─ T17
```

- **Wave 0, T00.** The tracer bullet through every layer, the wheel included. Nothing
  else can start until it has merged: every lane replaces stubs it creates, and every
  lane's definition of done is `just check` green, which only T00 can make true first.
- **Wave 1, T01 to T04.** Parallel lanes that share no path (`CONVENTIONS.md` §3, §11),
  with the frozen files frozen.
- **T05** reconciles what the four lanes handed back, proves the whole gate from a fresh
  clone and in CI, and lifts the freeze.
- **T06** comes last because Renovate has to know every pin, and T01 adds the action
  pins.
- **T07** brings in the Allium machinery the other Biscuit repositories carry: the
  specification gate, the seven Allium skills and the specification workflow, around a
  root module that declares no behaviour yet.
- **T08** is slice 0 of the product's implementation (T08 to T20, on
  `full-final-prototype`): decision 0013 on the mirror's state on disk, the runtime
  dependencies, the private package skeleton with its import-direction test, and the
  end-to-end harness. It implements no specification behaviour.
- **T09** is slice 1, the tracer bullet: `rovo init` creates a mirror and `rovo sync`
  fetches the seed page over HTTP, converts it with the generic profile, publishes it
  with its frontmatter and writes `crawl-report.json`. It fixes the patterns later
  slices follow: the module layout, the seams, the state files, configuration
  resolution, and the obligation-named and end-to-end tests.
- **T10** is slice 2: `rovo sync` follows links. Each stored page's links are enqueued
  within the crawl scope and fetched in later batches, and every finalisation rewrites
  a link to a written page as a relative path between page files, across hosts under
  `pages/<host>/` too; every other link stays absolute.
- **T11** is slice 3: the indexes. Every finalisation builds them from the written
  pages and their links and writes `index.md`, `_indexes/<host>/<dir>.md` for each
  directory over the threshold, `llms.txt`, `index.jsonl` and `links.jsonl` at the
  mirror's root, deterministically; `rovo index` rebuilds them offline from the
  manifest.
- **T12** is slice 4: politeness. `rovo sync` reads each origin's robots.txt before
  anything else there (a refused or unreachable one disallows that origin and is
  reported), paces each host name by its rate and the longest Crawl-delay its origins
  declare, retries a failed request with backoff and Retry-After, and exits 1 when a
  page fails or robots.txt could not be read.
- **T13** is slice 5: discovery. `rovo sync` reads each allowed host's declared and
  conventional sitemaps (an index's children only on the host that served it) and its
  `llms.txt`, records every URL they name as an observation, admits the in-scope ones
  within the sitemap caps and the page budget, reports a declared sitemap that fails,
  and `rovo sync --dry-run` lists the rows it would fetch without fetching a page.
- **T14** is slice 6: incremental sync. A second `rovo sync` sends each known page's and
  each saved sitemap's validators, keeps a page answered 304 or whose raw document did
  not change, reconverts one that changed or that `max_age` forces, reuses a sitemap
  answered 304 from its snapshot in `.rovo/sitemaps.json`, and rewrites no page file and
  no index file on an unchanged site.
- **T15** is slice 7: the page lifecycle. A page that answers 404 or 410 or redirects
  out of scope is removed and its file archived under `_removed/<host>/`, mirroring
  `pages/`; redirects within the scope are followed (robots.txt, sitemaps and
  `llms.txt` included), a page whose identity moves is moved with its old URLs as
  aliases, a canonical naming another page merges it, two URLs resolving to one page in
  one run leave one page and a duplicate row, a removed page that answers again is
  revived in place, a page a narrowed scope no longer admits is retired at the next
  finalisation, and the report lists every removal.
- **T16** is slice 8: errors and the report. A non-HTML answer settles its row
  `skipped_not_html` instead of stopping the sync; a bad configuration, a changed root
  without `--yes`, an off-host `--url` and an unknown `--path` are refused in the
  specified order, each with a refused `crawl-report.json` and no request; an
  interrupted or crashed sync publishes what it stored and still writes its report;
  every exit code is ranked; `--json` prints progress events; `ROVO_<SECTION>__<FIELD>`
  variables and `--set` flags layer over `rovo.toml`; and `rovo report` prints the last
  report.
- **T17** is slice 9: conversion quality. A page holding a complex table, a block
  definition list, `details`, math or a non-heading `id` anchor converts with each
  carried as a sanitised island instead of stopping the sync; every tab panel reaches
  the body under a profile with a tab selection; the `devsite` profile converts end to
  end and `mslearn`'s selection is unit-tested while its sitemap filter and version
  label wait on the maintainer; every gate and normalisation flag is raised;
  `fail_on_low_quality` exits 4; and `rovo verify` reports drift on disk offline.

## How to pick up a ticket

Before T00 starts, the `tickets/` directory is committed on `bootstrap-tickets` and that
branch is merged into `main` through a pull request (pushing and opening the pull request
are separately authorised), so that `CONVENTIONS.md` and every ticket are on `main`.

1. Create a worktree on the branch the ticket's `branch:` field names, from
   `origin/main`, after every ticket it depends on has merged. `<branch>` is that field
   (`ticket/t03-agent-contract`) and `<id>` the ticket id (`T03`):

   ```sh
   supacode repo worktree-new --fetch --branch <branch> --base origin/main --name <id>
   ```

   Outside a Supacode terminal:

   ```sh
   git fetch origin && git worktree add --no-track ../<id> -b <branch> origin/main
   ```

   Both fetch (network, authorised) and base the branch on `origin/main`, so that a
   stale local `main` can never seed a lane.

   Then run `just initialize` in the new worktree (network, authorised), except in T00,
   which creates the `Justfile`. Each worktree has its own gitignored `.venv/`, so a new
   worktree has no tools until it runs. `scripts/initialize.sh` skips `install-hooks` in
   a secondary worktree, so once, after T00 merges and before the first wave-1
   worktree, run `just initialize` in the primary checkout on an up-to-date `main`.

   Except in T00, run `just check` before changing anything, and quote its last line in
   the hand-back notes as the baseline. If it is red, stop: `main` is broken, and the fix
   is a `main` pull request, not part of this lane.

2. Read `CONVENTIONS.md`, then the ticket. Read the A, W, L and B files the ticket names
   at the commits `CONVENTIONS.md` §0 pins, with `git -C <clone> show <commit>:<path>`.
   Never modify a clone.
3. Edit only the files the ticket lists, plus the `status:` line and hand-back notes of
   the ticket itself. A change needed elsewhere is handed back, not made.
4. Run the ticket's verification commands and quote their output in the hand-back notes,
   each headed by the commit it ran at and showing its exit status. A check that passes
   by printing nothing is preceded by its positive control (`CONVENTIONS.md` §11).
5. At each **Adversarial review** the ticket marks, follow `CONVENTIONS.md` §14 before
   going on.
6. Commit on the ticket branch. Before asking to push, `git fetch origin`, rebase onto
   `origin/main`, rerun `just check` and the ticket's verification, and requote. If it
   goes red only after the rebase, hand the conflict back instead of editing another
   lane's files.
7. Pushing and opening the pull request are separately authorised: stop and ask.

## Definition of done

`just check` is green on the ticket branch rebased onto the current `main`: its output
ends with `All checks passed and the worktree is unchanged.`, and `git status --short`
prints nothing after the ticket's commit. The acceptance criteria are met, the
verification commands ran with their output quoted in the hand-back notes, the
adversarial reviews the ticket names have run (`CONVENTIONS.md` §14) and every valid
finding is fixed or handed back, every open point is answered or explicitly carried
forward, and the ticket's `status:` is `done` in the same pull request. A ticket whose
evidence exists only after its pull request merges (T01, T05, T06) sets `status: done`
in a closing pull request instead. That pull request touches only the ticket's
`status:` line and hand-back notes, quotes the post-merge evidence, and is separately
authorised like any push. A ticket is done when its gate passes, not when its files
exist.

## Ticket format

Every ticket carries frontmatter (`id`, `title`, `status`, `depends_on`, `parallel_with`,
`branch`, `estimated_size`) and these sections in this order: Context, Goal, Non-goals,
Files touched, Steps, Acceptance criteria, Verification, Hand-back notes, Open points.
Files touched is a table whose first cell is the path as a code span, with two exceptions
that name their scope in prose: T05's reconciliation row, because its paths are known only
from the hand-backs it reconciles, and a row of class `GitHub state` (T01's repository
settings and protection, T06's Renovate app installation), because it changes repository
state rather than a file. Steps mark each review checkpoint with a bold
**Adversarial review** paragraph that cites `CONVENTIONS.md` §14, and each stop for a
separately authorised action with a bold **Authorisation required**. Repository paths
and URLs are written as code spans, never as links, because the hook gate runs lychee
offline over this directory. A source file is cited as its letter and a code span,
A `Justfile`, so that every citation can be checked against its pinned commit
(`CONVENTIONS.md` §0).
