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
from structlog.stdlib import BoundLogger

from supa.connection import requester
from supa.connection.error import GenericInternalError, Variable
from supa.connection.fsm import DataPlaneStateMachine, ProvisionStateMachine
from supa.connection.requester import send_error
from supa.db.model import Reservation
from supa.grpc_nsi.connection_requester_pb2 import ProvisionConfirmedRequest
from supa.job.dataplane import ActivateJob
from supa.job.shared import Job, NsiException
from supa.util.converter import to_header

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

        The reservation will be provisioned and
        a ProvisionConfirmed message will be sent to the NSA/AG.
        If the provision state machine is not in the correct state for a Provision
        an NSI exception is returned leaving the state machine unchanged.
        """
        self.log.info("Provisioning reservation")

        from supa.db.session import db_session

        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one_or_none()
            )
            psm = ProvisionStateMachine(reservation, state_field="provision_state")
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
                from supa import scheduler

                psm.provision_confirmed()
                dpsm.data_plane_up()
                scheduler.add_job(job := ActivateJob(self.connection_id), trigger=job.trigger())
                self._send_provision_confirmed(session)

    @classmethod
    def recover(cls: Type[ProvisionJob]) -> List[Job]:
        """Recover ProvisionJob's that did not get to run before SuPA was terminated.

        Returns:
            List of ProvisionJob's that still need to be run.
        """
        from supa.db.session import db_session

        with db_session() as session:
            connection_ids: List[UUID] = list(
                flatten(
                    session.query(Reservation.connection_id)
                    .filter(Reservation.provision_state == ProvisionStateMachine.Provisioning.value)
                    .all()
                )
            )
        return [ProvisionJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Trigger for ReserveAbortJobs."""
        return DateTrigger(run_date=None)  # Run immediately
