import threading
from concurrent import futures
from datetime import datetime, timedelta, timezone
from typing import Any, Generator
from uuid import uuid4

import grpc
import pytest
import structlog

from supa import const, settings
from supa.connection.error import GenericMessagePayLoadError, InvalidTransition, StpUnavailable
from supa.grpc_nsi.connection_common_pb2 import GenericAcknowledgment, Header, Schedule
from supa.grpc_nsi.connection_provider_pb2 import (
    GenericRequest,
    ReservationRequestCriteria,
    ReserveRequest,
    ReserveResponse,
)
from supa.grpc_nsi.connection_provider_pb2_grpc import ConnectionProviderStub
from supa.grpc_nsi.connection_requester_pb2 import (
    ErrorRequest,
    GenericConfirmedRequest,
    GenericFailedRequest,
    ReserveConfirmedRequest,
)
from supa.grpc_nsi.connection_requester_pb2_grpc import (
    ConnectionRequesterServicer,
    add_ConnectionRequesterServicer_to_server,
)
from supa.grpc_nsi.services_pb2 import PointToPointService

logger = structlog.get_logger(__name__)


@pytest.fixture(scope="module")
def provider() -> ConnectionProviderStub:
    """Get the connection provider stub."""
    channel = grpc.insecure_channel(f"{settings.grpc_server_insecure_host}:{settings.grpc_server_insecure_port}")
    stub = ConnectionProviderStub(channel)
    return stub


class AsyncResult:
    """Pass asynchronous messages, synchronised with locks, between provider and requester."""

    def __init__(self) -> None:
        """Create new AsyncResult instance with locks and block read."""
        self.value = None
        self.read_lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.read_lock.acquire()

    def write(self, value: Any) -> None:
        """Acquire write lock, add message, and then allow it to be read."""
        self.write_lock.acquire()
        self.value = value
        self.read_lock.release()

    def read(self) -> Any:
        """Acquire read lock (wait a maximum of 5 seconds), get message, and then allow a new one to be written."""
        if self.read_lock.acquire(timeout=5):
            value = self.value
            self.value = None
            self.write_lock.release()
            return value
        else:
            return None


async_result = AsyncResult()


class ConnectionRequesterService(ConnectionRequesterServicer):
    """Connection requester service implementation, will just pass message through async_result to requester."""

    def ReserveConfirmed(self, request: ReserveConfirmedRequest, context: Any) -> GenericAcknowledgment:
        """Receive a ReserveConfirmed message and store in async_result."""
        async_result.write(request)
        return GenericAcknowledgment(header=request.header)

    def ReserveFailed(self, request: GenericFailedRequest, context: Any) -> GenericAcknowledgment:
        """Receive a ReserveFailed message and store in async_result."""
        async_result.write(request)
        return GenericAcknowledgment(header=request.header)

    def ReserveCommitConfirmed(self, request: GenericConfirmedRequest, context: Any) -> GenericAcknowledgment:
        """Receive a ReserveCommitConfirmed message and store in async_result."""
        async_result.write(request)
        return GenericAcknowledgment(header=request.header)

    def ProvisionConfirmed(self, request: GenericConfirmedRequest, context: Any) -> GenericAcknowledgment:
        """Receive a ProvisionConfirmed message and store in async_result."""
        async_result.write(request)
        return GenericAcknowledgment(header=request.header)

    def ReleaseConfirmed(self, request: GenericConfirmedRequest, context: Any) -> GenericAcknowledgment:
        """Receive a ReleaseConfirmed message and store in async_result."""
        async_result.write(request)
        return GenericAcknowledgment(header=request.header)

    def TerminateConfirmed(self, request: GenericConfirmedRequest, context: Any) -> GenericAcknowledgment:
        """Receive a TerminateConfirmed message and store in async_result."""
        async_result.write(request)
        return GenericAcknowledgment(header=request.header)

    def Error(self, request: ErrorRequest, context: Any) -> GenericAcknowledgment:
        """Receive an Error message and store in async_result."""
        async_result.write(request)
        return GenericAcknowledgment(header=request.header)


@pytest.fixture(scope="module", autouse=True)
def connection_requester_service(thread_pool_executor: futures.ThreadPoolExecutor) -> Generator[None, Any, None]:
    """Start the connection requester service."""
    grpc_server = grpc.server(thread_pool_executor)

    def run_server() -> None:
        add_ConnectionRequesterServicer_to_server(ConnectionRequesterService(), grpc_server)
        grpc_server.add_insecure_port(f"{settings.grpc_client_insecure_host}:{settings.grpc_client_insecure_port}")
        grpc_server.start()
        grpc_server.wait_for_termination()

    thread = threading.Thread(target=run_server)
    thread.start()
    yield
    grpc_server.stop(0)


