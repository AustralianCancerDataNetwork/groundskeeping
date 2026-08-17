from __future__ import annotations

import logging
from dataclasses import asdict, replace
from typing import cast

import pytest

from groundskeeping.configurator import (
    ConfigApplyResult,
    ConfigApplyStatus,
    ConfigBranchCondition,
    ConfigStepResult,
    ConfigTarget,
    ConfigTargetKind,
    ConfigWizardController,
    ConfigWorkflowSpec,
    ConfigWorkflowStep,
    EffectRef,
    FakeConfigMutationService,
    FakeDialectConfigMutationService,
    FakeMutationScenario,
    MutationOperation,
    MutationOperationUnsupported,
    fake_database_workflow,
    fake_dialect_database_workflow,
)
from groundskeeping.contracts import (
    ChoiceOption,
    ChoiceStep,
    FieldKind,
    FieldSpec,
    FormStep,
    ReviewStep,
    WizardDefinitionError,
    WizardResultStatus,
)


class RefreshingFieldService(FakeConfigMutationService):
    def __init__(self, future_fields: tuple[FieldSpec, ...]) -> None:
        super().__init__()
        self.future_fields = future_fields

    def fields(self, draft):
        super().fields(draft)
        return (
            FieldSpec("endpoint", "Provider endpoint"),
            FieldSpec(
                "model",
                "Model",
                kind=FieldKind.CHOICE,
                choices=(ChoiceOption("pending", "Complete the endpoint first"),),
                disabled=True,
            ),
        )

    def submit(self, draft, step_key, values, *, discard_fields=frozenset()):
        result = super().submit(
            draft,
            step_key,
            values,
            discard_fields=discard_fields,
        )
        return ConfigStepResult(
            issues=result.issues,
            changed_fields=result.changed_fields,
            future_fields=self.future_fields if step_key == "endpoint" else (),
        )


def _refreshing_controller(future_fields: tuple[FieldSpec, ...]):
    target = ConfigTarget(ConfigTargetKind.PROVIDER, "embedding", "Embedding provider")
    workflow = ConfigWorkflowSpec(
        "provider-model",
        target,
        MutationOperation.CREATE,
        "Configure a model",
        "Discover models after accepting the provider endpoint.",
        (
            ConfigWorkflowStep("endpoint", "Provider endpoint", ("endpoint",)),
            ConfigWorkflowStep("model", "Model", ("model",)),
        ),
    )
    return ConfigWizardController(workflow, RefreshingFieldService(future_fields))


def test_workflow_rejects_duplicate_steps_and_branch_fields() -> None:
    target = ConfigTarget(ConfigTargetKind.DATABASE, "db", "Database")
    step = ConfigWorkflowStep("name", "Name", ("database_name",))

    with pytest.raises(WizardDefinitionError, match="step keys"):
        ConfigWizardController(
            ConfigWorkflowSpec(
                "bad",
                target,
                MutationOperation.CREATE,
                "Bad",
                "Bad workflow",
                (step, step),
            ),
            FakeConfigMutationService(),
        )

    with pytest.raises(WizardDefinitionError, match="duplicate branch fields"):
        ConfigWizardController(
            ConfigWorkflowSpec(
                "bad-branch",
                target,
                MutationOperation.CREATE,
                "Bad branch",
                "Bad workflow",
                (
                    ConfigWorkflowStep("strategy", "Strategy", ("strategy",)),
                    ConfigWorkflowStep(
                        "name",
                        "Name",
                        ("database_name",),
                        when=(
                            ConfigBranchCondition(
                                "strategy", frozenset({"create"})
                            ),
                            ConfigBranchCondition(
                                "strategy", frozenset({"reuse"})
                            ),
                        ),
                    ),
                ),
            ),
            FakeConfigMutationService(),
        )


