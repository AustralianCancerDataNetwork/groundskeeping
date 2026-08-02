# Telemetry

Telemetry has a headless core and Textual widgets layered above it.

## The headless core

`groundskeeping.contracts.telemetry` contains source protocols, availability, normalized
metrics, and snapshots. `groundskeeping.telemetry` contains the sampling runtime and provider
implementations. Both layers remain free of Textual imports so collectors can be tested and
reused outside a running app.

This boundary is enforced by tests, not just by convention: importing Textual anywhere under
the telemetry runtime/provider layer fails the suite.

Sources are async. `TelemetryRuntime` fans out across every registered source, so a page
probes availability once and then samples on a timer.

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

`groundskeeping.widgets.telemetry` renders snapshots. Widgets should bind to metric keys and
capabilities, not concrete provider classes.

A GPU card, for example, should care about accelerator utilisation and memory metrics; it
should not need to know whether the source is NVIDIA, Apple Silicon, or something added later.
Adding a provider should not require touching a widget.

## Ownership

The shell owns Textual-free infrastructure telemetry contracts and the reusable widgets that
render normalized models.

Consumers own domain telemetry: queue depth, pipeline progress, database state, workload
throughput, and tuning interpretation.
