from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse, urlunparse

from app.db import get_connection
from app.models import ParsedRecipe


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_stale(last_indexed_at: str | None, stale_days: int) -> bool:
    parsed = _parse_iso_datetime(last_indexed_at)
    if parsed is None:
        return True
    return parsed < (datetime.now(UTC) - timedelta(days=stale_days))


def _url_variants(url: str) -> list[str]:
    raw = (url or "").strip()
    if not raw:
        return []

    variants = [raw]
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return variants

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")

    normalized = urlunparse((scheme, netloc, path, "", "", ""))
    if normalized not in variants:
        variants.append(normalized)

    if path == "/":
        return variants

    with_trailing_slash = f"{normalized}/"
    if with_trailing_slash not in variants:
        variants.append(with_trailing_slash)
    return variants


def _row_to_recipe(
    row: sqlite3.Row | None,
    stale_days: int,
) -> dict[str, Any] | None:
    if row is None:
        return None

    recipe = dict(row)
    recipe["categories"] = json.loads(recipe.pop("categories_json") or "[]")
    recipe["ingredients"] = json.loads(recipe.pop("ingredients_json") or "[]")
    recipe["instructions"] = json.loads(recipe.pop("instructions_json") or "[]")
    recipe["is_stale"] = _is_stale(recipe.get("last_indexed_at"), stale_days)
    return recipe


