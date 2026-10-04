"""One-tool MCP server for a local model.

The full admin server exposes the Studio catalogue. A small model will call
those tools at random. This process exposes only ``ask_frontier``.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from src.frontier import ask_cursor_agent

mcp = FastMCP("msty-frontier", "v6.1.0")


@mcp.tool()
def ask_frontier(question: str) -> str:
    """Answer a hard question. Call once, then stop."""
    try:
        return ask_cursor_agent(question).answer
    except Exception as exc:
        return f"Frontier handoff failed: {exc}"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
