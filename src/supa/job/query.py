#  Copyright 2023 SURF.
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
from __future__ import annotations

from typing import List, Type, Union
from uuid import UUID

import structlog
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import or_
from structlog.stdlib import BoundLogger

from supa.connection import requester
from supa.connection.fsm import DataPlaneStateMachine, ReservationStateMachine
from supa.db.model import Reservation
from supa.grpc_nsi.connection_common_pb2 import Header
from supa.grpc_nsi.connection_provider_pb2 import QuerySummaryRequest
from supa.grpc_nsi.connection_requester_pb2 import ErrorRequest, QuerySummaryConfirmedRequest, QuerySummaryResult
from supa.job.shared import Job
from supa.util.converter import to_connection_states, to_summary_criteria
from supa.util.timestamp import as_utc_timestamp

logger = structlog.get_logger(__name__)


def create_query_summary_confirmed_request(
    pb_query_summary_request: QuerySummaryRequest,
) -> QuerySummaryConfirmedRequest:
    """Create a list of reservation summary information matching the request.

    Args:
        pb_query_summary_request: Query summary request with match criteria.

    Returns:
        List of reservation summary information.
    """
    from supa.db.session import db_session

    request: Union[QuerySummaryConfirmedRequest, ErrorRequest]
    with db_session() as session:
        or_filter = []
        if pb_query_summary_request.connection_id:
            or_filter += [
                Reservation.connection_id == UUID(str(connection_id))
                for connection_id in pb_query_summary_request.connection_id
            ]
        if pb_query_summary_request.global_reservation_id:
            or_filter += [
                Reservation.global_reservation_id == global_reservation_id
                for global_reservation_id in pb_query_summary_request.global_reservation_id
            ]
        # TODO: implement ifModifiedSince filter after adding last_modified field to Reservation table
        reservations: List[Reservation] = (
            session.query(Reservation)
            .filter(or_(*or_filter))
            .filter(Reservation.reservation_state != ReservationStateMachine.ReserveChecking.value)
            .filter(Reservation.reservation_state != ReservationStateMachine.ReserveFailed.value)
            .all()
        )

        header = Header()
        header.CopyFrom(pb_query_summary_request.header)
        request = QuerySummaryConfirmedRequest(header=header)
        for reservation in reservations:
            result = QuerySummaryResult()
            result.connection_id = str(reservation.connection_id)
            result.requester_nsa = reservation.requester_nsa
            result.connection_states.CopyFrom(
                to_connection_states(
                    reservation,
                    data_plane_active=reservation.data_plane_state == DataPlaneStateMachine.Activated.value,
                )
            )
            if reservation.global_reservation_id:
                result.global_reservation_id = reservation.global_reservation_id
            if reservation.description:
                result.description = reservation.description
            # TODO: when Modify Reservation is implemented, add all criteria
            result.criteria.append(to_summary_criteria(reservation))
            # TODO: implement notification_id and result_id
            # result.notification_id
            # result.result_id
            request.reservation.append(result)

        return request


class QuerySummaryJob(Job):
    """Handle query summary requests."""

    log: BoundLogger
    pb_query_summary_request: QuerySummaryRequest

    def __init__(self, pb_query_summary_request: QuerySummaryRequest):
        """Initialize the QuerySummaryJob.

        Args:
           pb_query_summary_request: protobuf query summary request message

                Elements compose a filter for specifying the reservations to return
                in response to the query operation. Supports the querying of reservations
                based on connectionId or globalReservationId. Filter items specified
                are OR'ed to build the match criteria. If no criteria are specified
                then all reservations associated with the requesting NSA are returned.

                Elements:

                connectionId - Return reservations containing this connectionId.

                globalReservationId - Return reservations containing this globalReservationId.

                ifModifiedSince - If an NSA receives a querySummary or querySummarySync
                message containing this element, then the NSA only returns those
                reservations matching the filter elements (connectionId,
                globalReservationId) if the reservation has been created, modified, or
                has undergone a change since the specified ifModifiedSince time.
        """
        self.log = logger.bind(
            method="QuerySummary",
            connection_ids=pb_query_summary_request.connection_id,
            global_reservation_ids=pb_query_summary_request.global_reservation_id,
            if_modified_since=as_utc_timestamp(pb_query_summary_request.if_modified_since).isoformat(),
        )
        self.pb_query_summary_request = pb_query_summary_request

    def __call__(self) -> None:
        """Query summary request.

        Query summary listing reservations matching the optional connection id(s),
        global reservation id(s) and if modified since timestamp.
        """
        self.log.info("gathering matching reservations")
        request = create_query_summary_confirmed_request(self.pb_query_summary_request)
        stub = requester.get_stub()
        self.log.debug("Sending message", method="QuerySummaryConfirmed", request_message=request)
        stub.QuerySummaryConfirmed(request)

    @classmethod
    def recover(cls: Type[QuerySummaryJob]) -> List[Job]:
        """Recover QuerySummaryJob's that did not get to run before SuPA was terminated.

        As no query summary request details are stored in the database (at this time),
        it is not possible to recover QuerySummaryJob's.

        Returns:
            List of QuerySummaryJob's that still need to be run (currently always empty List).
        """
        return []

    def trigger(self) -> DateTrigger:
        """Trigger for QuerySummaryJob's.

        Returns:
            DateTrigger set to None, which means run now.
        """
        return DateTrigger(run_date=None)  # Run immediately