def pb_header(**kwargs: str | int | bool | datetime) -> Header:
    """Create protobuf header with unique correlation_id."""
    return Header(
        protocol_version=kwargs.get("protocol_version", "application/vnd.ogf.nsi.cs.v2.provider+soap"),
        correlation_id=kwargs.get("correlation_id", uuid4().urn),
        requester_nsa=kwargs.get("requester_nsa", "urn:ogf:network:surf.nl:2020:onsaclient"),
        provider_nsa=kwargs.get("provider_nsa", settings.nsa_id),
        reply_to=kwargs.get("reply_to", "http://127.0.0.1:7080/NSI/services/RequesterService2"),
    )


def pb_schedule(**kwargs: str | int | bool | datetime) -> Schedule:
    """Create protobuf schedule with start time now+1hour and end time now+2hours."""
    schedule = Schedule()
    schedule.start_time.FromDatetime(kwargs.get("start_time", datetime.now(timezone.utc) + timedelta(hours=1)))
    schedule.end_time.FromDatetime(kwargs.get("end_time", datetime.now(timezone.utc) + timedelta(hours=2)))
    return schedule


def pb_ptps(**kwargs: str | int | bool | datetime) -> PointToPointService:
    """Create protobuf point-to-point-service with standard STPs."""
    return PointToPointService(
        capacity=kwargs.get("capacity", 10),
        symmetric_path=kwargs.get("symmetric_path", True),
        source_stp=kwargs.get("source_stp", "urn:ogf:network:example.domain:2001:topology:port1?vlan=1784"),
        dest_stp=kwargs.get("dest_stp", "urn:ogf:network:example.domain:2001:topology:port2?vlan=1784"),
        # The initial version didn't have to support Explicit Routing Objects.
        # for param in reservation.parameters:
        #    pb_ptps.parameters[param.key] = param.value
    )


def pb_reservation_request_criteria(**kwargs: str | int | bool | datetime) -> ReservationRequestCriteria:
    """Create protobuf criteria with filled in schedule and point-to-point-service."""
    reservation_request_criteria = ReservationRequestCriteria()
    reservation_request_criteria.schedule.CopyFrom(pb_schedule(**kwargs))
    reservation_request_criteria.service_type = kwargs.get("service_type", const.SERVICE_TYPE)
    reservation_request_criteria.ptps.CopyFrom(pb_ptps(**kwargs))
    reservation_request_criteria.version = kwargs.get("version", 1)
    return reservation_request_criteria


def pb_reserve_request(**kwargs: str | int | bool | datetime) -> ReserveRequest:
    """Create protobuf reserve request with filled in header and criteria."""
    pb_request = ReserveRequest()
    pb_request.header.CopyFrom(pb_header(**kwargs))
    pb_request.description = kwargs.get("description", "reserve request")
    pb_request.global_reservation_id = kwargs.get("global_reservation_id", uuid4().urn)
    pb_request.criteria.CopyFrom(pb_reservation_request_criteria(**kwargs))
    pb_request.connection_id = kwargs.get("connection_id", "")
    # pb_request.connection_id = ""  # if modify
    return pb_request


def pb_modify_request(connection_id: str, **kwargs: str | int | bool | datetime) -> ReserveRequest:
    """Create protobuf modify request with modified start and end time or capacity."""
    # return pb_reserve_request(
    #     **{
    #         "description": kwargs.get("description", ""),
    #         "global_reservation_id": kwargs.get("global_reservation_id", ""),
    #         "connection_id": kwargs.get("connection_id", ""),
    #         "protocol_version": kwargs.get("protocol_version", ""),
    #         "service_type": kwargs.get("service_type", ""),
    #         "version": kwargs.get("version", 1),
    #         "start_time": kwargs.get("start_time", datetime.fromtimestamp(0, timezone.utc)),
    #         "end_time": kwargs.get("end_time", datetime.fromtimestamp(0, timezone.utc)),
    #         "capacity": kwargs.get("capacity", 0),
    #         "symmetric_path": kwargs.get("symmetric_path", False),
    #         "source_stp": kwargs.get("source_stp", ""),
    #         "dest_stp": kwargs.get("dest_stp", ""),
    #     }
    # )
    pb_request = ReserveRequest()
    pb_request.header.CopyFrom(pb_header(**kwargs))
    pb_request.connection_id = connection_id
    reservation_request_criteria = ReservationRequestCriteria()
    start_time = kwargs.get("start_time")
    end_time = kwargs.get("end_time")
    if start_time or end_time:
        schedule = Schedule()
        if start_time:
            schedule.start_time.FromDatetime(start_time)
        if end_time:
            schedule.end_time.FromDatetime(end_time)
        reservation_request_criteria.schedule.CopyFrom(schedule)
    if capacity := kwargs.get("capacity"):
        reservation_request_criteria.ptps.CopyFrom(PointToPointService(capacity=capacity))
    reservation_request_criteria.version = kwargs.get("version", 1)
    pb_request.criteria.CopyFrom(reservation_request_criteria)
    return pb_request


