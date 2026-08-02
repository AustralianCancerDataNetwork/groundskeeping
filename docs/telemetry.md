# Telemetry

Telemetry has simple data contracts, a sampling runtime, and optional Textual widgets.

## The headless core

`groundskeeping.contracts.telemetry` contains source protocols, availability, normalized
metrics, and snapshots. `groundskeeping.telemetry` contains the sampling runtime and provider
implementations. Both layers remain free of Textual imports so collectors can be tested and
reused outside a running app.

The runtime/provider layer does not import Textual. That keeps telemetry usable in tests,
workers, and small command-line checks.

Sources are async. `TelemetryRuntime` fans out across every registered source, so a page can
probe availability once and then sample on a timer.

```python
from groundskeeping.contracts import SourceAvailability, TelemetrySnapshot
from groundskeeping.telemetry import TelemetryRuntime
from groundskeeping.telemetry.providers import FakeTelemetrySource

runtime = TelemetryRuntime((FakeTelemetrySource(source_id="demo"),))

availability: dict[str, SourceAvailability] = await runtime.probe_all()
snapshots: tuple[TelemetrySnapshot, ...] = await runtime.sample_all()
```

`probe_all` reports which sources are usable and what each can measure; `sample_all` returns
normalized metrics keyed by strings such as `accelerator.utilisation` and
`workload.throughput`.

## Widgets

`groundskeeping.widgets.telemetry` renders snapshots. Bind widgets to metric keys and
capabilities, not concrete provider classes.

A GPU card, for example, cares about accelerator utilisation and memory metrics. It should not
need to know whether the source is NVIDIA, Apple Silicon, or something added later.

## Ownership

Groundskeeping owns the infrastructure telemetry contracts and the reusable widgets that
render normalized models.

Applications own domain telemetry: queue depth, pipeline progress, database state, workload
throughput, and tuning interpretation.
