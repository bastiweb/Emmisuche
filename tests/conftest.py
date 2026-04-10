from __future__ import annotations

from pathlib import Path

import pytest

from app.db import get_connection, init_db


@pytest.fixture()
def fixture_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures"


@pytest.fixture()
def temp_db_path(tmp_path: Path) -> Path:
    db_path = tmp_path / "recipes.db"
    connection = get_connection(db_path)
    try:
        init_db(connection)
    finally:
        connection.close()
    return db_path

