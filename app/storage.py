from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

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
                "SELECT * FROM recipes WHERE id = ?",
                (recipe_id,),
            ).fetchone()
        return _row_to_recipe(row, self.stale_days)

    def count_recipes(self) -> int:
        with get_connection(self.database_path) as conn:
            value = conn.execute("SELECT COUNT(*) AS count FROM recipes").fetchone()
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
