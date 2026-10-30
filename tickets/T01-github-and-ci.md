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

### Part 2 evidence, steps 7 and 8 (runs on `e2a83a4` and `4183def`)

**Authorisation.** On 2026-10-30, the orchestrator relayed the maintainer's plan
authorisation to push `bootstrap` and open one pull request, `bootstrap` into `main`.
The harness keeps this agent inside its lane worktree, so the lane branch was
fast-forwarded to `bootstrap` at `e2a83a4`, which holds T00 to T04. There `just check`
exited 0 and ended `All checks passed and the worktree is unchanged.`, and
`git status --short` printed nothing. Then `git push origin HEAD:bootstrap` (exit 0),
and `gh pr create` opened PR #2, `Bootstrap rovo: tickets T00–T06`
(`https://github.com/BiscuitBin/rove/pull/2`). No settings, protection or merge were
touched.

**Run 1**, CI `https://github.com/BiscuitBin/rove/actions/runs/41015997274` on
`e2a83a4`, watched with `gh pr checks 2 --watch` (exit 1):

```text
floor                 fail  1m24s
gate (ubuntu-latest)  fail  1m28s
gate (macos-latest)   fail  1m48s
check                 fail  4s
audit                 pass  1m22s   (runs/41015997272)
```

Every leg failed in `just coverage` at `tests/test_cli.py:47` and `:58`. The
`--help` output carried ANSI codes and rich boxes. Typer sets `FORCE_TERMINAL` when
`GITHUB_ACTIONS` is set, reading it once at import (`typer/rich_utils.py` lines 78-84).
So the `CliRunner` `env` cannot undo it, and it never happens locally. Locally,
`GITHUB_ACTIONS=true uv run --frozen pytest -q tests/test_cli.py` reproduced it
(`2 failed, 5 passed`), and with `_TYPER_FORCE_DISABLE_TERMINAL=1` added it gave
`10 passed`. The fix, `4183def` (`T01: fix CLI help tests on runners; show the
ripsecrets build`), sets `_TYPER_FORCE_DISABLE_TERMINAL: '1'` in `ci.yml`'s workflow
`env` as a stopgap (hand-back H1 below). It also adds a setup-action step that names
the ripsecrets binary prek built and its compiler, because prek prints no build line.
Before the push, actionlint passed (exit 0) and `just check` passed.

**Run 2**, CI `https://github.com/BiscuitBin/rove/actions/runs/41016347749` on
`4183defeff8f28c2f8fdbe80f6513343eb86e141`, watched the same way:

```text
floor                 fail  21s
gate (ubuntu-latest)  fail  30s
gate (macos-latest)   fail  3m11s
check                 fail  2s
audit                 pass  16s     (runs/41016347788)
```

- **`floor` and `gate (ubuntu-latest)`** passed every recipe up to `just wheel-smoke`
  (`coverage` 10 passed, 100%). The wheel-smoke API step passed, then:

  ```text
  error: No solution found when resolving dependencies
    cause: Because annotated-doc==0.0.5 needs to be downloaded from a registry and you require annotated-doc==0.0.5, we can conclude that your requirements are unsatisfiable.
  hint: Packages were unavailable because the network was disabled. When the network is disabled, registry packages may only be read from the cache.
  ```

  Reproduced locally on a cold cache (`ai_tmp/T01/cold-smoke.sh`, with its own
  `UV_CACHE_DIR`). `uv sync --frozen` exits 0, but the offline
  `uv pip install --require-hashes -r` then fails the same way: `annotated-doc was not
  found in the cache`. `uv sync` installs from the lock's file URLs and never caches
  the registry's index pages, which the offline `uv pip install -r` needs. Priming the
  index first, with one online `uv pip install --require-hashes -r` into a throwaway
  venv, makes the offline install pass. So `just wheel-smoke` passes only on a cache
  that already held those index pages, and fails on a fresh clone. §12 claims 3 and 4
  were proven warm. The fix belongs in the frozen `Justfile` (hand-back H2). T01 did not
  paper over it in CI.
