---
id: T06
title: "Renovate over every pin, behind an authorised app install"
status: open
depends_on: [T05]
parallel_with: []
branch: ticket/t06-renovate
estimated_size: M
---

# T06: Renovate over every pin, behind an authorised app install

## Context

Nothing updates this repository's pins today: the exact tool pins and typer's range in
`pyproject.toml`, `uv.lock`, the B git tag in `[tool.uv.sources]`, the `rev` SHAs in
both prek configurations, the action SHAs in `.github/`, and the uv and just versions
the setup action installs. L's spike S01 compared Dependabot, Renovate and nothing,
recommended Renovate through the Mend app with dependency-dashboard approval, and
drafted the build ticket (L `tickets/S01-dependency-updates.md` lines 666-905, with the
evidence from line 164); A's T17 adapted that draft (A `tickets/T17-renovate.md`). This
ticket adapts both to a uv project: the `pep621` manager reads `[project]`,
`[dependency-groups]` and `[build-system]`, and relocks `uv.lock`
(`CONVENTIONS.md` §12 claim 12); the prek `rev`s and the B tag may need custom
managers, as A's did.

It comes last because Renovate has to know every pin, and T01 added the action pins.

## Goal

`renovate.json` on `main` covers every pin in the repository through a native manager
where one exists and a custom manager where one does not, with nothing excluded; the
Mend Renovate app is installed on `BiscuitBin/rove` only, after the maintainer's
authorisation; the dashboard lists every pin with no configuration error;
`docs/how-to/maintain-dependencies.md` says what Renovate proposes and what stays
manual; and decision 0008 records it.

## Non-goals

- No automerge.
- No Dependabot. If the app is declined, stop and hand back.
- No pin moved by this ticket's hand. Renovate's first pull requests are the proof.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `renovate.json` | new | step 3 |
| `docs/decisions/0008-renovate.md` | new | `CONVENTIONS.md` §8 |
| `docs/manifest.yml` | shared, own lines | register 0008 |
| `docs/decisions/README.md` | shared, own lines | the 0008 row |
| `docs/how-to/maintain-dependencies.md` | shared, own lines | what Renovate proposes, what stays manual |
| `docs/explanation/security-model.md` | shared, own lines | the app's permissions |
| `docs/operations/maintenance.md` | shared, own lines | the dashboard in the routine |
| `CHANGELOG.md` | shared, own lines | one `Unreleased` line |
| repository installation of the Mend Renovate app | GitHub state | after **Authorisation required** |

## Steps

1. Create the worktree after T05 has merged; `just initialize`; `just check` baseline.
2. **Inventory every pin** on `main`, by file, each marked native manager, custom
   manager, or manual with a reason: `pyproject.toml` (`[build-system] requires`,
   `[project] dependencies`, `requires-python` — manual, it is decision 0001's floor —
   each `[dependency-groups]` pin, the B tag under `[tool.uv.sources]`), `uv.lock`,
   `.python-version` (manual: decision 0001), `.pre-commit-config.yaml` and
   `.pre-commit-fix.yaml` (each `rev` with its version comment, and the
   `LYCHEE_VERSION=` argument that must match lychee's `rev`, A
   `.pre-commit-config.yaml`), every remote `uses:` in `.github/`, the setup action's uv
   `version:` input and its `rust-just==` pin, and the `python-version` inputs of
   `ci.yml` (manual: decision 0001). Quote the inventory as a table.
