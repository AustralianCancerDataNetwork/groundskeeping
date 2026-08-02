from __future__ import annotations

import pytest

from groundskeeping.contracts import (
    PageRegistry,
    PageRoute,
    SectionItem,
    SectionNavigation,
    TableView,
    ViewAction,
)


def test_page_registry_rejects_duplicate_keys() -> None:
    route = PageRoute("overview", "Overview", "First page")

    with pytest.raises(ValueError, match="unique"):
        PageRegistry((route, route))


def test_page_registry_requires_at_least_one_route() -> None:
    with pytest.raises(ValueError, match="At least one"):
        PageRegistry(())


def test_page_registry_looks_up_routes_by_key() -> None:
    overview = PageRoute("overview", "Overview", "First page")
    telemetry = PageRoute("telemetry", "Telemetry", "Metrics page")
    registry = PageRegistry((overview, telemetry))

    assert registry.get("telemetry") == telemetry
    assert registry.keys() == ("overview", "telemetry")

    with pytest.raises(KeyError, match="Unknown"):
        registry.get("missing")


def test_section_navigation_is_flat_and_ordered() -> None:
    navigation = SectionNavigation(
        (
            SectionItem("database", "Database"),
            SectionItem("embeddings", "Embeddings"),
        ),
        title="Setup",
    )

    assert navigation.title == "Setup"
    assert tuple(item.key for item in navigation.items) == ("database", "embeddings")


def test_surface_actions_are_commands_not_navigation_items() -> None:
    view = TableView(
        title="Database",
        columns=("Resource",),
        rows=(),
        actions=(ViewAction("database.verify", "Test connections", variant="primary"),),
    )

    assert view.actions[0].key == "database.verify"
