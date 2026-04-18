from __future__ import annotations

from pathlib import Path

from app.models import ParsedRecipe
from app.storage import RecipeRepository


def _recipe(source_url: str, title: str) -> ParsedRecipe:
    return ParsedRecipe(
        source_url=source_url,
        title=title,
        intro="Test intro",
        ingredients=["1 Zutat"],
        instructions=["1 Schritt"],
        categories=["Test"],
    )


def test_favorite_create_update_delete_and_note_persistence(temp_db_path: Path) -> None:
    repo = RecipeRepository(temp_db_path)
    repo.upsert_recipe(_recipe("https://example.com/rezept-a/", "Rezept A"))

    recipe = repo.list_recent(limit=1)[0]
    recipe_id = int(recipe["id"])

    repo.set_favorite(recipe_id, note="Mehr Knoblauch")
    detail = repo.get_recipe_by_id(recipe_id)
    assert detail is not None
    assert detail["is_favorite"] is True
    assert detail["favorite_note"] == "Mehr Knoblauch"

    repo.update_favorite_note(recipe_id, "10 Minuten länger backen")
    detail = repo.get_recipe_by_id(recipe_id)
    assert detail is not None
    assert detail["favorite_note"] == "10 Minuten länger backen"

    favorites = repo.list_favorites()
    assert len(favorites) == 1
    assert favorites[0]["note"] == "10 Minuten länger backen"

    repo.remove_favorite(recipe_id)
    detail = repo.get_recipe_by_id(recipe_id)
    assert detail is not None
    assert detail["is_favorite"] is False
    assert detail["favorite_note"] is None

