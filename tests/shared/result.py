from uuid import UUID

from supa.db.model import Result
from supa.grpc_nsi.connection_requester_pb2 import ErrorRequest


def result_types(connection_id: UUID) -> list[str]:
    """Return the type of each result that was registered for the connection, in the order they were registered."""
    from supa.db.session import db_session

    with db_session() as session:
        results = session.query(Result).filter(Result.connection_id == connection_id).order_by(Result.result_id)
        return [result.result_type for result in results]


def error_ids(connection_id: UUID) -> list[str]:
    """Return the NSI error id of each Error result that was registered for the connection."""
    from supa.db.session import db_session

    with db_session() as session:
        results = session.query(Result).filter(Result.connection_id == connection_id, Result.result_type == "Error")
        return [ErrorRequest.FromString(result.result_data).service_exception.error_id for result in results]
