"""The public API: what `import rovo` provides, and what it never loads."""

import subprocess
import sys

# Runs in a fresh, isolated interpreter, so nothing this test session imported
# can make typer look absent or present.
PROBE = """
import importlib.metadata
import sys

import rovo

assert rovo.__version__ == importlib.metadata.version("rovo"), rovo.__version__
assert "typer" not in sys.modules, "import rovo imported typer"
"""


def test_import_rovo_reads_the_installed_version_without_typer() -> None:
    """`import rovo` exposes the installed version and never imports typer."""
    result = subprocess.run(
        [sys.executable, "-I", "-c", PROBE],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
