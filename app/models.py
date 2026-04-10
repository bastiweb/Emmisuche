from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SitemapUrlEntry:
    url: str
    lastmod: str | None = None
    sitemap_url: str | None = None


@dataclass(slots=True)
class ParsedRecipe:
    source_url: str
    title: str
    intro: str | None = None
    image_url: str | None = None
    categories: list[str] = field(default_factory=list)
    published_date: str | None = None
    prep_time: str | None = None
    cook_time: str | None = None
    total_time: str | None = None
    servings: str | None = None
    ingredients: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    nutrition_summary: str | None = None
    searchable_text: str = ""
    last_sitemap_mod: str | None = None


@dataclass(slots=True)
class IndexingStats:
    discovered_urls: int = 0
    scheduled_urls: int = 0
    crawled_urls: int = 0
    indexed_recipes: int = 0
    skipped_non_recipe: int = 0
    skipped_disallowed: int = 0
    skipped_existing: int = 0
    failures: int = 0