- **`gate (macos-latest)`** failed earlier. In `just install-hooks`, lychee's
  `cargo-binstall` hit `Timeout reached while checking fetcher` for every fetcher, then
  `cargo-install does not support --install-path`. The recipe's `-` swallowed that, and
  the checkpoint-1 lychee step then failed closed:
  `lychee was not warmed; the gate would reach the network`. In run 1, lychee had
  warmed on macOS (`/Users/runner/.cache/prek/repos/909c8f3d3d713742/.cargo/bin/lychee-0.24.2`),
  so this looks like a transient fetch failure. It was not re-run, because the leg
  would fail at wheel-smoke anyway (H2). See H3.

**Quotes.**

- `floor`'s interpreter, from the `uv run --frozen python --version` step in run 2:
  `Python 3.13.18`. Also `Using CPython 3.13.18` and
  `platform linux -- Python 3.13.18, pytest-9.2.0`. The log contains no
  `biscuit` line (`grep -c biscuit` printed 0).
- **Claim 6, runner half.**
  - Ubuntu: run 1 started on a cold prek cache (`Cache not found for input keys:
    Linux-X64-prek-817c4e...`). `just install-hooks` took 70.6 s, and `just check`'s lint
    printed `ripsecrets....Passed`. Run 2 restored the cache that run 1's green `audit`
    job saved. The new step printed
    `ripsecrets built: /home/runner/.cache/prek/hooks/rust-uXbM8URxGofKOLpJXiOY/bin/ripsecrets`,
    `"language_version": "1.99.1"` and
    `"toolchain": "/home/runner/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/bin/rustc"`,
    which is the runner's own rustup.
  - macOS: run 1 started cold (`Cache not found ... macOS-ARM64-prek-...`), built the
    hooks, and lint printed `ripsecrets....Passed`. Run 2's ripsecrets step did not run,
    because the lychee step failed before it. So macOS has no compiler line yet.
- **Claim 11.** `just sync` installed B from git with no credential on both 3.14 legs
  (`+ biscuit-games-tooling==0.3.0 (from git+https://github.com/steven-cutting/biscuit_games_tooling@6c5c07f6...)`).
  `bg-project-check` ran `just check` there, and B's other checkers never ran, because
  the gate failed at wheel-smoke first.
- **Claim 1, CI half.** `UV_NO_GROUP=tooling` with 3.13 synced and ran `lock-check`,
  `py-lint`, `py-typecheck` and `coverage` green. `wheel-smoke` was red, from H2.
- `All checks passed and the worktree is unchanged.` cannot be quoted from any leg yet.
- Timings, for the macOS open point. In run 1 every leg failed at about the same
  recipe: floor 1m24s, ubuntu 1m28s, macOS 1m48s, all on cold caches. In run 2 macOS
  took 3m11s, failing in setup.

**Step 8.**

```text
$ gh api repos/BiscuitBin/rove/commits/4183defeff8f28c2f8fdbe80f6513343eb86e141/check-runs --jq '.check_runs[] | {name, conclusion, app_id: .app.id, app: .app.slug}'
{"app":"github-actions","app_id":15368,"conclusion":"failure","name":"check"}
{"app":"github-actions","app_id":15368,"conclusion":"failure","name":"gate (macos-latest)"}
{"app":"github-actions","app_id":15368,"conclusion":"failure","name":"floor"}
{"app":"github-actions","app_id":15368,"conclusion":"failure","name":"gate (ubuntu-latest)"}
{"app":"github-actions","app_id":15368,"conclusion":"success","name":"audit"}
exit 0
```

The `check` context exists under app 15368, as §10 expected. It was red at
`4183def`, so under §13 step 9's protection could not be applied then.

Re-read on 2026-10-30 at PR #2's current head `6bc5925` (a T05 commit; `check` is green
there because of T05's fixes for H1 to H3, not T01 changes):

```text
$ gh api repos/BiscuitBin/rove/commits/6bc59254ef9d55943cc3a35ed4660cdb8ef64c7a/check-runs --jq '.check_runs[] | {name, conclusion, app_id: .app.id, app: .app.slug}'
{"app":"github-actions","app_id":15368,"conclusion":"success","name":"copilot-pull-request-reviewer"}
{"app":"github-actions","app_id":15368,"conclusion":"success","name":"check"}
{"app":"github-actions","app_id":15368,"conclusion":"success","name":"gate (macos-latest)"}
{"app":"github-actions","app_id":15368,"conclusion":"success","name":"gate (ubuntu-latest)"}
{"app":"github-actions","app_id":15368,"conclusion":"success","name":"floor"}
{"app":"github-actions","app_id":15368,"conclusion":"success","name":"audit"}
exit 0
```

