"""Textual-free models for presenting stack configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from groundskeeping.contracts.views import SemanticStatus


class ConfigTargetKind(StrEnum):
    """Stable kinds a configuration provider may expose for inspection."""

    CONNECTION = "connection"
    DATABASE = "database"
    PROVIDER = "provider"
    MODEL = "model"
    VECTOR_STORE = "vector_store"
    TOOL = "tool"
    LOGGING = "logging"


class ConfigReferenceStatus(StrEnum):
    """Whether a named configuration reference resolves in the inspected stack."""

    RESOLVED = "resolved"
    MISSING = "missing"
    WRONG_KIND = "wrong kind"


@dataclass(frozen=True)
class ConfigReferenceView:
    """Presentation-safe description of one ``RefTo`` field."""

    section: ConfigTargetKind
    name: str
    status: ConfigReferenceStatus
    expected_type: str
    actual_type: str | None = None

    def __str__(self) -> str:
        reference = f"{self.section.value}:{self.name}"
        if self.status is ConfigReferenceStatus.WRONG_KIND and self.actual_type:
            return f"{reference} ({self.status.value}: {self.actual_type})"
        return f"{reference} ({self.status.value})"


@dataclass(frozen=True)
class RedactedValue:
    """Marker used when a known secret must not enter ordinary view models."""

    label: str = "<redacted>"

    def __str__(self) -> str:
        return self.label


@dataclass(frozen=True)
class ConfigTarget:
    """One selectable configuration target."""

    kind: ConfigTargetKind
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
    """Read-only snapshot of an effective `oa-configurator` stack.

    ``path`` records where the inspected configuration came from. It is display
    metadata only and must not be interpreted as an instruction to write there.
    """

    title: str
    path: str | None
    sections: tuple[ConfigSectionView, ...]
