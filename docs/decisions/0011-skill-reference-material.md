---
title: "Decision 0011: Skill reference material beside the skills"
kind: "decision"
audience: ["maintainer", "agent"]
canonical_for: ["decision_skill_reference"]
requires: []
---

# Decision 0011: Skill reference material beside the skills

Adapted from pachinko's decision 0010 at `611a86e`, itself carried from libpawdoku's
decision 0010 at `ccdd001`.

## Context

The seven Allium skills come from the GitHub repository `juxt/allium`. Each `SKILL.md`
cites reference material of its own: a language reference, patterns, worked examples and
JSON schemas, several files per skill, which upstream ships beside the skill.

The agent contract's checker does not allow that. `validate_agents.py`, from the shared
tooling package ([decision 0004](0004-hook-runner-and-checkers.md)), expects exactly one
`SKILL.md` per skill under `.agents/skills/` and one bridge per provider under `.claude/`
and `.codex/`, counts every path Git lists under those three directories as managed, and
fails on any path it did not expect with `unexpected managed file`. A `references/`
directory beside a `SKILL.md` is a gate failure, however faithful the vendoring.

The repositories this one descends from met the same wall first and moved the reference
material to `allium-skill-reference/` at the repository root. This repository carries
that layout, and the files in it, unchanged from pachinko at `611a86e`, which holds them
unchanged from libpawdoku at `ccdd001`.

The carried record also leaned on a skills lock file, `skills-lock.json`, written by the
skills CLI, to hold the skills to upstream. Its `computedHash` is the CLI's hash of the
whole upstream skill folder, so it cannot be checked against the files vendored here, and
no gate reads it. libpawdoku at `ccdd001` carried it; pachinko does not, and neither does
this repository.

## Decision

The reference material lives at `allium-skill-reference/` at the repository root, one
directory for each skill that ships any: `allium`, `distill` and `elicit`. It is vendored
byte for byte. The skills keep their upstream relative links, rewritten only in depth:
`../../../allium-skill-reference/<skill>/` from `.agents/skills/<skill>/SKILL.md`. The
directory is excluded from markdownlint, lychee, typos and both hook configurations, and
marked `linguist-vendored` in `.gitattributes`, because it is upstream's text and not this
repository's to lint: a finding there is fixed upstream and arrives with the next
vendoring, not as an edit here.

The seven skills themselves are vendored with one adaptation each at most: the sentence
that names this repository's `AGENTS.md` and the `just` recipe that proves the skill's
work, which the checker requires of every skill. In `allium` and `propagate` that sentence
names `just coverage`, the gate, and `just py-test`, the quick run; in `witness` it names
the recipes the skill re-runs and no longer claims that a certified PASS is one the full
gate would give; every other line is upstream's as pachinko holds it.

No `skills-lock.json` is carried. The vendored files are the only record of upstream:
their source is `juxt/allium`, and their version is whatever libpawdoku held at
`ccdd001`. Nothing in this repository describes a lock as a pin or a checksum for the
skills.

## Consequences

A root directory that is not in the house shape and has to be explained on the repository
map. An upstream typo or dead link lands here unflagged, because the checkers that would
catch it are told to look away. Updating the skills from upstream means replacing both a
skill and its reference in one change, or living with a skill that cites a reference from
a different version; with no lock, which upstream version a file came from is known only
from the change that vendored it. The agent contract page carries the rule, so a
contributor adding a skill knows where its material goes.

## What would reopen this

The tooling package's validator tolerating a `references/` subdirectory beside a
`SKILL.md`, which is a change to the agent contract itself; or the Allium plugin shipping
the reference material, so that no repository has to vendor it. On either day the
directory is deleted, the links move, and this record is superseded. Separately, a skills
lock whose hash can be checked against the vendored files and which names a tag or a
commit would raise the question of carrying a lock again, with a gate that reads it; that
is the maintainer's decision, not this record's.

## Related pages

- [Agent contract](../reference/agent-contract.md)
- [Repository map](../project/repository-map.md)
- [Configuration](../reference/configuration.md)
- [Decision 0004: Hook runner and checkers](0004-hook-runner-and-checkers.md)
