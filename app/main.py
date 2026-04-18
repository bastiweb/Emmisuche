from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db import get_connection, init_db
from app.logging_utils import configure_logging
from app.schemas import Pagination
from app.search.service import SearchService
from app.storage import RecipeRepository

settings = get_settings()
configure_logging(settings.log_level, json_logs=settings.log_json)
logger = logging.getLogger(__name__)
project_root = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(project_root / "app" / "templates"))

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory=str(project_root / "app" / "static")), name="static")


def _safe_next_path(next_path: str | None, fallback: str) -> str:
    candidate = (next_path or "").strip()
    if not candidate:
        return fallback
    if not candidate.startswith("/") or candidate.startswith("//"):
        return fallback
    return candidate


@app.on_event("startup")
def startup() -> None:
    connection = get_connection(settings.database_path)
    try:
        init_db(connection)
    finally:
        connection.close()
    logger.info(
        "app.startup",
        extra={"event": "app.startup", "database_path": str(settings.database_path)},
    )


@app.get("/health", response_class=JSONResponse)
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/admin/index-status", response_class=JSONResponse)
def index_status() -> dict[str, object]:
    repository = RecipeRepository(
        settings.database_path, stale_days=settings.crawler_stale_days
    )
    return repository.get_index_diagnostics()


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/status", response_class=HTMLResponse)
def admin_status_page(request: Request) -> HTMLResponse:
    repository = RecipeRepository(
        settings.database_path, stale_days=settings.crawler_stale_days
    )
    diagnostics = repository.get_index_diagnostics()
    return templates.TemplateResponse(
        request=request,
        name="admin_status.html",
        context={"diagnostics": diagnostics, "app_name": settings.app_name},
    )


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    q: str = Query(default="", max_length=250),
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    repository = RecipeRepository(
        settings.database_path, stale_days=settings.crawler_stale_days
    )
    search_service = SearchService(
        settings.database_path, stale_days=settings.crawler_stale_days
    )

    query = q.strip()
    results, total = ([], 0)
    if query:
        results, total = search_service.search(
            query=query,
            page=page,
            per_page=settings.results_per_page,
        )
    pagination = Pagination(page=page, per_page=settings.results_per_page, total=total)
    recent_recipes = repository.list_recent(limit=10) if not query else []
    total_recipes = repository.count_recipes()
    total_favorites = repository.count_favorites()
    last_indexed_at = repository.get_latest_indexed_at()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "query": query,
            "results": results,
            "pagination": pagination,
            "total_recipes": total_recipes,
            "total_favorites": total_favorites,
            "recent_recipes": recent_recipes,
            "last_indexed_at": last_indexed_at,
            "app_name": settings.app_name,
        },
    )


@app.get("/recipes/{recipe_id}", response_class=HTMLResponse)
def recipe_detail(request: Request, recipe_id: int) -> HTMLResponse:
    repository = RecipeRepository(
        settings.database_path, stale_days=settings.crawler_stale_days
    )
    recipe = repository.get_recipe_by_id(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    return templates.TemplateResponse(
        request=request,
        name="recipe_detail.html",
        context={"recipe": recipe, "app_name": settings.app_name},
    )


@app.post("/recipes/{recipe_id}/favorite")
def favorite_toggle(
    recipe_id: int,
    action: str = Form(...),
    note: str = Form(default=""),
    next_path: str = Form(default="", alias="next"),
) -> RedirectResponse:
    repository = RecipeRepository(
        settings.database_path, stale_days=settings.crawler_stale_days
    )
    recipe = repository.get_recipe_by_id(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    if action == "remove":
        repository.remove_favorite(recipe_id)
    elif action == "add":
        repository.set_favorite(recipe_id, note=note.strip() or None)
    else:
        raise HTTPException(status_code=400, detail="Invalid favorite action")

    return RedirectResponse(
        url=_safe_next_path(next_path, f"/recipes/{recipe_id}"), status_code=303
    )


@app.post("/recipes/{recipe_id}/favorite-note")
def favorite_note_update(
    recipe_id: int,
    note: str = Form(default=""),
    next_path: str = Form(default="", alias="next"),
) -> RedirectResponse:
    repository = RecipeRepository(
        settings.database_path, stale_days=settings.crawler_stale_days
    )
    recipe = repository.get_recipe_by_id(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    repository.update_favorite_note(recipe_id, note.strip() or None)
    return RedirectResponse(
        url=_safe_next_path(next_path, f"/recipes/{recipe_id}"), status_code=303
    )


@app.get("/favorites", response_class=HTMLResponse)
def favorites_view(request: Request) -> HTMLResponse:
    repository = RecipeRepository(
        settings.database_path, stale_days=settings.crawler_stale_days
    )
    favorites = repository.list_favorites(limit=500)

    return templates.TemplateResponse(
        request=request,
        name="favorites.html",
        context={
            "favorites": favorites,
            "favorites_count": len(favorites),
            "app_name": settings.app_name,
        },
    )
