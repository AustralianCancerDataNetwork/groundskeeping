from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest
from textual.widgets import Button, Select
from textual.widgets._select import SelectOverlay

from groundskeeping.app import OperatorApp
from groundskeeping.contracts import (
    Choice,
    ChoiceOption,
    ChoiceStep,
    FieldKind,
    FieldSpec,
    FormStep,
    ReviewChange,
    ReviewStep,
    WizardDefinitionError,
    WizardResult,
    WizardResultStatus,
    WizardReview,
    WizardSnapshot,
    WizardSpec,
    WizardTransition,
    validate_wizard_steps,
)
from groundskeeping.demo import build_demo_spec
from groundskeeping.widgets.wizard import WizardScreen


class _DynamicChoiceWizard:
    spec = WizardSpec(
        key="model-picker",
        title="Pick a model",
        purpose="Choose one model from inventory.",
        apply_label="Apply",
    )

    def __init__(self) -> None:
        self.submitted: dict[str, object] = {}
        self.step = FormStep(
            key="model",
            title="Model inventory",
            fields=(
                FieldSpec(
                    key="model",
                    label="Model",
                    kind=FieldKind.CHOICE,
                    choices=tuple(
                        ChoiceOption(
                            value=f"model-{index:02d}",
                            label=f"Model {index:02d}",
                            description=f"{index * 1000} context",
                        )
                        for index in range(12)
                    ),
                ),
            ),
        )
        self.review_step = ReviewStep("review", "Review", WizardReview())

    def start(self) -> WizardSnapshot:
        return WizardSnapshot(
            spec=self.spec,
            step=self.step,
            step_index=0,
            step_count=2,
            values={"model": "model-04"},
        )

    def submit(self, values: Mapping[str, object]) -> WizardTransition:
        self.submitted = dict(values)
        return WizardTransition(
            WizardSnapshot(
                spec=self.spec,
                step=self.review_step,
                step_index=1,
                step_count=2,
                can_back=True,
                can_next=False,
                can_apply=True,
            )
        )

    def back(self) -> WizardSnapshot:
        return self.start()

    def review(self) -> WizardTransition:
        return self.submit(self.submitted)

    def apply(self) -> WizardResult:
        return WizardResult(WizardResultStatus.APPLIED, "Applied.")

    def cancel(self) -> WizardResult:
        return WizardResult(WizardResultStatus.CANCELLED, "Cancelled.")


class _NoChoiceWizard(_DynamicChoiceWizard):
    def __init__(self) -> None:
        super().__init__()
        self.step = FormStep(
            key="model",
            title="Model inventory",
            fields=(
                FieldSpec(
                    key="model",
                    label="Model",
                    kind=FieldKind.CHOICE,
                    choices=(),
                ),
            ),
        )

    def start(self) -> WizardSnapshot:
        return WizardSnapshot(
            spec=self.spec,
            step=self.step,
            step_index=0,
            step_count=2,
            values={"model": None},
        )


def test_wizard_definitions_require_unique_keys() -> None:
    field = FieldSpec("database", "Database")

    with pytest.raises(WizardDefinitionError, match="step keys"):
        validate_wizard_steps(
            (
                FormStep("database", "Database", fields=(field,)),
                FormStep("database", "Again", fields=(field,)),
            )
        )

    with pytest.raises(WizardDefinitionError, match="field keys"):
        validate_wizard_steps(
            (
                FormStep(
                    "database",
                    "Database",
                    fields=(field, FieldSpec("database", "Duplicate")),
                ),
            )
        )

    with pytest.raises(WizardDefinitionError, match="choice keys"):
        validate_wizard_steps(
            (
                ChoiceStep(
                    "strategy",
                    "Strategy",
                    choices=(
                        Choice("reuse", "Reuse", "Use an existing target."),
                        Choice("reuse", "Reuse again", "Duplicate key."),
                    ),
                ),
            )
        )


def test_review_changes_redact_sensitive_repr() -> None:
    change = ReviewChange(
        "password",
        "old-secret",
        "new-secret",
        sensitive=True,
    )

    assert "old-secret" not in repr(change)
    assert "new-secret" not in repr(change)
    assert "<redacted>" in repr(change)
    assert change.before == "<redacted>"
    assert change.after == "<redacted>"


