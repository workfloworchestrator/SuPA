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
from statemachine.exceptions import TransitionNotAllowed
from structlog.stdlib import BoundLogger

from supa.connection import requester
from supa.connection.error import GenericConnectionError, GenericInternalError, InvalidTransition, Variable
from supa.connection.fsm import DataPlaneStateMachine, LifecycleStateMachine, ProvisionStateMachine
from supa.db.model import Connection, Reservation, connection_to_dict
from supa.grpc_nsi.connection_requester_pb2 import ErrorRequest, GenericConfirmedRequest
from supa.job.dataplane import ActivateJob, AutoEndJob, AutoStartJob, DeactivateJob
from supa.job.shared import Job, NsiException, register_result
from supa.util.converter import to_error_request, to_generic_confirmed_request, to_header
from supa.util.timestamp import current_timestamp
from supa.util.type import ResultType

logger = structlog.get_logger(__name__)


class ProvisionJob(Job):
    """Handle provision requests."""

    connection_id: UUID
    log: BoundLogger

    def __init__(self, connection_id: UUID):
        """Initialize the ProvisionJob.

        Args:
           connection_id: The connection_id of the reservation provision request
        """
        self.log = logger.bind(job=self.__class__.__name__, connection_id=str(connection_id))
        self.connection_id = connection_id

    def __call__(self) -> None:
        """Provision reservation request.

        The reservation will be provisioned,
        a job to activate the data plane will be scheduled when start time was already reached
        or otherwise a job to auto start the data plane at start time will be scheduled
        and in both cases a ProvisionConfirmed message will be sent to the NSA/AG.
        """
        self.log.info("Provision reservation")

        from supa.db.session import db_session
        from supa.nrm.backend import backend

        request: Union[GenericConfirmedRequest, ErrorRequest]
        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            psm = ProvisionStateMachine(reservation, state_field="provision_state")
            lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            try:
                if circuit_id := backend.provision(**connection_to_dict(connection)):
                    connection.circuit_id = circuit_id
            except NsiException as nsi_exc:
                self.log.info("Provision failed.", reason=nsi_exc.text)
                request = to_error_request(
                    to_header(reservation),
                    nsi_exc,
                    self.connection_id,
                )
            except Exception as exc:
                self.log.exception("Unexpected error occurred.", reason=str(exc))
                request = to_error_request(
                    to_header(reservation),
                    NsiException(
                        GenericInternalError,
                        str(exc),
                        {
                            Variable.PROVISION_STATE: reservation.provsion_state,
                            Variable.CONNECTION_ID: str(self.connection_id),
                        },
                    ),
                    self.connection_id,
                )
            else:
                # the NRM successfully provisioned the reservation,
                # check if reservation is not terminated and data plane can be activated,
                # if start time has already passed schedule a ActivateJob otherwise a AutoStartJob
                if lsm.current_state != LifecycleStateMachine.Created:
                    self.log.info("No auto start or activate data plane", reason="Reservation already terminated")
                    request = to_error_request(
                        to_header(reservation),
                        NsiException(
                            GenericConnectionError,
                            "Reservation already terminated",
                            {
                                Variable.CONNECTION_ID: str(self.connection_id),
                            },
                        ),
                        self.connection_id,
                    )
                elif current_timestamp() < reservation.start_time:
                    try:
                        dpsm.auto_start_request()
                    except TransitionNotAllowed as tna:
                        self.log.info("No auto start", reason=str(tna))
                        request = to_error_request(
                            to_header(reservation),
                            NsiException(
                                InvalidTransition,
                                str(tna),
                                {
                                    Variable.CONNECTION_ID: str(self.connection_id),
                                },
                            ),
                            self.connection_id,
                        )
                    else:
                        start_time = reservation.start_time
                        request = to_generic_confirmed_request(reservation)
                        psm.provision_confirmed()
                else:
                    try:
                        dpsm.activate_request()
                    except TransitionNotAllowed as tna:
                        self.log.info("No activate data plane", reason=str(tna))
                        request = to_error_request(
                            to_header(reservation),
                            NsiException(
                                InvalidTransition,
                                str(tna),
                                {
                                    Variable.CONNECTION_ID: str(self.connection_id),
                                },
                            ),
                            self.connection_id,
                        )
                    else:
                        request = to_generic_confirmed_request(reservation)
                        psm.provision_confirmed()
                new_data_plane_state = reservation.data_plane_state

        stub = requester.get_stub()
        if type(request) == GenericConfirmedRequest:
            from supa import scheduler

            job: Job  # help mypy understand that both AutoStartJob and ActivateJob are Job's
            if new_data_plane_state == DataPlaneStateMachine.AutoStart.value:
                self.log.info("Schedule auto start", job="AutoStartJob", start_time=start_time.isoformat())
                scheduler.add_job(job := AutoStartJob(self.connection_id), trigger=job.trigger(), id=job.job_id)
            elif new_data_plane_state == DataPlaneStateMachine.Activating.value:
                self.log.info("Schedule activate", job="ActivateJob")
                scheduler.add_job(job := ActivateJob(self.connection_id), trigger=job.trigger(), id=job.job_id)
            register_result(request, ResultType.ProvisionConfirmed)
            self.log.debug("Sending message", method="ProvisionConfirmed", request_message=request)
            stub.ProvisionConfirmed(request)
        else:
            register_result(request, ResultType.Error)
            self.log.debug("Sending message", method="Error", request_message=request)
            stub.Error(request)

    @classmethod
    def recover(cls: Type[ProvisionJob]) -> List[Job]:
        """Recover ProvisionJob's that did not get to run before SuPA was terminated.

        Only include jobs for reservations that are still supposed to have its data plane activated
        according to their lifecycle state and end time.

        Returns:
            List of ProvisionJob's that still need to be run.
        """
        from supa.db.session import db_session

        with db_session() as session:
            connection_ids: List[UUID] = list(
                flatten(
                    session.query(Reservation.connection_id)
                    .filter(
                        Reservation.lifecycle_state == LifecycleStateMachine.Created.value,
                        Reservation.provision_state == ProvisionStateMachine.Provisioning.value,
                        Reservation.end_time > current_timestamp(),
                    )
                    .all()
                )
            )
        for cid in connection_ids:
            logger.info("Recovering job", job="ProvisionJob", connection_id=str(cid))

        return [ProvisionJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Trigger for ProvisionJobs."""
        return DateTrigger(run_date=None)  # Run immediately


class ReleaseJob(Job):
    """Handle release requests."""

    connection_id: UUID
    log: BoundLogger

    def __init__(self, connection_id: UUID):
        """Initialize the ReleaseJob.

        Args:
           connection_id: The connection_id of the reservation release request
        """
        self.log = logger.bind(job=self.__class__.__name__, connection_id=str(connection_id))
        self.connection_id = connection_id

    def __call__(self) -> None:
        """Release reservation request.

        The reservation will be released,
        a job to deactivate the data plane will be scheduled and
        a ReleaseConfirmed message will be sent to the NSA/AG.
        """
        self.log.info("Release reservation")

        from supa.db.session import db_session
        from supa.nrm.backend import backend

        request: Union[GenericConfirmedRequest, ErrorRequest]
        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            psm = ProvisionStateMachine(reservation, state_field="provision_state")
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")
            try:
                if circuit_id := backend.release(**connection_to_dict(connection)):
                    connection.circuit_id = circuit_id
            except NsiException as nsi_exc:
                self.log.info("Release failed.", reason=nsi_exc.text)
                request = to_error_request(
                    to_header(reservation),
                    nsi_exc,
                    self.connection_id,
                )
            except Exception as exc:
                self.log.exception("Unexpected error occurred.", reason=str(exc))
                request = to_error_request(
                    to_header(reservation),
                    NsiException(
                        GenericInternalError,
                        str(exc),
                        {
                            Variable.PROVISION_STATE: reservation.provsion_state,
                            Variable.CONNECTION_ID: str(self.connection_id),
                        },
                    ),
                    self.connection_id,
                )
            else:
                # the NRM successfully released the reservation,
                # check if reservation is not terminated,
                # cancel the AutoStartJob or AutoEndJob,
                # and schedule a DeactivateJob if the data plane is active
                if lsm.current_state != LifecycleStateMachine.Created:
                    self.log.info("No deactivate data plane", reason="Reservation already terminated")
                    request = to_error_request(
                        to_header(reservation),
                        NsiException(
                            GenericConnectionError,
                            "Reservation already terminated",
                            {
                                Variable.CONNECTION_ID: str(self.connection_id),
                            },
                        ),
                        self.connection_id,
                    )
                else:
                    previous_data_plane_state = reservation.data_plane_state
                    try:
                        dpsm.deactivate_request()
                    except TransitionNotAllowed as tna:
                        self.log.info("No deactivate data plane", reason=str(tna))
                        request = to_error_request(
                            to_header(reservation),
                            NsiException(
                                InvalidTransition,
                                str(tna),
                                {
                                    Variable.CONNECTION_ID: str(self.connection_id),
                                },
                            ),
                            self.connection_id,
                        )
                    request = to_generic_confirmed_request(reservation)
                    psm.release_confirmed()

        stub = requester.get_stub()
        if type(request) == GenericConfirmedRequest:
            from supa import scheduler

            if previous_data_plane_state == DataPlaneStateMachine.AutoStart.value:
                self.log.info("Cancel auto start")
                scheduler.remove_job(job_id=AutoStartJob(self.connection_id).job_id)
            else:  # previous data plane state is either AutoEnd or Activated
                if previous_data_plane_state == DataPlaneStateMachine.AutoEnd.value:
                    self.log.info("Cancel auto end")
                    scheduler.remove_job(job_id=AutoEndJob(self.connection_id).job_id)
                self.log.info("Schedule deactivate", job="DeactivateJob")
                scheduler.add_job(job := DeactivateJob(self.connection_id), trigger=job.trigger(), id=job.job_id)
            register_result(request, ResultType.ReleaseConfirmed)
            self.log.debug("Sending message", method="ReleaseConfirmed", request_message=request)
            stub.ReleaseConfirmed(request)
        else:
            register_result(request, ResultType.Error)
            self.log.debug("Sending message", method="Error", request_message=request)
            stub.Error(request)

    @classmethod
    def recover(cls: Type[ReleaseJob]) -> List[Job]:
        """Recover ReleaseJob's that did not get to run before SuPA was terminated.

        Returns:
            List of ReleaseJob's that still need to be run.
        """
        from supa.db.session import db_session

        with db_session() as session:
            connection_ids: List[UUID] = list(
                flatten(
                    session.query(Reservation.connection_id)
                    .filter(
                        Reservation.lifecycle_state == LifecycleStateMachine.Created.value,
                        Reservation.provision_state == ProvisionStateMachine.Releasing.value,
                    )
                    .all()
                )
            )
        for cid in connection_ids:
            logger.info("Recovering job", job="ReleaseJob", connection_id=str(cid))

        return [ReleaseJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Trigger for ReleaseJobs."""
        return DateTrigger(run_date=None)  # Run immediately
