from __future__ import annotations

import hashlib
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

    def _should_fetch_url(
        self,
        *,
        mode: str,
        entry: SitemapUrlEntry,
        crawl_state: dict[str, str | None] | None,
        stale_days: int,
    ) -> bool:
        if mode == "reindex-all":
            return True

        if crawl_state is None:
            return True

        now = datetime.now(UTC)
        status = (crawl_state.get("index_status") or "").lower()
        success_statuses = {"indexed", "non_recipe", "disallowed"}
        failure_statuses = {"fetch_failed", "parse_failed"}

        last_fetched_at = _parse_iso_datetime(crawl_state.get("last_fetched_at"))
        last_parsed_at = (
            _parse_iso_datetime(crawl_state.get("last_parsed_at")) or last_fetched_at
        )

        min_fetch_interval_hours = max(
            0.0, self.settings.crawler_min_fetch_interval_hours
        )
        recent_fetch_cutoff = now - timedelta(hours=min_fetch_interval_hours)
        fetched_too_recently = bool(
            last_fetched_at and last_fetched_at >= recent_fetch_cutoff
        )

        failure_retry_hours = max(0.0, self.settings.crawler_failure_retry_hours)
        failure_retry_cutoff = now - timedelta(hours=failure_retry_hours)
        failure_retry_ready = bool(
            last_fetched_at is None or last_fetched_at <= failure_retry_cutoff
        )

        if mode == "initial":
            return status not in success_statuses

        sitemap_lastmod = _parse_iso_datetime(entry.lastmod)
        stored_lastmod = _parse_iso_datetime(crawl_state.get("sitemap_lastmod"))
        sitemap_changed = bool(
            sitemap_lastmod and (stored_lastmod is None or sitemap_lastmod > stored_lastmod)
        )

        if sitemap_changed:
            return True

        if status in failure_statuses:
            return failure_retry_ready

        if status == "indexed":
            cutoff = now - timedelta(days=stale_days)
            is_stale = last_parsed_at is None or last_parsed_at < cutoff
            if not is_stale:
                return False
            return not fetched_too_recently

        if status == "non_recipe":
            cutoff = now - timedelta(
                days=max(1, self.settings.crawler_non_recipe_recheck_days)
            )
            is_stale = last_parsed_at is None or last_parsed_at < cutoff
            if not is_stale:
                return False
            return not fetched_too_recently

        if status == "disallowed":
            cutoff = now - timedelta(
                days=max(1, self.settings.crawler_disallowed_recheck_days)
            )
            is_stale = last_fetched_at is None or last_fetched_at < cutoff
            if not is_stale:
                return False
            return not fetched_too_recently

        if fetched_too_recently:
            return False

        if status in success_statuses:
            return False

        if status == "new":
            return True

        return True

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

            discovery_metrics: dict[str, int] = {}
            sitemap_entries = discover_sitemap_urls(
                sitemap_index_url=self.settings.sitemap_index_url,
                allowed_domain=self.settings.allowed_domain,
                allow_non_https=self.settings.crawler_allow_non_https,
                include_sitemap_keywords=self.settings.crawler_include_sitemap_keywords,
                include_url_keywords=self.settings.crawler_include_url_keywords,
                fetch_text=client.get_text,
                logger=self.logger,
                metrics=discovery_metrics,
            )
            stats.discovered_sitemaps = discovery_metrics.get("discovered_sitemaps", 0)
            stats.discovered_url_entries = discovery_metrics.get("discovered_url_entries", 0)
            stats.candidate_urls = discovery_metrics.get("candidate_urls", 0)
            stats.duplicate_urls = discovery_metrics.get("duplicate_urls", 0)
            stats.discovered_urls = len(sitemap_entries)

            if self.settings.crawler_max_pages > 0:
                sitemap_entries = sitemap_entries[: self.settings.crawler_max_pages]
            if limit and limit > 0:
                sitemap_entries = sitemap_entries[:limit]

            with self.repository.transaction() as conn:
                crawl_state = self.repository.get_crawl_state(
                    [entry.url for entry in sitemap_entries], connection=conn
                )

                targets: list[SitemapUrlEntry] = []
                for entry in sitemap_entries:
                    state = crawl_state.get(entry.url)
                    should_fetch = self._should_fetch_url(
                        mode=mode,
                        entry=entry,
                        crawl_state=state,
                        stale_days=stale_days,
                    )
                    if should_fetch:
                        targets.append(entry)
                    else:
                        stats.skipped_existing += 1
                        self.repository.upsert_crawl_state(
                            source_url=entry.url,
                            canonical_url=entry.url,
                            sitemap_url=entry.sitemap_url,
                            sitemap_lastmod=entry.lastmod,
                            index_status=(state or {}).get("index_status", "cached_skip"),
                            skipped=True,
                            connection=conn,
                        )

                stats.scheduled_urls = len(targets)
                self.logger.info(
                    "index.plan",
                    extra={
                        "event": "index.plan",
                        "discovered_sitemaps": stats.discovered_sitemaps,
                        "discovered_url_entries": stats.discovered_url_entries,
                        "candidate_urls": stats.candidate_urls,
                        "discovered_urls": stats.discovered_urls,
                        "scheduled_urls": stats.scheduled_urls,
                        "skipped_existing": stats.skipped_existing,
                        "duplicate_urls": stats.duplicate_urls,
                    },
                )

                for index, entry in enumerate(targets, start=1):
                    if robots and not robots.can_fetch(self.settings.crawler_user_agent, entry.url):
                        stats.skipped_disallowed += 1
                        self.repository.upsert_crawl_state(
                            source_url=entry.url,
                            canonical_url=entry.url,
                            sitemap_url=entry.sitemap_url,
                            sitemap_lastmod=entry.lastmod,
                            index_status="disallowed",
                            skipped=True,
                            connection=conn,
                        )
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
                        self.repository.upsert_crawl_state(
                            source_url=entry.url,
                            canonical_url=entry.url,
                            sitemap_url=entry.sitemap_url,
                            sitemap_lastmod=entry.lastmod,
                            index_status="fetch_failed",
                            last_error=str(exc),
                            fetched=True,
                            connection=conn,
                        )
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

                    content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
                    existing_state = crawl_state.get(entry.url) or {}
                    if (
                        mode != "reindex-all"
                        and existing_state.get("content_hash") == content_hash
                        and (existing_state.get("index_status") in {"indexed", "non_recipe"})
                    ):
                        stats.skipped_unchanged += 1
                        self.repository.upsert_crawl_state(
                            source_url=entry.url,
                            canonical_url=entry.url,
                            sitemap_url=entry.sitemap_url,
                            sitemap_lastmod=entry.lastmod,
                            index_status=existing_state.get("index_status", "indexed"),
                            content_hash=content_hash,
                            last_error=None,
                            fetched=True,
                            skipped=True,
                            connection=conn,
                        )
                        continue

                    try:
                        parse_result = self.parser.parse(
                            html=html,
                            source_url=entry.url,
                            sitemap_lastmod=entry.lastmod,
                        )
                    except Exception as exc:
                        stats.failures += 1
                        self.repository.upsert_crawl_state(
                            source_url=entry.url,
                            canonical_url=entry.url,
                            sitemap_url=entry.sitemap_url,
                            sitemap_lastmod=entry.lastmod,
                            index_status="parse_failed",
                            content_hash=content_hash,
                            last_error=str(exc),
                            fetched=True,
                            connection=conn,
                        )
                        self.logger.exception(
                            "parse.failed",
                            extra={
                                "event": "parse.failed",
                                "position": index,
                                "total": len(targets),
                                "url": entry.url,
                                "error": str(exc),
                            },
                        )
                        continue
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
                        self.repository.upsert_crawl_state(
                            source_url=entry.url,
                            canonical_url=entry.url,
                            sitemap_url=entry.sitemap_url,
                            sitemap_lastmod=entry.lastmod,
                            index_status="non_recipe",
                            content_hash=content_hash,
                            last_error=None,
                            fetched=True,
                            parsed=True,
                            connection=conn,
                        )
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
                    self.repository.upsert_crawl_state(
                        source_url=entry.url,
                        canonical_url=parse_result.recipe.source_url,
                        sitemap_url=entry.sitemap_url,
                        sitemap_lastmod=entry.lastmod,
                        index_status="indexed",
                        content_hash=content_hash,
                        last_error=None,
                        fetched=True,
                        parsed=True,
                        connection=conn,
                    )
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
                "discovered_sitemaps": stats.discovered_sitemaps,
                "discovered_url_entries": stats.discovered_url_entries,
                "candidate_urls": stats.candidate_urls,
                "scheduled_urls": stats.scheduled_urls,
                "crawled_urls": stats.crawled_urls,
                "indexed_recipes": stats.indexed_recipes,
                "skipped_non_recipe": stats.skipped_non_recipe,
                "skipped_disallowed": stats.skipped_disallowed,
                "failures": stats.failures,
                "skipped_unchanged": stats.skipped_unchanged,
                "duplicate_urls": stats.duplicate_urls,
            },
        )
        return stats
