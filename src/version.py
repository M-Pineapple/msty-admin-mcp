"""Single package version, read from install metadata or pyproject.toml."""

from __future__ import annotations

from pathlib import Path


def package_version() -> str:
    """Return the msty-admin-mcp version.

    Installed wheels use importlib.metadata. A source checkout that is not
    installed yet reads ``version`` from pyproject.toml so FastMCP initialize
    and ``get_server_status`` stay in lock-step without a second literal.
    """
    try:
        from importlib.metadata import version

        return version("msty-admin-mcp")
    except Exception:
        pass

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("version") and "=" in stripped:
            return stripped.split("=", 1)[1].strip().strip("'\"")
    raise RuntimeError("Could not determine msty-admin-mcp version")


__version__ = package_version()
