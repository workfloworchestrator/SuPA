from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Column

from supa.connection.fsm import ReservationStateMachine
from supa.db.model import Reservation
from supa.db.session import db_session
from supa.grpc_nsi.connection_requester_pb2 import (
    ReserveAbortConfirmedRequest,
    ReserveAbortConfirmedResponse,
    ReserveCommitConfirmedRequest,
    ReserveCommitConfirmedResponse,
)
from supa.grpc_nsi.connection_requester_pb2_grpc import ConnectionRequesterServicer, ConnectionRequesterStub


@pytest.fixture(scope="module")
def grpc_add_to_server() -> Any:
    """Add our own ConnectionRequesterServicer to the fake gRPC server."""
    from supa.grpc_nsi.connection_requester_pb2_grpc import add_ConnectionRequesterServicer_to_server

    return add_ConnectionRequesterServicer_to_server


@pytest.fixture(scope="module")
def grpc_servicer() -> Any:
    """Use the fake servicer implementation to mock replies."""
    return Servicer()


@pytest.fixture(scope="module")
def grpc_stub_cls(grpc_channel: Any) -> Any:
    """Use our own ConnectionRequesterStub."""
    return ConnectionRequesterStub


@pytest.fixture(scope="function")
def get_stub(grpc_stub_cls: Any, grpc_channel: Any, monkeypatch: Any) -> Any:
    """Monkey patch requester.get_stub to return the fake stub."""
    from supa.connection import requester

    def mock_get_stub() -> Any:
        return grpc_stub_cls(grpc_channel)

    monkeypatch.setattr(requester, "get_stub", mock_get_stub)


class Servicer(ConnectionRequesterServicer):
    """Fake servicer to mock replies."""

    def ReserveCommitConfirmed(
        self, request: ReserveCommitConfirmedRequest, context: Any
    ) -> ReserveCommitConfirmedResponse:
        """Fake ReserveCommitConfirmed to return mocked ReserveCommitConfirmedResponse."""
        return ReserveCommitConfirmedResponse(header=request.header)

    def ReserveAbortConfirmed(
        self, request: ReserveAbortConfirmedRequest, context: Any
    ) -> ReserveAbortConfirmedResponse:
        """Fake ReserveAbortConfirmed to return mocked ReserveAbortConfirmedResponse."""
        return ReserveAbortConfirmedResponse(header=request.header)


@pytest.fixture(scope="session")
def connection_id() -> Column:
    """Create new reservation in db and return connection ID."""
    with db_session() as session:
        reservation = Reservation(
            correlation_id=uuid4(),
            protocol_version="application/vnd.ogf.nsi.cs.v2.provider+soap",
            requester_nsa="urn:ogf:network:example.domain:2021:requester",
            provider_nsa="urn:ogf:network:example.domain:2021:provider",
            reply_to=None,
            session_security_attributes=None,
            global_reservation_id="global reservation id",
            description="reservation 1",
            version=0,
            start_time=datetime.now(timezone.utc) + timedelta(minutes=10),
            end_time=datetime.now(timezone.utc) + timedelta(minutes=20),
            bandwidth=10,
            symmetric=True,
            src_domain="test.domain:2001",
            src_network_type="topology",
            src_port="port1",
            src_vlans=1783,
            dst_domain="test.domain:2001",
            dst_network_type="topology",
            dst_port="port2",
            dst_vlans=1783,
            lifecycle_state="CREATED",
        )
        session.add(reservation)
        session.flush()  # let db generate connection_id

        yield reservation.connection_id

        session.delete(reservation)


@pytest.fixture
def reserve_held(connection_id: Column) -> None:
    """Set reserve state machine of reservation identified by connection_id to state ReserveHeld."""
    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.reservation_state = ReservationStateMachine.ReserveHeld.value


@pytest.fixture
def reserve_committing(connection_id: Column) -> None:
    """Set reserve state machine of reservation identified by connection_id to state ReserveCommitting."""
    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.reservation_state = ReservationStateMachine.ReserveCommitting.value


@pytest.fixture
def reserve_aborting(connection_id: Column) -> None:
    """Set reserve state machine of reservation identified by connection_id to state ReserveAborting."""
    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.reservation_state = ReservationStateMachine.ReserveAborting.value
