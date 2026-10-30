"""Smoke-test the installed rovo wheel from outside the worktree.

`api` runs after the wheel alone is installed, with no dependency: it proves
that `import rovo` works and never tries to import a module outside the
standard library.
`cli` runs after the locked runtime closure is installed: it proves that
`python -m rovo --version` works.
"""

import importlib.abc
import importlib.metadata
import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from types import ModuleType


class _Recorder(importlib.abc.MetaPathFinder):
    """Records every attempt to import a module outside the standard library, and finds nothing."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> None:
        del path, target
        top = fullname.partition(".")[0]
        if top != "rovo" and top not in sys.stdlib_module_names:
            self.seen.append(fullname)


def _fail(reason: str) -> int:
    print(f"wheel_smoke: {reason}", file=sys.stderr)
    return 1


def _api() -> int:
    recorder = _Recorder()
    sys.meta_path.insert(0, recorder)
    import rovo  # noqa: PLC0415  The import is the test: it must run after the recorder.

    sys.meta_path.remove(recorder)
    if recorder.seen:
        return _fail(f"import rovo tried to import {sorted(set(recorder.seen))}")
    if importlib.util.find_spec("typer") is not None:
        return _fail("typer is importable; the first install step must have no dependency")
    expected = importlib.metadata.version("rovo")
    if rovo.__version__ != expected:
        return _fail(f"rovo.__version__ is {rovo.__version__!r}, metadata says {expected!r}")
    files = importlib.metadata.files("rovo") or []
    if not any(file.name == "py.typed" and file.parent.name == "rovo" for file in files):
        return _fail("rovo/py.typed is not among the installed files")
    print(f"wheel_smoke api: rovo {rovo.__version__}, no CLI module imported, py.typed shipped")
    return 0


def _cli() -> int:
    expected = f"rovo {importlib.metadata.version('rovo')}"
    result = subprocess.run(
        [sys.executable, "-I", "-m", "rovo", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return _fail(f"python -m rovo --version exited {result.returncode}: {result.stderr}")
    if result.stdout.strip() != expected:
        return _fail(f"python -m rovo --version printed {result.stdout!r}, not {expected!r}")
    print(f"wheel_smoke cli: {expected}")
    return 0


def main(argv: Sequence[str]) -> int:
    """Run the named smoke step and return its exit status."""
    steps = {"api": _api, "cli": _cli}
    if len(argv) != 1 or argv[0] not in steps:
        return _fail("usage: wheel_smoke.py api|cli")
    return steps[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
