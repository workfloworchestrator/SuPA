from datetime import datetime, timedelta, timezone
from typing import Generator
from uuid import UUID

import pytest

from supa.db.model import Reservation
from supa.grpc_nsi.connection_provider_pb2 import QueryRequest
from supa.job.query import create_query_confirmed_request
from supa.util.timestamp import current_timestamp

OTHER_GLOBAL_RESERVATION_ID = "other global reservation id"


@pytest.fixture()
def other_connection_id() -> Generator[UUID, None, None]:
    """Create a second reservation, from another requester NSA, and return its connection ID."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = Reservation(
            protocol_version="application/vnd.ogf.nsi.cs.v2.provider+soap",
            requester_nsa="urn:ogf:network:example.domain:2021:other-requester",
            provider_nsa="urn:ogf:network:example.domain:2021:provider",
            reply_to="http://127.0.0.1/does_not_exist",
            global_reservation_id=OTHER_GLOBAL_RESERVATION_ID,
            description="reservation 2",
            version=0,
            last_modified=current_timestamp(),
        )
        session.add(reservation)
        session.flush()
        connection_id = reservation.connection_id

    yield connection_id

    with db_session() as session:
        session.delete(session.query(Reservation).filter(Reservation.connection_id == connection_id).one())


def _query_request(
    connection_ids: list[UUID], global_reservation_ids: list[str], if_modified_since: datetime | None
) -> QueryRequest:
    pb_query_request = QueryRequest()
    pb_query_request.header.requester_nsa = "urn:ogf:network:example.domain:2021:neither-requester"
    pb_query_request.connection_id.extend(str(connection_id) for connection_id in connection_ids)
    pb_query_request.global_reservation_id.extend(global_reservation_ids)
    if if_modified_since:
        pb_query_request.if_modified_since.FromDatetime(if_modified_since)
    return pb_query_request


@pytest.mark.filterwarnings("error::sqlalchemy.exc.SADeprecationWarning")
@pytest.mark.parametrize(
    ("by_connection_id", "by_global_reservation_id", "modified_in_future", "expected"),
    [
        pytest.param(False, False, False, {"first", "other"}, id="no-filter-returns-all-requesters"),
        pytest.param(True, False, False, {"first"}, id="connection-id"),
        pytest.param(False, True, False, {"other"}, id="global-reservation-id"),
        pytest.param(True, True, False, {"first", "other"}, id="filters-are-ored"),
        pytest.param(False, False, True, set(), id="no-filter-honours-if-modified-since"),
    ],
)
def test_create_query_confirmed_request(
    connection_id: UUID,
    other_connection_id: UUID,
    by_connection_id: bool,
    by_global_reservation_id: bool,
    modified_in_future: bool,
    expected: set[str],
) -> None:
    """Test the reservations selected by connection ID, global reservation ID, both or neither."""
    names = {str(connection_id): "first", str(other_connection_id): "other"}
    pb_query_request = _query_request(
        [connection_id] if by_connection_id else [],
        [OTHER_GLOBAL_RESERVATION_ID] if by_global_reservation_id else [],
        datetime.now(timezone.utc) + timedelta(hours=1) if modified_in_future else None,
    )

    request = create_query_confirmed_request(pb_query_request)

    # Other tests may leave reservations behind, so only these two are compared.
    assert {names[r.connection_id] for r in request.reservation if r.connection_id in names} == expected
