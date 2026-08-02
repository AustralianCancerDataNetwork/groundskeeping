"""Textual application shell composed from consumer-owned pages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar, cast

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    OptionList,
    Tab,
    Tabs,
    Tree,
)

from groundskeeping.contracts.actions import (
    ActionRegistry,
    AllowAllOperationPolicy,
    DefaultResultPresenter,
    OperationPolicy,
    ResultPresenter,
)
from groundskeeping.contracts.jobs import (
    JobManager,
    JobPolicy,
    SingleForegroundJobPolicy,
)
from groundskeeping.contracts.pages import (
    NotifySeverity,
    OperatorPage,
    PageContext,
    PageRegistration,
    PageRegistry,
    PageRoute,
    PageSurfacePort,
)
from groundskeeping.contracts.views import (
    CatalogueItem,
    DetailView,
    EmptyView,
    NavigationItem,
    PageNavigation,
    SectionItem,
    SurfaceView,
    WorkbenchLabels,
)
from groundskeeping.contracts.wizards import (
    WizardController,
    WizardResult,
    WizardResultStatus,
)
from groundskeeping.navigation import SurfaceLease
from groundskeeping.theme import GROUNDSKEEPING_THEME
from groundskeeping.widgets import Workbench
from groundskeeping.widgets.wizard import WizardScreen


@dataclass(frozen=True)
class OperatorAppSpec:
    """Immutable composition root for a Groundskeeping application."""

    app_id: str
    title: str
    subtitle: str | None
    pages: tuple[PageRegistration, ...]
    actions: ActionRegistry = field(default_factory=lambda: ActionRegistry(()))
    operation_policy: OperationPolicy = field(default_factory=AllowAllOperationPolicy)
    job_policy: JobPolicy = field(default_factory=SingleForegroundJobPolicy)
    result_presenter: ResultPresenter = field(default_factory=DefaultResultPresenter)
    workbench_labels: WorkbenchLabels = field(default_factory=WorkbenchLabels)
    default_page: str | None = None
    metadata: Mapping[str, object] | None = None

    def validate(self) -> PageRegistry:
        routes = tuple(registration.route for registration in self.pages)
        registry = PageRegistry(routes)
        if len({id(registration.factory) for registration in self.pages}) != len(
            self.pages
        ):
            raise ValueError("Page registrations must use distinct factories.")
        ActionRegistry(tuple(self.actions), page_keys=registry.keys())
        if self.default_page is not None:
            registry.get(self.default_page)
        return registry


class _WorkbenchSurface(PageSurfacePort):
    def __init__(self, workbench: Workbench) -> None:
        self._workbench = workbench
        self._lease_by_page: dict[str, SurfaceLease] = {}
        self._generation = 0

    def show_navigation(self, page_key: str, navigation: PageNavigation) -> None:
        self._workbench.show_navigation(navigation)
        self._lease(page_key, "navigation")

    def show_view(self, page_key: str, view: SurfaceView) -> None:
        self._workbench.show_surface(view)
        self._lease(page_key, view.title)

    def show_detail(self, page_key: str, detail: DetailView) -> None:
        self._workbench.show_detail(detail)
        self._lease(page_key, "detail")

    def _lease(self, page_key: str, source_key: str) -> SurfaceLease:
        self._generation += 1
        lease = SurfaceLease(
            page_key=page_key, source_key=source_key, generation=self._generation
        )
        self._lease_by_page[page_key] = lease
        return lease


class _AppPageContext(PageContext):
    def __init__(self, app: OperatorApp, surface: PageSurfacePort) -> None:
        self._app = app
        self._surface = surface

    @property
    def surface(self) -> PageSurfacePort:
        return self._surface

    def refresh_bindings(self) -> None:
        self._app.refresh_bindings()

    def request_navigation(self, page_key: str) -> None:
        self._app.show_page(page_key)

    def notify(self, message: str, *, severity: NotifySeverity = "information") -> None:
        self._app.notify(message, severity=severity)

    def open_wizard(self, controller: WizardController) -> None:
        self._app.open_wizard(controller)


class OperatorApp(App[None]):
    """Reusable application frame: header, tabs, mounted pages, and workbench."""

    CSS_PATH: ClassVar[str] = "themes/groundskeeping.tcss"
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, spec: OperatorAppSpec) -> None:
        self.spec = spec
        self.registry = spec.validate()
        super().__init__()
        self.title = spec.title
        self.sub_title = spec.subtitle or ""
        self.jobs = JobManager(spec.job_policy)
        self._active_page = spec.default_page or self.registry[0].key
        self._workbench = Workbench(spec.workbench_labels)
        self._surface = _WorkbenchSurface(self._workbench)
        # Textual's App already owns an internal `_context()` method used during
        # startup. Keep the page-facing context under a distinct name so the shell does
        # not accidentally shadow framework internals.
        self._page_context = _AppPageContext(self, self._surface)
        self._pages: dict[str, OperatorPage] = {
            registration.route.key: registration.factory(self._page_context)
            for registration in spec.pages
        }
        self._navigation_by_key: dict[str, NavigationItem] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="body"):
            yield Tabs(
                *(Tab(route.label, id=route.key) for route in self.registry),
                active=self._active_page,
                id="page-tabs",
            )
            with Vertical(id="workspace"):
                yield Label("", id="workspace-title")
                for route in self.registry:
                    page_widget = self._page_widget(route.key)
                    page_widget.add_class("operator-page")
                    page_widget.styles.height = 0
                    page_widget.styles.max_height = 0
                    yield page_widget
                yield self._workbench
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(GROUNDSKEEPING_THEME)
        self.theme = GROUNDSKEEPING_THEME.name
        if len(self.registry) == 1:
            self.query_one("#page-tabs", Tabs).styles.display = "none"
        self.show_page(self._active_page)

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tabs.id == "page-tabs" and event.tab.id:
            self.show_page(event.tab.id)

    def on_tree_node_selected(self, event: Tree.NodeSelected[CatalogueItem]) -> None:
        if event.control.id != "catalogue":
            return
        data = event.node.data
        if isinstance(data, CatalogueItem):
            self._select_navigation_item(data)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "sections" or event.option.id is None:
            return
        item = self._navigation_by_key.get(event.option.id)
        if isinstance(item, SectionItem):
            self._select_navigation_item(item)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "result-table":
            self._active_widget().row_highlighted(
                str(event.row_key.value), self._page_context
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "result-table":
            self._active_widget().row_selected(
                str(event.row_key.value), self._page_context
            )

    def on_workbench_selection_highlighted(
        self, event: Workbench.SelectionHighlighted
    ) -> None:
        self._active_widget().row_highlighted(event.row_key, self._page_context)

    def on_workbench_selection_changed(self, event: Workbench.SelectionChanged) -> None:
        page = self._active_widget()
        handler = getattr(page, "selection_changed", None)
        if callable(handler):
            handler(event.row_key, event.selected_keys, self._page_context)
            return
        page.row_selected(event.row_key, self._page_context)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action_key = self._workbench.action_key(event.button.id)
        if action_key is not None:
            self._active_widget().action_selected(action_key, self._page_context)

    def open_wizard(self, controller: WizardController) -> None:
        self.push_screen(WizardScreen(controller), callback=self._wizard_closed)

    def _wizard_closed(self, result: WizardResult | None) -> None:
        if result is None:
            return
        severity: NotifySeverity = "information"
        if result.status in {WizardResultStatus.CONFLICTED, WizardResultStatus.FAILED}:
            severity = "error"
        elif result.status is WizardResultStatus.CANCELLED:
            severity = "warning"
        self.notify(result.summary, severity=severity)
        refresh_pages = set(result.refresh_pages)
        if self._active_page in refresh_pages or (result.applied and not refresh_pages):
            self._render_page(self.registry.get(self._active_page))

    def show_page(self, page_key: str) -> None:
        route = self.registry.get(page_key)
        previous = self._pages.get(self._active_page)
        next_page = self._pages[page_key]
        if previous is not None and previous is not next_page:
            previous.deactivate(self._page_context)
            self._page_widget(self._active_page).remove_class("-active")
        self._active_page = page_key
        self._page_widget(page_key).add_class("-active")
        tabs = self.query_one("#page-tabs", Tabs)
        if tabs.active != page_key:
            tabs.active = page_key
        next_page.activate(self._page_context)
        self._render_page(route)

    def _render_page(self, route: PageRoute) -> None:
        heading = Text(route.label, style="bold")
        heading.append("  -  ", style="grey62")
        heading.append(route.purpose, style="grey62")
        self.query_one("#workspace-title", Label).update(heading)
        page = self._active_widget()
        navigation = page.build_navigation(self._page_context)
        self._navigation_by_key = {
            item.key: item for item in self._walk_navigation(navigation)
        }
        self._workbench.show_navigation(navigation)
        try:
            view = page.landing_view(self._page_context)
        except Exception as exc:  # noqa: BLE001
            view = EmptyView(title=route.label, message=f"Unable to render page: {exc}")
        self._workbench.show_surface(view)

    def _active_widget(self) -> OperatorPage:
        return self._pages[self._active_page]

    def _page_widget(self, page_key: str) -> Widget:
        page = self._pages[page_key]
        if not isinstance(page, Widget):
            raise TypeError(f"Page {page_key!r} must be a Textual Widget.")
        return cast(Widget, page)

    def _select_navigation_item(self, item: NavigationItem) -> None:
        self._active_widget().navigation_selected(item, self._page_context)

    def _walk_navigation(
        self, navigation: PageNavigation
    ) -> tuple[NavigationItem, ...]:
        walked: list[NavigationItem] = []
        for item in navigation.items:
            walked.append(item)
            if isinstance(item, CatalogueItem):
                walked.extend(self._walk_catalogue_items(item.children))
        return tuple(walked)

    def _walk_catalogue_items(
        self, items: tuple[CatalogueItem, ...]
    ) -> tuple[CatalogueItem, ...]:
        walked: list[CatalogueItem] = []
        for item in items:
            walked.append(item)
            walked.extend(self._walk_catalogue_items(item.children))
        return tuple(walked)
