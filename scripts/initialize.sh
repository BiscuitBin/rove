#!/bin/sh
set -eu

project_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$project_root"

git rev-parse --is-inside-work-tree >/dev/null

# The environment first: install-hooks needs its prek and `bg-*` scripts.
# `--locked` refuses a lockfile that disagrees with `pyproject.toml`, so a stale
# lock is fixed by `just lock` and committed, never rewritten silently by a
# first run.
uv sync --locked

# Hooks are installed only from the primary checkout. Every worktree of this
# repository shares one .git/hooks directory, and `prek install` writes a shim
# naming an absolute path into whichever worktree ran it — so a hook installed
# from a secondary worktree runs that worktree's .venv/bin/prek for commits
# made anywhere, and keeps doing so after the worktree is deleted, at which
# point every commit fails on a `prek` that is not on PATH. The comparison is
# the test git itself uses: in a secondary worktree the common directory and
# the git directory differ. The recipe also provisions every hook environment,
# so this is the last line of the first-run path that reaches the network.
# A secondary worktree skips only the shim: it still prepares both hook
# configurations and runs lychee once, as install-hooks does, because lychee
# downloads its binary at first run, not at prepare. Without this, the first
# `just lint` in a fresh worktree would reach the network. lychee's exit
# status is lint's business, not this script's.
if [ "$(git rev-parse --git-common-dir)" = "$(git rev-parse --git-dir)" ]; then
    just install-hooks
else
    printf '%s\n' 'Secondary worktree: skipping install-hooks.' >&2
    printf '%s\n' 'Run just install-hooks once from the primary checkout.' >&2
    uv run --frozen prek prepare-hooks
    uv run --frozen prek prepare-hooks --config .pre-commit-fix.yaml
    uv run --frozen prek run lychee --files README.md || :
fi

printf '\n%s\n' 'Ready. Next: just check.'
printf '%s\n' 'Nothing has been formatted, staged, committed, tagged, or pushed.'
