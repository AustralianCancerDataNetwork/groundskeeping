"""Small stateless widgets used by the shared workbench."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class EmptyState(Static):
    """Placeholder shown where rows would otherwise be rendered."""

    def show_empty(self, message: str, *, command: str | None = None) -> None:
        body = Text(message, style="bold")
        if command:
            body.append("\n\n")
            body.append(command, style="italic")
        self.update(body)
        self.styles.display = "block"

    def hide_empty(self) -> None:
        self.styles.display = "none"


class LoadingState(Static):
    """Frame-driven loading indicator."""

    FRAMES = ("|", "/", "-", "\\")

    def show_loading(
        self,
        message: str,
        *,
        detail: str | None = None,
        command: str | None = None,
        frame: int = 0,
    ) -> None:
        body = Text()
        body.append(f"{self.FRAMES[frame % len(self.FRAMES)]} ", style="cyan bold")
        body.append(message, style="bold")
        if detail:
            body.append("\n")
            body.append(detail, style="italic")
        if command:
            body.append("\n\n")
            body.append(command, style="grey62")
        self.update(body)
        self.styles.display = "block"

    def hide_loading(self) -> None:
        self.styles.display = "none"
