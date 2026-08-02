"""Catalogue, rows, and detail surface shared by consumer-owned pages."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Button, DataTable, OptionList, Static, TextArea, Tree
from textual.widgets.option_list import Option

from groundskeeping.contracts.views import (
    MAX_VIEW_ACTIONS,
    CatalogueItem,
    DetailView,
    EmptyView,
    KeyValueView,
    LoadingView,
    PageNavigation,
    SectionNavigation,
    SemanticStatus,
    SurfaceView,
    TableView,
    TextView,
    TreeNode,
    TreeView,
    ViewAction,
    WorkbenchLabels,
)
from groundskeeping.theme import node_label, status_style
from groundskeeping.widgets.primitives import EmptyState, LoadingState


class Workbench(Widget):
    """Shared page surface with navigation left and rows/detail right."""

    def __init__(self, labels: WorkbenchLabels | None = None) -> None:
        super().__init__(id="workbench")
        self.labels = labels or WorkbenchLabels()
        self._loading_timer: Timer | None = None
        self._loading_frame = 0
        self._loading_view: LoadingView | None = None
        self._action_by_button_id: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(id="workbench-main"):
            with Vertical(id="catalogue-panel", classes="section"):
                yield OptionList(id="sections")
                yield Tree("Catalogue", id="catalogue")
            with Vertical(id="workbench-right"):
                with Vertical(id="result-panel", classes="section"):
                    with Horizontal(id="result-header"):
                        yield Static("", id="result-status")
                        yield Static(
                            self.labels.initial_result_summary, id="result-summary"
                        )
                    with Horizontal(id="result-actions"):
                        for index in range(MAX_VIEW_ACTIONS):
                            yield Button("", id=f"view-action-{index}")
                    yield DataTable(id="result-table")
                    yield Tree("Result details", id="result-tree")
                    yield EmptyState("", id="result-empty")
                    yield LoadingState("", id="result-loading")
                with Vertical(id="context-panel", classes="section"):
                    yield TextArea(id="context")
                    yield DataTable(id="context-table")

    def on_mount(self) -> None:
        self.query_one("#catalogue-panel").border_title = self.labels.navigation_panel
        self.query_one("#result-panel").border_title = self.labels.result_panel
        self.query_one("#context-panel").border_title = self.labels.detail_panel
        self.catalogue.show_root = False
        self.catalogue.root.expand()
        self.catalogue.styles.display = "none"
        self.sections.styles.display = "none"
        self.query_one("#result-tree", Tree).show_root = False
        self.query_one("#result-tree", Tree).root.expand()
        self.rows_table.cursor_type = "row"
        self.rows_table.styles.display = "none"
        self.query_one("#result-tree", Tree).styles.display = "none"
        self.query_one("#result-empty", EmptyState).styles.display = "none"
        self.query_one("#result-loading", LoadingState).styles.display = "none"
        self.query_one("#result-actions").styles.display = "none"
        for button in self.query("#result-actions Button").results(Button):
            button.styles.display = "none"
        context = self.query_one("#context", TextArea)
        context.read_only = True
        context.soft_wrap = True
        self.query_one("#context-table", DataTable).styles.display = "none"

    @property
    def catalogue(self) -> Tree[Any]:
        return self.query_one("#catalogue", Tree)

    @property
    def sections(self) -> OptionList:
        return self.query_one("#sections", OptionList)

    @property
    def rows_table(self) -> DataTable[Any]:
        return self.query_one("#result-table", DataTable)

    def show_navigation(self, navigation: PageNavigation) -> None:
        panel = self.query_one("#catalogue-panel")
        panel.border_title = navigation.title
        if isinstance(navigation, SectionNavigation):
            self.catalogue.styles.display = "none"
            self.sections.styles.display = "block"
            self.sections.clear_options()
            self.sections.add_options(
                Option(
                    node_label(item.status, item.label, item.description),
                    id=item.key,
                )
                for item in navigation.items
            )
            if navigation.items:
                self.sections.highlighted = 0
            return

        self.sections.styles.display = "none"
        self.catalogue.styles.display = "block"
        self.populate_catalogue(navigation.items)

    def populate_catalogue(self, items: Sequence[CatalogueItem]) -> None:
        tree = self.catalogue
        tree.clear()
        tree.root.expand()
        for item in items:
            self._add_catalogue_item(tree.root, item)

    def _add_catalogue_item(self, parent: Any, item: CatalogueItem) -> None:
        node = parent.add(node_label(item.status, item.label), data=item, expand=True)
        for child in item.children:
            self._add_catalogue_item(node, child)

    def show_surface(self, view: SurfaceView) -> None:
        self.show_actions(view.actions)
        if isinstance(view, TableView):
            self.show_rows(view)
            return
        if isinstance(view, TreeView):
            self.show_tree(view)
            return
        if isinstance(view, EmptyView):
            self.show_empty(view)
            return
        if isinstance(view, LoadingView):
            self.show_loading(view)
            return
        raise TypeError(f"Unsupported surface view: {type(view).__name__}")

    def show_actions(self, actions: Sequence[ViewAction]) -> None:
        bar = self.query_one("#result-actions", Horizontal)
        visible_actions = tuple(actions[:MAX_VIEW_ACTIONS])
        self._action_by_button_id = {}
        buttons = tuple(self.query("#result-actions Button").results(Button))
        for index, button in enumerate(buttons):
            if index >= len(visible_actions):
                button.styles.display = "none"
                button.label = ""
                button.disabled = True
                continue
            action = visible_actions[index]
            assert button.id is not None
            self._action_by_button_id[button.id] = action.key
            button.label = action.label
            button.variant = action.variant
            button.disabled = action.disabled
            button.styles.display = "block"
        bar.styles.display = "block" if visible_actions else "none"

    def action_key(self, button_id: str | None) -> str | None:
        return self._action_by_button_id.get(button_id or "")

    def set_status(self, status: SemanticStatus | str) -> None:
        chip = self.query_one("#result-status", Static)
        chip.remove_class("-ok", "-warning", "-error", "-idle", "-info", "-running")
        resolved = status_style(status)
        chip.add_class(resolved.css_class)
        chip.update(f"{resolved.glyph} {str(status).lower()}")

    def set_summary(self, title: str, message: str | None = None) -> None:
        summary = Text(title, style="bold")
        if message:
            summary.append("  -  ", style="grey62")
            summary.append(message)
        self.query_one("#result-summary", Static).update(summary)

    def show_rows(self, view: TableView, *, select_first: bool = True) -> None:
        self._hide_loading()
        self.query_one("#result-tree", Tree).styles.display = "none"
        self.query_one("#result-empty", EmptyState).hide_empty()
        table = self.rows_table
        table.clear(columns=True)
        table.add_columns(*view.columns)
        for row in view.rows:
            table.add_row(*row.cells, key=row.key)
        table.styles.display = "block"
        self.set_status(view.status)
        self.set_summary(view.title, view.message)
        self.query_one("#result-panel").border_subtitle = f"{len(view.rows)} rows"
        if view.rows and select_first:
            table.move_cursor(row=0, column=0, animate=False)

    def show_tree(self, view: TreeView) -> None:
        self._hide_loading()
        self.rows_table.styles.display = "none"
        self.query_one("#result-empty", EmptyState).hide_empty()
        tree = self.query_one("#result-tree", Tree)
        tree.styles.display = "block"
        tree.clear()
        tree.root.expand()
        for row in view.rows:
            self._add_tree_node(tree.root, row)
        for note in view.notes:
            tree.root.add_leaf(Text(note, style="grey62"))
        if not view.rows and not view.notes:
            tree.root.add_leaf(
                node_label(view.status, view.message or "No details available.")
            )
        self.set_status(view.status)
        self.set_summary(view.title, view.message)
        self.query_one("#result-panel").border_subtitle = (
            f"{len(view.rows)} items" if view.rows else ""
        )

    def _add_tree_node(self, parent: Any, row: TreeNode) -> None:
        node = parent.add(node_label(row.status, row.label), expand=True)
        for field, value in row.fields.items():
            node.add_leaf(self._field_label(field, value))
        for child in row.children:
            self._add_tree_node(node, child)

    def _field_label(self, field: str, value: object) -> Text:
        label = Text(f"{field} ", style="grey62")
        label.append("-" if value is None else str(value))
        return label

    def show_empty(self, view: EmptyView) -> None:
        self._hide_loading()
        self.rows_table.styles.display = "none"
        self.query_one("#result-tree", Tree).styles.display = "none"
        self.query_one("#result-empty", EmptyState).show_empty(
            view.message, command=view.command
        )
        self.set_status(view.status)
        self.set_summary(view.title)
        self.query_one("#result-panel").border_subtitle = ""

    def show_loading(self, view: LoadingView) -> None:
        self.rows_table.styles.display = "none"
        self.query_one("#result-tree", Tree).styles.display = "none"
        self.query_one("#result-empty", EmptyState).hide_empty()
        self.set_status(SemanticStatus.RUNNING)
        self.set_summary(view.title, view.message)
        self._loading_view = view
        self._loading_frame = 0
        self._render_loading()
        if self._loading_timer is None:
            self._loading_timer = self.set_interval(0.2, self._tick_loading)

    def _tick_loading(self) -> None:
        self._loading_frame += 1
        self._render_loading()

    def _render_loading(self) -> None:
        if self._loading_view is None:
            return
        self.query_one("#result-loading", LoadingState).show_loading(
            self._loading_view.message,
            detail=self._loading_view.detail,
            command=self._loading_view.command,
            frame=self._loading_frame,
        )

    def _hide_loading(self) -> None:
        if self._loading_timer is not None:
            self._loading_timer.stop()
            self._loading_timer = None
        self._loading_view = None
        self.query_one("#result-loading", LoadingState).hide_loading()

    def show_detail(self, detail: DetailView) -> None:
        panel = self.query_one("#context-panel")
        panel.border_subtitle = ""
        if isinstance(detail, TextView):
            self.query_one("#context-table", DataTable).styles.display = "none"
            context = self.query_one("#context", TextArea)
            context.styles.display = "block"
            context.load_text(detail.body)
            panel.border_title = detail.title
            return
        if isinstance(detail, KeyValueView):
            panel.border_title = detail.title
            self.show_context_table(detail.rows)
            return
        if isinstance(detail, TableView):
            self.show_detail_table(detail)
            return
        raise TypeError(f"Unsupported detail view: {type(detail).__name__}")

    def show_detail_table(self, detail: TableView) -> None:
        self.query_one("#context", TextArea).styles.display = "none"
        table = self.query_one("#context-table", DataTable)
        table.styles.display = "block"
        table.clear(columns=True)
        table.add_columns(*detail.columns)
        for row in detail.rows:
            table.add_row(*row.cells, key=row.key)
        self.query_one("#context-panel").border_title = detail.title
        self.query_one("#context-panel").border_subtitle = f"{len(detail.rows)} rows"

    def show_context_table(
        self,
        rows: Iterable[tuple[str, str]],
        *,
        columns: tuple[str, ...] | None = None,
    ) -> None:
        self.query_one("#context", TextArea).styles.display = "none"
        table = self.query_one("#context-table", DataTable)
        table.styles.display = "block"
        table.clear(columns=True)
        table.add_columns(
            *(self.labels.key_value_columns if columns is None else columns)
        )
        for label, value in rows:
            table.add_row(label, value)
