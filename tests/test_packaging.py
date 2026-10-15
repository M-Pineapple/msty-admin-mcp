"""Packaging guards: a fresh install must be able to start the server."""
import importlib
import importlib.metadata as md
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_mcp_sdk_is_1x():
    major = int(md.version("mcp").split(".")[0])
    assert major == 1, f"mcp {md.version('mcp')} installed; this server needs mcp>=1,<2"


def test_fastmcp_importable():
    from mcp.server.fastmcp import FastMCP  # noqa: F401


def test_dependency_pin_excludes_mcp_2():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    mcp = [d for d in deps if d.replace(" ", "").startswith("mcp")]
    assert mcp and "<2" in mcp[0].replace(" ", ""), f"mcp must be pinned below 2: {mcp}"


def test_entry_points_resolve():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    for name, target in scripts.items():
        module, func = target.split(":")
        assert callable(getattr(importlib.import_module(module), func)), name


def test_versions_agree():
    import src
    from src.server import SERVER_VERSION
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert src.__version__ == SERVER_VERSION == project


def _floor(spec: str) -> tuple:
    import re as _re
    m = _re.search(r">=\s*([0-9.]+)", spec)
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def test_dependency_floors_exclude_known_vulnerable_versions():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    deps = data["dependencies"] + [d for ds in data.get("optional-dependencies", {}).values() for d in ds]
    mcp = [d for d in deps if d.replace(" ", "").startswith("mcp>")]
    star = [d for d in deps if d.replace(" ", "").startswith("starlette")]
    assert mcp and _floor(mcp[0]) >= (1, 27, 2), mcp
    assert all(_floor(s) >= (1, 3, 1) for s in star), star
    req = (ROOT / "requirements.txt").read_text()
    for line in req.splitlines():
        if line.replace(" ", "").startswith("mcp>"):
            assert _floor(line) >= (1, 27, 2), line


def test_readme_has_no_third_party_badge_host():
    assert "mseep" not in (ROOT / "README.md").read_text().lower()
