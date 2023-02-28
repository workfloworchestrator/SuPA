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
"""Converter functions for converting data to and from Protobuf messages."""
from typing import Optional
from uuid import UUID, uuid4

from supa import const, settings
from supa.connection.fsm import DataPlaneStateMachine
from supa.db import model
from supa.db.model import Reservation
from supa.grpc_nsi.connection_common_pb2 import (
    ConnectionStates,
    EventType,
    Header,
    LifecycleState,
    Notification,
    ProvisionState,
    ReservationState,
    Schedule,
    ServiceException,
    TypeValuePair,
)
from supa.grpc_nsi.connection_requester_pb2 import (
    DataPlaneStateChangeRequest,
    ErrorEventRequest,
    ErrorRequest,
    GenericConfirmedRequest,
    GenericFailedRequest,
    QueryResultCriteria,
    ReservationConfirmCriteria,
)
from supa.grpc_nsi.policy_pb2 import Segment
from supa.grpc_nsi.services_pb2 import PointToPointService
from supa.job.shared import NsiException
from supa.util.timestamp import NO_END_DATE, current_timestamp


def to_header(reservation: model.Reservation, *, add_path_segment: bool = False) -> Header:
    """Create Protobuf ``Header`` out of DB stored reservation data.

    .. warning::

        Using a DB model can be tricky.
        This function should either be called within a active SQLAlchemy session.
        Or it should be called with a :class:`~supa.db.model.Reservation` model
        that has been detached for a session.
        In case of the latter
        one should make sure that all relations have been eagerly loaded,
        as a detached model has no ability to load unload attributes.

        See also: https://docs.sqlalchemy.org/en/13/orm/session_state_management.html#session-object-states

    Args:
        reservation: DB model
        add_path_segment: Should we add our own Segment to the PathTrace?

    Returns:
        A Protobuf ``Header`` object.
    """
    pb_header = Header()
    pb_header.protocol_version = reservation.protocol_version
    pb_header.correlation_id = reservation.correlation_id.urn
    pb_header.requester_nsa = reservation.requester_nsa
    pb_header.provider_nsa = reservation.provider_nsa
    if reservation.reply_to is not None:
        pb_header.reply_to = reservation.reply_to
    if reservation.session_security_attributes:
        pb_header.session_security_attributes = reservation.session_security_attributes
    if reservation.path_trace:
        pb_header.path_trace.id = reservation.path_trace.path_trace_id
        pb_header.path_trace.connection_id = reservation.path_trace.ag_connection_id
        path: model.Path

        # A PathTrace can have multiple Paths according to its (WSDL) schema definition.
        # This has been has been carried over to the Protobuf definition.
        # However all examples in the specification always have only one Path!
        # Nor does the specification explain what multiple Paths even mean
        # or how we should deal with them.
        # With the specification inconclusive we have to make decision.
        # In case of multiple Path we will add our Segment to the last one!
        num_paths = len(reservation.path_trace.paths)
        for cur_path_num, path in enumerate(reservation.path_trace.paths, start=1):
            pb_path = pb_header.path_trace.paths.add()
            segment: model.Segment
            for segment in path.segments:
                pb_segment = pb_path.segments.add()
                pb_segment.id = segment.segment.id
                pb_segment.connection_id = segment.upa_connection_id
                stp: model.Stp
                for stp in segment.stps:
                    pb_segment.stps.append(stp.stp_id)
            if add_path_segment and cur_path_num == num_paths:
                pb_segment = Segment()
                pb_segment.id = settings.get_nsa_id()
                pb_segment.connection_id = str(reservation.connection_id)
                pb_segment.stps.extend([reservation.src_stp(selected=True), reservation.dst_stp(selected=True)])
                pb_path.append(pb_segment)
    return pb_header


def to_connection_states(reservation: model.Reservation, *, data_plane_active: bool = False) -> ConnectionStates:
    """Create Protobuf ``ConnectionStates`` out of DB stored reservation data.

    See Also: warning in :func:`to_header`

    Args:
        reservation: DB model
        data_plane_active: Whether the data plane is active or not.

    Returns:
        A Protobuf ``ConnectionStates`` object.
    """
    pb_cs = ConnectionStates()
    pb_cs.reservation_state = ReservationState.Value(reservation.reservation_state)
    if reservation.provision_state is not None:
        pb_cs.provision_state = ProvisionState.Value(reservation.provision_state)
    pb_cs.lifecycle_state = LifecycleState.Value(reservation.lifecycle_state)
    pb_cs.data_plane_status.active = data_plane_active
    pb_cs.data_plane_status.version = reservation.version
    pb_cs.data_plane_status.version_consistent = True  # always True for an uPA
    return pb_cs