def pb_generic_request(connection_id: str, **kwargs: str | int | bool | datetime) -> GenericRequest:
    """Create protobuf generic request with filled in header and connection id."""
    pb_request = GenericRequest(connection_id=connection_id)
    pb_request.header.CopyFrom(pb_header(**kwargs))
    return pb_request


def verify_headers(request_header: Header, response_header: Header) -> None:
    """Verify that the request and response headers match."""
    assert request_header.protocol_version == response_header.protocol_version
    assert request_header.correlation_id == response_header.correlation_id
    assert request_header.requester_nsa == response_header.requester_nsa
    assert request_header.provider_nsa == response_header.provider_nsa
    assert not response_header.reply_to


def reserve(
    stub: ConnectionProviderStub, async_error_id: str = "", **kwargs: str | int | bool | datetime
) -> ReserveResponse:
    """Send Reserve to provider and verify the synchronous and asynchronous responses."""
    reserve_request = pb_reserve_request(**kwargs)
    reserve_response = stub.Reserve(reserve_request)
    verify_headers(reserve_request.header, reserve_response.header)
    assert type(reserve_response) is ReserveResponse
    assert not reserve_response.HasField("service_exception")
    async_reply = async_result.read()
    if async_error_id:
        assert type(async_reply) is GenericFailedRequest
        assert async_reply.service_exception.error_id == async_error_id
    else:
        assert type(async_reply) is ReserveConfirmedRequest
    assert reserve_response.connection_id == async_reply.connection_id
    # TODO: add verification of returned criteria
    return async_reply


def modify(
    stub: ConnectionProviderStub,
    connection_id: str,
    error_id: str = "",
    async_error_id: str = "",
    **kwargs: str | int | bool | datetime,
) -> GenericFailedRequest | ReserveResponse:
    """Send modify to provider and verify the synchronous and asynchronous responses."""
    modify_request = pb_modify_request(connection_id, **kwargs)
    modify_response = stub.Reserve(modify_request)
    verify_headers(modify_request.header, modify_response.header)
    assert type(modify_response) is ReserveResponse
    if error_id:
        assert modify_response.HasField("service_exception")
        assert modify_response.service_exception.error_id == error_id
        return modify_response
    else:
        assert not modify_response.HasField("service_exception")
        async_reply = async_result.read()
        if async_error_id:
            assert type(async_reply) is GenericFailedRequest
            assert async_reply.service_exception.error_id == async_error_id
        else:
            assert type(async_reply) is ReserveConfirmedRequest
        assert modify_response.connection_id == async_reply.connection_id
        # TODO: add verification of returned criteria
        return async_reply


def get_and_verify_async_reply(
    request: GenericRequest, response: GenericAcknowledgment, async_error_id: str = ""
) -> GenericConfirmedRequest:
    """Verify the generic synchronous and asynchronous responses, works for all requests except Reserve."""
    verify_headers(request.header, response.header)
    assert type(response) is GenericAcknowledgment
    assert not response.HasField("service_exception")
    async_reply = async_result.read()
    if async_error_id:
        assert type(async_reply) is GenericFailedRequest
        assert async_reply.service_exception.error_id == async_error_id
    else:
        assert type(async_reply) is GenericConfirmedRequest
    assert request.connection_id == async_reply.connection_id
    return async_reply


def reserve_commit(
    stub: ConnectionProviderStub, connection_id: str, async_error_id: str = "", **kwargs: str | int | bool | datetime
) -> GenericConfirmedRequest:
    """Send ReserveCommit to provider and verify the synchronous and asynchronous responses."""
    reserve_commit_request = pb_generic_request(connection_id, **kwargs)
    reserve_commit_response = stub.ReserveCommit(reserve_commit_request)
    return get_and_verify_async_reply(reserve_commit_request, reserve_commit_response, async_error_id)


