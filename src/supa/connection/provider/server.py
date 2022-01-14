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
from uuid import UUID

import structlog
from grpc import ServicerContext
from statemachine.exceptions import TransitionNotAllowed

from supa.connection.error import (
    GenericServiceError,
    InvalidTransition,
    MissingParameter,
    ReservationNonExistent,
    Variable,
)
from supa.connection.fsm import LifecycleStateMachine, ProvisionStateMachine, ReservationStateMachine
from supa.db import model
from supa.grpc_nsi import connection_provider_pb2_grpc
from supa.grpc_nsi.connection_common_pb2 import Header, Schedule
from supa.grpc_nsi.connection_provider_pb2 import (
    ProvisionRequest,
    ProvisionResponse,
    ReleaseRequest,
    ReleaseResponse,
    ReservationRequestCriteria,
    ReserveAbortRequest,
    ReserveAbortResponse,
    ReserveCommitRequest,
    ReserveCommitResponse,
    ReserveRequest,
    ReserveResponse,
    TerminateRequest,
    TerminateResponse,
)
from supa.grpc_nsi.policy_pb2 import PathTrace
from supa.grpc_nsi.services_pb2 import Directionality, PointToPointService
from supa.job.lifecycle import TerminateJob
from supa.job.provision import ProvisionJob, ReleaseJob
from supa.job.reserve import ReserveAbortJob, ReserveCommitJob, ReserveJob, ReserveTimeoutJob
from supa.job.shared import Job, NsiException
from supa.util.converter import to_response_header, to_service_exception
from supa.util.nsi import parse_stp
from supa.util.timestamp import as_utc_timestamp, current_timestamp, is_specified

