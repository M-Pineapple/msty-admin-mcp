"""Local AI install and Modelfile settings.

Pull and create go through Msty's Ollama-compatible Local AI service.
``query_local_ai_service`` uses the allow-list here so pull and create are
not an unguarded side door.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Callable, Dict, Optional

from src.services import current_ports, make_api_request

RequestFn = Callable[..., Dict[str, Any]]

PASSTHROUGH_GET = frozenset(
    {
        "/v1/models",
        "/api/tags",
        "/api/version",
        "/api/ps",
        "/api/show",
    }
)
PASSTHROUGH_POST = frozenset(
    {
        "/v1/chat/completions",
        "/api/show",
        "/api/chat",
    }
)

_PULL_HINT = "Use install_model with confirm=true to pull a model."
_CREATE_HINT = "Use set_model_settings with confirm=true to create a tuned variant."
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9._:/-]+$")


def validate_model_name(name: str, field: str = "model") -> Optional[str]:
    """Return an error string, or None if ``name`` is a safe model identifier."""
    cleaned = (name or "").strip()
    if not cleaned:
        return f"{field} is empty"
    if not MODEL_NAME_RE.fullmatch(cleaned):
        return (
            f"{field} must match {MODEL_NAME_RE.pattern} "
            "(letters, digits, '.', '_', ':', '/', '-' only; no whitespace or control characters)"
        )
    return None


def normalise_endpoint(endpoint: str) -> str:
    path = (endpoint or "").strip()
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    path = path.split("?", 1)[0]
    if len(path) > 1:
        path = path.rstrip("/")
    return path or "/"


def passthrough_allowed(endpoint: str, method: str) -> Dict[str, Any]:
    """Return an allow-list decision for the generic Local AI passthrough."""
    path = normalise_endpoint(endpoint)
    verb = (method or "GET").upper()
    allowed = (verb == "GET" and path in PASSTHROUGH_GET) or (
        verb == "POST" and path in PASSTHROUGH_POST
    )
    if allowed:
        return {"allowed": True, "endpoint": path, "method": verb}
    hint = "That Local AI path is not on the allow-list."
    if "pull" in path:
        hint = _PULL_HINT
    elif "create" in path or "copy" in path:
        hint = _CREATE_HINT
    elif verb not in {"GET", "POST"}:
        hint = "Only GET and POST are accepted on the allow-list."
    return {
        "allowed": False,
        "endpoint": path,
        "method": verb,
        "error": hint,
        "allowed_get": sorted(PASSTHROUGH_GET),
        "allowed_post": sorted(PASSTHROUGH_POST),
    }


def _port_for(service: str) -> int:
    ports = current_ports()
    key = (service or "local_ai").strip().lower()
    if key in {"ollama", "local", "local-ai", "local_ai"}:
        key = "local_ai"
    if key not in ports:
        raise ValueError(f"Unknown service '{service}'. Use local_ai, mlx, or llamacpp.")
    return int(ports[key])


def list_installed_models(port: int, request_fn: RequestFn) -> Optional[list]:
    """Return installed model names, or None when Local AI cannot be listed."""
    response = request_fn("/api/tags", port=port, method="GET")
    if response.get("success"):
        models = (response.get("data") or {}).get("models") or []
        names = []
        for item in models:
            if isinstance(item, dict):
                names.append(item.get("name") or item.get("model"))
        return [n for n in names if n]
    response = request_fn("/v1/models", port=port, method="GET")
    if not response.get("success"):
        return None
    data = response.get("data") or {}
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [m.get("id") for m in items if isinstance(m, dict) and m.get("id")]


def _tags(port: int, request_fn: RequestFn) -> list:
    listed = list_installed_models(port, request_fn)
    return listed if listed is not None else []


def _name_present(name: str, installed: list) -> bool:
    needle = name.strip()
    for item in installed:
        text = str(item).strip()
        if not text:
            continue
        if text == needle or text.startswith(needle + ":") or needle.startswith(text + ":"):
            return True
    return False


def pull_model(
    name: str,
    confirm: bool = False,
    service: str = "local_ai",
    timeout: Optional[int] = None,
    request_fn: Optional[RequestFn] = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """POST /api/pull, then poll /api/tags until the model appears."""
    cleaned = (name or "").strip()
    name_error = validate_model_name(cleaned, "model")
    if name_error:
        return {"success": False, "error": name_error, "wrote": False}
    if service.strip().lower() in {"mlx", "llamacpp", "llama.cpp"}:
        return {
            "success": False,
            "wrote": False,
            "error": (
                f"{service} has no pull API in this MCP. "
                "Download that model in Msty, or pull via Local AI (Ollama-compatible)."
            ),
            "service": service,
        }
    if not confirm:
        return {
            "success": True,
            "wrote": False,
            "status": "preview",
            "model": cleaned,
            "service": service,
            "note": "Pass confirm=true to pull this model through Local AI /api/pull.",
        }
    port = _port_for(service)
    request = request_fn or make_api_request
    limit = timeout if timeout is not None else int(os.environ.get("MSTY_PULL_TIMEOUT", "300"))
    started = request(
        "/api/pull",
        port=port,
        method="POST",
        data={"name": cleaned, "stream": False},
        timeout=limit,
    )
    if not started.get("success"):
        return {
            "success": False,
            "wrote": False,
            "model": cleaned,
            "error": started.get("error") or "pull failed",
            "status": started.get("status"),
        }
    deadline = time.time() + max(limit, 5)
    installed = _tags(port, request)
    while not _name_present(cleaned, installed) and time.time() < deadline:
        sleeper(2.0)
        installed = _tags(port, request)
    present = _name_present(cleaned, installed)
    return {
        "success": present,
        "wrote": True,
        "model": cleaned,
        "installed": present,
        "models": installed,
        "pull": started.get("data"),
        "error": None if present else "pull finished but the model is not in /api/tags yet",
    }


def build_modelfile(
    base_model: str,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    num_ctx: Optional[int] = None,
    system: Optional[str] = None,
) -> str:
    name_error = validate_model_name(base_model, "base_model")
    if name_error:
        raise ValueError(name_error)
    lines = [f"FROM {base_model.strip()}"]
    if temperature is not None:
        lines.append(f"PARAMETER temperature {temperature}")
    if top_p is not None:
        lines.append(f"PARAMETER top_p {top_p}")
    if num_ctx is not None:
        lines.append(f"PARAMETER num_ctx {int(num_ctx)}")
    if system and system.strip():
        body = system.strip().replace('"""', "'''")
        lines.append(f'SYSTEM """{body}"""')
    return "\n".join(lines) + "\n"


