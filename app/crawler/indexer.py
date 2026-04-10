from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from urllib import robotparser
from urllib.parse import urlparse

from app.config import Settings
from app.crawler.client import CrawlError, PoliteHttpClient
from app.crawler.parser import RecipeParser
from app.crawler.sitemap import discover_sitemap_urls
from app.models import IndexingStats, SitemapUrlEntry
from app.storage import RecipeRepository


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class RecipeIndexer:
    def __init__(
        self,
        settings: Settings,
        repository: RecipeRepository,
        parser: RecipeParser | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.parser = parser or RecipeParser()
        self.logger = logger or logging.getLogger(__name__)

    def _load_robots_parser(self, client: PoliteHttpClient) -> robotparser.RobotFileParser | None:
        parsed_sitemap = urlparse(self.settings.sitemap_index_url)
        scheme = parsed_sitemap.scheme or "https"
        robots_url = f"{scheme}://{self.settings.allowed_domain}/robots.txt"

        parser = robotparser.RobotFileParser()
        try:
            robots_txt = client.get_text(robots_url)
        except Exception as exc:
            self.logger.warning(
                "crawl.robots_unavailable",
                extra={
                    "event": "crawl.robots_unavailable",
                    "robots_url": robots_url,
                    "error": str(exc),
                },
            )
            return None

        parser.parse(robots_txt.splitlines())
        crawl_delay = parser.crawl_delay(self.settings.crawler_user_agent)
        if crawl_delay is None:
            crawl_delay = parser.crawl_delay("*")
        if crawl_delay:
            client.delay_seconds = max(client.delay_seconds, float(crawl_delay))
            self.logger.info(
                "crawl.robots_delay_applied",
                extra={
                    "event": "crawl.robots_delay_applied",
                    "crawl_delay_seconds": float(crawl_delay),
                    "effective_delay_seconds": client.delay_seconds,
                },
            )
        else:
            self.logger.info(
                "crawl.robots_loaded",
                extra={"event": "crawl.robots_loaded", "robots_url": robots_url},
            )
        return parser

    def _should_crawl_url(
        self,
        *,
        mode: str,
        entry: SitemapUrlEntry,
        existing_meta: dict[str, str | None] | None,
        stale_days: int,
    ) -> bool:
        if mode == "reindex-all":
            return True

        if existing_meta is None:
            return True

        if mode == "initial":
            return False

        # reindex mode: changed sitemap timestamps and stale/missing content.
        indexed_at = _parse_iso_datetime(
            existing_meta.get("last_indexed_at") or existing_meta.get("last_crawled_at")
        )
        cutoff = datetime.now(UTC) - timedelta(days=stale_days)
        if indexed_at is None or indexed_at < cutoff:
            return True

        sitemap_lastmod = _parse_iso_datetime(entry.lastmod)
        stored_lastmod = _parse_iso_datetime(existing_meta.get("last_sitemap_mod"))
        if sitemap_lastmod and (stored_lastmod is None or sitemap_lastmod > stored_lastmod):
            return True

        return False

    def run(
        self,
        *,
        mode: str = "initial",
        limit: int | None = None,
        stale_days: int | None = None,
    ) -> IndexingStats:
        if mode not in {"initial", "reindex", "reindex-all"}:
            raise ValueError(f"Unsupported mode: {mode}")

        stats = IndexingStats()
        stale_days = stale_days if stale_days is not None else self.settings.crawler_stale_days

        self.logger.info(
            "index.run_start",
            extra={
                "event": "index.run_start",
                "mode": mode,
                "stale_days": stale_days,
                "limit": limit,
            },
        )
        with PoliteHttpClient(
            user_agent=self.settings.crawler_user_agent,
            timeout_seconds=self.settings.crawler_timeout_seconds,
            delay_seconds=self.settings.crawler_delay_seconds,
            rate_limit_per_minute=self.settings.crawler_rate_limit_per_minute,
            max_retries=self.settings.crawler_max_retries,
            retry_backoff_base_seconds=self.settings.crawler_retry_backoff_base_seconds,
            retry_backoff_max_seconds=self.settings.crawler_retry_backoff_max_seconds,
            retry_jitter_seconds=self.settings.crawler_retry_jitter_seconds,
            retry_status_codes=self.settings.crawler_retry_status_codes,
            logger=self.logger,
        ) as client:
            robots = self._load_robots_parser(client)

            sitemap_entries = discover_sitemap_urls(
                sitemap_index_url=self.settings.sitemap_index_url,
                allowed_domain=self.settings.allowed_domain,
                allow_non_https=self.settings.crawler_allow_non_https,
                include_sitemap_keywords=self.settings.crawler_include_sitemap_keywords,
                include_url_keywords=self.settings.crawler_include_url_keywords,
                fetch_text=client.get_text,
                logger=self.logger,
            )
            stats.discovered_urls = len(sitemap_entries)

            if self.settings.crawler_max_pages > 0:
                sitemap_entries = sitemap_entries[: self.settings.crawler_max_pages]
            if limit and limit > 0:
                sitemap_entries = sitemap_entries[:limit]

            with self.repository.transaction() as conn:
                existing = self.repository.get_url_metadata(
                    [entry.url for entry in sitemap_entries], connection=conn
                )

                targets: list[SitemapUrlEntry] = []
                for entry in sitemap_entries:
                    meta = existing.get(entry.url)
                    should_crawl = self._should_crawl_url(
                        mode=mode,
                        entry=entry,
                        existing_meta=meta,
                        stale_days=stale_days,
                    )
                    if should_crawl:
                        targets.append(entry)
                    else:
                        stats.skipped_existing += 1

                stats.scheduled_urls = len(targets)
                self.logger.info(
                    "index.plan",
                    extra={
                        "event": "index.plan",
                        "discovered_urls": stats.discovered_urls,
                        "scheduled_urls": stats.scheduled_urls,
                        "skipped_existing": stats.skipped_existing,
                    },
                )

                for index, entry in enumerate(targets, start=1):
                    if robots and not robots.can_fetch(self.settings.crawler_user_agent, entry.url):
                        stats.skipped_disallowed += 1
                        self.logger.info(
                            "crawl.disallowed",
                            extra={
                                "event": "crawl.disallowed",
                                "position": index,
                                "total": len(targets),
                                "url": entry.url,
                            },
                        )
                        continue

                    try:
                        html = client.get_text(entry.url)
                        stats.crawled_urls += 1
                    except CrawlError as exc:
                        stats.failures += 1
                        self.logger.warning(
                            "crawl.failed",
                            extra={
                                "event": "crawl.failed",
                                "position": index,
                                "total": len(targets),
                                "url": entry.url,
                                "error": str(exc),
                            },
                        )
                        continue

                    parse_result = self.parser.parse(
                        html=html,
                        source_url=entry.url,
                        sitemap_lastmod=entry.lastmod,
                    )
                    self.logger.info(
                        "parse.result",
                        extra={
                            "event": "parse.result",
                            "position": index,
                            "total": len(targets),
                            "url": entry.url,
                            "is_recipe": parse_result.recipe is not None,
                        },
                    )
                    if parse_result.recipe is None:
                        stats.skipped_non_recipe += 1
                        self.logger.debug(
                            "parse.skip_non_recipe",
                            extra={
                                "event": "parse.skip_non_recipe",
                                "position": index,
                                "total": len(targets),
                                "url": entry.url,
                            },
                        )
                        continue

                    self.repository.upsert_recipe(parse_result.recipe, connection=conn)
                    stats.indexed_recipes += 1
                    self.logger.info(
                        "index.upserted",
                        extra={
                            "event": "index.upserted",
                            "position": index,
                            "total": len(targets),
                            "url": entry.url,
                            "ingredients_count": len(parse_result.recipe.ingredients),
                            "instructions_count": len(parse_result.recipe.instructions),
                        },
                    )

        self.logger.info(
            "index.run_finished",
            extra={
                "event": "index.run_finished",
                "mode": mode,
                "discovered_urls": stats.discovered_urls,
                "scheduled_urls": stats.scheduled_urls,
                "crawled_urls": stats.crawled_urls,
                "indexed_recipes": stats.indexed_recipes,
                "skipped_non_recipe": stats.skipped_non_recipe,
                "skipped_disallowed": stats.skipped_disallowed,
                "failures": stats.failures,
            },
        )
        return stats
