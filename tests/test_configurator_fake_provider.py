from __future__ import annotations

import pytest

from groundskeeping.configurator import (
    ConfigTarget,
    ConfigTargetKind,
    MutationOperation,
)
from groundskeeping.configurator.conformance import (
    assert_mutation_service_conformance,
)
from groundskeeping.configurator.providers.fake import (
    FakeConfigMutationService,
    FakeMutationScenario,
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
    assert_mutation_service_conformance(
        FakeConfigMutationService(),
        _target(),
        operation,
        (
            ("strategy", {"strategy": "reuse"}),
            ("reuse-database", {"selected_database": "metadata"}),
            ("sharing", {"shared_reference": True}),
        ),
    )


def test_fake_supports_create_and_update_capabilities() -> None:
    service = FakeConfigMutationService()

    assert service.capabilities(_target(), MutationOperation.CREATE).supported
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
