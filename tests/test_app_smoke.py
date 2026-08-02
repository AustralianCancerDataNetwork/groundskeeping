from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from textual.coordinate import Coordinate
from textual.widget import Widget
from textual.widgets import Button, DataTable, OptionList, SelectionList

from groundskeeping.app import OperatorApp, OperatorAppSpec
from groundskeeping.contracts import (
    MAX_VIEW_ACTIONS,
    EmptyView,
    KeyValueView,
    NavigationItem,
    PageContext,
    PageRegistration,
    PageRoute,
    SectionNavigation,
    SelectionTableRow,
    SelectionTableView,
    SurfaceView,
    TableRow,
    TableView,
    TextView,
    ViewAction,
    WizardResult,
    WizardResultStatus,
    WorkbenchLabels,
)
from groundskeeping.demo import build_demo_spec


class _CountingPage(Widget):
    def __init__(self, route: PageRoute, *, actions: tuple[ViewAction, ...] = ()) -> None:
        super().__init__()
        self.route = route
        self.actions = actions
        self.render_count = 0

    def activate(self, context: PageContext) -> None:
        return None

    def deactivate(self, context: PageContext) -> None:
        return None

    def build_navigation(self, context: PageContext) -> SectionNavigation:
        return SectionNavigation(items=())

    def landing_view(self, context: PageContext) -> SurfaceView:
        self.render_count += 1
        return EmptyView(
            title=self.route.label,
            message=f"render {self.render_count}",
            actions=self.actions,
        )

    def navigation_selected(self, item: NavigationItem, context: PageContext) -> None:
        return None

    def action_selected(self, action_key: str, context: PageContext) -> None:
        return None

    def row_highlighted(self, row_key: str, context: PageContext) -> None:
        return None

    def row_selected(self, row_key: str, context: PageContext) -> None:
        return None


class _SelectionPage(_CountingPage):
    def __init__(self, route: PageRoute, view: SelectionTableView) -> None:
        super().__init__(route)
        self.view = view
        self.selection_events: list[tuple[str, tuple[str, ...]]] = []
        self.highlighted_rows: list[str] = []

    def landing_view(self, context: PageContext) -> SurfaceView:
        self.render_count += 1
        return self.view

    def row_highlighted(self, row_key: str, context: PageContext) -> None:
        self.highlighted_rows.append(row_key)

    def selection_changed(
        self, row_key: str, selected_keys: tuple[str, ...], context: PageContext
    ) -> None:
        self.selection_events.append((row_key, selected_keys))


class _NonWidgetPage:
    def __init__(self, route: PageRoute) -> None:
        self.route = route

    def activate(self, context: PageContext) -> None:
        return None

    def deactivate(self, context: PageContext) -> None:
        return None

    def build_navigation(self, context: PageContext) -> SectionNavigation:
        return SectionNavigation(items=())

    def landing_view(self, context: PageContext) -> SurfaceView:
        return EmptyView(title=self.route.label, message="render")

    def navigation_selected(self, item: NavigationItem, context: PageContext) -> None:
        return None

    def action_selected(self, action_key: str, context: PageContext) -> None:
        return None

    def row_highlighted(self, row_key: str, context: PageContext) -> None:
        return None

    def row_selected(self, row_key: str, context: PageContext) -> None:
        return None


def test_demo_app_enters_textual_startup_context() -> None:
    async def run() -> None:
        app = OperatorApp(build_demo_spec())

        async with app.run_test() as pilot:
            assert app.registry.keys() == ("overview", "config", "telemetry")
            assert app.query_one("#workspace-title") is not None
            assert app.query_one(".operator-page.-active").region.height == 0
            assert app.query_one("#workbench").region.height > 0
            catalogue_panel = app.query_one("#catalogue-panel")
            workbench_right = app.query_one("#workbench-right")
            result_panel = app.query_one("#result-panel")
            context_panel = app.query_one("#context-panel")

            assert catalogue_panel.region.height > 0
            assert app.query_one("#sections").styles.display == "block"
            assert app.query_one("#catalogue").styles.display == "none"
            assert workbench_right.region.height > 0
            assert catalogue_panel.region.x < workbench_right.region.x
            assert catalogue_panel.region.y == workbench_right.region.y
            assert result_panel.region.y < context_panel.region.y
            assert (
                result_panel.region.x
                == context_panel.region.x
                == workbench_right.region.x
            )
            await pilot.press("q")

    asyncio.run(run())


