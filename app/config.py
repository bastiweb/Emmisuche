from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv


def _parse_csv(raw: str | None, default: Iterable[str] = ()) -> list[str]:
    if raw is None:
        return [item.strip() for item in default if item.strip()]
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_int_csv(raw: str | None, default: Iterable[int] = ()) -> list[int]:
    if raw is None:
        return [int(item) for item in default]
    values: list[int] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        values.append(int(item))
    return values


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    log_level: str
    log_json: bool
    host: str
    port: int
    database_path: Path
    sitemap_index_url: str
    allowed_domain: str
    crawler_user_agent: str
    crawler_timeout_seconds: float
    crawler_delay_seconds: float
    crawler_rate_limit_per_minute: float
    crawler_max_retries: int
    crawler_retry_backoff_base_seconds: float
    crawler_retry_backoff_max_seconds: float
    crawler_retry_jitter_seconds: float
    crawler_retry_status_codes: list[int]
    crawler_max_pages: int
    crawler_stale_days: int
    crawler_include_sitemap_keywords: list[str]
    crawler_include_url_keywords: list[str]
    crawler_allow_non_https: bool
    results_per_page: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    project_root = Path(__file__).resolve().parent.parent
    default_db = project_root / "data" / "recipes.db"

    return Settings(
        app_name=os.getenv("APP_NAME", "Emmi Recipe Search"),
        environment=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_json=_parse_bool(os.getenv("LOG_JSON"), default=True),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        database_path=Path(os.getenv("DATABASE_PATH", str(default_db))).resolve(),
        sitemap_index_url=os.getenv(
            "SITEMAP_INDEX_URL", "https://emmikochteinfach.de/sitemap_index.xml"
        ),
        allowed_domain=os.getenv("ALLOWED_DOMAIN", "emmikochteinfach.de").lower(),
        crawler_user_agent=os.getenv(
            "CRAWLER_USER_AGENT",
            "EmmiRecipeSearchBot/1.0 (+personal-local-use; respectful-crawl)",
        ),
        crawler_timeout_seconds=float(os.getenv("CRAWLER_TIMEOUT_SECONDS", "20")),
        crawler_delay_seconds=float(os.getenv("CRAWLER_DELAY_SECONDS", "1.0")),
        crawler_rate_limit_per_minute=float(
            os.getenv("CRAWLER_RATE_LIMIT_PER_MINUTE", "0")
        ),
        crawler_max_retries=int(os.getenv("CRAWLER_MAX_RETRIES", "3")),
        crawler_retry_backoff_base_seconds=float(
            os.getenv("CRAWLER_RETRY_BACKOFF_BASE_SECONDS", "1.0")
        ),
        crawler_retry_backoff_max_seconds=float(
            os.getenv("CRAWLER_RETRY_BACKOFF_MAX_SECONDS", "16.0")
        ),
        crawler_retry_jitter_seconds=float(
            os.getenv("CRAWLER_RETRY_JITTER_SECONDS", "0.5")
        ),
        crawler_retry_status_codes=_parse_int_csv(
            os.getenv("CRAWLER_RETRY_STATUS_CODES"),
            default=(429, 500, 502, 503, 504),
        ),
        crawler_max_pages=int(os.getenv("CRAWLER_MAX_PAGES", "0")),
        crawler_stale_days=int(os.getenv("CRAWLER_STALE_DAYS", "30")),
        crawler_include_sitemap_keywords=_parse_csv(
            os.getenv("CRAWLER_INCLUDE_SITEMAP_KEYWORDS"),
            default=("post-sitemap", "recipe-sitemap"),
        ),
        crawler_include_url_keywords=_parse_csv(
            os.getenv("CRAWLER_INCLUDE_URL_KEYWORDS"), default=()
        ),
        crawler_allow_non_https=_parse_bool(
            os.getenv("CRAWLER_ALLOW_NON_HTTPS"), default=False
        ),
        results_per_page=int(os.getenv("RESULTS_PER_PAGE", "10")),
    )
