from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
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


def _build_test_client(temp_db_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_PATH", str(temp_db_path))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_JSON", "false")
    monkeypatch.setenv("PORT", "8000")
    get_settings.cache_clear()

    # Reload app module so global settings pick up test env values.
    import app.main as main_module

    reloaded_main = importlib.reload(main_module)
    return TestClient(reloaded_main.app)


def test_admin_status_html_page_renders(temp_db_path: Path, monkeypatch) -> None:
    repo = RecipeRepository(temp_db_path)
    repo.upsert_recipe(_recipe("https://example.com/rezept-a", "Rezept A"))
    repo.upsert_crawl_state(
        source_url="https://example.com/rezept-a",
        index_status="indexed",
        fetched=True,
        parsed=True,
    )

    with _build_test_client(temp_db_path, monkeypatch) as client:
        response = client.get("/admin")
    get_settings.cache_clear()
    assert response.status_code == 200
    assert "Index-Diagnose" in response.text
    assert "Status-Verteilung" in response.text


def test_favorite_routes_support_next_redirect_and_note_updates(
    temp_db_path: Path, monkeypatch
) -> None:
    repo = RecipeRepository(temp_db_path)
    repo.upsert_recipe(_recipe("https://example.com/rezept-fav", "Rezept Favorit"))
    recipe_id = int(repo.list_recent(limit=1)[0]["id"])

    with _build_test_client(temp_db_path, monkeypatch) as client:
        add_response = client.post(
            f"/recipes/{recipe_id}/favorite",
            data={"action": "add", "note": "Startnotiz", "next": "/favorites"},
            follow_redirects=False,
        )
        assert add_response.status_code == 303
        assert add_response.headers["location"] == "/favorites"

        update_note_response = client.post(
            f"/recipes/{recipe_id}/favorite-note",
            data={"note": "Aktualisierte Notiz", "next": "/favorites"},
            follow_redirects=False,
        )
        assert update_note_response.status_code == 303
        assert update_note_response.headers["location"] == "/favorites"

        remove_response = client.post(
            f"/recipes/{recipe_id}/favorite",
            data={"action": "remove", "next": "/favorites"},
            follow_redirects=False,
        )
        assert remove_response.status_code == 303
        assert remove_response.headers["location"] == "/favorites"
    get_settings.cache_clear()

    detail = repo.get_recipe_by_id(recipe_id)
    assert detail is not None
    assert detail["is_favorite"] is False
    assert detail["favorite_note"] is None


def test_favorite_next_redirect_rejects_external_urls(
    temp_db_path: Path, monkeypatch
) -> None:
    repo = RecipeRepository(temp_db_path)
    repo.upsert_recipe(_recipe("https://example.com/rezept-safe", "Rezept Sicher"))
    recipe_id = int(repo.list_recent(limit=1)[0]["id"])

    with _build_test_client(temp_db_path, monkeypatch) as client:
        response = client.post(
            f"/recipes/{recipe_id}/favorite",
            data={
                "action": "add",
                "next": "https://malicious.example/redirect",
            },
            follow_redirects=False,
        )
    get_settings.cache_clear()
    assert response.status_code == 303
    assert response.headers["location"] == f"/recipes/{recipe_id}"