def test_operator_app_rejects_non_widget_pages() -> None:
    async def run() -> None:
        route = PageRoute("setup", "Setup", "Setup page")
        app = OperatorApp(
            OperatorAppSpec(
                app_id="non-widget-test",
                title="Non Widget Test",
                subtitle=None,
                pages=(PageRegistration(route, lambda context: _NonWidgetPage(route)),),
            )
        )

        with pytest.raises(TypeError, match="must be a Textual Widget"):
            async with app.run_test():
                pass

    asyncio.run(run())


def test_single_page_hides_tabs_without_removing_page_registry() -> None:
    async def run() -> None:
        demo = build_demo_spec()
        spec = replace(
            demo,
            pages=(demo.pages[0],),
            default_page=demo.pages[0].route.key,
        )
        app = OperatorApp(spec)

        async with app.run_test() as pilot:
            assert app.registry.keys() == ("overview",)
            assert app.query_one("#page-tabs").styles.display == "none"
            await pilot.press("q")

    asyncio.run(run())


def test_app_spec_can_override_workbench_chrome_labels() -> None:
    async def run() -> None:
        demo = build_demo_spec()
        spec = replace(
            demo,
            workbench_labels=WorkbenchLabels(
                navigation_panel="Setup areas",
                result_panel="Checks",
                detail_panel="Inspector",
                initial_result_summary="Choose a setup area.",
                key_value_columns=("Setting", "Value"),
            ),
        )
        app = OperatorApp(spec)

        async with app.run_test() as pilot:
            assert app.query_one("#result-panel").border_title == "Checks"
            assert app.query_one("#context-panel").border_title == "Inspector"

            app._workbench.show_navigation(SectionNavigation(items=()))
            assert app.query_one("#catalogue-panel").border_title == "Sections"

            app._workbench.show_context_table((("provider", "ollama"),))
            await pilot.pause()

            table = app.query_one("#context-table", DataTable)
            assert tuple(str(column.label) for column in table.ordered_columns) == (
                "Setting",
                "Value",
            )

            app._workbench.show_context_table((), columns=())
            await pilot.pause()

            assert len(table.ordered_columns) == 0
            await pilot.press("q")

    asyncio.run(run())


def test_wizard_result_refreshes_active_page_when_requested() -> None:
    async def run() -> None:
        active_route = PageRoute("setup", "Setup", "Setup page")
        other_route = PageRoute("other", "Other", "Other page")
        active_page = _CountingPage(active_route)
        other_page = _CountingPage(other_route)
        app = OperatorApp(
            OperatorAppSpec(
                app_id="refresh-test",
                title="Refresh Test",
                subtitle=None,
                default_page=active_route.key,
                pages=(
                    PageRegistration(active_route, lambda context: active_page),
                    PageRegistration(other_route, lambda context: other_page),
                ),
            )
        )

        async with app.run_test() as pilot:
            baseline = active_page.render_count

            app._wizard_closed(
                WizardResult(
                    status=WizardResultStatus.CONFLICTED,
                    summary="Configuration changed.",
                    refresh_pages=frozenset({active_route.key}),
                )
            )
            await pilot.pause()

            assert active_page.render_count == baseline + 1

            app._wizard_closed(
                WizardResult(
                    status=WizardResultStatus.FAILED,
                    summary="Other page changed.",
                    refresh_pages=frozenset({other_route.key}),
                )
            )
            await pilot.pause()

            assert active_page.render_count == baseline + 1

            app._wizard_closed(
                WizardResult(
                    status=WizardResultStatus.APPLIED,
                    summary="Legacy applied result.",
                )
            )
            await pilot.pause()

            assert active_page.render_count == baseline + 2
            await pilot.press("q")

    asyncio.run(run())


