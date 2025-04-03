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
from structlog.stdlib import BoundLogger

from supa.connection import requester
from supa.connection.error import GenericInternalError, Variable
from supa.connection.fsm import DataPlaneStateMachine, LifecycleStateMachine
from supa.db.model import Connection, Reservation, Schedule, connection_to_dict
from supa.job.shared import Job, NsiException, register_notification
from supa.util.converter import to_activate_failed_event, to_data_plane_state_change_request, to_deactivate_failed_event
from supa.util.timestamp import NO_END_DATE, current_timestamp
from supa.util.type import NotificationType

logger = structlog.get_logger(__name__)


class ActivateJob(Job):
    """Handle data plane activation requests."""

    connection_id: UUID
    log: BoundLogger

    def __init__(self, connection_id: UUID):
        """Initialize the ActivateJob.

        Args:
           connection_id: The connection_id of the reservation activation request
        """
        self.log = logger.bind(job=self.__class__.__name__, connection_id=str(connection_id))
        self.connection_id = connection_id

    def __call__(self) -> None:
        """Activate data plane request.

        Activate the data plane according to the reservation criteria and
        send a data plane status notitication to the NSA/AG.
        If the data plane state machine is not in the correct state for a Activate
        an NSI exception is returned leaving the state machine unchanged.
        """
        self.log.info("Activate data plane")

        from supa.db.session import db_session
        from supa.nrm.backend import backend

        # call backend
        nsi_exception: NsiException | None = None
        circuit_id = None
        with db_session() as session:
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            backend_args = connection_to_dict(connection)
        try:
            circuit_id = backend.activate(**backend_args)
        except NsiException as nsi_exc:
            nsi_exception = nsi_exc
        except Exception as exc:
            self.log.exception("Unexpected error occurred", reason=str(exc))
            nsi_exception = NsiException(
                GenericInternalError,
                str(exc),
                {
                    Variable.CONNECTION_ID: str(self.connection_id),
                },
            )

        # update reservation and connection state in the database, start auto end job if necessary
        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            if nsi_exception:  # activate on backend failed
                self.log.info("Data plane activation failed", reason=str(nsi_exception))
                dpsm.activate_failed()
                event = to_activate_failed_event(reservation, nsi_exception)
                register_notification(event, NotificationType.ErrorEvent)
            else:  # activate on backend successful
                dpsm.activate_confirmed()
                data_plane_state_change = to_data_plane_state_change_request(reservation)
                if circuit_id:
                    connection.circuit_id = circuit_id
                if (end_time := reservation.schedule.end_time) != NO_END_DATE:
                    from supa import scheduler

                    dpsm.auto_end_request()
                    self.log.info("Schedule auto end", job="AutoEndJob", end_time=end_time.isoformat())
                    scheduler.add_job(job := AutoEndJob(self.connection_id), trigger=job.trigger(), id=job.job_id)
                register_notification(data_plane_state_change, NotificationType.DataPlaneStateChange)

        # send result to requester, done outside the database session because communication can throw exception
        stub = requester.get_stub()
        if nsi_exception:  # activate on backend failed
            self.log.debug("Sending message", method="ErrorEvent", message=event)
            stub.ErrorEvent(event)
        else:  # activate on backend successful
            self.log.debug("Sending message", method="DataPlaneStateChange", message=data_plane_state_change)
            stub.DataPlaneStateChange(data_plane_state_change)

    @classmethod
    def recover(cls: Type[ActivateJob]) -> List[Job]:
        """Recover ActivationJob's that did not get to run before SuPA was terminated.

        Only include jobs for reservations that are still supposed to have its data plane activated
        according to their lifecycle state and end time.

        Returns:
            List of ActivationJob's that still need to be run.
        """
        from supa.db.session import db_session

        with db_session() as session:
            connection_ids: List[UUID] = list(
                flatten(
                    session.query(Reservation.connection_id)
                    .join(Schedule)
                    .filter(
                        Reservation.lifecycle_state == LifecycleStateMachine.Created.value,
                        Reservation.data_plane_state == DataPlaneStateMachine.Activating.value,
                        Schedule.end_time > current_timestamp(),
                    )
                    .all()
                )
            )
        for cid in connection_ids:
            logger.info("Recovering job", job="ActivateJob", connection_id=str(cid))

        return [ActivateJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Trigger for ActivateJob's.

        Returns:
            DateTrigger set to run immediately.
        """
        return DateTrigger(run_date=None)  # Run immediately


class DeactivateJob(Job):
    """Handle data plane deactivation requests."""

    connection_id: UUID
    log: BoundLogger

    def __init__(self, connection_id: UUID):
        """Initialize the DeactivateJob.

        Args:
           connection_id: The connection_id of the reservation deactivation request
        """
        self.log = logger.bind(job=self.__class__.__name__, connection_id=str(connection_id))
        self.connection_id = connection_id

    def __call__(self) -> None:
        """Deactivate data plane request.

        Deactivate the data plane and
        send a data plane status notitication to the NSA/AG.
        If the data plane state machine is not in the correct state for a Deactivate
        a NSI exception is returned leaving the state machine unchanged.
        """
        self.log.info("Deactivate data plane")

        from supa.db.session import db_session
        from supa.nrm.backend import backend

        # call backend
        nsi_exception: NsiException | None = None
        circuit_id = None
        with db_session() as session:
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            backend_args = connection_to_dict(connection)
        try:
            circuit_id = backend.deactivate(**backend_args)
        except NsiException as nsi_exc:
            nsi_exception = nsi_exc
        except Exception as exc:
            self.log.exception("Unexpected error occurred", reason=str(exc))
            nsi_exception = NsiException(
                GenericInternalError,
                str(exc),
                {
                    Variable.CONNECTION_ID: str(self.connection_id),
                },
            )

        # update reservation and connection state in the database
        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            if nsi_exception:  # deactivate on backend failed
                self.log.info("Data plane deactivation failed", reason=str(nsi_exception))
                dpsm.deactivate_failed()
                event = to_deactivate_failed_event(reservation, nsi_exception)
                register_notification(event, NotificationType.ErrorEvent)
            else:  # deactivate on backend successful
                dpsm.deactivate_confirm()
                data_plane_state_change = to_data_plane_state_change_request(reservation)
                if circuit_id:
                    connection.circuit_id = circuit_id
                register_notification(data_plane_state_change, NotificationType.DataPlaneStateChange)

        # send result to requester, done outside the database session because communication can throw exception
        stub = requester.get_stub()
        if nsi_exception:  # activate on backend failed
            self.log.debug("Sending message", method="ErrorEvent", message=event)
            stub.ErrorEvent(event)
        else:  # activate on backend successful
            self.log.debug("Sending message", method="DataPlaneStateChange", message=data_plane_state_change)
            stub.DataPlaneStateChange(data_plane_state_change)

    @classmethod
    def recover(cls: Type[DeactivateJob]) -> List[Job]:
        """Recover DeactivationJob's that did not get to run before SuPA was terminated.

        Also include jobs for reservations that are passed end time to ensue date plane is deactivated,
        hence reservations are not filtered on lifecycle state or end time.

        Returns:
            List of DeactivationJob's that still need to be run.
        """
        from supa.db.session import db_session

        with db_session() as session:
            connection_ids: List[UUID] = list(
                flatten(
                    session.query(Reservation.connection_id)
                    .filter(
                        Reservation.data_plane_state == DataPlaneStateMachine.Deactivating.value,
                    )
                    .all()
                )
            )
        for cid in connection_ids:
            logger.info("Recovering job", job="DeactivateJob", connection_id=str(cid))

        return [DeactivateJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Trigger for DeactivateJob's.

        Returns:
            DateTrigger set to run immediately.
        """
        return DateTrigger(run_date=None)  # Run immediately


class AutoStartJob(Job):
    """Handle automatic activation of data plane when start time is reached."""

    connection_id: UUID
    log: BoundLogger

    def __init__(self, connection_id: UUID):
        """Initialize the AutoStartJob.

        Args:
           connection_id: The connection_id of the reservation autostart request
        """
        self.log = logger.bind(job=self.__class__.__name__, connection_id=str(connection_id))
        self.connection_id = connection_id

    def __call__(self) -> None:
        """Autostart data plane request.

        Now that start time was reached schedule a ActivateJob to activate the data plane.
        """
        self.log.info("Auto start data plane")

        from supa.db.session import db_session

        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            dpsm.activate_request()

        from supa import scheduler

        self.log.info("Schedule activate", job="ActivateJob")
        scheduler.add_job(job := ActivateJob(self.connection_id), trigger=job.trigger(), id=job.job_id)

    @classmethod
    def recover(cls: Type[AutoStartJob]) -> List[Job]:
        """Recover AutoStartJob's that did not get to run before SuPA was terminated.

        Only include jobs for reservations that are still supposed to have its data plane activated
        according to their lifecycle state and end time.

        Returns:
            List of AutoStartJob's that still need to be run.
        """
        from supa.db.session import db_session

        with db_session() as session:
            connection_ids: List[UUID] = list(
                flatten(
                    session.query(Reservation.connection_id)
                    .join(Schedule)
                    .filter(
                        Reservation.lifecycle_state == LifecycleStateMachine.Created.value,
                        Reservation.data_plane_state == DataPlaneStateMachine.AutoStart.value,
                        Reservation.connection_id == Schedule.connection_id,
                        Reservation.version == Schedule.version,
                        Schedule.end_time > current_timestamp(),
                    )
                    .all()
                )
            )
        for cid in connection_ids:
            logger.info("Recovering job", job="AutoStartJob", connection_id=str(cid))

        return [AutoStartJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Trigger for AutoStartJob's.

        Returns:
            AutoStart set to start_time of reservation.
        """
        from supa.db.session import db_session

        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            return DateTrigger(run_date=reservation.schedule.start_time)


class AutoEndJob(Job):
    """Handle automatic deactivation of data plane when end time is reached."""

    connection_id: UUID
    log: BoundLogger

    def __init__(self, connection_id: UUID):
        """Initialize the AutoEndJob.

        Args:
           connection_id: The connection_id of the reservation auto end request
        """
        self.log = logger.bind(job=self.__class__.__name__, connection_id=str(connection_id))
        self.connection_id = connection_id

    def __call__(self) -> None:
        """Auto ending data plane request.

        Now that end time was reached schedule a DeactivateJob to deactivate the data plane.
        """
        self.log.info("Auto end data plane")

        from supa.db.session import db_session

        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")
            lsm.endtime_event()
            dpsm.deactivate_request()

        from supa import scheduler

        self.log.info("Schedule deactivate", job="DeactivateJob")
        scheduler.add_job(job := DeactivateJob(self.connection_id), trigger=job.trigger(), id=job.job_id)

    @classmethod
    def recover(cls: Type[AutoEndJob]) -> List[Job]:
        """Recover AutoEndJob's that did not get to run before SuPA was terminated.

        Returns:
            List of AutoEndJob's that still need to be run.
        """
        from supa.db.session import db_session

        with db_session() as session:
            connection_ids: List[UUID] = list(
                flatten(
                    session.query(Reservation.connection_id)
                    .filter(Reservation.data_plane_state == DataPlaneStateMachine.AutoEnd.value)
                    .all()
                )
            )
        for cid in connection_ids:
            logger.info("Recovering job", job="AutoEndJob", connection_id=str(cid))

        return [AutoEndJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Trigger for AutoEndJob's.

        Returns:
            AutoEnd set to end_time of reservation.
        """
        from supa.db.session import db_session

        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            return DateTrigger(run_date=reservation.schedule.end_time)
