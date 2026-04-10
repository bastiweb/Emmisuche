from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SearchResultItem:
    id: int
    title: str
    snippet: str
    image_url: str | None
    source_url: str
    score: float
    last_indexed_at: str | None
    is_stale: bool


@dataclass(slots=True)
class Pagination:
    page: int
    per_page: int
    total: int

    @property
    def total_pages(self) -> int:
        if self.total == 0:
            return 0
        return ((self.total - 1) // self.per_page) + 1

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages
