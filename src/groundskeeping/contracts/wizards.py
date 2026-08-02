"""Textual-free contracts for consumer-owned setup wizards."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol

from groundskeeping.contracts.actions import FieldSpec, ValidationIssue
from groundskeeping.contracts.views import SemanticStatus


class WizardStepKind(StrEnum):
    FORM = "form"
    CHOICE = "choice"
    REVIEW = "review"


class WizardResultStatus(StrEnum):
    APPLIED = "applied"
    CANCELLED = "cancelled"
    CONFLICTED = "conflicted"
    FAILED = "failed"


@dataclass(frozen=True)
class WizardSpec:
    """Stable wizard identity and operator-facing copy."""

    key: str
    title: str
    purpose: str
    apply_label: str = "Apply"


@dataclass(frozen=True)
class Choice:
    key: str
    label: str
    description: str


@dataclass(frozen=True)
class FormStep:
    key: str
    title: str
    fields: tuple[FieldSpec, ...]
    purpose: str | None = None
    kind: Literal[WizardStepKind.FORM] = WizardStepKind.FORM


@dataclass(frozen=True)
class ChoiceStep:
    key: str
    title: str
    choices: tuple[Choice, ...]
    purpose: str | None = None
    kind: Literal[WizardStepKind.CHOICE] = WizardStepKind.CHOICE


@dataclass(frozen=True)
class ReviewChange:
    field: str
    before: object
    after: object
    sensitive: bool = False

    def __repr__(self) -> str:
        before = "<redacted>" if self.sensitive else repr(self.before)
        after = "<redacted>" if self.sensitive else repr(self.after)
        return (
            "ReviewChange("
            f"field={self.field!r}, before={before}, after={after}, "
            f"sensitive={self.sensitive!r})"
        )


@dataclass(frozen=True)
class WizardReview:
    """Presentation-safe review data. Real candidates stay in the controller."""

    changes: tuple[ReviewChange, ...] = ()
    effects: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    ready_to_apply: bool = True


@dataclass(frozen=True)
class ReviewStep:
    key: str
    title: str
    review: WizardReview
    purpose: str | None = None
    kind: Literal[WizardStepKind.REVIEW] = WizardStepKind.REVIEW


WizardStep = FormStep | ChoiceStep | ReviewStep


@dataclass(frozen=True)
class WizardSnapshot:
    """Complete render state for one wizard moment."""

    spec: WizardSpec
    step: WizardStep
    step_index: int
    step_count: int
    values: Mapping[str, object] = field(default_factory=dict)
    issues: tuple[ValidationIssue, ...] = ()
    can_back: bool = False
    can_next: bool = True
    can_apply: bool = False
    expected_revision: str | None = None

    def __post_init__(self) -> None:
        if self.step_count < 1:
            raise ValueError("WizardSnapshot.step_count must be at least 1.")
        if not 0 <= self.step_index < self.step_count:
            raise ValueError("WizardSnapshot.step_index must be inside step_count.")


@dataclass(frozen=True)
class WizardTransition:
    snapshot: WizardSnapshot
    issues: tuple[ValidationIssue, ...] = ()


@dataclass(frozen=True)
class WizardResult:
    status: WizardResultStatus
    summary: str
    detail: object | None = None
    refresh_pages: frozenset[str] = frozenset()

    @property
    def applied(self) -> bool:
        return self.status is WizardResultStatus.APPLIED


class WizardController(Protocol):
    """Consumer-owned state machine for one wizard session."""

    @property
    def spec(self) -> WizardSpec: ...

    def start(self) -> WizardSnapshot: ...

    def submit(self, values: Mapping[str, object]) -> WizardTransition: ...

    def back(self) -> WizardSnapshot: ...

    def review(self) -> WizardTransition: ...

    def apply(self) -> WizardResult: ...

    def cancel(self) -> WizardResult: ...


class WizardDefinitionError(ValueError):
    """Raised when a wizard declares duplicate or unusable keys."""


def validate_wizard_steps(steps: Sequence[WizardStep]) -> None:
    if not steps:
        raise WizardDefinitionError("A wizard requires at least one step.")
    step_keys = [step.key for step in steps]
    duplicates = sorted({key for key in step_keys if step_keys.count(key) > 1})
    if duplicates:
        raise WizardDefinitionError(f"Wizard step keys must be unique: {duplicates}")
    for step in steps:
        if isinstance(step, FormStep):
            field_keys = [field.key for field in step.fields]
            duplicate_fields = sorted(
                {key for key in field_keys if field_keys.count(key) > 1}
            )
            if duplicate_fields:
                raise WizardDefinitionError(
                    f"Form step {step.key!r} has duplicate field keys: {duplicate_fields}"
                )
        if isinstance(step, ChoiceStep) and not step.choices:
            raise WizardDefinitionError(f"Choice step {step.key!r} requires choices.")
        if isinstance(step, ChoiceStep):
            choice_keys = [choice.key for choice in step.choices]
            duplicate_choices = sorted(
                {key for key in choice_keys if choice_keys.count(key) > 1}
            )
            if duplicate_choices:
                raise WizardDefinitionError(
                    f"Choice step {step.key!r} has duplicate choice keys: "
                    f"{duplicate_choices}"
                )


def redact_wizard_value(field: FieldSpec, value: object) -> object:
    """Return the presentation value for a field without exposing secrets."""

    if field.masks_value:
        return "configured" if value not in (None, "") else "not configured"
    return value


def issues_status(issues: Sequence[ValidationIssue]) -> SemanticStatus:
    if any(issue.status == SemanticStatus.ERROR for issue in issues):
        return SemanticStatus.ERROR
    if issues:
        return SemanticStatus.WARNING
    return SemanticStatus.OK
