"""Smoke-test the installed rovo wheel from outside the worktree.

`api` runs after the wheel alone is installed, with no dependency: it proves
that `import rovo` works and never tries to import a module outside the
standard library, and that the wheel installed exactly the package and the
metadata it should.
`cli` runs after the locked runtime closure is installed: it proves that
`python -m rovo --version` works and that the console script beside the
interpreter prints the same line.
"""

import importlib.abc
import importlib.metadata
import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

# Every file the wheel may install outside its .dist-info/: the package, no tests, no fixtures.
PACKAGE_FILES = frozenset({"rovo/__init__.py", "rovo/__main__.py", "rovo/cli.py", "rovo/py.typed"})
# The one console script the installer generates and records, relative to site-packages.
CONSOLE_SCRIPT = "../../../bin/rovo"


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
    try:
        import rovo  # noqa: PLC0415  The import is the test: it must run after the recorder.
    except ImportError as error:
        return _fail(f"import rovo failed ({error}); it tried {sorted(set(recorder.seen))}")
    finally:
        sys.meta_path.remove(recorder)
    if recorder.seen:
        return _fail(f"import rovo tried to import {sorted(set(recorder.seen))}")
    if importlib.util.find_spec("typer") is not None:
        return _fail("typer is importable; the first install step must have no dependency")
    expected = importlib.metadata.version("rovo")
    if rovo.__version__ != expected:
        return _fail(f"rovo.__version__ is {rovo.__version__!r}, metadata says {expected!r}")
    reason = _contents(expected) or _metadata()
    if reason is not None:
        return _fail(reason)
    print(
        f"wheel_smoke api: rovo {rovo.__version__}, no CLI module imported,"
        " exactly the four package files and the expected metadata"
    )
    return 0


def _contents(version: str) -> str | None:
    """Return why the installed file list is wrong, or None."""
    recorded = {file.as_posix() for file in importlib.metadata.files("rovo") or []}
    if CONSOLE_SCRIPT not in recorded:
        return f"the console script {CONSOLE_SCRIPT} is not recorded: {sorted(recorded)}"
    dist_info = f"rovo-{version}.dist-info/"
    installed = {path for path in recorded if not path.startswith(dist_info)} - {CONSOLE_SCRIPT}
    if "rovo/py.typed" not in installed:
        return "rovo/py.typed is not among the installed files"
    if installed != PACKAGE_FILES:
        extra = sorted(installed - PACKAGE_FILES)
        missing = sorted(PACKAGE_FILES - installed)
        return f"the installed files differ: unexpected {extra}, missing {missing}"
    return None


def _metadata() -> str | None:
    """Return why the installed metadata is wrong, or None."""
    metadata = importlib.metadata.metadata("rovo")
    if metadata["Requires-Python"] != ">=3.13":
        return f"Requires-Python is {metadata['Requires-Python']!r}, not '>=3.13'"
    if "Private :: Do Not Upload" not in (metadata.get_all("Classifier") or []):
        return "the upload guard classifier 'Private :: Do Not Upload' is missing"
    licence = [key for key in ("License", "License-Expression", "License-File") if key in metadata]
    if licence:
        return f"the licence is undecided, yet the metadata has {licence}"
    entry_points = sorted(
        (point.group, point.name, point.value)
        for point in importlib.metadata.distribution("rovo").entry_points
    )
    if entry_points != [("console_scripts", "rovo", "rovo.cli:app")]:
        return f"the entry points are {entry_points}, not exactly rovo = rovo.cli:app"
    return None


def _run_version(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*command, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )


def _cli() -> int:
    expected = f"rovo {importlib.metadata.version('rovo')}"
    module = _run_version([sys.executable, "-I", "-m", "rovo"])
    if module.returncode != 0:
        return _fail(f"python -m rovo --version exited {module.returncode}: {module.stderr}")
    if module.stdout.strip() != expected:
        return _fail(f"python -m rovo --version printed {module.stdout!r}, not {expected!r}")
    script = Path(sys.executable).with_name("rovo")
    if not script.is_file():
        return _fail(f"no console script beside the interpreter, at {script}")
    installed = _run_version([str(script)])
    if installed.returncode != 0:
        return _fail(f"{script} --version exited {installed.returncode}: {installed.stderr}")
    if installed.stdout != module.stdout:
        return _fail(
            f"rovo --version printed {installed.stdout!r}, python -m rovo {module.stdout!r}"
        )
    print(f"wheel_smoke cli: {expected}, from python -m rovo and the console script alike")
    return 0


def main(argv: Sequence[str]) -> int:
    """Run the named smoke step and return its exit status."""
    steps = {"api": _api, "cli": _cli}
    if len(argv) != 1 or argv[0] not in steps:
        return _fail("usage: wheel_smoke.py api|cli")
    return steps[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
