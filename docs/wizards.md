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

`groundskeeping.contracts` holds presentation: field and validation contracts, the portable wizard step and result types, and the view vocabulary. `groundskeeping.configurator` holds mutation: targets, drafts, plans, diffs, apply intents and results, the workflow spec and controller, the conformance suite, and the reference fake providers.

## Branch safely

A condition checks whether an earlier non-sensitive field matches a declared set of values. Set `negated=True` for “anything except these values”; multiple conditions on one step are ANDed.

Fields are fetched after the provider session starts, so defaults and choices describe the same configuration revision the analyst will eventually review. Every provider field must appear in exactly one workflow step. Duplicate, missing, late, omitted, or secret-dependent fields fail as workflow definition errors before the analyst begins.

Some choices are available only after an earlier answer is accepted. For example, a model list may depend on the provider endpoint and credentials. An accepted `submit()` result can replace presentation descriptors for fields in later, uncompleted steps through `ConfigStepResult.future_fields`. Groundskeeping rejects refreshes that alter current or completed fields, change field kind, weaken sensitivity, include a secret default, or carry a validation callback. Providers return ordinary `FieldSpec` data only; discovery clients, callbacks, widgets, and private candidates stay behind the service boundary.

For example, a dialect choice can always show **Database name or SQLite path**, then show server fields for every choice except SQLite. New server dialects can be added to the provider's choice list without changing that negated condition.

## Keep submitted values behind the provider boundary

Accepted ordinary values remain in presentation-safe controller state so Back can restore them. When a branch changes, inactive values are removed and the provider receives their field keys in `discard_fields`.

Secrets take a shorter path: the screen collects a value, the controller parses it, `submit()` passes it to the provider, and the controller immediately clears its real-value mapping. A provider may retain the secret only in private candidate state addressed by the opaque session token. Wizard snapshots never receive it.

## Review and apply

Configuration review starts automatically after the final active step. `ConfigPlan` carries a redacted diff, structured source/destination effects, warnings, issues, the expected revision, and an opaque single-use apply token. Errors block apply; warnings do not.

Applying consumes the token before persistence begins. Applied, conflicted, rejected, and failed attempts close the wizard with the original result so the host application can refresh affected pages and present accurate guidance. A non-success result also invalidates the provider session rather than leaving a stale candidate behind. Cancellation calls the provider's `cancel()` method and returns `WizardResultStatus.CANCELLED`; it is separate from `ConfigApplyStatus` because no apply attempt occurred.

Open the controller through the page context:

```python
def action_selected(self, action_key: str, context: PageContext) -> None:
    if action_key == "database.configure":
        operation = resolve_operation(mutation_service, target)
        controller = ConfigWizardController(workflow(operation), mutation_service)
        context.open_wizard(controller)
```

A workflow spec is built for one fixed operation, so a single **Configure** action has to decide between creating and updating before it constructs the controller. `resolve_operation()` encodes that decision once — update the target if the provider supports updating it, otherwise create it — so hosts do not each write their own version and drift apart. Pass an explicit operation instead when an action is deliberately create-only or update-only; the wizard then blocks with the provider's own reason, which is the right outcome for **Create database** aimed at a database that already exists.

Run `uv run groundskeeping`, open **Configuration**, and select **Configure database** to try the complete lifecycle with a fake provider.

## Report apply outcomes

A provider classifies every apply attempt into one of four statuses. The host renders different remediation for each, so this is a decision to make deliberately rather than a label to pick by feel. Two questions separate them: was anything written, and if not, was the request itself at fault?

| Status | Meaning | Typical cause |
|---|---|---|
| `APPLIED` | The change was persisted. | — |
| `CONFLICTED` | The stored configuration changed after the plan was prepared; the expected revision no longer matches. Nothing was written. | Another writer saved between plan and apply. |
| `REJECTED` | The request itself was not acceptable, and no write was attempted. | Consumed or unknown apply token, intent not matching the prepared plan, candidate failing validation, ownership or policy forbidding the write. |
| `FAILED` | The write was attempted and errored. The previous configuration remains authoritative. | Filesystem permissions, disk full, I/O error, serialisation failure. |

`REJECTED` against `FAILED` is the pair that gets confused. A `PermissionError` raised while opening the configuration file for writing is `FAILED`, not `REJECTED`: the request was well formed, and the operator's next action is to fix the environment rather than to change a value. Bucketing it with validation errors sends the operator to edit something that was never the problem. Do not map exception types to statuses in a single `except` clause unless every type in it fails the same way.

`summary` and `detail` are rendered to the operator and written to application logs, so both must be presentation-safe: no submitted values, no secrets, no provider tracebacks. `summary` says what happened in one line; `detail` carries the next action, and should be present whenever the status is not `APPLIED`. `refresh_pages` names the host page keys whose data the change invalidated.

