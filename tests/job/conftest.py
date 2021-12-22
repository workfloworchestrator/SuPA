from typing import Any

import pytest

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
