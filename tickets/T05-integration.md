---
id: T05
title: "Integration: the first green `just check` from a fresh clone and in CI"
status: open
depends_on: [T01, T02, T03, T04]
parallel_with: []
branch: ticket/t05-integration
estimated_size: M
---

# T05: Integration: the first green `just check` from a fresh clone and in CI

## Context

Four lanes each proved their part green on their own branch, and each may have handed
back a change it was not allowed to make: a recipe in the frozen `Justfile`, a setting
in `pyproject.toml`, a page title in `docs/manifest.yml`, a fact `CONVENTIONS.md` got
wrong. Some of those landed as small `main` pull requests during wave 1; others are
still in hand-back notes. This ticket gathers every one, reconciles them, proves the
whole gate on `main` from a fresh clone and in CI, carries the open claims of
`CONVENTIONS.md` §12, and lifts the freeze so that T06 and the product tickets can edit
shared files. A's T11 is the original (A `tickets/T11-integration.md`).

## Goal

`main` at this ticket's merge passes `just check` from a fresh clone on the maintainer's
machine, and in CI on both `gate` legs (Python 3.14) with the `floor` job's recipes on
Python 3.13 (`CONVENTIONS.md` §10), so that the aggregate `check` is green; every hand-back from T00 to T04 is resolved, landed or
carried forward as a named open point; every `CONVENTIONS.md` §12 claim owned by T00 to
T04 has an outcome; protection on `main` is read back and matches T01's hand-back; and
`CONVENTIONS.md` records the freeze as lifted.

## Non-goals

- No new feature, gate or dependency. A reconciliation that would need one is an open
  point for the maintainer.
- No settings change; the protection read-back is read-only. A setting found wrong is
  reported, and changing it is a separately authorised action.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| Reconciliation | shared | the files the T00 to T04 hand-back notes name, and only those, each change citing the hand-back it resolves |
| `tickets/CONVENTIONS.md` | edited | §11 freeze lifted; §12 outcomes; any fact a hand-back corrected |
| `tickets/README.md` | edited | the index's status column |

## Steps

1. Create the worktree after T01 to T04 have merged; `just initialize`; `just check`
   baseline on `main`.
2. **Gather.** Read the hand-back notes and open points of T00 to T04 on `main`, and
   `gh pr list --repo BiscuitBin/rove --state merged --search 'T00 follow-up'` for the
   follow-ups already landed. Write the list to the hand-back notes: each item, its
   source, and its disposition (already landed with the pull request, to land here, or
   carried forward with a reason).
3. **Reconcile.** Land the "to land here" items, one commit each, each message naming
   the item. Run `just check` after each.
4. **Claims.** For every `CONVENTIONS.md` §12 row whose owner is T00 to T04, copy its
   outcome and the ticket that holds the evidence into the table as a new column. A
   claim without an outcome is rerun here or carried forward with a reason.
5. **The fresh clone.** Commit the reconciliation first, then `git clone` the worktree
   into `ai_tmp/fresh/` (a local clone, no network; the branch is not on GitHub until
   step 8's push) and confirm `git -C ai_tmp/fresh rev-parse --short HEAD` matches the
   worktree's `HEAD`; `just initialize` there (network, authorised), `just check`;
   quote the last line and `git status --short`. Then the same run under the 3.13
   variables of `CONVENTIONS.md` §10 for the `floor` recipes. Delete `ai_tmp/fresh/`.
6. **The read-back.** `gh api repos/BiscuitBin/rove/branches/main/protection/required_status_checks
   --jq '[.checks[] | {context, app_id}]'`; compare with T01's hand-back. If T01 recorded a
   maintainer decline, quote the output and exit status as they are (a 404 is the expected
   result when nothing was applied). Do not change the setting (see Non-goals); carry the
   missing protection forward as an open point.
7. **Lift the freeze.** Edit `CONVENTIONS.md` §11: after T05, any ticket may edit its
   own lines in a formerly frozen file and lists each as `shared, own lines`; tickets
   that share a file merge one at a time, each rebased on the last, and `uv.lock` is
   regenerated after a rebase, never merged by hand.

   **Adversarial review** (`CONVENTIONS.md` §14): the reconciliation diff, the claim
   outcomes and the freeze text, before the final commit. Ask: which hand-back was
   dropped; which claim outcome is not backed by quoted evidence in the ticket cited;
   which change reaches beyond what a hand-back asked for; does the fresh clone run
   prove what it claims (was the cache cold, was the clone's `HEAD` this branch's
   committed tip).
8. `just check`; commit. **Authorisation required**: push and open the pull request.
   Quote the CI run on the pull request (both `gate` legs, `floor` and the
   aggregate `check`, run URL, tested commit) and, after
   the maintainer merges, the first run on `main`, in the hand-back notes of a closing
   pull request that also sets `status: done` (README, Definition of done).
   **Authorisation required**: push and open it.

## Acceptance criteria

- Every hand-back item from T00 to T04 appears in the list with a disposition.
- Every `CONVENTIONS.md` §12 claim owned by T00 to T04 has an outcome naming the ticket
  that holds its evidence.
- `just check` is green from a fresh clone (quoted), and CI is green on the pull request
  and on `main` after merge (run URLs and commits quoted).
- Protection on `main` requires `check` from the GitHub Actions app, read back; or, where
  T01's hand-back notes record that the maintainer declined protection, the read-back
  result is quoted, it matches what T01 says was applied instead, and the missing
  protection is carried as a named open point for the maintainer.
- The adversarial review ran and every valid finding is fixed or handed back.

## Verification

```sh
git rev-parse --short HEAD
{ just check 2>&1; echo "exit $?"; } | tail -2
gh run list --repo BiscuitBin/rove --branch main --workflow ci.yml --limit 1 --json conclusion,headSha,url
gh api repos/BiscuitBin/rove/branches/main/protection/required_status_checks --jq '[.checks[] | .context]'
rg -n '^\| [0-9]+ \|' tickets/CONVENTIONS.md
```

## Hand-back notes

To be written by the executing agent: the reconciliation list, the claim outcomes, the
fresh-clone run, the CI runs, the protection read-back, and the review record.

## Open points

None at writing; step 2 may add some.
