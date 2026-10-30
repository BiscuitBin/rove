---
name: review-change
description: Review a change in this repository against its invariants, specifications, tests, and documentation contract.
---

# Review a change

1. Read `AGENTS.md` and the ticket or request the change claims to satisfy. Review the
   whole diff.
2. Check the six invariants in `AGENTS.md` one at a time:
   - `import rovo` loads no CLI-only module: `rovo.cli` imports the API, never the
     reverse, and `scripts/wheel_smoke.py api` still proves it on a wheel installed
     without dependencies.
   - The public API is exactly `__all__` in `src/rovo/__init__.py`; a new public name
     without an `__all__` entry, or an `__all__` entry starting with `_`, is a finding,
     and `src/rovo/py.typed` still ships.
   - The version is written once, in `pyproject.toml`; a literal version anywhere else
     is a finding.
   - ruff `select = ["ALL"]` and mypy strict stand; every `# noqa` and
     `# type: ignore` names its rule and a reason, and every per-file ignore in
     `ruff.toml` carries a comment.
   - Coverage of `src/rovo/**` stays at or above the `Justfile`'s floor, reached by
     tests, never by lowering the floor.
   - `uv.lock` is the pin: runtime dependencies are compatible ranges with a tested
     lower bound, tools are exact, and a new dependency carries the decision-0005 note.
3. Check behaviour against its source: behaviour beyond the placeholders that no ticket
   or decision record under `docs/decisions/` asks for is invented product, and a finding.
4. Check evidence: a test that failed before the change and passes after it; an API
   change tested in `tests/test_api.py` or a sibling module; a command-line change tested
   through `typer.testing.CliRunner`, and a new entry point through the installed script.
   A test that only asserts a function was called is insufficient.
5. Check documentation ownership: an API change moves `docs/reference/api.md`, a
   command-line change `docs/reference/cli.md`, and either moves the `Unreleased` section
   of `CHANGELOG.md`. Add durable facts to the page owning their topic in
   `docs/manifest.yml`.
6. Check scope: unrelated refactors, new dependencies and speculative abstractions are
   findings in themselves.
7. Report findings by severity with `file:line`, what breaks and the smallest fix.
   Run `just check` before concluding, and quote the commit it ran at.
