---
title: "Configuration"
kind: "reference"
audience: ["contributor", "maintainer", "operator", "agent"]
canonical_for: ["configuration_reference"]
requires: []
---

# Configuration

Every configuration file at the repository root, what it decides, and which ticket owns
it. The owners are those of the target tree in `tickets/CONVENTIONS.md` §3; a file
marked frozen is changed by no parallel lane, only by a follow-up on `main`.

## `pyproject.toml`

The project manifest, owned by T00 and frozen while the wave-1 lanes run.

| Table | What it sets |
| --- | --- |
| `[build-system]` | hatchling, pinned exactly, as the build backend. |
| `[project]` | Name `rovo`, the static `version`, `readme = "README.md"`, `requires-python = ">=3.13"`, the classifiers (including the upload guard), and the runtime dependency `typer>=0.27.3,<0.28`. No `license` field ([decision 0006](../decisions/0006-licence-deferred.md)). |
| `[project.scripts]` | The console script `rovo = "rovo.cli:app"`. |
| `[project.urls]` | `Repository`, the GitHub repository `BiscuitBin/rove`. |
| `[dependency-groups]` | `dev`: coverage, mypy, prek, pytest and ruff, each pinned exactly. `tooling`: the shared checkers. |
| `[tool.uv]` | `default-groups = ["dev", "tooling"]`, so `uv sync` installs both. |
| `[tool.uv.dependency-groups]` | `tooling = { requires-python = ">=3.14" }`, the group's own floor ([decision 0001](../decisions/0001-uv-and-hatchling.md)). |
| `[tool.uv.sources]` | The shared checkers from their Git repository at tag `v0.3.0`. |
| `[tool.hatch.build.targets.wheel]` | `packages = ["src/rovo"]`. |
| `[tool.hatch.build.targets.sdist]` | `only-include`: `src/rovo`, `tests`, `README.md`, `CHANGELOG.md`. |
| `[tool.biscuit-games-tooling]` | `recipes`, the eight gates `just check` runs in order, and `predicates = {}`. |

`uv.lock` is generated from it by `uv lock`, committed, never hand-edited, and frozen with
it. `.python-version` holds `3.14`, the tooling interpreter.

## The Python gate settings

Owned by T02. pyproject.toml carries none of these tables, so each tool reads exactly
one file.

| File | What it sets |
| --- | --- |
| `ruff.toml` | `target-version = "py313"`, `line-length = 99`, `src = ["src", "tests"]`, the fixtures excluded from discovery; `select = ["ALL"]` with `COM812`, `ISC001` and `CPY001` ignored, each with its reason; Google docstrings; relative imports banned; per-file ignores for `tests/**` and `scripts/**`, each commented. |
| `mypy.ini` | `strict = True` over `src`, `tests` and `scripts`, `python_version = 3.13`, the fixtures excluded, `warn_unused_ignores` and `warn_unused_configs`. |
| `pytest.ini` | `testpaths = tests`, strict configuration and markers, `xfail_strict`, warnings as errors. |
| `.coveragerc` | `branch`, `source_pkgs = rovo`, `parallel`; the report's `show_missing` and excluded lines. The floor is the `Justfile`'s `coverage_floor`, never here. |

## Hooks and text checks

Owned by T02.

| File | What it sets |
| --- | --- |
| `.pre-commit-config.yaml` | The read-only hook gate `just lint` runs and the installed hook uses: file hygiene, EditorConfig, markdownlint, typos, lychee (offline, and `lychee-online` on the manual stage), shellcheck, actionlint, ripsecrets, `py-lint`, `py-typecheck` and both contract validators. Remote hooks are pinned to commit SHAs. |
| `.pre-commit-fix.yaml` | The mutating hooks `just fix` runs, including ruff's formatter and fixer; it skips the positive-control fixtures. |
| `.editorconfig` | UTF-8, LF line endings, final newlines, and indentation: two spaces, four for Python and the `Justfile`. |
| `.markdownlint-cli2.jsonc` | markdownlint's rules: no line-length limit, `<important>` and `<br>` allowed for `AGENTS.md`, and `target`, `.venv` and `ai_tmp` ignored. |
| `_typos.toml` | The only typos configuration: the excluded paths (`uv.lock` among them) and the accepted words, each commented. |
| `lychee.toml` | The link checker's cache, retries, timeout, accepted status codes and excluded paths. |

## The rest

| File | Owner | What it sets |
| --- | --- | --- |
| `Justfile` | T00, frozen in wave 1 | Every recipe, and `coverage_floor := "90"`. |
| `.gitignore` | T00, frozen | Scratch, build output, the environment and every generated file, so the gate's snapshot never sees them. |
| `.gitattributes` | T00, frozen | `* text=auto eol=lf`: LF line endings for every text file. |
| `.github/` | T01 | The CI workflow and the setup action that installs uv, just, the environment and the hook environments. |
| `docs/manifest.yml` | T00, frozen in wave 1 | The registry the [documentation contract](documentation-contract.md) checks. |

There are no environment variables to configure. uv honours its own (`UV_PYTHON`,
`UV_NO_GROUP`, `UV_PROJECT_ENVIRONMENT`), which the
[3.13 run](../how-to/develop-locally.md#the-313-run) uses.

## Related pages

- [Commands](commands.md)
- [Quality gates](quality-gates.md)
- [Repository map](../project/repository-map.md)
