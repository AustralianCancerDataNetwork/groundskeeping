# What belongs where

Groundskeeping should stay boring and reusable. It owns the TUI frame and the portable contracts needed to render pages, actions, wizards, configuration, and telemetry. The application using it owns what those controls mean and what durable work they perform.

## Groundskeeping owns

- route validation and page activation;
- mounted-page state preservation;
- the shared workbench surface;
- generic view models;
- action, field, progress, cancellation, and job contracts;
- setup wizard contracts and the reusable wizard screen;
- the generic configuration controller, safe navigation state, and declarative branch recalculation;
- typed configuration inspection and presentation-safe mutation contracts;
- in-process job gating;
- headless infrastructure telemetry contracts; and
- reusable widgets that render normalized models.

## Applications own

- every production page;
- domain presenters and services;
- queue semantics and durable records;
- YAML or other application configuration formats;
- configuration field definitions, validation, private candidate state, and persistence providers;
- oa-configurator integration behind the mutation provider;
- model calls, database access, and runtime execution;
- domain telemetry and tuning algorithms;
- operation safety policy; and
- application branding and help text.

For example, Groundskeeping can run and render a database setup workflow. A consuming application decides what a database means, supplies the fields, validates the private candidate, identifies shared-reference effects, and saves the final configuration. The application uses `ConfigWorkflowSpec` to arrange those provider fields instead of maintaining its own wizard state machine.

## Why the boundary is enforced

`test_dependency_boundaries.py` checks that the shared package does not reach into application packages and confines oa-configurator imports to the typed inspection adapter. `test_telemetry_core.py` checks that telemetry runtime code never imports Textual, so collectors stay usable in worker and test processes that do not construct an application.

The package top level also avoids importing Textual, so headless contracts, configuration workflows, and telemetry sampling can be imported without a running app.
