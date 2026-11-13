"""Studio 3.0 support (v6.3.0). Built from schema dumps and gold rows captured on a
disposable Studio 3.0.0 Linux install (tests/fixtures/studio). No real user data."""

from __future__ import annotations

import asyncio
import json
import plistlib
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, Optional

import pytest

from src import db, inventory, paths, studio_storage, writes
from src.paths import LAYOUT_SUPPORTED, LAYOUT_UNKNOWN

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "studio"
GOLD = json.loads((FIXTURES / "studio-gold-rows.json").read_text(encoding="utf-8"))
SEED_TABLES = ("workspaces", "personaFolders", "promptsLibraryFolders", "tools", "toolsets", "toolsToToolsets")
FIXTURE_SECRET = "FIXTURE-"
MISSING = object()


def make_db(
    path: Path,
    version: str = "3.0.0",
    seed: Iterable[str] = SEED_TABLES,
    extra_rows: Optional[Dict[str, list]] = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript((FIXTURES / f"studio-{version}-schema.sql").read_text(encoding="utf-8"))
    rows = {t: list(GOLD[version].get(t, [])) for t in seed}
    for table, extra in (extra_rows or {}).items():
        rows.setdefault(table, []).extend(extra)
    for table, items in rows.items():
        for row in items:
            cols = ", ".join(f'"{c}"' for c in row)
            marks = ", ".join("?" for _ in row)
            conn.execute(f'INSERT INTO "{table}" ({cols}) VALUES ({marks})', list(row.values()))
    conn.commit()
    conn.close()
    return path


def workspace_row(slug: str, name: str, active: bool = False) -> dict:
    return {
        "id": f"ws-{slug}",
        "name": name,
        "slug": slug,
        "colorIcon": None,
        "extras": None,
        "isActive": 1 if active else 0,
        "createdAt": "2026-11-13 17:00:00",
    }


def native(data: Path, slug: str = "default") -> Path:
    return data / "data" / "workspaces" / slug / "msty.cloud.db"


@pytest.fixture()
def studio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fake Studio install. Returns (data_dir, browser_db_path)."""

    def build(version=("3.0.0"), running: bool = False):
        app = tmp_path / "MstyStudio.app"
        (app / "Contents").mkdir(parents=True, exist_ok=True)
        if version is not MISSING:
            with (app / "Contents" / "Info.plist").open("wb") as fh:
                plistlib.dump({"CFBundleShortVersionString": version}, fh)
        data = tmp_path / "MstyStudio"
        data.mkdir(exist_ok=True)
        browser = data / "File System" / "000" / "t" / "00" / "00000000"
        legacy = tmp_path / "Msty" / "msty.db"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(str(legacy)).executescript("CREATE TABLE personas (id TEXT, name TEXT);")
        fake = {
            "app": app,
            "app_user": tmp_path / "missing-user.app",
            "app_alt": None,
            "data": data,
            "data_legacy": tmp_path / "Msty",
            "sidecar": tmp_path / "MstySidecar",
            "database": browser,
            "database_legacy": legacy,
            "database_legacy_studio": data / "msty.db",
            "config": data / "Gifnoc.nosj",
            "mlx_models": data / "models-mlx",
            "local_models": data / "models",
            "nexus_app": None,
            "nexus_data": tmp_path / "MstyNexus",
        }
        monkeypatch.setattr(paths, "get_msty_paths", lambda: fake)
        monkeypatch.setattr(paths, "is_process_running", lambda name: running)
        monkeypatch.setattr(writes, "is_process_running", lambda name: running)
        monkeypatch.setenv("MSTY_ADMIN_HOME", str(tmp_path / "admin"))
        return data, browser

    return build


def _call(name: str, args: dict) -> str:
    from src.server import mcp

    try:
        result = asyncio.run(mcp.call_tool(name, args))
    except Exception as exc:
        return str(exc)
    content = result[0] if isinstance(result, tuple) else result
    return " ".join(getattr(block, "text", "") for block in content)


def _count(path: Path, table: str) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    finally:
        conn.close()


class TestFingerprints:
    @pytest.mark.parametrize("version", ["2.9.12", "3.0.0"])
    def test_fixture_matches_real_release(self, tmp_path, version):
        path = make_db(tmp_path / "w.db", version, seed=())
        fp = studio_storage.fingerprint_path(path)
        assert fp["matches_release"] == version
        assert fp["migration_release"] == version

    def test_write_tables_verified_only_for_3_0_0(self, tmp_path):
        for version, verified in (("3.0.0", True), ("2.9.12", False)):
            conn = sqlite3.connect(str(make_db(tmp_path / f"{version}.db", version, seed=())))
            shape = studio_storage.tables_fingerprint(conn, studio_storage.WRITE_TABLES)
            conn.close()
            assert (shape in studio_storage.VERIFIED_3X_WRITE_FINGERPRINTS) is verified

    def test_changed_column_changes_fingerprint(self, tmp_path):
        path = make_db(tmp_path / "w.db", seed=())
        conn = sqlite3.connect(str(path))
        before = studio_storage.tables_fingerprint(conn, studio_storage.WRITE_TABLES)
        conn.execute("ALTER TABLE personas ADD COLUMN surprise text")
        after = studio_storage.tables_fingerprint(conn, studio_storage.WRITE_TABLES)
        conn.close()
        assert before != after


class TestDiscovery:
    def test_fresh_install_reads_native_home(self, studio):
        data, _ = studio()
        home = make_db(native(data))
        install = paths.detect_msty_installation()
        assert install.layout_status == LAYOUT_SUPPORTED
        assert install.layout == "studio_3x_file_storage"
        assert install.database_path == str(home)
        assert install.active_workspace == "default"
        assert install.schema_fingerprint["matches_release"] == "3.0.0"
        assert db.get_database_path() == home

    def test_upgrade_without_move_reads_browser_storage(self, studio):
        data, browser = studio()
        make_db(browser)
        install = paths.detect_msty_installation()
        assert install.layout == "studio_3x_browser_storage"
        assert install.database_path == str(browser)
        assert install.stale_copies == []

    def test_moved_home_ignores_stale_browser_copy(self, studio):
        data, browser = studio()
        make_db(browser, extra_rows={"personas": [dict(GOLD["3.0.0"]["personas"][0], id="old", name="Stale", activeVersionId=None)]})
        home = make_db(native(data))
        install = paths.detect_msty_installation()
        assert install.database_path == str(home)
        assert [c["path"] for c in install.stale_copies] == [str(browser)]
        text = _call("list_personas", {})
        assert "Stale" not in text
        listed = json.loads(_call("list_workspaces", {}))
        assert listed["storage"]["stale_copies"][0]["path"] == str(browser)

    def test_active_custom_location_workspace(self, studio, tmp_path):
        data, _ = studio()
        make_db(native(data), extra_rows={"workspaces": [workspace_row("work", "Work", active=True)]})
        conn = sqlite3.connect(str(native(data)))
        conn.execute("UPDATE workspaces SET isActive = 0 WHERE slug = 'default'")
        conn.commit()
        conn.close()
        parent = tmp_path / "elsewhere"
        work = make_db(parent / "work" / "msty.cloud.db", seed=("personaFolders",), extra_rows={"personas": [dict(GOLD["3.0.0"]["personas"][0], name="Work Persona", activeVersionId=None)]})
        (data / "data" / "workspace-locations.json").write_text(json.dumps({"work": {"parentPath": str(parent)}}))
        install = paths.detect_msty_installation()
        assert install.active_workspace == "work"
        assert install.database_path == str(work)
        assert "Work Persona" in _call("list_personas", {})
        assert "Work Persona" not in _call("list_personas", {"workspace": "Home"})

    @pytest.mark.parametrize("selector", ["side", "Side Project", "side project", "ws-side"])
    def test_workspace_param_matches_slug_name_or_id(self, studio, selector):
        data, _ = studio()
        make_db(native(data), extra_rows={"workspaces": [workspace_row("side", "Side Project")]})
        make_db(native(data, "side"), seed=("personaFolders",), extra_rows={"personas": [dict(GOLD["3.0.0"]["personas"][0], name="Side Persona", activeVersionId=None)]})
        assert "Side Persona" not in _call("list_personas", {})
        assert "Side Persona" in _call("list_personas", {"workspace": selector})

    def test_unknown_workspace_returns_choices(self, studio):
        data, _ = studio()
        make_db(native(data))
        out = json.loads(_call("list_personas", {"workspace": "nope"}))
        assert "error" in out
        assert out["workspaces"][0]["slug"] == "default"

    def test_browser_workspace_is_unmapped_and_refused(self, studio):
        data, browser = studio()
        make_db(browser, extra_rows={"workspaces": [workspace_row("side", "Side")]})
        layout = paths.storage_layout()
        side = next(w for w in layout.workspaces if w.slug == "side")
        assert side.storage == studio_storage.STORAGE_UNMAPPED
        assert side.database_path is None
        out = json.loads(_call("list_personas", {"workspace": "side"}))
        assert "cannot be read" in out["error"]

    def test_no_workspace_never_falls_back_to_legacy(self, studio):
        studio()
        install = paths.detect_msty_installation()
        assert install.layout == "studio_3x_no_workspace"
        assert install.database_path is None

    def test_unknown_version_with_file_storage_warns_accurately(self, studio):
        data, _ = studio(version=MISSING)
        make_db(native(data))
        install = paths.detect_msty_installation()
        assert install.layout_status == LAYOUT_UNKNOWN
        assert install.layout == "studio_3x_file_storage"
        out = json.loads(_call("list_personas", {}))
        assert "File-based workspace storage was found" in out["warning"]

    def test_locations_file_rejects_relative_and_bad_slugs(self, tmp_path):
        data = tmp_path / "d"
        (data / "data").mkdir(parents=True)
        (data / "data" / "workspace-locations.json").write_text(
            json.dumps({"ok": {"parentPath": str(tmp_path)}, "rel": {"parentPath": "x/y"}, "../up": {"parentPath": str(tmp_path)}, "bad": "str"})
        )
        assert studio_storage.load_workspace_locations(data) == {"ok": tmp_path}


class TestSchemaTolerance:
    def test_missing_column_is_reported_not_fatal(self, studio):
        data, _ = studio()
        home = make_db(native(data))
        conn = sqlite3.connect(str(home))
        conn.execute("ALTER TABLE personas DROP COLUMN description")
        conn.commit()
        conn.close()
        out = json.loads(_call("list_personas", {}))
        assert out["missing_columns"] == ["description"]
        assert "error" not in out

    def test_crew_folders_listed_on_3_0(self, studio):
        data, _ = studio()
        make_db(native(data))
        out = json.loads(_call("list_crews", {}))
        assert out["folders"] == []
        assert "missing_columns" not in out

    def test_crews_on_2_9_have_no_folder_column_complaint(self, tmp_path):
        path = make_db(tmp_path / "w.db", "2.9.12", seed=())
        out = inventory.list_entities("crews", database_path=str(path))
        assert "missing_columns" not in out
        assert inventory.list_entities("crew_folders", database_path=str(path))["count"] == 0


class TestRedaction:
    def test_name_value_pairs(self):
        row = db.redact_row(
            {
                "h": [{"key": "Authorization", "value": "Basic Zm9vOmJhcg=="}],
                "j": json.dumps([{"name": "X-Api-Key", "value": "abc123"}, {"name": "Accept", "value": "text/plain"}]),
                "e": [{"name": "FOO_SECRET", "value": "s3"}, {"name": "PATH", "value": "/usr/bin"}],
                "bearer": "plain-value",
            }
        )
        assert row["h"] == [{"key": "Authorization", "value": "[REDACTED]"}]
        assert json.loads(row["j"]) == [{"name": "X-Api-Key", "value": "[REDACTED]"}, {"name": "Accept", "value": "text/plain"}]
        assert row["e"] == [{"name": "FOO_SECRET", "value": "[REDACTED]"}, {"name": "PATH", "value": "/usr/bin"}]
        assert row["bearer"] == "[REDACTED]"

    def test_real_3_0_tool_configs_never_leak(self, studio):
        data, _ = studio()
        make_db(native(data))
        for tool, args in (("list_configured_tools", {}), ("export_workflow_pack", {}), ("read_msty_database", {"query": "SELECT * FROM tools"})):
            assert FIXTURE_SECRET not in _call(tool, args), tool
        for t in GOLD["3.0.0"]["tools"]:
            assert FIXTURE_SECRET not in _call("export_tool_config", {"tool_name": t["name"]})

    def test_tool_connection_projection(self, studio):
        data, _ = studio()
        make_db(native(data))
        tools = json.loads(_call("list_configured_tools", {}))["tools"]
        by_auth = {t["connection"].get("auth_type"): t["connection"] for t in tools}
        assert set(by_auth) == {"bearer", "oauth", None}
        for conn in by_auth.values():
            assert FIXTURE_SECRET not in json.dumps(conn)
        assert by_auth["bearer"]["header_names"] == ["X-Api-Key"]
        assert by_auth["oauth"]["oauth_status"] == "not_stored_in_workspace"
        assert by_auth[None] == {"transport": "stdio", "env_names": ["FIXTURE_API_KEY"], "has_command": True}

    @pytest.mark.parametrize(
        "config,expected",
        [
            ({"transport": "http", "url": "https://u:p@mcp.example.com/x", "headers": {"X-Api-Key": "v"}, "auth": {"type": "bearer", "token": "t"}},
             {"transport": "http", "url_host": "mcp.example.com", "header_names": ["X-Api-Key"], "auth_type": "bearer"}),
            ({"transport": "http", "url": "https://a.example/m", "auth": {"type": "oauth", "mode": "oauth-dynamic"}},
             {"auth_type": "oauth", "oauth_mode": "oauth-dynamic", "oauth_client_id_set": False}),
            ({"transport": "http", "url": "https://a.example/m"}, {"auth_type": "none"}),
            ({"command": "npx", "args": ["x"], "env": {"API_TOKEN": "v"}}, {"transport": "stdio", "env_names": ["API_TOKEN"], "has_command": True}),
            ({"type": "http", "url": "https://a.example", "headers": [{"key": "Authorization", "value": "v"}]}, {"transport": "http", "header_names": ["Authorization"]}),
            ("not json", {"transport": "unknown"}),
        ],
    )
    def test_projection_shapes(self, config, expected):
        raw = json.dumps(config) if isinstance(config, dict) else config
        out = inventory.tool_connection(raw)
        for key, value in expected.items():
            assert out[key] == value
        dumped = json.dumps(out)
        assert '"v"' not in dumped and '"t"' not in dumped and "u:p" not in dumped


PACK = {
    "personas": [{"name": "Acceptance Persona", "systemPrompt": "Be brief.", "model": ""}],
    "prompts": [{"title": "Acceptance Prompt", "text": "Summarise {{ topic }}."}],
}


class TestWriteGate3:
    def _apply(self, tmp_path, explicit=None, pack=PACK):
        return writes.apply_pack(
            pack,
            confirm=True,
            database_path=str(explicit) if explicit else None,
            imports_root=tmp_path / "imports",
            backup_root=tmp_path / "backups",
        )

    def test_verified_write_matches_studio_gold_rows(self, studio, tmp_path, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        data, _ = studio()
        home = make_db(native(data))
        result = self._apply(tmp_path)
        assert result["wrote"] is True, result
        conn = sqlite3.connect(str(home))
        conn.row_factory = sqlite3.Row
        persona = dict(conn.execute("SELECT * FROM personas").fetchone())
        version = dict(conn.execute("SELECT * FROM personaVersions").fetchone())
        prompt = dict(conn.execute("SELECT * FROM promptsLibraryPrompts").fetchone())
        pversion = dict(conn.execute("SELECT * FROM promptsVersions").fetchone())
        conn.close()
        varying = {"id", "name", "title", "text", "createdAt", "systemPrompt", "description", "activeVersionId", "personaId", "promptId"}
        for mine, gold in ((persona, "personas"), (version, "personaVersions"), (prompt, "promptsLibraryPrompts"), (pversion, "promptsVersions")):
            gold_row = GOLD["3.0.0"][gold][0]
            assert set(mine) == set(gold_row)
            for col, value in gold_row.items():
                if col not in varying:
                    assert mine[col] == value, (gold, col)
        assert json.loads(persona["systemPrompt"]) == {"text": "Be brief.", "mode": "append"}
        assert version["personaId"] == persona["id"] and persona["activeVersionId"] == version["id"]
        assert pversion["promptId"] == prompt["id"] and pversion["id"] != prompt["id"]

    def test_fingerprint_mismatch_refuses(self, studio, tmp_path, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        data, _ = studio()
        home = make_db(native(data))
        conn = sqlite3.connect(str(home))
        conn.execute("ALTER TABLE personas ADD COLUMN newField text")
        conn.commit()
        conn.close()
        result = self._apply(tmp_path)
        assert result["wrote"] is False and "verified schema" in result["error"]
        assert _count(home, "personas") == 0
        assert not (tmp_path / "backups").exists()

    def test_unverified_migration_refuses(self, studio, tmp_path, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        data, _ = studio()
        home = make_db(native(data))
        conn = sqlite3.connect(str(home))
        conn.execute("INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('future', 99999999999999)")
        conn.commit()
        conn.close()
        result = self._apply(tmp_path)
        assert result["wrote"] is False and "unverified latest migration" in result["error"]

    def test_stale_copy_and_other_paths_refuse(self, studio, tmp_path, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        data, browser = studio()
        make_db(browser)
        home = make_db(native(data))
        other = make_db(tmp_path / "other" / "msty.cloud.db")
        stale = self._apply(tmp_path, browser)
        assert stale["wrote"] is False and "stale copy" in stale["error"]
        assert "not it" in self._apply(tmp_path, other)["error"]
        assert _count(browser, "personas") == 0 and _count(other, "personas") == 0
        assert self._apply(tmp_path, home)["wrote"] is True

    def test_running_studio_refuses(self, studio, tmp_path, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        data, _ = studio(running=True)
        home = make_db(native(data))
        result = self._apply(tmp_path)
        assert result["wrote"] is False and "running" in result["error"]
        assert _count(home, "personas") == 0

    def test_read_back_failure_rolls_back_everything(self, studio, tmp_path, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        data, _ = studio()
        home = make_db(native(data))
        conn = sqlite3.connect(str(home))
        # A trigger does not change table shape, so the fingerprint still passes.
        conn.execute(
            "CREATE TRIGGER t AFTER INSERT ON promptsLibraryPrompts BEGIN "
            "UPDATE promptsLibraryPrompts SET source = 'ootb' WHERE id = NEW.id; END"
        )
        conn.commit()
        conn.close()
        result = self._apply(tmp_path)
        assert result["wrote"] is False and "read-back failed" in result["error"]
        assert _count(home, "personas") == 0 and _count(home, "promptsLibraryPrompts") == 0

    def test_unknown_version_still_refuses_writes(self, studio, tmp_path, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        data, _ = studio(version=MISSING)
        home = make_db(native(data))
        result = self._apply(tmp_path)
        assert result["wrote"] is False and "version could not be read" in result["error"]
        assert _count(home, "personas") == 0

    def test_browser_storage_home_is_writable_when_verified(self, studio, tmp_path, monkeypatch):
        monkeypatch.setenv("MSTY_ALLOW_STUDIO_WRITES", "1")
        _, browser = studio()
        make_db(browser)
        assert self._apply(tmp_path)["wrote"] is True
        assert _count(browser, "personas") == 1


class TestSmallFixes:
    def test_linux_and_windows_have_no_empty_app_path(self, monkeypatch):
        for system in ("Linux", "Windows"):
            monkeypatch.setattr(paths.platform, "system", lambda s=system: s)
            got = paths.get_msty_paths()
            assert got["app"] is None and got["nexus_app"] is None

    def test_version_compare_is_numeric(self, studio):
        from src.server import _install_health_payload

        data, browser = studio(version="2.10.0")
        make_db(browser, "2.9.12")
        recs = " ".join(_install_health_payload()["recommendations"])
        assert "older than Knowledge Stacks" not in recs


class TestClaudeSync:
    def test_linux_config_path_and_delta(self, studio, tmp_path, monkeypatch):
        data, _ = studio()
        make_db(native(data))
        monkeypatch.setattr("src.server.platform.system", lambda: "Linux")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        cfg = tmp_path / "xdg" / "Claude" / "claude_desktop_config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"mcpServers": {"Gold HTTP Tool": {}, "only-in-claude": {}}}))
        out = json.loads(_call("sync_claude_preferences", {}))
        assert out["missing_in_msty"] == ["only-in-claude"]
