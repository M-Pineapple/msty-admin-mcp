"""
Typed inventory helpers for Msty Studio entities (Drizzle schema).

Column lists are a wish list: each read selects only the listed columns the
table really has (PRAGMA table_info), so a renamed or dropped column in a
newer Studio schema is reported, not fatal. ``optional_columns`` exist only
in some releases and are not reported when absent.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from src import db

# entity_key -> (table, default columns, order_by)
ENTITY_CATALOG: Dict[str, Dict[str, Any]] = {
    "workspaces": {
        "table": "workspaces",
        "columns": None,
        "order_by": "createdAt DESC",
    },
    "personas": {
        "table": "personas",
        "columns": [
            "id",
            "name",
            "description",
            "folderId",
            "systemPrompt",
            "activeVersionId",
            "createdAt",
        ],
        "order_by": "createdAt DESC",
    },
    "shadow_personas": {
        "table": "shadowPersonas",
        "columns": None,
        "order_by": "createdAt DESC",
    },
    "user_personas": {
        "table": "userPersonas",
        "columns": None,
        "order_by": "createdAt DESC",
    },
    "crews": {
        "table": "crews",
        "columns": [
            "id",
            "name",
            "description",
            "responseMode",
            "executionMode",
            "contextMode",
            "folderId",
            "createdAt",
            "updatedAt",
        ],
        # Crew folders arrived in Studio 3.0 (verified on 3.0.0).
        "optional_columns": ["folderId"],
        "order_by": "updatedAt DESC",
    },
    "crew_folders": {
        "table": "crewFolders",
        "columns": None,
        "order_by": "sortOrder ASC",
    },
    "knowledge_stacks": {
        "table": "knowledgeStacks",
        "columns": [
            "id",
            "title",
            "text",
            "source",
            "status",
            "folderId",
            "composeStats",
            "updatedAt",
            "createdAt",
        ],
        "order_by": "updatedAt DESC",
    },
    "tools": {
        "table": "tools",
        "columns": [
            "id",
            "toolId",
            "name",
            "provider",
            "folderId",
            "notes",
            "createdAt",
        ],
        "order_by": "createdAt DESC",
    },
    "toolsets": {
        "table": "toolsets",
        "columns": None,
        "order_by": "createdAt DESC",
    },
    "turnstiles": {
        "table": "turnstiles",
        "columns": [
            "id",
            "name",
            "description",
            "folderId",
            "createdAt",
        ],
        "order_by": "createdAt DESC",
    },
    "live_contexts": {
        "table": "liveContexts",
        "columns": None,
        "order_by": "createdAt DESC",
    },
    "prompts": {
        "table": "promptsLibraryPrompts",
        "columns": None,
        "order_by": "createdAt DESC",
    },
    "attachments": {
        "table": "attachments",
        "columns": [
            "id",
            "name",
            "type",
            "folderId",
            "processingStatus",
            "shortDescription",
            "tags",
            "updatedAt",
            "createdAt",
        ],
        "order_by": "updatedAt DESC",
    },
    "attachment_folders": {
        "table": "attachmentsStudioFolders",
        "columns": None,
        "order_by": "sortOrder ASC",
    },
    "skills": {
        "table": "skill_preferences",
        "columns": None,
        "order_by": "createdAt DESC",
    },
    "skill_folders": {
        "table": "skillFolders",
        "columns": None,
        "order_by": "sortOrder ASC",
    },
    "agent_plans": {
        "table": "agentModePlans",
        "columns": [
            "id",
            "chatSplitId",
            "isCurrent",
            "totalDurationMs",
            "createdAt",
        ],
        "order_by": "createdAt DESC",
    },
    "providers": {
        "table": "languageModelsProviders",
        "columns": [
            "id",
            "name",
            "providerId",
            "models",
            "extras",
            "createdAt",
        ],
        "order_by": "createdAt DESC",
    },
    "conversations": {
        "table": "conversationTexts",
        "columns": [
            "id",
            "title",
            "projectId",
            "type",
            "archivedAt",
            "lastActivityAt",
            "createdAt",
        ],
        "order_by": "createdAt DESC",
    },
    "projects": {
        "table": "conversationTextProjects",
        "columns": [
            "id",
            "name",
            "description",
            "projectParentId",
            "sortOrder",
            "createdAt",
        ],
        "order_by": "sortOrder ASC",
    },
}


def _singular(key: str) -> str:
    if key.endswith("ies") and len(key) > 3:
        return key[:-3] + "y"
    if key.endswith("s") and len(key) > 1:
        return key[:-1]
    return key


ENTITY_ALIASES: Dict[str, str] = {_singular(k): k for k in ENTITY_CATALOG}


def resolve_entity_key(entity: str) -> Optional[str]:
    """Map a user-supplied entity name onto ENTITY_CATALOG.

    Accepts canonical plural keys, singular aliases (persona → personas),
    and hyphenated forms (knowledge-stack → knowledge_stacks).
    """
    key = entity.strip().lower().replace("-", "_").replace(" ", "_")
    if key in ENTITY_CATALOG:
        return key
    return ENTITY_ALIASES.get(key)


def workspace_database(workspace: Optional[str]) -> Optional[str]:
    """Database path for a named workspace, or None for the active one."""
    if workspace is None or not str(workspace).strip():
        return None
    path = db.get_database_path(workspace=workspace)
    return str(path) if path else None


def _present_columns(
    meta: Dict[str, Any], table: str, database_path: Optional[str]
) -> tuple:
    wanted = meta.get("columns")
    if not wanted:
        return None, []
    present = set(db.table_columns(table, database_path=database_path))
    optional = set(meta.get("optional_columns") or [])
    selected = [c for c in wanted if c in present]
    missing = [c for c in wanted if c not in present and c not in optional]
    return selected, missing


def list_entities(
    entity: str,
    limit: int = 100,
    workspace: Optional[str] = None,
    database_path: Optional[str] = None,
) -> Dict[str, Any]:
    resolved = resolve_entity_key(entity)
    meta = ENTITY_CATALOG.get(resolved) if resolved else None
    if not meta:
        return {
            "error": f"Unknown entity '{entity}'",
            "available": sorted(ENTITY_CATALOG.keys()),
            "aliases": sorted(ENTITY_ALIASES.keys()),
        }
    entity = resolved  # type: ignore[assignment]
    table = meta["table"]
    database_path = database_path or workspace_database(workspace)
    if not db.table_exists(table, database_path=database_path):
        return {
            "entity": entity,
            "table": table,
            "items": [],
            "count": 0,
            "note": f"Table '{table}' not present in this Studio schema version",
        }
    columns, missing = _present_columns(meta, table, database_path)
    if columns is not None and not columns:
        columns, missing = None, list(meta.get("columns") or [])
    order_by = meta.get("order_by")
    if order_by and order_by.split()[0] not in db.table_columns(table, database_path=database_path):
        order_by = None
    items = db.fetch_all(
        table,
        columns=columns,
        limit=limit,
        order_by=order_by,
        database_path=database_path,
    )
    result: Dict[str, Any] = {
        "entity": entity,
        "table": table,
        "count": len(items),
        "items": items,
    }
    if workspace:
        result["workspace"] = workspace
    if missing:
        result["missing_columns"] = missing
        result["note"] = (
            f"Columns not in this Studio schema and skipped: {', '.join(missing)}"
        )
    return result


def get_entity(entity: str, entity_id: str, workspace: Optional[str] = None) -> Dict[str, Any]:
    resolved = resolve_entity_key(entity)
    meta = ENTITY_CATALOG.get(resolved) if resolved else None
    if not meta:
        return {
            "error": f"Unknown entity '{entity}'",
            "available": sorted(ENTITY_CATALOG.keys()),
            "aliases": sorted(ENTITY_ALIASES.keys()),
        }
    entity = resolved  # type: ignore[assignment]
    table = meta["table"]
    row = db.fetch_by_id(table, entity_id, database_path=workspace_database(workspace))
    if not row:
        return {"entity": entity, "id": entity_id, "found": False}
    return {"entity": entity, "id": entity_id, "found": True, "item": row}


def export_workflow_pack(
    include: Optional[List[str]] = None,
    limit: int = 200,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Export a read-only snapshot of selected Studio entities for backup/migration."""
    keys = include or [
        "personas",
        "tools",
        "toolsets",
        "turnstiles",
        "live_contexts",
        "prompts",
        "knowledge_stacks",
        "crews",
        "skills",
        "attachments",
    ]
    pack: Dict[str, Any] = {
        "format": "msty-admin-workflow-pack",
        "version": 1,
        "entities": {},
    }
    database_path = workspace_database(workspace)
    if workspace:
        pack["workspace"] = workspace
    for key in keys:
        resolved = resolve_entity_key(key) or key
        pack["entities"][resolved] = list_entities(
            resolved, limit=limit, database_path=database_path
        )
    return pack


