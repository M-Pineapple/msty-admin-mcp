"""Confirmed Studio writes: JSON pack always. SQLite only for safe kinds.

Tools, toolsets and skills are never inserted into Studio SQLite. Personas
and prompts need ``confirm=true`` and ``MSTY_ALLOW_STUDIO_WRITES=1`` in the
server environment. MCP tools must not expose ``database_path``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.paths import detect_msty_installation, is_process_running
from src.safe_io import secure_create, secure_mkdir, secure_write

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

ORPHANAGE_FOLDER_ID = "__MSTY__PERSONA__ORPHANAGE__FOLDER__"
DEFAULT_COLOR_ICON = '{"name":"tabler:user-scan"}'
DEFAULT_EXTRAS = "{}"
DEFAULT_PERSONA_EXTRAS = '{"attachmentsStudioDynamicSelection":null}'
DEFAULT_ATTACHMENTS = "[]"
DEFAULT_TAGS = "[]"
DEFAULT_SYSTEM_PROMPT_MODE = "append"
_VALID_PROMPT_MODES = frozenset({"append", "replace"})
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

NO_PERSONA_FOLDER = (
    "No personaFolders row. Personas are saved as a JSON pack only. "
    "This MCP does not create folders."
)
NO_PROMPT_FOLDER = (
    "No promptsLibraryFolders row. Prompts are saved as a JSON pack only. "
    "This MCP does not create folders. Add a folder in Msty, then retry."
)


class DuplicatePersonaName(ValueError):
    """Raised when a persona name is already in the Studio database."""

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


def _unique_stamp() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond:06d}Z-{uuid.uuid4().hex[:8]}"


def _sql_now() -> str:
    """Studio 2.9 stores createdAt as UTC 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def new_ulid() -> str:
    """26-character Crockford ULID. Matches Studio 2.9 persona ids."""
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    entropy = int.from_bytes(os.urandom(10), "big")
    value = (timestamp_ms << 80) | entropy
    chars = ["0"] * 26
    for index in range(25, -1, -1):
        chars[index] = _CROCKFORD[value & 31]
        value >>= 5
    return "".join(chars)


def save_import_pack(pack: Dict[str, Any], dest_dir: Optional[Path] = None) -> Path:
    folder = dest_dir or imports_dir()
    secure_mkdir(folder)
    payload = json.dumps(pack, indent=2, default=str) + "\n"
    last_error: Optional[Exception] = None
    for _ in range(8):
        path = folder / f"pack-{_unique_stamp()}.json"
        try:
            return secure_create(path, payload)
        except FileExistsError as exc:
            last_error = exc
    raise RuntimeError("could not allocate a unique import pack name") from last_error


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
    dest = folder / f"{database_path.name}-{_unique_stamp()}.bak"
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


def _json_text(value: Any, default: Optional[str] = None) -> Optional[str]:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    text = str(value)
    return text if text else default


def _system_prompt_blob(system: Any, mode: Optional[str] = None) -> str:
    """Studio 2.9 stores systemPrompt as compact JSON {text, mode}.

    Default mode is append. Caller mode replace is honoured. An already-wrapped
    JSON object with a text key keeps its mode unless the caller overrides it.
    """
    chosen = str(mode or "").strip().lower()
    text: Optional[str] = None
    if isinstance(system, dict) and "text" in system:
        text = system.get("text")
        if not chosen:
            chosen = str(system.get("mode") or "").strip().lower()
    else:
        raw = "" if system is None else str(system)
        parsed: Any = None
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict) and "text" in parsed:
            text = parsed.get("text")
            if not chosen:
                chosen = str(parsed.get("mode") or "").strip().lower()
        else:
            text = raw
    if chosen not in _VALID_PROMPT_MODES:
        chosen = DEFAULT_SYSTEM_PROMPT_MODE
    return json.dumps(
        {"text": "" if text is None else str(text), "mode": chosen},
        separators=(",", ":"),
    )


def _model_listed(parsed: Any, model: str) -> bool:
    if isinstance(parsed, dict):
        return model in parsed
    if isinstance(parsed, list):
        for item in parsed:
            if item == model:
                return True
            if isinstance(item, dict) and item.get("id") == model:
                return True
    return False


