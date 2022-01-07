import unittest.mock
from datetime import datetime, timedelta, timezone
from json import dumps
from typing import Any
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
from supa.grpc_nsi.connection_provider_pb2 import (
    ProvisionRequest,
    ReservationRequestCriteria,
    ReserveAbortRequest,
    ReserveCommitRequest,
    ReserveRequest,
)
from supa.grpc_nsi.services_pb2 import PointToPointService
from supa.util.timestamp import EPOCH


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
def pb_reserve_request_end_time_before_start_time(pb_reserve_request: ReserveRequest) -> ReserveRequest:
    """Modify schedule of reserve request so that end time is before start time."""
    pb_reserve_request.criteria.schedule.start_time.FromDatetime(datetime.now(timezone.utc) + timedelta(hours=2))
    pb_reserve_request.criteria.schedule.end_time.FromDatetime(datetime.now(timezone.utc) + timedelta(hours=1))
    return pb_reserve_request


@pytest.fixture()
def pb_reserve_request_end_time_in_past(pb_reserve_request: ReserveRequest) -> ReserveRequest:
    """Modify schedule of reserve request so that end time is in the past."""
    pb_reserve_request.criteria.schedule.start_time.FromDatetime(EPOCH)
    pb_reserve_request.criteria.schedule.end_time.FromDatetime(datetime.now(timezone.utc) - timedelta(hours=1))
    return pb_reserve_request


@pytest.fixture()
def pb_reserve_commit_request(pb_header: Header, connection_id: Column) -> ReserveCommitRequest:
    """Create protobuf reserve commit request for connection id in state reserve held."""
    pb_request = ReserveCommitRequest()
    pb_request.header.CopyFrom(pb_header)
    pb_request.connection_id = str(connection_id)
    return pb_request


@pytest.fixture()
def pb_reserve_abort_request(pb_header: Header, connection_id: Column) -> ReserveAbortRequest:
    """Create protobuf reserve abort request for connection id in state reserve held."""
    pb_request = ReserveAbortRequest()
    pb_request.header.CopyFrom(pb_header)
    pb_request.connection_id = str(connection_id)
    return pb_request


@pytest.fixture()
def pb_provision_request(pb_header: Header, connection_id: Column) -> ProvisionRequest:
    """Create protobuf provision request for connection id in state released."""
    pb_request = ProvisionRequest()
    pb_request.header.CopyFrom(pb_header)
    pb_request.connection_id = str(connection_id)
    return pb_request


@pytest.fixture(autouse=True, scope="module")
def add_ports() -> None:
    """Add standard STPs to database."""
    with db_session() as session:
        session.add(Port(port_id=uuid4(), name="port1", vlans="1779-1799", bandwidth=1000, enabled=True))
        session.add(Port(port_id=uuid4(), name="port2", vlans="1779-1799", bandwidth=1000, enabled=True))


def test_reserve_request(pb_reserve_request: ReserveRequest, caplog: Any) -> None:
    """Test the connection provider Reserve happy path returns connection id."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    request_correlation_id = pb_reserve_request.header.correlation_id
    reserve_response = service.Reserve(pb_reserve_request, mock_context)
    assert request_correlation_id == reserve_response.header.correlation_id
    assert not reserve_response.header.reply_to
    assert reserve_response.connection_id
    assert not reserve_response.HasField("service_exception")
    assert 'Added job "ReserveJob" to job store' in caplog.text


def test_reserve_request_end_time_before_start_time(
    pb_reserve_request_end_time_before_start_time: ReserveRequest,
) -> None:
    """Test the connection provider Reserve returns service exception when end time before start time."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_response = service.Reserve(pb_reserve_request_end_time_before_start_time, mock_context)
    assert pb_reserve_request_end_time_before_start_time.header.correlation_id == reserve_response.header.correlation_id
    assert not reserve_response.header.reply_to
    assert not reserve_response.connection_id
    assert reserve_response.HasField("service_exception")
    assert reserve_response.service_exception.error_id == "00101"


def test_reserve_request_end_time_in_past(pb_reserve_request_end_time_in_past: ReserveRequest) -> None:
    """Test the connection provider Reserve returns service exception when end time before start time."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_response = service.Reserve(pb_reserve_request_end_time_in_past, mock_context)
    assert pb_reserve_request_end_time_in_past.header.correlation_id == reserve_response.header.correlation_id
    assert not reserve_response.header.reply_to
    assert not reserve_response.connection_id
    assert reserve_response.HasField("service_exception")
    assert reserve_response.service_exception.error_id == "00101"


def test_reserve_commit(pb_reserve_commit_request: ReserveCommitRequest, reserve_held: None, caplog: Any) -> None:
    """Test the connection provider ReserveCommit happy path."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_commit_response = service.ReserveCommit(pb_reserve_commit_request, mock_context)
    assert pb_reserve_commit_request.header.correlation_id == reserve_commit_response.header.correlation_id
    assert not reserve_commit_response.header.reply_to
    assert not reserve_commit_response.HasField("service_exception")
    assert 'Added job "ReserveCommitJob" to job store' in caplog.text


