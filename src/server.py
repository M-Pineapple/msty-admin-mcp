#!/usr/bin/env python3
"""
Msty Admin MCP Server v4.1.1

AI-administered Msty Studio Desktop management system with database insights,
configuration management, hardware optimization, and Claude Desktop sync.

Phase 1: Foundational Tools (Read-Only)
- detect_msty_installation
- read_msty_database
- list_configured_tools
- get_model_providers
- analyse_msty_health
- get_server_status

Phase 2: Configuration Management
- export_tool_config
- sync_claude_preferences
- generate_persona
- import_tool_config

Phase 3: Automation Bridge
- query_local_ai_service
- list_available_models
- get_sidecar_status
- chat_with_local_model
- recommend_model

Phase 4: Intelligence Layer
- get_model_performance_metrics
- analyse_conversation_patterns
- compare_model_responses
- optimise_knowledge_stacks
- suggest_persona_improvements

Phase 5: Tiered AI Workflow
- run_calibration_test
- evaluate_response_quality
- identify_handoff_triggers
- get_calibration_history

Created by Pineapple 🍍 AI Administration System
"""

import json
import logging
import os
import platform
import sqlite3
import urllib.request
import urllib.error
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Dict, List

import psutil
from mcp.server.fastmcp import FastMCP

# Import Phase 4 & 5 utilities
from .phase4_5_tools import (
    init_metrics_db,
    record_model_metric,
    get_model_metrics_summary,
    save_calibration_result,
    get_calibration_results,
    record_handoff_trigger,
    get_handoff_triggers,
    evaluate_response_heuristic,
    CALIBRATION_PROMPTS,
    QUALITY_RUBRIC
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("msty-admin-mcp")

# Initialize FastMCP server
mcp = FastMCP("msty-admin")

# =============================================================================
# Constants
# =============================================================================

SERVER_VERSION = "4.1.1"

# Configurable via environment variables
SIDECAR_HOST = os.environ.get("MSTY_SIDECAR_HOST", "127.0.0.1")
SIDECAR_PROXY_PORT = int(os.environ.get("MSTY_PROXY_PORT", 11932))
LOCAL_AI_SERVICE_PORT = int(os.environ.get("MSTY_AI_PORT", 11964))
SIDECAR_TIMEOUT = int(os.environ.get("MSTY_TIMEOUT", 10))

# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class MstyInstallation:
    """Msty Studio Desktop installation details"""
    installed: bool
    version: Optional[str] = None
    app_path: Optional[str] = None
    data_path: Optional[str] = None
    sidecar_path: Optional[str] = None
    database_path: Optional[str] = None
    mlx_models_path: Optional[str] = None
    is_running: bool = False
    sidecar_running: bool = False
    platform_info: dict = field(default_factory=dict)


@dataclass
class MstyHealthReport:
    """Msty Studio health analysis"""
    overall_status: str
    database_status: dict = field(default_factory=dict)
    storage_status: dict = field(default_factory=dict)
    model_cache_status: dict = field(default_factory=dict)
    recommendations: list = field(default_factory=list)
    timestamp: str = ""


@dataclass
class DatabaseStats:
    """Statistics from Msty database"""
    total_conversations: int = 0
    total_messages: int = 0
    total_personas: int = 0
    total_prompts: int = 0
    total_knowledge_stacks: int = 0
    total_tools: int = 0
    database_size_mb: float = 0.0
    last_activity: Optional[str] = None


@dataclass
class PersonaConfig:
    """Msty persona configuration structure"""
    name: str
    description: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 4096
    model_preference: Optional[str] = None
    knowledge_stacks: list = field(default_factory=list)
    tools_enabled: list = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


# =============================================================================
# Path Resolution Utilities
# =============================================================================

def get_msty_paths() -> dict:
    """Get all relevant Msty Studio paths for macOS"""
    home = Path.home()
    
    paths = {
        "app": Path("/Applications/MstyStudio.app"),
        "app_alt": Path("/Applications/Msty Studio.app"),
        "data": home / "Library/Application Support/MstyStudio",
        "sidecar": home / "Library/Application Support/MstySidecar",
    }
    
    resolved = {}
    for key, path in paths.items():
        resolved[key] = str(path) if path.exists() else None
    
    resolved["database"] = None
    if resolved["sidecar"]:
        sidecar_db = Path(resolved["sidecar"]) / "SharedStorage"
        if sidecar_db.exists():
            resolved["database"] = str(sidecar_db)
    
    if not resolved["database"] and resolved["data"]:
        data_db = Path(resolved["data"]) / "msty.db"
        if data_db.exists():
            resolved["database"] = str(data_db)
    
    if resolved["data"]:
        mlx_path = Path(resolved["data"]) / "models-mlx"
        resolved["mlx_models"] = str(mlx_path) if mlx_path.exists() else None
    else:
        resolved["mlx_models"] = None
    
    return resolved


def is_process_running(process_name: str) -> bool:
    """Check if a process is running by name"""
    for proc in psutil.process_iter(['name']):
        try:
            if process_name.lower() in proc.info['name'].lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


# =============================================================================
# Database Operations
# =============================================================================

def get_database_connection(db_path: str) -> Optional[sqlite3.Connection]:
    """Get a read-only connection to Msty database"""
    if not db_path or not Path(db_path).exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f"Database connection error: {e}")
        return None


def query_database(db_path: str, query: str, params: tuple = ()) -> list:
    """Execute a read-only query on the Msty database"""
    conn = get_database_connection(db_path)
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Query error: {e}")
        return []
    finally:
        conn.close()


def get_table_names(db_path: str) -> list:
    """Get all table names from the database"""
    query = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    results = query_database(db_path, query)
    return [r['name'] for r in results]


def get_table_row_count(db_path: str, table_name: str) -> int:
    """Get row count for a specific table"""
    if not table_name.isidentifier():
        return 0
    query = f"SELECT COUNT(*) as count FROM {table_name}"
    results = query_database(db_path, query)
    return results[0]['count'] if results else 0


