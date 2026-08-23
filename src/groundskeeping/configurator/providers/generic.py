"""Generic ConfigMutationService driven by a ConfigSchemaAdapter.

Session bookkeeping, revision-conflict detection, single-use apply tokens,
and diff computation are implemented exactly once here -- the same
mechanics `providers.fake.FakeConfigMutationService` hand-rolls for its own
demo target, generalised over `ConfigSchemaAdapter` instead of two
hardcoded fields. A host wanting a `ConfigMutationService` for one more
configuration target implements that seam; it does not re-implement
sessions, tokens, or conflict detection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import count

from groundskeeping.configurator.models import ConfigTarget
from groundskeeping.configurator.mutation import (
    ConfigApplyIntent,
    ConfigApplyResult,
    ConfigApplyStatus,
    ConfigDraft,
    ConfigPlan,
    ConfigStepResult,
    MutationCapabilities,
    MutationOperation,
    MutationOperationUnsupported,
    UnavailableMutationService,
    build_config_diff,
)
from groundskeeping.configurator.providers.schema import (
    ConfigSchemaAdapter,
    ConfigSchemaConflictError,
    ConfigSchemaRejectedError,
)
from groundskeeping.contracts.actions import FieldSpec, ValidationIssue
from groundskeeping.contracts.views import SemanticStatus


@dataclass
class _Session:
    target: ConfigTarget
    operation: MutationOperation
    expected_revision: str
    values: dict[str, object] = field(default_factory=dict)
    changed_fields: frozenset[str] = frozenset()
    apply_token: str | None = None
    planned_candidate: dict[str, object] | None = None


class SchemaConfigMutationService:
    """ConfigMutationService for one target, backed by one ConfigSchemaAdapter.

    One instance serves exactly one `ConfigTarget` -- the natural shape for
    a plugin config page, where each plugin gets its own adapter over its
    own configuration. `capabilities()`/`begin()` report a target other than
    the one this instance was built for as unsupported rather than raising;
    a host juggling several targets constructs one service per target
    rather than routing through a single shared instance.

    CREATE and UPDATE are both always supported: unlike a database or model
    entry, a schema-backed configuration section does not have a meaningful
    "does it already exist" distinction when every field can have a usable
    default (the same reason `PackageConfigBase.resolve_package_config`
    treats an absent section as resolvable, not an error). A host that does
    need to distinguish them can still choose which operation to open with;
    this provider does not block whichever one it's asked for.
    """

    def __init__(self, target: ConfigTarget, schema: ConfigSchemaAdapter) -> None:
        self._target = target
        self._schema = schema
        self._session_ids = count(1)
        self._plan_ids = count(1)
        self._sessions: dict[str, _Session] = {}
        self._apply_tokens: dict[str, str] = {}

    def capabilities(
        self, target: ConfigTarget, operation: MutationOperation
    ) -> MutationCapabilities:
        if target != self._target:
            return MutationCapabilities(
                target=target,
                operation=operation,
                supported=False,
                reason="This provider does not serve that target.",
            )
        # A cheap read that doubles as the availability check every other
        # method skips: capabilities() is the call a host makes first, so
        # it is where "the schema adapter cannot currently be reached"
        # (file unreadable, backing store unreachable) surfaces as
        # UnavailableMutationService rather than an unhandled exception
        # from whichever method happens to touch the schema next.
        try:
            self._schema.revision()
        except Exception as exc:
            raise UnavailableMutationService(str(exc)) from exc
        return MutationCapabilities(target=target, operation=operation, supported=True)

    def begin(self, target: ConfigTarget, operation: MutationOperation) -> ConfigDraft:
        capabilities = self.capabilities(target, operation)
        if not capabilities.supported:
            raise MutationOperationUnsupported(
                capabilities.reason or "That operation is not supported."
            )
        token = f"schema-session-{next(self._session_ids)}"
        revision = self._schema.revision()
        self._sessions[token] = _Session(
            target=target, operation=operation, expected_revision=revision
        )
        return ConfigDraft(
            target=target,
            operation=operation,
            session_token=token,
            expected_revision=revision,
        )

    def fields(self, draft: ConfigDraft) -> tuple[FieldSpec, ...]:
        self._session_for_draft(draft)
        return self._schema.field_specs()

    def submit(
        self,
        draft: ConfigDraft,
        step_key: str,
        values: Mapping[str, object],
        *,
        discard_fields: frozenset[str] = frozenset(),
    ) -> ConfigStepResult:
        session = self._session_for_draft(draft)
        specs_by_key = {spec.key: spec for spec in self._schema.field_specs()}
        issues: list[ValidationIssue] = []
        parsed: dict[str, object] = {}
        for key, raw in values.items():
            spec = specs_by_key.get(key)
            if spec is None:
                issues.append(ValidationIssue(f"Unknown field {key!r}.", field_key=key))
                continue
            try:
                parsed[key] = spec.parse(raw).value
            except ValueError as exc:
                issues.append(ValidationIssue(str(exc), field_key=key))
        if issues:
            return ConfigStepResult(tuple(issues), session.changed_fields)

        for key in discard_fields:
            session.values.pop(key, None)
        session.values.update(parsed)
        session.changed_fields = frozenset(session.values)
        self._invalidate_apply_token(session)
        session.planned_candidate = None
        return ConfigStepResult(changed_fields=session.changed_fields)

    def plan(self, draft: ConfigDraft) -> ConfigPlan:
        session = self._session_for_draft(draft)
        # Overlaid on the currently stored values, not just what this session
        # touched: an update that only changes one field must still validate
        # and diff the complete configuration, not a candidate missing every
        # field the operator didn't happen to resubmit.
        stored = self._schema.load()
        candidate = {**stored, **session.values}
        issues = list(self._schema.validate(candidate))
        warnings = tuple(
            issue.message for issue in issues if issue.status is SemanticStatus.WARNING
        )
        sensitive_fields = frozenset(
            spec.key for spec in self._schema.field_specs() if spec.masks_value
        )
        diff = build_config_diff(
            session.target, stored, candidate, sensitive_fields=sensitive_fields
        )
        has_error = any(issue.status is SemanticStatus.ERROR for issue in issues)
        self._invalidate_apply_token(session)
        session.planned_candidate = None
        apply_token: str | None = None
        if not has_error:
            apply_token = f"schema-plan-{next(self._plan_ids)}"
            session.apply_token = apply_token
            session.planned_candidate = candidate
            self._apply_tokens[apply_token] = draft.session_token
        return ConfigPlan(
            target=session.target,
            operation=session.operation,
            diff=diff,
            issues=tuple(issues),
            warnings=warnings,
            apply_token=apply_token,
            expected_revision=session.expected_revision,
        )

    def apply(self, intent: ConfigApplyIntent) -> ConfigApplyResult:
        session_token = self._apply_tokens.pop(intent.apply_token, None)
        if session_token is None:
            return ConfigApplyResult(
                ConfigApplyStatus.REJECTED, "The apply plan is no longer valid."
            )
        session = self._sessions[session_token]
        session.apply_token = None
        if intent.target != session.target or intent.operation != session.operation:
            return ConfigApplyResult(
                ConfigApplyStatus.REJECTED,
                "The apply plan does not match the requested target or operation.",
            )
        # Checked against what this session captured at begin(), not only the
        # store's current value -- otherwise a stale token could be replayed
        # against today's revision and slip past the conflict check below
        # with a candidate planned against an older configuration.
        if intent.expected_revision != session.expected_revision:
            return ConfigApplyResult(
                ConfigApplyStatus.REJECTED,
                "The apply plan was not prepared for that configuration revision.",
            )
        candidate = session.planned_candidate
        if candidate is None:
            return ConfigApplyResult(
                ConfigApplyStatus.REJECTED,
                "The apply plan has no prepared configuration candidate.",
            )
        try:
            self._schema.save(
                candidate,
                expected_revision=session.expected_revision,
            )
        except ConfigSchemaConflictError:
            return ConfigApplyResult(
                ConfigApplyStatus.CONFLICTED,
                "Configuration changed before this plan could be applied.",
                detail="Reload the configuration and review the change again.",
            )
        except ConfigSchemaRejectedError:
            return ConfigApplyResult(
                ConfigApplyStatus.REJECTED,
                "The configuration change was rejected.",
                detail="Review the current configuration and prepare a new plan.",
            )
        except Exception:  # noqa: BLE001 - translated to a secret-safe provider result
            return ConfigApplyResult(
                ConfigApplyStatus.FAILED,
                "The configuration could not be saved.",
                detail="The previous configuration remains authoritative.",
            )
        self._sessions.pop(session_token, None)
        return ConfigApplyResult(
            ConfigApplyStatus.APPLIED, "Configuration applied.",
        )

    def cancel(self, draft: ConfigDraft) -> None:
        session = self._sessions.pop(draft.session_token, None)
        if session is not None and session.apply_token is not None:
            self._apply_tokens.pop(session.apply_token, None)

    def _session_for_draft(self, draft: ConfigDraft) -> _Session:
        try:
            session = self._sessions[draft.session_token]
        except KeyError:
            raise ValueError("The mutation session is no longer valid.") from None
        if draft.target != session.target or draft.operation != session.operation:
            raise ValueError("The mutation draft does not match its session.")
        return session

    def _invalidate_apply_token(self, session: _Session) -> None:
        if session.apply_token is not None:
            self._apply_tokens.pop(session.apply_token, None)
            session.apply_token = None
        session.planned_candidate = None
