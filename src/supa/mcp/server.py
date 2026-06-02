"""FastMCP server wiring for SuPA read-only circuit data."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import structlog
import uvicorn
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

_uvicorn_server: uvicorn.Server | None = None


def create_server() -> FastMCP:
    """Create and configure the FastMCP server instance from global settings. Does not start it."""
    port_resolver = PortResolver(settings.mcp_port_mapping_file)

    mcp = FastMCP(
        "supa-mcp",
        instructions=_INSTRUCTIONS,
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level=settings.mcp_log_level,
    )

    register_tools(mcp, port_resolver)

    return mcp


def _serve() -> None:
    """Run the uvicorn server in a fresh event loop. Called by the APScheduler date job."""
    assert _uvicorn_server is not None
    asyncio.run(_uvicorn_server.serve())


def start_mcp() -> None:
    """Schedule the MCP server as a one-shot APScheduler job.

    Running under APScheduler means uncaught errors surface through the existing
    ``EVENT_JOB_ERROR`` listener instead of dying silently in a daemon thread,
    and shutdown can be coordinated via :func:`stop_mcp`.

    Caveat: the job runs ``uvicorn.Server.serve()`` which blocks for the lifetime
    of the MCP server, so it permanently occupies one ``scheduler_max_workers``
    slot.
    """
    from supa import scheduler

    mcp = create_server()
    config = uvicorn.Config(
        mcp.streamable_http_app(),
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level=settings.mcp_log_level.lower(),
        log_config=None,
    )
    # Quiet per-request access lines (`POST /mcp HTTP/1.1 200 OK`) without losing
    # warnings/errors from the same logger.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    global _uvicorn_server
    _uvicorn_server = uvicorn.Server(config)

    logger.info(
        "scheduling mcp server",
        host=settings.mcp_host,
        port=settings.mcp_port,
        port_mapping_file=str(settings.mcp_port_mapping_file),
    )
    scheduler.add_job(
        func=_serve,
        trigger="date",
        run_date=datetime.now(timezone.utc),
        id="supa-mcp",
        replace_existing=True,
    )


def stop_mcp() -> None:
    """Signal the running MCP server to exit its serve loop.

    Setting ``should_exit`` causes uvicorn to drop out of the accept loop and
    finish in-flight requests, after which the APScheduler job returns and
    ``scheduler.shutdown(wait=True)`` can complete cleanly.
    """
    if _uvicorn_server is not None:
        logger.info("stopping mcp server")
        _uvicorn_server.should_exit = True
