"""Confirmed Studio writes: JSON pack always. SQLite only for safe kinds.

Tools, toolsets and skills are never inserted into Studio SQLite. Personas
and prompts need ``confirm=true`` and ``MSTY_ALLOW_STUDIO_WRITES=1`` in the
server environment. MCP tools must not expose ``database_path``.

Studio 3.0 writes have extra gates (see verify_3x_write_target): the target
must be the active workspace's current database, its persona and prompt tables
must match a schema verified on a real Studio 3.0 install, Studio must not be
running, and every inserted row is read back inside the transaction before
COMMIT.
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

from src import studio_storage
from src.paths import (
    LAYOUT_SUPPORTED,
    LAYOUT_UNSUPPORTED,
    MstyInstallation,
    UnsupportedStudioLayout,
    detect_msty_installation,
    is_process_running,
    is_studio_3,
    unknown_version_write_message,
    unsupported_layout_message,
)
from src.safe_io import secure_create, secure_mkdir, secure_write
from src.tooling import (
    DESCRIPTION_MAX,
    NAME_MAX,
    PROMPT_TEXT_MAX,
    SYSTEM_PROMPT_MAX,
    TITLE_MAX,
    sanitise_color_icon,
)

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


# Columns Studio 3.0.0 fills on a persona or prompt it creates (gold rows in
# tests/fixtures/studio/studio-gold-rows.json). A 3.x write needs them all
# present, and reads them back non-NULL before COMMIT.
GOLD_3X_COLUMNS = {
    "personas": (
        "id", "name", "systemPrompt", "folderId", "colorIcon", "extras",
        "activeVersionId", "createdAt", "partialSelectableAttachments",
    ),
    "personaVersions": (
        "id", "personaId", "versionNumber", "name", "colorIcon", "systemPrompt",
        "extras", "createdAt", "partialSelectableAttachments", "tags",
    ),
    "promptsLibraryPrompts": (
        "id", "title", "text", "folderId", "source", "isBookmarked", "createdAt",
    ),
    "promptsVersions": (
        "id", "promptId", "versionNumber", "title", "text", "changelog", "createdAt",
    ),
}
_GOLD_3X_JSON = {
    "personas": ("systemPrompt", "colorIcon", "extras", "partialSelectableAttachments"),
    "personaVersions": ("systemPrompt", "colorIcon", "extras", "partialSelectableAttachments", "tags"),
}
PROMPT_SOURCE_CUSTOM = "custom"
PROMPT_INITIAL_CHANGELOG = "Initial version"


class WriteVerificationFailed(RuntimeError):
    """Read-back inside the write transaction did not match a Studio-created row."""


class WriteRejected(ValueError):
    """Insert refused for a length cap or similar caller error."""


class DuplicatePersonaName(WriteRejected):
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


def studio_write_block(install: Optional[MstyInstallation] = None) -> Optional[str]:
    """Return a refusal message unless the detected Studio version is a supported 2.x.

    Writes fail closed on Studio 3.x and on an unknown or unreadable version.
    """
    install = install or detect_msty_installation()
    if install.layout_status == LAYOUT_UNSUPPORTED:
        return unsupported_layout_message(install.version)
    if install.layout_status != LAYOUT_SUPPORTED:
        return unknown_version_write_message()
    return None


def resolve_database_path(explicit: Optional[str] = None) -> Optional[Path]:
    """Resolve the Studio SQLite path for writes.

    Raises UnsupportedStudioLayout when the version gate refuses. An explicit
    path does not bypass the gate.
    """
    install = detect_msty_installation()
    blocked = studio_write_block(install)
    if blocked:
        raise UnsupportedStudioLayout(blocked)
    if is_studio_3(install.version):
        return verify_3x_write_target(install, explicit)
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    if install.database_path:
        candidate = Path(install.database_path)
        return candidate if candidate.exists() else None
    return None


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def verify_3x_write_target(install: MstyInstallation, explicit: Optional[str] = None) -> Path:
    """Return the only database a Studio 3.0 write may touch, or raise.

    The target is the active workspace's current database. An explicit path
    must be that same file, so a stale browser-storage copy or another
    workspace can never be written. The persona and prompt tables must match
    a shape verified on a real Studio 3.0 install, with the matching latest
    migration.
    """
    if install.layout not in ("studio_3x_file_storage", "studio_3x_browser_storage") or not install.database_path:
        raise UnsupportedStudioLayout(
            "Studio 3.0 writes need a readable active workspace database. "
            + (install.schema_note or "None was found.")
        )
    live = Path(install.database_path)
    if explicit:
        target = Path(explicit)
        stale = any(
            _same_file(target, Path(copy["path"]))
            for copy in install.stale_copies or []
            if isinstance(copy, dict) and copy.get("path")
        )
        if stale or not _same_file(target, live):
            raise UnsupportedStudioLayout(
                "On Studio 3.0 writes go only to the active workspace's current database. "
                + ("This path is a stale copy that Studio no longer reads." if stale else "This path is not it.")
            )
    if not live.is_file():
        raise UnsupportedStudioLayout("Studio 3.0 active workspace database not found.")
    conn = studio_storage.connect_readonly(live)
    try:
        shape = studio_storage.tables_fingerprint(conn, studio_storage.WRITE_TABLES)
        migration = studio_storage.latest_migration(conn)
        missing = [
            f"{table}.{col}"
            for table, cols in GOLD_3X_COLUMNS.items()
            for col in cols
            if col not in table_columns(conn, table)
        ]
    finally:
        conn.close()
    if shape not in studio_storage.VERIFIED_3X_WRITE_FINGERPRINTS:
        raise UnsupportedStudioLayout(
            "Studio 3.0 persona and prompt tables do not match a verified schema, so writes "
            "are refused. Import the JSON pack in Persona Studio or Prompts Studio instead."
        )
    if migration not in studio_storage.VERIFIED_3X_MIGRATIONS:
        raise UnsupportedStudioLayout(
            "Studio 3.0 database has an unverified latest migration, so writes are refused. "
            "Import the JSON pack in Studio instead."
        )
    if missing:
        raise UnsupportedStudioLayout(
            "Studio 3.0 database is missing columns Studio fills on a new row: "
            + ", ".join(missing)
        )
    return live


def _read_back_3x(conn: sqlite3.Connection, applied: Dict[str, List[str]]) -> None:
    """Check inserted rows match Studio 3.0's own rows before COMMIT."""

    def row(table: str, where: str, value: str) -> Dict[str, Any]:
        found = conn.execute(
            f'SELECT rowid AS _rowid, * FROM "{table}" WHERE "{where}" = ?', (value,)
        ).fetchall()
        if len(found) != 1:
            raise WriteVerificationFailed(f"{table} row for {value} not found exactly once")
        data = dict(found[0])
        for col in GOLD_3X_COLUMNS[table]:
            if data.get(col) is None:
                raise WriteVerificationFailed(f"{table}.{col} is NULL")
        for col in _GOLD_3X_JSON.get(table, ()):
            try:
                json.loads(data[col])
            except (TypeError, ValueError) as exc:
                raise WriteVerificationFailed(f"{table}.{col} is not valid JSON") from exc
        return data

    rowids: Dict[str, set] = {}
    for persona_id in applied.get("personas", []):
        persona = row("personas", "id", persona_id)
        prompt = json.loads(persona["systemPrompt"])
        if not isinstance(prompt, dict) or not isinstance(prompt.get("text"), str) or prompt.get("mode") not in _VALID_PROMPT_MODES:
            raise WriteVerificationFailed("personas.systemPrompt is not {text, mode}")
        version = row("personaVersions", "id", persona["activeVersionId"])
        if version["personaId"] != persona_id:
            raise WriteVerificationFailed("personaVersions row does not link to the persona")
        rowids.setdefault("personas", set()).add(persona["_rowid"])
        rowids.setdefault("personaVersions", set()).add(version["_rowid"])
    for prompt_id in applied.get("prompts", []):
        prompt = row("promptsLibraryPrompts", "id", prompt_id)
        if prompt["source"] != PROMPT_SOURCE_CUSTOM:
            raise WriteVerificationFailed("promptsLibraryPrompts.source is not custom")
        version = row("promptsVersions", "promptId", prompt_id)
        if version["text"] != prompt["text"]:
            raise WriteVerificationFailed("promptsVersions text does not match the prompt")
        rowids.setdefault("promptsLibraryPrompts", set()).add(prompt["_rowid"])
        rowids.setdefault("promptsVersions", set()).add(version["_rowid"])
    for table, ids in rowids.items():
        for violation in conn.execute(f'PRAGMA foreign_key_check("{table}")'):
            if violation[1] in ids:
                raise WriteVerificationFailed(f"{table} row breaks a foreign key")
    check = conn.execute("PRAGMA quick_check").fetchone()
    if not check or str(check[0]).lower() != "ok":
        raise WriteVerificationFailed("PRAGMA quick_check did not return ok")


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

    Process name live-observed on macOS: MstyStudio (app and Helper children),
    and on Linux: mstystudio (the match is case-insensitive). On Studio 3.0 any
    running Studio refuses, whichever database is targeted.
    is_process_running fails closed, so an unknown probe refuses the write.
    """
    if is_studio_3(detect_msty_installation().version):
        return is_process_running("MstyStudio")
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


def _length_error(field: str, length: int, maximum: int) -> WriteRejected:
    return WriteRejected(
        f"{field} is {length} characters; maximum is {maximum}."
    )


def check_persona_item(item: Dict[str, Any]) -> None:
    name = str(item.get("name") or "").strip()
    if len(name) > NAME_MAX:
        raise _length_error("persona name", len(name), NAME_MAX)
    description = item.get("description")
    if isinstance(description, str) and len(description) > DESCRIPTION_MAX:
        raise _length_error("persona description", len(description), DESCRIPTION_MAX)
    system = item.get("systemPrompt") or item.get("system_prompt") or ""
    if isinstance(system, dict):
        text = str(system.get("text") or "")
    else:
        raw = str(system)
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict) and "text" in parsed:
            text = str(parsed.get("text") or "")
        else:
            text = raw
    if len(text) > SYSTEM_PROMPT_MAX:
        raise _length_error("system prompt", len(text), SYSTEM_PROMPT_MAX)


def check_prompt_item(item: Dict[str, Any]) -> None:
    title = str(item.get("title") or item.get("name") or "").strip()
    if len(title) > TITLE_MAX:
        raise _length_error("prompt title", len(title), TITLE_MAX)
    text = item.get("text") or item.get("prompt") or ""
    text = str(text)
    if len(text) > PROMPT_TEXT_MAX:
        raise _length_error("prompt text", len(text), PROMPT_TEXT_MAX)


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
    check_persona_item(item)
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
    color = sanitise_color_icon(item.get("colorIcon"))
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
        # Gold Studio 2.9.12 row: the version mirrors name, colorIcon and
        # description from the persona. Remaining unlisted columns stay NULL.
        version_row = {
            "id": version_id,
            "personaId": persona_id,
            "versionNumber": 1,
            "name": name,
            "colorIcon": color,
            "systemPrompt": system_blob,
            "extras": extras,
            "createdAt": created,
            "partialSelectableAttachments": DEFAULT_ATTACHMENTS,
            "tags": DEFAULT_TAGS,
        }
        if "description" in persona_row:
            version_row["description"] = persona_row["description"]
        insert_row(
            conn, "personaVersions", _row_for_columns(version_row, version_columns)
        )
    return persona_id


def _insert_prompt(
    conn: sqlite3.Connection, item: Dict[str, Any], studio_3: bool = False
) -> str:
    columns = table_columns(conn, "promptsLibraryPrompts")
    title = str(item.get("title") or item.get("name") or "").strip()
    text = item.get("text") or item.get("prompt")
    if not title:
        raise ValueError("prompt needs title")
    if not text:
        raise ValueError("prompt needs text")
    check_prompt_item(item)
    folder_id = resolve_prompt_folder_id(conn)
    if not folder_id:
        raise RuntimeError("prompt folder missing")
    prompt_id = new_ulid()
    created = _sql_now()
    extras = _json_text(item.get("extras"), DEFAULT_EXTRAS)
    # Studio marks prompts it creates as source "custom". The column default
    # "ootb" is for prompts Studio ships.
    prompt_row = {
        "id": prompt_id,
        "title": title,
        "text": text,
        "folderId": folder_id,
        "source": PROMPT_SOURCE_CUSTOM,
        "activeVersionId": prompt_id,
        "createdAt": created,
        "extras": extras,
    }
    version_id = prompt_id
    if studio_3:
        # Gold Studio 3.0.0 row: no activeVersionId, extras NULL unless given,
        # and the version has its own id and an "Initial version" changelog.
        version_id = new_ulid()
        prompt_row["activeVersionId"] = None
        prompt_row["isBookmarked"] = 0
        prompt_row["extras"] = _json_text(item.get("extras"))
    insert_row(conn, "promptsLibraryPrompts", _row_for_columns(prompt_row, columns))
    if _table_exists(conn, "promptsVersions"):
        version_columns = table_columns(conn, "promptsVersions")
        version_row = {
            "id": version_id,
            "promptId": prompt_id,
            "versionNumber": 1,
            "title": title,
            "text": text,
            "createdAt": created,
            "extras": prompt_row["extras"],
        }
        if studio_3:
            version_row["changelog"] = PROMPT_INITIAL_CHANGELOG
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

    try:
        for item in pack.get("personas") or []:
            if isinstance(item, dict):
                check_persona_item(item)
        for item in pack.get("prompts") or []:
            if isinstance(item, dict):
                check_prompt_item(item)
    except WriteRejected as exc:
        return {
            "status": "refused",
            "wrote": False,
            "error": str(exc),
        }
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

    studio_3 = is_studio_3(detect_msty_installation().version)
    try:
        db_path = resolve_database_path(database_path)
    except UnsupportedStudioLayout as exc:
        result["status"] = "refused"
        result["error"] = str(exc)
        return result
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
                    ids.append(_insert_prompt(conn, item, studio_3=studio_3))
            if ids:
                applied[kind] = ids
        if studio_3:
            _read_back_3x(conn, applied)
        conn.execute("COMMIT")
    except WriteRejected as exc:
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
    except WriteVerificationFailed as exc:
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
            "error": f"Studio 3.0 read-back failed, nothing was written: {exc}",
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
