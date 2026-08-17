"""Boundary rules that import-linter cannot express.

Most of this file moved to `.importlinter`: no consumer imports, no Textual in the
headless core, oa-configurator confined to the typed adapter, and the layering between
presentation contracts, domain modules, and the Textual shell. Run `uv run lint-imports`
for those.

What remains are rules about *which part* of oa-configurator is imported. Import-linter
squashes external packages to their top level, so every import of `oa_configurator.cli`,
`oa_configurator._private`, and `oa_configurator` itself appears in the graph as the same
edge; a contract cannot tell them apart. Wildcards do not help — import-linter validates
them with "a wildcard can only replace a whole module", so `oa_configurator._*` is
rejected outright. The `.importlinter` contract confines oa-configurator to the adapter
file; these tests constrain what the adapter is allowed to reach for.

`test_telemetry_core.py` also stays hand-rolled: it imports the package in a subprocess
and inspects `sys.modules`, which is the only way to prove a deferred import does not
fire at runtime. Static analysis cannot answer that.
"""

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


def test_no_private_or_cli_oa_configurator_imports() -> None:
    """Only oa-configurator's public, non-CLI surface is a supported dependency."""

    for path in _source_files():
        for name in _oa_imports(path):
            assert name != "oa_configurator.cli", (
                f"{path.name} imports the oa-configurator CLI: {name}"
            )
            assert all(not part.startswith("_") for part in name.split(".")[1:]), (
                f"{path.name} imports a private oa-configurator name: {name}"
            )
