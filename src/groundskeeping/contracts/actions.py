"""Generic action, field, and result contracts.

Consumers own the verbs and the effects. Groundskeeping owns the repeatable operator
sequence around those verbs: describe fields, parse input, ask policy whether to proceed,
run with progress/cancellation context, and render a generic outcome.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from groundskeeping.contracts.jobs import (
    CancellationMode,
    CancellationToken,
    ProgressEvent,
    ProgressSink,
    RecordingProgressSink,
)
from groundskeeping.contracts.views import EmptyView, SemanticStatus, SurfaceView


class FieldKind(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    CHOICE = "choice"
    EXISTING_PATH = "existing_path"
    OUTPUT_PATH = "output_path"
    SECRET = "secret"
    MULTILINE = "multiline"


class ExecutionKind(StrEnum):
    QUICK = "quick"
    BACKGROUND = "background"
    LONG_RUNNING = "long_running"


@dataclass(frozen=True)
class ChoiceOption:
    value: str
    label: str
    description: str | None = None


@dataclass(frozen=True)
class ValidationIssue:
    message: str
    field_key: str | None = None
    status: SemanticStatus = SemanticStatus.ERROR


@dataclass(frozen=True)
class ParsedField:
    key: str
    value: object
    redacted: object


Validator = Callable[[object], ValidationIssue | None]


@dataclass(frozen=True)
class FieldSpec:
    """Declarative input field used by forms and headless tests."""

    key: str
    label: str
    kind: FieldKind = FieldKind.TEXT
    required: bool = True
    default: object | None = None
    help: str | None = None
    placeholder: str | None = None
    choices: tuple[ChoiceOption, ...] = ()
    minimum: Decimal | int | None = None
    maximum: Decimal | int | None = None
    disabled: bool = False
    read_only: bool = False
    sensitive: bool = False
    secret_clearable: bool = False
    validator: Validator | None = field(default=None, compare=False, repr=False)

    @property
    def masks_value(self) -> bool:
        return self.sensitive or self.kind is FieldKind.SECRET

    def parse(self, raw: object) -> ParsedField:
        """Parse one field value and return both real and presentation-safe values."""
        value = self.default if raw in (None, "") else raw
        if value in (None, ""):
            if self.required:
                raise ValueError(f"{self.label} is required.")
            return ParsedField(self.key, None, "<redacted>" if self.masks_value else None)

        parsed = self._parse_value(value)
        issue = self.validator(parsed) if self.validator is not None else None
        if issue is not None:
            raise ValueError(issue.message)
        return ParsedField(
            key=self.key,
            value=parsed,
            redacted="<redacted>" if self.masks_value and parsed is not None else parsed,
        )

    def _parse_value(self, value: object) -> object:
        if self.kind in {FieldKind.TEXT, FieldKind.SECRET, FieldKind.MULTILINE}:
            return str(value)
        if self.kind is FieldKind.INTEGER:
            if not isinstance(value, str | int | float | Decimal):
                raise ValueError(f"{self.label} must be a whole number.")
            try:
                parsed = int(value)
            except ValueError as exc:
                raise ValueError(f"{self.label} must be a whole number.") from exc
            self._check_bounds(parsed)
            return parsed
        if self.kind is FieldKind.DECIMAL:
            try:
                parsed = Decimal(str(value))
            except InvalidOperation as exc:
                raise ValueError(f"{self.label} must be a decimal number.") from exc
            self._check_bounds(parsed)
            return parsed
        if self.kind is FieldKind.BOOLEAN:
            if isinstance(value, bool):
                return value
            normalized = str(value).strip().lower()
            if normalized in {"1", "true", "t", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "f", "no", "n", "off"}:
                return False
            raise ValueError(f"{self.label} must be true or false.")
        if self.kind is FieldKind.CHOICE:
            parsed = str(value)
            allowed = {choice.value for choice in self.choices}
            if allowed and parsed not in allowed:
                raise ValueError(f"{self.label} must be one of: {', '.join(sorted(allowed))}.")
            return parsed
        if self.kind is FieldKind.EXISTING_PATH:
            path = Path(str(value)).expanduser()
            if not path.exists():
                raise ValueError(f"{self.label} does not exist: {path}")
            return path
        if self.kind is FieldKind.OUTPUT_PATH:
            return Path(str(value)).expanduser()
        raise ValueError(f"Unsupported field kind: {self.kind}")

    def _check_bounds(self, value: Decimal | int) -> None:
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"{self.label} must be at least {self.minimum}.")
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"{self.label} must be at most {self.maximum}.")


@dataclass(frozen=True)
class Confirmation:
    title: str
    message: str
    confirm_label: str = "Run"
    dangerous: bool = False


@dataclass(frozen=True)
class ActionOutcome:
    status: SemanticStatus
    summary: str
    view: SurfaceView
    detail: object | None = None
    refresh_pages: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ActionContext:
    """Everything a runner may touch while the action is in flight.

    Deliberately narrow: a runner reports progress and checks for cancellation through this
    object, so long-running domain work never needs to import a widget or reach the app.
    """

    progress: ProgressSink
    cancellation: CancellationToken
    action_id: str

    def emit(
        self,
        event: str,
        *,
        phase: str | None = None,
        completed: int = 0,
        total: int | None = None,
        unit: str | None = None,
        message: str | None = None,
    ) -> None:
        self.progress.emit(
            ProgressEvent(
                event=event,
                phase=phase,
                completed=completed,
                total=total,
                unit=unit,
                message=message,
            )
        )


class ActionRunner(Protocol):
    def __call__(self, params: Mapping[str, object], context: ActionContext) -> object: ...


Preflight = Callable[[Mapping[str, object]], Sequence[ValidationIssue]]


@dataclass(frozen=True)
class ActionSpec:
    """Declaration of one operator-facing command and the runner that performs it.

    The spec carries everything the shell needs to present, gate, and execute the command
    without knowing what it does: fields to parse, resources and effects for the operation
    policy to reason about, and the cancellation mode the runner honours.
    """

    key: str
    page_key: str
    label: str
    summary: str
    runner: ActionRunner
    command_hint: str | None = None
    fields: tuple[FieldSpec, ...] = ()
    execution: ExecutionKind = ExecutionKind.QUICK
    cancellation: CancellationMode = CancellationMode.UNSUPPORTED
    effect_refs: frozenset[str] = frozenset()
    resource_refs: frozenset[str] = frozenset()
    preflight: Preflight | None = field(default=None, compare=False, repr=False)

    @property
    def needs_params(self) -> bool:
        return bool(self.fields)

    @property
    def long_running(self) -> bool:
        return self.execution is ExecutionKind.LONG_RUNNING

    def parse_params(self, raw: Mapping[str, object] | None = None) -> tuple[dict[str, object], dict[str, object]]:
        raw = raw or {}
        params: dict[str, object] = {}
        redacted: dict[str, object] = {}
        for spec in self.fields:
            parsed = spec.parse(raw.get(spec.key))
            params[spec.key] = parsed.value
            redacted[spec.key] = parsed.redacted
        return params, redacted


class ResultPresenter(Protocol):
    def present(self, action: ActionSpec, result: object) -> ActionOutcome: ...


class DefaultResultPresenter:
    """Present plain runner results without imposing a consumer report schema."""

    def present(self, action: ActionSpec, result: object) -> ActionOutcome:
        if isinstance(result, ActionOutcome):
            return result
        return ActionOutcome(
            status=SemanticStatus.OK,
            summary=f"{action.label} completed.",
            view=EmptyView(title=action.label, message=str(result) if result is not None else "Completed."),
        )


class OperationPolicy(Protocol):
    def describe_effects(self, action: ActionSpec, params: Mapping[str, object]) -> str: ...

    def confirmation(self, action: ActionSpec, params: Mapping[str, object]) -> Confirmation | None: ...

    def blocked_reason(
        self,
        action: ActionSpec,
        params: Mapping[str, object],
        active_jobs: Sequence[object],
    ) -> str | None: ...


class AllowAllOperationPolicy:
    """Default policy for demos and tests; production consumers should be explicit."""

    def describe_effects(self, action: ActionSpec, params: Mapping[str, object]) -> str:
        if not action.effect_refs:
            return "read-only"
        return ", ".join(sorted(action.effect_refs))

    def confirmation(self, action: ActionSpec, params: Mapping[str, object]) -> Confirmation | None:
        if not action.effect_refs:
            return None
        return Confirmation(
            title=action.label,
            message=f"Effects: {self.describe_effects(action, params)}.",
            dangerous=False,
        )

    def blocked_reason(
        self,
        action: ActionSpec,
        params: Mapping[str, object],
        active_jobs: Sequence[object],
    ) -> str | None:
        return None


class ActionRegistry:
    """Exact-key lookup for actions with startup validation."""

    def __init__(self, actions: Sequence[ActionSpec], *, page_keys: Sequence[str] | None = None) -> None:
        self._actions = tuple(actions)
        self._by_key = {action.key: action for action in self._actions}
        if len(self._actions) != len(self._by_key):
            raise ValueError("Action keys must be unique.")
        if page_keys is not None:
            allowed = set(page_keys)
            missing = sorted({action.page_key for action in self._actions} - allowed)
            if missing:
                raise ValueError(f"Actions reference unknown pages: {', '.join(missing)}")

    def get(self, key: str) -> ActionSpec:
        try:
            return self._by_key[key]
        except KeyError as exc:
            raise KeyError(f"Unknown action: {key}") from exc

    def for_page(self, page_key: str) -> tuple[ActionSpec, ...]:
        return tuple(action for action in self._actions if action.page_key == page_key)

    def __iter__(self) -> Iterator[ActionSpec]:
        return iter(self._actions)


def run_action_sync(
    action: ActionSpec,
    raw_params: Mapping[str, object] | None,
    cancellation: CancellationToken,
    *,
    presenter: ResultPresenter | None = None,
    action_id: str | None = None,
) -> ActionOutcome:
    """Run an action synchronously for tests, demos, and simple quick actions."""
    params, _redacted = action.parse_params(raw_params)
    if action.preflight is not None:
        issues = tuple(action.preflight(params))
        errors = [issue.message for issue in issues if issue.status is SemanticStatus.ERROR]
        if errors:
            raise ValueError("; ".join(errors))
    context = ActionContext(
        progress=RecordingProgressSink(),
        cancellation=cancellation,
        action_id=action_id or action.key,
    )
    result = action.runner(params, context)
    return (presenter or DefaultResultPresenter()).present(action, result)
