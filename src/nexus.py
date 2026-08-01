"""
Msty Nexus bridge — detect and query the local AI gateway.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.paths import detect_nexus
from src.services import check_service_available, current_ports, make_api_request


def nexus_status() -> Dict[str, Any]:
    info = detect_nexus()
    ports = current_ports()
    port = ports.get("nexus", 11434)
    if not info.get("available") and check_service_available(port):
        info["available"] = True
        info["endpoint"] = f"http://127.0.0.1:{port}"
        info["found"] = True
    info["configured_port"] = port
    return info


def query_nexus_models() -> Dict[str, Any]:
    status = nexus_status()
    if not status.get("available"):
        return {
            "error": "Nexus gateway not reachable",
            "status": status,
            "hint": "Install/start Msty Nexus or set MSTY_NEXUS_PORT to its OpenAI-compatible port.",
        }

    endpoint = status.get("endpoint") or ""
    # endpoint like http://127.0.0.1:11434
    try:
        host_port = endpoint.rsplit("//", 1)[-1]
        host, port_s = host_port.split(":")
        port = int(port_s)
    except Exception:
        port = current_ports().get("nexus", 11434)
        host = "127.0.0.1"

    response = make_api_request("/v1/models", port=port, host=host)
    return {
        "status": status,
        "response": response,
    }


def query_nexus(
    path: str = "/v1/models",
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    status = nexus_status()
    if not status.get("available"):
        return {"error": "Nexus gateway not reachable", "status": status}
    endpoint = status.get("endpoint") or "http://127.0.0.1:11434"
    host_port = endpoint.rsplit("//", 1)[-1]
    host, port_s = host_port.split(":")
    return make_api_request(path, port=int(port_s), method=method, data=data, host=host)