class RecipeRepository:
    def __init__(self, database_path: Path, stale_days: int = 30):
        self.database_path = database_path
        self.stale_days = max(1, stale_days)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = get_connection(self.database_path)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def upsert_recipe(
        self, recipe: ParsedRecipe, connection: sqlite3.Connection | None = None
    ) -> None:
        categories = [item.strip() for item in recipe.categories if item.strip()]
        ingredients = [item.strip() for item in recipe.ingredients if item.strip()]
        instructions = [item.strip() for item in recipe.instructions if item.strip()]

        categories_text = " | ".join(categories)
        ingredients_text = "\n".join(ingredients)
        instructions_text = "\n".join(instructions)
        searchable_text = (
            recipe.searchable_text.strip()
            or " ".join(
                part
                for part in [
                    recipe.title,
                    recipe.intro or "",
                    categories_text,
                    ingredients_text,
                    instructions_text,
                ]
                if part
            )
        )
        now_iso = _utc_now_iso()

        own_connection = connection is None
        conn = connection or get_connection(self.database_path)
        try:
            conn.execute(
                """
                INSERT INTO recipes(
                    source_url,
                    title,
                    intro,
                    image_url,
                    categories_json,
                    categories_text,
                    published_date,
                    prep_time,
                    cook_time,
                    total_time,
                    servings,
                    ingredients_json,
                    ingredients_text,
                    instructions_json,
                    instructions_text,
                    nutrition_summary,
                    searchable_text,
                    last_sitemap_mod,
                    last_crawled_at,
                    last_indexed_at,
                    updated_at
                )
                VALUES(
                    :source_url,
                    :title,
                    :intro,
                    :image_url,
                    :categories_json,
                    :categories_text,
                    :published_date,
                    :prep_time,
                    :cook_time,
                    :total_time,
                    :servings,
                    :ingredients_json,
                    :ingredients_text,
                    :instructions_json,
                    :instructions_text,
                    :nutrition_summary,
                    :searchable_text,
                    :last_sitemap_mod,
                    :last_crawled_at,
                    :last_indexed_at,
                    :updated_at
                )
                ON CONFLICT(source_url) DO UPDATE SET
                    title = excluded.title,
                    intro = excluded.intro,
                    image_url = excluded.image_url,
                    categories_json = excluded.categories_json,
                    categories_text = excluded.categories_text,
                    published_date = excluded.published_date,
                    prep_time = excluded.prep_time,
                    cook_time = excluded.cook_time,
                    total_time = excluded.total_time,
                    servings = excluded.servings,
                    ingredients_json = excluded.ingredients_json,
                    ingredients_text = excluded.ingredients_text,
                    instructions_json = excluded.instructions_json,
                    instructions_text = excluded.instructions_text,
                    nutrition_summary = excluded.nutrition_summary,
                    searchable_text = excluded.searchable_text,
                    last_sitemap_mod = excluded.last_sitemap_mod,
                    last_crawled_at = excluded.last_crawled_at,
                    last_indexed_at = excluded.last_indexed_at,
                    updated_at = excluded.updated_at
                """,
                {
                    "source_url": recipe.source_url,
                    "title": recipe.title.strip(),
                    "intro": recipe.intro,
                    "image_url": recipe.image_url,
                    "categories_json": json.dumps(categories, ensure_ascii=False),
                    "categories_text": categories_text,
                    "published_date": recipe.published_date,
                    "prep_time": recipe.prep_time,
                    "cook_time": recipe.cook_time,
                    "total_time": recipe.total_time,
                    "servings": recipe.servings,
                    "ingredients_json": json.dumps(ingredients, ensure_ascii=False),
                    "ingredients_text": ingredients_text,
                    "instructions_json": json.dumps(instructions, ensure_ascii=False),
                    "instructions_text": instructions_text,
                    "nutrition_summary": recipe.nutrition_summary,
                    "searchable_text": searchable_text,
                    "last_sitemap_mod": recipe.last_sitemap_mod,
                    "last_crawled_at": now_iso,
                    "last_indexed_at": now_iso,
                    "updated_at": now_iso,
                },
            )
            if own_connection:
                conn.commit()
        finally:
            if own_connection:
                conn.close()

    def get_recipe_by_id(self, recipe_id: int) -> dict[str, Any] | None:
        with get_connection(self.database_path) as conn:
            row = conn.execute(
                """
                SELECT
                    r.*,
                    CASE WHEN f.recipe_id IS NULL THEN 0 ELSE 1 END AS is_favorite,
                    f.note AS favorite_note
                FROM recipes r
                LEFT JOIN favorites f ON f.recipe_id = r.id
                WHERE r.id = ?
                """,
                (recipe_id,),
            ).fetchone()
        recipe = _row_to_recipe(row, self.stale_days)
        if recipe is not None:
            recipe["is_favorite"] = bool(recipe.get("is_favorite"))
        return recipe

    def count_recipes(self) -> int:
        with get_connection(self.database_path) as conn:
            value = conn.execute("SELECT COUNT(*) AS count FROM recipes").fetchone()
        return int(value["count"]) if value else 0

    def count_favorites(self) -> int:
        with get_connection(self.database_path) as conn:
            value = conn.execute("SELECT COUNT(*) AS count FROM favorites").fetchone()
        return int(value["count"]) if value else 0

    def list_recent(self, limit: int = 12) -> list[dict[str, Any]]:
        with get_connection(self.database_path) as conn:
            rows = conn.execute(
                """
                SELECT id, title, intro, image_url, source_url, updated_at, last_indexed_at
                FROM recipes
                ORDER BY last_indexed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            item["is_stale"] = _is_stale(item.get("last_indexed_at"), self.stale_days)
        return result

    def get_latest_indexed_at(self) -> str | None:
        with get_connection(self.database_path) as conn:
            row = conn.execute(
                "SELECT MAX(last_indexed_at) AS last_indexed_at FROM recipes"
            ).fetchone()
        if not row:
            return None
        return row["last_indexed_at"]

    def get_url_metadata(
        self, urls: list[str], connection: sqlite3.Connection | None = None
    ) -> dict[str, dict[str, Any]]:
        if not urls:
            return {}

        placeholders = ",".join("?" for _ in urls)
        query = f"""
            SELECT source_url, last_crawled_at, last_indexed_at, last_sitemap_mod
            FROM recipes
            WHERE source_url IN ({placeholders})
        """
        own_connection = connection is None
        conn = connection or get_connection(self.database_path)
        try:
            rows = conn.execute(query, tuple(urls)).fetchall()
            return {row["source_url"]: dict(row) for row in rows}
        finally:
            if own_connection:
                conn.close()

    def get_crawl_state(
        self, urls: list[str], connection: sqlite3.Connection | None = None
    ) -> dict[str, dict[str, Any]]:
        if not urls:
            return {}

        expanded_urls: list[str] = []
        for url in urls:
            expanded_urls.extend(_url_variants(url))
        deduped_urls = list(dict.fromkeys(expanded_urls))
        if not deduped_urls:
            return {}

        placeholders = ",".join("?" for _ in deduped_urls)
        query = f"""
            SELECT
                source_url,
                canonical_url,
                sitemap_url,
                sitemap_lastmod,
                last_fetched_at,
                last_parsed_at,
                content_hash,
                index_status,
                last_error,
                fetch_count,
                parse_count,
                skip_count,
                updated_at
            FROM crawl_state
            WHERE source_url IN ({placeholders})
        """
        own_connection = connection is None
        conn = connection or get_connection(self.database_path)
        try:
            rows = conn.execute(query, tuple(deduped_urls)).fetchall()
            by_source = {row["source_url"]: dict(row) for row in rows}
            resolved: dict[str, dict[str, Any]] = {}
            for url in urls:
                for candidate in _url_variants(url):
                    row = by_source.get(candidate)
                    if row is not None:
                        resolved[url] = row
                        break
            return resolved
        finally:
            if own_connection:
                conn.close()

    def upsert_crawl_state(
        self,
        *,
        source_url: str,
        canonical_url: str | None = None,
        sitemap_url: str | None = None,
        sitemap_lastmod: str | None = None,
        index_status: str,
        content_hash: str | None = None,
        last_error: str | None = None,
        fetched: bool = False,
        parsed: bool = False,
        skipped: bool = False,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        now_iso = _utc_now_iso()
        own_connection = connection is None
        conn = connection or get_connection(self.database_path)
        try:
            conn.execute(
                """
                INSERT INTO crawl_state (
                    source_url,
                    canonical_url,
                    sitemap_url,
                    sitemap_lastmod,
                    last_fetched_at,
                    last_parsed_at,
                    content_hash,
                    index_status,
                    last_error,
                    fetch_count,
                    parse_count,
                    skip_count,
                    updated_at
                )
                VALUES (
                    :source_url,
                    :canonical_url,
                    :sitemap_url,
                    :sitemap_lastmod,
                    :last_fetched_at,
                    :last_parsed_at,
                    :content_hash,
                    :index_status,
                    :last_error,
                    :fetch_count,
                    :parse_count,
                    :skip_count,
                    :updated_at
                )
                ON CONFLICT(source_url) DO UPDATE SET
                    canonical_url = excluded.canonical_url,
                    sitemap_url = COALESCE(excluded.sitemap_url, crawl_state.sitemap_url),
                    sitemap_lastmod = COALESCE(excluded.sitemap_lastmod, crawl_state.sitemap_lastmod),
                    last_fetched_at = COALESCE(excluded.last_fetched_at, crawl_state.last_fetched_at),
                    last_parsed_at = COALESCE(excluded.last_parsed_at, crawl_state.last_parsed_at),
                    content_hash = COALESCE(excluded.content_hash, crawl_state.content_hash),
                    index_status = excluded.index_status,
                    last_error = excluded.last_error,
                    fetch_count = crawl_state.fetch_count + excluded.fetch_count,
                    parse_count = crawl_state.parse_count + excluded.parse_count,
                    skip_count = crawl_state.skip_count + excluded.skip_count,
                    updated_at = excluded.updated_at
                """,
                {
                    "source_url": source_url,
                    "canonical_url": canonical_url or source_url,
                    "sitemap_url": sitemap_url,
                    "sitemap_lastmod": sitemap_lastmod,
                    "last_fetched_at": now_iso if fetched else None,
                    "last_parsed_at": now_iso if parsed else None,
                    "content_hash": content_hash,
                    "index_status": index_status,
                    "last_error": last_error,
                    "fetch_count": 1 if fetched else 0,
                    "parse_count": 1 if parsed else 0,
                    "skip_count": 1 if skipped else 0,
                    "updated_at": now_iso,
                },
            )
            if own_connection:
                conn.commit()
        finally:
            if own_connection:
                conn.close()

    def set_favorite(
        self,
        recipe_id: int,
        note: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        now_iso = _utc_now_iso()
        own_connection = connection is None
        conn = connection or get_connection(self.database_path)
        try:
            conn.execute(
                """
                INSERT INTO favorites (recipe_id, note, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(recipe_id) DO UPDATE SET
                    note = COALESCE(excluded.note, favorites.note),
                    updated_at = excluded.updated_at
                """,
                (recipe_id, note, now_iso),
            )
            if own_connection:
                conn.commit()
        finally:
            if own_connection:
                conn.close()

    def remove_favorite(
        self, recipe_id: int, connection: sqlite3.Connection | None = None
    ) -> None:
        own_connection = connection is None
        conn = connection or get_connection(self.database_path)
        try:
            conn.execute("DELETE FROM favorites WHERE recipe_id = ?", (recipe_id,))
            if own_connection:
                conn.commit()
        finally:
            if own_connection:
                conn.close()

    def update_favorite_note(
        self,
        recipe_id: int,
        note: str | None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        now_iso = _utc_now_iso()
        own_connection = connection is None
        conn = connection or get_connection(self.database_path)
        try:
            conn.execute(
                """
                INSERT INTO favorites (recipe_id, note, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(recipe_id) DO UPDATE SET
                    note = excluded.note,
                    updated_at = excluded.updated_at
                """,
                (recipe_id, note, now_iso),
            )
            if own_connection:
                conn.commit()
        finally:
            if own_connection:
                conn.close()

    def get_favorite(
        self, recipe_id: int, connection: sqlite3.Connection | None = None
    ) -> dict[str, Any] | None:
        own_connection = connection is None
        conn = connection or get_connection(self.database_path)
        try:
            row = conn.execute(
                """
                SELECT recipe_id, note, created_at, updated_at
                FROM favorites
                WHERE recipe_id = ?
                """,
                (recipe_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            if own_connection:
                conn.close()

    def list_favorites(self, limit: int = 200) -> list[dict[str, Any]]:
        with get_connection(self.database_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    r.id,
                    r.title,
                    r.intro,
                    r.image_url,
                    r.source_url,
                    r.last_indexed_at,
                    f.note,
                    f.created_at AS favorite_created_at,
                    f.updated_at AS favorite_updated_at
                FROM favorites f
                JOIN recipes r ON r.id = f.recipe_id
                ORDER BY f.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        result = [dict(row) for row in rows]
        for item in result:
            item["is_stale"] = _is_stale(item.get("last_indexed_at"), self.stale_days)
        return result

    def get_index_diagnostics(self) -> dict[str, Any]:
        with get_connection(self.database_path) as conn:
            total_recipes_row = conn.execute(
                "SELECT COUNT(*) AS total FROM recipes"
            ).fetchone()
            total_favorites_row = conn.execute(
                "SELECT COUNT(*) AS total FROM favorites"
            ).fetchone()
            total_crawl_state_row = conn.execute(
                "SELECT COUNT(*) AS total FROM crawl_state"
            ).fetchone()
            latest_indexed_row = conn.execute(
                "SELECT MAX(last_indexed_at) AS last_indexed_at FROM recipes"
            ).fetchone()
            stale_row = conn.execute(
                """
                SELECT COUNT(*) AS stale
                FROM recipes
                WHERE last_indexed_at IS NULL
                   OR datetime(last_indexed_at) < datetime('now', ?)
                """,
                (f"-{self.stale_days} days",),
            ).fetchone()
            status_rows = conn.execute(
                """
                SELECT index_status, COUNT(*) AS count
                FROM crawl_state
                GROUP BY index_status
                ORDER BY index_status
                """
            ).fetchall()
            indexed_without_recipe_row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM crawl_state cs
                LEFT JOIN recipes r ON r.source_url = cs.source_url
                WHERE cs.index_status = 'indexed' AND r.id IS NULL
                """
            ).fetchone()
            recipe_without_state_row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM recipes r
                LEFT JOIN crawl_state cs ON cs.source_url = r.source_url
                WHERE cs.source_url IS NULL
                """
            ).fetchone()
            recent_failures_rows = conn.execute(
                """
                SELECT
                    source_url,
                    index_status,
                    last_error,
                    last_fetched_at,
                    updated_at
                FROM crawl_state
                WHERE index_status IN ('fetch_failed', 'parse_failed')
                   OR (last_error IS NOT NULL AND trim(last_error) <> '')
                ORDER BY updated_at DESC
                LIMIT 20
                """
            ).fetchall()

        total_recipes = int(total_recipes_row["total"]) if total_recipes_row else 0
        total_favorites = int(total_favorites_row["total"]) if total_favorites_row else 0
        total_crawl_state = (
            int(total_crawl_state_row["total"]) if total_crawl_state_row else 0
        )
        status_breakdown = {row["index_status"]: int(row["count"]) for row in status_rows}
        indexed_state_total = status_breakdown.get("indexed", 0)
        non_recipe_total = status_breakdown.get("non_recipe", 0)
        disallowed_total = status_breakdown.get("disallowed", 0)
        fetch_failed_total = status_breakdown.get("fetch_failed", 0)
        parse_failed_total = status_breakdown.get("parse_failed", 0)
        pending_total = status_breakdown.get("new", 0)
        coverage_percent = (
            round((indexed_state_total / total_crawl_state) * 100, 2)
            if total_crawl_state > 0
            else 0.0
        )

        return {
            "total_recipes": total_recipes,
            "total_favorites": total_favorites,
            "total_crawl_state": total_crawl_state,
            "last_indexed_at": latest_indexed_row["last_indexed_at"]
            if latest_indexed_row
            else None,
            "stale_recipes": int(stale_row["stale"]) if stale_row else 0,
            "status_breakdown": status_breakdown,
            "indexed_state_total": indexed_state_total,
            "non_recipe_state_total": non_recipe_total,
            "disallowed_state_total": disallowed_total,
            "fetch_failed_state_total": fetch_failed_total,
            "parse_failed_state_total": parse_failed_total,
            "pending_state_total": pending_total,
            "coverage_percent": coverage_percent,
            "indexed_without_recipe_total": int(indexed_without_recipe_row["total"])
            if indexed_without_recipe_row
            else 0,
            "recipe_without_state_total": int(recipe_without_state_row["total"])
            if recipe_without_state_row
            else 0,
            "recent_failures": [dict(row) for row in recent_failures_rows],
        }
