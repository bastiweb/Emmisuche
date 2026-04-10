from __future__ import annotations

from pathlib import Path

from app.crawler.parser import RecipeParser
from app.search.service import SearchService
from app.storage import RecipeRepository


def test_fixture_parse_index_and_search_flow(
    fixture_dir: Path,
    temp_db_path: Path,
) -> None:
    parser = RecipeParser()
    repo = RecipeRepository(temp_db_path)
    search = SearchService(temp_db_path)

    html = (fixture_dir / "sample_recipe_page.html").read_text(encoding="utf-8")
    parse_result = parser.parse(
        html=html,
        source_url="https://emmikochteinfach.de/lachs-pasta-mit-paprika/",
        sitemap_lastmod="2026-04-01T12:00:00+00:00",
    )
    assert parse_result.recipe is not None

    repo.upsert_recipe(parse_result.recipe)

    results, total = search.search(query="Paprika", page=1, per_page=10)
    assert total == 1
    result = results[0]
    assert result.title == "Lachs Pasta mit Paprika"

    recipe = repo.get_recipe_by_id(result.id)
    assert recipe is not None
    assert recipe["source_url"] == "https://emmikochteinfach.de/lachs-pasta-mit-paprika/"
    assert recipe["ingredients"]
    assert recipe["instructions"]

