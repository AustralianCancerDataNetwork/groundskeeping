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
    MutationOperationUnsupported,
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
                when=(
                    ConfigBranchCondition("strategy", frozenset({"reuse"})),
                ),
            ),
            ConfigWorkflowStep(
                key="create-database",
                title="New database",
                field_keys=("database_name", "connection_url", "password"),
                when=(
                    ConfigBranchCondition("strategy", frozenset({"create"})),
                ),
            ),
            ConfigWorkflowStep(
                key="sharing",
                title="Shared references",
                field_keys=("shared_reference",),
                purpose="Record whether other configuration entries use this database.",
            ),
        ),
    )


def fake_dialect_database_workflow(
    *, target: ConfigTarget | None = None
) -> ConfigWorkflowSpec:
    """Model shared identity and non-SQLite server fields in one workflow."""

    resolved_target = target or ConfigTarget(
        kind=ConfigTargetKind.CONNECTION,
        key="primary",
        title="Primary connection",
    )
    return ConfigWorkflowSpec(
        key="dialect-database-create",
        target=resolved_target,
        operation=MutationOperation.CREATE,
        title="Create database connection",
        purpose="Collect shared database identity and dialect-specific connection fields.",
        steps=(
            ConfigWorkflowStep(
                key="dialect",
                title="Database dialect",
                field_keys=("dialect",),
                kind=ConfigWorkflowStepKind.CHOICE,
            ),
            ConfigWorkflowStep(
                key="database-identity",
                title="Database identity",
                field_keys=("database_name",),
            ),
            ConfigWorkflowStep(
                key="server-connection",
                title="Server connection",
                field_keys=("host", "port", "user", "password"),
                when=(
                    ConfigBranchCondition(
                        "dialect", frozenset({"sqlite"}), negated=True
                    ),
                ),
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
        stored: Mapping[str, Mapping[str, object]] | None = None,
    ) -> None:
        """Create an isolated fake.

        ``stored`` seeds already-persisted values per target key, so an ``UPDATE``
        journey can start from a realistic base. Seed it with the same field keys the
        provider stages, or the diff will report the difference between two shapes
        rather than between two configurations.
        """

        self.scenario = scenario
        self.available = available
        self.supported_operations = supported_operations
        self._revision_number = 1
        self._session_number = 0
        self._plan_number = 0
        self._sessions: dict[str, _FakeSession] = {}
        self._apply_tokens: dict[str, str] = {}
        self._durable: dict[str, dict[str, object]] = {
            target_key: dict(values)
            for target_key, values in (stored or {}).items()
        }
        self._history: list[FakeMutationEvent] = []

    @property
    def revision(self) -> str:
        return f"fake-revision-{self._revision_number}"

    @property
    def history(self) -> tuple[FakeMutationEvent, ...]:
        return tuple(self._history)

    @property
    def durable(self) -> dict[str, dict[str, object]]:
        """Return an isolated snapshot of the fake provider's persisted values."""

        return {
            target_key: dict(values)
            for target_key, values in self._durable.items()
        }

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

    def fields(self, draft: ConfigDraft) -> tuple[FieldSpec, ...]:
        self._ensure_available()
        self._session_for_draft(draft)
        self._history.append(FakeMutationEvent("fields"))
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
            raise MutationOperationUnsupported(
                capabilities.reason or f"{operation.value.title()} is not supported."
            )
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

        # Both sides come from the same store of staged field keys, so an unchanged
        # journey diffs to nothing. Projecting the base any other way would surface
        # fields this workflow never collects as changes the operator has to approve.
        candidate = dict(session.values)
        before: Mapping[str, object] = dict(self._durable.get(session.target.key, {}))
        diff = build_config_diff(
            session.target,
            before,
            candidate,
            sensitive_fields=frozenset({"password"}),
        )
        effects = [
            EffectRef(
                impact_kind=session.operation.value,
                source_target=session.target,
                label="configuration entry",
            )
        ]
        if candidate.get("shared_reference"):
            effects.append(
                EffectRef(
                    impact_kind="shared-reference",
                    source_target=ConfigTarget(
                        kind=ConfigTargetKind.TOOL,
                        key="groundskeeping_demo",
                        title="Groundskeeping demo",
                    ),
                    label="another entry may observe this change",
                    destination_target=session.target,
                    field_key="database",
                    status=SemanticStatus.WARNING,
                )
            )

        # Retire any earlier token before deciding this plan's readiness, so a session
        # whose candidate becomes blocked is left with nothing to apply. Invalidating
        # only on the ready branch would let the superseded token outlive the plan that
        # minted it and bypass the newer, blocked one.
        has_error = any(issue.status is SemanticStatus.ERROR for issue in issues)
        if session.apply_token is not None:
            self._apply_tokens.pop(session.apply_token, None)
            session.apply_token = None
        apply_token: str | None = None
        if not has_error:
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
            expected_revision=session.expected_revision,
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
        if intent.target != session.target or intent.operation != session.operation:
            return ConfigApplyResult(
                ConfigApplyStatus.REJECTED,
                "The apply plan does not match the requested target or operation.",
            )
        # The revision is checked against the one this session captured at begin(),
        # not only against the current store. Trusting the caller's value would let a
        # stale token be paired with the current revision and slip past the conflict
        # check below with a candidate planned against an older configuration.
        if intent.expected_revision != session.expected_revision:
            return ConfigApplyResult(
                ConfigApplyStatus.REJECTED,
                "The apply plan was not prepared for that configuration revision.",
            )
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

    def _session_for_draft(self, draft: ConfigDraft) -> _FakeSession:
        session = self._session(draft.session_token)
        if draft.target != session.target or draft.operation != session.operation:
            raise ValueError("The mutation draft does not match its session.")
        return session

    def _ensure_available(self) -> None:
        if not self.available:
            raise UnavailableMutationService(
                "Configuration changes are temporarily unavailable."
            )


class FakeDialectConfigMutationService(FakeConfigMutationService):
    """Fake provider for shared database identity and server-only fields."""

    def fields(self, draft: ConfigDraft) -> tuple[FieldSpec, ...]:
        self._ensure_available()
        self._session_for_draft(draft)
        self._history.append(FakeMutationEvent("fields"))
        return (
            FieldSpec(
                key="dialect",
                label="Database dialect",
                kind=FieldKind.CHOICE,
                default="sqlite",
                choices=(
                    ChoiceOption("sqlite", "SQLite"),
                    ChoiceOption("postgresql+psycopg", "PostgreSQL"),
                    ChoiceOption("mssql+pyodbc", "Microsoft SQL Server"),
                    ChoiceOption("oracle+oracledb", "Oracle"),
                    ChoiceOption("duckdb", "DuckDB"),
                ),
            ),
            FieldSpec(
                key="database_name",
                label="Database name or SQLite path",
                help="Used by every dialect; for SQLite, enter the database file path.",
            ),
            FieldSpec(key="host", label="Host"),
            FieldSpec(key="port", label="Port", kind=FieldKind.INTEGER),
            FieldSpec(key="user", label="User"),
            FieldSpec(key="password", label="Password", kind=FieldKind.SECRET),
        )

    def _candidate_issues(
        self, values: Mapping[str, object]
    ) -> tuple[ValidationIssue, ...]:
        missing = [key for key in ("dialect", "database_name") if not values.get(key)]
        if values.get("dialect") != "sqlite":
            missing.extend(
                key
                for key in ("host", "port", "user", "password")
                if not values.get(key)
            )
        return tuple(
            ValidationIssue("This field is required.", field_key=key)
            for key in missing
        )
