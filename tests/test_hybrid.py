"""Hybrid tools: hardware, install, writes, frontier providers, Bloom. Fixtures only."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.hardware import _binary, catalog, detect_hardware
from src.hardware.catalog import memory_budget_gb, recommend
STUDIO_29_SCHEMA = """
CREATE TABLE personaFolders (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    colorIcon TEXT,
    isExpanded INTEGER DEFAULT 1 NOT NULL,
    sortOrder INTEGER DEFAULT -1 NOT NULL,
    extras TEXT,
    createdAt TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE TABLE personas (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL UNIQUE,
    colorIcon TEXT,
    description TEXT,
    folderId TEXT NOT NULL,
    systemPrompt TEXT NOT NULL,
    partialRTDInfo TEXT,
    partialSelectableAttachments TEXT,
    partialToolsetsInfo TEXT,
    partialLiveContextsInfo TEXT,
    contextShieldInfo TEXT,
    partialModelInfo TEXT,
    fewShotPrompts TEXT,
    extras TEXT,
    createdAt TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
    partialKnowledgeStacksInfo TEXT,
    activeVersionId TEXT,
    FOREIGN KEY (folderId) REFERENCES personaFolders(id) ON DELETE CASCADE
);
CREATE TABLE personaVersions (
    id TEXT PRIMARY KEY NOT NULL,
    personaId TEXT NOT NULL,
    versionNumber INTEGER NOT NULL,
    name TEXT NOT NULL,
    colorIcon TEXT,
    description TEXT,
    systemPrompt TEXT NOT NULL,
    partialRTDInfo TEXT,
    partialSelectableAttachments TEXT,
    partialToolsetsInfo TEXT,
    partialKnowledgeStacksInfo TEXT,
    partialLiveContextsInfo TEXT,
    contextShieldInfo TEXT,
    partialModelInfo TEXT,
    fewShotPrompts TEXT,
    tags TEXT,
    extras TEXT,
    changelog TEXT,
    createdAt TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
    FOREIGN KEY (personaId) REFERENCES personas(id) ON DELETE CASCADE
);
CREATE TABLE promptsLibraryFolders (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    colorIcon TEXT,
    isExpanded INTEGER DEFAULT 1 NOT NULL,
    sortOrder INTEGER DEFAULT -1 NOT NULL,
    folderParentId TEXT,
    extras TEXT,
    createdAt TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE TABLE promptsLibraryPrompts (
    id TEXT PRIMARY KEY NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    folderId TEXT NOT NULL,
    source TEXT DEFAULT 'ootb' NOT NULL,
    isBookmarked INTEGER DEFAULT 0 NOT NULL,
    extras TEXT,
    createdAt TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
    lastUsedAt TEXT,
    activeVersionId TEXT,
    FOREIGN KEY (folderId) REFERENCES promptsLibraryFolders(id) ON DELETE CASCADE
);
CREATE TABLE promptsVersions (
    id TEXT PRIMARY KEY NOT NULL,
    promptId TEXT NOT NULL,
    versionNumber INTEGER NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    variables TEXT,
    changelog TEXT,
    createdAt TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
    extras TEXT,
    FOREIGN KEY (promptId) REFERENCES promptsLibraryPrompts(id) ON DELETE CASCADE
);
CREATE TABLE languageModelsProviders (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    providerId TEXT NOT NULL,
    credentials TEXT,
    models TEXT,
    extras TEXT,
    createdAt TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
    logo TEXT
);
CREATE TABLE languageModelConfigs (
    id TEXT PRIMARY KEY NOT NULL,
    providerId TEXT NOT NULL,
    modelId TEXT NOT NULL,
    value TEXT,
    extras TEXT,
    logo TEXT,
    FOREIGN KEY (providerId) REFERENCES languageModelsProviders(id) ON DELETE CASCADE
);
CREATE TABLE tools (
    id TEXT PRIMARY KEY NOT NULL,
    toolId TEXT NOT NULL,
    name TEXT NOT NULL,
    config TEXT NOT NULL,
    notes TEXT,
    provider TEXT DEFAULT 'mcp',
    compatibility TEXT,
    colorIcon TEXT,
    extras TEXT,
    createdAt TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
    folderId TEXT
);
CREATE TABLE skill_preferences (
    id TEXT PRIMARY KEY NOT NULL,
    skillId TEXT NOT NULL,
    isEnabled TEXT DEFAULT 'true' NOT NULL,
    folderId TEXT NOT NULL,
    extras TEXT,
    createdAt TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE TABLE toolsets (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    priority REAL NOT NULL DEFAULT 0,
    notes TEXT,
    extras TEXT,
    createdAt TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
    folderId TEXT
);
CREATE VIRTUAL TABLE search USING fts5(extras, entity, content, entityId);
CREATE TRIGGER after_insert_promptsLibrary
    AFTER INSERT ON promptsLibraryPrompts
    FOR EACH ROW
BEGIN
    INSERT INTO search (entity, entityId, content, extras)
    VALUES (
        'promptsLibraryPrompts',
        NEW.id,
        NEW.title || ' ' || NEW.text,
        json_object('title', NEW.title)
    );
END;
INSERT INTO personaFolders (id, name) VALUES (
    '__MSTY__PERSONA__ORPHANAGE__FOLDER__',
    'Misc'
);
"""


from src.install import (
    build_modelfile,
    create_payload,
    create_variant,
    looks_like_local_path,
    leftover_scheme,
    normalise_model_name,
    passthrough_allowed,
    pull_model,
    pull_payload,
    validate_model_name,
)
from src.paths import is_process_running
from src import writes
from src.frontier import ask_claude, ask_frontier, ask_grok, resolve_provider
from src.bloom.evaluator import (
    EvaluationResult,
    bloom_child_env,
    handoff_from_history,
    load_persisted_history,
    persist_evaluation,
)
from src.server import (
    TOOL_COUNT,
    bloom_check_handoff,
    bloom_evaluate_model,
    bloom_get_history,
    generate_persona,
    get_hardware_profile,
    import_studio_pack,
    import_tool_config,
    install_model,
    query_local_ai_service,
    recommend_model,
    set_model_settings,
)
from src.escalation import HOOK_API_NOTE, ESCALATION_PERSONA


@pytest.fixture()
def admin_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "admin"
    home.mkdir()
    monkeypatch.setenv("MSTY_ADMIN_HOME", str(home))
    monkeypatch.setenv("MSTY_BLOOM_HISTORY", str(home / "bloom-history.json"))
    return home


@pytest.fixture()
def studio_fixture(tmp_path: Path) -> Path:
    db_path = tmp_path / "00000000"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(STUDIO_29_SCHEMA)
    conn.commit()
    conn.close()
    return db_path


APPLE_36 = {
    "platform": "Darwin",
    "arch": "arm64",
    "chip": "Apple M4 Max",
    "apple_silicon": True,
    "apple_generation": "M4 Max",
    "cpu_cores_physical": 14,
    "cpu_cores_logical": 14,
    "ram_gb": 36.0,
    "unified_memory": True,
    "gpu": "Apple M4 Max",
    "vram_gb": None,
    "memory_kind": "unified",
}

APPLE_8 = dict(APPLE_36, ram_gb=8.0, chip="Apple M1")


class TestHardware:
    def test_detect_returns_ram_and_chip(self):
        profile = detect_hardware()
        assert profile["ram_gb"] and profile["ram_gb"] > 0
        assert profile["chip"]
        assert "cpu_cores_logical" in profile

    def test_macos_sysctl_and_profiler(self, monkeypatch):
        def fake_run(argv, timeout=8.0):
            name = Path(argv[0]).name
            rest = " ".join(argv[1:])
            cmd = f"{name} {rest}".strip() if rest else name
            mapping = {
                "sysctl -n hw.memsize": str(36 * 1024 ** 3),
                "sysctl -n hw.physicalcpu": "14",
                "sysctl -n hw.logicalcpu": "14",
                "sysctl -n machdep.cpu.brand_string": "Apple M4 Max",
                "sysctl -n hw.model": "Mac16,5",
            }
            if cmd in mapping:
                return mapping[cmd]
            if "SPHardwareDataType" in cmd:
                return json.dumps(
                    {"SPHardwareDataType": [{"chip_type": "Apple M4 Max", "machine_name": "Mac16,5"}]}
                )
            if "SPDisplaysDataType" in cmd:
                return json.dumps({"SPDisplaysDataType": [{"sppci_model": "Apple M4 Max"}]})
            return ""

        monkeypatch.setattr("src.hardware._run", fake_run)
        monkeypatch.setattr("src.hardware.platform.system", lambda: "Darwin")
        monkeypatch.setattr("src.hardware.platform.machine", lambda: "arm64")
        profile = detect_hardware()
        assert profile["apple_silicon"] is True
        assert profile["apple_generation"] == "M4 Max"
        assert profile["unified_memory"] is True
        assert profile["ram_gb"] == 36.0
        assert profile["cpu_cores_physical"] == 14

    def test_binary_prefers_known_absolute_path(self, monkeypatch):
        monkeypatch.setattr(
            "src.hardware.os.path.isfile", lambda path: path == "/usr/sbin/sysctl"
        )
        monkeypatch.setattr("src.hardware.os.access", lambda path, mode: True)
        monkeypatch.setattr(
            "src.hardware.shutil.which", lambda name: "/opt/homebrew/bin/sysctl"
        )
        assert _binary("sysctl") == "/usr/sbin/sysctl"

    def test_budget_unified_and_discrete(self):
        assert memory_budget_gb({"ram_gb": 36, "unified_memory": True}) == 21.6
        assert memory_budget_gb({"ram_gb": 32, "vram_gb": 16, "unified_memory": False}) == 13.6

    def test_recommend_skips_70b_on_36gb(self):
        result = recommend(APPLE_36, use_case="research")
        assert result["recommendation"] != "llama3.1:70b"
        assert result["q4_gb"] <= result["budget_gb"]
        assert "21.6" in result["reason"] or "budget" in result["reason"]

    def test_recommend_small_machine(self):
        result = recommend(APPLE_8, use_case="general")
        assert result["q4_gb"] <= result["budget_gb"]
        assert result["recommendation"] in {"llama3.2:1b", "llama3.2:3b", "phi3:mini", "qwen2.5-coder:3b"}

    def test_recommend_prefers_used_model_that_fits(self):
        insights = [{"model_id": "qwen2.5:7b", "calls": 40, "avg_tokens_per_sec": 30}]
        result = recommend(APPLE_36, use_case="coding", insights_models=insights)
        assert result["recommendation"] == "qwen2.5:7b"
        assert result["source"] == "insights+hardware"

    def test_mcp_hardware_and_recommend(self, monkeypatch):
        monkeypatch.setattr("src.server._hardware_profile", lambda: APPLE_36)
        monkeypatch.setattr(
            "src.analytics.get_insights_usage",
            lambda timeframe="30d": {"models": [{"model_id": "llama3.1:70b", "calls": 9}]},
        )
        profile = json.loads(get_hardware_profile())
        rec = json.loads(recommend_model("research"))
        assert profile["ram_gb"] == 36.0
        assert rec["recommendation"] != "llama3.1:70b"
        assert "hardware" in rec


class TestInstallAndAllowList:
    def test_pull_and_create_denied_on_passthrough(self):
        denied = passthrough_allowed("/api/pull", "POST")
        assert denied["allowed"] is False
        assert "install_model" in denied["error"]
        create = passthrough_allowed("/api/create", "POST")
        assert create["allowed"] is False
        tags = passthrough_allowed("/api/tags", "GET")
        assert tags["allowed"] is True

    def test_query_local_ai_service_blocks_pull(self):
        payload = json.loads(query_local_ai_service("/api/pull", "POST", {"name": "x"}))
        assert payload["success"] is False
        assert "install_model" in payload["error"]

    def test_pull_preview_and_confirm(self):
        calls = []

        def fake_request(endpoint, port=None, method="GET", data=None, timeout=10):
            calls.append(endpoint)
            if endpoint == "/api/pull":
                return {"success": True, "data": {"status": "success"}}
            if endpoint == "/api/tags":
                return {"success": True, "data": {"models": [{"name": "llama3.2:3b"}]}}
            return {"success": False, "error": "no"}

        preview = pull_model("llama3.2:3b", confirm=False, request_fn=fake_request)
        assert preview["wrote"] is False
        assert "/api/pull" not in calls
        applied = pull_model(
            "llama3.2:3b", confirm=True, request_fn=fake_request, sleeper=lambda _s: None
        )
        assert applied["wrote"] is True
        assert applied["installed"] is True
        assert "/api/pull" in calls

    def test_pull_sends_model_field_not_name(self):
        captured = {}

        def fake_request(endpoint, port=None, method="GET", data=None, timeout=10):
            if endpoint == "/api/pull":
                captured["data"] = data
                if "modelfile" in (data or {}) or (
                    "name" in (data or {}) and "model" not in (data or {})
                ):
                    return {
                        "success": False,
                        "status": 400,
                        "error": '{"error":"missing model"}',
                    }
                return {"success": True, "data": {"status": "success"}}
            if endpoint == "/api/tags":
                return {"success": True, "data": {"models": [{"name": "llama3.2:3b"}]}}
            return {"success": False, "error": "no"}

        result = pull_model(
            "llama3.2:3b", confirm=True, request_fn=fake_request, sleeper=lambda _s: None
        )
        assert result["wrote"] is True
        assert captured["data"] == {"model": "llama3.2:3b", "stream": False}
        assert pull_payload("llama3.2:3b") == captured["data"]
        assert "name" not in captured["data"]

    def test_mlx_has_no_pull(self):
        result = pull_model("qwen", confirm=True, service="mlx")
        assert result["success"] is False
        assert "no pull API" in result["error"]

    def test_create_variant_preview_contains_modelfile(self):
        result = create_variant(
            "llama3.2:3b",
            "llama-tuned",
            temperature=0.2,
            num_ctx=8192,
            system="Be brief.",
            confirm=False,
        )
        assert result["wrote"] is False
        assert "PARAMETER temperature 0.2" in result["modelfile"]
        assert "FROM llama3.2:3b" in result["modelfile"]

    def test_create_variant_sends_structured_body_not_modelfile(self):
        captured = {}

        def fake_request(endpoint, port=None, method="GET", data=None, timeout=10):
            if endpoint == "/api/tags":
                return {"success": True, "data": {"models": [{"name": "llama3.2:3b"}]}}
            if endpoint == "/api/create":
                captured["data"] = data
                if "modelfile" in (data or {}) or "name" in (data or {}):
                    return {
                        "success": False,
                        "status": 400,
                        "error": '{"error":"neither \'from\' or \'files\' was specified"}',
                    }
                if data and data.get("model") and data.get("from"):
                    return {"success": True, "data": {"status": "success"}}
                return {
                    "success": False,
                    "status": 400,
                    "error": '{"error":"neither \'from\' or \'files\' was specified"}',
                }
            return {"success": False}

        result = create_variant(
            "llama3.2:3b",
            "llama-tuned",
            temperature=0.2,
            top_p=0.9,
            num_ctx=8192,
            system="Be brief.",
            confirm=True,
            request_fn=fake_request,
        )
        expected = {
            "model": "llama-tuned",
            "from": "llama3.2:3b",
            "parameters": {"temperature": 0.2, "top_p": 0.9, "num_ctx": 8192},
            "system": "Be brief.",
            "stream": False,
        }
        assert result["wrote"] is True
        assert captured["data"] == expected
        assert create_payload(
            "llama3.2:3b",
            "llama-tuned",
            temperature=0.2,
            top_p=0.9,
            num_ctx=8192,
            system="Be brief.",
        ) == expected
        assert "modelfile" not in captured["data"]
        assert "name" not in captured["data"]
        assert "FROM llama3.2:3b" in result["modelfile"]

    def test_create_payload_omits_unset_parameters_and_system(self):
        assert create_payload("llama3.2:3b", "llama-tuned") == {
            "model": "llama-tuned",
            "from": "llama3.2:3b",
            "stream": False,
        }

    def test_create_variant_rejects_newline_in_base(self):
        result = create_variant(
            "llama3\nADAPTER /tmp/x.gguf\n",
            "ok-name",
            confirm=False,
        )
        assert result["wrote"] is False
        assert result["success"] is False
        assert "base_model" in result["error"]
        assert "ADAPTER" not in result.get("modelfile", "")

    def test_build_modelfile_rejects_injection(self):
        with pytest.raises(ValueError, match="base_model"):
            build_modelfile("llama3\nADAPTER /tmp/x.gguf")

    def test_create_variant_refuses_existing_name(self):
        calls = []

        def fake_request(endpoint, port=None, method="GET", data=None, timeout=10):
            calls.append(endpoint)
            if endpoint == "/api/tags":
                return {"success": True, "data": {"models": [{"name": "llama-tuned"}]}}
            if endpoint == "/api/create":
                return {"success": True, "data": {"status": "success"}}
            return {"success": False}

        result = create_variant(
            "llama3.2:3b", "llama-tuned", confirm=True, request_fn=fake_request
        )
        assert result["wrote"] is False
        assert "already exists" in result["error"]
        assert "/api/create" not in calls

    def test_normalise_strips_registry_and_library_and_adds_latest(self):
        assert normalise_model_name("registry.ollama.ai/library/llama-tuned") == "llama-tuned:latest"
        assert normalise_model_name("library/llama-tuned") == "llama-tuned:latest"
        assert normalise_model_name("llama-tuned") == "llama-tuned:latest"
        assert normalise_model_name("llama3.2:3b") == "llama3.2:3b"

    def test_normalise_lowercases_and_strips_scheme_and_registry_port(self):
        assert normalise_model_name("LLAMA3") == "llama3:latest"
        assert normalise_model_name("llama3:LATEST") == "llama3:latest"
        assert normalise_model_name("registry.ollama.ai:443/library/llama3") == "llama3:latest"
        assert normalise_model_name("https://registry.ollama.ai/library/llama3") == "llama3:latest"
        assert normalise_model_name("HTTP://registry.ollama.ai:11434/library/llama3") == "llama3:latest"

    def test_create_variant_refuses_registry_name_matching_existing(self):
        calls = []

        def fake_request(endpoint, port=None, method="GET", data=None, timeout=10):
            calls.append(endpoint)
            if endpoint == "/api/tags":
                return {"success": True, "data": {"models": [{"name": "llama-tuned:latest"}]}}
            return {"success": False}

        result = create_variant(
            "llama3.2:3b",
            "registry.ollama.ai/library/llama-tuned",
            confirm=True,
            request_fn=fake_request,
        )
        assert result["wrote"] is False
        assert "already exists" in result["error"]
        assert "/api/create" not in calls

    def test_create_variant_refuses_library_prefix_matching_existing(self):
        def fake_request(endpoint, port=None, method="GET", data=None, timeout=10):
            if endpoint == "/api/tags":
                return {"success": True, "data": {"models": [{"name": "llama-tuned"}]}}
            return {"success": False}

        result = create_variant(
            "llama3.2:3b", "library/llama-tuned", confirm=True, request_fn=fake_request
        )
        assert result["wrote"] is False
        assert "already exists" in result["error"]

    def test_create_variant_refuses_untagged_when_latest_exists(self):
        def fake_request(endpoint, port=None, method="GET", data=None, timeout=10):
            if endpoint == "/api/tags":
                return {"success": True, "data": {"models": [{"name": "llama-tuned:latest"}]}}
            return {"success": False}

        result = create_variant(
            "llama3.2:3b", "llama-tuned", confirm=True, request_fn=fake_request
        )
        assert result["wrote"] is False
        assert result["normalised_name"] == "llama-tuned:latest"

    @pytest.mark.parametrize(
        "variant",
        (
            "LLAMA3",
            "llama3:LATEST",
            "registry.ollama.ai:443/library/llama3",
        ),
    )
    def test_create_variant_refuses_case_scheme_and_port_aliases(self, variant):
        calls = []

        def fake_request(endpoint, port=None, method="GET", data=None, timeout=10):
            calls.append(endpoint)
            if endpoint == "/api/tags":
                return {"success": True, "data": {"models": [{"name": "llama3:latest"}]}}
            return {"success": False}

        result = create_variant(
            "llama3.2:3b", variant, confirm=True, request_fn=fake_request
        )
        assert result["wrote"] is False
        assert "already exists" in result["error"]
        assert result["normalised_name"] == "llama3:latest"
        assert "/api/create" not in calls

    def test_rejects_leftover_scheme_separator(self):
        assert leftover_scheme("llama3:latest://evil")
        assert leftover_scheme("://still-here")
        assert leftover_scheme("https://registry.ollama.ai/library/llama3") is False
        err = validate_model_name("llama3:latest://evil")
        assert err is not None
        assert "://" in err
        result = create_variant("llama3.2:3b", "llama3:latest://evil", confirm=False)
        assert result["success"] is False
        assert "://" in result["error"]
        assert validate_model_name("https://registry.ollama.ai/library/llama3") is None

    def test_rejects_dotdot_in_model_name(self):
        assert looks_like_local_path("../evil")
        result = create_variant("llama3.2:3b", "foo/../bar", confirm=False)
        assert result["success"] is False
        assert "path" in result["error"]

    def test_rejects_leading_slash_in_model_name(self):
        result = create_variant("/tmp/model", "ok-name", confirm=False)
        assert result["success"] is False
        assert "path" in result["error"]

    def test_rejects_leading_tilde_in_model_name(self):
        result = create_variant("~/models/llama", "ok-name", confirm=False)
        assert result["success"] is False
        assert "path" in result["error"]

    def test_rejects_local_gguf_path_in_model_name(self):
        result = create_variant("./weights.gguf", "ok-name", confirm=False)
        assert result["success"] is False
        assert "path" in result["error"]

    def test_query_local_ai_sends_normalised_method(self, monkeypatch):
        captured = {}

        def fake_request(endpoint, port=None, method="GET", data=None, timeout=10):
            captured["method"] = method
            captured["endpoint"] = endpoint
            return {"success": True, "data": {}}

        monkeypatch.setattr("src.server.make_api_request", fake_request)
        monkeypatch.setattr("src.server.current_ports", lambda: {"local_ai": 11964})
        json.loads(query_local_ai_service("/api/tags", "get"))
        assert captured["method"] == "GET"
        assert captured["endpoint"] == "/api/tags"

    def test_mcp_install_and_settings_preview(self, monkeypatch):
        monkeypatch.setattr(
            "src.server.pull_model",
            lambda *a, **k: {"wrote": False, "status": "preview", "model": "x"},
        )
        monkeypatch.setattr(
            "src.server.create_variant",
            lambda *a, **k: {"wrote": False, "status": "preview", "modelfile": "FROM x"},
        )
        assert json.loads(install_model("x"))["wrote"] is False
        assert "FROM" in json.loads(set_model_settings("x", "y"))["modelfile"]


class TestWrites:
    def test_system_prompt_blob_defaults_to_append(self):
        blob = json.loads(writes._system_prompt_blob("Be brief."))
        assert blob == {"text": "Be brief.", "mode": "append"}
        wrapped = json.loads(
            writes._system_prompt_blob('{"text":"Stay.","mode":"replace"}')
        )
        assert wrapped == {"text": "Stay.", "mode": "replace"}
        override = json.loads(
            writes._system_prompt_blob('{"text":"Stay.","mode":"replace"}', "append")
        )
        assert override == {"text": "Stay.", "mode": "append"}

    def test_preview_saves_json_without_inserting(self, admin_home, studio_fixture):
        pack = writes.persona_pack("Research", "You research.", "llama3.2:3b")
        result = writes.apply_pack(
            pack,
            confirm=False,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
        )
        assert result["wrote"] is False
        assert Path(result["pack_path"]).is_file()
        conn = sqlite3.connect(str(studio_fixture))
        count = conn.execute("SELECT COUNT(*) FROM personas").fetchone()[0]
        conn.close()
        assert count == 0

    def test_confirm_without_env_writes_nothing(self, admin_home, studio_fixture, monkeypatch):
        monkeypatch.delenv("MSTY_ALLOW_STUDIO_WRITES", raising=False)
        result = writes.apply_pack(
            writes.persona_pack("Research", "You research.", "llama3.2:3b"),
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert result["wrote"] is False
        assert result["status"] == "refused"
        assert "MSTY_ALLOW_STUDIO_WRITES" in result["error"]
        conn = sqlite3.connect(str(studio_fixture))
        assert conn.execute("SELECT COUNT(*) FROM personas").fetchone()[0] == 0
        conn.close()

    def test_tools_never_reach_db_even_with_env(self, admin_home, studio_fixture, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        pack = {
            "personas": [{"name": "Research", "systemPrompt": "You research.", "model": "local"}],
            "tools": [{"name": "Memory", "toolId": "memory", "config": {}}],
            "prompts": [{"name": "Summarise", "prompt": "Summarise this."}],
            "skills": [{"name": "cite", "content": "Cite sources."}],
            "toolsets": [{"name": "Frontier only", "tools": "[]"}],
        }
        result = writes.apply_pack(
            pack,
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert result["status"] == "applied"
        assert result["wrote"] is True
        assert Path(result["backup_path"]).is_file()
        mode = Path(result["backup_path"]).stat().st_mode
        assert mode & 0o077 == 0
        pack_mode = Path(result["pack_path"]).stat().st_mode
        assert pack_mode & 0o077 == 0
        assert (admin_home / "imports").stat().st_mode & 0o077 == 0
        assert (admin_home / "backups").stat().st_mode & 0o077 == 0
        conn = sqlite3.connect(str(studio_fixture))
        assert conn.execute("SELECT name FROM personas").fetchone()[0] == "Research"
        assert conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM promptsLibraryPrompts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM skill_preferences").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM toolsets").fetchone()[0] == 0
        conn.close()
        assert "prompts" in result["skipped"]
        assert any("promptsLibraryFolders" in note for note in result.get("notes") or [])

    def test_malicious_tool_command_is_refused(self, admin_home, studio_fixture, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        result = writes.apply_pack(
            writes.tool_pack(
                {
                    "name": "evil",
                    "toolId": "evil",
                    "config": {"command": "/bin/sh", "args": ["-c", "id"], "env": {}},
                }
            ),
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert result["wrote"] is False
        assert result["status"] == "refused"
        assert "runs a program on your machine" in result["error"]
        assert Path(result["pack_path"]).is_file()
        conn = sqlite3.connect(str(studio_fixture))
        assert conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 0
        conn.close()

    def test_skill_with_command_is_refused(self, admin_home, studio_fixture, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        result = writes.apply_pack(
            {
                "skills": [
                    {
                        "name": "shell",
                        "content": {"command": "/bin/sh", "args": ["-c", "id"]},
                    }
                ]
            },
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert result["wrote"] is False
        assert result["status"] == "refused"
        assert "runs a program on your machine" in result["error"]
        conn = sqlite3.connect(str(studio_fixture))
        assert conn.execute("SELECT COUNT(*) FROM skill_preferences").fetchone()[0] == 0
        conn.close()

    def test_skills_never_reach_db_even_with_env(self, admin_home, studio_fixture, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        result = writes.apply_pack(
            {"skills": [{"name": "cite", "content": "Cite sources."}]},
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert result["wrote"] is False
        conn = sqlite3.connect(str(studio_fixture))
        assert conn.execute("SELECT COUNT(*) FROM skill_preferences").fetchone()[0] == 0
        conn.close()

    def test_persona_insert_matches_studio_schema(self, admin_home, studio_fixture, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        result = writes.apply_pack(
            writes.persona_pack("Fixture Persona", "Be brief.", "llama3.2:3b"),
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert result["wrote"] is True
        conn = sqlite3.connect(str(studio_fixture))
        conn.row_factory = sqlite3.Row
        persona = conn.execute("SELECT * FROM personas").fetchone()
        version = conn.execute("SELECT * FROM personaVersions").fetchone()
        conn.close()
        sql_datetime = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        gold_extras = '{"attachmentsStudioDynamicSelection":null}'
        prompt_blob = json.loads(persona["systemPrompt"])
        assert set(prompt_blob) == {"text", "mode"}
        assert prompt_blob["text"] == "Be brief."
        assert prompt_blob["mode"] == "append"
        assert persona["name"] == "Fixture Persona"
        assert persona["folderId"] == writes.ORPHANAGE_FOLDER_ID
        assert persona["colorIcon"] == '{"name":"tabler:user-scan"}'
        assert persona["description"] is None
        assert persona["extras"] == gold_extras
        assert persona["partialSelectableAttachments"] == "[]"
        assert persona["partialModelInfo"] is None
        assert persona["partialRTDInfo"] is None
        assert persona["partialToolsetsInfo"] is None
        assert persona["partialLiveContextsInfo"] is None
        assert persona["contextShieldInfo"] is None
        assert persona["fewShotPrompts"] is None
        assert persona["partialKnowledgeStacksInfo"] is None
        assert len(persona["id"]) == 26
        assert persona["id"] != persona["activeVersionId"]
        assert sql_datetime.match(persona["createdAt"])
        assert version["id"] == persona["activeVersionId"]
        assert version["personaId"] == persona["id"]
        assert version["versionNumber"] == 1
        assert version["name"] == "Fixture Persona"
        assert json.loads(version["systemPrompt"]) == prompt_blob
        assert version["colorIcon"] is None
        assert version["description"] is None
        assert version["extras"] == gold_extras
        assert version["partialSelectableAttachments"] == "[]"
        assert version["tags"] == "[]"
        assert version["partialModelInfo"] is None
        assert version["partialRTDInfo"] is None
        assert version["partialToolsetsInfo"] is None
        assert version["partialKnowledgeStacksInfo"] is None
        assert version["partialLiveContextsInfo"] is None
        assert version["contextShieldInfo"] is None
        assert version["fewShotPrompts"] is None
        assert version["changelog"] is None
        assert sql_datetime.match(version["createdAt"])
        assert any("partialModelInfo left null" in note for note in result.get("notes") or [])

    def test_persona_insert_ignores_caller_id_and_partial_model_info(
        self, admin_home, studio_fixture, monkeypatch
    ):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        pack = {
            "personas": [
                {
                    "id": "CALLER-SUPPLIED-ID-NOT-ULID",
                    "name": "Caller Id Persona",
                    "systemPrompt": "Stay quiet.",
                    "model": "llama3.2:3b",
                    "partialModelInfo": {
                        "id": "llama3.2:3b",
                        "providerId": "FORGED-PROVIDER",
                    },
                }
            ]
        }
        result = writes.apply_pack(
            pack,
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert result["wrote"] is True
        conn = sqlite3.connect(str(studio_fixture))
        row = conn.execute(
            "SELECT id, partialModelInfo, activeVersionId FROM personas"
        ).fetchone()
        conn.close()
        assert row[0] != "CALLER-SUPPLIED-ID-NOT-ULID"
        assert len(row[0]) == 26
        assert row[1] is None
        assert row[2] != row[0]
        assert any("partialModelInfo left null" in note for note in result.get("notes") or [])

    def test_persona_mode_replace_when_caller_asks(
        self, admin_home, studio_fixture, monkeypatch
    ):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        pack = {
            "personas": [
                {
                    "name": "Replace Mode",
                    "systemPrompt": "You replace.",
                    "model": "llama3.2:3b",
                    "mode": "replace",
                }
            ]
        }
        result = writes.apply_pack(
            pack,
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert result["wrote"] is True
        conn = sqlite3.connect(str(studio_fixture))
        blob = conn.execute("SELECT systemPrompt FROM personas").fetchone()[0]
        conn.close()
        parsed = json.loads(blob)
        assert parsed == {"text": "You replace.", "mode": "replace"}

    def test_persona_description_stays_off_the_version(
        self, admin_home, studio_fixture, monkeypatch
    ):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        pack = {
            "personas": [
                {
                    "name": "Described",
                    "systemPrompt": "Hi.",
                    "model": "llama3.2:3b",
                    "description": "A short note.",
                }
            ]
        }
        result = writes.apply_pack(
            pack,
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert result["wrote"] is True
        conn = sqlite3.connect(str(studio_fixture))
        persona_desc = conn.execute("SELECT description FROM personas").fetchone()[0]
        version_desc = conn.execute(
            "SELECT description FROM personaVersions"
        ).fetchone()[0]
        conn.close()
        assert persona_desc == "A short note."
        assert version_desc is None

    def test_duplicate_persona_name_is_refused(self, admin_home, studio_fixture, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        first = writes.apply_pack(
            writes.persona_pack("Unique Name", "First.", "llama3.2:3b"),
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert first["wrote"] is True
        second = writes.apply_pack(
            writes.persona_pack("Unique Name", "Second.", "llama3.2:3b"),
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert second["wrote"] is False
        assert second["status"] == "refused"
        assert "already exists" in second["error"]
        conn = sqlite3.connect(str(studio_fixture))
        assert conn.execute("SELECT COUNT(*) FROM personas").fetchone()[0] == 1
        first_blob = json.loads(
            conn.execute("SELECT systemPrompt FROM personas").fetchone()[0]
        )
        assert first_blob["text"] == "First."
        conn.close()

    def test_prompts_without_folder_are_pack_only(
        self, admin_home, studio_fixture, monkeypatch
    ):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        result = writes.apply_pack(
            {"prompts": [{"name": "Summarise", "prompt": "Summarise this."}]},
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert result["wrote"] is False
        assert result["status"] == "pack_only"
        assert "promptsLibraryFolders" in result["error"]
        conn = sqlite3.connect(str(studio_fixture))
        assert conn.execute("SELECT COUNT(*) FROM promptsLibraryPrompts").fetchone()[0] == 0
        conn.close()

    def test_prompt_insert_with_folder_writes_version(
        self, admin_home, studio_fixture, monkeypatch
    ):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        conn = sqlite3.connect(str(studio_fixture))
        conn.execute(
            "INSERT INTO promptsLibraryFolders (id, name) VALUES ('folder-1', 'Inbox')"
        )
        conn.commit()
        conn.close()
        result = writes.apply_pack(
            {"prompts": [{"name": "Summarise", "prompt": "Summarise this."}]},
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert result["wrote"] is True
        conn = sqlite3.connect(str(studio_fixture))
        prompt = conn.execute(
            "SELECT id, title, text, folderId, activeVersionId, createdAt, extras "
            "FROM promptsLibraryPrompts"
        ).fetchone()
        version = conn.execute(
            "SELECT id, promptId, versionNumber, title, text, createdAt FROM promptsVersions"
        ).fetchone()
        search_hits = conn.execute(
            "SELECT entity FROM search WHERE entityId = ?", (prompt[0],)
        ).fetchall()
        conn.close()
        sql_datetime = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        assert prompt[1] == "Summarise"
        assert prompt[2] == "Summarise this."
        assert prompt[3] == "folder-1"
        assert prompt[4] == prompt[0]
        assert sql_datetime.match(prompt[5])
        assert prompt[6] == "{}"
        assert len(prompt[0]) == 26
        assert version[0] == version[1] == prompt[0]
        assert version[2] == 1
        assert sql_datetime.match(version[5])
        assert search_hits

    def test_prompt_insert_ignores_caller_id(self, admin_home, studio_fixture, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        conn = sqlite3.connect(str(studio_fixture))
        conn.execute(
            "INSERT INTO promptsLibraryFolders (id, name) VALUES ('folder-1', 'Inbox')"
        )
        conn.commit()
        conn.close()
        result = writes.apply_pack(
            {
                "prompts": [
                    {
                        "id": "CALLER-PROMPT-ID",
                        "name": "Caller Prompt",
                        "prompt": "Do not keep this id.",
                    }
                ]
            },
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert result["wrote"] is True
        conn = sqlite3.connect(str(studio_fixture))
        prompt_id = conn.execute("SELECT id FROM promptsLibraryPrompts").fetchone()[0]
        conn.close()
        assert prompt_id != "CALLER-PROMPT-ID"
        assert len(prompt_id) == 26

    def test_partial_model_info_when_config_maps_provider(
        self, admin_home, studio_fixture, monkeypatch
    ):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        conn = sqlite3.connect(str(studio_fixture))
        conn.execute(
            "INSERT INTO languageModelsProviders (id, name, providerId) "
            "VALUES ('prov-1', 'Msty Local AI', 'mstyLocal')"
        )
        conn.execute(
            "INSERT INTO languageModelConfigs (id, providerId, modelId) "
            "VALUES ('cfg-1', 'prov-1', 'llama3.2:3b')"
        )
        conn.commit()
        conn.close()
        pack = writes.persona_pack("Mapped", "Hello.", "llama3.2:3b")
        pack["personas"][0]["partialModelInfo"] = {
            "id": "forged",
            "providerId": "FORGED-PROVIDER",
        }
        result = writes.apply_pack(
            pack,
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
            backup_root=admin_home / "backups",
        )
        assert result["wrote"] is True
        conn = sqlite3.connect(str(studio_fixture))
        info = conn.execute("SELECT partialModelInfo FROM personas").fetchone()[0]
        version_info = conn.execute(
            "SELECT partialModelInfo, colorIcon, description FROM personaVersions"
        ).fetchone()
        conn.close()
        assert json.loads(info) == {"id": "llama3.2:3b", "providerId": "prov-1"}
        assert version_info[0] is None
        assert version_info[1] is None
        assert version_info[2] is None

    def test_pack_names_are_unique_within_the_same_second(
        self, admin_home, studio_fixture
    ):
        names = []
        for index in range(8):
            path = writes.save_import_pack(
                {"n": index}, dest_dir=admin_home / "imports"
            )
            names.append(path.name)
            assert path.is_file()
        assert len(set(names)) == 8
        assert len(names) == len(set(str(admin_home / "imports" / n) for n in names))

    def test_sqlite_readonly_uri_uses_as_uri(self, tmp_path):
        db_path = tmp_path / "studio.db"
        db_path.write_bytes(b"")
        uri = writes.sqlite_readonly_uri(db_path)
        expected = db_path.resolve().as_uri()
        assert uri == f"{expected}?mode=ro"
        assert uri.startswith("file:")
        conn = sqlite3.connect(uri, uri=True)
        conn.close()

    def test_backup_includes_wal_row(self, tmp_path):
        db_path = tmp_path / "studio.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE items (id TEXT, name TEXT)")
        conn.commit()
        conn.execute("INSERT INTO items VALUES ('1', 'wal-row')")
        conn.commit()
        wal = Path(str(db_path) + "-wal")
        assert wal.exists()
        dest = writes.backup_database(db_path, dest_dir=tmp_path / "backups")
        assert dest.stat().st_mode & 0o077 == 0
        check = sqlite3.connect(writes.sqlite_readonly_uri(dest), uri=True)
        names = [row[0] for row in check.execute("SELECT name FROM items")]
        check.close()
        conn.close()
        assert "wal-row" in names

    def test_refuses_when_studio_holds_live_db(self, admin_home, studio_fixture, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        monkeypatch.setattr(writes, "is_live_studio_database", lambda _p: True)
        monkeypatch.setattr(writes, "is_process_running", lambda _n: True)
        result = writes.apply_pack(
            writes.persona_pack("X", "Y", "Z"),
            confirm=True,
            database_path=str(studio_fixture),
            imports_root=admin_home / "imports",
        )
        assert result["status"] == "refused"
        assert result["wrote"] is False
        assert "running" in result["error"]

    def test_generate_persona_and_import_tool_mcp(self, admin_home, studio_fixture, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        monkeypatch.setattr(writes, "resolve_database_path", lambda explicit=None: studio_fixture)
        monkeypatch.setattr(writes, "studio_holds_live_database", lambda _p: False)
        preview = json.loads(generate_persona("Tester", "Be thorough.", "llama3.2:3b"))
        assert preview["wrote"] is False
        applied = json.loads(
            generate_persona("Tester", "Be thorough.", "llama3.2:3b", confirm=True)
        )
        assert applied["wrote"] is True
        tool = json.loads(
            import_tool_config({"name": "Web", "toolId": "web", "config": {}}, confirm=True)
        )
        assert tool["wrote"] is False
        pack = json.loads(
            import_studio_pack(
                {"prompts": [{"name": "Hello", "prompt": "Hi"}]},
                confirm=True,
            )
        )
        assert pack["wrote"] is False
        assert pack["status"] == "pack_only"
        assert "promptsLibraryFolders" in (pack.get("error") or "")
        assert HOOK_API_NOTE in pack["hook_api"]

    def test_is_process_running_fails_closed(self, monkeypatch):
        monkeypatch.setattr("src.paths.psutil", None)
        assert is_process_running("MstyStudio") is True
        boom = MagicMock()
        boom.process_iter.side_effect = RuntimeError("denied")
        monkeypatch.setattr("src.paths.psutil", boom)
        assert is_process_running("MstyStudio") is True


class TestFrontierProviders:
    def test_resolve_provider_aliases(self):
        assert resolve_provider("xai") == "grok"
        assert resolve_provider("anthropic") == "claude"
        assert resolve_provider(None) == "cursor"

    def test_grok_mocked_http(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        store = tmp_path / "grok.json"

        def fake_http(url, headers, payload, timeout):
            assert "api.x.ai" in url
            assert headers["Authorization"] == "Bearer test-key"
            assert payload["messages"][-1]["role"] == "user"
            return {"choices": [{"message": {"content": "4"}}]}

        first = ask_grok("What is 2+2?", session_path=store, http_json=fake_http)
        assert first.answer == "4"
        assert first.resumed is False
        second = ask_grok("again", session_path=store, http_json=fake_http)
        assert second.resumed is True

    def test_claude_mocked_http(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        store = tmp_path / "claude.json"

        def fake_http(url, headers, payload, timeout):
            assert "api.anthropic.com" in url
            assert headers["x-api-key"] == "test-key"
            return {"content": [{"type": "text", "text": "hello"}]}

        result = ask_claude("Hi", session_path=store, http_json=fake_http)
        assert result.answer == "hello"

    def test_missing_keys(self, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="XAI_API_KEY"):
            ask_grok("x", http_json=lambda *a: {})
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            ask_claude("x", http_json=lambda *a: {})

    def test_dispatch_cursor_default(self, monkeypatch):
        monkeypatch.setattr(
            "src.frontier.ask_cursor_agent",
            lambda question, fresh=False, **k: type("R", (), {"answer": "cursor-ok", "chat_id": "c", "resumed": False})(),
        )
        assert ask_frontier("q").answer == "cursor-ok"

    def test_escalation_persona_mentions_ask_frontier(self):
        assert "ask_frontier" in ESCALATION_PERSONA["systemPrompt"]
        assert "no hook api" in HOOK_API_NOTE.lower()


class TestBloom:
    def test_evaluate_mcp_without_key_invents_no_score(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        payload = json.loads(bloom_evaluate_model("llama3.2:3b", "sycophancy"))
        assert payload.get("quality_score") is None
        assert "ANTHROPIC_API_KEY" in payload["error"]
        assert "invented" in payload["note"].lower()

    def test_history_and_handoff_from_sidecar(self, admin_home):
        empty = json.loads(bloom_get_history("llama3.2:3b"))
        assert empty["evaluations"] == []
        check = json.loads(bloom_check_handoff("llama3.2:3b", "advisory_tasks"))
        assert check["should_handoff"] is False
        assert "invented" in check["reason"].lower() or "no bloom history" in check["reason"].lower()
        persist_evaluation(
            EvaluationResult(
                behavior="sycophancy",
                model="llama3.2:3b",
                task_category="advisory_tasks",
                quality_score=0.2,
                passed=False,
                timestamp="2026-11-01T00:00:00",
            )
        )
        history = load_persisted_history(model="llama3.2:3b")
        assert history[-1]["quality_score"] == 0.2
        advice = handoff_from_history("llama3.2:3b", "advisory_tasks")
        assert advice["should_handoff"] is True
        history_file = Path(os.environ["MSTY_BLOOM_HISTORY"])
        assert history_file.stat().st_mode & 0o077 == 0

    def test_bloom_child_env_drops_other_keys(self):
        env = bloom_child_env(
            {
                "PATH": "/bin",
                "HOME": "/tmp",
                "ANTHROPIC_API_KEY": "a",
                "XAI_API_KEY": "x",
                "CURSOR_API_KEY": "c",
            }
        )
        assert env["ANTHROPIC_API_KEY"] == "a"
        assert env["PATH"] == "/bin"
        assert "XAI_API_KEY" not in env
        assert "CURSOR_API_KEY" not in env

    def test_evaluate_sync_wires_real_result(self, monkeypatch, admin_home):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        class FakeEval:
            bloom_path = "/tmp/bloom"

            def evaluate(self, **kwargs):
                return EvaluationResult(
                    behavior=kwargs["behavior"],
                    model=kwargs["model"],
                    task_category=kwargs.get("task_category"),
                    quality_score=0.81,
                    passed=True,
                    timestamp="2026-11-01T00:00:00",
                )

        monkeypatch.setattr("src.server.get_bloom_evaluator", lambda: FakeEval())
        payload = json.loads(bloom_evaluate_model("llama3.2:3b", "sycophancy"))
        assert payload["quality_score"] == 0.81
        assert payload["passed"] is True


class TestToolCount:
    def test_decorator_count_matches_constant(self):
        text = Path("src/server.py").read_text(encoding="utf-8")
        assert text.count("@mcp.tool()") == TOOL_COUNT
        assert TOOL_COUNT == 61

    def test_readme_lists_every_tool(self):
        import re

        src = Path("src/server.py").read_text(encoding="utf-8")
        names = re.findall(r"@mcp\.tool\(\)\s*\ndef (\w+)", src)
        readme = Path("README.md").read_text(encoding="utf-8")
        missing = [name for name in names if f"`{name}`" not in readme]
        assert names
        assert len(names) == TOOL_COUNT
        assert missing == []