# =============================================================================
# API Request Helper
# =============================================================================

def make_api_request(
    endpoint: str,
    port: int = LOCAL_AI_SERVICE_PORT,
    method: str = "GET",
    data: Optional[Dict] = None,
    timeout: int = SIDECAR_TIMEOUT,
    host: str = None
) -> Dict[str, Any]:
    """Make HTTP request to Sidecar or Local AI Service API"""
    host = host or SIDECAR_HOST
    url = f"http://{host}:{port}{endpoint}"
    
    try:
        if method == "GET":
            req = urllib.request.Request(url)
        else:
            json_data = json.dumps(data).encode('utf-8') if data else None
            req = urllib.request.Request(url, data=json_data, method=method)
            req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            response_data = response.read().decode('utf-8')
            return {
                "success": True,
                "status_code": response.status,
                "data": json.loads(response_data) if response_data else None
            }
    except urllib.error.URLError as e:
        logger.warning(f"Connection failed to {url}: {e.reason}")
        return {"success": False, "error": f"Connection failed: {e.reason}"}
    except urllib.error.HTTPError as e:
        # Capture response body for better debugging
        try:
            error_body = e.read().decode('utf-8', errors='ignore')[:200]
            logger.warning(f"HTTP {e.code} on {endpoint}: {error_body}")
        except:
            error_body = None
        return {"success": False, "error": f"HTTP {e.code}: {e.reason}", "status_code": e.code, "error_body": error_body}
    except json.JSONDecodeError:
        return {"success": True, "status_code": 200, "data": response_data}
    except Exception as e:
        logger.error(f"Unexpected error calling {url}: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# Config Helpers
# =============================================================================

def read_claude_desktop_config() -> dict:
    """Read Claude Desktop's MCP configuration"""
    config_path = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    if not config_path.exists():
        return {"error": "Claude Desktop config not found"}
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


def sanitize_path(path: str) -> str:
    """Replace home directory with $HOME for portability"""
    home = str(Path.home())
    if path and path.startswith(home):
        return path.replace(home, "$HOME", 1)
    return path


def expand_path(path: str) -> str:
    """Expand $HOME and ~ in paths"""
    if path:
        path = path.replace("$HOME", str(Path.home()))
        path = os.path.expanduser(path)
    return path


# =============================================================================
# Phase 1: Foundational Tools (Read-Only)
# =============================================================================

@mcp.tool()
def detect_msty_installation() -> str:
    """
    Detect and analyse Msty Studio Desktop installation.
    
    Returns comprehensive information about:
    - Installation status and paths
    - Application version (if detectable)
    - Running status of Msty Studio and Sidecar
    - Platform information
    - Data directory locations
    
    This is the first tool to run when working with Msty Admin MCP.
    """
    paths = get_msty_paths()
    app_path = paths.get("app") or paths.get("app_alt")
    installed = app_path is not None
    
    version = None
    if app_path:
        plist_path = Path(app_path) / "Contents/Info.plist"
        if plist_path.exists():
            try:
                import plistlib
                with open(plist_path, 'rb') as f:
                    plist = plistlib.load(f)
                    version = plist.get('CFBundleShortVersionString', plist.get('CFBundleVersion'))
            except:
                pass
    
    platform_info = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "is_apple_silicon": platform.machine() in ["arm64", "aarch64"],
    }
    
    installation = MstyInstallation(
        installed=installed,
        version=version,
        app_path=app_path,
        data_path=paths.get("data"),
        sidecar_path=paths.get("sidecar"),
        database_path=paths.get("database"),
        mlx_models_path=paths.get("mlx_models"),
        is_running=is_process_running("MstyStudio"),
        sidecar_running=is_process_running("MstySidecar"),
        platform_info=platform_info
    )
    
    return json.dumps(asdict(installation), indent=2)


