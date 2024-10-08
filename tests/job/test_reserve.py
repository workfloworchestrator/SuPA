from datetime import timedelta
from typing import Any, Generator
from uuid import UUID

import tests.shared.state_machine as state_machine

from supa.db.model import Connection, Reservation
from supa.db.session import db_session
from supa.job.reserve import ReserveAbortJob, ReserveCommitJob, ReserveJob, ReserveTimeoutJob
from supa.util.timestamp import current_timestamp


def test_reserve_job_reserve_confirmed(connection_id: UUID, reserve_checking: None, get_stub: None) -> None:
    """Test ReserveJob to transition to ReserveHeld."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert state_machine.is_reserve_held(connection_id)


def test_reserve_job_reserve_failed_src_stp_id_equals_dst_stp_id(
    connection_id: UUID,
    reserve_checking: None,
    reserve_timeout_job: None,
    src_stp_id_equals_dst_stp_id: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveJob to transition to ReserveFailed when src_stp_id is equal to dst_stp_id."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text
    assert state_machine.is_reserve_failed(connection_id)


def test_reserve_job_reserve_failed_unknown_stp_id(
    connection_id: UUID,
    reserve_checking: None,
    reserve_timeout_job: None,
    unknown_stp_id: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveJob to transition to ReserveFailed when one of the STP's is unknown."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text
    assert state_machine.is_reserve_failed(connection_id)


def test_reserve_job_reserve_failed_disabled_stp_id(
    connection_id: UUID,
    reserve_checking: None,
    reserve_timeout_job: None,
    disabled_stp: Generator,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveJob to transition to ReserveFailed when one of the ports is disabled."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text
    assert state_machine.is_reserve_failed(connection_id)


def test_reserve_job_reserve_failed_unknown_domain_stp_id(
    connection_id: UUID,
    reserve_checking: None,
    reserve_timeout_job: None,
    unknown_domain_stp_id: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveJob to transition to ReserveFailed when dst_domain is unknown."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text
    assert state_machine.is_reserve_failed(connection_id)


def test_reserve_job_reserve_failed_unknown_topology_stp_id(
    connection_id: UUID,
    reserve_checking: None,
    reserve_timeout_job: None,
    unknown_topology_stp_id: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveJob to transition to ReserveFailed when dst_topology is unknown."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text
    assert state_machine.is_reserve_failed(connection_id)


def test_reserve_job_reserve_failed_empty_vlans_stp_id(
    connection_id: UUID,
    reserve_checking: None,
    reserve_timeout_job: None,
    empty_vlans_stp_id: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveJob to transition to ReserveFailed when dst_vlans is empty."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text
    assert state_machine.is_reserve_failed(connection_id)


def test_reserve_job_reserve_failed_to_much_bandwidth(
    connection_id: UUID,
    reserve_checking: None,
    reserve_timeout_job: None,
    to_much_bandwidth: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveJob to transition to ReserveFailed when requested bandwidth is not available."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text
    assert state_machine.is_reserve_failed(connection_id)


def test_reserve_job_reserve_failed_no_matching_vlan(
    connection_id: UUID,
    reserve_checking: None,
    reserve_timeout_job: None,
    no_matching_vlan: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveJob to transition to ReserveFailed when requested vlan is not available."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text
    assert state_machine.is_reserve_failed(connection_id)


def test_reserve_job_reserve_failed_all_vlans_in_use(
    connection_id: UUID,
    reserve_checking: None,
    reserve_timeout_job: None,
    all_vlans_in_use: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveJob to transition to ReserveFailed when port has no available vlans."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text
    assert state_machine.is_reserve_failed(connection_id)


def test_reserve_job_recover(connection_id: UUID, reserve_checking: None, get_stub: None, caplog: Any) -> None:
    """Test ReserveJob to recover reservations in state ReserveChecking."""
    reserve_job = ReserveJob(connection_id)
    job_list = reserve_job.recover()
    assert len(job_list) == 1
    assert job_list[0].connection_id == connection_id
    assert state_machine.is_reserve_checking(connection_id)
    msgs = [
        logrecord.msg for logrecord in caplog.records if "job" in logrecord.msg and logrecord.msg["job"] == "ReserveJob"
    ]
    assert len(msgs) == 1
    assert msgs[0]["connection_id"] == str(connection_id)
    assert msgs[0]["event"] == "Recovering job"


def test_reserve_job_trigger(connection_id: UUID, caplog: Any) -> None:
    """Test ReserveJob to return trigger to run immediately."""
    reserve_job = ReserveJob(connection_id)
    job_trigger = reserve_job.trigger()
    assert current_timestamp() - job_trigger.run_date < timedelta(seconds=5)  # more or less now


#
# TODO rewrite test to check correct reservation timeout handling
#
# def test_reserve_commit_job_invalid_transition(caplog: Any, connection_id: UUID, reserve_held: None) -> None:
#     """Test ReserveCommitJob to detect an invalid transition.
#
#     Verify that a ReserveCommitJob will detect an invalid transition
#     when the reservation reserve state machine is not in state ReserveCommitting.
#     """
#     reserve_commit_job = ReserveCommitJob(connection_id)
#     caplog.clear()
#     reserve_commit_job.__call__()
#     assert "Cannot commit reservation" in caplog.text
#
#     # verify that reservation is still in state ReserveHeld
#     with db_session() as session:
#         reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
#         assert reservation.reservation_state == ReservationStateMachine.ReserveHeld.value


