---
title: "Terminology"
kind: "project"
audience: ["contributor", "maintainer", "operator", "agent"]
canonical_for: ["terminology"]
requires: []
---

# Terminology

These words mean one thing here. Using them loosely is how a review ends up arguing
about vocabulary instead of behaviour. The product has no vocabulary of its own yet;
its first ticket adds its terms to this page.

## The project

| Term | Meaning and preferred usage |
| --- | --- |
| Repository | This source tree, `BiscuitBin/rove`, and its engineering contract; use repository, and `rove`, only for it. |
| Distribution | What an installer installs: `rovo`, named in `pyproject.toml`; use distribution, not package, when the installable unit is meant. |
| Import package | The `rovo` directory under `src/` that `import rovo` loads; use package or import package, not distribution, for Python imports. |
| Public API | Exactly the names `rovo.__all__` lists; use public API, never "anything importable", for the boundary. |
| Console script | The installed `rovo` entry point, `rovo.cli:app`; use command or console script, not package, when invoking it. |
| Placeholder | `rovo.__version__`, `rovo --version` and `rovo version`, which hold the product's place; use placeholder, not feature. |
| Wheel | The built `.whl` installation artefact; use wheel, not sdist or build, for it. |
| Sdist | The source distribution, `rovo-<version>.tar.gz`, which an installer must build; use sdist, not wheel, for it. |

## The workflow

| Term | Meaning and preferred usage |
| --- | --- |
| Recipe | One named `Justfile` command; use recipe, not gate, for one outside `just check`. |
| Gate | One of the eight recipes `just check` runs in order; use gate, not test, for the aggregate policy. |
| Positive control | A deliberately failing input a gate must reject, proving the gate can fire; use positive control, not fixture, when that is its job. |
| Ticket | One file under `tickets/` describing one unit of work and its acceptance evidence. |
| Lane | A ticket running in its own worktree in parallel with others; a lane edits only its ticket's files. |
| Hand-back | A change a lane needs outside its own files, written in its ticket's notes for a later ticket to land, never applied in place. |
| Network recipe | A recipe allowed to reach the network: `initialize`, `sync`, `lock`, `lock-upgrade`, `install-hooks`, `audit`, `check-links-online`. |

The two names differ by one letter: the repository is `rove` and everything
it ships is `rovo` ([decision 0007](../decisions/0007-pypi-name-rovo.md)).

## Related pages

- [Purpose and scope](purpose-and-scope.md)
- [API reference](../reference/api.md)
- [Quality gates](../reference/quality-gates.md)
