# Actions and Jobs

Actions are buttons with a runner behind them. Use them for bounded operations such as
**Test connection**, **Refresh status**, **Populate embeddings**, or **Run evaluation sample**.

## ActionSpec

An [`ActionSpec`][groundskeeping.contracts.actions.ActionSpec] describes the operator-facing
command: label, summary, fields, resources, effects, cancellation mode, and runner.

`ActionRegistry` validates at startup that action keys are unique and that every `page_key`
refers to a registered page.

```python
from groundskeeping.contracts import (
    ActionRegistry,
    ActionSpec,
    ExecutionKind,
    FieldKind,
    FieldSpec,
)

registry = ActionRegistry(
    (
        ActionSpec(
            key="setup.verify",
            page_key="setup",
            label="Verify connection",
            summary="Open a read-only connection and report the server version.",
            runner=verify_runner,
            fields=(FieldSpec(key="timeout", label="Timeout", kind=FieldKind.INTEGER),),
            execution=ExecutionKind.QUICK,
        ),
    )
)
```

## Fields, parsing, and redaction

[`FieldSpec`][groundskeeping.contracts.actions.FieldSpec] parses and redacts input before it
reaches the runner. Each field declares a `FieldKind` — `TEXT`, `SECRET`, `MULTILINE`, `INTEGER`, `DECIMAL`,
`BOOLEAN`, `CHOICE`, `EXISTING_PATH`, or `OUTPUT_PATH` — and `parse` returns both the real
value and a presentation-safe value.

A field is masked when it is explicitly `sensitive` or when its kind is `SECRET`. Masked
values render as `<redacted>` in confirmations, diffs, and result surfaces.

Numeric fields validate bounds through `minimum` and `maximum`, and any field may carry a
`validator` that returns a `ValidationIssue`. Parsing failures raise `ValueError` with the
field's operator-facing label, not its key.

## Running an action

The runner receives an [`ActionContext`][groundskeeping.contracts.actions.ActionContext] with
progress and cancellation. That lets a runner report useful status without importing Textual
widgets.

```python
from collections.abc import Mapping

from groundskeeping.contracts import (
    ActionContext,
    ActionOutcome,
    SemanticStatus,
    TableRow,
    TableView,
)


def verify_runner(params: Mapping[str, object], context: ActionContext) -> ActionOutcome:
    context.emit("verify", completed=0, total=1, message="connecting")
    ...
    return ActionOutcome(
        status=SemanticStatus.OK,
        summary="Connection verified",
        view=TableView(
            title="Connection",
            columns=("check", "result"),
            rows=(TableRow(key="server", cells=("server", "postgres 16.2")),),
        ),
    )
```

`ActionOutcome.view` is a `SurfaceView` — `TableView`, `TreeView`, `EmptyView`, or
`LoadingView` — so an action decides how its own result is presented in the upper-right pane.
`refresh_pages` names the page keys whose content is now stale.

`run_action_sync` runs an action end to end for tests, demos, and simple quick actions: it
parses params, runs preflight validation, builds a context, and returns the outcome.

## Operation policy

`OperationPolicy` decides whether an action may proceed and what the operator is told first.
`AllowAllOperationPolicy` is the permissive default. Applications can substitute a policy that
uses their own vocabulary and blocks unsafe operations.

## Jobs

A shell job is work launched by this TUI process. It is **not** a durable processing queue.

Use [`JobManager`][groundskeeping.contracts.jobs.JobManager] and `JobPolicy` to gate
in-process work and show progress. `SingleForegroundJobPolicy` is the default and allows one
foreground job at a time.

Keep queue state, retries, leases, and durable records inside the application. The shell tracks
what is running right now so it can render progress and honour cancellation; it does not
remember work across restarts.
