"""Portable progress, cancellation, and shell-job contracts.

Shell jobs are deliberately smaller than consumer domain queues. A job here is work that
this TUI process started and can present, gate, or cancel. Durable processing queues,
leases, retries, and run records stay with the consuming application.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from threading import Event
from time import monotonic
from typing import Protocol
from uuid import uuid4


class CancellationRequested(RuntimeError):
    """Raised by cooperative runners when the operator has requested cancellation."""


class CancellationMode(StrEnum):
    """How the shell should present and route cancellation for an action."""

    UNSUPPORTED = "unsupported"
    COOPERATIVE = "cooperative"
    IMMEDIATE = "immediate"


class CancellationToken(Protocol):
    """Structural cancellation contract passed into consumer runners."""

    @property
    def requested(self) -> bool: ...

    def raise_if_requested(self) -> None: ...


class ThreadCancellationToken:
    """Thread-safe default cancellation token for ordinary shell workers."""

    def __init__(self) -> None:
        self._event = Event()

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    def request(self) -> None:
        self._event.set()

    def raise_if_requested(self) -> None:
        if self.requested:
            raise CancellationRequested("Operation cancelled by the operator.")


@dataclass(frozen=True)
class ProgressEvent:
    """One portable progress update emitted by a runner."""

    event: str
    phase: str | None = None
    completed: int = 0
    total: int | None = None
    unit: str | None = None
    message: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def fraction(self) -> float | None:
        if self.total in (None, 0):
            return None
        return max(0.0, min(1.0, self.completed / self.total))


class ProgressSink(Protocol):
    """Consumer runners call this; widgets never need to know the runner type."""

    def emit(self, event: ProgressEvent) -> None: ...


class RecordingProgressSink:
    """Small sink used by tests, demos, and synchronous action execution."""

    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    def emit(self, event: ProgressEvent) -> None:
        self.events.append(event)


@dataclass(frozen=True)
class JobSpec:
    """What the shell needs to decide whether work may start."""

    key: str
    label: str
    resources: frozenset[str] = frozenset()
    effects: frozenset[str] = frozenset()
    cancellation: CancellationMode = CancellationMode.UNSUPPORTED
    foreground: bool = True


@dataclass(frozen=True)
class JobSnapshot:
    """Immutable view of a shell job for policy, bars, and tests."""

    job_id: str
    spec: JobSpec
    started_at: float
    progress: ProgressEvent | None = None
    cancelling: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def fraction(self) -> float | None:
        return None if self.progress is None else self.progress.fraction

    @property
    def cancellable(self) -> bool:
        return self.spec.cancellation is not CancellationMode.UNSUPPORTED

    @property
    def elapsed(self) -> float:
        return max(0.0, monotonic() - self.started_at)

    def describe(self) -> str:
        if self.progress and self.progress.message:
            return f"{self.spec.label}: {self.progress.message}"
        if self.progress and self.progress.phase:
            return f"{self.spec.label}: {self.progress.phase}"
        return self.spec.label


@dataclass(frozen=True)
class BlockDecision:
    """Policy answer for whether a candidate job can start."""

    allowed: bool
    reason: str | None = None

    @classmethod
    def allow(cls) -> BlockDecision:
        return cls(True)

    @classmethod
    def block(cls, reason: str) -> BlockDecision:
        return cls(False, reason)


class JobPolicy(Protocol):
    """In-process gate for shell jobs."""

    def can_start(self, candidate: JobSpec, active: Sequence[JobSnapshot]) -> BlockDecision: ...


class SingleForegroundJobPolicy:
    """Default policy: one foreground job, plus no overlapping explicit resources."""

    def can_start(self, candidate: JobSpec, active: Sequence[JobSnapshot]) -> BlockDecision:
        if candidate.foreground and any(job.spec.foreground for job in active):
            return BlockDecision.block("another foreground job is already running")
        for job in active:
            overlap = candidate.resources & job.spec.resources
            if overlap:
                resources = ", ".join(sorted(overlap))
                return BlockDecision.block(f"resource already in use: {resources}")
        return BlockDecision.allow()


class JobManager:
    """Multi-job-capable manager with a conservative default policy.

    The manager does not execute work itself. Textual workers, threads, or synchronous test
    harnesses own execution and report lifecycle changes back here.
    """

    def __init__(self, policy: JobPolicy | None = None) -> None:
        self.policy = policy or SingleForegroundJobPolicy()
        self._active: dict[str, tuple[JobSnapshot, ThreadCancellationToken]] = {}

    @property
    def active(self) -> tuple[JobSnapshot, ...]:
        return tuple(snapshot for snapshot, _token in self._active.values())

    @property
    def foreground(self) -> JobSnapshot | None:
        return next((job for job in self.active if job.spec.foreground), None)

    def can_start(self, spec: JobSpec) -> BlockDecision:
        return self.policy.can_start(spec, self.active)

    def start(
        self,
        spec: JobSpec,
        *,
        job_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> tuple[JobSnapshot, ThreadCancellationToken]:
        decision = self.can_start(spec)
        if not decision.allowed:
            raise RuntimeError(decision.reason or "Job cannot start.")
        resolved_id = job_id or f"{spec.key}:{uuid4().hex}"
        token = ThreadCancellationToken()
        snapshot = JobSnapshot(
            job_id=resolved_id,
            spec=spec,
            started_at=monotonic(),
            metadata=dict(metadata or {}),
        )
        self._active[resolved_id] = (snapshot, token)
        return snapshot, token

    def update(self, job_id: str, progress: ProgressEvent) -> JobSnapshot:
        snapshot, token = self._active[job_id]
        updated = JobSnapshot(
            job_id=snapshot.job_id,
            spec=snapshot.spec,
            started_at=snapshot.started_at,
            progress=progress,
            cancelling=snapshot.cancelling,
            metadata=snapshot.metadata,
        )
        self._active[job_id] = (updated, token)
        return updated

    def request_cancel(self, job_id: str) -> JobSnapshot:
        snapshot, token = self._active[job_id]
        token.request()
        updated = JobSnapshot(
            job_id=snapshot.job_id,
            spec=snapshot.spec,
            started_at=snapshot.started_at,
            progress=snapshot.progress,
            cancelling=True,
            metadata=snapshot.metadata,
        )
        self._active[job_id] = (updated, token)
        return updated

    def complete(self, job_id: str) -> JobSnapshot:
        snapshot, _token = self._active.pop(job_id)
        return snapshot