`check`, both `gate` legs and `floor` are green in run `41019851932`, and `audit` in run
`41019851942`, all under app 15368. The step 9 payloads, commands and before-state are
prepared in `ai_tmp/T01/step9-payloads.md`, with the protection payload at
`ai_tmp/T01/protection.json` and the hygiene fields sent as `-F` flags. Nothing was sent.

- Departure: step 9's `--input` path is `ai_tmp/T01/protection.json`, not
  `ai_tmp/protection.json`, so the payload stays in T01's scratch directory.

**Hand-backs for T05.**

- **H1** (`tests/test_cli.py`, T02's): the help tests assume rich is not in terminal
  mode. Typer forces it under `GITHUB_ACTIONS`, `FORCE_COLOR` or `PY_COLORS`. Make the
  tests independent of that, for example by patching
  `typer.rich_utils.FORCE_TERMINAL` to `False` in a fixture, or by stripping ANSI. Then
  drop `ci.yml`'s `_TYPER_FORCE_DISABLE_TERMINAL`, which is a private Typer switch that
  a Typer upgrade could rename.
- **H2** (`Justfile` `wheel-smoke`, frozen; and §12 claims 3 and 4): on a cold cache,
  the offline `uv pip install --require-hashes -r` cannot resolve registry packages
  after `just sync`. Either install the closure without the registry index (for
  example a `uv sync --frozen --no-default-groups --no-install-project` into the smoke
  venv via `UV_PROJECT_ENVIRONMENT`, which uses the lock's cached file URLs), or have
  `just sync` or `install-hooks` prime the index. Then re-prove both claims from an
  empty `UV_CACHE_DIR`. This blocks every green CI run.
- **H3** (`Justfile` `install-hooks`, frozen, the same root as T00's C1): lychee's
  `cargo-binstall` fetch can time out on macOS runners. The setup action now fails
  closed on it. Consider a retry, or the run's `GITHUB_TOKEN` on that one step for
  binstall's GitHub API calls, as A gives it, weighing the token reaching hook builds.

Step 9 and later have not been done. `check` is green at `6bc5925`, so they wait only
on authorisation (re-read `check` on the head just before call 3).

### Review record, checkpoint 2 (step 8, reviewed at `6bc5925`)

There were two reviewers, both `codex exec -m gpt-6-astra -s read-only`, one per lens,
over the step 9 commands, payloads and before-state in `ai_tmp/T01/step9-payloads.md`.
Separate triage subagents judged each finding and applied the fixes. The raw files,
which are not committed, are in `ai_tmp/review/T01-2/`, with the merged verdicts in
`verdicts.md`. The lenses agreed; two findings were duplicates and were merged. There
were three findings, all valid, none high, so no second round runs; nothing was handed
back. Only `gh api --method GET` calls were made.

| id | severity | verdict | reason | action |
| --- | --- | --- | --- | --- |
| C1/B1 | medium | valid | calls 1 and 3 named `--input` files that do not exist (`ai_tmp/T01/repo-hygiene.json`, `ai_tmp/protection.json`) | call 1 sends `-F delete_branch_on_merge=true -F allow_auto_merge=false`; call 3 reads `ai_tmp/T01/protection.json` (departure above) |
| B2 | medium | valid | step 10's read-back did not fail closed: a failed GET leaves a 404 body that plain `jq` reads as nulls, exit 0 | each read echoes its exit status, and a `jq -e` assertion on the expected shape must print `true` |
| C2/B3 | low | valid | the blocker quoted the superseded red head `4183def` | re-read on `6bc5925`, green, quoted above; re-read `check` before call 3 |

Re-checks: every `--input` path in the payload document exists; its §10 JSON block is
`jq -e`-equal to `ai_tmp/T01/protection.json` (`true`, exit 0); the `jq -e` assertion's
controls gave exit 5 on a 404 body, exit 1 on `enforce_admins.enabled: true` and `true`,
exit 0 on the expected shape. Committed as `T01: §14 checkpoint 2 fixes`. Residual: if
the pull request's head moves before call 3, the green quote goes stale; the payload
document says to re-read `check` first.

## Open points

- Whether macOS should stay in every pull request's matrix once the gate is stable, or
  move to `main` pushes only. The maintainer decides after seeing step 7's timings,
  quoted per job.
