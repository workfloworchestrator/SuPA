"""Tests for MCP tool definitions."""

from __future__ import annotations

import json
import uuid
from typing import Any, Generator
from unittest.mock import PropertyMock, patch

import pytest
from mcp.server.fastmcp import Context, FastMCP

from supa.mcp.port_mapping import PortResolver
from supa.mcp.tools import register_tools

TEST_REQUEST_ID = "test-request-id-42"


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


@pytest.fixture(autouse=True)
def fake_request_context() -> Generator[None, None, None]:
    """Provide a stable ``ctx.request_id`` to tool invocations during tests.

    FastMCP.call_tool does not bind a request context outside a live transport,
    so ``Context.request_id`` raises by default. Patching the property keeps the
    tools' ``logger.bind(request_id=ctx.request_id)`` working under the same
    public entry point real clients use.
    """
    with patch.object(Context, "request_id", new_callable=PropertyMock, return_value=TEST_REQUEST_ID):
        yield


@pytest.fixture
def mcp_with_tools() -> FastMCP:
    """FastMCP instance with all SuPA tools registered."""
    mcp = make_mcp()
    register_tools(mcp, PortResolver(None))
    return mcp


# Success paths: each tool returns a different JSON shape, so each gets its own test.


@pytest.mark.anyio
async def test_list_circuits_returns_json_list(mcp_with_tools: FastMCP) -> None:
    """list_circuits returns a JSON array of circuit summaries."""
    circuits = [{"connection_id": str(uuid.uuid4()), "reservation_state": "RESERVE_HELD"}]
    with patch("supa.mcp.tools.list_circuits_query", return_value=circuits):
        result = await call_tool(mcp_with_tools, "list_circuits")
    data = json.loads(result)
    assert isinstance(data, list)
    assert data[0]["reservation_state"] == "RESERVE_HELD"


@pytest.mark.anyio
async def test_get_circuit_returns_json_dict(mcp_with_tools: FastMCP) -> None:
    """get_circuit returns a JSON dict for a found circuit."""
    cid = str(uuid.uuid4())
    circuit = {"connection_id": cid, "reservation_state": "RESERVE_HELD"}
    with patch("supa.mcp.tools.get_circuit_query", return_value=circuit):
        result = await call_tool(mcp_with_tools, "get_circuit", connection_id=cid)
    data = json.loads(result)
    assert data["connection_id"] == cid


@pytest.mark.anyio
async def test_get_circuit_endpoints_returns_json_dict(mcp_with_tools: FastMCP) -> None:
    """get_circuit_endpoints returns a JSON dict with src and dst endpoint info."""
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


# Error paths share identical structure across tools, so they are parametrized.


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool,query_func,kwargs",
    [
        pytest.param("list_circuits", "list_circuits_query", {}, id="list_circuits"),
        pytest.param(
            "get_circuit",
            "get_circuit_query",
            {"connection_id": "11111111-1111-1111-1111-111111111111"},
            id="get_circuit",
        ),
        pytest.param(
            "get_circuit_endpoints",
            "get_circuit_endpoints_query",
            {"connection_id": "11111111-1111-1111-1111-111111111111"},
            id="get_circuit_endpoints",
        ),
    ],
)
async def test_query_exception_returns_generic_error(
    mcp_with_tools: FastMCP, tool: str, query_func: str, kwargs: dict[str, str]
) -> None:
    """Returns a generic error with correlation id; never leaks the raw exception text."""
    with patch(f"supa.mcp.tools.{query_func}", side_effect=Exception("schema.table leak")):
        result = await call_tool(mcp_with_tools, tool, **kwargs)
    assert "Internal error" in result
    assert "correlation_id=" in result
    assert "schema.table leak" not in result


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool,query_func",
    [
        pytest.param("get_circuit", "get_circuit_query", id="get_circuit"),
        pytest.param("get_circuit_endpoints", "get_circuit_endpoints_query", id="get_circuit_endpoints"),
    ],
)
async def test_returns_not_found_message_when_query_returns_none(
    mcp_with_tools: FastMCP, tool: str, query_func: str
) -> None:
    """Returns 'not found' message when the query function yields None."""
    cid = str(uuid.uuid4())
    with patch(f"supa.mcp.tools.{query_func}", return_value=None):
        result = await call_tool(mcp_with_tools, tool, connection_id=cid)
    assert "not found" in result.lower()