def test_workflow_rejects_unknown_and_late_branch_fields() -> None:
    target = ConfigTarget(ConfigTargetKind.DATABASE, "db", "Database")
    unknown = ConfigWizardController(
        ConfigWorkflowSpec(
            "unknown",
            target,
            MutationOperation.CREATE,
            "Unknown",
            "Unknown field",
            (ConfigWorkflowStep("missing", "Missing", ("not_declared",)),),
        ),
        FakeConfigMutationService(),
    )
    with pytest.raises(WizardDefinitionError, match="unknown field"):
        unknown.start()

    late = ConfigWizardController(
        ConfigWorkflowSpec(
            "late",
            target,
            MutationOperation.CREATE,
            "Late",
            "Late branch",
            (
                ConfigWorkflowStep(
                    "name",
                    "Name",
                    ("database_name",),
                    when=(
                        ConfigBranchCondition(
                            "strategy", frozenset({"create"})
                        ),
                    ),
                ),
                ConfigWorkflowStep("strategy", "Strategy", ("strategy",)),
            ),
        ),
        FakeConfigMutationService(),
    )
    with pytest.raises(WizardDefinitionError, match="earlier step"):
        late.start()


def test_workflow_rejects_provider_fields_it_cannot_render() -> None:
    workflow = fake_database_workflow()
    controller = ConfigWizardController(
        ConfigWorkflowSpec(
            key=workflow.key,
            target=workflow.target,
            operation=workflow.operation,
            title=workflow.title,
            purpose=workflow.purpose,
            steps=workflow.steps[:-1],
        ),
        FakeConfigMutationService(),
    )

    with pytest.raises(WizardDefinitionError, match="absent from"):
        controller.start()


def test_dialect_workflow_handles_shared_and_non_sqlite_fields() -> None:
    sqlite = ConfigWizardController(
        fake_dialect_database_workflow(), FakeDialectConfigMutationService()
    )
    assert sqlite.start().step.key == "dialect"
    identity = sqlite.submit({"dialect": "sqlite"}).snapshot
    assert identity.step.key == "database-identity"
    sqlite_review = sqlite.submit({"database_name": "/tmp/demo.db"}).snapshot
    assert isinstance(sqlite_review.step, ReviewStep)

    server = ConfigWizardController(
        fake_dialect_database_workflow(), FakeDialectConfigMutationService()
    )
    server.start()
    assert server.submit({"dialect": "mssql+pyodbc"}).snapshot.step.key == (
        "database-identity"
    )
    server_step = server.submit({"database_name": "analytics"}).snapshot
    assert isinstance(server_step.step, FormStep)
    assert server_step.step.key == "server-connection"
    assert tuple(field.key for field in server_step.step.fields) == (
        "host",
        "port",
        "user",
        "password",
    )


def test_provider_can_refresh_a_future_field_after_discovery() -> None:
    controller = _refreshing_controller(
        (
            FieldSpec(
                "model",
                "Model",
                kind=FieldKind.CHOICE,
                choices=(
                    ChoiceOption("embed-small", "Embed small"),
                    ChoiceOption("embed-large", "Embed large"),
                ),
                default="embed-small",
                help="Models reported by the accepted endpoint.",
            ),
        )
    )

    assert controller.start().step.key == "endpoint"
    refreshed = controller.submit({"endpoint": "http://models.example"}).snapshot

    assert isinstance(refreshed.step, FormStep)
    assert refreshed.step.key == "model"
    field = refreshed.step.fields[0]
    assert field.disabled is False
    assert tuple(choice.value for choice in field.choices) == (
        "embed-small",
        "embed-large",
    )
    assert refreshed.values == {"model": "embed-small"}


def test_provider_cannot_refresh_current_or_change_future_field_kind() -> None:
    current = _refreshing_controller((FieldSpec("endpoint", "Changed endpoint"),))
    current.start()
    with pytest.raises(WizardDefinitionError, match="later workflow steps"):
        current.submit({"endpoint": "http://models.example"})

    changed_kind = _refreshing_controller((FieldSpec("model", "Model"),))
    changed_kind.start()
    with pytest.raises(WizardDefinitionError, match="cannot change kind"):
        changed_kind.submit({"endpoint": "http://models.example"})


