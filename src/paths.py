"""
Msty Studio path resolution and installation detection (Studio 2.4 to 3.0.x).

Resolves the real on-disk layout used by MstyStudio.app on macOS, including
the Chromium File System SQLite workspace database (Studio 2.x, and Studio 3.0
until file-based storage is enabled) and Studio 3.0 file-based workspace
storage (see src/studio_storage.py).
"""

from __future__ import annotations

import json
import platform
import plistlib
import re
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src import studio_storage

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore


DEFAULT_PORTS = {
    "local_ai": 11964,
    "mlx": 11973,
    "llamacpp": 11454,
    "vibe": 8317,
    "nexus": 11434,  # OpenAI-compatible gateway; overridden if detected
}


# Studio storage layouts this release can read. Studio 3.0.0 was verified on a
# disposable install (docs/msty-3-layout.md). Later 3.x releases stay refused
# until their storage is checked the same way.
STUDIO_3 = (3,)
SUPPORTED_MIN = (2, 4)
SUPPORTED_BELOW = (3, 1)
VERSION_MAX_LEN = 64
VERSION_PART_MAX_DIGITS = 6

LAYOUT_SUPPORTED = "supported"
LAYOUT_UNSUPPORTED = "unsupported"
LAYOUT_UNKNOWN = "unknown"

_VERSION_RE = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")


class UnsupportedStudioLayout(RuntimeError):
    """Raised when Studio storage access is refused for the detected version."""


def parse_version(value: Optional[str]) -> Optional[Tuple[int, ...]]:
    """Parse a dotted version into a numeric tuple, or None when unparseable.

    Numeric tuples order 10.0.0 above 2.9.12, which a string compare does not.
    """
    if not isinstance(value, str) or len(value) > VERSION_MAX_LEN:
        return None
    match = _VERSION_RE.match(value)
    if not match:
        return None
    parts = match.group(1).split(".")
    if any(len(part) > VERSION_PART_MAX_DIGITS for part in parts):
        return None
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def layout_status(version: Optional[str]) -> str:
    """Classify a Studio version.

    Supported only for 2.4 <= version < 3.1. Anything below 2.4 or at 3.1 and
    above is unsupported. A missing or unparseable version is unknown.
    """
    parsed = parse_version(version)
    if parsed is None:
        return LAYOUT_UNKNOWN
    if SUPPORTED_MIN <= parsed < SUPPORTED_BELOW:
        return LAYOUT_SUPPORTED
    return LAYOUT_UNSUPPORTED


def is_studio_3(version: Optional[str]) -> bool:
    """True for a parsed Studio 3.x or later version."""
    parsed = parse_version(version)
    return parsed is not None and parsed >= STUDIO_3


def _is_pre_2_4(version: Optional[str]) -> bool:
    parsed = parse_version(version)
    return parsed is not None and parsed < SUPPORTED_MIN


def unsupported_layout_message(version: Optional[str]) -> str:
    """User-facing refusal text for unsupported Studio versions."""
    if _is_pre_2_4(version):
        return (
            f"Msty Studio version {version} is older than 2.4. This MCP supports the Studio "
            "2.4 to 2.9.x storage layout only, so Studio reads and writes are disabled. "
            "Service, model and Nexus tools still work."
        )
    return (
        f"Msty Studio {version} detected. This MCP supports the Studio 2.4 to 2.9.x and "
        "3.0.x storage layouts only. Newer releases are refused until their storage is "
        "verified, so Studio reads and writes are disabled to avoid reading stale data or "
        "damaging your workspace. Service, model and Nexus tools still work. Track support "
        "in the msty-admin-mcp README."
    )


def unknown_version_file_storage_warning() -> str:
    """Warning for reads of Studio 3.0 file-based storage when the version is unknown."""
    return (
        "Msty Studio version could not be read. File-based workspace storage was found, so "
        "these results come from the active workspace in that storage (a Studio 3.0 layout). "
        "Check schema_fingerprint in get_msty_installation if a column is missing."
    )


def unknown_version_read_warning() -> str:
    """Warning added to Studio read results when the version cannot be read."""
    return (
        "Msty Studio version could not be read. These results come from the Studio 2.x "
        "database and may be a stale copy if this machine runs Studio 3.x."
    )


def unknown_version_write_message() -> str:
    """User-facing refusal text for Studio writes when the version cannot be read."""
    return (
        "Msty Studio version could not be read, so Studio writes are refused. Writes run only "
        "on a detected Studio 2.4 to 2.9.x or 3.0.x install, because Studio 3.0 changed "
        "workspace storage. On Windows and Linux the version cannot be read yet. "
        "Import the saved JSON pack in Persona Studio instead."
    )


