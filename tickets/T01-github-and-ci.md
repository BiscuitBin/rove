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

### Part 1 evidence, steps 1 to 6 (commit 7f4d943)

All of it was taken on 2026-10-29 in the wave-1 worktree
`/Users/scutting/projects/biscuitbin/rove/.claude/worktrees/agent-ab299d2594d2110e5`,
on branch `worktree-agent-ab299d2594d2110e5`. The harness created that branch at
`61f2357`, before T00. It was fast-forwarded (`git merge --ff-only 69f0d14`) to T00's
tip, `69f0d14` (`T00: status done`), before any work, and T01's commit sits on top.
Raw logs are in `ai_tmp/T01/`.

**Step 1, baseline.** `RUSTUP_TOOLCHAIN=stable just initialize` took the
secondary-worktree path (`Secondary worktree: skipping install-hooks.`) and exited 0.
`just check` on the untouched tree at `69f0d14` exited 0 and ended
`All checks passed and the worktree is unchanged.`

**Step 2, the state, read-only.** Each command ran as the ticket gives it:

```text
$ gh api repos/BiscuitBin/rove --jq '{visibility, default_branch, permissions, delete_branch_on_merge, allow_auto_merge, allow_squash_merge, allow_merge_commit, allow_rebase_merge}'
{"allow_auto_merge":false,"allow_merge_commit":true,"allow_rebase_merge":true,"allow_squash_merge":true,"default_branch":"main","delete_branch_on_merge":false,"permissions":{"admin":true,"maintain":true,"pull":true,"push":true,"triage":true},"visibility":"public"}
exit 0
$ gh api repos/BiscuitBin/rove/branches/main/protection
{"message":"Branch not protected","documentation_url":"https://docs.github.com/rest/branches/branch-protection#get-branch-protection","status":"404"}gh: Branch not protected (HTTP 404)
exit 1
$ gh api repos/BiscuitBin/rove/private-vulnerability-reporting --jq .enabled
false
exit 0
$ gh run list --repo BiscuitBin/rove --branch main --limit 3
exit 0
```

- `permissions.admin` is `true`, so the step does not stop.
- Protection on `main` is absent: an HTTP 404 whose message is `Branch not protected`.
- Private vulnerability reporting is off.
- `gh run list` printed nothing. To make that a number:
  `gh api 'repos/BiscuitBin/rove/actions/runs?branch=main' --jq .total_count` printed
  `0` (exit 0). Across the repository it printed `1`, and that one run is GitHub's
  dynamic `Running Copilot Code Review` on `bootstrap-tickets` (`57df217`), not a
  `ci.yml` run.
- So T00's stub has never run on a runner: T00 is on `bootstrap`, not on `main`.
  `CONVENTIONS.md` §13's "red stub run on `main`" cannot be judged yet, and §12 claims
  1 (the CI half), 6 (the runner half) and 11 stay open until step 7's run.

**Step 3, the pins.** `gh api repos/<o>/<r>/releases/latest --jq .tag_name` gave the
newest release of each action (exit 0 each). `gh api
repos/<o>/<r>/git/ref/tags/<tag>` gave each ref (exit 0 each). All three are
lightweight (`object.type` is `commit`), so nothing needed dereferencing:

```text
astral-sh/setup-uv v10.3.3  commit 68559e99cc807c1eb7e9238fd43a15bba460eec2
actions/checkout   v7.0.1   commit 3d3c42e5aac5ba805825da76410c181273ba90b1
actions/cache      v6.1.0   commit 55cc8345863c7cc4c66a329aec7e433d2d1c52a9
```

They equal T00's pins, and checkout and cache equal A's. setup-uv's `action.yml` at
that SHA declares the `version`, `enable-cache` and `cache-dependency-glob` inputs.
Its `github-token` input defaults to the run's own token, which this workflow limits to
`contents: read`. `uv run --frozen prek cache dir` prints `~/.cache/prek` on macOS,
the path the cache step names. T00's setup action already had §10's shape. T01 drops
its stub sentence, says in the description that `UV_NO_GROUP` leaves B out, and
comments that `UV_PYTHON` outranks `.python-version` and that a job's `env` reaches
`just sync`. The `install-hooks` comment keeps A's wording and adds the cold-cache
reason.

