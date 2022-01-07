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
"""Predefined NSI errors.

The errors are not defined in the NSI Connection Service v2.1 specification.
Instead there is a separate document
`Error Handling in NSI CS 2.1 <https://www.ogf.org/documents/GFD.235.pdf>`_
that specifies these errors.

Not all errors might be applicable to SuPA's operation,
it being a Provider Agent,
though all have been included for reference.

..
   Don't manually update the table below!
   Run this module instead, and copy and paste its output.

.. csv-table:: Predefined NSI errors
   :header: "Name", "``error_id``", "``error_code``", "``descriptive_text``"

   GenericMessagePayLoadError,00100,GENERIC_MESSAGE_PAYLOAD_ERROR,Illegal message payload.
   MissingParameter,00101,MISSING_PARAMETER,Invalid or missing parameter.
   UnsupportedParameter,00102,UNSUPPORTED_PARAMETER,Provided parameter contains an unsupported value that MUST be processed.
   NotImplemented,00103,NOT_IMPLEMENTED,Requested feature has not been implemented.
   VersionNotSupported,00104,VERSION_NOT_SUPPORTED,The protocol version requested is not supported.
   GenericConnectionError,00200,GENERIC_CONNECTION_ERROR,A connection error has occurred.
   InvalidTransition,00201,INVALID_TRANSITION,Connection state machine is in invalid state for received message.
   ReservationNonExistent,00203,RESERVATION_NONEXISTENT,Schedule does not exist for connectionId.
   GenericSecurityError,00300,GENERIC_SECURITY_ERROR,A security error has occurred.
   Unauthorized,00302,UNAUTHORIZED,Insufficient authorization to perform requested operation.
   GenericMetadataError,00400,GENERIC_METADATA_ERROR,A topology or generic path computation error has occurred.
   DomainLookupError,00405,DOMAIN_LOOKUP_ERROR,Unknown network for requested resource.
   NsaLookupError,00406,NSA_LOOKUP_ERROR,Cannot map networkId to service interface.
   NoServiceplanePathFound,00407,NO_SERVICEPLANE_PATH_FOUND,No service plane path for selected connection segments.
   GenericInternalError,00500,GENERIC_INTERNAL_ERROR,An internal error has caused a message processing failure.
   ChildSegmentError,00502,CHILD_SEGMENT_ERROR,Child connection segment error is present.
   MessageDeliveryError,00503,MESSAGE_DELIVERY_ERROR,Failed message delivery to peer NSA.
   GenericResourceUnavailable,00600,GENERIC_RESOURCE_UNAVAILABLE,A requested resource(s) is not available.
   GenericServiceError,00700,GENERIC_SERVICE_ERROR,A service specific error has occurred.
   UnknownStp,00701,UNKNOWN_STP,Could not find STP in topology database.
   LabelSwappingNotSupported,00703,LABEL_SWAPPING_NOT_SUPPORTED,Label swapping not supported for requested path.
   StpUnavailable,00704,STP_UNAVALABLE,Specified STP already in use.
   CapacityUnavailable,00705,CAPACITY_UNAVAILABLE,Insufficient capacity available for reservation.
   DirectionalityMismatch,00706,DIRECTIONALITY_MISMATCH,Directionality of specified STP does not match request directionality.
   InvalidEroMember,00707,INVALID_ERO_MEMBER,Invalid ERO member detected.
   UnknownLabelType,00708,UNKNOWN_LABEL_TYPE,Specified STP contains an unknown label type.
   InvalidLabelFormat,00709,INVALID_LABEL_FORMAT,Specified STP contains an invalid label.
   NoTransportplanePathFound,00710,NO_TRANSPORTPLANE_PATH_FOUND,Path computation failed to resolve route for reservation.
   GenericRmError,00800,GENERIC_RM_ERROR,An internal (N)RM error has caused a message processing failure.

"""  # noqa: E501
from __future__ import annotations

from enum import Enum
from typing import NamedTuple, Type, cast

P2P_NS = "http://schemas.ogf.org/nsi/2013/12/services/point2point"
HEADERS_NS = "http://schemas.ogf.org/nsi/2013/12/framework/headers"
TYPES_NS = "http://schemas.ogf.org/nsi/2013/12/connection/types"
PROVIDER_NS = "http://schemas.ogf.org/nsi/2013/12/connection/provider"


