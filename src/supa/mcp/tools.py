"""MCP tool definitions for SuPA circuit data."""

from __future__ import annotations

import json
import time
import uuid

import structlog
from mcp.server.fastmcp import Context, FastMCP

from supa.mcp.port_mapping import PortResolver
from supa.mcp.queries import get_circuit_endpoints_query, get_circuit_query, list_circuits_query

logger = structlog.get_logger(__name__)


def _internal_error(operation: str) -> tuple[str, str]:
    """Return a generic error message and the correlation id used to find it in the logs.

    Internal exception messages (SQLAlchemy errors, file paths, stack frames) must
    never reach the MCP client. The correlation id is the only handle the operator
    has to tie the client-visible message back to the structlog entry.
    """
    correlation_id = uuid.uuid4().hex[:12]
    return f"Internal error {operation} (correlation_id={correlation_id})", correlation_id


def _elapsed_ms(start: float) -> float:
    """Wall-clock duration in milliseconds since ``start`` (a ``time.perf_counter()`` value)."""
    return round((time.perf_counter() - start) * 1000, 1)


def register_tools(mcp: FastMCP, port_resolver: PortResolver) -> None:
    """Register all SuPA read-only tools on the FastMCP instance.

    Args:
        mcp: FastMCP server instance to register tools on.
        port_resolver: Resolver for mapping NRM port_id to device and interface.
    """

    @mcp.tool()
    async def list_circuits(  # noqa: D417 — `ctx` is injected by FastMCP and hidden from the LLM schema.
        ctx: Context,
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
        filters = {
            k: v
            for k, v in {
                "reservation_state": reservation_state,
                "provision_state": provision_state,
                "lifecycle_state": lifecycle_state,
                "data_plane_state": data_plane_state,
            }.items()
            if v is not None
        }
        log = logger.bind(request_id=ctx.request_id)
        log.info("list_circuits called", **filters)
        t0 = time.perf_counter()
        try:
            circuits = list_circuits_query(**filters)
        except Exception:
            message, correlation_id = _internal_error("listing circuits")
            log.exception(
                "list_circuits failed",
                correlation_id=correlation_id,
                duration_ms=_elapsed_ms(t0),
            )
            return message
        log.info("list_circuits completed", count=len(circuits), duration_ms=_elapsed_ms(t0))
        return json.dumps(circuits, indent=2)

    @mcp.tool()
    async def get_circuit(ctx: Context, connection_id: str) -> str:  # noqa: D417 — `ctx` is FastMCP-injected.
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
        log = logger.bind(request_id=ctx.request_id)
        log.info("get_circuit called", connection_id=connection_id)
        t0 = time.perf_counter()
        try:
            connection_uuid = uuid.UUID(connection_id)
        except ValueError:
            log.info("get_circuit invalid_uuid", connection_id=connection_id, duration_ms=_elapsed_ms(t0))
            return f"Invalid UUID: {connection_id!r}"

        try:
            circuit = get_circuit_query(connection_uuid)
        except Exception:
            message, correlation_id = _internal_error("retrieving circuit")
            log.exception(
                "get_circuit failed",
                correlation_id=correlation_id,
                connection_id=connection_id,
                duration_ms=_elapsed_ms(t0),
            )
            return message
        if circuit is None:
            log.info("get_circuit not_found", connection_id=connection_id, duration_ms=_elapsed_ms(t0))
            return f"Circuit not found: {connection_id}"
        log.info("get_circuit completed", connection_id=connection_id, duration_ms=_elapsed_ms(t0))
        return json.dumps(circuit, indent=2)

    @mcp.tool()
    async def get_circuit_endpoints(ctx: Context, connection_id: str) -> str:  # noqa: D417 — `ctx` is FastMCP-injected.
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
        log = logger.bind(request_id=ctx.request_id)
        log.info("get_circuit_endpoints called", connection_id=connection_id)
        t0 = time.perf_counter()
        try:
            connection_uuid = uuid.UUID(connection_id)
        except ValueError:
            log.info(
                "get_circuit_endpoints invalid_uuid",
                connection_id=connection_id,
                duration_ms=_elapsed_ms(t0),
            )
            return f"Invalid UUID: {connection_id!r}"

        try:
            endpoints = get_circuit_endpoints_query(connection_uuid, port_resolver)
        except Exception:
            message, correlation_id = _internal_error("retrieving circuit endpoints")
            log.exception(
                "get_circuit_endpoints failed",
                correlation_id=correlation_id,
                connection_id=connection_id,
                duration_ms=_elapsed_ms(t0),
            )
            return message
        if endpoints is None:
            log.info(
                "get_circuit_endpoints not_found",
                connection_id=connection_id,
                duration_ms=_elapsed_ms(t0),
            )
            return (
                f"Circuit not found or not yet committed: {connection_id}. "
                "Endpoint data is only available after the reservation is committed."
            )
        ports_resolved = sum(1 for side in (endpoints["src"], endpoints["dst"]) if "device" in side)
        log.info(
            "get_circuit_endpoints completed",
            connection_id=connection_id,
            ports_resolved=ports_resolved,
            duration_ms=_elapsed_ms(t0),
        )
        return json.dumps(endpoints, indent=2)
