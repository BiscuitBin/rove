---
title: "Documentation map"
kind: "project"
audience: ["user", "contributor", "maintainer", "operator", "agent"]
canonical_for: ["documentation_navigation"]
requires: []
---

# Documentation map

Every page below is registered in `manifest.yml`, owns at least one topic, and is
reachable from here. That is the whole of the arrangement; the rules behind it are in
the documentation contract, listed under Look up.

This repository builds one pure-Python distribution, `rovo`: an importable package,
`rovo`, which is the Python API, and a Typer command of the same name.

## Start here

- [Install and run](how-to/install-and-run.md) — run the command and import the package.
- [Purpose and scope](project/purpose-and-scope.md) — what the repository is for, and what it is not.
- [Repository map](project/repository-map.md) — where everything lives.
- [Terminology](project/terminology.md) — the words this repository uses precisely.
- [Make your first change](tutorials/first-change.md) — one small change, test first, to a green gate.

## How to

- [Develop locally](how-to/develop-locally.md)
- [Test and debug](how-to/test-and-debug.md)
- [Maintain dependencies](how-to/maintain-dependencies.md)

## Understand

- [Architecture](explanation/architecture.md) — the API package, the command line and the boundary between them.
- [Python packaging](explanation/packaging.md) — the wheel, the sdist and the upload guard.
- [Quality philosophy](explanation/quality-philosophy.md) — why each gate exists.
- [Security model](explanation/security-model.md) — untrusted input and the supply chain.

## Look up

- [Commands](reference/commands.md)
- [Command-line reference](reference/cli.md)
- [API reference](reference/api.md)
- [Configuration](reference/configuration.md)
- [Testing](reference/testing.md)
- [Quality gates](reference/quality-gates.md)
- [Documentation contract](reference/documentation-contract.md)
- [Agent contract](reference/agent-contract.md)

## Run it

- [Maintenance](operations/maintenance.md)
- [Troubleshooting](operations/troubleshooting.md)

## Decisions

- [Architecture decisions](decisions/README.md) — the record of what was chosen and why.