def test_reserve_commit_random_connection_id(
    pb_reserve_commit_request: ReserveCommitRequest,
) -> None:
    """Test the connection provider ReserveCommit returns service exception for random connection id."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    # overwrite connection id from reservation in db with random UUID
    pb_reserve_commit_request.connection_id = str(uuid4())
    reserve_commit_response = service.ReserveCommit(pb_reserve_commit_request, mock_context)
    assert pb_reserve_commit_request.header.correlation_id == reserve_commit_response.header.correlation_id
    assert not reserve_commit_response.header.reply_to
    assert reserve_commit_response.HasField("service_exception")
    assert reserve_commit_response.service_exception.error_id == "00203"
    assert pb_reserve_commit_request.connection_id == reserve_commit_response.service_exception.connection_id


def test_reserve_commit_invalid_transition(
    pb_reserve_commit_request: ReserveCommitRequest, reserve_committing: None, caplog: Any
) -> None:
    """Test the connection provider ReserveCommit returns service exception when in invalid state for request."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_commit_response = service.ReserveCommit(pb_reserve_commit_request, mock_context)
    assert pb_reserve_commit_request.header.correlation_id == reserve_commit_response.header.correlation_id
    assert not reserve_commit_response.header.reply_to
    assert reserve_commit_response.HasField("service_exception")
    assert reserve_commit_response.service_exception.error_id == "00201"
    assert pb_reserve_commit_request.connection_id == reserve_commit_response.service_exception.connection_id
    assert "Not scheduling ReserveCommitJob" in caplog.text


def test_reserve_abort(pb_reserve_abort_request: ReserveAbortRequest, reserve_held: None, caplog: Any) -> None:
    """Test the connection provider ReserveAbort happy path."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_abort_response = service.ReserveAbort(pb_reserve_abort_request, mock_context)
    assert pb_reserve_abort_request.header.correlation_id == reserve_abort_response.header.correlation_id
    assert not reserve_abort_response.header.reply_to
    assert not reserve_abort_response.HasField("service_exception")
    assert 'Added job "ReserveAbortJob" to job store' in caplog.text


def test_reserve_abort_random_connection_id(pb_reserve_abort_request: ReserveAbortRequest) -> None:
    """Test the connection provider ReserveAbort returns service exception for random connection id."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    # overwrite connection id from reservation in db with random UUID
    pb_reserve_abort_request.connection_id = str(uuid4())
    reserve_abort_response = service.ReserveAbort(pb_reserve_abort_request, mock_context)
    assert pb_reserve_abort_request.header.correlation_id == reserve_abort_response.header.correlation_id
    assert not reserve_abort_response.header.reply_to
    assert reserve_abort_response.HasField("service_exception")
    assert reserve_abort_response.service_exception.error_id == "00203"
    assert pb_reserve_abort_request.connection_id == reserve_abort_response.service_exception.connection_id


def test_reserve_abort_invalid_transition(
    pb_reserve_abort_request: ReserveAbortRequest, reserve_aborting: None, caplog: Any
) -> None:
    """Test the connection provider ReserveAbort returns service exception when in invalid state for request."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_abort_response = service.ReserveAbort(pb_reserve_abort_request, mock_context)
    assert pb_reserve_abort_request.header.correlation_id == reserve_abort_response.header.correlation_id
    assert not reserve_abort_response.header.reply_to
    assert reserve_abort_response.HasField("service_exception")
    assert reserve_abort_response.service_exception.error_id == "00201"
    assert pb_reserve_abort_request.connection_id == reserve_abort_response.service_exception.connection_id
    assert "Not scheduling ReserveAbortJob" in caplog.text


def test_provision(pb_provision_request: ProvisionRequest, released: None, caplog: Any) -> None:
    """Test the connection provider Provision happy path."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    provision_response = service.Provision(pb_provision_request, mock_context)
    assert pb_provision_request.header.correlation_id == provision_response.header.correlation_id
    assert not provision_response.header.reply_to
    assert not provision_response.HasField("service_exception")
    assert 'Added job "ProvisionJob" to job store' in caplog.text


def test_provision_random_connection_id(pb_provision_request: ProvisionRequest) -> None:
    """Test the connection provider Provision returns service exception for random connection id."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    # overwrite connection id from reservation in db with random UUID
    pb_provision_request.connection_id = str(uuid4())
    provision_response = service.Provision(pb_provision_request, mock_context)
    assert pb_provision_request.header.correlation_id == provision_response.header.correlation_id
    assert not provision_response.header.reply_to
    assert provision_response.HasField("service_exception")
    assert provision_response.service_exception.error_id == "00203"
    assert pb_provision_request.connection_id == provision_response.service_exception.connection_id


def test_provision_invalid_transition(pb_provision_request: ProvisionRequest, provisioned: None, caplog: Any) -> None:
    """Test the connection provider Provision returns service exception when in invalid state for request."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    provision_response = service.Provision(pb_provision_request, mock_context)
    assert pb_provision_request.header.correlation_id == provision_response.header.correlation_id
    assert not provision_response.header.reply_to
    assert provision_response.HasField("service_exception")
    assert provision_response.service_exception.error_id == "00201"
    assert pb_provision_request.connection_id == provision_response.service_exception.connection_id
    assert "Not scheduling ProvisionJob" in caplog.text
