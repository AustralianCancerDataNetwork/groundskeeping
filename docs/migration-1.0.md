# Migrating from 0.3 to 1.0

Groundskeeping 1.0 adopts the oa-configurator 1.x stack directly and replaces the provisional configuration write types with the generic mutation service and controller. This is a clean API transition; there are no aliases for the removed 0.x profile/resource model or forwarding wrappers for the provisional write API.

## Configuration inspection

Pass an oa-configurator 1.x `StackConfig` to `OAConfiguratorAdapter.snapshot()`. The browser shows connections, databases, providers, models, vector stores, tools, and logging. `ConfiguratorSnapshot` no longer contains profile state, and its optional path is inspection metadata sourced from `StackConfig.loaded_path`.

## Configuration writes

Replace application-specific configuration controllers and `ConfigResourceAdapter` implementations with:

- `ConfigWorkflowSpec` for stable copy, steps, field grouping, and branches;
- `ConfigMutationService` for fields, private candidates, validation, planning, persistence, and cancellation; and
- `ConfigWizardController` for the reusable lifecycle.

`ConfigDraft`, `ConfigDiff`, `ConfigPlan`, `ConfigApplyIntent`, and related mutation types live in `groundskeeping.configurator.mutation`. Effects are structured `EffectRef` objects rather than strings. Cancellation is performed through `cancel()` and produces `WizardResultStatus.CANCELLED`; it is not a `ConfigApplyStatus`.

Provider fields must all appear in the workflow exactly once. Branch conditions use value sets with optional negation, fields are fetched once when the controller starts, and configuration review is generated automatically after all active steps are complete.

## Sensitive review values

In 0.3, `ReviewChange(sensitive=True)` hid its values in `repr` but the `before` and `after` attributes still retained the originals. In 1.0, construction immediately replaces both attributes with `<redacted>`. `ConfigDiffEntry` applies the same rule with `RedactedValue`. Consumers that previously read a sensitive review value must move that logic behind their mutation provider; raw values are no longer available from presentation models.

Sensitive `FieldSpec` validators also receive a protected error boundary. If a validator returns or raises a message containing the submitted secret, the public parse error is the generic `<label> is invalid` message.
