from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from supa.connection import requester
from supa.grpc_nsi.connection_common_pb2 import Header
from supa.grpc_nsi.connection_requester_pb2 import ErrorRequest
from supa.grpc_nsi.connection_requester_pb2_grpc import ConnectionRequesterStub
from supa.job.resend import RESEND_DELAY, RESULT_MESSAGES, ResendResultJob
from supa.job.shared import register_result
from supa.util.timestamp import current_timestamp
from supa.util.type import ResultType


@pytest.fixture()
def stub(monkeypatch: Any) -> ConnectionRequesterStub:
    """Replace the requester stub with a real one on a mock channel, so only calls it really has can be made."""
    channel = MagicMock()
    channel.unary_unary.side_effect = lambda *args, **kwargs: MagicMock()
    real_stub = ConnectionRequesterStub(channel)
    monkeypatch.setattr(requester, "get_stub", lambda: real_stub)
    return real_stub


def called(stub: ConnectionRequesterStub) -> list[str]:
    """Return the names of the calls that were made on the stub."""
    return [name for name, rpc in vars(stub).items() if rpc.called]


def make_result(result_type: ResultType, connection_id: UUID) -> Any:
    """Build the message that a job stores as the result of a request, with a new correlation ID."""
    message = RESULT_MESSAGES[result_type]()
    message.header.CopyFrom(Header(correlation_id=uuid4().urn))
    match message:
        case ErrorRequest():
            message.service_exception.connection_id = str(connection_id)
        case _:
            message.connection_id = str(connection_id)
    return message


@pytest.mark.parametrize("result_type", list(ResultType))
def test_resend_result_job_sends_the_stored_result(
    result_type: ResultType, connection_id: UUID, stub: ConnectionRequesterStub
) -> None:
    """Test the stored result of every type goes to the requester again, as the call that sent it before."""
    message = make_result(result_type, connection_id)
    register_result(message, result_type)

    ResendResultJob(UUID(message.header.correlation_id))()

    assert called(stub) == [result_type.value]
    getattr(stub, result_type.value).assert_called_once_with(message)


def test_resend_result_job_without_result_sends_nothing(stub: ConnectionRequesterStub, caplog: Any) -> None:
    """Test a request without a result yet is left to the job that is still processing it."""
    ResendResultJob(uuid4())()

    assert called(stub) == []
    assert "No result yet" in caplog.text


def test_resend_result_job_id_names_the_job_and_the_request() -> None:
    """Test the job ID is of the form the scheduler's error listener splits, and not random."""
    correlation_id = uuid4()

    assert ResendResultJob(correlation_id).job_id == f"ResendResultJob={correlation_id}"


def test_resend_result_job_trigger_waits_for_the_acknowledgement() -> None:
    """Test the result is sent shortly after the repeated request is acknowledged, not at once."""
    before = current_timestamp()
    trigger = ResendResultJob(uuid4()).trigger()
    after = current_timestamp()

    assert before + timedelta(seconds=RESEND_DELAY) <= trigger.run_date <= after + timedelta(seconds=RESEND_DELAY)


def test_resend_result_job_recover() -> None:
    """Test there is nothing to recover, the requester sends its request again if it gets no result."""
    assert ResendResultJob.recover() == []
