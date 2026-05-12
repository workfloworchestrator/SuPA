"""Tests for MCP tool definitions."""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import patch

import pytest
from mcp.server.fastmcp import FastMCP

from supa.mcp.port_mapping import PortResolver
from supa.mcp.tools import register_tools


def make_mcp() -> FastMCP:
    """Create a minimal FastMCP instance for testing."""
    return FastMCP("test-supa")


async def call_tool(mcp: FastMCP, name: str, **kwargs: object) -> str:
    """Call a named tool on the FastMCP instance and return the text result.

    FastMCP.call_tool returns a (list[ContentBlock], dict) tuple at runtime.
    The stub types it as Sequence[ContentBlock] | dict, so we capture as Any.
    """
    from mcp.types import TextContent

    raw: Any = await mcp.call_tool(name, kwargs)
    contents, _meta = raw
    block = contents[0]
    assert isinstance(block, TextContent)
    return block.text


@pytest.fixture
def mcp_with_tools() -> FastMCP:
    """FastMCP instance with all SuPA tools registered."""
    mcp = make_mcp()
    register_tools(mcp, PortResolver(None))
    return mcp


class TestListCircuitsTool:
    """Tests for the list_circuits MCP tool."""

    @pytest.mark.anyio
    async def test_returns_json_list(self, mcp_with_tools: FastMCP) -> None:
        """Returns JSON array of circuit summaries."""
        circuits = [{"connection_id": str(uuid.uuid4()), "reservation_state": "RESERVE_HELD"}]
        with patch("supa.mcp.tools.list_circuits_query", return_value=circuits):
            result = await call_tool(mcp_with_tools, "list_circuits")
        data = json.loads(result)
        assert isinstance(data, list)
        assert data[0]["reservation_state"] == "RESERVE_HELD"

    @pytest.mark.anyio
    async def test_returns_error_string_on_exception(self, mcp_with_tools: FastMCP) -> None:
        """Returns error string (not exception) on DB failure."""
        with patch("supa.mcp.tools.list_circuits_query", side_effect=Exception("db error")):
            result = await call_tool(mcp_with_tools, "list_circuits")
        assert "Error" in result
        assert "db error" in result


class TestGetCircuitTool:
    """Tests for the get_circuit MCP tool."""

    @pytest.mark.anyio
    async def test_returns_circuit_json(self, mcp_with_tools: FastMCP) -> None:
        """Returns JSON dict for a found circuit."""
        cid = str(uuid.uuid4())
        circuit = {"connection_id": cid, "reservation_state": "RESERVE_HELD"}
        with patch("supa.mcp.tools.get_circuit_query", return_value=circuit):
            result = await call_tool(mcp_with_tools, "get_circuit", connection_id=cid)
        data = json.loads(result)
        assert data["connection_id"] == cid

    @pytest.mark.anyio
    async def test_returns_not_found_for_missing_circuit(self, mcp_with_tools: FastMCP) -> None:
        """Returns 'not found' message when circuit UUID doesn't exist."""
        cid = str(uuid.uuid4())
        with patch("supa.mcp.tools.get_circuit_query", return_value=None):
            result = await call_tool(mcp_with_tools, "get_circuit", connection_id=cid)
        assert "not found" in result.lower()

    @pytest.mark.anyio
    async def test_returns_error_for_invalid_uuid(self, mcp_with_tools: FastMCP) -> None:
        """Returns 'Invalid UUID' message for malformed UUID string."""
        result = await call_tool(mcp_with_tools, "get_circuit", connection_id="not-a-uuid")
        assert "Invalid UUID" in result


class TestGetCircuitEndpointsTool:
    """Tests for the get_circuit_endpoints MCP tool."""

    @pytest.mark.anyio
    async def test_returns_endpoints_json(self, mcp_with_tools: FastMCP) -> None:
        """Returns JSON dict with src and dst endpoint info."""
        cid = str(uuid.uuid4())
        endpoints = {
            "connection_id": cid,
            "circuit_id": "sub-xyz",
            "bandwidth_mbps": 1000,
            "src": {"port_id": "port-a1", "vlan": 100},
            "dst": {"port_id": "port-b2", "vlan": 200},
        }
        with patch("supa.mcp.tools.get_circuit_endpoints_query", return_value=endpoints):
            result = await call_tool(mcp_with_tools, "get_circuit_endpoints", connection_id=cid)
        data = json.loads(result)
        assert data["src"]["port_id"] == "port-a1"

    @pytest.mark.anyio
    async def test_returns_not_found_for_pre_commit_circuit(self, mcp_with_tools: FastMCP) -> None:
        """Returns 'not found' message when Connection row doesn't exist yet."""
        cid = str(uuid.uuid4())
        with patch("supa.mcp.tools.get_circuit_endpoints_query", return_value=None):
            result = await call_tool(mcp_with_tools, "get_circuit_endpoints", connection_id=cid)
        assert "not found" in result.lower()
