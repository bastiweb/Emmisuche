from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.crawler.indexer import RecipeIndexer
from app.db import get_connection, init_db
from app.logging_utils import configure_logging
from app.storage import RecipeRepository


def ensure_database() -> None:
    settings = get_settings()
    connection = get_connection(settings.database_path)
    try:
        init_db(connection)
    finally:
        connection.close()


def run_index(mode: str, limit: int | None = None, stale_days: int | None = None) -> int:
    settings = get_settings()
    repository = RecipeRepository(settings.database_path)
    indexer = RecipeIndexer(settings=settings, repository=repository)
    stats = indexer.run(mode=mode, limit=limit, stale_days=stale_days)

    print("")
    print("Indexing complete")
    print("----------------")
    print(f"Mode            : {mode}")
    print(f"Discovered URLs : {stats.discovered_urls}")
    print(f"Scheduled URLs  : {stats.scheduled_urls}")
    print(f"Crawled URLs    : {stats.crawled_urls}")
    print(f"Indexed recipes : {stats.indexed_recipes}")
    print(f"Skipped existing: {stats.skipped_existing}")
    print(f"Skipped nonrecipe: {stats.skipped_non_recipe}")
    print(f"Skipped robots  : {stats.skipped_disallowed}")
    print(f"Failures        : {stats.failures}")
    return 0 if stats.failures == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recipe index management utility.")
    parser.add_argument(
        "--log-level",
        default=None,
        help="Override LOG_LEVEL (DEBUG, INFO, WARNING, ERROR).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "init-db",
        help="Initialize or migrate the SQLite database schema.",
    )

    crawl_parser = subparsers.add_parser(
        "crawl",
        help="Initial crawl: index missing pages only.",
    )
    crawl_parser.add_argument("--limit", type=int, default=None, help="Limit URLs to crawl.")

    reindex_parser = subparsers.add_parser(
        "reindex",
        help="Reindex changed, missing, or stale entries (recommended).",
    )
    reindex_parser.add_argument("--limit", type=int, default=None, help="Limit URLs to crawl.")
    reindex_parser.add_argument(
        "--stale-days",
        type=int,
        default=None,
        help="Override CRAWLER_STALE_DAYS for this run.",
    )

    reindex_all_parser = subparsers.add_parser(
        "reindex-all",
        help="Re-crawl and upsert every discovered candidate page.",
    )
    reindex_all_parser.add_argument(
        "--limit", type=int, default=None, help="Limit URLs to crawl."
    )

    stale_parser = subparsers.add_parser(
        "update-stale",
        help="Deprecated alias for reindex.",
    )
    stale_parser.add_argument("--limit", type=int, default=None, help="Limit URLs to crawl.")
    stale_parser.add_argument(
        "--stale-days",
        type=int,
        default=None,
        help="Override CRAWLER_STALE_DAYS for this run.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(args.log_level or settings.log_level, json_logs=settings.log_json)
    ensure_database()

    if args.command == "init-db":
        logging.getLogger(__name__).info(
            "db.initialized",
            extra={"event": "db.initialized", "database_path": str(settings.database_path)},
        )
        return 0
    if args.command == "crawl":
        return run_index(mode="initial", limit=args.limit)
    if args.command == "reindex":
        return run_index(mode="reindex", limit=args.limit, stale_days=args.stale_days)
    if args.command == "reindex-all":
        return run_index(mode="reindex-all", limit=args.limit)
    if args.command == "update-stale":
        return run_index(
            mode="reindex",
            limit=args.limit,
            stale_days=args.stale_days,
        )
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
