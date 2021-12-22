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

from supa import settings
from supa.grpc_nsi.connection_common_pb2 import Header
from supa.grpc_nsi.connection_requester_pb2 import ErrorRequest
from supa.grpc_nsi.connection_requester_pb2_grpc import ConnectionRequesterStub
from supa.job.shared import NsiException


def get_stub() -> ConnectionRequesterStub:
    """Get the connection requester stub."""
    channel = grpc.insecure_channel(settings.grpc_client_insecure_address_port)
    stub = ConnectionRequesterStub(channel)
    return stub


def send_error(request_header: Header, nsi_exc: NsiException, connection_id: UUID) -> None:
    """Send a NSI Error referencing the request correlation_id together with details from the NsiException.

    The error message is sent from a PA to an RA in response to an outstanding operation request
    when an error condition encountered, and as a result, the operation cannot be successfully completed.
    The correlationId carried in the NSI CS header structure will identify the original request associated
    with this error message.
    """
    from supa.util.converter import to_service_exception

    pb_e_req = ErrorRequest()
    pb_e_req.header.CopyFrom(request_header)
    pb_e_req.service_exception.CopyFrom(to_service_exception(nsi_exc, connection_id))

    stub = get_stub()
    stub.Error(pb_e_req)
