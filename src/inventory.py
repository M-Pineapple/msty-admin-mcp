"""
Typed inventory helpers for Msty Studio entities (Drizzle schema).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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
            "createdAt",
            "updatedAt",
        ],
        "order_by": "updatedAt DESC",
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


def list_entities(entity: str, limit: int = 100) -> Dict[str, Any]:
    meta = ENTITY_CATALOG.get(entity)
    if not meta:
        return {
            "error": f"Unknown entity '{entity}'",
            "available": sorted(ENTITY_CATALOG.keys()),
        }
    table = meta["table"]
    if not db.table_exists(table):
        return {
            "entity": entity,
            "table": table,
            "items": [],
            "count": 0,
            "note": f"Table '{table}' not present in this Studio schema version",
        }
    items = db.fetch_all(
        table,
        columns=meta.get("columns"),
        limit=limit,
        order_by=meta.get("order_by"),
    )
    return {
        "entity": entity,
        "table": table,
        "count": len(items),
        "items": items,
    }


def get_entity(entity: str, entity_id: str) -> Dict[str, Any]:
    meta = ENTITY_CATALOG.get(entity)
    if not meta:
        return {
            "error": f"Unknown entity '{entity}'",
            "available": sorted(ENTITY_CATALOG.keys()),
        }
    table = meta["table"]
    row = db.fetch_by_id(table, entity_id)
    if not row:
        return {"entity": entity, "id": entity_id, "found": False}
    return {"entity": entity, "id": entity_id, "found": True, "item": row}


def export_workflow_pack(
    include: Optional[List[str]] = None,
    limit: int = 200,
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
    for key in keys:
        pack["entities"][key] = list_entities(key, limit=limit)
    return pack


def catalogue_summary() -> Dict[str, Any]:
    summary = {}
    for key, meta in ENTITY_CATALOG.items():
        table = meta["table"]
        if db.table_exists(table):
            try:
                summary[key] = {"table": table, "count": db.count_rows(table)}
            except Exception as exc:
                summary[key] = {"table": table, "error": str(exc)}
        else:
            summary[key] = {"table": table, "count": 0, "missing": True}
    return summary
