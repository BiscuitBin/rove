"""rovo: the Python API. The command line lives in rovo.cli, which this module never imports."""

from importlib.metadata import version as _version

__version__: str = _version("rovo")

__all__ = ["__version__"]