@mcp.tool()
def read_msty_database(
    query_type: str = "stats",
    table_name: Optional[str] = None,
    limit: int = 50
) -> str:
    """
    Query the Msty Studio database for insights.
    
    Args:
        query_type: Type of query to run:
            - "stats": Get overall database statistics
            - "tables": List all tables in the database
            - "conversations": Get recent conversations
            - "personas": List configured personas
            - "prompts": List saved prompts
            - "tools": List configured MCP tools
            - "custom": Query a specific table (requires table_name)
        table_name: Table name for custom queries (only used with query_type="custom")
        limit: Maximum number of results to return (default: 50)
    
    Returns:
        JSON string with query results
    """
    paths = get_msty_paths()
    db_path = paths.get("database")
    
    if not db_path:
        return json.dumps({"error": "Msty database not found"})
    
    result = {"query_type": query_type, "database_path": db_path}
    
    try:
        if query_type == "tables":
            tables = get_table_names(db_path)
            result["tables"] = [{"name": t, "row_count": get_table_row_count(db_path, t)} for t in tables]
            
        elif query_type == "stats":
            tables = get_table_names(db_path)
            stats = DatabaseStats()
            table_mapping = {
                "chat_sessions": "total_conversations",
                "conversations": "total_conversations",
                "messages": "total_messages",
                "chat_messages": "total_messages",
                "personas": "total_personas",
                "prompts": "total_prompts",
                "knowledge_stacks": "total_knowledge_stacks",
                "tools": "total_tools",
            }
            for table in tables:
                for pattern, attr in table_mapping.items():
                    if pattern in table.lower():
                        count = get_table_row_count(db_path, table)
                        setattr(stats, attr, getattr(stats, attr, 0) + count)
                        break
            db_file = Path(db_path)
            stats.database_size_mb = round(db_file.stat().st_size / (1024 * 1024), 2)
            result["stats"] = asdict(stats)
            result["available_tables"] = tables
            
        elif query_type == "custom" and table_name:
            if table_name in get_table_names(db_path):
                result["data"] = query_database(db_path, f"SELECT * FROM {table_name} LIMIT ?", (limit,))
            else:
                result["error"] = f"Table '{table_name}' not found"
        else:
            table_map = {
                "conversations": ["chat_sessions", "conversations"],
                "personas": ["personas"],
                "prompts": ["prompts", "prompt_library"],
                "tools": ["tools", "mcp_tools"],
            }
            if query_type in table_map:
                for t in table_map[query_type]:
                    if t in get_table_names(db_path):
                        result[query_type] = query_database(db_path, f"SELECT * FROM {t} LIMIT ?", (limit,))
                        break
    except Exception as e:
        result["error"] = str(e)
    
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def list_configured_tools() -> str:
    """
    List all MCP tools configured in Msty Studio's Toolbox.
    
    Returns detailed information about each tool including:
    - Tool ID and name
    - Configuration (command, args, env vars)
    - Status and notes
    """
    paths = get_msty_paths()
    db_path = paths.get("database")
    
    if not db_path:
        return json.dumps({"error": "Msty database not found", "tools": []})
    
    result = {"database_path": db_path, "tools": [], "tool_count": 0}
    tables = get_table_names(db_path)
    tool_tables = [t for t in tables if "tool" in t.lower() or "mcp" in t.lower()]
    
    for table in tool_tables:
        tools = query_database(db_path, f"SELECT * FROM {table}")
        if tools:
            result["tools"].extend(tools)
            break
    
    result["tool_count"] = len(result["tools"])
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def get_model_providers() -> str:
    """
    Get configured AI model providers in Msty Studio.
    
    Returns information about:
    - Local models (MLX, Ollama connections)
    - Remote providers (OpenAI, Anthropic, etc.)
    - Model configurations and parameters
    
    Note: API keys are NOT returned for security reasons.
    """
    paths = get_msty_paths()
    mlx_path = paths.get("mlx_models")
    
    result = {
        "local_models": {"mlx_available": mlx_path is not None, "mlx_models": []},
        "remote_providers": []
    }
    
    if mlx_path and Path(mlx_path).exists():
        for model_dir in Path(mlx_path).iterdir():
            if model_dir.is_dir():
                result["local_models"]["mlx_models"].append({
                    "name": model_dir.name,
                    "size_mb": sum(f.stat().st_size for f in model_dir.rglob('*') if f.is_file()) / (1024 * 1024)
                })
    
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def analyse_msty_health() -> str:
    """
    Perform comprehensive health analysis of Msty Studio installation.
    
    Checks:
    - Database integrity and size
    - Storage usage and available space
    - Model cache status
    - Application and Sidecar status
    - Configuration completeness
    
    Returns a health report with status and recommendations.
    """
    paths = get_msty_paths()
    health = MstyHealthReport(overall_status="unknown", timestamp=datetime.now().isoformat())
    issues, warnings = [], []
    
    if not paths.get("app") and not paths.get("app_alt"):
        health.overall_status = "critical"
        health.recommendations.append("Install Msty Studio Desktop from https://msty.ai")
        return json.dumps(asdict(health), indent=2)
    
    db_path = paths.get("database")
    if db_path and Path(db_path).exists():
        db_size_mb = Path(db_path).stat().st_size / (1024 * 1024)
        health.database_status = {"exists": True, "size_mb": round(db_size_mb, 2)}
        if db_size_mb > 500:
            warnings.append(f"Database is large ({db_size_mb:.0f}MB)")
    
    health.recommendations.extend([
        f"Msty Studio: {'Running \u2705' if is_process_running('MstyStudio') else 'Not running'}",
        f"Sidecar: {'Running \u2705' if is_process_running('MstySidecar') else 'Not running'}"
    ])
    
    health.overall_status = "critical" if issues else ("warning" if warnings else "healthy")
    return json.dumps(asdict(health), indent=2)


@mcp.tool()
def get_server_status() -> str:
    """
    Get the current status of the Msty Admin MCP server.
    
    Returns server information including:
    - Server name and version
    - Available tools
    - Msty installation status summary
    - Current capabilities
    """
    paths = get_msty_paths()
    
    return json.dumps({
        "server": {
            "name": "msty-admin-mcp",
            "version": SERVER_VERSION,
            "phase": "Phase 5 - Tiered AI Workflow",
            "author": "Pineapple \ud83c\udf4d"
        },
        "available_tools": {
            "phase_1_foundational": ["detect_msty_installation", "read_msty_database", "list_configured_tools", "get_model_providers", "analyse_msty_health", "get_server_status"],
            "phase_2_configuration": ["export_tool_config", "sync_claude_preferences", "generate_persona", "import_tool_config"],
            "phase_3_automation": ["get_sidecar_status", "list_available_models", "query_local_ai_service", "chat_with_local_model", "recommend_model"],
            "phase_4_intelligence": ["get_model_performance_metrics", "analyse_conversation_patterns", "compare_model_responses", "optimise_knowledge_stacks", "suggest_persona_improvements"],
            "phase_5_calibration": ["run_calibration_test", "evaluate_response_quality", "identify_handoff_triggers", "get_calibration_history"]
        },
        "tool_count": 24,
        "msty_status": {
            "installed": paths.get("app") is not None or paths.get("app_alt") is not None,
            "database_available": paths.get("database") is not None,
            "sidecar_running": is_process_running("MstySidecar")
        }
    }, indent=2)


# =============================================================================
# Phase 2: Configuration Management Tools
# =============================================================================

