from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import Settings
from app.crawler.indexer import RecipeIndexer
from app.models import SitemapUrlEntry
from app.storage import RecipeRepository


def _settings(temp_db_path: Path) -> Settings:
    return Settings(
        app_name="Test",
        environment="test",
        log_level="INFO",
        log_json=False,
        host="127.0.0.1",
        port=8000,
        database_path=temp_db_path,
        sitemap_index_url="https://example.com/sitemap_index.xml",
        allowed_domain="example.com",
        crawler_user_agent="TestBot/1.0",
        crawler_timeout_seconds=10.0,
        crawler_delay_seconds=0.0,
        crawler_rate_limit_per_minute=0.0,
        crawler_max_retries=0,
        crawler_retry_backoff_base_seconds=0.1,
        crawler_retry_backoff_max_seconds=0.1,
        crawler_retry_jitter_seconds=0.0,
        crawler_retry_status_codes=[429, 500],
        crawler_max_pages=0,
        crawler_stale_days=30,
        crawler_min_fetch_interval_hours=6.0,
        crawler_failure_retry_hours=12.0,
        crawler_non_recipe_recheck_days=90,
        crawler_disallowed_recheck_days=7,
        crawler_include_sitemap_keywords=[],
        crawler_include_url_keywords=[],
        crawler_allow_non_https=False,
        results_per_page=10,
    )


def test_reindex_skips_fresh_unchanged_cached_entries(temp_db_path: Path) -> None:
    settings = _settings(temp_db_path)
    indexer = RecipeIndexer(settings=settings, repository=RecipeRepository(temp_db_path))

    entry = SitemapUrlEntry(
        url="https://example.com/recipe-a/",
        lastmod="2026-04-10T00:00:00+00:00",
    )
    state = {
        "index_status": "indexed",
        "last_parsed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sitemap_lastmod": "2026-04-10T00:00:00+00:00",
    }

    should_fetch = indexer._should_fetch_url(  # noqa: SLF001 - explicit behavior test
        mode="reindex",
        entry=entry,
        crawl_state=state,
        stale_days=30,
    )
    assert should_fetch is False


def test_force_refresh_fetches_even_when_cached(temp_db_path: Path) -> None:
    settings = _settings(temp_db_path)
    indexer = RecipeIndexer(settings=settings, repository=RecipeRepository(temp_db_path))

    entry = SitemapUrlEntry(
        url="https://example.com/recipe-a/",
        lastmod="2026-04-10T00:00:00+00:00",
    )
    state = {
        "index_status": "indexed",
        "last_parsed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sitemap_lastmod": "2026-04-10T00:00:00+00:00",
    }

    should_fetch = indexer._should_fetch_url(  # noqa: SLF001 - explicit behavior test
        mode="reindex-all",
        entry=entry,
        crawl_state=state,
        stale_days=30,
    )
    assert should_fetch is True


def test_reindex_fetches_when_cached_entry_is_stale(temp_db_path: Path) -> None:
    settings = _settings(temp_db_path)
    indexer = RecipeIndexer(settings=settings, repository=RecipeRepository(temp_db_path))

    stale_time = (datetime.now(UTC) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = SitemapUrlEntry(
        url="https://example.com/recipe-a/",
        lastmod="2026-04-10T00:00:00+00:00",
    )
    state = {
        "index_status": "indexed",
        "last_parsed_at": stale_time,
        "sitemap_lastmod": "2026-04-10T00:00:00+00:00",
    }

    should_fetch = indexer._should_fetch_url(  # noqa: SLF001 - explicit behavior test
        mode="reindex",
        entry=entry,
        crawl_state=state,
        stale_days=30,
    )
    assert should_fetch is True


def test_reindex_respects_failure_retry_cooldown(temp_db_path: Path) -> None:
    settings = _settings(temp_db_path)
    indexer = RecipeIndexer(settings=settings, repository=RecipeRepository(temp_db_path))

    recent_failure = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = SitemapUrlEntry(
        url="https://example.com/recipe-a/",
        lastmod="2026-04-10T00:00:00+00:00",
    )
    state = {
        "index_status": "fetch_failed",
        "last_fetched_at": recent_failure,
        "sitemap_lastmod": "2026-04-10T00:00:00+00:00",
    }

    should_fetch = indexer._should_fetch_url(  # noqa: SLF001 - explicit behavior test
        mode="reindex",
        entry=entry,
        crawl_state=state,
        stale_days=30,
    )
    assert should_fetch is False


def test_reindex_retries_failure_after_cooldown(temp_db_path: Path) -> None:
    settings = _settings(temp_db_path)
    indexer = RecipeIndexer(settings=settings, repository=RecipeRepository(temp_db_path))

    old_failure = (datetime.now(UTC) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = SitemapUrlEntry(
        url="https://example.com/recipe-a/",
        lastmod="2026-04-10T00:00:00+00:00",
    )
    state = {
        "index_status": "fetch_failed",
        "last_fetched_at": old_failure,
        "sitemap_lastmod": "2026-04-10T00:00:00+00:00",
    }

    should_fetch = indexer._should_fetch_url(  # noqa: SLF001 - explicit behavior test
        mode="reindex",
        entry=entry,
        crawl_state=state,
        stale_days=30,
    )
    assert should_fetch is True


def test_reindex_skips_stale_when_recently_fetched(temp_db_path: Path) -> None:
    settings = _settings(temp_db_path)
    indexer = RecipeIndexer(settings=settings, repository=RecipeRepository(temp_db_path))

    stale_parsed = (datetime.now(UTC) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh_fetch = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = SitemapUrlEntry(
        url="https://example.com/recipe-a/",
        lastmod="2026-04-10T00:00:00+00:00",
    )
    state = {
        "index_status": "indexed",
        "last_parsed_at": stale_parsed,
        "last_fetched_at": fresh_fetch,
        "sitemap_lastmod": "2026-04-10T00:00:00+00:00",
    }

    should_fetch = indexer._should_fetch_url(  # noqa: SLF001 - explicit behavior test
        mode="reindex",
        entry=entry,
        crawl_state=state,
        stale_days=30,
    )
    assert should_fetch is False
