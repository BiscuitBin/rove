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

### Part A: reconciliation and a green CI (orchestrator brief, 2026-10-30)

Scope of part A: gather every hand-back, land the "to land here" items one commit each,
get pull request #2's CI green, amend `CONVENTIONS.md`, fill the §12 outcomes. Not done
here (the orchestrator runs them next): step 5's fresh clone, step 6's read-back,
step 7's freeze lift and adversarial review, the README index. Worked directly on
`bootstrap` in `/Users/scutting/.supacode/repos/rove/bootstrap` (single-branch decision,
2026-10-29), from `1fd2f13`.

**Departures.** `RUSTUP_TOOLCHAIN=stable` was exported for every local run (no rustup
default on this machine; the machine was not changed). Pushes went to `bootstrap` only,
as the brief authorised. `gh pr list --state merged --search 'T00 follow-up'` returned
only #1, the ticket set: no follow-up pull request landed in wave 1, so every hand-back
below was still open.

**Commits.**

| Commit | Item |
| --- | --- |
| `9af0452` | H2: `wheel-smoke` installs the closure with `uv sync` into the smoke venv |
| `1decdcc` | H1: the CLI help tests no longer depend on `_TYPER_FORCE_DISABLE_TERMINAL`; `ci.yml` drops it |
| `2c76a8d` | lychee warm-up fails closed, with retries (T00 C1/B1 and B2, T03 B1, T01 H3 and its open point) |
| `0d75e51` | the gate's `uv run` calls are offline (T03 B1, first bullet) |
| `557f403` | `CONVENTIONS.md` §1 fact 9, §4 `lock-upgrade`, §5, §9, §10 amendments |
| `fc01d5c` | §12 outcomes column |

**Reconciliation list.**

| Item | Source | Disposition |
| --- | --- | --- |
| H2, cold-cache `wheel-smoke` | T01 hand-backs | landed `9af0452` |
| H1, help tests under a forced terminal | T01 hand-backs | landed `1decdcc`; the `ci.yml` env is gone |
| H3, lychee download timeout on macOS | T01 hand-backs | landed `2c76a8d`: three tries in `warm-lychee`. The `GITHUB_TOKEN` alternative was not taken, so no token reaches hook builds |
| `install-hooks`' `-` hides a failed lychee download | T00 C1/B1; T01 checkpoint 1 B1 | landed `2c76a8d`: private `warm-lychee` recipe, run after the prepares (`install-hooks: && warm-lychee`) |
| `initialize.sh` secondary branch prepares hooks and warms lychee | T00 B2 | already in `scripts/initialize.sh` (T00 part 2); its `\|\| :` replaced by `just warm-lychee` in `2c76a8d`; §5 text in `2c76a8d` |
| `initialize.sh` `\|\| :` hides a failed download | T03 B1 (second bullet) | landed `2c76a8d` |
| lychee check accepts any cached version | T01 open (inventory) | landed `2c76a8d`: the version is read from `.pre-commit-config.yaml`; the setup action's own check is removed |
| gate recipes may sync over the network | T03 B1 (first bullet) | landed `0d75e51`: `UV_OFFLINE=1` on `check`, and in `floor` after setup. `AGENTS.md`'s scoped sentence stays: a cleared prek cache still makes `lint` fetch |
| §1 fact 9, typer's closure count | T04 | landed `557f403` |
| §4 `lock-upgrade` comment | T04 B3 | landed `557f403` (`Justfile` and §4) |
| §4 lychee line | T00 C1 | landed `2c76a8d` |
| §5 three dotfile deltas | T00 T00-2 C1 | landed `557f403` |
| §9 ruff `CPY001` ignore | T00 C2/B4 | landed `557f403` |
| §9 `wheel_smoke.py` recorder wording, typer vendors click | T00 T00-2 B1 | landed `557f403` |
| §10 prek cache key includes `uv.lock`; lychee check | T01 C1/B2 | landed `557f403`, `2c76a8d` |
| `cpy` lifted with `CPY001` (T00) versus kept (decision 0006) | T04 C2 | reconciled `557f403`: 0006 wins; §5 says so; a line under T00's bullet records it |
| `_typos.toml` `mis`/`als` | T02 open point | kept, carried: `tickets/T00-foundation.md:583` and T02's notes still quote them, and so does this table |
| T02 line 112 reword shipped in T00's `b86d3c1` | T00 open point; T00-2 C2 | reconciled as recorded: under the single-branch decision the reword stays in `b86d3c1`; `typos` passes |
| README `blob/main` links | T04 hand-back | carried: they resolve once `bootstrap` reaches `main` |
| T04's "re-check after the merge" list | T04 Part 2 | partly done: `testing.md` and `security-model.md` (wheel smoke), `commands.md`, `troubleshooting.md`, 0004 (lychee) changed with the recipes. The rest is carried to the adversarial review |
| install-hooks proven only in a fresh clone | T00 open (inventory) | unchanged: a secondary worktree must not run it. `install-hooks` with `warm-lychee` ran in a cold local clone (below) |
| macOS in every pull request's matrix | T01 open point | carried, maintainer: run 4 timings are floor 21s, ubuntu 28s, macOS 2m25s (cold prek cache) |
| T01 steps 9 to 11 (protection, settings) | T01 | carried: `check` is now green, which step 9 waited for. Nothing applied |
| Coverage floor at 100% | T02 open point | resolved, maintainer decision 2026-10-30: 95% (from 90%), below |
| `SECURITY.md` contact while private vulnerability reporting reads `false` | T04 open point, T01 step 9 | maintainer decision |
| Decision 0006's licence options | T04 open point | maintainer decision |
| Renovate installed org-wide with `repository_selection: all` | common brief | reported, for T06 and the maintainer |

