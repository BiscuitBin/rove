"""The import direction inside the package, read from the source with `ast`.

`_convert` sits at the bottom, `_mirror` above it, `_crawl` above that and `rovo.cli`
at the top (decision 0012); `rovo/__init__.py` loads none of them and no third-party
module (invariant 1). Every `import`, every `from ... import` and every call to
`importlib.import_module` or `__import__` with a literal name counts.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "rovo"

# The modules the direction is about; the scan must find each of them, so an emptied
# glob cannot pass.
PRIVATE_MODULES = ("rovo._convert", "rovo._mirror", "rovo._crawl", "rovo._config", "rovo._report")

# What `import rovo` must never load: the private modules, the command line and every
# runtime dependency, matched on the first dotted component for the third-party names.
ROOT_FORBIDDEN_MODULES = (*PRIVATE_MODULES, "rovo.cli")
ROOT_FORBIDDEN_TOPS = frozenset({"httpx", "bs4", "lxml", "markdownify", "playwright", "typer"})


def _module_name(path: Path) -> str:
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imported(tree: ast.AST) -> set[str]:
    """Every module name the tree imports, `from a import b` counting as `a` and `a.b`."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            first = node.args[0]
            if called in {"import_module", "__import__"} and isinstance(first, ast.Constant):
                names.add(str(first.value))
    return names


@pytest.fixture(scope="module")
def imports() -> dict[str, set[str]]:
    """Each module under src/rovo, by dotted name, with the names it imports."""
    return {
        _module_name(path): _imported(ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(PACKAGE.rglob("*.py"))
    }


def _within(name: str, module: str) -> bool:
    return name == module or name.startswith(f"{module}.")


def _violations(imports: dict[str, set[str]], layer: str, forbidden: tuple[str, ...]) -> list[str]:
    return sorted(
        f"{module} imports {name}"
        for module, names in imports.items()
        if _within(module, layer)
        for name in names
        if any(_within(name, target) for target in forbidden)
    )


def test_the_scan_finds_every_private_module(imports: dict[str, set[str]]) -> None:
    """The walk reaches the root and each of the five private modules."""
    assert {"rovo", *PRIVATE_MODULES} <= imports.keys()


def test_convert_imports_nothing_above_it(imports: dict[str, set[str]]) -> None:
    """Nothing under `_convert` imports `_mirror`, `_crawl` or the command line."""
    forbidden = ("rovo._mirror", "rovo._crawl", "rovo.cli")
    assert _violations(imports, "rovo._convert", forbidden) == []


def test_mirror_imports_neither_crawl_nor_the_command_line(
    imports: dict[str, set[str]],
) -> None:
    """Nothing under `_mirror` imports `_crawl` or the command line."""
    assert _violations(imports, "rovo._mirror", ("rovo._crawl", "rovo.cli")) == []


def test_crawl_never_imports_the_command_line(imports: dict[str, set[str]]) -> None:
    """Nothing under `_crawl` imports the command line."""
    assert _violations(imports, "rovo._crawl", ("rovo.cli",)) == []


def test_root_imports_no_private_module_and_no_dependency(
    imports: dict[str, set[str]],
) -> None:
    """`rovo/__init__.py` imports no private module, no command line and no dependency."""
    root = imports["rovo"]
    loaded = sorted(
        name
        for name in root
        if any(_within(name, target) for target in ROOT_FORBIDDEN_MODULES)
        or name.partition(".")[0] in ROOT_FORBIDDEN_TOPS
    )
    assert loaded == []
