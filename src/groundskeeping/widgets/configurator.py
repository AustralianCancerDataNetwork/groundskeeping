"""Textual configuration browser primitives."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from groundskeeping.configurator import (
    ConfigSectionView,
    ConfiguratorSnapshot,
    OAConfiguratorAdapter,
)
from groundskeeping.theme import node_label


class ConfiguratorBrowser(Widget):
    """Read-only browser for a `ConfiguratorSnapshot`."""

    def __init__(self, snapshot: ConfiguratorSnapshot, *, adapter: OAConfiguratorAdapter | None = None) -> None:
        super().__init__()
        self.snapshot = snapshot
        self.adapter = adapter or OAConfiguratorAdapter()

    def compose(self) -> ComposeResult:
        yield Tree(self.snapshot.title, id="configurator-tree")

    def on_mount(self) -> None:
        self.refresh_snapshot(self.snapshot)

    def refresh_snapshot(self, snapshot: ConfiguratorSnapshot) -> None:
        self.snapshot = snapshot
        tree = self.query_one("#configurator-tree", Tree)
        tree.clear()
        tree.root.expand()
        for section in snapshot.sections:
            self._add_section(tree.root, section)

    def _add_section(
        self,
        parent: TreeNode[object],
        section: ConfigSectionView,
    ) -> None:
        """Render every nested view and its inspection notes consistently."""
        node = parent.add(
            node_label(section.target.status, section.target.title),
            expand=True,
        )
        for key, value in section.fields.items():
            node.add_leaf(f"{key}: {value}")
        for note in section.notes:
            node.add_leaf(f"note: {note}")
        for child in section.children:
            self._add_section(node, child)
