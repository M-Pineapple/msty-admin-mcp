"""MCP tool annotations, Field descriptions, and write-field caps."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

NAME_MAX = 100
TITLE_MAX = 100
DESCRIPTION_MAX = 500
SYSTEM_PROMPT_MAX = 20000
PROMPT_TEXT_MAX = 20000

_TABLER_ICON = re.compile(r"^tabler:[a-z0-9-]{1,64}$")
DEFAULT_COLOR_ICON = '{"name":"tabler:user-scan"}'


def ann(
    title: str,
    *,
    read_only: bool,
    destructive: bool = False,
    idempotent: Optional[bool] = None,
    open_world: bool = False,
) -> dict:
    """Decorator kwargs: title plus ToolAnnotations."""
    if idempotent is None:
        idempotent = bool(read_only) and not destructive
    return {
        "title": title,
        "annotations": ToolAnnotations(
            title=title,
            readOnlyHint=read_only,
            destructiveHint=destructive,
            idempotentHint=idempotent,
            openWorldHint=open_world,
        ),
    }


def F(description: str, **kwargs: Any) -> Any:
    return Field(description=description, **kwargs)


def sanitise_color_icon(value: Any) -> str:
    """Keep only compact JSON {name: tabler:[a-z0-9-]{1,64}}. Else the default."""
    parsed: Any = value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return DEFAULT_COLOR_ICON
    if isinstance(parsed, dict) and set(parsed.keys()) == {"name"}:
        name = parsed.get("name")
        if isinstance(name, str) and _TABLER_ICON.fullmatch(name):
            return json.dumps({"name": name}, separators=(",", ":"))
    return DEFAULT_COLOR_ICON
