import unittest.mock
from datetime import datetime, timedelta, timezone
from json import dumps
from typing import Any
from uuid import UUID, uuid4

import pytest
from google.protobuf.json_format import Parse
from grpc import ServicerContext
from sqlalchemy import Column

from supa import const
from supa.connection.provider.server import ConnectionProviderService
from supa.db.model import Reservation
from supa.grpc_nsi.connection_common_pb2 import Header, Schedule
from supa.grpc_nsi.connection_provider_pb2 import GenericRequest, ReservationRequestCriteria, ReserveRequest
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
                "provider_nsa": "urn:ogf:network:example.domain:2001:nsa:supa",
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
    reservation_request_criteria.version = 1
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
def pb_reserve_modify_request(pb_reserve_request: ReserveRequest, connection_id: UUID) -> ReserveRequest:
    """Create protobuf reserve modify request with connection_id added to request."""
    pb_reserve_request.connection_id = str(connection_id)
    return pb_reserve_request


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
def pb_reserve_commit_request(pb_header: Header, connection_id: Column) -> GenericRequest:
    """Create protobuf reserve commit request for connection_id."""
    pb_request = GenericRequest()
    pb_request.header.CopyFrom(pb_header)
    pb_request.connection_id = str(connection_id)
    return pb_request


@pytest.fixture()
def pb_reserve_abort_request(pb_header: Header, connection_id: Column) -> GenericRequest:
    """Create protobuf reserve abort request for connection_id."""
    pb_request = GenericRequest()
    pb_request.header.CopyFrom(pb_header)
    pb_request.connection_id = str(connection_id)
    return pb_request


@pytest.fixture()
def pb_provision_request(pb_header: Header, connection_id: Column) -> GenericRequest:
    """Create protobuf provision request for connection_id."""
    pb_request = GenericRequest()
    pb_request.header.CopyFrom(pb_header)
    pb_request.connection_id = str(connection_id)
    return pb_request


@pytest.fixture()
def pb_release_request(pb_header: Header, connection_id: Column) -> GenericRequest:
    """Create protobuf release request for connection_id."""
    pb_request = GenericRequest()
    pb_request.header.CopyFrom(pb_header)
    pb_request.connection_id = str(connection_id)
    return pb_request


@pytest.fixture()
def pb_terminate_request(pb_header: Header, connection_id: Column) -> GenericRequest:
    """Create protobuf terminate request for connection_id."""
    pb_request = GenericRequest()
    pb_request.header.CopyFrom(pb_header)
    pb_request.connection_id = str(connection_id)
    return pb_request


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
    assert "Schedule reserve" in caplog.text
    assert "Schedule reserve timeout" in caplog.text


def test_reserve_request_end_time_before_start_time(
    pb_reserve_request_end_time_before_start_time: ReserveRequest, caplog: Any
) -> None:
    """Test the connection provider Reserve returns service exception when end time before start time."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_response = service.Reserve(pb_reserve_request_end_time_before_start_time, mock_context)
    assert pb_reserve_request_end_time_before_start_time.header.correlation_id == reserve_response.header.correlation_id
    assert not reserve_response.header.reply_to
    assert not reserve_response.connection_id
    assert reserve_response.HasField("service_exception")
    assert reserve_response.service_exception.error_id == "00102"
    assert "End time cannot come before start time" in caplog.text


def test_reserve_request_end_time_in_past(pb_reserve_request_end_time_in_past: ReserveRequest, caplog: Any) -> None:
    """Test the connection provider Reserve returns service exception when end time before start time."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_response = service.Reserve(pb_reserve_request_end_time_in_past, mock_context)
    assert pb_reserve_request_end_time_in_past.header.correlation_id == reserve_response.header.correlation_id
    assert not reserve_response.header.reply_to
    assert not reserve_response.connection_id
    assert reserve_response.HasField("service_exception")
    assert reserve_response.service_exception.error_id == "00102"
    assert "End time lies in the past" in caplog.text


