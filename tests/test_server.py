#!/usr/bin/env python3
"""
Tests for Msty Admin MCP Server v6.1.5

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
        assert SERVER_VERSION == "6.1.5"

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
        assert data["server"]["version"] == "6.1.5"
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

    @pytest.mark.timeout(20, method="thread")
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


class TestRedTeamFollowUp:
    """Guards for the red-team follow-up on the 15 Oct sweep. Dummy values only."""

    PLAIN = "zzDUMMYnotARealKey0000abcd"

    def _assert_no_secret(self, rows):
        text = json.dumps(rows, default=lambda b: b.hex() if isinstance(b, bytes) else str(b))
        assert self.PLAIN not in text
        assert self.PLAIN.encode().hex() not in text.lower()
        for i in range(0, len(self.PLAIN) - 8):
            assert self.PLAIN[i:i + 8] not in text

    def _url_db(self, tmp_path: Path, column: str = "baseUrl") -> str:
        p = tmp_path / "url.db"
        conn = sqlite3.connect(str(p))
        conn.execute(f"CREATE TABLE providers (id TEXT, {column} TEXT)")
        conn.execute("INSERT INTO providers VALUES ('p', ?)", (f"https://u:{self.PLAIN}@h.example/v1",))
        conn.commit()
        conn.close()
        return str(p)

    @pytest.mark.parametrize("expr", [
        "substr(baseUrl, 9)", "substr(baseUrl, 11)", "substr(baseUrl, 11, 12)",
        "ltrim(baseUrl, 'htps:/')", "upper(baseUrl)",
    ])
    def test_url_credentials_redacted_without_scheme(self, tmp_path: Path, expr: str):
        rows, _ = db.safe_query(f"SELECT {expr} AS v FROM providers", database_path=self._url_db(tmp_path))
        self._assert_no_secret(rows)

    def test_url_credentials_in_unlisted_column_redacted(self, tmp_path: Path):
        rows, _ = db.safe_query("SELECT substr(note, 9) AS v FROM providers",
                                database_path=self._url_db(tmp_path, "note"))
        self._assert_no_secret(rows)

    def test_bare_userinfo_pattern_redacted(self):
        assert self.PLAIN not in db._redact_secret_patterns(f"u:{self.PLAIN}@h.example/v1")

    @pytest.mark.parametrize("column", ["openaiKey", "apiKeys", "authHeader", "keyValue", "providerAuth", "dbPassword"])
    def test_wider_camel_case_names_are_secret(self, tmp_path: Path, column: str):
        assert db._is_sensitive_key(column)
        p = tmp_path / "camel.db"
        conn = sqlite3.connect(str(p))
        conn.execute(f"CREATE TABLE t (id TEXT, {column} TEXT)")
        conn.execute("INSERT INTO t VALUES ('x', ?)", (self.PLAIN,))
        conn.commit()
        conn.close()
        rows = db.fetch_all("t", database_path=str(p))
        self._assert_no_secret(rows)
        try:
            rows, _ = db.safe_query(f"SELECT substr({column}, 2) AS v FROM t", database_path=str(p))
        except ValueError:
            return
        self._assert_no_secret(rows)

    @pytest.mark.parametrize("column", ["id", "primaryKey", "sortKey", "keyId", "promptTokens", "maxTokens", "modelId", "name"])
    def test_identifier_columns_stay_readable(self, column: str):
        assert not db._is_sensitive_key(column)

    def test_raw_page_table_denied_by_authorizer(self):
        for table in ("sqlite_dbpage", "dbstat"):
            for column in ("data", "pgno", "name", "anything"):
                assert db._credential_authorizer(sqlite3.SQLITE_READ, table, column, "main", None) == sqlite3.SQLITE_DENY

    def test_raw_page_table_denied_with_benign_column_names(self, tmp_path: Path):
        p = tmp_path / "page.db"
        conn = sqlite3.connect(str(p))
        conn.execute("CREATE TABLE notes (id TEXT, body TEXT)")
        conn.execute("INSERT INTO notes VALUES ('x', ?)", (self.PLAIN,))
        conn.commit()
        conn.close()
        with sqlite3.connect(str(p)) as probe:
            try:
                probe.execute("SELECT data FROM sqlite_dbpage LIMIT 1").fetchall()
            except sqlite3.OperationalError:
                pytest.skip("this SQLite build has no sqlite_dbpage")
        with pytest.raises((sqlite3.DatabaseError, ValueError)):
            db.safe_query("SELECT data FROM sqlite_dbpage", database_path=str(p))


def test_streamable_http_transport_serves_mcp(monkeypatch):
    import src.server as server

    calls = {}
    monkeypatch.setattr(server.mcp, "run", lambda *a, **k: calls.update(args=a, kwargs=k))
    monkeypatch.setattr(sys, "argv", ["msty-admin-mcp", "--transport", "streamable-http", "--port", "8765"])
    server.main()
    assert calls["kwargs"].get("transport") == "streamable-http"
    assert server.mcp.settings.host == "127.0.0.1"
    assert server.mcp.settings.port == 8765
    app = server.mcp.streamable_http_app()
    paths = {getattr(r, "path", None) for r in app.routes}
    assert server.mcp.settings.streamable_http_path in paths


class TestAuthorizerIsTheBoundary:
    """The free-SQL boundary is the SQLite authorizer, not output scrubbing.

    The SQL-text pre-check is switched off here so only the authorizer stands
    between the caller and the secret. Removing the IGNORE rule must fail these.
    """

    PLAIN = "zzDUMMYnotARealKey0000abcd"
    COLUMNS = ["openaiKey", "apiKey", "accessToken", "authHeader", "clientSecret",
               "baseUrl", "config", "args", "metadata"]

    @pytest.fixture(autouse=True)
    def _no_text_precheck(self, monkeypatch):
        monkeypatch.setattr(db, "names_credential_column", lambda _q: False)

    def _db(self, tmp_path: Path, column: str) -> str:
        p = tmp_path / f"{column}.db"
        conn = sqlite3.connect(str(p))
        conn.execute(f'CREATE TABLE t (id TEXT, "{column}" TEXT)')
        conn.execute("INSERT INTO t VALUES ('x', ?)", (self.PLAIN,))
        conn.commit()
        conn.close()
        return str(p)

    def _no_leak(self, rows):
        text = json.dumps(rows, default=str)
        joined = text.replace("|", "").replace('"', "")
        assert self.PLAIN not in joined
        assert self.PLAIN.encode().hex() not in text.lower()
        for i in range(0, len(self.PLAIN) - 6, 7):
            assert self.PLAIN[i:i + 7] not in text

    @pytest.mark.parametrize("column", COLUMNS)
    def test_seven_char_substr_reassembly_reads_null(self, tmp_path: Path, column: str):
        q = (
            "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+7 FROM n WHERE i<40) "
            f'SELECT group_concat(substr("{column}", i, 7), \'|\') AS v FROM t, n'
        )
        rows, _ = db.safe_query(q, database_path=self._db(tmp_path, column))
        self._no_leak(rows)

    @pytest.mark.parametrize("column", COLUMNS)
    @pytest.mark.parametrize("expr", ['hex("{c}")', '"{c}" || \'\'', 'unicode(substr("{c}", 3, 1))', 'length("{c}")'])
    def test_column_is_null_inside_any_expression(self, tmp_path: Path, column: str, expr: str):
        rows, _ = db.safe_query(f"SELECT {expr.format(c=column)} AS v FROM t", database_path=self._db(tmp_path, column))
        assert rows[0]["v"] in (None, "")  # hex(NULL) is the empty string

    @pytest.mark.parametrize("column", COLUMNS + ["api_key", "password", "endpoint", "command"])
    def test_authorizer_ignores_secret_classified_reads(self, column: str):
        assert db._free_sql_authorizer(sqlite3.SQLITE_READ, "t", column, "main", None) == sqlite3.SQLITE_IGNORE

    @pytest.mark.parametrize("column", ["id", "name", "createdAt", "promptTokens", "modelId", "title"])
    def test_ordinary_columns_stay_readable(self, column: str):
        assert db._free_sql_authorizer(sqlite3.SQLITE_READ, "t", column, "main", None) == sqlite3.SQLITE_OK


def test_fetch_all_redacts_cli_flag_values(tmp_path: Path):
    secret = "zzDUMMYnotARealKey0000abcd"
    p = tmp_path / "mcp.db"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE mcpServers (id TEXT, name TEXT, args TEXT)")
    conn.execute("INSERT INTO mcpServers VALUES ('m', 'srv', ?)", (json.dumps(
        ["-y", "some-mcp", "--api-key", secret, f"--token={secret}", "-H", f"Authorization: {secret}"]),))
    conn.commit()
    conn.close()
    rows = db.fetch_all("mcpServers", database_path=str(p))
    text = json.dumps(rows)
    assert secret not in text
    assert "some-mcp" in text and "--api-key" in text


class TestGeneratedColumnsAndRawArgs:
    PLAIN = "zzDUMMYnotARealKey0000abcd"

    @pytest.fixture(autouse=True)
    def _no_text_precheck(self, monkeypatch):
        monkeypatch.setattr(db, "names_credential_column", lambda _q: False)

    def _db(self, tmp_path: Path) -> str:
        p = tmp_path / "gen.db"
        conn = sqlite3.connect(str(p))
        conn.execute(
            "CREATE TABLE t (id TEXT, apiKey TEXT, "
            "v TEXT GENERATED ALWAYS AS (substr(apiKey, 1, 100)) VIRTUAL, "
            "s TEXT GENERATED ALWAYS AS ('x' || apiKey) STORED, "
            "h TEXT GENERATED ALWAYS AS (hex(apiKey)) VIRTUAL)"
        )
        conn.execute("INSERT INTO t (id, apiKey) VALUES ('a', ?)", (self.PLAIN,))
        conn.commit()
        conn.close()
        return str(p)

    @pytest.mark.parametrize("expr", ["v", "s", "h", "substr(v, 3, 7)", "s || ''", "unicode(substr(s, 4, 1))"])
    def test_generated_columns_read_null(self, tmp_path: Path, expr: str):
        rows, _ = db.safe_query(f"SELECT {expr} AS out FROM t", database_path=self._db(tmp_path))
        text = json.dumps(rows)
        assert self.PLAIN[:7] not in text and self.PLAIN.encode().hex()[:14].upper() not in text
        assert rows[0]["out"] in (None, "")

    def test_ordinary_columns_still_readable_next_to_generated(self, tmp_path: Path):
        rows, _ = db.safe_query("SELECT id FROM t", database_path=self._db(tmp_path))
        assert rows == [{"id": "a"}]

    @pytest.mark.parametrize("raw", [
        "npx -y some-mcp --api-key {k}",
        "npx some-mcp --api-key={k}",
        "npx some-mcp --token '{k}'",
        'npx some-mcp -H "Authorization: Bearer {k}"',
        "npx some-mcp --unbalanced 'quote --secret {k}",
        "npx some-mcp --model gpt {k}",
        "npx some-mcp --key-file /x --opt sk-proj-abc123DEF456",
        "npx some-mcp xai-AbC123dEf456GhI789",
        "npx some-mcp ghp_ABCdef1234567890ABCdef12",
    ])
    def test_raw_string_args_redacted(self, tmp_path: Path, raw: str):
        value = raw.format(k=self.PLAIN)
        p = tmp_path / "args.db"
        conn = sqlite3.connect(str(p))
        conn.execute("CREATE TABLE mcpServers (id TEXT, args TEXT)")
        conn.execute("INSERT INTO mcpServers VALUES ('m', ?)", (value,))
        conn.commit()
        conn.close()
        text = json.dumps(db.fetch_all("mcpServers", database_path=str(p)))
        for secret in (self.PLAIN, "sk-proj-abc123DEF456", "xai-AbC123dEf456GhI789", "ghp_ABCdef1234567890ABCdef12"):
            assert secret not in text
        assert "some-mcp" in text

    def test_key_detector_spares_ordinary_arguments(self):
        for ok in ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/projects", "some-mcp",
                   "--port", "8080", "claude-3-5-sonnet-20241022", "localhost:11434"]:
            assert not db._looks_like_key(ok), ok
        for bad in ["sk-proj-abc123DEF456", self.PLAIN, "xai-AbC123dEf456GhI789", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"]:
            assert db._looks_like_key(bad), bad

    @pytest.mark.parametrize("raw", ["npx m --api-key passwordpassword", "npx m --token=passwordpassword",
                                     "npx m --client-secret passwordpassword"])
    def test_low_entropy_value_after_secret_flag_redacted(self, tmp_path: Path, raw: str):
        assert not db._looks_like_key("passwordpassword")
        assert "passwordpassword" not in db._redact_command_line(raw)