def provision(
    stub: ConnectionProviderStub, connection_id: str, async_error_id: str = "", **kwargs: str | int | bool | datetime
) -> GenericConfirmedRequest:
    """Send Provision to provider and verify the synchronous and asynchronous responses."""
    provision_request = pb_generic_request(connection_id, **kwargs)
    provision_response = stub.Provision(provision_request)
    return get_and_verify_async_reply(provision_request, provision_response, async_error_id)


def release(
    stub: ConnectionProviderStub, connection_id: str, async_error_id: str = "", **kwargs: str | int | bool | datetime
) -> GenericConfirmedRequest:
    """Send Release to provider and verify the synchronous and asynchronous responses."""
    release_request = pb_generic_request(connection_id, **kwargs)
    release_response = stub.Release(release_request)
    return get_and_verify_async_reply(release_request, release_response, async_error_id)


def terminate(
    stub: ConnectionProviderStub, connection_id: str, **kwargs: str | int | bool | datetime
) -> GenericConfirmedRequest:
    """Send Terminate to provider and verify the synchronous and asynchronous responses."""
    terminate_request = pb_generic_request(connection_id, **kwargs)
    terminate_response = stub.Terminate(terminate_request)
    return get_and_verify_async_reply(terminate_request, terminate_response)  # Cannot return GenericFailedRequest


def test_reserve_terminate(provider: ConnectionProviderStub) -> None:
    """Verify that available resources can be held and terminated."""
    reserve_response = reserve(provider)
    terminate_response = terminate(provider, reserve_response.connection_id)
    assert reserve_response.connection_id == terminate_response.connection_id


def test_reserve_commit_terminate(provider: ConnectionProviderStub) -> None:
    """Verify that available resources can be committed and terminated."""
    reserve_response = reserve(provider)
    reserve_commit_response = reserve_commit(provider, reserve_response.connection_id)
    terminate_response = terminate(provider, reserve_response.connection_id)
    assert reserve_response.connection_id == reserve_commit_response.connection_id
    assert reserve_response.connection_id == terminate_response.connection_id


def test_reserve_commit_provision_terminate(provider: ConnectionProviderStub) -> None:
    """Verify that available resources can be provisioned and terminated."""
    reserve_response = reserve(provider)
    reserve_commit_response = reserve_commit(provider, reserve_response.connection_id)
    provision_response = provision(provider, reserve_response.connection_id)
    terminate_response = terminate(provider, reserve_response.connection_id)
    assert reserve_response.connection_id == reserve_commit_response.connection_id
    assert reserve_response.connection_id == provision_response.connection_id
    assert reserve_response.connection_id == terminate_response.connection_id


def test_reserve_commit_provision_release_terminate(provider: ConnectionProviderStub) -> None:
    """Verify that available resources can be provisioned, released and terminated."""
    reserve_response = reserve(provider)
    reserve_commit_response = reserve_commit(provider, reserve_response.connection_id)
    provision_response = provision(provider, reserve_response.connection_id)
    release_response = release(provider, reserve_response.connection_id)
    terminate_response = terminate(provider, reserve_response.connection_id)
    assert reserve_response.connection_id == reserve_commit_response.connection_id
    assert reserve_response.connection_id == provision_response.connection_id
    assert reserve_response.connection_id == release_response.connection_id
    assert reserve_response.connection_id == terminate_response.connection_id


def test_cannot_reserve_held_or_reserved_resources(provider: ConnectionProviderStub) -> None:
    """Verify that any kind of reserved resources cannot be reserved until they are terminated."""
    # verify that reserving held resources fails
    reserve_response = reserve(provider)
    reserve(provider, async_error_id=StpUnavailable.error_id)
    # verify that reserving committed resources fails
    reserve_commit_response = reserve_commit(provider, reserve_response.connection_id)
    assert reserve_response.connection_id == reserve_commit_response.connection_id
    reserve(provider, async_error_id=StpUnavailable.error_id)
    # verify that reserving provisioned resources fails
    provision_response = provision(provider, reserve_response.connection_id)
    assert reserve_response.connection_id == provision_response.connection_id
    reserve(provider, async_error_id=StpUnavailable.error_id)
    # verify that reserving released resources fails
    release_response = release(provider, reserve_response.connection_id)
    assert reserve_response.connection_id == release_response.connection_id
    reserve(provider, async_error_id=StpUnavailable.error_id)
    # verify that reserving terminated resources succeeds
    terminate_response = terminate(provider, reserve_response.connection_id)
    assert reserve_response.connection_id == terminate_response.connection_id
    reserve_confirmed_response = reserve(provider)
    # terminated reserved resources that were terminated earlier
    terminate_confirmed_response = terminate(provider, reserve_confirmed_response.connection_id)
    assert reserve_confirmed_response.connection_id == terminate_confirmed_response.connection_id


