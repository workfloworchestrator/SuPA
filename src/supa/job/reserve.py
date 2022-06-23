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
from datetime import timedelta
from typing import Dict, List, NamedTuple, Type, Union
from uuid import UUID

import structlog
from apscheduler.triggers.date import DateTrigger
from more_itertools import flatten
from sqlalchemy import and_, func, or_, orm
from sqlalchemy.orm import aliased, joinedload
from statemachine.exceptions import TransitionNotAllowed
from structlog.stdlib import BoundLogger

from supa import settings
from supa.connection import requester
from supa.connection.error import (
    CapacityUnavailable,
    GenericInternalError,
    InvalidLabelFormat,
    NoServiceplanePathFound,
    StpUnavailable,
    UnknownStp,
    Variable,
)
from supa.connection.fsm import LifecycleStateMachine, ProvisionStateMachine, ReservationStateMachine
from supa.db.model import Connection, Path, PathTrace, Reservation, Segment, Topology, connection_to_dict
from supa.grpc_nsi.connection_requester_pb2 import (
    ErrorRequest,
    ReserveAbortConfirmedRequest,
    ReserveCommitConfirmedRequest,
    ReserveCommitFailedRequest,
    ReserveConfirmedRequest,
    ReserveFailedRequest,
    ReserveTimeoutRequest,
)
from supa.job.shared import Job, NsiException
from supa.util.bandwidth import format_bandwidth
from supa.util.converter import to_confirm_criteria, to_connection_states, to_header, to_service_exception
from supa.util.timestamp import current_timestamp
from supa.util.vlan import VlanRanges

logger = structlog.get_logger(__name__)


class StpResources(NamedTuple):
    """Capture STP resources, as returned by an SQLAlchemy query, so that they can be referred to by name."""

    bandwidth: int
    vlans: VlanRanges


