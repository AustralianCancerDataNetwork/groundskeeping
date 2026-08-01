from __future__ import annotations

from pathlib import Path


def test_package_has_no_consumer_imports() -> None:
    source_root = Path(__file__).parents[1] / "src" / "groundskeeping"
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source_root.rglob("*.py")
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
    source_root = Path(__file__).parents[1] / "src" / "groundskeeping"
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source_root.rglob("*.py")
    )

    assert "oa_configurator.cli" not in combined