**H2 evidence.** At `1fd2f13`, in a local clone with an empty `UV_CACHE_DIR`, after
`uv sync --frozen` (raw `ai_tmp/T05/`):

```text
Using Python 3.14.8 environment at: target/wheel-smoke/venv
error: No solution found when resolving dependencies
  cause: Because annotated-doc was not found in the cache and you require annotated-doc==0.0.5, we can conclude that your requirements are unsatisfiable.
```

At `0d75e51` (the recipe is unchanged since `9af0452`), `ai_tmp/T05/cold-smoke.sh`: a
fresh `git clone` of the worktree, an empty `UV_CACHE_DIR`, `uv sync --frozen` with the
network, then one `sandbox-exec -p '(version 1)(allow default)(deny network*)'` running
the negative control and `just wheel-smoke`, with `git status --porcelain` and the
`uv.lock` checksum taken before and after:

```text
clone HEAD 0d75e51; worktree HEAD 0d75e51
cache entries before sync: 0
curl: (6) Could not resolve host: pypi.org
curl exit 6
uv build --offline --out-dir dist
Successfully built dist/rovo-0.0.0-py3-none-any.whl
Installed 1 package in 1ms
 + rovo==0.0.0 (from file:///…/ai_tmp/T05/cold/dist/rovo-0.0.0-py3-none-any.whl)
wheel_smoke api: rovo 0.0.0, no CLI module imported, exactly the four package files and the expected metadata
Installed 7 packages in 8ms
wheel_smoke cli: rovo 0.0.0, from python -m rovo and the console script alike
rovo 0.0.0
wheel-smoke exit 0
status diff exit 0
lock diff exit 0
2d1a0cbd924460e4ba606dbf06e8928c5f7a11fbd708fc8f9e29c5e43115d85e  uv.lock
```

The same script with `UV_PYTHON=3.13 UV_NO_GROUP=tooling`: `curl exit 6`,
`Using Python 3.13.13 environment at: target/wheel-smoke/venv`, both `wheel_smoke`
lines, `wheel-smoke exit 0`, both diffs exit 0. Then, in that clone, under the denial
with `UV_OFFLINE=1`, the `floor` recipes: `curl exit 6`, `Python 3.13.13`, `just
lock-check`, `py-lint`, `py-typecheck`, `coverage` (TOTAL 100%) and `wheel-smoke` each
`exit 0`, and `git status --porcelain` printed 0 lines.

