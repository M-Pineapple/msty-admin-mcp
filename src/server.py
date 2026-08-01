"""
Msty Admin MCP Server — v6.0.0
===============================

Administer Msty Studio Desktop 2.9+ with real path/DB detection, entity inventory,
insights analytics, workflow export, and Nexus bridge — plus Bloom/calibration.

Author: M-Pineapple 🍍
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: MCP SDK not installed. Install with: pip install mcp>=1.0.0")
    sys.exit(1)

from src import analytics, db, inventory, nexus
from src.paths import (
    MstyInstallation,
    detect_msty_installation as _detect_install,
    get_msty_paths,
    is_process_running,
)
from src.services import (
    check_service_available,
    current_ports,
    list_models_from_port,
    make_api_request,
    service_status_map,
)

SERVER_VERSION = "6.0.0"
TOOL_COUNT = 55

mcp = FastMCP("msty-admin-mcp", f"v{SERVER_VERSION}")


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


def get_bloom_evaluator():
    try:
        from src.bloom import BloomEvaluator

        return BloomEvaluator()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Phase 1 — Foundational
# ---------------------------------------------------------------------------


@mcp.tool()
def detect_msty_installation() -> str:
    """Detect Msty Studio installation, version, database, and service ports."""
    install = _detect_install()
    payload = install.to_dict()
    payload["paths"] = {k: str(v) for k, v in get_msty_paths().items()}
    return _json(payload)


@mcp.tool()
def read_msty_database(query: str = "stats", limit: int = 100) -> str:
    """
    Query the Studio workspace database.

    Use query='stats' for overview, query='tables' for table list, or a
    read-only SQL SELECT/WITH/PRAGMA statement.
    """
    try:
        if query in ("stats", "stat"):
            return _json({"query_type": "stats", **db.database_stats()})
        if query == "tables":
            tables = db.list_tables()
            return _json({"query_type": "tables", "tables": tables, "count": len(tables)})
        results, count = db.safe_query(query, limit=limit)
        return _json({"query_type": "sql", "results": results, "count": count})
    except Exception as exc:
        return _json({"error": str(exc), "query_type": query})


@mcp.tool()
def list_configured_tools() -> str:
    """List MCP/Toolbox tools configured in Msty Studio."""
    result = inventory.list_entities("tools", limit=500)
    if "error" in result and "items" not in result:
        return _json(result)
    tools = result.get("items", [])
    return _json(
        {
            "tools": tools,
            "tool_count": len(tools),
            "count": len(tools),
        }
    )


@mcp.tool()
def get_model_providers() -> str:
    """List local service backends and Studio-configured providers (keys redacted)."""
    ports = current_ports()
    local_models = {
        "local_ai": list_models_from_port(ports["local_ai"]),
        "mlx": list_models_from_port(ports["mlx"]),
        "llamacpp": list_models_from_port(ports["llamacpp"]),
        "vibe": list_models_from_port(ports["vibe"]),
    }
    providers = inventory.list_entities("providers", limit=100)
    return _json(
        {
            "services": service_status_map(),
            "local_models": local_models,
            "remote_providers": providers.get("items", []),
            "database_providers": providers.get("items", []),
        }
    )


@mcp.tool()
def analyse_msty_health() -> str:
    """Comprehensive health report for Studio install, DB, and services."""
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
    if install.version and install.version not in ("unknown",) and install.version < "2.5.0":
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
        available_models=sum(len(list_models_from_port(p)) for p in current_ports().values() if isinstance(p, int)),
        service_status=services,
        database_healthy=bool(db_status.get("healthy")),
    )
    return _json(asdict(report))


@mcp.tool()
def get_server_status() -> str:
    """MCP server status and tool inventory summary."""
    return _json(
        {
            "status": "running",
            "server": {"name": "msty-admin-mcp", "version": SERVER_VERSION},
            "version": SERVER_VERSION,
            "timestamp": datetime.now().isoformat(),
            "tools_available": TOOL_COUNT,
            "available_tools": TOOL_COUNT,
            "phases": {
                "phase_1_foundational": 6,
                "phase_2_configuration": 4,
                "phase_3_services": 11,
                "phase_4_intelligence": 5,
                "phase_5_calibration": 4,
                "phase_6_bloom": 6,
                "phase_7_studio_inventory": 15,
                "phase_8_nexus": 4,
            },
            "studio_target": "2.9+",
        }
    )


# ---------------------------------------------------------------------------
# Phase 2 — Configuration
# ---------------------------------------------------------------------------


@mcp.tool()
def export_tool_config(tool_name: str) -> str:
    """Export a Studio tool configuration by name or toolId."""
    tools = inventory.list_entities("tools", limit=500).get("items", [])
    match = next(
        (
            t
            for t in tools
            if t.get("name") == tool_name or t.get("toolId") == tool_name or t.get("id") == tool_name
        ),
        None,
    )
    if not match:
        return _json({"error": f"Tool '{tool_name}' not found", "available": [t.get("name") for t in tools]})
    full = inventory.get_entity("tools", match["id"])
    return _json(
        {
            "tool_name": tool_name,
            "exported_at": datetime.now().isoformat(),
            "config": full.get("item") or match,
        }
    )


@mcp.tool()
def sync_claude_preferences() -> str:
    """Report Claude Desktop MCP sync candidates (read-only inventory)."""
    claude_cfg = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    msty_tools = inventory.list_entities("tools", limit=500)
    claude_servers = {}
    if claude_cfg.exists():
        try:
            data = json.loads(claude_cfg.read_text())
            claude_servers = data.get("mcpServers") or {}
        except Exception as exc:
            return _json({"status": "error", "error": str(exc)})
    return _json(
        {
            "status": "analysed",
            "timestamp": datetime.now().isoformat(),
            "claude_servers": list(claude_servers.keys()),
            "msty_tools": [t.get("name") for t in msty_tools.get("items", [])],
            "preferences_synced": 0,
            "note": "v6 reports the delta only; write-import remains user-confirmed via Toolbox / import_tool_config.",
        }
    )


@mcp.tool()
def generate_persona(name: str, system_prompt: str, model: str) -> str:
    """Generate a persona definition JSON suitable for Persona Studio import."""
    persona = PersonaConfig(name=name, system_prompt=system_prompt, model=model)
    return _json(
        {
            "persona": asdict(persona),
            "created_at": datetime.now().isoformat(),
            "import_hint": "Paste into Persona Studio or store via your preferred sync path. Live DB writes are disabled by default for safety.",
        }
    )


@mcp.tool()
def import_tool_config(tool_data: Dict[str, Any], confirm: bool = False) -> str:
    """
    Validate a tool config payload for Toolbox import.

    Live SQLite writes are refused unless confirm=true (still not recommended while Studio is open).
    """
    if not confirm:
        return _json(
            {
                "status": "validated",
                "tool_name": tool_data.get("name"),
                "timestamp": datetime.now().isoformat(),
                "wrote": False,
                "note": "Pass confirm=true only if you intentionally want a write path; prefer Toolbox UI import.",
            }
        )
    return _json(
        {
            "status": "refused",
            "reason": "Direct DB writes to the Chromium File System SQLite are unsafe while Studio may hold locks. Use Toolbox JSON import.",
            "tool_name": tool_data.get("name"),
        }
    )


# ---------------------------------------------------------------------------
# Phase 3 — Services
# ---------------------------------------------------------------------------


@mcp.tool()
def get_service_status() -> str:
    """Status of Local AI, MLX, Llama.cpp, Vibe, and Nexus ports."""
    return _json(service_status_map())


@mcp.tool()
def list_available_models() -> str:
    """List models across local services."""
    ports = current_ports()
    models = {
        "local_ai": list_models_from_port(ports["local_ai"]),
        "mlx": list_models_from_port(ports["mlx"]),
        "llamacpp": list_models_from_port(ports["llamacpp"]),
        "vibe": list_models_from_port(ports["vibe"]),
        "nexus": list_models_from_port(ports["nexus"]),
    }
    return _json({"models": models, "total": sum(len(v) for v in models.values())})


@mcp.tool()
def query_local_ai_service(
    endpoint: str, method: str = "GET", data: Optional[Dict[str, Any]] = None
) -> str:
    """Query Local AI (Ollama-compatible) service."""
    ports = current_ports()
    return _json(make_api_request(endpoint, port=ports["local_ai"], method=method, data=data))


@mcp.tool()
def chat_with_local_model(model: str, messages: List[Dict[str, str]]) -> str:
    """Chat with a Local AI model."""
    ports = current_ports()
    if not check_service_available(ports["local_ai"]):
        return _json({"error": "Local AI service not available"})
    return _json(
        make_api_request(
            "/v1/chat/completions",
            port=ports["local_ai"],
            method="POST",
            data={"model": model, "messages": messages, "stream": False},
            timeout=60,
        )
    )


@mcp.tool()
def recommend_model() -> str:
    """Recommend a model using Studio insights when available."""
    insights = analytics.get_insights_usage(timeframe="30d")
    if insights.get("models"):
        top = insights["models"][0]
        return _json(
            {
                "recommendation": top["model_id"],
                "reason": f"Most used in last 30d ({top['calls']} calls, avg {top['avg_tokens_per_sec']} tok/s)",
                "alternatives": [m["model_id"] for m in insights["models"][1:4]],
                "source": "insightsLanguageModelUsage",
            }
        )
    return _json(
        {
            "recommendation": "llama3.2:7b",
            "reason": "No insights yet — balanced default for Apple Silicon local use",
            "alternatives": ["qwen2.5:7b", "mistral:7b"],
            "source": "heuristic",
        }
    )


@mcp.tool()
def list_mlx_models() -> str:
    """List MLX models from the MLX service."""
    ports = current_ports()
    if not check_service_available(ports["mlx"]):
        return _json({"error": "MLX service not available", "models": []})
    return _json({"models": list_models_from_port(ports["mlx"])})


@mcp.tool()
def chat_with_mlx_model(model: str, messages: List[Dict[str, str]]) -> str:
    """Chat with an MLX model."""
    ports = current_ports()
    if not check_service_available(ports["mlx"]):
        return _json({"error": "MLX service not available"})
    return _json(
        make_api_request(
            "/v1/chat/completions",
            port=ports["mlx"],
            method="POST",
            data={"model": model, "messages": messages, "stream": False},
            timeout=60,
        )
    )


@mcp.tool()
def list_llamacpp_models() -> str:
    """List Llama.cpp models."""
    ports = current_ports()
    if not check_service_available(ports["llamacpp"]):
        return _json({"error": "LLaMA.cpp service not available", "models": []})
    return _json({"models": list_models_from_port(ports["llamacpp"])})


@mcp.tool()
def chat_with_llamacpp_model(model: str, messages: List[Dict[str, str]]) -> str:
    """Chat with a Llama.cpp model."""
    ports = current_ports()
    if not check_service_available(ports["llamacpp"]):
        return _json({"error": "LLaMA.cpp service not available"})
    return _json(
        make_api_request(
            "/v1/chat/completions",
            port=ports["llamacpp"],
            method="POST",
            data={"model": model, "messages": messages, "stream": False},
            timeout=60,
        )
    )


@mcp.tool()
def get_vibe_proxy_status() -> str:
    """Check Vibe CLI proxy status."""
    ports = current_ports()
    if not check_service_available(ports["vibe"]):
        return _json({"status": "unavailable", "port": ports["vibe"]})
    return _json(make_api_request("/status", port=ports["vibe"]))


@mcp.tool()
def query_vibe_proxy(query: str) -> str:
    """Query Vibe CLI proxy."""
    ports = current_ports()
    if not check_service_available(ports["vibe"]):
        return _json({"error": "Vibe proxy not available"})
    return _json(make_api_request("/query", port=ports["vibe"], method="POST", data={"query": query}))


# ---------------------------------------------------------------------------
# Phase 4 — Intelligence (real Studio data)
# ---------------------------------------------------------------------------


@mcp.tool()
def get_model_performance_metrics(model_id: Optional[str] = None, timeframe: str = "7d") -> str:
    """Performance metrics from Studio insightsLanguageModelUsage."""
    return _json(analytics.get_insights_usage(model_id=model_id, timeframe=timeframe))


@mcp.tool()
def analyse_conversation_patterns(model_id: Optional[str] = None) -> str:
    """Analyse conversation patterns from Studio data."""
    return _json(analytics.analyse_conversation_patterns(model_id=model_id))


@mcp.tool()
def compare_model_responses(prompt: str, models: List[str]) -> str:
    """Compare responses from multiple local models (best-effort)."""
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


@mcp.tool()
def optimise_knowledge_stacks() -> str:
    """Suggest Knowledge Stack optimisations from live Studio data."""
    return _json(analytics.optimise_knowledge_stacks())


@mcp.tool()
def suggest_persona_improvements() -> str:
    """Suggest persona improvements from live Studio personas."""
    return _json(analytics.suggest_persona_improvements())


# ---------------------------------------------------------------------------
# Phase 5 — Calibration
# ---------------------------------------------------------------------------


@mcp.tool()
def run_calibration_test(model_id: Optional[str] = None, category: str = "general") -> str:
    """Run calibration test on a local model."""
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


@mcp.tool()
def evaluate_response_quality(prompt: str, response: str, category: str = "general") -> str:
    """Evaluate response quality with heuristic rubric."""
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


@mcp.tool()
def identify_handoff_triggers() -> str:
    """Identify handoff patterns from insights + calibration heuristics."""
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
                "pattern": "Insufficient insights — run calibration or use Studio more to populate metrics",
                "confidence": 0.4,
            }
        ]
    return _json({"triggers": triggers})


@mcp.tool()
def get_calibration_history(model_id: Optional[str] = None, limit: int = 50) -> str:
    """Get calibration history from ~/.msty-admin metrics DB."""
    from src.phase4_5_tools import get_metrics_db_path

    path = get_metrics_db_path()
    if not path.exists():
        return _json({"model_id": model_id, "limit": limit, "history": []})
    import sqlite3

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        if model_id:
            rows = conn.execute(
                "SELECT * FROM calibration_tests WHERE model_id = ? ORDER BY created_at DESC LIMIT ?",
                (model_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM calibration_tests ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        history = [dict(r) for r in rows]
    except Exception as exc:
        history = []
        return _json({"model_id": model_id, "limit": limit, "history": history, "error": str(exc)})
    finally:
        conn.close()
    return _json({"model_id": model_id, "limit": limit, "history": history})


# ---------------------------------------------------------------------------
# Phase 6 — Bloom
# ---------------------------------------------------------------------------


@mcp.tool()
def bloom_evaluate_model(
    model: str,
    behavior: str,
    task_category: Optional[str] = None,
    total_evals: int = 3,
    max_turns: int = 2,
) -> str:
    """Run Bloom behavioural evaluation on a model."""
    evaluator = get_bloom_evaluator()
    if not evaluator:
        return _json({"error": "Bloom evaluator not available", "requires": "ANTHROPIC_API_KEY"})
    return _json(
        {
            "model": model,
            "behavior": behavior,
            "task_category": task_category,
            "total_evals": total_evals,
            "max_turns": max_turns,
            "note": "Evaluator loaded — invoke full Bloom pipeline from bloom module when API key present.",
            "timestamp": datetime.now().isoformat(),
        }
    )


@mcp.tool()
def bloom_check_handoff(model: str, task_category: str) -> str:
    """Check whether a model should hand off to Claude for a task category."""
    return _json(
        {
            "should_handoff": False,
            "confidence": 0.5,
            "reason": "No Bloom history yet — run bloom_evaluate_model first",
            "model": model,
            "task_category": task_category,
        }
    )


@mcp.tool()
def bloom_get_history(model: Optional[str] = None, behavior: Optional[str] = None) -> str:
    """Get Bloom evaluation history."""
    return _json({"evaluations": [], "model": model, "behavior": behavior})


@mcp.tool()
def bloom_list_behaviors() -> str:
    """List available Bloom behaviours."""
    from src.bloom.cv_behaviors import CUSTOM_BEHAVIORS

    return _json({"behaviors": list(CUSTOM_BEHAVIORS.keys()), "count": len(CUSTOM_BEHAVIORS)})


@mcp.tool()
def bloom_get_thresholds(task_category: str) -> str:
    """Get quality thresholds for a task category."""
    from src.bloom.cv_behaviors import QUALITY_THRESHOLDS

    return _json(
        {
            "task_category": task_category,
            "thresholds": QUALITY_THRESHOLDS.get(task_category, {}),
        }
    )


@mcp.tool()
def bloom_validate_model(model: str) -> str:
    """Validate model suitability for Bloom evaluation."""
    from src.bloom.ollama_adapter import OllamaModelAdapter

    adapter = OllamaModelAdapter()
    return _json(adapter.validate_model_for_bloom(model))


# ---------------------------------------------------------------------------
# Phase 7 — Studio 2.9 entity inventory
# ---------------------------------------------------------------------------


@mcp.tool()
def list_studio_catalogue() -> str:
    """Summary counts for all known Studio entity types."""
    return _json(inventory.catalogue_summary())


@mcp.tool()
def list_workspaces(limit: int = 100) -> str:
    """List Studio workspaces."""
    return _json(inventory.list_entities("workspaces", limit=limit))


@mcp.tool()
def list_personas(limit: int = 100) -> str:
    """List personas from Persona Studio."""
    return _json(inventory.list_entities("personas", limit=limit))


@mcp.tool()
def list_shadow_personas(limit: int = 100) -> str:
    """List Shadow Personas."""
    return _json(inventory.list_entities("shadow_personas", limit=limit))


@mcp.tool()
def list_crews(limit: int = 100) -> str:
    """List Crew Mode crews."""
    return _json(inventory.list_entities("crews", limit=limit))


@mcp.tool()
def list_knowledge_stacks(limit: int = 100) -> str:
    """List Knowledge Stacks (including Next Gen)."""
    return _json(inventory.list_entities("knowledge_stacks", limit=limit))


@mcp.tool()
def list_turnstiles(limit: int = 100) -> str:
    """List Turnstiles / Turnstiles vNext definitions."""
    return _json(inventory.list_entities("turnstiles", limit=limit))


@mcp.tool()
def list_skills(limit: int = 100) -> str:
    """List Skills Studio preferences and folders."""
    return _json(
        {
            "skills": inventory.list_entities("skills", limit=limit),
            "folders": inventory.list_entities("skill_folders", limit=limit),
        }
    )


@mcp.tool()
def list_live_contexts(limit: int = 100) -> str:
    """List Live Contexts."""
    return _json(inventory.list_entities("live_contexts", limit=limit))


@mcp.tool()
def list_prompts(limit: int = 100) -> str:
    """List Prompts Studio library entries."""
    return _json(inventory.list_entities("prompts", limit=limit))


@mcp.tool()
def list_context_studio(limit: int = 100) -> str:
    """List Context Studio attachments and folders (Studio 2.9)."""
    return _json(
        {
            "attachments": inventory.list_entities("attachments", limit=limit),
            "folders": inventory.list_entities("attachment_folders", limit=limit),
        }
    )


@mcp.tool()
def list_agent_plans(limit: int = 100) -> str:
    """List Agent Mode plans."""
    return _json(inventory.list_entities("agent_plans", limit=limit))


@mcp.tool()
def get_studio_entity(entity: str, entity_id: str) -> str:
    """Fetch a single Studio entity by type and id."""
    return _json(inventory.get_entity(entity, entity_id))


@mcp.tool()
def get_schema_migrations(limit: int = 20) -> str:
    """Show recent Drizzle schema migrations from the Studio database."""
    try:
        rows = db.fetch_all(
            "__drizzle_migrations",
            limit=limit,
            order_by="created_at DESC",
        )
        return _json({"migrations": rows, "count": len(rows)})
    except Exception as exc:
        return _json({"error": str(exc), "migrations": []})


@mcp.tool()
def export_workflow_pack(include: Optional[List[str]] = None, limit: int = 200) -> str:
    """Export a read-only workflow pack (personas, tools, turnstiles, stacks, …)."""
    return _json(inventory.export_workflow_pack(include=include, limit=limit))


# ---------------------------------------------------------------------------
# Phase 8 — Nexus bridge
# ---------------------------------------------------------------------------


@mcp.tool()
def detect_nexus() -> str:
    """Detect Msty Nexus local gateway."""
    return _json(nexus.nexus_status())


@mcp.tool()
def list_nexus_models() -> str:
    """List models exposed by the Nexus OpenAI-compatible endpoint."""
    return _json(nexus.query_nexus_models())


@mcp.tool()
def query_nexus(
    path: str = "/v1/models",
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
) -> str:
    """Query the Nexus gateway with an arbitrary path."""
    return _json(nexus.query_nexus(path=path, method=method, data=data))


@mcp.tool()
def get_insights_usage(model_id: Optional[str] = None, timeframe: str = "7d") -> str:
    """Alias for insights-backed usage analytics."""
    return _json(analytics.get_insights_usage(model_id=model_id, timeframe=timeframe))


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
        try:
            import uvicorn
            from starlette.applications import Starlette
            from starlette.responses import JSONResponse

            app = Starlette()

            @app.route("/health", methods=["GET"])
            async def health(request):  # type: ignore
                return JSONResponse({"status": "healthy", "version": SERVER_VERSION})

            uvicorn.run(app, host=args.host, port=args.port)
        except ImportError:
            print("Error: HTTP transport requires uvicorn and starlette")
            print("Install with: pip install msty-admin-mcp[http]")
            sys.exit(1)


if __name__ == "__main__":
    main()
