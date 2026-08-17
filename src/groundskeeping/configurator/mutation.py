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
    """Build a diff after replacing every declared sensitive value.

    Both mappings must come from the same projection of the same configuration shape.
    A field absent from one side and present on the other is reported as a change, so
    projecting the two sides differently produces a diff that is wrong in both
    directions.

    The usual way to get this wrong is to normalise only one side — flattening the
    stored base with something like ``exclude_none=True`` while the candidate comes
    back from a validator with every default materialised. Every defaulted field then
    appears as ``None -> <default>``. Flatten both sides through the same call, with
    the same options, before calling this function.

    ``sensitive_fields`` is the set of field keys whose values must never be rendered;
    both sides of such an entry are replaced with :class:`RedactedValue`, which also
    means a sensitive field that changed is still reported as a change.
    """

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

    ``future_fields`` may replace presentation descriptors for later, uncompleted
    workflow fields after an accepted step. The controller rejects callbacks, changes
    to completed fields, and changes that weaken a field's kind or sensitivity.
    """

    issues: tuple[ValidationIssue, ...] = ()
    changed_fields: frozenset[str] = frozenset()
    future_fields: tuple[FieldSpec, ...] = ()

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
    """How one apply attempt ended.

    A host renders different remediation for each member, so a provider must classify
    its errors rather than reach for the nearest label. Two questions separate the four:
    was anything written, and if not, was the request itself at fault?

    | Status | Meaning | Typical cause |
    |---|---|---|
    | `APPLIED` | The change was persisted. | — |
    | `CONFLICTED` | The stored configuration changed after the plan was prepared; the expected revision no longer matches. Nothing was written. | Another writer saved between plan and apply. |
    | `REJECTED` | The request itself was not acceptable, and no write was attempted. | Consumed or unknown apply token, intent not matching the prepared plan, candidate failing validation, ownership or policy forbidding the write. |
    | `FAILED` | The write was attempted and errored. The previous configuration remains authoritative. | Filesystem permissions, disk full, I/O error, serialisation failure. |
    """

    APPLIED = "applied"
    """The change was persisted; the stored configuration now reflects it."""

    CONFLICTED = "conflicted"
    """The stored revision moved after planning. Nothing was written."""

    REJECTED = "rejected"
    """The request was not acceptable, and no write was attempted."""

    FAILED = "failed"
    """The write was attempted and errored; the previous configuration stands."""


@dataclass(frozen=True)
class ConfigApplyResult:
    """Portable outcome returned by a mutation provider.

    ``summary`` and ``detail`` are rendered to the operator and written to application
    logs, so both must be presentation-safe: no submitted values, no secrets, no
    provider tracebacks, no absolute paths a host would not otherwise disclose.

    ``summary`` says what happened in one line. ``detail`` carries the operator's next
    action and should be present whenever the status is not ``APPLIED`` — "Reload the
    configuration and review the change again" for a conflict, "Grant write access to
    the configuration directory and retry" for a failure. Omit it when there is nothing
    useful to add; do not restate ``summary``.

    ``refresh_pages`` names the host page keys whose data this change invalidated.
    """

    status: ConfigApplyStatus
    summary: str
    detail: str | None = None
    refresh_pages: frozenset[str] = frozenset()


class UnavailableMutationService(RuntimeError):
    """The provider exists but cannot currently serve mutation requests.

    Raise this when the whole service is out of action — an unreadable or malformed
    configuration file, a backing store that cannot be reached. It is not the way to
    refuse one operation; see :class:`MutationOperationUnsupported`.
    """


class MutationOperationUnsupported(ValueError):
    """This provider will not begin this operation on this target.

    Raise this from ``begin()`` when the operation is legitimately unavailable — the
    entry already exists and the provider only creates, the entry does not exist and
    the provider only updates, the configuration is read-only, or policy forbids the
    change. The message is shown to the operator, so it must be presentation-safe and
    say why.

    It subclasses ``ValueError`` so hosts that already catch ``ValueError`` around
    ``begin()`` keep working, but a typed refusal lets a host separate "not available
    right now" from a programming error it should surface as a bug.

    ``capabilities()`` answers the same question without raising, and a host that calls
    it first will normally never see this. Providers should raise it anyway: a
    capability answer can go stale between the check and the call.
    """


class ConfigMutationService(Protocol):
    """Provider boundary for configuration candidate state and persistence.

    Implementations must consume an apply token at the start of every apply attempt,
    including conflict, rejection, and failure. ``submit`` may inspect real values only
    for the duration of the call; the service owns any candidate state retained behind
    ``draft.session_token``. Returned objects must be safe to render and log.

    Every method may raise :class:`UnavailableMutationService` when the provider as a
    whole cannot serve requests. ``begin()`` additionally raises
    :class:`MutationOperationUnsupported` to refuse one operation. Any other exception
    is treated as a provider defect: the controller logs it without its message and
    shows the operator a generic failure, so a condition a host should act on must use
    one of the two typed exceptions.
    """

    def capabilities(
        self, target: ConfigTarget, operation: MutationOperation
    ) -> MutationCapabilities:
        """Report whether one operation is available for one target.

        This is the non-raising way to ask what ``begin()`` would do. It still raises
        :class:`UnavailableMutationService` when the provider cannot answer at all.
        """
        ...

    def begin(
        self, target: ConfigTarget, operation: MutationOperation
    ) -> ConfigDraft:
        """Open a provider-owned candidate session and capture its base revision.

        Raises:
            MutationOperationUnsupported: The operation is not available for this
                target — already exists, does not exist, read-only, or forbidden by
                policy. The message is shown to the operator.
            UnavailableMutationService: The provider cannot serve requests at all.
        """
        ...

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


def resolve_operation(
    service: ConfigMutationService, target: ConfigTarget
) -> MutationOperation:
    """Return the operation a host should use for ``target``: update it, or create it.

    A :class:`~groundskeeping.configurator.controller.ConfigWorkflowSpec` is built for
    one fixed operation, so a host that offers a single "Configure" action must decide
    which one before constructing the controller. This encodes that decision once:
    ``UPDATE`` when the provider supports updating this target, ``CREATE`` otherwise.

    ```python
    operation = resolve_operation(service, target)
    controller = ConfigWizardController(workflow(operation), service)
    ```

    Checking ``UPDATE`` first is deliberate. A provider that supports both reports both
    as supported, and updating an entry the operator already has is the safer default.

    A host that wants create-only or update-only behaviour should keep passing an
    explicit operation instead of calling this — the controller then blocks with the
    provider's own reason when that operation is unsupported, which is the correct
    outcome for a "Create database" action aimed at a database that already exists.

    Raises:
        UnavailableMutationService: The provider cannot answer capability questions.
    """

    if service.capabilities(target, MutationOperation.UPDATE).supported:
        return MutationOperation.UPDATE
    return MutationOperation.CREATE
