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

## Dependency graph

```text
T00 ─┬─ T01 ─┐
     ├─ T02 ─┤
     ├─ T03 ─┼─ T05 ─┬─ T06
     └─ T04 ─┘       └─ T07
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
