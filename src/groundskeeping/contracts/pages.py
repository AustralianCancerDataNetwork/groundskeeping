"""Page and navigation contracts for consumer-owned operator pages."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, overload

from groundskeeping.contracts.views import (
    DetailView,
    NavigationItem,
    PageNavigation,
    SurfaceView,
)
from groundskeeping.contracts.wizards import WizardController

type NotifySeverity = Literal["information", "warning", "error"]
"""Toast severities the shell forwards to Textual's notification system."""


@dataclass(frozen=True)
class PageRoute:
    """Navigation identity for one operator page."""

    key: str
    label: str
    purpose: str


class PageRegistry(Sequence[PageRoute]):
    """Ordered routes with exact-key lookup and duplicate-key validation."""

    def __init__(self, routes: Sequence[PageRoute]) -> None:
        self._routes = tuple(routes)
        self._by_key = {route.key: route for route in self._routes}
        if len(self._routes) != len(self._by_key):
            raise ValueError("Page route keys must be unique.")
        if not self._routes:
            raise ValueError("At least one page route is required.")

    @overload
    def __getitem__(self, index: int) -> PageRoute: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[PageRoute]: ...

    def __getitem__(self, index: int | slice) -> PageRoute | Sequence[PageRoute]:
        return self._routes[index]

    def __iter__(self) -> Iterator[PageRoute]:
        return iter(self._routes)

    def __len__(self) -> int:
        return len(self._routes)

    def get(self, key: str) -> PageRoute:
        try:
            return self._by_key[key]
        except KeyError as exc:
            raise KeyError(f"Unknown TUI page route: {key}") from exc

    def keys(self) -> tuple[str, ...]:
        return tuple(route.key for route in self._routes)


class PageSurfacePort(Protocol):
    """Workbench surface methods consumer pages may call."""

    def show_navigation(self, page_key: str, navigation: PageNavigation) -> None: ...

    def show_view(self, page_key: str, view: SurfaceView) -> None: ...

    def show_detail(self, page_key: str, detail: DetailView) -> None: ...


class PageContext(Protocol):
    """Narrow context passed to page factories."""

    @property
    def surface(self) -> PageSurfacePort: ...

    def refresh_bindings(self) -> None: ...

    def request_navigation(self, page_key: str) -> None: ...

    def notify(
        self, message: str, *, severity: NotifySeverity = "information"
    ) -> None: ...

    def open_wizard(self, controller: WizardController) -> None: ...


class OperatorPage(Protocol):
    """Structural contract implemented by consumer Textual widgets."""

    route: PageRoute

    def activate(self, context: PageContext) -> None: ...

    def deactivate(self, context: PageContext) -> None: ...

    def build_navigation(self, context: PageContext) -> PageNavigation: ...

    def landing_view(self, context: PageContext) -> SurfaceView: ...

    def navigation_selected(
        self, item: NavigationItem, context: PageContext
    ) -> None: ...

    def action_selected(self, action_key: str, context: PageContext) -> None: ...

    def row_highlighted(self, row_key: str, context: PageContext) -> None: ...

    def row_selected(self, row_key: str, context: PageContext) -> None: ...


@dataclass(frozen=True)
class PageRegistration:
    """A page route plus the factory that creates the page widget."""

    route: PageRoute
    factory: Callable[[PageContext], OperatorPage]
