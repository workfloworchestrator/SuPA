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
#
# mypy: disable-error-code=attr-defined
from __future__ import annotations

import random
from datetime import timedelta
from typing import Dict, List, NamedTuple, Type
from uuid import UUID

import structlog
from apscheduler.triggers.date import DateTrigger
from more_itertools import flatten
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased, joinedload, scoped_session
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
from supa.connection.fsm import (
    DataPlaneStateMachine,
    LifecycleStateMachine,
    ProvisionStateMachine,
    ReservationStateMachine,
)
from supa.db.model import (
    Connection,
    P2PCriteria,
    Path,
    PathTrace,
    Reservation,
    Schedule,
    Segment,
    Topology,
    connection_to_dict,
)
from supa.grpc_nsi.connection_requester_pb2 import ReserveConfirmedRequest, ReserveTimeoutRequest
from supa.job.dataplane import AutoEndJob, AutoStartJob
from supa.job.shared import Job, NsiException, register_notification, register_result
from supa.util.bandwidth import format_bandwidth
from supa.util.converter import (
    to_confirm_criteria,
    to_error_request,
    to_generic_confirmed_request,
    to_generic_failed_request,
    to_header,
    to_notification_header,
)
from supa.util.timestamp import NO_END_DATE
from supa.util.type import NotificationType, ResultType
from supa.util.vlan import VlanRanges

logger = structlog.get_logger(__name__)


class StpResources(NamedTuple):
    """Capture STP resources, as returned by an SQLAlchemy query, so that they can be referred to by name."""

    bandwidth: int
    vlans: VlanRanges


def _to_reserve_confirmed_request(reservation: Reservation) -> ReserveConfirmedRequest:
    """Create a protobuf reserve confirmed request from a Reservation."""
    pb_rc_req = ReserveConfirmedRequest()
    # Confirming the reservation means we have a Path. hence we should add it to the Header.
    pb_rc_req.header.CopyFrom(to_header(reservation, add_path_segment=True))
    pb_rc_req.connection_id = str(reservation.connection_id)
    pb_rc_req.global_reservation_id = reservation.global_reservation_id
    # We skip setting the description, cause we have nothing specific to set it to (suggestions?)
    pb_rc_req.criteria.CopyFrom(to_confirm_criteria(reservation))
    return pb_rc_req