def test_provider_field_refresh_rejects_callbacks_and_weakened_sensitivity() -> None:
    callback = _refreshing_controller(
        (
            FieldSpec(
                "model",
                "Model",
                kind=FieldKind.CHOICE,
                choices=(ChoiceOption("embed", "Embed"),),
                validator=lambda _value: None,
            ),
        )
    )
    callback.start()
    with pytest.raises(WizardDefinitionError, match="callbacks"):
        callback.submit({"endpoint": "http://models.example"})

    class SensitiveRefreshingService(RefreshingFieldService):
        def fields(self, draft):
            super().fields(draft)
            return (
                FieldSpec("endpoint", "Provider endpoint"),
                FieldSpec("model", "Model", sensitive=True),
            )

    target = ConfigTarget(ConfigTargetKind.PROVIDER, "embedding", "Embedding provider")
    workflow = ConfigWorkflowSpec(
        "provider-secret",
        target,
        MutationOperation.CREATE,
        "Configure a model",
        "Keep secret fields secret.",
        (
            ConfigWorkflowStep("endpoint", "Provider endpoint", ("endpoint",)),
            ConfigWorkflowStep("model", "Model", ("model",)),
        ),
    )
    weakened = ConfigWizardController(
        workflow,
        SensitiveRefreshingService((FieldSpec("model", "Model"),)),
    )
    weakened.start()
    with pytest.raises(WizardDefinitionError, match="weaken sensitivity"):
        weakened.submit({"endpoint": "http://models.example"})


def _controller(
    *, scenario: FakeMutationScenario = FakeMutationScenario.READY
) -> tuple[ConfigWizardController, FakeConfigMutationService]:
    service = FakeConfigMutationService(scenario=scenario)
    return ConfigWizardController(fake_database_workflow(), service), service


def _reach_review(
    controller: ConfigWizardController,
    *,
    password: str = "controller-secret-canary",
    shared: bool = True,
):
    assert isinstance(controller.start().step, ChoiceStep)
    create = controller.submit({"strategy": "create"}).snapshot
    assert isinstance(create.step, FormStep)
    assert create.step.key == "create-database"
    sharing = controller.submit(
        {
            "database_name": "analytics",
            "connection_url": "postgresql://analytics/demo",
            "password": password,
        }
    ).snapshot
    assert isinstance(sharing.step, FormStep)
    assert sharing.step.key == "sharing"
    return controller.submit({"shared_reference": shared}).snapshot


def test_controller_binds_fields_to_the_started_session() -> None:
    controller, service = _controller()

    controller.start()

    assert tuple(event.action for event in service.history[:2]) == ("begin", "fields")


def test_controller_runs_a_branching_create_flow_and_applies() -> None:
    controller, service = _controller()
    review = _reach_review(controller)

    assert isinstance(review.step, ReviewStep)
    assert review.can_apply
    effect = next(
        effect
        for effect in review.step.review.effects
        if isinstance(effect, EffectRef) and effect.impact_kind == "shared-reference"
    )
    assert effect.source_target.kind is ConfigTargetKind.TOOL
    assert effect.destination_target is not None
    assert effect.destination_target.kind is ConfigTargetKind.DATABASE
    assert effect.destination_target.key == "metadata"

    result = controller.apply()

    assert result.status is WizardResultStatus.APPLIED
    assert "analytics" in repr(service.durable)
    assert service.durable["metadata"]["password"] is True


def test_controller_keeps_safe_values_across_back_but_clears_secret_controls() -> None:
    controller, _ = _controller()
    review = _reach_review(controller)
    assert isinstance(review.step, ReviewStep)

    sharing = controller.back()
    details = controller.back()

    assert sharing.step.key == "sharing"
    assert details.step.key == "create-database"
    assert details.values["database_name"] == "analytics"
    assert details.values["connection_url"] == "postgresql://analytics/demo"
    assert "password" not in details.values


