from __future__ import annotations

import logging
import random
import time
from collections.abc import Collection

import httpx


class CrawlError(Exception):
    """Raised when crawling fails after retries."""


class PoliteHttpClient:
    def __init__(
        self,
        user_agent: str,
        timeout_seconds: float,
        delay_seconds: float,
        rate_limit_per_minute: float,
        max_retries: int,
        retry_backoff_base_seconds: float,
        retry_backoff_max_seconds: float,
        retry_jitter_seconds: float,
        retry_status_codes: Collection[int],
        logger: logging.Logger,
    ) -> None:
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )
        self.delay_seconds = max(0.0, delay_seconds)
        self.rate_limit_per_minute = max(0.0, rate_limit_per_minute)
        self.max_retries = max(0, max_retries)
        self.retry_backoff_base_seconds = max(0.0, retry_backoff_base_seconds)
        self.retry_backoff_max_seconds = max(
            self.retry_backoff_base_seconds, retry_backoff_max_seconds
        )
        self.retry_jitter_seconds = max(0.0, retry_jitter_seconds)
        self.retry_status_codes = set(retry_status_codes)
        self.logger = logger
        self._last_request_at = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PoliteHttpClient":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # type: ignore[override]
        self.close()

    def _respect_delay(self) -> None:
        min_interval = 0.0
        if self.rate_limit_per_minute > 0:
            min_interval = 60.0 / self.rate_limit_per_minute
        effective_delay = max(self.delay_seconds, min_interval)
        if effective_delay <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < effective_delay:
            time.sleep(effective_delay - elapsed)

    def get_text(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                self._respect_delay()
                response = self._client.get(url)
                self._last_request_at = time.monotonic()

                if response.status_code in self.retry_status_codes:
                    raise CrawlError(
                        f"Transient HTTP {response.status_code} for {url}"
                    )

                response.raise_for_status()
                self.logger.debug(
                    "crawl.http_success",
                    extra={
                        "event": "crawl.http_success",
                        "url": url,
                        "status_code": response.status_code,
                    },
                )
                return response.text
            except (httpx.HTTPError, CrawlError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                backoff = min(
                    self.retry_backoff_max_seconds,
                    self.retry_backoff_base_seconds * (2**attempt),
                )
                if self.retry_jitter_seconds > 0:
                    backoff += random.uniform(0, self.retry_jitter_seconds)
                self.logger.warning(
                    "crawl.http_retry",
                    extra={
                        "event": "crawl.http_retry",
                        "url": url,
                        "attempt": attempt + 1,
                        "max_retries": self.max_retries,
                        "backoff_seconds": round(backoff, 3),
                        "error": str(exc),
                    },
                )
                time.sleep(backoff)

        raise CrawlError(f"Failed to fetch {url}: {last_error}") from last_error
