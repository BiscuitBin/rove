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
   approving any update on the dashboard; the first one approved proves the relock (claim 12).

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

## Open points

- Whether the B tag should follow B's releases automatically or stay manual: B's
  checkers decide what the gate accepts, so a bump can redden `main`. The maintainer
  decides; the default here is "held for dashboard approval", as every update is.
