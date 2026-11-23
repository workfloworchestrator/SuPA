from typing import Generator

import pytest
from sqlalchemy import delete, select

from supa.db.model import Reservation


@pytest.fixture(autouse=True)
def delete_new_reservations() -> Generator[None, None, None]:
    """Delete the reservations that a test created through a handler, so the recover() tests do not count them."""
    from supa.db.session import db_session

    with db_session() as session:
        existing = session.scalars(select(Reservation.connection_id)).all()
    yield
    with db_session() as session:
        session.execute(delete(Reservation).where(Reservation.connection_id.not_in(existing)))
