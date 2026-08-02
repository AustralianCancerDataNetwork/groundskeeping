"""Generic wizard screen rendered from Textual-free wizard contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    Label,
    OptionList,
    Select,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

from groundskeeping.contracts.actions import FieldKind, FieldSpec
from groundskeeping.contracts.wizards import (
    ChoiceStep,
    FormStep,
    ReviewStep,
    WizardController,
    WizardResult,
    WizardResultStatus,
    WizardSnapshot,
)


class WizardScreen(ModalScreen[WizardResult]):
    """Reusable one-step-at-a-time wizard surface."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "cancel", "Cancel")]

    def __init__(self, controller: WizardController) -> None:
        super().__init__()
        self._controller = controller
        self._snapshot: WizardSnapshot | None = None
        self._field_by_widget_id: dict[str, FieldSpec] = {}
        self._choice_widget_id = "wizard-choice"
        self._blank_choice_id = "__groundskeeping_blank_choice__"

    def compose(self) -> ComposeResult:
        with Vertical(id="wizard-frame"):
            yield Static("", id="wizard-title")
            yield Static("", id="wizard-progress")
            yield VerticalScroll(id="wizard-body")
            yield Static("", id="wizard-errors")
            with Horizontal(id="wizard-buttons"):
                yield Button("Back", id="wizard-back")
                yield Button("Next", variant="primary", id="wizard-next")
                yield Button("Review", id="wizard-review")
                yield Button("Apply", variant="success", id="wizard-apply")
                yield Button("Cancel", id="wizard-cancel")

    async def on_mount(self) -> None:
        await self._set_snapshot(self._controller.start())

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "wizard-back":
            await self._set_snapshot(self._controller.back())
            return
        if event.button.id == "wizard-next":
            await self._submit_current_step()
            return
        if event.button.id == "wizard-review":
            transition = self._controller.review()
            await self._set_snapshot(transition.snapshot)
            return
        if event.button.id == "wizard-apply":
            result = self._controller.apply()
            if result.status in {WizardResultStatus.CONFLICTED, WizardResultStatus.FAILED}:
                self._show_result_issue(result)
                event.button.disabled = True
                return
            self.dismiss(result)
            return
        if event.button.id == "wizard-cancel":
            self.dismiss(self._controller.cancel())

    def action_cancel(self) -> None:
        self.dismiss(self._controller.cancel())

    async def _submit_current_step(self) -> None:
        snapshot = self._require_snapshot()
        values = {} if isinstance(snapshot.step, ReviewStep) else self._collect_values(snapshot)
        transition = self._controller.submit(values)
        await self._set_snapshot(transition.snapshot)

    async def _set_snapshot(self, snapshot: WizardSnapshot) -> None:
        self._snapshot = snapshot
        self.query_one("#wizard-title", Static).update(snapshot.spec.title)
        self.query_one("#wizard-progress", Static).update(
            f"Step {snapshot.step_index + 1} of {snapshot.step_count}: {snapshot.step.title}"
        )
        self._show_issues(snapshot)
        await self._render_step(snapshot)
        self._sync_buttons(snapshot)
        self._focus_first_issue(snapshot)

    async def _render_step(self, snapshot: WizardSnapshot) -> None:
        body = self.query_one("#wizard-body", VerticalScroll)
        await body.remove_children()
        self._field_by_widget_id = {}
        step = snapshot.step
        if step.purpose:
            await body.mount(Static(step.purpose, classes="wizard-purpose"))
        if isinstance(step, FormStep):
            for index, field in enumerate(step.fields):
                widget_id = f"wizard-field-{index}"
                self._field_by_widget_id[widget_id] = field
                await body.mount(Label(field.label, classes="wizard-field-label"))
                await body.mount(self._field_widget(widget_id, field, snapshot.values.get(field.key)))
                if field.help:
                    await body.mount(Static(field.help, classes="wizard-field-help"))
            return
        if isinstance(step, ChoiceStep):
            options = [(choice.label, choice.key) for choice in step.choices]
            current = snapshot.values.get(step.key, Select.BLANK)
            await body.mount(
                Select(
                    options,
                    prompt="Choose an option",
                    value=current if current is not None else Select.BLANK,
                    id=self._choice_widget_id,
                    allow_blank=False,
                )
            )
            for choice in step.choices:
                await body.mount(
                    Static(f"{choice.label}: {choice.description}", classes="wizard-field-help")
                )
            return
        if isinstance(step, ReviewStep):
            table = DataTable(id="wizard-review-table")
            table.add_columns("Field", "Before", "After")
            for change in step.review.changes:
                table.add_row(
                    change.field,
                    "<redacted>" if change.sensitive else _display(change.before),
                    "<redacted>" if change.sensitive else _display(change.after),
                )
            await body.mount(table)
            for effect in step.review.effects:
                await body.mount(Static(f"Effect: {effect}", classes="wizard-field-help"))
            for warning in step.review.warnings:
                await body.mount(Static(f"Warning: {warning}", classes="wizard-warning"))

    def _field_widget(
        self, widget_id: str, field: FieldSpec, value: object
    ) -> Input | TextArea | Checkbox | OptionList:
        disabled = field.disabled or field.read_only
        if field.kind is FieldKind.BOOLEAN:
            return Checkbox(value=bool(value if value is not None else field.default), id=widget_id, disabled=disabled)
        if field.kind is FieldKind.CHOICE:
            current = value if value is not None else field.default
            options = []
            if not field.required:
                options.append(
                    Option(field.placeholder or "No selection", id=self._blank_choice_id)
                )
            options.extend(
                Option(
                    choice.label
                    if choice.description is None
                    else f"{choice.label} — {choice.description}",
                    id=choice.value,
                )
                for choice in field.choices
            )
            if not options:
                options.append(Option(field.placeholder or "No choices", disabled=True))
            widget = OptionList(
                *options,
                id=widget_id,
                disabled=disabled,
                classes="wizard-choice-list",
            )
            widget.styles.height = min(max(len(options), 2), 8)
            choice_ids = tuple(option.id for option in options)
            if current is None and not field.required:
                widget.highlighted = 0
            elif current in choice_ids:
                widget.highlighted = choice_ids.index(current)
            elif field.required and field.choices:
                widget.highlighted = 0
            return widget
        if field.kind is FieldKind.MULTILINE:
            widget = TextArea("" if value is None else str(value), id=widget_id)
            widget.read_only = disabled
            return widget
        input_type = "text"
        if field.kind is FieldKind.INTEGER:
            input_type = "integer"
        elif field.kind is FieldKind.DECIMAL:
            input_type = "number"
        return Input(
            "" if value is None else str(value),
            placeholder=field.placeholder or "",
            password=field.kind is FieldKind.SECRET,
            type=input_type,
            id=widget_id,
            disabled=disabled,
        )

    def _collect_values(self, snapshot: WizardSnapshot) -> dict[str, object]:
        step = snapshot.step
        if isinstance(step, ChoiceStep):
            selected = self.query_one(f"#{self._choice_widget_id}", Select).value
            return {step.key: None if selected is Select.BLANK else selected}
        if not isinstance(step, FormStep):
            return {}
        values: dict[str, object] = {}
        for widget_id, field in self._field_by_widget_id.items():
            values[field.key] = _widget_value(self.query_one(f"#{widget_id}"))
        return values

    def _show_issues(self, snapshot: WizardSnapshot) -> None:
        if not snapshot.issues:
            self.query_one("#wizard-errors", Static).update("")
            return
        self.query_one("#wizard-errors", Static).update(
            "\n".join(f"{issue.field_key or 'step'}: {issue.message}" for issue in snapshot.issues)
        )

    def _show_result_issue(self, result: WizardResult) -> None:
        detail = "" if result.detail is None else f"\n{result.detail}"
        self.query_one("#wizard-errors", Static).update(f"{result.summary}{detail}")

    def _focus_first_issue(self, snapshot: WizardSnapshot) -> None:
        for issue in snapshot.issues:
            if issue.field_key is None:
                continue
            for widget_id, field in self._field_by_widget_id.items():
                if field.key == issue.field_key:
                    self.query_one(f"#{widget_id}").focus()
                    return

    def _sync_buttons(self, snapshot: WizardSnapshot) -> None:
        self.query_one("#wizard-back", Button).disabled = not snapshot.can_back
        self.query_one("#wizard-next", Button).disabled = not snapshot.can_next
        self.query_one("#wizard-review", Button).disabled = isinstance(
            snapshot.step, ReviewStep
        )
        apply_button = self.query_one("#wizard-apply", Button)
        apply_button.label = snapshot.spec.apply_label
        apply_button.disabled = not snapshot.can_apply

    def _require_snapshot(self) -> WizardSnapshot:
        if self._snapshot is None:
            raise RuntimeError("Wizard has not started.")
        return self._snapshot


def _widget_value(widget: object) -> object:
    if isinstance(widget, Input):
        return widget.value
    if isinstance(widget, TextArea):
        return widget.text
    if isinstance(widget, Checkbox):
        return widget.value
    if isinstance(widget, OptionList):
        if widget.highlighted is None:
            return None
        selected = widget.get_option_at_index(widget.highlighted)
        return None if selected.id == "__groundskeeping_blank_choice__" else selected.id
    if isinstance(widget, Select):
        selected = widget.value
        return None if selected is Select.BLANK else selected
    return None


def _display(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, Decimal):
        return str(value)
    return str(value)
