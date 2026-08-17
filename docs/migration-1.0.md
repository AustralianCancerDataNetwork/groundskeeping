# Migrating from 0.3 to 1.0

Groundskeeping 1.0 uses the oa-configurator 1.x stack directly and replaces the provisional configuration write API with the generic mutation service and controller. This is a clean transition: there are no aliases for the removed profile/resource model and no forwarding wrappers for provisional write types.

This page is for developers maintaining an existing integration. Analysts do not need to migrate saved wizard state; a wizard session is intentionally temporary.

## Change summary

| 0.3 integration | 1.0 replacement | Required action |
|---|---|---|
| Provisional profile/resource inspection | `OAConfiguratorAdapter.snapshot(StackConfig)` | Pass the effective oa-configurator stack directly. |
| Profile or active-profile presentation | No equivalent | Remove UI and code that expect profile state. |
| `ConfigResourceAdapter` or application-specific configuration controller | `ConfigWorkflowSpec`, `ConfigMutationService`, and `ConfigWizardController` | Move candidate and persistence behavior behind the provider. |
| String effects | Structured `EffectRef` values | Supply source, optional destination, field, label, kind, and status. |
| Cancellation represented with apply outcomes | `ConfigMutationService.cancel()` and `WizardResultStatus.CANCELLED` | Keep cancellation separate from actual apply attempts. |
| Sensitive `ReviewChange` values retained but hidden by `repr` | Values replaced with `<redacted>` during construction | Move any logic that needs the real value behind the provider boundary. |
| Apply outcome chosen by whichever status read closest | Documented `ConfigApplyStatus` semantics | Re-check the classification. A write that was attempted and errored is `FAILED`; only a request that was refused before any write is `REJECTED`. |
| Host resolves create versus update itself | `resolve_operation(service, target)` | Replace the local capability check, or keep pinning an operation deliberately. |

## Update inspection

Pass an oa-configurator 1.x `StackConfig` to `OAConfiguratorAdapter.snapshot()`. The resulting browser contains connections, databases, providers, models, vector stores, tools, and logging. `ConfiguratorSnapshot` no longer has profile state, and its optional path is display metadata sourced from `StackConfig.loaded_path`.

```python
adapter = OAConfiguratorAdapter()
snapshot = adapter.snapshot(stack_config)
```

If the stack's tool dictionaries have resolved package configuration instances, pass them through `package_configs` so typed sensitivity and reference metadata remain available.

## Replace configuration writes

The new composition has three parts:

```text
ConfigWorkflowSpec + ConfigMutationService → ConfigWizardController → WizardScreen
```

- Put stable copy, steps, field grouping, and branch conditions in `ConfigWorkflowSpec`.
- Put fields, private candidates, validation, planning, revision checks, persistence, and cancellation in `ConfigMutationService`.
- Open `ConfigWizardController` through the existing `PageContext.open_wizard()` entry point.

Provider fields must all appear in the workflow exactly once. Conditions match an earlier non-sensitive field against a set of values and may be negated. The controller begins a revision-bound draft before fetching fields from it, and review is generated automatically after all active steps are complete.

`ConfigDraft`, `ConfigDiff`, `ConfigPlan`, `ConfigApplyIntent`, and the remaining write contracts live in `groundskeeping.configurator.mutation`. Plans require an expected revision and single-use apply token before they are ready.

## Move sensitive logic behind the provider

In 0.3, `ReviewChange(sensitive=True)` hid values in `repr`, but `before` and `after` still held the originals. In 1.0, construction replaces both values with `<redacted>`. `ConfigDiffEntry` applies the same rule with `RedactedValue`.

Sensitive `FieldSpec` validators also use a protected error boundary. If a validator returns or raises a message containing submitted input, the public error becomes `<label> is invalid.`

Do not recover real values from review or exception text. Validation and any transformation that needs the submitted value belong inside the mutation provider's private candidate lifecycle.

## Verify the migrated provider

Import `assert_mutation_service_conformance()` and `MutationConformanceHooks` from `groundskeeping.configurator` and run them as a committed test, with hooks for invalid input, revision conflict, warnings, blocked plans, rejection, failure, unavailability, and unsupported operations. Run it once per operation the provider supports. Then retain provider-specific tests for candidate construction and persistence behavior.

See [Verify your provider](wizards.md#verify-your-provider) for a runnable example, [Configuration](configuration.md#test-a-provider-before-integrating-its-screen) for the scenario map, and [API reference](api/configurator.md) for exact signatures.
