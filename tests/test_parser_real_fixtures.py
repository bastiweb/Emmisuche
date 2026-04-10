from __future__ import annotations

from pathlib import Path

import pytest

from app.crawler.parser import RecipeParser

NOISE_TERMS = [
    "newsletter",
    "kommentar",
    "kommentare",
    "beliebte rezepte",
    "author",
    "autor",
    "datenschutz",
    "impressum",
]


@pytest.mark.parametrize(
    ("fixture_name", "source_url", "expected_title_fragment", "min_ingredients", "min_steps"),
    [
        (
            "real_pancakes.html",
            "https://emmikochteinfach.de/pancakes-rezept-das-original/",
            "Pancakes",
            8,
            6,
        ),
        (
            "real_risotto.html",
            "https://emmikochteinfach.de/risotto-rezept-klassisch/",
            "Risotto",
            7,
            6,
        ),
    ],
)
def test_parser_real_recipe_fixture_quality(
    fixture_dir: Path,
    fixture_name: str,
    source_url: str,
    expected_title_fragment: str,
    min_ingredients: int,
    min_steps: int,
) -> None:
    parser = RecipeParser()
    html = (fixture_dir / fixture_name).read_text(encoding="utf-8")

    result = parser.parse(html=html, source_url=source_url)
    assert result.is_recipe_page is True
    assert result.recipe is not None

    recipe = result.recipe
    assert expected_title_fragment.lower() in recipe.title.lower()
    assert recipe.intro is not None and len(recipe.intro) > 30
    assert recipe.prep_time
    assert recipe.cook_time
    assert recipe.total_time
    assert recipe.servings
    assert len(recipe.ingredients) >= min_ingredients
    assert len(recipe.instructions) >= min_steps
    assert recipe.nutrition_summary
    assert "calories" in recipe.nutrition_summary.lower()

    combined_text = " ".join(
        [recipe.intro, *recipe.ingredients, *recipe.instructions]
    ).lower()
    for noise in NOISE_TERMS:
        assert noise not in combined_text

