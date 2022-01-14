#  Copyright 2022 SURF.
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
from __future__ import annotations

from typing import List, Type
from uuid import UUID

import structlog
from apscheduler.triggers.date import DateTrigger
from more_itertools import flatten
from sqlalchemy import orm
from statemachine.exceptions import TransitionNotAllowed
from structlog.stdlib import BoundLogger

from supa.connection import requester
from supa.connection.error import GenericInternalError, Variable
from supa.connection.fsm import DataPlaneStateMachine, LifecycleStateMachine
from supa.connection.requester import send_error
from supa.db.model import Reservation
from supa.grpc_nsi.connection_requester_pb2 import TerminateConfirmedRequest
from supa.job.dataplane import DeactivateJob
from supa.job.shared import Job, NsiException
from supa.util.converter import to_header

logger = structlog.get_logger(__name__)


class TerminateJob(Job):
    """Handle provision requests."""

    connection_id: UUID
    log: BoundLogger

    def __init__(self, connection_id: UUID):
        """Initialize the TerminateJob.

        Args:
           connection_id: The connection_id of the reservation terminate request
        """
        self.log = logger.bind(job=self.__class__.__name__, connection_id=str(connection_id))
        self.connection_id = connection_id

    def _send_terminate_confirmed(self, session: orm.Session) -> None:
        # the reservation is still in the session, hence no actual query will be performed
        reservation: Reservation = session.query(Reservation).get(self.connection_id)
        pb_tc_req = TerminateConfirmedRequest()

        pb_tc_req.header.CopyFrom(to_header(reservation, add_path_segment=True))  # Yes, add our segment!
        pb_tc_req.connection_id = str(reservation.connection_id)

        self.log.debug("Sending message.", method="TerminateConfirmed", request_message=pb_tc_req)
        stub = requester.get_stub()
        stub.TerminateConfirmed(pb_tc_req)

    def __call__(self) -> None:
        """Terminate reservation request.

        The reservation will be terminated,
        if the data plane is still active a job to deactivate the data plane will be scheduled and
        a TerminateConfirmed message will be sent to the NSA/AG.
        """
        self.log.info("Terminating reservation")

        from supa.db.session import db_session

        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one_or_none()
            )
            lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            try:
                #
                # TODO:  If there is a Network Resource Manager that needs to be contacted
                #        to terminate the reservation request then this is the place.
                #        If this is a recovered job then try to recover the reservation state
                #        from the NRM.
                #
                pass
            except NsiException as nsi_exc:
                self.log.info("Terminate failed.", reason=nsi_exc.text)
                send_error(
                    to_header(reservation),
                    nsi_exc,
                    self.connection_id,
                )
            except Exception as exc:
                self.log.exception("Unexpected error occurred.", reason=str(exc))
                send_error(
                    to_header(reservation),
                    NsiException(
                        GenericInternalError,
                        str(exc),
                        {
                            Variable.LIFECYCLE_STATE: reservation.lifecycle_state,
                            Variable.CONNECTION_ID: str(self.connection_id),
                        },
                    ),
                    self.connection_id,
                )
            else:
                # the NRM successfully terminated the reservation,
                # cancel the AutoStartJob or AutoEndJob,
                # and schedule a DeactivateJob if the data plane is active
                from supa import scheduler

                previous_data_plane_state = reservation.data_plane_state
                try:
                    dpsm.deactivate_request()
                except TransitionNotAllowed:
                    pass  # silently pass if no data plane related actions are required
                else:
                    if previous_data_plane_state == DataPlaneStateMachine.AutoStart.value:
                        scheduler.remove_job(job_id=f"{str(self.connection_id)}-AutoStartJob")
                        self.log.info("Canceled automatic enable of data plane at start time")
                    else:  # previous data plane state is either AutoEnd or Activated
                        if previous_data_plane_state == DataPlaneStateMachine.AutoEnd.value:
                            scheduler.remove_job(job_id=f"{str(self.connection_id)}-AutoEndJob")
                            self.log.info("Canceled automatic disable of data plane at end time")
                        scheduler.add_job(
                            DeactivateJob(self.connection_id),
                            trigger=DateTrigger(run_date=None),
                            id=f"{str(self.connection_id)}-DeactivateJob",
                        )
                lsm.terminate_confirmed()
                self._send_terminate_confirmed(session)

    @classmethod
    def recover(cls: Type[TerminateJob]) -> List[Job]:
        """Recover TerminateJobs's that did not get to run before SuPA was terminated.

        Returns:
            List of TerminateJob's that still need to be run.
        """
        from supa.db.session import db_session

        with db_session() as session:
            connection_ids: List[UUID] = list(
                flatten(
                    session.query(Reservation.connection_id)
                    .filter(Reservation.lifecycle_state == LifecycleStateMachine.Terminating.value)
                    .all()
                )
            )
        for cid in connection_ids:
            logger.info("Recovering job", job="TerminateJob", connection_id=str(cid))

        return [TerminateJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Trigger for TerminateJob's."""
        return DateTrigger(run_date=None)  # Run immediately