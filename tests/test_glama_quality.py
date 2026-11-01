"""Glama quality: annotations, descriptions, parameter text, allow-lists."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from src.install import pull_model, validate_pull_source
from src.server import TOOL_COUNT, mcp
from src.tooling import DEFAULT_COLOR_ICON, sanitise_color_icon
from src.writes import WriteRejected, check_persona_item, check_prompt_item

ROOT = Path(__file__).resolve().parent.parent
_SENTENCE_SPLIT = re.compile(r"[.!?]+")
_REQUIRED_HINTS = (
    "readOnlyHint",
    "destructiveHint",
    "idempotentHint",
    "openWorldHint",
    "title",
)


def _tools():
    return asyncio.run(mcp.list_tools())


def test_every_tool_has_annotations_and_title():
    tools = _tools()
    assert len(tools) == TOOL_COUNT
    missing = []
    for tool in tools:
        annotations = tool.annotations
        if annotations is None:
            missing.append((tool.name, "annotations"))
            continue
        for field in _REQUIRED_HINTS:
            if getattr(annotations, field, None) is None:
                missing.append((tool.name, field))
        if not (tool.title or getattr(annotations, "title", None)):
            missing.append((tool.name, "title"))
    assert missing == []


def test_every_description_has_at_least_two_sentences():
    short = []
    for tool in _tools():
        description = (tool.description or "").strip()
        sentences = [part for part in _SENTENCE_SPLIT.split(description) if part.strip()]
        if len(sentences) < 2:
            short.append((tool.name, len(sentences), description[:120]))
    assert short == []


def test_every_parameter_has_a_description():
    missing = []
    for tool in _tools():
        properties = (tool.inputSchema or {}).get("properties") or {}
        for name, schema in properties.items():
            if not (schema.get("description") or "").strip():
                missing.append((tool.name, name))
    assert missing == []


def test_open_world_on_network_tools():
    by_name = {tool.name: tool for tool in _tools()}
    for name in ("ask_frontier", "chat_with_model", "install_model", "query_nexus"):
        assert by_name[name].annotations.openWorldHint is True
    assert by_name["get_status"].annotations.readOnlyHint is True
    assert by_name["get_status"].annotations.openWorldHint is False


def test_color_icon_allow_list():
    assert sanitise_color_icon('{"name":"tabler:user-scan"}') == '{"name":"tabler:user-scan"}'
    assert sanitise_color_icon({"name": "tabler:robot"}) == '{"name":"tabler:robot"}'
    assert sanitise_color_icon('{"name":"mdi:home"}') == DEFAULT_COLOR_ICON
    assert sanitise_color_icon('{"name":"tabler:User"}') == DEFAULT_COLOR_ICON
    assert sanitise_color_icon('{"name":"tabler:robot","extra":1}') == DEFAULT_COLOR_ICON
    assert sanitise_color_icon("not-json") == DEFAULT_COLOR_ICON
    assert sanitise_color_icon("") == DEFAULT_COLOR_ICON


def test_length_caps_refuse_with_clear_error():
    try:
        check_persona_item({"name": "n" * 101, "systemPrompt": "hi"})
    except WriteRejected as exc:
        assert "persona name" in str(exc)
        assert "100" in str(exc)
    else:
        raise AssertionError("expected WriteRejected")
    try:
        check_persona_item({"name": "ok", "description": "d" * 501, "systemPrompt": "hi"})
    except WriteRejected as exc:
        assert "persona description" in str(exc)
    else:
        raise AssertionError("expected WriteRejected")
    try:
        check_persona_item({"name": "ok", "systemPrompt": "s" * 20001})
    except WriteRejected as exc:
        assert "system prompt" in str(exc)
    else:
        raise AssertionError("expected WriteRejected")
    try:
        check_prompt_item({"title": "t" * 101, "text": "hi"})
    except WriteRejected as exc:
        assert "prompt title" in str(exc)
    else:
        raise AssertionError("expected WriteRejected")
    try:
        check_prompt_item({"title": "ok", "text": "p" * 20001})
    except WriteRejected as exc:
        assert "prompt text" in str(exc)
    else:
        raise AssertionError("expected WriteRejected")


def test_pull_host_allow_list():
    assert validate_pull_source("llama3.2:3b") is None
    assert validate_pull_source("library/llama3.2:3b") is None
    assert validate_pull_source("hf.co/org/model") is None
    assert validate_pull_source("registry.ollama.ai/library/llama3.2:3b") is None
    refused = validate_pull_source("evil.example/model")
    assert refused and "Refused host" in refused
    refused_scheme = validate_pull_source("https://evil.example/model")
    assert refused_scheme and "Refused host" in refused_scheme
    result = pull_model("http://not-ollama.example/stolen", confirm=False)
    assert result["success"] is False
    assert result["wrote"] is False
    assert "Refused host" in result["error"]


def test_readme_version_and_tool_count():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "v6.2.1" in readme
    assert "54 in total" in readme
    assert "## v6.2.1 - 2026-11-02" in changelog
    assert "`get_server_status`" in changelog
    assert "`get_status(scope=server)`" in changelog
