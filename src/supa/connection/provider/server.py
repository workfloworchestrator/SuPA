#  Copyright 2020 SURF.
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
"""Implementation of the gRPC based Connection Provider Service."""
from __future__ import annotations

from typing import Union
from uuid import UUID

import structlog
from grpc import ServicerContext
from statemachine.exceptions import TransitionNotAllowed

from supa import settings
from supa.connection.error import (
    GenericMessagePayLoadError,
    GenericServiceError,
    InvalidTransition,
    ReservationNonExistent,
    UnsupportedParameter,
    Variable,
)
from supa.connection.fsm import LifecycleStateMachine, ProvisionStateMachine, ReservationStateMachine
from supa.db import model
from supa.grpc_nsi import connection_provider_pb2_grpc
from supa.grpc_nsi.connection_common_pb2 import GenericAcknowledgment, Header, Schedule
from supa.grpc_nsi.connection_provider_pb2 import (
    GenericRequest,
    QueryNotificationRequest,
    QueryRequest,
    QueryResultRequest,
    ReservationRequestCriteria,
    ReserveRequest,
    ReserveResponse,
)
from supa.grpc_nsi.connection_requester_pb2 import (
    QueryConfirmedRequest,
    QueryNotificationConfirmedRequest,
    QueryResultConfirmedRequest,
)
from supa.grpc_nsi.policy_pb2 import PathTrace
from supa.grpc_nsi.services_pb2 import Directionality, PointToPointService
from supa.job.lifecycle import TerminateJob
from supa.job.provision import ProvisionJob, ReleaseJob
from supa.job.query import (
    QueryNotificationJob,
    QueryRecursiveJob,
    QueryResultJob,
    QuerySummaryJob,
    create_query_confirmed_request,
    create_query_notification_confirmed_request,
    create_query_result_confirmed_request,
)
from supa.job.reserve import ReserveAbortJob, ReserveCommitJob, ReserveJob, ReserveTimeoutJob
from supa.job.shared import Job, NsiException
from supa.util.converter import to_response_header, to_service_exception
from supa.util.nsi import parse_stp
from supa.util.timestamp import EPOCH, as_utc_timestamp, current_timestamp, is_specified
from supa.util.type import RequestType

logger = structlog.get_logger(__name__)


def _validate_message_header(header: Header) -> None:
    """Verify request message header, see NSI CS 2.1 paragraph 6.3.2, raise NsiException on failure."""
    # Verify presence of requesterNSA field (always set when using PolyNSI)
    if not header.requester_nsa:
        extra_info = "missing requester NSA ID"
        logger.info(extra_info, requester_nsa=header.requester_nsa)
        raise NsiException(
            UnsupportedParameter,
            extra_info,
            {Variable.REQUESTER_NSA: header.requester_nsa},
        )
    # Verify presence of providerNSA field (always set when using PolyNSI)
    if not header.provider_nsa:
        extra_info = "missing provider NSA ID"
        logger.info(extra_info, provider_nsa=header.provider_nsa)
        raise NsiException(
            UnsupportedParameter,
            extra_info,
            {Variable.PROVIDER_NSA: header.provider_nsa},
        )
    # Verify that we are the targeted providerNSA
    if header.provider_nsa != settings.nsa_id:
        extra_info = "Unknown provider NSA ID"
        logger.info(extra_info, provider_nsa=header.provider_nsa)
        raise NsiException(
            UnsupportedParameter,
            extra_info,
            {Variable.PROVIDER_NSA: header.provider_nsa},
        )
    # Verify the uniqueness of supplied correlation_id
    from supa.db.session import db_session

    with db_session() as session:
        request: Union[model.Request, None] = (
            session.query(model.Request)
            .filter(model.Request.correlation_id == UUID(header.correlation_id))
            .one_or_none()
        )
        unique_correlation_id = not request  # no request with this correlation ID yet
    if not unique_correlation_id:
        extra_info = "correlation ID must be unique"
        logger.info(extra_info, correlation_id=header.correlation_id)
        raise NsiException(
            UnsupportedParameter,
            extra_info,
            {Variable.CORRELATION_ID: header.correlation_id},
        )


def _validate_schedule(pb_schedule: Schedule) -> None:
    """Verify reservation schedule, raise NsiException on failure."""
    start_time = as_utc_timestamp(pb_schedule.start_time)
    end_time = as_utc_timestamp(pb_schedule.end_time)
    if pb_schedule.end_time:
        if end_time != EPOCH and end_time <= current_timestamp():
            err_msg = "End time lies in the past."
            logger.info(err_msg, end_time=end_time.isoformat())
            raise NsiException(
                UnsupportedParameter,
                err_msg,
                {Variable.END_TIME: end_time.isoformat()},
            )
        if end_time != EPOCH and end_time <= start_time:
            err_msg = "End time cannot come before start time."
            logger.info(
                err_msg,
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
            )
            raise NsiException(
                UnsupportedParameter,
                err_msg,
                {
                    Variable.START_TIME: start_time.isoformat(),
                    Variable.END_TIME: end_time.isoformat(),
                },
            )


def _register_request(
    request: ReserveRequest | GenericRequest | QueryRequest | QueryNotificationRequest | QueryResultRequest,
    request_type: RequestType,
    connection_id: UUID | None = None,
) -> None:
    """Register request against connection_id in the database.

    To avoid race conditions,
    make sure that the request is registered in the database
    before adding the corresponding job to the queue,
    because the correlation_id used in the response message generated in the job
    is stored in this function.
    """
    if not connection_id and not isinstance(request, QueryRequest):
        connection_id = UUID(request.connection_id)

    from supa.db.session import db_session

    with db_session() as session:
        session.add(
            model.Request(
                correlation_id=UUID(request.header.correlation_id),
                connection_id=connection_id,
                request_type=request_type.value,
                request_data=request.SerializeToString(),
            )
        )