@pytest.mark.anyio
@pytest.mark.parametrize("tool", ["get_circuit", "get_circuit_endpoints"])
async def test_invalid_uuid_returns_invalid_uuid_message(mcp_with_tools: FastMCP, tool: str) -> None:
    """Returns 'Invalid UUID' for a malformed connection_id string."""
    result = await call_tool(mcp_with_tools, tool, connection_id="not-a-uuid")
    assert "Invalid UUID" in result


# Logging behaviour: tool-name-as-event, duration_ms on every completion,
# unset filters omitted from the called event, ports_resolved counted from the resolver output.


@pytest.mark.anyio
async def test_list_circuits_called_event_omits_unset_filters(mcp_with_tools: FastMCP) -> None:
    """list_circuits called event carries only the filters that were supplied."""
    import structlog.testing

    with patch("supa.mcp.tools.list_circuits_query", return_value=[]):
        with structlog.testing.capture_logs() as logs:
            await call_tool(mcp_with_tools, "list_circuits", provision_state="PROVISIONED")
    called = next(entry for entry in logs if entry["event"] == "list_circuits called")
    assert called["provision_state"] == "PROVISIONED"
    assert "reservation_state" not in called
    assert "lifecycle_state" not in called
    assert "data_plane_state" not in called


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool,query_func,kwargs,query_return,expected_event",
    [
        pytest.param("list_circuits", "list_circuits_query", {}, [], "list_circuits completed", id="list_circuits"),
        pytest.param(
            "get_circuit",
            "get_circuit_query",
            {"connection_id": "11111111-1111-1111-1111-111111111111"},
            {"connection_id": "11111111-1111-1111-1111-111111111111"},
            "get_circuit completed",
            id="get_circuit",
        ),
        pytest.param(
            "get_circuit_endpoints",
            "get_circuit_endpoints_query",
            {"connection_id": "11111111-1111-1111-1111-111111111111"},
            {"src": {"port_id": "a"}, "dst": {"port_id": "b"}},
            "get_circuit_endpoints completed",
            id="get_circuit_endpoints",
        ),
    ],
)
async def test_completion_event_includes_duration_ms(
    mcp_with_tools: FastMCP,
    tool: str,
    query_func: str,
    kwargs: dict[str, str],
    query_return: object,
    expected_event: str,
) -> None:
    """Every tool emits a completion event carrying duration_ms."""
    import structlog.testing

    with patch(f"supa.mcp.tools.{query_func}", return_value=query_return):
        with structlog.testing.capture_logs() as logs:
            await call_tool(mcp_with_tools, tool, **kwargs)
    completed = next(entry for entry in logs if entry["event"] == expected_event)
    assert isinstance(completed["duration_ms"], (int, float))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "src,dst,expected",
    [
        pytest.param({"port_id": "a"}, {"port_id": "b"}, 0, id="neither_mapped"),
        pytest.param({"port_id": "a", "device": "r1", "interface": "et-0"}, {"port_id": "b"}, 1, id="src_mapped"),
        pytest.param(
            {"port_id": "a", "device": "r1", "interface": "et-0"},
            {"port_id": "b", "device": "r2", "interface": "et-1"},
            2,
            id="both_mapped",
        ),
    ],
)
async def test_get_circuit_endpoints_completed_ports_resolved_count(
    mcp_with_tools: FastMCP, src: dict[str, str], dst: dict[str, str], expected: int
) -> None:
    """get_circuit_endpoints completion event reports how many endpoints carry device info."""
    import structlog.testing

    cid = "11111111-1111-1111-1111-111111111111"
    endpoints = {"connection_id": cid, "src": src, "dst": dst}
    with patch("supa.mcp.tools.get_circuit_endpoints_query", return_value=endpoints):
        with structlog.testing.capture_logs() as logs:
            await call_tool(mcp_with_tools, "get_circuit_endpoints", connection_id=cid)
    completed = next(entry for entry in logs if entry["event"] == "get_circuit_endpoints completed")
    assert completed["ports_resolved"] == expected


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool,query_func,kwargs,event",
    [
        pytest.param(
            "get_circuit",
            "get_circuit_query",
            {"connection_id": "11111111-1111-1111-1111-111111111111"},
            "get_circuit not_found",
            id="get_circuit",
        ),
        pytest.param(
            "get_circuit_endpoints",
            "get_circuit_endpoints_query",
            {"connection_id": "11111111-1111-1111-1111-111111111111"},
            "get_circuit_endpoints not_found",
            id="get_circuit_endpoints",
        ),
    ],
)
async def test_not_found_logs_distinct_event(
    mcp_with_tools: FastMCP, tool: str, query_func: str, kwargs: dict[str, str], event: str
) -> None:
    """Per-uuid tools emit a not_found event (distinct from completed) when the query returns None."""
    import structlog.testing

    with patch(f"supa.mcp.tools.{query_func}", return_value=None):
        with structlog.testing.capture_logs() as logs:
            await call_tool(mcp_with_tools, tool, **kwargs)
    assert any(entry["event"] == event for entry in logs)


