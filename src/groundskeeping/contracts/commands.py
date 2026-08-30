"""Headless declarative command-plan contracts.

These types describe work; they do not execute commands or persist run state. A
``CommandPlan.resources`` tuple is ordered for display and lock ordering, while the
existing ``JobSpec.resources`` field is an unordered policy set. Consumers should
convert between them explicitly at their boundary when needed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    """One command and the environment entries passed to it."""

    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...] = ()

    @property
    def display(self) -> str:
        """Return a shell-readable display without changing the command."""

        parts = [f"{key}={_shell_quote(value)}" for key, value in self.environment]
        parts.extend(_shell_quote(part) for part in self.argv)
        return " ".join(parts)


@dataclass(frozen=True)
class CommandStep:
    """One ordered command in a plan."""

    key: str
    command: Command
    affected_resources: tuple[str, ...] = ()
    idempotent: bool = True


@dataclass(frozen=True)
class CommandPlan:
    """A serialisable ordered plan of commands."""

    kind: str
    steps: tuple[CommandStep, ...]
    affected_resources: tuple[str, ...] = ()

    @property
    def resources(self) -> tuple[str, ...]:
        """Return plan and step resources in first-seen order without duplicates."""

        return tuple(
            dict.fromkeys(
                (
                    *self.affected_resources,
                    *(
                        resource
                        for step in self.steps
                        for resource in step.affected_resources
                    ),
                )
            )
        )


def retry_plan(
    plan: CommandPlan,
    *,
    succeeded: Sequence[bool],
) -> CommandPlan:
    """Return the safe suffix of a failed plan for retry.

    The first incomplete step and every step after it must be idempotent. The
    returned plan contains only that suffix; creating a durable run remains the
    responsibility of the consuming application.
    """

    if len(succeeded) != len(plan.steps):
        raise ValueError("succeeded must contain one value per step")

    first_incomplete = next(
        (index for index, complete in enumerate(succeeded) if not complete),
        len(plan.steps),
    )
    remaining = plan.steps[first_incomplete:]
    if any(not step.idempotent for step in remaining):
        raise ValueError("The first incomplete step is not safe to retry.")
    return CommandPlan(
        kind=plan.kind,
        steps=remaining,
        affected_resources=plan.affected_resources,
    )


def _shell_quote(value: str) -> str:
    if value and all(ch.isalnum() or ch in "-_./:=+" for ch in value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


__all__ = ["Command", "CommandPlan", "CommandStep", "retry_plan"]
