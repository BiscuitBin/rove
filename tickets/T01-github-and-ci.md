---
id: T01
title: "GitHub and CI: workflows, settings, branch protection"
status: open
depends_on: [T00]
parallel_with: [T02, T03, T04]
branch: ticket/t01-github-and-ci
estimated_size: M
---

# T01: GitHub and CI: workflows, settings, branch protection

## Context

T00 left a one-job `ci.yml` stub that runs `just check` on Ubuntu and a setup action
that installs uv and just. This ticket gives CI its final shape (`CONVENTIONS.md` §10):
the full gate on Ubuntu and macOS under Python 3.14, the Python gates on 3.13 without B
(`CONVENTIONS.md` §1 fact 1), the aggregate `check` job as the one required check, and a
scheduled `audit.yml`. Then, behind an authorisation stop, it applies the repository
settings and the branch protection `CONVENTIONS.md` §10 proposes and reads them back.

A's T01 did the same for a private repository on the free plan (A
`tickets/T01-github-and-ci.md`); its hand-back notes record what live runs proved,
including that a required check must be the aggregate job's name and nothing else. The
visibility logic is not carried: `BiscuitBin/rove` is public, so protection is available,
but `BiscuitBin` is an organisation and the settings may need an owner.

## Goal

`ci.yml` runs the `gate` matrix and the `floor` job, both green on a pull request, with
`check` green as their aggregate; `audit.yml` runs `just audit` on a schedule and on
pull requests, never required; every remote action is SHA-pinned; and, after the
maintainer's authorisation, `main` is protected with `check` as its only required check
and the hygiene settings applied, each read back and quoted.

## Non-goals

- No release workflow, no Pages, no environments (out of scope, `CONVENTIONS.md` §1
  decision 5).
- No change to the `Justfile` or `pyproject.toml` (frozen). A recipe CI needs that does
  not exist is handed back.
- No Renovate (T06).

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `.github/actions/setup/action.yml` | final | `CONVENTIONS.md` §10 "The setup action"; A `.github/actions/setup/action.yml`'s register and comments |
| `.github/workflows/ci.yml` | final | `CONVENTIONS.md` §10; A `.github/workflows/ci.yml`'s header, `concurrency`, `permissions` and the `check` job |
| `.github/workflows/audit.yml` | new | A `.github/workflows/audit.yml` with the setup action and `just audit` |
| repository settings and protection on `BiscuitBin/rove` | GitHub state | `CONVENTIONS.md` §10, after **Authorisation required** |

## Steps

