"""Reusable lifecycle assertions for external configuration providers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from groundskeeping.configurator.models import ConfigTarget
from groundskeeping.configurator.mutation import (
    ConfigApplyIntent,
    ConfigApplyStatus,
    ConfigDraft,
    ConfigMutationService,
    ConfigStepResult,
    MutationOperation,
    UnavailableMutationService,
)
from groundskeeping.contracts.views import SemanticStatus

MutationServiceFactory = Callable[[], ConfigMutationService]
MutationServiceHook = Callable[[ConfigMutationService], None]
InvalidSubmissionHook = Callable[
    [ConfigMutationService, ConfigDraft], ConfigStepResult
]


@dataclass(frozen=True)
class MutationConformanceHooks:
    """Provider-specific fault injection for the portable lifecycle suite.

    Hooks receive a fresh service instance. They should alter external state or a test
    double's next outcome without returning candidate values. A production provider test
    commonly uses ``advance_revision`` to perform an out-of-band write after planning.
    """

    invalid_submission: InvalidSubmissionHook | None = field(
        default=None, repr=False, compare=False
    )
    expected_invalid_fields: frozenset[str | None] = frozenset()
    advance_revision: MutationServiceHook | None = field(
        default=None, repr=False, compare=False
    )
    prepare_warning: MutationServiceHook | None = field(
        default=None, repr=False, compare=False
    )
    prepare_plan_error: MutationServiceHook | None = field(
        default=None, repr=False, compare=False
    )
    prepare_rejection: MutationServiceHook | None = field(
        default=None, repr=False, compare=False
    )
    prepare_failure: MutationServiceHook | None = field(
        default=None, repr=False, compare=False
    )
    make_unavailable: MutationServiceHook | None = field(
        default=None, repr=False, compare=False
    )
    prepare_unsupported: MutationServiceHook | None = field(
        default=None, repr=False, compare=False
    )
    unsupported_operation: MutationOperation | None = None


class MutationConformanceError(AssertionError):
    """A provider did not honour an observable mutation-service guarantee."""


def assert_mutation_service_conformance(
    service_factory: MutationServiceFactory,
    target: ConfigTarget,
    operation: MutationOperation,
    submissions: Sequence[tuple[str, Mapping[str, object]]],
    *,
    hooks: MutationConformanceHooks | None = None,
    secret_canary: str | None = None,
) -> None:
    """Exercise supported lifecycle behavior against isolated provider instances.

    The core assertions cover capability discovery, fields, begin/stage/plan/apply,
    single-use tokens, and cancellation. Supplying hooks additionally proves validation,
    warning/non-ready planning, stale revision conflict, rejection, operational failure,
    unavailability, and unsupported-operation behavior. Values remain transient method
    arguments and are never included in conformance errors.
    """

    hooks = hooks or MutationConformanceHooks()
    service = service_factory()
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
    if capabilities.can_inspect_impact:
        _require(
            bool(plan.effects),
            "Impact inspection was advertised but the plan returned no effects.",
        )
    apply_token = _apply_token(plan.apply_token)
    result = service.apply(
        _intent(target, operation, apply_token, plan.expected_revision)
    )
    _require(
        result.status is ConfigApplyStatus.APPLIED,
        "A valid apply intent was not applied.",
    )
    reused = service.apply(
        _intent(target, operation, apply_token, plan.expected_revision)
    )
    _require(
        reused.status is ConfigApplyStatus.REJECTED,
        "An apply token was accepted more than once.",
    )
    _assert_canary_absent(secret_canary, capabilities, draft, plan, result, reused)

    cancelled_service = service_factory()
    cancelled = _stage_candidate(
        cancelled_service, target, operation, submissions, fields
    )
    cancelled_plan = cancelled_service.plan(cancelled)
    cancelled_token = _apply_token(cancelled_plan.apply_token)
    cancelled_service.cancel(cancelled)
    cancelled_result = cancelled_service.apply(
        _intent(
            target,
            operation,
            cancelled_token,
            cancelled_plan.expected_revision,
        )
    )
    _require(
        cancelled_result.status is ConfigApplyStatus.REJECTED,
        "Cancellation did not invalidate the prepared apply token.",
    )
    _assert_canary_absent(secret_canary, cancelled, cancelled_plan, cancelled_result)

    if hooks.invalid_submission is not None:
        invalid_service = service_factory()
        invalid_draft = invalid_service.begin(target, operation)
        invalid = hooks.invalid_submission(invalid_service, invalid_draft)
        _require(not invalid.accepted, "An invalid submission was accepted.")
        actual_fields = frozenset(issue.field_key for issue in invalid.issues)
        _require(
            actual_fields == hooks.expected_invalid_fields,
            "Invalid submission returned unexpected issue locations.",
        )
        _assert_canary_absent(secret_canary, invalid_draft, invalid)
        invalid_service.cancel(invalid_draft)

    _assert_hooked_apply(
        service_factory,
        target,
        operation,
        submissions,
        fields,
        hooks.advance_revision,
        ConfigApplyStatus.CONFLICTED,
        secret_canary,
    )
    _assert_hooked_apply(
        service_factory,
        target,
        operation,
        submissions,
        fields,
        hooks.prepare_rejection,
        ConfigApplyStatus.REJECTED,
        secret_canary,
    )
    _assert_hooked_apply(
        service_factory,
        target,
        operation,
        submissions,
        fields,
        hooks.prepare_failure,
        ConfigApplyStatus.FAILED,
        secret_canary,
    )
    _assert_hooked_plan(
        service_factory,
        target,
        operation,
        submissions,
        fields,
        hooks.prepare_warning,
        expect_ready=True,
        secret_canary=secret_canary,
    )
    _assert_hooked_plan(
        service_factory,
        target,
        operation,
        submissions,
        fields,
        hooks.prepare_plan_error,
        expect_ready=False,
        secret_canary=secret_canary,
    )

    if hooks.make_unavailable is not None:
        unavailable = service_factory()
        hooks.make_unavailable(unavailable)
        try:
            unavailable.capabilities(target, operation)
        except UnavailableMutationService:
            pass
        else:
            raise MutationConformanceError(
                "An unavailable provider did not raise UnavailableMutationService."
            )

    if hooks.unsupported_operation is not None:
        unsupported_service = service_factory()
        if hooks.prepare_unsupported is not None:
            hooks.prepare_unsupported(unsupported_service)
        unsupported = unsupported_service.capabilities(target, hooks.unsupported_operation)
        _require(
            not unsupported.supported,
            "The declared unsupported operation was advertised as supported.",
        )


def _assert_hooked_apply(
    service_factory: MutationServiceFactory,
    target: ConfigTarget,
    operation: MutationOperation,
    submissions: Sequence[tuple[str, Mapping[str, object]]],
    fields: set[str],
    hook: MutationServiceHook | None,
    expected: ConfigApplyStatus,
    secret_canary: str | None,
) -> None:
    if hook is None:
        return
    service = service_factory()
    draft = _stage_candidate(service, target, operation, submissions, fields)
    plan = service.plan(draft)
    token = _apply_token(plan.apply_token)
    hook(service)
    result = service.apply(
        _intent(target, operation, token, plan.expected_revision)
    )
    _require(result.status is expected, f"Provider did not return {expected.value}.")
    reused = service.apply(
        _intent(target, operation, token, plan.expected_revision)
    )
    _require(
        reused.status is ConfigApplyStatus.REJECTED,
        f"The apply token remained usable after {expected.value}.",
    )
    _assert_canary_absent(secret_canary, draft, plan, result, reused)
    service.cancel(draft)


def _assert_hooked_plan(
    service_factory: MutationServiceFactory,
    target: ConfigTarget,
    operation: MutationOperation,
    submissions: Sequence[tuple[str, Mapping[str, object]]],
    fields: set[str],
    hook: MutationServiceHook | None,
    *,
    expect_ready: bool,
    secret_canary: str | None,
) -> None:
    if hook is None:
        return
    service = service_factory()
    draft = _stage_candidate(service, target, operation, submissions, fields)
    hook(service)
    plan = service.plan(draft)
    _require(plan.ready is expect_ready, "Provider returned unexpected plan readiness.")
    if expect_ready:
        _require(bool(plan.warnings), "Warning scenario returned no warnings.")
    else:
        _require(plan.apply_token is None, "A blocked plan returned an apply token.")
        _require(
            any(issue.status is SemanticStatus.ERROR for issue in plan.issues),
            "A blocked plan returned no error issue.",
        )
    _assert_canary_absent(secret_canary, draft, plan)
    service.cancel(draft)


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


def _intent(
    target: ConfigTarget,
    operation: MutationOperation,
    apply_token: str,
    expected_revision: str | None,
) -> ConfigApplyIntent:
    return ConfigApplyIntent(target, operation, apply_token, expected_revision)


def _apply_token(value: str | None) -> str:
    if value is None:
        raise MutationConformanceError("A ready plan has no apply token.")
    return value


def _assert_canary_absent(canary: str | None, *values: object) -> None:
    if canary is not None and canary in repr(values):
        raise MutationConformanceError(
            "A submitted secret appeared in an observable provider result."
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MutationConformanceError(message)
