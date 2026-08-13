from __future__ import annotations

from dataclasses import asdict
from typing import cast

import pytest

from groundskeeping.configurator import (
    ConfigApplyResult,
    ConfigApplyStatus,
    ConfigBranchCondition,
    ConfigTarget,
    ConfigTargetKind,
    ConfigWizardController,
    ConfigWorkflowSpec,
    ConfigWorkflowStep,
    EffectRef,
    MutationOperation,
)
from groundskeeping.configurator.providers.fake import (
    FakeConfigMutationService,
    FakeDialectConfigMutationService,
    FakeMutationScenario,
    fake_database_workflow,
    fake_dialect_database_workflow,
)
from groundskeeping.contracts import (
    ChoiceStep,
    FormStep,
    ReviewStep,
    WizardDefinitionError,
    WizardResultStatus,
)


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
    controller, _ = _controller(scenario=scenario)
    _reach_review(controller, shared=False)

    result = controller.apply()

    assert result.status is expected
    assert not result.applied


def test_revision_change_is_a_conflict_not_an_operational_failure() -> None:
    controller, service = _controller()
    _reach_review(controller, shared=False)
    service.advance_revision()

    result = controller.apply()

    assert result.status is WizardResultStatus.CONFLICTED
    assert "Reload" in str(result.detail)


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
