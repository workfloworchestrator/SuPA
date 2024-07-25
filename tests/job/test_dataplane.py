from datetime import timedelta
from typing import Any
from uuid import UUID

import tests.shared.state_machine as state_machine

from supa.db.model import Reservation
from supa.job.dataplane import ActivateJob, AutoEndJob, AutoStartJob, DeactivateJob
from supa.util.timestamp import NO_END_DATE, current_timestamp


def test_activate_job_end_date(
    connection_id: UUID, connection: None, activating: None, get_stub: None, caplog: Any
) -> None:
    """Test ActivateJob to transition to AutoEnd."""
    activate_job = ActivateJob(connection_id)
    activate_job.__call__()
    assert state_machine.is_auto_end(connection_id)
    assert "Activate data plane" in caplog.text
    assert "Schedule auto end" in caplog.text


def test_activate_job_no_end_date(
    connection_id: UUID, connection: None, activating: None, get_stub: None, caplog: Any
) -> None:
    """Test ActivateJob to transition to Activated when no end date."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.schedule.end_time = NO_END_DATE
    activate_job = ActivateJob(connection_id)
    activate_job.__call__()
    assert state_machine.is_activated(connection_id)
    assert "Activate data plane" in caplog.text
    assert "Schedule auto end" not in caplog.text


def test_activate_job_recover(connection_id: UUID, activating: None, get_stub: None, caplog: Any) -> None:
    """Test ActivateJob to recover reservations in state Created and Activating and are not passed end time."""
    activate_job = ActivateJob(connection_id)
    job_list = activate_job.recover()
    assert len(job_list) == 1
    assert job_list[0].connection_id == connection_id
    assert state_machine.is_activating(connection_id)
    msgs = [
        logrecord.msg
        for logrecord in caplog.records
        if "job" in logrecord.msg and logrecord.msg["job"] == "ActivateJob"
    ]
    assert len(msgs) == 1
    assert msgs[0]["connection_id"] == str(connection_id)
    assert msgs[0]["event"] == "Recovering job"


def test_activate_job_trigger(connection_id: UUID, caplog: Any) -> None:
    """Test ActivateJob to return trigger to run immediately."""
    terminate_job = ActivateJob(connection_id)
    job_trigger = terminate_job.trigger()
    assert current_timestamp() - job_trigger.run_date < timedelta(seconds=5)  # more or less now


def test_deactivate_job(connection_id: UUID, connection: None, deactivating: None, get_stub: None, caplog: Any) -> None:
    """Test DeactivateJob to transition to Deactivated."""
    deactivate_job = DeactivateJob(connection_id)
    deactivate_job.__call__()
    assert state_machine.is_deactivated(connection_id)
    assert "Deactivate data plane" in caplog.text


def test_deactivate_job_recover(connection_id: UUID, deactivating: None, get_stub: None, caplog: Any) -> None:
    """Test DectivateJob to recover reservations in state Created and Deactivating."""
    deactivate_job = DeactivateJob(connection_id)
    job_list = deactivate_job.recover()
    assert len(job_list) == 1
    assert job_list[0].connection_id == connection_id
    assert state_machine.is_deactivating(connection_id)
    msgs = [
        logrecord.msg
        for logrecord in caplog.records
        if "job" in logrecord.msg and logrecord.msg["job"] == "DeactivateJob"
    ]
    assert len(msgs) == 1
    assert msgs[0]["connection_id"] == str(connection_id)
    assert msgs[0]["event"] == "Recovering job"


def test_deactivate_job_trigger(connection_id: UUID, caplog: Any) -> None:
    """Test DeactivateJob to return trigger to run immediately."""
    terminate_job = DeactivateJob(connection_id)
    job_trigger = terminate_job.trigger()
    assert current_timestamp() - job_trigger.run_date < timedelta(seconds=5)  # more or less now


def test_auto_start_job(connection_id: UUID, auto_start: None, get_stub: None, caplog: Any) -> None:
    """Test AutoStartJob to transition to Activating."""
    auto_start_job = AutoStartJob(connection_id)
    auto_start_job.__call__()
    assert state_machine.is_activating(connection_id)
    assert "Schedule activate" in caplog.text


def test_auto_start_job_recover(connection_id: UUID, auto_start: None, get_stub: None, caplog: Any) -> None:
    """Test AutoStartJob to recover reservations in state Created and AutoStart and not passed end time."""
    auto_start_job = AutoStartJob(connection_id)
    job_list = auto_start_job.recover()
    assert len(job_list) == 1
    assert job_list[0].connection_id == connection_id
    assert state_machine.is_auto_start(connection_id)
    msgs = [
        logrecord.msg
        for logrecord in caplog.records
        if "job" in logrecord.msg and logrecord.msg["job"] == "AutoStartJob"
    ]
    assert len(msgs) == 1
    assert msgs[0]["connection_id"] == str(connection_id)
    assert msgs[0]["event"] == "Recovering job"


def test_auto_start_job_trigger(connection_id: UUID, caplog: Any) -> None:
    """Test AutoStartJob to return trigger with start time of reservation."""
    auto_start_job = AutoStartJob(connection_id)
    job_trigger = auto_start_job.trigger()

    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        assert job_trigger.run_date == reservation.schedule.start_time


def test_auto_end_job(connection_id: UUID, auto_end: None, get_stub: None, caplog: Any) -> None:
    """Test AutoEndJob to transition to Deactivating and PassedEndTime."""
    auto_end_job = AutoEndJob(connection_id)
    auto_end_job.__call__()
    # Cannot really check the state because AutoEndJob schedules a DeactivateJob that also manipulates the state,
    # making this a flaky test.
    # assert state_machine.is_deactivating(connection_id)
    # assert state_machine.passed_end_time(connection_id)
    assert "Schedule deactivate" in caplog.text


def test_auto_end_job_recover(connection_id: UUID, auto_end: None, get_stub: None, caplog: Any) -> None:
    """Test AutoEndJob to recover reservations in state Created and AutoEnd."""
    auto_end_job = AutoEndJob(connection_id)
    job_list = auto_end_job.recover()
    assert len(job_list) == 1
    assert job_list[0].connection_id == connection_id
    assert state_machine.is_auto_end(connection_id)
    msgs = [
        logrecord.msg for logrecord in caplog.records if "job" in logrecord.msg and logrecord.msg["job"] == "AutoEndJob"
    ]
    assert len(msgs) == 1
    assert msgs[0]["connection_id"] == str(connection_id)
    assert msgs[0]["event"] == "Recovering job"


def test_auto_end_job_trigger(connection_id: UUID, caplog: Any) -> None:
    """Test AutoEndJob to return trigger with end time of reservation."""
    auto_end_job = AutoEndJob(connection_id)
    job_trigger = auto_end_job.trigger()

    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        assert job_trigger.run_date == reservation.schedule.end_time
