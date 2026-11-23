from typing import Any
from uuid import UUID

import pytest

from supa.db.model import Reservation


def test_db_session_rolls_back_and_raises_when_the_work_fails(connection_id: UUID, caplog: Any) -> None:
    """Test that the changes of a session that fails are rolled back, logged, and that the exception is raised."""
    from supa.db.session import db_session

    with pytest.raises(RuntimeError, match="the work failed"), db_session() as session:
        session.query(Reservation).filter(Reservation.connection_id == connection_id).one().description = "changed"
        raise RuntimeError("the work failed")

    assert "Rolling back" in caplog.text
    with db_session() as session:
        assert (
            session.query(Reservation).filter(Reservation.connection_id == connection_id).one().description != "changed"
        )