def catalogue_summary(workspace: Optional[str] = None) -> Dict[str, Any]:
    summary = {}
    database_path = workspace_database(workspace)
    tables = set(db.list_tables(database_path=database_path))
    for key, meta in ENTITY_CATALOG.items():
        table = meta["table"]
        if table in tables:
            try:
                summary[key] = {
                    "table": table,
                    "count": db.count_rows(table, database_path=database_path),
                }
            except Exception as exc:
                summary[key] = {"table": table, "error": str(exc)}
        else:
            summary[key] = {"table": table, "count": 0, "missing": True}
    return summary


KNOWN_TRANSPORTS = frozenset({"http", "sse", "stdio", "streamable-http"})
KNOWN_OAUTH_MODES = frozenset({"oauth", "oauth-dynamic"})
KNOWN_AUTH_TYPES = frozenset({"bearer", "oauth", "none"})


def _allowed(value: str, allowed: frozenset) -> str:
    return value if value in allowed else "other"


def tool_connection(config: Any) -> Dict[str, Any]:
    """Safe projection of one Toolbox tool config. Never returns a value.

    Shapes verified on Studio 3.0.0: HTTP tools store
    {transport: "http", url, headers: {name: value}, auth: {type: "bearer", token}}
    or auth {type: "oauth", mode: "oauth" | "oauth-dynamic", clientId, clientSecret,
    scope}. No auth means no auth key. STDIO tools store {command, args, env}.
    OAuth tokens live in Studio's encrypted secrets store, not the workspace
    database, so authorisation status cannot be read here.
    """
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except ValueError:
            config = None
    if not isinstance(config, dict):
        return {"transport": "unknown"}
    transport = str(config.get("transport") or config.get("type") or "").lower()
    if not transport:
        transport = "stdio" if "command" in config else "unknown"
    else:
        transport = _allowed(transport, KNOWN_TRANSPORTS)
    out: Dict[str, Any] = {"transport": transport}
    url = config.get("url")
    if isinstance(url, str) and url:
        try:
            out["url_host"] = urlsplit(url).hostname
        except ValueError:
            out["url_host"] = None
    headers = config.get("headers")
    if isinstance(headers, dict):
        out["header_names"] = sorted(str(k) for k in headers)
    elif isinstance(headers, list):
        names = []
        for item in headers:
            if isinstance(item, dict):
                parts = [item.get(k) for k in ("name", "key", "header") if isinstance(item.get(k), str)]
                if parts:
                    names.append(parts[0])
        out["header_names"] = sorted(names)
    if transport != "stdio":
        auth = config.get("auth")
        if isinstance(auth, dict):
            auth_type = _allowed(str(auth.get("type") or "").lower(), KNOWN_AUTH_TYPES)
            out["auth_type"] = auth_type
            if auth_type == "oauth":
                out["oauth_mode"] = _allowed(str(auth.get("mode") or "oauth").lower(), KNOWN_OAUTH_MODES)
                out["oauth_client_id_set"] = bool(auth.get("clientId"))
                out["oauth_status"] = "not_stored_in_workspace"
        else:
            out["auth_type"] = "none"
    env = config.get("env")
    if isinstance(env, dict):
        out["env_names"] = sorted(str(k) for k in env)
    if "command" in config:
        out["has_command"] = True
    return out
