"""The import direction inside the package, read from the source with `ast`.

`_convert` sits at the bottom, `_mirror` above it, `_crawl` above that, `_config` and
`_report` above the crawl, `_commands` above them and `rovo.cli` at the top (decisions
0012 and 0013); the leaf `_unfinished` imports no rovo module, so every layer may raise
it. `rovo/__init__.py` loads none of them and no third-party module (invariant 1), and
`rovo.cli` imports a private module only inside a command's body, so `rovo --version`
loads no runtime dependency. Every `import`, every `from ... import` (a relative one
resolved against the importing module) and every call to `importlib.import_module` or
`__import__` with a literal name counts; a relative `import_module` name is resolved
against its literal package argument, else the importing module's package. "Module
level" means every statement that runs on import: inside `if`, `try`, `with`, loops and
class bodies, but not a function's or lambda's body, nor an `if TYPE_CHECKING:` body.
"""

import ast
import importlib.util
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "rovo"

# The modules the direction is about; the scan must find each of them, so an emptied
# glob cannot pass.
PRIVATE_MODULES = (
    "rovo._convert",
    "rovo._mirror",
    "rovo._crawl",
    "rovo._config",
    "rovo._report",
    "rovo._commands",
    "rovo._unfinished",
)

# What `import rovo` must never load: the private modules, the command line and every
# runtime dependency, matched on the first dotted component for the third-party names.
ROOT_FORBIDDEN_MODULES = (*PRIVATE_MODULES, "rovo.cli")
ROOT_FORBIDDEN_TOPS = frozenset({"httpx", "bs4", "lxml", "markdownify", "playwright", "typer"})


def _module_name(path: Path) -> str:
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imported(tree: ast.AST, module: str = "", *, is_package: bool = False) -> set[str]:
    """Every module name the tree imports, `from a import b` counting as `a` and `a.b`.

    A relative import is resolved against `module`, the importing module's dotted name;
    `from . import x` counts as `<package>.x`.
    """
    return _names(ast.walk(tree), module, is_package=is_package)


def _names(nodes: Iterable[ast.AST], module: str, *, is_package: bool) -> set[str]:
    """The module names the nodes import, resolved as `_imported` says."""
    package = module if is_package else module.rpartition(".")[0]
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = importlib.util.resolve_name("." * node.level + base, package).rstrip(".")
            if node.module is not None:
                names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call) and (name := _called_import(node, package)) is not None:
            names.add(name)
    return names


def _called_import(call: ast.Call, package: str) -> str | None:
    """The literal name an `import_module` or `__import__` call loads, resolved, else None."""
    func = call.func
    called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if called not in {"import_module", "__import__"} or not call.args:
        return None
    first = call.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return None
    name = first.value
    if called != "import_module" or not name.startswith("."):
        return name
    anchors = [*call.args[1:2], *(k.value for k in call.keywords if k.arg == "package")]
    anchor = next(
        (a.value for a in anchors if isinstance(a, ast.Constant) and isinstance(a.value, str)),
        package,
    )
    return importlib.util.resolve_name(name, anchor)