def _to_reserve_timeout_request(reservation: Reservation) -> ReserveTimeoutRequest:
    """Create a protobuf reserve timeout request from a Reservation."""
    pb_rt_req = ReserveTimeoutRequest()

    pb_rt_req.header.CopyFrom(to_header(reservation, add_path_segment=True))  # Yes, add our segment!
    pb_rt_req.notification.CopyFrom(to_notification_header(reservation))
    pb_rt_req.timeout_value = settings.reserve_timeout
    pb_rt_req.originating_connection_id = str(reservation.connection_id)
    pb_rt_req.originating_nsa = reservation.provider_nsa

    return pb_rt_req


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
        self.src_selected_vlan: int = 0
        self.dst_selected_vlan: int = 0

    def _stp_resources_in_use(self, session: scoped_session) -> Dict[str, StpResources]:
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
        CurrentSchedule = aliased(Schedule, name="cs")
        overlap_active = (
            select(Reservation)
            # The other part
            .join(
                Schedule,
                and_(Reservation.connection_id == Schedule.connection_id, Reservation.version == Schedule.version),
            ).join(
                CurrentSchedule,
                # Do they overlap?
                and_(
                    CurrentSchedule.start_time < Schedule.end_time,
                    CurrentSchedule.end_time > Schedule.start_time,
                ),
            )
            # This filter assumes that this selection is only done to verify initial reservations.
            .filter(
                # Only select active reservations ...
                Reservation.lifecycle_state != LifecycleStateMachine.Failed.value,
                Reservation.lifecycle_state != LifecycleStateMachine.PassedEndTime.value,
                Reservation.lifecycle_state != LifecycleStateMachine.Terminated.value,
                # ... that have resources held, committing or reserved (back in start again).
                or_(
                    Reservation.reservation_state == ReservationStateMachine.ReserveHeld.value,
                    Reservation.reservation_state == ReservationStateMachine.ReserveCommitting.value,
                    Reservation.reservation_state == ReservationStateMachine.ReserveStart.value,
                ),
            )
            # And only those that overlap with our reservation.
            .filter(CurrentSchedule.connection_id == self.connection_id)
        )
        OverlappingActiveReservation = aliased(Reservation, overlap_active.subquery(), name="oar")

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
            P2PCriteria.src_stp_id.label("stp"),
            P2PCriteria.src_selected_vlan.label("vlan"),
        ).join(
            P2PCriteria,
            and_(Reservation.connection_id == P2PCriteria.connection_id, Reservation.version == P2PCriteria.version),
        )
        dst_stp = session.query(
            Reservation.connection_id,
            P2PCriteria.dst_stp_id.label("stp"),
            P2PCriteria.dst_selected_vlan.label("vlan"),
        ).join(
            P2PCriteria,
            and_(Reservation.connection_id == P2PCriteria.connection_id, Reservation.version == P2PCriteria.version),
        )
        stps = src_stp.union(dst_stp).subquery()

        # With the 'hard' work done for us in two subqueries,
        # calculating the STP resources (bandwidth, VLANs) in use is now relatively straightforward.
        stp_resources_in_use = (
            session.query(
                stps.c.stp,
                func.sum(P2PCriteria.bandwidth).label("bandwidth"),
                func.group_concat(stps.c.vlan, ",").label("vlans"),  # yes, plural!
            )
            .select_from(OverlappingActiveReservation)
            .join(
                P2PCriteria,
                and_(
                    OverlappingActiveReservation.connection_id == P2PCriteria.connection_id,
                    OverlappingActiveReservation.version == P2PCriteria.version,
                ),
            )
            .join(stps, OverlappingActiveReservation.connection_id == stps.c.connection_id)
            .filter(
                stps.c.stp.in_(
                    (
                        P2PCriteria.src_stp_id,
                        P2PCriteria.dst_stp_id,
                    )
                )
            )
            .group_by(stps.c.stp)
            .all()
        )

        return {
            rec.stp: StpResources(bandwidth=rec.bandwidth, vlans=VlanRanges(rec.vlans)) for rec in stp_resources_in_use
        }

    def _process_stp(self, target: str, var: Variable, reservation: Reservation, session: scoped_session) -> None:
        """Check validity of STP and select available VLAN.

        Target can be either "src" or "dst".
        When the STP is valid and a VLAN is available
        the corresponding {src|dst}_selected_vlan will be set on the the job instance
        and the associated port {src|dst}_port_id will also be set on  on the job instance.
        """
        stp_resources_in_use = self._stp_resources_in_use(session)
        self.log.debug("stp resources in use", stp_resources_in_use=stp_resources_in_use)
        res_stp = getattr(reservation.p2p_criteria, f"{target}_stp_id")
        nsi_stp = str(getattr(reservation.p2p_criteria, f"{target}_stp")())  # <-- mind the func call
        domain = getattr(reservation.p2p_criteria, f"{target}_domain")
        topology = getattr(reservation.p2p_criteria, f"{target}_topology")
        requested_vlans = VlanRanges(getattr(reservation.p2p_criteria, f"{target}_vlans"))
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
        if bandwidth_available < reservation.p2p_criteria.bandwidth:
            raise NsiException(
                CapacityUnavailable,
                f"requested: {format_bandwidth(reservation.p2p_criteria.bandwidth)}, "
                f"available: {format_bandwidth(bandwidth_available)}",
                {
                    Variable.CAPACITY: str(reservation.p2p_criteria.bandwidth),
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
        # selected vlan will be stored on reservation p2p criteria below
        setattr(self, f"{target}_selected_vlan", selected_vlan)
        # port id will be stored on connection below
        setattr(self, f"{target}_port_id", stp.port_id)

    def __call__(self) -> None:
        """Check reservation request.

        If the reservation can be made
        a ReserveConfirmed message will be send to the NSA/AG.
        If not, a ReserveFailed message will be send instead.
        """
        from supa.db.session import db_session
        from supa.nrm.backend import backend

        self.log.info("Reserve reservation")

        # process reservation request
        nsi_exception: NsiException | None = None
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
                .filter(Reservation.connection_id == self.connection_id)
                .one()
            )
            assert reservation.version == reservation.schedule.version  # assert versions on references are the same
            assert reservation.version == reservation.p2p_criteria.version  # TODO: refactor into unit test(s)

            self.bandwidth = reservation.p2p_criteria.bandwidth
            if len(reservation.schedules) > 1:
                self.log.info("modify reservation")
            else:
                self.log.info("verify schedule and criteria")
                try:
                    if reservation.p2p_criteria.src_stp_id == reservation.p2p_criteria.dst_stp_id:
                        raise NsiException(
                            # Not sure if this is the correct error to use.
                            # As its descriptive text refers to path computation
                            # it suggests it's an error typically returned by an aggregator.
                            # On the other hand it is the only error related to a path/connection as a whole
                            # and that is what is at issue here.
                            NoServiceplanePathFound,
                            "source and destination STP's are the same",
                            {
                                Variable.PROVIDER_NSA: settings.nsa_id,
                                Variable.SOURCE_STP: str(reservation.p2p_criteria.src_stp()),
                                Variable.DEST_STP: str(reservation.p2p_criteria.dst_stp()),
                            },
                        )
                    for target, var in (("src", Variable.SOURCE_STP), ("dst", Variable.DEST_STP)):
                        # Dynamic attribute lookups as we want to use the same code for
                        # both src and dst STP's
                        self._process_stp(target, var, reservation, session)
                    reservation.p2p_criteria.src_selected_vlan = self.src_selected_vlan
                    reservation.p2p_criteria.dst_selected_vlan = self.dst_selected_vlan
                except NsiException as nsi_exc:
                    nsi_exception = nsi_exc

        # call backend
        circuit_id = None
        if not nsi_exception:
            try:
                circuit_id = backend.reserve(
                    connection_id=self.connection_id,
                    bandwidth=self.bandwidth,
                    src_port_id=self.src_port_id,
                    src_vlan=self.src_selected_vlan,
                    dst_port_id=self.dst_port_id,
                    dst_vlan=self.dst_selected_vlan,
                )
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

        # update reservation and connection state in the database, stop reserve timeout job if necessary
        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            rsm = ReservationStateMachine(reservation, state_field="reservation_state")
            if nsi_exception:  # reserve failed
                from supa import scheduler

                self.log.info("Reservation failed.", reason=str(nsi_exception))
                rsm.reserve_failed()
                failed_request = to_generic_failed_request(reservation, nsi_exception)
                self.log.info("Cancel reserve timeout")
                scheduler.remove_job(job_id=ReserveTimeoutJob(self.connection_id).job_id)
            else:  # reserve successful
                rsm.reserve_confirmed()
                confirmed_request = _to_reserve_confirmed_request(reservation)
                if len(reservation.schedules) == 1:  # new reservation
                    session.add(
                        Connection(
                            connection_id=reservation.connection_id,
                            bandwidth=reservation.p2p_criteria.bandwidth,
                            src_port_id=self.src_port_id,
                            src_vlan=reservation.p2p_criteria.src_selected_vlan,
                            dst_port_id=self.dst_port_id,
                            dst_vlan=reservation.p2p_criteria.dst_selected_vlan,
                            circuit_id=circuit_id,
                        )
                    )
                else:  # modify reservation
                    connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
                    connection.bandwidth = reservation.p2p_criteria.bandwidth
                if circuit_id:
                    connection.circuit_id = circuit_id

        # send result to requester, done outside the database session because communication can throw exception
        stub = requester.get_stub()
        if nsi_exception:  # reserve failed
            self.log.debug("Sending message.", method="ReserveFailed", message=failed_request)
            register_result(failed_request, ResultType.ReserveFailed)
            stub.ReserveFailed(failed_request)
        else:  # reserve successful
            self.log.debug("Sending message.", method="ReserveConfirmed", message=confirmed_request)
            register_result(confirmed_request, ResultType.ReserveConfirmed)
            stub.ReserveConfirmed(confirmed_request)

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

    def __call__(self) -> None:
        """Commit reservation request.

        If the reservation can be committed
        a ReserveCommitConfirmed message will be send to the NSA/AG.
        If for whatever reason the reservation cannot be committed
        a ReserveCommitFailed message will be sent instead.
        If the reservation state machine is not in the correct state for a ReserveCommit
        an NSI error is returned leaving the state machine unchanged.
        """
        self.log.info("Reserve commit reservation")

        from supa.db.session import db_session
        from supa.nrm.backend import backend

        # call backend
        nsi_exception: NsiException | None = None
        circuit_id = None
        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            backend_args = connection_to_dict(connection)
            new_bandwidth = reservation.p2p_criteria.bandwidth
            if len(reservation.schedules) > 1:  # modify reservation
                old_bandwidth = reservation.p2p_criteria_list[-2].bandwidth
                data_plane_active = (
                    dpsm.current_state == DataPlaneStateMachine.Activated
                    or dpsm.current_state == DataPlaneStateMachine.AutoEnd
                )
            else:
                old_bandwidth = new_bandwidth

        # call backend
        try:
            # always reserve commit (possible new values) to NRM, also in case of modify
            circuit_id = backend.reserve_commit(**backend_args)
            # 1. if bandwidth has changed and data plane is active then call modify() on backend
            #    to allow NRM to change the bandwidth on the active connection in the network
            if new_bandwidth != old_bandwidth and data_plane_active:
                self.log.info("modify bandwidth on connection", old=old_bandwidth, new=new_bandwidth)
                if modify_circuit_id := backend.modify(**backend_args):
                    circuit_id = modify_circuit_id
        except NsiException as nsi_exc:
            nsi_exception = nsi_exc
        except Exception as exc:
            self.log.exception("Unexpected error occurred.", reason=str(exc))
            nsi_exception = NsiException(GenericInternalError, str(exc))

        # update reservation and connection state in the database, start and stop jobs if necessary
        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            rsm = ReservationStateMachine(reservation, state_field="reservation_state")
            dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
            # for modify psm will be the existing state machine, otherwise a new one is created
            psm = ProvisionStateMachine(reservation, state_field="provision_state")
            if nsi_exception:  # reserve commit on backend failed
                self.log.info("Reserve commit failed.", reason=str(nsi_exception))
                rsm.reserve_commit_failed()
                failed_request = to_generic_failed_request(reservation, nsi_exception)
            else:  # reserve commit on backend successful
                from supa import scheduler

                if len(reservation.schedules) > 1:  # modify reservation
                    old_start_time = reservation.schedules[-2].start_time
                    old_end_time = reservation.schedules[-2].end_time
                    new_start_time = reservation.schedule.start_time
                    new_end_time = reservation.schedule.end_time
                    job: Job
                    # 2. if start time has changed:
                    #    - start time was not reached yet, this is checked in ConnectionProviderService.Reserve
                    #    - if the reservation was not provisioned then let ProvisionJob take care of everything
                    #    - if the reservation was provisioned then reschedule a AutoStartJob with new start time
                    if (
                        new_start_time != old_start_time
                        and psm.current_state == ProvisionStateMachine.Provisioned
                        and dpsm.current_state == DataPlaneStateMachine.AutoStart
                    ):
                        self.log.info(
                            "Reschedule auto start", job="AutoStartJob", start_time=new_start_time.isoformat()
                        )
                        scheduler.remove_job(job_id=AutoStartJob(self.connection_id).job_id)
                        scheduler.add_job(
                            job := AutoStartJob(self.connection_id),
                            trigger=DateTrigger(run_date=new_start_time),
                            id=job.job_id,
                        )
                    # 3. if end time has changed and the reservation was provisioned:
                    #    - if there is an AutoEndJob then either:
                    #      - if end time changed to NO_END_DATE then remove AutoEndJob
                    #      - otherwise reschedule AutoEndJob
                    #    - if the data plane was active with NO_END_DATA then now schedule AutoEndJob
                    #    - in all other cases the AutoStartJob or ProvisionJob will take the new end time into account
                    if new_end_time != old_end_time and psm.current_state == ProvisionStateMachine.Provisioned:
                        if dpsm.current_state == DataPlaneStateMachine.AutoEnd:
                            dpsm.cancel_auto_end_request()
                            self.log.info("Cancel previous auto end")
                            scheduler.remove_job(job_id=AutoEndJob(self.connection_id).job_id)
                        if dpsm.current_state == DataPlaneStateMachine.Activated and new_end_time != NO_END_DATE:
                            dpsm.auto_end_request()
                            self.log.info("Schedule new auto end", job="AutoEndJob", end_time=new_end_time.isoformat())
                            scheduler.add_job(
                                job := AutoEndJob(self.connection_id),
                                trigger=DateTrigger(run_date=new_end_time),
                                id=job.job_id,
                            )
                rsm.reserve_commit_confirmed()
                confirmed_request = to_generic_confirmed_request(reservation)
                if circuit_id:
                    connection.circuit_id = circuit_id

        # send result to requester, done outside the database session because communication can throw exception
        stub = requester.get_stub()
        if nsi_exception:  # reserve commit on backend failed
            self.log.debug("Sending message.", method="ReserveCommitFailed", message=failed_request)
            register_result(failed_request, ResultType.ReserveCommitFailed)
            stub.ReserveCommitFailed(failed_request)
        else:  # reserve commit on backend successful
            self.log.debug("Sending message", method="ReserveCommitConfirmed", message=confirmed_request)
            register_result(confirmed_request, ResultType.ReserveCommitConfirmed)
            stub.ReserveCommitConfirmed(confirmed_request)

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

    def __call__(self) -> None:
        """Abort reservation request.

        The reservation will be aborted and
        a ReserveAbortConfirmed message will be sent to the NSA/AG.
        If the reservation state machine is not in the correct state for a ReserveAbort
        an NSI error is returned leaving the state machine unchanged.
        """
        self.log.info("Reserve abort reservation")

        from supa.db.session import db_session
        from supa.nrm.backend import backend

        # call backend
        nsi_exception: NsiException | None = None
        circuit_id = None
        with db_session() as session:
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            backend_args = connection_to_dict(connection)
        try:
            circuit_id = backend.reserve_abort(**backend_args)
        except NsiException as nsi_exc:
            nsi_exception = nsi_exc
        except Exception as exc:
            self.log.exception("Unexpected error occurred.", reason=str(exc))
            nsi_exception = NsiException(
                GenericInternalError, str(exc), {Variable.CONNECTION_ID: str(self.connection_id)}
            )

        # update reservation and connection state in the database
        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            rsm = ReservationStateMachine(reservation, state_field="reservation_state")
            if nsi_exception:  # reserve abort on backend failed
                self.log.info("Reserve abort failed.", reason=str(nsi_exception))
                error_request = to_error_request(to_header(reservation), nsi_exception, self.connection_id)
            else:  # reserve abort on backend successful
                confirmed_request = to_generic_confirmed_request(reservation)
                reservation.reservation_timeout = False  # would probably be better to add reservation state to fsm
                # only allowed to abort a reserve modify request, e.q. there is more than one criteria version
                if len(reservation.p2p_criteria_list) > 1:
                    # 1. set connection.bandwidth to previous bandwidth
                    connection.bandwidth = reservation.p2p_criteria_list[-2].bandwidth
                    # 2. remove most recent version of criteria
                    session.delete(reservation.p2p_criteria_list[-1])
                    # 3. remove most recent version of schedule
                    session.delete(reservation.schedules[-1])
                    # 4. decrement reservation version with one
                    reservation.version -= 1
                    rsm.reserve_abort_confirmed()
                else:  # the server should have prevented that this code is reached
                    self.log.error("cannot abort an initial reserve request, should not have reached this code")
                if circuit_id:
                    connection.circuit_id = circuit_id

        # send result to requester, done outside the database session because communication can throw exception
        stub = requester.get_stub()
        if nsi_exception:  # reserve abort failed
            self.log.debug("Sending message", method="Error", message=error_request)
            register_result(error_request, ResultType.Error)
            stub.Error(error_request)
        else:  # reserve abort successful
            self.log.debug("Sending message", method="ReserveAbortConfirmed", message=confirmed_request)
            register_result(confirmed_request, ResultType.ReserveAbortConfirmed)
            stub.ReserveAbortConfirmed(confirmed_request)

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
        self.log.info("Reserve timeout reservation")

        from supa.db.session import db_session
        from supa.nrm.backend import backend

        # call backend
        nsi_exception: NsiException | None = None
        circuit_id = None
        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            backend_args = connection_to_dict(connection)
            rsm = ReservationStateMachine(reservation, state_field="reservation_state")
            try:
                rsm.reserve_timeout_notification()
            except TransitionNotAllowed as tna:
                # Reservation is already in another state turning this into a no-op.
                self.log.warning("Reserve timeout failed", reason=str(tna), state=rsm.current_state.id)
                return
        try:
            circuit_id = backend.reserve_timeout(**backend_args)
        except NsiException as nsi_exc:
            nsi_exception = nsi_exc
        except Exception as exc:
            self.log.exception("Unexpected error occurred.", reason=str(exc))
            nsi_exception = NsiException(
                GenericInternalError,
                str(exc),
                {
                    Variable.RESERVATION_STATE: reservation.reservation_state,
                    Variable.CONNECTION_ID: str(self.connection_id),
                },
            )

        # update reservation and connection state in the database
        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            connection = session.query(Connection).filter(Connection.connection_id == self.connection_id).one()
            if nsi_exception:  # reserve timeout on backend failed
                self.log.info("Reserve timeout failed.", reason=str(nsi_exception))
                error_request = to_error_request(to_header(reservation), nsi_exception, self.connection_id)
            else:  # reserve timeout on backend successful
                self.log.debug("set reservation timeout to true in db")
                timeout_request = _to_reserve_timeout_request(reservation)
                if circuit_id:
                    connection.circuit_id = circuit_id
                reservation.reservation_timeout = True

        # send result to requester, done outside the database session because communication can throw exception
        stub = requester.get_stub()
        if nsi_exception:  # reserve timeout on backend failed
            self.log.debug("Sending message", method="Error", message=error_request)
            register_result(error_request, ResultType.Error)
            stub.Error(error_request)
        else:  # reserve timeout on backend successful
            self.log.debug("Sending message", method="ReserveTimeout", message=timeout_request)
            register_notification(timeout_request, NotificationType.ReserveTimeout)
            stub.ReserveTimeout(timeout_request)

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
        from supa.db.session import db_session

        with db_session() as session:
            reservation = session.query(Reservation).filter(Reservation.connection_id == self.connection_id).one()
            timeout_date = reservation.create_date if len(reservation.schedules) == 1 else reservation.last_modified
            timeout_date += timedelta(seconds=settings.reserve_timeout)  # type: ignore
            self.log.debug("reserve timeout set", timeout_date=timeout_date)

        return DateTrigger(run_date=timeout_date)
