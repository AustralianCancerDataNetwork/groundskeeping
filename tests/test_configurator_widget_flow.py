from __future__ import annotations

import asyncio

from textual.widgets import Button, Checkbox, Input

from groundskeeping.app import OperatorApp
from groundskeeping.configurator import ConfigWizardController
from groundskeeping.configurator.providers.fake import (
    FakeConfigMutationService,
    FakeMutationScenario,
    fake_database_workflow,
)
from groundskeeping.demo import build_demo_spec
from groundskeeping.widgets.wizard import WizardScreen


async def _fill_create_flow(
    app: OperatorApp,
    pilot,
    *,
    password: str,
) -> None:
    app.screen.query_one("#wizard-next", Button).press()
    await pilot.pause()
    fields = app.screen.query(Input)
    fields[0].value = "analytics"
    fields[1].value = "postgresql://analytics/demo"
    fields[2].value = password
    app.screen.query_one("#wizard-next", Button).press()
    await pilot.pause()
    checkboxes = app.screen.query(Checkbox)
    assert checkboxes, (
        str(app.screen.query_one("#wizard-progress").render()),
        str(app.screen.query_one("#wizard-errors").render()),
    )
    checkboxes.first().value = True
    app.screen.query_one("#wizard-next", Button).press()
    await pilot.pause()


def test_generic_configuration_flow_renders_and_clears_secret_input() -> None:
    async def run() -> None:
        canary = "widget-secret-canary"
        controller = ConfigWizardController(
            fake_database_workflow(), FakeConfigMutationService()
        )
        app = OperatorApp(build_demo_spec())

        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(WizardScreen(controller))
            await pilot.pause()
            assert app.screen.query_one("#wizard-review", Button).disabled

            await _fill_create_flow(app, pilot, password=canary)

            assert not app.screen.query(Input)
            assert canary not in app.export_screenshot()
            assert not app.screen.query_one("#wizard-apply", Button).disabled
            await pilot.click("#wizard-apply")
            await pilot.pause()
            assert app.screen.id == "_default"
            await pilot.press("q")

    asyncio.run(run())


def test_rejected_apply_remains_open_with_safe_guidance() -> None:
    async def run() -> None:
        controller = ConfigWizardController(
            fake_database_workflow(),
            FakeConfigMutationService(scenario=FakeMutationScenario.REJECTED),
        )
        app = OperatorApp(build_demo_spec())

        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(WizardScreen(controller))
            await pilot.pause()
            await _fill_create_flow(app, pilot, password="rejected-widget-secret")
            await pilot.click("#wizard-apply")
            await pilot.pause()

            assert app.screen.query_one("#wizard-frame") is not None
            assert app.screen.query_one("#wizard-apply", Button).disabled
            assert "rejected" in app.export_screenshot().lower()
            assert "rejected-widget-secret" not in app.export_screenshot()
            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())


def test_invalid_step_clears_the_mounted_secret_control() -> None:
    async def run() -> None:
        canary = "invalid-widget-secret"
        controller = ConfigWizardController(
            fake_database_workflow(), FakeConfigMutationService()
        )
        app = OperatorApp(build_demo_spec())

        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(WizardScreen(controller))
            await pilot.pause()
            app.screen.query_one("#wizard-next", Button).press()
            await pilot.pause()
            fields = app.screen.query(Input)
            fields[0].value = "reserved"
            fields[1].value = "not-a-url"
            fields[2].value = canary
            app.screen.query_one("#wizard-next", Button).press()
            await pilot.pause()

            assert app.screen.query(Input)[2].value == ""
            assert canary not in app.export_screenshot()
            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())