Hashes: `uv sync` checks the lock's hashes offline. With one `annotated-doc` hash
digit changed in a scratch `uv.lock`, under the denial:
`error: Failed to download annotated-doc==0.0.5 / cause: Hash mismatch for annotated-doc==0.0.5`,
exit 1; the lock was restored.

**H1 evidence** (at `9af0452` plus the edit, with `_TYPER_FORCE_DISABLE_TERMINAL` unset):
before the fixture, `GITHUB_ACTIONS=true uv run --frozen pytest -q tests/test_cli.py`
gave `2 failed, 5 passed`. After it: `GITHUB_ACTIONS=true`, `FORCE_COLOR=1`,
`PY_COLORS=1` and none each gave `7 passed`. A first version that set `None` still
failed under `FORCE_COLOR=1` (rich reads it itself), hence `False`. Control: with the
fixture's `setattr` replaced by `pass`, `GITHUB_ACTIONS=true` gave `2 failed, 5 passed`.

**Lychee evidence** (at `2c76a8d`'s tree). `just warm-lychee` on the warm cache:
`lychee 0.24.2 warmed: /Users/scutting/.cache/prek/repos/909c8f3d3d713742/.cargo/bin/lychee-0.24.2`,
exit 0. Under the denial (`curl exit 6`), with `PREK_HOME` empty, and again with a
`PREK_HOME` holding only an executable `lychee-0.24.1`, each printed
`warm-lychee: no lychee-0.24.2 binary after attempt 1`, `2`, `3` and exited 1.
`just initialize` in this secondary worktree ended
`lychee 0.24.2 warmed: …` then `Ready. Next: just check.` (exit 0). In the cold clone
at `0d75e51` (its own primary checkout, `git rev-parse --git-common-dir` and
`--git-dir` both `.git`), with an empty `PREK_HOME`, `just install-hooks` exited 0 and
printed `lychee 0.24.2 warmed: …/ai_tmp/T05/prek-cold/repos/909c8f3d3d713742/.cargo/bin/lychee-0.24.2`.

**Offline gate evidence** (`0d75e51`). In the clone, `shellingham` uninstalled from
`.venv` and an empty `UV_CACHE_DIR`, network available:

```text
## UV_OFFLINE=1 (as just check / floor set it)
error: Failed to download `shellingham==1.5.4`
  cause: Network connectivity is disabled, but the requested data wasn't found in the cache: https://files.pythonhosted.org/…/shellingham-1.5.4-py2.py3-none-any.whl
exit 1
## without UV_OFFLINE (before this change)
Installed 1 package in 1ms
```

**`just check` before the push** (`0d75e51`, raw `ai_tmp/T05/check-prepush1.log`), and
again after `557f403` and `fc01d5c`:

```text
All checks passed and the worktree is unchanged.
exit 0
```

**CI, run 4.** Pushed `1fd2f13..0d75e51` to `bootstrap`; watched with
`gh pr checks 2 --watch`. CI `https://github.com/BiscuitBin/rove/actions/runs/41018370415`,
Audit `https://github.com/BiscuitBin/rove/actions/runs/41018370588`, head
`0d75e512da2bfe3791652d5a93e0067f287947e6`:

```text
$ gh api repos/BiscuitBin/rove/commits/0d75e512da2bfe3791652d5a93e0067f287947e6/check-runs --jq '.check_runs[] | {name, conclusion, app_id: .app.id}'
{"app_id":15368,"conclusion":"success","name":"check"}
{"app_id":15368,"conclusion":"success","name":"audit"}
{"app_id":15368,"conclusion":"success","name":"gate (macos-latest)"}
{"app_id":15368,"conclusion":"success","name":"gate (ubuntu-latest)"}
{"app_id":15368,"conclusion":"success","name":"floor"}
```

Timings: floor 21s, gate ubuntu 28s, gate macOS 2m25s, check 3s, audit 18s. From the
job logs (raw `ai_tmp/T05/run4-*.log`):

- Both `gate` legs: `UV_OFFLINE=1 uv run --frozen bg-project-check run`, then
  `All checks passed and the worktree is unchanged.`
- macOS: `No GitHub Actions cache found for key: setup-uv-2-aarch64-apple-darwin-…`
  (a cold uv cache, so `wheel-smoke` passed cold in CI too), and
  `Cache not found for input keys: macOS-ARM64-prek-817c4e…`; then
  `lychee 0.24.2 warmed: /Users/runner/.cache/prek/repos/909c8f3d3d713742/.cargo/bin/lychee-0.24.2`,
  `ripsecrets built: /Users/runner/.cache/prek/hooks/rust-TTCoz9KTa0k0gIuEbbG8/bin/ripsecrets`,
  `"language_version": "1.99.1"`, `"toolchain": "/opt/homebrew/opt/rustup/bin/rustc"`
  (claim 6, macOS).
- `floor`: `Python 3.13.18`; `UV_OFFLINE: 1` in the recipe steps' env;
  `Using Python 3.13.18 environment at: target/wheel-smoke/venv`, `Installed 7 packages`,
  `wheel_smoke cli: rovo 0.0.0, from python -m rovo and the console script alike`.

`557f403` and `fc01d5c` (documents only: `CONVENTIONS.md`, `T00`'s note, these notes)
were pushed after run 4; their run is quoted below if it differs.

**After the CI diagnosis (`ai_tmp/ci-diag/PLAN.md`).** Run 4's macOS leg warmed lychee
on its first try from a cold prek cache and saved it (`Cache saved with key:
macOS-ARM64-prek-817c4e…`); run 5 (`b6dc55a`, `https://github.com/BiscuitBin/rove/actions/runs/41019047739`,
all five green) restored it (`Cache restored from key: macOS-ARM64-prek-817c4e…`).
The diagnosis found the earlier macOS failures were cargo-binstall's anonymous GitHub
API limit (60 an hour per IP), which `warm-lychee`'s back-to-back retries share, and
that `actions/cache` saves only when the whole job succeeds. So, as the orchestrator
directed, the setup action now passes `github.token` as `GITHUB_TOKEN` to the
`install-hooks` step alone, and
splits the prek cache into `actions/cache/restore` (`id: prek-cache`) and
`actions/cache/save` after the ripsecrets step on a miss. `CONVENTIONS.md` §10 follows,
§12 claims 4 and 5 are restated for the new command, and §1 fact 9 says the gate no
longer uses `uv export`.

Landed as `4057425`, run 6 (`https://github.com/BiscuitBin/rove/actions/runs/41019478400`,
audit 41019478394): all five jobs `success`. macOS: `Cache restored from key:
macOS-ARM64-prek-817c4e…`, `GITHUB_TOKEN: ***` on the install-hooks step,
`lychee 0.24.2 warmed: …`, the save step `outcome=skipped` (a hit), `All checks passed
and the worktree is unchanged.` The cold path with the token and the early save has not
run in CI: it runs on the next prek cache-key change. `develop-locally.md` no longer says
lychee runs "once".

**Claim outcomes.** In `CONVENTIONS.md` §12's new column (`fc01d5c`). Claim 4 failed
cold and its step was replaced; claim 5's command left the recipe; claim 12 is T06's.

**Maintainer decisions collected, not resolved.** The coverage floor at 100% (T02, since
resolved: 95%, below);
`SECURITY.md`'s contact while private vulnerability reporting reads `false` (T04, T01
step 9); decision 0006's licence options (T04); whether macOS stays in every pull
request's matrix (T01; timings above); T01 steps 9 to 11 (protection now has a green
`check` to name); Renovate's org-wide `repository_selection: all` (T06).

