"""
HTTP helpers for Msty local inference services and OpenAI-compatible gateways.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from urllib import request
from urllib.error import HTTPError, URLError

from src.paths import DEFAULT_PORTS, detect_msty_installation, is_port_open

MSTY_HOST = os.getenv("MSTY_HOST", "127.0.0.1")


def current_ports() -> Dict[str, int]:
    install = detect_msty_installation()
    ports = dict(DEFAULT_PORTS)
    ports.update(install.service_ports or {})
    # Env overrides win
    ports["local_ai"] = int(os.getenv("MSTY_AI_PORT", ports["local_ai"]))
    ports["mlx"] = int(os.getenv("MSTY_MLX_PORT", ports["mlx"]))
    ports["llamacpp"] = int(os.getenv("MSTY_LLAMACPP_PORT", ports["llamacpp"]))
    ports["vibe"] = int(os.getenv("MSTY_VIBE_PORT", ports["vibe"]))
    ports["nexus"] = int(os.getenv("MSTY_NEXUS_PORT", ports.get("nexus", 11434)))
    return ports


def check_service_available(port: int, host: str = MSTY_HOST) -> bool:
    return is_port_open(host, port)


def make_api_request(
    endpoint: str,
    port: int,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
    host: str = MSTY_HOST,
) -> Dict[str, Any]:
    url = f"http://{host}:{port}{endpoint}"
    try:
        body = None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if data is not None:
            body = json.dumps(data).encode("utf-8")
        req = request.Request(url, data=body, method=method, headers=headers)
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            parsed: Any
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"raw": raw}
            return {"success": True, "data": parsed, "status": getattr(response, "status", 200)}
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        return {"success": False, "error": detail, "status": exc.code}
    except (URLError, TimeoutError, OSError) as exc:
        return {"success": False, "error": str(exc)}


def service_status_map() -> Dict[str, Any]:
    ports = current_ports()
    mapping = {
        "local_ai": ("Local AI (Ollama)", ports["local_ai"]),
        "mlx": ("MLX", ports["mlx"]),
        "llamacpp": ("LLaMA.cpp", ports["llamacpp"]),
        "vibe": ("Vibe CLI Proxy", ports["vibe"]),
        "nexus": ("Msty Nexus", ports["nexus"]),
    }
    result = {}
    for key, (name, port) in mapping.items():
        available = check_service_available(port)
        result[key] = {
            "name": name,
            "port": port,
            "available": available,
        }
    return result


def list_models_from_port(port: int) -> List[str]:
    if not check_service_available(port):
        return []
    response = make_api_request("/v1/models", port=port)
    if not response.get("success"):
        # Ollama-style
        response = make_api_request("/api/tags", port=port)
        if response.get("success"):
            models = response.get("data", {}).get("models", [])
            return [m.get("name") or m.get("model") for m in models if isinstance(m, dict)]
        return []
    data = response.get("data", {})
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [m.get("id") for m in items if isinstance(m, dict) and m.get("id")]