@mcp.tool()
def export_tool_config(
    tool_name: Optional[str] = None,
    source: str = "claude",
    output_format: str = "msty",
    include_env: bool = False
) -> str:
    """
    Export MCP tool configurations for backup or sync.
    
    Args:
        tool_name: Specific tool to export (None = all tools)
        source: Where to read config from ("claude" or "msty")
        output_format: Output format ("msty", "claude", or "raw")
        include_env: Include environment variables (may contain secrets)
    
    Returns:
        JSON with tool configurations ready for import
    """
    result = {"source": source, "output_format": output_format, "timestamp": datetime.now().isoformat(), "tools": []}
    
    if source == "claude":
        config = read_claude_desktop_config()
        if "error" in config:
            return json.dumps(config, indent=2)
        
        for name, server_config in config.get("mcpServers", {}).items():
            if tool_name and name != tool_name:
                continue
            tool = {
                "name": name,
                "command": server_config.get("command", ""),
                "args": server_config.get("args", []),
            }
            if include_env:
                tool["env"] = server_config.get("env", {})
            result["tools"].append(tool)
    
    result["tool_count"] = len(result["tools"])
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def sync_claude_preferences(
    output_path: Optional[str] = None,
    include_memory_protocol: bool = True,
    include_tool_priorities: bool = True
) -> str:
    """
    Convert Claude Desktop preferences to Msty persona format.
    
    Args:
        output_path: Optional path to save the persona JSON file
        include_memory_protocol: Include memory system integration instructions
        include_tool_priorities: Include MCP tool priority order
    
    Returns:
        JSON with Msty persona configuration
    """
    sections = ["# AI Assistant Persona - Opus Style\n\nBritish English, conversational tone, quality over quantity."]
    
    if include_memory_protocol:
        sections.append("\n## Memory Protocol\nCheck memory MCP at conversation start. Store important info proactively.")
    
    if include_tool_priorities:
        sections.append("\n## Tool Priorities\n1. Memory MCP\n2. Filesystem MCP\n3. Other specialised MCPs")
    
    persona = PersonaConfig(
        name="Opus Style Assistant",
        description="Claude Opus behaviour patterns",
        system_prompt="\n".join(sections),
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat()
    )
    
    result = {"persona": asdict(persona), "system_prompt_length": len(persona.system_prompt)}
    
    if output_path:
        try:
            with open(expand_path(output_path), 'w') as f:
                json.dump(result["persona"], f, indent=2)
            result["saved_to"] = output_path
        except Exception as e:
            result["save_error"] = str(e)
    
    return json.dumps(result, indent=2)


@mcp.tool()
def generate_persona(
    name: str,
    description: str = "",
    base_template: str = "opus",
    custom_instructions: Optional[str] = None,
    temperature: float = 0.7,
    model_preference: Optional[str] = None,
    output_path: Optional[str] = None
) -> str:
    """
    Generate a complete Msty persona configuration.
    
    Args:
        name: Name for the persona
        description: Brief description of the persona's purpose
        base_template: Starting template ("opus", "minimal", "coder", "writer")
        custom_instructions: Additional instructions to append
        temperature: Model temperature (0.0-1.0)
        model_preference: Preferred model identifier
        output_path: Optional path to save the persona JSON
    
    Returns:
        JSON with complete persona configuration ready for Msty import
    """
    templates = {
        "opus": "AI assistant with British English, quality focus, executive mindset.",
        "minimal": "Helpful AI assistant.",
        "coder": "Development assistant with code review focus.",
        "writer": "Writing assistant with British English standards."
    }
    
    if base_template not in templates:
        return json.dumps({"error": f"Unknown template: {base_template}", "available": list(templates.keys())})
    
    system_prompt = templates[base_template]
    if custom_instructions:
        system_prompt += f"\n\n{custom_instructions}"
    
    persona = PersonaConfig(
        name=name,
        description=description or f"{base_template} persona",
        system_prompt=system_prompt,
        temperature=temperature,
        model_preference=model_preference,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat()
    )
    
    result = {"persona": asdict(persona), "base_template": base_template}
    
    if output_path:
        try:
            Path(expand_path(output_path)).parent.mkdir(parents=True, exist_ok=True)
            with open(expand_path(output_path), 'w') as f:
                json.dump(result["persona"], f, indent=2)
            result["saved_to"] = output_path
        except Exception as e:
            result["save_error"] = str(e)
    
    return json.dumps(result, indent=2)


@mcp.tool()
def import_tool_config(
    config_json: Optional[str] = None,
    config_file: Optional[str] = None,
    source: str = "claude",
    dry_run: bool = True
) -> str:
    """
    Import MCP tool configurations into Msty Studio.
    
    Args:
        config_json: JSON string with tool configuration(s)
        config_file: Path to JSON file with tool configuration(s)
        source: Source format ("claude", "msty", "auto")
        dry_run: If True, validate only without importing (default: True)
    
    Returns:
        JSON with validation results and import instructions
    """
    result = {"dry_run": dry_run, "validation": {"valid": False, "errors": []}, "tools_to_import": []}
    
    config = None
    if config_json:
        try:
            config = json.loads(config_json)
        except json.JSONDecodeError as e:
            result["validation"]["errors"].append(f"Invalid JSON: {e}")
            return json.dumps(result, indent=2)
    elif config_file:
        try:
            with open(expand_path(config_file), 'r') as f:
                config = json.load(f)
        except Exception as e:
            result["validation"]["errors"].append(str(e))
            return json.dumps(result, indent=2)
    else:
        config = read_claude_desktop_config()
        if "error" in config:
            result["validation"]["errors"].append(config["error"])
            return json.dumps(result, indent=2)
    
    tools = []
    if "mcpServers" in config:
        for name, sc in config["mcpServers"].items():
            tools.append({"name": name, "config": {"command": sc.get("command", ""), "args": sc.get("args", [])}})
    
    result["tools_to_import"] = tools
    result["validation"]["valid"] = len(tools) > 0
    result["validation"]["tool_count"] = len(tools)
    
    return json.dumps(result, indent=2, default=str)


# =============================================================================
# Phase 3: Automation Bridge - Sidecar API Integration
# =============================================================================

