"""Telemetry source protocols."""

from __future__ import annotations

from typing import Protocol

from groundskeeping.telemetry.models import SourceAvailability, TelemetrySnapshot


class TelemetrySource(Protocol):
    """A read-only source of normalized telemetry snapshots."""

    source_id: str

    async def probe(self) -> SourceAvailability: ...

    async def sample(self) -> TelemetrySnapshot: ...
