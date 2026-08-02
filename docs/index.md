# groundskeeping

`groundskeeping` is a reusable Textual shell for operator tools: setup checks, configuration,
queues, telemetry, tuning, and long-running operations.

It provides the common TUI pieces; each application decides what those pieces mean. In
Groundworkers, that means setup pages for database configuration, embeddings, and semantic
projection. In `cava-nlp-shard`, it means pages for evaluation runs, runtime configuration,
and model/backend health.

## Install

```bash
uv add groundskeeping
```

## What you get

| Area | What it is useful for |
|---|---|
| [Pages and the Workbench](pages.md) | Put application-owned pages into a consistent tabbed shell |
| [Actions and Jobs](actions.md) | Add safe buttons for things like testing a connection or running a bounded check |
| [Setup Wizards](wizards.md) | Guide an operator through multi-step setup without putting secrets in view state |
| [Configuration](configuration.md) | Inspect `oa-configurator` stack config and prepare safe, redacted edits |
| [Telemetry](telemetry.md) | Sample simple infrastructure metrics and render them in the TUI |

## The shape of an app

A `groundskeeping` app starts with one
[`OperatorAppSpec`][groundskeeping.app.OperatorAppSpec]. The spec names the app, orders the
pages, registers actions, and supplies the policies that decide whether work may run.

Application-specific services arrive through page factories. The shared package should not
import Groundworkers, `cava-nlp-shard`, or any other application that happens to use it.

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
[What belongs where](ownership.md) for what belongs in the shell versus your application.
