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

from typing import List, Type, Union
from uuid import UUID

import structlog
from apscheduler.triggers.date import DateTrigger
from more_itertools import flatten
from structlog.stdlib import BoundLogger

from supa.connection import requester
from supa.connection.error import GenericInternalError, Variable
from supa.connection.fsm import DataPlaneStateMachine, LifecycleStateMachine
from supa.connection.requester import to_data_plane_state_change_request, to_error_request
from supa.db.model import Reservation
from supa.grpc_nsi.connection_requester_pb2 import DataPlaneStateChangeRequest, ErrorRequest
from supa.job.shared import Job, NsiException
from supa.nrm.backend import call_backend
from supa.util.converter import to_header
from supa.util.timestamp import NO_END_DATE, current_timestamp

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
        self.log.info("Activating data plane")

        from supa.db.session import db_session

        response: Union[DataPlaneStateChangeRequest, ErrorRequest]
        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one_or_none()
            )
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            try:
                call_backend("activate", reservation, session)
            except NsiException as nsi_exc:
                dpsm.activate_failed()
                self.log.info("Data plane activation failed", reason=nsi_exc.text)
                response = to_error_request(
                    to_header(reservation),
                    nsi_exc,
                    self.connection_id,
                )
            except Exception as exc:
                dpsm.activate_failed()
                self.log.exception("Unexpected error occurred", reason=str(exc))
                response = to_error_request(
                    to_header(reservation),
                    NsiException(
                        GenericInternalError,
                        str(exc),
                        {
                            Variable.CONNECTION_ID: str(self.connection_id),
                        },
                    ),
                    self.connection_id,
                )
            else:
                from supa import scheduler

                dpsm.activate_confirmed()
                response = to_data_plane_state_change_request(reservation)
                if reservation.end_time != NO_END_DATE:
                    dpsm.auto_end_request()
                    scheduler.add_job(
                        AutoEndJob(self.connection_id),
                        trigger=DateTrigger(run_date=reservation.end_time),
                        id=f"{str(self.connection_id)}-AutoEndJob",
                    )
                    self.log.info(
                        "Automatic disable of data plane at end time", end_time=reservation.end_time.isoformat()
                    )

        stub = requester.get_stub()
        if type(response) == DataPlaneStateChangeRequest:
            self.log.debug("Sending message", method="DataPlaneStateChange", request_message=response)
            stub.DataPlaneStateChange(response)
        else:
            self.log.debug("Sending message", method="Error", request_message=response)
            stub.Error(response)

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
                    .filter(
                        Reservation.lifecycle_state == LifecycleStateMachine.Created.value,
                        Reservation.data_plane_state == DataPlaneStateMachine.Activating.value,
                        Reservation.end_time > current_timestamp(),
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
            DateTrigger set to start_time of reservation.
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
        self.log.info("Deactivating data plane")

        from supa.db.session import db_session

        response: Union[DataPlaneStateChangeRequest, ErrorRequest]
        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one_or_none()
            )
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            # lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")
            # # when past end time register a lifecycle end time event
            # if reservation.end_time <= current_timestamp():
            #     lsm.endtime_event()
            #     dpsm.deactivate_request()
            try:
                call_backend("deactivate", reservation, session)
            except NsiException as nsi_exc:
                dpsm.deactivate_failed()
                self.log.info("Data plane deactivation failed", reason=nsi_exc.text)
                response = to_error_request(
                    to_header(reservation),
                    nsi_exc,
                    self.connection_id,
                )
            except Exception as exc:
                dpsm.deactivate_failed()
                self.log.exception("Unexpected error occurred", reason=str(exc))
                response = to_error_request(
                    to_header(reservation),
                    NsiException(
                        GenericInternalError,
                        str(exc),
                        {
                            Variable.CONNECTION_ID: str(self.connection_id),
                        },
                    ),
                    self.connection_id,
                )
            else:
                dpsm.deactivate_confirm()
                response = to_data_plane_state_change_request(reservation)

        stub = requester.get_stub()
        if type(response) == DataPlaneStateChangeRequest:
            self.log.debug("Sending message", method="DataPlaneStateChange", request_message=response)
            stub.DataPlaneStateChange(response)
        else:
            self.log.debug("Sending message", method="Error", request_message=response)
            stub.Error(response)

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
            DateTrigger set to None if (run immediately) if reservation is released or not active anymore or
            to end_time otherwise (end_time can be in the past when recovering).
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
        self.log.info("AutoStarting data plane")

        from supa.db.session import db_session

        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one_or_none()
            )
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")

            from supa import scheduler

            dpsm.activate_request()
            scheduler.add_job(
                ActivateJob(self.connection_id),
                trigger=DateTrigger(run_date=None),
                id=f"{str(self.connection_id)}-ActivateJob",
            )

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
                    .filter(
                        Reservation.lifecycle_state == LifecycleStateMachine.Created.value,
                        Reservation.data_plane_state == DataPlaneStateMachine.AutoStart.value,
                        Reservation.end_time > current_timestamp(),
                    )
                    .all()
                )
            )
        for cid in connection_ids:
            logger.info("Recovering job", job="AutoStartJob", connection_id=str(cid))

        return [ActivateJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Trigger for AutoStartJob's.

        Returns:
            AutoStart set to start_time of reservation.
        """
        from supa.db.session import db_session

        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one_or_none()
            )
            return DateTrigger(run_date=reservation.start_time)


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
        self.log.info("AutoEnding data plane")

        from supa.db.session import db_session

        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one_or_none()
            )
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")

            from supa import scheduler

            lsm.endtime_event()
            dpsm.deactivate_request()
            scheduler.add_job(
                DeactivateJob(self.connection_id),
                trigger=DateTrigger(run_date=None),
                id=f"{str(self.connection_id)}-DeactivateJob",
            )

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
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one_or_none()
            )
            return DateTrigger(run_date=reservation.end_time)