class ReserveJob(Job):
    """Handle reservation requests."""

    connection_id: UUID
    log: BoundLogger

    def __init__(self, connection_id: UUID):
        """Initialize the ReserveJob.

        Args:
           connection_id: The connection_id of the reservation request
        """
        self.log = logger.bind(job=self.__class__.__name__, connection_id=str(connection_id))
        self.connection_id = connection_id
        self.src_port_id: str = ""
        self.dst_port_id: str = ""

    def _stp_resources_in_use(self, session: orm.Session) -> Dict[str, StpResources]:
        """Calculate STP resources in use for active reservations that overlap with ours.

        Active reservations being those that:

        - are currently being held
        - have been committed and not yet been terminated.

        Overlap as in: their start times and end times overlap with ours.

        The bandwidth in use is calculated per STP.
        Eg, if a STP is used in two active reservations,
        (one reservation for a connection with a bandwidth of 100 Mbps
        and another with a bandwidth of 400 Mbps)
        the bandwidth in use for the port will be:
        100 + 400 = 500 Mbps.

        Similarly for the VLANs in use.
        Given the same STP used in two active reservations
        (one reservation where the STP has a VLAN of 100
        and another one where the STP has a VLAN of 105),
        the VLANs in use for the STP will be:
        VlanRanges([100, 105])

        Args:
            session: A SQLAlchemy session to construct and run the DB query

        Returns:
            A dict mapping STP (names) to their STP resources.

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
                        Reservation.reservation_state == ReservationStateMachine.ReserveStart.value,
                        Reservation.provision_state.isnot(None),
                        Reservation.lifecycle_state == LifecycleStateMachine.Created.value,
                    ),
                    Reservation.reservation_state == ReservationStateMachine.ReserveHeld.value,
                )
            )
            # And only those that overlap with our reservation.
            .filter(CurrentReservation.connection_id == self.connection_id)
        ).subquery()
        OverlappingActiveReservation = aliased(Reservation, overlap_active, name="oar")

        # To map STP's to resources (bandwidth and vlan) in use
        # we need to unpivot the two pair of STP columns from the reservations table into separate rows.
        # Eg, from:
        #
        # row 1:  connection_id, ..., src_stp, src_selected_vlan, dst_stp, .dst_selected_vlan ..
        #
        # to:
        #
        # row 1: connection_id, stp, vlan  <-- former src_stp, src_selected_vlan
        # row 2: connection_id, stp, vlan  <-- former dst_stp, dst_selected_vlan
        src_stp = session.query(
            Reservation.connection_id.label("connection_id"),
            Reservation.src_stp_id.label("stp"),
            Reservation.src_selected_vlan.label("vlan"),
        )
        dst_stp = session.query(
            Reservation.connection_id,
            Reservation.dst_stp_id.label("stp"),
            Reservation.dst_selected_vlan.label("vlan"),
        )
        stps = src_stp.union(dst_stp).subquery()

        # With the 'hard' work done for us in two subqueries,
        # calculating the STP resources (bandwidth, VLANs) in use is now relatively straightforward.
        stp_resources_in_use = (
            session.query(
                stps.c.stp,
                func.sum(OverlappingActiveReservation.bandwidth).label("bandwidth"),
                func.group_concat(stps.c.vlan, ",").label("vlans"),  # yes, plural!
            )
            .select_from(OverlappingActiveReservation)
            .join(stps, OverlappingActiveReservation.connection_id == stps.c.connection_id)
            .filter(
                stps.c.stp.in_(
                    (
                        OverlappingActiveReservation.src_stp_id,
                        OverlappingActiveReservation.dst_stp_id,
                    )
                )
            )
            .group_by(stps.c.stp)
            .all()
        )

        return {
            rec.stp: StpResources(bandwidth=rec.bandwidth, vlans=VlanRanges(rec.vlans)) for rec in stp_resources_in_use
        }

    def _process_stp(self, target: str, var: Variable, reservation: Reservation, session: orm.Session) -> None:
        """Check validity of STP and select available VLAN.

        Target can be either "src" or "dst".
        When the STP is valid and a VLAN is available
        the corresponding {src|dst}_selected_vlan will be set on the reservation
        and the associated port will be stored in {src|dst}_port_id on the job instance.
        """
        stp_resources_in_use = self._stp_resources_in_use(session)
        res_stp = getattr(reservation, f"{target}_stp_id")
        nsi_stp = str(getattr(reservation, f"{target}_stp")())  # <-- mind the func call
        domain = getattr(reservation, f"{target}_domain")
        topology = getattr(reservation, f"{target}_topology")
        requested_vlans = VlanRanges(getattr(reservation, f"{target}_vlans"))
        stp = session.query(Topology).filter(Topology.stp_id == res_stp).one_or_none()
        if (
            stp is None
            or not stp.enabled
            or domain != settings.domain  # only process requests for our domain
            or topology != settings.topology  # only process requests for our network
        ):
            raise NsiException(UnknownStp, nsi_stp, {var: nsi_stp})
        if not requested_vlans:
            raise NsiException(InvalidLabelFormat, "missing VLANs label on STP", {var: nsi_stp})
        if stp.stp_id in stp_resources_in_use:
            bandwidth_available = stp.bandwidth - stp_resources_in_use[stp.stp_id].bandwidth
            available_vlans = VlanRanges(stp.vlans) - stp_resources_in_use[stp.stp_id].vlans
        else:
            bandwidth_available = stp.bandwidth
            available_vlans = VlanRanges(stp.vlans)
        if bandwidth_available < reservation.bandwidth:
            raise NsiException(
                CapacityUnavailable,
                f"requested: {format_bandwidth(reservation.bandwidth)}, "
                f"available: {format_bandwidth(bandwidth_available)}",
                {
                    Variable.CAPACITY: str(reservation.bandwidth),
                    var: nsi_stp,
                },
            )
        if not available_vlans:
            raise NsiException(StpUnavailable, "all VLANs in use", {var: nsi_stp})
        candidate_vlans = requested_vlans & available_vlans
        if not candidate_vlans:
            raise NsiException(
                StpUnavailable,
                f"no matching VLAN found (requested: {requested_vlans!s}, available: {available_vlans!s}",
                {var: nsi_stp},
            )
        selected_vlan = random.choice(list(candidate_vlans))
        setattr(reservation, f"{target}_selected_vlan", selected_vlan)
        # remember port id, will be stored as part of Connection below
        setattr(self, f"{target}_port_id", stp.port_id)

    def _to_reserve_failed_request(self, reservation: Reservation, nsi_exc: NsiException) -> ReserveFailedRequest:
        """Create a protobuf reserve failed request from a Reservation and NsiException."""
        pb_rf_req = ReserveFailedRequest()
        pb_rf_req.header.CopyFrom(to_header(reservation, add_path_segment=False))
        pb_rf_req.connection_id = str(reservation.connection_id)
        pb_rf_req.connection_states.CopyFrom(to_connection_states(reservation, data_plane_active=False))
        pb_rf_req.service_exception.CopyFrom(to_service_exception(nsi_exc, reservation.connection_id))
        return pb_rf_req

    def _to_reserve_confirmed_request(self, reservation: Reservation) -> ReserveConfirmedRequest:
        """Create a protobuf reserve confirmed request from a Reservation."""
        pb_rc_req = ReserveConfirmedRequest()
        # Confirming the reservation means we have a Path. hence we should add it to the Header.
        pb_rc_req.header.CopyFrom(to_header(reservation, add_path_segment=True))
        pb_rc_req.connection_id = str(reservation.connection_id)
        pb_rc_req.global_reservation_id = reservation.global_reservation_id
        # We skip setting the description, cause we have nothing specific to set it to (suggestions?)
        pb_rc_req.criteria.CopyFrom(to_confirm_criteria(reservation))
        return pb_rc_req

    def __call__(self) -> None:
        """Check reservation request.

        If the reservation can be made
        a ReserveConfirmed message will be send to the NSA/AG.
        If not, a ReserveFailed message will be send instead.
        """
        from supa.db.session import db_session
        from supa.nrm.backend import backend

        self.log.info("Checking reservation request")

        response = Union[ReserveConfirmedRequest, ReserveFailedRequest]
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

            try:
                if reservation.src_stp_id == reservation.dst_stp_id:
                    raise NsiException(
                        # Not sure if this is the correct error to use.
                        # As its descriptive text refers to path computation
                        # it suggests its an error typically returned by an aggregator.
                        # On the other hand it is the only error related to a path/connection as a whole
                        # and that is what is at issue here.
                        NoServiceplanePathFound,
                        "source and destination STP's are the same",
                        {
                            Variable.PROVIDER_NSA: settings.get_nsa_id(),
                            Variable.SOURCE_STP: str(reservation.src_stp()),
                            Variable.DEST_STP: str(reservation.dst_stp()),
                        },
                    )
                for target, var in (("src", Variable.SOURCE_STP), ("dst", Variable.DEST_STP)):
                    # Dynamic attribute lookups as we want to use the same code for
                    # both src and dst STP's
                    self._process_stp(target, var, reservation, session)

                circuit_id = backend.reserve(
                    connection_id=reservation.connection_id,
                    bandwidth=reservation.bandwidth,
                    src_port_id=self.src_port_id,
                    src_vlan=reservation.src_selected_vlan,
                    dst_port_id=self.dst_port_id,
                    dst_vlan=reservation.dst_selected_vlan,
                )
                session.add(
                    Connection(
                        connection_id=reservation.connection_id,
                        bandwidth=reservation.bandwidth,
                        src_port_id=self.src_port_id,
                        src_vlan=reservation.src_selected_vlan,
                        dst_port_id=self.dst_port_id,
                        dst_vlan=reservation.dst_selected_vlan,
                        circuit_id=circuit_id,
                    )
                )

            except NsiException as nsi_exc:
                self.log.info("Reservation failed.", reason=nsi_exc.text)
                response = self._to_reserve_failed_request(reservation, nsi_exc)  # type: ignore[misc]
                rsm.reserve_failed()
            except Exception as exc:
                self.log.exception("Unexpected error occurred.", reason=str(exc))
                nsi_exc = NsiException(GenericInternalError, str(exc))  # type: ignore[misc]
                response = self._to_reserve_failed_request(reservation, nsi_exc)  # type: ignore[misc]
                rsm.reserve_failed()
            else:
                response = self._to_reserve_confirmed_request(reservation)  # type: ignore[misc]
                rsm.reserve_confirmed()

        stub = requester.get_stub()
        if type(response) == ReserveConfirmedRequest:
            self.log.debug("Sending message.", method="ReserveConfirmed", request_message=response)
            stub.ReserveConfirmed(response)
        else:
            from supa import scheduler

            scheduler.remove_job(job_id=f"{str(self.connection_id)}-ReserveTimeoutJob")
            self.log.info("Canceled reservation timeout timer")
            self.log.debug("Sending message.", method="ReserveFailed", request_message=response)
            stub.ReserveFailed(response)

    @classmethod
    def recover(cls: Type[ReserveJob]) -> List[Job]:
        """Recover ReserveJob's that did not get to run before SuPA was terminated.

        Returns:
            List of ReserveJob's that still need to be run.
        """
        from supa.db.session import db_session

        with db_session() as session:
            connection_ids: List[UUID] = list(
                flatten(
                    session.query(Reservation.connection_id)
                    .filter(Reservation.reservation_state == ReservationStateMachine.ReserveChecking.value)
                    .all()
                )
            )
        for cid in connection_ids:
            logger.info("Recovering job", job="ReserveJob", connection_id=str(cid))

        return [ReserveJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Return APScheduler trigger information for scheduling ReserveJob's."""
        return DateTrigger(run_date=None)  # Run immediately


