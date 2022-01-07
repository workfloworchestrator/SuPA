from typing import Any

from sqlalchemy import Column

from supa.connection.fsm import ReservationStateMachine
from supa.db.model import Reservation
from supa.db.session import db_session
from supa.job.reserve import ReserveAbortJob, ReserveCommitJob, ReserveTimeoutJob

#
# TODO rewrite test to check correct reservation timeout handling
#
# def test_reserve_commit_job_invalid_transition(caplog: Any, connection_id: Column, reserve_held: None) -> None:
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
    connection_id: Column, reserve_committing: None, get_stub: None
) -> None:
    """Test ReserveCommitJob to transition to ReserveStart.

    Verify that a ReserveCommitJob will transition the reserve state machine
    to state ReserveStart when in state ReserveCommitting.
    """
    reserve_commit_job = ReserveCommitJob(connection_id)
    reserve_commit_job.__call__()

    # verify that reservation is transitioned to ReserveStart
    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value


#
# TODO removed this check from ReserveAbortJob, what else should we check here?
#
# def test_reserve_abort_job_invalid_transition(caplog: Any, connection_id: Column, reserve_held: None) -> None:
#     """Test ReserveAbortJob to detect an invalid transition.
#
#     Verify that a ReserveAbortJob will detect an invalid transition
#     when the reservation reserve state machine is not in state ReserveAborting.
#     """
#     reserve_abort_job = ReserveAbortJob(connection_id)
#     caplog.clear()
#     reserve_abort_job.__call__()
#     assert "Cannot abort reservation" in caplog.text
#
#     # verify that reservation is still in state ReserveHeld
#     with db_session() as session:
#         reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
#         assert reservation.reservation_state == ReservationStateMachine.ReserveHeld.value


def test_reserve_abort_job_reserve_abort_confirmed(
    connection_id: Column, reserve_aborting: None, get_stub: None
) -> None:
    """Test ReserveAbortJob to transition to ReserveStart.

    Verify that a ReserveAbortJob will transition the reserve state machine
    to state ReserveStart when in state ReserveAborting.
    """
    reserve_abort_job = ReserveAbortJob(connection_id)
    reserve_abort_job.__call__()

    # verify that reservation is transitioned to ReserveStart
    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value


def test_reserve_timeout_job_invalid_transition(caplog: Any, connection_id: Column, reserve_committing: None) -> None:
    """Test ReserveTimeoutJob to detect an invalid transition.

    Verify that a ReserveTimeoutJob will detect an invalid transition attempt
    when the reservation reserve state machine is not in a state that accepts an timeout.
    """
    reserve_timeout_job = ReserveTimeoutJob(connection_id)
    caplog.clear()
    reserve_timeout_job.__call__()
    assert "Reservation not timed out" in caplog.text

    # verify that reservation is still in state ReserveHeld
    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        assert reservation.reservation_state == ReservationStateMachine.ReserveCommitting.value


def test_reserve_timeout_job_reserve_timeout_notification(connection_id: Column, reserve_held: None) -> None:
    """Test ReserveTimeoutJob to transition to ReserveTimeout.

    Verify that a ReserveTimeoutJob will transition the reserve state machine
    to state ReserveTimeout when in state ReserveHeld.
    """
    reserve_timeout_job = ReserveTimeoutJob(connection_id)
    reserve_timeout_job.__call__()

    # verify that reservation is transitioned to ReserveTimeout
    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        assert reservation.reservation_state == ReservationStateMachine.ReserveTimeout.value