def test_reserve_modify(
    pb_reserve_modify_request: ReserveRequest, connection_id: UUID, connection: None, caplog: Any
) -> None:
    """Test the connection provider Reserve Modify happy path."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    request_correlation_id = pb_reserve_modify_request.header.correlation_id
    reserve_response = service.Reserve(pb_reserve_modify_request, mock_context)
    assert request_correlation_id == reserve_response.header.correlation_id
    assert not reserve_response.header.reply_to
    assert reserve_response.connection_id == str(connection_id)
    assert not reserve_response.HasField("service_exception")
    assert "modify reservation" in caplog.text
    assert "Schedule reserve" in caplog.text
    assert "Schedule reserve timeout" in caplog.text


def test_reserve_modify_illegal_version(
    pb_reserve_modify_request: ReserveRequest, connection_id: UUID, connection: None, caplog: Any
) -> None:
    """Test the connection provider Reserve Modify returns UnsupportedParameter exception on illegal version."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    request_correlation_id = pb_reserve_modify_request.header.correlation_id
    # criteria version may only be incremented by 1
    pb_reserve_modify_request.criteria.version = pb_reserve_modify_request.criteria.version + 2
    reserve_response = service.Reserve(pb_reserve_modify_request, mock_context)
    assert request_correlation_id == reserve_response.header.correlation_id
    assert not reserve_response.header.reply_to
    assert not reserve_response.connection_id
    assert reserve_response.HasField("service_exception")
    assert reserve_response.service_exception.error_id == "00102"
    assert reserve_response.service_exception.connection_id == str(connection_id)
    assert "version may only be incremented by 1" in caplog.text


def test_reserve_modify_unknown_connection_id(
    pb_reserve_modify_request: ReserveRequest, connection: None, caplog: Any
) -> None:
    """Test the connection provider Reserve returns ReservationNonExistent exception for unknown connection id."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    request_correlation_id = pb_reserve_modify_request.header.correlation_id
    # add unknown connection_id to this modify request
    non_existing_connection_id = str(uuid4())
    pb_reserve_modify_request.connection_id = str(non_existing_connection_id)
    reserve_response = service.Reserve(pb_reserve_modify_request, mock_context)
    assert request_correlation_id == reserve_response.header.correlation_id
    assert not reserve_response.header.reply_to
    assert not reserve_response.connection_id
    assert reserve_response.HasField("service_exception")
    assert reserve_response.service_exception.connection_id == non_existing_connection_id
    assert reserve_response.service_exception.error_id == "00203"
    assert "Connection ID does not exist" in caplog.text
    assert reserve_response.service_exception.variables[0].type == "connectionId"
    assert reserve_response.service_exception.variables[0].value == non_existing_connection_id


def test_reserve_modify_reservation_already_started(
    pb_reserve_modify_request: ReserveRequest, connection_id: UUID, start_now: None, connection: None, caplog: Any
) -> None:
    """Test the connection provider Reserve returns UnsupportedParameter exception when already started."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    request_correlation_id = pb_reserve_modify_request.header.correlation_id
    # change start time to 1 minute in te future
    pb_reserve_modify_request.criteria.schedule.start_time.FromDatetime(
        datetime.now(timezone.utc) + timedelta(minutes=1)
    )
    reserve_response = service.Reserve(pb_reserve_modify_request, mock_context)
    assert request_correlation_id == reserve_response.header.correlation_id
    assert not reserve_response.header.reply_to
    assert not reserve_response.connection_id
    assert reserve_response.HasField("service_exception")
    assert reserve_response.service_exception.connection_id == str(connection_id)
    assert reserve_response.service_exception.error_id == "00102"
    assert "cannot change start time when reservation already started" in caplog.text


