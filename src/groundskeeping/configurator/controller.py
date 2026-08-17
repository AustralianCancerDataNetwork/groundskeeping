"""Generic configuration wizard built over :mod:`.mutation` contracts.

The workflow is declarative: applications group provider field keys into ordered steps
and attach simple equality conditions for branches. Groundskeeping owns safe navigation
state and branch recalculation. Providers own validation, candidate values, planning, and
apply semantics. There is intentionally no callback-shaped branching API and no provider
candidate object crosses this module.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from groundskeeping.configurator.models import ConfigTarget
from groundskeeping.configurator.mutation import (
    ConfigApplyIntent,
    ConfigApplyStatus,
    ConfigDraft,
    ConfigMutationService,
    ConfigPlan,
    MutationOperation,
    UnavailableMutationService,
)
from groundskeeping.contracts.actions import FieldKind, FieldSpec, ValidationIssue
from groundskeeping.contracts.views import SemanticStatus
from groundskeeping.contracts.wizards import (
    Choice,
    ChoiceStep,
    FormStep,
    ReviewChange,
    ReviewStep,
    WizardDefinitionError,
    WizardResult,
    WizardResultStatus,
    WizardReview,
    WizardSnapshot,
    WizardSpec,
    WizardTransition,
    redact_wizard_value,
)


class ConfigWorkflowStepKind(StrEnum):
    FORM = "form"
    CHOICE = "choice"


@dataclass(frozen=True)
class ConfigBranchCondition:
    """Show a step when an earlier field is in, or outside, a set of values."""

    field_key: str
    values: frozenset[object]
    negated: bool = False

    def matches(self, value: object) -> bool:
        matched = value in self.values
        return not matched if self.negated else matched


@dataclass(frozen=True)
class ConfigWorkflowStep:
    """Declarative grouping of provider fields into one wizard step."""

    key: str
    title: str
    field_keys: tuple[str, ...]
    purpose: str | None = None
    kind: ConfigWorkflowStepKind = ConfigWorkflowStepKind.FORM
    when: tuple[ConfigBranchCondition, ...] = ()


@dataclass(frozen=True)
class ConfigWorkflowSpec:
    """Application-owned copy and branching for a generic write flow."""

    key: str
    target: ConfigTarget
    operation: MutationOperation
    title: str
    purpose: str
    steps: tuple[ConfigWorkflowStep, ...]
    apply_label: str = "Apply"


class ConfigWizardController:
    """Drive one provider-owned mutation session through the generic wizard UI."""

    def __init__(
        self,
        workflow: ConfigWorkflowSpec,
        service: ConfigMutationService,
    ) -> None:
        self.workflow = workflow
        self.service = service
        self.spec = WizardSpec(
            key=workflow.key,
            title=workflow.title,
            purpose=workflow.purpose,
            apply_label=workflow.apply_label,
        )
        self._fields: dict[str, FieldSpec] = {}
        self._display_values: dict[str, object] = {}
        self._completed_steps: set[str] = set()
        self._current_step_key: str | None = None
        self._draft: ConfigDraft | None = None
        self._plan: ConfigPlan | None = None
        self._issues: tuple[ValidationIssue, ...] = ()
        self._blocked_reason: str | None = None
        self._started = False
        self._closed = False
        self._apply_consumed = False
        self._validate_workflow_shape()

    def start(self) -> WizardSnapshot:
        if self._started:
            return self._snapshot()
        self._started = True
        try:
            capabilities = self.service.capabilities(
                self.workflow.target, self.workflow.operation
            )
        except UnavailableMutationService as exc:
            self._blocked_reason = str(exc) or "Configuration changes are unavailable."
            return self._snapshot()
        except Exception as exc:  # noqa: BLE001
            _log_provider_failure("capability discovery", exc)
            self._blocked_reason = "The configuration provider could not start a change."
            return self._snapshot()
        if (
            capabilities.target != self.workflow.target
            or capabilities.operation is not self.workflow.operation
        ):
            raise ValueError(
                "Mutation provider returned capabilities for the wrong target or operation."
            )
        if not capabilities.supported:
            self._blocked_reason = capabilities.reason or (
                f"{self.workflow.operation.value.title()} is not supported for this target."
            )
            return self._snapshot()

        try:
            draft = self.service.begin(
                self.workflow.target, self.workflow.operation
            )
        except UnavailableMutationService as exc:
            self._blocked_reason = str(exc) or "Configuration changes are unavailable."
            return self._snapshot()
        except Exception as exc:  # noqa: BLE001
            _log_provider_failure("session creation", exc)
            self._blocked_reason = "The configuration provider could not start a change."
            return self._snapshot()
        try:
            self._validate_draft(draft)
        except ValueError:
            try:
                self.service.cancel(draft)
            except Exception as exc:  # noqa: BLE001
                _log_provider_failure("invalid-session cleanup", exc)
                self._closed = True
            raise
        try:
            provider_fields = self.service.fields(draft)
        except UnavailableMutationService as exc:
            self._discard_start_draft(draft)
            self._blocked_reason = str(exc) or "Configuration changes are unavailable."
            return self._snapshot()
        except Exception as exc:  # noqa: BLE001
            self._discard_start_draft(draft)
            _log_provider_failure("field discovery", exc)
            self._blocked_reason = "The configuration provider could not start a change."
            return self._snapshot()
        try:
            self._fields = {field.key: field for field in provider_fields}
            self._validate_provider_fields(provider_fields)
        except Exception:
            self._discard_start_draft(draft)
            raise
        self._display_values = {
            field.key: field.default
            for field in provider_fields
            if field.default is not None and not field.masks_value
        }
        self._draft = draft
        active = self._active_steps(self._display_values)
        if active:
            self._current_step_key = active[0].key
        else:
            return self.review().snapshot
        return self._snapshot()

    def submit(self, values: Mapping[str, object]) -> WizardTransition:
        self._ensure_open()
        if self._blocked_reason is not None or self._current_step_key is None:
            return WizardTransition(self._snapshot(), self._issues)
        current = self._workflow_step(self._current_step_key)
        parsed_values: dict[str, object] = {}
        safe_values: dict[str, object] = {}
        parse_issues: list[ValidationIssue] = []
        for field_key in current.field_keys:
            field = self._fields[field_key]
            try:
                parsed = field.parse(values.get(field_key))
            except ValueError as exc:
                parse_issues.append(
                    ValidationIssue(str(exc), field_key=field_key)
                )
                continue
            parsed_values[field_key] = parsed.value
            safe_values[field_key] = redact_wizard_value(field, parsed.value)

        if parse_issues:
            parsed_values.clear()
            self._issues = tuple(parse_issues)
            return WizardTransition(self._snapshot(), self._issues)

        prospective = dict(self._display_values)
        prospective.update(safe_values)
        previous_active = self._active_steps(self._display_values)
        next_active = self._active_steps(prospective)
        next_active_keys = {step.key for step in next_active}
        invalidated_steps = tuple(
            step for step in previous_active if step.key not in next_active_keys
        )
        discard_fields = frozenset(
            field_key
            for step in invalidated_steps
            for field_key in step.field_keys
        )

        try:
            try:
                result = self.service.submit(
                    self._require_draft(),
                    current.key,
                    parsed_values,
                    discard_fields=discard_fields,
                )
            except Exception as exc:  # noqa: BLE001
                _log_provider_failure("step validation", exc)
                self._issues = (
                    ValidationIssue("The provider could not validate this step."),
                )
                return WizardTransition(self._snapshot(), self._issues)
        finally:
            # Secret-bearing locals should live only across the provider call. The
            # caller owns its input mapping; snapshots receive only safe_values.
            parsed_values.clear()

        self._issues = result.issues
        if not result.accepted:
            return WizardTransition(self._snapshot(), self._issues)
        if not result.changed_fields <= self._fields.keys():
            raise ValueError("Mutation provider returned undeclared changed fields.")

        for field_key in discard_fields:
            self._display_values.pop(field_key, None)
        self._display_values.update(safe_values)
        self._completed_steps.difference_update(
            step.key for step in invalidated_steps
        )
        self._completed_steps.add(current.key)
        self._draft = replace(
            self._require_draft(), changed_fields=result.changed_fields
        )
        self._plan = None
        self._apply_consumed = False

        active = self._active_steps(self._display_values)
        current_index = next(
            index for index, step in enumerate(active) if step.key == current.key
        )
        if current_index + 1 < len(active):
            self._current_step_key = active[current_index + 1].key
            return WizardTransition(self._snapshot(), self._issues)
        return self.review()

    def back(self) -> WizardSnapshot:
        self._ensure_open()
        if self._blocked_reason is not None:
            return self._snapshot()
        active = self._active_steps(self._display_values)
        if self._current_step_key is None:
            if active:
                self._current_step_key = active[-1].key
            self._issues = ()
            return self._snapshot()
        current_index = next(
            index for index, step in enumerate(active) if step.key == self._current_step_key
        )
        if current_index > 0:
            self._current_step_key = active[current_index - 1].key
        self._issues = ()
        return self._snapshot()

    def review(self) -> WizardTransition:
        self._ensure_open()
        if self._blocked_reason is not None:
            return WizardTransition(self._snapshot(), self._issues)
        active = self._active_steps(self._display_values)
        incomplete = [step for step in active if step.key not in self._completed_steps]
        if incomplete:
            self._current_step_key = incomplete[0].key
            self._issues = (
                ValidationIssue("Complete this step before review."),
            )
            return WizardTransition(self._snapshot(), self._issues)
        try:
            plan = self.service.plan(self._require_draft())
        except UnavailableMutationService as exc:
            self._issues = (
                ValidationIssue(str(exc) or "Configuration planning is unavailable."),
            )
            return WizardTransition(self._snapshot(), self._issues)
        except Exception as exc:  # noqa: BLE001
            _log_provider_failure("plan preparation", exc)
            self._issues = (
                ValidationIssue("The provider could not prepare a configuration plan."),
            )
            return WizardTransition(self._snapshot(), self._issues)
        try:
            self._validate_plan(plan)
        except ValueError as exc:
            _log_provider_failure("plan validation", exc)
            self._issues = (
                ValidationIssue("The provider returned an unusable configuration plan."),
            )
            return WizardTransition(self._snapshot(), self._issues)
        self._plan = plan
        self._current_step_key = None
        self._issues = plan.issues
        self._apply_consumed = False
        return WizardTransition(self._snapshot(), self._issues)

    def apply(self) -> WizardResult:
        self._ensure_open()
        plan = self._plan
        if (
            self._current_step_key is not None
            or plan is None
            or not plan.ready
            or plan.apply_token is None
        ):
            return WizardResult(
                WizardResultStatus.REJECTED,
                "The configuration plan is not ready to apply.",
            )
        if self._apply_consumed:
            return WizardResult(
                WizardResultStatus.REJECTED,
                "This apply plan has already been used. Review the configuration again.",
            )
        self._apply_consumed = True
        intent = ConfigApplyIntent(
            target=self.workflow.target,
            operation=self.workflow.operation,
            apply_token=plan.apply_token,
            expected_revision=plan.expected_revision,
        )
        try:
            result = self.service.apply(intent)
        except Exception as exc:  # noqa: BLE001
            _log_provider_failure("apply", exc)
            self._close_after_apply(clean_up_provider=True)
            return WizardResult(
                WizardResultStatus.FAILED,
                "The configuration change failed.",
                detail="The provider did not return a usable result.",
            )
        status = {
            ConfigApplyStatus.APPLIED: WizardResultStatus.APPLIED,
            ConfigApplyStatus.CONFLICTED: WizardResultStatus.CONFLICTED,
            ConfigApplyStatus.REJECTED: WizardResultStatus.REJECTED,
            ConfigApplyStatus.FAILED: WizardResultStatus.FAILED,
        }.get(result.status)
        if status is None:
            _LOGGER.error(
                "Configuration provider returned an unsupported apply status."
            )
            self._close_after_apply(clean_up_provider=True)
            return WizardResult(
                WizardResultStatus.FAILED,
                "The configuration provider returned an unsupported result.",
            )
        self._close_after_apply(
            clean_up_provider=status is not WizardResultStatus.APPLIED
        )
        return WizardResult(
            status=status,
            summary=result.summary,
            detail=result.detail,
            refresh_pages=result.refresh_pages,
        )

    def cancel(self) -> WizardResult:
        summary = "Configuration was not changed."
        if not self._closed and self._draft is not None:
            try:
                self.service.cancel(self._draft)
            except Exception as exc:  # noqa: BLE001
                _log_provider_failure("cancellation", exc)
                summary = "The wizard closed, but the provider could not confirm cancellation."
        self._closed = True
        self._plan = None
        self._apply_consumed = True
        return WizardResult(
            WizardResultStatus.CANCELLED,
            summary,
        )

    def _snapshot(self) -> WizardSnapshot:
        if self._blocked_reason is not None:
            issue = ValidationIssue(self._blocked_reason)
            step = ReviewStep(
                key="configuration-unavailable",
                title="Configuration unavailable",
                review=WizardReview(ready_to_apply=False),
                purpose=self._blocked_reason,
            )
            return WizardSnapshot(
                spec=self.spec,
                step=step,
                step_index=0,
                step_count=1,
                issues=(issue,),
                can_next=False,
                can_review=False,
            )

        active = self._active_steps(self._display_values)
        if self._current_step_key is not None:
            current_index = next(
                index
                for index, step in enumerate(active)
                if step.key == self._current_step_key
            )
            step = self._render_step(active[current_index])
            visible_keys = set(active[current_index].field_keys)
            values = {
                key: value
                for key, value in self._display_values.items()
                if key in visible_keys and not self._fields[key].masks_value
            }
            return WizardSnapshot(
                spec=self.spec,
                step=step,
                step_index=current_index,
                step_count=len(active) + 1,
                values=values,
                issues=self._issues,
                can_back=current_index > 0,
                can_next=True,
                can_review=False,
                expected_revision=self._require_draft().expected_revision,
            )

        plan = self._plan
        review = WizardReview(
            changes=tuple(
                ReviewChange(
                    field=entry.field,
                    before=entry.before,
                    after=entry.after,
                    sensitive=entry.sensitive,
                )
                for entry in plan.diff.entries
            )
            if plan is not None
            else (),
            effects=plan.effects if plan else (),
            warnings=(
                tuple(plan.warnings)
                + tuple(
                    issue.message
                    for issue in plan.issues
                    if issue.status is SemanticStatus.WARNING
                )
            )
            if plan
            else (),
            ready_to_apply=bool(plan and plan.ready and not self._apply_consumed),
        )
        return WizardSnapshot(
            spec=self.spec,
            step=ReviewStep(
                key="review",
                title="Review changes",
                review=review,
                purpose="Check the proposed change and its effects before applying it.",
            ),
            step_index=len(active),
            step_count=len(active) + 1,
            issues=self._issues,
            can_back=bool(active),
            can_next=False,
            can_review=False,
            can_apply=review.ready_to_apply,
            expected_revision=self._require_draft().expected_revision,
        )

    def _render_step(self, step: ConfigWorkflowStep) -> FormStep | ChoiceStep:
        if step.kind is ConfigWorkflowStepKind.CHOICE:
            field = self._fields[step.field_keys[0]]
            return ChoiceStep(
                key=step.key,
                title=step.title,
                purpose=step.purpose,
                choices=tuple(
                    Choice(
                        key=choice.value,
                        label=choice.label,
                        description=choice.description or "",
                    )
                    for choice in field.choices
                ),
            )
        return FormStep(
            key=step.key,
            title=step.title,
            purpose=step.purpose,
            fields=tuple(self._fields[key] for key in step.field_keys),
        )

    def _active_steps(
        self, values: Mapping[str, object]
    ) -> tuple[ConfigWorkflowStep, ...]:
        return tuple(
            step
            for step in self.workflow.steps
            if all(
                condition.matches(values.get(condition.field_key))
                for condition in step.when
            )
        )

    def _workflow_step(self, key: str) -> ConfigWorkflowStep:
        return next(step for step in self.workflow.steps if step.key == key)

    def _validate_workflow_shape(self) -> None:
        if not self.workflow.steps:
            raise WizardDefinitionError("A configuration workflow requires at least one step.")
        keys = [step.key for step in self.workflow.steps]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise WizardDefinitionError(
                f"Configuration workflow step keys must be unique: {duplicates}"
            )
        for step in self.workflow.steps:
            if not step.field_keys:
                raise WizardDefinitionError(
                    f"Configuration workflow step {step.key!r} requires fields."
                )
            if step.kind is ConfigWorkflowStepKind.CHOICE and (
                len(step.field_keys) != 1 or step.key != step.field_keys[0]
            ):
                raise WizardDefinitionError(
                    "A choice step must contain one field and use that field key as its step key."
                )
            condition_keys = [condition.field_key for condition in step.when]
            if any(not condition.values for condition in step.when):
                raise WizardDefinitionError(
                    f"Configuration step {step.key!r} has an empty branch value set."
                )
            duplicate_conditions = sorted(
                {
                    key
                    for key in condition_keys
                    if condition_keys.count(key) > 1
                }
            )
            if duplicate_conditions:
                raise WizardDefinitionError(
                    f"Configuration step {step.key!r} has duplicate branch fields: "
                    f"{duplicate_conditions}"
                )

    def _validate_provider_fields(self, fields: Sequence[FieldSpec]) -> None:
        keys = [field.key for field in fields]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise WizardDefinitionError(
                f"Provider field keys must be unique: {duplicates}"
            )
        used: set[str] = set()
        step_index: dict[str, int] = {}
        for index, step in enumerate(self.workflow.steps):
            for key in step.field_keys:
                if key not in self._fields:
                    raise WizardDefinitionError(
                        f"Configuration workflow references unknown field {key!r}."
                    )
                if key in used:
                    raise WizardDefinitionError(
                        f"Configuration field {key!r} appears in more than one step."
                    )
                used.add(key)
                step_index[key] = index
            if step.kind is ConfigWorkflowStepKind.CHOICE:
                field = self._fields[step.field_keys[0]]
                if field.kind is not FieldKind.CHOICE or not field.choices:
                    raise WizardDefinitionError(
                        f"Choice step {step.key!r} requires a choice field with options."
                    )
                choice_values = [choice.value for choice in field.choices]
                duplicate_choices = sorted(
                    {
                        value
                        for value in choice_values
                        if choice_values.count(value) > 1
                    }
                )
                if duplicate_choices:
                    raise WizardDefinitionError(
                        f"Choice field {field.key!r} has duplicate values: "
                        f"{duplicate_choices}"
                    )
                if field.default is not None and str(field.default) not in choice_values:
                    raise WizardDefinitionError(
                        f"Choice field {field.key!r} has a default outside its choices."
                    )
        for index, step in enumerate(self.workflow.steps):
            for condition in step.when:
                field = self._fields.get(condition.field_key)
                if field is None:
                    raise WizardDefinitionError(
                        f"Branch references unknown field {condition.field_key!r}."
                    )
                if field.masks_value:
                    raise WizardDefinitionError("Sensitive fields cannot control branches.")
                if step_index.get(condition.field_key, index) >= index:
                    raise WizardDefinitionError(
                        f"Branch field {condition.field_key!r} must appear in an earlier step."
                    )
        unused = sorted(set(self._fields) - used)
        if unused:
            raise WizardDefinitionError(
                f"Provider fields are absent from the configuration workflow: {unused}"
            )

    def _validate_draft(self, draft: ConfigDraft) -> None:
        if draft.target != self.workflow.target or draft.operation is not self.workflow.operation:
            raise ValueError("Mutation provider returned a draft for the wrong target or operation.")
        if draft.expected_revision is None:
            raise ValueError("Mutation provider returned a draft without a revision.")

    def _validate_plan(self, plan: ConfigPlan) -> None:
        if plan.target != self.workflow.target or plan.operation is not self.workflow.operation:
            raise ValueError("Mutation provider returned a plan for the wrong target or operation.")
        if plan.diff.target != self.workflow.target:
            raise ValueError("Mutation provider returned a diff for the wrong target.")
        if plan.ready and plan.expected_revision is None:
            raise ValueError("Mutation provider returned a ready plan without a revision.")
        if plan.ready and plan.expected_revision != self._require_draft().expected_revision:
            raise ValueError("Mutation provider returned a plan for a different revision.")

    def _discard_start_draft(self, draft: ConfigDraft) -> None:
        try:
            self.service.cancel(draft)
        except Exception as exc:  # noqa: BLE001
            _log_provider_failure("start-session cleanup", exc)

    def _close_after_apply(self, *, clean_up_provider: bool) -> None:
        if clean_up_provider and self._draft is not None:
            try:
                self.service.cancel(self._draft)
            except Exception as exc:  # noqa: BLE001
                _log_provider_failure("terminal apply cleanup", exc)
        self._closed = True
        self._plan = None
        self._apply_consumed = True

    def _require_draft(self) -> ConfigDraft:
        if self._draft is None:
            raise RuntimeError("The configuration workflow has not started.")
        return self._draft

    def _ensure_open(self) -> None:
        if not self._started:
            self.start()
        if self._closed:
            raise RuntimeError("The configuration workflow is closed.")


_LOGGER = logging.getLogger(__name__)


def _log_provider_failure(operation: str, exc: Exception) -> None:
    """Record a useful traceback without logging a provider exception message.

    Provider exceptions can echo submitted values. Reusing the traceback with a sanitized
    terminal exception preserves the diagnostic call path without putting those values in
    logs.
    """

    sanitized = RuntimeError(f"{type(exc).__name__}; provider details suppressed")
    _LOGGER.error(
        "Configuration provider failed during %s.",
        operation,
        exc_info=(RuntimeError, sanitized, exc.__traceback__),
    )
