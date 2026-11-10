"""Studio 3.x version gate (v6.2.2). Fixtures only, no real Studio data."""

from __future__ import annotations

import asyncio
import json
import plistlib
import sqlite3
from pathlib import Path
from typing import Optional

import pytest

from src import db, paths, writes
from src.paths import (
    LAYOUT_SUPPORTED,
    LAYOUT_UNKNOWN,
    LAYOUT_UNSUPPORTED,
    UnsupportedStudioLayout,
    layout_status,
    parse_version,
)
from tests.test_hybrid import STUDIO_29_SCHEMA

REFUSAL = "Msty Studio 3.x detected"
OLD_REFUSAL = "is older than 2.4"
UNKNOWN_REFUSAL = "Msty Studio version could not be read, so Studio writes are refused"
READ_WARNING = "may be a stale copy if this machine runs Studio 3.x"
MISSING = object()

# Tools that read or write Studio storage. Each must refuse on Studio 3.x.
STUDIO_STORAGE_TOOLS = {
    "read_msty_database": {},
    "list_configured_tools": {},
    "get_model_providers": {},
    "export_tool_config": {"tool_name": "memory"},
    "sync_claude_preferences": {},
    "get_model_performance_metrics": {},
    "get_conversation_patterns": {},
    "optimise_knowledge_stacks": {},
    "suggest_persona_improvements": {},
    "identify_handoff_triggers": {},
    "list_studio_catalogue": {},
    "list_workspaces": {},
    "list_personas": {},
    "list_shadow_personas": {},
    "list_crews": {},
    "list_knowledge_stacks": {},
    "list_turnstiles": {},
    "list_skills": {},
    "list_live_contexts": {},
    "list_prompts": {},
    "list_context_studio": {},
    "list_agent_plans": {},
    "get_studio_entity": {"entity": "personas", "entity_id": "x"},
    "get_schema_migrations": {},
    "export_workflow_pack": {},
    "get_insights_usage": {},
}


