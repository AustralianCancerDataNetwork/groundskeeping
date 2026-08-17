"""The conformance suite must fail the provider mistakes it exists to prevent.

Each test builds a provider that is correct except for one contract breach, then asserts
the suite names the cause rather than the symptom.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from groundskeeping.configurator import (
    ConfigApplyIntent,
    ConfigApplyResult,
    ConfigDraft,
    ConfigTarget,
    ConfigTargetKind,
    FakeConfigMutationService,
    MutationCapabilities,
    MutationConformanceError,
    MutationConformanceHooks,
    MutationOperation,
    assert_mutation_service_conformance,
    resolve_operation,
)

SUBMISSIONS: Sequence[tuple[str, Mapping[str, object]]] = (
    ("strategy", {"strategy": "create"}),
    (
        "create-database",
        {
            "database_name": "analytics",
            "connection_url": "postgresql://analytics/demo",
            "password": "conformance-secret-canary",
        },
    ),
    ("sharing", {"shared_reference": True}),
)


def _target() -> ConfigTarget:
    return ConfigTarget(
        kind=ConfigTargetKind.DATABASE,
        key="metadata",
        title="Metadata database",
    )


class AsymmetricProjectionService(FakeConfigMutationService):
    """Persist a package default the candidate projection never carries."""

    def apply(self, intent: ConfigApplyIntent) -> ConfigApplyResult:
        result = super().apply(intent)
        stored = self._durable.get(intent.target.key)
        if stored is not None:
            stored["mcp.port"] = 8000
        return result


class CreateOnlyService(FakeConfigMutationService):
    """Refuse to create a target that already exists, as a real provider would."""

    def capabilities(
        self, target: ConfigTarget, operation: MutationOperation
    ) -> MutationCapabilities:
        capabilities = super().capabilities(target, operation)
        if operation is MutationOperation.CREATE and target.key in self._durable:
            return MutationCapabilities(
                target=target,
                operation=operation,
                supported=False,
                reason="That configuration entry already exists.",
            )
        return capabilities


class UntypedRefusalService(FakeConfigMutationService):
    """Refuse an unsupported operation without the contract's typed exception."""

    def begin(
        self, target: ConfigTarget, operation: MutationOperation
    ) -> ConfigDraft:
        if operation not in self.supported_operations:
            raise ValueError("Update is not supported.")
        return super().begin(target, operation)


class PermissiveBeginService(FakeConfigMutationService):
    """Advertise an operation as unsupported, then open a session for it anyway."""

    def begin(
        self, target: ConfigTarget, operation: MutationOperation
    ) -> ConfigDraft:
        supported = self.supported_operations
        self.supported_operations = frozenset(MutationOperation)
        try:
            return super().begin(target, operation)
        finally:
            self.supported_operations = supported


def test_conformance_detects_a_one_sided_projection() -> None:
    with pytest.raises(MutationConformanceError) as error:
        assert_mutation_service_conformance(
            AsymmetricProjectionService,
            _target(),
            MutationOperation.CREATE,
            SUBMISSIONS,
        )

    message = str(error.value)
    assert "not projected the same way" in message
    assert "build_config_diff" in message


def test_projection_check_skips_a_provider_that_cannot_repeat_its_operation() -> None:
    assert_mutation_service_conformance(
        CreateOnlyService,
        _target(),
        MutationOperation.CREATE,
        SUBMISSIONS,
    )


def test_conformance_requires_a_typed_refusal_from_begin() -> None:
    with pytest.raises(MutationConformanceError) as error:
        assert_mutation_service_conformance(
            lambda: UntypedRefusalService(
                supported_operations=frozenset({MutationOperation.CREATE})
            ),
            _target(),
            MutationOperation.CREATE,
            SUBMISSIONS,
            hooks=MutationConformanceHooks(
                unsupported_operation=MutationOperation.UPDATE
            ),
        )

    message = str(error.value)
    assert "ValueError instead of MutationOperationUnsupported" in message
    assert "Update is not supported" not in message


def test_conformance_requires_begin_to_honour_its_own_capabilities() -> None:
    with pytest.raises(MutationConformanceError, match="reported as unsupported"):
        assert_mutation_service_conformance(
            lambda: PermissiveBeginService(
                supported_operations=frozenset({MutationOperation.CREATE})
            ),
            _target(),
            MutationOperation.CREATE,
            SUBMISSIONS,
            hooks=MutationConformanceHooks(
                unsupported_operation=MutationOperation.UPDATE
            ),
        )


def test_resolve_operation_prefers_update_and_falls_back_to_create() -> None:
    both = FakeConfigMutationService()
    create_only = FakeConfigMutationService(
        supported_operations=frozenset({MutationOperation.CREATE})
    )

    assert resolve_operation(both, _target()) is MutationOperation.UPDATE
    assert resolve_operation(create_only, _target()) is MutationOperation.CREATE
