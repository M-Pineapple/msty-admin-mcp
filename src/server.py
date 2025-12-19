#!/usr/bin/env python3
"""
Msty Admin MCP Server

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

Created by Pineapple 🍍 AI Administration System
"""

import json
import logging
import os
import platform
import sqlite3
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Dict, List

import psutil
from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("msty-admin-mcp")

# Initialize FastMCP server
mcp = FastMCP("msty-admin")

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
    overall_status: str  # healthy, warning, critical
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
        "legacy_app": Path("/Applications/Msty.app"),
        "legacy_data": home / "Library/Application Support/Msty",
    }
    
    # Resolve actual paths
    resolved = {}
    for key, path in paths.items():
        resolved[key] = str(path) if path.exists() else None
    
    # Find database - check multiple locations
    resolved["database"] = None
    
    # Primary: SharedStorage in Sidecar folder (Msty 2.x)
    if resolved["sidecar"]:
        sidecar_db = Path(resolved["sidecar"]) / "SharedStorage"
        if sidecar_db.exists():
            resolved["database"] = str(sidecar_db)
    
    # Fallback: msty.db in data folder (older versions)
    if not resolved["database"] and resolved["data"]:
        data_db = Path(resolved["data"]) / "msty.db"
        if data_db.exists():
            resolved["database"] = str(data_db)
    
    # MLX models path
    if resolved["data"]:
        mlx_path = Path(resolved["data"]) / "models-mlx"
        resolved["mlx_models"] = str(mlx_path) if mlx_path.exists() else None
    else:
        resolved["mlx_models"] = None
    
    # Check sidecar token
    if resolved["sidecar"]:
        token_path = Path(resolved["sidecar"]) / ".token"
        resolved["sidecar_token"] = str(token_path) if token_path.exists() else None
    else:
        resolved["sidecar_token"] = None
    
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
        # Connect in read-only mode
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
        results = [dict(row) for row in cursor.fetchall()]
        return results
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
    # Sanitize table name to prevent SQL injection
    if not table_name.isidentifier():
        return 0
    query = f"SELECT COUNT(*) as count FROM {table_name}"
    results = query_database(db_path, query)
    return results[0]['count'] if results else 0


