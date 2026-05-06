"""Read-only database query functions for MCP tools."""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from supa.db.model import Connection, Reservation
from supa.db.session import db_session
from supa.mcp.port_mapping import PortResolver

logger = structlog.get_logger(__name__)


def _str(val: Any) -> str | None:
    """Safely convert a state value (string or enum) to string.

    Args:
        val: State value — may be a string or an object with a .value attribute.

    Returns:
        String representation, or None if val is None.
    """
    if val is None:
        return None
    return val.value if hasattr(val, "value") else str(val)


def list_circuits_query(
    reservation_state: str | None = None,
    provision_state: str | None = None,
    lifecycle_state: str | None = None,
    data_plane_state: str | None = None,
) -> list[dict[str, Any]]:
    """Return a list of all circuits with their states.

    Args:
        reservation_state: Filter to circuits in this reservation state.
        provision_state: Filter to circuits in this provision state.
        lifecycle_state: Filter to circuits in this lifecycle state.
        data_plane_state: Filter to circuits in this data plane state.

    Returns:
        List of dicts, each with connection_id, description, global_reservation_id,
        create_date, and the four state values.
    """
    with db_session() as session:
        query = session.query(Reservation)
        if reservation_state is not None:
            query = query.filter(Reservation.reservation_state == reservation_state)
        if provision_state is not None:
            query = query.filter(Reservation.provision_state == provision_state)
        if lifecycle_state is not None:
            query = query.filter(Reservation.lifecycle_state == lifecycle_state)
        if data_plane_state is not None:
            query = query.filter(Reservation.data_plane_state == data_plane_state)

        reservations = query.order_by(Reservation.create_date.desc()).all()
        return [
            {
                "connection_id": str(r.connection_id),
                "description": r.description,
                "global_reservation_id": r.global_reservation_id,
                "reservation_state": _str(r.reservation_state),
                "provision_state": _str(r.provision_state),
                "lifecycle_state": _str(r.lifecycle_state),
                "data_plane_state": _str(r.data_plane_state),
                "create_date": r.create_date.isoformat() if r.create_date else None,
            }
            for r in reservations
        ]


def get_circuit_query(connection_id: uuid.UUID) -> dict[str, Any] | None:
    """Return full circuit details for a single connection_id.

    Args:
        connection_id: UUID of the circuit to retrieve.

    Returns:
        Dict with circuit details, or None if not found.
    """
    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one_or_none()
        if reservation is None:
            return None

        result: dict[str, Any] = {
            "connection_id": str(reservation.connection_id),
            "description": reservation.description,
            "global_reservation_id": reservation.global_reservation_id,
            "requester_nsa": reservation.requester_nsa,
            "reservation_state": _str(reservation.reservation_state),
            "provision_state": _str(reservation.provision_state),
            "lifecycle_state": _str(reservation.lifecycle_state),
            "data_plane_state": _str(reservation.data_plane_state),
            "create_date": reservation.create_date.isoformat() if reservation.create_date else None,
        }

        p2p = reservation.p2p_criteria
        if p2p is not None:
            result["bandwidth_mbps"] = p2p.bandwidth
            result["src_stp_id"] = p2p.src_stp_id
            result["dst_stp_id"] = p2p.dst_stp_id

        schedule = reservation.schedule
        if schedule is not None:
            result["schedule"] = {
                "start_time": schedule.start_time.isoformat() if schedule.start_time else None,
                "end_time": schedule.end_time.isoformat() if schedule.end_time else None,
            }

        connection = reservation.connection
        if connection is not None:
            result["bandwidth_mbps"] = connection.bandwidth
            result["src_port_id"] = connection.src_port_id
            result["src_vlan"] = connection.src_vlan
            result["dst_port_id"] = connection.dst_port_id
            result["dst_vlan"] = connection.dst_vlan
            result["circuit_id"] = connection.circuit_id

        return result


def get_circuit_endpoints_query(connection_id: uuid.UUID, port_resolver: PortResolver) -> dict[str, Any] | None:
    """Return src/dst endpoint info for a circuit.

    Args:
        connection_id: UUID of the circuit.
        port_resolver: Resolver for mapping port_id to device and interface.

    Returns:
        Dict with connection_id, circuit_id, bandwidth_mbps, src, and dst endpoint dicts.
        Returns None if the Connection row does not exist (circuit not yet committed).
    """
    with db_session() as session:
        connection = session.query(Connection).filter(Connection.connection_id == connection_id).one_or_none()
        if connection is None:
            return None

        p2p = connection.reservation.p2p_criteria

        src: dict[str, Any] = {
            "port_id": connection.src_port_id,
            "vlan": connection.src_vlan,
            "stp_id": p2p.src_stp_id if p2p else None,
            **port_resolver.resolve(connection.src_port_id),
        }
        dst: dict[str, Any] = {
            "port_id": connection.dst_port_id,
            "vlan": connection.dst_vlan,
            "stp_id": p2p.dst_stp_id if p2p else None,
            **port_resolver.resolve(connection.dst_port_id),
        }

        return {
            "connection_id": str(connection_id),
            "circuit_id": connection.circuit_id,
            "bandwidth_mbps": connection.bandwidth,
            "src": src,
            "dst": dst,
        }
