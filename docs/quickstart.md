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

The demo composes overview, configuration, and telemetry pages. It also registers a small
action so the app spec and action registry can be exercised without a consumer application.

The demo source is the shortest complete example of the composition root; read
`src/groundskeeping/demo.py` alongside this guide.

## Build your first page

A page is an ordinary Textual widget that satisfies the
[`OperatorPage`][groundskeeping.contracts.pages.OperatorPage] protocol. The shell mounts it
once, then activates and deactivates it as the operator moves between tabs.

```python
from textual.widget import Widget

from groundskeeping.contracts import (
    CatalogueItem,
    EmptyView,
    PageContext,
    PageRoute,
    SurfaceView,
)

SETUP_ROUTE = PageRoute(key="setup", label="Setup", purpose="Check the environment")


class SetupPage(Widget):
    route = SETUP_ROUTE

    def activate(self, context: PageContext) -> None: ...

    def deactivate(self, context: PageContext) -> None: ...

    def build_catalogue(self, context: PageContext) -> tuple[CatalogueItem, ...]:
        return (CatalogueItem(key="config", label="Configuration", kind="area"),)

    def landing_view(self, context: PageContext) -> SurfaceView:
        return EmptyView(title="Setup", message="Select an area from the catalogue.")

    def catalogue_selected(self, item: CatalogueItem, context: PageContext) -> None: ...

    def row_highlighted(self, row_key: str, context: PageContext) -> None: ...

    def row_selected(self, row_key: str, context: PageContext) -> None: ...
```

Register it in an `OperatorAppSpec` and run the app. Start read-only: a page that only
inspects is enough to exercise routing, the workbench, and failure presentation before you
take ownership of durable changes.

## Run the tests

```bash
uv sync --all-extras --dev
uv run pytest -q
uv run ruff check .
uv run ty check src/
```

The tests cover route validation, app startup, action and job contracts, configurator
redaction, telemetry import boundaries, and consumer dependency boundaries.
