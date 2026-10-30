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

To be written by the executing agent: the word count, the reference check, what was
dropped from each A skill and why, the review record, and anything handed back to T04
for `docs/reference/agent-contract.md`.

## Open points

None at writing.
