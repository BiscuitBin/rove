"""The public API: what `import rovo` provides, and what it never loads."""

import importlib.metadata
import json
import subprocess
import sys

import pytest

# Runs in a fresh, isolated interpreter (`python -I`), so nothing this test
# session imported can make a module look absent or present. It reports what
# `import rovo` left behind; the tests below judge it.
PROBE = """
import importlib.metadata
import json
import sys

import rovo

print(json.dumps({
    "modules": sorted(sys.modules),
    "all": rovo.__all__,
    "all_type": type(rovo.__all__).__name__,
    "version": rovo.__version__,
    "metadata_version": importlib.metadata.version("rovo"),
}))
"""

# The command line's own stack. Matched on the first dotted component, so a
# submodule such as typer's vendored `typer._click` counts too.
CLI_ONLY = frozenset({"typer", "rich", "click"})


@pytest.fixture(scope="module")
def imported() -> dict[str, object]:
    """What a fresh, isolated `import rovo` reports about itself."""
    result = subprocess.run(
        [sys.executable, "-I", "-c", PROBE],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report: dict[str, object] = json.loads(result.stdout)
    return report


def test_invariant_1_import_rovo_never_imports_the_command_line(
    imported: dict[str, object],
) -> None:
    """Invariant 1: `import rovo` leaves typer, rich and click out of sys.modules."""
    modules = imported["modules"]
    assert isinstance(modules, list)
    loaded = sorted(name for name in modules if str(name).partition(".")[0] in CLI_ONLY)
    assert loaded == []


def test_public_api_is_exactly_the_version(imported: dict[str, object]) -> None:
    """Invariant 2: `rovo.__all__` lists `__version__` and nothing else."""
    assert imported["all"] == ["__version__"]
    assert imported["all_type"] == "list"


def test_version_is_the_installed_distribution_version(imported: dict[str, object]) -> None:
    """Invariant 3: `rovo.__version__` is what the installed metadata says."""
    assert imported["version"] == imported["metadata_version"]
    assert imported["version"] == importlib.metadata.version("rovo")
