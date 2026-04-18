from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    intro TEXT,
    image_url TEXT,
    categories_json TEXT NOT NULL DEFAULT '[]',
    categories_text TEXT NOT NULL DEFAULT '',
    published_date TEXT,
    prep_time TEXT,
    cook_time TEXT,
    total_time TEXT,
    servings TEXT,
    ingredients_json TEXT NOT NULL DEFAULT '[]',
    ingredients_text TEXT NOT NULL DEFAULT '',
    instructions_json TEXT NOT NULL DEFAULT '[]',
    instructions_text TEXT NOT NULL DEFAULT '',
    nutrition_summary TEXT,
    searchable_text TEXT NOT NULL DEFAULT '',
    last_sitemap_mod TEXT,
    last_crawled_at TEXT NOT NULL,
    last_indexed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS crawl_state (
    source_url TEXT PRIMARY KEY,
    canonical_url TEXT NOT NULL,
    sitemap_url TEXT,
    sitemap_lastmod TEXT,
    last_fetched_at TEXT,
    last_parsed_at TEXT,
    content_hash TEXT,
    index_status TEXT NOT NULL DEFAULT 'new',
    last_error TEXT,
    fetch_count INTEGER NOT NULL DEFAULT 0,
    parse_count INTEGER NOT NULL DEFAULT 0,
    skip_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_crawl_state_status ON crawl_state(index_status);

CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL UNIQUE,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    FOREIGN KEY(recipe_id) REFERENCES recipes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_favorites_recipe_id ON favorites(recipe_id);

CREATE VIRTUAL TABLE IF NOT EXISTS recipes_fts USING fts5(
    title,
    intro,
    categories_text,
    ingredients_text,
    instructions_text,
    searchable_text,
    content='recipes',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS recipes_ai AFTER INSERT ON recipes BEGIN
    INSERT INTO recipes_fts(
        rowid,
        title,
        intro,
        categories_text,
        ingredients_text,
        instructions_text,
        searchable_text
    )
    VALUES(
        new.id,
        coalesce(new.title, ''),
        coalesce(new.intro, ''),
        coalesce(new.categories_text, ''),
        coalesce(new.ingredients_text, ''),
        coalesce(new.instructions_text, ''),
        coalesce(new.searchable_text, '')
    );
END;

CREATE TRIGGER IF NOT EXISTS recipes_ad AFTER DELETE ON recipes BEGIN
    INSERT INTO recipes_fts(recipes_fts, rowid, title, intro, categories_text, ingredients_text, instructions_text, searchable_text)
    VALUES('delete', old.id, old.title, old.intro, old.categories_text, old.ingredients_text, old.instructions_text, old.searchable_text);
END;

CREATE TRIGGER IF NOT EXISTS recipes_au AFTER UPDATE ON recipes BEGIN
    INSERT INTO recipes_fts(recipes_fts, rowid, title, intro, categories_text, ingredients_text, instructions_text, searchable_text)
    VALUES('delete', old.id, old.title, old.intro, old.categories_text, old.ingredients_text, old.instructions_text, old.searchable_text);

    INSERT INTO recipes_fts(
        rowid,
        title,
        intro,
        categories_text,
        ingredients_text,
        instructions_text,
        searchable_text
    )
    VALUES(
        new.id,
        coalesce(new.title, ''),
        coalesce(new.intro, ''),
        coalesce(new.categories_text, ''),
        coalesce(new.ingredients_text, ''),
        coalesce(new.instructions_text, ''),
        coalesce(new.searchable_text, '')
    );
END;
"""


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _run_migrations(connection: sqlite3.Connection) -> None:
    if not _column_exists(connection, "recipes", "last_indexed_at"):
        connection.execute(
            """
            ALTER TABLE recipes
            ADD COLUMN last_indexed_at TEXT
            """
        )
        connection.execute(
            """
            UPDATE recipes
            SET last_indexed_at = COALESCE(last_crawled_at, updated_at, created_at)
            WHERE last_indexed_at IS NULL
            """
        )

    # Backfill crawl_state from already indexed recipe rows to avoid full refetches.
    connection.execute(
        """
        INSERT INTO crawl_state (
            source_url,
            canonical_url,
            sitemap_lastmod,
            last_fetched_at,
            last_parsed_at,
            index_status,
            fetch_count,
            parse_count,
            updated_at
        )
        SELECT
            r.source_url,
            r.source_url,
            r.last_sitemap_mod,
            r.last_crawled_at,
            r.last_indexed_at,
            'indexed',
            CASE WHEN r.last_crawled_at IS NULL THEN 0 ELSE 1 END,
            CASE WHEN r.last_indexed_at IS NULL THEN 0 ELSE 1 END,
            COALESCE(r.last_indexed_at, r.last_crawled_at, r.updated_at, r.created_at)
        FROM recipes r
        LEFT JOIN crawl_state c ON c.source_url = r.source_url
        WHERE c.source_url IS NULL
        """
    )


def get_connection(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    _run_migrations(connection)
    connection.commit()