The analyst-facing view of the same four outcomes is in [Understand the result](operator-guide.md#understand-the-result).

## Refuse an operation you cannot serve

`capabilities()` is the non-raising question: can this provider perform this operation on this target? A host normally asks it first, through `resolve_operation()` or directly.

`begin()` must refuse anyway. A capability answer can go stale between the check and the call, and some conditions are only visible once a session is opened. Raise `MutationOperationUnsupported` with a presentation-safe message saying why — the entry already exists, the entry does not exist, the configuration is read-only, policy forbids the change. The controller shows that message and blocks the wizard.

| Exception from `begin()` | Meaning | Wizard behaviour |
|---|---|---|
| `MutationOperationUnsupported` | This operation is legitimately unavailable for this target. | Blocks with your message. |
| `UnavailableMutationService` | The provider as a whole cannot serve requests. | Blocks with your message. |
| Anything else | A provider defect. | Blocks with a generic message; the traceback is logged without its exception message, because provider exceptions can echo submitted values. |

`MutationOperationUnsupported` subclasses `ValueError`, so a host that already catches `ValueError` around `begin()` keeps working. Raising a bare `ValueError` is not sufficient: a host cannot tell it from a programming error, so it cannot choose between showing the operator guidance and letting the error surface as a bug.

## Project both sides of the diff the same way

`build_config_diff()` compares two flattened mappings and reports every field that differs. It has no schema access and cannot know which values are package defaults, so it is only as good as the two mappings you hand it. Both must come from the same projection of the same configuration shape.

The failure is easy to miss because nothing raises. Flatten the stored base with `exclude_none=True` while the candidate comes back from a validator with every default materialised, and every defaulted field appears as a change: `mcp.port: None -> 8000`, `rest.base_path: None -> /v1`. A journey that touched four fields presents the operator with sixteen changes to approve, and the four that matter are buried among the twelve that do not exist. Flatten both sides through the same call, with the same options, before diffing.

The conformance suite checks this for you: it restages the values it has just applied and requires the resulting plan to report no change.

## Verify your provider

`assert_mutation_service_conformance()` is the release gate for a provider. Run it as a committed test, not an ad-hoc script — a provider that has never been through it is a provider whose contract behaviour is unverified.

```python
from groundskeeping.configurator import (
    MutationConformanceHooks,
    MutationOperation,
    assert_mutation_service_conformance,
)


def test_provider_conformance() -> None:
    canary = "conformance-secret-canary"
    assert_mutation_service_conformance(
        lambda: MyMutationService(root=make_isolated_config_dir()),
        target,
        MutationOperation.CREATE,
        submissions=(
            ("strategy", {"strategy": "create"}),
            ("connection", {"database_name": "analytics", "password": canary}),
        ),
        hooks=MutationConformanceHooks(
            invalid_submission=lambda service, draft: service.submit(
                draft, "connection", {"database_name": "reserved"}
            ),
            expected_invalid_fields=frozenset({"database_name"}),
            advance_revision=lambda service: write_config_out_of_band(service),
            prepare_rejection=lambda service: forbid_by_policy(service),
            prepare_failure=lambda service: make_config_dir_unwritable(service),
            make_unavailable=lambda service: corrupt_config_file(service),
            unsupported_operation=MutationOperation.UPDATE,
        ),
        secret_canary=canary,
    )
```

The first argument is a factory, not an instance. The suite calls it repeatedly and each call must return a provider over isolated state — a fresh temporary directory, a fresh database — because a hook that makes one instance fail must not affect the next assertion.

`submissions` must reach a valid candidate. They are staged more than once, so they must not depend on state left behind by an earlier run.

`secret_canary` is a value you submit into a sensitive field. The suite requires it to be absent from the `repr()` of every object the provider returns. Always set it; it is the cheapest check here and the one whose absence is most expensive.

Without hooks, the suite proves capability discovery, the begin/fields/submit/plan/apply sequence, single-use apply tokens, diff projection symmetry, and cancellation. Each hook adds one behaviour:

| Hook | Proves |
|---|---|
| `invalid_submission` with `expected_invalid_fields` | An invalid submission is refused, with issues at exactly the expected field locations. |
| `advance_revision` | An out-of-band write between plan and apply returns `CONFLICTED` and consumes the token. |
| `prepare_warning` | A warning still produces a ready plan. |
| `prepare_plan_error` | A blocked candidate produces a plan with an error issue and no apply token. |
| `prepare_rejection` | A refused request returns `REJECTED` and consumes the token. |
| `prepare_failure` | A failed write returns `FAILED` and consumes the token. |
| `make_unavailable` | An unusable provider raises `UnavailableMutationService` from `capabilities()`. |
| `unsupported_operation` with optional `prepare_unsupported` | The operation is advertised as unsupported, and `begin()` refuses it with `MutationOperationUnsupported`. |

A production provider is expected to pass the hooked suite. If a hook has no meaningful implementation for your provider, that is worth a second look before you omit it: `prepare_failure` in particular exists because a provider that cannot describe how its writes fail has usually not decided how to classify them.

Run the suite once per operation the provider supports. The projection check is skipped when an operation stops being available after it succeeds — a create-only provider refusing to create the same entry twice — so a `CREATE` run alone can leave it unexercised.

Failures raise `MutationConformanceError`, which never includes submitted values.
