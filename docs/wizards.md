# Setup Wizards

Use a setup wizard when an analyst needs a little guidance: choosing whether to reuse or create a database, entering provider settings, reviewing shared-reference effects, or understanding why a proposed change cannot be applied.

`WizardScreen` renders the portable step contracts in `groundskeeping.contracts.wizards`. It supports choice, form, and review steps, plus Back, Next, Review, Apply, and Cancel behavior. Choice fields work with keyboard and mouse input, and long option lists remain scrollable.

For general application workflows, an application can implement `WizardController` directly. For configuration, use `ConfigWizardController` and `ConfigMutationService`; this gives all consuming applications the same branch, validation, redaction, planning, conflict, and apply behavior without duplicating a controller.

## Configuration wizard responsibilities

The application declares the words and shape of the workflow with `ConfigWorkflowSpec`. The mutation provider supplies `FieldSpec` values and owns real candidate state. `ConfigWizardController` joins the two and emits render-safe `WizardSnapshot` values for `WizardScreen`.

This separation is useful when configuration rules evolve. A provider can add a field, change validation, or produce a richer effect without teaching the Textual screen about oa-configurator or application policy. The workflow needs an update only when the actual step grouping or branch experience changes.

Conditions are simple equality checks against an earlier, non-sensitive field. A branch cannot depend on a secret, and each field appears in exactly one step. Groundskeeping validates the declaration when the controller starts and reports duplicate, missing, late, or unsuitable field keys as definition errors.

## What happens to submitted values

Ordinary accepted values are retained in presentation-safe controller state so Back can restore them. When a branch changes, values belonging to inactive steps are removed from the controller and the provider is told which fields to discard.

Secrets take a shorter path. The screen collects the value, the controller parses it and passes it to the provider for that step, and then the controller clears its real-value mapping. The provider may keep a secret only inside private candidate state behind the opaque session token. Snapshots and revisited secret controls never receive it.

## Review and apply

The provider prepares the review. A `ConfigPlan` contains a redacted diff, structured effects, warnings, validation issues, and an opaque apply token. An error blocks apply; warnings do not. The screen never reconstructs a candidate from displayed values.

Applying consumes the token before work begins. The result distinguishes:

- **applied**, which may refresh affected pages;
- **conflicted**, which tells the analyst to reload rather than overwriting a newer revision;
- **rejected**, which means the provider understood the request but refused it; and
- **failed**, which means the operation itself could not be completed.

Cancel asks the provider to invalidate the session and prepared token without applying. Conflict, rejection, failure, success, and cancel all prevent the same apply token from being used again.

## Open a wizard

Pages continue to use the same `PageContext` entry point:

```python
def action_selected(self, action_key, context):
    if action_key == "database.configure":
        context.open_wizard(ConfigWizardController(workflow, mutation_service))
```

Run `uv run groundskeeping` and open **Configuration** to try the fake provider's branching database flow.