# =============================================================================
# MCP Tools - Phase 1: Foundational (Read-Only)
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
    
    # Determine if installed
    app_path = paths.get("app") or paths.get("app_alt")
    installed = app_path is not None
    
    # Get version from Info.plist if possible
    version = None
    if app_path:
        plist_path = Path(app_path) / "Contents/Info.plist"
        if plist_path.exists():
            try:
                import plistlib
                with open(plist_path, 'rb') as f:
                    plist = plistlib.load(f)
                    version = plist.get('CFBundleShortVersionString', 
                                       plist.get('CFBundleVersion'))
            except Exception as e:
                logger.warning(f"Could not read version: {e}")
    
    # Check running status
    msty_running = is_process_running("MstyStudio") or is_process_running("Msty Studio")
    sidecar_running = is_process_running("MstySidecar")
    
    # Platform info
    platform_info = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "is_apple_silicon": platform.machine() in ["arm64", "aarch64"],
        "python_version": platform.python_version()
    }
    
    installation = MstyInstallation(
        installed=installed,
        version=version,
        app_path=app_path,
        data_path=paths.get("data"),
        sidecar_path=paths.get("sidecar"),
        database_path=paths.get("database"),
        mlx_models_path=paths.get("mlx_models"),
        is_running=msty_running,
        sidecar_running=sidecar_running,
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
        return json.dumps({
            "error": "Msty database not found",
            "suggestion": "Ensure Msty Studio Desktop is installed and has been run at least once"
        })
    
    result = {"query_type": query_type, "database_path": db_path}
    
    try:
        if query_type == "tables":
            tables = get_table_names(db_path)
            table_info = []
            for table in tables:
                count = get_table_row_count(db_path, table)
                table_info.append({"name": table, "row_count": count})
            result["tables"] = table_info
            
        elif query_type == "stats":
            tables = get_table_names(db_path)
            stats = DatabaseStats()
            
            # Map common table names to stats
            table_mapping = {
                "chat_sessions": "total_conversations",
                "conversations": "total_conversations",
                "messages": "total_messages",
                "chat_messages": "total_messages",
                "personas": "total_personas",
                "prompts": "total_prompts",
                "knowledge_stacks": "total_knowledge_stacks",
                "tools": "total_tools",
                "mcp_tools": "total_tools"
            }
            
            for table in tables:
                table_lower = table.lower()
                for pattern, attr in table_mapping.items():
                    if pattern in table_lower:
                        count = get_table_row_count(db_path, table)
                        current = getattr(stats, attr, 0)
                        setattr(stats, attr, current + count)
                        break
            
            # Get database file size
            db_file = Path(db_path)
            stats.database_size_mb = round(db_file.stat().st_size / (1024 * 1024), 2)
            
            result["stats"] = asdict(stats)
            result["available_tables"] = tables
            
        elif query_type == "conversations":
            # Try common table names for conversations
            for table in ["chat_sessions", "conversations", "chat_session_folders"]:
                if table in get_table_names(db_path):
                    query = f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?"
                    result["conversations"] = query_database(db_path, query, (limit,))
                    result["source_table"] = table
                    break
            else:
                result["error"] = "No conversation table found"
                
        elif query_type == "personas":
            for table in ["personas", "persona"]:
                if table in get_table_names(db_path):
                    query = f"SELECT * FROM {table} LIMIT ?"
                    result["personas"] = query_database(db_path, query, (limit,))
                    result["source_table"] = table
                    break
            else:
                result["error"] = "No personas table found"
                
        elif query_type == "prompts":
            for table in ["prompts", "prompt_library", "saved_prompts"]:
                if table in get_table_names(db_path):
                    query = f"SELECT * FROM {table} LIMIT ?"
                    result["prompts"] = query_database(db_path, query, (limit,))
                    result["source_table"] = table
                    break
            else:
                result["error"] = "No prompts table found"
                
        elif query_type == "tools":
            for table in ["tools", "mcp_tools", "toolbox"]:
                if table in get_table_names(db_path):
                    query = f"SELECT * FROM {table} LIMIT ?"
                    result["tools"] = query_database(db_path, query, (limit,))
                    result["source_table"] = table
                    break
            else:
                result["error"] = "No tools table found"
                
        elif query_type == "custom":
            if not table_name:
                result["error"] = "table_name required for custom queries"
            elif table_name not in get_table_names(db_path):
                result["error"] = f"Table '{table_name}' not found"
                result["available_tables"] = get_table_names(db_path)
            else:
                query = f"SELECT * FROM {table_name} LIMIT ?"
                result["data"] = query_database(db_path, query, (limit,))
                result["source_table"] = table_name
        else:
            result["error"] = f"Unknown query_type: {query_type}"
            result["valid_types"] = ["stats", "tables", "conversations", "personas", "prompts", "tools", "custom"]
            
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Database query error: {e}")
    
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def list_configured_tools() -> str:
    """
    List all MCP tools configured in Msty Studio's Toolbox.
    
    Returns detailed information about each tool including:
    - Tool ID and name
    - Configuration (command, args, env vars)
    - Status and notes
    
    This helps understand what integrations are available in Msty
    and assists with Claude Desktop sync operations.
    """
    paths = get_msty_paths()
    db_path = paths.get("database")
    
    if not db_path:
        return json.dumps({
            "error": "Msty database not found",
            "tools": []
        })
    
    result = {
        "database_path": db_path,
        "tools": [],
        "tool_count": 0
    }
    
    # Try to find tools in various possible table structures
    tables = get_table_names(db_path)
    tool_tables = [t for t in tables if any(x in t.lower() for x in ["tool", "mcp"])]
    
    for table in tool_tables:
        query = f"SELECT * FROM {table}"
        tools = query_database(db_path, query)
        if tools:
            result["tools"].extend(tools)
            result["source_table"] = table
            break
    
    result["tool_count"] = len(result["tools"])
    result["available_tool_tables"] = tool_tables
    
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
    db_path = paths.get("database")
    mlx_path = paths.get("mlx_models")
    
    result = {
        "local_models": {
            "mlx_available": mlx_path is not None,
            "mlx_path": mlx_path,
            "mlx_models": []
        },
        "remote_providers": [],
        "database_providers": []
    }
    
    # List MLX models if available
    if mlx_path and Path(mlx_path).exists():
        mlx_dir = Path(mlx_path)
        for model_dir in mlx_dir.iterdir():
            if model_dir.is_dir():
                model_info = {
                    "name": model_dir.name,
                    "path": str(model_dir),
                    "size_mb": sum(f.stat().st_size for f in model_dir.rglob('*') if f.is_file()) / (1024 * 1024)
                }
                result["local_models"]["mlx_models"].append(model_info)
    
    # Query database for provider configurations
    if db_path:
        tables = get_table_names(db_path)
        provider_tables = [t for t in tables if any(x in t.lower() for x in ["provider", "model", "remote"])]
        
        for table in provider_tables:
            query = f"SELECT * FROM {table}"
            providers = query_database(db_path, query)
            if providers:
                # Sanitize - remove any API keys
                for p in providers:
                    for key in list(p.keys()):
                        if any(x in key.lower() for x in ["key", "secret", "token", "password"]):
                            p[key] = "[REDACTED]"
                result["database_providers"].extend(providers)
                result["provider_source_table"] = table
    
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
    
    health = MstyHealthReport(
        overall_status="unknown",
        timestamp=datetime.now().isoformat()
    )
    
    issues = []
    warnings = []
    
    # Check installation
    if not paths.get("app") and not paths.get("app_alt"):
        issues.append("Msty Studio Desktop not installed")
        health.overall_status = "critical"
        health.recommendations.append("Install Msty Studio Desktop from https://msty.ai")
        return json.dumps(asdict(health), indent=2)
    
    # Database health
    db_path = paths.get("database")
    if db_path and Path(db_path).exists():
        db_file = Path(db_path)
        db_size_mb = db_file.stat().st_size / (1024 * 1024)
        
        # Check WAL files
        wal_path = Path(f"{db_path}-wal")
        shm_path = Path(f"{db_path}-shm")
        wal_size = wal_path.stat().st_size / (1024 * 1024) if wal_path.exists() else 0
        
        health.database_status = {
            "exists": True,
            "path": db_path,
            "size_mb": round(db_size_mb, 2),
            "wal_size_mb": round(wal_size, 2),
            "has_wal": wal_path.exists(),
            "has_shm": shm_path.exists()
        }
        
        # Database size warnings
        if db_size_mb > 500:
            warnings.append(f"Database is large ({db_size_mb:.0f}MB) - consider cleanup")
        if wal_size > 100:
            warnings.append(f"WAL file is large ({wal_size:.0f}MB) - consider VACUUM")
            health.recommendations.append("Run database optimization: sqlite3 msty.db 'PRAGMA wal_checkpoint(FULL);'")
        
        # Test database integrity
        try:
            conn = get_database_connection(db_path)
            if conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check")
                integrity = cursor.fetchone()[0]
                health.database_status["integrity"] = integrity
                if integrity != "ok":
                    issues.append(f"Database integrity issue: {integrity}")
                conn.close()
        except Exception as e:
            health.database_status["integrity_error"] = str(e)
            warnings.append(f"Could not check database integrity: {e}")
    else:
        health.database_status = {"exists": False}
        warnings.append("Database not found - Msty may not have been run yet")
    
    # Storage health
    data_path = paths.get("data")
    if data_path:
        data_dir = Path(data_path)
        try:
            total_size = sum(f.stat().st_size for f in data_dir.rglob('*') if f.is_file())
            disk_usage = psutil.disk_usage(str(data_dir))
            
            health.storage_status = {
                "data_directory": data_path,
                "data_size_mb": round(total_size / (1024 * 1024), 2),
                "disk_total_gb": round(disk_usage.total / (1024 ** 3), 1),
                "disk_free_gb": round(disk_usage.free / (1024 ** 3), 1),
                "disk_percent_used": disk_usage.percent
            }
            
            if disk_usage.percent > 90:
                issues.append(f"Disk space critically low ({disk_usage.percent}% used)")
            elif disk_usage.percent > 80:
                warnings.append(f"Disk space getting low ({disk_usage.percent}% used)")
                
        except Exception as e:
            health.storage_status = {"error": str(e)}
    
    # Model cache health
    mlx_path = paths.get("mlx_models")
    if mlx_path and Path(mlx_path).exists():
        mlx_dir = Path(mlx_path)
        model_count = len([d for d in mlx_dir.iterdir() if d.is_dir()])
        total_size = sum(f.stat().st_size for f in mlx_dir.rglob('*') if f.is_file())
        
        health.model_cache_status = {
            "mlx_path": mlx_path,
            "model_count": model_count,
            "total_size_gb": round(total_size / (1024 ** 3), 2)
        }
        
        if total_size > 100 * (1024 ** 3):  # > 100GB
            warnings.append(f"Large model cache ({total_size / (1024**3):.1f}GB) - consider cleanup")
    else:
        health.model_cache_status = {"mlx_available": False}
    
    # Process status
    msty_running = is_process_running("MstyStudio") or is_process_running("Msty Studio")
    sidecar_running = is_process_running("MstySidecar")
    
    health.recommendations.extend([
        f"Msty Studio: {'Running ✅' if msty_running else 'Not running'}",
        f"Sidecar: {'Running ✅' if sidecar_running else 'Not running - MCP tools may not work'}"
    ])
    
    if not sidecar_running:
        health.recommendations.append("Start Sidecar: open -a MstySidecar (from Terminal for best dependency detection)")
    
    # Determine overall status
    if issues:
        health.overall_status = "critical"
        health.recommendations = [f"❌ {i}" for i in issues] + health.recommendations
    elif warnings:
        health.overall_status = "warning"
        health.recommendations = [f"⚠️ {w}" for w in warnings] + health.recommendations
    else:
        health.overall_status = "healthy"
        health.recommendations.insert(0, "✅ Msty Studio installation is healthy")
    
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
    
    status = {
        "server": {
            "name": "msty-admin-mcp",
            "version": "3.0.0",
            "phase": "Phase 3 - Automation Bridge",
            "author": "Pineapple 🍍"
        },
        "available_tools": {
            "phase_1_foundational": [
                "detect_msty_installation",
                "read_msty_database",
                "list_configured_tools",
                "get_model_providers",
                "analyse_msty_health",
                "get_server_status"
            ],
            "phase_2_configuration": [
                "export_tool_config",
                "sync_claude_preferences",
                "generate_persona",
                "import_tool_config"
            ],
            "phase_3_automation": [
                "get_sidecar_status",
                "list_available_models",
                "query_local_ai_service",
                "chat_with_local_model",
                "recommend_model"
            ]
        },
        "tool_count": 15,
        "msty_status": {
            "installed": paths.get("app") is not None or paths.get("app_alt") is not None,
            "database_available": paths.get("database") is not None,
            "sidecar_configured": paths.get("sidecar") is not None,
            "sidecar_running": is_process_running("MstySidecar"),
            "mlx_models_available": paths.get("mlx_models") is not None
        },
        "api_endpoints": {
            "sidecar_proxy": f"http://127.0.0.1:{SIDECAR_PROXY_PORT}",
            "local_ai_service": f"http://127.0.0.1:{LOCAL_AI_SERVICE_PORT}"
        },
        "planned_phases": {
            "phase_4": "Intelligence Layer (conversation analytics, optimization)",
            "phase_5": "Tiered AI Workflow (local model calibration, Claude escalation)"
        }
    }
    
    return json.dumps(status, indent=2)


# =============================================================================
# Phase 2: Configuration Management Tools
# =============================================================================

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


@dataclass
class ToolConfig:
    """MCP tool configuration structure"""
    name: str
    command: str
    args: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    cwd: Optional[str] = None
    enabled: bool = True
    notes: str = ""


def read_claude_desktop_config() -> dict:
    """Read Claude Desktop's MCP configuration"""
    config_path = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    
    if not config_path.exists():
        return {"error": "Claude Desktop config not found", "path": str(config_path)}
    
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON in config: {e}", "path": str(config_path)}
    except Exception as e:
        return {"error": str(e), "path": str(config_path)}


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
        source: Where to read config from:
            - "claude": Claude Desktop's config
            - "msty": Msty Studio's database
        output_format: Output format:
            - "msty": Msty-compatible JSON for import
            - "claude": Claude Desktop format
            - "raw": Original format unchanged
        include_env: Include environment variables (may contain secrets)
    
    Returns:
        JSON with tool configurations ready for import
    """
    result = {
        "source": source,
        "output_format": output_format,
        "timestamp": datetime.now().isoformat(),
        "tools": []
    }
    
    if source == "claude":
        config = read_claude_desktop_config()
        if "error" in config:
            return json.dumps(config, indent=2)
        
        mcp_servers = config.get("mcpServers", {})
        
        for name, server_config in mcp_servers.items():
            if tool_name and name != tool_name:
                continue
            
            tool = {
                "name": name,
                "command": server_config.get("command", ""),
                "args": server_config.get("args", []),
                "cwd": sanitize_path(server_config.get("cwd", "")) if server_config.get("cwd") else None,
            }
            
            if include_env:
                tool["env"] = server_config.get("env", {})
            else:
                env_vars = server_config.get("env", {})
                if env_vars:
                    tool["env"] = {k: "[REDACTED]" for k in env_vars.keys()}
                    tool["env_count"] = len(env_vars)
            
            if output_format == "msty":
                tool = {
                    "name": name,
                    "type": "stdio",
                    "config": {
                        "command": tool["command"],
                        "args": tool["args"],
                        "env": tool.get("env", {}),
                    },
                    "notes": f"Imported from Claude Desktop on {datetime.now().strftime('%Y-%m-%d')}",
                    "enabled": True
                }
                if server_config.get("cwd"):
                    tool["config"]["cwd"] = sanitize_path(server_config["cwd"])
            
            result["tools"].append(tool)
        
        result["tool_count"] = len(result["tools"])
        
    elif source == "msty":
        paths = get_msty_paths()
        db_path = paths.get("database")
        
        if not db_path:
            return json.dumps({"error": "Msty database not found"})
        
        tables = get_table_names(db_path)
        tool_table = None
        for t in ["tools", "mcp_tools", "toolbox"]:
            if t in tables:
                tool_table = t
                break
        
        if not tool_table:
            return json.dumps({"error": "No tools table found in Msty database", "tables": tables})
        
        query = f"SELECT * FROM {tool_table}"
        if tool_name:
            query += f" WHERE name = ?"
            tools = query_database(db_path, query, (tool_name,))
        else:
            tools = query_database(db_path, query)
        
        for tool in tools:
            if not include_env:
                if 'env' in tool and tool['env']:
                    try:
                        env_dict = json.loads(tool['env']) if isinstance(tool['env'], str) else tool['env']
                        tool['env'] = {k: "[REDACTED]" for k in env_dict.keys()}
                    except:
                        pass
            
            if output_format == "claude":
                try:
                    config = json.loads(tool.get('config', '{}')) if isinstance(tool.get('config'), str) else tool.get('config', {})
                    tool = {
                        "name": tool.get('name'),
                        "command": config.get('command', ''),
                        "args": config.get('args', []),
                        "env": config.get('env', {}),
                    }
                    if config.get('cwd'):
                        tool["cwd"] = expand_path(config['cwd'])
                except:
                    pass
            
            result["tools"].append(tool)
        
        result["tool_count"] = len(result["tools"])
        result["source_table"] = tool_table
    
    else:
        result["error"] = f"Unknown source: {source}. Use 'claude' or 'msty'"
    
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def sync_claude_preferences(
    output_path: Optional[str] = None,
    include_memory_protocol: bool = True,
    include_tool_priorities: bool = True
) -> str:
    """
    Convert Claude Desktop preferences to Msty persona format.
    
    Reads your Universal Preferences and converts them into a Msty-compatible
    persona configuration that can be imported.
    
    Args:
        output_path: Optional path to save the persona JSON file
        include_memory_protocol: Include memory system integration instructions
        include_tool_priorities: Include MCP tool priority order
    
    Returns:
        JSON with Msty persona configuration
    """
    system_prompt_sections = []
    
    system_prompt_sections.append("""# AI Assistant Persona - Opus Style

You are an AI assistant configured to match Claude Opus behaviour patterns.

## Core Principles
- British English spelling throughout (organise, colour, centre)
- Sentence case for titles
- En dashes with spaces - like this
- Natural, conversational tone
- Quality over quantity in responses
- Executive mindset - seasoned advisor, not eager intern""")
    
    if include_memory_protocol:
        system_prompt_sections.append("""
## Memory System Integration Protocol

At the start of every conversation:
1. Check user preferences and project knowledge base first
2. Use Memory Service MCP: recall_memory as primary retrieval
3. Use Time MCP to get current date/time and timezone
4. Apply project-specific preferences when relevant
5. Synthesise all sources before responding

When important information is shared, proactively offer to store in memory.""")
    
    if include_tool_priorities:
        system_prompt_sections.append("""
## MCP Tool Priority Order

1. Memory Service MCP - Contextual snapshots, solutions, learning progress
2. Filesystem MCPs - Access local files (use $HOME/relative paths)
3. Trello MCP - Task management with file attachments
4. GitHub MCP - Git operations with enforced privacy protocols
5. Time MCP - Calendar integration for scheduling
6. Web Search MCP - API documentation, troubleshooting
7. Command Runner MCP - LAST RESORT for terminal operations""")
    
    system_prompt_sections.append("""
## Writing Style

### Lists and Formatting
- Avoid over-formatting with bullets, headers, and bold
- Use minimum formatting for clarity
- Keep tone natural in conversations
- Use prose and paragraphs for reports, not bullet points
- Only use lists when explicitly requested or essential

### Response Calibration
- Start with the core answer, not preambles
- Maximum 3-5 main points unless complexity demands more
- Skip obvious explanations - assume intelligence
- End with clear direction, not endless possibilities""")
    
    system_prompt_sections.append("""
## Privacy Protocol

- ALWAYS replace personal names with "Pineapple" in public contexts
- NEVER hardcode paths - use $HOME or relative paths
- SANITIZE all commits with generic, professional messages
- Run privacy audit before any public operations""")
    
    full_system_prompt = "\n".join(system_prompt_sections)
    
    persona = PersonaConfig(
        name="Opus Style Assistant",
        description="AI assistant configured to match Claude Opus behaviour with Universal Preferences",
        system_prompt=full_system_prompt,
        temperature=0.7,
        top_p=0.9,
        max_tokens=4096,
        model_preference=None,
        knowledge_stacks=[],
        tools_enabled=[],
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat()
    )
    
    result = {
        "persona": asdict(persona),
        "system_prompt_length": len(full_system_prompt),
        "sections_included": {
            "core_identity": True,
            "memory_protocol": include_memory_protocol,
            "tool_priorities": include_tool_priorities,
            "writing_style": True,
            "privacy_protocol": True
        },
        "usage": {
            "import_instructions": "In Msty Studio: Settings > Personas > Import > paste this JSON",
            "manual_steps": [
                "1. Open Msty Studio",
                "2. Go to Settings > Personas",
                "3. Click 'Create New' or 'Import'",
                "4. Paste the persona JSON or fill in fields manually",
                "5. Set your preferred local model",
                "6. Enable desired MCP tools"
            ]
        }
    }
    
    if output_path:
        output_file = Path(expand_path(output_path))
        try:
            with open(output_file, 'w') as f:
                json.dump(result["persona"], f, indent=2)
            result["saved_to"] = str(output_file)
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
        base_template: Starting template:
            - "opus": Claude Opus-style with Universal Preferences
            - "minimal": Basic assistant with no special instructions
            - "coder": Development-focused with code review emphasis
            - "writer": Writing-focused with British English enforcement
        custom_instructions: Additional instructions to append to system prompt
        temperature: Model temperature (0.0-1.0, default 0.7)
        model_preference: Preferred model identifier (e.g., "qwen2.5-72b")
        output_path: Optional path to save the persona JSON
    
    Returns:
        JSON with complete persona configuration ready for Msty import
    """
    templates = {
        "opus": """# AI Assistant - Opus Style

You are an advanced AI assistant optimised for thoughtful, high-quality responses.

## Core Behaviour
- British English spelling throughout
- Natural, conversational tone
- Quality over quantity
- Executive mindset - confident conclusions
- Practical wisdom over theoretical frameworks

## Response Style
- Start with the core answer
- Maximum 3-5 main points
- Skip obvious explanations
- End with clear direction

## Formatting
- Minimal formatting unless requested
- Prose over bullet points
- No excessive headers or bold text""",
        
        "minimal": """# AI Assistant

You are a helpful AI assistant.

Respond clearly and concisely to user queries.""",
        
        "coder": """# Development Assistant

You are a senior software development assistant.

## Behaviour
- British English in comments and documentation
- Proactive code review after changes
- Suggest optimisations and best practices
- Explain reasoning behind recommendations

## Code Standards
- Clean, readable code
- Proper error handling
- Meaningful variable names
- Comments for complex logic only

## Tool Usage
- Use Filesystem MCP for file operations
- Use GitHub MCP for version control
- Store solutions in Memory MCP for future reference""",
        
        "writer": """# Writing Assistant

You are a professional writing assistant specialising in British English.

## Language Standards
- British spelling: organise, colour, centre, programme
- Sentence case for titles
- En dashes with spaces - like this
- No Oxford comma

## Style
- Clear, concise prose
- Active voice preferred
- Short paragraphs (max 50 words)
- Avoid corporate jargon

## Formatting
- Minimal formatting
- Prose over bullet points
- Headers only when necessary"""
    }
    
    if base_template not in templates:
        return json.dumps({
            "error": f"Unknown template: {base_template}",
            "available_templates": list(templates.keys())
        })
    
    system_prompt = templates[base_template]
    
    if custom_instructions:
        system_prompt += f"\n\n## Custom Instructions\n\n{custom_instructions}"
    
    persona = PersonaConfig(
        name=name,
        description=description or f"Persona based on {base_template} template",
        system_prompt=system_prompt.strip(),
        temperature=temperature,
        top_p=0.9,
        max_tokens=4096,
        model_preference=model_preference,
        knowledge_stacks=[],
        tools_enabled=[],
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat()
    )
    
    result = {
        "persona": asdict(persona),
        "base_template": base_template,
        "system_prompt_length": len(system_prompt),
        "usage": {
            "import_instructions": "In Msty Studio: Settings > Personas > Import",
            "or_manual": "Copy persona fields into Msty's persona editor"
        }
    }
    
    if output_path:
        output_file = Path(expand_path(output_path))
        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, 'w') as f:
                json.dump(result["persona"], f, indent=2)
            result["saved_to"] = str(output_file)
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
    
    This tool prepares configurations for import. Due to safety constraints,
    actual database writes require explicit confirmation.
    
    Args:
        config_json: JSON string with tool configuration(s)
        config_file: Path to JSON file with tool configuration(s)
        source: Source format:
            - "claude": Claude Desktop config format
            - "msty": Already in Msty format
            - "auto": Auto-detect format
        dry_run: If True, validate only without importing (default: True)
    
    Returns:
        JSON with validation results and import instructions
    """
    result = {
        "dry_run": dry_run,
        "source_format": source,
        "timestamp": datetime.now().isoformat(),
        "validation": {
            "valid": False,
            "errors": [],
            "warnings": []
        },
        "tools_to_import": []
    }
    
    config = None
    if config_json:
        try:
            config = json.loads(config_json)
        except json.JSONDecodeError as e:
            result["validation"]["errors"].append(f"Invalid JSON: {e}")
            return json.dumps(result, indent=2)
    elif config_file:
        config_path = Path(expand_path(config_file))
        if not config_path.exists():
            result["validation"]["errors"].append(f"File not found: {config_file}")
            return json.dumps(result, indent=2)
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
        except Exception as e:
            result["validation"]["errors"].append(f"Error reading file: {e}")
            return json.dumps(result, indent=2)
    else:
        claude_config = read_claude_desktop_config()
        if "error" in claude_config:
            result["validation"]["errors"].append(claude_config["error"])
            return json.dumps(result, indent=2)
        config = claude_config
    
    tools = []
    
    if "mcpServers" in config:
        for name, server_config in config["mcpServers"].items():
            tool = {
                "name": name,
                "type": "stdio",
                "config": {
                    "command": server_config.get("command", ""),
                    "args": server_config.get("args", []),
                    "env": server_config.get("env", {}),
                },
                "enabled": True
            }
            if server_config.get("cwd"):
                tool["config"]["cwd"] = sanitize_path(server_config["cwd"])
            tools.append(tool)
    elif "tools" in config:
        tools = config["tools"]
    elif isinstance(config, list):
        tools = config
    else:
        result["validation"]["errors"].append("Could not find tools in configuration")
        return json.dumps(result, indent=2)
    
    valid_tools = []
    for tool in tools:
        tool_errors = []
        tool_warnings = []
        
        if not tool.get("name"):
            tool_errors.append("Missing 'name' field")
        
        config_obj = tool.get("config", tool)
        if not config_obj.get("command"):
            tool_errors.append("Missing 'command' field")
        
        command = config_obj.get("command", "")
        command_path = expand_path(command)
        if command_path and not command_path.startswith("/") and command not in ["npx", "uvx", "python", "python3", "node"]:
            tool_warnings.append(f"Command '{command}' may need full path")
        elif command_path.startswith("/") and not Path(command_path).exists():
            tool_warnings.append(f"Command path does not exist: {command_path}")
        
        cwd = config_obj.get("cwd")
        if cwd:
            cwd_path = expand_path(cwd)
            if not Path(cwd_path).exists():
                tool_warnings.append(f"Working directory does not exist: {cwd}")
        
        if tool_errors:
            result["validation"]["errors"].extend([f"{tool.get('name', 'unknown')}: {e}" for e in tool_errors])
        else:
            tool["_validation"] = {
                "valid": True,
                "warnings": tool_warnings
            }
            valid_tools.append(tool)
            if tool_warnings:
                result["validation"]["warnings"].extend([f"{tool.get('name')}: {w}" for w in tool_warnings])
    
    result["tools_to_import"] = valid_tools
    result["validation"]["valid"] = len(valid_tools) > 0 and len(result["validation"]["errors"]) == 0
    result["validation"]["tool_count"] = len(valid_tools)
    
    if dry_run:
        result["next_steps"] = {
            "to_import": "Call import_tool_config with dry_run=False to generate import file",
            "manual_import": "In Msty Studio: Toolbox > Import > paste the tool configurations",
            "note": "Direct database writes not yet implemented - use manual import via Msty UI"
        }
    else:
        paths = get_msty_paths()
        output_dir = Path(paths.get("data", Path.home() / "Desktop")) / "imports"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_file = output_dir / f"mcp_tools_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        export_data = {
            "_meta": {
                "exported_from": "msty-admin-mcp",
                "timestamp": datetime.now().isoformat(),
                "tool_count": len(valid_tools)
            },
            "tools": valid_tools
        }
        
        try:
            with open(output_file, 'w') as f:
                json.dump(export_data, f, indent=2)
            result["export_file"] = str(output_file)
            result["import_instructions"] = [
                f"1. Open file: {output_file}",
                "2. In Msty Studio: Toolbox > Import",
                "3. Paste the tool configurations or select the file",
                "4. Verify and enable each tool"
            ]
        except Exception as e:
            result["export_error"] = str(e)
    
    return json.dumps(result, indent=2, default=str)


# =============================================================================
# Phase 3: Automation Bridge - Sidecar API Integration
# =============================================================================

# Sidecar API Configuration
SIDECAR_PROXY_PORT = 11932      # Sidecar proxy/web interface
LOCAL_AI_SERVICE_PORT = 11964   # Ollama-compatible Local AI Service
SIDECAR_TIMEOUT = 10            # Request timeout in seconds


def get_sidecar_config() -> Dict[str, Any]:
    """Read Sidecar configuration from config.json"""
    paths = get_msty_paths()
    sidecar_path = paths.get("sidecar")
    
    if not sidecar_path:
        return {"error": "Sidecar path not found"}
    
    config_file = Path(sidecar_path) / "config.json"
    if not config_file.exists():
        return {"error": "Sidecar config.json not found", "path": str(config_file)}
    
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"Failed to read config: {e}"}


def make_api_request(
    endpoint: str,
    port: int = LOCAL_AI_SERVICE_PORT,
    method: str = "GET",
    data: Optional[Dict] = None,
    timeout: int = SIDECAR_TIMEOUT
) -> Dict[str, Any]:
    """Make HTTP request to Sidecar or Local AI Service API"""
    url = f"http://127.0.0.1:{port}{endpoint}"
    
    try:
        if method == "GET":
            req = urllib.request.Request(url)
        else:
            json_data = json.dumps(data).encode('utf-8') if data else None
            req = urllib.request.Request(
                url, 
                data=json_data,
                method=method
            )
            req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            response_data = response.read().decode('utf-8')
            return {
                "success": True,
                "status_code": response.status,
                "data": json.loads(response_data) if response_data else None
            }
    except urllib.error.URLError as e:
        return {
            "success": False,
            "error": f"Connection failed: {e.reason}",
            "suggestion": "Ensure Sidecar is running"
        }
    except urllib.error.HTTPError as e:
        return {
            "success": False,
            "error": f"HTTP {e.code}: {e.reason}",
            "status_code": e.code
        }
    except json.JSONDecodeError:
        return {
            "success": True,
            "status_code": 200,
            "data": response_data,
            "note": "Response was not JSON"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def get_sidecar_status() -> str:
    """
    Get comprehensive status of Msty Sidecar and Local AI Service.
    
    Returns:
        - Sidecar process status
        - Local AI Service availability
        - Available models
        - Configuration details
        - Port information
    
    Use this to verify Sidecar is running before other operations.
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "sidecar": {
            "process_running": False,
            "proxy_port": SIDECAR_PROXY_PORT,
            "proxy_reachable": False
        },
        "local_ai_service": {
            "port": LOCAL_AI_SERVICE_PORT,
            "reachable": False,
            "models_available": 0
        },
        "configuration": {},
        "recommendations": []
    }
    
    # Check if Sidecar process is running
    result["sidecar"]["process_running"] = is_process_running("MstySidecar")
    
    if not result["sidecar"]["process_running"]:
        result["recommendations"].append(
            "Start Sidecar: open -a MstySidecar (or from Msty Studio menu)"
        )
        return json.dumps(result, indent=2)
    
    # Check Sidecar proxy port
    proxy_response = make_api_request("/", port=SIDECAR_PROXY_PORT, timeout=3)
    result["sidecar"]["proxy_reachable"] = proxy_response.get("success", False) or \
        proxy_response.get("status_code") == 404  # 404 means server is responding
    
    # Check Local AI Service
    models_response = make_api_request("/v1/models", port=LOCAL_AI_SERVICE_PORT, timeout=5)
    if models_response.get("success"):
        result["local_ai_service"]["reachable"] = True
        data = models_response.get("data", {})
        if isinstance(data, dict) and "data" in data:
            result["local_ai_service"]["models_available"] = len(data["data"])
            result["local_ai_service"]["model_list"] = [
                m.get("id", "unknown") for m in data["data"]
            ]
    else:
        result["local_ai_service"]["error"] = models_response.get("error")
    
    # Read Sidecar configuration
    config = get_sidecar_config()
    if "error" not in config:
        # Sanitise config - don't expose tokens
        safe_config = {}
        for key, value in config.items():
            if "token" not in key.lower() and "secret" not in key.lower():
                safe_config[key] = value
        result["configuration"] = safe_config
    
    # Generate recommendations
    if result["local_ai_service"]["reachable"]:
        if result["local_ai_service"]["models_available"] == 0:
            result["recommendations"].append(
                "No models loaded. Download models in Msty Studio > Models"
            )
        else:
            result["recommendations"].append(
                f"✅ Sidecar healthy with {result['local_ai_service']['models_available']} model(s) available"
            )
    else:
        result["recommendations"].append(
            "Local AI Service not responding. Try restarting Sidecar."
        )
    
    return json.dumps(result, indent=2)


