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
from supa.connection.error import GenericConnectionError, GenericInternalError, InvalidTransition, Variable
from supa.connection.fsm import DataPlaneStateMachine, LifecycleStateMachine, ProvisionStateMachine
from supa.connection.requester import send_error
from supa.db.model import Reservation
from supa.grpc_nsi.connection_requester_pb2 import ProvisionConfirmedRequest, ReleaseConfirmedRequest
from supa.job.dataplane import ActivateJob, AutoStartJob, DeactivateJob
from supa.job.shared import Job, NsiException
from supa.util.converter import to_header
from supa.util.timestamp import current_timestamp

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

    def _send_provision_confirmed(self, session: orm.Session) -> None:
        # the reservation is still in the session, hence no actual query will be performed
        reservation: Reservation = session.query(Reservation).get(self.connection_id)
        pb_pc_req = ProvisionConfirmedRequest()

        pb_pc_req.header.CopyFrom(to_header(reservation, add_path_segment=True))  # Yes, add our segment!
        pb_pc_req.connection_id = str(reservation.connection_id)

        self.log.debug("Sending message.", method="ProvisionConfirmed", request_message=pb_pc_req)
        stub = requester.get_stub()
        stub.ProvisionConfirmed(pb_pc_req)

    def __call__(self) -> None:
        """Provision reservation request.

        The reservation will be provisioned,
        a job to activate the data plane will be scheduled when start time was already reached
        or otherwise a job to auto start the data plane at start time will be scheduled
        and in both cases a ProvisionConfirmed message will be sent to the NSA/AG.
        """
        self.log.info("Provisioning reservation")

        from supa.db.session import db_session

        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one_or_none()
            )
            psm = ProvisionStateMachine(reservation, state_field="provision_state")
            lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            try:
                #
                # TODO:  If there is a Network Resource Manager that needs to be contacted
                #        to provision the reservation request then this is the place.
                #        If this is a recovered job then try to recover the reservation state
                #        from the NRM.
                #
                pass
            except NsiException as nsi_exc:
                self.log.info("Provision failed.", reason=nsi_exc.text)
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
                from supa import scheduler

                if lsm.current_state != LifecycleStateMachine.Created:
                    self.log.info("Not scheduling AutoStartJob or ActivateJob", reason="Reservation already terminated")
                    send_error(
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
                        self.log.info("Not scheduling AutoStartJob", reason=str(tna))
                        send_error(
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
                        scheduler.add_job(
                            AutoStartJob(self.connection_id),
                            trigger=DateTrigger(run_date=reservation.start_time),
                            id=f"{str(self.connection_id)}-AutoStartJob",
                        )
                        self.log.info(f"Automatic enable of data plane at {reservation.start_time.isoformat()}")
                        psm.provision_confirmed()
                        self._send_provision_confirmed(session)
                else:
                    try:
                        dpsm.activate_request()
                    except TransitionNotAllowed as tna:
                        self.log.info("Not scheduling ActivateJob", reason=str(tna))
                        send_error(
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
                        scheduler.add_job(
                            ActivateJob(self.connection_id),
                            trigger=DateTrigger(run_date=None),
                            id=f"{str(self.connection_id)}-ActivateJob",
                        )
                        psm.provision_confirmed()
                        self._send_provision_confirmed(session)

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

    def _send_release_confirmed(self, session: orm.Session) -> None:
        # the reservation is still in the session, hence no actual query will be performed
        reservation: Reservation = session.query(Reservation).get(self.connection_id)
        pb_rc_req = ReleaseConfirmedRequest()

        pb_rc_req.header.CopyFrom(to_header(reservation, add_path_segment=True))  # Yes, add our segment!
        pb_rc_req.connection_id = str(reservation.connection_id)

        self.log.debug("Sending message.", method="ReleaseConfirmed", request_message=pb_rc_req)
        stub = requester.get_stub()
        stub.ReleaseConfirmed(pb_rc_req)

    def __call__(self) -> None:
        """Release reservation request.

        The reservation will be released,
        a job to deactivate the data plane will be scheduled and
        a ReleaseConfirmed message will be sent to the NSA/AG.
        """
        self.log.info("Releasing reservation")

        from supa.db.session import db_session

        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one_or_none()
            )
            psm = ProvisionStateMachine(reservation, state_field="provision_state")
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")
            try:
                #
                # TODO:  If there is a Network Resource Manager that needs to be contacted
                #        to release the reservation request then this is the place.
                #        If this is a recovered job then try to recover the reservation state
                #        from the NRM.
                #
                pass
            except NsiException as nsi_exc:
                self.log.info("Release failed.", reason=nsi_exc.text)
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
                from supa import scheduler

                if lsm.current_state != LifecycleStateMachine.Created:
                    self.log.info("Not scheduling DeactivateJob", reason="Reservation already terminated")
                    send_error(
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
                        self.log.info("Not scheduling DeactivateJob", reason=str(tna))
                        send_error(
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
                    psm.release_confirmed()
                    self._send_release_confirmed(session)

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
