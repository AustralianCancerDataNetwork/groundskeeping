"""Shared navigation helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SurfaceLease:
    """Identity of the page/generation that currently owns workbench row events."""

    page_key: str
    source_key: str
    generation: int

    def next_generation(self, *, source_key: str | None = None) -> SurfaceLease:
        return SurfaceLease(
            page_key=self.page_key,
            source_key=self.source_key if source_key is None else source_key,
            generation=self.generation + 1,
        )
