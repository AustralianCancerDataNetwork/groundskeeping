# Developer quickstart

This guide builds the smallest useful Groundskeeping application: one page with a section list and a readiness summary. If you are operating an existing application, start with [Using a Groundskeeping app](operator-guide.md) instead.

## Install

Groundskeeping requires Python 3.12 or newer and oa-configurator 1.1 or later within the 1.x series.

```bash
uv add groundskeeping
```

## Run the demo first

```bash
uv run groundskeeping
```

The demo has Overview, Configuration, Telemetry, and Setup pages and does not depend on Groundworkers or `cava-nlp-shard`. Its configuration page uses the deterministic fake mutation provider, so no file is written. The Setup page demonstrates an ordinary results table whose highlighted row fills the lower detail pane; the source in `src/groundskeeping/demo.py` is also a useful composition reference.

## Build one page

A page is an ordinary Textual widget that satisfies the [`OperatorPage`][groundskeeping.contracts.pages.OperatorPage] protocol. Keep application services on the page; the shell passes a narrow `PageContext` for navigation, rendering, notifications, and wizards.

```python
from textual.widget import Widget

from groundskeeping.app import OperatorApp, OperatorAppSpec
from groundskeeping.contracts import (
    NavigationItem,
    PageContext,
    PageRegistration,
    PageRoute,
    SectionItem,
    SectionNavigation,
    SemanticStatus,
    SurfaceView,
    TreeNode,
    TreeView,
)

SETUP_ROUTE = PageRoute(
    key="setup",
    label="Setup",
    purpose="Check whether this environment is ready.",
)


class SetupPage(Widget):
    route = SETUP_ROUTE

    def activate(self, context: PageContext) -> None:
        pass

    def deactivate(self, context: PageContext) -> None:
        pass

    def build_navigation(self, context: PageContext) -> SectionNavigation:
        return SectionNavigation(
            items=(
                SectionItem(
                    key="database",
                    label="Database",
                    status=SemanticStatus.OK,
                    description="Connection and schema checks",
                ),
            ),
            title="Setup areas",
        )

    def landing_view(self, context: PageContext) -> SurfaceView:
        return TreeView(
            title="Environment readiness",
            rows=(
                TreeNode(
                    label="Database",
                    status=SemanticStatus.OK,
                    fields={"connection": "available"},
                ),
            ),
        )

    def navigation_selected(self, item: NavigationItem, context: PageContext) -> None:
        context.surface.show_view(self.route.key, self.landing_view(context))

    def action_selected(self, action_key: str, context: PageContext) -> None:
        pass

    def row_highlighted(self, row_key: str, context: PageContext) -> None:
        pass

    def row_selected(self, row_key: str, context: PageContext) -> None:
        pass


spec = OperatorAppSpec(
    app_id="my-tool",
    title="My Tool",
    subtitle="environment setup",
    pages=(
        PageRegistration(
            route=SETUP_ROUTE,
            factory=lambda context: SetupPage(),
        ),
    ),
)

OperatorApp(spec).run()
```

The shell mounts the page once and calls its lifecycle methods as the operator moves around. On each render it places `build_navigation()` in the left pane and `landing_view()` in the result pane.

## Add behavior in layers

Start with the smallest layer that answers a user need.

| Need | Add | Continue with |
|---|---|---|
| Show current state | A page returning `TreeView`, `TableView`, or `EmptyView` | [Pages and the workbench](pages.md) |
| Run a bounded check | A `ViewAction` and `ActionSpec` | [Actions and jobs](actions.md) |
| Collect several related answers | A `WizardController` | [Setup wizards](wizards.md) |
| Inspect an oa-configurator stack | `OAConfiguratorAdapter` | [Configuration](configuration.md) |
| Persist an oa-configurator change | `ConfigWorkflowSpec` plus `ConfigMutationService` | [Configuration](configuration.md) |
| Show infrastructure measurements | A telemetry source and normalized snapshots | [Telemetry](telemetry.md) |

Start read-only. A page that shows current state and offers **Refresh status** or **Test connection** proves routing, service wiring, error presentation, and operator wording before persistence is involved.

## Verify the integration

```bash
uv sync --all-extras --dev
uv run pytest -q
uv run ruff check .
uv run ty check src/
```

In a consuming application, also test that every page factory can be constructed with its real dependencies and that operation policy rejects unsafe work before a runner or mutation provider performs it.
