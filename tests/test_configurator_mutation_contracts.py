from __future__ import annotations

import pytest

from groundskeeping.configurator import (
    ConfigApplyIntent,
    ConfigApplyStatus,
    ConfigDiffEntry,
    ConfigDraft,
    ConfigPlan,
    ConfigTarget,
    ConfigTargetKind,
    EffectRef,
    MutationOperation,
    RedactedValue,
    build_config_diff,
)
from groundskeeping.configurator.providers.fake import (
    FakeConfigMutationService,
    FakeMutationScenario,
)
from groundskeeping.contracts import SemanticStatus, ValidationIssue


def _target() -> ConfigTarget:
    return ConfigTarget(
        kind=ConfigTargetKind.DATABASE,
        key="metadata",
        title="Metadata database",
    )


def test_draft_tracks_only_safe_identity_and_changed_field_presence() -> None:
    draft = ConfigDraft(
        target=_target(),
        operation=MutationOperation.UPDATE,
        session_token="opaque-session",
        changed_fields=frozenset({"connection_url", "password"}),
        expected_revision="opaque-revision",
    )

    assert draft.changed
    assert draft.changed_fields == frozenset({"connection_url", "password"})
    assert not hasattr(draft, "values")


def test_diff_replaces_sensitive_values_before_repr() -> None:
    canary = "mutation-contract-secret"
    diff = build_config_diff(
        _target(),
        {"connection_url": "postgresql://old", "password": "old-secret"},
        {"connection_url": "postgresql://new", "password": canary},
        sensitive_fields=frozenset({"password"}),
    )

    password = next(entry for entry in diff.entries if entry.field == "password")
    assert isinstance(password.before, RedactedValue)
    assert isinstance(password.after, RedactedValue)
    assert canary not in repr(diff)
    assert "old-secret" not in repr(diff)


def test_sensitive_diff_entry_cannot_retain_directly_supplied_values() -> None:
    canary = "direct-diff-secret"
    entry = ConfigDiffEntry("password", "old-secret", canary, sensitive=True)

    assert isinstance(entry.before, RedactedValue)
    assert isinstance(entry.after, RedactedValue)
    assert canary not in repr(entry)


def test_plan_requires_an_apply_token_and_no_error_issues() -> None:
    diff = build_config_diff(_target(), {}, {"name": "metadata"})
    ready = ConfigPlan(
        target=_target(),
        operation=MutationOperation.CREATE,
        diff=diff,
        apply_token="opaque-plan",
    )
    blocked = ConfigPlan(
        target=_target(),
        operation=MutationOperation.CREATE,
        diff=diff,
        issues=(ValidationIssue("Blocked."),),
        apply_token="must-not-make-this-ready",
    )
    warning = ConfigPlan(
        target=_target(),
        operation=MutationOperation.CREATE,
        diff=diff,
        issues=(
            ValidationIssue("Check this.", status=SemanticStatus.WARNING),
        ),
        apply_token="opaque-warning-plan",
    )

    assert ready.ready
    assert not blocked.ready
    assert warning.ready


def test_effect_references_are_structural() -> None:
    effect = EffectRef(
        kind="shared-reference",
        target=_target(),
        field_key="database",
        detail="used by another entry",
    )

    assert effect.target.kind is ConfigTargetKind.DATABASE
    assert effect.field_key == "database"
    assert str(effect) == (
        "shared-reference: database:metadata.database — used by another entry"
    )


@pytest.mark.parametrize(
    ("scenario", "expected"),
    (
        (FakeMutationScenario.READY, ConfigApplyStatus.APPLIED),
        (FakeMutationScenario.CONFLICTED, ConfigApplyStatus.CONFLICTED),
        (FakeMutationScenario.REJECTED, ConfigApplyStatus.REJECTED),
        (FakeMutationScenario.FAILED, ConfigApplyStatus.FAILED),
    ),
)
def test_fake_apply_tokens_are_single_use_for_every_outcome(
    scenario: FakeMutationScenario,
    expected: ConfigApplyStatus,
) -> None:
    service = FakeConfigMutationService(scenario=scenario)
    target = _target()
    draft = service.begin(target, MutationOperation.CREATE)
    service.submit(draft, "strategy", {"strategy": "reuse"})
    staged = service.submit(
        draft, "reuse-database", {"selected_database": "metadata"}
    )
    draft = ConfigDraft(
        target=draft.target,
        operation=draft.operation,
        session_token=draft.session_token,
        changed_fields=staged.changed_fields,
        expected_revision=draft.expected_revision,
    )
    plan = service.plan(draft)
    assert plan.apply_token is not None
    intent = ConfigApplyIntent(
        target=target,
        operation=MutationOperation.CREATE,
        apply_token=plan.apply_token,
        expected_revision=draft.expected_revision,
    )

    assert service.apply(intent).status is expected
    assert service.apply(intent).status is ConfigApplyStatus.REJECTED


def test_cancel_invalidates_a_prepared_plan_without_applying() -> None:
    service = FakeConfigMutationService()
    target = _target()
    draft = service.begin(target, MutationOperation.CREATE)
    service.submit(draft, "strategy", {"strategy": "reuse"})
    service.submit(draft, "reuse-database", {"selected_database": "metadata"})
    plan = service.plan(draft)
    assert plan.apply_token is not None
    service.cancel(draft)

    result = service.apply(
        ConfigApplyIntent(
            target=target,
            operation=MutationOperation.CREATE,
            apply_token=plan.apply_token,
            expected_revision=draft.expected_revision,
        )
    )

    assert result.status is ConfigApplyStatus.REJECTED
    assert service.durable == {}


def test_unknown_session_is_a_rejection_at_the_provider_boundary() -> None:
    service = FakeConfigMutationService()

    with pytest.raises(ValueError, match="no longer valid"):
        service.plan(
            ConfigDraft(
                target=_target(),
                operation=MutationOperation.CREATE,
                session_token="not-a-session",
            )
        )
