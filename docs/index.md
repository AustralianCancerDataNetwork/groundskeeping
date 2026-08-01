# groundskeeping

`groundskeeping` is a reusable Textual shell for operator tools that help people care for a
working environment: setup checks, configuration, queues, telemetry, tuning, and long-running
operations.

The package provides the shared operating frame. A consumer application provides the domain.
Keep that distinction close and most design decisions become simpler.

## Install

```bash
uv add groundskeeping
```

## What you get

| Area | What the shell provides |
|---|---|
| [Pages and the Workbench](pages.md) | Route validation, tab navigation, mounted-page state, and the three-pane workbench surface |
| [Actions and Jobs](actions.md) | Field parsing and redaction, operation policy, progress and cancellation, in-process job gating |
| [Configuration](configuration.md) | Read-only inspection of `oa-configurator` stack config, plus draft and redacted-diff models |
| [Telemetry](telemetry.md) | Textual-free source protocols, normalized metrics, sampling runtime, and widgets that render them |

## The shape of an app

A `groundskeeping` app starts with one
[`OperatorAppSpec`][groundskeeping.app.OperatorAppSpec]. The spec names the app, orders the
pages, registers the actions, and supplies the policies that decide whether work may run.

It is the composition root: everything application-specific should arrive there from the
consumer, not through global lookup inside the shared package.

```python
from groundskeeping.app import OperatorApp, OperatorAppSpec
from groundskeeping.contracts import ActionRegistry, PageRegistration, PageRoute

spec = OperatorAppSpec(
    app_id="my-tool",
    title="My Tool",
    subtitle="operator shell",
    pages=(
        PageRegistration(
            route=PageRoute(key="setup", label="Setup", purpose="Check the environment"),
            factory=lambda context: SetupPage(),
        ),
    ),
    actions=ActionRegistry(()),
)

OperatorApp(spec).run()
```

See [Getting Started](quickstart.md) to run the bundled demo, and
[Ownership Boundary](ownership.md) for what belongs in the shell versus your application.