class ReserveCommitJob(Job):
    """Handle reservation commit requests."""

    connection_id: UUID
    log: BoundLogger

    def __init__(self, connection_id: UUID):
        """Initialize the ReserveCommitJob.

        Args:
           connection_id: The connection_id of the reservation commit request
        """
        self.log = logger.bind(job=self.__class__.__name__, connection_id=str(connection_id))
        self.connection_id = connection_id

    def _to_reserve_commit_failed_request(
        self, reservation: Reservation, nsi_exc: NsiException
    ) -> ReserveCommitFailedRequest:
        """Create a protobuf reserve commit failed request from a Reservation and NsiException."""
        pb_rcf_req = ReserveCommitFailedRequest()
        pb_rcf_req.header.CopyFrom(to_header(reservation, add_path_segment=False))
        pb_rcf_req.connection_id = str(reservation.connection_id)
        pb_rcf_req.connection_states.CopyFrom(to_connection_states(reservation, data_plane_active=False))
        pb_rcf_req.service_exception.CopyFrom(to_service_exception(nsi_exc, reservation.connection_id))
        return pb_rcf_req

    def _to_reserve_commit_confirmed_request(self, reservation: Reservation) -> ReserveCommitConfirmedRequest:
        """Create a protobuf reserve commit confirmed request from a Reservation and NsiException."""
        pb_rcc_req = ReserveCommitConfirmedRequest()
        pb_rcc_req.header.CopyFrom(to_header(reservation, add_path_segment=True))  # Yes, add our segment!
        pb_rcc_req.connection_id = str(reservation.connection_id)
        return pb_rcc_req

    def __call__(self) -> None:
        """Commit reservation request.

        If the reservation can be committed
        a ReserveCommitConfirmed message will be send to the NSA/AG.
        If for whatever reason the reservation cannot be committed
        a ReserveCommitFailed message will be sent instead.
        If the reservation state machine is not in the correct state for a ReserveCommit
        an NSI error is returned leaving the state machine unchanged.
        """
        from supa.db.session import db_session
        from supa.nrm.backend import backend

        self.log.info("Committing reservation")

        response: Union[ReserveCommitConfirmedRequest, ReserveCommitFailedRequest]
        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            rsm = ReservationStateMachine(reservation, state_field="reservation_state")
            try:
                if circuit_id := backend.reserve_commit(**connection_to_dict(connection)):
                    connection.circuit_id = circuit_id
            except NsiException as nsi_exc:
                self.log.info("Reserve commit failed.", reason=nsi_exc.text)
                response = self._to_reserve_commit_failed_request(session, nsi_exc)
                rsm.reserve_commit_failed()
            except Exception as exc:
                self.log.exception("Unexpected error occurred.", reason=str(exc))
                nsi_exc = NsiException(GenericInternalError, str(exc))  # type: ignore[misc]
                response = self._to_reserve_commit_failed_request(session, nsi_exc)  # type: ignore[misc]
                rsm.reserve_commit_failed()
            else:
                response = self._to_reserve_commit_confirmed_request(reservation)
                # create new psm just before the reserveCommitConfirmed,
                # this will set initial provision_state on reservation
                psm = ProvisionStateMachine(reservation, state_field="provision_state")  # noqa: F841
                rsm.reserve_commit_confirmed()

        stub = requester.get_stub()
        if type(response) == ReserveCommitConfirmedRequest:
            self.log.debug("Sending message", method="ReserveCommitConfirmed", request_message=response)
            stub.ReserveCommitConfirmed(response)
        else:
            self.log.debug("Sending message.", method="ReserveCommitFailed", request_message=response)
            stub.ReserveCommitFailed(response)

    @classmethod
    def recover(cls: Type[ReserveCommitJob]) -> List[Job]:
        """Recover ReserveCommitJob's that did not get to run before SuPA was terminated.

        Returns:
            List of ReserveCommitJob's that still need to be run.
        """
        from supa.db.session import db_session

        with db_session() as session:
            connection_ids: List[UUID] = list(
                flatten(
                    session.query(Reservation.connection_id)
                    .filter(Reservation.reservation_state == ReservationStateMachine.ReserveCommitting.value)
                    .all()
                )
            )
        for cid in connection_ids:
            logger.info("Recovering job", job="ReserveCommitJob", connection_id=str(cid))

        return [ReserveCommitJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Trigger for ReserveCommitJobs."""
        return DateTrigger(run_date=None)  # Run immediately


class ReserveAbortJob(Job):
    """Handle reservation obort requests."""

    connection_id: UUID
    log: BoundLogger

    def __init__(self, connection_id: UUID):
        """Initialize the ReserveAbortJob.

        Args:
           connection_id: The connection_id of the reservation abort request
        """
        self.log = logger.bind(job=self.__class__.__name__, connection_id=str(connection_id))
        self.connection_id = connection_id

    def _to_reserve_abort_confirmed_request(self, reservation: Reservation) -> ReserveAbortConfirmedRequest:
        # the reservation is still in the session, hence no actual query will be performed
        pb_rcc_req = ReserveAbortConfirmedRequest()

        pb_rcc_req.header.CopyFrom(to_header(reservation, add_path_segment=True))  # Yes, add our segment!
        pb_rcc_req.connection_id = str(reservation.connection_id)

        return pb_rcc_req

    def __call__(self) -> None:
        """Abort reservation request.

        The reservation will be aborted and
        a ReserveAbortConfirmed message will be sent to the NSA/AG.
        If the reservation state machine is not in the correct state for a ReserveCommit
        an NSI error is returned leaving the state machine unchanged.
        """
        self.log.info("Aborting reservation")

        from supa.db.session import db_session
        from supa.nrm.backend import backend

        response: Union[ReserveAbortConfirmedRequest, ErrorRequest]
        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            rsm = ReservationStateMachine(reservation, state_field="reservation_state")
            try:
                if circuit_id := backend.reserve_abort(**connection_to_dict(connection)):
                    connection.circuit_id = circuit_id
            except NsiException as nsi_exc:
                self.log.info("Reserve abort failed.", reason=nsi_exc.text)
                response = requester.to_error_request(
                    to_header(reservation),
                    nsi_exc,
                    self.connection_id,
                )
            except Exception as exc:
                self.log.exception("Unexpected error occurred.", reason=str(exc))
                response = requester.to_error_request(
                    to_header(reservation),
                    NsiException(
                        GenericInternalError,
                        str(exc),
                        {
                            Variable.RESERVATION_STATE: reservation.reservation_state,
                            Variable.CONNECTION_ID: str(self.connection_id),
                        },
                    ),
                    self.connection_id,
                )
            else:
                response = self._to_reserve_abort_confirmed_request(reservation)
                rsm.reserve_abort_confirmed()

        stub = requester.get_stub()
        if type(response) == ReserveAbortConfirmedRequest:
            self.log.debug("Sending message", method="ReserveAbortConfirmed", request_message=response)
            stub.ReserveAbortConfirmed(response)
        else:
            self.log.debug("Sending message", method="Error", request_message=response)
            stub.Error(response)

    @classmethod
    def recover(cls: Type[ReserveAbortJob]) -> List[Job]:
        """Recover ReserveAbortJob's that did not get to run before SuPA was terminated.

        Returns:
            List of ReserveAbortJob's that still need to be run.
        """
        from supa.db.session import db_session

        with db_session() as session:
            connection_ids: List[UUID] = list(
                flatten(
                    session.query(Reservation.connection_id)
                    .filter(Reservation.reservation_state == ReservationStateMachine.ReserveAborting.value)
                    .all()
                )
            )
        for cid in connection_ids:
            logger.info("Recovering job", job="ReserveAbortJob", connection_id=str(cid))

        return [ReserveAbortJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Trigger for ReserveAbortJobs."""
        return DateTrigger(run_date=None)  # Run immediately


class ReserveTimeoutJob(Job):
    """Handle reserve timeouts."""

    connection_id: UUID
    log: BoundLogger

    def _to_reserve_timeout_request(self, reservation: Reservation) -> ReserveTimeoutRequest:
        pb_rt_req = ReserveTimeoutRequest()

        pb_rt_req.header.CopyFrom(to_header(reservation, add_path_segment=True))  # Yes, add our segment!
        pb_rt_req.notification.CopyFrom(requester.new_notification_header(reservation))
        pb_rt_req.timeout_value = settings.reserve_timeout
        pb_rt_req.originating_connection_id = str(reservation.connection_id)
        pb_rt_req.originating_nsa = reservation.provider_nsa

        return pb_rt_req

    def __init__(self, connection_id: UUID):
        """Initialize the ReserveTimeoutJob.

        Args:
           connection_id: The connection_id of the reservation to timeout
        """
        self.log = logger.bind(job=self.__class__.__name__, connection_id=str(connection_id))
        self.connection_id = connection_id

    def __call__(self) -> None:
        """Timeout reservation request.

        The reservation will be timed out
        if the ReservationStateMachine is still in the ReserveHeld state and
        a ReserveTimeoutNotification message will be sent to the NSA/AG.
        If another transition already moved the state beyond ReserveHeld
        then this is practically a no-op.
        """
        self.log.info("Timeout reservation")

        from supa.db.session import db_session
        from supa.nrm.backend import backend

        response: Union[ReserveTimeoutRequest, ErrorRequest]
        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            rsm = ReservationStateMachine(reservation, state_field="reservation_state")
            try:
                rsm.reserve_timeout_notification()
                if circuit_id := backend.reserve_timeout(**connection_to_dict(connection)):
                    connection.circuit_id = circuit_id
            except TransitionNotAllowed:
                # Reservation is already in another state turning this into a no-op.
                self.log.info(
                    "Reservation not timed out",
                    state=rsm.current_state.identifier,
                    connection_id=str(self.connection_id),
                )
                return
            except NsiException as nsi_exc:
                self.log.info("Reserve timeout failed.", reason=nsi_exc.text)
                response = requester.to_error_request(
                    to_header(reservation),
                    nsi_exc,
                    self.connection_id,
                )
            except Exception as exc:
                self.log.exception("Unexpected error occurred.", reason=str(exc))
                response = requester.to_error_request(
                    to_header(reservation),
                    NsiException(
                        GenericInternalError,
                        str(exc),
                        {
                            Variable.RESERVATION_STATE: reservation.reservation_state,
                            Variable.CONNECTION_ID: str(self.connection_id),
                        },
                    ),
                    self.connection_id,
                )
            else:
                #
                # TODO: release reserved resources(?)
                #
                self.log.debug("setting reservation.reservation_timeout to true in db")
                response = self._to_reserve_timeout_request(reservation)
                reservation.reservation_timeout = True

        stub = requester.get_stub()
        if type(response) == ReserveTimeoutRequest:
            self.log.debug("Sending message", method="ReserveTimeout", request_message=response)
            stub.ReserveTimeout(response)
        else:
            self.log.debug("Sending message", method="Error", request_message=response)
            stub.Error(response)

    @classmethod
    def recover(cls: Type[ReserveTimeoutJob]) -> List[Job]:
        """Recover ReserveTimeoutJob's that did not get to run before SuPA was terminated.

        The current implementation just re-adds a new reservation timeout
        for all reservations that are still in ReserveHeld,
        potentially almost doubling the original reservation hold time.

        Returns:
            List of ReserveTimeoutJob's that still need to be run.
        """
        from supa.db.session import db_session

        with db_session() as session:
            connection_ids: List[UUID] = list(
                flatten(
                    session.query(Reservation.connection_id)
                    .filter(Reservation.reservation_state == ReservationStateMachine.ReserveHeld.value)
                    .all()
                )
            )
        for cid in connection_ids:
            logger.info("Recovering job", job="ReserveTimeoutJob", connection_id=str(cid))

        return [ReserveTimeoutJob(cid) for cid in connection_ids]

    def trigger(self) -> DateTrigger:
        """Trigger for ReserveTimeoutJobs."""
        return DateTrigger(run_date=current_timestamp() + timedelta(seconds=settings.reserve_timeout))
