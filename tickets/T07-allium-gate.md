---
id: T07
title: "Allium gate: the placeholder module, the spec recipes, the Allium skills, the specification workflow"
status: done
depends_on: [T05]
parallel_with: []
branch: ticket/t07-allium-gate
estimated_size: M
---

# T07: Allium gate: the placeholder module, the spec recipes, the Allium skills, the specification workflow

## Context

Every other Biscuit repository decides behaviour in Allium modules under `docs/specs/`
and holds them to a gate; this one does not. `AGENTS.md` says so today: "this repository
holds no `docs/specs/` directory, because it has no Allium specifications yet". The
product is still unspecified, and this ticket does not specify it. It brings in the
machinery the first product ticket will need, exactly as pachinko carries it, so that the
first real module lands into a working loop rather than building one.

Pachinko is source **P** (`CONVENTIONS.md` §0, `/Users/scutting/projects/pachinko` at
`611a86e`). P `tickets/T06-allium-gate.md` is the nearest procedure and its hand-back
notes record allium 3.6.1's behaviour on a comments-only module; P
`tickets/T05-agent-contract.md` carried the seven Allium skills and
`allium-skill-reference/`. P holds L's `ccdd001` copies of `allium`, `distill`,
`elicit`, `tend`, `weed` and `witness` byte for byte; its `propagate` carries one
pachinko-specific sentence, named in step 3.

The tooling package already installed in `.venv/bin` (B at `v0.3.0`) ships
`bg-install-allium`, which pins allium 3.6.1 by version and SHA-256 into the gitignored
`.tools/bin/`, and `bg-run-allium`, which runs a subcommand over `docs/specs/` and
asserts that every module reports an empty `diagnostics` array and an empty `findings`
array (B `src/biscuit_games_tooling/install_allium.py`, `run_allium.py`). No dependency
changes, so no decision 0005 note.

## Goal

`just check` runs ten gates, the eight of `CONVENTIONS.md` §4 plus `check-specs` and
`analyse-specs`, and is green on a comments-only root module `docs/specs/rovo.allium`
that says plainly it holds no behaviour; `just install-allium`, `just check-specs`,
`just analyse-specs` and `just plan-spec rovo` are each quoted green; two negative
controls show the empty-result green is not a silent pass; `just check-agents` prints
`Validated AGENTS.md, 2 adapters, and 14 skills.`; and the handbook, three decision
records and `AGENTS.md` describe the specification workflow.

## Non-goals

- No behaviour in the module: no entity, rule, surface, invariant or config.
- No dependency change: the installer and the runner are already in B `v0.3.0`.
- No product decision. The module's Excludes say every behaviour waits for a
  specification change.
- No change to the six house skills or their bridges, save `project-check`'s gate
  count and enumeration, eight to ten. No frontmatter changes, so no bridge changes.
