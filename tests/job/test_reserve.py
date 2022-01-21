from typing import Any

from sqlalchemy import Column

from supa.connection.fsm import ReservationStateMachine
from supa.db.model import Reservation
from supa.job.reserve import ReserveAbortJob, ReserveCommitJob, ReserveJob, ReserveTimeoutJob


def test_reserve_job_reserve_confirmed(connection_id: Column, reserve_checking: None, get_stub: None) -> None:
    """Test ReserveJob to transition to ReserveHeld."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()


def test_reserve_job_reserve_failed_src_port_equals_dst_port(
    connection_id: Column, reserve_checking: None, src_port_equals_dst_port: None, get_stub: None, caplog: Any
) -> None:
    """Test ReserveJob to transition to ReserveFailed when src_port is equal to dst_port."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text


def test_reserve_job_reserve_failed_unknown_port(
    connection_id: Column, reserve_checking: None, unknown_port: None, get_stub: None, caplog: Any
) -> None:
    """Test ReserveJob to transition to ReserveFailed when one of the STP's is unknown."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text


def test_reserve_job_reserve_failed_disabled_port(
    connection_id: Column, reserve_checking: None, disabled_port: None, get_stub: None, caplog: Any
) -> None:
    """Test ReserveJob to transition to ReserveFailed when one of the ports is disabled."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text


def test_reserve_job_reserve_failed_unknown_domain_port(
    connection_id: Column, reserve_checking: None, unknown_domain_port: None, get_stub: None, caplog: Any
) -> None:
    """Test ReserveJob to transition to ReserveFailed when dst_domain is unknown."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text


def test_reserve_job_reserve_failed_unknown_topology_port(
    connection_id: Column, reserve_checking: None, unknown_topology_port: None, get_stub: None, caplog: Any
) -> None:
    """Test ReserveJob to transition to ReserveFailed when dst_network_type is unknown."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text


def test_reserve_job_reserve_failed_empty_vlans_port(
    connection_id: Column, reserve_checking: None, empty_vlans_port: None, get_stub: None, caplog: Any
) -> None:
    """Test ReserveJob to transition to ReserveFailed when dst_vlans is empty."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text


def test_reserve_job_reserve_failed_to_much_bandwidth(
    connection_id: Column, reserve_checking: None, to_much_bandwidth: None, get_stub: None, caplog: Any
) -> None:
    """Test ReserveJob to transition to ReserveFailed when requested bandwidth is not available."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text


def test_reserve_job_reserve_failed_no_matching_vlan(
    connection_id: Column, reserve_checking: None, no_matching_vlan: None, get_stub: None, caplog: Any
) -> None:
    """Test ReserveJob to transition to ReserveFailed when requested vlan is not available."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text


def test_reserve_job_reserve_failed_all_vlans_in_use(
    connection_id: Column, reserve_checking: None, all_vlans_in_use: None, get_stub: None, caplog: Any
) -> None:
    """Test ReserveJob to transition to ReserveFailed when port has no available vlans."""
    reserve_job = ReserveJob(connection_id)
    reserve_job.__call__()
    assert "Reservation failed" in caplog.text


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

    Verify (see fake_servicer) that a ReserveCommitJob will
    transition the reserve state machine to state ReserveStart when in state ReserveCommitting.
    """
    reserve_commit_job = ReserveCommitJob(connection_id)
    reserve_commit_job.__call__()


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

    from supa.db.session import db_session

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

    from supa.db.session import db_session

    # verify that reservation is still in state ReserveHeld
    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        assert reservation.reservation_state == ReservationStateMachine.ReserveCommitting.value


def test_reserve_timeout_job_reserve_timeout_notification(
    connection_id: Column, reserve_held: None, get_stub: None
) -> None:
    """Test ReserveTimeoutJob to transition to ReserveTimeout.

    Verify that a ReserveTimeoutJob will transition the reserve state machine
    to state ReserveTimeout when in state ReserveHeld.
    """
    reserve_timeout_job = ReserveTimeoutJob(connection_id)
    reserve_timeout_job.__call__()

    from supa.db.session import db_session

    # verify that reservation is transitioned to ReserveTimeout
    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        assert reservation.reservation_state == ReservationStateMachine.ReserveTimeout.value