def test_reserve_commit_job_reserve_commit_confirmed(
    connection_id: UUID, connection: None, reserve_committing: None, get_stub: None
) -> None:
    """Test ReserveCommitJob to transition to ReserveStart.

    Verify (see fake_servicer) that a ReserveCommitJob will
    transition the reserve state machine to state ReserveStart when in state ReserveCommitting.
    """
    reserve_commit_job = ReserveCommitJob(connection_id)
    reserve_commit_job.__call__()
    assert state_machine.is_reserve_start(connection_id)


def test_reserve_commit_modified_start_time(
    connection_id: UUID,
    connection: None,
    reserve_committing: None,
    modified_start_time: None,
    auto_start_job: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveCommitJob to reschedule AutoStartJob when start time is modified.

    Verify (see fake_servicer) that a ReserveCommitJob will
    ......
    """
    reserve_commit_job = ReserveCommitJob(connection_id)
    reserve_commit_job.__call__()
    assert state_machine.is_reserve_start(connection_id)
    assert "Reschedule auto start" in caplog.text


def test_reserve_commit_modified_no_end_time(
    connection_id: UUID,
    connection: None,
    reserve_committing: None,
    modified_no_end_time: None,
    auto_end_job: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveCommitJob to reschedule AutoStartJob when start time is modified.

    Verify (see fake_servicer) that a ReserveCommitJob will
    transition reservation state machine to ReserveStart,
    and transition data plane state machine from AutoEnd to Activated,
    and that the previous auto end job is canceled.
    """
    reserve_commit_job = ReserveCommitJob(connection_id)
    reserve_commit_job.__call__()
    assert state_machine.is_reserve_start(connection_id)
    assert state_machine.is_activated(connection_id)
    assert "Cancel previous auto end" in caplog.text


def test_reserve_commit_modified_set_end_time(
    connection_id: UUID,
    connection: None,
    reserve_committing: None,
    modified_end_time: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveCommitJob to schedule AutoEndJob when end time is set on connection without end time.

    Verify (see fake_servicer) that a ReserveCommitJob will
    transition reservation state machine to ReserveStart,
    and transition data plane state machine from Activated to AutoEnd,
    and that a auto end job is scheduled.
    """
    reserve_commit_job = ReserveCommitJob(connection_id)
    reserve_commit_job.__call__()
    assert state_machine.is_reserve_start(connection_id)
    assert state_machine.is_auto_end(connection_id)
    assert "Schedule new auto end" in caplog.text


def test_reserve_commit_modified_change_bandwidth(
    connection_id: UUID,
    connection: None,
    reserve_committing: None,
    modified_bandwidth: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveCommitJob to call modify() on backend of activated connection without end time.

    Verify (see fake_servicer) that a ReserveCommitJob will
    transition reservation state machine to ReserveStart,
    and that modify() is called on the backend.
    """
    reserve_commit_job = ReserveCommitJob(connection_id)
    reserve_commit_job.__call__()
    assert state_machine.is_reserve_start(connection_id)
    assert state_machine.is_activated(connection_id)
    assert "modify bandwidth on connection" in caplog.text
    assert "Modify resources in NRM" in caplog.text


def test_reserve_commit_job_recover(connection_id: UUID, reserve_committing: None, get_stub: None, caplog: Any) -> None:
    """Test ReserveCommitJob to recover reservations in state ReserveCommitting."""
    reserve_commit_job = ReserveCommitJob(connection_id)
    job_list = reserve_commit_job.recover()
    assert len(job_list) == 1
    assert job_list[0].connection_id == connection_id
    assert state_machine.is_reserve_committing(connection_id)
    msgs = [
        logrecord.msg
        for logrecord in caplog.records
        if "job" in logrecord.msg and logrecord.msg["job"] == "ReserveCommitJob"
    ]
    assert len(msgs) == 1
    assert msgs[0]["connection_id"] == str(connection_id)
    assert msgs[0]["event"] == "Recovering job"


def test_reserve_commit_job_trigger(connection_id: UUID, caplog: Any) -> None:
    """Test ReserveCommitJob to return trigger to run immediately."""
    reserve_commit_job = ReserveCommitJob(connection_id)
    job_trigger = reserve_commit_job.trigger()
    assert current_timestamp() - job_trigger.run_date < timedelta(seconds=5)  # more or less now


def test_reserve_abort_job_reserve_abort_confirmed(
    connection_id: UUID,
    connection_id_modified: None,
    connection: None,
    connection_modified: None,
    reserve_aborting: None,
    get_stub: None,
) -> None:
    """Test ReserveAbortJob to transition to ReserveStart.

    Verify that a ReserveAbortJob will transition the reserve state machine
    to state ReserveStart when in state ReserveAborting. Also Check that
    the return to the previous version of the reservation.
    """
    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        connection_from_db = session.query(Connection).filter(Connection.connection_id == connection_id).one()
        assert len(reservation.p2p_criteria_list) == 2
        assert len(reservation.schedules) == 2
        assert reservation.version == 1
        assert connection_from_db.bandwidth == reservation.p2p_criteria.bandwidth
        assert connection_from_db.bandwidth == 20
    reserve_abort_job = ReserveAbortJob(connection_id)
    reserve_abort_job.__call__()
    assert state_machine.is_reserve_start(connection_id)
    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        connection_from_db = session.query(Connection).filter(Connection.connection_id == connection_id).one()
        assert len(reservation.p2p_criteria_list) == 1
        assert len(reservation.schedules) == 1
        assert reservation.version == 0
        assert connection_from_db.bandwidth == reservation.p2p_criteria.bandwidth
        assert connection_from_db.bandwidth == 10


def test_reserve_abort_job_recover(connection_id: UUID, reserve_aborting: None, get_stub: None, caplog: Any) -> None:
    """Test ReserveAbortJob to recover reservations in state ReserveAborting."""
    reserve_abort_job = ReserveAbortJob(connection_id)
    job_list = reserve_abort_job.recover()
    assert len(job_list) == 1
    assert job_list[0].connection_id == connection_id
    assert state_machine.is_reserve_aborting(connection_id)
    msgs = [
        logrecord.msg
        for logrecord in caplog.records
        if "job" in logrecord.msg and logrecord.msg["job"] == "ReserveAbortJob"
    ]
    assert len(msgs) == 1
    assert msgs[0]["connection_id"] == str(connection_id)
    assert msgs[0]["event"] == "Recovering job"


def test_reserve_abort_job_trigger(connection_id: UUID, caplog: Any) -> None:
    """Test ReserveAbortJob to return trigger to run immediately."""
    reserve_abort_job = ReserveAbortJob(connection_id)
    job_trigger = reserve_abort_job.trigger()
    assert current_timestamp() - job_trigger.run_date < timedelta(seconds=5)  # more or less now


def test_reserve_timeout_job_invalid_transition(
    caplog: Any, connection_id: UUID, connection: None, reserve_committing: None
) -> None:
    """Test ReserveTimeoutJob to detect an invalid transition.

    Verify that a ReserveTimeoutJob will detect an invalid transition attempt
    when the reservation reserve state machine is not in a state that accepts an timeout.
    """
    reserve_timeout_job = ReserveTimeoutJob(connection_id)
    caplog.clear()
    reserve_timeout_job.__call__()
    assert "Reserve timeout failed" in caplog.text
    assert state_machine.is_reserve_committing(connection_id)


def test_reserve_timeout_job_reserve_timeout_notification(
    connection_id: UUID, connection: None, reserve_held: None, get_stub: None
) -> None:
    """Test ReserveTimeoutJob to transition to ReserveTimeout.

    Verify that a ReserveTimeoutJob will transition the reserve state machine
    to state ReserveTimeout when in state ReserveHeld.
    """
    reserve_timeout_job = ReserveTimeoutJob(connection_id)
    reserve_timeout_job.__call__()
    assert state_machine.is_reserve_timeout(connection_id)


def test_reserve_timeout_job_recover(connection_id: UUID, reserve_held: None, get_stub: None, caplog: Any) -> None:
    """Test ReserveTimeoutJob to recover reservations in state ReserveHeld."""
    reserve_timeout_job = ReserveTimeoutJob(connection_id)
    job_list = reserve_timeout_job.recover()
    assert len(job_list) == 1
    assert job_list[0].connection_id == connection_id
    assert state_machine.is_reserve_held(connection_id)
    msgs = [
        logrecord.msg
        for logrecord in caplog.records
        if "job" in logrecord.msg and logrecord.msg["job"] == "ReserveTimeoutJob"
    ]
    assert len(msgs) == 1
    assert msgs[0]["connection_id"] == str(connection_id)
    assert msgs[0]["event"] == "Recovering job"


def test_reserve_timeout_job_trigger(connection_id: UUID, caplog: Any) -> None:
    """Test ReserveTimeoutJob to return trigger to when the reservation is timed out."""
    reserve_timeout_job = ReserveTimeoutJob(connection_id)
    job_trigger = reserve_timeout_job.trigger()
    # more or less 30 seconds from now, FIXME: update test when timeout is configurable
    assert (current_timestamp() + timedelta(seconds=30) - job_trigger.run_date) < timedelta(seconds=5)