- No `floor` CI change: that job has no B and never runs these recipes.
- Pushing and opening the pull request: separately authorised.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `.gitignore` | shared, own lines | `.tools/`, `.allium-loop/`, `!.claude/settings.json` |
| `.claude/settings.json` | new | P's two-line file enabling `allium@juxt-plugins` |
| `docs/specs/rovo.allium` | new | the comments-only root module, step 1 |
| `Justfile` | shared, own lines | `install-allium`, `check-specs`, `analyse-specs`, `plan-spec` |
| `pyproject.toml` | shared, own lines | `check-specs`, `analyse-specs` appended to `recipes` |
| `.pre-commit-config.yaml` | shared, own lines | `allium-skill-reference/` excluded; the two spec hooks |
| `.pre-commit-fix.yaml` | shared, own lines | `allium-skill-reference/` excluded |
| `.editorconfig` | shared, own lines | `[*.allium]` at four spaces, as P |
| `scripts/initialize.sh` | shared, own lines | `just install-allium` after `uv sync --locked` |
| `.github/workflows/ci.yml` | shared, own lines | `just install-allium` before `just check` in `gate` |
| `.agents/skills/<7>/SKILL.md` | new | the seven Allium skills from P, three sentences adapted (step 3) |
| `.agents/skills/spec-change/SKILL.md` | new | adapted from P |
| `.claude/skills/<8>/SKILL.md`, `.codex/skills/<8>/SKILL.md` | new | sixteen bridges, copied from P |
| `allium-skill-reference/` | new | copied from P, verified identical |
| `.gitattributes`, `.markdownlint-cli2.jsonc`, `_typos.toml`, `lychee.toml` | shared, own lines | `allium-skill-reference` vendored and ignored |
| `AGENTS.md` | shared, own lines | step 4 |
| `.agents/skills/project-check/SKILL.md` | shared, own lines | the gate count, eight to ten |
| `docs/decisions/0009-specs-are-the-source-of-truth.md`, `0010-project-managed-allium-cli.md`, `0011-skill-reference-material.md` | new | adapted from P 0002, 0005, 0010 |
| `docs/how-to/work-with-the-specs.md`, `docs/explanation/specifications.md` | new | adapted from P |
| `docs/manifest.yml`, `docs/README.md`, `docs/decisions/README.md` | shared, own lines | the five new pages registered and reachable |
| `docs/project/repository-map.md`, `docs/project/terminology.md`, `docs/reference/commands.md`, `docs/reference/quality-gates.md`, `docs/reference/agent-contract.md`, `docs/reference/configuration.md`, `docs/how-to/develop-locally.md`, `docs/how-to/maintain-dependencies.md`, `docs/operations/troubleshooting.md`, `docs/explanation/security-model.md`, `docs/decisions/0004-hook-runner-and-checkers.md`, `docs/tutorials/first-change.md` | shared, own lines | the gate count, the skill count, the network list, the new paths |
| `README.md`, `CHANGELOG.md` | shared, own lines | one sentence; one `Unreleased` line |
| `docs/operations/maintenance.md` | shared, own lines | the per-release routine installs the binary (found after review 4) |
| `tickets/CONVENTIONS.md` | shared, own lines | §0 source P; §4 and §7 notes that T07 raises the counts |
| `tickets/README.md`, `tickets/T07-allium-gate.md` | ticket | index row, graph, this ticket |

Nothing under `src/` or `tests/` changes. `renovate.json` is read, not changed: its
`biscuit-games-tooling` rule carries no description to update.

## Steps

0. Rename the branch to `ticket/t07-allium-gate`; `just check` baseline on the untouched
   worktree, last line quoted. Write this ticket and the index row.
