---
title: "Agent contract"
kind: "reference"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["agent_contract"]
requires: []
---

# Agent contract

Enforced by `bg-validate-agents`, a console script of the `biscuit-games-tooling`
package, run by `just check-agents` and by a pre-commit hook. `AGENTS.md` is the single
source of truth for how an agent works in this repository; everything else in the agent
surface exists only so that a particular tool can find it.

## The four surfaces

| Path | Role |
| --- | --- |
| `AGENTS.md` | Canonical. Read natively by Codex, and by anything following the convention. |
| `CLAUDE.md` | A pointer, byte-pinned to `@AGENTS.md` and nothing else. |
| `.github/copilot-instructions.md` | A pointer, byte-pinned to one paragraph. |
| `.agents/skills/` | Canonical task procedures, mirrored by thin bridges under `.claude/skills/` and `.codex/skills/`. |

A `CODEX.md` at the repository root is forbidden: Codex reads `AGENTS.md` directly, and a
second file would be a second source of truth.

## What `AGENTS.md` must contain

- At least 300 words.
- Six phrases, each naming an invariant that is expensive to rediscover: `untrusted`,
  `just check`, `explicit authorization`, `ai_tmp/`, `docs/specs/` and `runes`.

The phrase list is a crude check and is meant to be. It does not verify that the guidance
is good; it verifies that the six topics were not dropped in an edit. Two of the phrases
have nothing to govern here: this repository has no `docs/specs/` directory, because it
has no Allium specifications, and does not use Svelte, whose `runes` the sixth phrase
names. `AGENTS.md` says so in one honest sentence each, in its Provenance section,
outside every `<important if>` block, until the shared package makes the list
configurable.

## The skills and the blocks that route to them

This repository carries six canonical skills with twelve bridges. Their triggers are
their `description` lines:

| Skill | Trigger |
| --- | --- |
| `plan-change` | Plan a change when scope, risks or validation need evidence before code is written. |
| `review-change` | Review a change against its invariants, tests and documentation contract. |
| `python-change` | Implement or review a change to the package, its command line or its tests, with lint, type, coverage and wheel-smoke evidence. |
| `fix-quality` | Diagnose and repair a failing gate at its root instead of suppressing the finding. |
| `project-check` | Bring a workspace to a state where the full gate runs, and interpret what it reports. |
| `review-docs` | Add or revise a handbook page so it satisfies the documentation contract and stays reachable. |

`AGENTS.md` routes each kind of task to its skill through one `<important if="...">`
block per task:

| Block (`if=`) | Skill | Recipes it names |
| --- | --- | --- |
| changing Python under `src/` or `tests/` | `python-change` | `py-lint`, `py-typecheck`, `coverage`, `wheel-smoke`, `py-test` |
| changing the command line | `python-change` | `coverage`, `wheel-smoke` |
| adding or moving a dependency | `plan-change` | `lock`, `lock-check`, `wheel-smoke` |
| adding or changing a page under `docs/` | `review-docs` | `check-docs` |
| changing `AGENTS.md`, an adapter, a skill or a bridge | none | `check-agents` |
| a failing gate, or handing work back | `fix-quality`, then `project-check` | `format`, `fix`, `lint` |

The always-visible text routes the remaining two: `plan-change` to plan a change or pick
up a ticket, and `review-change` to review one.

## What a skill must be

Frontmatter of exactly two keys, `name` and `description`, adjacent:

```markdown
---
name: python-change
description: Implement or review a change to the rovo package, its command line or its tests with the lint, type, coverage and wheel-smoke evidence the invariants require.
---
```

- `name` equals the directory name.
- `description` is at least eight words and states a real trigger.
- The body cites `AGENTS.md` and names at least one `just` recipe. A procedure that ends
  without saying how to verify it is not a procedure.

The frontmatter parser is deliberately literal: it splits every line between the `---`
markers on the first colon, so a blank line inside the block fails with
`invalid frontmatter line`, and a key that appears twice is an error rather than an
overwrite.

## What a bridge must be

Each of `.claude/skills/<name>/SKILL.md` and `.codex/skills/<name>/SKILL.md` carries the
canonical frontmatter verbatim, then exactly this sentence and nothing else:

```markdown
Follow `../../../.agents/skills/<name>/SKILL.md`. That file is canonical and this bridge adds nothing to it.
```

A bridge that grows content fails, however short it is: a clause smuggled into a bridge
is read as guidance and becomes a second source of truth for the skill it points at.

## The inventory

The validator lists managed files from Git, honouring this repository's `.gitignore`,
and compares that against what it expects. Every expected file must exist; no
unexpected file may exist under `.agents/`, `.claude/` or `.codex/`, except a
`.claude/settings.json`, which is tolerated and absent here; and managed files must be
regular files, never symlinks. Local assistant state stays out of the inventory by being
listed in `.gitignore`.

On this tree `just check-agents` prints
`Validated AGENTS.md, 2 adapters, and 6 skills.`

## Related pages

- [Documentation contract](documentation-contract.md)
- [Quality gates](quality-gates.md)
- [Decision 0004: Hook runner and checkers](../decisions/0004-hook-runner-and-checkers.md)
