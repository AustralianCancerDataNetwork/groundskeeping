# Configuration

Groundskeeping gives an application a safe, consistent way to show an `oa-configurator` 1.x stack and guide an analyst through a configuration change. Groundskeeping supports oa-configurator 1.1 and later releases in the 1.x series.

## Inspect the current environment

The configuration browser shows connections, databases, providers, models, vector stores, package-specific tools, and logging in a stable order. Empty sections stay visible, so an analyst can tell the difference between “not configured” and “not inspected.” Default logging is identified explicitly.

References include the destination section and name plus a useful state:

- **resolved** means the entry exists with the required type;
- **missing** means no entry with that name exists; and
- **wrong kind** means the name exists, but its concrete type cannot be used by that field—for example, a vector store pointing to a CDM database instead of a generic database.

The source path helps the analyst confirm which configuration is open. It is display metadata, not permission to write that file. The current stack model has no profile, resource-alias, or active-profile layer; the application passes the effective `StackConfig` it wants inspected.

### Add inspection to an application

Pass the current `StackConfig` to `snapshot()`, then render the snapshot directly or convert it to the shared `TreeView`:

```python
from groundskeeping.configurator import OAConfiguratorAdapter

adapter = OAConfiguratorAdapter()
snapshot = adapter.snapshot(stack_config)
tree_view = adapter.as_tree_view(snapshot)
```

For a stack loaded from disk, `snapshot.path` comes from `StackConfig.loaded_path`. An application inspecting a candidate from another source can provide an explicit display path:

```python
snapshot = adapter.snapshot(candidate, config_path="/review/proposed.toml")
```

The adapter walks public fields on oa-configurator's concrete models. A generic database therefore shows generic database fields, while a CDM database also shows its vocabulary connection and vocabulary/results schemas.

### Give tool sections a schema

`StackConfig.tools` contains untyped dictionaries because package schemas are discovered at runtime. If the application has resolved package configuration instances, pass them to the adapter so their sensitivity metadata and `RefTo` declarations can be inspected:

```python
snapshot = adapter.snapshot(
    stack_config,
    package_configs=(my_package_config,),
)
```

Without a matching package instance, the tool remains visible and is marked **Package schema unavailable**. Groundskeeping shows a conservative summary but does not claim that unknown references are valid.

## Guide an analyst through a change

A configuration workflow looks like an ordinary setup wizard. The analyst chooses an available operation, completes one step at a time, reviews a redacted diff and the affected references, and applies only when the provider says the plan is ready.

Back keeps previously accepted ordinary values. Changing an earlier branch removes values from steps that no longer apply. Secret controls clear as soon as they are submitted; the review shows only that a secret changed. If another process updates the configuration first, the result is a conflict with reload guidance rather than an overwrite. A provider rejection is also distinct from a transport or operational failure.

Unavailable and unsupported are different states. An unavailable provider may work again later. An unsupported operation is not offered as an actionable control for that target.

## Add a write flow to an application

The application supplies two pieces:

1. a `ConfigWorkflowSpec` with operator-facing copy, ordered field groups, and declarative branch conditions; and
2. a `ConfigMutationService` that supplies fields and privately owns validation, candidate state, planning, revision checks, and persistence.

The workflow names stable provider field keys. It does not contain callbacks, widgets, oa-configurator models, or application state:

```python
from groundskeeping.configurator import (
    ConfigBranchCondition,
    ConfigTarget,
    ConfigTargetKind,
    ConfigWizardController,
    ConfigWorkflowSpec,
    ConfigWorkflowStep,
    ConfigWorkflowStepKind,
    MutationOperation,
)

target = ConfigTarget(
    kind=ConfigTargetKind.DATABASE,
    key="metadata",
    title="Metadata database",
)

workflow = ConfigWorkflowSpec(
    key="database-create",
    target=target,
    operation=MutationOperation.CREATE,
    title="Create database configuration",
    purpose="Reuse an existing database or describe a new one.",
    steps=(
        ConfigWorkflowStep(
            key="strategy",
            title="Setup approach",
            field_keys=("strategy",),
            kind=ConfigWorkflowStepKind.CHOICE,
        ),
        ConfigWorkflowStep(
            key="new-database",
            title="New database",
            field_keys=("database_name", "connection_url", "password"),
            when=(ConfigBranchCondition("strategy", "create"),),
        ),
    ),
)

controller = ConfigWizardController(workflow, mutation_service)
context.open_wizard(controller)
```

`ConfigMutationService` is deliberately independent of oa-configurator. A provider can use oa-configurator internally, but it must return Groundskeeping's portable fields, issues, plans, and results. The seven service calls have clear jobs:

- `capabilities()` says whether this target and operation are supported;
- `fields()` provides the `FieldSpec` definitions used by the declared workflow;
- `begin()` creates private candidate state and returns an opaque session and expected revision;
- `submit()` validates one step, updates the private candidate, and discards invalidated branch fields;
- `plan()` returns only a redacted diff, structured effects, warnings, issues, and a single-use apply token;
- `apply()` consumes that token before returning applied, conflicted, rejected, or failed; and
- `cancel()` invalidates the session and any prepared token without persisting.

Plan readiness is derived from the plan: an error issue always blocks apply, and a ready plan always has an apply token. Warnings may accompany a ready plan. Apply tokens and expected revisions are opaque provider values; applications should not parse or construct them in UI code.

## Secret boundary

For inspection, typed fields marked `Sensitive` by oa-configurator become `RedactedValue` before a `ConfigSectionView` is created. Untyped tool dictionaries and nested free-form configuration use a conservative fallback for names such as `password`, `api_key`, `secret`, and `token`. Collections are summarized only after that recursive redaction pass.

For writes, `FieldSpec` identifies sensitive inputs. The generic controller passes a submitted secret to `ConfigMutationService.submit()` and immediately drops its local real-value mapping. Controller state keeps only a configured/not-configured marker, secret controls render empty when revisited, and plans must contain a redacted diff. `ConfigDraft`, `ConfigPlan`, `ConfigApplyIntent`, snapshots, issues, effects, results, and test history must never contain raw submitted values.

Free-form data still needs honest field names or schema metadata. Groundskeeping cannot infer that an arbitrary value under a misleading key is a credential.

## Try the reference provider

`FakeConfigMutationService` provides deterministic create, update, validation, warning, conflict, rejection, failure, token-reuse, and cancellation scenarios without writing a file. The bundled demo uses it with `fake_database_workflow()` so an app developer can see the intended composition without first implementing persistence.

External providers can run `assert_mutation_service_conformance()` from `groundskeeping.configurator.conformance` with a target and valid step submissions. The helper verifies capabilities, field coverage, begin/stage/plan/apply, single-use apply tokens, and cancellation invalidation. Provider-specific tests should additionally inject validation, conflict, rejection, failure, and secret canaries.

## Ownership boundary

Groundskeeping owns wizard mechanics, safe presentation state, declarative branch recalculation, and portable lifecycle results. It does not write TOML or decide what a valid database, provider, or model looks like.

The consuming application and its mutation provider own candidate construction, oa-configurator validation, reference policy, verification, persistence, revision comparison, and restart behavior. Real candidate objects and raw submitted values stay behind that provider boundary.
