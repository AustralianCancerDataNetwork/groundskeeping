"""Small demonstration app for the standalone package."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from textual.widget import Widget

from groundskeeping.app import OperatorApp, OperatorAppSpec
from groundskeeping.configurator import OAConfiguratorAdapter
from groundskeeping.contracts import (
    ActionContext,
    ActionOutcome,
    ActionRegistry,
    ActionSpec,
    CatalogueItem,
    EmptyView,
    ExecutionKind,
    FieldKind,
    FieldSpec,
    KeyValueView,
    OperatorPage,
    PageContext,
    PageRegistration,
    PageRoute,
    SemanticStatus,
    SurfaceView,
    TableRow,
    TableView,
    TreeNode,
    TreeView,
)
from groundskeeping.telemetry.providers import FakeTelemetrySource


@dataclass
class _DemoDatabase:
    url: str
    password: str
    role: str


@dataclass
class _DemoStackConfig:
    path: str
    active_profile: str
    databases: dict[str, _DemoDatabase]
    resources: dict[str, dict[str, str]]
    profiles: dict[str, dict[str, str]]
    aliases: dict[str, str]


class _DemoPage(Widget):
    route: PageRoute

    def activate(self, context: PageContext) -> None:
        return None

    def deactivate(self, context: PageContext) -> None:
        return None

    def build_catalogue(self, context: PageContext) -> tuple[CatalogueItem, ...]:
        return ()

    def landing_view(self, context: PageContext) -> SurfaceView:
        return EmptyView(title=self.route.label, message="No demo content.")

    def catalogue_selected(self, item: CatalogueItem, context: PageContext) -> None:
        context.surface.show_view(self.route.key, self.landing_view(context))

    def row_highlighted(self, row_key: str, context: PageContext) -> None:
        return None

    def row_selected(self, row_key: str, context: PageContext) -> None:
        return None


OVERVIEW_ROUTE = PageRoute(
    key="overview",
    label="Overview",
    purpose="Composition smoke test for the reusable shell.",
)
CONFIG_ROUTE = PageRoute(
    key="config",
    label="Configuration",
    purpose="Read-only stack configuration browser.",
)
TELEMETRY_ROUTE = PageRoute(
    key="telemetry",
    label="Telemetry",
    purpose="Normalized metrics rendered without provider-specific branches.",
)


class OverviewPage(_DemoPage):
    route = OVERVIEW_ROUTE

    def build_catalogue(self, context: PageContext) -> tuple[CatalogueItem, ...]:
        return (
            CatalogueItem("overview.shell", "Shell contracts", "topic", status=SemanticStatus.OK),
            CatalogueItem("overview.boundaries", "Consumer boundaries", "topic", status=SemanticStatus.INFO),
        )

    def landing_view(self, context: PageContext) -> SurfaceView:
        return TreeView(
            title="Groundskeeping demo",
            message="standalone shell, no consumer imports",
            rows=(
                TreeNode(
                    "Phase one",
                    status=SemanticStatus.OK,
                    fields={
                        "pages": "explicitly registered",
                        "surface": "shared workbench",
                        "configuration": "read-only inspection",
                        "telemetry": "normalized snapshots",
                    },
                ),
            ),
        )


class ConfigPage(_DemoPage):
    route = CONFIG_ROUTE

    def __init__(self) -> None:
        super().__init__()
        stack = _DemoStackConfig(
            path="/demo/stack.toml",
            active_profile="tre",
            databases={
                "metadata": _DemoDatabase(
                    url="postgresql://metadata.local/demo",
                    password="not-rendered",
                    role="readonly",
                )
            },
            resources={"ollama": {"url": "http://ollama:11434", "kind": "model-server"}},
            profiles={"tre": {"database": "metadata"}},
            aliases={"default-model": "snowflake-arctic-embed2"},
        )
        self._snapshot = OAConfiguratorAdapter().snapshot(stack, title="Demo stack configuration")

    def build_catalogue(self, context: PageContext) -> tuple[CatalogueItem, ...]:
        return tuple(
            CatalogueItem(
                key=section.target.key,
                label=section.target.title,
                kind=section.target.kind,
                status=section.target.status,
            )
            for section in self._snapshot.sections
        )

    def landing_view(self, context: PageContext) -> SurfaceView:
        return OAConfiguratorAdapter().as_tree_view(self._snapshot)


class TelemetryPage(_DemoPage):
    route = TELEMETRY_ROUTE

    def __init__(self) -> None:
        super().__init__()
        self._source = FakeTelemetrySource()

    def build_catalogue(self, context: PageContext) -> tuple[CatalogueItem, ...]:
        return (
            CatalogueItem("fake.accelerator", "Accelerator", "capability", status=SemanticStatus.OK),
            CatalogueItem("fake.workload", "Workload", "capability", status=SemanticStatus.RUNNING),
        )

    def landing_view(self, context: PageContext) -> SurfaceView:
        metrics = (
            ("Accelerator", f"{self._source.utilisation:.0f}%", "fake"),
            ("Memory", f"{self._source.memory_used_mb} / {self._source.memory_total_mb} MiB", "fake"),
            ("Throughput", f"{self._source.throughput:.0f} items/s", "fake"),
        )
        return TableView(
            title="Fake telemetry",
            message="capability-aware display data",
            status=SemanticStatus.RUNNING,
            columns=("Metric", "Value", "Source"),
            rows=tuple(
                TableRow(key=f"metric.{index}", cells=row, detail={"metric": row[0], "value": row[1]})
                for index, row in enumerate(metrics)
            ),
        )

    def row_highlighted(self, row_key: str, context: PageContext) -> None:
        context.surface.show_detail(
            self.route.key,
            KeyValueView(
                rows=(
                    ("row", row_key),
                    ("source", self._source.source_id),
                    ("note", "The widget sees normalized metric keys, not a provider class."),
                )
            ),
        )


def build_demo_spec() -> OperatorAppSpec:
    def overview_factory(context: PageContext) -> OperatorPage:
        return OverviewPage()

    def config_factory(context: PageContext) -> OperatorPage:
        return ConfigPage()

    def telemetry_factory(context: PageContext) -> OperatorPage:
        return TelemetryPage()

    def demo_runner(params: Mapping[str, object], context: ActionContext) -> ActionOutcome:
        context.emit("demo", completed=1, total=1, message="demo action executed")
        return ActionOutcome(
            status=SemanticStatus.OK,
            summary=f"Echoed {params['message']}",
            view=EmptyView(title="Demo action", message=str(params["message"])),
        )

    return OperatorAppSpec(
        app_id="groundskeeping-demo",
        title="Groundskeeping Demo",
        subtitle="standalone reusable shell",
        default_page=OVERVIEW_ROUTE.key,
        actions=ActionRegistry(
            (
                ActionSpec(
                    key="overview.echo",
                    page_key=OVERVIEW_ROUTE.key,
                    label="Echo message",
                    summary="Small executable action used by the demo contract tests.",
                    runner=demo_runner,
                    fields=(
                        FieldSpec(
                            key="message",
                            label="Message",
                            kind=FieldKind.TEXT,
                            default="groundskeeping",
                        ),
                    ),
                    execution=ExecutionKind.QUICK,
                ),
            )
        ),
        pages=(
            PageRegistration(route=OVERVIEW_ROUTE, factory=overview_factory),
            PageRegistration(route=CONFIG_ROUTE, factory=config_factory),
            PageRegistration(route=TELEMETRY_ROUTE, factory=telemetry_factory),
        ),
    )


def main() -> None:
    OperatorApp(build_demo_spec()).run()
