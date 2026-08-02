from __future__ import annotations

import asyncio
import subprocess
import sys

from groundskeeping.contracts import SourceStatus
from groundskeeping.telemetry import TelemetryRuntime
from groundskeeping.telemetry.providers import FakeTelemetrySource


def test_telemetry_core_does_not_import_textual() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import groundskeeping.telemetry; print('textual' in sys.modules)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"


def test_fake_source_samples_normalized_metrics() -> None:
    async def run() -> None:
        source = FakeTelemetrySource(source_id="demo")
        runtime = TelemetryRuntime((source,))

        availability = await runtime.probe_all()
        snapshots = await runtime.sample_all()

        assert availability["demo"].status is SourceStatus.AVAILABLE
        assert snapshots[0].source_id == "demo"
        assert {metric.key for metric in snapshots[0].metrics} >= {
            "accelerator.utilisation",
            "accelerator.memory.used",
            "workload.throughput",
        }
        assert len(runtime.history("demo")) == 1

    asyncio.run(run())
