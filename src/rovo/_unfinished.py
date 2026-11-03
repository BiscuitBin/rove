"""A development guard: a specified branch that a later slice implements.

A leaf: it imports no rovo module, so every layer may raise it without breaking the
import direction. Each later slice deletes the raises it implements.
"""


class NotInThisSlice(Exception):  # noqa: N818  The name says what it guards, not that it errs.
    """Raised where the specification has a branch this slice does not implement yet."""

    def __init__(self, rule: str) -> None:
        """Name the specification rule whose branch was reached."""
        super().__init__(f"{rule}: not implemented in this slice")
        self.rule = rule