def to_service_exception(nsi_exc: NsiException, connection_id: Optional[UUID] = None) -> ServiceException:
    """Create Protobuf ``ServiceException`` out of an NsiException.

    Args:
        nsi_exc: The NsiException to convert.
        connection_id: The connnection_id of the Reservation the exception pertains to.

    Returns:
        A ``ServiceException``.
    """
    pb_se = ServiceException()
    pb_se.nsa_id = settings.get_nsa_id()
    if connection_id:
        pb_se.connection_id = str(connection_id)
    pb_se.error_id = nsi_exc.nsi_error.error_id
    pb_se.text = nsi_exc.text
    for var in nsi_exc.variables:
        tvp = TypeValuePair()
        tvp.type = var.variable
        tvp.namespace = var.namespace
        tvp.value = nsi_exc.variables[var]
        pb_se.variables.append(tvp)
    return pb_se


def to_schedule(reservation: model.Reservation) -> Schedule:
    """Create Protobuf ``Schedule`` out of DB stored reservation data.

    See Also: warning in :func:`to_header`

    Args:
        reservation: DB model

    Returns:
        A Schedule object.
    """
    pb_s = Schedule()
    pb_s.start_time.FromDatetime(reservation.start_time)
    if not reservation.end_time == NO_END_DATE:
        pb_s.end_time.FromDatetime(reservation.end_time)
    return pb_s


def to_p2p_service(reservation: model.Reservation) -> PointToPointService:
    """Create Protobuf ``PointToPointService`` out of DB stored reservation data.

    See Also: warning in :func:`to_header`

    Args:
        reservation: DB Model

    Returns:
        A ``PointToPointService`` object.
    """
    pb_ptps = PointToPointService()
    pb_ptps.capacity = reservation.bandwidth
    pb_ptps.symmetric_path = reservation.symmetric
    pb_ptps.source_stp = str(reservation.src_stp(selected=True))
    pb_ptps.dest_stp = str(reservation.dst_stp(selected=True))
    # The initial version didn't have to support Explicit Routing Objects.
    for param in reservation.parameters:
        pb_ptps.parameters[param.key] = param.value
    return pb_ptps


def to_confirm_criteria(reservation: model.Reservation) -> ReservationConfirmCriteria:
    """Create Protobuf ``ReservationConfirmCriteria`` out of DB stored reservation data.

    Args:
        reservation: DB Model

    Returns:
        A ``ReservationConfirmCriteria`` object.
    """
    pb_rcc = ReservationConfirmCriteria()
    pb_rcc.version = reservation.version
    pb_rcc.schedule.CopyFrom(to_schedule(reservation))
    pb_rcc.serviceType = const.SERVICE_TYPE
    pb_rcc.ptps.CopyFrom(to_p2p_service(reservation))
    return pb_rcc


def to_criteria(reservation: model.Reservation) -> QueryResultCriteria:
    """Create Protobuf ``QueryResultCriteria`` out of DB stored reservation data.

    Args:
        reservation: DB Model

    Returns:
        A ``QueryResultCriteria`` object.
    """
    pb_rsc = QueryResultCriteria()
    pb_rsc.version = reservation.version
    pb_rsc.schedule.CopyFrom(to_schedule(reservation))
    pb_rsc.service_type = const.SERVICE_TYPE
    # Leave empty as this is an uPA, and uPA's do not have children
    # pb_rsc.child
    pb_rsc.ptps.CopyFrom(to_p2p_service(reservation))
    return pb_rsc


def to_response_header(request_header: Header) -> Header:
    """Create Protobuf response ``Header`` out of a Protobuf request ``Header``.

    The reply_to field holds the Requester NSA's SOAP endpoint address to which
    asynchronous messages associated with this operation request will be delivered.
    This is only populated for the original operation request (reserve, provision,
    release, terminate and query), and not for any additional messaging associated
    with the operation.

    Args:
        request_header: Protobuf Header from request messsage.

    Returns:
        A ``Header`` copy of the input with reply_to cleared.
    """
    response_header = Header()
    response_header.CopyFrom(request_header)
    response_header.ClearField("reply_to")
    return response_header


def to_error_request(request_header: Header, nsi_exc: NsiException, connection_id: UUID) -> ErrorRequest:
    """Return a NSI ErrorRequest referencing the request correlation_id together with details from the NsiException.

    The error message is sent from a PA to an RA in response to an outstanding operation request
    when an error condition encountered, and as a result, the operation cannot be successfully completed.
    The correlationId carried in the NSI CS header structure will identify the original request associated
    with this error message.
    """
    pb_e_req = ErrorRequest()
    pb_e_req.header.CopyFrom(request_header)
    pb_e_req.service_exception.CopyFrom(to_service_exception(nsi_exc, connection_id))

    return pb_e_req