**Step 4, `ci.yml`.** It keeps A's `on`, `permissions`, `concurrency` and their
comments, and carries the `check` job verbatim from A, with `needs: [gate, floor]`.
`gate` uses `fail-fast: false` and passes `python-version: '3.14'`. `floor` puts
`UV_NO_GROUP: tooling` in the job's `env`. Its steps are
`uv run --frozen python --version`, so the log prints the interpreter, then one recipe
per step, then the `git status --porcelain` guard, which prints what it found before
`exit 1`. The header comment says why macOS is there and why 3.13 is not the full gate.

**Step 5, `audit.yml`.** A's triggers, schedule and `concurrency`, one `audit` job:
checkout, the setup action, `just audit`. The comment now names `uv audit`'s network
dependency, the OSV service (`uv audit --help`: `--service-format ... [default: osv]`).

**Step 6, checks.** The positive control lists every remote `uses:`. The negative
check prints nothing and exits 1:

```text
$ rg -n 'uses: [^.]' .github; echo "exit $?"
.github/workflows/audit.yml:29:      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
.github/workflows/ci.yml:39:      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
.github/workflows/ci.yml:56:      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
.github/actions/setup/action.yml:21:    - uses: astral-sh/setup-uv@68559e99cc807c1eb7e9238fd43a15bba460eec2 # v10.3.3
.github/actions/setup/action.yml:46:    - uses: actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0
exit 0
$ rg -n 'uses: [^.]' .github | rg -v '@[0-9a-f]{40} # '; echo "exit $?"
exit 1
```

actionlint, on the committed tree:

```text
$ uv run --frozen prek run actionlint --all-files
Lint GitHub Actions workflow files.......................................Passed
exit 0
```

Its positive control was run before the commit. `ci.yml` was saved to `ai_tmp/scratch/`,
`needs: [gate, floor, nope]` was edited in, and the hook then failed with
`job "check" needs job "nope" which does not exist in this workflow [job-needs]`
(exit 1). The file was copied back, and `cmp` exited 0. actionlint lints
`.github/workflows/` only, so the composite action is not linted by it.

A local dry run of `floor`, outside CI, used a scratch environment so that `.venv`
was left alone. The run was
`UV_PYTHON=3.13 UV_NO_GROUP=tooling UV_PROJECT_ENVIRONMENT=ai_tmp/T01/venv313 uv sync --frozen --offline`.
It used CPython 3.13.13, installed 21 packages with no `biscuit-games-tooling`, and
exited 0 offline from the warm cache. Under the same three variables,
`uv run --frozen python --version` printed `Python 3.13.13`. `just lock-check`,
`just py-lint`, `just py-typecheck`, `just coverage` (total 100%) and `just
wheel-smoke` each exited 0, and the smoke venv reported `Using Python 3.13.13`. The
scratch environment held no `bg-*` script. Afterwards `git status --porcelain` listed
only T01's three edited files. This is the local half of §12 claim 1 on the real
`pyproject.toml`. The CI half waits for step 7.

`just check` on `7f4d943`, with `RUSTUP_TOOLCHAIN=stable`, exited 0 and ended
`All checks passed and the worktree is unchanged.` `git status --short` then printed
nothing.

**Departures from `CONVENTIONS.md` §10 and from A, part 1.**

- `ci.yml` and `audit.yml` drop A's `CARGO_*` workflow `env` block, because there is no
  Rust here. `audit.yml`'s setup step has no `with:`, because rovo's action takes no
  `cache-key`.
