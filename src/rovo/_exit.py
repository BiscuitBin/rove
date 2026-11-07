"""The exit codes a command ends with (rovo.allium CommandExited): a leaf.

It imports no rovo module, so a command that never crawls (`rovo index`) can return an
exit code without loading rovo._crawl through rovo._report, which re-exports it.
"""

import enum


class ExitCode(enum.Enum):
    """Severity rises in declaration order; the process exits with `number`."""

    ok = "ok"
    partial = "partial"
    usage = "usage"
    blocked = "blocked"
    quality = "quality"

    @property
    def number(self) -> int:
        """The process exit status: ok 0, partial 1, usage 2, blocked 3, quality 4."""
        return list(ExitCode).index(self)
