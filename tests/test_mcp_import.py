# tests/test_mcp_import.py
def test_fastmcp_import() -> None:
    from mcp.server.fastmcp import FastMCP
    assert FastMCP is not None
