"""Rendered-state tests for `WizardScreen`.

Every assertion here is about geometry or drawn colour rather than contract data. A field
whose height rounds to zero, or a disabled button that still reads as its variant colour,
satisfies `FormStep`/`FieldSpec` exactly and only fails in front of an operator, so these
cases drive the real widget through `run_test` instead of inspecting a snapshot.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace

from textual.widget import Widget
from textual.widgets import Button, Checkbox, Input, Select, TextArea

from groundskeeping.app import OperatorApp
from groundskeeping.contracts.actions import ChoiceOption, FieldKind, FieldSpec
from groundskeeping.contracts.wizards import (
    FormStep,
    ReviewChange,
    ReviewStep,
    WizardResult,
    WizardResultStatus,
    WizardReview,
    WizardSnapshot,
    WizardSpec,
    WizardTransition,
)
from groundskeeping.demo import build_demo_spec
from groundskeeping.widgets.wizard import WizardScreen

# A defaulted absolute path is the value most at risk from select-on-focus, so the text
# and path fields carry one here rather than a short placeholder.
CONFIG_PATH = "/Users/operator/.config/omop/config.toml"
VOCABULARY_CSV = "/data/vocabularies/omop/CONCEPT.csv"

ALL_KINDS = (
    FieldSpec(key="name", label="Profile name", kind=FieldKind.TEXT, default=CONFIG_PATH),
    FieldSpec(
        key="source",
        label="Vocabulary file",
        kind=FieldKind.EXISTING_PATH,
        default=VOCABULARY_CSV,
    ),
    FieldSpec(
        key="target", label="Output database", kind=FieldKind.OUTPUT_PATH, default="/tmp/omop.db"
    ),
    FieldSpec(key="password", label="Password", kind=FieldKind.SECRET, required=False),
    FieldSpec(key="batch", label="Batch size", kind=FieldKind.INTEGER, default=1000),
    FieldSpec(key="threshold", label="Threshold", kind=FieldKind.DECIMAL, default="0.5"),
    FieldSpec(key="strict", label="Strict mode", kind=FieldKind.BOOLEAN, default=True),
    FieldSpec(
        key="dialect",
        label="Dialect",
        kind=FieldKind.CHOICE,
        choices=(
            ChoiceOption(value="postgresql", label="PostgreSQL"),
            ChoiceOption(value="sqlite", label="SQLite"),
        ),
    ),
    FieldSpec(
        key="vocabularies",
        label="Vocabularies",
        kind=FieldKind.MULTILINE,
        default="SNOMED\nRxNorm",
        help="One vocabulary per line.",
    ),
)

# Numeric inputs reject a letter, so they need a digit to prove the keypress landed.
_NUMERIC = frozenset({FieldKind.INTEGER, FieldKind.DECIMAL})

SPEC = WizardSpec(
    key="rendering", title="Rendering wizard", purpose="Exercise every field kind."
)


class _StubController:
    """Two-step wizard: one form carrying the fields under test, then a review."""

    def __init__(
        self, fields: tuple[FieldSpec, ...] = ALL_KINDS, *, apply_label: str = "Apply"
    ) -> None:
        self.spec = replace(SPEC, apply_label=apply_label)
        self._form = FormStep(
            key="form", title="Fields", fields=fields, purpose="Enter the values."
        )
        self._review = ReviewStep(
            key="review",
            title="Review",
            review=WizardReview(
                changes=(ReviewChange(field="name", before=None, after=CONFIG_PATH),)
            ),
        )

    def start(self) -> WizardSnapshot:
        return WizardSnapshot(
            spec=self.spec,
            step=self._form,
            step_index=0,
            step_count=2,
            values={field.key: field.default for field in self._form.fields},
            can_back=False,
            can_next=True,
            can_review=True,
            can_apply=False,
        )

    def submit(self, values: Mapping[str, object]) -> WizardTransition:
        return self.review()

    def back(self) -> WizardSnapshot:
        return self.start()

    def review(self) -> WizardTransition:
        return WizardTransition(
            snapshot=WizardSnapshot(
                spec=self.spec,
                step=self._review,
                step_index=1,
                step_count=2,
                can_back=True,
                can_next=False,
                can_review=False,
                can_apply=True,
            )
        )

    def apply(self) -> WizardResult:
        return WizardResult(status=WizardResultStatus.APPLIED, summary="Applied.")

    def cancel(self) -> WizardResult:
        return WizardResult(status=WizardResultStatus.CANCELLED, summary="Cancelled.")


def _field_widgets(
    app: OperatorApp, fields: tuple[FieldSpec, ...]
) -> list[tuple[FieldSpec, Widget]]:
    return [
        (field, app.screen.query_one(f"#wizard-field-{index}"))
        for index, field in enumerate(fields)
    ]


def test_every_field_kind_renders_at_a_usable_size() -> None:
    async def run() -> None:
        # Small terminal included: a fractional field height starves first when the modal
        # has fewer rows to hand out.
        for size in ((120, 40), (80, 24)):
            app = OperatorApp(build_demo_spec())
            async with app.run_test(size=size) as pilot:
                app.push_screen(WizardScreen(_StubController()))
                await pilot.pause()

                for field, widget in _field_widgets(app, ALL_KINDS):
                    assert widget.size.height >= 1, (field.kind, size, widget.size)
                    assert widget.size.width > 0, (field.kind, size, widget.size)
                    assert not widget.disabled, field.kind
                    if field.kind is FieldKind.MULTILINE:
                        # One row would technically be drawn but is not an entry box.
                        assert widget.size.height >= 3, (size, widget.size)

                await pilot.press("escape")
                await pilot.press("q")

    asyncio.run(run())


def test_every_editable_field_kind_accepts_a_keypress() -> None:
    async def run() -> None:
        app = OperatorApp(build_demo_spec())
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(WizardScreen(_StubController()))
            await pilot.pause()

            for field, widget in _field_widgets(app, ALL_KINDS):
                widget.focus()
                await pilot.pause()
                if isinstance(widget, Input):
                    before = widget.value
                    await pilot.press("7" if field.kind in _NUMERIC else "z")
                    assert widget.value != before, field.kind
                elif isinstance(widget, TextArea):
                    before = widget.text
                    await pilot.press("z")
                    assert widget.text != before, field.kind
                elif isinstance(widget, Checkbox):
                    before = widget.value
                    await pilot.press("enter")
                    assert widget.value is not before, field.kind
                else:
                    assert isinstance(widget, Select), field.kind
                    await pilot.press("enter")
                    await pilot.pause()
                    overlay = widget.query_one("SelectOverlay")
                    assert overlay.size.height >= 1, field.kind
                    await pilot.press("escape")

            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())


def test_editable_kinds_keep_their_default_value_when_typed_into() -> None:
    async def run() -> None:
        app = OperatorApp(build_demo_spec())
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(WizardScreen(_StubController()))
            await pilot.pause()

            for index in (0, 1, 2):
                field, widget = _field_widgets(app, ALL_KINDS)[index]
                assert isinstance(widget, Input)
                default = str(field.default)
                widget.focus()
                await pilot.pause()
                await pilot.press("z")
                assert widget.value == f"{default}z", (field.kind, widget.value)

            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())


def test_a_field_can_ask_for_select_on_focus() -> None:
    async def run() -> None:
        fields = (
            FieldSpec(
                key="name",
                label="Profile name",
                kind=FieldKind.TEXT,
                default=CONFIG_PATH,
                select_on_focus=True,
            ),
        )
        app = OperatorApp(build_demo_spec())
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(WizardScreen(_StubController(fields)))
            await pilot.pause()

            widget = app.screen.query_one("#wizard-field-0", Input)
            widget.focus()
            await pilot.pause()
            await pilot.press("z")
            assert widget.value == "z"

            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())


def test_a_value_wider_than_its_field_stays_visible() -> None:
    """A single-row Input has no row to give a horizontal scrollbar."""

    async def run() -> None:
        long_path = (
            "/Users/operator/Documents/CODE/core-stack/omop-alchemy/vocabularies/"
            "2026-05/standard/CONCEPT.csv"
        )
        fields = (
            FieldSpec(
                key="source",
                label="Vocabulary file",
                kind=FieldKind.EXISTING_PATH,
                default=long_path,
            ),
        )
        app = OperatorApp(build_demo_spec())
        async with app.run_test(size=(100, 34)) as pilot:
            app.push_screen(WizardScreen(_StubController(fields)))
            await pilot.pause()

            widget = app.screen.query_one("#wizard-field-0", Input)
            assert len(widget.value) > widget.size.width
            # The field's own row must still belong to the field. A horizontal scrollbar
            # here would take the only row it has and the value would look empty.
            row = widget.region.y + widget.region.height // 2
            column = widget.region.x + widget.region.width // 2
            covering, _ = app.screen.get_widget_at(column, row)
            assert covering is widget, covering

            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())


def test_a_long_apply_label_stays_inside_its_button() -> None:
    """`apply_label` is application copy, so the button has to fit what it is given."""

    async def run() -> None:
        for label in ("Apply", "Create database", "Replace shared configuration target"):
            app = OperatorApp(build_demo_spec())
            async with app.run_test(size=(120, 40)) as pilot:
                app.push_screen(WizardScreen(_StubController(apply_label=label)))
                await pilot.pause()

                button = app.screen.query_one("#wizard-apply", Button)
                assert str(button.label) == label
                lines = button.get_content_height(
                    button.container_size, button.size, button.size.width
                )
                # A wrapped label spills onto the button's bottom border row, and the button
                # itself grows taller than the three-row button strip it sits in.
                assert lines == 1, (label, lines)
                assert button.region.height == 3, (label, button.region)
                # Growing to the label must not cost the buttons beside it.
                frame = app.screen.query_one("#wizard-frame")
                for other in app.screen.query(Button):
                    assert frame.region.contains_region(other.region), (label, other.id)

                await pilot.press("escape")
                await pilot.press("q")

    asyncio.run(run())


def test_disabled_buttons_do_not_render_as_their_variant_colour() -> None:
    async def run() -> None:
        app = OperatorApp(build_demo_spec())
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(WizardScreen(_StubController()))
            await pilot.pause()

            def background(button_id: str) -> str:
                button = app.screen.query_one(f"#{button_id}", Button)
                region = button.region
                style = app.screen.get_style_at(
                    region.x + region.width // 2, region.y + region.height // 2
                )
                assert style.bgcolor is not None and style.bgcolor.triplet is not None
                return style.bgcolor.triplet.hex

            apply_disabled = background("wizard-apply")
            # A disabled success button must not read as a variant at all, so it matches the
            # disabled default button beside it rather than a dimmer green.
            assert apply_disabled == background("wizard-back")
            assert apply_disabled != background("wizard-next")

            app.screen.query_one("#wizard-review", Button).press()
            await pilot.pause()
            assert not app.screen.query_one("#wizard-apply", Button).disabled
            assert background("wizard-apply") != apply_disabled

            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())


def test_a_subclassed_app_starts_and_keeps_the_packaged_theme() -> None:
    """A consumer subclass must not have to re-anchor `CSS_PATH` to add its own rules."""

    class _ConsumerApp(OperatorApp):
        CSS = "#wizard-body TextArea { height: 4; }"

    async def run() -> None:
        app = _ConsumerApp(build_demo_spec())
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(WizardScreen(_StubController()))
            await pilot.pause()

            # The consumer rule wins on the field, and the packaged theme is still loaded.
            assert app.screen.query_one(TextArea).region.height == 4
            assert app.screen.query_one("#wizard-buttons").size.height == 3

            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(run())
