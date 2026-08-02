"""Bounded sampler for telemetry sources."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping

from groundskeeping.contracts.telemetry import (
    SourceAvailability,
    SourceStatus,
    TelemetrySnapshot,
    TelemetrySource,
)


class TelemetryRuntime:
    """Collect snapshots without coupling callers to provider classes or Textual."""

    def __init__(
        self,
        sources: Iterable[TelemetrySource],
        *,
        timeout_seconds: float = 2.0,
        history_limit: int = 120,
    ) -> None:
        self.sources = tuple(sources)
        self.timeout_seconds = timeout_seconds
        self._history: dict[str, deque[TelemetrySnapshot]] = defaultdict(
            lambda: deque(maxlen=history_limit)
        )

    async def probe_all(self) -> Mapping[str, SourceAvailability]:
        results = await asyncio.gather(
            *(self._probe(source) for source in self.sources),
            return_exceptions=False,
        )
        return {result.source_id: result for result in results}

    async def sample_all(self) -> tuple[TelemetrySnapshot, ...]:
        snapshots = await asyncio.gather(
            *(self._sample(source) for source in self.sources),
            return_exceptions=False,
        )
        for snapshot in snapshots:
            self._history[snapshot.source_id].append(snapshot)
        return tuple(snapshots)

    def history(self, source_id: str) -> tuple[TelemetrySnapshot, ...]:
        return tuple(self._history.get(source_id, ()))

    async def _probe(self, source: TelemetrySource) -> SourceAvailability:
        try:
            return await asyncio.wait_for(source.probe(), timeout=self.timeout_seconds)
        except TimeoutError:
            return SourceAvailability(
                source_id=source.source_id,
                status=SourceStatus.DEGRADED,
                message="Probe timed out.",
            )
        except Exception as exc:  # noqa: BLE001
            return SourceAvailability(
                source_id=source.source_id,
                status=SourceStatus.UNAVAILABLE,
                message=f"{type(exc).__name__}: {exc}",
            )

    async def _sample(self, source: TelemetrySource) -> TelemetrySnapshot:
        try:
            return await asyncio.wait_for(source.sample(), timeout=self.timeout_seconds)
        except Exception:  # noqa: BLE001
            return TelemetrySnapshot.empty(source.source_id)