def test_reserve_modify_invalid_transition(
    pb_reserve_modify_request: ReserveRequest, connection_id: UUID, reserve_held: None, connection: None, caplog: Any
) -> None:
    """Test the connection provider Reserve Modify returns InvalidTransition exception when not in modifiable state."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    request_correlation_id = pb_reserve_modify_request.header.correlation_id
    reserve_response = service.Reserve(pb_reserve_modify_request, mock_context)
    assert request_correlation_id == reserve_response.header.correlation_id
    assert not reserve_response.header.reply_to
    assert not reserve_response.connection_id
    assert reserve_response.HasField("service_exception")
    assert reserve_response.service_exception.connection_id == str(connection_id)
    assert reserve_response.service_exception.error_id == "00201"
    assert "Connection not in modifiable state" in caplog.text
    assert reserve_response.service_exception.variables[0].type == "connectionId"
    assert reserve_response.service_exception.variables[0].value == str(connection_id)


def test_reserve_modify_unset_criteria_version(
    pb_reserve_modify_request: ReserveRequest, connection_id: UUID, connection: None, caplog: Any
) -> None:
    """Test the connection provider Reserve Modify returns InvalidTransition exception when not in modifiable state."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    request_correlation_id = pb_reserve_modify_request.header.correlation_id
    # criteria version set to 0, is equivalent to unset (Python ProtoBuf is unable to distinguish)
    pb_reserve_modify_request.criteria.version = 0
    reserve_response = service.Reserve(pb_reserve_modify_request, mock_context)
    assert request_correlation_id == reserve_response.header.correlation_id
    assert not reserve_response.header.reply_to
    assert reserve_response.connection_id == str(connection_id)
    assert not reserve_response.HasField("service_exception")
    # assert that the supplied version 0 was incremented by 1
    assert any(record.msg["event"] == "modify reservation" and record.msg["version"] == 1 for record in caplog.records)
    assert "Schedule reserve" in caplog.text
    assert "Schedule reserve timeout" in caplog.text


def test_reserve_commit(pb_reserve_commit_request: GenericRequest, reserve_held: None, caplog: Any) -> None:
    """Test the connection provider ReserveCommit happy path."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_commit_response = service.ReserveCommit(pb_reserve_commit_request, mock_context)
    assert pb_reserve_commit_request.header.correlation_id == reserve_commit_response.header.correlation_id
    assert not reserve_commit_response.header.reply_to
    assert not reserve_commit_response.HasField("service_exception")
    assert "Cancel reserve timeout" in caplog.text
    assert "Schedule reserve commit" in caplog.text


def test_reserve_commit_random_connection_id(pb_reserve_commit_request: GenericRequest, caplog: Any) -> None:
    """Test the connection provider ReserveCommit returns service exception for random connection id."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    # overwrite connection id from reservation in db with random UUID
    pb_reserve_commit_request.connection_id = str(uuid4())
    reserve_commit_response = service.ReserveCommit(pb_reserve_commit_request, mock_context)
    assert pb_reserve_commit_request.header.correlation_id == reserve_commit_response.header.correlation_id
    assert pb_reserve_commit_request.connection_id == reserve_commit_response.service_exception.connection_id
    assert not reserve_commit_response.header.reply_to
    assert reserve_commit_response.HasField("service_exception")
    assert reserve_commit_response.service_exception.error_id == "00203"
    assert len(reserve_commit_response.service_exception.variables) == 1
    assert reserve_commit_response.service_exception.variables[0].type == "connectionId"
    assert reserve_commit_response.service_exception.variables[0].value == pb_reserve_commit_request.connection_id
    assert "Connection ID does not exist" in caplog.text


