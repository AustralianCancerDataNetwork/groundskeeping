"""Conformance and behavior tests for SchemaConfigMutationService.

Uses an in-memory ConfigSchemaAdapter -- not oa-configurator -- because
groundskeeping's own generic provider must not depend on it (see
`providers.schema`'s module docstring). A host backing this with
`PackageConfigBase` reflection and real persistence is a separate,
oa-configurator-aware adapter implemented outside this package; this suite
proves the session/revision/apply-token mechanics that adapter gets for
free are correct.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from groundskeeping.configurator import (
    ConfigSchemaConflictError,
    ConfigTarget,
    ConfigTargetKind,
    MutationConformanceHooks,
    MutationOperation,
    SchemaConfigMutationService,
    assert_mutation_service_conformance,
)
from groundskeeping.contracts.actions import (
    ChoiceOption,
    FieldKind,
    FieldSpec,
    ValidationIssue,
)


class _InMemorySchemaAdapter:
    """Fake ConfigSchemaAdapter: an in-memory stand-in for a config section."""

    def __init__(
        self,
        *,
        stored: Mapping[str, object] | None = None,
        available: bool = True,
    ) -> None:
        self._store: dict[str, object] = dict(stored or {})
        self._revision_number = 1
        self.available = available
        self.fail_save = False

    def field_specs(self) -> tuple[FieldSpec, ...]:
        return (
            FieldSpec(
                key="comparator_db",
                label="Database",
                kind=FieldKind.CHOICE,
                default="cdm_db",
                choices=(
                    ChoiceOption("cdm_db", "CDM database"),
                    ChoiceOption("other_db", "Other database"),
                ),
            ),
            FieldSpec(
                key="min_databases_default",
                label="Minimum databases",
                kind=FieldKind.INTEGER,
                default=2,
                minimum=1,
            ),
            FieldSpec(
                key="api_key",
                label="API key",
                kind=FieldKind.SECRET,
                required=False,
            ),
        )

    def load(self) -> Mapping[str, object]:
        return dict(self._store)

    def revision(self) -> str:
        if not self.available:
            raise RuntimeError("schema store is unavailable")
        return f"rev-{self._revision_number}"

    def validate(self, candidate: Mapping[str, object]) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        minimum = cast(int | None, candidate.get("min_databases_default"))
        if minimum is not None and minimum < 1:
            issues.append(
                ValidationIssue(
                    "Must be at least 1.", field_key="min_databases_default"
                )
            )
        database = candidate.get("comparator_db")
        if database not in (None, "cdm_db", "other_db"):
            issues.append(
                ValidationIssue("Unknown database entry.", field_key="comparator_db")
            )
        return tuple(issues)

    def save(
        self,
        candidate: Mapping[str, object],
        *,
        expected_revision: str,
    ) -> None:
        if expected_revision != self.revision():
            raise ConfigSchemaConflictError("stale revision")
        if self.fail_save:
            raise OSError("simulated write failure")
        self._store = dict(candidate)
        self._revision_number += 1

    def advance_revision(self) -> None:
        """Simulate another writer changing the configuration."""
        self._revision_number += 1


def _target() -> ConfigTarget:
    return ConfigTarget(
        kind=ConfigTargetKind.TOOL,
        key="plugin.comparator_recommender",
        title="Comparator Recommender",
    )


@pytest.mark.parametrize(
    "operation", (MutationOperation.CREATE, MutationOperation.UPDATE)
)
def test_schema_provider_passes_reusable_provider_conformance(
    operation: MutationOperation,
) -> None:
    def make_service() -> SchemaConfigMutationService:
        return SchemaConfigMutationService(_target(), _InMemorySchemaAdapter())

    def schema(service) -> _InMemorySchemaAdapter:
        return cast(_InMemorySchemaAdapter, service._schema)

    assert_mutation_service_conformance(
        make_service,
        _target(),
        operation,
        (
            ("identity", {"comparator_db": "cdm_db"}),
            ("limits", {"min_databases_default": 3}),
        ),
        hooks=MutationConformanceHooks(
            invalid_submission=lambda service, draft: service.submit(
                draft, "limits", {"min_databases_default": -1}
            ),
            expected_invalid_fields=frozenset({"min_databases_default"}),
            advance_revision=lambda service: schema(service).advance_revision(),
            prepare_failure=lambda service: setattr(schema(service), "fail_save", True),
            make_unavailable=lambda service: setattr(
                schema(service), "available", False
            ),
        ),
    )


def test_plan_overlays_touched_fields_on_the_current_store() -> None:
    """An update touching one field must still diff/validate the whole
    configuration, not a candidate missing every field left untouched."""

    schema = _InMemorySchemaAdapter(
        stored={"comparator_db": "cdm_db", "min_databases_default": 2}
    )
    service = SchemaConfigMutationService(_target(), schema)
    draft = service.begin(_target(), MutationOperation.UPDATE)
    service.submit(draft, "limits", {"min_databases_default": 5})

    plan = service.plan(draft)

    assert plan.ready
    assert [entry.field for entry in plan.diff.entries] == ["min_databases_default"]


def test_unknown_field_is_rejected_without_reaching_the_schema() -> None:
    service = SchemaConfigMutationService(_target(), _InMemorySchemaAdapter())
    draft = service.begin(_target(), MutationOperation.CREATE)

    result = service.submit(draft, "identity", {"nonexistent": "value"})

    assert not result.accepted
    assert {issue.field_key for issue in result.issues} == {"nonexistent"}


def test_secret_fields_are_redacted_in_the_plan_diff() -> None:
    canary = "generic-provider-secret-canary"
    service = SchemaConfigMutationService(_target(), _InMemorySchemaAdapter())
    draft = service.begin(_target(), MutationOperation.CREATE)
    service.submit(draft, "identity", {"comparator_db": "cdm_db", "api_key": canary})

    plan = service.plan(draft)

    assert canary not in repr(plan)
    entry = next(e for e in plan.diff.entries if e.field == "api_key")
    assert entry.sensitive


def test_fields_are_returned_unfiltered_regardless_of_step() -> None:
    """fields() is the whole catalog; step scoping belongs to the workflow,
    not the provider -- matching every existing ConfigMutationService."""

    service = SchemaConfigMutationService(_target(), _InMemorySchemaAdapter())
    draft = service.begin(_target(), MutationOperation.CREATE)

    keys = {spec.key for spec in service.fields(draft)}

    assert keys == {"comparator_db", "min_databases_default", "api_key"}
