from __future__ import annotations

import json

import pytest

from groundskeeping.contracts import Command, CommandPlan, CommandStep, retry_plan


def _step(
    key: str,
    *,
    resources: tuple[str, ...] = (),
    idempotent: bool = True,
) -> CommandStep:
    return CommandStep(
        key=key,
        command=Command(argv=("worker", key)),
        affected_resources=resources,
        idempotent=idempotent,
    )


def test_command_display_quotes_values_and_keeps_environment_first() -> None:
    command = Command(
        argv=("worker", "argument with spaces"),
        environment=(("CONFIG", "/tmp/config.yaml"), ("LABEL", "needs quoting")),
    )

    assert command.display == (
        "CONFIG=/tmp/config.yaml LABEL='needs quoting' worker 'argument with spaces'"
    )


def test_command_plan_resources_are_ordered_and_deduplicated() -> None:
    plan = CommandPlan(
        kind="example",
        affected_resources=("plan:first", "shared"),
        steps=(
            _step("one", resources=("shared", "step:first")),
            _step("two", resources=("step:first", "step:second")),
        ),
    )

    assert plan.resources == ("plan:first", "shared", "step:first", "step:second")


def test_retry_plan_returns_the_suffix_after_the_first_incomplete_step() -> None:
    steps = (_step("one"), _step("two", resources=("db",)), _step("three"))
    plan = CommandPlan(
        kind="example", steps=steps, affected_resources=("plan-resource",)
    )

    retried = retry_plan(plan, succeeded=(True, False, False))

    assert retried == CommandPlan(
        kind="example",
        steps=steps[1:],
        affected_resources=("plan-resource",),
    )


def test_retry_plan_rejects_a_non_idempotent_incomplete_step() -> None:
    steps = (_step("one"), _step("two", idempotent=False))

    with pytest.raises(ValueError, match="not safe to retry"):
        retry_plan(CommandPlan(kind="example", steps=steps), succeeded=(True, False))


def test_retry_plan_requires_one_status_per_step() -> None:
    with pytest.raises(ValueError, match="one value per step"):
        retry_plan(
            CommandPlan(kind="example", steps=(_step("one"),)),
            succeeded=(),
        )


def test_command_step_json_shape_round_trips_like_existing_run_records() -> None:
    step = CommandStep(
        key="embed",
        command=Command(
            argv=("worker", "--mode", "full"),
            environment=(("OA_CONFIG_PATH", "/tmp/config.yaml"),),
        ),
        affected_resources=("db:concept",),
        idempotent=False,
    )
    persisted = {
        "key": step.key,
        "command": {
            "argv": list(step.command.argv),
            "environment": [list(pair) for pair in step.command.environment],
            "display": step.command.display,
        },
        "affected_resources": list(step.affected_resources),
        "idempotent": step.idempotent,
    }

    restored_data = json.loads(json.dumps(persisted))
    restored_command = Command(
        argv=tuple(restored_data["command"]["argv"]),
        environment=tuple(tuple(pair) for pair in restored_data["command"]["environment"]),
    )
    restored = CommandStep(
        key=restored_data["key"],
        command=restored_command,
        affected_resources=tuple(restored_data["affected_resources"]),
        idempotent=restored_data["idempotent"],
    )

    assert persisted == {
        "key": "embed",
        "command": {
            "argv": ["worker", "--mode", "full"],
            "environment": [["OA_CONFIG_PATH", "/tmp/config.yaml"]],
            "display": "OA_CONFIG_PATH=/tmp/config.yaml worker --mode full",
        },
        "affected_resources": ["db:concept"],
        "idempotent": False,
    }
    assert restored == step
