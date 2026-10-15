"""
Read-only access to the Msty Studio workspace SQLite database.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
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

# JSON extractors leak individual keys even when the column name (config, extras) is safe.
_JSON_EXTRACT_FUNCTIONS = {
    "json_extract",
    "->",
    "->>",
    "json_remove",
    "json_replace",
    "json_set",
    "json_insert",
    "json_patch",
}
_JSON_VALUE_TABLES = {"json_each", "json_tree"}
_DENIED_SQL_ACTIONS = {
    sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_UPDATE,
    sqlite3.SQLITE_DELETE,
    sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_ATTACH,
    sqlite3.SQLITE_DETACH,
    sqlite3.SQLITE_ALTER_TABLE,
    sqlite3.SQLITE_REINDEX,
    sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_CREATE_VTABLE,
    sqlite3.SQLITE_DROP_VTABLE,
}

# Distinctive provider-key shapes. Column-name redaction still covers generic secrets.
_SECRET_VALUE_RE = re.compile(
    r"("
    r"sk-[A-Za-z0-9_-]{8,}"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|AIza[0-9A-Za-z_-]{32,}"
    r"|Bearer\s+\S+"
    r"|-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----[\s\S]*?-----END(?: [A-Z]+)? PRIVATE KEY-----"
    r")",
    re.IGNORECASE,
)
_URL_USERINFO_RE = re.compile(r"([a-z][a-z0-9+.-]*://)[^/\s@]+@", re.IGNORECASE)
# userinfo with the scheme cut off (e.g. substr(baseUrl, 9)): "user:pass@host" or "pass@host/".
_BARE_USERINFO_RE = re.compile(r"(?<![\w.+-])[^\s/@:'\"]+(?::[^\s/@'\"]*)?@(?=[A-Za-z0-9.-]+[:/])")
# Raw page / storage introspection tables bypass every column check.
_RAW_STORAGE_TABLES = {"sqlite_dbpage", "dbstat"}
_FREE_SQL_TIMEOUT_S = 5.0
_HEX_BLOB_RE = re.compile(r"\A(?:[0-9a-fA-F]{2}){8,}\Z")


# camelCase / kebab-case names (accessToken, clientSecret, x-api-key) fold to these.
_SENSITIVE_FOLDED_SUFFIXES = (
    "apikey", "secret", "secrets", "token", "password", "passwords", "passwd",
    "credential", "credentials", "authorization", "privatekey", "secretkey",
    "accesskey", "accesskeyid", "key", "keys", "header", "headers", "auth",
)
_SENSITIVE_FOLDED_PREFIXES = (
    "keyvalue", "keymaterial", "keydata", "secret", "password", "credential", "apikey",
    "authtoken", "authheader", "accesstoken", "refreshtoken", "privatekey",
)
# Identifier / index style names that end in "key" but never hold a secret.
_SAFE_FOLDED_NAMES = {
    "primarykey", "foreignkey", "sortkey", "partitionkey", "cachekey", "groupkey",
    "idempotencykey", "lookupkey", "uniquekey", "rowkey", "indexkey", "shortcutkey",
    "hotkey", "keyid", "keyname", "keys_count",
}
# Usage counters such as promptTokens / maxTokens are numbers, not secrets.
_TOKEN_COUNTER_HINTS = ("count", "limit", "usage", "max", "min", "total", "prompt", "completion", "used")
# Columns that commonly embed userinfo (user:pass@host). Free-form SQL reads them as NULL;
# fetch_all / fetch_by_id still return them with userinfo redacted.
_URL_LIKE_SUFFIXES = ("url", "uri", "endpoint", "dsn", "proxy", "webhook", "connectionstring")


def _is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    if lower in SENSITIVE_EXACT:
        return True
    folded = re.sub(r"[^a-z0-9]", "", lower)
    if folded in _SAFE_FOLDED_NAMES or folded == "id" or folded.endswith("id"):
        return False
    if folded.endswith("tokens") or ("token" in folded and any(h in folded for h in _TOKEN_COUNTER_HINTS)):
        return False
    if folded.endswith(_SENSITIVE_FOLDED_SUFFIXES) or folded.startswith(_SENSITIVE_FOLDED_PREFIXES):
        return True
    # Avoid false positives on promptTokens / completionTokens / totalTokens
    if "tokens" in lower and lower.endswith("tokens"):
        return False
    return any(lower.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)


def _try_json(value: str) -> Any:
    text = value.strip()
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _redact_secret_patterns(value: str, *, decode_hex: bool = True) -> str:
    redacted = _SECRET_VALUE_RE.sub("[REDACTED]", value)
    redacted = _URL_USERINFO_RE.sub(r"\1[REDACTED]@", redacted)
    redacted = _BARE_USERINFO_RE.sub("[REDACTED]@", redacted)
    if decode_hex and _HEX_BLOB_RE.fullmatch(value):
        try:
            decoded = bytes.fromhex(value).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            decoded = None
        if decoded:
            parsed = _try_json(decoded)
            if parsed is not None:
                walked = redact_value("", parsed)
                if walked != parsed:
                    return "[REDACTED]"
            if decoded != _redact_secret_patterns(decoded, decode_hex=False):
                return "[REDACTED]"
    return redacted


def redact_value(key: str, value: Any) -> Any:
    if isinstance(value, str):
        parsed = _try_json(value)
        if parsed is not None:
            redacted = redact_value(key, parsed)
            return json.dumps(redacted) if not isinstance(redacted, str) else redacted
        if _is_sensitive_key(key) and value not in (None, "", [], {}):
            return "[REDACTED]"
        return _redact_secret_patterns(value)
    if _is_sensitive_key(key) and value not in (None, "", [], {}):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return _redact_arg_list(key, value)
    return value


_FLAG_RE = re.compile(r"^-{1,2}([A-Za-z0-9_.-]+)(?:=(.*))?$", re.DOTALL)


def _redact_arg_list(key: str, items: list) -> list:
    """Redact list items, including the value after a secret-named CLI flag
    (`--api-key VALUE`, `--token=VALUE`, `-H "Authorization: ..."`)."""
    out: list = []
    redact_next = False
    for item in items:
        if redact_next and isinstance(item, str):
            out.append("[REDACTED]")
            redact_next = False
            continue
        redact_next = False
        if isinstance(item, str):
            m = _FLAG_RE.match(item)
            if m and (_is_sensitive_key(m.group(1)) or m.group(1).lower() in {"h", "header"}):
                if m.group(2) is not None:
                    out.append(f"{item.split('=', 1)[0]}=[REDACTED]")
                else:
                    out.append(item)
                    redact_next = True
                continue
        out.append(redact_value(key, item))
    return out


# Free-form SQL (safe_query) must never see these raw: they hold JSON that can
# embed provider keys or MCP env tokens, and SQL string functions (substr, ||,
# unicode) can slice that text past any output redaction. fetch_all and
# fetch_by_id still return them, parsed and redacted by redact_row.
_RAW_JSON_COLUMNS = {
    "config", "extras", "settings", "env", "headers", "environment",
    # Generic JSON blob names a future Studio schema could use for keys.
    "data", "metadata", "meta", "options", "params", "payload", "auth",
    "credentials", "secrets", "providerconfig", "connection", "connectionconfig",
}


def _credential_authorizer(
    action: int,
    arg1: Optional[str],
    arg2: Optional[str],
    _dbname: Optional[str],
    _source: Optional[str],
) -> int:
    """Refuse credential-column reads at the SQLite layer, including aliases and JSON extractors."""
    if action in _DENIED_SQL_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        fn = (arg2 or "").lower()
        if fn in _JSON_EXTRACT_FUNCTIONS or fn == "load_extension":
            # IGNORE yields NULL instead of aborting a wider SELECT list.
            return sqlite3.SQLITE_IGNORE
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        table = (arg1 or "").lower()
        if table in _RAW_STORAGE_TABLES:
            return sqlite3.SQLITE_DENY
        column = arg2 or ""
        if table in _JSON_VALUE_TABLES:
            return sqlite3.SQLITE_IGNORE
        if column and _is_sensitive_key(column):
            return sqlite3.SQLITE_IGNORE
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_OK


# Command-line columns: MCP server entries keep `--api-key <value>` in args.
_COMMAND_LINE_COLUMNS = {"args", "arguments", "argv", "command", "cmd", "commandline"}


def is_secret_column(column: str) -> bool:
    """True for every column the free-SQL tool must never read.

    Covers credential names (api_key, accessToken, openaiKey, authHeader ...),
    URL-type columns (userinfo), JSON/blob columns that embed keys, and
    command-line columns. Secrets stored in arbitrary free-text columns
    (e.g. a note or message body) are out of scope for the free-SQL tool.
    """
    lower = (column or "").lower()
    if not lower:
        return False
    return (
        _is_sensitive_key(column)
        or lower in _RAW_JSON_COLUMNS
        or lower in _COMMAND_LINE_COLUMNS
        or lower.endswith(_URL_LIKE_SUFFIXES)
    )


def _free_sql_authorizer(action, arg1, arg2, dbname, source) -> int:
    """Authorizer for caller-written SQL.

    This is the security boundary of the free-SQL tool: every SQLITE_READ of a
    secret-classified column returns SQLITE_IGNORE, so the column reads as NULL
    inside any expression (substr, hex, ||, unicode, json_*, CTEs). Output
    redaction afterwards is defence in depth only.
    """
    verdict = _credential_authorizer(action, arg1, arg2, dbname, source)
    if verdict != sqlite3.SQLITE_OK:
        return verdict
    if action == sqlite3.SQLITE_READ and is_secret_column(arg2 or ""):
        return sqlite3.SQLITE_IGNORE
    return sqlite3.SQLITE_OK


def redact_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: redact_value(k, v) for k, v in row.items()}


_SQL_STRINGS = re.compile(r"'(?:''|[^'])*'|\"(?:[^\"]|\"\")*\"")
_SQL_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
_SQL_KEYWORDS = {
    "SELECT",
    "FROM",
    "WHERE",
    "WITH",
    "AS",
    "AND",
    "OR",
    "ON",
    "JOIN",
    "LEFT",
    "RIGHT",
    "INNER",
    "OUTER",
    "GROUP",
    "BY",
    "ORDER",
    "LIMIT",
    "PRAGMA",
    "NULL",
    "TRUE",
    "FALSE",
    "NOT",
    "IN",
    "IS",
    "LIKE",
    "DISTINCT",
    "CASE",
    "WHEN",
    "THEN",
    "ELSE",
    "END",
    "HAVING",
    "UNION",
    "ALL",
    "EXISTS",
    "BETWEEN",
    "ASC",
    "DESC",
    "COUNT",
    "SUM",
    "AVG",
    "MIN",
    "MAX",
    "CAST",
    "TABLE",
}


def names_credential_column(query: str) -> bool:
    stripped = _SQL_STRINGS.sub(" ", query)
    for ident in _SQL_IDENT.findall(stripped):
        if ident.upper() in _SQL_KEYWORDS:
            continue
        if _is_sensitive_key(ident):
            return True
    return False


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
    conn.set_authorizer(_credential_authorizer)
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
    if names_credential_column(query):
        raise ValueError("Queries must not select credential columns")

    with connect(database_path=database_path) as conn:
        conn.set_authorizer(_free_sql_authorizer)
        deadline = time.monotonic() + _FREE_SQL_TIMEOUT_S
        # Non-zero return aborts the statement (runaway recursive CTEs etc.).
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
        cursor = conn.execute(query)
        rows = cursor.fetchmany(limit)
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