@dataclass
class MstyInstallation:
    """Detected Msty Studio installation."""

    installed: bool = False
    found: bool = False
    version: Optional[str] = None
    app_path: Optional[str] = None
    data_path: Optional[str] = None
    database_path: Optional[str] = None
    config_path: Optional[str] = None
    sidecar_path: Optional[str] = None
    mlx_models_path: Optional[str] = None
    local_models_path: Optional[str] = None
    is_running: bool = False
    platform_info: Dict[str, Any] = field(default_factory=dict)
    service_ports: Dict[str, int] = field(default_factory=dict)
    schema_note: Optional[str] = None
    layout: Optional[str] = None
    layout_status: str = LAYOUT_UNKNOWN
    active_workspace: Optional[str] = None
    workspaces: List[Dict[str, Any]] = field(default_factory=list)
    stale_copies: List[Dict[str, str]] = field(default_factory=list)
    schema_fingerprint: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_msty_paths() -> Dict[str, Optional[Path]]:
    """Return candidate paths for the current platform."""
    home = Path.home()
    system = platform.system()

    if system == "Darwin":
        return {
            "app": Path("/Applications/MstyStudio.app"),
            "app_user": home / "Applications" / "MstyStudio.app",
            "app_alt": Path("/Applications/Msty.app"),
            "data": home / "Library" / "Application Support" / "MstyStudio",
            "data_legacy": home / "Library" / "Application Support" / "Msty",
            "sidecar": home / "Library" / "Application Support" / "MstySidecar",
            "database": home
            / "Library"
            / "Application Support"
            / "MstyStudio"
            / "File System"
            / "000"
            / "t"
            / "00"
            / "00000000",
            "database_legacy": home / "Library" / "Application Support" / "Msty" / "msty.db",
            "database_legacy_studio": home
            / "Library"
            / "Application Support"
            / "MstyStudio"
            / "msty.db",
            "config": home / "Library" / "Application Support" / "MstyStudio" / "Gifnoc.nosj",
            "mlx_models": home / "Library" / "Application Support" / "MstyStudio" / "models-mlx",
            "local_models": home / "Library" / "Application Support" / "MstyStudio" / "models",
            "nexus_app": Path("/Applications/MstyNexus.app"),
            "nexus_data": home / "Library" / "Application Support" / "MstyNexus",
        }

    if system == "Windows":
        appdata = Path.home() / "AppData" / "Roaming"
        # No app bundle path: Path("") would resolve to the working directory.
        return {
            "app": None,
            "app_alt": None,
            "data": appdata / "MstyStudio",
            "data_legacy": appdata / "Msty",
            "sidecar": appdata / "MstySidecar",
            "database": appdata / "MstyStudio" / "File System" / "000" / "t" / "00" / "00000000",
            "database_legacy": appdata / "Msty" / "msty.db",
            "database_legacy_studio": appdata / "MstyStudio" / "msty.db",
            "config": appdata / "MstyStudio" / "Gifnoc.nosj",
            "mlx_models": appdata / "MstyStudio" / "models-mlx",
            "local_models": appdata / "MstyStudio" / "models",
            "nexus_app": None,
            "nexus_data": appdata / "MstyNexus",
        }

    # Linux
    config_home = home / ".config"
    return {
        "app": None,
        "app_alt": None,
        "data": config_home / "MstyStudio",
        "data_legacy": config_home / "Msty",
        "sidecar": config_home / "MstySidecar",
        "database": config_home / "MstyStudio" / "File System" / "000" / "t" / "00" / "00000000",
        "database_legacy": config_home / "Msty" / "msty.db",
        "database_legacy_studio": config_home / "MstyStudio" / "msty.db",
        "config": config_home / "MstyStudio" / "Gifnoc.nosj",
        "mlx_models": config_home / "MstyStudio" / "models-mlx",
        "local_models": config_home / "MstyStudio" / "models",
        "nexus_app": None,
        "nexus_data": config_home / "MstyNexus",
    }


def read_app_version(app_path: Path) -> Optional[str]:
    """Read CFBundleShortVersionString from a macOS app bundle."""
    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.exists():
        return None
    try:
        with plist_path.open("rb") as fh:
            info = plistlib.load(fh)
        return info.get("CFBundleShortVersionString") or info.get("CFBundleVersion")
    except Exception:
        return None


