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
| Coverage floor at 100% | T02 open point | maintainer decision |
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

**Claim outcomes.** In `CONVENTIONS.md` §12's new column (`fc01d5c`). Claim 4 failed
cold and its step was replaced; claim 5's command left the recipe; claim 12 is T06's.

**Maintainer decisions collected, not resolved.** The coverage floor at 100% (T02);
`SECURITY.md`'s contact while private vulnerability reporting reads `false` (T04, T01
step 9); decision 0006's licence options (T04); whether macOS stays in every pull
request's matrix (T01; timings above); T01 steps 9 to 11 (protection now has a green
`check` to name); Renovate's org-wide `repository_selection: all` (T06).

## Open points

None at writing; step 2 may add some.

- Carried from part A: README `blob/main` links (T04); `_typos.toml` `mis`/`als`
  (kept while tickets quote them); the rest of T04's re-check list, for the adversarial
  review; the maintainer decisions listed at the end of part A.
