#!/usr/bin/env python3
"""
Tests for Msty Admin MCP Server v6.0.0

Run with: pytest tests/ -v
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.paths import (
    MstyInstallation,
    get_msty_paths,
    is_process_running,
    is_port_open,
    parse_service_ports,
    resolve_database_path,
)
from src import db, inventory, analytics
from src.server import (
    DatabaseStats,
    MstyHealthReport,
    SERVER_VERSION,
    detect_msty_installation,
    get_server_status,
    list_configured_tools,
    read_msty_database,
    analyse_msty_health,
    get_model_providers,
    list_personas,
    list_studio_catalogue,
    optimise_knowledge_stacks,
    suggest_persona_improvements,
    get_model_performance_metrics,
    export_workflow_pack,
    detect_nexus,
    evaluate_response_quality,
)


@pytest.fixture()
def temp_studio_db(tmp_path: Path) -> Path:
    """Minimal Studio-like SQLite for unit tests."""
    db_path = tmp_path / "00000000"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE personas (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            folderId TEXT,
            systemPrompt TEXT NOT NULL,
            partialRTDInfo TEXT,
            partialSelectableAttachments TEXT,
            partialToolsetsInfo TEXT,
            partialLiveContextsInfo TEXT,
            contextShieldInfo TEXT,
            partialModelInfo TEXT,
            fewShotPrompts TEXT,
            extras TEXT,
            createdAt TEXT DEFAULT CURRENT_TIMESTAMP,
            partialKnowledgeStacksInfo TEXT,
            activeVersionId TEXT,
            colorIcon TEXT
        );
        CREATE TABLE tools (
            id TEXT PRIMARY KEY,
            toolId TEXT NOT NULL,
            name TEXT NOT NULL,
            config TEXT NOT NULL,
            notes TEXT,
            provider TEXT,
            compatibility TEXT,
            colorIcon TEXT,
            extras TEXT,
            createdAt TEXT DEFAULT CURRENT_TIMESTAMP,
            folderId TEXT
        );
        CREATE TABLE knowledgeStacks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            text TEXT,
            source TEXT,
            sortOrder INTEGER,
            folderId TEXT,
            status TEXT,
            files TEXT,
            notes TEXT,
            youTubeLinks TEXT,
            folders TEXT,
            obsidianVaults TEXT,
            composeStats TEXT,
            composeSettings TEXT,
            querySettings TEXT,
            vectorInfo TEXT,
            extras TEXT,
            createdAt TEXT DEFAULT CURRENT_TIMESTAMP,
            updatedAt TEXT DEFAULT CURRENT_TIMESTAMP,
            webLinks TEXT,
            conversations TEXT,
            conversationProjects TEXT
        );
        CREATE TABLE insightsLanguageModelUsage (
            id TEXT PRIMARY KEY,
            providerId TEXT NOT NULL,
            providerType TEXT NOT NULL,
            modelId TEXT NOT NULL,
            promptTokens INTEGER NOT NULL,
            completionTokens INTEGER NOT NULL,
            totalTokens INTEGER NOT NULL,
            inputCostInUSD REAL NOT NULL,
            outputCostInUSD REAL NOT NULL,
            totalCostInUSD REAL NOT NULL,
            timeToFirstResponseInSec REAL NOT NULL,
            totalTimeInSec REAL NOT NULL,
            tokensPerSec REAL NOT NULL,
            chatSplitId TEXT,
            conversationId TEXT,
            createdAt TEXT DEFAULT CURRENT_TIMESTAMP,
            extras TEXT
        );
        CREATE TABLE workspaces (
            id TEXT PRIMARY KEY,
            name TEXT,
            createdAt TEXT DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO personas (id, name, folderId, systemPrompt)
        VALUES ('p1', 'Tester', 'f1', 'You are a thorough test assistant that validates MCP tools.');
        INSERT INTO tools (id, toolId, name, config, provider)
        VALUES ('t1', 'memory', 'Memory Service', '{}', 'mcp');
        INSERT INTO knowledgeStacks (id, title, status, composeSettings, querySettings, folderId)
        VALUES ('k1', 'Docs', 'draft', '{}', '{}', 'f1');
        INSERT INTO insightsLanguageModelUsage (
            id, providerId, providerType, modelId, promptTokens, completionTokens, totalTokens,
            inputCostInUSD, outputCostInUSD, totalCostInUSD, timeToFirstResponseInSec,
            totalTimeInSec, tokensPerSec
        ) VALUES (
            'i1', 'local', 'mstyLocal', 'llama3.2:3b', 10, 20, 30, 0, 0, 0, 0.1, 1.5, 12.0
        );
        INSERT INTO workspaces (id, name) VALUES ('w1', 'Default');
        """
    )
    conn.commit()
    conn.close()
    # SQLite magic already present
    return db_path


class TestPathResolution:
    def test_get_msty_paths_returns_dict(self):
        paths = get_msty_paths()
        assert isinstance(paths, dict)

    def test_get_msty_paths_has_expected_keys(self):
        paths = get_msty_paths()
        for key in ["app", "app_alt", "data", "sidecar", "database", "mlx_models"]:
            assert key in paths

    def test_parse_service_ports(self):
        ports = parse_service_ports(
            {"localAIService": {"host": "127.0.0.1:11964"}, "mlxService": {"host": "127.0.0.1"}}
        )
        assert ports["local_ai"] == 11964
        assert "mlx" in ports

    def test_resolve_database_path_finds_sqlite(self, temp_studio_db: Path, tmp_path: Path):
        paths = {
            "database": temp_studio_db,
            "database_legacy_studio": tmp_path / "missing.db",
            "database_legacy": tmp_path / "missing2.db",
            "data": tmp_path,
        }
        resolved = resolve_database_path(paths)
        assert resolved == temp_studio_db


