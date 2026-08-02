from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest
from textual.widgets import Button, OptionList

from groundskeeping.app import OperatorApp
from groundskeeping.configurator import (
    ConfigApplyIntent,
    ConfigDraft,
    ConfigTarget,
    OAConfiguratorAdapter,
)
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
from groundskeeping.demo import ConfigPage, _DemoConfigWizardController, build_demo_spec
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


def test_wizard_snapshot_validates_progress_bounds() -> None:
    spec = WizardSpec("demo", "Demo", "Demo")
    step = ReviewStep("review", "Review", WizardReview())

    with pytest.raises(ValueError, match="at least 1"):
        WizardSnapshot(spec, step, step_index=0, step_count=0)

    with pytest.raises(ValueError, match="inside"):
        WizardSnapshot(spec, step, step_index=3, step_count=2)


def test_demo_config_wizard_branches_validates_and_applies() -> None:
    page = ConfigPage()
    controller = _DemoConfigWizardController(page)

    start = controller.start()
    assert isinstance(start.step, ChoiceStep)
    assert start.values["strategy"] == "reuse"

    create = controller.submit({"strategy": "create"}).snapshot
    assert isinstance(create.step, FormStep)
    assert create.step.key == "create-database"

    invalid = controller.submit(
        {
            "database_key": "bad key!",
            "url": "",
            "role": "writer",
            "ssl": True,
            "password": "",
        }
    )
    assert {issue.field_key for issue in invalid.issues} == {
        "database_key",
        "url",
        "password",
    }
    assert invalid.snapshot.step.key == "create-database"

    review = controller.submit(
        {
            "database_key": "analytics",
            "url": "postgresql://analytics.local/demo",
            "role": "writer",
            "ssl": True,
            "password": "new-secret",
            "notes": "created by demo",
        }
    ).snapshot

    assert isinstance(review.step, ReviewStep)
    assert review.can_apply
    assert "new-secret" not in repr(review)

    result = controller.apply()

    assert result.status == WizardResultStatus.APPLIED
    assert page.active_database == "analytics"
    assert page.revision == "demo-config-1"


def test_demo_config_wizard_supports_back_and_branch_recalculation() -> None:
    page = ConfigPage()
    controller = _DemoConfigWizardController(page)

    assert controller.submit({"strategy": "create"}).snapshot.step.key == "create-database"
    assert controller.back().step.key == "strategy"
    assert controller.submit({"strategy": "reuse"}).snapshot.step.key == "reuse-database"


def test_demo_config_wizard_reports_stale_revision_conflict() -> None:
    page = ConfigPage()
    controller = _DemoConfigWizardController(page)
    page.apply_demo_config(
        {
            "strategy": "reuse",
            "target": page.active_database,
            "make_default": True,
        }
    )

    result = controller.apply()

    assert result.status == WizardResultStatus.CONFLICTED
    assert result.refresh_pages == frozenset({"config"})


def test_wizard_choice_field_renders_dynamic_options_inline() -> None:
    async def run() -> None:
        controller = _DynamicChoiceWizard()
        app = OperatorApp(build_demo_spec())

        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(WizardScreen(controller))
            await pilot.pause()

            picker = app.screen.query_one("#wizard-field-0", OptionList)
            assert picker.option_count == 12
            assert picker.region.height > 1
            assert picker.highlighted == 4

            picker.focus()
            await pilot.press("down")
            await pilot.pause()

            assert picker.highlighted == 5

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

            picker = app.screen.query_one("#wizard-field-0", OptionList)
            assert picker.option_count == 1
            assert picker.highlighted == 0
            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())


def test_config_draft_and_apply_intent_are_safe_and_revision_aware() -> None:
    target = ConfigTarget(kind="database", key="metadata", title="metadata")
    draft = ConfigDraft(
        target=target,
        changed_fields=frozenset({"password", "url"}),
        expected_revision="rev-1",
    )

    assert draft.changed
    assert draft.changed_fields == frozenset({"password", "url"})
    assert "new-secret" not in repr(draft)

    diff = OAConfiguratorAdapter().diff(
        target,
        original_fields={"url": "postgresql://old", "password": "old-secret"},
        candidate_fields={"url": "postgresql://new", "password": "new-secret"},
        sensitive_fields=frozenset({"password"}),
    )
    intent = ConfigApplyIntent(
        target=target,
        apply_token="opaque-token",
        expected_revision=draft.expected_revision,
        diff=diff,
        effects=("refresh:config",),
    )

    assert diff.changed
    assert intent.apply_token == "opaque-token"
    assert intent.expected_revision == "rev-1"
    assert intent.effects == ("refresh:config",)


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
            assert not app.screen.query_one("#wizard-review", Button).disabled

            await pilot.click("#wizard-review")
            await pilot.pause()

            assert app.screen.query_one("#wizard-review", Button).disabled
            assert not app.screen.query_one("#wizard-apply", Button).disabled

            await pilot.click("#wizard-cancel")
            await pilot.pause()

            assert app.screen.id == "_default"
            await pilot.press("q")

    asyncio.run(run())