def test_wizard_snapshot_validates_progress_bounds() -> None:
    spec = WizardSpec("demo", "Demo", "Demo")
    step = ReviewStep("review", "Review", WizardReview())

    with pytest.raises(ValueError, match="at least 1"):
        WizardSnapshot(spec, step, step_index=0, step_count=0)

    with pytest.raises(ValueError, match="inside"):
        WizardSnapshot(spec, step, step_index=3, step_count=2)


def test_wizard_choice_field_renders_stable_select_control() -> None:
    async def run() -> None:
        controller = _DynamicChoiceWizard()
        app = OperatorApp(build_demo_spec())

        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(WizardScreen(controller))
            await pilot.pause()

            picker = app.screen.query_one("#wizard-field-0", Select)
            assert picker.value == "model-04"
            assert not picker.disabled

            picker.focus()
            await pilot.press("enter")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()

            await pilot.click("#wizard-next")
            await pilot.pause()

            assert controller.submitted["model"] == "model-05"
            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())


def test_wizard_choice_field_handles_empty_required_choices() -> None:
    async def run() -> None:
        app = OperatorApp(build_demo_spec())

        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(WizardScreen(_NoChoiceWizard()))
            await pilot.pause()

            picker = app.screen.query_one("#wizard-field-0", Select)
            assert picker.disabled
            assert picker.value == "__groundskeeping_no_choice__"
            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())


def test_wizard_choice_field_selects_via_mouse() -> None:
    async def run() -> None:
        controller = _DynamicChoiceWizard()
        app = OperatorApp(build_demo_spec())

        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(WizardScreen(controller))
            await pilot.pause()

            await pilot.click("#wizard-field-0")
            await pilot.pause()
            await pilot.click(SelectOverlay, offset=(2, 2))
            await pilot.pause()

            await pilot.click("#wizard-next")
            await pilot.pause()

            assert controller.submitted["model"] == "model-01"
            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())


def test_demo_app_opens_and_cancels_wizard_from_view_action() -> None:
    async def run() -> None:
        app = OperatorApp(build_demo_spec())

        async with app.run_test(size=(120, 40)) as pilot:
            app.show_page("config")
            await pilot.pause()

            button = app.query_one("#view-action-0", Button)
            assert str(button.label) == "Configure database"

            await pilot.click("#view-action-0")
            await pilot.pause()

            assert app.screen.query_one("#wizard-frame") is not None
            assert app.screen.query_one("#wizard-review", Button).disabled
            assert app.screen.query_one("#wizard-apply", Button).disabled

            await pilot.click("#wizard-cancel")
            await pilot.pause()

            assert app.screen.id == "_default"
            await pilot.press("q")

    asyncio.run(run())


def test_demo_wizard_choice_step_selects_setup_path_via_keyboard() -> None:
    async def run() -> None:
        app = OperatorApp(build_demo_spec())

        async with app.run_test(size=(120, 40)) as pilot:
            app.show_page("config")
            await pilot.pause()

            await pilot.click("#view-action-0")
            await pilot.pause()

            picker = app.screen.query_one("#wizard-choice", Select)
            picker.focus()
            await pilot.press("enter")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()

            await pilot.click("#wizard-next")
            await pilot.pause()

            assert app.screen.query_one("#wizard-field-0", Select) is not None
            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())


def test_demo_wizard_choice_step_selects_setup_path_via_mouse() -> None:
    async def run() -> None:
        app = OperatorApp(build_demo_spec())

        async with app.run_test(size=(120, 40)) as pilot:
            app.show_page("config")
            await pilot.pause()

            await pilot.click("#view-action-0")
            await pilot.pause()

            await pilot.click("#wizard-choice")
            await pilot.pause()
            overlay = app.screen.query_one(SelectOverlay)
            assert overlay.styles.display == "block"
            assert overlay.content_region.height > 0
            await pilot.click(SelectOverlay, offset=(2, 2))
            await pilot.pause()

            await pilot.click("#wizard-next")
            await pilot.pause()

            assert app.screen.query_one("#wizard-field-0", Select) is not None
            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())
