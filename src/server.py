"""
Msty Admin MCP Server v6.2.2
============================

Administer Msty Studio Desktop 2.9+ with real path/DB detection, entity inventory,
insights analytics, workflow export, and Nexus bridge, plus Bloom/calibration.

Author: M-Pineapple 🍍
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: MCP SDK not installed. Install with: pip install 'mcp>=1.0.0,<2'")
    sys.exit(1)

from src import analytics, db, inventory, nexus, studio_storage
from src.tooling import F, ann
from src.version import __version__ as SERVER_VERSION
from src.paths import (
    MstyInstallation,
    UnsupportedStudioLayout,
    detect_msty_installation as _detect_install,
    get_msty_paths,
    is_process_running,
    parse_version,
    storage_layout,
)
from src.services import (
    check_service_available,
    current_ports,
    list_models_from_port,
    make_api_request,
    service_status_map,
)
from src.hardware import get_hardware_profile as _hardware_profile
from src.hardware import catalog as hardware_catalog
from src.install import create_variant, passthrough_allowed, pull_model
from src import writes as studio_writes
from src.escalation import HOOK_API_NOTE, escalation_pack

TOOL_COUNT = 54
CHAT_BACKENDS = ("local_ai", "mlx", "llamacpp")
MODEL_BACKENDS = ("all", "local_ai", "mlx", "llamacpp", "vibe", "nexus")
STATUS_SCOPES = ("all", "server", "install", "services")

mcp = FastMCP("msty-admin-mcp", f"v{SERVER_VERSION}")
# FastMCP 1.x has no version= argument. Unset Server.version makes
# initialize report the MCP SDK version (e.g. 1.30.0) instead of us.
mcp._mcp_server.version = SERVER_VERSION


@dataclass
class MstyHealthReport:
    overall_status: str = "unknown"
    database_status: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    server_status: str = "running"
    msty_version: Optional[str] = None
    installed_tools_count: int = 0
    available_models: int = 0
    service_status: Dict[str, Any] = field(default_factory=dict)
    database_healthy: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class DatabaseStats:
    total_conversations: int = 0
    total_messages: int = 0
    total_tools: int = 0
    total_models: int = 0
    database_size_mb: float = 0.0


@dataclass
class PersonaConfig:
    name: str
    system_prompt: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 2000


def get_table_names() -> List[str]:
    try:
        return db.list_tables()
    except Exception:
        return []


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)


def _storage_json(payload: Any) -> str:
    """JSON for Studio storage reads, with a warning when the version is unknown."""
    return _json(db.with_read_warning(payload))


WORKSPACE_HELP = (
    "Optional Studio workspace name, slug or id from list_workspaces. "
    "Omit for the active workspace."
)


def _workspace_error(exc: Exception) -> Dict[str, Any]:
    """JSON error for an unknown or unreadable workspace, with the valid choices."""
    try:
        layout = storage_layout()
        choices = [
            {"name": w.name, "slug": w.slug, "storage": w.storage} for w in layout.workspaces
        ]
    except Exception:
        choices = []
    return {"error": str(exc), "workspaces": choices}


def _inventory_json(fn: Any) -> str:
    """Run an inventory read and turn workspace lookup failures into JSON errors."""
    try:
        return _storage_json(fn())
    except (studio_storage.WorkspaceNotFound, studio_storage.WorkspaceUnreadable) as exc:
        return _storage_json(_workspace_error(exc))


def get_bloom_evaluator():
    try:
        from src.bloom import BloomEvaluator

        return BloomEvaluator()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Phase 1 — Foundational
# ---------------------------------------------------------------------------


def _server_status_payload() -> Dict[str, Any]:
    return {
        "status": "running",
        "server": {"name": "msty-admin-mcp", "version": SERVER_VERSION},
        "version": SERVER_VERSION,
        "timestamp": datetime.now().isoformat(),
        "tools_available": TOOL_COUNT,
        "available_tools": TOOL_COUNT,
        "phases": {
            "phase_1_foundational": 5,
            "phase_2_configuration": 5,
            "phase_3_services": 9,
            "phase_4_intelligence": 5,
            "phase_5_calibration": 5,
            "phase_6_bloom": 6,
            "phase_7_studio_inventory": 15,
            "phase_8_nexus": 3,
            "phase_9_frontier": 1,
        },
        "studio_target": "2.4 to 2.9.x and 3.0.x (Studio 3.1 and later refused)",
    }


def _install_health_payload() -> Dict[str, Any]:
    install = _detect_install()
    services = service_status_map()
    recommendations: List[str] = []
    db_status: Dict[str, Any] = {"healthy": False}
    try:
        stats = db.database_stats()
        db_status = {"healthy": "error" not in stats, **stats}
    except Exception as exc:
        db_status = {"healthy": False, "error": str(exc)}
        recommendations.append(f"Database unreadable: {exc}")
    if not install.found:
        recommendations.append(
            "Studio data/database not detected. Ensure MstyStudio.app has been launched once."
        )
    parsed = parse_version(install.version)
    if parsed and parsed < (2, 5):
        recommendations.append(
            f"Studio {install.version} is older than Knowledge Stacks Next Gen (2.5). Consider upgrading."
        )
    if not any(s.get("available") for k, s in services.items() if k != "nexus"):
        recommendations.append(
            "No local inference services are listening. Start Local AI / MLX / Llama.cpp in Studio settings."
        )
    if not recommendations:
        recommendations.append("Installation looks healthy.")
    overall = "healthy"
    if not install.found or not db_status.get("healthy"):
        overall = "degraded"
    if not install.installed:
        overall = "missing"
    tool_count = 0
    try:
        tool_count = db.count_rows("tools") if db.table_exists("tools") else 0
    except Exception:
        pass
    report = MstyHealthReport(
        overall_status=overall,
        database_status=db_status,
        recommendations=recommendations,
        msty_version=install.version,
        installed_tools_count=tool_count,
        available_models=sum(
            len(list_models_from_port(p))
            for p in current_ports().values()
            if isinstance(p, int)
        ),
        service_status=services,
        database_healthy=bool(db_status.get("healthy")),
    )
    return asdict(report)


@mcp.tool(
    **ann("Get Msty installation", read_only=True),
    description=(
        "Locate the Msty Studio app, version, database path and service ports on this machine. "
        "Use this before other Studio tools when you need paths or to confirm Studio is installed. "
        "Read-only. Returns a JSON object with installed, version, database and ports."
    ),
)
def get_msty_installation() -> str:
    install = _detect_install()
    payload = install.to_dict()
    payload["paths"] = {k: (str(v) if v else None) for k, v in get_msty_paths().items()}
    return _json(payload)


@mcp.tool(
    **ann("Read Studio database", read_only=True),
    description=(
        "Run a read-only query against the Studio SQLite database. "
        "Use query=stats or query=tables for overviews, or a SELECT/WITH/PRAGMA statement. "
        "Do not use this to change data. Credential columns read as NULL. "
        "Returns JSON with query_type and either stats, a table list, or rows."
    ),
)
def read_msty_database(
    query: Annotated[
        str,
        F("stats, tables, or a read-only SQL SELECT/WITH/PRAGMA statement. Default stats."),
    ] = "stats",
    limit: Annotated[
        int,
        F("Maximum SQL rows to return. Integer from 1 to 500. Default 100."),
    ] = 100,
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    try:
        path = inventory.workspace_database(workspace)
        if query in ("stats", "stat"):
            return _storage_json({"query_type": "stats", **db.database_stats(path)})
        if query == "tables":
            tables = db.list_tables(database_path=path)
            return _storage_json({"query_type": "tables", "tables": tables, "count": len(tables)})
        results, count = db.safe_query(query, limit=limit, database_path=path)
        return _storage_json({"query_type": "sql", "results": results, "count": count})
    except Exception as exc:
        return _storage_json({"error": str(exc), "query_type": query})


@mcp.tool(
    **ann("List configured Toolbox tools", read_only=True),
    description=(
        "List MCP and Toolbox tools stored in Studio. "
        "Use this for Toolbox contents. Use list_studio_catalogue for entity counts across Studio. "
        "Each tool has a connection summary (transport, auth type, OAuth mode, URL host, "
        "header and env names) that never includes a secret value. "
        "Read-only. Returns JSON with tools and tool_count."
    ),
)
def list_configured_tools(
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    def build() -> Dict[str, Any]:
        path = inventory.workspace_database(workspace)
        result = inventory.list_entities("tools", limit=500, database_path=path)
        if "error" in result and "items" not in result:
            return result
        raw = db.tool_configs_for_projection(path) if result.get("items") else {}
        tools = []
        for item in result.get("items", []):
            tool = dict(item)
            tool["connection"] = inventory.tool_connection(raw.get(str(item.get("id"))))
            tools.append(tool)
        return {"tools": tools, "tool_count": len(tools), "count": len(tools)}

    return _inventory_json(build)


@mcp.tool(
    **ann("Get model providers", read_only=True),
    description=(
        "List local inference backends and Studio-configured remote providers, with keys redacted. "
        "Use list_models when you only need model names. Use get_status with scope=services for port health only. "
        "Read-only. Returns JSON with services, local_models and remote_providers."
    ),
)
def get_model_providers() -> str:
    ports = current_ports()
    local_models = {
        "local_ai": list_models_from_port(ports["local_ai"]),
        "mlx": list_models_from_port(ports["mlx"]),
        "llamacpp": list_models_from_port(ports["llamacpp"]),
        "vibe": list_models_from_port(ports["vibe"]),
    }
    providers = inventory.list_entities("providers", limit=100)
    return _storage_json(
        {
            "services": service_status_map(),
            "local_models": local_models,
            "remote_providers": providers.get("items", []),
            "database_providers": providers.get("items", []),
        }
    )


@mcp.tool(
    **ann("Get status", read_only=True),
    description=(
        "Report MCP server status, Studio install health, and local service ports in one tool. "
        "Use scope=server for this MCP process, scope=install for the Studio app and database, "
        "scope=services for Local AI/MLX/Llama.cpp/Vibe/Nexus ports, or scope=all for every section. "
        "Read-only. Returns JSON for the chosen scope."
    ),
)
def get_status(
    scope: Annotated[
        str,
        F("Which view to return. One of all, server, install, services. Default all."),
    ] = "all",
) -> str:
    cleaned = (scope or "all").strip().lower()
    if cleaned not in STATUS_SCOPES:
        return _json(
            {
                "error": f"Unknown scope {scope!r}. Use all, server, install or services.",
                "allowed": list(STATUS_SCOPES),
            }
        )
    server = _server_status_payload()
    services = service_status_map()
    install = _install_health_payload()
    if cleaned == "server":
        return _json(server)
    if cleaned == "services":
        return _json(services)
    if cleaned == "install":
        return _json(install)
    return _json({"server": server, "install": install, "services": services})


# ---------------------------------------------------------------------------
# Phase 2 — Configuration
# ---------------------------------------------------------------------------


@mcp.tool(
    **ann("Export tool config", read_only=True),
    description=(
        "Export one Studio Toolbox tool configuration by name, toolId or id. "
        "Use this to copy a config. Use import_tool_config to save a pack for Toolbox import. "
        "Read-only. Returns JSON with the tool config, or an error and available names."
    ),
)
def export_tool_config(
    tool_name: Annotated[
        str,
        F("Toolbox tool name, toolId or id to export. Non-empty string."),
    ],
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    try:
        path = inventory.workspace_database(workspace)
    except (studio_storage.WorkspaceNotFound, studio_storage.WorkspaceUnreadable) as exc:
        return _storage_json(_workspace_error(exc))
    tools = inventory.list_entities("tools", limit=500, database_path=path).get("items", [])
    match = next(
        (
            t
            for t in tools
            if t.get("name") == tool_name or t.get("toolId") == tool_name or t.get("id") == tool_name
        ),
        None,
    )
    if not match:
        return _storage_json({"error": f"Tool '{tool_name}' not found", "available": [t.get("name") for t in tools]})
    full = inventory.get_entity("tools", match["id"], workspace=workspace)
    raw = db.tool_configs_for_projection(path)
    return _storage_json(
        {
            "tool_name": tool_name,
            "exported_at": datetime.now().isoformat(),
            "config": full.get("item") or match,
            "connection": inventory.tool_connection(raw.get(str(match.get("id")))),
        }
    )


def _claude_desktop_config() -> Path:
    """Claude Desktop config path for this platform."""
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "Claude"
    elif system == "Windows":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Claude"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "Claude"
    return base / "claude_desktop_config.json"


@mcp.tool(
    **ann("Sync Claude preferences", read_only=True),
    description=(
        "Compare Claude Desktop MCP server names with tools already in Msty Toolbox. "
        "Use this for a delta report. It does not write to Studio. Import missing tools with import_tool_config. "
        "Read-only. Returns JSON with claude_servers, msty_tools and a note that writes stay user-confirmed."
    ),
)
def sync_claude_preferences() -> str:
    claude_cfg = _claude_desktop_config()
    msty_tools = inventory.list_entities("tools", limit=500)
    claude_servers = {}
    if claude_cfg.exists():
        try:
            data = json.loads(claude_cfg.read_text())
            claude_servers = data.get("mcpServers") or {}
        except Exception as exc:
            return _storage_json({"status": "error", "error": str(exc)})
    return _storage_json(
        {
            "status": "analysed",
            "timestamp": datetime.now().isoformat(),
            "claude_servers": list(claude_servers.keys()),
            "msty_tools": [t.get("name") for t in msty_tools.get("items", [])],
            "missing_in_msty": sorted(
                set(claude_servers) - {t.get("name") for t in msty_tools.get("items", [])}
            ),
            "preferences_synced": 0,
            "note": "v6 reports the delta only; write-import remains user-confirmed via Toolbox / import_tool_config.",
        }
    )


@mcp.tool(
    **ann("Generate persona", read_only=False, idempotent=False),
    description=(
        "Build a persona JSON pack and, when gated, insert it into Studio SQLite. "
        "Use this to create a persona. Use import_studio_pack for a full pack. "
        "Always writes a pack under ~/.msty-admin/imports/. SQLite insert needs confirm=true, "
        "MSTY_ALLOW_STUDIO_WRITES=1 in the server environment, and Studio must be closed. "
        "Name max 100 characters, system prompt max 20000. Returns JSON with pack_path and wrote."
    ),
)
def generate_persona(
    name: Annotated[str, F("Persona name. 1 to 100 characters. Must be unique in Studio.")],
    system_prompt: Annotated[
        str,
        F("System prompt text. 1 to 20000 characters. Stored as JSON with mode append unless you ask for replace via import_studio_pack."),
    ],
    model: Annotated[
        str,
        F("Local model name to associate, for example llama3.2:3b. Used for partialModelInfo lookup only."),
    ],
    confirm: Annotated[
        bool,
        F("Set true to insert into Studio after a backup. Default false (pack only)."),
    ] = False,
) -> str:
    persona = PersonaConfig(name=name, system_prompt=system_prompt, model=model)
    pack = studio_writes.persona_pack(name, system_prompt, model)
    result = studio_writes.apply_pack(pack, confirm=confirm)
    result["persona"] = asdict(persona)
    result["created_at"] = datetime.now().isoformat()
    if not confirm:
        result["import_hint"] = (
            "JSON pack saved under ~/.msty-admin/imports/. "
            "SQLite insert needs confirm=true and MSTY_ALLOW_STUDIO_WRITES=1 in the server "
            "environment. Skills stay in the JSON pack. Or import the pack in Persona Studio."
        )
    return _json(result)


@mcp.tool(
    **ann("Import tool config", read_only=False, idempotent=False),
    description=(
        "Save a Toolbox tool config as a JSON pack. Never writes the Studio database. "
        "Use this for tools. Use import_studio_pack for personas, prompts, skills and toolsets. "
        "Configs with command, args or env are flagged as running a program on your machine and stay pack-only. "
        "Returns JSON with pack_path, wrote=false, and launch_risk when present."
    ),
)
def import_tool_config(
    tool_data: Annotated[
        Dict[str, Any],
        F("Tool object with name, toolId and config. command, args and env are allowed in the pack but never inserted into SQLite."),
    ],
    confirm: Annotated[
        bool,
        F("Accepted for symmetry. Tools are never inserted into SQLite. Default false."),
    ] = False,
) -> str:
    pack = studio_writes.tool_pack(tool_data)
    result = studio_writes.apply_pack(pack, confirm=confirm)
    result["tool_name"] = tool_data.get("name")
    result["timestamp"] = datetime.now().isoformat()
    return _json(result)


@mcp.tool(
    **ann("Import Studio pack", read_only=False, idempotent=False),
    description=(
        "Save a Studio pack as JSON. Tools, toolsets and skills stay pack-only. "
        "Personas and prompts insert only with confirm=true and MSTY_ALLOW_STUDIO_WRITES=1, after a backup, and only when Studio is closed. "
        "Use generate_persona for a single persona. Length caps apply (name/title 100, description 500, prompt 20000). "
        "Returns JSON with pack_path, wrote, status and any error."
    ),
)
def import_studio_pack(
    pack: Annotated[
        Dict[str, Any],
        F("Pack object with optional personas, prompts, skills, tools, toolsets. include_escalation_persona adds the Frontier persona."),
    ],
    confirm: Annotated[
        bool,
        F("Set true to insert personas and prompts into Studio. Default false (pack only)."),
    ] = False,
) -> str:
    if pack.get("include_escalation_persona"):
        merged = dict(pack)
        personas = list(merged.get("personas") or [])
        personas.extend(escalation_pack()["personas"])
        merged["personas"] = personas
        pack = merged
    result = studio_writes.apply_pack(pack, confirm=confirm)
    result["hook_api"] = HOOK_API_NOTE
    return _json(result)


# ---------------------------------------------------------------------------
# Phase 3 — Services
# ---------------------------------------------------------------------------


@mcp.tool(
    **ann("List models", read_only=True, open_world=True),
    description=(
        "List models on a local backend. "
        "Use backend=all for every service, or local_ai, mlx, llamacpp, vibe or nexus. "
        "Use chat_with_model to talk to a listed model. Read-only aside from local HTTP. "
        "Returns JSON with backend and models, or an error when that service is down."
    ),
)
def list_models(
    backend: Annotated[
        str,
        F("Which backend to list. One of all, local_ai, mlx, llamacpp, vibe, nexus. Default all."),
    ] = "all",
) -> str:
    cleaned = (backend or "all").strip().lower().replace("llama.cpp", "llamacpp")
    if cleaned not in MODEL_BACKENDS:
        return _json(
            {
                "error": f"Unknown backend {backend!r}. Use all, local_ai, mlx, llamacpp, vibe or nexus.",
                "allowed": list(MODEL_BACKENDS),
            }
        )
    if cleaned == "nexus":
        return _json({"backend": "nexus", **nexus.query_nexus_models()})
    ports = current_ports()
    if cleaned == "all":
        models = {
            "local_ai": list_models_from_port(ports["local_ai"]),
            "mlx": list_models_from_port(ports["mlx"]),
            "llamacpp": list_models_from_port(ports["llamacpp"]),
            "vibe": list_models_from_port(ports["vibe"]),
            "nexus": nexus.query_nexus_models(),
        }
        named = [v for v in models.values() if isinstance(v, list)]
        return _json({"backend": "all", "models": models, "total": sum(len(v) for v in named)})
    if not check_service_available(ports[cleaned]):
        return _json(
            {"error": f"{cleaned} service not available", "models": [], "backend": cleaned}
        )
    return _json({"backend": cleaned, "models": list_models_from_port(ports[cleaned])})


@mcp.tool(
    **ann("Query Local AI service", read_only=False, idempotent=False, open_world=True),
    description=(
        "Call the Local AI (Ollama-compatible) HTTP API on an allow-list of read and chat paths. "
        "Use install_model to pull and set_model_settings to create a variant. Pull and create are refused here. "
        "Talks to the local network. Returns JSON with the API body or an allow-list error."
    ),
)
def query_local_ai_service(
    endpoint: Annotated[
        str,
        F("API path such as /api/tags or /v1/chat/completions. Leading slash optional. No query string."),
    ],
    method: Annotated[
        str,
        F("HTTP method. GET or POST. Default GET."),
    ] = "GET",
    data: Annotated[
        Optional[Dict[str, Any]],
        F("JSON body for POST. Omit for GET."),
    ] = None,
) -> str:
    decision = passthrough_allowed(endpoint, method)
    if not decision.get("allowed"):
        return _json(
            {
                "success": False,
                "error": decision.get("error"),
                "endpoint": decision.get("endpoint"),
                "method": decision.get("method"),
                "allowed_get": decision.get("allowed_get"),
                "allowed_post": decision.get("allowed_post"),
            }
        )
    ports = current_ports()
    return _json(
        make_api_request(
            decision["endpoint"], port=ports["local_ai"], method=decision["method"], data=data
        )
    )


@mcp.tool(
    **ann("Chat with model", read_only=False, idempotent=False, open_world=True),
    description=(
        "Send a chat completion to a local model on Local AI, MLX or Llama.cpp. "
        "Use list_models first if you need names. Use ask_frontier for a cloud model. "
        "Calls the local OpenAI-compatible /v1/chat/completions endpoint. Not read-only. "
        "Returns the backend JSON or an error when the service is down."
    ),
)
def chat_with_model(
    model: Annotated[str, F("Model name as listed by list_models for that backend.")],
    messages: Annotated[
        List[Dict[str, str]],
        F("Chat messages. Each object needs role (system, user or assistant) and content."),
    ],
    backend: Annotated[
        str,
        F("Inference backend. One of local_ai, mlx, llamacpp. Default local_ai."),
    ] = "local_ai",
) -> str:
    cleaned = (backend or "local_ai").strip().lower().replace("llama.cpp", "llamacpp")
    if cleaned not in CHAT_BACKENDS:
        return _json(
            {
                "error": f"Unknown backend {backend!r}. Use local_ai, mlx or llamacpp.",
                "allowed": list(CHAT_BACKENDS),
            }
        )
    ports = current_ports()
    if not check_service_available(ports[cleaned]):
        return _json({"error": f"{cleaned} service not available"})
    return _json(
        make_api_request(
            "/v1/chat/completions",
            port=ports[cleaned],
            method="POST",
            data={"model": model, "messages": messages, "stream": False},
            timeout=60,
        )
    )


@mcp.tool(
    **ann("Get hardware profile", read_only=True),
    description=(
        "Read chip, CPU cores, RAM, GPU/VRAM and Apple Silicon generation for model sizing. "
        "Use recommend_model to turn this into a model pick. Read-only. Returns JSON hardware fields."
    ),
)
def get_hardware_profile() -> str:
    return _json(_hardware_profile())


@mcp.tool(
    **ann("Recommend model", read_only=True),
    description=(
        "Recommend a local model from hardware fit, then 30-day Studio usage when it still fits. "
        "Use get_hardware_profile for the raw numbers. Use install_model to pull the pick. "
        "Read-only. Returns JSON with the recommendation and a hardware summary."
    ),
)
def recommend_model(
    use_case: Annotated[
        str,
        F("Intended use. One of general, coding, chat, summarisation, or a short free-text use case. Default general."),
    ] = "general",
) -> str:
    profile = _hardware_profile()
    usage_note = None
    try:
        insights = analytics.get_insights_usage(timeframe="30d")
    except UnsupportedStudioLayout as exc:
        # Studio storage is refused (for example Studio 3.x). Recommend from
        # hardware alone instead of failing the model tool.
        insights = {}
        usage_note = f"Studio usage not used. {exc}"
    result = hardware_catalog.recommend(
        profile,
        use_case=use_case,
        insights_models=insights.get("models") or [],
    )
    result["hardware"] = {
        "chip": profile.get("chip"),
        "ram_gb": profile.get("ram_gb"),
        "unified_memory": profile.get("unified_memory"),
        "apple_generation": profile.get("apple_generation"),
        "memory_kind": profile.get("memory_kind"),
    }
    if usage_note:
        result["usage_note"] = usage_note
    return _json(result)


@mcp.tool(
    **ann("Install model", read_only=False, destructive=True, idempotent=False, open_world=True),
    description=(
        "Pull a model through Local AI (Ollama-compatible /api/pull). "
        "Use recommend_model to pick a size. MLX and Llama.cpp have no pull API here. "
        "Only bare Ollama names (registry.ollama.ai) and hf.co/ paths are allowed. "
        "Needs confirm=true to write. Returns JSON with wrote, model and any error."
    ),
)
def install_model(
    model: Annotated[
        str,
        F("Model to pull. Bare Ollama name such as llama3.2:3b, or hf.co/org/model. No other hosts."),
    ],
    confirm: Annotated[
        bool,
        F("Set true to run /api/pull. Default false (preview)."),
    ] = False,
    service: Annotated[
        str,
        F("Pull service. local_ai only. mlx and llamacpp are refused. Default local_ai."),
    ] = "local_ai",
) -> str:
    return _json(pull_model(model, confirm=confirm, service=service))


@mcp.tool(
    **ann("Set model settings", read_only=False, destructive=True, idempotent=False, open_world=True),
    description=(
        "Create a tuned Ollama variant via /api/create from an installed base model. "
        "Use install_model first if the base is missing. Does not overwrite an existing name. "
        "Needs confirm=true to write. Returns JSON with wrote, variant and a Modelfile preview."
    ),
)
def set_model_settings(
    base_model: Annotated[str, F("Installed base model name, for example llama3.2:3b.")],
    variant_name: Annotated[str, F("New variant name to create. Must not already exist.")],
    temperature: Annotated[
        Optional[float], F("Sampling temperature 0 to 2. Omit to leave unset.")
    ] = None,
    top_p: Annotated[
        Optional[float], F("Nucleus sampling 0 to 1. Omit to leave unset.")
    ] = None,
    num_ctx: Annotated[
        Optional[int], F("Context window in tokens. Positive integer. Omit to leave unset.")
    ] = None,
    system: Annotated[
        Optional[str], F("System prompt for the variant. Max 20000 characters. Omit to leave unset.")
    ] = None,
    confirm: Annotated[
        bool, F("Set true to POST /api/create. Default false (preview).")
    ] = False,
) -> str:
    return _json(
        create_variant(
            base_model,
            variant_name,
            temperature=temperature,
            top_p=top_p,
            num_ctx=num_ctx,
            system=system,
            confirm=confirm,
        )
    )


@mcp.tool(
    **ann("Get Vibe proxy status", read_only=True, open_world=True),
    description=(
        "Check whether the Vibe CLI proxy port is up. "
        "Use query_vibe_proxy to send a query. Local HTTP. Returns JSON status or unavailable."
    ),
)
def get_vibe_proxy_status() -> str:
    ports = current_ports()
    if not check_service_available(ports["vibe"]):
        return _json({"status": "unavailable", "port": ports["vibe"]})
    return _json(make_api_request("/status", port=ports["vibe"]))


@mcp.tool(
    **ann("Query Vibe proxy", read_only=False, idempotent=False, open_world=True),
    description=(
        "Send a query to the Vibe CLI proxy. "
        "Use get_vibe_proxy_status first if you only need liveness. Local HTTP POST. "
        "Returns the proxy JSON or an error when the proxy is down."
    ),
)
def query_vibe_proxy(
    query: Annotated[str, F("Query text to send to the Vibe proxy. Non-empty string.")],
) -> str:
    ports = current_ports()
    if not check_service_available(ports["vibe"]):
        return _json({"error": "Vibe proxy not available"})
    return _json(make_api_request("/query", port=ports["vibe"], method="POST", data={"query": query}))


# ---------------------------------------------------------------------------
# Phase 4 — Intelligence (real Studio data)
# ---------------------------------------------------------------------------


@mcp.tool(
    **ann("Get model performance metrics", read_only=True),
    description=(
        "Read token, latency and call counts from Studio insightsLanguageModelUsage. "
        "Use get_insights_usage as the same data under a shorter name. Use get_conversation_patterns for chat shape. "
        "Read-only. Returns JSON totals and per-model rows."
    ),
)
def get_model_performance_metrics(
    model_id: Annotated[
        Optional[str], F("Optional model id to filter. Omit for all models.")
    ] = None,
    timeframe: Annotated[
        str, F("Window such as 7d, 30d or all. Default 7d.")
    ] = "7d",
) -> str:
    return _storage_json(analytics.get_insights_usage(model_id=model_id, timeframe=timeframe))


@mcp.tool(
    **ann("Get conversation patterns", read_only=True),
    description=(
        "Summarise conversation patterns from Studio data for one model or all models. "
        "Use get_model_performance_metrics for speed and token counts. Read-only. Returns JSON pattern stats."
    ),
)
def get_conversation_patterns(
    model_id: Annotated[
        Optional[str], F("Optional model id to filter. Omit for all models.")
    ] = None,
) -> str:
    return _storage_json(analytics.analyse_conversation_patterns(model_id=model_id))


@mcp.tool(
    **ann("Compare model responses", read_only=False, idempotent=False, open_world=True),
    description=(
        "Send the same prompt to several Local AI models and compare latency and a preview of each reply. "
        "Use chat_with_model for a full conversation with one model. Calls local inference. "
        "Returns JSON with comparisons. Best-effort if a model is cold."
    ),
)
def compare_model_responses(
    prompt: Annotated[str, F("Prompt to send to every listed model. Non-empty string.")],
    models: Annotated[
        List[str], F("Local AI model names to compare. At least one name.")
    ],
) -> str:
    ports = current_ports()
    comparisons = []
    for model in models:
        start = time.time()
        resp = make_api_request(
            "/v1/chat/completions",
            port=ports["local_ai"],
            method="POST",
            data={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=45,
        )
        elapsed = time.time() - start
        text = ""
        if resp.get("success"):
            choices = resp.get("data", {}).get("choices", [])
            if choices:
                text = choices[0].get("message", {}).get("content", "")
        comparisons.append(
            {
                "model": model,
                "latency_sec": round(elapsed, 2),
                "success": bool(resp.get("success")),
                "response_preview": (text or resp.get("error") or "")[:500],
            }
        )
    return _json({"prompt": prompt[:200], "comparisons": comparisons})


@mcp.tool(
    **ann("Optimise knowledge stacks", read_only=True),
    description=(
        "Suggest Knowledge Stack changes from live Studio Next Gen, draft and compose status. "
        "Does not edit stacks. Use list_knowledge_stacks to browse them. Read-only. Returns JSON suggestions."
    ),
)
def optimise_knowledge_stacks() -> str:
    return _storage_json(analytics.optimise_knowledge_stacks())


@mcp.tool(
    **ann("Suggest persona improvements", read_only=True),
    description=(
        "Suggest persona edits from live Studio personas. "
        "Does not write personas. Use generate_persona to create one. Read-only. Returns JSON suggestions."
    ),
)
def suggest_persona_improvements() -> str:
    return _storage_json(analytics.suggest_persona_improvements())


# ---------------------------------------------------------------------------
# Phase 5 — Calibration
# ---------------------------------------------------------------------------


@mcp.tool(
    **ann("Run calibration test", read_only=False, idempotent=False, open_world=True),
    description=(
        "Run heuristic calibration prompts against a Local AI model and store scores in ~/.msty-admin. "
        "Use evaluate_response_quality to score a single reply without calling the model. "
        "Calls local inference and writes sidecar metrics. Returns JSON with tests_run and average_score."
    ),
)
def run_calibration_test(
    model_id: Annotated[
        Optional[str], F("Local AI model to test. Omit to use the first installed model.")
    ] = None,
    category: Annotated[
        str,
        F("Prompt category, or general for one prompt per category. Default general."),
    ] = "general",
) -> str:
    from src.phase4_5_tools import (
        CALIBRATION_PROMPTS,
        evaluate_response_heuristic,
        init_metrics_db,
        save_calibration_result,
    )

    ports = current_ports()
    target_model = model_id
    if not target_model and check_service_available(ports["local_ai"]):
        models = list_models_from_port(ports["local_ai"])
        if models:
            target_model = models[0]
    if not target_model:
        return _json({"error": "No model specified and no models detected."})

    if category == "general":
        test_prompts = [
            {"category": cat, "prompt": prompts[0]}
            for cat, prompts in CALIBRATION_PROMPTS.items()
            if prompts
        ]
    elif category in CALIBRATION_PROMPTS:
        test_prompts = [
            {"category": category, "prompt": p} for p in CALIBRATION_PROMPTS[category]
        ]
    else:
        return _json(
            {
                "error": f"Unknown category '{category}'",
                "available": list(CALIBRATION_PROMPTS.keys()) + ["general"],
            }
        )

    try:
        init_metrics_db()
    except Exception:
        pass

    results = []
    total_score = 0.0
    for item in test_prompts:
        test_id = str(uuid.uuid4())
        start_time = time.time()
        api_response = make_api_request(
            "/v1/chat/completions",
            port=ports["local_ai"],
            method="POST",
            data={
                "model": target_model,
                "messages": [{"role": "user", "content": item["prompt"]}],
                "stream": False,
            },
            timeout=30,
        )
        elapsed = time.time() - start_time
        if not api_response.get("success"):
            results.append(
                {
                    "test_id": test_id,
                    "category": item["category"],
                    "error": api_response.get("error", "Request failed"),
                }
            )
            continue
        choices = api_response.get("data", {}).get("choices", [])
        model_response = choices[0].get("message", {}).get("content", "") if choices else ""
        completion_tokens = api_response.get("data", {}).get("usage", {}).get(
            "completion_tokens", len(model_response.split())
        )
        tps = completion_tokens / elapsed if elapsed > 0 else 0
        evaluation = evaluate_response_heuristic(item["prompt"], model_response, item["category"])
        try:
            save_calibration_result(
                test_id=test_id,
                model_id=target_model,
                prompt_category=item["category"],
                prompt=item["prompt"],
                local_response=model_response[:500],
                quality_score=evaluation["score"],
                evaluation_notes=evaluation["notes"],
                tokens_per_second=tps,
                passed=evaluation["passed"],
            )
        except Exception:
            pass
        total_score += evaluation["score"]
        results.append(
            {
                "test_id": test_id,
                "category": item["category"],
                "quality_score": round(evaluation["score"], 3),
                "passed": evaluation["passed"],
                "tokens_per_second": round(tps, 1),
                "latency_seconds": round(elapsed, 2),
            }
        )

    avg_score = total_score / len(results) if results else 0
    return _json(
        {
            "model": target_model,
            "category": category,
            "tests_run": len(results),
            "tests_passed": sum(1 for r in results if r.get("passed")),
            "average_score": round(avg_score, 3),
            "overall_passed": avg_score >= 0.6,
            "results": results,
            "timestamp": datetime.now().isoformat(),
        }
    )


@mcp.tool(
    **ann("Evaluate response quality", read_only=True),
    description=(
        "Score a prompt and reply with a local heuristic rubric. "
        "Does not call a model. Use run_calibration_test to generate replies first. "
        "Read-only. Returns JSON with quality_score, passed and criteria."
    ),
)
def evaluate_response_quality(
    prompt: Annotated[str, F("Original prompt text.")],
    response: Annotated[str, F("Model reply to score.")],
    category: Annotated[
        str, F("Rubric category such as general, analysis or coding. Default general.")
    ] = "general",
) -> str:
    from src.phase4_5_tools import evaluate_response_heuristic

    evaluation = evaluate_response_heuristic(prompt, response, category)
    return _json(
        {
            "prompt_preview": prompt[:100],
            "quality_score": round(evaluation["score"], 2),
            "passed": evaluation["passed"],
            "criteria": evaluation["criteria_scores"],
        }
    )


@mcp.tool(
    **ann("Identify handoff triggers", read_only=True),
    description=(
        "Flag models that look slow or low-throughput from 30-day Studio insights. "
        "This only reports. Use escalate_if_needed or ask_frontier to send a question to the cloud. "
        "Read-only. Returns JSON triggers and hook_api."
    ),
)
def identify_handoff_triggers() -> str:
    insights = analytics.get_insights_usage(timeframe="30d")
    triggers = []
    for model in insights.get("models", []):
        if model.get("avg_tokens_per_sec", 99) < 5:
            triggers.append(
                {
                    "pattern": f"Low throughput on {model['model_id']}",
                    "confidence": 0.7,
                    "model_id": model["model_id"],
                }
            )
        if model.get("avg_latency_sec", 0) > 20:
            triggers.append(
                {
                    "pattern": f"High latency on {model['model_id']}",
                    "confidence": 0.75,
                    "model_id": model["model_id"],
                }
            )
    if not triggers:
        triggers = [
            {
                "pattern": "Insufficient insights. Run calibration or use Studio more to populate metrics",
                "confidence": 0.4,
            }
        ]
    return _storage_json(
        {
            "triggers": triggers,
            "escalate_tool": "escalate_if_needed",
            "hook_api": HOOK_API_NOTE,
        }
    )


@mcp.tool(
    **ann("Escalate if needed", read_only=False, idempotent=False, open_world=True),
    description=(
        "Send a hard question to Cursor, Grok or Claude via the Frontier helper. "
        "Use ask_frontier for the same call without a reason field. Use identify_handoff_triggers to decide whether to escalate. "
        "Calls the network. Needs the matching API key. Returns JSON with escalated, answer and hook_api."
    ),
)
def escalate_if_needed(
    question: Annotated[str, F("Question to send to the cloud model.")],
    reason: Annotated[
        str, F("Optional reason recorded in the result. Default empty.")
    ] = "",
    provider: Annotated[
        Optional[str],
        F("Cloud provider: cursor, grok or claude. Default cursor."),
    ] = None,
) -> str:
    from src.frontier import ask_frontier as dispatch_frontier

    try:
        outcome = dispatch_frontier(question, provider=provider)
    except Exception as exc:
        return _json(
            {
                "escalated": False,
                "error": str(exc),
                "reason": reason,
                "hook_api": HOOK_API_NOTE,
            }
        )
    return _json(
        {
            "escalated": True,
            "provider": provider or "cursor",
            "reason": reason,
            "answer": outcome.answer,
            "hook_api": HOOK_API_NOTE,
        }
    )


@mcp.tool(
    **ann("Get calibration history", read_only=True),
    description=(
        "Read calibration scores from the sidecar metrics database under ~/.msty-admin. "
        "Use run_calibration_test to add rows. Read-only. Returns JSON history rows."
    ),
)
def get_calibration_history(
    model_id: Annotated[
        Optional[str], F("Optional model id to filter. Omit for all models.")
    ] = None,
    limit: Annotated[
        int, F("Maximum rows. Integer from 1 to 500. Default 50.")
    ] = 50,
) -> str:
    from src.phase4_5_tools import fetch_calibration_history

    return _json(fetch_calibration_history(model_id=model_id, limit=limit))


# ---------------------------------------------------------------------------
# Phase 6 — Bloom
# ---------------------------------------------------------------------------


@mcp.tool(
    **ann("Bloom evaluate model", read_only=False, idempotent=False, open_world=True),
    description=(
        "Run a Bloom behavioural evaluation on a local model. Never invents a score. "
        "Needs ANTHROPIC_API_KEY and a Bloom checkout. Use bloom_validate_model first. "
        "Calls the network. Returns JSON with quality_score or an honest error and quality_score null."
    ),
)
def bloom_evaluate_model(
    model: Annotated[str, F("Local Ollama model name, for example llama3.2:3b.")],
    behavior: Annotated[str, F("Bloom behaviour id from bloom_list_behaviors.")],
    task_category: Annotated[
        Optional[str], F("Optional task category for thresholds. Omit for default.")
    ] = None,
    total_evals: Annotated[
        int, F("Number of evaluation scenarios. Integer 1 to 20. Default 3.")
    ] = 3,
    max_turns: Annotated[
        int, F("Maximum conversation turns per scenario. Integer 1 to 10. Default 2.")
    ] = 2,
) -> str:
    import os

    from src.bloom.evaluator import evaluate_sync

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _json(
            {
                "error": "ANTHROPIC_API_KEY is not set",
                "requires": "ANTHROPIC_API_KEY",
                "quality_score": None,
                "note": "No score was invented.",
            }
        )
    evaluator = get_bloom_evaluator()
    if not evaluator:
        return _json(
            {
                "error": "Bloom evaluator could not start",
                "requires": "ANTHROPIC_API_KEY and a Bloom checkout (BLOOM_PATH or ~/bloom)",
                "quality_score": None,
                "note": "No score was invented.",
            }
        )
    if not getattr(evaluator, "bloom_path", None):
        return _json(
            {
                "error": "Bloom framework not found. Install from https://github.com/anthropics/bloom and set BLOOM_PATH.",
                "quality_score": None,
                "model": model,
                "behavior": behavior,
                "note": "No score was invented.",
            }
        )
    try:
        result = evaluate_sync(
            evaluator,
            model=model,
            behavior=behavior,
            task_category=task_category,
            total_evals=total_evals,
            max_turns=max_turns,
        )
    except Exception as exc:
        return _json(
            {
                "error": str(exc),
                "quality_score": None,
                "model": model,
                "behavior": behavior,
                "note": "No score was invented.",
            }
        )
    payload = result.to_dict() if hasattr(result, "to_dict") else result
    return _json(payload)


@mcp.tool(
    **ann("Bloom check handoff", read_only=True),
    description=(
        "Decide from Bloom history whether a model should hand off a task category. "
        "Does not call Bloom. Use bloom_evaluate_model to add history. Read-only. Returns JSON handoff advice."
    ),
)
def bloom_check_handoff(
    model: Annotated[str, F("Local model name whose Bloom history to read.")],
    task_category: Annotated[str, F("Task category such as research, coding or advisory.")],
) -> str:
    from src.bloom.evaluator import handoff_from_history

    return _json(handoff_from_history(model, task_category))


@mcp.tool(
    **ann("Bloom get history", read_only=True),
    description=(
        "Read persisted Bloom evaluation rows from ~/.msty-admin/bloom-history.json. "
        "Use bloom_evaluate_model to add rows. Read-only. Returns JSON evaluations."
    ),
)
def bloom_get_history(
    model: Annotated[Optional[str], F("Optional model name filter.")] = None,
    behavior: Annotated[Optional[str], F("Optional behaviour id filter.")] = None,
) -> str:
    from src.bloom.evaluator import load_persisted_history

    evaluations = load_persisted_history(model=model, behavior=behavior, limit=50)
    return _json({"evaluations": evaluations, "model": model, "behavior": behavior})


@mcp.tool(
    **ann("Bloom list behaviours", read_only=True),
    description=(
        "List Bloom behaviours this server can evaluate. "
        "Use bloom_evaluate_model with one of these ids. Read-only. Returns JSON behaviors and count."
    ),
)
def bloom_list_behaviors() -> str:
    from src.bloom.cv_behaviors import CUSTOM_BEHAVIORS

    return _json({"behaviors": list(CUSTOM_BEHAVIORS.keys()), "count": len(CUSTOM_BEHAVIORS)})


@mcp.tool(
    **ann("Bloom get thresholds", read_only=True),
    description=(
        "Read quality thresholds and handoff triggers for a task category. "
        "Use bloom_check_handoff to apply them to history. Read-only. Returns JSON thresholds."
    ),
)
def bloom_get_thresholds(
    task_category: Annotated[str, F("Task category such as research, coding, advisory or general.")],
) -> str:
    from src.bloom.cv_behaviors import QUALITY_THRESHOLDS

    return _json(
        {
            "task_category": task_category,
            "thresholds": QUALITY_THRESHOLDS.get(task_category, {}),
        }
    )


@mcp.tool(
    **ann("Bloom validate model", read_only=True, open_world=True),
    description=(
        "Check whether a local Ollama model is reachable and suitable for Bloom. "
        "Use this before bloom_evaluate_model. Local HTTP. Returns JSON validation fields."
    ),
)
def bloom_validate_model(
    model: Annotated[str, F("Local Ollama model name to validate.")],
) -> str:
    from src.bloom.ollama_adapter import OllamaModelAdapter

    adapter = OllamaModelAdapter()
    return _json(adapter.validate_model_for_bloom(model))


# ---------------------------------------------------------------------------
# Phase 7 — Studio 2.9 and 3.0 entity inventory
# ---------------------------------------------------------------------------


@mcp.tool(
    **ann("List Studio catalogue", read_only=True),
    description=(
        "Return row counts for every known Studio entity type. "
        "Use a specific list_* tool for the rows themselves. Read-only. Returns JSON counts."
    ),
)
def list_studio_catalogue(
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    return _inventory_json(lambda: inventory.catalogue_summary(workspace=workspace))


@mcp.tool(
    **ann("List workspaces", read_only=True),
    description=(
        "List Studio workspaces. "
        "Use get_studio_entity with entity=workspaces for one workspace, and list_studio_catalogue for counts. "
        "On Studio 3.0 the storage key shows where each workspace lives, which one is active, "
        "and any stale copy left behind by a storage move. "
        "Read-only. Returns JSON items up to limit."
    ),
)
def list_workspaces(
    limit: Annotated[int, F("Maximum rows. Integer from 1 to 500. Default 100.")] = 100,
) -> str:
    result = inventory.list_entities("workspaces", limit=limit)
    try:
        layout = storage_layout()
        if layout.workspaces or layout.stale_copies:
            result["storage"] = layout.to_dict()
    except Exception as exc:
        result["storage_error"] = str(exc)
    return _storage_json(result)


@mcp.tool(
    **ann("List personas", read_only=True),
    description=(
        "List personas from Persona Studio. "
        "Use generate_persona to create one, list_shadow_personas for Shadow Personas, and get_studio_entity for one row. "
        "Read-only. Returns JSON items up to limit."
    ),
)
def list_personas(
    limit: Annotated[int, F("Maximum rows. Integer from 1 to 500. Default 100.")] = 100,
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    return _inventory_json(lambda: inventory.list_entities("personas", limit=limit, workspace=workspace))


@mcp.tool(
    **ann("List shadow personas", read_only=True),
    description=(
        "List Shadow Personas, which are variants of ordinary personas. "
        "Use list_personas for the main Persona Studio list, and get_studio_entity for one row. "
        "Read-only. Returns JSON items up to limit."
    ),
)
def list_shadow_personas(
    limit: Annotated[int, F("Maximum rows. Integer from 1 to 500. Default 100.")] = 100,
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    return _inventory_json(lambda: inventory.list_entities("shadow_personas", limit=limit, workspace=workspace))


@mcp.tool(
    **ann("List crews", read_only=True),
    description=(
        "List Crew Mode crews from Studio, with crew folders on Studio 3.0. "
        "Use get_studio_entity with entity=crews for one crew, and list_personas for members. "
        "Read-only. Returns JSON items up to limit."
    ),
)
def list_crews(
    limit: Annotated[int, F("Maximum rows. Integer from 1 to 500. Default 100.")] = 100,
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    def build() -> Dict[str, Any]:
        result = inventory.list_entities("crews", limit=limit, workspace=workspace)
        folders = inventory.list_entities("crew_folders", limit=limit, workspace=workspace)
        if folders.get("items") or "note" not in folders:
            result["folders"] = folders.get("items", [])
        return result

    return _inventory_json(build)


@mcp.tool(
    **ann("List knowledge stacks", read_only=True),
    description=(
        "List Knowledge Stacks, including Next Gen stacks. "
        "Use optimise_knowledge_stacks for suggestions, and get_studio_entity for one stack. "
        "Read-only. Returns JSON items up to limit."
    ),
)
def list_knowledge_stacks(
    limit: Annotated[int, F("Maximum rows. Integer from 1 to 500. Default 100.")] = 100,
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    return _inventory_json(lambda: inventory.list_entities("knowledge_stacks", limit=limit, workspace=workspace))


@mcp.tool(
    **ann("List turnstiles", read_only=True),
    description=(
        "List Turnstile and Turnstiles vNext routing definitions from Studio. "
        "Use get_studio_entity with entity=turnstiles for one row, and list_studio_catalogue for counts. "
        "Read-only. Returns JSON items up to limit."
    ),
)
def list_turnstiles(
    limit: Annotated[int, F("Maximum rows. Integer from 1 to 500. Default 100.")] = 100,
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    return _inventory_json(lambda: inventory.list_entities("turnstiles", limit=limit, workspace=workspace))


@mcp.tool(
    **ann("List skills", read_only=True),
    description=(
        "List Skills Studio preferences and folders. Skills are imported as JSON packs, not SQLite inserts. "
        "Read-only. Returns JSON skills and folders."
    ),
)
def list_skills(
    limit: Annotated[int, F("Maximum rows. Integer from 1 to 500. Default 100.")] = 100,
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    return _inventory_json(
        lambda: {
            "skills": inventory.list_entities("skills", limit=limit, workspace=workspace),
            "folders": inventory.list_entities("skill_folders", limit=limit, workspace=workspace),
        }
    )


@mcp.tool(
    **ann("List live contexts", read_only=True),
    description=(
        "List Live Contexts that Studio injects into chats. "
        "Use list_context_studio for attachment files, and get_studio_entity for one row. "
        "Read-only. Returns JSON items up to limit."
    ),
)
def list_live_contexts(
    limit: Annotated[int, F("Maximum rows. Integer from 1 to 500. Default 100.")] = 100,
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    return _inventory_json(lambda: inventory.list_entities("live_contexts", limit=limit, workspace=workspace))


@mcp.tool(
    **ann("List prompts", read_only=True),
    description=(
        "List Prompts Studio library entries. "
        "Use import_studio_pack to add prompts, and get_studio_entity for one row. "
        "Read-only. Returns JSON items up to limit."
    ),
)
def list_prompts(
    limit: Annotated[int, F("Maximum rows. Integer from 1 to 500. Default 100.")] = 100,
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    return _inventory_json(lambda: inventory.list_entities("prompts", limit=limit, workspace=workspace))


@mcp.tool(
    **ann("List Context Studio", read_only=True),
    description=(
        "List Context Studio attachments and their folders. "
        "Use list_live_contexts for Live Context rows, and get_studio_entity for one attachment. "
        "Read-only. Returns JSON attachments and folders up to limit."
    ),
)
def list_context_studio(
    limit: Annotated[int, F("Maximum rows. Integer from 1 to 500. Default 100.")] = 100,
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    return _inventory_json(
        lambda: {
            "attachments": inventory.list_entities("attachments", limit=limit, workspace=workspace),
            "folders": inventory.list_entities("attachment_folders", limit=limit, workspace=workspace),
        }
    )


@mcp.tool(
    **ann("List agent plans", read_only=True),
    description=(
        "List Agent Mode plans stored in Studio. "
        "Use get_studio_entity with entity=agent_plans for one plan, and list_crews for Crew Mode. "
        "Read-only. Returns JSON items up to limit."
    ),
)
def list_agent_plans(
    limit: Annotated[int, F("Maximum rows. Integer from 1 to 500. Default 100.")] = 100,
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    return _inventory_json(lambda: inventory.list_entities("agent_plans", limit=limit, workspace=workspace))


@mcp.tool(
    **ann("Get Studio entity", read_only=True),
    description=(
        "Fetch one Studio entity by catalogue type and id. "
        "Use the matching list_* tool to discover ids. Plural keys are canonical. Singular aliases are accepted. "
        "Read-only. Returns JSON item or the allowed type list."
    ),
)
def get_studio_entity(
    entity: Annotated[
        str,
        F("Catalogue key such as personas, crews or knowledge_stacks. Singular aliases such as persona are accepted."),
    ],
    entity_id: Annotated[str, F("Row id in that table.")],
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    return _inventory_json(lambda: inventory.get_entity(entity, entity_id, workspace=workspace))


@mcp.tool(
    **ann("Get schema migrations", read_only=True),
    description=(
        "Show recent Drizzle schema migrations from the Studio database. "
        "Use get_msty_installation for the app version. Read-only. Returns JSON migrations."
    ),
)
def get_schema_migrations(
    limit: Annotated[int, F("Maximum rows. Integer from 1 to 100. Default 20.")] = 20,
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    try:
        rows = db.fetch_all(
            "__drizzle_migrations",
            limit=limit,
            order_by="created_at DESC",
            database_path=inventory.workspace_database(workspace),
        )
        return _storage_json({"migrations": rows, "count": len(rows)})
    except Exception as exc:
        return _storage_json({"error": str(exc), "migrations": []})


@mcp.tool(
    **ann("Export workflow pack", read_only=True),
    description=(
        "Export a read-only workflow pack of personas, tools, turnstiles and stacks. "
        "Does not write Studio. Use import_studio_pack to bring a pack back in. Returns JSON pack."
    ),
)
def export_workflow_pack(
    include: Annotated[
        Optional[List[str]],
        F("Optional entity kinds to include, such as personas or tools. Omit for the default set."),
    ] = None,
    limit: Annotated[int, F("Maximum rows per kind. Integer from 1 to 500. Default 200.")] = 200,
    workspace: Annotated[
        Optional[str],
        F(WORKSPACE_HELP),
    ] = None,
) -> str:
    return _inventory_json(
        lambda: inventory.export_workflow_pack(include=include, limit=limit, workspace=workspace)
    )


# ---------------------------------------------------------------------------
# Phase 8 — Nexus bridge
# ---------------------------------------------------------------------------


@mcp.tool(
    **ann("Get Nexus", read_only=True, open_world=True),
    description=(
        "Detect the Msty Nexus local gateway and its port. "
        "Use list_models with backend=nexus for model names. Local HTTP. Returns JSON found, endpoint and port."
    ),
)
def get_nexus() -> str:
    return _json(nexus.nexus_status())


@mcp.tool(
    **ann("Query Nexus", read_only=False, idempotent=False, open_world=True),
    description=(
        "Call the Nexus OpenAI-compatible gateway with a path. "
        "Use list_models with backend=nexus for model names. Local HTTP. Returns the gateway JSON or an error."
    ),
)
def query_nexus(
    path: Annotated[
        str, F("Gateway path such as /v1/models or /v1/chat/completions. Default /v1/models.")
    ] = "/v1/models",
    method: Annotated[str, F("HTTP method. GET or POST. Default GET.")] = "GET",
    data: Annotated[
        Optional[Dict[str, Any]], F("JSON body for POST. Omit for GET.")
    ] = None,
) -> str:
    return _json(nexus.query_nexus(path=path, method=method, data=data))


@mcp.tool(
    **ann("Get insights usage", read_only=True),
    description=(
        "Read Studio insights usage for one model or all models. "
        "Same data as get_model_performance_metrics. Read-only. Returns JSON totals and models."
    ),
)
def get_insights_usage(
    model_id: Annotated[
        Optional[str], F("Optional model id to filter. Omit for all models.")
    ] = None,
    timeframe: Annotated[str, F("Window such as 7d, 30d or all. Default 7d.")] = "7d",
) -> str:
    return _storage_json(analytics.get_insights_usage(model_id=model_id, timeframe=timeframe))


# ---------------------------------------------------------------------------
# Phase 9 — Frontier handoff
# ---------------------------------------------------------------------------


@mcp.tool(
    **ann("Ask Frontier", read_only=False, idempotent=False, open_world=True),
    description=(
        "Send one hard question to Cursor (default), Grok or Claude and return the answer. "
        "Stay as this one tool. Use escalate_if_needed when you also want a reason field. "
        "Calls the network. Needs the matching API key. Call once, then stop. Returns the answer text."
    ),
)
def ask_frontier(
    question: Annotated[str, F("Question for the cloud model.")],
    provider: Annotated[
        Optional[str], F("Cloud provider: cursor, grok or claude. Default cursor.")
    ] = None,
    fresh: Annotated[
        bool, F("Set true to start a new cloud chat instead of continuing the last session. Default false.")
    ] = False,
) -> str:
    from src.frontier import ask_frontier as dispatch_frontier

    try:
        outcome = dispatch_frontier(question, provider=provider, fresh=fresh)
    except Exception as exc:
        return f"Frontier handoff failed: {exc}"
    return outcome.answer


def main() -> None:
    parser = argparse.ArgumentParser(description="Msty Admin MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port")
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
    else:
        # Serve the real MCP endpoint (/mcp). The old hand-built Starlette app
        # only exposed /health and crashed on Starlette 1.x (no app.route).
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
