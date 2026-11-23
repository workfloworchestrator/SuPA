from uuid import UUID

from sqlalchemy import inspect

from supa.db.model import Reservation


def test_repr_lists_the_columns_and_not_the_relationships(connection_id: UUID) -> None:
    """Test that the repr of a model lists each of its columns and no relationships, and that str is the same."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        mapper = inspect(reservation).mapper
        text = repr(reservation)
        assert text.startswith("Reservation(")
        assert all(f"{attr.key}={getattr(reservation, attr.key)}" in text for attr in mapper.column_attrs)
        assert not any(f"{relationship.key}=" in text for relationship in mapper.relationships)
        assert str(reservation) == text