def test_workbench_clamps_extra_view_actions_without_crashing() -> None:
    async def run() -> None:
        route = PageRoute("setup", "Setup", "Setup page")
        page = _CountingPage(
            route,
            actions=tuple(
                ViewAction(f"setup.action.{index}", f"Action {index}")
                for index in range(MAX_VIEW_ACTIONS + 2)
            ),
        )
        app = OperatorApp(
            OperatorAppSpec(
                app_id="action-clamp-test",
                title="Action Clamp Test",
                subtitle=None,
                pages=(PageRegistration(route, lambda context: page),),
            )
        )

        async with app.run_test() as pilot:
            visible_buttons = tuple(
                button
                for button in app.query("#result-actions Button").results(Button)
                if button.styles.display == "block"
            )

            assert len(visible_buttons) == MAX_VIEW_ACTIONS
            assert app._workbench.action_key("view-action-0") == "setup.action.0"
            assert app._workbench.action_key(
                f"view-action-{MAX_VIEW_ACTIONS - 1}"
            ) == f"setup.action.{MAX_VIEW_ACTIONS - 1}"
            assert app._workbench.action_key(f"view-action-{MAX_VIEW_ACTIONS}") is None
            await pilot.press("q")

    asyncio.run(run())


def test_workbench_renders_table_view_in_detail_pane() -> None:
    async def run() -> None:
        app = OperatorApp(build_demo_spec())

        async with app.run_test(size=(120, 40)) as pilot:
            detail = TableView(
                title="Model inventory",
                columns=("Model", "Context", "Status"),
                rows=tuple(
                    TableRow(
                        key=f"model-{index}",
                        cells=(f"model-{index}", f"{index * 1000}", "available"),
                    )
                    for index in range(12)
                ),
            )

            app._workbench.show_detail(detail)
            await pilot.pause()

            context = app.query_one("#context")
            table = app.query_one("#context-table", DataTable)

            assert context.styles.display == "none"
            assert table.styles.display == "block"
            assert table.row_count == 12
            assert len(table.ordered_columns) == 3
            assert app.query_one("#context-panel").border_title == "Model inventory"
            assert app.query_one("#context-panel").border_subtitle == "12 rows"

            app._workbench.show_detail(TextView("Model notes", "Use qwen locally."))
            await pilot.pause()

            assert context.styles.display == "block"
            assert table.styles.display == "none"
            assert app.query_one("#context-panel").border_title == "Model notes"
            assert app.query_one("#context-panel").border_subtitle == ""

            app._workbench.show_detail(
                KeyValueView(
                    rows=(("Provider", "Ollama"),),
                    title="Model facts",
                )
            )
            await pilot.pause()

            assert context.styles.display == "none"
            assert table.styles.display == "block"
            assert app.query_one("#context-panel").border_title == "Model facts"
            assert app.query_one("#context-panel").border_subtitle == ""
            await pilot.press("q")

    asyncio.run(run())


def test_workbench_selection_table_mouse_first_click_toggles_row() -> None:
    async def run() -> None:
        route = PageRoute("setup", "Setup", "Setup page")
        page = _SelectionPage(
            route,
            SelectionTableView(
                title="Vocabulary coverage",
                columns=("Vocabulary", "Coverage"),
                rows=(
                    SelectionTableRow("snomed", ("SNOMED", "complete")),
                    SelectionTableRow("loinc", ("LOINC", "partial")),
                ),
            ),
        )
        app = OperatorApp(
            OperatorAppSpec(
                app_id="selection-click-test",
                title="Selection Click Test",
                subtitle=None,
                pages=(PageRegistration(route, lambda context: page),),
            )
        )

        async with app.run_test(size=(120, 40)) as pilot:
            selection = app.query_one("#result-selection-table", SelectionList)
            assert selection.styles.display == "block"

            await pilot.click("#result-selection-table", offset=(2, 1))
            await pilot.pause()

            assert page.selection_events[-1] == ("snomed", ("snomed",))
            await pilot.press("q")

    asyncio.run(run())


def test_workbench_selection_table_keyboard_enter_toggles_highlighted_row() -> None:
    async def run() -> None:
        route = PageRoute("setup", "Setup", "Setup page")
        page = _SelectionPage(
            route,
            SelectionTableView(
                title="Vocabulary coverage",
                columns=("Vocabulary",),
                rows=(
                    SelectionTableRow("snomed", ("SNOMED",)),
                    SelectionTableRow("loinc", ("LOINC",)),
                ),
            ),
        )
        app = OperatorApp(
            OperatorAppSpec(
                app_id="selection-enter-test",
                title="Selection Enter Test",
                subtitle=None,
                pages=(PageRegistration(route, lambda context: page),),
            )
        )

        async with app.run_test(size=(120, 40)) as pilot:
            selection = app.query_one("#result-selection-table", SelectionList)
            selection.focus()
            selection.highlighted = 1

            await pilot.press("enter")
            await pilot.pause()

            assert page.selection_events[-1] == ("loinc", ("loinc",))
            await pilot.press("q")

    asyncio.run(run())


