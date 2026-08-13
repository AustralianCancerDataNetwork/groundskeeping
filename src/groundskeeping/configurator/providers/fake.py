"""Deterministic in-memory provider for exercising configuration workflows.

The fake follows the same privacy boundary expected of external providers: test history
records field names and outcomes, never submitted values, and secret candidate state is
replaced with a boolean presence marker during ``submit``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from groundskeeping.configurator.controller import (
    ConfigBranchCondition,
    ConfigWorkflowSpec,
    ConfigWorkflowStep,
    ConfigWorkflowStepKind,
)
from groundskeeping.configurator.models import ConfigTarget, ConfigTargetKind
from groundskeeping.configurator.mutation import (
    ConfigApplyIntent,
    ConfigApplyResult,
    ConfigApplyStatus,
    ConfigDraft,
    ConfigPlan,
    ConfigStepResult,
    EffectRef,
    MutationCapabilities,
    MutationOperation,
    UnavailableMutationService,
    build_config_diff,
)
from groundskeeping.contracts.actions import (
    ChoiceOption,
    FieldKind,
    FieldSpec,
    ValidationIssue,
)
from groundskeeping.contracts.views import SemanticStatus


class FakeMutationScenario(StrEnum):
    READY = "ready"
    WARNING = "warning"
    PLAN_ERROR = "plan_error"
    CONFLICTED = "conflicted"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class FakeMutationEvent:
    """Safe observable trace used by tests and demos."""

    action: str
    field_keys: frozenset[str] = frozenset()


@dataclass
class _FakeSession:
    target: ConfigTarget
    operation: MutationOperation
    expected_revision: str
    values: dict[str, object] = field(default_factory=dict)
    changed_fields: frozenset[str] = frozenset()
    apply_token: str | None = None


def fake_database_workflow(
    *,
    operation: MutationOperation = MutationOperation.CREATE,
    target: ConfigTarget | None = None,
) -> ConfigWorkflowSpec:
    """Return the branching workflow used by the fake and package demo."""

    resolved_target = target or ConfigTarget(
        kind=ConfigTargetKind.DATABASE,
        key="metadata",
        title="Metadata database",
    )
    return ConfigWorkflowSpec(
        key=f"database-{operation.value}",
        target=resolved_target,
        operation=operation,
        title=f"{operation.value.title()} database configuration",
        purpose="Choose an existing database or describe a new connection.",
        apply_label=f"{operation.value.title()} database",
        steps=(
            ConfigWorkflowStep(
                key="strategy",
                title="Setup approach",
                field_keys=("strategy",),
                kind=ConfigWorkflowStepKind.CHOICE,
            ),
            ConfigWorkflowStep(
                key="reuse-database",
                title="Existing database",
                field_keys=("selected_database",),
                when=(ConfigBranchCondition("strategy", "reuse"),),
            ),
            ConfigWorkflowStep(
                key="create-database",
                title="New database",
                field_keys=("database_name", "connection_url", "password"),
                when=(ConfigBranchCondition("strategy", "create"),),
            ),
            ConfigWorkflowStep(
                key="sharing",
                title="Shared references",
                field_keys=("shared_reference",),
                purpose="Record whether other configuration entries use this database.",
            ),
        ),
    )


class FakeConfigMutationService:
    """In-memory service covering the complete generic mutation lifecycle."""

    def __init__(
        self,
        *,
        scenario: FakeMutationScenario = FakeMutationScenario.READY,
        available: bool = True,
        supported_operations: frozenset[MutationOperation] = frozenset(
            {MutationOperation.CREATE, MutationOperation.UPDATE}
        ),
    ) -> None:
        self.scenario = scenario
        self.available = available
        self.supported_operations = supported_operations
        self._revision_number = 1
        self._session_number = 0
        self._plan_number = 0
        self._sessions: dict[str, _FakeSession] = {}
        self._apply_tokens: dict[str, str] = {}
        self._durable: dict[str, Mapping[str, object]] = {}
        self._history: list[FakeMutationEvent] = []

    @property
    def revision(self) -> str:
        return f"fake-revision-{self._revision_number}"

    @property
    def history(self) -> tuple[FakeMutationEvent, ...]:
        return tuple(self._history)

    @property
    def durable(self) -> Mapping[str, Mapping[str, object]]:
        return dict(self._durable)

    def advance_revision(self) -> None:
        """Simulate another writer changing the configuration."""

        self._revision_number += 1

    def capabilities(
        self, target: ConfigTarget, operation: MutationOperation
    ) -> MutationCapabilities:
        self._ensure_available()
        supported = operation in self.supported_operations
        return MutationCapabilities(
            target=target,
            operation=operation,
            supported=supported,
            reason=None if supported else f"{operation.value.title()} is not supported.",
        )

    def fields(
        self, target: ConfigTarget, operation: MutationOperation
    ) -> tuple[FieldSpec, ...]:
        self._ensure_available()
        return (
            FieldSpec(
                key="strategy",
                label="Setup approach",
                kind=FieldKind.CHOICE,
                default="create",
                choices=(
                    ChoiceOption("create", "Create new", "Add a new database entry."),
                    ChoiceOption("reuse", "Reuse existing", "Select an existing entry."),
                ),
            ),
            FieldSpec(
                key="selected_database",
                label="Existing database",
                kind=FieldKind.CHOICE,
                choices=(
                    ChoiceOption("metadata", "Metadata"),
                    ChoiceOption("analytics", "Analytics"),
                ),
            ),
            FieldSpec(
                key="database_name",
                label="Database name",
                placeholder="metadata",
            ),
            FieldSpec(
                key="connection_url",
                label="Connection URL",
                placeholder="postgresql://host/database",
            ),
            FieldSpec(
                key="password",
                label="Password",
                kind=FieldKind.SECRET,
                help="Submitted to the provider and cleared from wizard state immediately.",
            ),
            FieldSpec(
                key="shared_reference",
                label="Used by another entry",
                kind=FieldKind.BOOLEAN,
                default=False,
                required=False,
            ),
        )

    def begin(
        self, target: ConfigTarget, operation: MutationOperation
    ) -> ConfigDraft:
        self._ensure_available()
        capabilities = self.capabilities(target, operation)
        if not capabilities.supported:
            raise ValueError(capabilities.reason)
        self._session_number += 1
        token = f"fake-session-{self._session_number}"
        self._sessions[token] = _FakeSession(
            target=target,
            operation=operation,
            expected_revision=self.revision,
        )
        self._history.append(FakeMutationEvent("begin"))
        return ConfigDraft(
            target=target,
            operation=operation,
            session_token=token,
            expected_revision=self.revision,
        )

    def submit(
        self,
        draft: ConfigDraft,
        step_key: str,
        values: Mapping[str, object],
        *,
        discard_fields: frozenset[str] = frozenset(),
    ) -> ConfigStepResult:
        self._ensure_available()
        session = self._session(draft.session_token)
        issues: list[ValidationIssue] = []
        if values.get("database_name") == "reserved":
            issues.append(
                ValidationIssue(
                    "That database name is reserved.", field_key="database_name"
                )
            )
        connection_url = values.get("connection_url")
        if connection_url is not None and not str(connection_url).startswith(
            ("postgresql://", "sqlite://")
        ):
            issues.append(
                ValidationIssue(
                    "The database entry could not be validated with that connection URL."
                )
            )
        if issues:
            self._history.append(
                FakeMutationEvent("submit-rejected", frozenset(values))
            )
            return ConfigStepResult(tuple(issues), session.changed_fields)

        for field_key in discard_fields:
            session.values.pop(field_key, None)
        safe_values: dict[str, object] = {}
        for field_key, value in values.items():
            safe_values[field_key] = (
                value not in (None, "") if field_key == "password" else value
            )
        session.values.update(safe_values)
        session.changed_fields = frozenset(session.values)
        if session.apply_token is not None:
            self._apply_tokens.pop(session.apply_token, None)
            session.apply_token = None
        self._history.append(
            FakeMutationEvent(
                f"submit:{step_key}",
                frozenset(set(values) | set(discard_fields)),
            )
        )
        return ConfigStepResult(changed_fields=session.changed_fields)

    def plan(self, draft: ConfigDraft) -> ConfigPlan:
        self._ensure_available()
        session = self._session(draft.session_token)
        issues = list(self._candidate_issues(session.values))
        if self.scenario is FakeMutationScenario.PLAN_ERROR:
            issues.append(ValidationIssue("The candidate is blocked by provider policy."))
        warnings: tuple[str, ...] = ()
        if self.scenario is FakeMutationScenario.WARNING:
            warnings = ("The target is currently used by a running demo workload.",)

        candidate = dict(session.values)
        before: Mapping[str, object] = (
            {
                "database_name": "metadata",
                "connection_url": "postgresql://old/metadata",
                "password": True,
                "shared_reference": False,
            }
            if session.operation is MutationOperation.UPDATE
            else {}
        )
        diff = build_config_diff(
            session.target,
            before,
            candidate,
            sensitive_fields=frozenset({"password"}),
        )
        effects = [
            EffectRef(
                kind=session.operation.value,
                target=session.target,
                detail="configuration entry",
            )
        ]
        if candidate.get("shared_reference"):
            effects.append(
                EffectRef(
                    kind="shared-reference",
                    target=session.target,
                    field_key="shared_reference",
                    detail="another entry may observe this change",
                )
            )

        has_error = any(issue.status is SemanticStatus.ERROR for issue in issues)
        apply_token: str | None = None
        if not has_error:
            if session.apply_token is not None:
                self._apply_tokens.pop(session.apply_token, None)
            self._plan_number += 1
            apply_token = f"fake-plan-{self._plan_number}"
            session.apply_token = apply_token
            self._apply_tokens[apply_token] = draft.session_token
        self._history.append(FakeMutationEvent("plan"))
        return ConfigPlan(
            target=session.target,
            operation=session.operation,
            diff=diff,
            effects=tuple(effects),
            issues=tuple(issues),
            warnings=warnings,
            apply_token=apply_token,
        )

    def apply(self, intent: ConfigApplyIntent) -> ConfigApplyResult:
        self._ensure_available()
        session_token = self._apply_tokens.pop(intent.apply_token, None)
        if session_token is None:
            return ConfigApplyResult(
                ConfigApplyStatus.REJECTED,
                "The apply plan is no longer valid.",
            )
        session = self._session(session_token)
        session.apply_token = None
        self._history.append(FakeMutationEvent("apply"))
        if (
            intent.expected_revision != self.revision
            or self.scenario is FakeMutationScenario.CONFLICTED
        ):
            return ConfigApplyResult(
                ConfigApplyStatus.CONFLICTED,
                "Configuration changed before this plan could be applied.",
                detail="Reload the configuration and review the change again.",
            )
        if self.scenario is FakeMutationScenario.REJECTED:
            return ConfigApplyResult(
                ConfigApplyStatus.REJECTED,
                "The provider rejected the configuration change.",
            )
        if self.scenario is FakeMutationScenario.FAILED:
            return ConfigApplyResult(
                ConfigApplyStatus.FAILED,
                "The provider could not apply the configuration change.",
            )

        self._durable[session.target.key] = dict(session.values)
        self._revision_number += 1
        self._sessions.pop(session_token, None)
        return ConfigApplyResult(
            ConfigApplyStatus.APPLIED,
            "Configuration applied.",
            refresh_pages=frozenset({"config"}),
        )

    def cancel(self, draft: ConfigDraft) -> None:
        session = self._sessions.pop(draft.session_token, None)
        if session is not None and session.apply_token is not None:
            self._apply_tokens.pop(session.apply_token, None)
        self._history.append(FakeMutationEvent("cancel"))

    def _candidate_issues(
        self, values: Mapping[str, object]
    ) -> tuple[ValidationIssue, ...]:
        strategy = values.get("strategy")
        if strategy == "reuse" and not values.get("selected_database"):
            return (
                ValidationIssue(
                    "Choose an existing database.", field_key="selected_database"
                ),
            )
        if strategy == "create":
            missing = [
                key
                for key in ("database_name", "connection_url", "password")
                if not values.get(key)
            ]
            if missing:
                return tuple(
                    ValidationIssue("This field is required.", field_key=key)
                    for key in missing
                )
        if strategy not in {"create", "reuse"}:
            return (ValidationIssue("Choose a setup approach.", field_key="strategy"),)
        return ()

    def _session(self, token: str) -> _FakeSession:
        try:
            return self._sessions[token]
        except KeyError:
            raise ValueError("The mutation session is no longer valid.") from None

    def _ensure_available(self) -> None:
        if not self.available:
            raise UnavailableMutationService(
                "Configuration changes are temporarily unavailable."
            )
