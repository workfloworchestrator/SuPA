"""Smoke test to verify the MCP SDK is importable."""

from mcp.server.fastmcp import FastMCP


def test_fastmcp_import() -> None:
    """Verify FastMCP can be imported from the mcp SDK."""
    assert FastMCP is not None
