"""Neutral theme and status styling helpers for Groundskeeping widgets."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.theme import Theme

from groundskeeping.contracts.views import SemanticStatus


GROUNDSKEEPING_THEME = Theme(
    name="groundskeeping",
    dark=True,
    primary="#5EA0A8",
    secondary="#8795A6",
    accent="#74B6C2",
    foreground="#D8E0E8",
    background="#101418",
    surface="#171D23",
    panel="#202832",
    success="#69A96F",
    warning="#C8A637",
    error="#C65F5A",
)


@dataclass(frozen=True)
class StatusStyle:
    glyph: str
    style: str
    css_class: str


STATUS: dict[str, StatusStyle] = {
    SemanticStatus.OK.value: StatusStyle("*", "green", "-ok"),
    "completed": StatusStyle("*", "green", "-ok"),
    SemanticStatus.WARNING.value: StatusStyle("!", "yellow3", "-warning"),
    SemanticStatus.ERROR.value: StatusStyle("x", "red", "-error"),
    "failed": StatusStyle("x", "red", "-error"),
    SemanticStatus.IDLE.value: StatusStyle("o", "grey70", "-idle"),
    SemanticStatus.RUNNING.value: StatusStyle("o", "cyan", "-running"),
    SemanticStatus.INFO.value: StatusStyle("-", "grey62", "-info"),
}

_FALLBACK = STATUS[SemanticStatus.INFO.value]


def status_style(status: str | SemanticStatus | None) -> StatusStyle:
    value = status.value if isinstance(status, SemanticStatus) else status
    return STATUS.get((value or "").strip().lower(), _FALLBACK)


def status_glyph(status: str | SemanticStatus | None) -> Text:
    resolved = status_style(status)
    return Text(resolved.glyph, style=resolved.style)


def node_label(status: str | SemanticStatus | None, name: str, *metrics: str | None) -> Text:
    label = status_glyph(status)
    label.append(" ")
    label.append(name)
    shown = [metric for metric in metrics if metric]
    if shown:
        label.append("  ")
        label.append(" · ".join(shown), style="grey62")
    return label