def create_variant(
    base_model: str,
    variant_name: str,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    num_ctx: Optional[int] = None,
    system: Optional[str] = None,
    confirm: bool = False,
    service: str = "local_ai",
    timeout: Optional[int] = None,
    request_fn: Optional[RequestFn] = None,
) -> Dict[str, Any]:
    """POST /api/create with a Modelfile. Prefer this over writing Studio SQLite."""
    base = (base_model or "").strip()
    variant = (variant_name or "").strip()
    name_error = validate_model_name(base, "base_model") or validate_model_name(
        variant, "variant_name"
    )
    if name_error:
        return {"success": False, "error": name_error, "wrote": False}
    modelfile = build_modelfile(base, temperature, top_p, num_ctx, system)
    if not confirm:
        return {
            "success": True,
            "wrote": False,
            "status": "preview",
            "base_model": base,
            "variant_name": variant,
            "modelfile": modelfile,
            "note": "Pass confirm=true to create this variant through Local AI /api/create.",
        }
    port = _port_for(service)
    request = request_fn or make_api_request
    installed = list_installed_models(port, request)
    if installed is None:
        return {
            "success": False,
            "wrote": False,
            "base_model": base,
            "variant_name": variant,
            "error": (
                "could not list models at /api/tags; refusing create to avoid "
                "overwriting an existing model"
            ),
        }
    if _name_present(variant, installed):
        return {
            "success": False,
            "wrote": False,
            "base_model": base,
            "variant_name": variant,
            "error": (
                f"variant_name {variant!r} already exists in /api/tags. "
                "This tool never overwrites an existing model."
            ),
            "installed": installed,
        }
    limit = timeout if timeout is not None else int(os.environ.get("MSTY_CREATE_TIMEOUT", "120"))
    created = request(
        "/api/create",
        port=port,
        method="POST",
        data={"name": variant, "modelfile": modelfile, "stream": False},
        timeout=limit,
    )
    if not created.get("success"):
        return {
            "success": False,
            "wrote": False,
            "base_model": base,
            "variant_name": variant,
            "modelfile": modelfile,
            "error": created.get("error") or "create failed",
            "status": created.get("status"),
        }
    return {
        "success": True,
        "wrote": True,
        "base_model": base,
        "variant_name": variant,
        "modelfile": modelfile,
        "create": created.get("data"),
    }
