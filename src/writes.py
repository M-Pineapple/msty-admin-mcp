"""Confirmed Studio writes: JSON pack always. SQLite only for safe kinds.

Tools, toolsets and skills are never inserted into Studio SQLite. Personas
and prompts need ``confirm=true`` and ``MSTY_ALLOW_STUDIO_WRITES=1`` in the
server environment. MCP tools must not expose ``database_path``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.paths import detect_msty_installation, is_process_running
from src.safe_io import secure_mkdir, secure_write

TABLE_FOR_KIND = {
    "personas": "personas",
    "tools": "tools",
    "prompts": "promptsLibraryPrompts",
    "skills": "skill_preferences",
    "toolsets": "toolsets",
}

# MCP never writes these tables. Import the JSON pack in Toolbox.
# Skills use free-form content that can carry command/args/env, so they stay pack-only.
PACK_ONLY_KINDS = frozenset({"tools", "toolsets", "skills"})
DB_KINDS = frozenset({"personas", "prompts"})
LAUNCH_KEYS = frozenset({"command", "args", "env", "executable", "bin", "script", "stdio", "cmd"})
WRITES_ENV = "MSTY_ALLOW_STUDIO_WRITES"

REQUIRED_COLUMNS = {
    "personas": ("name", "systemPrompt"),
    "tools": ("name",),
}

ENV_OFF_NOTE = (
    "Studio database writes are off. Set MSTY_ALLOW_STUDIO_WRITES=1 in the MCP "
    "server environment (not as a tool argument), then pass confirm=true. "
    "Tools, toolsets and skills are never written to the database. Import the JSON pack "
    "in Toolbox."
)
LAUNCH_FLAG = "runs a program on your machine, review before importing"
PACK_ONLY_NOTE = (
    "Tools, toolsets and skills are saved as a JSON pack only. Import them in Msty Toolbox. "
    "They are never written to the Studio database from this MCP."
)


def sidecar_root() -> Path:
    override = os.environ.get("MSTY_ADMIN_HOME", "").strip()
    if override:
        return secure_mkdir(Path(override))
    return secure_mkdir(Path.home() / ".msty-admin")


def imports_dir() -> Path:
    return secure_mkdir(sidecar_root() / "imports")


def backups_dir() -> Path:
    return secure_mkdir(sidecar_root() / "backups")


def studio_writes_allowed() -> bool:
    return os.environ.get(WRITES_ENV, "") == "1"


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def save_import_pack(pack: Dict[str, Any], dest_dir: Optional[Path] = None) -> Path:
    folder = dest_dir or imports_dir()
    secure_mkdir(folder)
    path = folder / f"pack-{_now_stamp()}.json"
    secure_write(path, json.dumps(pack, indent=2, default=str) + "\n")
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
    """True when this path is the live Studio DB and a Studio process is running.

    Process name live-observed on macOS: MstyStudio (app and Helper children).
    is_process_running fails closed, so an unknown probe refuses the write.
    """
    if not is_live_studio_database(path):
        return False
    return is_process_running("MstyStudio")


def sqlite_readonly_uri(path: Path) -> str:
    """Read-only SQLite URI. Path.as_uri encodes special characters."""
    return f"{path.resolve().as_uri()}?mode=ro"


def backup_database(database_path: Path, dest_dir: Optional[Path] = None) -> Path:
    """Copy the logical SQLite database, including WAL, into a 0600 file."""
    folder = dest_dir or backups_dir()
    secure_mkdir(folder)
    dest = folder / f"{database_path.name}-{_now_stamp()}.bak"
    secure_write(dest, b"")
    src = sqlite3.connect(sqlite_readonly_uri(database_path), uri=True)
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    return dest


def connect_writable(database_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(database_path), timeout=1.0)
    conn.isolation_level = None
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=1000")
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


def launch_keys_in(obj: Any) -> List[str]:
    found: List[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in LAUNCH_KEYS:
                found.append(str(key))
            found.extend(launch_keys_in(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(launch_keys_in(item))
    elif isinstance(obj, str):
        text = obj.strip()
        if text[:1] in "{[":
            try:
                found.extend(launch_keys_in(json.loads(text)))
            except json.JSONDecodeError:
                pass
    return found


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
    """Save a JSON pack. SQLite inserts only personas and prompts."""
    launch_hits = launch_keys_in(
        {
            "tools": pack.get("tools"),
            "toolsets": pack.get("toolsets"),
            "skills": pack.get("skills"),
        }
    )
    launch_risk = []
    if launch_hits:
        unique = sorted(set(k.lower() for k in launch_hits))
        launch_risk = [f"{key}: {LAUNCH_FLAG}" for key in unique]

    saved = save_import_pack(pack, dest_dir=imports_root)
    counts = {
        kind: len(pack.get(kind) or [])
        for kind in TABLE_FOR_KIND
        if pack.get(kind)
    }
    result: Dict[str, Any] = {
        "status": "preview",
        "wrote": False,
        "pack_path": str(saved),
        "counts": counts,
        "pack_only_kinds": sorted(PACK_ONLY_KINDS),
        "note": PACK_ONLY_NOTE,
    }
    if launch_risk:
        result["launch_risk"] = launch_risk
        result["status"] = "refused"
        result["error"] = (
            "Tool config contains command, args or env. Saved as a JSON pack only. "
            + LAUNCH_FLAG + "."
        )
    if not confirm:
        result["note"] = (
            "JSON pack saved. Personas and prompts insert into Studio only with "
            "confirm=true and MSTY_ALLOW_STUDIO_WRITES=1 in the server environment. "
            + PACK_ONLY_NOTE
        )
        return result

    if launch_risk:
        return result

    if not studio_writes_allowed():
        result["status"] = "refused"
        result["error"] = ENV_OFF_NOTE
        return result

    db_kinds_present = [kind for kind in DB_KINDS if pack.get(kind)]
    pack_only_present = [kind for kind in PACK_ONLY_KINDS if pack.get(kind)]
    if pack_only_present and not db_kinds_present:
        result["status"] = "pack_only"
        result["skipped"] = pack_only_present
        result["error"] = PACK_ONLY_NOTE
        return result

    db_path = resolve_database_path(database_path)
    if not db_path:
        result["status"] = "refused"
        result["error"] = "Studio database not found"
        return result
    if studio_holds_live_database(db_path):
        result["status"] = "refused"
        result["error"] = (
            "Msty Studio appears to be running and holding the live database. "
            "Quit Studio, or import the JSON pack in Persona Studio / Toolbox."
        )
        result["database"] = str(db_path)
        return result

    backup = backup_database(db_path, dest_dir=backup_root)
    applied: Dict[str, List[str]] = {}
    skipped: List[str] = list(pack_only_present)
    conn = connect_writable(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for kind in DB_KINDS:
            table = TABLE_FOR_KIND[kind]
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
        conn.execute("COMMIT")
    except sqlite3.OperationalError as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        conn.close()
        locked = "locked" in str(exc).lower()
        return {
            "status": "refused",
            "wrote": False,
            "pack_path": str(saved),
            "backup_path": str(backup),
            "error": "Studio database is locked. Quit Msty Studio and retry."
            if locked
            else str(exc),
        }
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        conn.close()
        return {
            "status": "error",
            "wrote": False,
            "pack_path": str(saved),
            "backup_path": str(backup),
            "error": str(exc),
        }
    conn.close()
    wrote = bool(applied)
    return {
        "status": "applied" if wrote else "pack_only",
        "wrote": wrote,
        "pack_path": str(saved),
        "backup_path": str(backup),
        "database": str(db_path),
        "applied": applied,
        "skipped": skipped,
        "counts": {k: len(v) for k, v in applied.items()},
        "note": PACK_ONLY_NOTE,
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
