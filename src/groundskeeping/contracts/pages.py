"""Page and navigation contracts for consumer-owned operator pages."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol, overload

from groundskeeping.contracts.views import (
    CatalogueItem,
    DetailView,
    SurfaceView,
)


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

    def show_catalogue(self, page_key: str, items: Sequence[CatalogueItem]) -> None: ...

    def show_view(self, page_key: str, view: SurfaceView) -> None: ...

    def show_detail(self, page_key: str, detail: DetailView) -> None: ...


class PageContext(Protocol):
    """Narrow context passed to page factories."""

    @property
    def surface(self) -> PageSurfacePort: ...

    def refresh_bindings(self) -> None: ...

    def request_navigation(self, page_key: str) -> None: ...

    def notify(self, message: str, *, severity: str = "information") -> None: ...


class OperatorPage(Protocol):
    """Structural contract implemented by consumer Textual widgets."""

    route: PageRoute

    def activate(self, context: PageContext) -> None: ...

    def deactivate(self, context: PageContext) -> None: ...

    def build_catalogue(self, context: PageContext) -> Sequence[CatalogueItem]: ...

    def landing_view(self, context: PageContext) -> SurfaceView: ...

    def catalogue_selected(self, item: CatalogueItem, context: PageContext) -> None: ...

    def row_highlighted(self, row_key: str, context: PageContext) -> None: ...

    def row_selected(self, row_key: str, context: PageContext) -> None: ...


@dataclass(frozen=True)
class PageRegistration:
    """A page route plus the factory that creates the page widget."""

    route: PageRoute
    factory: Callable[[PageContext], OperatorPage]