1. **Gitignore, module, recipes, hooks, init, CI.** `.gitignore` first: `.tools/` (a
   visible binary aborts `check-clean`), `.allium-loop/` (the loop's ledger),
   `!.claude/settings.json` after the `.claude/*` line. The module: `-- allium: 3`, then
   Scope (the product is undefined; this is its root), Includes (nothing yet), Excludes
   (every behaviour until a specification change defines one), Dependencies (none),
   Vocabulary (none; `docs/project/terminology.md` is the glossary), in P
   `docs/specs/pachinko.allium`'s header shape. The `Justfile`: `install-allium` in
   setup, `check-specs`, `analyse-specs` and `plan-spec module` in documents, comments
   adapted from P `Justfile`; `plan-spec` names `.tools/bin/allium` by path. The
   `recipes` list, the two `local` hooks with `files: ^(docs/specs/|pyproject\.toml$)`
   (the B pin lives in `pyproject.toml`), `scripts/initialize.sh`, and the `gate` job.
   Then `just install-allium` (**network, authorised by this ticket**),
   `.tools/bin/allium --version`, `just check-specs`, `just analyse-specs`,
   `just plan-spec rovo`, each quoted with its exit status.
2. **Negative controls**, as P T06 step 4 and its hand-back notes, on a scratch copy
   (`CONVENTIONS.md` §11): append `entity {`, and `just check-specs` must fail naming a
   parse error; append P's `Probe` fixture with no producer for `ready = true`, and
   `just check-specs` must pass while `just analyse-specs` reports `missing_producer`.
   Restore the module; quote both.

   **Adversarial review** (`CONVENTIONS.md` §14) over the gate wiring: the diff and the
   quoted controls. Ask whether the empty-result green could still be a silent pass;
   whether a fresh clone, the CI `gate` job and the `floor` job each behave (`floor` has
   no B and never runs these recipes); whether `check-clean` can see `.tools/`.
3. **Skills and reference.** Copy the seven Allium skills from P. Adapt three sentences
   and nothing else: in `allium`, "`just test` for the tests it produces" becomes
   `just coverage`; in `propagate`, the sentence "This repository's `AGENTS.md` sets
   those conventions: ..." names `tests/` under pytest, `typer.testing.CliRunner` and the
   installed script, `just py-test` as the quick run and `just coverage` as the gate; in
   `witness`, the "Ground truth here follows this repository's `AGENTS.md`" sentence
   says which recipes the skill re-runs and that `just check`, the full gate, still runs
   before a change lands (P's sentence claimed a certified PASS is one the gate would
   give; adversarial review 2 found it overstated, since the skill re-runs the tests
   and the spec checks, not ten gates).
   Adapt `spec-change` from P: module `docs/specs/rovo.allium`; `just py-test` and
   `just coverage` for `just test`. Copy the sixteen bridges from P. Copy
   `allium-skill-reference/` and show `diff -r` against P empty. `just check-agents`.
4. **`AGENTS.md`.** The identity paragraph says behaviour arrives through a specification
   under `docs/specs/`; the project map gains `docs/specs/` and
   `allium-skill-reference/` and says fourteen skills; `just install-allium` joins the
   network recipes; a new block for a module under `docs/specs/`, from P; the
   agent-surface block names `allium-skill-reference/` and decision 0011; Provenance
   drops the "no `docs/specs/`" sentence and keeps the `runes` sentence. The six
   phrases stay in always-visible text. `just check-agents` again.

   **Adversarial review** (`CONVENTIONS.md` §14) over the agent surface: fourteen
   skills; bridges byte-exact; the six phrases outside every block; a vendored skill
   changed beyond the sentences step 3 names; the reference identical to P.
5. **Decisions and handbook.** Decisions 0009 to 0011 adapted from P 0002, 0005 and
   0010, each opening with its provenance; the two new pages from P, the module table
   with one row and the "Diagnostics and waivers" section P's verbatim save the decision
   link; every page in Files touched; the counts (ten gates, fourteen skills, eight
   network recipes) agreeing everywhere. `just check-docs`.

   **Adversarial review** (`CONVENTIONS.md` §14) over the documents: each topic has one
   owning page; the waiver section is P's verbatim apart from the decision link; the gate
   count, skill count and network list agree across `AGENTS.md`, `commands.md`,
   `quality-gates.md`, `agent-contract.md` and `terminology.md`; the decision records'
   reopening conditions are checkable.
6. Hand-back notes, `status: done`, `just check`.

   **Adversarial review** (`CONVENTIONS.md` §14) over the full diff before the commit.
   Rerun `just check` if any fix landed. Commit on the ticket branch.
   **Authorisation required**: pushing and opening the pull request.

## Acceptance criteria

- `.tools/bin/allium --version` prints `allium 3.6.1`; `just check-specs` and
  `just analyse-specs` each print one block with empty `diagnostics` and `findings`;
  `just plan-spec rovo` exits 0; all four quoted.
- Both negative controls are quoted: a parse error fails `check-specs`, and the
  `Probe` fixture passes `check-specs` and fails `analyse-specs` with `missing_producer`.
- `allium-skill-reference/` is identical to P's (`diff -r` prints nothing).
- `just check-agents` prints `Validated AGENTS.md, 2 adapters, and 14 skills.`
- `just check` runs ten gates and is green; `git status --short` is empty.
- The four adversarial reviews ran (`CONVENTIONS.md` §14), and every valid finding is
  fixed or handed back.

## Verification

```sh
.tools/bin/allium --version
just check-specs
just analyse-specs
just plan-spec rovo
diff -r /Users/scutting/projects/pachinko/allium-skill-reference allium-skill-reference
just check-agents
just check-docs
just check
git status --short
```

CI evidence (the `gate` job installing the binary and running ten gates) exists only
after the push, which is separately authorised; it goes in the closing pull request's
notes, as T01, T05 and T06 did.

## Hand-back notes

### Baseline: `12db5fe`

Branch renamed from `spec-rovo` to `ticket/t07-allium-gate` at `12db5fe`; the worktree
was clean and the environment already installed (no `just initialize` needed).

```text
just check
All checks passed and the worktree is unchanged.
exit 0
```

### Installation and placeholder: `12db5fe` with uncommitted changes

```text
just install-allium
downloading https://github.com/juxt/allium-tools/releases/download/v3.6.1/allium-aarch64-apple-darwin.tar.gz
installed allium 3.6.1 at <worktree>/.tools/bin/allium
exit 0

.tools/bin/allium --version
allium 3.6.1 (language versions: 1, 2, 3)
exit 0

just check-specs
{
  "command": "check",
  "diagnostics": [],
  "findings": [],
  "spec_file": "docs/specs/rovo.allium"
}
allium check: 1 specifications, no diagnostics and no findings.
exit 0

just analyse-specs
{
  "command": "analyse",
  "diagnostics": [],
  "findings": [],
  "spec_file": "docs/specs/rovo.allium"
}
allium analyse: 1 specifications, no diagnostics and no findings.
exit 0

just plan-spec rovo
{
  "diagnostics": [],
  "obligations": [],
  "version": 3
}
exit 0
```

`uv run --frozen` re-synced the editable `rovo` install on the first run after the
`pyproject.toml` edit (the `recipes` list); `uv.lock` was untouched and
`just lock-check` passed (exit 0).

### Negative controls: `12db5fe` with uncommitted changes, on a scratch copy

The module was saved to `ai_tmp/scratch/`, edited, run, and copied back; `cmp` against
the saved copy printed nothing after each restore.

Appended `entity {`:

```text
just check-specs
docs/specs/rovo.allium: 1 diagnostic
  docs/specs/rovo.allium:26:8: error: parse error: expected entity name, found '{'
allium check reported 1 diagnostic; the specifications must report none.
error: recipe `check-specs` failed on line 198 with exit code 1
exit 1
```

The JSON held one `error` diagnostic with `"code": null` and empty `findings`.

Appended P T06's `Probe` fixture (an entity whose only transition needs
`probe.ready = true`, which nothing establishes):

