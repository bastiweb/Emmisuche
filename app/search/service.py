from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.db import get_connection
from app.schemas import SearchResultItem


class SearchService:
    def __init__(
        self,
        database_path: Path,
        stale_days: int = 30,
        logger: logging.Logger | None = None,
    ):
        self.database_path = database_path
        self.stale_days = max(1, stale_days)
        self.logger = logger or logging.getLogger(__name__)

    @staticmethod
    def _parse_iso_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _is_stale(self, last_indexed_at: str | None) -> bool:
        parsed = self._parse_iso_datetime(last_indexed_at)
        if parsed is None:
            return True
        return parsed < (datetime.now(UTC) - timedelta(days=self.stale_days))

    @staticmethod
    def _build_fts_query(raw_query: str) -> str:
        terms = re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+", raw_query.lower())
        cleaned = [term for term in terms if len(term) >= 2]
        if not cleaned:
            return ""
        return " AND ".join(f"{term}*" for term in cleaned)

    @staticmethod
    def _fallback_snippet(title: str, intro: str | None, ingredients: str | None) -> str:
        candidate = intro or ingredients or ""
        if not candidate:
            return title
        snippet = candidate.strip().replace("\n", " ")
        if len(snippet) <= 180:
            return snippet
        return f"{snippet[:177]}..."

    def search(
        self, query: str, page: int, per_page: int
    ) -> tuple[list[SearchResultItem], int]:
        self.logger.info(
            "search.request",
            extra={
                "event": "search.request",
                "query": query,
                "page": page,
                "per_page": per_page,
            },
        )
        fts_query = self._build_fts_query(query)
        if not fts_query:
            self.logger.info(
                "search.empty_query",
                extra={"event": "search.empty_query", "query": query},
            )
            return [], 0

        offset = max(0, (page - 1) * per_page)
        with get_connection(self.database_path) as conn:
            count_row = conn.execute(
                "SELECT COUNT(*) AS count FROM recipes_fts WHERE recipes_fts MATCH ?",
                (fts_query,),
            ).fetchone()
            total = int(count_row["count"]) if count_row else 0

            rows = conn.execute(
                """
                SELECT
                    r.id,
                    r.title,
                    r.intro,
                    r.ingredients_text,
                    r.image_url,
                    r.source_url,
                    r.last_indexed_at,
                    snippet(
                        recipes_fts,
                        5,
                        '<mark>',
                        '</mark>',
                        ' ... ',
                        18
                    ) AS snippet_text,
                    bm25(
                        recipes_fts,
                        20.0,
                        2.0,
                        1.0,
                        8.0,
                        4.0,
                        0.8
                    ) AS score
                FROM recipes_fts
                JOIN recipes r ON r.id = recipes_fts.rowid
                WHERE recipes_fts MATCH ?
                ORDER BY score ASC
                LIMIT ? OFFSET ?
                """,
                (fts_query, per_page, offset),
            ).fetchall()

        items: list[SearchResultItem] = []
        for row in rows:
            snippet_text = row["snippet_text"] or self._fallback_snippet(
                row["title"], row["intro"], row["ingredients_text"]
            )
            last_indexed_at = row["last_indexed_at"]
            items.append(
                SearchResultItem(
                    id=int(row["id"]),
                    title=row["title"],
                    snippet=snippet_text,
                    image_url=row["image_url"],
                    source_url=row["source_url"],
                    score=float(row["score"]) if row["score"] is not None else 0.0,
                    last_indexed_at=last_indexed_at,
                    is_stale=self._is_stale(last_indexed_at),
                )
            )
        self.logger.info(
            "search.response",
            extra={
                "event": "search.response",
                "query": query,
                "page": page,
                "per_page": per_page,
                "total": total,
                "returned": len(items),
            },
        )
        return items, total