def lookup_model_provider_id(conn: sqlite3.Connection, model: str) -> Optional[str]:
    """Return languageModelsProviders.id for a model, or None if unmapped.

    Studio stores partialModelInfo.providerId as languageModelsProviders.id.
    languageModelConfigs is (providerId, modelId). providers.models is a JSON
    list or object when present. The live 2.9.12 copy had empty configs and
    NULL models, so a typical Local AI name stays unmapped.
    """
    cleaned = (model or "").strip()
    if not cleaned:
        return None
    if _table_exists(conn, "languageModelConfigs"):
        row = conn.execute(
            "SELECT providerId FROM languageModelConfigs WHERE modelId = ? LIMIT 1",
            (cleaned,),
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    if _table_exists(conn, "languageModelsProviders"):
        for rec in conn.execute("SELECT id, models FROM languageModelsProviders"):
            raw = rec[1]
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if _model_listed(parsed, cleaned):
                return str(rec[0])
    return None


def _first_folder_id(
    conn: sqlite3.Connection, table: str, preferred_id: Optional[str] = None
) -> Optional[str]:
    if not _table_exists(conn, table):
        return None
    columns = table_columns(conn, table)
    if "id" not in columns:
        return None
    if preferred_id:
        row = conn.execute(
            f'SELECT id FROM "{table}" WHERE id = ? LIMIT 1', (preferred_id,)
        ).fetchone()
        if row:
            return str(row[0])
    if "createdAt" in columns:
        row = conn.execute(
            f'SELECT id FROM "{table}" ORDER BY createdAt ASC, id ASC LIMIT 1'
        ).fetchone()
    else:
        row = conn.execute(f'SELECT id FROM "{table}" ORDER BY id ASC LIMIT 1').fetchone()
    return str(row[0]) if row else None


def resolve_persona_folder_id(conn: sqlite3.Connection) -> Optional[str]:
    return _first_folder_id(conn, "personaFolders", ORPHANAGE_FOLDER_ID)


def resolve_prompt_folder_id(conn: sqlite3.Connection) -> Optional[str]:
    return _first_folder_id(conn, "promptsLibraryFolders")


def _row_for_columns(row: Dict[str, Any], columns: Sequence[str]) -> Dict[str, Any]:
    return {key: value for key, value in row.items() if key in columns}


def _insert_persona(
    conn: sqlite3.Connection, item: Dict[str, Any], notes: List[str]
) -> str:
    columns = table_columns(conn, "personas")
    name = str(item.get("name") or "").strip()
    system = item.get("systemPrompt") or item.get("system_prompt")
    if not name:
        raise ValueError("persona needs name")
    if not system:
        raise ValueError("persona needs systemPrompt")
    if conn.execute("SELECT 1 FROM personas WHERE name = ? LIMIT 1", (name,)).fetchone():
        raise DuplicatePersonaName(
            f"persona name {name!r} already exists. Choose a different name."
        )
    folder_id = resolve_persona_folder_id(conn)
    if not folder_id:
        raise RuntimeError("persona folder missing")
    persona_id = new_ulid()
    version_id = new_ulid()
    created = _sql_now()
    color = _json_text(item.get("colorIcon"), DEFAULT_COLOR_ICON)
    extras = DEFAULT_PERSONA_EXTRAS
    system_blob = _system_prompt_blob(system, item.get("mode"))
    model = str(item.get("model") or "").strip()
    partial_text = None
    if model and "partialModelInfo" in columns:
        provider_id = lookup_model_provider_id(conn, model)
        if provider_id:
            partial_text = json.dumps(
                {"id": model, "providerId": provider_id}, separators=(",", ":")
            )
        else:
            notes.append(
                f"partialModelInfo left null for persona {name!r}: no "
                f"languageModelConfigs.modelId or languageModelsProviders.models "
                f"entry for {model!r}."
            )
    persona_row = {
        "id": persona_id,
        "name": name,
        "systemPrompt": system_blob,
        "folderId": folder_id,
        "colorIcon": color,
        "extras": extras,
        "activeVersionId": version_id,
        "createdAt": created,
        "partialModelInfo": partial_text,
        "partialSelectableAttachments": DEFAULT_ATTACHMENTS,
    }
    description = item.get("description")
    if isinstance(description, str) and description.strip():
        persona_row["description"] = description.strip()
    insert_row(conn, "personas", _row_for_columns(persona_row, columns))
    if _table_exists(conn, "personaVersions"):
        version_columns = table_columns(conn, "personaVersions")
        # Gold Studio 2.9.12 row: name is NOT NULL; remaining unlisted columns stay NULL.
        version_row = {
            "id": version_id,
            "personaId": persona_id,
            "versionNumber": 1,
            "name": name,
            "systemPrompt": system_blob,
            "extras": extras,
            "createdAt": created,
            "partialSelectableAttachments": DEFAULT_ATTACHMENTS,
            "tags": DEFAULT_TAGS,
        }
        insert_row(
            conn, "personaVersions", _row_for_columns(version_row, version_columns)
        )
    return persona_id


def _insert_prompt(conn: sqlite3.Connection, item: Dict[str, Any]) -> str:
    columns = table_columns(conn, "promptsLibraryPrompts")
    title = str(item.get("title") or item.get("name") or "").strip()
    text = item.get("text") or item.get("prompt")
    if not title:
        raise ValueError("prompt needs title")
    if not text:
        raise ValueError("prompt needs text")
    folder_id = resolve_prompt_folder_id(conn)
    if not folder_id:
        raise RuntimeError("prompt folder missing")
    prompt_id = new_ulid()
    created = _sql_now()
    extras = _json_text(item.get("extras"), DEFAULT_EXTRAS)
    prompt_row = {
        "id": prompt_id,
        "title": title,
        "text": text,
        "folderId": folder_id,
        "activeVersionId": prompt_id,
        "createdAt": created,
        "extras": extras,
    }
    insert_row(conn, "promptsLibraryPrompts", _row_for_columns(prompt_row, columns))
    if _table_exists(conn, "promptsVersions"):
        version_columns = table_columns(conn, "promptsVersions")
        version_row = {
            "id": prompt_id,
            "promptId": prompt_id,
            "versionNumber": 1,
            "title": title,
            "text": text,
            "createdAt": created,
            "extras": extras,
        }
        insert_row(
            conn, "promptsVersions", _row_for_columns(version_row, version_columns)
        )
    return prompt_id


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
    notes: List[str] = []
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
            ids: List[str] = []
            if kind == "personas":
                if not resolve_persona_folder_id(conn):
                    skipped.append("personas")
                    notes.append(NO_PERSONA_FOLDER)
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        raise ValueError("personas entries must be objects")
                    ids.append(_insert_persona(conn, item, notes))
            elif kind == "prompts":
                if not resolve_prompt_folder_id(conn):
                    skipped.append("prompts")
                    notes.append(NO_PROMPT_FOLDER)
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        raise ValueError("prompts entries must be objects")
                    ids.append(_insert_prompt(conn, item))
            if ids:
                applied[kind] = ids
        conn.execute("COMMIT")
    except DuplicatePersonaName as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        conn.close()
        return {
            "status": "refused",
            "wrote": False,
            "pack_path": str(saved),
            "backup_path": str(backup),
            "error": str(exc),
        }
    except sqlite3.IntegrityError as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        conn.close()
        message = str(exc)
        refused = "unique" in message.lower() or "not null" in message.lower()
        return {
            "status": "refused" if refused else "error",
            "wrote": False,
            "pack_path": str(saved),
            "backup_path": str(backup),
            "error": (
                "persona name already exists. Choose a different name."
                if "unique" in message.lower()
                else message
            ),
        }
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
    result_out: Dict[str, Any] = {
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
    if notes:
        result_out["notes"] = notes
        if not wrote and any(NO_PROMPT_FOLDER in note or NO_PERSONA_FOLDER in note for note in notes):
            result_out["error"] = notes[0]
    return result_out


def persona_pack(name: str, system_prompt: str, model: str) -> Dict[str, Any]:
    return {
        "personas": [
            {
                "name": name,
                "systemPrompt": system_prompt,
                "model": model,
            }
        ]
    }


def tool_pack(tool_data: Dict[str, Any]) -> Dict[str, Any]:
    return {"tools": [dict(tool_data)]}