def _type_checking_only(node: ast.AST) -> bool:
    """An `if TYPE_CHECKING:` (or `typing.TYPE_CHECKING`) statement."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _import_time_nodes(tree: ast.AST) -> Iterator[ast.AST]:
    """The nodes that run when the module is imported.

    A function's or lambda's body runs only when called, so only its decorators and
    defaults are kept; an `if TYPE_CHECKING:` body never runs, so only its `else` is.
    """
    stack: list[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            decorators = [] if isinstance(node, ast.Lambda) else node.decorator_list
            defaults = [*node.args.defaults, *(d for d in node.args.kw_defaults if d)]
            stack.extend([*decorators, *defaults])
        elif _type_checking_only(node):
            stack.extend(node.orelse)  # type: ignore[attr-defined]  # An ast.If, as just tested.
        else:
            stack.extend(ast.iter_child_nodes(node))


def _module_level_imports(
    tree: ast.Module, module: str = "", *, is_package: bool = False
) -> set[str]:
    """The names the module imports when it is imported, not inside a function body."""
    return _names(_import_time_nodes(tree), module, is_package=is_package)


@pytest.fixture(scope="module")
def imports() -> dict[str, set[str]]:
    """Each module under src/rovo, by dotted name, with the names it imports."""
    return {
        _module_name(path): _imported(
            ast.parse(path.read_text(encoding="utf-8")),
            _module_name(path),
            is_package=path.name == "__init__.py",
        )
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
    """The walk reaches the root and each of the seven private modules."""
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


def test_the_lower_layers_import_neither_config_nor_report_nor_commands(
    imports: dict[str, set[str]],
) -> None:
    """Nothing under `_convert`, `_mirror` or `_crawl` imports a layer above the crawl."""
    above = ("rovo._config", "rovo._report", "rovo._commands")
    for layer in ("rovo._convert", "rovo._mirror", "rovo._crawl"):
        assert _violations(imports, layer, above) == []


def test_config_and_report_import_neither_commands_nor_the_command_line(
    imports: dict[str, set[str]],
) -> None:
    """`_config` and `_report` import neither `_commands` nor the command line."""
    for layer in ("rovo._config", "rovo._report"):
        assert _violations(imports, layer, ("rovo._commands", "rovo.cli")) == []


def test_commands_never_import_the_command_line(imports: dict[str, set[str]]) -> None:
    """`_commands` imports the layers below it, never the command line."""
    assert _violations(imports, "rovo._commands", ("rovo.cli",)) == []


def test_unfinished_is_a_leaf(imports: dict[str, set[str]]) -> None:
    """`_unfinished` imports no rovo module, so every layer may raise its exception."""
    assert sorted(name for name in imports["rovo._unfinished"] if _within(name, "rovo")) == []


def test_convert_imports_no_http_client(imports: dict[str, set[str]]) -> None:
    """Conversion is pure: nothing under `_convert` imports httpx."""
    assert _violations(imports, "rovo._convert", ("httpx",)) == []


def test_the_command_line_imports_private_modules_only_inside_commands() -> None:
    """No module-level statement of `cli.py` imports a private module or a dependency."""
    tree = ast.parse((PACKAGE / "cli.py").read_text(encoding="utf-8"))
    loaded = sorted(
        name
        for name in _module_level_imports(tree, "rovo.cli")
        if any(_within(name, target) for target in PRIVATE_MODULES)
        or name.partition(".")[0] in ROOT_FORBIDDEN_TOPS - {"typer"}
    )
    assert loaded == []


def test_relative_imports_are_resolved() -> None:
    """`from .._crawl import X` inside `rovo._mirror.finalise` counts as `rovo._crawl`."""
    tree = ast.parse("from .._crawl import X\nfrom . import model\n")
    names = _imported(tree, "rovo._mirror.finalise")
    assert {"rovo._crawl", "rovo._crawl.X", "rovo._mirror.model"} <= names
    assert _imported(ast.parse("from . import fidelity\n"), "rovo._convert", is_package=True) == {
        "rovo._convert.fidelity"
    }


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("if True:\n    from rovo import _commands\n", id="inside-if"),
        pytest.param("try:\n    import rovo._commands\nexcept ImportError:\n    pass\n", id="try"),
        pytest.param("with x:\n    from ._commands import sync\n", id="relative-in-with"),
        pytest.param("class C:\n    from rovo import _commands\n", id="class-body"),
        pytest.param("x = importlib.import_module('._commands')\n", id="relative-import-module"),
        pytest.param(
            "if TYPE_CHECKING:\n    pass\nelse:\n    import rovo._commands\n",
            id="type-checking-else",
        ),
    ],
)
def test_module_level_imports_reach_into_compound_statements(source: str) -> None:
    """Positive control: an import that runs on import, in any statement, is seen."""
    assert "rovo._commands" in _module_level_imports(ast.parse(source), "rovo.cli")


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("def f():\n    from rovo import _commands\n", id="function-body"),
        pytest.param("f = lambda: __import__('rovo._commands')\n", id="lambda-body"),
        pytest.param("if TYPE_CHECKING:\n    from rovo import _commands\n", id="type-checking"),
        pytest.param(
            "import typing\nif typing.TYPE_CHECKING:\n    import rovo._commands\n",
            id="typing-type-checking",
        ),
    ],
)
def test_module_level_imports_skip_code_that_does_not_run_on_import(source: str) -> None:
    """A function's body and an `if TYPE_CHECKING:` body do not run on import."""
    assert "rovo._commands" not in _module_level_imports(ast.parse(source), "rovo.cli")


def test_relative_import_module_names_are_resolved() -> None:
    """A relative `import_module` name resolves against its literal package, else the module's."""
    with_package = "import_module('.._commands', 'rovo._convert')\n"
    keyword = "importlib.import_module('.._commands', package='rovo._convert')\n"
    implicit = "import_module('.._commands')\n"
    for source in (with_package, keyword, implicit):
        assert "rovo._commands" in _imported(ast.parse(source), "rovo._convert.fidelity")
