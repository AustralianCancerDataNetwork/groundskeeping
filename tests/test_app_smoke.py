from __future__ import annotations

import asyncio

from groundskeeping.app import OperatorApp
from groundskeeping.demo import build_demo_spec


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
            assert workbench_right.region.height > 0
            assert catalogue_panel.region.x < workbench_right.region.x
            assert catalogue_panel.region.y == workbench_right.region.y
            assert result_panel.region.y < context_panel.region.y
            assert result_panel.region.x == context_panel.region.x == workbench_right.region.x
            await pilot.press("q")

    asyncio.run(run())