class Variable(Enum):
    """Variable to namespace mapping.

    This is a peculiarity of the original SOAP underpinning of the NSI protocol.
    Even though all that is XML has largely been abstracted away from us
    by using the Protobuf version of NSI,
    we still need to track certain things
    to facilitate a proper translation between the two protocol versions.
    The namespace associated with each variable (in the `ServiceException``) is such a thing.
    """

    variable: str
    namespace: str

    def __new__(cls: Type[Variable], variable: str, namespace: str) -> Variable:  # noqa: D102
        obj = cast("Variable", object.__new__(cls))
        obj._value_ = (variable, namespace)
        obj.variable = variable
        obj.namespace = namespace
        return obj

    CAPACITY = "capacity", P2P_NS
    CONNECTION_ID = "connectionId", TYPES_NS
    DEST_STP = "destSTP", P2P_NS
    DIRECTIONALITY = "directionality", P2P_NS
    END_TIME = "endTime", TYPES_NS
    NETWORK_ID = "networkId", P2P_NS
    PROTECTION = "protection", P2P_NS
    PROTOCOL_VERSION = "protocolVersion", HEADERS_NS
    PROVIDER_NSA = "providerNSA", HEADERS_NS
    QUERY_RECURSIVE = "queryRecursive", PROVIDER_NS
    REQUESTER_NSA = "requesterNSA", HEADERS_NS
    RESERVATION_STATE = "reservationState", TYPES_NS
    PROVISION_STATE = "provisionState", TYPES_NS
    LIFECYCLE_STATE = "lifecycleState", TYPES_NS
    SOURCE_STP = "sourceSTP", P2P_NS
    STP = "stp", P2P_NS


class NsiError(NamedTuple):
    """Predefined NSI errors.

    Reporting of these errors happens as part of the ``ServiceException`` message.

    The ``text`` field of the ``ServiceException`` should be made up of three parts::

        error_code: descriptive_text [extra information]
    """

    error_id: str
    """An unique ID for the error.

    The :attr:`error_id` can optionally be included in the ``ServiceException``.
    """

    error_code: str
    """Human readable name of the error.

    The :attr:`error_code` should always be included in the ``ServiceException``.
    """

    descriptive_text: str
    """Descriptive text explaining the error.

    The :attr:`text` should always be included in the ``ServiceException``.
    """


