---
title: "Work with the specifications"
kind: "how-to"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["specification_workflow"]
requires: []
---

# Work with the specifications

The Allium specifications under `docs/specs/` decide what rovo does. Today the sole
module, the root, declares no behaviour: the product is undefined, and the placeholder
API and command stand outside it. This page is the procedure;
[Specifications](../explanation/specifications.md) is the reasoning.

## Find the module that owns the behaviour

| Module | Owns |
| --- | --- |
| `rovo.allium` | The root. Nothing yet: its Scope says the product is undefined, its Includes say nothing, and its Excludes say every behaviour, until a specification change defines one. It imports nothing. |

Each module opens with Scope, Includes and Excludes. Read the whole module before
editing it. A behaviour listed under its Excludes belongs outside that module;
find or define its owner before proceeding.

## Change behaviour

1. Change the specification first: state the rule, its triggers, guards and outcomes.
2. Check every module that imports it. Changes to shared entities and triggers can
   change what dependent modules require.
3. Derive tests from the changed clauses and confirm they fail before implementing.
   A test already green may be covered already or may prove nothing.
4. Implement until the tests pass without weakening them.
5. Run `just check-specs`, then `just analyse-specs`. Fix diagnostics and findings
   at their root; the narrow waiver terms below apply only to checker errors.
6. Run `just py-test` while iterating, then `just coverage`, then `just check`.

Run `just plan-spec <module>` for an initial list of test obligations as raw JSON.
It plans that module alone and does not read imports; plan each imported module
separately. Treat the output as suggestions, outside the gate: an obligation for
excluded storage or unobservable behaviour can be struck with a reason, but a
clause the planner misses is still owed a test.

## Add a module

Use the `spec-change` skill to define the behaviour before implementing it, then
`propagate` to derive its tests. The first behaviour goes into the root: replace its
Scope, Includes and Excludes with what the product is, and its Vocabulary with the
product's words. A behaviour that outgrows the root's Scope goes in a module under
`docs/specs/` with `-- allium: 3` and Scope, Includes, Excludes, Dependencies and
Vocabulary comments. Import it from the root using `use "./<module>.allium" as
<alias>`, replacing both placeholders with its actual name and alias. Update the
root's header and this page's module table to reflect its new responsibility.

Record domain terms in [Terminology](../project/terminology.md). Run both spec
gates and plan the new module, then follow the test and implementation loop above.
`just plan-spec rovo` lists no obligations today, because the root states nothing;
the first specification change gives it some, and the same change derives their
tests with `propagate` and brings them with it.

## Handle an open question

An `open question` block records a product decision nobody has made yet. The root
carries none today, because it states nothing to be uncertain about; the first
specification change will raise some, and none is permission to invent an answer in
code.

- If your change depends on an unanswered decision, raise it rather than answer in code.
- If a new gap appears, add an `open question` rather than guess.
- When a decision is made, state it in the specification and remove its question
  in the same commit.

## Tooling

The project owns a pinned, checksummed Allium 3.6.1 binary in the gitignored
`.tools/bin/`. `just initialize` installs it; `just install-allium` installs it
separately or after a version change. Both reach the network and require task
authorization. See [decision 0010](../decisions/0010-project-managed-allium-cli.md).

`just check-specs` checks syntax and references across the modules.
`just analyse-specs` repeats those diagnostics and adds process findings, including
reachability, deadlocks, conflicts and invariants. Reachability there means that some
rule produces the state or field a guard needs, not that the guard's condition can hold:
contradictory guards, such as two numeric bounds that cannot both be true, pass, so a
green `just analyse-specs` is not proof that every guard is satisfiable. Read the rule
and its tests for that. Use these recipes so the project's pin and report checks apply.

The following section is carried verbatim from pachinko at `611a86e`, which carries it
verbatim from libpawdoku at `ccdd001`, save that its decision link names this
repository's decision 0010 in place of pachinko's 0005. Its historical module examples
describe libpawdoku; this repository has only the root module listed above, and it
carries no waiver.

