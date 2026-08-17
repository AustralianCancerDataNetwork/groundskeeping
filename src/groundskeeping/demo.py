"""Small demonstration app for the standalone package."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, cast

from pydantic import BaseModel, Field
from textual.widget import Widget

from groundskeeping.app import OperatorApp, OperatorAppSpec
from groundskeeping.configurator import ConfigWizardController, OAConfiguratorAdapter
from groundskeeping.configurator.providers.fake import (
    FakeConfigMutationService,
    fake_database_workflow,
)
from groundskeeping.contracts import (
    ActionContext,
    ActionOutcome,
    ActionRegistry,
    ActionSpec,
    EmptyView,
    ExecutionKind,
    FieldKind,
    FieldSpec,
    KeyValueView,
    NavigationItem,
    OperatorPage,
    PageContext,
    PageRegistration,
    PageRoute,
    SectionItem,
    SectionNavigation,
    SelectionTableRow,
    SelectionTableView,
    SemanticStatus,
    SurfaceView,
    TableRow,
    TableView,
    TreeNode,
    TreeView,
    ViewAction,
)
from groundskeeping.telemetry.providers import FakeTelemetrySource


class _DemoConnection(BaseModel):
    url: str
    password: str
    access: str


class _DemoDatabase(BaseModel):
    kind: str = "generic"
    connection: str
    schema_name: str | None = None


class _DemoProvider(BaseModel):
    provider: str
    base_url: str
    api_key: str | None = None


class _DemoModel(BaseModel):
    provider: str
    model: str


class _DemoVectorStore(BaseModel):
    backend_type: str
    database: str


class _DemoLogging(BaseModel):
    level: str | None = None
    loggers: dict[str, str] = Field(default_factory=dict)


@dataclass
class _DemoStackConfig:
    loaded_path: str
    connections: dict[str, _DemoConnection]
    databases: dict[str, _DemoDatabase]
    providers: dict[str, _DemoProvider]
    models: dict[str, _DemoModel]
    vector_stores: dict[str, _DemoVectorStore]
    tools: dict[str, dict[str, object]]
    logging: _DemoLogging


class _DemoPage(Widget):
    route: PageRoute

    def activate(self, context: PageContext) -> None:
        return None

    def deactivate(self, context: PageContext) -> None:
        return None

    def build_navigation(self, context: PageContext) -> SectionNavigation:
        return SectionNavigation(items=())

    def landing_view(self, context: PageContext) -> SurfaceView:
        return EmptyView(title=self.route.label, message="No demo content.")

    def navigation_selected(self, item: NavigationItem, context: PageContext) -> None:
        context.surface.show_view(self.route.key, self.landing_view(context))

    def action_selected(self, action_key: str, context: PageContext) -> None:
        return None

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

    def __init__(self) -> None:
        super().__init__()
        self._selected_vocab_keys: tuple[str, ...] = ("__all__",)

    def build_navigation(self, context: PageContext) -> SectionNavigation:
        return SectionNavigation(
            items=(
                SectionItem(
                    "overview.shell", "Shell contracts", status=SemanticStatus.OK
                ),
                SectionItem(
                    "overview.selection",
                    "Selection table",
                    status=SemanticStatus.RUNNING,
                    description="All-vs-specific row controls",
                ),
                SectionItem("overview.boundaries", "Consumer boundaries"),
            )
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

    def navigation_selected(self, item: NavigationItem, context: PageContext) -> None:
        if item.key == "overview.selection":
            context.surface.show_view(self.route.key, self._selection_view())
            context.surface.show_detail(
                self.route.key,
                KeyValueView(
                    title="Selection",
                    rows=(
                        ("changed row", "-"),
                        ("selected keys", ", ".join(self._selected_vocab_keys)),
                    ),
                ),
            )
            return
        context.surface.show_view(self.route.key, self.landing_view(context))

    def selection_changed(
        self, row_key: str, selected_keys: tuple[str, ...], context: PageContext
    ) -> None:
        self._selected_vocab_keys = selected_keys or ("__all__",)
        context.surface.show_view(self.route.key, self._selection_view())
        context.surface.show_detail(
            self.route.key,
            KeyValueView(
                title="Selection",
                rows=(
                    ("changed row", row_key),
                    ("selected keys", ", ".join(self._selected_vocab_keys)),
                ),
            ),
        )

    def _selection_view(self) -> SelectionTableView:
        selected = set(self._selected_vocab_keys)
        return SelectionTableView(
            title="Vocabulary selection",
            message="workbench-owned all-vs-specific controls",
            status=SemanticStatus.RUNNING,
            columns=("Vocabulary", "Coverage", "State"),
            selection_mode="all_or_specific",
            all_row_key="__all__",
            rows=(
                SelectionTableRow(
                    "__all__",
                    ("All vocabularies", "default", "ready"),
                    selected="__all__" in selected,
                ),
                SelectionTableRow(
                    "snomed",
                    ("SNOMED CT", "100%", "complete"),
                    disabled=True,
                ),
                SelectionTableRow(
                    "loinc",
                    ("LOINC", "73%", "available"),
                    selected="loinc" in selected,
                ),
                SelectionTableRow(
                    "rxnorm",
                    ("RxNorm", "41%", "available"),
                    selected="rxnorm" in selected,
                ),
            ),
        )


class ConfigPage(_DemoPage):
    route = CONFIG_ROUTE

    def __init__(self) -> None:
        super().__init__()
        self._mutation_service = FakeConfigMutationService()
        self._stack = _DemoStackConfig(
            loaded_path="/demo/stack.toml",
            connections={
                "metadata_connection": _DemoConnection(
                    url="postgresql://metadata.local/demo",
                    password="not-rendered",
                    access="readonly",
                )
            },
            databases={
                "metadata": _DemoDatabase(
                    connection="metadata_connection",
                    schema_name="metadata",
                )
            },
            providers={
                "local": _DemoProvider(
                    provider="ollama",
                    base_url="http://ollama:11434",
                )
            },
            models={"embed": _DemoModel(provider="local", model="nomic-embed")},
            vector_stores={
                "vectors": _DemoVectorStore(
                    backend_type="pgvector",
                    database="metadata",
                )
            },
            tools={"groundskeeping_demo": {"selected_database": "metadata"}},
            logging=_DemoLogging(),
        )
        self._snapshot = self._build_snapshot()

    def _build_snapshot(self):
        return OAConfiguratorAdapter().snapshot(
            cast(Any, self._stack), title="Demo stack configuration"
        )

    def build_navigation(self, context: PageContext) -> SectionNavigation:
        return SectionNavigation(
            items=tuple(
                SectionItem(
                    key=section.target.key,
                    label=section.target.title,
                    status=section.target.status,
                )
                for section in self._snapshot.sections
            )
        )

    def landing_view(self, context: PageContext) -> SurfaceView:
        view = OAConfiguratorAdapter().as_tree_view(self._snapshot)
        return replace(
            view,
            message=(
                f"{view.message}; revision: {self._mutation_service.revision}; "
                f"applied entries: {len(self._mutation_service.durable)}"
            ),
            actions=(
                ViewAction(
                    "config.configure",
                    "Configure database",
                    variant="primary",
                ),
            ),
        )

    def action_selected(self, action_key: str, context: PageContext) -> None:
        if action_key == "config.configure":
            context.open_wizard(
                ConfigWizardController(
                    fake_database_workflow(), self._mutation_service
                )
            )


class TelemetryPage(_DemoPage):
    route = TELEMETRY_ROUTE

    def __init__(self) -> None:
        super().__init__()
        self._source = FakeTelemetrySource()

    def build_navigation(self, context: PageContext) -> SectionNavigation:
        return SectionNavigation(
            items=(
                SectionItem(
                    "fake.accelerator", "Accelerator", status=SemanticStatus.OK
                ),
                SectionItem("fake.workload", "Workload", status=SemanticStatus.RUNNING),
            )
        )

    def landing_view(self, context: PageContext) -> SurfaceView:
        metrics = (
            ("Accelerator", f"{self._source.utilisation:.0f}%", "fake"),
            (
                "Memory",
                f"{self._source.memory_used_mb} / {self._source.memory_total_mb} MiB",
                "fake",
            ),
            ("Throughput", f"{self._source.throughput:.0f} items/s", "fake"),
        )
        return TableView(
            title="Fake telemetry",
            message="capability-aware display data",
            status=SemanticStatus.RUNNING,
            columns=("Metric", "Value", "Source"),
            rows=tuple(
                TableRow(
                    key=f"metric.{index}",
                    cells=row,
                    detail={"metric": row[0], "value": row[1]},
                )
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
                    (
                        "note",
                        "The widget sees normalized metric keys, not a provider class.",
                    ),
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

    def demo_runner(
        params: Mapping[str, object], context: ActionContext
    ) -> ActionOutcome:
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