def test_workbench_selection_table_all_row_clears_specific_rows() -> None:
    async def run() -> None:
        route = PageRoute("setup", "Setup", "Setup page")
        page = _SelectionPage(
            route,
            SelectionTableView(
                title="Vocabulary coverage",
                columns=("Vocabulary",),
                rows=(
                    SelectionTableRow("__all__", ("All",)),
                    SelectionTableRow("snomed", ("SNOMED",), selected=True),
                    SelectionTableRow("loinc", ("LOINC",), selected=True),
                ),
                selection_mode="all_or_specific",
                all_row_key="__all__",
            ),
        )
        app = OperatorApp(
            OperatorAppSpec(
                app_id="selection-all-test",
                title="Selection All Test",
                subtitle=None,
                pages=(PageRegistration(route, lambda context: page),),
            )
        )

        async with app.run_test(size=(120, 40)) as pilot:
            selection = app.query_one("#result-selection-table", SelectionList)
            selection.focus()
            selection.highlighted = 0

            await pilot.press("enter")
            await pilot.pause()

            assert page.selection_events[-1] == ("__all__", ("__all__",))
            await pilot.press("q")

    asyncio.run(run())


def test_workbench_selection_table_specific_row_clears_all_row() -> None:
    async def run() -> None:
        route = PageRoute("setup", "Setup", "Setup page")
        page = _SelectionPage(
            route,
            SelectionTableView(
                title="Vocabulary coverage",
                columns=("Vocabulary",),
                rows=(
                    SelectionTableRow("__all__", ("All",), selected=True),
                    SelectionTableRow("snomed", ("SNOMED",)),
                ),
                selection_mode="all_or_specific",
                all_row_key="__all__",
            ),
        )
        app = OperatorApp(
            OperatorAppSpec(
                app_id="selection-specific-test",
                title="Selection Specific Test",
                subtitle=None,
                pages=(PageRegistration(route, lambda context: page),),
            )
        )

        async with app.run_test(size=(120, 40)) as pilot:
            selection = app.query_one("#result-selection-table", SelectionList)
            selection.focus()
            selection.highlighted = 1

            await pilot.press("enter")
            await pilot.pause()

            assert page.selection_events[-1] == ("snomed", ("snomed",))
            await pilot.press("q")

    asyncio.run(run())


def test_workbench_selection_table_disabled_rows_do_not_toggle() -> None:
    async def run() -> None:
        route = PageRoute("setup", "Setup", "Setup page")
        page = _SelectionPage(
            route,
            SelectionTableView(
                title="Vocabulary coverage",
                columns=("Vocabulary",),
                rows=(
                    SelectionTableRow("__all__", ("All",), selected=True),
                    SelectionTableRow("snomed", ("SNOMED",), disabled=True),
                ),
                selection_mode="all_or_specific",
                all_row_key="__all__",
            ),
        )
        app = OperatorApp(
            OperatorAppSpec(
                app_id="selection-disabled-test",
                title="Selection Disabled Test",
                subtitle=None,
                pages=(PageRegistration(route, lambda context: page),),
            )
        )

        async with app.run_test(size=(120, 40)) as pilot:
            selection = app.query_one("#result-selection-table", SelectionList)
            selection.focus()
            selection.highlighted = 1

            await pilot.press("enter")
            await pilot.pause()

            assert page.selection_events == []
            assert selection.selected == ["__all__"]
            await pilot.press("q")

    asyncio.run(run())


def test_demo_app_exposes_selection_table_view() -> None:
    async def run() -> None:
        app = OperatorApp(build_demo_spec())

        async with app.run_test(size=(120, 40)) as pilot:
            sections = app.query_one("#sections", OptionList)
            sections.focus()
            sections.highlighted = 1
            await pilot.press("enter")
            await pilot.pause()

            selection = app.query_one("#result-selection-table", SelectionList)
            assert selection.styles.display == "block"
            assert selection.selected == ["__all__"]

            selection.focus()
            selection.highlighted = 2
            await pilot.press("enter")
            await pilot.pause()

            assert selection.selected == ["loinc"]
            detail = app.query_one("#context-table", DataTable)
            assert "loinc" in str(detail.get_cell_at(Coordinate(1, 1)))
            await pilot.press("q")

    asyncio.run(run())
