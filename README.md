# groundskeeping

`groundskeeping` is a reusable Textual application shell for operator tools that need
the same kind of everyday care: environment checks, configuration, queues, telemetry,
tuning, and long-running work.

The package owns the mechanics that are generic. Consumer applications own the domain.
That boundary is the main idea.

## Mental model

A `groundskeeping` app is composed from one explicit `OperatorAppSpec`.

The spec declares:

- the visible application title;
- the ordered page routes;
- a factory for each consumer-owned page;
- available actions;
- operation and job policies; and
- the result presenter that turns runner output into a workbench view.

Pages are Textual widgets supplied by the consumer. The shell mounts them once, switches
which page is active, and preserves page-local state while the operator moves around.
Pages do not reach into the app or into each other. They receive a narrow `PageContext`
with a shared surface, navigation, notifications, and binding refresh.

The workbench is the default shared surface: catalogue on the left, rows and detail on the
right. Pages render generic view models such as `CatalogueItem`, `TableView`, `TreeView`,
`EmptyView`, and `KeyValueView`. Domain objects should be converted before they reach the
shared shell.

Actions are descriptions plus runners. The package provides the common contract for
fields, parsing, redaction, progress, cancellation, job gating, and outcomes. Consumers
provide the actual verbs, effects, preflight checks, confirmation policy, and durable
safety rules.

Telemetry has two layers:

- `groundskeeping.telemetry` contains source contracts, snapshots, sampling, and provider
  implementations with no Textual imports.
- `groundskeeping.widgets.telemetry` renders normalized snapshots in Textual widgets.

Configuration follows the same split. `groundskeeping.configurator` can inspect and
describe `oa-configurator` stack concepts without writing files itself. Editable
configuration flows should produce drafts, redacted diffs, and apply intents; persistence
belongs to the public `oa-configurator` mutation API and the consuming application’s
operation policy.

## Ownership boundary

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

## Code style

The code is written for people who will adapt it under pressure.

Comments should explain why a boundary exists, what operator-facing behaviour depends on
it, and which tempting changes would move domain logic into the shared package. Good
comments are especially valuable around Textual lifecycle methods, event routing, worker
handoffs, cancellation, secret redaction, and extension points.

Prefer comments that preserve design intent over comments that narrate syntax. For
example, explain why row events return to the active page through the workbench surface;
do not explain that a loop iterates over rows.

## Demo

Run the demo app in an environment with dependencies installed:

```bash
uv run groundskeeping
```

The demo composes three pages: overview, configuration, and telemetry. It also registers a
small action so the action registry and app spec can be exercised without a consumer
application.

## Tests

```bash
uv run --extra dev pytest -q
```

The tests cover route validation, action and job contracts, configurator redaction,
telemetry import boundaries, and the absence of consumer imports.