def test_reserve_commit_invalid_transition(
    pb_reserve_commit_request: GenericRequest, reserve_committing: None, caplog: Any
) -> None:
    """Test the connection provider ReserveCommit returns service exception when in invalid state for request."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_commit_response = service.ReserveCommit(pb_reserve_commit_request, mock_context)
    assert pb_reserve_commit_request.header.correlation_id == reserve_commit_response.header.correlation_id
    assert pb_reserve_commit_request.connection_id == reserve_commit_response.service_exception.connection_id
    assert not reserve_commit_response.header.reply_to
    assert reserve_commit_response.HasField("service_exception")
    assert reserve_commit_response.service_exception.error_id == "00201"
    assert len(reserve_commit_response.service_exception.variables) == 2
    assert reserve_commit_response.service_exception.variables[0].type == "connectionId"
    assert reserve_commit_response.service_exception.variables[0].value == pb_reserve_commit_request.connection_id
    assert reserve_commit_response.service_exception.variables[1].type == "reservationState"
    assert reserve_commit_response.service_exception.variables[1].value == "RESERVE_COMMITTING"
    assert "Not scheduling ReserveCommitJob" in caplog.text


def test_reserve_commit_timed_out(
    pb_reserve_commit_request: GenericRequest, reserve_held: None, flag_reservation_timeout: None, caplog: Any
) -> None:
    """Test connection provider ReserveCommit returns service exception when reservation was flagged as timed out."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_commit_response = service.ReserveCommit(pb_reserve_commit_request, mock_context)
    assert pb_reserve_commit_request.header.correlation_id == reserve_commit_response.header.correlation_id
    assert pb_reserve_commit_request.connection_id == reserve_commit_response.service_exception.connection_id
    assert not reserve_commit_response.header.reply_to
    assert reserve_commit_response.HasField("service_exception")
    assert reserve_commit_response.service_exception.error_id == "00700"
    assert len(reserve_commit_response.service_exception.variables) == 1
    assert reserve_commit_response.service_exception.variables[0].type == "connectionId"
    assert reserve_commit_response.service_exception.variables[0].value == pb_reserve_commit_request.connection_id
    assert "Cannot commit a timed out reservation" in caplog.text


def test_reserve_abort(
    connection_id: UUID,
    connection_id_modified: None,
    connection: None,
    pb_reserve_abort_request: GenericRequest,
    reserve_held: None,
    caplog: Any,
) -> None:
    """Test the connection provider ReserveAbort happy path."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_abort_response = service.ReserveAbort(pb_reserve_abort_request, mock_context)
    assert pb_reserve_abort_request.header.correlation_id == reserve_abort_response.header.correlation_id
    assert not reserve_abort_response.header.reply_to
    assert not reserve_abort_response.HasField("service_exception")
    assert "Schedule reserve abort" in caplog.text


def test_reserve_abort_random_connection_id(pb_reserve_abort_request: GenericRequest, caplog: Any) -> None:
    """Test the connection provider ReserveAbort returns service exception for random connection id."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    # overwrite connection id from reservation in db with random UUID
    pb_reserve_abort_request.connection_id = str(uuid4())
    reserve_abort_response = service.ReserveAbort(pb_reserve_abort_request, mock_context)
    assert pb_reserve_abort_request.header.correlation_id == reserve_abort_response.header.correlation_id
    assert pb_reserve_abort_request.connection_id == reserve_abort_response.service_exception.connection_id
    assert not reserve_abort_response.header.reply_to
    assert reserve_abort_response.HasField("service_exception")
    assert reserve_abort_response.service_exception.error_id == "00203"
    assert len(reserve_abort_response.service_exception.variables) == 1
    assert reserve_abort_response.service_exception.variables[0].type == "connectionId"
    assert reserve_abort_response.service_exception.variables[0].value == pb_reserve_abort_request.connection_id
    assert "Connection ID does not exist" in caplog.text


