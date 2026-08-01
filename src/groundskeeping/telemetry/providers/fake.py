"""Fake telemetry source used by tests and the demo app."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from groundskeeping.contracts.views import SemanticStatus
from groundskeeping.telemetry.models import (
    MetricValue,
    SourceAvailability,
    SourceStatus,
    TelemetrySnapshot,
)


@dataclass
class FakeTelemetrySource:
    source_id: str = "fake"
    capabilities: frozenset[str] = frozenset(
        {
            "accelerator.utilisation",
            "accelerator.memory.used",
            "accelerator.memory.total",
            "workload.throughput",
        }
    )
    utilisation: float = 72.0
    memory_used_mb: int = 8192
    memory_total_mb: int = 16384
    throughput: float = 128.0

    async def probe(self) -> SourceAvailability:
        return SourceAvailability(
            source_id=self.source_id,
            status=SourceStatus.AVAILABLE,
            capabilities=self.capabilities,
            message="Fake source is available.",
        )

    async def sample(self) -> TelemetrySnapshot:
        return TelemetrySnapshot(
            source_id=self.source_id,
            sampled_at=datetime.now(UTC),
            capabilities=self.capabilities,
            metrics=(
                MetricValue(
                    key="accelerator.utilisation",
                    label="Accelerator",
                    value=self.utilisation,
                    unit="%",
                    status=SemanticStatus.OK,
                    source_id=self.source_id,
                ),
                MetricValue(
                    key="accelerator.memory.used",
                    label="Memory used",
                    value=self.memory_used_mb,
                    unit="MiB",
                    status=SemanticStatus.INFO,
                    source_id=self.source_id,
                ),
                MetricValue(
                    key="accelerator.memory.total",
                    label="Memory total",
                    value=self.memory_total_mb,
                    unit="MiB",
                    status=SemanticStatus.INFO,
                    source_id=self.source_id,
                ),
                MetricValue(
                    key="workload.throughput",
                    label="Throughput",
                    value=self.throughput,
                    unit="items/s",
                    status=SemanticStatus.RUNNING,
                    source_id=self.source_id,
                ),
            ),
        )
