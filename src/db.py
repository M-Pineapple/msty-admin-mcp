"""
Read-only access to the Msty Studio workspace SQLite database.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.paths import detect_msty_installation

# Only allow SELECT / WITH / PRAGMA for arbitrary query tool
_SAFE_SQL = re.compile(r"^\s*(SELECT|WITH|PRAGMA)\b", re.IGNORECASE | re.DOTALL)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|ATTACH|DETACH|REPLACE|CREATE|VACUUM|REINDEX)\b",
    re.IGNORECASE,
)

SENSITIVE_EXACT = {
    "key",
    "secret",
    "token",
    "password",
    "credential",
    "credentials",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "auth_token",
}
SENSITIVE_SUFFIXES = ("_key", "_secret", "_token", "_password", "_credential", "_credentials")


def _is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    if lower in SENSITIVE_EXACT:
        return True
    # Avoid false positives on promptTokens / completionTokens / totalTokens
    if "tokens" in lower and lower.endswith("tokens"):
        return False
    return any(lower.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)


def redact_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key) and value not in (None, "", [], {}):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(key, item) for item in value]
    return value


def redact_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: redact_value(k, v) for k, v in row.items()}


def get_database_path(explicit: Optional[str] = None) -> Optional[Path]:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    install = detect_msty_installation()
    if install.database_path:
        return Path(install.database_path)
    return None


def connect(readonly: bool = True, database_path: Optional[str] = None) -> sqlite3.Connection:
    path = get_database_path(database_path)
    if not path:
        raise FileNotFoundError("Msty Studio database not found")

    if readonly:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def list_tables(database_path: Optional[str] = None) -> List[str]:
    with connect(database_path=database_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]


def table_exists(table: str, database_path: Optional[str] = None) -> bool:
    return table in list_tables(database_path=database_path)


def count_rows(table: str, database_path: Optional[str] = None) -> int:
    if not re.fullmatch(r"[A-Za-z0-9_]+", table):
        raise ValueError(f"Invalid table name: {table}")
    with connect(database_path=database_path) as conn:
        row = conn.execute(f'SELECT COUNT(*) AS c FROM "{table}"').fetchone()
        return int(row["c"]) if row else 0


def fetch_all(
    table: str,
    columns: Optional[Sequence[str]] = None,
    where: Optional[str] = None,
    params: Sequence[Any] = (),
    limit: int = 100,
    order_by: Optional[str] = None,
    database_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9_]+", table):
        raise ValueError(f"Invalid table name: {table}")
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")

    cols = "*"
    if columns:
        safe_cols = []
        for col in columns:
            if not re.fullmatch(r"[A-Za-z0-9_]+", col):
                raise ValueError(f"Invalid column: {col}")
            safe_cols.append(f'"{col}"')
        cols = ", ".join(safe_cols)

    sql = [f'SELECT {cols} FROM "{table}"']
    if where:
        # where must be a simple equality fragment built by callers; reject injections
        if ";" in where or "--" in where or "/*" in where:
            raise ValueError("Unsafe WHERE clause")
        sql.append(f"WHERE {where}")
    if order_by:
        if not re.fullmatch(r"[A-Za-z0-9_]+(\s+(ASC|DESC))?", order_by, re.IGNORECASE):
            raise ValueError("Invalid ORDER BY")
        sql.append(f"ORDER BY {order_by}")
    sql.append(f"LIMIT {int(limit)}")

    with connect(database_path=database_path) as conn:
        rows = conn.execute(" ".join(sql), params).fetchall()
        return [redact_row(dict(r)) for r in rows]


def fetch_by_id(
    table: str,
    entity_id: str,
    id_column: str = "id",
    database_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9_]+", table):
        raise ValueError(f"Invalid table name: {table}")
    if not re.fullmatch(r"[A-Za-z0-9_]+", id_column):
        raise ValueError(f"Invalid id column: {id_column}")
    with connect(database_path=database_path) as conn:
        row = conn.execute(
            f'SELECT * FROM "{table}" WHERE "{id_column}" = ? LIMIT 1',
            (entity_id,),
        ).fetchone()
        return redact_row(dict(row)) if row else None


def safe_query(
    query: str,
    limit: int = 100,
    database_path: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    if not _SAFE_SQL.search(query) or _FORBIDDEN.search(query):
        raise ValueError("Only read-only SELECT / WITH / PRAGMA queries are allowed")
    if ";" in query.strip().rstrip(";"):
        raise ValueError("Multiple statements are not allowed")

    with connect(database_path=database_path) as conn:
        cursor = conn.execute(query)
        rows = cursor.fetchall()
        results = [redact_row(dict(r)) for r in rows[:limit]]
        return results, len(results)


def database_stats(database_path: Optional[str] = None) -> Dict[str, Any]:
    path = get_database_path(database_path)
    if not path:
        return {"error": "Database not found"}

    tables = list_tables(database_path=database_path)
    counts: Dict[str, int] = {}
    interesting = [
        "workspaces",
        "conversationTexts",
        "conversationTextMessages",
        "personas",
        "shadowPersonas",
        "crews",
        "knowledgeStacks",
        "tools",
        "toolsets",
        "turnstiles",
        "liveContexts",
        "attachments",
        "promptsLibraryPrompts",
        "skill_preferences",
        "agentModePlans",
        "insightsLanguageModelUsage",
        "languageModelsProviders",
    ]
    for table in interesting:
        if table in tables:
            try:
                counts[table] = count_rows(table, database_path=database_path)
            except Exception:
                counts[table] = -1

    migrations: List[Dict[str, Any]] = []
    if "__drizzle_migrations" in tables:
        try:
            migrations = fetch_all(
                "__drizzle_migrations",
                limit=20,
                order_by="created_at DESC",
                database_path=database_path,
            )
        except Exception:
            migrations = []

    return {
        "database_path": str(path),
        "size_mb": round(path.stat().st_size / (1024 * 1024), 3),
        "table_count": len(tables),
        "tables": tables,
        "entity_counts": counts,
        "recent_migrations": migrations,
    }


def dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)
