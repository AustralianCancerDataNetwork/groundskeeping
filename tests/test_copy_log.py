from __future__ import annotations

import asyncio
from pathlib import Path

from groundskeeping.app import OperatorApp
from groundskeeping.contracts import JobSpec
from groundskeeping.demo import build_demo_spec


def test_copy_log_binding_survives_job_completion_and_refreshes_footer(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        log_path = tmp_path / "known.log"
        content = "failure output\n"
        log_path.write_text(content, encoding="utf-8")
        app = OperatorApp(build_demo_spec())
        copied: list[str] = []

        async with app.run_test() as pilot:
            app.copy_to_clipboard = copied.append  # type: ignore[method-assign]
            refresh_count = 0
            original_refresh = app.refresh_bindings

            def refresh_bindings() -> None:
                nonlocal refresh_count
                refresh_count += 1
                original_refresh()

            app.refresh_bindings = refresh_bindings  # type: ignore[method-assign]

            assert not app.check_action("copy_log", ())
            await pilot.press("y")
            assert copied == []

            app.set_current_log(log_path)
            assert refresh_count == 1
            assert app.check_action("copy_log", ())

            snapshot, _token = app.jobs.start(JobSpec(key="test", label="Test"))
            app.jobs.complete(snapshot.job_id)
            await pilot.press("y")
            await pilot.pause()

            assert copied == [content]
            await pilot.press("q")

    asyncio.run(run())
