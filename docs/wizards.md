# Setup wizards

Use a wizard when an analyst needs guidance through several related choices and should review the outcome before committing it. Common examples are choosing whether to reuse or create a database, entering provider settings, or understanding the impact of replacing a shared configuration target.

If you are using an existing application, the important behaviors are described first. Developers can continue to [choose a controller](#choose-a-controller).

## What an analyst can expect

```text
Choose or enter values → resolve validation issues → review changes and effects → apply or go Back
```

- **Back** restores accepted ordinary values from earlier active steps.
- Changing an earlier choice can remove later steps that no longer apply; answers from those steps are discarded.
- Secret fields clear after submission and are never restored into the control. Re-enter a required secret if you return to that step and move forward again.
- **Review** shows presentation-safe changes and effects, not the private candidate object.
- **Apply** is available only when the provider has produced a complete plan without errors.
- **Cancel** closes the session without applying its prepared plan.

For the meaning of applied, conflicted, rejected, failed, and cancelled results, see [Understand the result](operator-guide.md#understand-the-result).

## Choose a controller

| Workflow | Use | You implement |
|---|---|---|
| General multi-step application task | A custom `WizardController` | Step state, validation, review, and result behavior |
| oa-configurator or another provider-backed configuration change | `ConfigWizardController` | `ConfigWorkflowSpec` and `ConfigMutationService` |

`WizardScreen` renders the portable contracts from `groundskeeping.contracts.wizards`. It supports choice, form, and review steps plus keyboard- and mouse-friendly navigation. Long choice lists scroll within the modal.

For configuration, prefer `ConfigWizardController` so every consuming application gets the same branch invalidation, redaction, planning, conflict, apply, and cancellation behavior.

## Compose a configuration wizard

The three components have distinct responsibilities:

| Component | Owns | Must not own |
|---|---|---|
| `ConfigWorkflowSpec` | Operator-facing wording, step order, field grouping, static branch conditions | Widgets, callbacks, candidates, persistence |
| `ConfigMutationService` | Fields, validation, private candidate state, effects, revision checks, persistence | Textual screen state |
| `ConfigWizardController` | Navigation, accepted safe values, branch recalculation, review and apply lifecycle | Raw durable configuration or persistence rules |

This split lets validation and reference policy evolve behind the provider without teaching the Textual screen about oa-configurator or application internals.

## Branch safely

A condition checks whether an earlier non-sensitive field matches a declared set of values. Set `negated=True` for “anything except these values”; multiple conditions on one step are ANDed.

Fields are fetched once when the controller starts. Every provider field must appear in exactly one workflow step, and labels, defaults, choices, required state, and sensitivity cannot change by branch. Duplicate, missing, late, omitted, or secret-dependent fields fail as workflow definition errors before the analyst begins.

For example, a dialect choice can always show **Database name or SQLite path**, then show server fields for every choice except SQLite. New server dialects can be added to the provider's choice list without changing that negated condition.

## Keep submitted values behind the provider boundary

Accepted ordinary values remain in presentation-safe controller state so Back can restore them. When a branch changes, inactive values are removed and the provider receives their field keys in `discard_fields`.

Secrets take a shorter path: the screen collects a value, the controller parses it, `submit()` passes it to the provider, and the controller immediately clears its real-value mapping. A provider may retain the secret only in private candidate state addressed by the opaque session token. Wizard snapshots never receive it.

## Review and apply

Configuration review starts automatically after the final active step. `ConfigPlan` carries a redacted diff, structured source/destination effects, warnings, issues, the expected revision, and an opaque single-use apply token. Errors block apply; warnings do not.

Applying consumes the token before persistence begins. This makes applied, conflicted, rejected, and failed attempts terminal and prevents stale review replay. Cancellation calls the provider's `cancel()` method and returns `WizardResultStatus.CANCELLED`; it is separate from `ConfigApplyStatus` because no apply attempt occurred.

Open the controller through the page context:

```python
def action_selected(self, action_key: str, context: PageContext) -> None:
    if action_key == "database.configure":
        controller = ConfigWizardController(workflow, mutation_service)
        context.open_wizard(controller)
```

Run `uv run groundskeeping`, open **Configuration**, and select **Configure database** to try the complete lifecycle with a fake provider.
