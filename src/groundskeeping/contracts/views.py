"""Generic presentation models rendered by the shared workbench."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

type ViewActionVariant = Literal["default", "primary", "success", "warning", "error"]

MAX_VIEW_ACTIONS = 6


@dataclass(frozen=True)
class WorkbenchLabels:
    """Operator-facing labels for reusable workbench chrome.

    Page-owned content still supplies its own titles through navigation and view contracts.
    These labels only cover structural defaults in the shared shell.
    """

    navigation_panel: str = "Sections"
    result_panel: str = "Rows"
    detail_panel: str = "Detail"
    initial_result_summary: str = "Select a section to inspect it."
    key_value_columns: tuple[str, str] = ("Field", "Value")


class SemanticStatus(StrEnum):
    """Small health/status vocabulary understood by shared widgets."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    IDLE = "idle"
    INFO = "info"
    RUNNING = "running"


@dataclass(frozen=True)
class ViewAction:
    """One command rendered with the current workbench view.

    The shared workbench renders at most `MAX_VIEW_ACTIONS` actions. Extra actions remain part
    of the view model but are not assigned visible buttons.
    """

    key: str
    label: str
    variant: ViewActionVariant = "default"
    disabled: bool = False


@dataclass(frozen=True)
class CatalogueItem:
    """One navigable item in a page's catalogue tree."""

    key: str
    label: str
    kind: str
    ref: object | None = None
    status: SemanticStatus = SemanticStatus.INFO
    children: tuple[CatalogueItem, ...] = ()


@dataclass(frozen=True)
class SectionItem:
    """One flat, navigable section within a page."""

    key: str
    label: str
    status: SemanticStatus = SemanticStatus.INFO
    description: str | None = None


@dataclass(frozen=True)
class SectionNavigation:
    """Flat page navigation rendered as a selectable section list."""

    items: tuple[SectionItem, ...]
    title: str = "Sections"


@dataclass(frozen=True)
class CatalogueNavigation:
    """Hierarchical page navigation rendered as a catalogue tree."""

    items: tuple[CatalogueItem, ...]
    title: str = "Catalogue"


type NavigationItem = SectionItem | CatalogueItem
type PageNavigation = SectionNavigation | CatalogueNavigation


@dataclass(frozen=True)
class TableRow:
    """One row in a selectable workbench table."""

    key: str
    cells: tuple[str, ...]
    detail: object | None = None


@dataclass(frozen=True)
class TableView:
    """A table-shaped surface view."""

    title: str
    columns: tuple[str, ...]
    rows: tuple[TableRow, ...]
    status: SemanticStatus = SemanticStatus.INFO
    message: str | None = None
    actions: tuple[ViewAction, ...] = ()


@dataclass(frozen=True)
class TreeNode:
    """A tree-shaped detail node."""

    label: str
    status: SemanticStatus = SemanticStatus.INFO
    fields: Mapping[str, object] = field(default_factory=dict)
    children: tuple[TreeNode, ...] = ()


@dataclass(frozen=True)
class TreeView:
    """A nested, heterogeneous surface view."""

    title: str
    rows: tuple[TreeNode, ...] = ()
    status: SemanticStatus = SemanticStatus.INFO
    message: str | None = None
    notes: tuple[str, ...] = ()
    actions: tuple[ViewAction, ...] = ()


@dataclass(frozen=True)
class EmptyView:
    """A surface view explaining that no rows are available."""

    title: str
    message: str
    status: SemanticStatus = SemanticStatus.IDLE
    command: str | None = None
    actions: tuple[ViewAction, ...] = ()


@dataclass(frozen=True)
class LoadingView:
    """A surface view for in-progress page work."""

    title: str
    message: str
    detail: str | None = None
    command: str | None = None
    actions: tuple[ViewAction, ...] = ()


@dataclass(frozen=True)
class TextView:
    """Free-text detail content."""

    title: str
    body: str


@dataclass(frozen=True)
class KeyValueView:
    """Structured detail content rendered as a two-column table."""

    rows: tuple[tuple[str, str], ...]
    title: str = "Detail"


type DetailView = TextView | KeyValueView | TableView
type SurfaceView = TableView | TreeView | EmptyView | LoadingView