- `timeout-minutes`, which §10 does not state: `gate` 30 (as T00's stub had), `floor`
  20, `check` 5 and `audit` 10 (A's).
- `floor` has a non-recipe step, `uv run --frozen python --version`, so that step 7 has
  the `Python 3.13` line to quote. Without it no recipe prints the version.
- The prek cache key hashes both hook configurations and `uv.lock`, as A's hashed
  `pixi.lock`: `uv.lock` pins prek, and an exact cache hit is never re-saved
  (`actions/cache` `src/saveImpl.ts:50-55` at `55cc834`), so without it a prek bump
  would rebuild hook environments on every run. This departs from §10's literal "keyed
  on the hash of both prek configurations" and from step 3. Trade-off: any relock, not
  only a prek bump, gives one cold prek cache (and one ripsecrets rebuild). Checkpoint 1
  review, C1 and B2; B2's alternative (key on `prek --version` from an extra step) was
  not taken, to keep A's shape.
- The setup action has a step after `just install-hooks` that fails if no executable
  `lychee-*` binary is under `~/.cache/prek/repos`. The `Justfile`'s warm-up ignores its
  own exit status (`-uv run --frozen prek run lychee ...`), so without the check a failed
  download would be retried, over the network, by `just check`. §10 does not state this
  step. Checkpoint 1 review, B1.
- Work began from a worktree branch created before T00, fast-forwarded to `69f0d14`
  (above), not from `origin/main` (single-branch decision, 2026-10-29).
- `RUSTUP_TOOLCHAIN=stable` was exported for every local run (no rustup default on
  this machine). The machine was not changed.

**Hand-backs from checkpoint 1 review.**

- `Justfile:47` (frozen, §11): the leading `-` on the lychee warm-up drops its exit
  status. Still open; already handed back by T00 (C1). T01's setup action now fails
  closed instead (above).
- `CONVENTIONS.md` §10 (not T01's to edit), for T05: the prek cache key wording should
  read "keyed on the hash of both prek configurations and `uv.lock`, which pins prek",
  and may mention the lychee check after `just install-hooks`.

### Review record, checkpoint 1 (step 6, reviewed at `33e5cbe`)

The orchestrator ran it, as `CONVENTIONS.md` §14 lays out. There were two reviewers,
both `codex exec -m gpt-6-astra -s read-only`, one per lens. Separate triage subagents
judged each finding and applied the fixes. The raw files, which are not committed, are
in `ai_tmp/review/T01-1/`, with the merged verdicts in `verdicts.md`. There were three
findings, all valid, none high, so no second round runs:

| id | severity | verdict | reason | action |
| --- | --- | --- | --- | --- |
| C1 | low | valid | the prek cache key leaves out `uv.lock`, which pins prek, and an exact hit is never re-saved | `uv.lock` added to `hashFiles` |
| B2 | low | valid | same defect as C1; it proposed keying on `prek --version` | applied as C1's fix (A's key shape, no extra step) |
| B1 | medium | valid | `Justfile:47`'s `-` hides a failed lychee warm-up, so `just check` could reach the network | a fail-closed lychee check step in the setup action; the root cause is handed back (above) |

Re-run after the fixes, on `33e5cbe` with them uncommitted, with
`RUSTUP_TOOLCHAIN=stable`. They were then committed as `T01: §14 checkpoint 1 fixes`.

- `uv run --frozen prek run actionlint --all-files`: `Passed`, exit 0. Control: with
  `needs: [gate, floor, nope]` edited into a copy-saved `ci.yml`, the hook failed with
  `[job-needs]`, exit 1. After the copy back, `git diff --quiet` exited 0.
- `rg -n 'uses: [^.]' .github` listed the same five lines as in step 6 (exit 0), and the
  unpinned filter printed nothing (exit 1).
- The new lychee step's command, run against the real cache, found
  `~/.cache/prek/repos/909c8f3d3d713742/.cargo/bin/lychee-0.24.2`, exit 0. Its control,
  against an empty `ai_tmp/T01/empty-prek/repos`, gave `test -n` exit 1.
- Residual: the step accepts any cached `lychee-*` version, not only the pinned one, and
  the composite action has not yet run on a real runner (step 7).

Steps 7 and later have not been done. Each one needs authorisation, and the work
stops at step 6's **Adversarial review**.

## Open points

- Whether macOS should stay in every pull request's matrix once the gate is stable, or
  move to `main` pushes only. The maintainer decides after seeing step 7's timings,
  quoted per job.
