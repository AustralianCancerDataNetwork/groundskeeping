from __future__ import annotations

import asyncio

from textual.widget import Widget

from groundskeeping.app import OperatorApp, OperatorAppSpec
from groundskeeping.contracts import (
    LoadingView,
    NavigationItem,
    PageContext,
    PageRegistration,
    PageRoute,
    SectionItem,
    SectionNavigation,
    SurfaceView,
    TableRow,
    TableView,
)

ROUTE = PageRoute("jobs", "Jobs", "Durable jobs")


class _TablePage(Widget):
    route = ROUTE

    def __init__(self, view: TableView) -> None:
        super().__init__()
        self.view = view
        self.highlighted_rows: list[str] = []

    def activate(self, context: PageContext) -> None:
        return None

    def deactivate(self, context: PageContext) -> None:
        return None

    def build_navigation(self, context: PageContext) -> SectionNavigation:
        return SectionNavigation(
            items=(SectionItem("one", "One"), SectionItem("two", "Two"))
        )

    def landing_view(self, context: PageContext) -> SurfaceView:
        return self.view

    def navigation_selected(self, item: NavigationItem, context: PageContext) -> None:
        return None

    def action_selected(self, action_key: str, context: PageContext) -> None:
        return None

    def row_highlighted(self, row_key: str, context: PageContext) -> None:
        self.highlighted_rows.append(row_key)

    def row_selected(self, row_key: str, context: PageContext) -> None:
        return None


def _view(*rows: tuple[str, str]) -> TableView:
    return TableView(
        title="Jobs",
        columns=("Job", "State"),
        rows=tuple(TableRow(key, (key, state)) for key, state in rows),
    )


def test_refresh_rows_preserves_cursor_and_handles_membership_changes() -> None:
    async def run() -> None:
        page = _TablePage(_view(("a", "queued"), ("b", "running"), ("c", "done")))
        app = OperatorApp(
            OperatorAppSpec(
                app_id="workbench-refresh-test",
                title="Workbench refresh test",
                subtitle=None,
                pages=(PageRegistration(ROUTE, lambda context: page),),
            )
        )

        async with app.run_test() as pilot:
            table = app._workbench.rows_table
            table.move_cursor(row=1, column=0, animate=False)
            await pilot.pause()
            baseline_events = len(page.highlighted_rows)
            assert page.highlighted_rows[-1] == "b"

            app._page_context.surface.refresh_view(
                ROUTE.key,
                _view(("a", "queued"), ("b", "finished"), ("d", "queued"))
            )
            await pilot.pause()

            assert len(page.highlighted_rows) == baseline_events
            assert table.ordered_rows[table.cursor_row].key.value == "b"
            assert table.get_row("b")[1] == "finished"
            assert tuple(row.key.value for row in table.ordered_rows) == ("a", "b", "d")

            app._page_context.surface.refresh_view(
                ROUTE.key, _view(("d", "queued"), ("e", "running"))
            )
            await pilot.pause()

            assert len(page.highlighted_rows) == baseline_events
            assert table.ordered_rows[table.cursor_row].key.value == "e"
            assert tuple(row.key.value for row in table.ordered_rows) == ("d", "e")
            await pilot.press("q")

    asyncio.run(run())


def test_refresh_view_patches_loading_surface_in_place() -> None:
    async def run() -> None:
        page = _TablePage(_view(("a", "queued")))
        app = OperatorApp(
            OperatorAppSpec(
                app_id="workbench-loading-refresh-test",
                title="Workbench loading refresh test",
                subtitle=None,
                pages=(PageRegistration(ROUTE, lambda context: page),),
            )
        )

        async with app.run_test() as pilot:
            workbench = app._workbench
            surface = app._page_context.surface

            surface.show_view(
                ROUTE.key,
                LoadingView(title="Migration", message="Starting"),
            )
            await pilot.pause()

            # A long-running job may refresh this surface many times a second; none
            # of those refreshes should re-run the structural entry work (hiding the
            # tree/empty-state/table, restyling the status chip) again, and only a
            # changed message should touch the summary widget.
            entry_calls = 0
            original_show_loading = workbench.show_loading

            def _counting_show_loading(view: LoadingView) -> None:
                nonlocal entry_calls
                entry_calls += 1
                original_show_loading(view)

            workbench.show_loading = _counting_show_loading  # type: ignore[method-assign]

            summary = workbench.query_one("#result-summary")
            for step in range(5):
                surface.refresh_view(
                    ROUTE.key,
                    LoadingView(title="Migration", message=f"Step {step}"),
                )
                await pilot.pause()

            assert entry_calls == 0
            assert "Step 4" in str(summary.content)
            await pilot.press("q")

    asyncio.run(run())


def test_show_navigation_preserves_the_selected_section_key() -> None:
    async def run() -> None:
        page = _TablePage(_view(("a", "queued")))
        app = OperatorApp(
            OperatorAppSpec(
                app_id="workbench-navigation-refresh-test",
                title="Workbench navigation refresh test",
                subtitle=None,
                pages=(PageRegistration(ROUTE, lambda context: page),),
            )
        )

        async with app.run_test() as pilot:
            sections = app._workbench.sections
            sections.highlighted = 1
            assert sections.highlighted_option is not None
            assert sections.highlighted_option.id == "two"

            app._workbench.show_navigation(
                SectionNavigation(
                    items=(
                        SectionItem("one", "One (updated)"),
                        SectionItem("two", "Two (updated)"),
                        SectionItem("three", "Three"),
                    )
                )
            )
            await pilot.pause()

            assert sections.highlighted_option is not None
            assert sections.highlighted_option.id == "two"
            await pilot.press("q")

    asyncio.run(run())