def test_reserve_abort_initial_reserve_request(
    connection_id: UUID,
    pb_reserve_abort_request: GenericRequest,
    caplog: Any,
) -> None:
    """Test the connection provider ReserveAbort returns service exception when aborting initial reserve request."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_abort_response = service.ReserveAbort(pb_reserve_abort_request, mock_context)
    assert pb_reserve_abort_request.header.correlation_id == reserve_abort_response.header.correlation_id
    assert pb_reserve_abort_request.connection_id == reserve_abort_response.service_exception.connection_id
    assert not reserve_abort_response.header.reply_to
    assert reserve_abort_response.HasField("service_exception")
    assert reserve_abort_response.service_exception.error_id == "00201"
    assert len(reserve_abort_response.service_exception.variables) == 1
    assert reserve_abort_response.service_exception.variables[0].type == "connectionId"
    assert reserve_abort_response.service_exception.variables[0].value == pb_reserve_abort_request.connection_id
    assert "Cannot abort an initial reserve request, abort only allowed on modify" in caplog.text


def test_reserve_abort_invalid_transition(
    connection_id: UUID,
    connection_id_modified: None,
    connection: None,
    pb_reserve_abort_request: GenericRequest,
    reserve_aborting: None,
    caplog: Any,
) -> None:
    """Test the connection provider ReserveAbort returns service exception when in invalid state for request."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    reserve_abort_response = service.ReserveAbort(pb_reserve_abort_request, mock_context)
    assert pb_reserve_abort_request.header.correlation_id == reserve_abort_response.header.correlation_id
    assert pb_reserve_abort_request.connection_id == reserve_abort_response.service_exception.connection_id
    assert not reserve_abort_response.header.reply_to
    assert reserve_abort_response.HasField("service_exception")
    assert reserve_abort_response.service_exception.error_id == "00201"
    assert len(reserve_abort_response.service_exception.variables) == 2
    assert reserve_abort_response.service_exception.variables[0].type == "connectionId"
    assert reserve_abort_response.service_exception.variables[0].value == pb_reserve_abort_request.connection_id
    assert reserve_abort_response.service_exception.variables[1].type == "reservationState"
    assert reserve_abort_response.service_exception.variables[1].value == "RESERVE_ABORTING"
    assert "Not scheduling ReserveAbortJob" in caplog.text


def test_provision(pb_provision_request: GenericRequest, released: None, caplog: Any) -> None:
    """Test the connection provider Provision happy path."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    provision_response = service.Provision(pb_provision_request, mock_context)
    assert pb_provision_request.header.correlation_id == provision_response.header.correlation_id
    assert not provision_response.header.reply_to
    assert not provision_response.HasField("service_exception")
    assert "Schedule provision" in caplog.text


def test_provision_random_connection_id(pb_provision_request: GenericRequest, caplog: Any) -> None:
    """Test the connection provider Provision returns service exception for random connection id."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    # overwrite connection id from reservation in db with random UUID
    pb_provision_request.connection_id = str(uuid4())
    provision_response = service.Provision(pb_provision_request, mock_context)
    assert pb_provision_request.header.correlation_id == provision_response.header.correlation_id
    assert pb_provision_request.connection_id == provision_response.service_exception.connection_id
    assert not provision_response.header.reply_to
    assert provision_response.HasField("service_exception")
    assert provision_response.service_exception.error_id == "00203"
    assert pb_provision_request.connection_id == provision_response.service_exception.connection_id
    assert len(provision_response.service_exception.variables) == 1
    assert provision_response.service_exception.variables[0].type == "connectionId"
    assert provision_response.service_exception.variables[0].value == pb_provision_request.connection_id
    assert "Connection ID does not exist" in caplog.text


def test_provision_invalid_transition(pb_provision_request: GenericRequest, provisioned: None, caplog: Any) -> None:
    """Test the connection provider Provision returns service exception when in invalid state for request."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    provision_response = service.Provision(pb_provision_request, mock_context)
    assert pb_provision_request.header.correlation_id == provision_response.header.correlation_id
    assert pb_provision_request.connection_id == provision_response.service_exception.connection_id
    assert not provision_response.header.reply_to
    assert provision_response.HasField("service_exception")
    assert provision_response.service_exception.error_id == "00201"
    assert pb_provision_request.connection_id == provision_response.service_exception.connection_id
    assert len(provision_response.service_exception.variables) == 2
    assert provision_response.service_exception.variables[0].type == "connectionId"
    assert provision_response.service_exception.variables[0].value == pb_provision_request.connection_id
    assert provision_response.service_exception.variables[1].type == "provisionState"
    assert provision_response.service_exception.variables[1].value == "PROVISIONED"
    assert "Not scheduling ProvisionJob" in caplog.text


def test_provision_not_committed(pb_provision_request: GenericRequest, reserve_held: None, caplog: Any) -> None:
    """Test the connection provider Provision returns service exception when reservation not committed yet."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    provision_response = service.Provision(pb_provision_request, mock_context)
    assert pb_provision_request.header.correlation_id == provision_response.header.correlation_id
    assert pb_provision_request.connection_id == provision_response.service_exception.connection_id
    assert not provision_response.header.reply_to
    assert provision_response.HasField("service_exception")
    assert provision_response.service_exception.error_id == "00201"
    assert len(provision_response.service_exception.variables) == 2
    assert provision_response.service_exception.variables[0].type == "connectionId"
    assert provision_response.service_exception.variables[0].value == pb_provision_request.connection_id
    assert provision_response.service_exception.variables[1].type == "reservationState"
    assert provision_response.service_exception.variables[1].value == "RESERVE_HELD"
    assert "First version of reservation not committed yet" in caplog.text