def to_notification_header(reservation: model.Reservation) -> Notification:
    """Return new notification with unique id in the context of the reservation."""
    pb_n_header = Notification()

    pb_n_header.connection_id = str(reservation.connection_id)
    # a unique id is assigned to notification_id when it is stored in the database just before it is sent
    pb_n_header.time_stamp.FromDatetime(current_timestamp())

    return pb_n_header


def to_data_plane_state_change_request(reservation: model.Reservation) -> DataPlaneStateChangeRequest:
    """Return a NSI dataPlaneStateChange notification.

    The dataPlaneStateChange is an autonomous notification sent from a PA to an RA
    to inform about a change in status of the data plane.
    """
    dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
    pb_dpsc_req = DataPlaneStateChangeRequest()

    pb_dpsc_req.header.CopyFrom(to_header(reservation, add_path_segment=True))  # Yes, add our segment!
    pb_dpsc_req.notification.CopyFrom(to_notification_header(reservation))
    pb_dpsc_req.data_plane_status.version = reservation.version
    pb_dpsc_req.data_plane_status.version_consistent = True  # always True for an uPA
    pb_dpsc_req.data_plane_status.active = dpsm.current_state == DataPlaneStateMachine.Activated

    return pb_dpsc_req


def to_error_event(reservation: model.Reservation, nsi_exc: NsiException, event: int) -> ErrorEventRequest:
    """Return a NSI Error Event notification.

    An Error Event is an autonomous message issued from a Provider NSA to
    a Requester NSA when an existing reservation encounters an
    autonomous error condition such as being administratively terminated
    before the reservation's scheduled end-time.
    """
    pb_header = Header()
    pb_header.protocol_version = reservation.protocol_version
    pb_header.correlation_id = uuid4().urn
    pb_header.requester_nsa = reservation.requester_nsa
    pb_header.provider_nsa = reservation.provider_nsa
    pb_header.reply_to = reservation.reply_to

    pb_ee_req = ErrorEventRequest()
    pb_ee_req.header.CopyFrom(pb_header)
    pb_ee_req.notification.CopyFrom(to_notification_header(reservation))
    pb_ee_req.event = event
    pb_ee_req.originating_connection_id = str(reservation.connection_id)
    pb_ee_req.originating_nsa = reservation.provider_nsa
    for var in nsi_exc.variables:
        tvp = TypeValuePair()
        tvp.type = var.variable
        tvp.namespace = var.namespace
        tvp.value = nsi_exc.variables[var]
        pb_ee_req.additional_info.append(tvp)
    pb_ee_req.service_exception.CopyFrom(to_service_exception(nsi_exc, reservation.connection_id))

    return pb_ee_req


def to_activate_failed_event(reservation: model.Reservation, nsi_exc: NsiException) -> ErrorEventRequest:
    """Return a NSI Error Event of type Activate Failed."""
    return to_error_event(reservation, nsi_exc, EventType.ACTIVATE_FAILED)


def to_deactivate_failed_event(reservation: model.Reservation, nsi_exc: NsiException) -> ErrorEventRequest:
    """Return a NSI Error Event of type Deactivate Failed."""
    return to_error_event(reservation, nsi_exc, EventType.DEACTIVATE_FAILED)


def to_dataplane_error_event(reservation: model.Reservation, nsi_exc: NsiException) -> ErrorEventRequest:
    """Return a NSI Error Event of type Dataplane Error."""
    return to_error_event(reservation, nsi_exc, EventType.DATAPLANE_ERROR)


def to_forced_end_event(reservation: model.Reservation, nsi_exc: NsiException) -> ErrorEventRequest:
    """Return a NSI Error Event of type Forced End."""
    return to_error_event(reservation, nsi_exc, EventType.FORCED_END)


def to_generic_confirmed_request(reservation: Reservation) -> GenericConfirmedRequest:
    """Create a protobuf generic confirmed request from a Reservation."""
    pb_gc_req = GenericConfirmedRequest()
    pb_gc_req.header.CopyFrom(to_header(reservation, add_path_segment=True))  # Yes, add our segment!
    pb_gc_req.connection_id = str(reservation.connection_id)
    return pb_gc_req


def to_generic_failed_request(reservation: Reservation, nsi_exc: NsiException) -> GenericFailedRequest:
    """Create a protobuf generic failed request from a Reservation and NsiException."""
    pb_gf_req = GenericFailedRequest()
    pb_gf_req.header.CopyFrom(to_header(reservation, add_path_segment=False))
    pb_gf_req.connection_id = str(reservation.connection_id)
    pb_gf_req.connection_states.CopyFrom(to_connection_states(reservation, data_plane_active=False))
    pb_gf_req.service_exception.CopyFrom(to_service_exception(nsi_exc, reservation.connection_id))
    return pb_gf_req
