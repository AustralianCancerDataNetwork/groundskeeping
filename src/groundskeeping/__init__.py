"""Reusable operator TUI shell contracts.

The package top level intentionally avoids importing Textual. Headless contracts,
configuration inspection, and telemetry sampling should be importable in worker and test
processes that do not construct an application.
"""

from __future__ import annotations

__version__ = "0.1.0"
