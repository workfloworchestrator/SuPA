from typing import Any
from uuid import UUID

from supa.connection.fsm import (
    DataPlaneStateMachine,
    LifecycleStateMachine,
    ProvisionStateMachine,
    ReservationStateMachine,
)
from supa.db.model import Reservation


def is_reserve_start(connection_id: UUID) -> Any:
    """Test if reservation state machine is in state ReserveStart."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ReservationStateMachine(reservation, state_field="reservation_state").is_ReserveStart


def is_reserve_failed(connection_id: UUID) -> Any:
    """Test if reservation state machine is in state ReserveFailed."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ReservationStateMachine(reservation, state_field="reservation_state").is_ReserveFailed


def is_reserve_committing(connection_id: UUID) -> Any:
    """Test if reservation state machine is in state ReserveCommitting."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ReservationStateMachine(reservation, state_field="reservation_state").is_ReserveCommitting


def is_reserve_held(connection_id: UUID) -> Any:
    """Test if reservation state machine is in state ReserveHeld."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ReservationStateMachine(reservation, state_field="reservation_state").is_ReserveHeld


def is_reserve_checking(connection_id: UUID) -> Any:
    """Test if reservation state machine is in state ReserveChecking."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ReservationStateMachine(reservation, state_field="reservation_state").is_ReserveChecking


def is_reserve_aborting(connection_id: UUID) -> Any:
    """Test if reservation state machine is in state ReserveAborting."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ReservationStateMachine(reservation, state_field="reservation_state").is_ReserveAborting


def is_reserve_timeout(connection_id: UUID) -> Any:
    """Test if reservation state machine is in state ReserveTimeout."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ReservationStateMachine(reservation, state_field="reservation_state").is_ReserveTimeout


def is_released(connection_id: UUID) -> Any:
    """Test if provision state machine is in state Released."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ProvisionStateMachine(reservation, state_field="provision_state").is_Released


def is_provisioning(connection_id: UUID) -> Any:
    """Test if provision state machine is in state Provisioning."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ProvisionStateMachine(reservation, state_field="provision_state").is_Provisioning


def is_provisioned(connection_id: UUID) -> Any:
    """Test if provision state machine is in state Provisioned."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ProvisionStateMachine(reservation, state_field="provision_state").is_Provisioned


def is_releasing(connection_id: UUID) -> Any:
    """Test if provision state machine is in state Releasing."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ProvisionStateMachine(reservation, state_field="provision_state").is_Releasing


def is_deactivated(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state Deactivated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").is_Deactivated


def is_auto_start(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state AutoStart."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").is_AutoStart


def is_activating(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state Activating."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").is_Activating


def is_activated(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state Activated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").is_Activated


def is_auto_end(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state AutoEnd."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").is_AutoEnd


def is_deactivating(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state Deactivating."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").is_Deactivating


def is_activate_failed(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state ActivateFailed."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").is_ActivateFailed


def is_deactivate_failed(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state DeactivateFailed."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").is_DeactivateFailed


def created(connection_id: UUID) -> Any:
    """Test if lifecycle state machine is in state Created."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return LifecycleStateMachine(reservation, state_field="data_plane_state").is_Created


def failed(connection_id: UUID) -> Any:
    """Test if lifecycle state machine is in state Failed."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return LifecycleStateMachine(reservation, state_field="data_plane_state").is_Failed


def terminating(connection_id: UUID) -> Any:
    """Test if lifecycle state machine is in state Terminating."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return LifecycleStateMachine(reservation, state_field="data_plane_state").is_Terminating


def passed_end_time(connection_id: UUID) -> Any:
    """Test if lifecycle state machine is in state PassedEndTime."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return LifecycleStateMachine(reservation, state_field="data_plane_state").is_PassedEndTime


def terminated(connection_id: UUID) -> Any:
    """Test if lifecycle state machine is in state Terminated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return LifecycleStateMachine(reservation, state_field="data_plane_state").is_Terminated