```text
just check-specs
allium check: 1 specifications, no diagnostics and no findings.
exit 0

just analyse-specs
docs/specs/rovo.allium: 3 findings
  dead_transition: Transition 'pending' → 'done' on entity 'Probe' is declared but unachievable [Probe]
  deadlock: Entity 'Probe' can reach state 'pending' but has no achievable path to any terminal state [Probe]
  missing_producer: Nothing establishes Probe.ready = true [Probe, rule NeverRuns]
allium analyse reported 3 findings; the specifications must report none.
error: recipe `analyse-specs` failed on line 201 with exit code 1
exit 1
```

The analysis JSON had empty `diagnostics` and exactly those three findings, so the two
gates read different arrays: `check-specs` passes the fixture and `analyse-specs` fails
it. Restored, `just check-specs` printed `allium check: 1 specifications, no diagnostics
and no findings.` (exit 0).

### Skills, reference and `AGENTS.md`: `12db5fe` with uncommitted changes

The eight skills (seven Allium skills and `spec-change`), their sixteen bridges and
`allium-skill-reference/` were copied from P. `diff -r` of the reference against P printed
nothing; `cmp` of each bridge against P's printed nothing. Changed lines against P, per
skill (`diff | grep -c '^[<>]'`): `allium` 2, `propagate` 2, `spec-change` 4 (one, one and
two sentences, each counted as the removed and the added line); `distill`, `elicit`,
`tend`, `weed`, `witness` 0.

```text
just check-agents
Validated AGENTS.md, 2 adapters, and 14 skills.
exit 0
```

After the `AGENTS.md` edit the same line printed again (exit 0), and each of the six
required phrases was confirmed present in the text outside every `<important if>` block.

### Adversarial review 1 (gate wiring): `12db5fe` with uncommitted changes

Harness and model: Codex (`codex-cli 0.165.0`), `codex exec -m gpt-6-astra -s read-only`,
its `-m`, `-s read-only`, `-C` and `-o` flags confirmed with `codex exec --help` on the
day, and `gpt-6-astra` present in the user's Codex configuration; two reviewers in
parallel (conformance, breakage), each run by a subagent; triage by a third subagent;
raw files in `ai_tmp/review/T07-1/`. Both reviewers could run
`just plan-spec rovo` (exit 0) but not the `uv run` recipes, which exited 2 inside the
read-only sandbox on uv's cache lock; their fresh-clone and CI conclusions are source
inspection.

