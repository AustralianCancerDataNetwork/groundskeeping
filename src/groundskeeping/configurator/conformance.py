"""Reusable assertions for external configuration mutation providers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from groundskeeping.configurator.models import ConfigTarget
from groundskeeping.configurator.mutation import (
    ConfigApplyIntent,
    ConfigApplyStatus,
    ConfigDraft,
    ConfigMutationService,
    MutationOperation,
)


class MutationConformanceError(AssertionError):
    """A provider did not honour an observable mutation-service guarantee."""


def assert_mutation_service_conformance(
    service: ConfigMutationService,
    target: ConfigTarget,
    operation: MutationOperation,
    submissions: Sequence[tuple[str, Mapping[str, object]]],
) -> None:
    """Exercise a provider's happy path, token reuse, and cancellation semantics.

    ``submissions`` should be a valid candidate for the chosen target. Values are passed
    straight to the provider and are not included in any conformance error or retained by
    this helper.
    """

    capabilities = service.capabilities(target, operation)
    _require(capabilities.target == target, "Capabilities returned the wrong target.")
    _require(
        capabilities.operation is operation,
        "Capabilities returned the wrong operation.",
    )
    _require(capabilities.supported, "The conformance operation is unsupported.")
    fields = {field.key for field in service.fields(target, operation)}

    draft = _stage_candidate(service, target, operation, submissions, fields)
    plan = service.plan(draft)
    _require(plan.target == target, "Plan returned the wrong target.")
    _require(plan.operation is operation, "Plan returned the wrong operation.")
    _require(plan.ready, "A valid candidate did not produce a ready plan.")
    apply_token = plan.apply_token
    if apply_token is None:
        raise MutationConformanceError("A ready plan has no apply token.")
    intent = ConfigApplyIntent(
        target=target,
        operation=operation,
        apply_token=apply_token,
        expected_revision=draft.expected_revision,
    )
    _require(
        service.apply(intent).status is ConfigApplyStatus.APPLIED,
        "A valid apply intent was not applied.",
    )
    _require(
        service.apply(intent).status is ConfigApplyStatus.REJECTED,
        "An apply token was accepted more than once.",
    )

    cancelled = _stage_candidate(service, target, operation, submissions, fields)
    cancelled_plan = service.plan(cancelled)
    cancelled_token = cancelled_plan.apply_token
    if cancelled_token is None:
        raise MutationConformanceError(
            "A valid cancellation candidate has no apply token."
        )
    service.cancel(cancelled)
    cancelled_intent = ConfigApplyIntent(
        target=target,
        operation=operation,
        apply_token=cancelled_token,
        expected_revision=cancelled.expected_revision,
    )
    _require(
        service.apply(cancelled_intent).status is ConfigApplyStatus.REJECTED,
        "Cancellation did not invalidate the prepared apply token.",
    )


def _stage_candidate(
    service: ConfigMutationService,
    target: ConfigTarget,
    operation: MutationOperation,
    submissions: Sequence[tuple[str, Mapping[str, object]]],
    fields: set[str],
) -> ConfigDraft:
    draft = service.begin(target, operation)
    _require(draft.target == target, "Draft returned the wrong target.")
    _require(draft.operation is operation, "Draft returned the wrong operation.")
    for step_key, values in submissions:
        _require(set(values) <= fields, "A submission uses an undeclared field.")
        result = service.submit(draft, step_key, values)
        _require(result.accepted, "A valid submission was rejected.")
        draft = ConfigDraft(
            target=draft.target,
            operation=draft.operation,
            session_token=draft.session_token,
            changed_fields=result.changed_fields,
            expected_revision=draft.expected_revision,
        )
    return draft


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MutationConformanceError(message)
