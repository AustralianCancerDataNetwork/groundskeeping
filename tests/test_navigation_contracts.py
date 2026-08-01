from __future__ import annotations

import pytest

from groundskeeping.contracts import PageRegistry, PageRoute


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
