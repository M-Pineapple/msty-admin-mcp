"""One-tool MCP server for a local model.

The full admin server exposes the Studio catalogue. A small model will call
those tools at random. This process exposes only ``ask_frontier``.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from typing import Optional

from src.frontier import ask_frontier as dispatch_frontier
from src.version import __version__ as SERVER_VERSION

mcp = FastMCP("msty-frontier", f"v{SERVER_VERSION}")
mcp._mcp_server.version = SERVER_VERSION


@mcp.tool()
def ask_frontier(question: str, provider: Optional[str] = None, fresh: bool = False) -> str:
    """Answer a hard question via Cursor (default), Grok, or Claude. Call once, then stop."""
    try:
        return dispatch_frontier(question, provider=provider, fresh=fresh).answer
    except Exception as exc:
        return f"Frontier handoff failed: {exc}"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