def test_provision_passed_end_time(
    pb_provision_request: GenericRequest, connection_id: Column, released: None, caplog: Any
) -> None:
    """Test the connection provider Provision returns service exception when reservation is passed end time."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.schedule.start_time = datetime.now(timezone.utc) - timedelta(hours=2)
        reservation.schedule.end_time = datetime.now(timezone.utc) - timedelta(hours=1)
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    provision_response = service.Provision(pb_provision_request, mock_context)
    assert pb_provision_request.header.correlation_id == provision_response.header.correlation_id
    assert pb_provision_request.connection_id == provision_response.service_exception.connection_id
    assert not provision_response.header.reply_to
    assert provision_response.HasField("service_exception")
    assert provision_response.service_exception.error_id == "00700"
    assert len(provision_response.service_exception.variables) == 1
    assert provision_response.service_exception.variables[0].type == "connectionId"
    assert provision_response.service_exception.variables[0].value == pb_provision_request.connection_id
    assert "Cannot provision a reservation that is passed end time" in caplog.text


def test_release(pb_release_request: GenericRequest, provisioned: None, caplog: Any) -> None:
    """Test the connection provider Release happy path."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    release_response = service.Release(pb_release_request, mock_context)
    assert pb_release_request.header.correlation_id == release_response.header.correlation_id
    assert not release_response.header.reply_to
    assert not release_response.HasField("service_exception")
    assert "Schedule release" in caplog.text


def test_release_random_connection_id(pb_release_request: GenericRequest, caplog: Any) -> None:
    """Test the connection provider Release returns service exception for random connection id."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    # overwrite connection id from reservation in db with random UUID
    pb_release_request.connection_id = str(uuid4())
    release_response = service.Release(pb_release_request, mock_context)
    assert pb_release_request.header.correlation_id == release_response.header.correlation_id
    assert pb_release_request.connection_id == release_response.service_exception.connection_id
    assert not release_response.header.reply_to
    assert release_response.HasField("service_exception")
    assert release_response.service_exception.error_id == "00203"
    assert len(release_response.service_exception.variables) == 1
    assert release_response.service_exception.variables[0].type == "connectionId"
    assert release_response.service_exception.variables[0].value == pb_release_request.connection_id
    assert "Connection ID does not exist" in caplog.text


def test_release_invalid_transition(pb_release_request: GenericRequest, released: None, caplog: Any) -> None:
    """Test the connection provider release returns service exception when in invalid state for request."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    release_response = service.Release(pb_release_request, mock_context)
    assert pb_release_request.header.correlation_id == release_response.header.correlation_id
    assert pb_release_request.connection_id == release_response.service_exception.connection_id
    assert not release_response.header.reply_to
    assert release_response.HasField("service_exception")
    assert release_response.service_exception.error_id == "00201"
    assert len(release_response.service_exception.variables) == 2
    assert release_response.service_exception.variables[0].type == "connectionId"
    assert release_response.service_exception.variables[0].value == pb_release_request.connection_id
    assert release_response.service_exception.variables[1].type == "provisionState"
    assert release_response.service_exception.variables[1].value == "RELEASED"
    assert "Not scheduling ReleaseJob" in caplog.text