@mcp.tool()
def list_available_models() -> str:
    """
    List all AI models available through Sidecar's Local AI Service.
    
    Returns detailed information about each model including:
    - Model ID/name
    - Model type and capabilities
    - Size information (if available)
    
    This queries the Ollama-compatible API on port 11964.
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "source": "Local AI Service API",
        "port": LOCAL_AI_SERVICE_PORT,
        "models": [],
        "model_count": 0
    }
    
    # Check if Sidecar is running
    if not is_process_running("MstySidecar"):
        result["error"] = "Sidecar is not running"
        result["suggestion"] = "Start Sidecar first: open -a MstySidecar"
        return json.dumps(result, indent=2)
    
    # Query models from Local AI Service
    response = make_api_request("/v1/models", port=LOCAL_AI_SERVICE_PORT)
    
    if not response.get("success"):
        result["error"] = response.get("error", "Failed to query models")
        result["suggestion"] = "Ensure Local AI Service is running on port 11964"
        return json.dumps(result, indent=2)
    
    data = response.get("data", {})
    if isinstance(data, dict) and "data" in data:
        models = data["data"]
        result["models"] = models
        result["model_count"] = len(models)
        
        # Add summary
        if models:
            result["summary"] = {
                "model_ids": [m.get("id", "unknown") for m in models],
                "ready_for_inference": True
            }
    else:
        result["models"] = []
        result["note"] = "Unexpected response format"
        result["raw_response"] = data
    
    return json.dumps(result, indent=2)


@mcp.tool()
def query_local_ai_service(
    endpoint: str = "/v1/models",
    method: str = "GET",
    request_body: Optional[str] = None
) -> str:
    """
    Query the Sidecar Local AI Service API directly.
    
    This provides low-level access to the Ollama-compatible API.
    
    Args:
        endpoint: API endpoint (e.g., "/v1/models", "/v1/chat/completions")
        method: HTTP method (GET, POST)
        request_body: JSON string for POST requests
    
    Returns:
        Raw API response with status information
    
    Common endpoints:
        - GET /v1/models - List available models
        - POST /v1/chat/completions - Chat completion (requires model and messages)
    """
    result = {
        "endpoint": endpoint,
        "method": method,
        "port": LOCAL_AI_SERVICE_PORT,
        "timestamp": datetime.now().isoformat()
    }
    
    # Check Sidecar status
    if not is_process_running("MstySidecar"):
        result["error"] = "Sidecar is not running"
        result["suggestion"] = "Start Sidecar: open -a MstySidecar"
        return json.dumps(result, indent=2)
    
    # Parse request body if provided
    data = None
    if request_body:
        try:
            data = json.loads(request_body)
        except json.JSONDecodeError as e:
            result["error"] = f"Invalid JSON in request_body: {e}"
            return json.dumps(result, indent=2)
    
    # Make the API request
    response = make_api_request(
        endpoint=endpoint,
        port=LOCAL_AI_SERVICE_PORT,
        method=method,
        data=data,
        timeout=30  # Longer timeout for inference
    )
    
    result["response"] = response
    
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def chat_with_local_model(
    message: str,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024
) -> str:
    """
    Send a chat message to a local model via Sidecar.
    
    This uses the Ollama-compatible chat completions API.
    
    Args:
        message: The user message to send
        model: Model ID to use (if None, uses first available model)
        system_prompt: Optional system prompt to set context
        temperature: Sampling temperature (0.0-1.0)
        max_tokens: Maximum tokens in response
    
    Returns:
        Model response with timing and token information
    
    Note: This is for quick testing. For production use, prefer
    direct API integration or Msty Studio's chat interface.
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "request": {
            "message": message[:100] + "..." if len(message) > 100 else message,
            "model": model,
            "temperature": temperature
        }
    }
    
    # Check Sidecar status
    if not is_process_running("MstySidecar"):
        result["error"] = "Sidecar is not running"
        result["suggestion"] = "Start Sidecar: open -a MstySidecar"
        return json.dumps(result, indent=2)
    
    # Get available models if none specified
    if not model:
        models_response = make_api_request("/v1/models", port=LOCAL_AI_SERVICE_PORT)
        if models_response.get("success"):
            data = models_response.get("data", {})
            if isinstance(data, dict) and "data" in data and data["data"]:
                model = data["data"][0].get("id")
                result["request"]["model"] = model
                result["note"] = f"Auto-selected model: {model}"
        
        if not model:
            result["error"] = "No models available"
            result["suggestion"] = "Download models in Msty Studio > Models"
            return json.dumps(result, indent=2)
    
    # Build messages
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": message})
    
    # Build request
    request_data = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }
    
    # Make inference request
    import time
    start_time = time.time()
    
    response = make_api_request(
        endpoint="/v1/chat/completions",
        port=LOCAL_AI_SERVICE_PORT,
        method="POST",
        data=request_data,
        timeout=120  # 2 minute timeout for inference
    )
    
    elapsed_time = time.time() - start_time
    result["timing"] = {
        "elapsed_seconds": round(elapsed_time, 2)
    }
    
    if response.get("success"):
        data = response.get("data", {})
        
        # Extract response content
        if "choices" in data and data["choices"]:
            choice = data["choices"][0]
            result["response"] = {
                "content": choice.get("message", {}).get("content", ""),
                "finish_reason": choice.get("finish_reason")
            }
        else:
            result["response"] = {"raw": data}
        
        # Extract usage info
        if "usage" in data:
            result["usage"] = data["usage"]
            result["timing"]["tokens_per_second"] = round(
                data["usage"].get("completion_tokens", 0) / max(elapsed_time, 0.1), 1
            )
    else:
        result["error"] = response.get("error", "Inference failed")
        result["raw_response"] = response
    
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def recommend_model(
    use_case: str = "general",
    max_size_gb: Optional[float] = None
) -> str:
    """
    Get model recommendations based on use case and hardware.
    
    Args:
        use_case: Type of work:
            - "general": General purpose assistant
            - "coding": Code generation and review
            - "writing": Content creation, British English
            - "analysis": Data analysis and reasoning
            - "fast": Quick responses, lower quality acceptable
        max_size_gb: Maximum model size in GB (optional)
    
    Returns:
        Recommended models with installation instructions
    """
    result = {
        "use_case": use_case,
        "max_size_gb": max_size_gb,
        "timestamp": datetime.now().isoformat(),
        "recommendations": [],
        "currently_available": []
    }
    
    # Model recommendations database
    model_db = {
        "general": [
            {"id": "qwen2.5:72b", "size_gb": 41, "quality": "excellent", "speed": "slow"},
            {"id": "qwen2.5:32b", "size_gb": 19, "quality": "very good", "speed": "medium"},
            {"id": "qwen2.5:14b", "size_gb": 9, "quality": "good", "speed": "fast"},
            {"id": "qwen2.5:7b", "size_gb": 4.5, "quality": "acceptable", "speed": "very fast"},
            {"id": "gemma3:4b", "size_gb": 3, "quality": "basic", "speed": "instant"},
        ],
        "coding": [
            {"id": "qwen2.5-coder:32b", "size_gb": 19, "quality": "excellent", "speed": "medium"},
            {"id": "qwen2.5-coder:14b", "size_gb": 9, "quality": "very good", "speed": "fast"},
            {"id": "qwen2.5-coder:7b", "size_gb": 4.5, "quality": "good", "speed": "very fast"},
            {"id": "deepseek-coder:33b", "size_gb": 19, "quality": "very good", "speed": "medium"},
        ],
        "writing": [
            {"id": "qwen2.5:72b", "size_gb": 41, "quality": "excellent", "speed": "slow", "note": "Best for British English"},
            {"id": "llama3.3:70b", "size_gb": 40, "quality": "excellent", "speed": "slow"},
            {"id": "qwen2.5:32b", "size_gb": 19, "quality": "very good", "speed": "medium"},
        ],
        "analysis": [
            {"id": "qwen2.5:72b", "size_gb": 41, "quality": "excellent", "speed": "slow"},
            {"id": "llama3.3:70b", "size_gb": 40, "quality": "excellent", "speed": "slow"},
            {"id": "qwen2.5:32b", "size_gb": 19, "quality": "very good", "speed": "medium"},
        ],
        "fast": [
            {"id": "qwen3:0.6b", "size_gb": 0.5, "quality": "basic", "speed": "instant"},
            {"id": "gemma3:1b", "size_gb": 1, "quality": "basic", "speed": "instant"},
            {"id": "gemma3:4b", "size_gb": 3, "quality": "acceptable", "speed": "very fast"},
            {"id": "qwen2.5:7b", "size_gb": 4.5, "quality": "good", "speed": "fast"},
        ]
    }
    
    # Get recommendations for use case
    if use_case not in model_db:
        result["error"] = f"Unknown use case: {use_case}"
        result["valid_use_cases"] = list(model_db.keys())
        return json.dumps(result, indent=2)
    
    recommendations = model_db[use_case]
    
    # Filter by size if specified
    if max_size_gb:
        recommendations = [m for m in recommendations if m["size_gb"] <= max_size_gb]
    
    result["recommendations"] = recommendations
    
    # Check which models are currently available
    if is_process_running("MstySidecar"):
        models_response = make_api_request("/v1/models", port=LOCAL_AI_SERVICE_PORT)
        if models_response.get("success"):
            data = models_response.get("data", {})
            if isinstance(data, dict) and "data" in data:
                available_ids = [m.get("id", "") for m in data["data"]]
                result["currently_available"] = available_ids
                
                # Mark which recommendations are already installed
                for rec in result["recommendations"]:
                    rec["installed"] = any(
                        rec["id"].split(":")[0] in aid for aid in available_ids
                    )
    
    # Add installation instructions
    result["installation"] = {
        "instructions": [
            "1. Open Msty Studio",
            "2. Go to Models section",
            "3. Search for the model ID",
            "4. Click Download/Install",
            "5. Wait for download to complete"
        ],
        "note": "Models are downloaded from Ollama registry"
    }
    
    # Hardware check
    try:
        memory = psutil.virtual_memory()
        total_ram_gb = memory.total / (1024 ** 3)
        result["hardware"] = {
            "total_ram_gb": round(total_ram_gb, 1),
            "max_recommended_model_gb": round(total_ram_gb * 0.7, 1),
            "note": "Models should use < 70% of total RAM for smooth operation"
        }
    except:
        pass
    
    return json.dumps(result, indent=2)


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Run the Msty Admin MCP server"""
    logger.info("Starting Msty Admin MCP Server v3.0.0")
    logger.info("Phase 1: Foundational Tools (Read-Only)")
    logger.info("Phase 2: Configuration Management")
    logger.info("Phase 3: Automation Bridge")
    mcp.run()


if __name__ == "__main__":
    main()
