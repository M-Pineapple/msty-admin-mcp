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
