# What belongs where

Groundskeeping owns a reusable interaction model. The consuming application owns the meaning of that interaction and every durable or domain-specific effect behind it.

## Responsibility map

| Concern | Groundskeeping | Consuming application |
|---|---|---|
| Application frame | Route validation, page activation, mounted-page state, workbench layout | Branding, production page set, environment-specific help |
| Presentation | Generic navigation, result, detail, status, and selection models | Domain presenters and wording that helps the operator decide what to do |
| Actions | Fields, parsing, redaction, progress, cancellation, result contracts | Runners, operation safety policy, model calls, database access |
| Jobs | In-process job gating and current progress | Durable records, queues, retries, leases, restart recovery |
| Wizards | Portable step contracts and reusable modal screen | General workflow meaning and application services |
| Configuration | oa-configurator inspection, generic controller, safe snapshots, branch recalculation | Field definitions, private candidates, validation, reference policy, persistence, restart behavior |
| Telemetry | Headless infrastructure contracts, sampling runtime, reusable widgets | Domain telemetry, domain interpretation, application-state collectors |

For example, Groundskeeping can render and run a database setup workflow. The consuming application decides what a valid database is, supplies the fields, keeps the candidate private, identifies shared-reference effects, compares revisions, and saves the final configuration. `ConfigWorkflowSpec` arranges those provider-owned fields without becoming another persistence layer.

## A practical placement test

Ask these questions before adding behavior to Groundskeeping:

1. Can two unrelated applications use it without importing either application's models or services?
2. Is it primarily interaction, presentation, redaction, or portable lifecycle behavior?
3. Can the contract describe the work without knowing a source system, queue implementation, deployment layout, or business rule?

If the answer to any of these is no, the behavior probably belongs in the consuming application. Adapt its safe result into a Groundskeeping contract at the boundary.

## How the boundary is enforced

`test_dependency_boundaries.py` walks the package and rejects imports from consuming applications. oa-configurator imports are confined to the typed inspection adapter; provider-neutral workflow contracts do not depend on it.

`test_telemetry_core.py` checks that telemetry runtime code does not import Textual. The package top level also avoids importing Textual, so headless contracts, configuration workflows, and sampling can be used without constructing an app.
