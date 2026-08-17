from __future__ import annotations

import pytest

from groundskeeping.configurator import (
    ConfigApplyIntent,
    ConfigApplyStatus,
    ConfigDraft,
    ConfigTarget,
    ConfigTargetKind,
    FakeConfigMutationService,
    FakeMutationScenario,
    MutationConformanceHooks,
    MutationOperation,
    MutationOperationUnsupported,
    assert_mutation_service_conformance,
)
from groundskeeping.contracts import SemanticStatus


def _target() -> ConfigTarget:
    return ConfigTarget(
        kind=ConfigTargetKind.DATABASE,
        key="metadata",
        title="Metadata database",
    )


@pytest.mark.parametrize(
    "operation", (MutationOperation.CREATE, MutationOperation.UPDATE)
)
def test_fake_passes_reusable_provider_happy_path(
    operation: MutationOperation,
) -> None:
    canary = "conformance-secret-canary"
    unsupported = (
        MutationOperation.UPDATE
        if operation is MutationOperation.CREATE
        else MutationOperation.CREATE
    )
    assert_mutation_service_conformance(
        FakeConfigMutationService,
        _target(),
        operation,
        (
            ("strategy", {"strategy": "create"}),
            (
                "create-database",
                {
                    "database_name": "analytics",
                    "connection_url": "postgresql://analytics/demo",
                    "password": canary,
                },
            ),
            ("sharing", {"shared_reference": True}),
        ),
        hooks=MutationConformanceHooks(
            invalid_submission=_invalid_submission,
            expected_invalid_fields=frozenset({"database_name", None}),
            advance_revision=lambda service: _fake(service).advance_revision(),
            prepare_warning=lambda service: _set_scenario(
                service, FakeMutationScenario.WARNING
            ),
            prepare_plan_error=lambda service: _set_scenario(
                service, FakeMutationScenario.PLAN_ERROR
            ),
            prepare_rejection=lambda service: _set_scenario(
                service, FakeMutationScenario.REJECTED
            ),
            prepare_failure=lambda service: _set_scenario(
                service, FakeMutationScenario.FAILED
            ),
            make_unavailable=lambda service: setattr(
                _fake(service), "available", False
            ),
            prepare_unsupported=lambda service: setattr(
                _fake(service), "supported_operations", frozenset({operation})
            ),
            unsupported_operation=unsupported,
        ),
        secret_canary=canary,
    )


def _fake(service) -> FakeConfigMutationService:
    assert isinstance(service, FakeConfigMutationService)
    return service


def _set_scenario(service, scenario: FakeMutationScenario) -> None:
    _fake(service).scenario = scenario


def _invalid_submission(service, draft):
    return service.submit(
        draft,
        "create-database",
        {"database_name": "reserved", "connection_url": "not-a-url"},
    )


def test_fake_diffs_a_seeded_base_against_the_same_projection() -> None:
    stored = {
        "strategy": "reuse",
        "selected_database": "metadata",
    }
    service = FakeConfigMutationService(stored={"metadata": stored})
    draft = service.begin(_target(), MutationOperation.UPDATE)
    service.submit(draft, "strategy", {"strategy": "reuse"})
    service.submit(draft, "reuse-database", {"selected_database": "analytics"})

    plan = service.plan(draft)

    assert [entry.field for entry in plan.diff.entries] == ["selected_database"]
    assert stored == {"strategy": "reuse", "selected_database": "metadata"}


def test_fake_refuses_an_unsupported_operation_with_the_typed_exception() -> None:
    service = FakeConfigMutationService(
        supported_operations=frozenset({MutationOperation.CREATE})
    )

    with pytest.raises(MutationOperationUnsupported, match="not supported"):
        service.begin(_target(), MutationOperation.UPDATE)


def test_fake_supports_create_and_update_capabilities() -> None:
    service = FakeConfigMutationService()

    capabilities = service.capabilities(_target(), MutationOperation.CREATE)
    assert capabilities.supported
    assert service.capabilities(_target(), MutationOperation.UPDATE).supported


