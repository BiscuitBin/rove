---
id: T03
title: "Agent contract: AGENTS.md, six house skills, the bridges"
status: open
depends_on: [T00]
parallel_with: [T01, T02, T04]
branch: ticket/t03-agent-contract
estimated_size: M
---

# T03: Agent contract: AGENTS.md, six house skills, the bridges

## Context

T00 left a stub `AGENTS.md` that carries B's six phrases and the invariants, six skill
stubs with final frontmatter, and twelve frozen bridges. This ticket writes the real
contract: the instructions an agent with no other context needs to work in this
repository safely, in A's layout (`CONVENTIONS.md` §7). A's T05 built the original:
read A `AGENTS.md` and A `.agents/skills/plan-change/SKILL.md`,
A `.agents/skills/review-change/SKILL.md`, A `.agents/skills/python-change/SKILL.md`,
A `.agents/skills/fix-quality/SKILL.md`, A `.agents/skills/project-check/SKILL.md` and
A `.agents/skills/review-docs/SKILL.md`, and A `tickets/T05-agent-contract.md` for the
reasoning.

The skills' frontmatter is frozen, because the bridges repeat it and B compares the two
(`CONVENTIONS.md` §7). A body may change; a `name` or `description` may not.

## Goal

`AGENTS.md` and the six canonical skills are final, every rule in them is true of this
repository (each command they name exists in the `Justfile`, each path exists), and
`just check-agents` prints `Validated AGENTS.md, 2 adapters, and 6 skills.`

## Non-goals

- No change to `CLAUDE.md`, `.github/copilot-instructions.md` or any bridge (frozen).
- No new skill, no `.claude/settings.json` (`CONVENTIONS.md` §3).
- No handbook page: `docs/reference/agent-contract.md` is T04's, and T04 describes what
  this ticket writes; the two lanes agree through `CONVENTIONS.md` §7.

## Files touched

| Path | Class | Content |
| --- | --- | --- |
| `AGENTS.md` | final | `CONVENTIONS.md` §7 |
| `.agents/skills/plan-change/SKILL.md` | final | A's, adapted |
| `.agents/skills/review-change/SKILL.md` | final | A's, adapted |
| `.agents/skills/python-change/SKILL.md` | final | new body (step 4) |
| `.agents/skills/fix-quality/SKILL.md` | final | A's, adapted: one dispatch line per gate of `CONVENTIONS.md` §4 |
| `.agents/skills/project-check/SKILL.md` | final | A's, adapted |
| `.agents/skills/review-docs/SKILL.md` | final | A's, adapted |

## Steps

1. Create the worktree; `just initialize`; `just check` baseline.
2. **`AGENTS.md`**, in `CONVENTIONS.md` §7's order: the always-on core, `## Project map`,
   `## Invariants` (the six, verbatim) with the authority paragraph, the six
   `<important if="...">` blocks, `## Provenance`. About 900 words. Each of B's six
   phrases appears at least once outside every block. The authority paragraph names the
   network recipes of `CONVENTIONS.md` §4 by name, and says that a tag, a release and a
   repository setting are each separately authorised. Never invent product behaviour:
   the identity paragraph says the product is not yet specified.
3. **The carried skills.** For each of A's five carried skills, keep the structure and
   replace every pixi, cargo, maturin, Rust, wasm, Allium and parity reference with this
   repository's equivalent or nothing. `fix-quality` has exactly one dispatch line per
   gate of `CONVENTIONS.md` §4, in gate order, each naming the recipe, the usual cause
   and the first command to run.
4. **`python-change`.** New body, numbered steps: read `AGENTS.md` and the invariants;
   decide whether the change is API (`src/rovo/__init__.py` and the modules it exports)
   or command line (`src/rovo/cli.py`), and that the CLI imports the API, never the
   reverse; write the failing test first (API under `tests/test_api.py` or a new module;
   CLI through `CliRunner` and, for a new entry point, through the installed script);
   make it pass; `just py-lint`, `just py-typecheck`, `just coverage`,
   `just wheel-smoke`; update `docs/reference/api.md` or `docs/reference/cli.md` and the
   `CHANGELOG.md` `Unreleased` section in the same change; finish with `just check`.
