#  Copyright 2020 SURF.
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

import random
from typing import Dict, List, NamedTuple, Type
from uuid import UUID

import structlog
from sqlalchemy import and_, func, or_, orm
from sqlalchemy.orm import aliased, joinedload
from structlog.stdlib import BoundLogger

from supa import settings
from supa.connection import requester
from supa.connection.error import (
    CapacityUnavailable,
    GenericInternalError,
    InvalidLabelFormat,
    InvalidTransition,
    NoServiceplanePathFound,
    StpUnavailable,
    UnknownStp,
    Variable,
)
from supa.connection.fsm import LifecycleStateMachine, ReservationStateMachine
from supa.db.model import Path, PathTrace, Port, Reservation, Segment
from supa.grpc_nsi.connection_requester_pb2 import ReserveConfirmedRequest, ReserveFailedRequest
from supa.job.shared import Job, NsiException
from supa.util.bandwidth import format_bandwidth
from supa.util.converter import to_confirm_criteria, to_connection_states, to_header, to_service_exception
from supa.util.vlan import VlanRanges

logger = structlog.get_logger(__name__)


class PortResources(NamedTuple):
    """Capture port resources, as returned by an SQLAlchemy query, so that they can be referred to by name."""

    bandwidth: int
    vlans: VlanRanges


