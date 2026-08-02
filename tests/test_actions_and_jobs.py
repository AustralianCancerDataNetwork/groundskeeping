from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import pytest

from groundskeeping.contracts import (
    ActionContext,
    ActionOutcome,
    ActionRegistry,
    ActionSpec,
    CancellationMode,
    EmptyView,
    ExecutionKind,
    FieldKind,
    FieldSpec,
    JobManager,
    JobSpec,
    ProgressEvent,
    SemanticStatus,
    SingleForegroundJobPolicy,
    ThreadCancellationToken,
    run_action_sync,
)


def test_field_spec_parses_types_and_redacts_sensitive_values() -> None:
    batch = FieldSpec("batch", "Batch", kind=FieldKind.INTEGER, minimum=1, maximum=1024)
    threshold = FieldSpec("threshold", "Threshold", kind=FieldKind.DECIMAL)
    secret = FieldSpec("password", "Password", kind=FieldKind.SECRET)

    assert batch.parse("512").value == 512
    assert threshold.parse("0.5").value == Decimal("0.5")
    assert secret.parse("not-for-display").redacted == "<redacted>"

    with pytest.raises(ValueError, match="at most 1024"):
        batch.parse("2048")


def test_action_registry_validates_unique_keys_and_page_references() -> None:
    def runner(params: Mapping[str, object], context: ActionContext) -> None:
        return None

    action = ActionSpec("overview.echo", "overview", "Echo", "Echo test", runner)

    with pytest.raises(ValueError, match="unique"):
        ActionRegistry((action, action))

    with pytest.raises(ValueError, match="unknown pages"):
        ActionRegistry((action,), page_keys=("telemetry",))


def test_run_action_sync_parses_preflights_and_presents_outcome() -> None:
    def runner(params: Mapping[str, object], context: ActionContext) -> ActionOutcome:
        context.emit("step", completed=1, total=1, message="done")
        context.cancellation.raise_if_requested()
        return ActionOutcome(
            status=SemanticStatus.OK,
            summary=f"Batch {params['batch']}",
            view=EmptyView(title="Done", message="Completed."),
        )

    action = ActionSpec(
        key="tune.batch",
        page_key="telemetry",
        label="Tune batch",
        summary="Try one batch size.",
        runner=runner,
        fields=(FieldSpec("batch", "Batch", kind=FieldKind.INTEGER, minimum=1),),
        execution=ExecutionKind.QUICK,
    )

    outcome = run_action_sync(action, {"batch": "128"}, ThreadCancellationToken())

    assert outcome.summary == "Batch 128"


def test_single_foreground_job_policy_blocks_foreground_and_resource_overlap() -> None:
    manager = JobManager(SingleForegroundJobPolicy())
    first, _token = manager.start(
        JobSpec(
            key="embed",
            label="Embed",
            resources=frozenset({"gpu:0"}),
            cancellation=CancellationMode.COOPERATIVE,
        ),
        job_id="job-1",
    )

    blocked_foreground = manager.can_start(JobSpec(key="llm", label="LLM"))
    blocked_resource = manager.can_start(
        JobSpec(key="sample", label="Sample", resources=frozenset({"gpu:0"}), foreground=False)
    )

    assert first.cancellable
    assert not blocked_foreground.allowed
    assert not blocked_resource.allowed

    updated = manager.update("job-1", ProgressEvent("batch", completed=50, total=100, message="halfway"))
    assert updated.fraction == 0.5
    assert manager.request_cancel("job-1").cancelling
    assert manager.complete("job-1").job_id == "job-1"
