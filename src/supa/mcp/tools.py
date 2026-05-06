"""MCP tool definitions for SuPA circuit data."""

from __future__ import annotations

import json
import uuid

import structlog
from mcp.server.fastmcp import FastMCP

from supa.mcp.port_mapping import PortResolver
from supa.mcp.queries import get_circuit_endpoints_query, get_circuit_query, list_circuits_query

logger = structlog.get_logger(__name__)


def register_tools(mcp: FastMCP, port_resolver: PortResolver) -> None:
    """Register all SuPA read-only tools on the FastMCP instance.

    Args:
        mcp: FastMCP server instance to register tools on.
        port_resolver: Resolver for mapping NRM port_id to device and interface.
    """

    @mcp.tool()
    async def list_circuits(
        reservation_state: str | None = None,
        provision_state: str | None = None,
        lifecycle_state: str | None = None,
        data_plane_state: str | None = None,
    ) -> str:
        """List NSI circuits with optional state filtering. Returns JSON array of circuit summaries.

        Each circuit includes connection_id (UUID), description, global_reservation_id, create_date,
        and four state machine values:

        - reservation_state: RESERVE_START | RESERVE_CHECKING | RESERVE_HELD | RESERVE_COMMITTING
          | RESERVE_FAILED | RESERVE_TIMEOUT | RESERVE_ABORTING
        - provision_state: RELEASED | PROVISIONING | PROVISIONED | RELEASING
        - lifecycle_state: CREATED | FAILED | TERMINATING | PASSED_END_TIME | TERMINATED
        - data_plane_state: DEACTIVATED | AUTO_START | ACTIVATING | ACTIVATED | AUTO_END
          | DEACTIVATING | ACTIVATE_FAILED | DEACTIVATE_FAILED | UNHEALTHY

        Pass any state parameter to filter, e.g. provision_state="PROVISIONED" for active circuits.

        Args:
            reservation_state: Filter by reservation state value.
            provision_state: Filter by provision state value.
            lifecycle_state: Filter by lifecycle state value.
            data_plane_state: Filter by data plane state value.

        Returns:
            JSON array string of circuit summary dicts.
        """
        logger.info(
            "tool called",
            tool="list_circuits",
            reservation_state=reservation_state,
            provision_state=provision_state,
            lifecycle_state=lifecycle_state,
            data_plane_state=data_plane_state,
        )
        try:
            circuits = list_circuits_query(
                reservation_state=reservation_state,
                provision_state=provision_state,
                lifecycle_state=lifecycle_state,
                data_plane_state=data_plane_state,
            )
            logger.info("tool ok", tool="list_circuits", count=len(circuits))
            return json.dumps(circuits, indent=2)
        except Exception as e:
            logger.error("tool error", tool="list_circuits", error=str(e))
            return f"Error listing circuits: {e}"

    @mcp.tool()
    async def get_circuit(connection_id: str) -> str:
        """Get full details for a single NSI circuit by its UUID (connection_id).

        Returns JSON with all four state machine values, bandwidth, schedule (start/end time),
        src_stp_id, dst_stp_id, src_port_id, dst_port_id, src_vlan, dst_vlan,
        and circuit_id (NRM backend identifier, present only after provisioning).

        Use list_circuits first to discover connection_id values.

        Args:
            connection_id: UUID string of the circuit (connection_id from list_circuits).

        Returns:
            JSON object string with circuit details, or error message string.
        """
        logger.info("tool called", tool="get_circuit", connection_id=connection_id)
        try:
            connection_uuid = uuid.UUID(connection_id)
        except ValueError:
            return f"Invalid UUID: {connection_id!r}"

        try:
            circuit = get_circuit_query(connection_uuid)
            if circuit is None:
                return f"Circuit not found: {connection_id}"
            logger.info("tool ok", tool="get_circuit")
            return json.dumps(circuit, indent=2)
        except Exception as e:
            logger.error("tool error", tool="get_circuit", error=str(e))
            return f"Error retrieving circuit: {e}"

    @mcp.tool()
    async def get_circuit_endpoints(connection_id: str) -> str:
        """Get device and interface information for a circuit's source and destination endpoints.

        Returns JSON with src and dst endpoint objects, each containing:

        - port_id: NRM port identifier (always present; pass to an external resolver tool for
          additional device details if a port mapping file is not configured)
        - vlan: selected VLAN integer
        - stp_id: NSI Service Termination Point URN
        - device: router hostname (only if port_mapping_file is configured in supa serve)
        - interface: interface name (only if port_mapping_file is configured in supa serve)

        Also returns circuit_id (NRM backend identifier) and bandwidth_mbps.

        Only available after the reservation is committed (provision_state has been initialized).
        Returns not-found for circuits still in early reservation states.

        Args:
            connection_id: UUID string of the circuit.

        Returns:
            JSON object string with endpoint details, or error message string.
        """
        logger.info("tool called", tool="get_circuit_endpoints", connection_id=connection_id)
        try:
            connection_uuid = uuid.UUID(connection_id)
        except ValueError:
            return f"Invalid UUID: {connection_id!r}"

        try:
            endpoints = get_circuit_endpoints_query(connection_uuid, port_resolver)
            if endpoints is None:
                return (
                    f"Circuit not found or not yet committed: {connection_id}. "
                    "Endpoint data is only available after the reservation is committed."
                )
            logger.info("tool ok", tool="get_circuit_endpoints")
            return json.dumps(endpoints, indent=2)
        except Exception as e:
            logger.error("tool error", tool="get_circuit_endpoints", error=str(e))
            return f"Error retrieving circuit endpoints: {e}"