def test_fake_reports_field_and_entry_scoped_validation() -> None:
    service = FakeConfigMutationService()
    draft = service.begin(_target(), MutationOperation.CREATE)
    result = service.submit(
        draft,
        "create-database",
        {"database_name": "reserved", "connection_url": "not-a-url"},
    )

    assert not result.accepted
    assert {issue.field_key for issue in result.issues} == {"database_name", None}


def test_warning_scenario_produces_a_ready_plan() -> None:
    service = FakeConfigMutationService(scenario=FakeMutationScenario.WARNING)
    draft = service.begin(_target(), MutationOperation.CREATE)
    service.submit(draft, "strategy", {"strategy": "reuse"})
    service.submit(draft, "reuse-database", {"selected_database": "metadata"})
    plan = service.plan(draft)

    assert plan.ready
    assert plan.warnings
    assert plan.expected_revision == service.revision


def test_error_scenario_produces_a_non_ready_plan() -> None:
    service = FakeConfigMutationService(scenario=FakeMutationScenario.PLAN_ERROR)
    draft = service.begin(_target(), MutationOperation.CREATE)
    service.submit(draft, "strategy", {"strategy": "reuse"})
    service.submit(draft, "reuse-database", {"selected_database": "metadata"})
    plan = service.plan(draft)

    assert not plan.ready
    assert plan.apply_token is None
    assert any(issue.status is SemanticStatus.ERROR for issue in plan.issues)


def test_fake_history_never_records_submitted_values() -> None:
    canary = "fake-history-secret-canary"
    service = FakeConfigMutationService()
    draft = service.begin(_target(), MutationOperation.CREATE)
    service.submit(draft, "create-database", {"password": canary})

    assert canary not in repr(service.history)


def test_durable_returns_an_isolated_snapshot() -> None:
    service = FakeConfigMutationService()
    target = _target()
    draft = service.begin(target, MutationOperation.CREATE)
    service.submit(draft, "strategy", {"strategy": "reuse"})
    staged = service.submit(
        draft, "reuse-database", {"selected_database": "metadata"}
    )
    draft = ConfigDraft(
        target=draft.target,
        operation=draft.operation,
        session_token=draft.session_token,
        changed_fields=staged.changed_fields,
        expected_revision=draft.expected_revision,
    )
    plan = service.plan(draft)
    assert plan.apply_token is not None
    result = service.apply(
        ConfigApplyIntent(
            target=target,
            operation=MutationOperation.CREATE,
            apply_token=plan.apply_token,
            expected_revision=plan.expected_revision,
        )
    )
    assert result.status is ConfigApplyStatus.APPLIED

    snapshot = service.durable
    snapshot[target.key]["selected_database"] = "tampered"
    snapshot[target.key]["added_by_caller"] = True

    assert service.durable[target.key] == {
        "strategy": "reuse",
        "selected_database": "metadata",
    }


@pytest.mark.parametrize("mismatch", ("target", "operation"))
def test_apply_rejects_intent_that_does_not_match_its_session(
    mismatch: str,
) -> None:
    service = FakeConfigMutationService()
    target = _target()
    draft = service.begin(target, MutationOperation.CREATE)
    service.submit(draft, "strategy", {"strategy": "reuse"})
    service.submit(draft, "reuse-database", {"selected_database": "metadata"})
    plan = service.plan(draft)
    assert plan.apply_token is not None

    intent = ConfigApplyIntent(
        target=(
            ConfigTarget(
                kind=ConfigTargetKind.DATABASE,
                key="other",
                title="Other database",
            )
            if mismatch == "target"
            else target
        ),
        operation=(
            MutationOperation.UPDATE
            if mismatch == "operation"
            else MutationOperation.CREATE
        ),
        apply_token=plan.apply_token,
        expected_revision=plan.expected_revision,
    )

    result = service.apply(intent)

    assert result.status is ConfigApplyStatus.REJECTED
    assert "target or operation" in result.summary
    assert service.durable == {}
    assert (
        service.apply(
            ConfigApplyIntent(
                target=target,
                operation=MutationOperation.CREATE,
                apply_token=plan.apply_token,
                expected_revision=plan.expected_revision,
            )
        ).status
        is ConfigApplyStatus.REJECTED
    )
