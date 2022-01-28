from typing import Any

from sqlalchemy import Column

import tests.shared.state_machine as state_machine

from supa.db.model import Reservation
from supa.job.dataplane import ActivateJob, AutoEndJob, AutoStartJob, DeactivateJob
from supa.util.timestamp import NO_END_DATE


def test_activate_job_end_date(connection_id: Column, activating: None, get_stub: None, caplog: Any) -> None:
    """Test AutoEndJob to transition to AutoEnd."""
    activate_job = ActivateJob(connection_id)
    activate_job.__call__()
    assert state_machine.is_auto_end(connection_id)
    assert "Activating data plane" in caplog.text
    assert "Automatic disable of data plane at" in caplog.text
    assert 'Added job "AutoEndJob" to job store' in caplog.text


def test_activate_job_no_end_date(connection_id: Column, activating: None, get_stub: None, caplog: Any) -> None:
    """Test AutoEndJob to transition to Activated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.end_time = NO_END_DATE
    activate_job = ActivateJob(connection_id)
    activate_job.__call__()
    assert state_machine.is_activated(connection_id)
    assert "Activating data plane" in caplog.text
    assert "Automatic disable of data plane at" not in caplog.text
    assert 'Added job "AutoEndJob" to job store' not in caplog.text


def test_deactivate_job(connection_id: Column, deactivating: None, get_stub: None, caplog: Any) -> None:
    """Test AutoEndJob to transition to Deactivated."""
    deactivate_job = DeactivateJob(connection_id)
    deactivate_job.__call__()
    assert state_machine.is_deactivated(connection_id)
    assert "Deactivating data plane" in caplog.text


def test_auto_start_job(connection_id: Column, auto_start: None, get_stub: None, caplog: Any) -> None:
    """Test AutoStartJob to transition to Activating."""
    auto_start_job = AutoStartJob(connection_id)
    auto_start_job.__call__()
    assert state_machine.is_activating(connection_id)
    assert 'Added job "ActivateJob" to job store' in caplog.text


def test_auto_end_job(connection_id: Column, auto_end: None, get_stub: None, caplog: Any) -> None:
    """Test AutoEndJob to transition to Deactivating and PassedEndTime."""
    auto_end_job = AutoEndJob(connection_id)
    auto_end_job.__call__()
    # Cannot really check the state because AutoEndJob schedules a DeactivateJob that also manipulates the state,
    # making this a flaky test.
    # assert state_machine.is_deactivating(connection_id)
    # assert state_machine.passed_end_time(connection_id)
    assert 'Added job "DeactivateJob" to job store' in caplog.text
