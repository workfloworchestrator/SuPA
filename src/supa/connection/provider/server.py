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
from uuid import uuid4

import structlog
from grpc import ServicerContext

from supa.grpc_nsi import connection_provider_pb2_grpc
from supa.grpc_nsi.connection_provider_pb2 import ReserveRequest, ReserveResponse

logger = structlog.get_logger(__name__)


class ConnectionProviderService(connection_provider_pb2_grpc.ConnectionProviderServicer):
    def Reserve(self, reserve_request: ReserveRequest, context: ServicerContext) -> ReserveResponse:
        log = logger.bind(method="Reserve")
        logger.info("Message received.", request_message=reserve_request)

        connection_id = "urn:uuid:{}".format(uuid4())
        reserve_response = ReserveResponse(header=reserve_request.header, connection_id=connection_id)

        log.info("Sending response.", response_message=reserve_response)
        return reserve_response
