# Getting Started

## Install

```bash
uv add groundskeeping
```

`groundskeeping` requires Python 3.12 or newer and pulls in `textual` and `oa-configurator`.

## Run the demo

```bash
uv run groundskeeping
```

The demo shows the shell without depending on Groundworkers or `cava-nlp-shard`. It includes
overview, configuration, telemetry, an action button, and a small setup wizard.

The demo source is the shortest complete example of the app shape; read
`src/groundskeeping/demo.py` alongside this guide.

## Build your first page

A page is an ordinary Textual widget that satisfies the
[`OperatorPage`][groundskeeping.contracts.pages.OperatorPage] protocol. The shell mounts it
once, then activates and deactivates it as the operator moves between tabs.

```python
from textual.widget import Widget

from groundskeeping.contracts import (
    EmptyView,
    NavigationItem,
    PageContext,
    PageRoute,
    SectionItem,
    SectionNavigation,
    SurfaceView,
)

SETUP_ROUTE = PageRoute(key="setup", label="Setup", purpose="Check the environment")


class SetupPage(Widget):
    route = SETUP_ROUTE

    def activate(self, context: PageContext) -> None: ...

    def deactivate(self, context: PageContext) -> None: ...

    def build_navigation(self, context: PageContext) -> SectionNavigation:
        return SectionNavigation(items=(SectionItem("config", "Configuration"),))

    def landing_view(self, context: PageContext) -> SurfaceView:
        return EmptyView(title="Setup", message="Select a setup section.")

    def navigation_selected(self, item: NavigationItem, context: PageContext) -> None: ...

    def action_selected(self, action_key: str, context: PageContext) -> None: ...

    def row_highlighted(self, row_key: str, context: PageContext) -> None: ...

    def row_selected(self, row_key: str, context: PageContext) -> None: ...
```

Register it in an `OperatorAppSpec` and run the app. Start read-only: a page that only
inspects is enough to exercise routing, the workbench, and failure presentation before you
add durable changes.

## Run the tests

```bash
uv sync --all-extras --dev
uv run pytest -q
uv run ruff check .
uv run ty check src/
```

The tests cover route validation, app startup, action and job contracts, wizard branching and
redaction, configuration redaction, telemetry import boundaries, and application dependency
boundaries.
