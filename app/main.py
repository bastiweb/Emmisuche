from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
    last_indexed_at = repository.get_latest_indexed_at()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "query": query,
            "results": results,
            "pagination": pagination,
            "total_recipes": total_recipes,
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
