# Configuration

Groundskeeping presents an oa-configurator 1.x stack in a form an analyst can inspect safely and gives developers a provider-neutral way to add guided changes. It supports oa-configurator 1.1 and later releases in the 1.x series.

## For analysts: inspect the environment you are using

The configuration browser shows connections, databases, providers, models, vector stores, package-specific tools, and logging in a stable order. Empty sections remain visible so **not configured** is not confused with **not inspected**. Default logging is identified explicitly.

The source path helps confirm which stack is open. It is display metadata, not a statement that the application can write to that file. The current stack model has no profile, resource-alias, or active-profile layer; the application shows the effective `StackConfig` it was given.

### Understand references

References connect one setting to another, such as a vector store selecting a database.

| State | Meaning | Example |
|---|---|---|
| Resolved | The named entry exists with the required type. | A vector store points to a generic database. |
| Missing | No entry has that name. | A model names a provider that is not configured. |
| Wrong kind | The name exists, but its type cannot be used here. | A vector store points to a CDM database where a generic database is required. |
| No schema available | A tool section is visible, but no installed package declares what belongs in it. | A tool section names a package that is not installed. Its keys are counted and its values are hidden. |

### Make a guided change

A configuration action opens a wizard rather than editing the displayed tree directly.

```text
Current stack → guided answers → provider validation → redacted review → revision-aware apply
```

Back restores accepted ordinary values. If an earlier answer changes the active branch, answers from steps that no longer apply are discarded. Secret controls clear immediately after submission and are never repopulated from controller state. An analyst who returns to a required secret step must re-enter the value before moving forward again.

The review shows changed fields, warnings, validation issues, and structured effects on other configuration entries. It never shows the private candidate or a raw secret. Warnings deserve attention but permit apply; errors block it.

| Apply result | What happened |
|---|---|
| Applied | The provider persisted the prepared candidate. Refresh the affected pages and run any relevant verification action. |
| Conflicted | The configuration changed since planning. The provider did not overwrite the newer revision. Reload and prepare the change again. |
| Rejected | The provider understood the request but application policy or current state refused it. |
| Failed | Persistence or another apply operation could not be completed. |
| Cancelled | The wizard session and prepared token were invalidated without calling apply. |

Unavailable and unsupported are also different. An unavailable provider exists but may recover later; an unsupported operation is not offered as an actionable control for that target.

## For developers: inspect an oa-configurator stack

Pass the effective `StackConfig` to `OAConfiguratorAdapter.snapshot()`, then render the immutable snapshot directly or convert it to the shared `TreeView`.

```python
from groundskeeping.configurator import OAConfiguratorAdapter

adapter = OAConfiguratorAdapter()
snapshot = adapter.snapshot(stack_config)
tree_view = adapter.as_tree_view(snapshot)
```

For a stack loaded from disk, `snapshot.path` comes from `StackConfig.loaded_path`. If you are inspecting a candidate from another source, provide a display path explicitly:

```python
snapshot = adapter.snapshot(
    candidate,
    config_path="/review/proposed.toml",
    title="Proposed stack configuration",
)
```

The adapter walks public fields on oa-configurator's concrete models. A generic database therefore shows its common fields, while a CDM database also shows its vocabulary connection and vocabulary/results schemas.

### Tool sections are typed from the registry

`StackConfig.tools` holds plain dictionaries, so a tool section is only as inspectable as the schema behind it. The adapter resolves that schema itself: it reads the `omop.config` entry-point group, loads each registered `PackageConfigBase`, and validates the matching section against it. `Sensitive()` markers and `RefTo` declarations are then inspected exactly as they are on the core models, with nothing passed in.

Pass `package_configs` when the application already holds a resolved instance. An explicit instance wins over the registry, which matters when it carries values that validating the section afresh would not reproduce.

```python
snapshot = adapter.snapshot(
    stack_config,
    package_configs=(my_package_config,),
)
```

A section with no usable schema is rendered by shape alone: a key count, a `WARNING` status, and a note naming the reason. Its values are not displayed. This covers a package that registers nothing, one that fails to import, and a section name that matches nothing installed. Without a schema there is no way to tell a credential from a hostname, so nothing is shown rather than guessed at.

To make your package's section inspectable, register its config class under the `omop.config` entry-point group and mark its secrets with `Sensitive()`:

```toml
[project.entry-points."omop.config"]
my_package = "my_package.config:MyPackageConfig"
```

## For developers: add a write flow

The write path separates reusable interaction from application-owned persistence.

```text
ConfigWorkflowSpec ── wording, steps, branches ─┐
                                                ├─ ConfigWizardController ─ WizardScreen
ConfigMutationService ─ fields, candidate, I/O ─┘
```

The application supplies:

1. a `ConfigWorkflowSpec` containing operator-facing copy, ordered field groups, and declarative branch conditions; and
2. a `ConfigMutationService` containing fields, validation, private candidate state, planning, revision checks, and persistence.

Groundskeeping joins them in `ConfigWizardController`. It does not write TOML or reconstruct a candidate from the values shown in review.

### Declare a static workflow

The workflow names stable provider field keys. It contains no widgets, callbacks, oa-configurator models, or application services.

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
    purpose="Choose a database type and provide the settings it needs.",
    steps=(
        ConfigWorkflowStep(
            key="dialect",
            title="Database type",
            field_keys=("dialect",),
            kind=ConfigWorkflowStepKind.CHOICE,
        ),
        ConfigWorkflowStep(
            key="database",
            title="Database name or SQLite path",
            field_keys=("database_name",),
        ),
        ConfigWorkflowStep(
            key="server",
            title="Server connection",
            field_keys=("host", "port", "user", "password"),
            when=(
                ConfigBranchCondition(
                    field_key="dialect",
                    values=frozenset({"sqlite"}),
                    negated=True,
                ),
            ),
        ),
    ),
)