def test_changing_a_branch_discards_invalidated_downstream_values() -> None:
    controller, _ = _controller()
    controller.start()
    controller.submit({"strategy": "create"})
    controller.submit(
        {
            "database_name": "analytics",
            "connection_url": "postgresql://analytics/demo",
            "password": "branch-secret-canary",
        }
    )
    controller.back()
    strategy = controller.back()
    assert strategy.step.key == "strategy"

    reuse = controller.submit({"strategy": "reuse"}).snapshot
    assert reuse.step.key == "reuse-database"
    controller.submit({"selected_database": "metadata"})
    review = controller.submit({"shared_reference": False}).snapshot

    assert isinstance(review.step, ReviewStep)
    changed_fields = {change.field for change in review.step.review.changes}
    assert "database_name" not in changed_fields
    assert "connection_url" not in changed_fields
    assert "password" not in changed_fields
    assert "selected_database" in changed_fields


def test_local_and_provider_validation_stay_on_the_current_step() -> None:
    controller, _ = _controller()
    controller.start()
    controller.submit({"strategy": "create"})

    local = controller.submit(
        {
            "database_name": "",
            "connection_url": "",
            "password": "",
        }
    )
    assert local.snapshot.step.key == "create-database"
    assert {issue.field_key for issue in local.issues} == {
        "database_name",
        "connection_url",
        "password",
    }

    provider = controller.submit(
        {
            "database_name": "reserved",
            "connection_url": "not-a-url",
            "password": "not-retained",
        }
    )
    assert provider.snapshot.step.key == "create-database"
    assert {issue.field_key for issue in provider.issues} == {
        "database_name",
        None,
    }


def test_warning_plan_is_ready_and_error_plan_is_not() -> None:
    warning_controller, _ = _controller(scenario=FakeMutationScenario.WARNING)
    warning = _reach_review(warning_controller, shared=False)
    assert isinstance(warning.step, ReviewStep)
    assert warning.can_apply
    assert warning.step.review.warnings

    error_controller, _ = _controller(scenario=FakeMutationScenario.PLAN_ERROR)
    blocked = _reach_review(error_controller, shared=False)
    assert not blocked.can_apply
    assert blocked.issues


@pytest.mark.parametrize(
    ("scenario", "expected"),
    (
        (FakeMutationScenario.CONFLICTED, WizardResultStatus.CONFLICTED),
        (FakeMutationScenario.REJECTED, WizardResultStatus.REJECTED),
        (FakeMutationScenario.FAILED, WizardResultStatus.FAILED),
    ),
)
def test_controller_maps_non_success_apply_outcomes(
    scenario: FakeMutationScenario,
    expected: WizardResultStatus,
) -> None:
    controller, service = _controller(scenario=scenario)
    _reach_review(controller, shared=False)

    result = controller.apply()

    assert result.status is expected
    assert not result.applied
    assert service.history[-1].action == "cancel"


def test_revision_change_is_a_conflict_not_an_operational_failure() -> None:
    controller, service = _controller()
    _reach_review(controller, shared=False)
    service.advance_revision()

    result = controller.apply()

    assert result.status is WizardResultStatus.CONFLICTED
    assert "Reload" in str(result.detail)


def test_plan_must_use_the_revision_captured_by_the_draft() -> None:
    class WrongRevisionService(FakeConfigMutationService):
        def plan(self, draft):
            return replace(super().plan(draft), expected_revision="another-revision")

    controller = ConfigWizardController(
        fake_database_workflow(), WrongRevisionService()
    )

    result = _reach_review(controller, shared=False)

    assert result.issues[0].message == (
        "The provider returned an unusable configuration plan."
    )