def is_process_running(name_substring: str) -> bool:
    """Return True if any process name or exe path contains the substring.

    Fails closed: missing psutil or an iteration error is treated as running,
    so Studio writes refuse rather than proceeding on an unknown lock.
    """
    needle = name_substring.lower()
    if psutil is None:
        return True
    try:
        for proc in psutil.process_iter(["name", "exe"]):
            info = proc.info or {}
            pname = info.get("name")
            pexe = info.get("exe")
            pname = pname.lower() if isinstance(pname, str) else ""
            pexe = pexe.lower() if isinstance(pexe, str) else ""
            if needle in pname or needle in pexe:
                return True
        return False
    except Exception:
        return True


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def load_service_config(config_path: Path) -> Dict[str, Any]:
    """Load Gifnoc.nosj (config.json reversed) if present."""
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_service_ports(config: Dict[str, Any]) -> Dict[str, int]:
    """Extract service ports from Studio config, falling back to defaults."""
    ports = dict(DEFAULT_PORTS)

    local = config.get("localAIService") or {}
    host = local.get("host") or ""
    if ":" in str(host):
        try:
            ports["local_ai"] = int(str(host).rsplit(":", 1)[-1])
        except ValueError:
            pass

    mlx = config.get("mlxService") or {}
    mlx_host = mlx.get("host") or ""
    if ":" in str(mlx_host):
        try:
            ports["mlx"] = int(str(mlx_host).rsplit(":", 1)[-1])
        except ValueError:
            pass
    # MLX often stores host without port; keep default unless explicitly set

    return ports


def resolve_database_path(paths: Dict[str, Path]) -> Optional[Path]:
    """Prefer the Chromium File System SQLite, then legacy msty.db locations."""
    for key in ("database", "database_legacy_studio", "database_legacy"):
        candidate = paths.get(key)
        if candidate and candidate.exists() and candidate.is_file():
            # Confirm SQLite magic
            try:
                header = candidate.read_bytes()[:16]
                if header.startswith(b"SQLite format 3"):
                    return candidate
            except Exception:
                continue
    # Search File System tree for the primary SQLite blob
    data = paths.get("data")
    if data and data.exists():
        fs_root = data / "File System"
        if fs_root.exists():
            for candidate in sorted(fs_root.rglob("*")):
                if not candidate.is_file():
                    continue
                try:
                    if candidate.stat().st_size < 100:
                        continue
                    if candidate.read_bytes()[:16].startswith(b"SQLite format 3"):
                        # Prefer the canonical 00000000 blob
                        if candidate.name == "00000000":
                            return candidate
                except Exception:
                    continue
    return None


def _browser_home_database(paths: Dict[str, Optional[Path]]) -> Optional[Path]:
    candidate = paths.get("database")
    return candidate if studio_storage.is_sqlite_file(candidate) else None


def _apply_studio_3_storage(install: MstyInstallation, paths: Dict[str, Optional[Path]]) -> bool:
    """Resolve the active workspace for Studio 3.0, or for an unknown version
    when file-based storage exists (only Studio 3.0 creates it).

    Returns False when the Studio 2.x resolver should run instead.
    """
    studio_3 = is_studio_3(install.version)
    if not studio_3 and install.layout_status != LAYOUT_UNKNOWN:
        return False
    data = paths.get("data")
    if data and data.exists():
        layout = studio_storage.discover(data, _browser_home_database(paths))
    elif studio_3:
        layout = studio_storage.StorageLayout()
    else:
        return False
    if not studio_3 and not layout.uses_file_storage:
        return False
    if not layout.workspaces:
        # Studio 3.0 with no workspace database: never fall back to legacy msty.db.
        install.layout = "studio_3x_no_workspace"
        install.schema_note = (
            "Studio 3.0 detected but no workspace database was found. Launch Studio once."
        )
        return True
    install.workspaces = [w.to_dict() for w in layout.workspaces]
    install.stale_copies = list(layout.stale_copies)
    install.active_workspace = layout.active_slug
    active = layout.active()
    notes: List[str] = []
    if active and active.database_path:
        install.database_path = active.database_path
        if active.storage == studio_storage.STORAGE_NATIVE:
            install.layout = "studio_3x_file_storage"
            notes.append(
                f"Studio 3.0 file-based workspace storage. Active workspace "
                f"{active.name or active.slug!r} is read from its own msty.cloud.db."
            )
        else:
            install.layout = "studio_3x_browser_storage"
            notes.append(
                "Studio 3.0 still keeps this workspace in Chromium File System storage "
                "(file-based storage not enabled yet)."
            )
        try:
            install.schema_fingerprint = studio_storage.fingerprint_path(Path(active.database_path))
        except Exception:
            install.schema_fingerprint = None
    else:
        install.layout = "studio_3x_workspace_unreadable"
        label = (active.name or active.slug) if active else "active workspace"
        reason = active.note if active and active.note else "Its database was not found."
        notes.append(f"Active workspace {label!r} cannot be read. {reason}")
    if layout.stale_copies:
        notes.append(
            f"{len(layout.stale_copies)} stale browser-storage copy found and ignored "
            "(see stale_copies)."
        )
    if install.layout_status == LAYOUT_UNKNOWN:
        notes.insert(0, unknown_version_file_storage_warning())
    install.schema_note = " ".join(notes)
    return True