def test_reserve_commit_modify_terminate(provider: ConnectionProviderStub) -> None:
    """Verify that available resources can be committed, modified and terminated."""
    start_time = datetime.now() + timedelta(minutes=30)
    reserve_response = reserve(provider, version=1, start_time=start_time)
    reserve_commit_response = reserve_commit(provider, reserve_response.connection_id)
    start_time += timedelta(minutes=15)
    modify_response = modify(provider, reserve_response.connection_id, version=2, start_time=start_time)
    assert modify_response.criteria.version == 2
    assert modify_response.criteria.schedule.start_time.ToDatetime() == start_time
    terminate_response = terminate(provider, reserve_response.connection_id)
    assert reserve_response.connection_id == reserve_commit_response.connection_id
    assert reserve_response.connection_id == modify_response.connection_id
    assert reserve_response.connection_id == terminate_response.connection_id


def test_reserve_modify_failes(provider: ConnectionProviderStub) -> None:
    """Verify that available resources can be committed, modified and terminated."""
    reserve_response = reserve(provider, version=1)
    modify_response = modify(provider, reserve_response.connection_id, error_id=InvalidTransition.error_id, version=2)
    assert modify_response.service_exception.connection_id == reserve_response.connection_id
    terminate_response = terminate(provider, reserve_response.connection_id)
    assert reserve_response.connection_id == terminate_response.connection_id


def test_reserve_commit_terminate_modify_failes(provider: ConnectionProviderStub) -> None:
    """Verify that available resources can be committed, modified and terminated."""
    reserve_response = reserve(provider, version=1)
    reserve_commit_response = reserve_commit(provider, reserve_response.connection_id)
    terminate_response = terminate(provider, reserve_response.connection_id)
    modify_response = modify(provider, reserve_response.connection_id, error_id=InvalidTransition.error_id, version=2)
    assert modify_response.service_exception.connection_id == reserve_response.connection_id
    assert reserve_response.connection_id == terminate_response.connection_id
    assert reserve_response.connection_id == reserve_commit_response.connection_id
    assert reserve_response.connection_id == terminate_response.connection_id


def test_modify_unsuported_value_fails(provider: ConnectionProviderStub) -> None:
    """Verify that unsupported values in modify are handled correctly."""

    def modify(provider: ConnectionProviderStub, request: ReserveRequest, error_id: str) -> None:
        response = provider.Reserve(request)
        assert response.HasField("service_exception")
        assert response.service_exception.error_id == error_id

    # reserve and commit reservation
    reserve_response = reserve(provider, version=1)
    reserve_commit_response = reserve_commit(provider, reserve_response.connection_id)
    assert reserve_response.connection_id == reserve_commit_response.connection_id
    modify_request = pb_modify_request(connection_id=reserve_response.connection_id, version=2)
    # try to modify description
    modify_request.description = "my new description"
    modify(provider, modify_request, GenericMessagePayLoadError.error_id)
    modify_request.ClearField("description")
    # try to modify global_reservation_id
    modify_request.global_reservation_id = uuid4().urn
    modify(provider, modify_request, GenericMessagePayLoadError.error_id)
    modify_request.ClearField("global_reservation_id")
    # try to modify service_type
    modify_request.criteria.service_type = "my new service_type"
    modify(provider, modify_request, GenericMessagePayLoadError.error_id)
    modify_request.criteria.ClearField("service_type")
    # try to modify source_stp
    modify_request.criteria.ptps.source_stp = "urn:ogf:network:example.domain:2001:topology:port1?vlan=1785"
    modify(provider, modify_request, GenericMessagePayLoadError.error_id)
    modify_request.criteria.ptps.ClearField("source_stp")
    # try to modify dest_stp
    modify_request.criteria.ptps.dest_stp = "urn:ogf:network:example.domain:2001:topology:port1?vlan=1785"
    modify(provider, modify_request, GenericMessagePayLoadError.error_id)
    modify_request.criteria.ptps.ClearField("dest_stp")
    # try to modify symmetric_path
    modify_request.criteria.ptps.symmetric_path = True
    modify(provider, modify_request, GenericMessagePayLoadError.error_id)
    modify_request.criteria.ptps.ClearField("symmetric_path")