### Part B: fresh clone, read-back, freeze lift, index (orchestrator brief, 2026-10-30)

Scope: steps 5 to 7 up to, not including, the adversarial review. `RUSTUP_TOOLCHAIN=stable`
exported throughout (departure as in part A). Commits: `8777c90` (§11 freeze lifted),
`165874d` (README status column from each ticket's frontmatter: T00, T02 to T04 `done`;
T01, T05, T06 `open`). `develop-locally.md`'s "once" was already fixed in `06b48a2`.

**Fresh clone** (`ai_tmp/T05/fresh-b.sh`, raw `ai_tmp/T05/fresh-b.log`): `git clone -b
bootstrap` of the worktree into `ai_tmp/fresh`, with `UV_CACHE_DIR` and `PREK_HOME`
pointed at new empty directories under `ai_tmp/T05/`:

```text
worktree HEAD 06b48a2
clone exit 0
clone HEAD 06b48a2
uv cache entries:        0; prek entries:        0
## just initialize
Using CPython 3.14.8
lychee 0.24.2 warmed: …/ai_tmp/T05/prek-cold-b/repos/909c8f3d3d713742/.cargo/bin/lychee-0.24.2
Ready. Next: just check.
initialize exit 0
## just check
TOTAL                     17      0      2      0   100%
wheel_smoke cli: rovo 0.0.0, from python -m rovo and the console script alike
All checks passed and the worktree is unchanged.
check exit 0
## git status --short
status lines        0
```

