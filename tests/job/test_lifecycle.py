from typing import Any

from sqlalchemy import Column

import tests.shared.state_machine as state_machine

from supa.job.lifecycle import TerminateJob


def test_terminate_job_auto_start(
    connection_id: Column, terminating: None, auto_start: None, auto_start_job: None, get_stub: None, caplog: Any
) -> None:
    """Test TerminateJob to transition to Terminated and transition data plane to Deactivated."""
    terminate_job = TerminateJob(connection_id)
    terminate_job.__call__()
    assert state_machine.is_deactivated(connection_id)
    assert state_machine.is_terminated(connection_id)
    assert "Terminating reservation" in caplog.text
    assert "Canceled automatic enable of data plane at start time" in caplog.text


def test_terminate_job_auto_end(
    connection_id: Column, terminating: None, auto_end: None, get_stub: None, caplog: Any
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
    connection_id: Column, terminating: None, activated: None, get_stub: None, caplog: Any
) -> None:
    """Test TerminateJob to transition to Terminated and add DeactivateJob."""
    terminate_job = TerminateJob(connection_id)
    terminate_job.__call__()
    # assert state_machine.is_deactivating(connection_id) # FIXME need DeactivateJob monkey patch
    assert state_machine.is_terminated(connection_id)
    assert "Terminating reservation" in caplog.text
    assert "Canceled automatic disable of data plane at end time" not in caplog.text
    assert 'Added job "DeactivateJob" to job store' in caplog.text
