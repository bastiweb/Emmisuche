from __future__ import annotations

from pathlib import Path

from app.models import ParsedRecipe
from app.search.service import SearchService
from app.storage import RecipeRepository


def _recipe(
    *,
    source_url: str,
    title: str,
    ingredients: list[str],
    instructions: list[str],
    intro: str = "",
) -> ParsedRecipe:
    return ParsedRecipe(
        source_url=source_url,
        title=title,
        intro=intro,
        ingredients=ingredients,
        instructions=instructions,
        categories=["Test"],
        searchable_text=" ".join([title, intro, " ".join(ingredients), " ".join(instructions)]),
    )


def test_search_prefers_title_matches(temp_db_path: Path) -> None:
    repo = RecipeRepository(temp_db_path)
    search = SearchService(temp_db_path)

    repo.upsert_recipe(
        _recipe(
            source_url="https://emmikochteinfach.de/paprika-pasta/",
            title="Paprika Pasta",
            ingredients=["Pasta", "Paprika"],
            instructions=["Alles kochen"],
            intro="Schnelles Essen",
        )
    )
    repo.upsert_recipe(
        _recipe(
            source_url="https://emmikochteinfach.de/sahne-pasta/",
            title="Cremige Pasta",
            ingredients=["Pasta", "Paprika", "Sahne"],
            instructions=["Alles köcheln"],
            intro="Paprika steckt nur in der Zutatenliste",
        )
    )

    results, total = search.search(query="Paprika", page=1, per_page=10)
    assert total == 2
    assert results[0].title == "Paprika Pasta"


def test_search_finds_ingredient_terms(temp_db_path: Path) -> None:
    repo = RecipeRepository(temp_db_path)
    search = SearchService(temp_db_path)

    repo.upsert_recipe(
        _recipe(
            source_url="https://emmikochteinfach.de/lachs-pasta/",
            title="Lachs Pasta",
            ingredients=["Lachs", "Pasta", "Zitrone"],
            instructions=["Lachs anbraten", "Pasta kochen"],
        )
    )

    results, total = search.search(query="Lachs", page=1, per_page=10)
    assert total == 1
    assert results[0].title == "Lachs Pasta"
    assert "Lachs" in results[0].snippet


def test_search_ranking_title_then_ingredients_then_instructions(temp_db_path: Path) -> None:
    repo = RecipeRepository(temp_db_path)
    search = SearchService(temp_db_path)

    repo.upsert_recipe(
        _recipe(
            source_url="https://emmikochteinfach.de/paprika-cremesuppe/",
            title="Paprika Cremesuppe",
            ingredients=["Sahne", "Zwiebel"],
            instructions=["Suppe pürieren"],
        )
    )
    repo.upsert_recipe(
        _recipe(
            source_url="https://emmikochteinfach.de/gemuese-suppe/",
            title="Gemüse Suppe",
            ingredients=["Paprika", "Karotte", "Zwiebel"],
            instructions=["Gemüse garen"],
        )
    )
    repo.upsert_recipe(
        _recipe(
            source_url="https://emmikochteinfach.de/tomatensuppe/",
            title="Tomatensuppe",
            ingredients=["Tomate", "Basilikum"],
            instructions=["Paprika fein schneiden und kurz anschwitzen."],
        )
    )

    results, total = search.search(query="Paprika", page=1, per_page=10)
    assert total == 3
    assert [result.title for result in results] == [
        "Paprika Cremesuppe",
        "Gemüse Suppe",
        "Tomatensuppe",
    ]
