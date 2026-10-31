---
title: "Terminology"
kind: "project"
audience: ["contributor", "maintainer", "operator", "agent"]
canonical_for: ["terminology"]
requires: []
---

# Terminology

These words mean one thing here. Using them loosely is how a review ends up arguing
about vocabulary instead of behaviour. The product's words come from its
specification under `docs/specs/`; a term that is not in the table below is not a
term, and the rejected synonyms never appear.

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
| Gate | One of the ten recipes `just check` runs in order; use gate, not test, for the aggregate policy. |
| Positive control | A deliberately failing input a gate must reject, proving the gate can fire; use positive control, not fixture, when that is its job. |
| Ticket | One file under `tickets/` describing one unit of work and its acceptance evidence. |
| Lane | A ticket running in its own worktree in parallel with others; a lane edits only its ticket's files. |
| Hand-back | A change a lane needs outside its own files, written in its ticket's notes for a later ticket to land, never applied in place. |
| Network recipe | A recipe allowed to reach the network: `initialize`, `sync`, `lock`, `lock-upgrade`, `install-hooks`, `install-allium`, `audit`, `check-links-online`. |
| Specification | An `.allium` file under `docs/specs/`. Decides behaviour, and wins wherever the code disagrees ([decision 0009](../decisions/0009-specs-are-the-source-of-truth.md)). Never requirements or design document: a ticket says what to do next, a specification says what the code does. |
| Module | One specification, named by its file without the extension: `rovo` is `docs/specs/rovo.allium`, the root, which imports `crawl`, `mirror` and `convert`. `just plan-spec <module>` takes this name. Where a Python module could be meant, say specification module. |

The two names differ by one letter: the repository is `rove` and everything
it ships is `rovo` ([decision 0007](../decisions/0007-pypi-name-rovo.md)).

## The product

One name per concept; the right-hand column lists the synonyms that never appear.

| Term | Meaning and rejected synonyms |
| --- | --- |
| Mirror | The output directory, its page files, manifest, frontier, indexes and last report. Never knowledge base, local copy or cache. |
| Page, page file | A mirrored page and its `.md` file. Never artefact or output file. |
| Identity | The normalised URL that keys a page and a frontier entry. Canonical URL is reserved for what a page declares about itself; never normalized URL. |
| Source URL | The URL whose response was converted, after redirects. Never final URL. |
| Alias | Any other URL that resolves to a page: a redirect hop or a non-canonical URL. Never redirect record. |
| Removed, removed area | A page gone at the source; `_removed/` holds its archived file unless prune deletes it. Never tombstone, and never gone as a page state. |
| Absent | A URL that answers 404 or 410; a fetch outcome, not a page state. |
| Moved | A page whose identity changed, so its path changed. Never redirected as a page state. |
| Sync run | One `rovo sync` invocation, of kind initial or update; the report says which. Never crawl run or update run. |
| Owner-testing run | A sync run in owner-testing mode on declared hosts. Never stealth run or relaxed run. |
| Tier | A fetch tier: `http`, `browser` or `stealth`. Never render or render tier. |
| Breaker | The per-host circuit breaker. Never antibot. |
| Profile | Platform knowledge as configuration: selectors, tabs, anchors, query parameters, versions, locales. Never site adapter. |
| Fidelity | What the Markdown must carry from the extracted content; the `Fidelity` contract. Never losslessness. |
| Quality score, flags, low confidence | The measured gate share, the named flags, and the boolean the report ranks on. Never confidence score. |
| Uncrawled | A link to an in-scope URL with no page; the page flag is `uncrawled_internal`. Never internal-missing. |
| Candidate | What one settled fetch delivers to the mirror: converted content, an unchanged confirmation, an absent or redirected-out notice. |
| Pass | One finalise, index or verify job over the mirror. |

## Related pages

- [Purpose and scope](purpose-and-scope.md)
- [API reference](../reference/api.md)
- [Quality gates](../reference/quality-gates.md)