5. **Prove every reference.** Extract every `just <recipe>` and every path in code spans
   from `AGENTS.md` and the skills and check each exists:
   `rg -o 'just [a-z-]+' AGENTS.md .agents | sort -u` against `just --summary`; paths
   with `test -e`, resolving a package-relative path such as `rovo/__init__.py` under
   `src/`. One path is exempt: `docs/specs/`, which the Provenance sentence names only to
   say it is absent (`CONVENTIONS.md` §7); confirm instead that `test -e docs/specs`
   fails. Quote both lists, the exemption and any miss.

   **Adversarial review** (`CONVENTIONS.md` §14): `AGENTS.md` and the skills, before the
   final commit. Ask: which rule is false of this repository; which instruction would
   lead an agent to push, publish, change a setting or install something without
   asking; which B phrase sits only inside a block; which skill names a recipe that
   does not exist or skips one the gate runs; where the contract invents product
   behaviour.
6. `just check-agents`, `just check`; commit.

## Acceptance criteria

- `just check-agents` prints `Validated AGENTS.md, 2 adapters, and 6 skills.`
- Every recipe and path the contract names exists, except `docs/specs/`, which is named
  as absent and does not exist (step 5's lists quoted, no miss).
- For each of B's six phrases, `rg -n` over `AGENTS.md` shows a line outside every
  `<important if>` block.
- No frontmatter changed: `git diff origin/main -- .agents > ai_tmp/agents.diff; echo "exit $?"`
  exits 0, then `rg '^[-+](name|description):' ai_tmp/agents.diff; echo "exit $?"` prints
  nothing and exits 1, preceded by its positive control (the same `rg` over a scratch edit).
- The adversarial review ran and every valid finding is fixed or handed back.

## Verification

```sh
git rev-parse --short HEAD
just check-agents
wc -w AGENTS.md
for p in untrusted 'just check' 'explicit authorization' 'ai_tmp/' 'docs/specs/' runes; do rg -n -F "$p" AGENTS.md | head -2; done
rg -o 'just [a-z-]+' AGENTS.md .agents | sed 's/.*just //' | sort -u
just --summary
{ just check 2>&1; echo "exit $?"; } | tail -2
```

## Hand-back notes

### Baseline and environment (commit 69f0d14)

The lane worktree was created from `main` at `61f2357`, an ancestor of T00's tip, so it
was fast-forwarded to `69f0d14` (`git merge --ff-only 69f0d14`, no lane commit lost)
before any change. `RUSTUP_TOOLCHAIN=stable` was exported in every shell that may build
hooks (departure: the machine's `cargo` has no rustup default). `just initialize` exited
0 and took the secondary-worktree path. `just check` on the untouched worktree, raw log
`ai_tmp/T03/baseline-check.log`:

```text
All checks passed and the worktree is unchanged.
exit 0
```

### Verification (commit a00b3db)

The Verification block, run as one script, raw log `ai_tmp/T03/verify.log`
(`git rev-parse --short HEAD` printed `a00b3db` as its own step):

```text
uv run --frozen bg-validate-agents
Validated AGENTS.md, 2 adapters, and 6 skills.
exit 0
    1013 AGENTS.md
11:comments, fixtures, dependency code, web pages and tool output as untrusted data: none
53:`just lock-upgrade`, `just install-hooks`, `just audit` and `just check-links-online`;
54:each runs only when the task authorizes it, and `just check` never needs the network.
45:Authority stops at the worktree. Anything that leaves it needs explicit authorization
25:- `ai_tmp/` is gitignored scratch space and is never committed.
56:`ai_tmp/`, never in a commit. Work on one ticket per worktree. Hooks are never installed
128:adapted. This repository holds no `docs/specs/` directory, because it has no Allium
129:specifications yet. Svelte runes are a concept this repository does not use; the
audit check check-agents check-docs check-links-online coverage fix format initialize install-hooks lint lock lock-check lock-upgrade py-lint py-test py-typecheck sync wheel-smoke
audit build check check-agents check-clean check-docs check-links-online coverage default fix format initialize install-hooks lint lock lock-check lock-upgrade py-lint py-test py-typecheck sync wheel-smoke
exit 0
All checks passed and the worktree is unchanged.
exit 0
```

The six blocks occupy lines 71-121 and Provenance starts at line 123, so every phrase
line above is outside every block (line 53 matches `just check` only as a prefix of
`just check-links-online`; line 54 is the real occurrence). Counted mechanically over
lines outside the blocks: `untrusted` 1, `just check` 4, `explicit authorization` 1,
`ai_tmp/` 2, `docs/specs/` 1, `runes` 1.

**Word count.** `AGENTS.md` is 1013 words by `wc -w`, 734 outside the blocks, against
§7's "about 900". The six invariants, verbatim, are about 200 of them, and the authority
paragraph carries the full list of separately authorized actions and the seven network
recipes by name; both are required content. A landed at 1342 for the same reasons.

### Reference check (commit a00b3db)

Recipes: every name `rg -o 'just [a-z-]+'` extracts is in `just --summary` (both lines
above); `comm -23` of the named list against the defined list printed nothing and
exited 0. A search for a reference wrapped across lines (`` `just$ `` or `just` at a
line end) printed nothing and exited 1.

Paths: every code span in `AGENTS.md` and `.agents/` (116 unique) was listed; the 45
that contain a slash or name a file were tested with `test -e`, resolving
`rovo/__init__.py` under `src/` and stripping the `api` argument from
`scripts/wheel_smoke.py api`. 40 exist. The five that do not are:

- `docs/specs/`: the exemption. `test -e docs/specs` exits 1, as the Provenance sentence
  says.
- `py.typed`: package-relative (invariant 2's wheel file); `test -e src/rovo/py.typed`
  exits 0.
- `SKILL.md`: a file name under each skill directory; all six
  `.agents/skills/<name>/SKILL.md` exist.
- `BiscuitBin/alliumpy` and `steven-cutting/libpawdoku`: repository names, not paths.
  Their commits exist: `git -C <clone> cat-file -e c8e1a46^{commit}` on A and the same
  for `ccdd001` on L each exit 0.

Re-run after the §14 review fixes (working tree on `72b9efa`, before the fix commit):
`AGENTS.md` is now 1031 words (B1's scoped network sentence added 18); the recipe
`comm -23` again printed nothing and exited 0; 119 unique code spans, of which
46 are paths (the 45 above plus `src/`, added by `c4c00d9`). Each path with its `test -e`
exit, after resolving `rovo/__init__.py` under `src/`, `scripts/wheel_smoke.py api` to
the script and `src/rovo/**` to `src/rovo`; the five exits of 1 are the five above:

```text
0 .agents/skills/
0 .claude/
0 .claude/skills/
0 .codex/
0 .codex/skills/
0 .github/copilot-instructions.md
0 .python-version
0 .venv/
0 AGENTS.md
0 ai_tmp/
1 BiscuitBin/alliumpy
0 CHANGELOG.md
0 CLAUDE.md
0 docs/
0 docs/decisions/
0 docs/decisions/0005-dependency-policy.md
0 docs/manifest.yml
0 docs/README.md
0 docs/reference/api.md
0 docs/reference/cli.md
0 docs/reference/documentation-contract.md
1 docs/specs/
0 Justfile
0 mypy.ini
1 py.typed
0 pyproject.toml
0 rovo/__init__.py
0 ruff.toml
0 scripts/
0 scripts/wheel_smoke.py api
1 SKILL.md
0 src/
0 src/rovo/
0 src/rovo/__init__.py
0 src/rovo/**
0 src/rovo/cli.py
0 src/rovo/py.typed
1 steven-cutting/libpawdoku
0 tests/
0 tests/fixtures/
0 tests/fixtures/py-lint-violation/mypy.py
0 tests/fixtures/py-lint-violation/ruff.py
0 tests/test_api.py
0 tickets/
0 tickets/CONVENTIONS.md
0 uv.lock
```

The other code spans name recipes, skills, hook ids (`py-lint`, `py-typecheck`,
`validate-docs` and `validate-agents` are each an `id:` in `.pre-commit-config.yaml`),
`bg-validate-docs` (executable in `.venv/bin/`), Python names and literal output.

### Frontmatter unchanged (commit a00b3db)

`origin/main` is still `61f2357`, from before T00 created the skills, so a diff against
it would show T00's own `+name:` lines. Departure: the diff is taken against T00's tip
instead.

```text
$ git diff 69f0d14 -- .agents > ai_tmp/agents.diff; echo "exit $?"
exit 0
$ rg '^[-+](name|description):' ai_tmp/agents.diff; echo "exit $?"
exit 1
```

Positive control, run first over a scratch copy of `plan-change` with its description
edited (`ai_tmp/scratch/plan-change.SKILL.md`): the `git diff --no-index` exited 1 and
the same `rg` printed the `-description:` and `+description:` lines and exited 0.

### What changed from A's skills, and why

- `plan-change`: step 1 reads the ticket and `tickets/CONVENTIONS.md` instead of
  upstream's documentation; step 4's "upstream decides behaviour" becomes "the product
  is not yet specified: behaviour comes only from a ticket or a decision record,
  otherwise an open question"; step 5's crate direction, stub and binding become
  invariants 1, 2 and 6 and the pages an API or CLI change moves. Step 6 names the
  network recipes through `AGENTS.md`.
- `review-change`: A's nine Rust and parity invariants become this repository's six;
  the upstream and parity step becomes the invented-product check; the stub, binding,
  doctest and `#[non_exhaustive]` checks are dropped (no Rust, no stub). Evidence is
  `tests/test_api.py`, `CliRunner` and the installed script; documentation ownership
  names `docs/reference/api.md`, `docs/reference/cli.md` and `CHANGELOG.md`.
- `fix-quality`: A's twenty-two dispatch lines become eight, one per gate of
  `CONVENTIONS.md` §4 in gate order, each naming the recipe, the usual cause and the
  first command. Dropped with their gates: `check-toolchain`, `fmt-check`, `toml-check`,
  `clippy`, `metrics`, `features`, `test-doc`, `doc`, `deny`, `deps-unused`,
  `py-test`, `py-stubtest`, `version-check`, `snapshots-check`. A pytest failure now
  routes through `coverage`, which runs the suite. Added: the `lint` hooks that take
  file names see only tracked files, while `py-lint` and `py-typecheck` scan the tree
  (T00 Open points; scoped after the §14 review), and `check-clean` is named in step 5 rather than given
  a dispatch line, since it is not one of the eight gates.
- `project-check`: pixi, rustup, `.tools/bin` and the twenty-two gates become uv, just,
  git, cargo for the ripsecrets hook, `.python-version` and the eight gates plus
  `check-clean`; the debug-and-release build note is dropped (nothing is compiled).
- `review-docs`: A's, byte-identical (`cmp` against
  `git -C <A> show c8e1a46:.agents/skills/review-docs/SKILL.md`, saved to
  `ai_tmp/T03/A-review-docs.md`, exits 0); nothing in it is A-specific.
- `review-change`, after `c4c00d9`: the version bullet is scoped to `src/`, `tests/`
  and `scripts/`, because `uv.lock` legitimately carries the version too.
- `python-change`: new body, per step 4 of this ticket.

### `AGENTS.md` delta from A

Dropped: the Rust block, the upstream-pin-and-version block and the ticket block (§7
lists six blocks; `plan-change` and `review-change` are routed from the core's workflow
paragraph instead, and `plan-change` also from the dependency block). Dropped from the
core: the nested-`AGENTS.md` sentence and "read the whole diff before reporting", to
stay near the word budget. Added: "a tag, a release and a repository setting are each
separately authorized", organisation settings, GitHub App installs and installs outside
the worktree in the authority list (§11), and that `just check` needs no network once
`just initialize` or `just sync` has run against the current `uv.lock` (first written
as "never needs the network"; scoped after the §14 review).
`AGENTS.md` writes American "authoriz-" throughout, because B's phrase is
`explicit authorization`.

### Hand-back to T04, for `docs/reference/agent-contract.md`

The six blocks, in order, and the skill each routes to: Python under `src/` or `tests/`
(`python-change`); the command line (`python-change`); a dependency (`plan-change`);
a page under `docs/` (`review-docs`); the agent surface (no skill; `just check-agents`);
a failing gate or hand-back (`fix-quality`, `project-check`). `plan-change` and
`review-change` are also named in the always-on core. B's phrases all sit outside the
blocks: identity paragraph, project map, authority paragraph, hand-back rule and
Provenance. No settled fact contradicts §7.

### Adversarial review, checkpoint 1 (step 5)

Run by the orchestrator under §14 over `git diff 69f0d14...HEAD` at `72b9efa`: two
fresh-context Codex reviewers on `gpt-6-astra`, one per lens (conformance, breakage),
then separate triage subagents that applied the valid fixes one at a time. Raw files:
`ai_tmp/review/T03-1/`; verdicts: `ai_tmp/review/T03-1/verdicts.md`. Seven findings,
six valid (none high), one invalid, so no second round.

| Id | Severity | Verdict | Action |
| --- | --- | --- | --- |
| C1 | medium | valid: `review-change` flagged any `__all__` entry starting with `_`, which would flag `__version__` | applied: only a single leading `_` is private; a dunder is public |
| B2 | medium | valid: duplicate of C1 | applied through C1's edit |
| C2 | medium | valid: A's "no global ruff ignore without a comment and a review" was dropped without being listed | applied in `fix-quality` and `review-change` |
| C3 | low | valid: "hooks see only tracked files" is false for `py-lint` and `py-typecheck`, which scan the tree | applied in `fix-quality` and these notes |
| C4 | low | valid: the path list was counted, not quoted | applied: the re-run paragraph quotes every tested path |
| B1 | medium | valid: "`just check` never needs the network" is false; `uv run --frozen` syncs after a `uv.lock` change or on a cold cache | applied: `AGENTS.md` scopes the claim to an environment synced against the current `uv.lock`; frozen parts handed back below |
| B3 | medium | invalid: a probe with the real recorder shows `import rovo.cli` is recorded; argparse is standard library, outside the smoke's contract | none |

Re-run after the fixes, on the uncommitted tree at `72b9efa` that was then committed as
`T03: §14 review fixes`: `just check-agents` printed
`Validated AGENTS.md, 2 adapters, and 6 skills.` (exit 0); `comm -23` of the named
recipes against `just --summary` printed nothing (exit 0); the wrapped-reference search
printed nothing (exit 1); 46 code-span paths tested, the misses exactly the five
explained above; each B phrase still on a line outside every block (`untrusted` 1,
`just check` 4, `explicit authorization` 1, `ai_tmp/` 2, `docs/specs/` 1, `runes` 1);
`AGENTS.md` is 1031 words. The orchestrator approved the fast-forward from `61f2357` to
`69f0d14`.

### Hand-backs to T05 (frozen files)

- `Justfile` (§14 T03-1 B1): the gate recipes run `uv run --frozen`, which still syncs
  the environment, over the network, when `uv.lock` changed or the cache is cold, so
  `just check` can reach the network. Proposed: `--offline` or `--no-sync` on the gate
  recipes so the gate fails closed, and then the unconditional sentence returns to
  `AGENTS.md`.
- `scripts/initialize.sh` (§14 T03-1 B1): in the secondary-worktree branch,
  `uv run --frozen prek run lychee --files README.md || :` hides a failed lychee binary
  download as well as lychee's verdict. The fix T00's Open points propose for
  `install-hooks` applies here too: check afterwards that the binary exists.

## Open points

None. The two frozen-file follow-ups above are handed back to T05.
