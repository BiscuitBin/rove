---
name: plan-change
description: Plan a change when the scope, affected specifications, risks, or validation need evidence before any code is written.
---

# Plan a change

1. Read `AGENTS.md`, then the ticket or request and the `tickets/CONVENTIONS.md`
   sections it cites. Separate what you read from what you are guessing.
2. Inspect the worktree before proposing anything, and preserve work you did not author.
3. Write down the observable outcome and explicit non-goals, so the scope can be reviewed.
4. Identify whether behaviour changes. The product is not yet specified: behaviour
   beyond today's placeholders comes only from a ticket or a decision record under
   `docs/decisions/`. When neither defines what the change should do, mark it as an open
   question for the maintainer instead of choosing an answer.
5. Identify the boundaries crossed: the import direction of invariant 1 (`rovo.cli`
   imports the API, never the reverse), the public API of invariant 2 (what
   `src/rovo/__init__.py` lists in `__all__`), a dependency under invariant 6 and the
   note decision 0005 asks for, and a new topic's owning page in `docs/manifest.yml`.
   An API change moves its test, `docs/reference/api.md` and the `Unreleased` section of
   `CHANGELOG.md` together; a command-line change moves `docs/reference/cli.md`.
6. Name the risks and the evidence that would settle them, and say which actions need
   explicit authorization the agent does not already have: anything that leaves the
   worktree, and the network recipes `AGENTS.md` lists.
7. Split into independently verifiable steps, each pairing behaviour, test and documentation.
8. Present the plan with open questions marked as open. Confirm the work runs green
   with `just check` before treating it as done.
