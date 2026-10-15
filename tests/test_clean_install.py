"""Clean-install findings: calibration column, initialize version, entity aliases."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import importlib.metadata as md

from src import db
from src.inventory import list_entities, resolve_entity_key
from src.phase4_5_tools import fetch_calibration_history, table_order_column
from src.server import SERVER_VERSION, get_calibration_history, get_studio_entity, mcp
from src.version import package_version


def _metrics_db(tmp_path: Path, time_column: str) -> Path:
    path = tmp_path / "msty_admin_metrics.db"
    conn = sqlite3.connect(str(path))
    conn.execute(
        f"""
        CREATE TABLE calibration_tests (
            id INTEGER PRIMARY KEY,
            test_id TEXT UNIQUE,
            model_id TEXT NOT NULL,
            prompt_category TEXT,
            prompt TEXT,
            quality_score REAL,
            {time_column} DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "INSERT INTO calibration_tests (test_id, model_id, prompt_category, prompt, quality_score) "
        "VALUES ('t1', 'dummy-model', 'reasoning', '2+2?', 0.9)"
    )
    conn.execute(
        "INSERT INTO calibration_tests (test_id, model_id, prompt_category, prompt, quality_score) "
        "VALUES ('t2', 'other-model', 'coding', 'sum?', 0.5)"
    )
    conn.commit()
    conn.close()
    return path


def test_package_version_matches_pyproject():
    assert package_version() == SERVER_VERSION
    assert SERVER_VERSION == md.version("msty-admin-mcp")


def test_initialize_reports_package_version_not_sdk():
    assert mcp._mcp_server.version == SERVER_VERSION
    options = mcp._mcp_server.create_initialization_options()
    assert options.server_version == SERVER_VERSION
    assert options.server_version != md.version("mcp")


def test_calibration_history_uses_timestamp_column(tmp_path: Path, monkeypatch):
    db_path = _metrics_db(tmp_path, "timestamp")
    monkeypatch.setattr(
        "src.phase4_5_tools.get_metrics_db_path", lambda: db_path
    )
    conn = sqlite3.connect(str(db_path))
    assert table_order_column(conn, "calibration_tests") == "timestamp"
    conn.close()

    payload = fetch_calibration_history(limit=10)
    assert "error" not in payload
    assert payload["ordered_by"] == "timestamp"
    assert payload["history"][0]["model_id"] == "dummy-model"

    tool = json.loads(get_calibration_history(limit=10))
    assert "error" not in tool
    assert len(tool["history"]) == 2


def test_calibration_history_model_id_on_timestamp_only_table(
    tmp_path: Path, monkeypatch
):
    """Exact clean-install bug: WHERE model_id plus ORDER BY timestamp, not created_at."""
    db_path = _metrics_db(tmp_path, "timestamp")
    monkeypatch.setattr(
        "src.phase4_5_tools.get_metrics_db_path", lambda: db_path
    )
    conn = sqlite3.connect(str(db_path))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(calibration_tests)")}
    conn.close()
    assert "timestamp" in cols
    assert "created_at" not in cols

    payload = fetch_calibration_history(model_id="dummy-model", limit=5)
    assert "error" not in payload
    assert payload["ordered_by"] == "timestamp"
    assert [row["model_id"] for row in payload["history"]] == ["dummy-model"]
    assert payload["history"][0]["test_id"] == "t1"

    tool = json.loads(get_calibration_history(model_id="dummy-model", limit=5))
    assert "error" not in tool
    assert tool["ordered_by"] == "timestamp"
    assert len(tool["history"]) == 1
    assert tool["history"][0]["model_id"] == "dummy-model"


def test_calibration_history_detects_created_at(tmp_path: Path, monkeypatch):
    db_path = _metrics_db(tmp_path, "created_at")
    monkeypatch.setattr(
        "src.phase4_5_tools.get_metrics_db_path", lambda: db_path
    )
    payload = fetch_calibration_history(model_id="dummy-model", limit=5)
    assert "error" not in payload
    assert payload["ordered_by"] == "created_at"
    assert payload["history"][0]["test_id"] == "t1"


def test_studio_entity_accepts_singular_persona(tmp_path: Path, monkeypatch):
    studio = tmp_path / "00000000"
    conn = sqlite3.connect(str(studio))
    conn.execute(
        "CREATE TABLE personas (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "systemPrompt TEXT NOT NULL, createdAt TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO personas (id, name, systemPrompt) VALUES ('p1', 'Tester', 'Be thorough.')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "get_database_path", lambda explicit=None: studio)

    assert resolve_entity_key("persona") == "personas"
    assert resolve_entity_key("crew") == "crews"
    assert resolve_entity_key("knowledge-stack") == "knowledge_stacks"
    assert resolve_entity_key("personas") == "personas"

    data = json.loads(get_studio_entity("persona", "p1"))
    assert "error" not in data
    assert data["entity"] == "personas"
    assert data["found"] is True
    assert data["item"]["name"] == "Tester"


def test_list_entities_accepts_singular_persona(tmp_path: Path, monkeypatch):
    studio = tmp_path / "00000000"
    conn = sqlite3.connect(str(studio))
    conn.execute(
        "CREATE TABLE personas (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "systemPrompt TEXT NOT NULL, createdAt TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO personas (id, name, systemPrompt) VALUES ('p1', 'Tester', 'Be thorough.')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "get_database_path", lambda explicit=None: studio)

    listed = list_entities("persona", limit=10)
    assert "error" not in listed
    assert listed["entity"] == "personas"
    assert listed["count"] == 1
    assert listed["items"][0]["name"] == "Tester"

    unknown = list_entities("not-an-entity")
    assert "error" in unknown
    assert "persona" in unknown["aliases"]
