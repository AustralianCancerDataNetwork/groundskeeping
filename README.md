# groundskeeping

`groundskeeping` is a reusable Textual shell for operator tools that help people care for a working environment: setup checks, configuration, queues, telemetry, tuning, and long-running operations.

The package provides the shared operating frame. A consumer application provides the domain. Keep that distinction close and most design decisions become simpler.

## The Shape Of An App

A `groundskeeping` app starts with one `OperatorAppSpec`.

The spec names the app, orders the pages, registers the actions, and supplies the policies that decide whether work may run. It is the composition root: everything application-specific should arrive there from the consumer, not through global lookup inside the shared package.

Pages are owned by the consumer and are ordinary Textual widgets. The shell mounts them once, activates and deactivates them as the operator moves between tabs, and preserves page-local state. A page receives a narrow `PageContext`; it does not receive the whole app.

The default page surface is the workbench:

- catalogue on the left;
- rows or tree content on the upper right; and
- selected detail on the lower right.

Pages render package-owned view models such as `CatalogueItem`, `TableView`, `TreeView`, `EmptyView`, `TextView`, and `KeyValueView`. Domain objects should be translated before they reach the workbench. That keeps the shared shell reusable and keeps consumer language in the consumer.

## Setup Pages

A setup page should answer a concrete operator question: "can this environment do the work I am about to ask of it?"

The page should normally live in the consumer package and use consumer services to inspect the environment. `groundskeeping` supplies the rendering and action contracts; it should not know what "ready" means for Groundworkers, CAVA, or any future application.

A good setup page usually has:

- a catalogue of setup areas, such as config, database, runtime, model server, paths, or credentials;
- a landing `TreeView` summarising overall readiness;
- a `TableView` for repeated checks where scanning matters;
- `KeyValueView` detail for the selected check;
- one or two safe verification actions; and
- an operation policy that describes effects in the consumer's own vocabulary.

Start read-only. Verification actions are a good first step because they exercise the shell, action contracts, progress reporting, and failure presentation without taking ownership of durable setup changes too early.

## Actions And Jobs

Actions are declarations plus runners.

An `ActionSpec` describes the operator-facing command: label, summary, fields, resources, effects, cancellation mode, and runner. `FieldSpec` parses and redacts input before it reaches the runner. The runner receives an `ActionContext` with progress and cancellation, so long-running work can report what it is doing without importing widgets.

A shell job is work launched by this TUI process. It is not a durable processing queue. Use `JobManager` and `JobPolicy` to gate in-process work and show progress; keep queue state, retries, leases, and durable records inside the consumer.

## Configuration

`groundskeeping.configurator` understands the public shape of `oa-configurator` stack configuration well enough to inspect and present it safely. It can build snapshots, section views, drafts, redacted diffs, and apply intents.

It does not write TOML. Persistence belongs to the public `oa-configurator` mutation API and to the consumer's operation policy. That separation protects comments, secrets, external edits, and tenant-specific safety rules.

Consumer applications can add `ConfigResourceAdapter` implementations for resource types that need better labels, choices, validation, verification, or post-apply effects.

## Telemetry

Telemetry has a headless core and Textual widgets layered above it.

`groundskeeping.telemetry` contains source protocols, availability, normalized metrics, snapshots, and sampling runtime. It must remain free of Textual imports so collectors can be tested and reused outside a running app.

`groundskeeping.widgets.telemetry` renders snapshots. Widgets should bind to metric keys and capabilities, not concrete provider classes. A GPU card, for example, should care about accelerator utilisation and memory metrics; it should not need to know whether the source is NVIDIA, Apple Silicon, or something added later.

Consumers own domain telemetry: queue depth, pipeline progress, database state, workload throughput, and tuning interpretation.

## Ownership Boundary

`groundskeeping` owns:

- route validation and page activation;
- mounted-page state preservation;
- the shared workbench surface;
- generic view models;
- action, field, progress, cancellation, and job contracts;
- in-process job gating;
- read-only configuration inspection and draft/diff models;
- Textual-free infrastructure telemetry contracts; and
- reusable widgets that render normalized models.

Consumers own:

- every production page;
- domain presenters, controllers, and services;
- queue semantics and durable records;
- YAML or other consumer configuration formats;
- resource-specific `oa-configurator` adapters;
- model calls, database access, and runtime execution;
- domain telemetry and tuning algorithms;
- operation safety policy; and
- application branding and help text.

## Commenting Style

Write comments for the next person adapting the tool.

Good comments explain why a boundary exists, what operator-facing behaviour depends on it, and where domain logic should stay. They are especially useful around Textual lifecycle methods, event routing, worker handoffs, cancellation, secret redaction, and extension points.

Prefer comments that preserve intent over comments that narrate syntax. Explain why row events return to the active page through the workbench surface. Do not explain that a loop iterates over rows.

If a future maintainer is likely to wonder "why is this shaped this way?", leave them a small signpost.

## Running The Demo

```bash
uv run groundskeeping
```

The demo composes overview, configuration, and telemetry pages. It also registers a small action so the app spec and action registry can be exercised without a consumer application.

## Running Tests

```bash
uv run --extra dev pytest -q
```

The tests cover route validation, app startup, action and job contracts, configurator redaction, telemetry import boundaries, and consumer dependency boundaries.