logger = structlog.get_logger(__name__)


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

        # Sanity check on start and end time, in case of problem return ServiceException
        pb_criteria: ReservationRequestCriteria = pb_reserve_request.criteria
        pb_schedule: Schedule = pb_criteria.schedule
        start_time = as_utc_timestamp(pb_schedule.start_time)
        end_time = as_utc_timestamp(pb_schedule.end_time)
        extra_info = ""
        if is_specified(end_time):
            if end_time <= start_time:
                extra_info = f"End time cannot come before start time. {start_time=!s}, {end_time=!s}"
            elif end_time <= current_timestamp():
                extra_info = f"End time lies in the past. {end_time=!s}"
        if extra_info:
            log.info(extra_info)
            reserve_response = ReserveResponse(
                header=to_response_header(pb_reserve_request.header),
                service_exception=to_service_exception(
                    NsiException(MissingParameter, extra_info, {Variable.END_TIME: end_time.isoformat()})
                ),
            )
            log.debug("Sending response.", response_message=reserve_response)
            return reserve_response

        if not pb_reserve_request.connection_id:  # new reservation
            pb_header: Header = pb_reserve_request.header
            pb_ptps: PointToPointService = pb_criteria.ptps
            pb_path_trace: PathTrace = pb_header.path_trace

            reservation = model.Reservation(
                correlation_id=UUID(pb_header.correlation_id),
                protocol_version=pb_header.protocol_version,
                requester_nsa=pb_header.requester_nsa,
                provider_nsa=pb_header.provider_nsa,
                reply_to=pb_header.reply_to if pb_header.reply_to else None,
                session_security_attributes=pb_header.session_security_attributes
                if pb_header.session_security_attributes
                else None,
                global_reservation_id=pb_reserve_request.global_reservation_id,
                description=pb_reserve_request.description if pb_reserve_request.description else None,
                version=pb_criteria.version,
            )
            if is_specified(start_time):
                reservation.start_time = start_time
            if is_specified(end_time):
                reservation.end_time = end_time
            reservation.bandwidth = pb_ptps.capacity
            reservation.directionality = Directionality.Name(pb_ptps.directionality)
            reservation.symmetric = pb_ptps.symmetric_path

            src_stp = parse_stp(pb_ptps.source_stp)
            reservation.src_domain = src_stp.domain
            reservation.src_network_type = src_stp.network_type
            reservation.src_port = src_stp.port
            reservation.src_vlans = str(src_stp.vlan_ranges)

            dst_stp = parse_stp(pb_ptps.dest_stp)
            reservation.dst_domain = dst_stp.domain
            reservation.dst_network_type = dst_stp.network_type
            reservation.dst_port = dst_stp.port
            reservation.dst_vlans = str(dst_stp.vlan_ranges)

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
                connection_id = reservation.connection_id  # Can't reference it outside of the session, hence new var.

            log = log.bind(connection_id=str(connection_id))

        else:
            log = log.bind(connection_id=pb_reserve_request.connection_id)
            # TODO modify reservation (else clause)

        from supa import scheduler

        job: Job

        scheduler.add_job(
            job := ReserveJob(connection_id), trigger=job.trigger(), id=f"{str(connection_id)}-ReserveJob"
        )
        reserve_response = ReserveResponse(
            header=to_response_header(pb_reserve_request.header), connection_id=str(connection_id)
        )
        #
        # TODO: - make timeout delta configurable
        #       - add reservation version to timeout job so we do not accidentally timeout a modify
        #
        log.info("Schedule reserve timeout", connection_id=str(connection_id), timeout=30)
        scheduler.add_job(
            job := ReserveTimeoutJob(connection_id),
            trigger=job.trigger(),
            id=f"{str(connection_id)}-ReserveTimeoutJob",
        )

        log.debug("Sending response.", response_message=reserve_response)
        return reserve_response

    def ReserveCommit(
        self, pb_reserve_commit_request: ReserveCommitRequest, context: ServicerContext
    ) -> ReserveCommitResponse:
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

        from supa.db.session import db_session

        with db_session() as session:
            reservation = (
                session.query(model.Reservation).filter(model.Reservation.connection_id == connection_id).one_or_none()
            )
            if reservation is None:
                log.info("Connection ID does not exist")
                reserve_commit_response = ReserveCommitResponse(
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
                reserve_commit_response = ReserveCommitResponse(
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
                    reserve_commit_response = ReserveCommitResponse(
                        header=to_response_header(pb_reserve_commit_request.header),
                        service_exception=to_service_exception(
                            NsiException(
                                InvalidTransition,
                                str(tna),
                                {
                                    Variable.RESERVATION_STATE: reservation.reservation_state,
                                    Variable.CONNECTION_ID: str(connection_id),
                                },
                            ),
                            connection_id,
                        ),
                    )
                else:
                    from supa import scheduler

                    scheduler.remove_job(job_id=f"{str(connection_id)}-ReserveTimeoutJob")
                    log.info("Canceled reservation timeout timer")
                    scheduler.add_job(
                        job := ReserveCommitJob(connection_id),
                        trigger=job.trigger(),
                        id=f"{str(connection_id)}-ReserveCommitJob",
                    )
                    reserve_commit_response = ReserveCommitResponse(
                        header=to_response_header(pb_reserve_commit_request.header)
                    )

        log.debug("Sending response.", response_message=reserve_commit_response)
        return reserve_commit_response

    def ReserveAbort(
        self, pb_reserve_abort_request: ReserveAbortRequest, context: ServicerContext
    ) -> ReserveAbortResponse:
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

        from supa.db.session import db_session

        with db_session() as session:
            reservation = (
                session.query(model.Reservation).filter(model.Reservation.connection_id == connection_id).one_or_none()
            )
            if reservation is None:
                log.info("Connection ID does not exist")
                reserve_abort_response = ReserveAbortResponse(
                    header=to_response_header(pb_reserve_abort_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            ReservationNonExistent, str(connection_id), {Variable.CONNECTION_ID: str(connection_id)}
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
                    reserve_abort_response = ReserveAbortResponse(
                        header=to_response_header(pb_reserve_abort_request.header),
                        service_exception=to_service_exception(
                            NsiException(
                                InvalidTransition,
                                str(tna),
                                {
                                    Variable.RESERVATION_STATE: reservation.reservation_state,
                                    Variable.CONNECTION_ID: str(connection_id),
                                },
                            ),
                            connection_id,
                        ),
                    )
                else:
                    from supa import scheduler

                    scheduler.add_job(
                        job := ReserveAbortJob(connection_id),
                        trigger=job.trigger(),
                        id=f"{str(connection_id)}-ReserveAbortJob",
                    )
                    reserve_abort_response = ReserveAbortResponse(
                        header=to_response_header(pb_reserve_abort_request.header)
                    )

        log.debug("Sending response.", response_message=reserve_abort_response)
        return reserve_abort_response

    def Provision(self, pb_provision_request: ProvisionRequest, context: ServicerContext) -> ProvisionResponse:
        """Provision reservation.

        Check if the connection ID exists, if the provision state machine exists (as an indication
        that the reservation was committed, and if the provision state machine transition is
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

        from supa.db.session import db_session

        with db_session() as session:
            reservation = (
                session.query(model.Reservation).filter(model.Reservation.connection_id == connection_id).one_or_none()
            )
            if reservation is None:
                log.info("Connection ID does not exist")
                provision_response = ProvisionResponse(
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
                provision_response = ProvisionResponse(
                    header=to_response_header(pb_provision_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            InvalidTransition,
                            "First version of reservation not committed yet",
                            {
                                Variable.RESERVATION_STATE: reservation.reservation_state,
                                Variable.CONNECTION_ID: str(connection_id),
                            },
                        ),
                        connection_id,
                    ),
                )
            elif current_timestamp() > reservation.end_time:
                log.info("Cannot provision a timed out reservation")
                provision_response = ProvisionResponse(
                    header=to_response_header(pb_provision_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            GenericServiceError,
                            "Cannot provision a timed out reservation",
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
                    provision_response = ProvisionResponse(
                        header=to_response_header(pb_provision_request.header),
                        service_exception=to_service_exception(
                            NsiException(
                                InvalidTransition,
                                str(tna),
                                {
                                    Variable.PROVISION_STATE: reservation.provision_state,
                                    Variable.CONNECTION_ID: str(connection_id),
                                },
                            ),
                            connection_id,
                        ),
                    )
                else:
                    from supa import scheduler

                    scheduler.add_job(
                        job := ProvisionJob(connection_id),
                        trigger=job.trigger(),
                        id=f"{str(connection_id)}-ProvisionJob",
                    )
                    provision_response = ProvisionResponse(header=to_response_header(pb_provision_request.header))

        log.debug("Sending response.", response_message=provision_response)
        return provision_response

    def Release(self, pb_release_request: ReleaseRequest, context: ServicerContext) -> ReleaseResponse:
        """Release reservation.

        Check if the connection ID exists, if the provision state machine exists (as an indication
        that the reservation was committed, and if the provision state machine transition is
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

        from supa.db.session import db_session

        with db_session() as session:
            reservation = (
                session.query(model.Reservation).filter(model.Reservation.connection_id == connection_id).one_or_none()
            )
            if reservation is None:
                log.info("Connection ID does not exist")
                release_response = ReleaseResponse(
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
                release_response = ReleaseResponse(
                    header=to_response_header(pb_release_request.header),
                    service_exception=to_service_exception(
                        NsiException(
                            InvalidTransition,
                            "First version of reservation not committed yet",
                            {
                                Variable.RESERVATION_STATE: reservation.reservation_state,
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
                    release_response = ReleaseResponse(
                        header=to_response_header(pb_release_request.header),
                        service_exception=to_service_exception(
                            NsiException(
                                InvalidTransition,
                                str(tna),
                                {
                                    Variable.PROVISION_STATE: reservation.provision_state,
                                    Variable.CONNECTION_ID: str(connection_id),
                                },
                            ),
                            connection_id,
                        ),
                    )
                else:
                    from supa import scheduler

                    scheduler.add_job(
                        job := ReleaseJob(connection_id),
                        trigger=job.trigger(),
                        id=f"{str(connection_id)}-ReleaseJob",
                    )
                    release_response = ReleaseResponse(header=to_response_header(pb_release_request.header))

        log.debug("Sending response.", response_message=release_response)
        return release_response

    def Terminate(self, pb_terminate_request: TerminateRequest, context: ServicerContext) -> TerminateResponse:
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

        from supa.db.session import db_session

        with db_session() as session:
            reservation = (
                session.query(model.Reservation).filter(model.Reservation.connection_id == connection_id).one_or_none()
            )
            if reservation is None:
                log.info("Connection ID does not exist")
                terminate_response = TerminateResponse(
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
                    terminate_response = TerminateResponse(
                        header=to_response_header(pb_terminate_request.header),
                        service_exception=to_service_exception(
                            NsiException(
                                InvalidTransition,
                                str(tna),
                                {
                                    Variable.PROVISION_STATE: reservation.lifecycle_state,
                                    Variable.CONNECTION_ID: str(connection_id),
                                },
                            ),
                            connection_id,
                        ),
                    )
                else:
                    from supa import scheduler

                    scheduler.add_job(
                        job := TerminateJob(connection_id),
                        trigger=job.trigger(),
                        id=f"{str(connection_id)}-TerminateJob",
                    )
                    terminate_response = TerminateResponse(header=to_response_header(pb_terminate_request.header))

        log.debug("Sending response.", response_message=terminate_response)
        return terminate_response
