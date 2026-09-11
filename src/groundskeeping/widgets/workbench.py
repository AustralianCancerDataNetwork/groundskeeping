"""Catalogue, rows, and detail surface shared by consumer-owned pages."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    OptionList,
    SelectionList,
    Static,
    TextArea,
    Tree,
)
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

from groundskeeping.contracts.views import (
    MAX_VIEW_ACTIONS,
    CatalogueItem,
    DetailView,
    EmptyView,
    KeyValueView,
    LoadingView,
    PageNavigation,
    SectionNavigation,
    SelectionMode,
    SelectionTableRow,
    SelectionTableView,
    SemanticStatus,
    SurfaceView,
    TableRow,
    TableView,
    TextView,
    TreeNode,
    TreeView,
    ViewAction,
    WorkbenchLabels,
)
from groundskeeping.theme import node_label, status_style
from groundskeeping.widgets.primitives import EmptyState, LoadingState


class _SelectionTableList(SelectionList[str]):
    """SelectionList with table-surface keyboard affordances."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "select", "Toggle row", show=False),
        Binding("enter", "select", "Toggle row", show=False),
    ]


class _WorkbenchDataTable(DataTable[Any]):
    """DataTable adapter used to make silent cursor restoration possible.

    Textual's cursor watcher always posts ``RowHighlighted`` when a row cursor moves;
    there is no public flag for a data refresh to restore a cursor without notifying the
    page. The Workbench owns this narrow adapter so user cursor movement keeps the
    normal event contract while reconciliation can update membership and coordinates
    silently.
    """

    suppress_row_highlights = False

    def _highlight_row(self, row_index: int) -> None:
        if self.suppress_row_highlights:
            self.refresh_row(row_index)
            return
        super()._highlight_row(row_index)


