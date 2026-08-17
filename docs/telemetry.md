# Telemetry

Groundskeeping separates telemetry collection from presentation. Headless sources return normalized snapshots; optional Textual widgets render those snapshots without knowing which vendor or library produced them.

## Decide where a metric belongs

| Metric | Owner | Example |
|---|---|---|
| Reusable infrastructure measurement | Groundskeeping contract/provider | Accelerator utilisation, accelerator memory |
| Application workflow state | Consuming application | Queue depth, pipeline progress, records processed |
| Domain interpretation or recommendation | Consuming application | Whether throughput is acceptable for a particular workload |

Keep collectors that depend on application sessions or domain services in the application. Adapt their output to normalised `MetricValue` and `TelemetrySnapshot` values at the page boundary.

## Sample through the headless runtime

`groundskeeping.contracts.telemetry` contains source protocols, availability, metrics, and snapshots. `groundskeeping.telemetry` contains the sampling runtime and reusable providers. Neither layer imports Textual, so collection remains usable in tests, workers, and command-line checks.

Sources are asynchronous. `TelemetryRuntime` can probe all registered sources for availability and then sample them concurrently.

```python
from groundskeeping.contracts import SourceAvailability, TelemetrySnapshot
from groundskeeping.telemetry import TelemetryRuntime
from groundskeeping.telemetry.providers import FakeTelemetrySource

runtime = TelemetryRuntime((FakeTelemetrySource(source_id="demo"),))

availability: dict[str, SourceAvailability] = await runtime.probe_all()
snapshots: tuple[TelemetrySnapshot, ...] = await runtime.sample_all()
```

Probe before displaying a source so the page can distinguish unsupported capability from a temporary sampling failure. Sample on a cadence appropriate to the cost and volatility of the measurement; the runtime does not impose a refresh interval.

## Bind widgets to meaning, not vendors

`groundskeeping.widgets.telemetry` renders normalized snapshots. Bind a widget to metric keys and source capabilities rather than a concrete provider class.

An accelerator card, for example, can use `accelerator.utilisation` and memory metrics whether the source is NVIDIA, Apple Silicon, or a future provider. Vendor-specific setup and failure messages can remain with the source or consuming application while the widget stays reusable.

If a metric needs units, freshness, or availability context to be interpreted safely, include that context in the normalized model or nearby page detail. Avoid turning a missing measurement into a zero value; “not sampled” and “measured as zero” are different states.
