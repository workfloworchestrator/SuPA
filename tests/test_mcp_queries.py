"""Tests for MCP database query functions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from supa.mcp.queries import get_circuit_endpoints_query, get_circuit_query, list_circuits_query


def _make_reservation(
    connection_id: uuid.UUID | None = None,
    reservation_state: str = "RESERVE_HELD",
    provision_state: str | None = "RELEASED",
    lifecycle_state: str = "CREATED",
    data_plane_state: str | None = "DEACTIVATED",
    description: str | None = "test circuit",
    global_reservation_id: str = "global-1",
    create_date: datetime | None = None,
) -> MagicMock:
    """Create a mock Reservation object."""
    r = MagicMock()
    r.connection_id = connection_id or uuid.uuid4()
    r.reservation_state = reservation_state
    r.provision_state = provision_state
    r.lifecycle_state = lifecycle_state
    r.data_plane_state = data_plane_state
    r.description = description
    r.global_reservation_id = global_reservation_id
    r.requester_nsa = "urn:ogf:network:example.net:nsa"
    r.create_date = create_date or datetime(2025, 1, 1, tzinfo=timezone.utc)
    r.connection = None
    r.p2p_criteria = None
    r.schedule = None
    return r


def _make_connection(connection_id: uuid.UUID | None = None) -> MagicMock:
    """Create a mock Connection object."""
    c = MagicMock()
    c.connection_id = connection_id or uuid.uuid4()
    c.bandwidth = 1000
    c.src_port_id = "port-a1"
    c.src_vlan = 100
    c.dst_port_id = "port-b2"
    c.dst_vlan = 200
    c.circuit_id = "subscription-xyz"
    return c


def _make_p2p() -> MagicMock:
    """Create a mock P2PCriteria object."""
    p = MagicMock()
    p.src_stp_id = "urn:ogf:network:example.net:topology:stp/port-a1?vlan=100"
    p.dst_stp_id = "urn:ogf:network:example.net:topology:stp/port-b2?vlan=200"
    p.bandwidth = 1000
    return p


def _make_schedule() -> MagicMock:
    """Create a mock Schedule object."""
    s = MagicMock()
    s.start_time = datetime(2025, 6, 1, tzinfo=timezone.utc)
    s.end_time = datetime(2025, 6, 30, tzinfo=timezone.utc)
    return s


class TestListCircuitsQuery:
    """Tests for list_circuits_query."""

    def test_returns_list_of_dicts(self) -> None:
        """Returns a list of dicts with connection_id and state fields."""
        cid = uuid.uuid4()
        reservation = _make_reservation(connection_id=cid)
        mock_session = MagicMock()
        mock_session.query.return_value.order_by.return_value.all.return_value = [reservation]

        with patch("supa.mcp.queries.db_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = list_circuits_query()

        assert len(result) == 1
        assert result[0]["connection_id"] == str(cid)
        assert result[0]["reservation_state"] == "RESERVE_HELD"
        assert result[0]["lifecycle_state"] == "CREATED"

    def test_returns_empty_list_when_no_circuits(self) -> None:
        """Returns empty list when no circuits exist."""
        mock_session = MagicMock()
        mock_session.query.return_value.order_by.return_value.all.return_value = []

        with patch("supa.mcp.queries.db_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = list_circuits_query()

        assert result == []


class TestGetCircuitQuery:
    """Tests for get_circuit_query."""

    def test_returns_dict_with_states(self) -> None:
        """Returns a dict with circuit details including states and schedule."""
        cid = uuid.uuid4()
        reservation = _make_reservation(connection_id=cid)
        reservation.p2p_criteria = _make_p2p()
        reservation.schedule = _make_schedule()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = reservation

        with patch("supa.mcp.queries.db_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = get_circuit_query(cid)

        assert result is not None
        assert result["connection_id"] == str(cid)
        assert result["reservation_state"] == "RESERVE_HELD"
        assert result["bandwidth_mbps"] == 1000
        assert result["schedule"]["start_time"] == "2025-06-01T00:00:00+00:00"

    def test_returns_none_when_not_found(self) -> None:
        """Returns None when circuit UUID does not exist."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = None

        with patch("supa.mcp.queries.db_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = get_circuit_query(uuid.uuid4())

        assert result is None


class TestGetCircuitEndpointsQuery:
    """Tests for get_circuit_endpoints_query."""

    def test_returns_endpoints_with_port_ids(self) -> None:
        """Returns src/dst endpoints with port_id, vlan, stp_id."""
        from supa.mcp.port_mapping import PortResolver

        cid = uuid.uuid4()
        connection = _make_connection(connection_id=cid)
        p2p = _make_p2p()
        reservation = _make_reservation(connection_id=cid)
        reservation.p2p_criteria = p2p
        connection.reservation = reservation
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = connection

        resolver = PortResolver(None)

        with patch("supa.mcp.queries.db_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = get_circuit_endpoints_query(cid, resolver)

        assert result is not None
        assert result["src"]["port_id"] == "port-a1"
        assert result["src"]["vlan"] == 100
        assert result["dst"]["port_id"] == "port-b2"
        assert result["circuit_id"] == "subscription-xyz"

    def test_returns_device_interface_when_mapped(self) -> None:
        """Returns device and interface when port_mapping_file is configured."""
        import os
        import tempfile
        import textwrap

        from supa.mcp.port_mapping import PortResolver

        cid = uuid.uuid4()
        connection = _make_connection(connection_id=cid)
        reservation = _make_reservation(connection_id=cid)
        reservation.p2p_criteria = _make_p2p()
        connection.reservation = reservation
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = connection

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(
                textwrap.dedent("""\
                port_mapping:
                  "port-a1":
                    device: "router1.example.net"
                    interface: "ge-0/0/1"
            """)
            )
            tmp_path = f.name

        try:
            resolver = PortResolver(Path(tmp_path))
            with patch("supa.mcp.queries.db_session") as mock_ctx:
                mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
                mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
                result = get_circuit_endpoints_query(cid, resolver)
        finally:
            os.unlink(tmp_path)

        assert result["src"]["device"] == "router1.example.net"
        assert result["src"]["interface"] == "ge-0/0/1"
        assert result["dst"].get("device") is None

    def test_returns_none_when_connection_not_found(self) -> None:
        """Returns None when Connection row does not exist (pre-commit circuit)."""
        from supa.mcp.port_mapping import PortResolver

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = None

        with patch("supa.mcp.queries.db_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            result = get_circuit_endpoints_query(uuid.uuid4(), PortResolver(None))

        assert result is None
