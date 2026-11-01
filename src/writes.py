"""Confirmed Studio writes: JSON pack always, SQLite only with backup and lock check.

Read tools stay on ``src.db.connect(readonly=True)``. This module opens a
separate writable connection and never uses the read-only SQL authorizer.
MCP tools must not expose ``database_path``. Tests pass a fixture path.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.paths import detect_msty_installation, is_process_running

TABLE_FOR_KIND = {
    "personas": "personas",
    "tools": "tools",
    "prompts": "promptsLibraryPrompts",
    "skills": "skill_preferences",
    "toolsets": "toolsets",
}

REQUIRED_COLUMNS = {
    "personas": ("name", "systemPrompt"),
    "tools": ("name",),
}


def sidecar_root() -> Path:
    override = os.environ.get("MSTY_ADMIN_HOME", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".msty-admin"


def imports_dir() -> Path:
    path = sidecar_root() / "imports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir() -> Path:
    path = sidecar_root() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def save_import_pack(pack: Dict[str, Any], dest_dir: Optional[Path] = None) -> Path:
    folder = dest_dir or imports_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"pack-{_now_stamp()}.json"
    path.write_text(json.dumps(pack, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def resolve_database_path(explicit: Optional[str] = None) -> Optional[Path]:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    install = detect_msty_installation()
    if install.database_path:
        candidate = Path(install.database_path)
        return candidate if candidate.exists() else None
    return None


def is_live_studio_database(path: Path) -> bool:
    install = detect_msty_installation()
    live = install.database_path
    if not live:
        return False
    try:
        return Path(live).resolve() == path.resolve()
    except OSError:
        return False


def studio_holds_live_database(path: Path) -> bool:
    """True when this path is the live Studio DB and a Studio process is running."""
    if not is_live_studio_database(path):
        return False
    return is_process_running("MstyStudio") or is_process_running("Msty Studio")


def backup_database(database_path: Path, dest_dir: Optional[Path] = None) -> Path:
    folder = dest_dir or backups_dir()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{database_path.name}-{_now_stamp()}.bak"
    shutil.copy2(database_path, dest)
    return dest


def connect_writable(database_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(database_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [r["name"] for r in rows]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _prepare_row(kind: str, item: Dict[str, Any], columns: Sequence[str]) -> Dict[str, Any]:
    row = dict(item)
    if "id" not in row or not row["id"]:
        row["id"] = str(uuid.uuid4())
    if "createdAt" in columns and not row.get("createdAt"):
        row["createdAt"] = _iso_now()
    if kind == "personas":
        if "systemPrompt" not in row and row.get("system_prompt"):
            row["systemPrompt"] = row["system_prompt"]
        if "systemPrompt" not in row:
            raise ValueError("persona needs systemPrompt")
        if row.get("model") and "partialModelInfo" in columns and "partialModelInfo" not in row:
            row["partialModelInfo"] = json.dumps({"model": row["model"]})
    if kind == "tools":
        if "toolId" not in row or not row["toolId"]:
            row["toolId"] = str(row.get("id") or row.get("name") or "tool")
        config = row.get("config", {})
        if not isinstance(config, str):
            row["config"] = json.dumps(config)
        elif not config:
            row["config"] = "{}"
    if kind == "prompts":
        if "prompt" not in row and row.get("text"):
            row["prompt"] = row["text"]
    allowed = {key: row[key] for key in row if key in columns}
    required = REQUIRED_COLUMNS.get(kind, ())
    missing = [col for col in required if col in columns and not allowed.get(col)]
    if missing:
        raise ValueError(f"{kind} missing required columns: {', '.join(missing)}")
    return allowed


def insert_row(conn: sqlite3.Connection, table: str, row: Dict[str, Any]) -> None:
    columns = list(row.keys())
    placeholders = ", ".join("?" for _ in columns)
    quoted = ", ".join(f'"{c}"' for c in columns)
    conn.execute(
        f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})',
        [row[c] for c in columns],
    )


def apply_pack(
    pack: Dict[str, Any],
    confirm: bool = False,
    database_path: Optional[str] = None,
    backup_root: Optional[Path] = None,
    imports_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Save a JSON pack. With confirm=true, insert into Studio SQLite when safe."""
    saved = save_import_pack(pack, dest_dir=imports_root)
    counts = {
        kind: len(pack.get(kind) or [])
        for kind in TABLE_FOR_KIND
        if pack.get(kind)
    }
    preview = {
        "status": "preview" if not confirm else "applying",
        "wrote": False,
        "pack_path": str(saved),
        "counts": counts,
        "note": (
            "JSON pack saved. Pass confirm=true to insert into the Studio database "
            "after a timestamped backup. Refused while Msty Studio holds the live DB."
        ),
    }
    if not confirm:
        return preview

    db_path = resolve_database_path(database_path)
    if not db_path:
        preview["status"] = "refused"
        preview["error"] = "Studio database not found"
        return preview
    if studio_holds_live_database(db_path):
        preview["status"] = "refused"
        preview["error"] = (
            "Msty Studio appears to be running and holding the live database. "
            "Quit Studio, or import the JSON pack in Persona Studio / Toolbox."
        )
        preview["database"] = str(db_path)
        return preview

    backup = backup_database(db_path, dest_dir=backup_root)
    applied: Dict[str, List[str]] = {}
    skipped: List[str] = []
    conn = connect_writable(db_path)
    try:
        conn.execute("BEGIN")
        for kind, table in TABLE_FOR_KIND.items():
            items: Iterable[Any] = pack.get(kind) or []
            if not items:
                continue
            if not _table_exists(conn, table):
                skipped.append(f"{kind} (table {table} missing)")
                continue
            columns = table_columns(conn, table)
            ids: List[str] = []
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError(f"{kind} entries must be objects")
                row = _prepare_row(kind, item, columns)
                insert_row(conn, table, row)
                ids.append(str(row.get("id")))
            applied[kind] = ids
        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.close()
        return {
            "status": "error",
            "wrote": False,
            "pack_path": str(saved),
            "backup_path": str(backup),
            "error": str(exc),
        }
    conn.close()
    return {
        "status": "applied",
        "wrote": True,
        "pack_path": str(saved),
        "backup_path": str(backup),
        "database": str(db_path),
        "applied": applied,
        "skipped": skipped,
        "counts": {k: len(v) for k, v in applied.items()},
    }


def persona_pack(name: str, system_prompt: str, model: str) -> Dict[str, Any]:
    return {
        "personas": [
            {
                "name": name,
                "systemPrompt": system_prompt,
                "model": model,
                "description": f"Generated persona for {model}",
            }
        ]
    }


def tool_pack(tool_data: Dict[str, Any]) -> Dict[str, Any]:
    return {"tools": [dict(tool_data)]}