class Workbench(Widget):
    """Shared page surface with navigation left and rows/detail right."""

    class SelectionChanged(Message):
        """Posted when a workbench-owned selection table changes selected row keys."""

        def __init__(
            self, workbench: Workbench, row_key: str, selected_keys: tuple[str, ...]
        ) -> None:
            super().__init__()
            self.workbench = workbench
            self.row_key = row_key
            self.selected_keys = selected_keys

        @property
        def control(self) -> Workbench:
            return self.workbench

    class SelectionHighlighted(Message):
        """Posted when the highlighted row changes in a selection table."""

        def __init__(self, workbench: Workbench, row_key: str) -> None:
            super().__init__()
            self.workbench = workbench
            self.row_key = row_key

        @property
        def control(self) -> Workbench:
            return self.workbench

    def __init__(self, labels: WorkbenchLabels | None = None) -> None:
        super().__init__(id="workbench")
        self.labels = labels or WorkbenchLabels()
        self._loading_timer: Timer | None = None
        self._loading_frame = 0
        self._loading_view: LoadingView | None = None
        self._action_by_button_id: dict[str, str] = {}
        self._selection_rows: dict[str, SelectionTableRow] = {}
        self._selection_mode: SelectionMode = "multiple"
        self._selection_all_row_key: str | None = None
        self._syncing_selection = False

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
                    yield _WorkbenchDataTable(id="result-table")
                    yield Static("", id="result-selection-header")
                    yield _SelectionTableList(id="result-selection-table")
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
        selection_table = self.selection_table
        selection_table.styles.display = "none"
        selection_table.can_focus = True
        self.query_one("#result-selection-header", Static).styles.display = "none"
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
    def rows_table(self) -> _WorkbenchDataTable:
        return self.query_one("#result-table", _WorkbenchDataTable)

    @property
    def selection_table(self) -> SelectionList[str]:
        return self.query_one("#result-selection-table", SelectionList)

    def show_navigation(self, navigation: PageNavigation) -> None:
        panel = self.query_one("#catalogue-panel")
        panel.border_title = navigation.title
        if isinstance(navigation, SectionNavigation):
            selected_key = None
            highlighted = self.sections.highlighted_option
            if highlighted is not None and highlighted.id is not None:
                selected_key = highlighted.id
            self.catalogue.styles.display = "none"
            self.sections.styles.display = "block"
            self.sections.clear_options()
            self.sections.add_options(
                Option(
                    node_label(item.status, item.label, item.description), id=item.key
                )
                for item in navigation.items
            )
            if navigation.items:
                item_keys = tuple(item.key for item in navigation.items)
                self.sections.highlighted = (
                    item_keys.index(selected_key)
                    if selected_key in item_keys
                    else 0
                )
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
        if isinstance(view, SelectionTableView):
            self.show_selection_rows(view)
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
        table = self.rows_table
        self._prepare_table_surface(view)
        table.clear(columns=True)
        table.add_columns(*view.columns)
        for row in view.rows:
            table.add_row(*row.cells, key=row.key)
        if view.rows and select_first:
            table.move_cursor(row=0, column=0, animate=False)

    def refresh_view(self, view: SurfaceView) -> None:
        """Refresh a surface, preserving cursor state when it is a table.

        Consumer pages should use this for ordinary data refreshes. Table surfaces
        reconcile rows in place, and a loading surface already showing another loading
        view patches its text in place, since a long-running job may refresh this
        surface many times a second. Every other surface still uses the normal
        replacement path because it has no in-place identity to retain.
        """
        if isinstance(view, TableView):
            self.refresh_rows(view)
            return
        if isinstance(view, LoadingView) and self.is_showing_loading:
            self.update_loading(view)
            return
        self.show_surface(view)

    def refresh_rows(self, view: TableView) -> None:
        """Reconcile table rows in place while preserving the highlighted row by key.

        Existing cells are updated without rebuilding the DataTable. Added and removed
        rows are reconciled by their stable keys; if the highlighted row disappears, the
        cursor stays at its previous position where possible. Cursor changes caused by
        this reconciliation are deliberately silent, so a refresh cannot re-enter a
        page's ``row_highlighted`` handler.
        """
        self.show_actions(view.actions)
        table = self.rows_table
        was_visible = table.styles.display != "none"
        old_index = table.cursor_row
        old_column = table.cursor_column
        old_key = self._row_key_at(table, old_index) if was_visible else None
        old_keys = self._table_row_keys(table) if was_visible else ()

        self._prepare_table_surface(view)
        table.suppress_row_highlights = True
        try:
            new_keys = tuple(row.key for row in view.rows)
            if not was_visible or self._table_columns(table) != tuple(view.columns):
                self._replace_table_rows(table, view)
            elif old_keys != new_keys:
                self._reconcile_table_rows(table, view, old_keys)
            else:
                for row in view.rows:
                    self._update_table_row(table, row, len(view.columns))

            if view.rows:
                target_index = (
                    new_keys.index(old_key)
                    if old_key in new_keys
                    else min(old_index, len(view.rows) - 1)
                )
                target_column = min(old_column, len(view.columns) - 1)
                table.move_cursor(
                    row=target_index,
                    column=target_column,
                    animate=False,
                )
        finally:
            table.suppress_row_highlights = False

    def _prepare_table_surface(self, view: TableView) -> None:
        self._hide_loading()
        self._hide_selection_table()
        self.query_one("#result-tree", Tree).styles.display = "none"
        self.query_one("#result-empty", EmptyState).hide_empty()
        self.rows_table.styles.display = "block"
        self.set_status(view.status)
        self.set_summary(view.title, view.message)
        self.query_one("#result-panel").border_subtitle = (
            view.pagination.summary if view.pagination is not None else f"{len(view.rows)} rows"
        )

    def _replace_table_rows(self, table: _WorkbenchDataTable, view: TableView) -> None:
        table.clear(columns=True)
        table.add_columns(*view.columns)
        for row in view.rows:
            table.add_row(*row.cells, key=row.key)

    def _reconcile_table_rows(
        self,
        table: _WorkbenchDataTable,
        view: TableView,
        old_keys: tuple[str, ...],
    ) -> None:
        new_keys = tuple(row.key for row in view.rows)
        expected_incremental_order = tuple(
            key for key in old_keys if key in new_keys
        ) + tuple(key for key in new_keys if key not in old_keys)
        if new_keys != expected_incremental_order:
            self._replace_table_rows(table, view)
            return

        new_by_key = {row.key: row for row in view.rows}
        for key in old_keys:
            if key not in new_by_key:
                table.remove_row(key)
        for row in view.rows:
            if row.key not in old_keys:
                table.add_row(*row.cells, key=row.key)
            else:
                self._update_table_row(table, row, len(view.columns))

    def _update_table_row(
        self, table: _WorkbenchDataTable, row: TableRow, column_count: int
    ) -> None:
        if len(row.cells) > column_count:
            raise ValueError(
                f"Table row {row.key!r} has more cells than the view has columns."
            )
        cells = tuple(row.cells) + (None,) * (column_count - len(row.cells))
        for column, cell in zip(table.ordered_columns, cells):
            table.update_cell(row.key, column.key, cell, update_width=True)

    @staticmethod
    def _table_columns(table: _WorkbenchDataTable) -> tuple[str, ...]:
        return tuple(str(column.label) for column in table.ordered_columns)

    @staticmethod
    def _table_row_keys(table: _WorkbenchDataTable) -> tuple[str, ...]:
        return tuple(str(row.key.value) for row in table.ordered_rows)

    @staticmethod
    def _row_key_at(table: _WorkbenchDataTable, index: int) -> str | None:
        if not 0 <= index < table.row_count:
            return None
        return str(table.ordered_rows[index].key.value)

    def show_selection_rows(
        self, view: SelectionTableView, *, highlight_first: bool = True
    ) -> None:
        self._hide_loading()
        self.rows_table.styles.display = "none"
        self.query_one("#result-tree", Tree).styles.display = "none"
        self.query_one("#result-empty", EmptyState).hide_empty()
        rows = self._normalise_selection_rows(view)
        self._selection_rows = {row.key: row for row in rows}
        self._selection_mode = view.selection_mode
        self._selection_all_row_key = view.all_row_key

        self.query_one("#result-selection-header", Static).update(
            self._selection_header(view.columns, rows)
        )
        self.query_one("#result-selection-header", Static).styles.display = "block"
        selection_table = self.selection_table
        selection_table.styles.display = "block"
        selection_table.clear_options()
        selection_table.add_options(
            Selection(
                self._selection_prompt(row, view.columns, rows),
                row.key,
                initial_state=row.selected,
                disabled=row.disabled,
            )
            for row in rows
        )
        self.set_status(view.status)
        self.set_summary(view.title, view.message)
        self.query_one("#result-panel").border_subtitle = f"{len(rows)} rows"
        if rows and highlight_first:
            selection_table.highlighted = 0

    def show_tree(self, view: TreeView) -> None:
        self._hide_loading()
        self._hide_selection_table()
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
        self._hide_selection_table()
        self.rows_table.styles.display = "none"
        self.query_one("#result-tree", Tree).styles.display = "none"
        self.query_one("#result-empty", EmptyState).show_empty(
            view.message, command=view.command
        )
        self.set_status(view.status)
        self.set_summary(view.title)
        self.query_one("#result-panel").border_subtitle = ""

    def show_loading(self, view: LoadingView) -> None:
        self._hide_selection_table()
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

    @property
    def is_showing_loading(self) -> bool:
        return self._loading_view is not None

    def update_loading(self, view: LoadingView) -> None:
        """Patch an already-shown loading surface without re-hiding other widgets.

        A long-running job may call this many times a second through
        ``refresh_view()``; only the pieces that actually changed are touched so the
        result panel does not flicker.
        """
        previous = self._loading_view
        self._loading_view = view
        self.show_actions(view.actions)
        self._render_loading()
        if (
            previous is None
            or previous.title != view.title
            or previous.message != view.message
        ):
            self.set_summary(view.title, view.message)

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

    def _hide_selection_table(self) -> None:
        self.selection_table.styles.display = "none"
        self.query_one("#result-selection-header", Static).styles.display = "none"
        self._selection_rows = {}
        self._selection_mode = "multiple"
        self._selection_all_row_key = None

    def _normalise_selection_rows(
        self, view: SelectionTableView
    ) -> tuple[SelectionTableRow, ...]:
        rows = view.rows
        if view.selection_mode == "all_or_specific" and view.all_row_key is not None:
            selected = [row for row in rows if row.selected and not row.disabled]
            has_all = any(row.key == view.all_row_key for row in selected)
            has_specific = any(row.key != view.all_row_key for row in selected)
            if has_all and has_specific:
                return tuple(
                    SelectionTableRow(
                        key=row.key,
                        cells=row.cells,
                        selected=row.key != view.all_row_key and row.selected,
                        disabled=row.disabled,
                        selection_group=row.selection_group,
                        detail=row.detail,
                    )
                    for row in rows
                )
            if not selected:
                return tuple(
                    SelectionTableRow(
                        key=row.key,
                        cells=row.cells,
                        selected=row.key == view.all_row_key and not row.disabled,
                        disabled=row.disabled,
                        selection_group=row.selection_group,
                        detail=row.detail,
                    )
                    for row in rows
                )
        return rows

    def _selection_header(
        self, columns: Sequence[str], rows: Sequence[SelectionTableRow]
    ) -> Text:
        if not columns:
            return Text("")
        text = Text("    ", style="grey62")
        text.append(self._padded_cells(columns, columns, rows), style="bold")
        return text

    def _selection_prompt(
        self,
        row: SelectionTableRow,
        columns: Sequence[str],
        rows: Sequence[SelectionTableRow],
    ) -> Text:
        style = "grey50" if row.disabled else ""
        prompt = Text(self._padded_cells(row.cells, columns, rows), style=style)
        # if row.disabled:
        #     prompt.append("  disabled", style="italic grey50")
        return prompt

    def _padded_cells(
        self,
        cells: Sequence[str],
        columns: Sequence[str],
        rows: Sequence[SelectionTableRow],
    ) -> str:
        widths = [
            max(
                len(columns[index]) if index < len(columns) else 0,
                *(len(row.cells[index]) for row in rows if index < len(row.cells)),
            )
            for index in range(len(columns))
        ]
        padded: list[str] = []
        for index, width in enumerate(widths):
            value = cells[index] if index < len(cells) else ""
            padded.append(value.ljust(width))
        if len(cells) > len(widths):
            padded.extend(cells[len(widths) :])
        return "  ".join(padded)

    def on_selection_list_selection_highlighted(
        self, event: SelectionList.SelectionHighlighted[str]
    ) -> None:
        if event.selection_list.id == "result-selection-table":
            self.post_message(
                Workbench.SelectionHighlighted(self, str(event.selection.value))
            )

    def on_selection_list_selection_toggled(
        self, event: SelectionList.SelectionToggled[str]
    ) -> None:
        if event.selection_list.id != "result-selection-table":
            return
        if self._syncing_selection:
            return
        row_key = str(event.selection.value)
        row = self._selection_rows.get(row_key)
        if row is None:
            return
        if row.disabled:
            self._syncing_selection = True
            try:
                if row.selected:
                    event.selection_list.select(row_key)
                else:
                    event.selection_list.deselect(row_key)
            finally:
                self._syncing_selection = False
            return
        self._syncing_selection = True
        try:
            self._enforce_selection_mode(row_key)
        finally:
            self._syncing_selection = False
        self.post_message(
            Workbench.SelectionChanged(
                self, row_key, tuple(event.selection_list.selected)
            )
        )

    def _enforce_selection_mode(self, row_key: str) -> None:
        selection_table = self.selection_table
        selected_keys = set(selection_table.selected)
        if self._selection_mode == "single":
            if row_key in selected_keys:
                for selected_key in tuple(selected_keys):
                    if selected_key != row_key:
                        selection_table.deselect(selected_key)
            return
        if self._selection_mode != "all_or_specific":
            return
        all_row_key = self._selection_all_row_key
        if all_row_key is None:
            return
        if row_key == all_row_key and row_key in selected_keys:
            for selected_key in tuple(selected_keys):
                if selected_key != all_row_key:
                    selection_table.deselect(selected_key)
            return
        if row_key != all_row_key and row_key in selected_keys:
            selection_table.deselect(all_row_key)

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