def _sqlite(path: Path, schema: str = "CREATE TABLE personas (id TEXT, name TEXT);") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(schema)
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def fake_studio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a fake Studio install. Call with a version string, None for no
    version key, or MISSING for no Info.plist at all."""

    def build(version=MISSING, location: str = "app") -> Path:
        app = tmp_path / ("user-apps" if location == "app_user" else "") / "MstyStudio.app"
        (app / "Contents").mkdir(parents=True, exist_ok=True)
        if version is not MISSING:
            info = {} if version is None else {"CFBundleShortVersionString": version}
            with (app / "Contents" / "Info.plist").open("wb") as fh:
                plistlib.dump(info, fh)
        data = tmp_path / "MstyStudio"
        primary = _sqlite(data / "File System" / "000" / "t" / "00" / "00000000", STUDIO_29_SCHEMA)
        legacy_studio = _sqlite(data / "msty.db")
        legacy = _sqlite(tmp_path / "Msty" / "msty.db")
        fake_paths = {
            "app": app if location == "app" else tmp_path / "missing-system.app",
            "app_user": app if location == "app_user" else tmp_path / "missing-user.app",
            "app_alt": tmp_path / "missing.app",
            "data": data,
            "data_legacy": tmp_path / "Msty",
            "sidecar": tmp_path / "MstySidecar",
            "database": primary,
            "database_legacy": legacy,
            "database_legacy_studio": legacy_studio,
            "config": data / "Gifnoc.nosj",
            "mlx_models": data / "models-mlx",
            "local_models": data / "models",
            "nexus_app": tmp_path / "MstyNexus.app",
            "nexus_data": tmp_path / "MstyNexus",
        }
        monkeypatch.setattr(paths, "get_msty_paths", lambda: fake_paths)
        monkeypatch.setattr(paths, "is_process_running", lambda name: False)
        monkeypatch.setattr(writes, "is_process_running", lambda name: False)
        return primary

    return build


class TestParseVersion:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2.9.12", (2, 9, 12)),
            ("3.0.0", (3, 0, 0)),
            ("3.1.0", (3, 1, 0)),
            ("10.0.0", (10, 0, 0)),
            ("v2.9", (2, 9)),
            ("3.0.0-beta.15", (3, 0, 0)),
            ("garbage", None),
            ("9" * 5000, None),
            ("2.9." + "1" * 7, None),
            ("3." + "0" * 100, None),
            ("", None),
            ("unknown", None),
            (None, None),
        ],
    )
    def test_parse(self, value, expected):
        assert parse_version(value) == expected

    def test_numeric_order_not_lexical(self):
        assert parse_version("10.0.0") > parse_version("2.9.12")
        assert "10.0.0" < "2.9.12"  # the string compare this replaces

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2.4", LAYOUT_SUPPORTED),
            ("2.4.0", LAYOUT_SUPPORTED),
            ("2.9.12", LAYOUT_SUPPORTED),
            ("2.10", LAYOUT_SUPPORTED),
            ("2.3.9", LAYOUT_UNSUPPORTED),
            ("1.5.0", LAYOUT_UNSUPPORTED),
            ("0.9", LAYOUT_UNSUPPORTED),
            ("3.0.0", LAYOUT_UNSUPPORTED),
            ("3.1.0", LAYOUT_UNSUPPORTED),
            ("10.0.0", LAYOUT_UNSUPPORTED),
            ("unknown", LAYOUT_UNKNOWN),
            ("garbage", LAYOUT_UNKNOWN),
            ("9" * 5000, LAYOUT_UNKNOWN),
            (None, LAYOUT_UNKNOWN),
        ],
    )
    def test_layout_status(self, value, expected):
        assert layout_status(value) == expected


class TestDetection:
    def test_2_9_12_resolves_primary_blob(self, fake_studio):
        primary = fake_studio("2.9.12")
        install = paths.detect_msty_installation()
        assert install.version == "2.9.12"
        assert install.layout_status == LAYOUT_SUPPORTED
        assert install.layout == "studio_2x_file_system"
        assert install.database_path == str(primary)

    @pytest.mark.parametrize("version", ["3.0.0", "3.1.0"])
    def test_3x_has_no_database_and_no_fallback(self, fake_studio, version):
        fake_studio(version)
        install = paths.detect_msty_installation()
        assert install.version == version
        assert install.layout_status == LAYOUT_UNSUPPORTED
        assert install.layout == "unsupported_3x"
        # Legacy msty.db files exist in the fixture and must not be used.
        assert install.database_path is None
        assert REFUSAL in install.schema_note
        assert f"version {version}" in install.schema_note

    @pytest.mark.parametrize("version", [MISSING, None, "garbage", "9" * 5000])
    def test_unknown_version_still_reads(self, fake_studio, version):
        primary = fake_studio(version)
        install = paths.detect_msty_installation()
        assert install.layout_status == LAYOUT_UNKNOWN
        assert install.database_path == str(primary)
        assert READ_WARNING in install.schema_note
        assert db.get_database_path() == primary

    @pytest.mark.parametrize("version", ["1.5.0", "2.3.9", "0.9"])
    def test_pre_2_4_has_no_database(self, fake_studio, version):
        fake_studio(version)
        install = paths.detect_msty_installation()
        assert install.layout_status == LAYOUT_UNSUPPORTED
        assert install.layout == "unsupported_pre_2_4"
        assert install.database_path is None
        assert OLD_REFUSAL in install.schema_note
        with pytest.raises(UnsupportedStudioLayout, match=OLD_REFUSAL):
            db.get_database_path()

    def test_user_applications_bundle_is_detected(self, fake_studio):
        fake_studio("3.0.0", location="app_user")
        install = paths.detect_msty_installation()
        assert install.version == "3.0.0"
        assert install.layout_status == LAYOUT_UNSUPPORTED
        assert install.database_path is None

    def test_huge_version_does_not_break_service_ports(self, fake_studio):
        fake_studio("9" * 5000)
        from src.services import current_ports

        assert current_ports()


class TestReadGate:
    @pytest.mark.parametrize("version", ["3.0.0", "3.1.0"])
    def test_db_layer_refuses_even_with_explicit_path(self, fake_studio, version):
        primary = fake_studio(version)
        with pytest.raises(UnsupportedStudioLayout, match=REFUSAL):
            db.get_database_path()
        with pytest.raises(UnsupportedStudioLayout, match=REFUSAL):
            db.get_database_path(str(primary))
        with pytest.raises(UnsupportedStudioLayout, match=REFUSAL):
            db.list_tables()

    def test_2_9_12_reads_unchanged(self, fake_studio):
        fake_studio("2.9.12")
        assert "personas" in db.list_tables()


def _call(name: str, args: dict) -> str:
    from src.server import mcp

    try:
        result = asyncio.run(mcp.call_tool(name, args))
    except Exception as exc:  # FastMCP raises ToolError for tool exceptions
        return str(exc)
    content = result[0] if isinstance(result, tuple) else result
    return " ".join(getattr(block, "text", "") for block in content)


class TestToolsOn3x:
    def test_tool_list_covers_every_storage_tool(self):
        from src.server import mcp

        names = {t.name for t in asyncio.run(mcp.list_tools())}
        assert set(STUDIO_STORAGE_TOOLS) <= names

    @pytest.mark.parametrize("tool", sorted(STUDIO_STORAGE_TOOLS))
    def test_storage_tool_returns_refusal(self, fake_studio, tool):
        fake_studio("3.0.0")
        text = _call(tool, STUDIO_STORAGE_TOOLS[tool])
        assert REFUSAL in text, f"{tool}: {text[:300]}"

    def test_installation_reports_refusal(self, fake_studio):
        fake_studio("3.0.0")
        data = json.loads(_call("get_msty_installation", {}))
        assert data["layout_status"] == LAYOUT_UNSUPPORTED
        assert data["database_path"] is None
        assert REFUSAL in data["schema_note"]

    def test_install_health_reports_refusal(self, fake_studio):
        fake_studio("3.0.0")
        assert REFUSAL in _call("get_status", {"scope": "install"})

    @pytest.mark.parametrize("tool", sorted(STUDIO_STORAGE_TOOLS))
    def test_storage_tool_refused_below_2_4(self, fake_studio, tool):
        fake_studio("1.5.0")
        text = _call(tool, STUDIO_STORAGE_TOOLS[tool])
        assert OLD_REFUSAL in text, f"{tool}: {text[:300]}"

    def test_recommend_model_works_on_3x(self, fake_studio, monkeypatch):
        from tests.test_hybrid import APPLE_36

        monkeypatch.setattr("src.server._hardware_profile", lambda: APPLE_36)
        fake_studio("3.0.0")
        data = json.loads(_call("recommend_model", {}))
        assert data["hardware"]["ram_gb"] == 36.0
        assert REFUSAL in data["usage_note"]

    def test_service_tools_unaffected(self, fake_studio):
        fake_studio("3.0.0")
        server = json.loads(_call("get_status", {"scope": "server"}))
        assert server["studio_target"].startswith("2.4 to 2.9.x")
        behaviours = _call("bloom_list_behaviors", {})
        assert REFUSAL not in behaviours and "Error" not in behaviours
        hardware = _call("get_hardware_profile", {})
        assert REFUSAL not in hardware and "Error" not in hardware


class TestReadWarning:
    @pytest.mark.parametrize("tool", sorted(STUDIO_STORAGE_TOOLS))
    def test_unknown_version_read_carries_warning(self, fake_studio, tool):
        fake_studio(MISSING)
        text = _call(tool, STUDIO_STORAGE_TOOLS[tool])
        assert READ_WARNING in text, f"{tool}: {text[:300]}"

    @pytest.mark.parametrize("tool", ["list_personas", "read_msty_database"])
    def test_supported_version_has_no_warning(self, fake_studio, tool):
        fake_studio("2.9.12")
        text = _call(tool, STUDIO_STORAGE_TOOLS[tool])
        assert READ_WARNING not in text
        assert "warning" not in json.loads(text)


class TestReadme:
    def test_write_conditions_name_version_and_platforms(self):
        readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
        assert readme.count("a detected Studio 2.4 to 2.9.x") >= 4
        assert "On Windows and Linux the Studio version cannot be read yet" in readme


class TestWriteGate:
    def _apply(self, tmp_path: Path, db_path: Optional[Path]):
        return writes.apply_pack(
            writes.persona_pack("Gate Persona", "Be brief.", "llama3.2:3b"),
            confirm=True,
            database_path=str(db_path) if db_path else None,
            imports_root=tmp_path / "imports",
            backup_root=tmp_path / "backups",
        )

    @staticmethod
    def _persona_count(db_path: Path) -> int:
        conn = sqlite3.connect(str(db_path))
        try:
            return conn.execute("SELECT COUNT(*) FROM personas").fetchone()[0]
        finally:
            conn.close()

    @pytest.mark.parametrize(
        "version,needle",
        [
            ("3.0.0", REFUSAL),
            ("3.1.0", REFUSAL),
            ("1.5.0", OLD_REFUSAL),
            ("2.3.9", OLD_REFUSAL),
            ("9" * 5000, UNKNOWN_REFUSAL),
            (MISSING, UNKNOWN_REFUSAL),
            (None, UNKNOWN_REFUSAL),
            ("garbage", UNKNOWN_REFUSAL),
        ],
    )
    def test_write_refused_even_with_explicit_path(
        self, fake_studio, tmp_path, monkeypatch, version, needle
    ):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        fake_studio(version)
        target = _sqlite(tmp_path / "copy" / "00000000", STUDIO_29_SCHEMA)
        for explicit in (target, None):
            result = self._apply(tmp_path, explicit)
            assert result["status"] == "refused"
            assert result["wrote"] is False
            assert needle in result["error"]
            assert Path(result["pack_path"]).is_file()
        assert self._persona_count(target) == 0
        assert not (tmp_path / "backups").exists()

    def test_generate_persona_tool_refused_on_3x(self, fake_studio, monkeypatch, tmp_path):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        monkeypatch.setenv("MSTY_ADMIN_HOME", str(tmp_path / "admin"))
        fake_studio("3.0.0")
        text = _call(
            "generate_persona",
            {"name": "Gate", "system_prompt": "Be brief.", "model": "llama3.2:3b", "confirm": True},
        )
        assert REFUSAL in text
        assert '"wrote": false' in text

    def test_2_9_12_write_still_applies(self, fake_studio, tmp_path, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        fake_studio("2.9.12")
        target = _sqlite(tmp_path / "copy" / "00000000", STUDIO_29_SCHEMA)
        result = self._apply(tmp_path, target)
        assert result["wrote"] is True, result
        assert self._persona_count(target) == 1
