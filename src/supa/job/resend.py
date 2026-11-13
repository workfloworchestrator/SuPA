#  Copyright 2026 SURF.
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
"""Module with the job that sends the stored result of a request to the requester again."""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Type
from uuid import UUID

import structlog
from apscheduler.triggers.date import DateTrigger
from google.protobuf.message import Message
from structlog.stdlib import BoundLogger

from supa.connection import requester
from supa.db.model import Result
from supa.grpc_nsi.connection_requester_pb2 import (
    ErrorRequest,
    GenericConfirmedRequest,
    GenericFailedRequest,
    ReserveConfirmedRequest,
)
from supa.job.shared import Job
from supa.util.timestamp import current_timestamp
from supa.util.type import ResultType

logger = structlog.get_logger(__name__)

RESEND_DELAY = 1
"""Seconds between acknowledging a repeated request and sending its result again."""

RESULT_MESSAGES: Dict[ResultType, Type[Message]] = {
    ResultType.ReserveConfirmed: ReserveConfirmedRequest,
    ResultType.ReserveFailed: GenericFailedRequest,
    ResultType.ReserveCommitConfirmed: GenericConfirmedRequest,
    ResultType.ReserveCommitFailed: GenericFailedRequest,
    ResultType.ReserveAbortConfirmed: GenericConfirmedRequest,
    ResultType.ProvisionConfirmed: GenericConfirmedRequest,
    ResultType.ReleaseConfirmed: GenericConfirmedRequest,
    ResultType.TerminateConfirmed: GenericConfirmedRequest,
    ResultType.Error: ErrorRequest,
}
"""For each stored result type, the message that was stored; the requester call that sent it is named as the type."""


class ResendResultJob(Job):
    """Send the stored result of a repeated request to the requester again."""

    log: BoundLogger
    correlation_id: UUID

    def __init__(self, correlation_id: UUID):
        """Initialize the ResendResultJob.

        Args:
            correlation_id: Correlation ID of the request, and so of its result.
        """
        self.log = logger.bind(job="ResendResultJob", correlation_id=str(correlation_id))
        self.correlation_id = correlation_id

    def __call__(self) -> None:
        """Send the stored result again.

        A request that has no result yet is still being processed,
        and its own job sends the result when it is done.
        """
        from supa.db.session import db_session

        with db_session() as session:
            result = session.query(Result).filter(Result.correlation_id == self.correlation_id).one_or_none()
            if not result:
                self.log.info("No result yet, the original request sends it")
                return
            result_type = ResultType(result.result_type)
            message = RESULT_MESSAGES[result_type].FromString(result.result_data)

        # send result to requester, done outside the database session because communication can throw exception
        self.log.debug("Sending message", method=result_type.value, message=message)
        getattr(requester.get_stub(), result_type.value)(message)

    @property
    def job_id(self) -> str:
        """ID of the job like <type of job>=<correlation ID>, which names a request, not a connection."""
        return "=".join(["ResendResultJob", str(self.correlation_id)])

    @classmethod
    def recover(cls: Type[ResendResultJob]) -> List[Job]:
        """Nothing to recover: a requester that got no result sends the request again."""
        return []

    def trigger(self) -> DateTrigger:
        """Send the result after :data:`RESEND_DELAY`."""
        return DateTrigger(run_date=current_timestamp() + timedelta(seconds=RESEND_DELAY))
