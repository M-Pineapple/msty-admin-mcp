"""
Msty Studio path resolution and installation detection (Studio 2.4+ / 2.9+).

Resolves the real on-disk layout used by MstyStudio.app on macOS, including
the Chromium File System SQLite workspace database.
"""

from __future__ import annotations

import json
import platform
import plistlib
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_msty_paths() -> Dict[str, Path]:
    """Return candidate paths for the current platform."""
    home = Path.home()
    system = platform.system()

    if system == "Darwin":
        return {
            "app": Path("/Applications/MstyStudio.app"),
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
        return {
            "app": Path(""),
            "app_alt": Path(""),
            "data": appdata / "MstyStudio",
            "data_legacy": appdata / "Msty",
            "sidecar": appdata / "MstySidecar",
            "database": appdata / "MstyStudio" / "File System" / "000" / "t" / "00" / "00000000",
            "database_legacy": appdata / "Msty" / "msty.db",
            "database_legacy_studio": appdata / "MstyStudio" / "msty.db",
            "config": appdata / "MstyStudio" / "Gifnoc.nosj",
            "mlx_models": appdata / "MstyStudio" / "models-mlx",
            "local_models": appdata / "MstyStudio" / "models",
            "nexus_app": Path(""),
            "nexus_data": appdata / "MstyNexus",
        }

    # Linux
    config_home = home / ".config"
    return {
        "app": Path(""),
        "app_alt": Path(""),
        "data": config_home / "MstyStudio",
        "data_legacy": config_home / "Msty",
        "sidecar": config_home / "MstySidecar",
        "database": config_home / "MstyStudio" / "File System" / "000" / "t" / "00" / "00000000",
        "database_legacy": config_home / "Msty" / "msty.db",
        "database_legacy_studio": config_home / "MstyStudio" / "msty.db",
        "config": config_home / "MstyStudio" / "Gifnoc.nosj",
        "mlx_models": config_home / "MstyStudio" / "models-mlx",
        "local_models": config_home / "MstyStudio" / "models",
        "nexus_app": Path(""),
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
    """Return True if any process name contains the substring."""
    needle = name_substring.lower()
    if psutil is None:
        return False
    try:
        for proc in psutil.process_iter(["name"]):
            pname = (proc.info.get("name") or "").lower()
            if needle in pname:
                return True
    except Exception:
        return False
    return False


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
    app_alt = paths.get("app_alt")
    if app and app.exists():
        install.app_path = str(app)
        install.version = read_app_version(app)
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

    db = resolve_database_path(paths)
    if db:
        install.database_path = str(db)
        if "File System" in str(db):
            install.schema_note = (
                "Studio stores the workspace SQLite under Chromium File System "
                "(not legacy msty.db)."
            )
        else:
            install.schema_note = "Using legacy msty.db path."

    install.is_running = is_process_running("MstyStudio") or is_process_running("Msty")
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
