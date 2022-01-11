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
from sqlalchemy import or_, orm
from structlog.stdlib import BoundLogger

from supa.connection import requester
from supa.connection.error import GenericInternalError, Variable
from supa.connection.fsm import DataPlaneStateMachine, LifecycleStateMachine, ProvisionStateMachine
from supa.connection.requester import send_data_plane_state_change, send_error
from supa.db.model import Reservation
from supa.grpc_nsi.connection_requester_pb2 import ProvisionConfirmedRequest, ReleaseConfirmedRequest
from supa.job.shared import Job, NsiException
from supa.util.converter import to_header

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

        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one_or_none()
            )
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            try:
                #
                # TODO:  Call the Network Resource Manager to activate the data plane.
                #        If this is a recovered job then try to recover the data plane state
                #        from the NRM.
                #
                pass
            except NsiException as nsi_exc:
                self.log.info("Data plane activation failed", reason=nsi_exc.text)
                send_error(
                    to_header(reservation),
                    nsi_exc,
                    self.connection_id,
                )
            except Exception as exc:
                self.log.exception("Unexpected error occurred", reason=str(exc))
                send_error(
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
                dpsm.data_plane_activated()
                send_data_plane_state_change(session, self.connection_id)

    @classmethod
    def recover(cls: Type[ActivateJob]) -> List[Job]:
        """Recover ActivationJob's that did not get to run before SuPA was terminated.

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
                        Reservation.provision_state == ProvisionStateMachine.Provisioned.value,
                        or_(
                            Reservation.data_plane_state == DataPlaneStateMachine.Inactive.value,
                            Reservation.data_plane_state == DataPlaneStateMachine.Activating.value,
                        ),
                    )
                    .all()
                )
            )
        for cid in connection_ids:
            logger.debug("Recover job", job="ActivateJob", connection_id=str(cid))

        return [ActivateJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Trigger for ActivateJob's.

        Returns:
            DateTrigger set to start_time of reservation.
        """
        from supa.db.session import db_session

        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one_or_none()
            )
            # If start_time is in the past then the job will run immediately.
            return DateTrigger(run_date=reservation.start_time)