def test_release_not_committed(pb_release_request: GenericRequest, reserve_held: None, caplog: Any) -> None:
    """Test the connection provider Release returns service exception when reservation not committed yet."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    release_response = service.Release(pb_release_request, mock_context)
    assert pb_release_request.header.correlation_id == release_response.header.correlation_id
    assert pb_release_request.connection_id == release_response.service_exception.connection_id
    assert not release_response.header.reply_to
    assert release_response.HasField("service_exception")
    assert release_response.service_exception.error_id == "00201"
    assert len(release_response.service_exception.variables) == 2
    assert release_response.service_exception.variables[0].type == "connectionId"
    assert release_response.service_exception.variables[0].value == pb_release_request.connection_id
    assert release_response.service_exception.variables[1].type == "reservationState"
    assert release_response.service_exception.variables[1].value == "RESERVE_HELD"
    assert "First version of reservation not committed yet" in caplog.text


def test_release_passed_end_time(
    pb_release_request: GenericRequest, connection_id: Column, provisioned: None, caplog: Any
) -> None:
    """Test the connection provider Release returns service exception when reservation is passed end time."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.schedule.start_time = datetime.now(timezone.utc) - timedelta(hours=2)
        reservation.schedule.end_time = datetime.now(timezone.utc) - timedelta(hours=1)
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    release_response = service.Release(pb_release_request, mock_context)
    assert pb_release_request.header.correlation_id == release_response.header.correlation_id
    assert pb_release_request.connection_id == release_response.service_exception.connection_id
    assert not release_response.header.reply_to
    assert release_response.HasField("service_exception")
    assert release_response.service_exception.error_id == "00700"
    assert len(release_response.service_exception.variables) == 1
    assert release_response.service_exception.variables[0].type == "connectionId"
    assert release_response.service_exception.variables[0].value == pb_release_request.connection_id
    assert "Cannot release a reservation that is passed end time" in caplog.text


def test_terminate(pb_terminate_request: GenericRequest, provisioned: None, caplog: Any) -> None:
    """Test the connection provider Terminate happy path."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    terminate_response = service.Terminate(pb_terminate_request, mock_context)
    assert pb_terminate_request.header.correlation_id == terminate_response.header.correlation_id
    assert not terminate_response.header.reply_to
    assert not terminate_response.HasField("service_exception")
    assert "Schedule terminate" in caplog.text


def test_terminate_random_connection_id(pb_terminate_request: GenericRequest, caplog: Any) -> None:
    """Test the connection provider Release returns service exception for random connection id."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    # overwrite connection id from reservation in db with random UUID
    pb_terminate_request.connection_id = str(uuid4())
    terminate_response = service.Terminate(pb_terminate_request, mock_context)
    assert pb_terminate_request.header.correlation_id == terminate_response.header.correlation_id
    assert pb_terminate_request.connection_id == terminate_response.service_exception.connection_id
    assert not terminate_response.header.reply_to
    assert terminate_response.HasField("service_exception")
    assert terminate_response.service_exception.error_id == "00203"
    assert len(terminate_response.service_exception.variables) == 1
    assert terminate_response.service_exception.variables[0].type == "connectionId"
    assert terminate_response.service_exception.variables[0].value == pb_terminate_request.connection_id
    assert "Connection ID does not exist" in caplog.text


def test_terminate_invalid_transition(pb_terminate_request: GenericRequest, terminated: None, caplog: Any) -> None:
    """Test the connection provider Release returns service exception for random connection id."""
    service = ConnectionProviderService()
    mock_context = unittest.mock.create_autospec(spec=ServicerContext)
    terminate_response = service.Terminate(pb_terminate_request, mock_context)
    assert pb_terminate_request.header.correlation_id == terminate_response.header.correlation_id
    assert pb_terminate_request.connection_id == terminate_response.service_exception.connection_id
    assert not terminate_response.header.reply_to
    assert terminate_response.HasField("service_exception")
    assert terminate_response.service_exception.error_id == "00201"
    assert len(terminate_response.service_exception.variables) == 2
    assert terminate_response.service_exception.variables[0].type == "connectionId"
    assert terminate_response.service_exception.variables[0].value == pb_terminate_request.connection_id
    assert terminate_response.service_exception.variables[1].type == "lifecycleState"
    assert terminate_response.service_exception.variables[1].value == "TERMINATED"
    assert "Not scheduling TerminateJob" in caplog.text
