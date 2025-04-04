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
from statemachine.exceptions import TransitionNotAllowed
from structlog.stdlib import BoundLogger

from supa.connection import requester
from supa.connection.error import GenericInternalError, Variable
from supa.connection.fsm import DataPlaneStateMachine, LifecycleStateMachine
from supa.db.model import Connection, Reservation, connection_to_dict
from supa.job.dataplane import AutoEndJob, AutoStartJob, DeactivateJob
from supa.job.shared import Job, NsiException, register_result
from supa.util.converter import to_error_request, to_generic_confirmed_request, to_header
from supa.util.type import ResultType

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

    def __call__(self) -> None:
        """Terminate reservation request.

        The reservation will be terminated,
        if the data plane is still active a job to deactivate the data plane will be scheduled and
        a TerminateConfirmed message will be sent to the NSA/AG.
        """
        self.log.info("Terminate reservation")

        from supa.db.session import db_session
        from supa.nrm.backend import backend

        # call backend
        nsi_exception: NsiException | None = None
        circuit_id = None
        with db_session() as session:
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one_or_none()
            connection_present = connection is not None
            if connection_present:
                backend_args = connection_to_dict(connection)  # type: ignore[arg-type]
        try:
            # skip call to the NRM when Terminate is executed before a connection was registered
            if connection_present:
                circuit_id = backend.terminate(**backend_args)
        except NsiException as nsi_exc:
            nsi_exception = nsi_exc
        except Exception as exc:
            self.log.exception("Unexpected error occurred.", reason=str(exc))
            nsi_exception = NsiException(
                GenericInternalError,
                str(exc),
                {
                    Variable.CONNECTION_ID: str(self.connection_id),
                },
            )

        # update reservation and connection state in the database
        from supa import scheduler

        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one_or_none()
            lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            if nsi_exception:  # terminate failed
                self.log.info("Terminate failed.", reason=str(nsi_exception))
                error_request = to_error_request(to_header(reservation), nsi_exception, self.connection_id)
            else:  # terminate successful
                # the NRM successfully terminated the reservation,
                # cancel the AutoStartJob or AutoEndJob,
                # and schedule a DeactivateJob if the data plane is active
                # TODO if reservation still pending cancel timeout job
                previous_data_plane_state = reservation.data_plane_state
                try:
                    dpsm.deactivate_request()
                except TransitionNotAllowed:
                    pass  # silently pass if no data plane related actions are required
                else:
                    if previous_data_plane_state == DataPlaneStateMachine.AutoStart.value:
                        self.log.info("Cancel auto start")
                        scheduler.remove_job(job_id=AutoStartJob(self.connection_id).job_id)
                    else:  # previous data plane state is either AutoEnd or Activated
                        if previous_data_plane_state == DataPlaneStateMachine.AutoEnd.value:
                            self.log.info("Cancel auto end")
                            scheduler.remove_job(job_id=AutoEndJob(self.connection_id).job_id)
                confirmed_request = to_generic_confirmed_request(reservation)
                lsm.terminate_confirmed()
                if circuit_id:
                    connection.circuit_id = circuit_id  # type: ignore[union-attr]

        # send result to requester, done outside the database session because communication can throw exception
        stub = requester.get_stub()
        if nsi_exception:  # terminate failed
            register_result(error_request, ResultType.Error)
            self.log.debug("Sending message", method="Error", message=error_request)
            stub.Error(error_request)
        else:  # terminate successful
            if (
                previous_data_plane_state == DataPlaneStateMachine.AutoEnd.value
                or previous_data_plane_state == DataPlaneStateMachine.Activated.value
            ):
                self.log.info("Schedule deactivate", job="DeactivateJob")
                scheduler.add_job(job := DeactivateJob(self.connection_id), trigger=job.trigger(), id=job.job_id)
            register_result(confirmed_request, ResultType.TerminateConfirmed)
            self.log.debug("Sending message", method="TerminateConfirmed", message=confirmed_request)
            stub.TerminateConfirmed(confirmed_request)

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