- Conformance: no findings. Checked scope against Files touched, the index and graph,
  the controls, `initialize.sh` and the `gate`/`floor` jobs (`floor` never runs `lint`
  or the spec recipes), `git check-ignore` on `.tools/` and `.allium-loop/`, and that
  both spec hooks fire on the tracked `pyproject.toml` even before the module is staged.
- Breakage B1 (low): `bg-run-allium` demands the `diagnostics` and `findings` keys but
  not that their values are arrays, so a checker regression printing `null` for both
  would read as clean. Triage: **valid**, reproduced by calling B's `_read` and
  `_report` on a synthetic block; allium 3.6.1 emits `[]`, so it is a missing guard, not
  a present false pass. **Handed back** to `steven-cutting/biscuit_games_tooling`
  (`run_allium.py` `_read`: require `isinstance(block[kind], list)`), outside this
  ticket's Files touched. Recorded under Open points.
- No high-severity finding, so no second round. Nothing applied.

### Adversarial review 2 (agent surface): `12db5fe` with uncommitted changes

Same harness and model; raw files in `ai_tmp/review/T07-2/`. The breakage reviewer's
findings body was overwritten by its closing summary (`codex exec -o` writes the last
message to the file the reviewer had itself written to); the summary named the one
finding and triage worked from it and the skill text.

- Conformance C1 (low): `.agents/skills/project-check/SKILL.md` was edited although the
  ticket's Non-goals excluded the house skills; the reviewer saw the edit land mid-review,
  between the executing agent's sweep for stale counts and the ticket amendment.
  Triage: **valid, already applied**: the enumeration now runs to ten, and the ticket's
  Non-goals and Files touched name the file.
- Breakage B1 (medium): `witness`'s sentence "the checks you re-run are the same ones
  `just check` runs ... so a PASS you certify is a PASS that gate would also give"
  overstates: the skill re-runs the tests and the two spec checks, not ten gates. The
  sentence is byte-identical in P and L. Triage: **valid, applied**: the sentence now
  names the recipes the skill re-runs and says `just check` still runs before a change
  lands; `diff` against P shows only that line; `just check-agents` printed
  `Validated AGENTS.md, 2 adapters, and 14 skills.` (exit 0). The ticket's step 3,
  `docs/reference/agent-contract.md` and decision 0011 now name it as the third
  adaptation. Worth raising in P and L, where the same sentence stands.
- Both reviewers confirmed: fourteen skills and fourteen bridges per provider, every
  bridge byte-equal to P's (`cmp`), the reference identical to P (`diff -r`), all 63
  links from the skills into it resolving, `.claude/settings.json` equal to P's, the six
  phrases outside every block, and `AGENTS.md` keeping HEAD's rules.
- No high-severity finding, so no second round.

### Adversarial review 3 (documents): `12db5fe` with uncommitted changes

