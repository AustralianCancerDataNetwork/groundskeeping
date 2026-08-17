"""Provider-neutral contracts for safe configuration write flows.

Groundskeeping owns the operator sequence, not the configuration candidate. A mutation
service keeps real candidate state behind an opaque session token and returns only
presentation-safe plans and results. Submitted values are method arguments rather than
dataclass fields so they cannot accidentally settle in snapshots, reprs, or widget state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from groundskeeping.configurator.models import ConfigTarget, RedactedValue
from groundskeeping.contracts.actions import FieldSpec, ValidationIssue
from groundskeeping.contracts.views import SemanticStatus


class MutationOperation(StrEnum):
    """A portable configuration operation."""

    CREATE = "create"
    UPDATE = "update"


@dataclass(frozen=True)
class MutationCapabilities:
    """Whether one operation is available for one target."""

    target: ConfigTarget
    operation: MutationOperation
    supported: bool
    reason: str | None = None


@dataclass(frozen=True)
class EffectRef:
    """A structural, presentation-safe impact between configuration targets."""

    impact_kind: str
    source_target: ConfigTarget
    label: str
    destination_target: ConfigTarget | None = None
    field_key: str | None = None
    status: SemanticStatus = SemanticStatus.INFO

    def __str__(self) -> str:
        subject = f"{self.source_target.kind.value}:{self.source_target.key}"
        if self.field_key:
            subject = f"{subject}.{self.field_key}"
        destination = ""
        if self.destination_target is not None:
            destination = (
                f" → {self.destination_target.kind.value}:"
                f"{self.destination_target.key}"
            )
        return f"{self.impact_kind}: {subject}{destination} — {self.label}"


@dataclass(frozen=True)
class ConfigDraft:
    """Safe identity and progress for provider-owned candidate state."""

    target: ConfigTarget
    operation: MutationOperation
    session_token: str
    changed_fields: frozenset[str] = frozenset()
    expected_revision: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.changed_fields)


@dataclass(frozen=True)
class ConfigDiffEntry:
    """One presentation-safe change in a configuration plan."""

    field: str
    before: object
    after: object
    sensitive: bool = False

    def __post_init__(self) -> None:
        if self.sensitive:
            object.__setattr__(self, "before", RedactedValue())
            object.__setattr__(self, "after", RedactedValue())

    def __repr__(self) -> str:
        return (
            "ConfigDiffEntry("
            f"field={self.field!r}, before={self.before!r}, after={self.after!r}, "
            f"sensitive={self.sensitive!r})"
        )


@dataclass(frozen=True)
class ConfigDiff:
    """A redacted structural diff suitable for review UI."""

    target: ConfigTarget
    entries: tuple[ConfigDiffEntry, ...]

    @property
    def changed(self) -> bool:
        return bool(self.entries)


def build_config_diff(
    target: ConfigTarget,
    original_fields: Mapping[str, object],
    candidate_fields: Mapping[str, object],
    *,
    sensitive_fields: frozenset[str] = frozenset(),
) -> ConfigDiff:
    """Build a diff after replacing every declared sensitive value."""

    entries: list[ConfigDiffEntry] = []
    for field in sorted(set(original_fields) | set(candidate_fields)):
        before = original_fields.get(field)
        after = candidate_fields.get(field)
        if before == after:
            continue
        sensitive = (
            field in sensitive_fields
            or isinstance(before, RedactedValue)
            or isinstance(after, RedactedValue)
        )
        entries.append(
            ConfigDiffEntry(
                field=field,
                before=RedactedValue() if sensitive else before,
                after=RedactedValue() if sensitive else after,
                sensitive=sensitive,
            )
        )
    return ConfigDiff(target=target, entries=tuple(entries))


@dataclass(frozen=True)
class ConfigStepResult:
    """Presentation-safe outcome of staging one wizard step.

    ``changed_fields`` is the complete current set for the provider session, not only
    the fields submitted in this call. This lets a provider account for defaults,
    unchanged updates, and branch invalidation without exposing candidate values.
    """

    issues: tuple[ValidationIssue, ...] = ()
    changed_fields: frozenset[str] = frozenset()

    @property
    def accepted(self) -> bool:
        return not any(issue.status is SemanticStatus.ERROR for issue in self.issues)


@dataclass(frozen=True)
class ConfigPlan:
    """Provider-produced, presentation-safe plan for an apply attempt."""

    target: ConfigTarget
    operation: MutationOperation
    diff: ConfigDiff
    effects: tuple[EffectRef, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()
    warnings: tuple[str, ...] = ()
    apply_token: str | None = None
    expected_revision: str | None = None

    @property
    def ready(self) -> bool:
        has_error = any(
            issue.status is SemanticStatus.ERROR for issue in self.issues
        )
        return (
            self.apply_token is not None
            and self.expected_revision is not None
            and not has_error
        )


@dataclass(frozen=True)
class ConfigApplyIntent:
    """Opaque, revision-aware request to apply a previously prepared plan."""

    target: ConfigTarget
    operation: MutationOperation
    apply_token: str
    expected_revision: str | None


class ConfigApplyStatus(StrEnum):
    APPLIED = "applied"
    CONFLICTED = "conflicted"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class ConfigApplyResult:
    """Portable outcome returned by a mutation provider."""

    status: ConfigApplyStatus
    summary: str
    detail: str | None = None
    refresh_pages: frozenset[str] = frozenset()


class UnavailableMutationService(RuntimeError):
    """The provider exists but cannot currently serve mutation requests."""


class ConfigMutationService(Protocol):
    """Provider boundary for configuration candidate state and persistence.

    Implementations must consume an apply token at the start of every apply attempt,
    including conflict, rejection, and failure. ``submit`` may inspect real values only
    for the duration of the call; the service owns any candidate state retained behind
    ``draft.session_token``. Returned objects must be safe to render and log.
    """

    def capabilities(
        self, target: ConfigTarget, operation: MutationOperation
    ) -> MutationCapabilities: ...

    def begin(
        self, target: ConfigTarget, operation: MutationOperation
    ) -> ConfigDraft: ...

    def fields(self, draft: ConfigDraft) -> tuple[FieldSpec, ...]: ...

    def submit(
        self,
        draft: ConfigDraft,
        step_key: str,
        values: Mapping[str, object],
        *,
        discard_fields: frozenset[str] = frozenset(),
    ) -> ConfigStepResult: ...

    def plan(self, draft: ConfigDraft) -> ConfigPlan: ...

    def apply(self, intent: ConfigApplyIntent) -> ConfigApplyResult: ...

    def cancel(self, draft: ConfigDraft) -> None: ...
