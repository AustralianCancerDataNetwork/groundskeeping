"""Textual widgets that render normalized telemetry snapshots."""

from __future__ import annotations

from rich.table import Table
from textual.widgets import Static

from groundskeeping.contracts.telemetry import TelemetrySnapshot


class TelemetryMetricGrid(Static):
    """Capability-aware metric grid driven by normalized snapshots."""

    def render_snapshot(self, snapshot: TelemetrySnapshot) -> None:
        table = Table.grid(expand=True)
        table.add_column("Metric", style="bold")
        table.add_column("Value")
        table.add_column("Source", style="grey62")
        for metric in snapshot.metrics:
            value = "-" if metric.value is None else str(metric.value)
            if metric.unit:
                value = f"{value} {metric.unit}"
            table.add_row(metric.label, value, metric.source_id)
        if not snapshot.metrics:
            table.add_row("No telemetry available", "-", snapshot.source_id)
        self.update(table)
