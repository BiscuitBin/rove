---
title: "Architecture decisions"
kind: "decision"
audience: ["contributor", "maintainer", "agent"]
canonical_for: ["decision_index"]
requires: []
---

# Architecture decisions

This index is a stub that T04 writes in full. It will say how the series is
numbered, how a record is superseded rather than deleted, and how to write a
new record. Each record below is itself a stub until T04 writes it; record
0008 arrives with the Renovate ticket, which registers it here.

## The record

| Number | Decision |
| --- | --- |
| [0001](0001-uv-and-hatchling.md) | uv and hatchling, with Python 3.13 as the floor and 3.14 for the tools |
| [0002](0002-src-layout-and-public-api.md) | The src layout, the public API boundary and the single version |
| [0003](0003-typer-cli-and-lazy-import.md) | A Typer command line that `import rovo` never loads |
| [0004](0004-hook-runner-and-checkers.md) | Hook runner and checkers |
| [0005](0005-dependency-policy.md) | Dependency policy: compatible ranges for runtime, exact tools, `uv.lock` the pin |
| [0006](0006-licence-deferred.md) | The licence is undecided, and a release waits for it |
| [0007](0007-pypi-name-rovo.md) | The PyPI name `rovo` in the repository `rove` |
