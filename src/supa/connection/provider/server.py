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

from uuid import uuid4

import structlog
from grpc import ServicerContext

from supa.grpc_nsi import connection_provider_pb2_grpc
from supa.grpc_nsi.connection_provider_pb2 import ReserveRequest, ReserveResponse

logger = structlog.get_logger(__name__)


class ConnectionProviderService(connection_provider_pb2_grpc.ConnectionProviderServicer):
    """Implementation of the gRPC Connection Provider Service.

    Each of the methods in this class corresponds to gRPC defined ``rpc`` calls in the ``connection.provider``
    gPRC package.
    """

    def Reserve(self, reserve_request: ReserveRequest, context: ServicerContext) -> ReserveResponse:
        """Request new reservation, or modify existing reservation.

        The reserve message is sent from an RA to a PA when a new reservation is being requested, or
        a modification to an existing reservation is required. The :class:`ReserveResponse` indicates that the PA
        has accepted the reservation request for processing and has assigned it the returned
        connectionId. The original ``connection_id`` will be returned for the :class:`ReserveResponse`` of a
        modification. A :class:`ReserveConfirmed` or :class:`ReserveFailed` message will be sent asynchronously to the
        RA when reserve operation has completed processing.

        Args:
            reserve_request: All the details about the requested reservation.
            context: gRPC server context object.

        Returns:
            A :class:`ReserveResponse` message containing the PA assigned ``connection_id`` for this reservation
            request. This value will be unique within the context of the PA.

        """
        log = logger.bind(method="Reserve")
        logger.info("Message received.", request_message=reserve_request)

        connection_id = f"urn:uuid:{uuid4()}"
        reserve_response = ReserveResponse(header=reserve_request.header, connection_id=connection_id)

        log.info("Sending response.", response_message=reserve_response)
        return reserve_response