class ReserveJob(Job):
    connection_id: UUID
    log: BoundLogger

    def __init__(self, connection_id: UUID):
        self.log = logger.bind(job=self.__class__.__name__)
        self.connection_id = connection_id

    def _port_resources_in_use(self, session: orm.Session) -> Dict[str, PortResources]:
        """Calculate port resources in use for active reservations that overlap with ours.

        Active reservations being those that:

        - are currently being held
        - have been committed and not yet been terminated.

        Overlap as in: their start times and end times overlap with ours.

        The bandwidth in use is calculated per port.
        Eg, if a port is used in two active reservations,
        (one reservation for a connection with a bandwidth of 100 Mbps
        and another with a bandwidth of 400 Mbps)
        the bandwidth in use for the port will be:
        100 + 400 = 500 Mbps.

        Similarly for the VLANs in use.
        Given the same port used in two active reservations
        (one reservation where the port has a VLAN of 100
        and another one where the port has a VLAN of 105),
        the VLANs in use for the port will be:
        VlanRanges([100, 105])

        Args:
            session: A SQLAlchemy session to construct and run the DB query

        Returns:
            A dict mapping port (names) to their port resources.

        """
        # To calculate the active overlapping reservation we need to perform a self-join.
        # One part of the join is for our (current) reservation.
        # The other part is for joining the overlapping ones with our (current) reservation.
        CurrentReservation = aliased(Reservation, name="cr")
        overlap_active = (
            # The other part
            session.query(Reservation)
            .join(
                (
                    CurrentReservation,
                    # Do they overlap?
                    and_(
                        CurrentReservation.start_time < Reservation.end_time,
                        CurrentReservation.end_time > Reservation.start_time,
                    ),
                )
            )
            .filter(
                # Only select active reservations
                or_(
                    and_(
                        Reservation.reservation_state == ReservationStateMachine.ReserveStart.name,
                        Reservation.provisioning_state.isnot(None),
                        Reservation.lifecycle_state == LifecycleStateMachine.Created.name,
                    ),
                    Reservation.reservation_state == ReservationStateMachine.ReserveHeld.name,
                )
            )
            # And only those that overlap with our reservation.
            .filter(CurrentReservation.connection_id == self.connection_id)
        ).subquery()
        OverlappingActiveReservation = aliased(Reservation, overlap_active, name="oar")

        # To map ports to resources (bandwidth and vlan) in use
        # we need to unpivot the two pair of port columns from the reservations table into separate rows.
        # Eg, from:
        #
        # row 1:  connection_id, ..., src_port, src_selected_vlan, dst_port, .dst_selected_vlan ..
        #
        # to:
        #
        # row 1: connection_id, port, vlan  <-- former src_port, src_selected_vlan
        # row 2: connection_id, port, vlan  <-- former dst_port, dst_selected_vlan
        src_port = session.query(
            Reservation.connection_id.label("connection_id"),
            Reservation.src_port.label("port"),
            Reservation.src_selected_vlan.label("vlan"),
        )
        dst_port = session.query(
            Reservation.connection_id,
            Reservation.dst_port.label("port"),
            Reservation.dst_selected_vlan.label("vlan"),
        )
        ports = src_port.union(dst_port).subquery()

        # With the 'hard' work done for us in two subqueries,
        # calculating the port resources (bandwidth, VLANs) in use is now relatively straightforward.
        port_resources_in_use = (
            session.query(
                ports.c.port,
                func.sum(OverlappingActiveReservation.bandwidth).label("bandwidth"),
                func.group_concat(ports.c.vlan, ",").label("vlans"),  # yes, plural!
            )
            .select_from(OverlappingActiveReservation)
            .join(ports, OverlappingActiveReservation.connection_id == ports.c.connection_id)
            .filter(
                ports.c.port.in_(
                    (
                        OverlappingActiveReservation.src_port,
                        OverlappingActiveReservation.dst_port,
                    )
                )
            )
            .group_by(ports.c.port)
            .all()
        )

        return {
            rec.port: PortResources(bandwidth=rec.bandwidth, vlans=VlanRanges(rec.vlans))
            for rec in port_resources_in_use
        }

    def _send_reserve_failed(self, session: orm.Session, nsi_exc: NsiException) -> None:
        # the reservation is still in the session, hence no actual query will be performed
        reservation: Reservation = session.query(Reservation).get(self.connection_id)
        pb_rf_req = ReserveFailedRequest()

        pb_rf_req.header.CopyFrom(to_header(reservation, add_path_segment=False))
        pb_rf_req.connection_id = str(reservation.connection_id)
        pb_rf_req.connection_states.CopyFrom(to_connection_states(reservation, data_plane_active=False))
        pb_rf_req.service_exception.CopyFrom(to_service_exception(nsi_exc, reservation.connection_id))

        self.log.info("Sending message.", method="ReserveFailed", request_message=pb_rf_req)
        stub = requester.get_stub()
        stub.ReserveFailed(pb_rf_req)

    def _send_reserve_confirmed(self, session: orm.Session) -> None:
        # the reservation is still in the session, hence no actual query will be performed
        reservation: Reservation = session.query(Reservation).get(self.connection_id)

        pb_rc_req = ReserveConfirmedRequest()
        # Confirming the reservation means we have a Path. hence we should add it to the Header.
        pb_rc_req.header.CopyFrom(to_header(reservation, add_path_segment=True))
        pb_rc_req.connection_id = str(reservation.connection_id)
        pb_rc_req.global_reservation_id = reservation.global_reservation_id
        # We skip setting the description, cause we have nothing specific to set it to (suggestions?)
        pb_rc_req.criteria.CopyFrom(to_confirm_criteria(reservation))

        self.log.info("Sending message.", method="ReserveConfirmed", request_message=pb_rc_req)
        stub = requester.get_stub()
        stub.ReserveConfirmed(pb_rc_req)

    def __call__(self) -> None:
        self.log.info("Checking reservation request.")
        from supa.db.session import db_session

        with db_session() as session:
            reservation: Reservation = (
                session.query(Reservation)
                .options(
                    joinedload(Reservation.parameters),
                    joinedload(Reservation.path_trace)
                    .joinedload(PathTrace.paths)
                    .joinedload(Path.segments)
                    .joinedload(Segment.stps),
                )
                .get(self.connection_id)
            )
            rsm = ReservationStateMachine(reservation, state_field="reservation_state")
            port_resources_in_use = self._port_resources_in_use(session)

            try:
                if rsm.current_state != ReservationStateMachine.ReserveChecking:
                    raise NsiException(
                        InvalidTransition,
                        rsm.current_state.name,
                        {Variable.RESERVATION_STATE: rsm.current_state.value},
                    )
                if reservation.src_port == reservation.dst_port:
                    raise NsiException(
                        # Not sure if this is the correct error to use.
                        # As its descriptive text refers to path computation
                        # it suggests its an error typically returned by an aggregator.
                        # On the other hand it is the only error related to a path/connection as a whole
                        # and that is what is at issue here.
                        NoServiceplanePathFound,
                        "source and destination ports are the same",
                        {
                            Variable.PROVIDER_NSA: settings.nsa_id,
                            Variable.SOURCE_STP: str(reservation.src_stp()),
                            Variable.DEST_STP: str(reservation.dst_stp()),
                        },
                    )
                for target, var in (("src", Variable.SOURCE_STP), ("dst", Variable.DEST_STP)):
                    # Dynamic attribute lookups as we want to use the same code for
                    # both src and dst ports/stps
                    res_port = getattr(reservation, f"{target}_port")
                    stp = str(getattr(reservation, f"{target}_stp")())  # <-- mind the func call
                    domain = getattr(reservation, f"{target}_domain")
                    network_type = getattr(reservation, f"{target}_network_type")
                    requested_vlans = VlanRanges(getattr(reservation, f"{target}_vlans"))
                    port = session.query(Port).filter(Port.name == res_port).one_or_none()
                    if (
                        port is None
                        or not port.enabled
                        or domain != settings.domain  # only process requests for our domain
                        or network_type != settings.network_type  # only process requests for our network
                    ):
                        raise NsiException(UnknownStp, stp, {var: stp})
                    if not requested_vlans:
                        raise NsiException(InvalidLabelFormat, "missing VLANs label on STP", {var: stp})
                    if port.name in port_resources_in_use:
                        bandwidth_available = port.bandwidth - port_resources_in_use[port.name].bandwidth
                        available_vlans = VlanRanges(port.vlans) - port_resources_in_use[port.name].vlans
                    else:
                        bandwidth_available = port.bandwidth
                        available_vlans = VlanRanges(port.vlans)
                    if bandwidth_available < reservation.bandwidth:
                        raise NsiException(
                            CapacityUnavailable,
                            f"requested: {format_bandwidth(reservation.bandwidth)}, "
                            f"available: {format_bandwidth(bandwidth_available)}",
                            {
                                Variable.CAPACITY: str(reservation.bandwidth),
                                var: stp,
                            },
                        )
                    if not available_vlans:
                        raise NsiException(StpUnavailable, "all VLANs in use", {var: stp})
                    candidate_vlans = requested_vlans & available_vlans
                    if not candidate_vlans:
                        raise NsiException(
                            StpUnavailable,
                            f"no matching VLAN found (requested: {requested_vlans!s}, available: {available_vlans!s}",
                            {var: stp},
                        )
                    selected_vlan = random.choice(list(candidate_vlans))
                    setattr(reservation, f"{target}_selected_vlan", selected_vlan)
            except NsiException as nsi_exc:
                self.log.info("Reservation failed.", reason=nsi_exc.text)
                rsm.reserve_failed()
                self._send_reserve_failed(session, nsi_exc)
            except Exception as exc:
                self.log.exception("Unexpected error occurred.", reason=str(exc))
                rsm.reserve_failed()
                nsi_exc = NsiException(GenericInternalError, str(exc))  # type: ignore[misc]
                self._send_reserve_failed(session, nsi_exc)  # type: ignore[misc]
            else:
                rsm.reserve_confirmed()
                self._send_reserve_confirmed(session)

    @classmethod
    def recover(cls: Type[ReserveJob]) -> List[Job]:
        # TODO [GK 20201003] Fancy query restoring all Job to peform Reservation checking
        pass
