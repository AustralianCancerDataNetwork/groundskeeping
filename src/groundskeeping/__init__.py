"""Reusable operator TUI shell contracts.

The package top level intentionally avoids importing Textual. Headless contracts,
configuration inspection, and telemetry sampling should be importable in worker and test
processes that do not construct an application.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("groundskeeping")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.0.0"

__all__ = ["__version__"]
