"""Msty Studio workspace storage discovery (Studio 2.x and 3.0).

Verified on disposable Linux installs of Studio 2.9.12 and 3.0.0 (see
docs/msty-3-layout.md). macOS and Windows use the same layout under the
Electron userData folder (MstyStudio), which is inferred, not live-tested.

Every workspace is one SQLite file named msty.cloud.db. Studio keeps it in
one of two places:

- browser storage: Chromium's origin-private file system under
  ``<userData>/File System``. Studio 2.x always uses this. The Home workspace
  is the first blob, ``File System/000/t/00/00000000``. Studio 3.0 keeps using
  it after an upgrade until the user enables file-based storage.
- file-based storage (Studio 3.0): ``<userData>/data/workspaces/<slug>/msty.cloud.db``,
  or ``<parentPath>/<slug>/msty.cloud.db`` when ``data/workspace-locations.json``
  names a custom parent folder for that slug.

Enabling file-based storage copies the database and leaves the browser copy
behind, so the old blob becomes a stale copy. Moving a workspace to another
folder deletes the source. The workspace registry is the ``workspaces`` table
in the Home database, with ``isActive = 1`` on the active workspace.

Nothing here writes. Every database open is read-only.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DB_FILE_NAME = "msty.cloud.db"
DEFAULT_SLUG = "default"
DEFAULT_WORKSPACE_ID = "__MSTY__DEFAULT__WORKSPACE__"
WORKSPACE_MARKER = ".msty.workspace"
LOCATIONS_FILE = "workspace-locations.json"
LOCATIONS_MAX_BYTES = 1_000_000

STORAGE_NATIVE = "file"
STORAGE_BROWSER = "browser"
STORAGE_UNAVAILABLE = "unavailable"
STORAGE_UNMAPPED = "browser_unmapped"

_SLUG_RE = re.compile(r"^[\w-]+$")

# Full-schema fingerprints captured from Studio-created databases.
KNOWN_SCHEMA_FINGERPRINTS: Dict[str, str] = {
    "014febe701c3a311cf3f915bbce882ca15f60377eec16a508c4499191598a6f8": "2.9.12",
    "8006b6fe2940f2d5b6b5d9d4992b704aa3b3b1b2230278b34310b129f319a18e": "3.0.0",
}
# Latest __drizzle_migrations hash per verified Studio release.
KNOWN_LATEST_MIGRATIONS: Dict[str, str] = {
    "3167d24f06196a4b55ab08900d5f9eb86089357a7865d2d7cd0105f2490f1b89": "2.9.12",
    "dfd015ce2d3143d02275131190db973f05a5f7af4cf9f08995bc7f3d38576ad0": "3.0.0",
}

# Tables a persona or prompt write touches. Their shape is pinned for 3.x writes.
WRITE_TABLES = (
    "personas",
    "personaVersions",
    "personaFolders",
    "promptsLibraryPrompts",
    "promptsVersions",
    "promptsLibraryFolders",
)


# WRITE_TABLES fingerprint per verified 3.x release. A 3.x write refuses on any
# other shape, so a schema change in a later 3.0.x patch fails closed.
VERIFIED_3X_WRITE_FINGERPRINTS: Dict[str, str] = {
    "6349bbbc21b2c9ff2fcf933fd7896c0586037b1ca6a1c305f1c9fbaffc112237": "3.0.0",
}
VERIFIED_3X_MIGRATIONS = frozenset({"dfd015ce2d3143d02275131190db973f05a5f7af4cf9f08995bc7f3d38576ad0"})


class WorkspaceNotFound(LookupError):
    """Raised when a workspace name, slug or id does not match the registry."""


class WorkspaceUnreadable(RuntimeError):
    """Raised when a workspace exists but this MCP cannot read its database."""


@dataclass
class WorkspaceInfo:
    id: Optional[str]
    name: Optional[str]
    slug: str
    is_active: bool = False
    storage: str = STORAGE_UNAVAILABLE
    database_path: Optional[str] = None
    custom_location: Optional[str] = None
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StorageLayout:
    home_storage: Optional[str] = None
    home_database: Optional[str] = None
    workspaces: List[WorkspaceInfo] = field(default_factory=list)
    active_slug: Optional[str] = None
    stale_copies: List[Dict[str, str]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def uses_file_storage(self) -> bool:
        return any(w.storage == STORAGE_NATIVE for w in self.workspaces) or (
            self.home_storage == STORAGE_NATIVE
        )

    def active(self) -> Optional[WorkspaceInfo]:
        for ws in self.workspaces:
            if ws.slug == self.active_slug:
                return ws
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "home_storage": self.home_storage,
            "home_database": self.home_database,
            "active_workspace": self.active_slug,
            "workspaces": [w.to_dict() for w in self.workspaces],
            "stale_copies": list(self.stale_copies),
            "notes": list(self.notes),
        }


def is_sqlite_file(path: Optional[Path]) -> bool:
    if not path:
        return False
    try:
        if not path.is_file():
            return False
        with path.open("rb") as fh:
            return fh.read(16).startswith(b"SQLite format 3")
    except OSError:
        return False


def native_root(data_path: Path) -> Path:
    return data_path / "data"


def load_workspace_locations(data_path: Path) -> Dict[str, Path]:
    """Read data/workspace-locations.json the way Studio does.

    Only slug-shaped keys with an absolute parentPath are kept. A missing or
    malformed file means every workspace uses the default folder.
    """
    file = native_root(data_path) / LOCATIONS_FILE
    try:
        if not file.is_file() or file.stat().st_size > LOCATIONS_MAX_BYTES:
            return {}
        stored = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(stored, dict):
        return {}
    out: Dict[str, Path] = {}
    for slug, entry in stored.items():
        if not isinstance(slug, str) or not _SLUG_RE.match(slug):
            continue
        parent = entry.get("parentPath") if isinstance(entry, dict) else None
        if isinstance(parent, str) and Path(parent).is_absolute():
            out[slug] = Path(parent)
    return out


def native_database_path(data_path: Path, slug: str, locations: Dict[str, Path]) -> Path:
    parent = locations.get(slug) or (native_root(data_path) / "workspaces")
    return parent / slug / DB_FILE_NAME


def connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=1.0)
    conn.row_factory = sqlite3.Row
    return conn


def _registry_rows(home_db: Path) -> List[Dict[str, Any]]:
    try:
        conn = connect_readonly(home_db)
    except sqlite3.Error:
        return []
    try:
        cols = {r[1] for r in conn.execute('PRAGMA table_info("workspaces")')}
        if not {"slug"} <= cols:
            return []
        wanted = [c for c in ("id", "name", "slug", "isActive", "createdAt") if c in cols]
        quoted = ", ".join(f'"{c}"' for c in wanted)
        order = ' ORDER BY "createdAt" ASC' if "createdAt" in cols else ""
        return [dict(r) for r in conn.execute(f'SELECT {quoted} FROM "workspaces"{order}')]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def discover(data_path: Optional[Path], browser_home_db: Optional[Path]) -> StorageLayout:
    """Map every registered workspace to the database Studio currently uses."""
    layout = StorageLayout()
    if not data_path:
        return layout
    locations = load_workspace_locations(data_path)
    home_native = native_database_path(data_path, DEFAULT_SLUG, locations)
    browser_ok = is_sqlite_file(browser_home_db)

    if is_sqlite_file(home_native):
        layout.home_storage = STORAGE_NATIVE
        layout.home_database = str(home_native)
        if browser_ok:
            layout.stale_copies.append(
                {
                    "path": str(browser_home_db),
                    "reason": (
                        "Home moved to file-based storage. Studio no longer updates this "
                        "browser-storage copy, so it is not read."
                    ),
                }
            )
    elif browser_ok:
        layout.home_storage = STORAGE_BROWSER
        layout.home_database = str(browser_home_db)
    else:
        return layout

    rows = _registry_rows(Path(layout.home_database))
    if not any(r.get("slug") == DEFAULT_SLUG for r in rows):
        rows.insert(0, {"id": DEFAULT_WORKSPACE_ID, "name": "Home", "slug": DEFAULT_SLUG, "isActive": 0})
    active_slug: Optional[str] = None
    for row in rows:
        slug = str(row.get("slug") or "")
        if not _SLUG_RE.match(slug):
            continue
        info = WorkspaceInfo(
            id=row.get("id"),
            name=row.get("name"),
            slug=slug,
            is_active=bool(row.get("isActive")),
            custom_location=str(locations[slug]) if slug in locations else None,
        )
        if slug == DEFAULT_SLUG:
            info.storage = layout.home_storage or STORAGE_UNAVAILABLE
            info.database_path = layout.home_database
        else:
            candidate = native_database_path(data_path, slug, locations)
            if is_sqlite_file(candidate):
                info.storage = STORAGE_NATIVE
                info.database_path = str(candidate)
            elif slug in locations:
                info.storage = STORAGE_UNAVAILABLE
                info.note = f"Custom location {candidate.parent} is missing or unreadable."
            else:
                info.storage = STORAGE_UNMAPPED
                info.note = (
                    "Workspace is in browser storage. This MCP reads only the Home workspace "
                    "from browser storage. Enable file-based storage for it in Studio 3.0 "
                    "Settings, Data, to read it here."
                )
        if info.is_active and active_slug is None:
            active_slug = slug
        layout.workspaces.append(info)
    layout.active_slug = active_slug or DEFAULT_SLUG
    for ws in layout.workspaces:
        ws.is_active = ws.slug == layout.active_slug
    return layout


def resolve_workspace(layout: StorageLayout, workspace: Optional[str]) -> WorkspaceInfo:
    """Pick a workspace by slug, id or name (case-insensitive). None means active."""
    if not layout.workspaces:
        raise WorkspaceNotFound("No Studio workspace database was found.")
    if workspace is None or not str(workspace).strip():
        chosen = layout.active()
    else:
        needle = str(workspace).strip()
        folded = needle.casefold()
        chosen = next(
            (
                w
                for w in layout.workspaces
                if needle in (w.slug, w.id) or (w.name or "").casefold() == folded
            ),
            None,
        )
        if chosen is None:
            available = [w.name or w.slug for w in layout.workspaces]
            raise WorkspaceNotFound(
                f"Workspace {needle!r} not found. Available: {', '.join(available)}"
            )
    if chosen is None or not chosen.database_path:
        label = (chosen.name or chosen.slug) if chosen else "active workspace"
        reason = chosen.note if chosen and chosen.note else "Its database was not found."
        raise WorkspaceUnreadable(f"Workspace {label!r} cannot be read. {reason}")
    return chosen


def _table_shape(conn: sqlite3.Connection, table: str) -> List[List[Any]]:
    quoted = '"' + table.replace('"', '""') + '"'
    return [
        [r[1], str(r[2]).lower(), int(r[3]), r[4], int(r[5])]
        for r in conn.execute(f"PRAGMA table_info({quoted})")
    ]


def _hash(payload: Any) -> str:
    text = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tables_fingerprint(conn: sqlite3.Connection, tables: Optional[Iterable[str]] = None) -> str:
    """sha256 over table names and PRAGMA table_info rows. Missing tables hash as absent."""
    if tables is None:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
    else:
        names = sorted(tables)
    return _hash({name: _table_shape(conn, name) for name in names})


def latest_migration(conn: sqlite3.Connection) -> Optional[str]:
    try:
        row = conn.execute(
            'SELECT hash FROM "__drizzle_migrations" ORDER BY created_at DESC LIMIT 1'
        ).fetchone()
    except sqlite3.Error:
        return None
    return str(row[0]) if row and row[0] else None


def schema_fingerprint(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Layout fingerprint of one workspace database, matched to a verified release."""
    full = tables_fingerprint(conn)
    latest = latest_migration(conn)
    return {
        "schema_sha256": full,
        "latest_migration": latest,
        "matches_release": KNOWN_SCHEMA_FINGERPRINTS.get(full),
        "migration_release": KNOWN_LATEST_MIGRATIONS.get(latest or ""),
    }


def fingerprint_path(path: Path) -> Dict[str, Any]:
    conn = connect_readonly(path)
    try:
        return schema_fingerprint(conn)
    finally:
        conn.close()