The `floor` recipes, same clone, `UV_PYTHON=3.13 UV_NO_GROUP=tooling just py-lint
py-typecheck coverage wheel-smoke` (without `lock-check` and the job's `UV_OFFLINE=1`;
the full set is rerun under "Review T05-1 fixes" below):

```text
Using CPython 3.13.13
platform darwin -- Python 3.13.13, pytest-9.2.0, pluggy-1.7.0
TOTAL                     17      0      2      0   100%
Using Python 3.13.13 environment at: target/wheel-smoke/venv
wheel_smoke api: rovo 0.0.0, no CLI module imported, exactly the four package files and the expected metadata
wheel_smoke cli: rovo 0.0.0, from python -m rovo and the console script alike
floor exit 0
## git status --short after floor
status lines        0
```

`ai_tmp/fresh` was then deleted. `8777c90` and `165874d` change only `tickets/`, after
the clone's `HEAD`.

**Protection read-back** (at `06b48a2`; read-only, nothing applied; T01 steps 9 to 11
await the maintainer, and T01 owns the apply):

```text
$ gh api repos/BiscuitBin/rove/branches/main/protection/required_status_checks --jq '[.checks[] | {context, app_id}]'
{"message":"Branch not protected","documentation_url":"https://docs.github.com/rest/branches/branch-protection#get-status-checks-protection","status":"404"}gh: Branch not protected (HTTP 404)
exit 1
$ gh api repos/BiscuitBin/rove/branches/main/protection
{"message":"Branch not protected",…,"status":"404"}gh: Branch not protected (HTTP 404)
exit 1
$ gh api repos/BiscuitBin/rove --jq '.permissions.admin'
true
$ gh api repos/BiscuitBin/rove/rulesets --jq 'length'      → 0, exit 0
$ gh api repos/BiscuitBin/rove/rules/branches/main --jq 'length'  → 0, exit 0
```

The 404 names absence and the token is admin, so protection is absent, matching T01's
notes (nothing sent). Carried as an open point.

### Review T05-1 fixes (conformance and breakage lenses)

Applied in the working tree on `6bc5925`, uncommitted at writing; the triage is in
`ai_tmp/review/T05-1/verdicts.md`. `RUSTUP_TOOLCHAIN=stable` throughout.

**No token reaches hook builds again** (C1). `install-hooks` runs both prepares under
`env -u GITHUB_TOKEN -u GH_TOKEN`, so the run's token, which the setup action still
passes to that step, reaches only `warm-lychee`'s cargo-binstall calls, as in A's
`install-tools`. `GITHUB_TOKEN=x just install-hooks` on the warm cache: both prepares
print with the `env -u` prefix, `lychee 0.24.2 warmed: …/909c8f3d3d713742/…`, exit 0.
Unproven: the cold path (a ripsecrets build with the token unset) has not run, and the
prek cache key does not include the `Justfile`, so CI's next run restores a warm cache;
if lychee's hook falls back from cargo-binstall to `cargo install`, that compile still
sees the token.