def test_unavailable_and_unsupported_starts_are_legible() -> None:
    unavailable = ConfigWizardController(
        fake_database_workflow(),
        FakeConfigMutationService(available=False),
    ).start()
    unsupported = ConfigWizardController(
        fake_database_workflow(operation=MutationOperation.CREATE),
        FakeConfigMutationService(
            supported_operations=frozenset({MutationOperation.UPDATE})
        ),
    ).start()

    assert isinstance(unavailable.step, ReviewStep)
    assert "temporarily unavailable" in unavailable.issues[0].message
    assert not unavailable.can_apply
    assert isinstance(unsupported.step, ReviewStep)
    assert "not supported" in unsupported.issues[0].message
    assert not unsupported.can_apply


def test_a_refusal_from_begin_blocks_with_the_provider_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class LateRefusalService(FakeConfigMutationService):
        """Advertise the operation, then refuse it, as a stale capability answer does."""

        def begin(self, target, operation):
            raise MutationOperationUnsupported(
                "The configuration file is open read-only."
            )

    with caplog.at_level(logging.ERROR):
        blocked = ConfigWizardController(
            fake_database_workflow(), LateRefusalService()
        ).start()

    assert isinstance(blocked.step, ReviewStep)
    assert blocked.issues[0].message == "The configuration file is open read-only."
    assert not blocked.can_apply
    assert not caplog.records


def test_cancel_invalidates_the_session_without_durable_mutation() -> None:
    controller, service = _controller()
    _reach_review(controller)

    result = controller.cancel()

    assert result.status is WizardResultStatus.CANCELLED
    assert service.durable == {}
    assert service.history[-1].action == "cancel"


def test_secret_canary_never_enters_observable_controller_or_provider_state(
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = "never-observe-controller-secret"
    controller, service = _controller()
    snapshots = [controller.start()]
    snapshots.append(controller.submit({"strategy": "create"}).snapshot)
    snapshots.append(
        controller.submit(
            {
                "database_name": "analytics",
                "connection_url": "postgresql://analytics/demo",
                "password": canary,
            }
        ).snapshot
    )
    snapshots.append(controller.submit({"shared_reference": False}).snapshot)

    assert canary not in repr(snapshots)
    assert canary not in repr([asdict(snapshot) for snapshot in snapshots])
    assert canary not in repr(service.history)
    assert canary not in repr(service.durable)
    assert canary not in caplog.text


def test_provider_exceptions_are_sanitized() -> None:
    canary = "provider-exception-secret"

    class ExplodingService(FakeConfigMutationService):
        def submit(self, *args, **kwargs):
            raise RuntimeError(canary)

    controller = ConfigWizardController(
        fake_database_workflow(), ExplodingService()
    )
    controller.start()
    transition = controller.submit({"strategy": "create"})

    assert canary not in repr(transition)
    assert transition.issues[0].message == "The provider could not validate this step."


def test_provider_exception_logging_keeps_traceback_but_not_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = "logged-provider-secret"

    class ExplodingService(FakeConfigMutationService):
        def submit(self, *args, **kwargs):
            raise RuntimeError(canary)

    controller = ConfigWizardController(
        fake_database_workflow(), ExplodingService()
    )
    controller.start()
    controller.submit({"strategy": "create"})

    assert "failed during step validation" in caplog.text
    assert "RuntimeError" in caplog.text
    assert canary not in caplog.text


def test_unknown_provider_apply_status_fails_safely() -> None:
    class FutureStatusService(FakeConfigMutationService):
        def apply(self, intent):
            result = super().apply(intent)
            return ConfigApplyResult(
                status=cast(ConfigApplyStatus, "future-status"),
                summary=result.summary,
            )

    controller = ConfigWizardController(
        fake_database_workflow(), FutureStatusService()
    )
    _reach_review(controller, shared=False)

    result = controller.apply()

    assert result.status is WizardResultStatus.FAILED
    assert result.summary == "The configuration provider returned an unsupported result."
