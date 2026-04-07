"""Tests covering code paths that use statemachine APIs changing in v3.

These tests pin current behavior of `current_state` comparisons in:
- `src/supa/util/converter.py:314` (to_data_plane_state_change_request)
"""

from uuid import UUID

from supa.connection.fsm import DataPlaneStateMachine
from supa.db.model import Reservation
from supa.util.converter import to_data_plane_state_change_request


def test_to_data_plane_state_change_request_active(connection_id: UUID, activated: None) -> None:
    """Test data plane status is active when state is Activated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        result = to_data_plane_state_change_request(reservation)
        assert result.data_plane_status.active is True
        assert result.data_plane_status.version == reservation.version
        assert result.data_plane_status.version_consistent is True


def test_to_data_plane_state_change_request_not_active(connection_id: UUID, deactivated: None) -> None:
    """Test data plane status is not active when state is Deactivated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        assert reservation.data_plane_state == DataPlaneStateMachine.Deactivated.value
        result = to_data_plane_state_change_request(reservation)
        assert result.data_plane_status.active is False


def test_to_data_plane_state_change_request_auto_end_not_active(connection_id: UUID) -> None:
    """Test data plane status is not active when state is AutoEnd."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.data_plane_state = DataPlaneStateMachine.AutoEnd.value

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        result = to_data_plane_state_change_request(reservation)
        assert result.data_plane_status.active is False
