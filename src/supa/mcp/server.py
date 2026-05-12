"""FastMCP server wiring for SuPA read-only circuit data."""

from __future__ import annotations

import threading

import structlog
from mcp.server.fastmcp import FastMCP

from supa.mcp.config import McpSettings
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


def create_server(mcp_settings: McpSettings) -> FastMCP:
    """Create and configure the FastMCP server instance. Does not start it.

    Args:
        mcp_settings: MCP server configuration (host, port, port_mapping_file).

    Returns:
        Configured FastMCP instance with all SuPA tools registered.
    """
    port_resolver = PortResolver(mcp_settings.port_mapping_file)

    mcp = FastMCP(
        "supa-mcp",
        instructions=_INSTRUCTIONS,
        host=mcp_settings.host,
        port=mcp_settings.port,
    )

    register_tools(mcp, port_resolver)

    return mcp


def start_mcp_background(mcp_settings: McpSettings) -> None:
    """Start the MCP server in a background daemon thread alongside supa serve.

    The thread is daemon so it exits automatically when the main process exits.
    No explicit shutdown is needed — supa serve's signal handling terminates the process.

    Args:
        mcp_settings: MCP server configuration.
    """
    mcp = create_server(mcp_settings)
    logger.info(
        "starting mcp server in background thread",
        host=mcp_settings.host,
        port=mcp_settings.port,
        port_mapping_file=str(mcp_settings.port_mapping_file),
    )
    thread = threading.Thread(
        target=mcp.run,
        kwargs={"transport": "streamable-http"},
        daemon=True,
        name="supa-mcp",
    )
    thread.start()


def run_server(mcp_settings: McpSettings) -> None:
    """Initialize SuPA DB and run the MCP server in the foreground.

    This is the development/standalone entrypoint. For production, use
    start_mcp_background() inside supa serve.

    Args:
        mcp_settings: MCP server configuration.
    """
    from supa import init_app

    logger.info(
        "starting supa mcp server",
        host=mcp_settings.host,
        port=mcp_settings.port,
    )
    init_app(with_scheduler=False)
    mcp = create_server(mcp_settings)
    mcp.run(transport="streamable-http")
