from __future__ import annotations

from pathlib import Path

from app.models import ParsedRecipe
from app.storage import RecipeRepository


def _recipe(source_url: str, title: str) -> ParsedRecipe:
    return ParsedRecipe(
        source_url=source_url,
        title=title,
        intro="Kurzbeschreibung",
        ingredients=["Zutat 1"],
        instructions=["Schritt 1"],
        categories=["Test"],
    )


def test_get_crawl_state_matches_trailing_slash_variants(temp_db_path: Path) -> None:
    repo = RecipeRepository(temp_db_path)
    repo.upsert_crawl_state(
        source_url="https://example.com/rezept-a",
        index_status="indexed",
        fetched=True,
        parsed=True,
    )

    state = repo.get_crawl_state(["https://example.com/rezept-a/"])
    assert "https://example.com/rezept-a/" in state
    assert state["https://example.com/rezept-a/"]["index_status"] == "indexed"


def test_index_diagnostics_reports_consistency_and_failures(temp_db_path: Path) -> None:
    repo = RecipeRepository(temp_db_path)

    repo.upsert_recipe(_recipe("https://example.com/rezept-a", "Rezept A"))
    repo.upsert_recipe(_recipe("https://example.com/rezept-ohne-state", "Rezept B"))

    repo.upsert_crawl_state(
        source_url="https://example.com/rezept-a",
        index_status="indexed",
        fetched=True,
        parsed=True,
    )
    repo.upsert_crawl_state(
        source_url="https://example.com/rezept-fehler",
        index_status="fetch_failed",
        last_error="Timeout",
        fetched=True,
    )
    repo.upsert_crawl_state(
        source_url="https://example.com/rezept-ohne-row",
        index_status="indexed",
        fetched=True,
        parsed=True,
    )

    diagnostics = repo.get_index_diagnostics()
    assert diagnostics["total_recipes"] == 2
    assert diagnostics["total_crawl_state"] == 3
    assert diagnostics["indexed_state_total"] == 2
    assert diagnostics["fetch_failed_state_total"] == 1
    assert diagnostics["indexed_without_recipe_total"] == 1
    assert diagnostics["recipe_without_state_total"] == 1
    assert diagnostics["recent_failures"]
    assert diagnostics["recent_failures"][0]["source_url"] == "https://example.com/rezept-fehler"