Same harness and model; raw files in `ai_tmp/review/T07-3/`. Neither reviewer could run
`just check-docs` (exit 2 on uv's cache lock in the read-only sandbox); both inspected
the manifest, the frontmatter and the links by hand. Both confirmed the "Diagnostics and
waivers" section mechanically identical to P's apart from the decision link, 37 pages
with matching frontmatter and unique owners, every page reachable, ten gates, fourteen
skills, eleven records and the eight-recipe network list agreeing on every live page.

- C1 = B2 (low): `docs/reference/agent-contract.md` called the first seven skills "the
  house skills"; `AGENTS.md` groups them as six house skills, `spec-change` and seven
  Allium skills. **Valid, applied**: the table is now introduced as the six house skills
  and `spec-change`.
- C2 = B3 (low): decision 0011 said no repository in the chain carries
  `skills-lock.json` any more; L at `ccdd001` does. **Valid, applied**: the record now
  says L carried it and P and this repository do not.
- C3 (low): `docs/reference/commands.md` said every tool runs through `uv run --frozen`;
  `plan-spec` runs `.tools/bin/allium` by path. **Valid, applied**: the sentence names
  the exception.
- B1 (medium): decision 0010's reopening paragraph said the installer goes on either of
  two events, but upstream checksums would only remove the hand computation, since no
  lockfile here can name a binary. **Valid, applied**: the paragraph now separates the
  two consequences, and only a `uv.lock`-nameable channel supersedes the record.
- After the fixes `just check-docs` printed `Validated 37 pages and 37 canonical
  topics.` (exit 0). No high-severity finding, so no second round.

### Documents: `12db5fe` with uncommitted changes

```text
just check-docs
markdownlint.............................................................Passed
typos....................................................................Passed
lychee...................................................................Passed
bg-validate-docs
Validated 37 pages and 37 canonical topics.
exit 0
```

`just lint` passed every hook, the two new ones (`Specification diagnostics`,
`Specification analysis`) included (exit 0). `renovate.json` was read and not changed:
its `biscuit-games-tooling` rule carries no description, so there was nothing to say
about the allium pin riding the tag; `docs/how-to/maintain-dependencies.md` says it
instead.

### Adversarial review 4 (the full diff): `12db5fe` with uncommitted changes

Same harness and model; raw files in `ai_tmp/review/T07-4/`. Both reviewers reported
no new findings. Conformance checked every changed and new path against Files touched
(every row changed, nothing unlisted), the sixteen bridges, `.claude/settings.json` and
the 23 reference files against P (byte-identical), the waiver section (identical after
the link substitution), the ten-gate order, both hooks' patterns and `pass_filenames`,
the initialization and CI order, the untouched `floor` job, and the existing `dist/`
archives (neither holds `docs/specs/` or `allium-skill-reference/`). Breakage checked
the same wiring, B's handling of diagnostics, findings, missing modules, empty output
and non-zero exits, and the new-file inventory for scratch, binaries or symlinks, and
restated review 1's B1 as the one open hand-back. Neither could run `just check`
(uv's cache lock, read-only sandbox); `just plan-spec rovo` ran (exit 0). Nothing
applied, no second round.

### Final gate: `12db5fe` with uncommitted changes

```text
just check
All checks passed and the worktree is unchanged.
exit 0
```

The run lists ten gates: `lock-check`, `lint`, `py-lint`, `py-typecheck`, `coverage`,
`wheel-smoke`, `check-docs`, `check-agents`, `check-specs`, `analyse-specs`, then
`check-clean`. CI evidence (the `gate` job installing the binary and running the ten
gates on both runners) exists only after the push, which is separately authorised, and
goes in the closing pull request's notes. The rebase onto `origin/main` and the re-run
`tickets/README.md` step 6 asks for happen at the push stop, since `git fetch` reaches
the network.

### After review 4: `6b3c471`, a follow-up commit

A self-check of the pages outside Files touched (`rg -i 'allium|docs/specs|specification'`
over `purpose-and-scope.md`, `install-and-run.md`, `test-and-debug.md`,
`quality-philosophy.md`, `architecture.md`, `testing.md`, `maintenance.md`,
`documentation-contract.md`, `cli.md`, `api.md` and `SECURITY.md`) found no mention, and
one contradiction by omission: `docs/operations/maintenance.md`'s per-release routine
said to move the shared checkers' tag and run `just check`, which is now red at the hook
gate until `just install-allium` installs the binary the new tag pins. The routine now
says so and points at the how-to. Not a review finding, so no further round. At
`6b3c471` with uncommitted changes:

```text
just check-docs
Validated 37 pages and 37 canonical topics.
exit 0

just check
All checks passed and the worktree is unchanged.
exit 0
```

One harness note for the next ticket: `codex exec -o` writes the reviewer's last message
to the file, so a reviewer told to write its findings to that same path has its body
overwritten by its closing summary (review 2, breakage); give `-o` a different name or
tell the reviewer not to write the file.

## Open points

- **Handed back to B** (`steven-cutting/biscuit_games_tooling`, `run_allium.py`):
  `bg-run-allium` requires the `diagnostics` and `findings` keys but not that their
  values are lists, so a future checker printing `null` for both would read as clean
  (review 1, B1). allium 3.6.1 prints `[]`, so nothing passes falsely today. The fix is
  one `isinstance(block[kind], list)` test in `_read`; it arrives here with the next
  tag move.
- **Worth raising in P and L**: the `witness` skill's ground-truth sentence, byte-equal
  in both, claims a certified PASS is one `just check` would give (review 2, B1). This
  repository's copy says what the skill re-runs instead.
- **CI evidence after the push**: the `gate` job on both runners installing the binary
  and running ten gates, in the closing pull request's notes.
