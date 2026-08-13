from __future__ import annotations

import ast
from pathlib import Path


def _source_files() -> tuple[Path, ...]:
    source_root = Path(__file__).parents[1] / "src" / "groundskeeping"
    return tuple(source_root.rglob("*.py"))


def _oa_imports(path: Path) -> tuple[str, ...]:
    imported: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported.append(module)
            imported.extend(f"{module}.{alias.name}" for alias in node.names)
    return tuple(name for name in imported if name.startswith("oa_configurator"))


def test_package_has_no_consumer_imports() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _source_files()
    )

    assert "cava_nlp_shard" not in combined
    assert "groundworkers" not in combined
    assert "agent_stack" not in combined


def test_telemetry_core_has_no_textual_imports() -> None:
    telemetry_root = Path(__file__).parents[1] / "src" / "groundskeeping" / "telemetry"
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in telemetry_root.rglob("*.py")
    )

    assert "textual" not in combined


def test_no_private_oa_configurator_cli_imports() -> None:
    for path in _source_files():
        for name in _oa_imports(path):
            assert name != "oa_configurator.cli"
            assert all(not part.startswith("_") for part in name.split(".")[1:])


def test_oa_configurator_imports_are_confined_to_typed_adapter() -> None:
    allowed = Path("configurator/adapter.py")
    package_root = Path(__file__).parents[1] / "src" / "groundskeeping"

    for path in _source_files():
        if _oa_imports(path):
            assert path.relative_to(package_root) == allowed
