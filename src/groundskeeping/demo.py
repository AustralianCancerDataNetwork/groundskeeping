"""Small demonstration app for the standalone package."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from textual.widget import Widget

from groundskeeping.app import OperatorApp, OperatorAppSpec
from groundskeeping.configurator import OAConfiguratorAdapter
from groundskeeping.contracts import (
    ActionContext,
    ActionOutcome,
    ActionRegistry,
    ActionSpec,
    Choice,
    ChoiceOption,
    ChoiceStep,
    EmptyView,
    ExecutionKind,
    FieldKind,
    FieldSpec,
    FormStep,
    KeyValueView,
    NavigationItem,
    OperatorPage,
    PageContext,
    PageRegistration,
    PageRoute,
    ReviewChange,
    ReviewStep,
    SectionItem,
    SectionNavigation,
    SelectionTableRow,
    SelectionTableView,
    SemanticStatus,
    SurfaceView,
    TableRow,
    TableView,
    TreeNode,
    TreeView,
    ValidationIssue,
    ViewAction,
    WizardResult,
    WizardResultStatus,
    WizardReview,
    WizardSnapshot,
    WizardSpec,
    WizardTransition,
    validate_wizard_steps,
)
from groundskeeping.telemetry.providers import FakeTelemetrySource


@dataclass
class _DemoDatabase:
    url: str
    password: str
    role: str


@dataclass
class _DemoStackConfig:
    path: str
    active_profile: str
    databases: dict[str, _DemoDatabase]
    resources: dict[str, dict[str, str]]
    profiles: dict[str, dict[str, str]]
    aliases: dict[str, str]


class _DemoPage(Widget):
    route: PageRoute

    def activate(self, context: PageContext) -> None:
        return None

    def deactivate(self, context: PageContext) -> None:
        return None

    def build_navigation(self, context: PageContext) -> SectionNavigation:
        return SectionNavigation(items=())

    def landing_view(self, context: PageContext) -> SurfaceView:
        return EmptyView(title=self.route.label, message="No demo content.")

    def navigation_selected(self, item: NavigationItem, context: PageContext) -> None:
        context.surface.show_view(self.route.key, self.landing_view(context))

    def action_selected(self, action_key: str, context: PageContext) -> None:
        return None

    def row_highlighted(self, row_key: str, context: PageContext) -> None:
        return None

    def row_selected(self, row_key: str, context: PageContext) -> None:
        return None


OVERVIEW_ROUTE = PageRoute(
    key="overview",
    label="Overview",
    purpose="Composition smoke test for the reusable shell.",
)
CONFIG_ROUTE = PageRoute(
    key="config",
    label="Configuration",
    purpose="Read-only stack configuration browser.",
)
TELEMETRY_ROUTE = PageRoute(
    key="telemetry",
    label="Telemetry",
    purpose="Normalized metrics rendered without provider-specific branches.",
)


class OverviewPage(_DemoPage):
    route = OVERVIEW_ROUTE

    def __init__(self) -> None:
        super().__init__()
        self._selected_vocab_keys: tuple[str, ...] = ("__all__",)

    def build_navigation(self, context: PageContext) -> SectionNavigation:
        return SectionNavigation(
            items=(
                SectionItem(
                    "overview.shell", "Shell contracts", status=SemanticStatus.OK
                ),
                SectionItem(
                    "overview.selection",
                    "Selection table",
                    status=SemanticStatus.RUNNING,
                    description="All-vs-specific row controls",
                ),
                SectionItem("overview.boundaries", "Consumer boundaries"),
            )
        )

    def landing_view(self, context: PageContext) -> SurfaceView:
        return TreeView(
            title="Groundskeeping demo",
            message="standalone shell, no consumer imports",
            rows=(
                TreeNode(
                    "Phase one",
                    status=SemanticStatus.OK,
                    fields={
                        "pages": "explicitly registered",
                        "surface": "shared workbench",
                        "configuration": "read-only inspection",
                        "telemetry": "normalized snapshots",
                    },
                ),
            ),
        )

    def navigation_selected(self, item: NavigationItem, context: PageContext) -> None:
        if item.key == "overview.selection":
            context.surface.show_view(self.route.key, self._selection_view())
            context.surface.show_detail(
                self.route.key,
                KeyValueView(
                    title="Selection",
                    rows=(
                        ("changed row", "-"),
                        ("selected keys", ", ".join(self._selected_vocab_keys)),
                    ),
                ),
            )
            return
        context.surface.show_view(self.route.key, self.landing_view(context))

    def selection_changed(
        self, row_key: str, selected_keys: tuple[str, ...], context: PageContext
    ) -> None:
        self._selected_vocab_keys = selected_keys or ("__all__",)
        context.surface.show_view(self.route.key, self._selection_view())
        context.surface.show_detail(
            self.route.key,
            KeyValueView(
                title="Selection",
                rows=(
                    ("changed row", row_key),
                    ("selected keys", ", ".join(self._selected_vocab_keys)),
                ),
            ),
        )

    def _selection_view(self) -> SelectionTableView:
        selected = set(self._selected_vocab_keys)
        return SelectionTableView(
            title="Vocabulary selection",
            message="workbench-owned all-vs-specific controls",
            status=SemanticStatus.RUNNING,
            columns=("Vocabulary", "Coverage", "State"),
            selection_mode="all_or_specific",
            all_row_key="__all__",
            rows=(
                SelectionTableRow(
                    "__all__",
                    ("All vocabularies", "default", "ready"),
                    selected="__all__" in selected,
                ),
                SelectionTableRow(
                    "snomed",
                    ("SNOMED CT", "100%", "complete"),
                    disabled=True,
                ),
                SelectionTableRow(
                    "loinc",
                    ("LOINC", "73%", "available"),
                    selected="loinc" in selected,
                ),
                SelectionTableRow(
                    "rxnorm",
                    ("RxNorm", "41%", "available"),
                    selected="rxnorm" in selected,
                ),
            ),
        )


class ConfigPage(_DemoPage):
    route = CONFIG_ROUTE

    def __init__(self) -> None:
        super().__init__()
        self._revision = "demo-config-0"
        self._apply_count = 0
        self._stack = _DemoStackConfig(
            path="/demo/stack.toml",
            active_profile="tre",
            databases={
                "metadata": _DemoDatabase(
                    url="postgresql://metadata.local/demo",
                    password="not-rendered",
                    role="readonly",
                )
            },
            resources={
                "ollama": {"url": "http://ollama:11434", "kind": "model-server"}
            },
            profiles={"tre": {"database": "metadata"}},
            aliases={"default-model": "snowflake-arctic-embed2"},
        )
        self._snapshot = self._build_snapshot()

    @property
    def revision(self) -> str:
        return self._revision

    @property
    def active_database(self) -> str:
        return self._stack.profiles[self._stack.active_profile]["database"]

    def _build_snapshot(self):
        return OAConfiguratorAdapter().snapshot(
            self._stack, title="Demo stack configuration"
        )

    def build_navigation(self, context: PageContext) -> SectionNavigation:
        return SectionNavigation(
            items=tuple(
                SectionItem(
                    key=section.target.key,
                    label=section.target.title,
                    status=section.target.status,
                )
                for section in self._snapshot.sections
            )
        )

    def landing_view(self, context: PageContext) -> SurfaceView:
        view = OAConfiguratorAdapter().as_tree_view(self._snapshot)
        return replace(
            view,
            message=f"{view.message}; revision: {self._revision}",
            actions=(
                ViewAction(
                    "config.configure",
                    "Configure database",
                    variant="primary",
                ),
            ),
        )

    def action_selected(self, action_key: str, context: PageContext) -> None:
        if action_key == "config.configure":
            context.open_wizard(_DemoConfigWizardController(self))

    def apply_demo_config(self, candidate: Mapping[str, object]) -> None:
        strategy = str(candidate["strategy"])
        if strategy == "create":
            key = str(candidate["database_key"])
            self._stack.databases[key] = _DemoDatabase(
                url=str(candidate["url"]),
                password=str(candidate["password"]),
                role=str(candidate["role"]),
            )
            self._stack.profiles[self._stack.active_profile]["database"] = key
        else:
            self._stack.profiles[self._stack.active_profile]["database"] = str(
                candidate["target"]
            )
        self._apply_count += 1
        self._revision = f"demo-config-{self._apply_count}"
        self._snapshot = self._build_snapshot()


class _DemoConfigWizardController:
    """Tiny consumer-owned wizard proving the setup API shape."""

    spec = WizardSpec(
        key="demo.database-config",
        title="Configure demo database",
        purpose=(
            "Choose an existing database target or create a new one. The controller "
            "owns real candidate values; snapshots only carry render-safe values."
        ),
        apply_label="Apply config",
    )

    def __init__(self, page: ConfigPage) -> None:
        self._page = page
        self._expected_revision = page.revision
        self._step_index = 0
        self._candidate: dict[str, object] = {
            "strategy": "reuse",
            "target": page.active_database,
            "make_default": True,
        }
        self._display_values: dict[str, object] = dict(self._candidate)
        validate_wizard_steps(self._steps())

    def start(self) -> WizardSnapshot:
        return self._snapshot()

    def submit(self, values: Mapping[str, object]) -> WizardTransition:
        step = self._steps()[self._step_index]
        if isinstance(step, ChoiceStep):
            issues = self._submit_choice(step, values)
        elif isinstance(step, FormStep):
            issues = self._submit_form(step, values)
        else:
            issues = ()
        if issues:
            return WizardTransition(self._snapshot(issues=issues), issues)
        self._step_index = min(self._step_index + 1, len(self._steps()) - 1)
        return WizardTransition(self._snapshot())

    def back(self) -> WizardSnapshot:
        self._step_index = max(0, self._step_index - 1)
        return self._snapshot()

    def review(self) -> WizardTransition:
        self._step_index = len(self._steps()) - 1
        return WizardTransition(self._snapshot())

    def apply(self) -> WizardResult:
        if self._page.revision != self._expected_revision:
            return WizardResult(
                status=WizardResultStatus.CONFLICTED,
                summary="Configuration changed before apply.",
                detail={
                    "expected_revision": self._expected_revision,
                    "actual_revision": self._page.revision,
                },
                refresh_pages=frozenset({CONFIG_ROUTE.key}),
            )
        self._page.apply_demo_config(self._candidate)
        return WizardResult(
            status=WizardResultStatus.APPLIED,
            summary="Demo database configuration applied.",
            refresh_pages=frozenset({CONFIG_ROUTE.key}),
        )

    def cancel(self) -> WizardResult:
        return WizardResult(
            status=WizardResultStatus.CANCELLED,
            summary="Configuration wizard cancelled.",
        )

    def _steps(self) -> tuple[ChoiceStep | FormStep | ReviewStep, ...]:
        form = self._create_step()
        if self._candidate.get("strategy") == "reuse":
            form = self._reuse_step()
        return (self._strategy_step(), form, self._review_step())

    def _snapshot(
        self, *, issues: tuple[ValidationIssue, ...] = ()
    ) -> WizardSnapshot:
        steps = self._steps()
        self._step_index = min(self._step_index, len(steps) - 1)
        step = steps[self._step_index]
        return WizardSnapshot(
            spec=self.spec,
            step=step,
            step_index=self._step_index,
            step_count=len(steps),
            values=self._safe_values(step),
            issues=issues,
            can_back=self._step_index > 0,
            can_next=not isinstance(step, ReviewStep),
            can_apply=isinstance(step, ReviewStep)
            and step.review.ready_to_apply
            and not issues,
            expected_revision=self._expected_revision,
        )

    def _safe_values(self, step: ChoiceStep | FormStep | ReviewStep) -> Mapping[str, object]:
        if isinstance(step, ChoiceStep):
            return {step.key: self._display_values.get(step.key)}
        if isinstance(step, FormStep):
            return {
                field.key: None
                if field.masks_value
                else self._display_values.get(field.key, field.default)
                for field in step.fields
            }
        return {}

    def _strategy_step(self) -> ChoiceStep:
        return ChoiceStep(
            key="strategy",
            title="Choose setup path",
            purpose="Reuse a known target or create a new database entry.",
            choices=(
                Choice(
                    "reuse",
                    "Reuse existing database",
                    "Select a configured database and make it active.",
                ),
                Choice(
                    "create",
                    "Create new database",
                    "Collect the connection details needed for a new target.",
                ),
            ),
        )

    def _reuse_step(self) -> FormStep:
        return FormStep(
            key="reuse-database",
            title="Select existing target",
            fields=(
                FieldSpec(
                    key="target",
                    label="Database target",
                    kind=FieldKind.CHOICE,
                    choices=tuple(
                        ChoiceOption(value=key, label=key)
                        for key in sorted(self._page._stack.databases)
                    ),
                    default=self._page.active_database,
                    help="Choose the database entry the active profile should use.",
                ),
                FieldSpec(
                    key="make_default",
                    label="Use for active profile",
                    kind=FieldKind.BOOLEAN,
                    default=True,
                    help="Demo-only boolean field used to prove typed inputs.",
                ),
            ),
        )

    def _create_step(self) -> FormStep:
        return FormStep(
            key="create-database",
            title="Enter connection details",
            fields=(
                FieldSpec(
                    key="database_key",
                    label="Database key",
                    kind=FieldKind.TEXT,
                    placeholder="metadata",
                    help="Unique key used by the active profile.",
                    validator=_validate_database_key,
                ),
                FieldSpec(
                    key="url",
                    label="Connection URL",
                    kind=FieldKind.TEXT,
                    placeholder="postgresql://host:5432/db",
                    help="Connection string or service URL owned by the consumer.",
                ),
                FieldSpec(
                    key="role",
                    label="Role",
                    kind=FieldKind.CHOICE,
                    choices=(
                        ChoiceOption("readonly", "Read only"),
                        ChoiceOption("writer", "Writer"),
                    ),
                    default="readonly",
                ),
                FieldSpec(
                    key="ssl",
                    label="Require TLS",
                    kind=FieldKind.BOOLEAN,
                    default=True,
                    required=False,
                ),
                FieldSpec(
                    key="password",
                    label="Password",
                    kind=FieldKind.SECRET,
                    placeholder="not shown in review",
                    help="Secret values stay in the controller and are redacted in snapshots.",
                ),
                FieldSpec(
                    key="notes",
                    label="Operator notes",
                    kind=FieldKind.MULTILINE,
                    required=False,
                    help="Optional free-text context for the consumer apply operation.",
                ),
            ),
        )

    def _review_step(self) -> ReviewStep:
        strategy = str(self._candidate.get("strategy", "reuse"))
        changes: list[ReviewChange] = []
        if strategy == "reuse":
            changes.append(
                ReviewChange(
                    "active database",
                    self._page.active_database,
                    self._candidate.get("target"),
                )
            )
        else:
            changes.extend(
                (
                    ReviewChange("database key", "-", self._candidate.get("database_key")),
                    ReviewChange("url", "-", self._candidate.get("url")),
                    ReviewChange("role", "-", self._candidate.get("role")),
                    ReviewChange("password", "-", "configured", sensitive=True),
                )
            )
        return ReviewStep(
            key="review",
            title="Review changes",
            purpose="Check the render-safe summary before the consumer applies changes.",
            review=WizardReview(
                changes=tuple(changes),
                effects=(
                    "Update the active profile database target.",
                    f"Carry revision token {self._expected_revision}.",
                ),
                warnings=(
                    "Real applications should run database verification off the event loop.",
                ),
            ),
        )

    def _submit_choice(
        self, step: ChoiceStep, values: Mapping[str, object]
    ) -> tuple[ValidationIssue, ...]:
        value = values.get(step.key)
        allowed = {choice.key for choice in step.choices}
        if value not in allowed:
            return (ValidationIssue("Choose a setup path.", field_key=step.key),)
        self._candidate[step.key] = value
        self._display_values[step.key] = value
        return ()

    def _submit_form(
        self, step: FormStep, values: Mapping[str, object]
    ) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        for field in step.fields:
            try:
                parsed = field.parse(values.get(field.key))
            except ValueError as exc:
                issues.append(ValidationIssue(str(exc), field_key=field.key))
                continue
            self._candidate[field.key] = parsed.value
            self._display_values[field.key] = parsed.redacted
        return tuple(issues)


def _validate_database_key(value: object) -> ValidationIssue | None:
    text = str(value)
    if not text.replace("_", "").replace("-", "").isalnum():
        return ValidationIssue(
            "Use letters, numbers, hyphens, or underscores only.",
            field_key="database_key",
        )
    return None


class TelemetryPage(_DemoPage):
    route = TELEMETRY_ROUTE

    def __init__(self) -> None:
        super().__init__()
        self._source = FakeTelemetrySource()

    def build_navigation(self, context: PageContext) -> SectionNavigation:
        return SectionNavigation(
            items=(
                SectionItem(
                    "fake.accelerator", "Accelerator", status=SemanticStatus.OK
                ),
                SectionItem("fake.workload", "Workload", status=SemanticStatus.RUNNING),
            )
        )

    def landing_view(self, context: PageContext) -> SurfaceView:
        metrics = (
            ("Accelerator", f"{self._source.utilisation:.0f}%", "fake"),
            (
                "Memory",
                f"{self._source.memory_used_mb} / {self._source.memory_total_mb} MiB",
                "fake",
            ),
            ("Throughput", f"{self._source.throughput:.0f} items/s", "fake"),
        )
        return TableView(
            title="Fake telemetry",
            message="capability-aware display data",
            status=SemanticStatus.RUNNING,
            columns=("Metric", "Value", "Source"),
            rows=tuple(
                TableRow(
                    key=f"metric.{index}",
                    cells=row,
                    detail={"metric": row[0], "value": row[1]},
                )
                for index, row in enumerate(metrics)
            ),
        )

    def row_highlighted(self, row_key: str, context: PageContext) -> None:
        context.surface.show_detail(
            self.route.key,
            KeyValueView(
                rows=(
                    ("row", row_key),
                    ("source", self._source.source_id),
                    (
                        "note",
                        "The widget sees normalized metric keys, not a provider class.",
                    ),
                )
            ),
        )


def build_demo_spec() -> OperatorAppSpec:
    def overview_factory(context: PageContext) -> OperatorPage:
        return OverviewPage()

    def config_factory(context: PageContext) -> OperatorPage:
        return ConfigPage()

    def telemetry_factory(context: PageContext) -> OperatorPage:
        return TelemetryPage()

    def demo_runner(
        params: Mapping[str, object], context: ActionContext
    ) -> ActionOutcome:
        context.emit("demo", completed=1, total=1, message="demo action executed")
        return ActionOutcome(
            status=SemanticStatus.OK,
            summary=f"Echoed {params['message']}",
            view=EmptyView(title="Demo action", message=str(params["message"])),
        )

    return OperatorAppSpec(
        app_id="groundskeeping-demo",
        title="Groundskeeping Demo",
        subtitle="standalone reusable shell",
        default_page=OVERVIEW_ROUTE.key,
        actions=ActionRegistry(
            (
                ActionSpec(
                    key="overview.echo",
                    page_key=OVERVIEW_ROUTE.key,
                    label="Echo message",
                    summary="Small executable action used by the demo contract tests.",
                    runner=demo_runner,
                    fields=(
                        FieldSpec(
                            key="message",
                            label="Message",
                            kind=FieldKind.TEXT,
                            default="groundskeeping",
                        ),
                    ),
                    execution=ExecutionKind.QUICK,
                ),
            )
        ),
        pages=(
            PageRegistration(route=OVERVIEW_ROUTE, factory=overview_factory),
            PageRegistration(route=CONFIG_ROUTE, factory=config_factory),
            PageRegistration(route=TELEMETRY_ROUTE, factory=telemetry_factory),
        ),
    )


def main() -> None:
    OperatorApp(build_demo_spec()).run()
