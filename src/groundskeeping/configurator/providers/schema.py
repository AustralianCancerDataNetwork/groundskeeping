"""The seam a host implements to get a generic ConfigMutationService for free.

Groundskeeping owns the operator sequence, not the configuration candidate
(see `mutation.py`'s module docstring), and editable candidates and
persistence explicitly remain outside groundskeeping (see
`adapter.OAConfiguratorAdapter`'s docstring). `SchemaConfigMutationService`
in `generic.py` is the generic operator-sequence side of that split: it
handles sessions, revision-conflict detection, apply-token single-use, and
diffing exactly once. Everything that requires knowing what the
configuration actually *is* -- field descriptions, current values,
validation, persistence -- is this protocol, implemented by a host.

Nothing here is oa-configurator-shaped. A host backed by `PackageConfigBase`
implements it by reflecting over pydantic fields and calling
`validate_candidate`/its own save path; a host with a completely different
configuration format could implement the same protocol just as easily.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from groundskeeping.contracts.actions import FieldSpec, ValidationIssue


class ConfigSchemaConflictError(RuntimeError):
    """The schema changed after the candidate was prepared."""


class ConfigSchemaRejectedError(ValueError):
    """The schema rejected the prepared candidate before attempting a write."""


class ConfigSchemaAdapter(Protocol):
    """One configuration target's shape, current state, and persistence."""

    def field_specs(self) -> tuple[FieldSpec, ...]:
        """Describe every field this schema has, regardless of workflow step.

        `SchemaConfigMutationService.fields()` returns this unfiltered, the
        same way `ConfigMutationService.fields()` already works for every
        existing provider -- step-scoping is a `ConfigWorkflowStep` concern,
        not something the provider itself tracks.
        """
        ...

    def load(self) -> Mapping[str, object]:
        """Return the currently persisted values, for diffing against a candidate.

        Must be projected the same way `validate`'s candidate view is -- see
        `assert_mutation_service_conformance`'s projection-symmetry check,
        which fails loudly if the two sides disagree on which fields are
        materialised.
        """
        ...

    def revision(self) -> str:
        """Return an opaque marker that changes whenever the persisted values do.

        Read fresh, not cached -- this is what lets the generic provider
        detect a write from outside its own session.
        """
        ...

    def validate(self, candidate: Mapping[str, object]) -> tuple[ValidationIssue, ...]:
        """Validate a fully-merged candidate. Empty means it is acceptable."""
        ...

    def save(
        self,
        candidate: Mapping[str, object],
        *,
        expected_revision: str,
    ) -> None:
        """Compare and persist candidate as the new stored values.

        The comparison and write belong in this one adapter operation. Splitting
        them into ``revision()`` followed by ``save()`` leaves a race in which a
        second writer can commit between the two calls. Raise
        :class:`ConfigSchemaConflictError` when the expected revision is stale,
        and :class:`ConfigSchemaRejectedError` when policy or validation rejects
        the request before a write is attempted. Other exceptions are treated as
        attempted-write failures by the generic provider.
        """
        ...