class ConnectionProviderService(connection_provider_pb2_grpc.ConnectionProviderServicer):
    """Implementation of the gRPC Connection Provider Service.

    Each of the methods in this class corresponds to gRPC defined ``rpc`` calls in the ``connection.provider``
    gPRC package.
    """

    def Reserve(self, pb_reserve_request: ReserveRequest, context: ServicerContext) -> ReserveResponse:
        """Request new reservation, or modify existing reservation.

        The reserve message is sent from an RA to a PA when a new reservation is being requested, or
        a modification to an existing reservation is required. The :class:`ReserveResponse` indicates that the PA
        has accepted the reservation request for processing and has assigned it the returned
        connectionId. The original ``connection_id`` will be returned for the :class:`ReserveResponse`` of a
        modification. A :class:`ReserveConfirmed` or :class:`ReserveFailed` message will be sent asynchronously to the
        RA when reserve operation has completed processing.

        Args:
            pb_reserve_request: All the details about the requested reservation.
            context: gRPC server context object.

        Returns:
            A :class:`ReserveResponse` message containing the PA assigned ``connection_id`` for this reservation
            request. This value will be unique within the context of the PA.

        """
        log = logger.bind(method="Reserve")
        log.debug("Received message.", request_message=pb_reserve_request)
        log.info(
            "reserve request",
            connection_id=pb_reserve_request.connection_id,
            version=pb_reserve_request.criteria.version,
            src_stp=pb_reserve_request.criteria.ptps.source_stp,
            dst_stp=pb_reserve_request.criteria.ptps.dest_stp,
            start_time=as_utc_timestamp(pb_reserve_request.criteria.schedule.start_time).isoformat(),
            end_time=as_utc_timestamp(pb_reserve_request.criteria.schedule.end_time).isoformat(),
            description=pb_reserve_request.description,
            global_reservation_id=pb_reserve_request.global_reservation_id,
        )

        try:
            _validate_message_header(pb_reserve_request.header)
            _validate_schedule(pb_reserve_request.criteria.schedule)
        except NsiException as nsi_exc:
            reserve_response = ReserveResponse(
                header=to_response_header(pb_reserve_request.header),
                service_exception=to_service_exception(nsi_exc),
            )
            log.debug("Sending response.", response_message=reserve_response)
            return reserve_response

        reservation: model.Reservation
        if not pb_reserve_request.connection_id:  # new reservation
            pb_header: Header = pb_reserve_request.header
            pb_path_trace: PathTrace = pb_header.path_trace
            pb_criteria: ReservationRequestCriteria = pb_reserve_request.criteria
            pb_ptps: PointToPointService = pb_criteria.ptps
            pb_schedule: Schedule = pb_criteria.schedule
            start_time = as_utc_timestamp(pb_schedule.start_time)
            end_time = as_utc_timestamp(pb_schedule.end_time)

            reservation = model.Reservation(
                version=pb_criteria.version,
                protocol_version=pb_header.protocol_version,
                requester_nsa=pb_header.requester_nsa,
                provider_nsa=pb_header.provider_nsa,
                reply_to=pb_header.reply_to if pb_header.reply_to else None,
                session_security_attributes=(
                    pb_header.session_security_attributes if pb_header.session_security_attributes else None
                ),
                global_reservation_id=pb_reserve_request.global_reservation_id,
                description=pb_reserve_request.description if pb_reserve_request.description else None,
            )

            reservation.schedules.append(
                model.Schedule(
                    version=pb_criteria.version,
                    start_time=start_time if is_specified(start_time) else None,
                    end_time=end_time if is_specified(end_time) else None,
                )
            )

            # TODO: select service type specific table based on pb_criteria.service_type
            src_stp = parse_stp(pb_ptps.source_stp)
            dst_stp = parse_stp(pb_ptps.dest_stp)
            reservation.p2p_criteria_list.append(
                model.P2PCriteria(
                    version=pb_criteria.version,
                    bandwidth=pb_ptps.capacity,
                    directionality=Directionality.Name(pb_ptps.directionality),
                    symmetric=pb_ptps.symmetric_path,
                    src_domain=src_stp.domain,
                    src_topology=src_stp.topology,
                    src_stp_id=src_stp.stp_id,
                    src_vlans=str(src_stp.vlan_ranges),
                    dst_domain=dst_stp.domain,
                    dst_topology=dst_stp.topology,
                    dst_stp_id=dst_stp.stp_id,
                    dst_vlans=str(dst_stp.vlan_ranges),
                )
            )

            for k, v in pb_ptps.parameters.items():
                reservation.parameters.append(model.Parameter(key=k, value=v))

            if pb_path_trace.id:
                path_trace = model.PathTrace(
                    path_trace_id=pb_path_trace.id, ag_connection_id=pb_path_trace.connection_id
                )
                for pb_path in pb_path_trace.paths:
                    path = model.Path()
                    for pb_segment in pb_path.segments:
                        segment = model.Segment(segment_id=pb_segment.id, upa_connection_id=pb_segment.connection_id)
                        for pb_stp in pb_segment.stps:
                            segment.stps.append(model.Stp(stp_id=pb_stp))
                        path.segments.append(segment)
                    path_trace.paths.append(path)
                reservation.path_trace = path_trace

            rsm = ReservationStateMachine(reservation, state_field="reservation_state")
            rsm.reserve_request()

            from supa.db.session import db_session

            with db_session() as session:
                session.add(reservation)
                session.flush()  # Let DB (actually SQLAlchemy) generate the connection_id for us.
                connection_id = reservation.connection_id  # Can't reference it outside the session, hence new var.

            log = log.bind(connection_id=str(connection_id))

        else:  # modify reservation
            connection_id = UUID(pb_reserve_request.connection_id)
            log = log.bind(connection_id=str(connection_id))

            if (
                pb_reserve_request.description
                or pb_reserve_request.global_reservation_id
                or pb_reserve_request.criteria.service_type
                or pb_reserve_request.criteria.ptps.source_stp
                or pb_reserve_request.criteria.ptps.dest_stp
                or pb_reserve_request.criteria.ptps.symmetric_path
                or pb_reserve_request.criteria.ptps.eros
            ):
                reserve_response = ReserveResponse(
                    header=to_response_header(pb_reserve_request.header),
                    service_exception=to_service_exception(
                        NsiException(GenericMessagePayLoadError, "unsupported parameter for modify"), connection_id
                    ),
                )
                log.debug("Sending response.", response_message=reserve_response)
                return reserve_response  # return NSI Exception to requester

            from supa.db.session import db_session

            with db_session() as session:
                reservation = (
                    session.query(model.Reservation)  # type: ignore[assignment]
                    .filter(model.Reservation.connection_id == connection_id)
                    .one_or_none()
                )

                nsi_exception: Union[NsiException, None] = None
                if not reservation:
                    log.info("Connection ID does not exist")
                    nsi_exception = NsiException(
                        ReservationNonExistent, str(connection_id), {Variable.CONNECTION_ID: str(connection_id)}
                    )
                elif (
                    reservation.reservation_state != ReservationStateMachine.ReserveStart.value
                    or reservation.lifecycle_state != LifecycleStateMachine.Created.value
                ):
                    log.info(
                        "Connection not in modifiable state",
                        reservation_state=reservation.reservation_state,
                        lifecycle_state=reservation.lifecycle_state,
                    )
                    nsi_exception = NsiException(
                        InvalidTransition,
                        str(connection_id),
                        {
                            Variable.CONNECTION_ID: str(connection_id),
                            Variable.RESERVATION_STATE: reservation.reservation_state,
                            Variable.LIFECYCLE_STATE: reservation.lifecycle_state,
                        },
                    )
                else:
                    old_version = reservation.version
                    old_start_time = reservation.schedules[-1].start_time
                    if pb_reserve_request.criteria.version != 0:
                        new_version = pb_reserve_request.criteria.version
                    else:
                        # cannot distinguish between unset (defaults to 0) and set to 0,
                        # in the latter case we wrongly treat it as unset as well
                        new_version = old_version + 1
                    new_start_time = as_utc_timestamp(pb_reserve_request.criteria.schedule.start_time)
                    new_end_time = as_utc_timestamp(pb_reserve_request.criteria.schedule.end_time)
                    new_bandwidth = pb_reserve_request.criteria.ptps.capacity
                    if old_version + 1 != new_version:
                        log.info(
                            "version may only be incremented by 1",
                            old_version=old_version,
                            new_version=new_version,
                        )
                        nsi_exception = NsiException(UnsupportedParameter, f"version={new_version}")
                    elif (
                        old_start_time < current_timestamp()
                        and new_start_time > current_timestamp()
                        and old_start_time != new_start_time
                    ):
                        log.info(
                            "cannot change start time when reservation already started",
                            old_start_time=old_start_time.isoformat(),
                            new_start_time=new_start_time.isoformat(),
                        )
                        nsi_exception = NsiException(UnsupportedParameter, f"start_time={new_start_time.isoformat()}")
                if nsi_exception:
                    reserve_response = ReserveResponse(
                        header=to_response_header(pb_reserve_request.header),
                        service_exception=to_service_exception(nsi_exception, connection_id),
                    )
                    log.debug("Sending response.", response_message=reserve_response)
                    return reserve_response  # return NSI Exception to requester

                # now that the parameters are sane, process the modify request
                try:
                    rsm = ReservationStateMachine(reservation, state_field="reservation_state")
                    rsm.reserve_request()
                except TransitionNotAllowed as tna:
                    log.info("Not scheduling ReserveJob", reason=str(tna))
                    reserve_response = ReserveResponse(
                        header=to_response_header(pb_reserve_request.header),
                        service_exception=to_service_exception(
                            NsiException(
                                InvalidTransition,
                                str(tna),
                                {
                                    Variable.CONNECTION_ID: str(connection_id),
                                    Variable.RESERVATION_STATE: reservation.reservation_state,
                                },
                            ),
                            connection_id,
                        ),
                    )
                    return reserve_response

                log.info(
                    "modify reservation",
                    version=new_version,
                    start_time=new_start_time.isoformat(),
                    end_time=new_end_time.isoformat(),
                    bandwidth=new_bandwidth,
                )
                schedule = model.Schedule(
                    version=new_version,
                    start_time=new_start_time if is_specified(new_start_time) else None,
                    end_time=new_end_time if is_specified(new_end_time) else None,
                )
                p2p_criteria = model.P2PCriteria(
                    # connection_id=connection_id,
                    version=new_version,
                    bandwidth=new_bandwidth,
                    directionality=reservation.p2p_criteria.directionality,
                    symmetric=reservation.p2p_criteria.symmetric,
                    src_domain=reservation.p2p_criteria.src_domain,
                    src_topology=reservation.p2p_criteria.src_topology,
                    src_stp_id=reservation.p2p_criteria.src_stp_id,
                    src_vlans=reservation.p2p_criteria.src_vlans,
                    src_selected_vlan=reservation.p2p_criteria.src_selected_vlan,
                    dst_domain=reservation.p2p_criteria.dst_domain,
                    dst_topology=reservation.p2p_criteria.dst_topology,
                    dst_stp_id=reservation.p2p_criteria.dst_stp_id,
                    dst_vlans=reservation.p2p_criteria.dst_vlans,
                    dst_selected_vlan=reservation.p2p_criteria.dst_selected_vlan,
                )
                reservation.version = new_version
                reservation.schedules.append(schedule)
                reservation.p2p_criteria_list.append(p2p_criteria)

        from supa import scheduler

        job: Job

        log.info("Schedule reserve", job="ReserveJob")
        _register_request(pb_reserve_request, RequestType.Reserve, connection_id)
        scheduler.add_job(job := ReserveJob(connection_id), trigger=job.trigger(), id=job.job_id)
        reserve_response = ReserveResponse(
            header=to_response_header(pb_reserve_request.header), connection_id=str(connection_id)
        )
        log.info(
            "Schedule reserve timeout",
            job="ReserveTimeoutJob",
            connection_id=str(connection_id),
            timeout=settings.reserve_timeout,
        )
        scheduler.add_job(job := ReserveTimeoutJob(connection_id), trigger=job.trigger(), id=job.job_id)

        log.debug("Sending response.", response_message=reserve_response)
        return reserve_response

    def ReserveCommit(
        self, pb_reserve_commit_request: GenericRequest, context: ServicerContext
    ) -> GenericAcknowledgment:
        """Commit reservation.

        Check if the connection ID exists and if the reservation state machine transition is
        allowed, all real work for committing the reservation is done asynchronously by
        :class:`~supa.job.reserve.ReserveCommitJob`

        Args:
            pb_reserve_commit_request: Basically the connection_id wrapped in a request like object
            context: gRPC server context object.

        Returns:
            A response telling the caller we have received its commit request.
        """
        connection_id = UUID(pb_reserve_commit_request.connection_id)
        log = logger.bind(method="ReserveCommit", connection_id=str(connection_id))
        log.debug("Received message.", request_message=pb_reserve_commit_request)

        try:
            _validate_message_header(pb_reserve_commit_request.header)
        except NsiException as nsi_exc:
            reserve_commit_response = GenericAcknowledgment(
                header=to_response_header(pb_reserve_commit_request.header),
                service_exception=to_service_exception(nsi_exc),
            )
            log.debug("Sending response.", response_message=reserve_commit_response)
            return reserve_commit_response

        from supa.db.session import db_session

        with db_session() as session:
            reservation: Union[model.Reservation, None] = (
                session.query(model.Reservation).filter(model.Reservation.connection_id == connection_id).one_or_none()
            )
            if reservation is None:
                log.info("Connection ID does not exist")
                reserve_commit_response = GenericAcknowledgment(
                    header=to_response_header(pb_reserve_commit_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            ReservationNonExistent, str(connection_id), {Variable.CONNECTION_ID: str(connection_id)}
                        ),
                        connection_id,
                    ),
                )
            elif reservation.reservation_timeout:
                # we use this column because the reserve state machine is actually missing a state
                log.info("Cannot commit a timed out reservation")
                reserve_commit_response = GenericAcknowledgment(
                    header=to_response_header(pb_reserve_commit_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            GenericServiceError,
                            "Cannot commit a timed out reservation",
                            {Variable.CONNECTION_ID: str(connection_id)},
                        ),
                        connection_id,
                    ),
                )
            else:
                try:
                    rsm = ReservationStateMachine(reservation, state_field="reservation_state")
                    rsm.reserve_commit_request()
                except TransitionNotAllowed as tna:
                    log.info("Not scheduling ReserveCommitJob", reason=str(tna))
                    reserve_commit_response = GenericAcknowledgment(
                        header=to_response_header(pb_reserve_commit_request.header),
                        service_exception=to_service_exception(
                            NsiException(
                                InvalidTransition,
                                str(tna),
                                {
                                    Variable.CONNECTION_ID: str(connection_id),
                                    Variable.RESERVATION_STATE: reservation.reservation_state,
                                },
                            ),
                            connection_id,
                        ),
                    )
                else:
                    reserve_commit_response = GenericAcknowledgment(
                        header=to_response_header(pb_reserve_commit_request.header)
                    )

        if not reserve_commit_response.service_exception.connection_id:
            from supa import scheduler

            log.info("Cancel reserve timeout", job="ReserveTimeoutJob")
            scheduler.remove_job(job_id=ReserveTimeoutJob(connection_id).job_id)
            log.info("Schedule reserve commit", job="ReserveCommitJob")
            _register_request(pb_reserve_commit_request, RequestType.ReserveCommit)
            scheduler.add_job(job := ReserveCommitJob(connection_id), trigger=job.trigger(), id=job.job_id)
        log.debug("Sending response.", response_message=reserve_commit_response)
        return reserve_commit_response

    def ReserveAbort(self, pb_reserve_abort_request: GenericRequest, context: ServicerContext) -> GenericAcknowledgment:
        """Abort reservation.

        Check if the connection ID exists and if the reservation state machine transition is
        allowed, all real work for aborting the reservation is done asynchronously by
        :class:`~supa.job.reserve.ReserveAbortJob`

        Args:
            pb_reserve_abort_request: Basically the connection wrapped in a request like object
            context: gRPC server context object.

        Returns:
            A response telling the caller we have received its abort request.
        """
        connection_id = UUID(pb_reserve_abort_request.connection_id)
        log = logger.bind(method="ReserveAbort", connection_id=str(connection_id))
        log.debug("Received message.", request_message=pb_reserve_abort_request)

        try:
            _validate_message_header(pb_reserve_abort_request.header)
        except NsiException as nsi_exc:
            reserve_abort_response = GenericAcknowledgment(
                header=to_response_header(pb_reserve_abort_request.header),
                service_exception=to_service_exception(nsi_exc),
            )
            log.debug("Sending response.", response_message=reserve_abort_response)
            return reserve_abort_response

        from supa.db.session import db_session

        with db_session() as session:
            reservation: Union[model.Reservation, None] = (
                session.query(model.Reservation).filter(model.Reservation.connection_id == connection_id).one_or_none()
            )
            if reservation is None:
                log.info("Connection ID does not exist")
                reserve_abort_response = GenericAcknowledgment(
                    header=to_response_header(pb_reserve_abort_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            ReservationNonExistent, str(connection_id), {Variable.CONNECTION_ID: str(connection_id)}
                        ),
                        connection_id,
                    ),
                )
            else:
                if len(reservation.p2p_criteria_list) <= 1:
                    log.info("Cannot abort an initial reserve request, abort only allowed on modify")
                    reserve_abort_response = GenericAcknowledgment(
                        header=to_response_header(pb_reserve_abort_request.header),
                        service_exception=to_service_exception(
                            NsiException(
                                InvalidTransition,
                                "cannot abort an initial reserve request, abort only allowed on modify",
                                {Variable.CONNECTION_ID: str(connection_id)},
                            ),
                            connection_id,
                        ),
                    )
                else:
                    try:
                        rsm = ReservationStateMachine(reservation, state_field="reservation_state")
                        rsm.reserve_abort_request()
                    except TransitionNotAllowed as tna:
                        log.info("Not scheduling ReserveAbortJob", reason=str(tna))
                        reserve_abort_response = GenericAcknowledgment(
                            header=to_response_header(pb_reserve_abort_request.header),
                            service_exception=to_service_exception(
                                NsiException(
                                    InvalidTransition,
                                    str(tna),
                                    {
                                        Variable.CONNECTION_ID: str(connection_id),
                                        Variable.RESERVATION_STATE: reservation.reservation_state,
                                    },
                                ),
                                connection_id,
                            ),
                        )
                    else:
                        reserve_abort_response = GenericAcknowledgment(
                            header=to_response_header(pb_reserve_abort_request.header)
                        )

        if not reserve_abort_response.service_exception.connection_id:
            from supa import scheduler

            log.info("Schedule reserve abort", job="ReserveAbortJob")
            _register_request(pb_reserve_abort_request, RequestType.ReserveAbort)
            scheduler.add_job(job := ReserveAbortJob(connection_id), trigger=job.trigger(), id=job.job_id)
        log.debug("Sending response.", response_message=reserve_abort_response)
        return reserve_abort_response

    def Provision(self, pb_provision_request: GenericRequest, context: ServicerContext) -> GenericAcknowledgment:
        """Provision reservation.

        Check if the connection ID exists, if the provision state machine exists (as an indication
        that the reservation was committed), and if the provision state machine transition is
        allowed, all real work for provisioning the reservation is done asynchronously by
        :class:`~supa.job.reserve.ProvisionJob`

        Args:
            pb_provision_request: Basically the connection id wrapped in a request like object
            context: gRPC server context object.

        Returns:
            A response telling the caller we have received its provision request.
        """
        connection_id = UUID(pb_provision_request.connection_id)
        log = logger.bind(method="Provision", connection_id=str(connection_id))
        log.debug("Received message.", request_message=pb_provision_request)

        try:
            _validate_message_header(pb_provision_request.header)
        except NsiException as nsi_exc:
            provision_response = GenericAcknowledgment(
                header=to_response_header(pb_provision_request.header),
                service_exception=to_service_exception(nsi_exc),
            )
            log.debug("Sending response.", response_message=provision_response)
            return provision_response

        from supa.db.session import db_session

        with db_session() as session:
            reservation: Union[model.Reservation, None] = (
                session.query(model.Reservation).filter(model.Reservation.connection_id == connection_id).one_or_none()
            )
            if reservation is None:
                log.info("Connection ID does not exist")
                provision_response = GenericAcknowledgment(
                    header=to_response_header(pb_provision_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            ReservationNonExistent, str(connection_id), {Variable.CONNECTION_ID: str(connection_id)}
                        ),
                        connection_id,
                    ),
                )
            elif not reservation.provision_state:
                log.info("First version of reservation not committed yet")
                provision_response = GenericAcknowledgment(
                    header=to_response_header(pb_provision_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            InvalidTransition,
                            "First version of reservation not committed yet",
                            {
                                Variable.CONNECTION_ID: str(connection_id),
                                Variable.RESERVATION_STATE: reservation.reservation_state,
                            },
                        ),
                        connection_id,
                    ),
                )
            elif (current_time := current_timestamp()) > reservation.schedule.end_time:
                log.info(
                    "Cannot provision a reservation that is passed end time",
                    current_time=current_time.isoformat(),
                    end_time=reservation.schedule.end_time.isoformat(),
                )
                provision_response = GenericAcknowledgment(
                    header=to_response_header(pb_provision_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            GenericServiceError,
                            "Cannot provision a reservation that is passed end time",
                            {
                                Variable.CONNECTION_ID: str(connection_id),
                            },
                        ),
                        connection_id,
                    ),
                )
            else:
                try:
                    rsm = ProvisionStateMachine(reservation, state_field="provision_state")
                    rsm.provision_request()
                except TransitionNotAllowed as tna:
                    log.info("Not scheduling ProvisionJob", reason=str(tna))
                    provision_response = GenericAcknowledgment(
                        header=to_response_header(pb_provision_request.header),
                        service_exception=to_service_exception(
                            NsiException(
                                InvalidTransition,
                                str(tna),
                                {
                                    Variable.CONNECTION_ID: str(connection_id),
                                    Variable.PROVISION_STATE: reservation.provision_state,
                                },
                            ),
                            connection_id,
                        ),
                    )
                else:
                    provision_response = GenericAcknowledgment(header=to_response_header(pb_provision_request.header))

        if not provision_response.service_exception.connection_id:
            from supa import scheduler

            log.info("Schedule provision", job="ProvisionJob")
            _register_request(pb_provision_request, RequestType.Provision)
            scheduler.add_job(job := ProvisionJob(connection_id), trigger=job.trigger(), id=job.job_id)
        log.debug("Sending response.", response_message=provision_response)
        return provision_response

    def Release(self, pb_release_request: GenericRequest, context: ServicerContext) -> GenericAcknowledgment:
        """Release reservation.

        Check if the connection ID exists, if the provision state machine exists (as an indication
        that the reservation was committed), and if the provision state machine transition is
        allowed, all real work for releasing the reservation is done asynchronously by
        :class:`~supa.job.reserve.ReleaseJob`

        Args:
            pb_release_request: Basically the connection id wrapped in a request like object
            context: gRPC server context object.

        Returns:
            A response telling the caller we have received its release request.
        """
        connection_id = UUID(pb_release_request.connection_id)
        log = logger.bind(method="Release", connection_id=str(connection_id))
        log.debug("Received message.", request_message=pb_release_request)

        try:
            _validate_message_header(pb_release_request.header)
        except NsiException as nsi_exc:
            release_response = GenericAcknowledgment(
                header=to_response_header(pb_release_request.header),
                service_exception=to_service_exception(nsi_exc),
            )
            log.debug("Sending response.", response_message=release_response)
            return release_response

        from supa.db.session import db_session

        with db_session() as session:
            reservation: Union[model.Reservation, None] = (
                session.query(model.Reservation).filter(model.Reservation.connection_id == connection_id).one_or_none()
            )
            if reservation is None:
                log.info("Connection ID does not exist")
                release_response = GenericAcknowledgment(
                    header=to_response_header(pb_release_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            ReservationNonExistent, str(connection_id), {Variable.CONNECTION_ID: str(connection_id)}
                        ),
                        connection_id,
                    ),
                )
            elif not reservation.provision_state:
                log.info("First version of reservation not committed yet")
                release_response = GenericAcknowledgment(
                    header=to_response_header(pb_release_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            InvalidTransition,
                            "First version of reservation not committed yet",
                            {
                                Variable.CONNECTION_ID: str(connection_id),
                                Variable.RESERVATION_STATE: reservation.reservation_state,
                            },
                        ),
                        connection_id,
                    ),
                )
            elif (current_time := current_timestamp()) > reservation.schedule.end_time:
                log.info(
                    "Cannot release a reservation that is passed end time",
                    current_time=current_time.isoformat(),
                    end_time=reservation.schedule.end_time.isoformat(),
                )
                release_response = GenericAcknowledgment(
                    header=to_response_header(pb_release_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            GenericServiceError,
                            "Cannot release a reservation that is passed end time",
                            {
                                Variable.CONNECTION_ID: str(connection_id),
                            },
                        ),
                        connection_id,
                    ),
                )
            else:
                try:
                    rsm = ProvisionStateMachine(reservation, state_field="provision_state")
                    rsm.release_request()
                except TransitionNotAllowed as tna:
                    log.info("Not scheduling ReleaseJob", reason=str(tna))
                    release_response = GenericAcknowledgment(
                        header=to_response_header(pb_release_request.header),
                        service_exception=to_service_exception(
                            NsiException(
                                InvalidTransition,
                                str(tna),
                                {
                                    Variable.CONNECTION_ID: str(connection_id),
                                    Variable.PROVISION_STATE: reservation.provision_state,
                                },
                            ),
                            connection_id,
                        ),
                    )
                else:
                    release_response = GenericAcknowledgment(header=to_response_header(pb_release_request.header))

        if not release_response.service_exception.connection_id:
            from supa import scheduler

            log.info("Schedule release", job="ReleaseJob")
            _register_request(pb_release_request, RequestType.Release)
            scheduler.add_job(job := ReleaseJob(connection_id), trigger=job.trigger(), id=job.job_id)
        log.debug("Sending response.", response_message=release_response)
        return release_response

    def Terminate(self, pb_terminate_request: GenericRequest, context: ServicerContext) -> GenericAcknowledgment:
        """Terminate reservation.

        Check if the connection ID exists and if the lifecycle state machine transition is
        allowed, all real work for terminating the reservation is done asynchronously by
        :class:`~supa.job.reserve.TerminateJob`

        Args:
            pb_terminate_request: Basically the connection id wrapped in a request like object
            context: gRPC server context object.

        Returns:
            A response telling the caller we have received its terminate request.
        """
        connection_id = UUID(pb_terminate_request.connection_id)
        log = logger.bind(method="Terminate", connection_id=str(connection_id))
        log.debug("Received message.", request_message=pb_terminate_request)

        try:
            _validate_message_header(pb_terminate_request.header)
        except NsiException as nsi_exc:
            terminate_response = GenericAcknowledgment(
                header=to_response_header(pb_terminate_request.header),
                service_exception=to_service_exception(nsi_exc),
            )
            log.debug("Sending response.", response_message=terminate_response)
            return terminate_response

        from supa.db.session import db_session

        with db_session() as session:
            reservation: Union[model.Reservation, None] = (
                session.query(model.Reservation).filter(model.Reservation.connection_id == connection_id).one_or_none()
            )
            if reservation is None:
                log.info("Connection ID does not exist")
                terminate_response = GenericAcknowledgment(
                    header=to_response_header(pb_terminate_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            ReservationNonExistent, str(connection_id), {Variable.CONNECTION_ID: str(connection_id)}
                        ),
                        connection_id,
                    ),
                )
            else:
                try:
                    lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")
                    lsm.terminate_request()
                except TransitionNotAllowed as tna:
                    log.info("Not scheduling TerminateJob", reason=str(tna))
                    terminate_response = GenericAcknowledgment(
                        header=to_response_header(pb_terminate_request.header),
                        service_exception=to_service_exception(
                            NsiException(
                                InvalidTransition,
                                str(tna),
                                {
                                    Variable.CONNECTION_ID: str(connection_id),
                                    Variable.LIFECYCLE_STATE: reservation.lifecycle_state,
                                },
                            ),
                            connection_id,
                        ),
                    )
                else:
                    terminate_response = GenericAcknowledgment(header=to_response_header(pb_terminate_request.header))

        if not terminate_response.service_exception.connection_id:
            from supa import scheduler

            log.info("Schedule terminate", job="TerminateJob")
            _register_request(pb_terminate_request, RequestType.Terminate)
            scheduler.add_job(job := TerminateJob(connection_id), trigger=job.trigger(), id=job.job_id)
        log.debug("Sending response.", response_message=terminate_response)
        return terminate_response

    def QuerySummary(self, pb_query_request: QueryRequest, context: ServicerContext) -> GenericAcknowledgment:
        """Query reservation(s) summary.

        Start an :class:`~supa.job.reserve.QuerySummaryJob` to gather and return
        all requested information.

        Args:
            pb_query_request: protobuf query request message
            context: gRPC server context object.

        Returns:
            A response telling the caller we have received its query request.
        """
        log = logger.bind(
            method="QuerySummary",
            connection_ids=pb_query_request.connection_id,
            global_reservation_ids=pb_query_request.global_reservation_id,
            if_modified_since=as_utc_timestamp(pb_query_request.if_modified_since).isoformat(),
        )
        log.debug("Received message.", request_message=pb_query_request)

        try:
            _validate_message_header(pb_query_request.header)
        except NsiException as nsi_exc:
            query_response = GenericAcknowledgment(
                header=to_response_header(pb_query_request.header),
                service_exception=to_service_exception(nsi_exc),
            )
            log.debug("Sending response.", response_message=query_response)
            return query_response

        from supa import scheduler

        log.info("Schedule query summary", job="QuerySummaryJob")
        _register_request(pb_query_request, RequestType.QuerySummary)
        scheduler.add_job(
            job := QuerySummaryJob(pb_query_request=pb_query_request),
            trigger=job.trigger(),
            id="=".join(["QuerySummaryJob", str(UUID(pb_query_request.header.correlation_id))]),
        )
        query_response = GenericAcknowledgment(header=to_response_header(pb_query_request.header))
        log.debug("Sending response.", response_message=query_response)
        return query_response

    def QuerySummarySync(self, pb_query_request: QueryRequest, context: ServicerContext) -> QueryConfirmedRequest:
        """Query reservation(s) summary and synchronously return result.

        Args:
            pb_query_request: protobuf query request message
            context: gRPC server context object.

        Returns:
            The matching reservation information.
        """
        log = logger.bind(
            method="QuerySummarySync",
            connection_ids=pb_query_request.connection_id,
            global_reservation_ids=pb_query_request.global_reservation_id,
            if_modified_since=as_utc_timestamp(pb_query_request.if_modified_since).isoformat(),
        )
        log.debug("Received message.", request_message=pb_query_request)
        log.info("Query summary sync")

        try:
            _validate_message_header(pb_query_request.header)
        except NsiException as nsi_exc:
            log.info("QuerySummarySync failed.", reason=nsi_exc.text)
            # TODO: should use interface:error, but we re-raise exception instead
            raise nsi_exc

        _register_request(pb_query_request, RequestType.QuerySummarySync)
        request = create_query_confirmed_request(pb_query_request)
        log.debug("Sending response.", response_message=request)
        return request

    def QueryRecursive(self, pb_query_request: QueryRequest, context: ServicerContext) -> GenericAcknowledgment:
        """Query recursive reservation(s) summary.

        Start an :class:`~supa.job.reserve.QueryRecursiveJob` to gather and return
        all requested information.

        Args:
            pb_query_request: protobuf query request message
            context: gRPC server context object.

        Returns:
            A response telling the caller we have received its query request.
        """
        log = logger.bind(
            method="QueryRecursive",
            connection_ids=pb_query_request.connection_id,
            global_reservation_ids=pb_query_request.global_reservation_id,
            if_modified_since=as_utc_timestamp(pb_query_request.if_modified_since).isoformat(),
        )
        log.debug("Received message.", request_message=pb_query_request)

        try:
            _validate_message_header(pb_query_request.header)
        except NsiException as nsi_exc:
            query_response = GenericAcknowledgment(
                header=to_response_header(pb_query_request.header),
                service_exception=to_service_exception(nsi_exc),
            )
            log.debug("Sending response.", response_message=query_response)
            return query_response

        from supa import scheduler

        log.info("Schedule query recursive", job="QueryRecursiveJob")
        _register_request(pb_query_request, RequestType.QueryRecursive)
        scheduler.add_job(
            job := QueryRecursiveJob(pb_query_request=pb_query_request),
            trigger=job.trigger(),
            id="=".join(["QueryRecursiveJob", str(UUID(pb_query_request.header.correlation_id))]),
        )
        query_response = GenericAcknowledgment(header=to_response_header(pb_query_request.header))
        log.debug("Sending response.", response_message=query_response)
        return query_response

    def QueryNotification(
        self, pb_query_notification_request: QueryNotificationRequest, context: ServicerContext
    ) -> GenericAcknowledgment:
        """Query notification(s).

        Start an :class:`~supa.job.reserve.QueryNotificationJob` to gather and return
        all requested information.

        Args:
            pb_query_notification_request: protobuf query notification request message
            context: gRPC server context object.

        Returns:
            A response telling the caller we have received its query request.
        """
        log = logger.bind(
            method="QueryNotification",
            connection_id=pb_query_notification_request.connection_id,
            start_notification_id=pb_query_notification_request.start_notification_id,
            end_notification_id=pb_query_notification_request.end_notification_id,
        )
        log.debug("Received message.", request_message=pb_query_notification_request)

        try:
            _validate_message_header(pb_query_notification_request.header)
        except NsiException as nsi_exc:
            response = GenericAcknowledgment(
                header=to_response_header(pb_query_notification_request.header),
                service_exception=to_service_exception(nsi_exc),
            )
            log.debug("Sending response.", response_message=response)
            return response

        from supa import scheduler

        log.info("Schedule query notification", job="QueryNotificationJob")
        _register_request(pb_query_notification_request, RequestType.QueryNotification)
        scheduler.add_job(
            job := QueryNotificationJob(pb_query_notification_request=pb_query_notification_request),
            trigger=job.trigger(),
            id="=".join(["QueryNotificationJob", str(UUID(pb_query_notification_request.header.correlation_id))]),
        )
        response = GenericAcknowledgment(header=to_response_header(pb_query_notification_request.header))
        log.debug("Sending response.", response_message=response)
        return response

    def QueryNotificationSync(
        self, pb_query_notification_request: QueryNotificationRequest, context: ServicerContext
    ) -> QueryNotificationConfirmedRequest:
        """Return a QueryNotificationConfirmedRequest bypassing the usual Response message.

        Args:
            pb_query_notification_request: protobuf query notification request message
            context: gRPC server context object.

        Returns:
            A response containing the requested notifications for this connection ID.
        """
        log = logger.bind(
            method="QueryNotificationSync",
            connection_id=pb_query_notification_request.connection_id,
            start_notification_id=pb_query_notification_request.start_notification_id,
            end_notification_id=pb_query_notification_request.end_notification_id,
        )
        log.debug("Received message.", request_message=pb_query_notification_request)
        log.info("Query notification sync")

        try:
            _validate_message_header(pb_query_notification_request.header)
        except NsiException as nsi_exc:
            log.info("QuerySummarySync failed.", reason=nsi_exc.text)
            # TODO: should use interface:error, but we re-raise exception instead
            raise nsi_exc

        _register_request(pb_query_notification_request, RequestType.QueryNotificationSync)
        request = create_query_notification_confirmed_request(pb_query_notification_request)
        log.debug("Sending response.", response_message=request)
        return request

    def QueryResult(
        self, pb_query_result_request: QueryResultRequest, context: ServicerContext
    ) -> GenericAcknowledgment:
        """Query result(s).

        Start an :class:`~supa.job.reserve.QueryResultJob` to gather and return
        all requested information.

        Args:
            pb_query_result_request: protobuf query result request message
            context: gRPC server context object.

        Returns:
            A response telling the caller we have received its query request.
        """
        log = logger.bind(
            method="QueryResult",
            connection_id=pb_query_result_request.connection_id,
            start_result_id=pb_query_result_request.start_result_id,
            end_result_id=pb_query_result_request.end_result_id,
        )
        log.debug("Received message.", request_message=pb_query_result_request)

        try:
            _validate_message_header(pb_query_result_request.header)
        except NsiException as nsi_exc:
            response = GenericAcknowledgment(
                header=to_response_header(pb_query_result_request.header),
                service_exception=to_service_exception(nsi_exc),
            )
            log.debug("Sending response.", response_message=response)
            return response

        from supa import scheduler

        log.info("Schedule query result", job="QueryResultJob")
        _register_request(pb_query_result_request, RequestType.QueryResult)
        scheduler.add_job(
            job := QueryResultJob(pb_query_result_request=pb_query_result_request),
            trigger=job.trigger(),
            id="=".join(["QueryResultJob", str(UUID(pb_query_result_request.header.correlation_id))]),
        )
        response = GenericAcknowledgment(header=to_response_header(pb_query_result_request.header))
        log.debug("Sending response.", response_message=response)
        return response

    def QueryResultSync(
        self, pb_query_result_request: QueryResultRequest, context: ServicerContext
    ) -> QueryResultConfirmedRequest:
        """Return a QueryResultConfirmedRequest bypassing the usual Response message.

        Args:
            pb_query_result_request: protobuf query result request message
            context: gRPC server context object.

        Returns:
            A response containing the requested results for this connection ID.
        """
        log = logger.bind(
            method="QueryResultSync",
            connection_id=pb_query_result_request.connection_id,
            start_result_id=pb_query_result_request.start_result_id,
            end_result_id=pb_query_result_request.end_result_id,
        )
        log.debug("Received message.", request_message=pb_query_result_request)
        log.info("Query result sync")

        try:
            _validate_message_header(pb_query_result_request.header)
        except NsiException as nsi_exc:
            log.info("QuerySummarySync failed.", reason=nsi_exc.text)
            # TODO: should use interface:error, but we re-raise exception instead
            raise nsi_exc

        _register_request(pb_query_result_request, RequestType.QueryResultSync)
        request = create_query_result_confirmed_request(pb_query_result_request)
        log.debug("Sending response.", response_message=request)
        return request
