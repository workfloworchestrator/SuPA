"""DB-backed integration tests for MCP query functions.

The existing ``test_mcp_queries.py`` mocks ``db_session`` and only checks the
dict shape — it would pass even if a column name were wrong. These tests use
the session-scoped ``init`` fixture from ``conftest.py`` to exercise the real
SQLAlchemy query against a SQLite database, so a schema or query-builder
regression actually fails.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from supa.mcp.port_mapping import PortResolver
from supa.mcp.queries import get_circuit_endpoints_query, get_circuit_query, list_circuits_query


def test_list_circuits_query_returns_reservation(connection_id: UUID) -> None:
    """A committed Reservation appears in list_circuits_query output with the documented fields."""
    circuits = list_circuits_query()
    found = [c for c in circuits if c["connection_id"] == str(connection_id)]
    assert len(found) == 1, "the fixture-created reservation should be in the list"
    entry = found[0]
    assert entry["description"] == "reservation 1"
    assert entry["global_reservation_id"] == "global reservation id"
    assert entry["lifecycle_state"] == "CREATED"
    # All four state fields must be present even when the column is NULL.
    for field in ("reservation_state", "provision_state", "lifecycle_state", "data_plane_state"):
        assert field in entry


@pytest.mark.parametrize(
    "filter_kwargs",
    [
        {"lifecycle_state": "CREATED"},
        {"reservation_state": "RESERVE_START"},
    ],
)
def test_list_circuits_query_filter_matches(connection_id: UUID, filter_kwargs: dict[str, str]) -> None:
    """State filters round-trip through SQLAlchemy and return the matching row."""
    circuits = list_circuits_query(**filter_kwargs)
    assert any(c["connection_id"] == str(connection_id) for c in circuits)


def test_list_circuits_query_filter_excludes_non_matching(connection_id: UUID) -> None:
    """A state filter that does not match the fixture row excludes it."""
    circuits = list_circuits_query(lifecycle_state="TERMINATED")
    assert all(c["connection_id"] != str(connection_id) for c in circuits)


def test_list_circuits_query_filter_by_provision_state(connection_id: UUID, released: None) -> None:
    """provision_state filter round-trips through SQLAlchemy."""
    circuits = list_circuits_query(provision_state="RELEASED")
    assert any(c["connection_id"] == str(connection_id) for c in circuits)


def test_list_circuits_query_filter_by_data_plane_state(connection_id: UUID, activated: None) -> None:
    """data_plane_state filter round-trips through SQLAlchemy."""
    circuits = list_circuits_query(data_plane_state="ACTIVATED")
    assert any(c["connection_id"] == str(connection_id) for c in circuits)


def test_get_circuit_query_returns_dict(connection_id: UUID) -> None:
    """Returns a populated dict for an existing reservation, including p2p_criteria and schedule."""
    circuit = get_circuit_query(connection_id)
    assert circuit is not None
    assert circuit["connection_id"] == str(connection_id)
    assert circuit["description"] == "reservation 1"
    assert circuit["lifecycle_state"] == "CREATED"
    assert circuit["bandwidth_mbps"] == 10
    assert circuit["src_stp_id"] == "port1"
    assert circuit["dst_stp_id"] == "port2"
    assert "schedule" in circuit
    assert circuit["schedule"]["start_time"] is not None
    assert circuit["schedule"]["end_time"] is not None


def test_get_circuit_query_returns_none_for_unknown(connection_id: UUID) -> None:
    """Returns None for a UUID that does not exist."""
    unknown = UUID("00000000-0000-0000-0000-000000000000")
    assert unknown != connection_id  # fixture parameter included to share the session DB setup
    assert get_circuit_query(unknown) is None


def test_get_circuit_endpoints_query_returns_endpoints(connection_id: UUID, connection: None) -> None:
    """With a Connection row, returns src/dst endpoint info with the stored port_id values."""
    endpoints = get_circuit_endpoints_query(connection_id, PortResolver(None))
    assert endpoints is not None
    assert endpoints["connection_id"] == str(connection_id)
    assert endpoints["bandwidth_mbps"] == 10
    # port_id values come from the Topology rows linked via the fixture's stp_ids.
    assert endpoints["src"]["port_id"] == "2d35f97c-7e90-4f2d-bc52-d22d05d972f4"
    assert endpoints["src"]["vlan"] == 1783
    assert endpoints["src"]["stp_id"] == "port1"
    assert endpoints["dst"]["port_id"] == "port.id"
    assert endpoints["dst"]["vlan"] == 1783
    assert endpoints["dst"]["stp_id"] == "port2"
    # No port mapping configured, so device/interface are absent.
    assert "device" not in endpoints["src"]
    assert "interface" not in endpoints["src"]


def test_get_circuit_endpoints_query_returns_none_pre_commit(connection_id: UUID) -> None:
    """Returns None when only a Reservation exists (Connection row not created yet)."""
    assert get_circuit_endpoints_query(connection_id, PortResolver(None)) is None
