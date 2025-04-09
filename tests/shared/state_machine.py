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
        return ReservationStateMachine(reservation, state_field="reservation_state").ReserveStart.is_active


def is_reserve_failed(connection_id: UUID) -> Any:
    """Test if reservation state machine is in state ReserveFailed."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ReservationStateMachine(reservation, state_field="reservation_state").ReserveFailed.is_active


def is_reserve_committing(connection_id: UUID) -> Any:
    """Test if reservation state machine is in state ReserveCommitting."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ReservationStateMachine(reservation, state_field="reservation_state").ReserveCommitting.is_active


def is_reserve_held(connection_id: UUID) -> Any:
    """Test if reservation state machine is in state ReserveHeld."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ReservationStateMachine(reservation, state_field="reservation_state").ReserveHeld.is_active


def is_reserve_checking(connection_id: UUID) -> Any:
    """Test if reservation state machine is in state ReserveChecking."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ReservationStateMachine(reservation, state_field="reservation_state").ReserveChecking.is_active


def is_reserve_aborting(connection_id: UUID) -> Any:
    """Test if reservation state machine is in state ReserveAborting."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ReservationStateMachine(reservation, state_field="reservation_state").ReserveAborting.is_active


def is_reserve_timeout(connection_id: UUID) -> Any:
    """Test if reservation state machine is in state ReserveTimeout."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ReservationStateMachine(reservation, state_field="reservation_state").ReserveTimeout.is_active


def is_released(connection_id: UUID) -> Any:
    """Test if provision state machine is in state Released."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ProvisionStateMachine(reservation, state_field="provision_state").Released.is_active


def is_provisioning(connection_id: UUID) -> Any:
    """Test if provision state machine is in state Provisioning."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ProvisionStateMachine(reservation, state_field="provision_state").Provisioning.is_active


def is_provisioned(connection_id: UUID) -> Any:
    """Test if provision state machine is in state Provisioned."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ProvisionStateMachine(reservation, state_field="provision_state").Provisioned.is_active


def is_releasing(connection_id: UUID) -> Any:
    """Test if provision state machine is in state Releasing."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return ProvisionStateMachine(reservation, state_field="provision_state").Releasing.is_active


def is_deactivated(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state Deactivated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").Deactivated.is_active


def is_auto_start(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state AutoStart."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").AutoStart.is_active


def is_activating(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state Activating."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").Activating.is_active


def is_activated(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state Activated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").Activated.is_active


def is_auto_end(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state AutoEnd."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").AutoEnd.is_active


def is_deactivating(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state Deactivating."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").Deactivating.is_active


def is_activate_failed(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state ActivateFailed."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").ActivateFailed.is_active


def is_deactivate_failed(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state DeactivateFailed."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").DeactivateFailed.is_active


def is_unhealthy(connection_id: UUID) -> Any:
    """Test if data plane state machine is in state Unhealthy."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return DataPlaneStateMachine(reservation, state_field="data_plane_state").Unhealthy.is_active


def is_created(connection_id: UUID) -> Any:
    """Test if lifecycle state machine is in state Created."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return LifecycleStateMachine(reservation, state_field="lifecycle_state").Created.is_active


def is_failed(connection_id: UUID) -> Any:
    """Test if lifecycle state machine is in state Failed."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return LifecycleStateMachine(reservation, state_field="lifecycle_state").Failed.is_active


def is_terminating(connection_id: UUID) -> Any:
    """Test if lifecycle state machine is in state Terminating."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return LifecycleStateMachine(reservation, state_field="lifecycle_state").Terminating.is_active


def is_passed_end_time(connection_id: UUID) -> Any:
    """Test if lifecycle state machine is in state PassedEndTime."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return LifecycleStateMachine(reservation, state_field="lifecycle_state").PassedEndTime.is_active


def is_terminated(connection_id: UUID) -> Any:
    """Test if lifecycle state machine is in state Terminated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        return LifecycleStateMachine(reservation, state_field="lifecycle_state").Terminated.is_active
