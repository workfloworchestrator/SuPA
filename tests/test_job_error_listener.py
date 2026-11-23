import logging
from typing import Any
from uuid import uuid4

import grpc
import pytest
from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent

from supa import _job_error_event_listener
from supa.util.timestamp import current_timestamp


class FakeRpcError(grpc.RpcError):
    """A failed call to the requester, which is what makes a job fail on its scheduler thread."""

    def details(self) -> str:
        """Return the text that the listener logs."""
        return "requester unreachable"


@pytest.mark.parametrize(
    ("job_id", "expected_level", "connection_logged"),
    [
        pytest.param(f"ReserveJob={uuid4()}", logging.WARNING, True, id="job-of-a-connection"),
        pytest.param("HealthCheckJob", logging.ERROR, False, id="job-without-a-connection"),
    ],
)
def test_job_error_event_listener_logs_the_error_of_the_job(
    job_id: str, expected_level: int, connection_logged: bool, caplog: Any
) -> None:
    """Test that a job that failed is logged as a warning when it has a connection, and as an error when it has not."""
    event = JobExecutionEvent(EVENT_JOB_ERROR, job_id, "default", current_timestamp(), exception=FakeRpcError())

    _job_error_event_listener(event)

    [record] = [record for record in caplog.records if record.name == "supa"]
    assert record.levelno == expected_level
    assert record.msg["event"] == "requester unreachable"
    assert ("connection_id" in record.msg) == connection_logged