1. Create the worktree; `just initialize`; `just check` baseline (`README.md`, "How to
   pick up a ticket").
2. **Read the state, read-only.** Quote each, with its exit status:
   `gh api repos/BiscuitBin/rove --jq '{visibility, default_branch, permissions,
   delete_branch_on_merge, allow_auto_merge, allow_squash_merge, allow_merge_commit,
   allow_rebase_merge}'`; `gh api repos/BiscuitBin/rove/branches/main/protection`
   (a 404 whose message is `Branch not protected` is "absent"; any other error stops
   the step, `CONVENTIONS.md` §11); `gh api
   repos/BiscuitBin/rove/private-vulnerability-reporting --jq .enabled`; and the runs
   T00's stub produced on `main`: `gh run list --repo BiscuitBin/rove --branch main
   --limit 3`. If `permissions.admin` is not `true`, stop: the settings need someone who
   has it (`CONVENTIONS.md` §13, "Organisation settings").
3. **The setup action.** `astral-sh/setup-uv` at the newest release's SHA with
   `version: "0.13.6"` (or the `CONVENTIONS.md` §2 pin, if it has since moved),
   `enable-cache: true` and `cache-dependency-glob: uv.lock`; the `python-version`
   input exported as `UV_PYTHON`; `uv tool install rust-just==1.59.0` and
   `uv tool dir --bin >> "$GITHUB_PATH"`; `just sync`; `actions/cache` over prek's
   cache directory (`~/.cache/prek`) keyed on `hashFiles('.pre-commit-config.yaml',
   '.pre-commit-fix.yaml')`, saved on any branch, as A's action saves its prek cache (only
   A's pixi and cargo caches are written from `main` alone); then `just install-hooks`, with A's comment that the prepare and the lychee warm are
   the point and that after this step no step reaches the network. A restored cache is
   not enough: on a cold one, `just check` would otherwise fetch every hook environment
   and lychee (`CONVENTIONS.md` §4, §11).
   Every `uses:` is a full SHA with a version comment, read with
   `gh api repos/<owner>/<repo>/git/ref/tags/<tag>` and dereferenced if annotated.
4. **`ci.yml`** (`CONVENTIONS.md` §10). Jobs `gate` (matrix `os: [ubuntu-latest,
   macos-latest]`, `fail-fast: false`, Python 3.14, one step `just check`), `floor`
   (Ubuntu, Python 3.13, `UV_NO_GROUP: tooling` in `env`, one recipe per step, then the
   `git status --porcelain` guard as its own step with a comment saying why it cannot be
   `check-clean`), and `check` (A's aggregate, `needs: [gate, floor]`). The header
   comment says why macOS is in the matrix (the maintainer's platform) and why 3.13 is
   not the full gate. Job names carry no slash or space, so that the required check's
   context is exactly `check`.
5. **`audit.yml`**: A's triggers, schedule and comment, reworded for `uv audit`; one job.
6. `uv run --frozen prek run actionlint --all-files` and `just check`, quoted.

   **Adversarial review** (`CONVENTIONS.md` §14): the workflows, the action and the
   proposed settings, before step 7 asks. Ask: can `check` be green while a `gate` leg
   was skipped or cancelled; does `floor` really run on 3.13 (the log must print the
   version); can any job reach a secret; is any `uses:` unpinned or pinned to a tag;
   does the proposed protection name a context that will exist; would the settings
   lock the maintainer out of merging T02 to T04.
7. **Push and run.** **Authorisation required**: push the branch and open a pull
   request. Wait for the run; quote `gh pr checks <n>` and the run URL. If any job is
   red, fix it on the branch; never require a red check (`CONVENTIONS.md` §13, "A red
   stub run on `main`"). Quote from the `floor` job's log the line that prints
   `Python 3.13`, from each `gate` leg's `just install-hooks` step the line showing the
   ripsecrets hook environment built (`CONVENTIONS.md` §12 claim 6), and from each `gate`
   leg the line `All checks passed and the worktree is unchanged.`
8. **Read the `check` run's app.** `gh api repos/BiscuitBin/rove/commits/<sha>/check-runs
   --jq '.check_runs[] | select(.name == "check") | {name, conclusion, app_id: .app.id}'`
   on the pull request's head commit. The `app_id` goes into the protection payload.

   **Adversarial review** (`CONVENTIONS.md` §14): the exact `gh api` commands and JSON
   payloads step 9 will send, before the stop. Ask: does each payload match
   `CONVENTIONS.md` §10; is anything sent that was not shown to the maintainer.
9. **Authorisation required: settings and protection.** Show the maintainer the
   before-state of step 2, each payload, and the exact commands:
   `gh api -X PATCH repos/BiscuitBin/rove` with the hygiene fields;
   `gh api -X PUT repos/BiscuitBin/rove/private-vulnerability-reporting`;
   `gh api -X PUT repos/BiscuitBin/rove/branches/main/protection --input
   ai_tmp/protection.json`. Apply only what they approve, in that order, each with its
   exit status quoted.
10. **Read back.** Rerun step 2's reads; save the protection to
    `ai_tmp/protection-after.json`, quote `jq '{required_status_checks,
    enforce_admins: .enforce_admins.enabled, allow_force_pushes:
    .allow_force_pushes.enabled, allow_deletions: .allow_deletions.enabled}'` of it,
    and say which fields changed.

    **Adversarial review** (`CONVENTIONS.md` §14): the final diff and the read-back,
    before the merge stop and before the final commit of the hand-back notes.
11. **Authorisation required**: merge the pull request. Merge only after the maintainer
    authorises it; then quote the first `ci.yml` run on `main` and its `check` conclusion.
    The final commit of the hand-back notes, with `status: done`, goes on a closing pull
    request off the updated `main` (README, Definition of done).
    **Authorisation required**: push and open it.

## Acceptance criteria

- On the pull request, `gate` (both legs), `floor` and `check` are green; `audit` ran
  and is not required. Run URL and tested commit quoted.
- The `floor` log shows Python 3.13 and no `biscuit-games-tooling` install.
- Every remote `uses:` is a 40-character SHA with a version comment:
  `rg -n 'uses: [^.]' .github | rg -v '@[0-9a-f]{40} # '` prints nothing, preceded by
  its positive control.
- Protection on `main` requires exactly `check` from the GitHub Actions app, read back,
  or the hand-back notes say the maintainer declined and what was applied instead.
- `CONVENTIONS.md` §12 claims 1 (the CI half), 6 (the runner half) and 11 have outcomes.
- The adversarial reviews ran and every valid finding is fixed or handed back.

## Verification

```sh
rg -n 'uses: [^.]' .github; echo "exit $?"
rg -n 'uses: [^.]' .github | rg -v '@[0-9a-f]{40} # '; echo "exit $?"
uv run --frozen prek run actionlint --all-files
gh pr checks <n> --repo BiscuitBin/rove
gh api repos/BiscuitBin/rove/branches/main/protection/required_status_checks --jq '[.checks[] | {context, app_id}]'
gh api repos/BiscuitBin/rove --jq '{delete_branch_on_merge, allow_auto_merge}'
{ just check 2>&1; echo "exit $?"; } | tail -2
```

The first `rg` is the positive control and must list every remote action; the second
must print nothing and exit 1.

## Hand-back notes

To be written by the executing agent: the before-state, the SHAs read and their tags,
the run URLs with the commits they tested, what the maintainer authorised and when, the
payloads sent, the read-back and its diff, the review record for each checkpoint, and
every departure from `CONVENTIONS.md` §10.

## Open points

- Whether macOS should stay in every pull request's matrix once the gate is stable, or
  move to `main` pushes only. The maintainer decides after seeing step 7's timings,
  quoted per job.
