# Ownership Boundary

The package provides the shared operating frame. A consumer application provides the domain.
Keep that distinction close and most design decisions become simpler.

## groundskeeping owns

- route validation and page activation;
- mounted-page state preservation;
- the shared workbench surface;
- generic view models;
- action, field, progress, cancellation, and job contracts;
- in-process job gating;
- read-only configuration inspection and draft/diff models;
- Textual-free infrastructure telemetry contracts; and
- reusable widgets that render normalized models.

## Consumers own

- every production page;
- domain presenters, controllers, and services;
- queue semantics and durable records;
- YAML or other consumer configuration formats;
- resource-specific `oa-configurator` adapters;
- model calls, database access, and runtime execution;
- domain telemetry and tuning algorithms;
- operation safety policy; and
- application branding and help text.

## Why the boundary is enforced

Two tests hold the line:

- `test_dependency_boundaries.py` checks that the shared package does not reach into consumer
  packages.
- `test_telemetry_core.py` checks that `groundskeeping.telemetry` never imports Textual, so
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
