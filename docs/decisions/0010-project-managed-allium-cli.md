---
title: "Decision 0010: A project-managed Allium binary"
kind: "decision"
audience: ["maintainer", "agent"]
canonical_for: ["decision_allium_cli"]
requires: []
---

# Decision 0010: A project-managed Allium binary

Adapted from pachinko's decision 0005 at `611a86e`, itself carried from libpawdoku's
decision 0005 at `ccdd001`.

## Context

The specifications under `docs/specs/` decide every behaviour in this project
([decision 0009](0009-specs-are-the-source-of-truth.md)), so something has to confirm
mechanically that they parse and analyse cleanly, rather than leaving modules that
outrank the code to be read by eye. `allium` is the tool that checks them.

`allium` is a Rust binary published by [`juxt/allium-tools`][upstream]. `uv.lock` cannot
name it, which is the whole difficulty: `just lock-check` proves only what the lock
holds, so the binary's pin needs a proof of its own.

Two packages share the name and are not this tool. On PyPI, `allium-cli` is a client for
the Allium *blockchain data* APIs. On npm, `allium` is a Gherkin parser. Neither has any
relationship to the specification language, and adding either would be a supply-chain
mistake wearing the right name. On crates.io a third stranger, `allium`, is an
onion-routing library; the crate that is this tool is `allium-cli`.

## Decision

Install the prebuilt release binary, pinned by version and by SHA-256, into a gitignored
`.tools/bin/`. The `biscuit-games-tooling` package that `pyproject.toml` pins at a Git tag
([decision 0004](0004-hook-runner-and-checkers.md)) holds the version, the release URL and
the checksum of each supported artefact, and `just install-allium` runs its
`bg-install-allium` through `uv run --frozen`. `just check-specs` and `just analyse-specs`
run the result through `bg-run-allium`. The version that package pins today is 3.6.1.

The pin sits in the installer beside the URL it pins, which is the shape
`.pre-commit-config.yaml` already uses for `lychee`: the version travels with the thing it
describes rather than in a manifest with no second reader. Moving it is therefore a release
of that package, taken here by moving the tag in `pyproject.toml` and relocking; the
package's README carries the checksums and how to recompute them.

`allium-cli` 3.6.1, "CLI for checking Allium specification files", is on crates.io beside
`allium-parser` 3.6.1, so `cargo install allium-cli --locked` is a real alternative. It is
not taken. This repository's toolchain is uv; a Rust toolchain is here only because prek
builds one hook with it, and a source build costs minutes on every cold runner and
verifies nothing about what it built. The house installer, with its recorded version,
URL and checksums, is the only path that proves what was downloaded. It also keeps one
owner per pin: the tooling package holds the version, moved by one tag and shared with
every house repository, and the JSON-reading runner travels with the version it was
verified against.

## Consequences

The binary is not in `uv.lock`, so `just lock-check` cannot speak for it, and `just sync`
does not install it. `just initialize` runs `just install-allium` after `uv sync
--locked`, and the CI `gate` job runs it before `just check`; both are network steps.
The procedure for moving it is in
[Maintain dependencies](../how-to/maintain-dependencies.md).

Checksums have to be produced by hand, because upstream publishes none that cover these
files. The release's own `SHA256SUMS.txt` lists only the editor extension and the language
server, and the Homebrew formula fills in two of the four unix targets and leaves the
`x86_64` entries as empty strings, `x86_64` Linux being exactly what continuous
integration runs on. The four recorded values were computed by downloading each artefact;
the two Homebrew does publish match. Moving the version means recomputing all four, in
the tooling package.

`.tools/` must stay ignored by Git. `just check` snapshots the worktree between recipes, so
a binary Git could see would abort the run before any recipe's exit code was read.

Both recipes are gates: hooks in `.pre-commit-config.yaml` triggered by `docs/specs/`
and by the pin itself (`pyproject.toml`), and gates 9 and 10 of `just check`.

Gating took more than a line in the `Justfile`, because no exit code here carries the
verdict. `allium check` exits non-zero on warnings as well as errors but 0 on an `info`
diagnostic, and `allium analyse` keys its status on findings alone and ignores diagnostics
entirely, so a module that fails to parse passes it with the `error` in the JSON it has
just printed. Neither status means clean, so `bg-run-allium` runs the subcommand,
prints its output whole, and asserts what the contract says: an empty `diagnostics` array
and an empty `findings` array in every module. A diagnostic can be waived with a
whole-line `-- allium-ignore <code>` comment, on the terms in
[Work with the specifications](../how-to/work-with-the-specs.md), and a finding cannot.

The binary is a per-worktree install in a gitignored directory, so a worktree that has not
run `just initialize` fails `just lint` and `just check` until `just install-allium` puts
one there. That is accepted rather than softened: a gate that skips itself when its tool
is missing asserts nothing.

Only the four unix targets are supported. The release also carries a Windows zip; a target
nobody here runs would be a checksum nobody re-verifies.

## What would reopen this

Two events, with different consequences. Upstream publishing checksums that cover the
platform binaries would remove the hand computation and nothing more: no lockfile here
can name a binary, so `install-allium` would still fetch and verify, now against
upstream's figures, and this record would be amended. A distribution channel that
`uv.lock` can name, a PyPI package that is this tool and not the blockchain client, would
let `just sync` install the checker and remove the one network step `install-allium` adds
to a first run and to CI. Only on that second day does the installer go and this record
get superseded.

[upstream]: https://github.com/juxt/allium-tools

## Related pages

- [Work with the specifications](../how-to/work-with-the-specs.md)
- [Maintain dependencies](../how-to/maintain-dependencies.md)
- [Quality gates](../reference/quality-gates.md)
