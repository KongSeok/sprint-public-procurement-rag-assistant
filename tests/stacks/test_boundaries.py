from __future__ import annotations

import ast
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
SRC = ROOT / "src" / "midprojectrag"
TESTS = ROOT / "tests"


def _module_context(path: Path, import_root: Path) -> tuple[str, str]:
    relative = path.relative_to(import_root).with_suffix("")
    parts = list(relative.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    module = ".".join(parts)
    package = module if is_package else module.rpartition(".")[0]
    return module, package


def _imports(path: Path, import_root: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    _module, package = _module_context(path, import_root)
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative_name = "." * node.level + (node.module or "")
                imported = importlib.util.resolve_name(relative_name, package)
            elif node.module:
                imported = node.module
            else:
                continue
            result.add(imported)
            if node.module is None or imported.endswith(".stacks"):
                result.update(
                    f"{imported}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
    return result


def _imports_package(imports: set[str], package: str) -> bool:
    return any(name == package or name.startswith(f"{package}.") for name in imports)


class StackBoundaryTests(unittest.TestCase):
    def test_api_and_local_stacks_do_not_import_each_other(self) -> None:
        for path in (SRC / "stacks" / "api").rglob("*.py"):
            self.assertFalse(
                _imports_package(
                    _imports(path, SOURCE_ROOT),
                    "midprojectrag.stacks.local",
                ),
                path,
            )
        for path in (SRC / "stacks" / "local").rglob("*.py"):
            imports = _imports(path, SOURCE_ROOT)
            self.assertFalse(
                _imports_package(imports, "midprojectrag.stacks.api"),
                path,
            )
            self.assertFalse(_imports_package(imports, "openai"), path)
            self.assertFalse(_imports_package(imports, "langfuse"), path)

    def test_core_does_not_import_concrete_stack_packages(self) -> None:
        for directory in (SRC / "answering", SRC / "indexing"):
            for path in directory.rglob("*.py"):
                self.assertFalse(
                    _imports_package(
                        _imports(path, SOURCE_ROOT),
                        "midprojectrag.stacks",
                    ),
                    path,
                )

    def test_cli_composes_stacks_only_through_public_packages(self) -> None:
        imports = _imports(SRC / "cli.py", SOURCE_ROOT)
        concrete = {
            name
            for name in imports
            if name.startswith("midprojectrag.stacks.")
            and name not in {"midprojectrag.stacks.api", "midprojectrag.stacks.local"}
        }
        self.assertEqual(concrete, set())

    def test_api_and_local_test_trees_do_not_cross_import(self) -> None:
        for path in (TESTS / "stacks" / "api").rglob("*.py"):
            imports = _imports(path, ROOT)
            self.assertFalse(
                _imports_package(imports, "midprojectrag.stacks.local")
                or _imports_package(imports, "tests.stacks.local"),
                path,
            )
        for path in (TESTS / "stacks" / "local").rglob("*.py"):
            imports = _imports(path, ROOT)
            self.assertFalse(
                _imports_package(imports, "midprojectrag.stacks.api")
                or _imports_package(imports, "tests.stacks.api"),
                path,
            )
            self.assertFalse(_imports_package(imports, "openai"), path)
            self.assertFalse(_imports_package(imports, "langfuse"), path)

    def test_relative_imports_are_normalized_before_boundary_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            import_root = Path(directory)
            module = import_root / "pkg" / "api" / "module.py"
            module.parent.mkdir(parents=True)
            module.write_text(
                "from ..local import Adapter\nfrom .. import local\n",
                encoding="utf-8",
            )
            self.assertIn("pkg.local", _imports(module, import_root))

            package = import_root / "pkg" / "api" / "__init__.py"
            package.write_text("from .embeddings import Provider\n", encoding="utf-8")
            self.assertIn("pkg.api.embeddings", _imports(package, import_root))

    def test_module_contracts_exist_for_both_stacks(self) -> None:
        for stack in ("api", "local"):
            contract = SRC / "stacks" / stack / "module-contract.md"
            self.assertTrue(contract.is_file(), contract)
            self.assertIn("Must not", contract.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
