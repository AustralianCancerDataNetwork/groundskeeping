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

Four [import-linter](https://import-linter.readthedocs.io/) contracts in `.importlinter` hold the structure. Run them with `uv run lint-imports`; CI runs them as their own job, so a boundary breach fails the build before the tests do.

| Contract | Rule |
|---|---|
| `no-consumer-imports` | Nothing in the package imports a consuming application. |
| `headless-core` | `contracts`, `configurator`, `telemetry`, and `navigation` do not import Textual, so they can be used without constructing an app. |
| `oa-confined` | Only the typed inspection adapter imports oa-configurator; the provider-neutral workflow contracts do not depend on it. |
| `layers` | The Textual shell sits above the domain modules, which sit above the presentation contracts. `contracts` may not import `configurator`, `widgets`, or `app`. |

The layers contract carries one recorded exception, written into `.importlinter` with its reason: `WizardReview.effects` is typed `tuple[EffectRef | str, ...]`, so `contracts.wizards` names a `configurator` type under `TYPE_CHECKING`. It is the only upward reference in the package and costs nothing at runtime. Type-only imports are otherwise checked like any other, so a second one has to be argued for rather than added quietly.

Two rules stay in tests because a contract cannot express them:

- `test_dependency_boundaries.py` rejects private and CLI oa-configurator imports. Import-linter squashes external packages to their top level, so it cannot distinguish `oa_configurator.cli` from `oa_configurator`.
- `test_telemetry_core.py` imports the package in a subprocess and checks `sys.modules`. Only a runtime check can prove a deferred import does not fire.