### Diagnostics and waivers

Both recipes are part of `just check`, and both run as hooks in the read-only gate, so a
commit that touches `docs/specs/` is held to them. That is what
[decision 0010](../decisions/0010-project-managed-allium-cli.md) records, and it means a
worktree needs `just install-allium` before `just lint` or `just check` will pass. Both are
clean on an untouched checkout: every module reports an empty `diagnostics` array and an
empty `findings` array, and both recipes print one JSON block per module and exit 0.

Neither recipe takes the exit code as its verdict, because neither exit code carries what
this project means by clean. `allium check` exits 0 on an `info` diagnostic — `allium.field.unused` is
one, so the waiver the modules used to carry for it was never what kept the recipe green —
and `allium analyse` keys its status on findings alone, so a module that does not parse
passes it with the `error` sitting in the JSON it has just printed.
`bg-run-allium` reads the arrays instead, and treats a non-zero status beside an
empty report as a fault in the tool, never as a pass.

Either recipe reporting anything at all is therefore a regression in the change under
review. Fix it at the root. A finding cannot be waived. A diagnostic can, but only when the
diagnostic itself is wrong — the construct is valid Allium that the pinned checker cannot
resolve — and then it is waived in place:

```text
-- Why the checker is wrong here, in a sentence.
-- allium-ignore allium.reference.unknownName
```

The directive is a whole-line comment holding the full diagnostic code and nothing else —
prose on the directive line disables it, which is why the reason sits on its own line
above — and it covers only the line directly beneath it. One rule, one line, one stated
reason. Upstream documents none of this: the directive was found in the binary and
re-verified against 3.6.1, so every waiver must be re-verified whenever the pinned version
moves — see [Maintain dependencies](maintain-dependencies.md). No waiver is currently in
the modules.

Where a shape can be retired rather than waived, that is the better route. A `related:`
clause that names a surface through a module alias is one the checker cannot resolve, and
the language reference cannot be read to sanction it either: rule 31 asks only that a
surface in `related:` be defined, and no example anywhere qualifies a surface name with an
alias. Where a waiver would assert that the checker is wrong, the honest form is prose —
state the adjacency in the guarantees of the surfaces concerned — and no waiver is written.

`allium.field.unused` counts uses within one module only, so a definition whose only
readers sit in another module is reported, although the language has always allowed a
module to read another's fields. It also does not count a use inside a projection's
`where` predicate, so a derived value read only as `moves where is_next_to_redo` is
reported as unused; `board.allium` answers that with an invariant that states a true
property of the value, which is the better route than a waiver. A waiver for it is
legitimate on these terms, but read the definition twice before writing one: the
diagnostic can be wrong about the language and still right that the declaring module has
something true to say about the field, such as the property its readers exist to
maintain. Waive only what the reference plainly permits, and only when there is nothing
truthful to say instead.

Two more gaps are handled without a waiver at all. The checker sees a `.created(...)` call
only when it stands alone as an ensures statement, at 3.6.1 exactly as at 3.5.3: bind the
creation — `let entity = Entity.created(...)`, or assign it straight into a field — and
both the status it sets and every field it establishes vanish from the checker's status
scan and from the analyser's producer search, so create unbound and let a `.created` rule
pick the entity up. And 3.6.1 resolves `alias/config.field` without checking the name behind
the dot, so a mistyped cross-module config reference draws nothing and is read by eye; a
local one is reported as `allium.config.undefinedReference` from a derived value, a rule or
a module-level invariant, but not from inside an entity-level `invariant` block, which is
read by eye too.

## Related pages

- [Specifications](../explanation/specifications.md)
- [Quality gates](../reference/quality-gates.md)
- [Decision 0009: Specifications decide behaviour](../decisions/0009-specs-are-the-source-of-truth.md)
