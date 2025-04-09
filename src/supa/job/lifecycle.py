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

from datetime import timedelta
from typing import List, Type
from uuid import UUID

import structlog
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from more_itertools import flatten
from statemachine.exceptions import TransitionNotAllowed
from structlog.stdlib import BoundLogger

from supa import settings
from supa.connection import requester
from supa.connection.error import GenericInternalError, GenericServiceError, Variable
from supa.connection.fsm import DataPlaneStateMachine, LifecycleStateMachine
from supa.db.model import Connection, Reservation, connection_to_dict
from supa.job.dataplane import AutoEndJob, AutoStartJob, DeactivateJob
from supa.job.shared import Job, NsiException, register_notification, register_result
from supa.util.converter import to_error_request, to_forced_end_event, to_generic_confirmed_request, to_header
from supa.util.timestamp import current_timestamp
from supa.util.type import NotificationType, ResultType

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
            self.log.debug("Sending message", method="Error", message=error_request)
            register_result(error_request, ResultType.Error)
            stub.Error(error_request)
        else:  # terminate successful
            if (
                previous_data_plane_state == DataPlaneStateMachine.AutoEnd.value
                or previous_data_plane_state == DataPlaneStateMachine.Activated.value
            ):
                self.log.info("Schedule deactivate", job="DeactivateJob")
                scheduler.add_job(job := DeactivateJob(self.connection_id), trigger=job.trigger(), id=job.job_id)
            self.log.debug("Sending message", method="TerminateConfirmed", message=confirmed_request)
            register_result(confirmed_request, ResultType.TerminateConfirmed)
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


class HealthCheckJob(Job):
    """Check the health in NRM of all active circuits."""

    log: BoundLogger

    def __init__(self) -> None:
        """Initialize the HealthCheckJob."""
        self.log = logger.bind(job=self.__class__.__name__)

    def __call__(self) -> None:
        """Check the health in NRM of all active connections.

        For all active connections in the database,
        call the health_check method on the backend that will return the current connection health status,
        when a connection is not healthy anymore,
        sent a forcedEnd errorEvent to the NSA/AG.
        """
        self.log.debug("Connection health check")

        from supa.db.session import db_session
        from supa.nrm.backend import backend

        # call backend
        with db_session() as session:
            session.expire_on_commit = False  # type: ignore[attr-defined] # to use `connections` outside the session
            connections = (
                session.query(Connection)
                .filter(
                    (Connection.connection_id == Reservation.connection_id)
                    & (
                        (Reservation.data_plane_state == DataPlaneStateMachine.Activated.value)
                        | (Reservation.data_plane_state == DataPlaneStateMachine.AutoEnd.value)
                    )
                )
                .all()
            )
        # check health of every active connection by calling health_check on backend
        for connection in connections:
            nsi_exception: NsiException | None = None
            healthy: bool = True
            try:
                healthy = backend.health_check(**connection_to_dict(connection))
            except NsiException as nsi_exc:
                nsi_exception = nsi_exc
            except Exception as exc:
                self.log.exception("Unexpected error occurred.", reason=str(exc))
                nsi_exception = NsiException(
                    GenericInternalError,
                    str(exc),
                    {
                        Variable.CONNECTION_ID: str(connection.connection_id),
                    },
                )
            # when connection is not healthy anymore, transition to failed and send forcedEnd errorEvent
            if nsi_exception:
                self.log.warning(
                    "Error getting connection health from NRM",
                    connection_id=str(connection.connection_id),
                    reason=str(nsi_exception),
                )
            elif not healthy:
                with db_session() as session:
                    reservation = (
                        session.query(Reservation).filter(Reservation.connection_id == connection.connection_id).one()
                    )
                    lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")
                    lsm.forced_end_notification()
                    dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
                    dpsm.unhealthy()
                    event = to_forced_end_event(
                        reservation,
                        NsiException(
                            GenericServiceError,
                            "Unexpected failure of connection in NRM.",
                            {
                                Variable.CONNECTION_ID: str(connection.connection_id),
                            },
                        ),
                    )
                # send errorEvent to requester
                stub = requester.get_stub()
                self.log.debug("Sending message", method="Error", message=event)
                register_notification(event, NotificationType.ErrorEvent)
                stub.ErrorEvent(event)

    @classmethod
    def recover(cls: Type[HealthCheckJob]) -> List[Job]:
        """Recover HealthCheckJob's.

        Health check is job is only started once at startup,
        return an empy list in case somebody tries to recover HealthCheckJob's.

        Returns:
            Always returns an empy list of jobs to recover.
        """
        return []

    def trigger(self) -> IntervalTrigger:
        """Trigger for HealthCheckJob."""
        return IntervalTrigger(
            seconds=settings.backend_health_check_interval,
            start_date=current_timestamp() + timedelta(seconds=settings.backend_health_check_interval),
        )

    @property
    def job_id(self) -> str:
        """Uniq name for job instances.

        Only one HealthCheckJob will be scheduled,
        therefor a static name is returned.
        """
        return self.__class__.__name__
