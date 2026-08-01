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
            await pilot.press("q")

    asyncio.run(run())
