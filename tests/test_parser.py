from __future__ import annotations

from pathlib import Path

from app.crawler.parser import RecipeParser


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_parser_extracts_recipe_fields(fixture_dir: Path) -> None:
    parser = RecipeParser()
    html = _read_text(fixture_dir / "sample_recipe_page.html")

    result = parser.parse(
        html=html,
        source_url="https://emmikochteinfach.de/lachs-pasta-mit-paprika/",
        sitemap_lastmod="2026-03-20T10:00:00+00:00",
    )

    assert result.is_recipe_page is True
    assert result.recipe is not None
    recipe = result.recipe

    assert recipe.title == "Lachs Pasta mit Paprika"
    assert recipe.intro == "Schnelles Rezept mit cremiger Sauce."
    assert recipe.image_url == "https://emmikochteinfach.de/wp-content/uploads/lachs-pasta.jpg"
    assert recipe.prep_time == "10 min"
    assert recipe.cook_time == "20 min"
    assert recipe.total_time == "30 min"
    assert recipe.servings == "2 Portionen"
    assert "250 g Pasta" in recipe.ingredients
    assert any("anbraten" in step for step in recipe.instructions)
    assert recipe.nutrition_summary is not None
    assert "calories: 560 kcal" in recipe.nutrition_summary.lower()
    assert "Pasta" in recipe.categories
    assert recipe.last_sitemap_mod == "2026-03-20T10:00:00+00:00"


def test_parser_skips_non_recipe_pages(fixture_dir: Path) -> None:
    parser = RecipeParser()
    html = _read_text(fixture_dir / "sample_non_recipe_page.html")

    result = parser.parse(
        html=html,
        source_url="https://emmikochteinfach.de/so-salzt-du-richtig/",
    )

    assert result.is_recipe_page is False
    assert result.recipe is None