@pytest.mark.anyio
@pytest.mark.parametrize("tool", ["get_circuit", "get_circuit_endpoints"])
async def test_invalid_uuid_logs_distinct_event(mcp_with_tools: FastMCP, tool: str) -> None:
    """Per-uuid tools emit a tool-specific invalid_uuid event so silent client errors are visible."""
    import structlog.testing

    with structlog.testing.capture_logs() as logs:
        await call_tool(mcp_with_tools, tool, connection_id="not-a-uuid")
    assert any(entry["event"] == f"{tool} invalid_uuid" for entry in logs)


# request_id correlation: every tool-emitted log entry carries the JSON-RPC request id
# from the FastMCP Context, so an operator can grep one identifier and find every line
# the tool produced for a given call.


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool,query_func,kwargs,query_return,events",
    [
        pytest.param(
            "list_circuits",
            "list_circuits_query",
            {},
            [],
            ["list_circuits called", "list_circuits completed"],
            id="list_circuits",
        ),
        pytest.param(
            "get_circuit",
            "get_circuit_query",
            {"connection_id": "11111111-1111-1111-1111-111111111111"},
            {"connection_id": "11111111-1111-1111-1111-111111111111"},
            ["get_circuit called", "get_circuit completed"],
            id="get_circuit",
        ),
        pytest.param(
            "get_circuit_endpoints",
            "get_circuit_endpoints_query",
            {"connection_id": "11111111-1111-1111-1111-111111111111"},
            {"src": {"port_id": "a"}, "dst": {"port_id": "b"}},
            ["get_circuit_endpoints called", "get_circuit_endpoints completed"],
            id="get_circuit_endpoints",
        ),
    ],
)
async def test_tool_log_entries_carry_request_id(
    mcp_with_tools: FastMCP,
    tool: str,
    query_func: str,
    kwargs: dict[str, str],
    query_return: object,
    events: list[str],
) -> None:
    """Every log entry emitted by the tool carries request_id from the Context."""
    import structlog.testing

    with patch(f"supa.mcp.tools.{query_func}", return_value=query_return):
        with structlog.testing.capture_logs() as logs:
            await call_tool(mcp_with_tools, tool, **kwargs)
    matching = [entry for entry in logs if entry["event"] in events]
    assert matching, f"expected at least one of {events} in {[e['event'] for e in logs]}"
    assert all(entry.get("request_id") == TEST_REQUEST_ID for entry in matching)
