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
"""Module with function for communication with the PolyNSI connection requester."""
from uuid import UUID

import grpc
import structlog

from supa import settings
from supa.connection.fsm import DataPlaneStateMachine
from supa.db.model import Reservation
from supa.grpc_nsi.connection_common_pb2 import Header, Notification
from supa.grpc_nsi.connection_requester_pb2 import DataPlaneStateChangeRequest, ErrorRequest
from supa.grpc_nsi.connection_requester_pb2_grpc import ConnectionRequesterStub
from supa.job.shared import NsiException
from supa.util.converter import to_header
from supa.util.timestamp import current_timestamp

logger = structlog.get_logger(__name__)


def get_stub() -> ConnectionRequesterStub:
    """Get the connection requester stub."""
    channel = grpc.insecure_channel(settings.grpc_client_insecure_address_port)
    stub = ConnectionRequesterStub(channel)
    return stub


def to_error_request(request_header: Header, nsi_exc: NsiException, connection_id: UUID) -> ErrorRequest:
    """Return a NSI ErrorRequest referencing the request correlation_id together with details from the NsiException.

    The error message is sent from a PA to an RA in response to an outstanding operation request
    when an error condition encountered, and as a result, the operation cannot be successfully completed.
    The correlationId carried in the NSI CS header structure will identify the original request associated
    with this error message.
    """
    from supa.util.converter import to_service_exception

    pb_e_req = ErrorRequest()
    pb_e_req.header.CopyFrom(request_header)
    pb_e_req.service_exception.CopyFrom(to_service_exception(nsi_exc, connection_id))

    return pb_e_req


def new_notification_header(reservation: Reservation) -> Notification:
    """Return new notification with unique id in the context of the reservation."""
    pb_n_header = Notification()

    pb_n_header.connection_id = str(reservation.connection_id)
    pb_n_header.notification_id = 1  # TODO Add Column to database for unique notification ID for this reservation.
    pb_n_header.time_stamp.FromDatetime(current_timestamp())

    return pb_n_header


def to_data_plane_state_change_request(reservation: Reservation) -> DataPlaneStateChangeRequest:
    """Send a NSI dataPlaneStateChange notification.

    The dataPlaneStateChange is an autonomous notification sent from a PA to an RA
    to inform about a change in status of the data plane.
    """
    dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
    pb_dpsc_req = DataPlaneStateChangeRequest()

    pb_dpsc_req.header.CopyFrom(to_header(reservation, add_path_segment=True))  # Yes, add our segment!
    pb_dpsc_req.notification.CopyFrom(new_notification_header(reservation))
    pb_dpsc_req.data_plane_status.version = reservation.version
    pb_dpsc_req.data_plane_status.version_consistent = True  # always True for an uPA
    pb_dpsc_req.data_plane_status.active = dpsm.current_state == DataPlaneStateMachine.Activated

    return pb_dpsc_req