3. **`renovate.json`.** L's draft (L `tickets/S01-dependency-updates.md` from line 474)
   as A `tickets/T17-renovate.md` step 3 adapted it, minus everything Rust, pixi and
   allium, with: `:dependencyDashboard` and `:dependencyDashboardApproval`; GitHub
   Actions digests pinned with their version comments kept; lock-file maintenance
   weekly; lychee brought into Renovate, which the draft keeps out, so that its `rev` and
   its `LYCHEE_VERSION=` arguments always move together: drop the draft's
   `{ "matchDepNames": ["lycheeverse/lychee"], "enabled": false }` rule (it would also
   disable any new manager under that depName). Leave the draft's hook-rev regex as it is:
   its `# v\d+` comment match leaves out lychee's `# lychee-v0.24.2` on purpose, so it
   never reads lychee's `rev`. Add two regex managers under `depNameTemplate:
   lycheeverse/lychee`, `datasourceTemplate: github-tags` and `extractVersionTemplate:
   ^lychee-v(?<version>.*)$`: one over the lychee `rev` line in `.pre-commit-config.yaml`
   (capturing the 40-character `currentDigest` and the version after `# lychee-v` as
   `currentValue`, with an `autoReplaceStringTemplate` that writes the `lychee-v` prefix
   back), and one over every `LYCHEE_VERSION=(?<currentValue>\d+\.\d+\.\d+)`. Add a
   `packageRules` entry `{ "matchDepNames": ["lycheeverse/lychee"], "groupName":
   "lychee" }` placed after the hook-revs rule, so that both readings land in one pull
   request. Step 6 proves this: the dashboard lists the `rev` and both arguments under
   `lycheeverse/lychee`, and the first lychee pull request moves all three; a custom
   manager for the B tag if `pep621`
   does not read it (decided from the dashboard in step 5, not assumed); a custom
   manager for `rust-just==` and the setup-uv `version:` input. Validate it as A's
   ticket does: well-formed JSON now (`python3 -I -c 'import json, sys;
   json.load(open(sys.argv[1]))' renovate.json`), Renovate's own validation after
   landing.
4. **Docs.** Decision 0008, registered in the manifest and the decisions index; the
   how-to, the security model (the app's permissions, read from its installation page
   in step 5), the maintenance routine, the `CHANGELOG.md` line. `just check-docs`.

   **Adversarial review** (`CONVENTIONS.md` §14): the inventory and `renovate.json`,
   before step 5 asks. The review goes into the authorisation request. Ask: which pin is
   missing from the inventory; which manager pattern matches more or less than it
   claims; is lychee's `rev` read at all (not disabled, matched by a regex), and can it
   move without its `LYCHEE_VERSION`; which pin Renovate would bump that no gate would
   catch if the bump were wrong.