GenericMessagePayLoadError = NsiError(
    error_id="00100",
    error_code="GENERIC_MESSAGE_PAYLOAD_ERROR",
    descriptive_text="Illegal message payload.",
)
MissingParameter = NsiError(
    error_id="00101",
    error_code="MISSING_PARAMETER",
    descriptive_text="Invalid or missing parameter.",
)
UnsupportedParameter = NsiError(
    error_id="00102",
    error_code="UNSUPPORTED_PARAMETER",
    descriptive_text="Provided parameter contains an unsupported value that MUST be processed.",
)
NotImplemented = NsiError(  # noqa: A001
    error_id="00103",
    error_code="NOT_IMPLEMENTED",
    descriptive_text="Requested feature has not been implemented.",
)
VersionNotSupported = NsiError(
    error_id="00104",
    error_code="VERSION_NOT_SUPPORTED",
    descriptive_text="The protocol version requested is not supported.",
)
GenericConnectionError = NsiError(
    error_id="00200",
    error_code="GENERIC_CONNECTION_ERROR",
    descriptive_text="A connection error has occurred.",
)
InvalidTransition = NsiError(
    error_id="00201",
    error_code="INVALID_TRANSITION",
    descriptive_text="Connection state machine is in invalid state for received message.",
)
ReservationNonExistent = NsiError(
    error_id="00203",
    error_code="RESERVATION_NONEXISTENT",
    descriptive_text="Schedule does not exist for connectionId.",
)
GenericSecurityError = NsiError(
    error_id="00300",
    error_code="GENERIC_SECURITY_ERROR",
    descriptive_text="A security error has occurred.",
)
Unauthorized = NsiError(
    error_id="00302",
    error_code="UNAUTHORIZED",
    descriptive_text="Insufficient authorization to perform requested operation.",
)
GenericMetadataError = NsiError(
    error_id="00400",
    error_code="GENERIC_METADATA_ERROR",
    descriptive_text="A topology or generic path computation error has occurred.",
)
DomainLookupError = NsiError(
    error_id="00405",
    error_code="DOMAIN_LOOKUP_ERROR",
    descriptive_text="Unknown network for requested resource.",
)
NsaLookupError = NsiError(
    error_id="00406",
    error_code="NSA_LOOKUP_ERROR",
    descriptive_text="Cannot map networkId to service interface.",
)
NoServiceplanePathFound = NsiError(
    error_id="00407",
    error_code="NO_SERVICEPLANE_PATH_FOUND",
    descriptive_text="No service plane path for selected connection segments.",
)
GenericInternalError = NsiError(
    error_id="00500",
    error_code="GENERIC_INTERNAL_ERROR",
    descriptive_text="An internal error has caused a message processing failure.",
)
ChildSegmentError = NsiError(
    error_id="00502",
    error_code="CHILD_SEGMENT_ERROR",
    descriptive_text="Child connection segment error is present.",
)
MessageDeliveryError = NsiError(
    error_id="00503",
    error_code="MESSAGE_DELIVERY_ERROR",
    descriptive_text="Failed message delivery to peer NSA.",
)
GenericResourceUnavailable = NsiError(
    error_id="00600",
    error_code="GENERIC_RESOURCE_UNAVAILABLE",
    descriptive_text="A requested resource(s) is not available.",
)
GenericServiceError = NsiError(
    error_id="00700",
    error_code="GENERIC_SERVICE_ERROR",
    descriptive_text="A service specific error has occurred.",
)
GenericRmError = NsiError(
    error_id="00800",
    error_code="GENERIC_RM_ERROR",
    descriptive_text="An internal (N)RM error has caused a message processing failure.",
)
UnknownStp = NsiError(
    error_id="00701",
    error_code="UNKNOWN_STP",
    descriptive_text="Could not find STP in topology database.",
)
LabelSwappingNotSupported = NsiError(
    error_id="00703",
    error_code="LABEL_SWAPPING_NOT_SUPPORTED",
    descriptive_text="Label swapping not supported for requested path.",
)
StpUnavailable = NsiError(
    error_id="00704",
    error_code="STP_UNAVALABLE",
    descriptive_text="Specified STP already in use.",
)
CapacityUnavailable = NsiError(
    error_id="00705",
    error_code="CAPACITY_UNAVAILABLE",
    descriptive_text="Insufficient capacity available for reservation.",
)
DirectionalityMismatch = NsiError(
    error_id="00706",
    error_code="DIRECTIONALITY_MISMATCH",
    descriptive_text="Directionality of specified STP does not match request directionality.",
)
InvalidEroMember = NsiError(
    error_id="00707",
    error_code="INVALID_ERO_MEMBER",
    descriptive_text="Invalid ERO member detected.",
)
UnknownLabelType = NsiError(
    error_id="00708",
    error_code="UNKNOWN_LABEL_TYPE",
    descriptive_text="Specified STP contains an unknown label type.",
)
InvalidLabelFormat = NsiError(
    error_id="00709",
    error_code="INVALID_LABEL_FORMAT",
    descriptive_text="Specified STP contains an invalid label.",
)
NoTransportplanePathFound = NsiError(
    error_id="00710",
    error_code="NO_TRANSPORTPLANE_PATH_FOUND",
    descriptive_text="Path computation failed to resolve route for reservation.",
)

if __name__ == "__main__":
    """Run this module to generate a table of all NSIErrors for inclusion in the module level docstring.

    Updating the module level docstring with the output generated by this code
    is still a manual process.
    """
    import csv
    import io

    nsi_errors = [(attr, globals()[attr]) for attr in list(globals().keys()) if isinstance(globals()[attr], NsiError)]
    nsi_errors.sort(key=lambda t: str(t[1].error_id))
    print(  # noqa: T001
        """
.. csv-table:: Predefined NSI errors
   :header: "Name", "``error_id``", "``error_code``", "``descriptive_text``"
    """
    )
    output = io.StringIO()
    writer = csv.writer(output)
    for ne in nsi_errors:
        writer.writerow((ne[0], *ne[1]))
    for line in output.getvalue().split("\n"):
        print(f"   {line}")  # noqa: T001
