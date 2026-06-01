"""FastMCP server wiring for SuPA read-only circuit data."""

from __future__ import annotations

import threading

import structlog
from mcp.server.fastmcp import FastMCP

from supa import settings
from supa.mcp.port_mapping import PortResolver
from supa.mcp.tools import register_tools

logger = structlog.get_logger(__name__)

_INSTRUCTIONS = """You have access to SuPA (SURF ultimate Provider Agent), which manages NSI network
circuit reservations across federated research and education networks.

Available tools:
- list_circuits: List all circuits with optional filtering by state. Use to discover circuit UUIDs.
- get_circuit: Get full details for one circuit by UUID, including all states and endpoint STPs.
- get_circuit_endpoints: Get the NRM port_id, VLAN, device, and interface for both endpoints.

A circuit progresses through four concurrent state machines:
- reservation_state: tracks the NSI reserve/commit/abort lifecycle
- provision_state: tracks whether the circuit is provisioned in the NRM (PROVISIONED = active)
- lifecycle_state: tracks the overall connection lifecycle (TERMINATED = done)
- data_plane_state: tracks whether traffic is flowing (ACTIVATED = traffic active)

The most useful filter for finding active circuits is provision_state="PROVISIONED".
"""


def create_server() -> FastMCP:
    """Create and configure the FastMCP server instance from global settings. Does not start it."""
    port_resolver = PortResolver(settings.mcp_port_mapping_file)

    mcp = FastMCP(
        "supa-mcp",
        instructions=_INSTRUCTIONS,
        host=settings.mcp_host,
        port=settings.mcp_port,
    )

    register_tools(mcp, port_resolver)

    return mcp


def start_mcp_background() -> None:
    """Start the MCP server in a background daemon thread alongside supa serve.

    The thread is daemon so it exits automatically when the main process exits.
    """
    mcp = create_server()
    logger.info(
        "starting mcp server in background thread",
        host=settings.mcp_host,
        port=settings.mcp_port,
        port_mapping_file=str(settings.mcp_port_mapping_file),
    )
    thread = threading.Thread(
        target=mcp.run,
        kwargs={"transport": "streamable-http"},
        daemon=True,
        name="supa-mcp",
    )
    thread.start()


def run_server() -> None:
    """Initialize SuPA DB and run the MCP server in the foreground."""
    from supa import init_app

    logger.info(
        "starting supa mcp server",
        host=settings.mcp_host,
        port=settings.mcp_port,
    )
    init_app(with_scheduler=False)
    mcp = create_server()
    mcp.run(transport="streamable-http")
