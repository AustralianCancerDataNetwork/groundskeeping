# Actions and jobs

Actions connect operator-facing buttons to application-owned work. Use them for bounded operations such as **Test connection**, **Refresh status**, **Populate embeddings**, or **Run evaluation sample**.

## Choose the right execution model

| Work | Use | Why |
|---|---|---|
| A quick check completed by this process | `ActionSpec` with `ExecutionKind.QUICK` | The result can be shown immediately. |
| Work that should remain responsive in the TUI | `ActionSpec` plus `JobManager` | The shell can show progress and honour the declared cancellation mode. |
| Work that must survive restarts, retry, lease, or run on another worker | An application-owned durable queue | Shell jobs exist only for the lifetime of this TUI process. |
| A configuration change with review and revision checks | `ConfigWizardController` | The configuration lifecycle is richer than a general action. |

## Describe an action for the operator

An [`ActionSpec`][groundskeeping.contracts.actions.ActionSpec] carries the label, summary, input fields, effects, resources, execution mode, cancellation mode, and runner. Use language that explains both intent and scope.

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
            key="setup.verify_database",
            page_key="setup",
            label="Test database connection",
            summary="Open a read-only connection and report the server version.",
            runner=verify_database,
            fields=(
                FieldSpec(
                    key="timeout",
                    label="Timeout in seconds",
                    kind=FieldKind.INTEGER,
                    default=10,
                    minimum=1,
                    maximum=60,
                ),
            ),
            execution=ExecutionKind.QUICK,
            resource_refs=frozenset({"database:metadata"}),
        ),
    )
)
```

`ActionRegistry` checks key uniqueness and, when page keys are supplied, verifies that every action belongs to a registered page.

## Collect and protect inputs

[`FieldSpec`][groundskeeping.contracts.actions.FieldSpec] converts raw form input into a real value for the runner and a presentation-safe value for confirmation and results.

| Input | `FieldKind` | Useful options |
|---|---|---|
| Short text | `TEXT` | `placeholder`, `validator` |
| Password, key, or token | `SECRET` | `sensitive`, `secret_clearable` |
| Longer free text | `MULTILINE` | `placeholder`, `validator` |
| Whole or decimal number | `INTEGER`, `DECIMAL` | `minimum`, `maximum` |
| Yes/no value | `BOOLEAN` | `default` |
| One declared option | `CHOICE` | `choices` |
| Existing input path | `EXISTING_PATH` | Existence is checked during parsing. |
| Destination path | `OUTPUT_PATH` | `~` is expanded, but the path is not created. |

A field is masked when its kind is `SECRET` or `sensitive=True`. Its presentation value becomes `<redacted>`. Sensitive validator messages are also replaced with a generic field error so a validator cannot echo a submitted credential into the UI or logs.

Use `preflight` for validation that depends on several parsed fields or current application state. Keep lasting business rules in the application service as well; UI validation improves guidance but is not an authorization boundary.

## Report progress without importing Textual

The runner receives an [`ActionContext`][groundskeeping.contracts.actions.ActionContext] with a progress sink and cancellation token. It can remain headless and easy to test.

```python
from collections.abc import Mapping

from groundskeeping.contracts import (
    ActionContext,
    ActionOutcome,
    EmptyView,
    SemanticStatus,
)


def verify_database(
    params: Mapping[str, object],
    context: ActionContext,
) -> ActionOutcome:
    context.emit("connect", completed=0, total=1, message="Opening a read-only connection")
    version = database_service.server_version(timeout=int(params["timeout"]))
    context.emit("connect", completed=1, total=1, message="Connection verified")
    return ActionOutcome(
        status=SemanticStatus.OK,
        summary="Database connection verified",
        view=EmptyView(
            title="Database connection",
            message=f"Server {version} accepted a read-only connection.",
            status=SemanticStatus.OK,
        ),
    )
```

`ActionOutcome.view` can be any `SurfaceView`. Use a `TableView` when the result contains comparable checks, a `TreeView` for nested readiness, or an `EmptyView` for one concise result. `refresh_pages` identifies pages whose displayed state became stale.

`run_action_sync()` is useful in tests and small demos: it parses fields, runs preflight validation, creates an action context, and returns the outcome without constructing the TUI.

## Gate effects with operation policy

`OperationPolicy` decides whether an action may proceed and what the operator should be told before it runs. `AllowAllOperationPolicy` is a permissive default for low-risk applications and demos.

Production applications should use their own vocabulary and policy when actions consume shared resources, alter durable state, or need an explicit confirmation. `resource_refs` and `effect_refs` give policy stable identifiers without teaching Groundskeeping about application objects.

## Treat shell jobs as temporary

`JobManager` tracks work launched by the current TUI and provides progress and cancellation state. `SingleForegroundJobPolicy` allows one foreground job at a time.

Do not use it as a durable queue. Keep retry rules, leases, persisted job records, recovery after restart, and remote-worker coordination in the consuming application. The page can adapt that durable state into Groundskeeping views without transferring ownership to the shell.
