import unittest.mock
from datetime import datetime, timedelta, timezone
from json import dumps
from uuid import uuid4

import pytest
from google.protobuf.json_format import Parse
from grpc import ServicerContext
from sqlalchemy import Column

from supa import const
from supa.connection.provider.server import ConnectionProviderService
from supa.db.model import Port
from supa.db.session import db_session
from supa.grpc_nsi.connection_common_pb2 import Header, Schedule
from supa.grpc_nsi.connection_provider_pb2 import ReservationRequestCriteria, ReserveCommitRequest, ReserveRequest
from supa.grpc_nsi.services_pb2 import PointToPointService

msg = {
    "header": {
        "protocol_version": "application/vnd.ogf.nsi.cs.v2.provider+soap",
        "correlation_id": "urn:uuid:1ee6db2e-6278-11ec-b38f-acde48001122",
        "requester_nsa": "urn:ogf:network:surf.nl:2020:onsaclient",
        "provider_nsa": "urn:ogf:network:test.domain:2001:supa",
        "reply_to": "http://127.0.0.1:7080/NSI/services/RequesterService2",
    },
    "description": "Test Connection",
    "criteria": {
        "schedule": {
            "start_time": {
                "seconds": 1640102919,
            },
            "end_time": {
                "seconds": 1640102979,
            },
        },
        "serviceType": "http://services.ogf.org/nsi/2013/12/descriptions/EVTS.A-GOLE",
        "ptps": {
            "capacity": 10,
            "source_stp": "urn:ogf:network:netherlight.net:2013:production8:port1?vlan=1783",
            "dest_stp": "urn:ogf:network:netherlight.net:2013:production8:port2?vlan=1783",
        },
    },
}


@pytest.fixture()
def pb_header() -> Header:
    """Create protobuf header with unique correlation_id."""
    return Parse(
        dumps(
            {
                "protocol_version": "application/vnd.ogf.nsi.cs.v2.provider+soap",
                "correlation_id": uuid4().urn,
                "requester_nsa": "urn:ogf:network:surf.nl:2020:onsaclient",
                "provider_nsa": "urn:ogf:network:test.domain:2001:supa",
                "reply_to": "http://127.0.0.1:7080/NSI/services/RequesterService2",
            }
        ),
        Header(),
    )


@pytest.fixture()
def pb_schedule() -> Schedule:
    """Create protobuf schedule with start time now+1hour and end time now+2hours."""
    schedule = Schedule()
    schedule.start_time.FromDatetime(datetime.now(timezone.utc) + timedelta(hours=1))
    schedule.end_time.FromDatetime(datetime.now(timezone.utc) + timedelta(hours=2))
    return schedule


@pytest.fixture()
def pb_ptps() -> PointToPointService:
    """Create protobuf point-to-point-service with standard STPs."""
    ptps = PointToPointService()
    ptps.capacity = 10
    ptps.symmetric_path = True
    ptps.source_stp = "urn:ogf:network:netherlight.net:2013:production8:port1?vlan=1783"
    ptps.dest_stp = "urn:ogf:network:netherlight.net:2013:production8:port2?vlan=1783"
    # The initial version didn't have to support Explicit Routing Objects.
    # for param in reservation.parameters:
    #    pb_ptps.parameters[param.key] = param.value
    return ptps


@pytest.fixture()
def pb_reservation_request_criteria(pb_schedule: Schedule, pb_ptps: PointToPointService) -> ReservationRequestCriteria:
    """Create protobuf criteria with filled in schedule and point-to-point-service."""
    reservation_request_criteria = ReservationRequestCriteria()
    reservation_request_criteria.schedule.CopyFrom(pb_schedule)
    reservation_request_criteria.service_type = const.SERVICE_TYPE
    reservation_request_criteria.ptps.CopyFrom(pb_ptps)
    return reservation_request_criteria


@pytest.fixture()
def pb_reserve_request(
    pb_header: Header, pb_reservation_request_criteria: ReservationRequestCriteria
) -> ReserveRequest:
    """Create protobuf reserve request with filled in header and criteria."""
    pb_request = ReserveRequest()
    pb_request.header.CopyFrom(pb_header)
    pb_request.description = "reserve request"
    pb_request.criteria.CopyFrom(pb_reservation_request_criteria)
    # pb_request.connection_id = ""
    return pb_request


@pytest.fixture()
def pb_reserve_commit_request(pb_header: Header, connection_id: Column, reserve_held: None) -> ReserveRequest:
    """Create protobuf reserve request with filled in header and criteria."""
    pb_request = ReserveCommitRequest()
    pb_request.header.CopyFrom(pb_header)
    pb_request.connection_id = str(connection_id)
    return pb_request


@pytest.fixture(autouse=True, scope="module")
def add_ports() -> None:
    """Add standard STPs to database."""
    with db_session() as session:
        session.add(Port(port_id=uuid4(), name="port1", vlans="1779-1799", bandwidth=1000, enabled=True))
        session.add(Port(port_id=uuid4(), name="port2", vlans="1779-1799", bandwidth=1000, enabled=True))


def test_reserve_request(pb_reserve_request: ReserveRequest) -> None:
    """Test the connection provider ReserveRequest."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    #
    # Test happy path with correct reservation request returning a reservation response with the connection_id.
    #
    reserve_response = service.Reserve(pb_reserve_request, mock_context)
    assert reserve_response.connection_id
    #
    # Test reservation request with end time before start time.
    # TODO: Enable and finish test after Reserve() is returning a proper service exception.
    #
    # pb_reserve_request.criteria.schedule.start_time.FromDatetime(datetime.now(timezone.utc) + timedelta(hours=2))
    # pb_reserve_request.criteria.schedule.end_time.FromDatetime(datetime.now(timezone.utc) + timedelta(hours=1))
    # pb_reserve_request.header.correlation_id = uuid4().urn
    # reserve_response = service.Reserve(pb_reserve_request, mock_context)
    # assert reserve_respone == "correct service exception"
    #
    # Test reservation request with end time in the past.
    # TODO: Enable and finish test after Reserve() is returning a proper service exception.
    #
    # pb_reserve_request.criteria.schedule.start_time.FromDatetime(datetime.now(timezone.utc) - timedelta(hours=2))
    # pb_reserve_request.criteria.schedule.end_time.FromDatetime(datetime.now(timezone.utc) - timedelta(hours=1))
    # pb_reserve_request.header.correlation_id = uuid4().urn
    # reserve_response = service.Reserve(pb_reserve_request, mock_context)
    # assert reserve_respone == "correct service exception"


def test_reserve_commit(pb_reserve_commit_request: ReserveRequest) -> None:
    """Test the connection provider ReserveRequest."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    #
    # Test happy path with reservation commit request for a reservation in the correct state.
    #
    reserve_response = service.ReserveCommit(pb_reserve_commit_request, mock_context)
    assert reserve_response.header.correlation_id == pb_reserve_commit_request.header.correlation_id
