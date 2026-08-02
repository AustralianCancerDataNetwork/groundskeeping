# What belongs where

Groundskeeping should stay boring and reusable. It owns the TUI frame and the small contracts
needed to render pages, actions, wizards, configuration summaries, and telemetry. The
application using it owns the real work.

## Groundskeeping owns

- route validation and page activation;
- mounted-page state preservation;
- the shared workbench surface;
- generic view models;
- action, field, progress, cancellation, and job contracts;
- setup wizard contracts and the reusable wizard screen;
- in-process job gating;
- read-only configuration inspection and draft/diff models;
- headless infrastructure telemetry contracts; and
- reusable widgets that render normalized models.

## Applications own

- every production page;
- domain presenters, controllers, and services;
- queue semantics and durable records;
- YAML or other application configuration formats;
- resource-specific `oa-configurator` adapters;
- model calls, database access, and runtime execution;
- domain telemetry and tuning algorithms;
- operation safety policy; and
- application branding and help text.

For example, Groundskeeping can render a database setup wizard. Groundworkers decides what a
"database" means, how to validate a candidate connection, whether an edit affects shared
resources, and how the final config is saved.

## Why the boundary is enforced

Two tests hold the line:

- `test_dependency_boundaries.py` checks that the shared package does not reach into
  application packages.
- `test_telemetry_core.py` checks that telemetry runtime code never imports Textual, so
  collectors stay usable in worker and test processes that do not construct an application.

The package top level also avoids importing Textual, so headless contracts, configuration
inspection, and telemetry sampling can be imported without a running app.

## Commenting style

Write comments for the next person adapting the tool.

Good comments explain why a boundary exists, what operator-facing behaviour depends on it, and
where domain logic should stay. They are especially useful around Textual lifecycle methods,
event routing, worker handoffs, cancellation, secret redaction, and extension points.

Prefer comments that preserve intent over comments that narrate syntax. Explain why row events
return to the active page through the workbench surface. Do not explain that a loop iterates
over rows.

If a future maintainer is likely to wonder "why is this shaped this way?", leave them a small
signpost.
