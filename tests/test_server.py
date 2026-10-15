#!/usr/bin/env python3
"""
Tests for Msty Admin MCP Server v6.1.4

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
        CREATE TABLE languageModelsProviders (
            id TEXT PRIMARY KEY,
            name TEXT,
            providerId TEXT,
            models TEXT,
            apiKey TEXT,
            config TEXT,
            extras TEXT,
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
        INSERT INTO languageModelsProviders (id, name, apiKey, config, extras)
        VALUES (
            'prov1',
            'OpenAI',
            'sk-live-TESTSECRET99',
            '{"apiKey":"sk-json-TESTSECRET99","name":"ok"}',
            '{}'
        );
        """
    )
    conn.commit()
    conn.close()
    # SQLite magic already present
    return db_path


DUMMY_PROVIDER_KEY = "DUMMY-FAKE-KEY-NOT-REAL-0000"
DUMMY_CONFIG_KEY = "DUMMY-FAKE-CONFIG-KEY-NOT-REAL-0000"
DUMMY_EXTRAS_KEY = "DUMMY-FAKE-EXTRAS-KEY-NOT-REAL-0000"


@pytest.fixture()
def fake_studio_db(temp_studio_db: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the db layer at a fake Studio DB so tool tests run without Msty installed.

    Adds an extra provider row with obviously dummy credentials. Only the
    database location is patched; redaction and authorizer code are untouched.
    """
    conn = sqlite3.connect(str(temp_studio_db))
    conn.execute(
        "INSERT INTO languageModelsProviders (id, name, apiKey, config, extras) VALUES (?, ?, ?, ?, ?)",
        (
            "prov-dummy",
            "Dummy Provider",
            DUMMY_PROVIDER_KEY,
            json.dumps({"apiKey": DUMMY_CONFIG_KEY, "name": "dummy"}),
            json.dumps({"apiKey": DUMMY_EXTRAS_KEY, "label": "dummy"}),
        ),
    )
    conn.commit()
    conn.close()

    real_get_database_path = db.get_database_path

    def _fake_get_database_path(explicit=None):
        if explicit:
            return real_get_database_path(explicit)
        return temp_studio_db

    monkeypatch.setattr(db, "get_database_path", _fake_get_database_path)
    return temp_studio_db


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

    def test_redacts_keys_inside_json_text(self):
        row = db.redact_row({"extras": '{"apiKey":"sk-live","name":"ok"}'})
        payload = json.loads(row["extras"])
        assert payload["apiKey"] == "[REDACTED]"
        assert payload["name"] == "ok"

    def test_redacts_secret_shaped_values_when_column_name_is_safe(self):
        row = db.redact_row({"x": "sk-live-TESTSECRET99"})
        assert row["x"] == "[REDACTED]"
        row2 = db.redact_row({"x": "ordinary-name"})
        assert row2["x"] == "ordinary-name"

    def test_refuses_queries_that_name_credential_columns(self):
        assert db.names_credential_column("SELECT apiKey AS x FROM providers")
        assert db.names_credential_column("SELECT api_key FROM providers")
        assert not db.names_credential_column("SELECT name, extras FROM personas")

    def test_safe_query_rejects_credential_columns(self, temp_studio_db: Path):
        with pytest.raises(ValueError, match="credential"):
            db.safe_query("SELECT api_key AS x FROM tools", database_path=str(temp_studio_db))

    def _query_hiding_secrets(self, sql: str, temp_studio_db: Path):
        try:
            results, count = db.safe_query(sql, database_path=str(temp_studio_db))
            payload: dict = {"results": results, "count": count}
        except Exception as exc:
            payload = {"error": str(exc)}
        blob = json.dumps(payload, default=str)
        assert "TESTSECRET99" not in blob
        assert "sk-live-" not in blob
        assert "sk-json-" not in blob
        return payload

    def test_quoted_identifier_does_not_leak_apikey(self, temp_studio_db: Path):
        payload = self._query_hiding_secrets(
            'SELECT "apiKey" AS x FROM languageModelsProviders',
            temp_studio_db,
        )
        if "results" in payload:
            assert payload["results"]
            assert payload["results"][0].get("x") in (None, "[REDACTED]")

    def test_cte_column_rename_does_not_leak_apikey(self, temp_studio_db: Path):
        payload = self._query_hiding_secrets(
            "WITH t(a, b, c, d, e) AS (SELECT * FROM languageModelsProviders) SELECT c FROM t",
            temp_studio_db,
        )
        if "results" in payload:
            assert payload["results"]
            assert payload["results"][0].get("c") in (None, "[REDACTED]")

    def test_json_extract_does_not_leak_apikey(self, temp_studio_db: Path):
        payload = self._query_hiding_secrets(
            "SELECT json_extract(config, '$.apiKey') AS x FROM languageModelsProviders",
            temp_studio_db,
        )
        if "results" in payload:
            assert payload["results"]
            assert payload["results"][0].get("x") in (None, "[REDACTED]")

    def test_json_extract_variants_do_not_leak_apikey(self, temp_studio_db: Path):
        queries = [
            "SELECT config->>'apiKey' AS x FROM languageModelsProviders",
            "SELECT config->'$.apiKey' AS x FROM languageModelsProviders",
            "SELECT `apiKey` AS x FROM languageModelsProviders",
            "SELECT [apiKey] AS x FROM languageModelsProviders",
            "SELECT j.value FROM languageModelsProviders, json_each(config) AS j",
            "SELECT substr(config, 12, 24) AS x FROM languageModelsProviders",
            "SELECT hex(apiKey) AS x FROM languageModelsProviders",
        ]
        for sql in queries:
            self._query_hiding_secrets(sql, temp_studio_db)

    def test_legitimate_provider_queries_still_work(self, temp_studio_db: Path):
        names, count = db.safe_query(
            "SELECT name FROM languageModelsProviders",
            database_path=str(temp_studio_db),
        )
        assert count == 1
        assert names[0]["name"] == "OpenAI"

        configs, _ = db.safe_query(
            "SELECT config FROM languageModelsProviders",
            database_path=str(temp_studio_db),
        )
        # Free SQL never sees raw JSON config; entity tools return it redacted.
        assert configs[0]["config"] is None
        rows = db.fetch_all("languageModelsProviders", database_path=str(temp_studio_db))
        payload = json.loads(rows[0]["config"])
        assert payload["apiKey"] == "[REDACTED]"
        assert payload["name"] == "ok"

        personas, _ = db.safe_query(
            "SELECT name, systemPrompt FROM personas",
            database_path=str(temp_studio_db),
        )
        assert personas[0]["name"] == "Tester"
        assert "thorough test assistant" in personas[0]["systemPrompt"]

    def test_read_msty_database_tool_does_not_leak_quoted_apikey(
        self, temp_studio_db: Path, monkeypatch
    ):
        monkeypatch.setattr(db, "get_database_path", lambda explicit=None: temp_studio_db)
        data = json.loads(
            read_msty_database('SELECT "apiKey" AS x FROM languageModelsProviders')
        )
        blob = json.dumps(data)
        assert "TESTSECRET99" not in blob
        assert data.get("error") or data.get("results")


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


@pytest.mark.usefixtures("fake_studio_db")
class TestMCPTools:
    def test_server_version(self):
        assert SERVER_VERSION == "6.1.4"

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
        assert data["server"]["version"] == "6.1.4"
        assert data["phases"]["phase_9_frontier"] == 1
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


@pytest.mark.usefixtures("fake_studio_db")
class TestSecurityFeatures:
    def test_api_keys_redacted(self):
        result = get_model_providers()
        data = json.loads(result)
        for provider in data.get("database_providers", []):
            for key, value in provider.items():
                if any(x in key.lower() for x in ["key", "secret", "token", "credential"]):
                    if value not in (None, "", [], {}):
                        assert value == "[REDACTED]", f"Key {key} not redacted"
        providers = data.get("database_providers", [])
        assert {p.get("id") for p in providers} >= {"prov1", "prov-dummy"}, providers
        for secret in (DUMMY_PROVIDER_KEY, DUMMY_CONFIG_KEY, DUMMY_EXTRAS_KEY, "TESTSECRET99"):
            assert secret not in result, f"dummy credential {secret} leaked"
        dummy = next(p for p in providers if p.get("id") == "prov-dummy")
        assert dummy.get("apiKey") in (None, "[REDACTED]"), dummy
        # extras is a returned column carrying a dummy key: it must come back redacted
        extras = dummy.get("extras")
        extras = json.loads(extras) if isinstance(extras, str) else extras
        assert extras and extras.get("apiKey") == "[REDACTED]", extras


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestCredentialAuthorizerGuard:
    """Guards the SQLite-layer authorizer itself (not only the SQL-text filter).

    Queries go straight through db.connect(), bypassing safe_query, so the only
    thing standing between the caller and the dummy keys is _credential_authorizer.
    If it ever returned SQLITE_OK for everything, these tests fail.
    """

    QUERIES = [
        "SELECT apiKey FROM languageModelsProviders",
        "SELECT apiKey AS x FROM languageModelsProviders",
        "SELECT json_extract(config, '$.apiKey') FROM languageModelsProviders",
        "SELECT json_extract(config, '$.apiKey') AS x FROM languageModelsProviders",
    ]

    @pytest.mark.parametrize("query", QUERIES)
    def test_raw_credential_reads_are_denied_or_null(self, temp_studio_db: Path, query: str):
        try:
            with db.connect(database_path=str(temp_studio_db)) as conn:
                rows = [tuple(r) for r in conn.execute(query).fetchall()]
        except sqlite3.DatabaseError:
            return  # denied outright: acceptable
        assert rows, "fixture should contain provider rows"
        for row in rows:
            assert all(v is None for v in row), f"credential readable via {query!r}: {row}"
        assert "TESTSECRET99" not in repr(rows)

    def test_authorizer_is_installed_on_connections(self, temp_studio_db: Path):
        with sqlite3.connect(str(temp_studio_db)) as raw:
            leaked = raw.execute("SELECT apiKey FROM languageModelsProviders").fetchone()[0]
        assert leaked and "TESTSECRET99" in leaked, "control: the fixture must hold a dummy key"
        with db.connect(database_path=str(temp_studio_db)) as conn:
            try:
                value = conn.execute("SELECT apiKey FROM languageModelsProviders").fetchone()[0]
            except sqlite3.DatabaseError:
                value = None
        assert value is None


class TestFreeSqlBypassGuards:
    """Guard tests for the 15 Oct sweep. Dummy values only."""

    PLAIN = "zzDUMMYnotARealKey0000abcd"

    def _db(self, tmp_path: Path) -> str:
        p = tmp_path / "bypass.db"
        conn = sqlite3.connect(str(p))
        conn.execute("CREATE TABLE languageModelsProviders (id TEXT, config TEXT, accessToken TEXT, baseUrl TEXT)")
        conn.execute(
            "INSERT INTO languageModelsProviders VALUES ('p', ?, ?, ?)",
            (json.dumps({"apiKey": self.PLAIN, "accessToken": self.PLAIN}), self.PLAIN, f"https://u:{self.PLAIN}@h/"),
        )
        conn.commit()
        conn.close()
        return str(p)

    @pytest.mark.parametrize("query", [
        "SELECT substr(config, 1, 200) AS v FROM languageModelsProviders",
        "SELECT 'x' || config AS v FROM languageModelsProviders",
        "SELECT hex(config) AS v FROM languageModelsProviders",
        "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i<80) "
        "SELECT group_concat(unicode(substr(config,i,1))) AS v FROM languageModelsProviders, n",
        "SELECT baseUrl AS v FROM languageModelsProviders",
    ])
    def test_string_functions_cannot_slice_secrets(self, tmp_path: Path, query: str):
        rows, _ = db.safe_query(query, database_path=self._db(tmp_path))
        self._assert_no_secret(rows)

    def _assert_no_secret(self, rows):
        text = json.dumps(rows, default=lambda b: b.hex() if isinstance(b, bytes) else str(b))
        assert self.PLAIN not in text
        assert self.PLAIN.encode().hex() not in text.lower()
        codes = ",".join(str(ord(c)) for c in self.PLAIN)
        assert codes not in text

    def test_camel_case_credential_column_refused(self, tmp_path: Path):
        with pytest.raises(ValueError):
            db.safe_query("SELECT accessToken FROM languageModelsProviders", database_path=self._db(tmp_path))

    def test_camel_case_json_keys_redacted(self, tmp_path: Path):
        rows = db.fetch_all("languageModelsProviders", database_path=self._db(tmp_path))
        assert self.PLAIN not in json.dumps(rows)

    @pytest.mark.parametrize("table", ["sqlite_dbpage", "dbstat"])
    def test_raw_page_tables_denied(self, tmp_path: Path, table: str):
        path = self._db(tmp_path)
        try:
            rows, _ = db.safe_query(f"SELECT * FROM {table}", database_path=path)
        except (sqlite3.DatabaseError, ValueError):
            return
        self._assert_no_secret(rows)

    def test_runaway_query_is_interrupted(self, tmp_path: Path):
        with pytest.raises(sqlite3.OperationalError):
            db.safe_query(
                "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n) SELECT count(*) FROM n",
                database_path=self._db(tmp_path),
            )

    @pytest.mark.parametrize("column", ["data", "metadata", "options", "payload", "credentials"])
    def test_generic_json_blob_columns_not_sliceable(self, tmp_path: Path, column: str):
        p = tmp_path / "blob.db"
        conn = sqlite3.connect(str(p))
        conn.execute(f"CREATE TABLE someStudioTable (id TEXT, {column} TEXT)")
        conn.execute("INSERT INTO someStudioTable VALUES ('x', ?)", (json.dumps({"apiKey": self.PLAIN}),))
        conn.commit()
        conn.close()
        try:
            rows, _ = db.safe_query(
                "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i<80) "
                f"SELECT group_concat(unicode(substr({column},i,1))) AS v FROM someStudioTable, n",
                database_path=str(p),
            )
        except ValueError:
            return  # refused outright is also safe
        self._assert_no_secret(rows)
