# groundskeeping

`groundskeeping` is a reusable Textual shell for operator tools that help people care for a
working environment: setup checks, configuration, queues, telemetry, tuning, and long-running
operations.

It provides the common TUI pieces; each application decides what those pieces mean. In
Groundworkers, that means setup pages for database configuration, embeddings, and semantic
projection. In `cava-nlp-shard`, it means pages for evaluation runs, runtime configuration,
and model/backend health.

## The shape of an app

A `groundskeeping` app starts with one `OperatorAppSpec`.

The spec names the app, orders the pages, registers actions, and supplies the policies that
decide whether work may run. Application-specific services arrive through your page factories;
Groundskeeping does not go looking for them globally.

Pages are ordinary Textual widgets owned by the application using Groundskeeping. The shell
mounts them once, activates and deactivates them as the operator moves between tabs, and
preserves page-local state. A page receives a narrow `PageContext`; it does not receive the
whole app.

In practice, an application wires its own services into its own pages, then hands those pages
to the shared shell:

```python
from groundskeeping.app import OperatorApp, OperatorAppSpec
from groundskeeping.contracts import PageRegistration, PageRoute

spec = OperatorAppSpec(
    app_id="groundworkers",
    title="Groundworkers",
    subtitle="setup and projection operator",
    pages=(
        PageRegistration(
            route=PageRoute(
                key="database",
                label="Database",
                purpose="Configure and verify the OMOP database connection.",
            ),
            factory=lambda context: DatabaseSetupPage(database_service),
        ),
        PageRegistration(
            route=PageRoute(
                key="embeddings",
                label="Embeddings",
                purpose="Prepare model providers and populate vector indexes.",
            ),
            factory=lambda context: EmbeddingsSetupPage(embedding_service),
        ),
    ),
)

OperatorApp(spec).run()
```

Groundskeeping owns the frame around those pages. `DatabaseSetupPage`,
`EmbeddingsSetupPage`, and the services behind them stay in the application.
Use `workbench_labels` on `OperatorAppSpec` when the shared pane chrome needs different
language, such as naming the upper-right pane **Checks** instead of **Rows**. Page navigation
and view contracts still supply their own content titles.

The default page surface is the workbench:

- flat section navigation or a hierarchical catalogue on the left;
- rows or tree content on the upper right; and
- selected detail on the lower right.

![Application layout demo](./docs/static/images/demo-layout-example.png)

Read the screenshot from left to right:

| Screen area | What the page supplies | Typical contracts |
| --- | --- | --- |
| Top tabs | The registered pages in the app | `PageRoute`, `PageRegistration` |
| Left pane | Things the operator can move between inside the current page | `SectionNavigation` + `SectionItem`, or `CatalogueNavigation` + `CatalogueItem` |
| Upper-right pane | The main content for the selected section or catalogue item | `TableView`, `TreeView`, `EmptyView`, `LoadingView` |
| Lower-right pane | Extra context for the highlighted row or item | `KeyValueView`, `TextView`, `TableView` |
| Buttons above the view | Commands for the current view only | `ViewAction`, routed to `action_selected` |

Pages choose `SectionNavigation` for peer areas or `CatalogueNavigation` for hierarchical
content. They render Groundskeeping view models such as `SectionItem`, `CatalogueItem`,
`TableView`, `TreeView`, `EmptyView`, `TextView`, and `KeyValueView`. Translate application
objects before they reach the workbench.

## Setup pages

A setup page should answer a practical operator question: "is this environment ready for the
work I am about to run?"

The page usually lives in the application using Groundskeeping. It can call whatever services
that application already has for config, credentials, model providers, database checks, or
runtime health. Groundskeeping supplies the screen layout and interaction contracts.

A good setup page usually has:

- a flat section list for peer setup areas such as config, database, runtime, or credentials;
- a landing `TreeView` summarising overall readiness;
- a `TableView` for repeated checks where scanning matters;
- `KeyValueView` detail for the selected check;
- one or two safe verification actions; and
- an operation policy that describes effects in the application's own vocabulary.

Start read-only. A **Test connection** or **Refresh status** button is often enough to prove
the page shape before you add durable writes.

## Actions and jobs

Actions are buttons with a runner behind them.

An `ActionSpec` describes the operator-facing command: label, summary, fields, resources,
effects, cancellation mode, and runner. `FieldSpec` parses and redacts input before it reaches
the runner. The runner receives an `ActionContext` with progress and cancellation, so
long-running work can report what it is doing without importing widgets.

A shell job is work launched by this TUI process. It is not a durable processing queue. Use
`JobManager` and `JobPolicy` to gate in-process work and show progress; keep queue state,
retries, leases, and durable records inside the application.

## Configuration

`groundskeeping.configurator` presents `oa-configurator` stack configuration safely. It can
build snapshots, section views, safe drafts, redacted diffs, and apply intents.

It does not write TOML. Persistence belongs to `oa-configurator` and to the application using
Groundskeeping. That separation protects comments, secrets, external edits, and local safety
rules.

Applications can add `ConfigResourceAdapter` implementations for resource types that need
better labels, choices, validation, verification, or post-apply effects.

## Telemetry

Telemetry is split into headless data contracts and optional Textual widgets.

`groundskeeping.contracts.telemetry` contains source protocols, availability, normalized
metrics, and snapshots. `groundskeeping.telemetry` contains the sampling runtime. Both remain
free of Textual imports so collectors can be tested and reused outside a running app.

`groundskeeping.widgets.telemetry` renders snapshots. Widgets bind to metric keys and
capabilities, not concrete provider classes. An accelerator card, for example, cares about
utilisation and memory metrics; it does not need to know which collector produced them.

Applications own domain telemetry: queue depth, pipeline progress, database state, workload
throughput, tuning interpretation, and any other application-specific signal.

## Ownership boundary

`groundskeeping` owns:

- route validation and page activation;
- mounted-page state preservation;
- the shared workbench surface;
- generic view models;
- action, field, progress, cancellation, and job contracts;
- headless setup wizard contracts and a reusable modal wizard surface;
- in-process job gating;
- read-only configuration inspection and draft/diff models;
- headless infrastructure telemetry contracts; and
- reusable widgets that render normalized models.

Applications using Groundskeeping own:

- every production page;
- domain presenters, controllers, and services;
- queue semantics and durable records;
- YAML or other application configuration formats;
- resource-specific `oa-configurator` adapters;
- model calls, database access, and runtime execution;
- domain telemetry and tuning algorithms;
- operation safety policy; and
- application branding and help text.

## Running the demo

```bash
uv run groundskeeping
```

The demo shows the shell shape without depending on Groundworkers or `cava-nlp-shard`.

Open the Configuration page and choose **Configure database** to try the reusable setup
wizard surface.

## Running tests

```bash
uv run --extra dev pytest -q
```

The tests cover route validation, app startup, action and job contracts, wizard branching and
redaction, configurator redaction, telemetry import boundaries, and application dependency
boundaries.
