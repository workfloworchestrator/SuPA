#  Copyright 2019 SURF.
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
"""Handy types to keep things sane."""
from enum import Enum, unique


@unique
class ResultType(str, Enum):
    """Capture the set of valid results as returned by QueryResult."""

    ReserveConfirmed = "ReserveConfirmed"
    ReserveFailed = "ReserveFailed"
    ReserveCommitConfirmed = "ReserveCommitConfirmed"
    ReserveCommitFailed = "ReserveCommitFailed"
    ReserveAbortConfirmed = "ReserveAbortConfirmed"
    ProvisionConfirmed = "ProvisionConfirmed"
    ReleaseConfirmed = "ReleaseConfirmed"
    TerminateConfirmed = "TerminateConfirmed"
    Error = "Error"


@unique
class NotificationType(str, Enum):
    """Capture the set of valid notifications as returned by QueryNotification."""

    ReserveTimeout = "ReserveTimeout"
    ErrorEvent = "ErrorEvent"
    MessageDeliveryTimeout = "MessageDeliveryTimeout"
    DataPlaneStateChange = "DataPlaneStateChange"
