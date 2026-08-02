"""Textual-free models for presenting stack configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from groundskeeping.contracts.actions import FieldSpec, ValidationIssue
from groundskeeping.contracts.views import SemanticStatus
from groundskeeping.contracts.wizards import WizardController

EffectRef = str


@dataclass(frozen=True)
class RedactedValue:
    """Marker used when a known secret must not enter ordinary view models."""

    label: str = "<redacted>"

    def __str__(self) -> str:
        return self.label


@dataclass(frozen=True)
class ConfigTarget:
    """One selectable configuration target."""

    kind: str
    key: str
    title: str
    status: SemanticStatus = SemanticStatus.INFO


@dataclass(frozen=True)
class ConfigSectionView:
    """Read-only view of one configuration section."""

    target: ConfigTarget
    fields: Mapping[str, object] = field(default_factory=dict)
    children: tuple[ConfigSectionView, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfiguratorSnapshot:
    """Read-only snapshot of an effective `oa-configurator` stack."""

    title: str
    profile: str | None
    path: str | None
    sections: tuple[ConfigSectionView, ...]


@dataclass(frozen=True)
class ConfigDraft:
    """Presentation-safe description of an edit session.

    The expected revision is opaque on purpose. `oa-configurator` owns how a real file or
    in-memory stack is fingerprinted; the widget only carries the token back when asking
    a public mutation service to apply the draft.

    The real candidate object belongs to the consumer-owned wizard/controller. This draft
    only names the safe target and records which fields are changed.
    """

    target: ConfigTarget
    changed_fields: frozenset[str] = frozenset()
    expected_revision: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.changed_fields)


@dataclass(frozen=True)
class ConfigDiffEntry:
    field: str
    before: object
    after: object
    sensitive: bool = False


@dataclass(frozen=True)
class ConfigDiff:
    target: ConfigTarget
    entries: tuple[ConfigDiffEntry, ...]

    @property
    def changed(self) -> bool:
        return bool(self.entries)


@dataclass(frozen=True)
class ConfigApplyIntent:
    """UI-level request to apply a validated draft through `oa-configurator`."""

    target: ConfigTarget
    apply_token: str
    expected_revision: str | None
    diff: ConfigDiff
    effects: tuple[EffectRef, ...] = ()


class ConfigResourceAdapter(Protocol):
    """Consumer extension point for richer resource-specific presentation."""

    key: str

    def supports(self, target: ConfigTarget) -> bool: ...

    def describe(self, target: ConfigTarget) -> ConfigSectionView: ...

    def fields(self, target: ConfigTarget) -> tuple[FieldSpec, ...]: ...

    def validate(self, draft: ConfigDraft) -> tuple[ValidationIssue, ...]: ...

    def post_apply_effects(self, draft: ConfigDraft) -> tuple[EffectRef, ...]: ...

    def wizard_controller(self, target: ConfigTarget) -> WizardController | None: ...