class TestProcessDetection:
    def test_is_process_running_returns_bool(self):
        result = is_process_running("nonexistent_process_12345")
        assert result is False

    @patch("src.paths.psutil")
    def test_is_process_running_finds_process(self, mock_psutil):
        mock_proc = MagicMock()
        mock_proc.info = {"name": "MstyStudio"}
        mock_psutil.process_iter.return_value = [mock_proc]
        assert is_process_running("MstyStudio") is True

    def test_is_port_open_closed(self):
        assert is_port_open("127.0.0.1", 1) is False


class TestDataClasses:
    def test_msty_installation_defaults(self):
        install = MstyInstallation(installed=False)
        assert install.installed is False
        assert install.version is None
        assert install.is_running is False
        assert install.platform_info == {}

    def test_msty_health_report_defaults(self):
        report = MstyHealthReport(overall_status="unknown")
        assert report.overall_status == "unknown"
        assert report.database_status == {}
        assert report.recommendations == []

    def test_database_stats_defaults(self):
        stats = DatabaseStats()
        assert stats.total_conversations == 0
        assert stats.total_messages == 0
        assert stats.database_size_mb == 0.0


class TestDatabaseLayer:
    def test_safe_query_rejects_writes(self, temp_studio_db: Path):
        with pytest.raises(ValueError):
            db.safe_query("DELETE FROM personas", database_path=str(temp_studio_db))

    def test_fetch_personas(self, temp_studio_db: Path):
        rows = db.fetch_all("personas", database_path=str(temp_studio_db))
        assert len(rows) == 1
        assert rows[0]["name"] == "Tester"

    def test_redacts_credentials(self):
        row = db.redact_row({"name": "x", "api_key": "secret-value", "token": "abc"})
        assert row["api_key"] == "[REDACTED]"
        assert row["token"] == "[REDACTED]"


class TestInventoryAnalytics:
    def test_list_entities(self, temp_studio_db: Path, monkeypatch):
        monkeypatch.setattr(db, "get_database_path", lambda explicit=None: temp_studio_db)
        result = inventory.list_entities("personas")
        assert result["count"] == 1

    def test_optimise_knowledge_stacks(self, temp_studio_db: Path, monkeypatch):
        monkeypatch.setattr(db, "get_database_path", lambda explicit=None: temp_studio_db)
        result = analytics.optimise_knowledge_stacks()
        assert result["draft_count"] == 1
        assert any("draft" in s.lower() for s in result["suggestions"])

    def test_insights_usage(self, temp_studio_db: Path, monkeypatch):
        monkeypatch.setattr(db, "get_database_path", lambda explicit=None: temp_studio_db)
        result = analytics.get_insights_usage(timeframe="all")
        assert result["totals"]["calls"] == 1
        assert result["models"][0]["model_id"] == "llama3.2:3b"


class TestMCPTools:
    def test_server_version(self):
        assert SERVER_VERSION == "6.0.0"

    def test_detect_msty_installation_returns_json(self):
        data = json.loads(detect_msty_installation())
        assert "installed" in data or "found" in data
        assert "platform_info" in data

    def test_read_msty_database_stats_returns_json(self):
        data = json.loads(read_msty_database(query="stats"))
        assert "query_type" in data

    def test_read_msty_database_tables_returns_json(self):
        data = json.loads(read_msty_database(query="tables"))
        assert "query_type" in data

    def test_list_configured_tools_returns_json(self):
        data = json.loads(list_configured_tools())
        assert "tools" in data
        assert "tool_count" in data

    def test_get_model_providers_returns_json(self):
        data = json.loads(get_model_providers())
        assert "local_models" in data
        assert "remote_providers" in data

    def test_analyse_msty_health_returns_json(self):
        data = json.loads(analyse_msty_health())
        assert "overall_status" in data
        assert "recommendations" in data

    def test_get_server_status_returns_json(self):
        data = json.loads(get_server_status())
        assert data["server"]["version"] == "6.0.0"
        assert data["tools_available"] >= 50

    def test_list_personas_json(self):
        data = json.loads(list_personas())
        assert "items" in data or "error" in data

    def test_list_studio_catalogue_json(self):
        data = json.loads(list_studio_catalogue())
        assert isinstance(data, dict)

    def test_optimise_and_persona_tools_json(self):
        assert "suggestions" in json.loads(optimise_knowledge_stacks())
        assert "suggestions" in json.loads(suggest_persona_improvements())

    def test_performance_metrics_json(self):
        data = json.loads(get_model_performance_metrics(timeframe="all"))
        assert "models" in data or "error" in data or "metrics" in data

    def test_export_workflow_pack_json(self):
        data = json.loads(export_workflow_pack(include=["personas", "tools"], limit=10))
        assert data["format"] == "msty-admin-workflow-pack"

    def test_detect_nexus_json(self):
        data = json.loads(detect_nexus())
        assert "found" in data

    def test_evaluate_response_quality(self):
        data = json.loads(
            evaluate_response_quality(
                prompt="Explain gravity",
                response="Gravity is a force that attracts masses toward each other.",
                category="analysis",
            )
        )
        assert "quality_score" in data


class TestSecurityFeatures:
    def test_api_keys_redacted(self):
        result = get_model_providers()
        data = json.loads(result)
        for provider in data.get("database_providers", []):
            for key, value in provider.items():
                if any(x in key.lower() for x in ["key", "secret", "token", "credential"]):
                    if value not in (None, "", [], {}):
                        assert value == "[REDACTED]", f"Key {key} not redacted"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
