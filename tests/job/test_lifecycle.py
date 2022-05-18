from datetime import timedelta
from typing import Any

from sqlalchemy import Column

import tests.shared.state_machine as state_machine

from supa.job.lifecycle import TerminateJob
from supa.util.timestamp import current_timestamp


def test_terminate_job_auto_start(
    connection_id: Column,
    connection: None,
    terminating: None,
    auto_start: None,
    auto_start_job: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test TerminateJob to transition to Terminated and transition data plane to Deactivated."""
    terminate_job = TerminateJob(connection_id)
    terminate_job.__call__()
    assert state_machine.is_deactivated(connection_id)
    assert state_machine.is_terminated(connection_id)
    assert "Terminating reservation" in caplog.text
    assert "Canceled automatic enable of data plane at start time" in caplog.text


def test_terminate_job_auto_end(
    connection_id: Column, connection: None, terminating: None, auto_end: None, get_stub: None, caplog: Any
) -> None:
    """Test TerminateJob to transition to Terminated, add DeactivateJob and canceling AutoEndJob."""
    terminate_job = TerminateJob(connection_id)
    terminate_job.__call__()
    # assert state_machine.is_deactivating(connection_id) # FIXME need DeactivateJob monkey patch
    assert state_machine.is_terminated(connection_id)
    assert "Terminating reservation" in caplog.text
    assert "Canceled automatic disable of data plane at end time" in caplog.text
    assert 'Added job "DeactivateJob" to job store' in caplog.text


def test_terminate_job_activated(
    connection_id: Column, connection: None, terminating: None, activated: None, get_stub: None, caplog: Any
) -> None:
    """Test TerminateJob to transition to Terminated and add DeactivateJob."""
    terminate_job = TerminateJob(connection_id)
    terminate_job.__call__()
    # assert state_machine.is_deactivating(connection_id) # FIXME need DeactivateJob monkey patch
    assert state_machine.is_terminated(connection_id)
    assert "Terminating reservation" in caplog.text
    assert "Canceled automatic disable of data plane at end time" not in caplog.text
    assert 'Added job "DeactivateJob" to job store' in caplog.text


def test_terminate_job_recover(connection_id: Column, terminating: None, get_stub: None, caplog: Any) -> None:
    """Test TerminateJob to recover reservations in state Terminating."""
    terminate_job = TerminateJob(connection_id)
    job_list = terminate_job.recover()
    assert len(job_list) == 1
    assert job_list[0].connection_id == connection_id
    assert state_machine.is_terminating(connection_id)
    msgs = [
        logrecord.msg
        for logrecord in caplog.records
        if "job" in logrecord.msg and logrecord.msg["job"] == "TerminateJob"
    ]
    assert len(msgs) == 1
    assert msgs[0]["connection_id"] == str(connection_id)
    assert msgs[0]["event"] == "Recovering job"


def test_terminate_job_trigger(connection_id: Column, caplog: Any) -> None:
    """Test TerminateJob to return trigger to run immediately."""
    terminate_job = TerminateJob(connection_id)
    job_trigger = terminate_job.trigger()
    assert current_timestamp() - job_trigger.run_date < timedelta(seconds=5)  # more or less now