controller = ConfigWizardController(workflow, mutation_service)
context.open_wizard(controller)
```

The server step means “any dialect except SQLite,” so a new server dialect added to the provider's choice list follows the correct branch without another condition. Use separate stable field keys when branches genuinely need different labels, defaults, or validation.

### Work within the static workflow limits

The controller calls `begin()` first, then passes that draft to `fields()`. Field defaults and choices must therefore describe the same configuration revision as the provider's private candidate. `fields()` is called once during this initial session setup. Every returned field must appear in exactly one declared step, and its label, default, choices, required state, and sensitivity remain fixed for that session. Each condition must refer to an earlier non-sensitive field; conditions on one step are ANDed.

These constraints catch provider/workflow version skew before the analyst reaches an impossible review. Dynamic field re-querying is intentionally outside the contract.

Review starts automatically after the final active step. There is no editing-stage shortcut to Review because a provider plan must include every active step. Back remains available from review.

### Implement the mutation provider

`ConfigMutationService` is independent of oa-configurator. A provider may use oa-configurator internally, but every returned object must use Groundskeeping's portable, presentation-safe contracts.

| Method | Provider responsibility | Safe return value |
|---|---|---|
| `capabilities()` | Report whether this target and operation are supported. | `MutationCapabilities` |
| `begin()` | Create private candidate state and capture the current revision. | `ConfigDraft` with opaque session token |
| `fields()` | Describe every input using defaults and choices from that draft's revision. | `tuple[FieldSpec, ...]` |
| `submit()` | Validate one step, update the candidate, and discard inactive branch fields. | Issues and the complete changed-field set |
| `plan()` | Validate the complete candidate and calculate changes and impacts. | Redacted `ConfigPlan` with expected revision and single-use apply token |
| `apply()` | Consume the token, compare revisions, and persist if still valid. | Applied, conflicted, rejected, or failed result |
| `cancel()` | Invalidate the candidate session and prepared token. | No candidate or secret data |

Connection tests and other operational checks remain ordinary application actions rather than mutation capabilities. Preview is intrinsic to the generic write flow, and a provider includes structured `effects` when it can determine them reliably.

A plan is ready only when it has an apply token, the same expected revision captured by its draft, and no error issues. Warnings can accompany a ready plan. Treat revisions and tokens as opaque values: UI code must not parse or construct them.

`EffectRef` remains structured through `WizardReview`. Its impact kind, source target and field, optional destination target, label, and status let a TUI style effects while another client groups or navigates them. Consumers should not parse the human-readable string representation to recover those endpoints.

## Keep secrets and candidates out of presentation state

The inspection and write paths use different protections.

| Boundary | Protection |
|---|---|
| Typed inspection | oa-configurator `Sensitive` fields become `RedactedValue` before a `ConfigSectionView` exists. |
| Free-form inspection | Keys such as `password`, `api_key`, `secret`, and `token` are conservatively redacted before collections are summarized. |
| Field parsing | `SECRET` and `sensitive=True` fields expose only `<redacted>` to presentation; validator details are suppressed for sensitive values. |
| Step submission | The controller passes the real value to `submit()` and immediately removes it from its own mapping. |
| Candidate lifetime | Only the provider may retain real values, behind an opaque session token. |
| Plan and apply | Diffs, effects, issues, warnings, results, and history remain safe to render and log. |

`ConfigDraft`, `ConfigPlan`, `ConfigApplyIntent`, wizard snapshots, issues, effects, results, and test history must never contain raw submitted values. Free-form redaction still depends on honest field names or schema metadata; Groundskeeping cannot identify a credential stored under a misleading key.

## Test a provider before integrating its screen

`FakeConfigMutationService` demonstrates create, update, validation, warning, conflict, rejection, failure, token reuse prevention, and cancellation without writing a file. The bundled demo pairs it with `fake_database_workflow()`.

External providers should run `assert_mutation_service_conformance()` in their own test suite. It is exported from `groundskeeping.configurator`, alongside `MutationConformanceHooks` and the fake providers. Supply a service factory, target, valid step submissions, and hooks for behaviors the generic runner cannot trigger itself. [Verify your provider](wizards.md#verify-your-provider) has a runnable example and the full hook map.

Without hooks the runner already checks capability discovery, the begin/fields/submit/plan/apply sequence, single-use apply tokens, cancellation, and that restaging applied values plans no change. Hooks add the rest:

| Hooked scenario | What conformance verifies |
|---|---|
| Invalid step | Issue locations and no secret canary in returned objects |
| Out-of-band revision change | Conflict result and consumed token |
| Warning or blocked plan | Correct readiness and token behavior |
| Rejection or failure | Terminal status and token invalidation |
| Unavailable or unsupported operation | Accurate capability boundary, and a typed `MutationOperationUnsupported` from `begin()` |
| Cancellation | Session and prepared token invalidation |

The conformance runner complements provider-specific tests for candidate construction, oa-configurator validation, atomic persistence, file permissions, and application recovery instructions.

## Ownership summary

Groundskeeping owns wizard mechanics, safe controller state, static branch recalculation, and portable lifecycle results. The consuming application and mutation provider own field meaning, candidate construction, oa-configurator validation, reference policy, verification, persistence, revision comparison, and restart behavior.

Cancellation is deliberately not a `ConfigApplyStatus`. `cancel()` returns a cancelled wizard result without calling `apply()`; `ConfigApplyResult` describes only actual apply attempts.
