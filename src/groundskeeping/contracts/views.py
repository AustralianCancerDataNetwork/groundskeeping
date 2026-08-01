"""Generic presentation models rendered by the shared workbench."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class SemanticStatus(StrEnum):
    """Small health/status vocabulary understood by shared widgets."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    IDLE = "idle"
    INFO = "info"
    RUNNING = "running"


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


@dataclass(frozen=True)
class EmptyView:
    """A surface view explaining that no rows are available."""

    title: str
    message: str
    status: SemanticStatus = SemanticStatus.IDLE
    command: str | None = None


@dataclass(frozen=True)
class LoadingView:
    """A surface view for in-progress page work."""

    title: str
    message: str
    detail: str | None = None
    command: str | None = None


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


type DetailView = TextView | KeyValueView
type SurfaceView = TableView | TreeView | EmptyView | LoadingView