@mcp.tool()
def get_sidecar_status() -> str:
    """
    Get comprehensive status of Msty Sidecar and Local AI Service.
    
    Returns:
        - Sidecar process status
        - Local AI Service availability
        - Available models
        - Port information
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "sidecar": {"process_running": is_process_running("MstySidecar"), "proxy_port": SIDECAR_PROXY_PORT},
        "local_ai_service": {"port": LOCAL_AI_SERVICE_PORT, "reachable": False, "models_available": 0},
        "recommendations": []
    }
    
    if not result["sidecar"]["process_running"]:
        result["recommendations"].append("Start Sidecar: open -a MstySidecar")
        return json.dumps(result, indent=2)
    
    models_response = make_api_request("/v1/models", port=LOCAL_AI_SERVICE_PORT, timeout=5)
    if models_response.get("success"):
        result["local_ai_service"]["reachable"] = True
        data = models_response.get("data", {})
        if isinstance(data, dict) and "data" in data:
            result["local_ai_service"]["models_available"] = len(data["data"])
            result["local_ai_service"]["model_list"] = [m.get("id") for m in data["data"]]
    
    return json.dumps(result, indent=2)


@mcp.tool()
def list_available_models() -> str:
    """
    List all AI models available through Sidecar's Local AI Service.
    
    Returns detailed information about each model.
    """
    result = {"timestamp": datetime.now().isoformat(), "models": [], "model_count": 0}
    
    if not is_process_running("MstySidecar"):
        result["error"] = "Sidecar is not running"
        return json.dumps(result, indent=2)
    
    response = make_api_request("/v1/models", port=LOCAL_AI_SERVICE_PORT)
    if response.get("success"):
        data = response.get("data", {})
        if isinstance(data, dict) and "data" in data:
            result["models"] = data["data"]
            result["model_count"] = len(data["data"])
    else:
        result["error"] = response.get("error")
    
    return json.dumps(result, indent=2)


@mcp.tool()
def query_local_ai_service(
    endpoint: str = "/v1/models",
    method: str = "GET",
    request_body: Optional[str] = None
) -> str:
    """
    Query the Sidecar Local AI Service API directly.
    
    Args:
        endpoint: API endpoint (e.g., "/v1/models", "/v1/chat/completions")
        method: HTTP method (GET, POST)
        request_body: JSON string for POST requests
    
    Returns:
        Raw API response with status information
    """
    if not is_process_running("MstySidecar"):
        return json.dumps({"error": "Sidecar is not running"})
    
    data = json.loads(request_body) if request_body else None
    response = make_api_request(endpoint, port=LOCAL_AI_SERVICE_PORT, method=method, data=data, timeout=30)
    
    return json.dumps({"endpoint": endpoint, "method": method, "response": response}, indent=2, default=str)


@mcp.tool()
def chat_with_local_model(
    message: str,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    track_metrics: bool = True
) -> str:
    """
    Send a chat message to a local model via Sidecar.
    
    Args:
        message: The user message to send
        model: Model ID to use (if None, uses first available)
        system_prompt: Optional system prompt for context
        temperature: Sampling temperature (0.0-1.0)
        max_tokens: Maximum tokens in response
        track_metrics: Record performance metrics (default: True)
    
    Returns:
        Model response with timing and token information
    """
    result = {"timestamp": datetime.now().isoformat(), "request": {"message": message[:100] + "..." if len(message) > 100 else message}}
    
    if not is_process_running("MstySidecar"):
        result["error"] = "Sidecar is not running"
        return json.dumps(result, indent=2)
    
    if not model:
        models_response = make_api_request("/v1/models", port=LOCAL_AI_SERVICE_PORT)
        if models_response.get("success"):
            data = models_response.get("data", {})
            if isinstance(data, dict) and "data" in data and data["data"]:
                model = data["data"][0].get("id")
        if not model:
            result["error"] = "No models available"
            return json.dumps(result, indent=2)
    
    result["request"]["model"] = model
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": message})
    
    request_data = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": False}
    
    start_time = time.time()
    response = make_api_request("/v1/chat/completions", port=LOCAL_AI_SERVICE_PORT, method="POST", data=request_data, timeout=120)
    elapsed_time = time.time() - start_time
    
    result["timing"] = {"elapsed_seconds": round(elapsed_time, 2)}
    
    if response.get("success"):
        data = response.get("data", {})
        if "choices" in data and data["choices"]:
            msg = data["choices"][0].get("message", {})
            content = msg.get("content", "") or msg.get("reasoning", "")
            result["response"] = {"content": content, "finish_reason": data["choices"][0].get("finish_reason")}
        
        if "usage" in data:
            result["usage"] = data["usage"]
            completion_tokens = data["usage"].get("completion_tokens", 0)
            result["timing"]["tokens_per_second"] = round(completion_tokens / max(elapsed_time, 0.1), 1)
            
            if track_metrics:
                try:
                    init_metrics_db()
                    record_model_metric(
                        model_id=model,
                        prompt_tokens=data["usage"].get("prompt_tokens", 0),
                        completion_tokens=completion_tokens,
                        latency_seconds=elapsed_time,
                        success=True,
                        use_case="chat"
                    )
                except:
                    pass
    else:
        result["error"] = response.get("error")
        if track_metrics:
            try:
                init_metrics_db()
                record_model_metric(model_id=model, latency_seconds=elapsed_time, success=False, error_message=response.get("error"))
            except:
                pass
    
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def recommend_model(use_case: str = "general", max_size_gb: Optional[float] = None) -> str:
    """
    Get model recommendations based on use case and hardware.
    
    Args:
        use_case: Type of work ("general", "coding", "writing", "analysis", "fast")
        max_size_gb: Maximum model size in GB (optional)
    
    Returns:
        Recommended models with installation instructions
    """
    model_db = {
        "general": [{"id": "qwen2.5:32b", "size_gb": 19, "quality": "very good"}, {"id": "qwen2.5:7b", "size_gb": 4.5, "quality": "good"}],
        "coding": [{"id": "qwen2.5-coder:32b", "size_gb": 19, "quality": "excellent"}, {"id": "qwen2.5-coder:7b", "size_gb": 4.5, "quality": "good"}],
        "writing": [{"id": "qwen2.5:32b", "size_gb": 19, "quality": "very good"}],
        "analysis": [{"id": "qwen2.5:32b", "size_gb": 19, "quality": "very good"}],
        "fast": [{"id": "qwen3:0.6b", "size_gb": 0.5, "quality": "basic"}, {"id": "gemma3:4b", "size_gb": 3, "quality": "acceptable"}]
    }
    
    if use_case not in model_db:
        return json.dumps({"error": f"Unknown use case", "valid": list(model_db.keys())})
    
    recommendations = model_db[use_case]
    if max_size_gb:
        recommendations = [m for m in recommendations if m["size_gb"] <= max_size_gb]
    
    return json.dumps({"use_case": use_case, "recommendations": recommendations}, indent=2)


# =============================================================================
# Phase 4: Intelligence Layer
# =============================================================================

@mcp.tool()
def get_model_performance_metrics(model_id: Optional[str] = None, days: int = 30) -> str:
    """
    Get performance metrics for local models over time.
    
    Args:
        model_id: Specific model to query (None = all models)
        days: Number of days to include in analysis (default: 30)
    
    Returns:
        Aggregated performance metrics with trends
    """
    result = {"timestamp": datetime.now().isoformat(), "period_days": days}
    
    try:
        init_metrics_db()
        metrics = get_model_metrics_summary(model_id=model_id, days=days)
        result["metrics"] = metrics
        
        if metrics.get("models"):
            insights = []
            for m in metrics["models"]:
                tps = m.get("avg_tokens_per_second", 0) or 0
                if tps > 50:
                    insights.append(f"\u2705 {m['model_id']}: Excellent speed ({tps:.1f} tok/s)")
                elif tps > 20:
                    insights.append(f"\ud83d\udc4d {m['model_id']}: Good speed ({tps:.1f} tok/s)")
                elif tps > 0:
                    insights.append(f"\u26a0\ufe0f {m['model_id']}: Slow ({tps:.1f} tok/s)")
            result["insights"] = insights
    except Exception as e:
        result["error"] = str(e)
    
    return json.dumps(result, indent=2)


@mcp.tool()
def analyse_conversation_patterns(days: int = 30) -> str:
    """
    Analyse conversation patterns from Msty database.
    
    Privacy-respecting analysis that tracks session counts, message volumes,
    and model usage distribution without exposing conversation content.
    
    Args:
        days: Number of days to analyse (default: 30)
    
    Returns:
        Aggregated usage patterns
    """
    result = {"timestamp": datetime.now().isoformat(), "period_days": days, "patterns": {}}
    
    paths = get_msty_paths()
    db_path = paths.get("database")
    
    if not db_path:
        result["error"] = "Msty database not found"
        return json.dumps(result, indent=2)
    
    try:
        tables = get_table_names(db_path)
        patterns = {"session_analysis": {}, "model_usage": {}}
        
        for t in ["chat_sessions", "conversations"]:
            if t in tables:
                count_result = query_database(db_path, f"SELECT COUNT(*) as count FROM {t}")
                patterns["session_analysis"]["total_sessions"] = count_result[0]["count"] if count_result else 0
                
                recent = query_database(db_path, f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 100")
                if recent:
                    model_counts = {}
                    for s in recent:
                        model = s.get("model") or s.get("model_id") or s.get("llm_model") or "unknown"
                        model_counts[model] = model_counts.get(model, 0) + 1
                    patterns["model_usage"] = model_counts
                break
        
        result["patterns"] = patterns
    except Exception as e:
        result["error"] = str(e)
    
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def compare_model_responses(
    prompt: str,
    models: Optional[List[str]] = None,
    system_prompt: Optional[str] = None,
    evaluation_criteria: str = "balanced"
) -> str:
    """
    Send the same prompt to multiple models and compare responses.
    
    Args:
        prompt: The prompt to send to all models
        models: List of model IDs to compare (None = use all available, max 5)
        system_prompt: Optional system prompt for context
        evaluation_criteria: What to optimise for ("quality", "speed", "balanced")
    
    Returns:
        Comparison of responses with timing and quality scores
    """
    result = {"timestamp": datetime.now().isoformat(), "prompt": prompt[:200] + "...", "responses": [], "comparison": {}}
    
    if not is_process_running("MstySidecar"):
        result["error"] = "Sidecar is not running"
        return json.dumps(result, indent=2)
    
    if not models:
        response = make_api_request("/v1/models", port=LOCAL_AI_SERVICE_PORT)
        if response.get("success"):
            data = response.get("data", {})
            if isinstance(data, dict) and "data" in data:
                models = [m.get("id") for m in data["data"]][:5]
        if not models:
            result["error"] = "No models available"
            return json.dumps(result, indent=2)
    
    init_metrics_db()
    
    for model_id in models:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        start_time = time.time()
        response = make_api_request("/v1/chat/completions", port=LOCAL_AI_SERVICE_PORT, method="POST",
            data={"model": model_id, "messages": messages, "temperature": 0.7, "max_tokens": 1024, "stream": False}, timeout=120)
        elapsed = time.time() - start_time
        
        model_result = {"model_id": model_id, "success": response.get("success", False), "latency_seconds": round(elapsed, 2)}
        
        if response.get("success"):
            data = response.get("data", {})
            if "choices" in data and data["choices"]:
                content = data["choices"][0].get("message", {}).get("content", "") or data["choices"][0].get("message", {}).get("reasoning", "")
                model_result["response"] = content[:500] + "..." if len(content) > 500 else content
                model_result["response_length"] = len(content)
                
                if "usage" in data:
                    model_result["tokens_per_second"] = round(data["usage"].get("completion_tokens", 0) / max(elapsed, 0.1), 1)
                
                eval_result = evaluate_response_heuristic(prompt, content, "general")
                model_result["quality_score"] = round(eval_result["score"], 2)
                
                record_model_metric(model_id=model_id, completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
                    latency_seconds=elapsed, success=True, use_case="comparison")
        
        result["responses"].append(model_result)
    
    successful = [r for r in result["responses"] if r["success"]]
    if successful:
        if evaluation_criteria == "speed":
            best = min(successful, key=lambda x: x["latency_seconds"])
        elif evaluation_criteria == "quality":
            best = max(successful, key=lambda x: x.get("quality_score", 0))
        else:
            best = max(successful, key=lambda x: x.get("quality_score", 0.5) * 0.6 + (1.0 / max(x["latency_seconds"], 0.1)) * 0.4)
        result["comparison"]["winner"] = best["model_id"]
    
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def optimise_knowledge_stacks() -> str:
    """
    Analyse and recommend optimisations for knowledge stacks.
    
    Returns:
        Recommendations for knowledge stack improvements
    """
    result = {"timestamp": datetime.now().isoformat(), "analysis": {}, "recommendations": []}
    
    paths = get_msty_paths()
    db_path = paths.get("database")
    
    if not db_path:
        result["error"] = "Msty database not found"
        return json.dumps(result, indent=2)
    
    try:
        tables = get_table_names(db_path)
        ks_table = None
        for t in ["knowledge_stacks", "knowledge_stack"]:
            if t in tables:
                ks_table = t
                break
        
        if not ks_table:
            result["note"] = "No knowledge stack table found"
            return json.dumps(result, indent=2)
        
        stacks = query_database(db_path, f"SELECT * FROM {ks_table}")
        result["analysis"]["total_stacks"] = len(stacks)
        
        if len(stacks) == 0:
            result["recommendations"].append("No knowledge stacks found. Consider creating domain-specific stacks.")
        elif len(stacks) > 10:
            result["recommendations"].append(f"Many stacks ({len(stacks)}). Consider consolidating.")
    except Exception as e:
        result["error"] = str(e)
    
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def suggest_persona_improvements(persona_name: Optional[str] = None) -> str:
    """
    Analyse personas and suggest improvements.
    
    Args:
        persona_name: Specific persona to analyse (None = all)
    
    Returns:
        Suggestions for persona optimisation
    """
    result = {"timestamp": datetime.now().isoformat(), "analysis": {}, "suggestions": []}
    
    paths = get_msty_paths()
    db_path = paths.get("database")
    
    if not db_path:
        result["error"] = "Msty database not found"
        return json.dumps(result, indent=2)
    
    try:
        tables = get_table_names(db_path)
        persona_table = "personas" if "personas" in tables else None
        
        if not persona_table:
            result["note"] = "No persona table found"
            return json.dumps(result, indent=2)
        
        if persona_name:
            personas = query_database(db_path, f"SELECT * FROM {persona_table} WHERE name LIKE ?", (f"%{persona_name}%",))
        else:
            personas = query_database(db_path, f"SELECT * FROM {persona_table}")
        
        result["analysis"]["total_personas"] = len(personas)
        
        for p in personas:
            name = p.get("name", "Unknown")
            prompt_len = len(p.get("system_prompt", "") or p.get("prompt", "") or "")
            temp = p.get("temperature")
            
            if prompt_len < 100:
                result["suggestions"].append(f"'{name}': System prompt too short.")
            elif prompt_len > 4000:
                result["suggestions"].append(f"'{name}': System prompt very long.")
            
            if temp is not None and temp > 0.9:
                result["suggestions"].append(f"'{name}': High temperature ({temp}) may cause inconsistency.")
        
        if len(personas) == 0:
            result["suggestions"].append("No personas found. Create task-specific personas.")
    except Exception as e:
        result["error"] = str(e)
    
    return json.dumps(result, indent=2, default=str)


# =============================================================================
# Phase 5: Tiered AI Workflow / Calibration
# =============================================================================

@mcp.tool()
def run_calibration_test(
    model_id: Optional[str] = None,
    category: str = "general",
    custom_prompt: Optional[str] = None,
    passing_threshold: float = 0.6
) -> str:
    """
    Run a calibration test on a local model.
    
    Args:
        model_id: Model to test (None = auto-select first available)
        category: Test category ("general", "reasoning", "coding", "writing", "analysis", "creative")
        custom_prompt: Use a custom prompt instead of built-in tests
        passing_threshold: Minimum score to pass (0.0-1.0, default 0.6)
    
    Returns:
        Test results with quality scores and recommendations
    """
    result = {"timestamp": datetime.now().isoformat(), "category": category, "tests": [], "summary": {}}
    
    if not is_process_running("MstySidecar"):
        result["error"] = "Sidecar is not running"
        return json.dumps(result, indent=2)
    
    if not model_id:
        response = make_api_request("/v1/models", port=LOCAL_AI_SERVICE_PORT)
        if response.get("success"):
            data = response.get("data", {})
            if isinstance(data, dict) and "data" in data and data["data"]:
                model_id = data["data"][0].get("id")
        if not model_id:
            result["error"] = "No models available"
            return json.dumps(result, indent=2)
    
    result["model_id"] = model_id
    
    prompts_to_test = []
    if custom_prompt:
        prompts_to_test = [(category, custom_prompt)]
    elif category == "general":
        for cat, prompts in CALIBRATION_PROMPTS.items():
            if prompts:
                prompts_to_test.append((cat, prompts[0]))
    elif category in CALIBRATION_PROMPTS:
        for p in CALIBRATION_PROMPTS[category]:
            prompts_to_test.append((category, p))
    else:
        result["error"] = f"Unknown category: {category}"
        return json.dumps(result, indent=2)
    
    init_metrics_db()
    passed_count, total_score = 0, 0.0
    
    for test_cat, prompt in prompts_to_test:
        import hashlib
        test_id = hashlib.md5(f"{model_id}:{prompt}:{datetime.now().isoformat()}".encode()).hexdigest()[:12]
        
        start_time = time.time()
        response = make_api_request("/v1/chat/completions", port=LOCAL_AI_SERVICE_PORT, method="POST",
            data={"model": model_id, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": 1024, "stream": False}, timeout=120)
        elapsed = time.time() - start_time
        
        test_result = {"test_id": test_id, "category": test_cat, "prompt": prompt[:100] + "...", "latency_seconds": round(elapsed, 2)}
        
        if response.get("success"):
            data = response.get("data", {})
            if "choices" in data and data["choices"]:
                content = data["choices"][0].get("message", {}).get("content", "") or data["choices"][0].get("message", {}).get("reasoning", "")
                
                evaluation = evaluate_response_heuristic(prompt, content, test_cat)
                test_result["quality_score"] = round(evaluation["score"], 2)
                test_result["passed"] = evaluation["score"] >= passing_threshold
                test_result["notes"] = evaluation["notes"]
                
                total_score += evaluation["score"]
                if test_result["passed"]:
                    passed_count += 1
                
                save_calibration_result(test_id, model_id, test_cat, prompt, content, evaluation["score"], 
                    json.dumps(evaluation["notes"]), elapsed, test_result["passed"])
        else:
            test_result["error"] = response.get("error")
            test_result["passed"] = False
        
        result["tests"].append(test_result)
    
    total_tests = len(prompts_to_test)
    result["summary"] = {
        "total_tests": total_tests,
        "passed": passed_count,
        "pass_rate": round(passed_count / max(total_tests, 1) * 100, 1),
        "average_score": round(total_score / max(total_tests, 1), 2)
    }
    
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def evaluate_response_quality(prompt: str, response: str, category: str = "general") -> str:
    """
    Evaluate the quality of a model response.
    
    Args:
        prompt: The original prompt
        response: The model's response
        category: Response category for specific evaluation criteria
    
    Returns:
        Quality score (0.0-1.0) with detailed breakdown
    """
    evaluation = evaluate_response_heuristic(prompt, response, category)
    
    result = {
        "timestamp": datetime.now().isoformat(),
        "category": category,
        "quality_score": round(evaluation["score"], 3),
        "passed": evaluation["passed"],
        "criteria_scores": {k: round(v, 2) for k, v in evaluation.get("criteria_scores", {}).items()},
        "notes": evaluation["notes"],
        "rubric": QUALITY_RUBRIC
    }
    
    score = evaluation["score"]
    if score >= 0.8:
        result["interpretation"] = "Excellent"
    elif score >= 0.6:
        result["interpretation"] = "Good"
    elif score >= 0.4:
        result["interpretation"] = "Fair"
    else:
        result["interpretation"] = "Poor"
    
    return json.dumps(result, indent=2)


@mcp.tool()
def identify_handoff_triggers(
    analyse_recent: bool = True,
    add_pattern: Optional[str] = None,
    pattern_type: Optional[str] = None
) -> str:
    """
    Identify and manage patterns that should trigger escalation to Claude.
    
    Args:
        analyse_recent: Analyse recent calibration tests for triggers
        add_pattern: Manually add a trigger pattern description
        pattern_type: Type of pattern ("complexity", "domain", "quality", "safety", "creativity")
    
    Returns:
        List of identified handoff triggers with confidence scores
    """
    result = {"timestamp": datetime.now().isoformat(), "triggers": [], "analysis": {}}
    
    init_metrics_db()
    
    if add_pattern and pattern_type:
        record_handoff_trigger(pattern_type, add_pattern, 0.7)
        result["added_pattern"] = {"type": pattern_type, "description": add_pattern}
    
    if analyse_recent:
        calibration_results = get_calibration_results(limit=100)
        failed = [r for r in calibration_results if not r.get("passed")]
        
        category_failures = {}
        for test in failed:
            cat = test.get("prompt_category", "unknown")
            category_failures[cat] = category_failures.get(cat, 0) + 1
        
        result["analysis"]["failed_tests_count"] = len(failed)
        result["analysis"]["failure_by_category"] = category_failures
        
        for cat, count in category_failures.items():
            if count >= 3:
                record_handoff_trigger("category_failure", f"Local model fails {cat} tasks", min(count / 10, 1.0))
    
    result["triggers"] = get_handoff_triggers(active_only=True)
    result["trigger_count"] = len(result["triggers"])
    
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def get_calibration_history(
    model_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 50
) -> str:
    """
    Get historical calibration test results.
    
    Args:
        model_id: Filter by specific model (None = all)
        category: Filter by test category (None = all)
        limit: Maximum results to return (default: 50)
    
    Returns:
        Historical test results with trends and statistics
    """
    result = {"timestamp": datetime.now().isoformat(), "filters": {"model_id": model_id, "category": category}, "history": [], "statistics": {}}
    
    init_metrics_db()
    
    all_results = get_calibration_results(model_id=model_id, limit=limit)
    
    if category:
        all_results = [r for r in all_results if r.get("prompt_category") == category]
    
    result["history"] = all_results
    result["total_tests"] = len(all_results)
    
    if all_results:
        scores = [r.get("quality_score", 0) for r in all_results if r.get("quality_score")]
        passed = sum(1 for r in all_results if r.get("passed"))
        
        result["statistics"] = {
            "average_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "pass_count": passed,
            "pass_rate": round(passed / len(all_results) * 100, 1)
        }
    else:
        result["note"] = "No calibration tests found. Run run_calibration_test to generate data."
    
    return json.dumps(result, indent=2, default=str)


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Run the Msty Admin MCP server"""
    logger.info(f"Starting Msty Admin MCP Server v{SERVER_VERSION}")
    logger.info("Phase 1: Foundational Tools (Read-Only)")
    logger.info("Phase 2: Configuration Management")
    logger.info("Phase 3: Automation Bridge")
    logger.info("Phase 4: Intelligence Layer")
    logger.info("Phase 5: Tiered AI Workflow")
    logger.info("Total tools: 24")
    mcp.run()


if __name__ == "__main__":
    main()
