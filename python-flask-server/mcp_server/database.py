from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, db_path: Path, timeout_seconds: int) -> None:
        self._db_path = db_path
        self._timeout_seconds = timeout_seconds
        self._table_exists_cache: dict[str, bool] = {}

    def connect(self) -> sqlite3.Connection:
        uri = f"file:{self._db_path}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=self._timeout_seconds)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._timeout_seconds * 1000}")
        return connection

    def table_exists(self, connection: sqlite3.Connection, table_name: str) -> bool:
        if table_name in self._table_exists_cache:
            return self._table_exists_cache[table_name]
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        ).fetchone()
        exists = row is not None
        self._table_exists_cache[table_name] = exists
        return exists


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def parse_json_blob(blob: str | None) -> Any:
    if not blob:
        return None
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return blob
