"""Normalized telemetry models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from groundskeeping.contracts.views import SemanticStatus


class SourceStatus(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SourceAvailability:
    source_id: str
    status: SourceStatus
    capabilities: frozenset[str] = frozenset()
    message: str | None = None

    @property
    def available(self) -> bool:
        return self.status is SourceStatus.AVAILABLE


@dataclass(frozen=True)
class MetricValue:
    key: str
    label: str
    value: float | int | str | None
    unit: str | None
    status: SemanticStatus
    source_id: str
    scope: str | None = None


@dataclass(frozen=True)
class TelemetrySnapshot:
    source_id: str
    sampled_at: datetime
    capabilities: frozenset[str]
    metrics: tuple[MetricValue, ...]

    @classmethod
    def empty(cls, source_id: str, *, capabilities: frozenset[str] = frozenset()) -> "TelemetrySnapshot":
        return cls(
            source_id=source_id,
            sampled_at=datetime.now(UTC),
            capabilities=capabilities,
            metrics=(),
        )