5. **Land, then install.** **Authorisation required**: push, open the pull request, and
   merge it, so that the configuration is on `main` before the app arrives (L's draft,
   step 1: no onboarding pull request). Then **Authorisation required**: the maintainer
   installs the Mend Renovate app on `BiscuitBin/rove` only ("Only select
   repositories"), which may need an organisation owner (`CONVENTIONS.md` §13). Quote
   the dated read-back of the installation's repository access and permissions, and who
   performed it.
6. **Prove it.** Wait for the dependency dashboard issue. Quote: the absence of an
   `Action Required: Fix Renovate Configuration` issue
   (`gh issue list --repo BiscuitBin/rove --search 'Fix Renovate Configuration in:title'`),
   the dashboard's detected-dependencies section, and for each inventory row the
   dashboard line that covers it. If a row is not detected, add the custom manager it
   needs on a follow-up branch and repeat. **Authorisation required**:
   approving any update on the dashboard. Claim 12 needs an update from the `pep621`
   manager (a `[project]` or `[dependency-groups]` pin), not an action SHA, a hook `rev`
   or lock-file maintenance, because those can land without touching `uv.lock` or
   without a manifest change. Ask the maintainer to approve one such update, then quote
   `gh pr diff <n> --repo BiscuitBin/rove --name-only` showing both `pyproject.toml` and
   `uv.lock`, the changed `uv.lock` entry, and that PR's green `check`. Until then the
   claim stays open.

   **Adversarial review** (`CONVENTIONS.md` §14): the final diff and the dashboard
   evidence, before the final commit of the hand-back notes. That commit, with
   `status: done`, goes on a closing pull request off the updated `main` (README,
   Definition of done). **Authorisation required**: push and open it.

## Acceptance criteria

- Every inventory row is covered with dashboard evidence, or manual with its reason in
  the how-to.
- No configuration-error issue exists; the dashboard issue is open; both quoted.
- The app's repository access lists only `BiscuitBin/rove`, quoted with date and reader.
- `CONVENTIONS.md` §12 claim 12 has an outcome.
- `just check` is green.
- The adversarial reviews ran and every valid finding is fixed or handed back.

## Verification

```sh
git rev-parse --short HEAD
python3 -I -c 'import json, sys; json.load(open(sys.argv[1]))' renovate.json; echo "exit $?"
gh issue list --repo BiscuitBin/rove --search 'Dependency Dashboard in:title' --json number,title,state
gh issue list --repo BiscuitBin/rove --search 'Fix Renovate Configuration in:title' --json number,state
gh pr list --repo BiscuitBin/rove --author 'app/renovate' --state all --json number,title,headRefName
just check-docs; echo "exit $?"
{ just check 2>&1; echo "exit $?"; } | tail -2
```

## Hand-back notes

To be written by the executing agent: the inventory, what the maintainer authorised and
when, the installation read-back, the per-row dashboard evidence, the first relock, the
review record for each checkpoint, and where this ticket departed from L's draft and
A's T17 (at least: lychee is now enabled and has its own regex managers).

### Steps 1 to 4, at `2c37124` (local part)

Run on 2026-10-30 in the `bootstrap` worktree, not a `ticket/t06-renovate` worktree off
`main`: `main` holds only the tickets until PR #2 (`bootstrap`, carrying T00 to T05)
merges, so the inventory is taken on `bootstrap` (recorded departure, as for every
ticket in this round). `RUSTUP_TOOLCHAIN=stable` exported for the hook builds. Nothing
was pushed and no GitHub state was changed.

**State reads (read-only `gh`, 2026-10-30T21:48Z, each exit 0).** The Mend Renovate app
is already installed on the organisation: `gh api orgs/BiscuitBin/installations`
returns installation `174933380`, `app_slug: renovate`, `repository_selection: all`,
created 2026-10-24, permissions `administration: read, checks: write, contents: write,
issues: write, members: read, metadata: read, packages: read, pull_requests: write,
statuses: write, vulnerability_alerts: read, workflows: write`. The ticket's "rove only"
is therefore not the current state; reported, not changed. `gh pr list --repo
BiscuitBin/rove --author app/renovate --state all` prints `[]`, a title search for
`Renovate` in issues prints `[]`, and the branches are `bootstrap`,
`bootstrap-tickets`, `main`: no onboarding pull request, dashboard or Renovate branch
after six days of access (cause unknown; the Mend portal's settings are not readable
from here). Consequence for step 5: the app already reads this repository, so the merge
that puts `renovate.json` on `main` is the moment Renovate starts on it. `main`
protection: `checks: [{context: check, app_id: 15368}]`, `required_pull_request_reviews:
null`, `enforce_admins: false`.

**Inventory (step 2).** Extraction column from a local Renovate run (below).

| File | Pin | Coverage | Extracted as |
| --- | --- | --- | --- |
| `pyproject.toml` | `[build-system] requires = ["hatchling==1.33.0"]` | native `pep621` | `hatchling`, `build-system.requires`, pypi; a bump edits `pyproject.toml` only |
| `pyproject.toml` | `typer>=0.27.3,<0.28` | native `pep621`, `update-lockfile` | `typer`, `project.dependencies` |
| `pyproject.toml` | `coverage`, `mypy`, `prek`, `pytest`, `ruff` `==` pins | native `pep621` | five `dependency-groups` deps, pypi |
| `pyproject.toml` | `requires-python = ">=3.13"` | manual, decision 0001; rule disables it | `python`, `requires-python`; lookup `skipReason: disabled` |
| `pyproject.toml` | B tag `v0.3.0` in `[tool.uv.sources]` | native `pep621` (no custom manager needed) | `biscuit-games-tooling`, `tool.uv.sources`, github-tags `steven-cutting/biscuit_games_tooling` |
| `uv.lock` | the transitive closure | native `pep621` relock, plus weekly lock-file maintenance | (lock file of the `pep621` package file) |
| `.python-version` | `3.14` | manual, decision 0001; rule disables `pyenv` | `pyenv`, `python` 3.14; lookup `skipReason: disabled` |
| `.pre-commit-config.yaml` | six `rev`s with `# v…` comments (editorconfig-checker, markdownlint-cli2, typos, shellcheck-py, actionlint, ripsecrets) | regex manager (hook revs) | six github-tags deps with digests |
| `.pre-commit-config.yaml` | lychee `rev` `2bba271…` `# lychee-v0.24.2` | regex manager (lychee rev) | `lycheeverse/lychee` 0.24.2 with digest |
| `.pre-commit-config.yaml` | `LYCHEE_VERSION=0.24.2`, twice (lines 110, 123) | regex manager (`LYCHEE_VERSION`) | two `lycheeverse/lychee` 0.24.2 |
| `.pre-commit-fix.yaml` | markdownlint-cli2 `rev` | regex manager (hook revs) | one github-tags dep with digest |
| `.github/workflows/ci.yml`, `audit.yml` | `actions/checkout` SHA `# v7.0.1` (three uses) | native `github-actions` | three `action` deps |
| `.github/actions/setup/action.yml` | `astral-sh/setup-uv` SHA `# v10.3.3`; `actions/cache/restore`, `actions/cache/save` SHA `# v6.1.0` | native `github-actions` | three `action` deps |
| `.github/actions/setup/action.yml` | setup-uv `version: '0.13.6'` | native `github-actions` (known-actions table) | `astral-sh/uv`, `uses-with`, github-releases |
| `.github/actions/setup/action.yml` | `uv tool install rust-just==1.59.0` | regex manager (just) | `rust-just` 1.59.0, pypi |
| `.github/workflows/ci.yml` | `python-version: '3.14'`, `'3.13'` (inputs of the local action) | manual, decision 0001 | not extracted |
| not pins | `uses: ./.github/actions/setup`, `runs-on: ubuntu-latest`/`macos-latest` | none | `ubuntu` runner `skipReason: invalid-version` |
| `docs/how-to/develop-locally.md` lines 15-16 | prose floors `0.13.6 or newer`, `rust-just==1.59.0` | manual (stated floors, no manager) | not extracted |

Count by manager (local extraction): `github-actions` 10 deps in 3 files (7 pins, 3
runner labels skipped), `pep621` 9 in 1, `pyenv` 1 in 1 (disabled), regex 11 in 5
matches over 3 files (hook revs 7, lychee rev 1, `LYCHEE_VERSION` 2, just 1); total 31.

**Proof that each pattern matches (step 3).** Renovate 44.181.1 from the npx cache
(`~/.npm/_npx/feb637db22af21da`, no install), on a copy of the tracked tree plus
`renovate.json` in `ai_tmp/T06/copy`, under
`sandbox-exec -p '(version 1)(allow default)(deny network*)'`:

- `node …/dist/config-validator.js --strict` in the copy: `Validating renovate.json`,
  `Config validated successfully against 1 file(s)`, exit 0.
- `node …/dist/renovate.js --platform=local --dry-run=extract --onboarding=false`:
  `Dependency extraction complete`, stats `{"github-actions": {"fileCount": 3,
  "depCount": 10}, "pep621": {"fileCount": 1, "depCount": 9}, "pyenv": {"fileCount": 1,
  "depCount": 1}, "regex": {"fileCount": 5, "depCount": 11}}, total 31`. Exit 1, whose
  only level-50 log line is `Unsupported node environment detected` (node 26.5.1
  against Renovate's `^24.11.0`), not an extraction error.
- `--dry-run=lookup` under the same denial: `requires-python` and `.python-version`
  carry `skipReason: disabled` and no other dependency does, so the two rules hit only
  their targets. Every github-tags dependency shows `github-token-required` (no token
  offline); no update lookup ran, so no update or grouping was proven locally.
- Negative control inside the same denial: `curl -fsS --max-time 10
  https://pypi.org/simple/` exits 6 (`Could not resolve host`).
- A Python `re` pass of each custom manager's `matchStrings` over its files: hook revs,
  6 matches in `.pre-commit-config.yaml` (lines 73, 82, 88, 127, 132, 138; lychee's
  line 96 not among them) and 1 in `.pre-commit-fix.yaml` (line 35); lychee rev, 1
  (line 96, digest `2bba271688c1`, value `0.24.2`); `LYCHEE_VERSION`, 2 (lines 110,
  123); just, 1 (`action.yml` line 35, `1.59.0`).
- `python3 -I -c 'import json, sys; json.load(open(sys.argv[1]))' renovate.json`:
  exit 0.

**Departures from the ticket, L's draft and A's T17.**

- lychee is enabled: the draft's `enabled: false` rule is gone; two regex managers read
  its `rev` and both `LYCHEE_VERSION=`, and a `lychee` group rule after the hook-revs
  rule joins them.
- No custom manager for the setup-uv `version:` input, against step 3's text: Renovate's
  `github-actions` manager reads it natively (`astral-sh/setup-uv` is in its
  known-actions table; extracted as `astral-sh/uv`, `uses-with`), and a regex manager on
  the same line would read it twice. It falls in the `github actions` group.
- No custom manager for the B tag: `pep621` extracted it locally. The dashboard in step
  6 is still the proof on the hosted app's version.
- Two `enabled: false` rules the draft does not have: `pyenv` (it reads
  `.python-version`) and `pep621` `requires-python`, so the two rows marked manual cannot
  be proposed.
- Dropped from the draft as not applicable here: cargo, rust toolchain, pixi, the pixi
  bootstrap pair, `tools.txt`, cargo-hack. The draft's B-tag regex manager is dropped
  (native).
- Docs are in held-mode wording (every update waits for a dashboard approval).
- `docs/explanation/security-model.md` records the permissions from the organisation
  installation's API read, not from an installation screen, since the app is already
  installed.

**Hand-backs (outside Files touched).** `docs/decisions/0005-dependency-policy.md` line
49 says nothing updates any pin until T06 lands; it goes stale when this lands (a
decision record, to be amended or superseded by its owner).
`docs/how-to/develop-locally.md` lines 15-16 state uv and just versions that no manager
reads; after a Renovate bump they are floors that still hold, but read stale.

**Checks at `2c37124`.** `just check-docs`: `Validated 32 pages and 32 canonical
topics.`, exit 0. `just check`, exit 0, last line `All checks passed and the worktree is
unchanged.` The commit's prek hook temporarily set aside an unrelated, concurrent
unstaged edit to `tickets/T01-github-and-ci.md` and restored it.

**Checks at `93821a2`** (this notes commit, on top of the concurrent T01 commit
`7bc4b65`). The commit was chained after `{ just check-docs; echo "exit $?"; } | tail -3
&&`, so `&&` tested `tail`, and the commit went in after `just check-docs` had exited 1
(failing hook not captured; concurrent unstaged edits to `tickets/README.md`,
`tickets/T01-github-and-ci.md` and `tickets/T05-integration.md` were present). Re-run at
`93821a2` with the same concurrent edits: `just check-docs` exit 0, `Validated 32 pages
and 32 canonical topics.`; `just check` exit 0, last line `All checks passed and the
worktree is unchanged.`

**Open at this point.** `CONVENTIONS.md` §12 claim 12: open. Local extraction shows
`pep621` reading `[dependency-groups]` and the `[tool.uv.sources]` tag; the relock of
`uv.lock` is unproven until a step 6 `pep621` pull request. Nothing in the gate checks
that lychee's `rev` and `LYCHEE_VERSION=` agree (the hook downloads the
`LYCHEE_VERSION` binary whatever the `rev`), so the `lychee` group is the only guard;
and a hook or B bump that weakens a check passes `just check`. Both for the adversarial
review.

## Open points

- Whether the B tag should follow B's releases automatically or stay manual: B's
  checkers decide what the gate accepts, so a bump can redden `main`. The maintainer
  decides; the default here is "held for dashboard approval", as every update is.