**`warm-lychee` accepts only the hook's own checkout** (B1). It reads the lychee repo's
`rev` from `.pre-commit-config.yaml` (fails closed unless 40 hex) and accepts a binary
only in a cache checkout whose `.prek-repo.json` names `"repo":
"https://github.com/lycheeverse/lychee"` and that rev; this machine also holds a
`…/lychee.git` checkout of the same rev from another project, which the old glob
accepted. Positive: the warm run above. Negative, a `PREK_HOME` holding only that
`.git` checkout with its executable `lychee-0.24.2`, under the §11 denial (`curl exit
6`): `warm-lychee: no lychee-0.24.2 binary after attempt 1` (and 2, 3), exit 1. Control:
`6bc5925`'s recipe on the same `PREK_HOME` printed `lychee 0.24.2 warmed:
…/9c6e4fd962800d41/…`, exit 0. `.prek-repo.json` is prek's internal format.

**§12 claim 5, the repository tree measured directly** (B2, C3). In a scratch clone of
`6bc5925` after `just build`, the smoke venv and the wheel install, a marker file, then
`UV_PROJECT_ENVIRONMENT=target/wheel-smoke/venv uv sync --frozen --offline
--no-default-groups --no-install-project --inexact` (installed `shellingham`, `typer`):
`find . -newer <marker> -not -path './target/*' -not -path './.git/*'` printed nothing
(`outside lines 0`); positive control, `find target -newer <marker>`: 62; `git status
--porcelain`: 0 lines. The uv cache, outside the repository, was not measured.

**Step 5's full `floor` set** (C2). A fresh `git clone -b bootstrap` of the worktree
into `ai_tmp/fresh` (clone `HEAD` `6bc5925`; warm default caches), `just initialize`
(exit 0), then `UV_PYTHON=3.13 UV_NO_GROUP=tooling UV_OFFLINE=1 just lock-check py-lint
py-typecheck coverage wheel-smoke` (raw `ai_tmp/T05/fresh-c2-floor.log`):

```text
Using CPython 3.13.13
Resolved 23 packages in 2ms
All checks passed!
Success: no issues found in 6 source files
platform darwin -- Python 3.13.13, pytest-9.2.0, pluggy-1.7.0
TOTAL                     17      0      2      0   100%
wheel_smoke api: rovo 0.0.0, no CLI module imported, exactly the four package files and the expected metadata
wheel_smoke cli: rovo 0.0.0, from python -m rovo and the console script alike
floor exit 0
status lines 0
```

`ai_tmp/fresh` was then deleted. The review's other edits are `CONVENTIONS.md` §10's
setup-action bullet, the setup action's comment, and §12 rows 5 and 10 (row 10 now
cites T00 part 3, whose quote is the passing one) (C4).

### Review record, T05-1 (step 7's checkpoint, reviewed at `6bc5925`)

There were two reviewers, both `codex exec -m gpt-6-astra -s read-only`, one per lens
(conformance, breakage). Separate triage subagents judged each finding and applied the
fixes one at a time. The raw files, which are not committed, are in
`ai_tmp/review/T05-1/`, with the merged verdicts in `verdicts.md`. There were six
findings, all valid, none high, so no second round runs; nothing was handed back.

| id | severity | verdict | reason | action |
| --- | --- | --- | --- | --- |
| C1 | medium | valid | `GITHUB_TOKEN` reached both prek prepares, which compile ripsecrets; A kept the token from compiles | `env -u GITHUB_TOKEN -u GH_TOKEN` on both prepares; §10 and the action's comment follow |
| C2 | low | valid | part B's fresh-clone `floor` quote left out `lock-check` and `UV_OFFLINE=1` | the full set rerun and quoted above |
| C3 | low | valid | §12 claim 5's evidence was blind to ignored paths | applied as B2's form |
| C4 | low | valid | §12 claim 10 cited T00 part 2, a failing quote | cites part 3 |
| B1 | medium | valid | `warm-lychee` accepted a `lychee-<ver>` from any prek checkout, a foreign one included | matches the hook's repo URL and 40-hex rev in `.prek-repo.json` |
| B2 | low | valid | the same gap as C3; a direct `find -newer` measurement shows the claim holds | §12 row 5 quotes the measurement |

C3 and B2 both rewrote §12 row 5; B2's form, the direct measurement with a positive
control, was applied. Re-run after the fixes, on `6bc5925` with them uncommitted, with
`RUSTUP_TOOLCHAIN=stable`; they were then committed as `T05: §14 review fixes`:

```text
$ { just check 2>&1; echo "exit $?"; } | tail -2
All checks passed and the worktree is unchanged.
exit 0
$ { uv run --frozen prek run actionlint --all-files 2>&1; echo "exit $?"; } | tail -2
Lint GitHub Actions workflow files.......................................Passed
exit 0
```

Residuals, open: C1's cold path is unproven (no cold ripsecrets build with the token
unset has run, and the prek cache key leaves out the `Justfile`, so CI restores a warm
cache), and a lychee `cargo install` fallback would still see the token; B1 relies on
prek's internal `.prek-repo.json` format; `just --fmt --check` reports differences, as
it did before the review (not a gate).

### Maintainer decision: coverage floor 95% (2026-10-30)

The maintainer set the coverage floor to 95%. The brief phrased it as lowering the floor
from 100%; the floor was in fact `coverage_floor := "90"`, and 100% is the measured
total (T02's open point asked whether to raise it to 100%). So the floor rises from 90
to 95, and the total stays 100%. Changed, every place the number lives (`rg -n
'\b90\b'` over the tree outside `tickets/T0*` and `ai_tmp/` then printed nothing, exit
1): `Justfile` `coverage_floor`, `tickets/CONVENTIONS.md` §4's `Justfile` and §7 invariant
5, `AGENTS.md` invariant 5, `docs/reference/configuration.md`, `testing.md`,
`commands.md`, `quality-gates.md` and `docs/explanation/quality-philosophy.md`.
`.coveragerc` names no number (the floor is the `Justfile`'s, never also there), and
the skills say only "the floor". T02's open point is answered in its notes.

The floor bites, on `4f6ebbf` with the change uncommitted. A scratch copy of
`src/rovo/cli.py` was saved to `ai_tmp/scratch/`, an uncalled function appended, `just
coverage` run, and the copy restored, each time:

```text
## a two-statement uncalled function: between 90 and 95
TOTAL                     20      2      2      0    91%
Coverage failure: total of 91 is less than fail-under=95
error: recipe `coverage` failed on line 129 with exit code 2
exit 2
## same data, `coverage report --fail-under 90` (the old floor)
TOTAL                     20      2      2      0    91%
at 90: exit 0
## a five-statement function with a branch
TOTAL                     23      5      4      0    74%
Coverage failure: total of 74 is less than fail-under=95
exit 2
## restored
cmp exit 0
git diff --quiet exit 0
TOTAL                     17      0      2      0   100%
exit 0
```

One untested statement alone does not breach it: coverage rounds the total to its
precision (0) before comparing, and 20 of 21 units rounds to 95.

### Protection read-back after T01's step 9 (2026-10-30T21:53:35Z)

T01 applied protection with the maintainer's authorisation (T01's "Part 3 evidence").
Step 6's read-back now:

```text
$ gh api repos/BiscuitBin/rove/branches/main/protection/required_status_checks --jq '[.checks[] | {context, app_id}]'
[{"app_id":15368,"context":"check"}]
exit 0
```

This matches T01's hand-back: `check` alone, from the GitHub Actions app. The
part B open point (protection absent) is closed. CI on PR #2's head `debdb10`: run
`41133146908` (`check`, both `gate` legs, `floor`) and `41133147022` (`audit`), all
`pass`.

**Status.** Every acceptance criterion has evidence except "CI is green on `main` after
merge", which exists only after the maintainer merges PR #2. That merge happens with
T06's merge stop, so the criterion is carried there, and `status:` stays `open` until
the first `ci.yml` run on `main` is quoted.

### Final code review (bootstrap at `71011da`, 2026-10-30)

Ten findings from the final code review, each checked by two adversarial verifiers.
A finding was applied only when both verdicts held it real; each applied fix is its
own commit with a negative and a positive control, and `just check` passed after the
last (`090d25f`). Commands and exit codes: `ai_tmp/final-review/fix-log.md`.

| Id | Finding | Verdicts | Outcome |
| --- | --- | --- | --- |
| F1 | `install-hooks` had no secondary-worktree guard; run there, it pointed the shared shim at that worktree's `.venv`. | real (low), real (medium) | Applied, `f234e9a`: the recipe exits 2 before touching anything when `--git-common-dir` and `--git-dir` differ. Refused in this worktree with the shared shim unchanged; installed in a scratch primary clone. |
| F2 | `.markdownlint-cli2.jsonc`'s `globs: ["**/*.md"]` made every run lint, and `just fix` rewrite, every `.md` on disk, ignored ones included. | real (medium), real (medium) | Applied, `103e8b8`: `globs` removed. Scratch clone with defects in `.pytest_cache/` and `.claude/worktrees/`: old config failed on them (67 files linted for `README.md`), new one lints 1 file, 65 across `--all-files`, leaves them byte-identical under the fix config, and still fails a tracked `SECURITY.md` defect. |
| F3 | `initialize.sh`'s secondary-worktree prepares kept `GITHUB_TOKEN` and `GH_TOKEN`, unlike `install-hooks`. | real (low), real (low) | Applied, `1524955`: both prepares run under `env -u`; `warm-lychee` keeps the token. Stub `uv`/`just` showed the tokens before and `unset` after. CONVENTIONS §4's `install-hooks` block now equals the `Justfile`. |
| F4 | The maintain-dependencies how-to and decision 0008 said no gate compares lychee's rev comment with `LYCHEE_VERSION`, stale since `71011da`. | real (low), real (low) | Applied, `fcaad0b`: both say `install-hooks` fails on a mismatch and that nothing checks the SHA against the tag (a zeroed SHA passes the comparison; a changed comment fails it). |
| F5 | `just check` runs py-lint, py-typecheck and the docs and agents checks twice (through `lint` and by name). | not real, not real | Not applied: CONVENTIONS §2/§4 fix the recipe list and order, §5 keeps the hooks, as A does; the repeats are read-only and deterministic. |
| F6 | `floor` and `audit` run `install-hooks` though they run no hook. | not real, not real | Not applied: §10 has the setup action run `install-hooks` unconditionally with `python-version` its only input, as A's does. |
| F7 | The lychee comment check is not in `just check`. | not real, real (low) | Not applied (split): §4 puts it in `warm-lychee`, and every CI setup fails on the drift, so it cannot merge. |
| F8 | The prek cache key omitted the Python version, so the 3.13 floor and 3.14 Linux legs shared an entry whose python hook environment names an interpreter path. | real (low), real (low) | Applied, `090d25f`: restore and save keys carry `py<python-version>`. Rendered per job: floor `Linux-X64-prek-py3.13-…`, gate (ubuntu) and audit `…-py3.14-…`, where all three were one key before. Not yet run in CI. |
| F9 | `floor` checks a clean tree with inline `git status --porcelain`, not a recipe. | not real, not real | Not applied: §10 prescribes it, because `check-clean` is B's and cannot run on 3.13. |
| F10 | `cancel-in-progress: true` cancels a superseded `main` run and `check` then reports it failed. | not real, real (low) | Not applied (split): §10 requires A's `concurrency` block; nothing consumes a `main` run's result. |

Maintainer action carried from F1: the shared shim at
`/Users/scutting/projects/biscuitbin/rove/.git/hooks/pre-commit` still names this
worktree's `.venv/bin/prek`. Once `main` has `f234e9a`, run `just install-hooks` once
from the primary checkout (a network recipe, so it needs explicit authorization), and do
it before this worktree is removed, or every commit fails.

## Open points

None at writing; step 2 may add some.

- Carried from part A: README `blob/main` links (T04); `_typos.toml` `mis`/`als`
  (kept while tickets quote them); the rest of T04's re-check list, for the adversarial
  review; the maintainer decisions listed at the end of part A.
- Protection on `main`: closed, applied by T01 and read back above.
- Step 7's adversarial review ran (T05-1, recorded above). Step 8's merge and the first
  `ci.yml` run on `main` are not done: carried to T06's merge stop.