def storage_layout() -> studio_storage.StorageLayout:
    """Discover every workspace and the database Studio currently uses for it."""
    paths = get_msty_paths()
    data = paths.get("data")
    if not data or not data.exists():
        return studio_storage.StorageLayout()
    return studio_storage.discover(data, _browser_home_database(paths))


def workspace_database_path(workspace: str) -> Path:
    """Database path for one workspace by slug, id or name.

    Raises WorkspaceNotFound or WorkspaceUnreadable. Never returns a stale copy.
    """
    chosen = studio_storage.resolve_workspace(storage_layout(), workspace)
    return Path(chosen.database_path)  # type: ignore[arg-type]


def detect_msty_installation() -> MstyInstallation:
    """Detect Msty Studio app, data directory, database, and service ports."""
    paths = get_msty_paths()
    install = MstyInstallation(
        platform_info={
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        service_ports=dict(DEFAULT_PORTS),
    )

    app = paths.get("app")
    app_user = paths.get("app_user")
    app_alt = paths.get("app_alt")
    if app and app.exists():
        install.app_path = str(app)
        install.version = read_app_version(app)
    elif app_user and app_user.exists():
        install.app_path = str(app_user)
        install.version = read_app_version(app_user)
    elif app_alt and app_alt.exists():
        install.app_path = str(app_alt)
        install.version = read_app_version(app_alt)

    data = paths.get("data")
    data_legacy = paths.get("data_legacy")
    if data and data.exists():
        install.data_path = str(data)
    elif data_legacy and data_legacy.exists():
        install.data_path = str(data_legacy)

    config_path = paths.get("config")
    config: Dict[str, Any] = {}
    if config_path and config_path.exists():
        install.config_path = str(config_path)
        config = load_service_config(config_path)
        install.service_ports = parse_service_ports(config)
        # Prefer models paths from config when present
        local = config.get("localAIService") or {}
        mlx = config.get("mlxService") or {}
        if local.get("modelsPath"):
            install.local_models_path = local["modelsPath"]
        if mlx.get("modelsPath"):
            install.mlx_models_path = mlx["modelsPath"]

    if not install.local_models_path and paths.get("local_models"):
        install.local_models_path = str(paths["local_models"])
    if not install.mlx_models_path and paths.get("mlx_models"):
        install.mlx_models_path = str(paths["mlx_models"])

    sidecar = paths.get("sidecar")
    if sidecar and sidecar.exists():
        install.sidecar_path = str(sidecar)

    install.layout_status = layout_status(install.version)
    if install.layout_status == LAYOUT_UNSUPPORTED:
        # Studio 3.1+ (or below 2.4): never fall back to the 2.9 blob, legacy
        # msty.db or an rglob search. Those files may be a stale copy.
        install.layout = "unsupported_pre_2_4" if _is_pre_2_4(install.version) else "unsupported_3x"
        install.schema_note = unsupported_layout_message(install.version)
    elif not _apply_studio_3_storage(install, paths):
        db = resolve_database_path(paths)
        if db:
            install.database_path = str(db)
            if "File System" in str(db):
                install.layout = "studio_2x_file_system"
                install.schema_note = (
                    "Studio stores the workspace SQLite under Chromium File System "
                    "(not legacy msty.db)."
                )
            else:
                install.layout = "legacy_msty_db"
                install.schema_note = "Using legacy msty.db path."
            if install.layout_status == LAYOUT_UNKNOWN:
                install.schema_note = f"{unknown_version_read_warning()} {install.schema_note}"

    install.is_running = is_process_running("MstyStudio")
    install.installed = bool(install.app_path or install.data_path or install.database_path)
    install.found = install.installed and bool(install.database_path or install.data_path)

    if not install.version and install.installed:
        install.version = "unknown"

    return install


def detect_nexus() -> Dict[str, Any]:
    """Detect Msty Nexus local gateway if installed or listening."""
    paths = get_msty_paths()
    result: Dict[str, Any] = {
        "found": False,
        "app_path": None,
        "data_path": None,
        "endpoint": None,
        "available": False,
        "ports_checked": [],
    }

    nexus_app = paths.get("nexus_app")
    if nexus_app and nexus_app.exists():
        result["found"] = True
        result["app_path"] = str(nexus_app)
        result["version"] = read_app_version(nexus_app)

    nexus_data = paths.get("nexus_data")
    if nexus_data and nexus_data.exists():
        result["found"] = True
        result["data_path"] = str(nexus_data)

    # Probe common OpenAI-compatible gateway ports
    candidate_ports = [11434, 8080, 4000, 1234, 8317]
    for port in candidate_ports:
        result["ports_checked"].append(port)
        if is_port_open("127.0.0.1", port):
            result["available"] = True
            result["endpoint"] = f"http://127.0.0.1:{port}"
            result["found"] = True
            break

    return result
